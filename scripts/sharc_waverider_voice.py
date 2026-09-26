"""Waverider Milestone 2 (offline): one DN2 voice rendered in the runner, and our reader substituted into it.

    python scripts/sharc_waverider_voice.py \\
        --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \\
        --digikit ../digikit-wt-sharcemu [--blocks 16] [--seconds 2.5]

Steps, each reported PASS or FAIL (`docs/waverider-feasibility.md`, "Milestone 2"):

1. **map** -- controls for the runner workarounds (`scripts/sharc_dn2_fixups.py`),
   then the DN2 engine init (`sw 0x1c1445`) to its return and one slot dispatch
   (`sw 0x1c8ef1`); the block size, the per-track buffers, the machine-type
   field and the WaveTone voice state are read back from the run.
2. **stock** -- track 0 is WaveTone (machine 1), every other track MIDI (4).
   Oscillator 1 is hand-armed at the render call (a phase increment and the
   index scale oscillator 2 already has); N blocks run through the firmware's
   own dispatch. Taps: oscillator 1's buffer, the track buffer after the machine
   render, the track buffer as the amp stage (`sw 0xb80345`) receives it, and
   the track buffer at the end. Control: the same run unarmed.
3. **reader** -- the same run with the WaveTone render call (`0x1c9611`)
   replaced by our reader (the committed `csrc/waverider/sharc/reader.json`)
   writing the track buffer; compared with `dnfw.waverider.render` at each tap.
4. **hooks** -- the candidate hooks ranked from what 1-3 measured.

Every run writes WAVs under out/waverider/ (48 kHz, 16-bit mono, at least
`--seconds`): the rendered blocks are looped out to that length, because the
runner manages about 20 blocks a minute. `m2_report.json` has the numbers.

digikit (GPL-2.0+) and selache are tools, called from checkouts you name; this
script copies none of their code. Exit 0 when every step passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import random
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_dn2_fixups as fx                               # noqa: E402
import sharc_waverider_render as m1                          # noqa: E402
from dnfw.waverider import render, testtable, voice as V    # noqa: E402

OUT = ROOT / "out" / "waverider"
RATE = 48000
BLOCK = 32
INIT = 0x1C1445
DISPATCH = 0x1C8EF1
DISPATCH_RETURN = 0x1C9B6E        # the RETURN of sw 0x1c8ef1
FAKE_RETURN = 0x1C3047            # where sw 0x1c2712 resumes after its call
STACK = 0x300000
SINE_TABLE = 0x8052FBE0           # init's first table: 1024-point sine (a scratch buffer later)
SINE_DONE = 0x1C46B7              # first instruction after the sine loop in sw 0x1c463b
WT_CALL, WT_RESUME = 0x1C9611, 0x1C9618    # the WaveTone render call in sw 0x1c8ef1
AMP_STAGE = 0xB80345              # the per-track stage that zeroes an un-triggered voice
OSC1_BUF = 0x266490               # oscillator 1's output, 2 x BLOCK samples (96 kHz)
MIDI = 4
# oscillator 1 is armed with oscillator 2's index scale / segment fields (words
# 14..17, written by the WaveTone setup sw 0x1c694a) and a phase increment:
# 26-bit phase at 96 kHz: 0x60000 = 562.5 Hz, 3/8 of a cycle a block, so 16
# blocks hold 6 whole cycles and the looped WAV has no seam
ARM_INC = 0x60000
PHASE_MASK = (1 << 26) - 1
ARM_COPY = (14, 15, 16, 17)


# -- the machine ----------------------------------------------------------------------

class Machine:
    """DN2 1.11 in digikit's runner, with our reader spliced in at unloaded spans."""

    def __init__(self, dk, stream: bytes, code: bytes, table):
        self.dk = dk
        spliced, self.placement = m1.place(dk, stream, code, render.dsp_bytes(table))
        self.memory = dk.ldr.LoadedMemory.from_stream(spliced)
        self.sha = hashlib.sha256(spliced).hexdigest()

    def runner(self, start: int, regs=None):
        base = {"I6": STACK, "I7": STACK}
        base.update(regs or {})
        return fx.sr.Runner(self.memory, start, regs=base, explicit_memory_model=True,
                            approx_recips=True, follow_loaded_calls=True, max_call_depth=64)

    @staticmethod
    def fixups(accelerate: bool) -> fx.Fixups:
        f = fx.Fixups()
        if accelerate:
            f.hooks[fx.SIN] = fx.native_sin
            for pc in fx.ADDITIVE:
                f.hooks[pc] = fx.native_additive
        return f


def word(state, addr: int) -> int | None:
    v = fx._dm_read(state, addr, 4)
    return v.value if isinstance(v, fx.Const) else None


def floats(state, addr: int, n: int) -> list[float]:
    return [V.bits_f32(word(state, addr + 4 * k) or 0) for k in range(n)]


def ints(state, addr: int, n: int) -> list[int]:
    out = []
    for k in range(n):
        w = word(state, addr + 4 * k) or 0
        out.append(w - (1 << 32) if w & 0x80000000 else w)
    return out


def poke(state, addr: int, value: int) -> None:
    if not fx._dm_write(state, addr, 4, fx.Const(value & 0xFFFFFFFF)):
        raise SystemExit(f"poke {addr:#x} did not take")


# -- step 1 ----------------------------------------------------------------------------

def controls(mach: Machine) -> dict:
    """The controls behind G2/G4 and A1: init's sine table with and without the 17a
    companion, and sinf in the runner against math.sin."""
    rows = {}
    for companion in (False, True):
        r = mach.runner(INIT)
        f = mach.fixups(False)
        f.simd_17a = companion
        f.hooks[fx.SIN] = fx.native_sin
        fx.run(r, 400_000, f, stop_at=[SINE_DONE])
        t = floats(r.state, SINE_TABLE, 1024)
        ref = [math.sin((k + 0.5) * 2 * math.pi / 1024) for k in range(1024)]
        rows[companion] = (max(abs(t[k] - ref[k]) for k in range(0, 1024, 2)),
                           max(abs(t[k] - ref[k]) for k in range(1, 1024, 2)))
    base = mach.runner(INIT)
    rnd = random.Random(1)
    xs = [(k + 0.5) * 2 * math.pi / 1024 for k in range(0, 1024, 37)] + \
         [rnd.uniform(0, 250.0) for _ in range(30)]
    worst = 0
    for x in xs:
        xf = fx.f32(x)
        r = base.fresh_call(fx.SIN, regs={"R4": V.f32_bits(xf), "MODE1": 0}, return_address=0x123456)
        fx.run(r, 5000, mach.fixups(False), stop_at=[0x123456])
        got = V.bits_f32(word_reg(r, "R0"))
        worst = max(worst, abs(V.f32_bits(got) - V.f32_bits(fx.f32(math.sin(xf)))))
    return {"sine_err_without_17a_companion": {"even": rows[False][0], "odd": rows[False][1]},
            "sine_err_with_17a_companion": {"even": rows[True][0], "odd": rows[True][1]},
            "sinf_inputs": len(xs), "sinf_worst_ulp": worst}


def word_reg(runner, name: str) -> int:
    v = runner.state.uregs[fx.UREG_CODES[name]]
    return v.value if isinstance(v, fx.Const) else 0


def run_init(mach: Machine, cache: pathlib.Path, accelerate: bool, validate: int) -> dict:
    """Init to its return, cached. A2 is checked word for word on the first VALIDATE
    entries of each additive loop, emulated beside the native version."""
    if cache.exists():
        runner = fx.sr.load_snapshot(str(cache), mach.memory)
        meta = json.loads(cache.with_suffix(".json").read_text(encoding="utf-8"))
        return {"runner": runner, **meta, "cached": str(cache.relative_to(ROOT))}
    r = mach.runner(INIT)
    f = mach.fixups(accelerate)
    checks = []
    seen: dict[int, int] = {}

    def validating(runner):
        pc = runner.state.pc_sw
        seen[pc] = seen.get(pc, 0) + 1
        if seen[pc] > validate:
            fx.native_additive(runner)
            return
        base = runner.state.uregs[fx.UREG_CODES["I3"]].value
        emu = runner.fresh_call(pc)
        emu.state = fx.dataclasses.replace(
            runner.state, uregs=dict(runner.state.uregs), overlay=dict(runner.state.overlay),
            call_stack=list(runner.state.call_stack), loops=list(runner.state.loops),
            status_stack=list(runner.state.status_stack), trace=[])
        ef = mach.fixups(False)
        ef.hooks[fx.SIN] = fx.native_sin
        res = fx.run(emu, 200_000, ef, stop_at=[fx.ADDITIVE[pc][0]])
        want = [word(emu.state, base + 4 * k) for k in range(1024)]
        fx.native_additive(runner)
        got = [word(runner.state, base + 4 * k) for k in range(1024)]
        checks.append({"loop": f"{pc:#x}", "entry": seen[pc], "emulated": res[0],
                       "words_differing": sum(a != b for a, b in zip(got, want))})

    if accelerate:
        for pc in fx.ADDITIVE:
            f.hooks[pc] = validating
    t0 = time.perf_counter()
    res = fx.run(r, 60_000_000, f)
    ok = res[0] == "halt" and res[1].reason == "return without followed call"
    meta = {"ok": ok, "instructions": res[2], "wall_s": round(time.perf_counter() - t0, 1),
            "halt": f"{res[1].reason} at {res[1].pc_sw:#x}" if res[0] == "halt" else res[0],
            "fixups": dict(f.counts), "accelerated": accelerate, "additive_checks": checks,
            "additive_entries": {f"{k:#x}": v for k, v in seen.items()}}
    if ok:
        cache.parent.mkdir(parents=True, exist_ok=True)
        fx.sr.save_snapshot(r, str(cache))
        cache.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return {"runner": r, **meta}


def step_map(mach: Machine, init: dict, ctl: dict) -> dict:
    s = init["runner"].state
    block = word(s, V.CONFIG)
    bufs = [word(s, V.TRACK_BUFFERS + 4 * t) for t in range(V.N_TRACKS)]
    strides = {b - a for a, b in zip(bufs, bufs[1:])}
    shaper = floats(s, V.STAGE5_TABLE, 1025)
    mono = all(b >= a for a, b in zip(shaper, shaper[1:]))
    fr = dispatch(mach, init["runner"], {0: 1, **{t: MIDI for t in range(1, 16)}})
    ws = V.machine_state(1, 0)
    ta = word(fr["runner"].state, ws + V.WAVETONE_OSC[0] + 4 * V.OSC_TABLE_A)
    checks = {
        "control: without the 17a companion the sine table's odd half is wrong":
            ctl["sine_err_without_17a_companion"]["odd"] > 0.1,
        "init's sine table = sin((k+.5)2pi/1024) with it, max err < 1e-6":
            max(ctl["sine_err_with_17a_companion"].values()) < 1e-6,
        "sinf in the runner is within 1 ulp of math.sin (A1)": ctl["sinf_worst_ulp"] <= 1,
        "additive loops: native = emulated, word for word (A2)":
            bool(init.get("additive_checks")) and all(c["words_differing"] == 0 for c in init["additive_checks"]),
        "init returns": init["ok"],
        "block size (DM 0x257e6c) = 32": block == BLOCK,
        "16 track buffers, 32 floats apart": len(set(bufs)) == 16 and strides == {4 * BLOCK},
        "dispatch sw 0x1c8ef1 returns with track 0 = WaveTone": fr["ok"],
        "WaveTone osc 1 has a table pointer": bool(ta),
        "stage-5 table is a monotone -1..1 shaper, not a waveform":
            mono and shaper[0] < -0.99 and shaper[-1] > 0.99,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"controls": ctl, "init_instructions": init["instructions"],
                        "block": block, "track_buffers": [hex(b) for b in bufs],
                        "dispatch_instructions": fr["instructions"],
                        "wavetone_state_track0": hex(ws), "osc1_table_a": hex(ta or 0),
                        "stage5_table": [round(shaper[k], 4) for k in (0, 256, 512, 768, 1024)]}}


# -- one block -------------------------------------------------------------------------

def dispatch(mach: Machine, state_runner, machine_of: dict, *, arm: bool = False,
             replace_wavetone=None) -> dict:
    """One call of sw 0x1c8ef1 from STATE_RUNNER's state, with track 0's buffer
    tapped after the machine render, at the amp stage and at the end."""
    s0 = state_runner.state
    for t, m in machine_of.items():
        poke(s0, V.track_record(t) + V.TRACK_MACHINE, m)
    r = state_runner.fresh_call(DISPATCH, regs={"R4": V.ENGINE, "R8": V.TRACKS, "R12": V.CONFIG},
                                return_address=FAKE_RETURN)
    f = mach.fixups(True)
    tap: dict = {}
    buf = word(r.state, V.TRACK_BUFFERS)
    ws = V.machine_state(1, 0)

    def at_call(runner):
        tap.setdefault("phase_in", word(runner.state, ws + V.WAVETONE_OSC[0] + 4 * V.OSC_PHASE))
        if arm:
            o1, o2 = ws + V.WAVETONE_OSC[0], ws + V.WAVETONE_OSC[1]
            poke(runner.state, o1 + 4 * V.OSC_INC, ARM_INC)
            for k in ARM_COPY:
                poke(runner.state, o1 + 4 * k, word(runner.state, o2 + 4 * k) or 0)
        if replace_wavetone is not None:
            replace_wavetone(runner, word_reg(runner, "R12"), BLOCK)
            runner.state.pc_sw = WT_RESUME

    def after_render(runner):
        tap.setdefault("machine", floats(runner.state, buf, BLOCK))
        tap.setdefault("osc1", ints(runner.state, OSC1_BUF, 2 * BLOCK))
        tap.setdefault("phase", word(runner.state, ws + V.WAVETONE_OSC[0] + 4 * V.OSC_PHASE))

    def amp(runner):
        if word_reg(runner, "R12") == buf and "pre_amp" not in tap:
            tap["pre_amp"] = floats(runner.state, buf, BLOCK)

    f.hooks[WT_CALL] = at_call
    f.hooks[WT_RESUME] = after_render
    f.hooks[AMP_STAGE] = amp
    t0 = time.perf_counter()
    res = fx.run(r, 5_000_000, f)
    ok = res[0] == "halt" and res[1].pc_sw == DISPATCH_RETURN
    tap["chain"] = floats(r.state, buf, BLOCK)
    return {"ok": ok, "runner": r, "instructions": res[2], "wall_s": time.perf_counter() - t0,
            "halt": f"{res[1].reason} at {res[1].pc_sw:#x}" if res[0] == "halt" else res[0],
            "tap": tap}


TAPS = ("osc1", "machine", "pre_amp", "chain")


def render_blocks(mach, init_runner, blocks: int, machine_of: dict, **kw) -> dict:
    state, out, phases = init_runner, {k: [] for k in TAPS}, []
    instr, wall, ok, halt, done = 0, 0.0, True, None, 0
    for b in range(blocks):
        fr = dispatch(mach, state, machine_of if b == 0 else {}, **kw)
        instr += fr["instructions"]
        wall += fr["wall_s"]
        if not fr["ok"]:
            ok, halt = False, fr["halt"]
            break
        for k in TAPS:
            out[k] += fr["tap"].get(k, [0.0] * (2 * BLOCK if k == "osc1" else BLOCK))
        phases.append((fr["tap"].get("phase_in"), fr["tap"].get("phase")))
        state, done = fr["runner"], done + 1
    return {"ok": ok, "halt": halt, **out, "instructions": instr, "wall_s": wall, "blocks": done,
            "phases": phases}


# -- our reader, at the WaveTone call site -----------------------------------------------

class ReaderAtCallSite:
    """Runs wr_render on the block's own memory, writing the track buffer."""

    def __init__(self, freq: float, positions: list[int]):
        self.inc = render.increment(freq)
        self.positions = positions
        self.phase = 0
        self.calls = 0

    def __call__(self, runner, out: int, count: int) -> None:
        pos = self.positions[min(self.calls, len(self.positions) - 1)]
        sub = runner.fresh_call(m1.CODE_SW, regs={"R4": m1.PARAMS_DM}, return_address=WT_RESUME)
        for k, v in enumerate((m1.TABLE_DM, self.phase, self.inc, pos, count, out)):
            poke(sub.state, m1.PARAMS_DM + 4 * k, v)
        res = fx.run(sub, 200 * count + 400, fx.Fixups(), stop_at=[WT_RESUME])
        # wr_render ends in a plain return; the runner stops there, one way or the other
        returned = res[0] == "stop" or (res[0] == "halt" and "return" in res[1].reason
                                        and m1.CODE_SW <= res[1].pc_sw < m1.CODE_SW + 0x200)
        if not returned:
            raise SystemExit(f"wr_render at the call site stopped: {res}")
        self.phase = word(sub.state, m1.PARAMS_DM + 4)
        runner.state.overlay = sub.state.overlay     # the block, and the params block
        self.calls += 1


# -- WAVs ----------------------------------------------------------------------------------

def wav(name: str, samples: list[float], seconds: float, wavs: list, what: str,
        normalise: bool = False) -> None:
    n = int(seconds * RATE)
    pk = V.peak(samples)
    scale = 0.9 / pk if normalise and pk else 1.0
    looped = V.loop_to([x * scale for x in samples], n)
    path = OUT / name
    m1.write_wav(path, looped, RATE)
    wavs.append({"file": str(path), "seconds": round(len(looped) / RATE, 3),
                 "rendered_samples": len(samples), "looped": len(samples) < n,
                 "gain_applied": round(scale, 6), "peak": pk, "rms": V.rms(samples), "what": what})


def zero_crossings(samples: list[float]) -> int:
    return sum(1 for a, b in zip(samples, samples[1:]) if (a < 0) != (b < 0))


# -- main ----------------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--blocks", type=int, default=16, help="32-sample blocks per run")
    p.add_argument("--seconds", type=float, default=2.5, help="WAV length (looped), >= 2")
    p.add_argument("--freq", type=float, default=375.0,
                   help="our reader's pitch (375 Hz: 4 cycles in 512 samples, so the loop is seamless)")
    p.add_argument("--exact", action="store_true", help="no accelerations A1/A2 (init takes hours)")
    p.add_argument("--validate", type=int, default=3, help="additive-loop entries checked per loop")
    p.add_argument("--fresh", action="store_true", help="ignore the cached init snapshot")
    a = p.parse_args(argv)
    if a.seconds < 2:
        raise SystemExit("--seconds must be at least 2")

    OUT.mkdir(parents=True, exist_ok=True)
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    stream = m1.dn2_section7(a.image)
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        code, _, provenance = m1.reader_code(False, pathlib.Path(tmp))
    table = testtable.table()
    mach = Machine(dk, stream, code, table)
    report: dict = {"digikit": {"path": str(a.digikit), "head": dk.head},
                    "image_sha256": mach.sha, "reader": provenance, "placement": mach.placement,
                    "blocks": a.blocks}
    wavs: list = []
    results: dict = {}

    print("step 1: map")
    ctl = controls(mach)
    cache = OUT / f"m2_init_{mach.sha[:12]}{'_exact' if a.exact else ''}.snap"
    if a.fresh and cache.exists():
        cache.unlink()
    init = run_init(mach, cache, not a.exact, a.validate)
    report["init"] = {k: v for k, v in init.items() if k != "runner"}
    print(f"  init: {'returned' if init['ok'] else 'STOPPED: ' + str(init['halt'])} after "
          f"{init['instructions']:,} instructions ({init.get('cached') or str(init.get('wall_s')) + ' s'})")
    if not init["ok"]:
        return finish(report, results, wavs)
    results["1_map"] = s1 = step_map(mach, init, ctl)
    show(s1)

    print(f"\nstep 2: the stock WaveTone voice, {a.blocks} blocks")
    midi = {t: MIDI for t in range(1, V.N_TRACKS)}
    stock = render_blocks(mach, init["runner"], a.blocks, {0: 1, **midi}, arm=True)
    off = render_blocks(mach, init["runner"], a.blocks, {0: 1, **midi}, arm=False)
    osc = [x / 2 ** 31 for x in stock["osc1"][::2]]      # 96 kHz -> every other sample
    osc_off = [x / 2 ** 31 for x in off["osc1"][::2]]
    wav("m2_voice_stock_osc.wav", osc, a.seconds, wavs,
        "the firmware's WaveTone oscillator 1 (sw 0x1c44ae), hand-armed, every other sample "
        "of its 96 kHz output, normalised", normalise=True)
    wav("m2_voice_stock_machine.wav", stock["machine"], a.seconds, wavs,
        "track buffer after the WaveTone render (after its mixer and decimator)")
    wav("m2_voice_stock_chain.wav", stock["chain"], a.seconds, wavs,
        "track buffer at the end of the block, after the per-track chain")
    wav("m2_voice_disarmed_osc.wav", osc_off, a.seconds, wavs,
        "control: oscillator 1 of the same run without the hand-arm")
    step = (2 * BLOCK * ARM_INC) & PHASE_MASK
    advanced = [((b - a) & PHASE_MASK) == step for a, b in stock["phases"][1:] if a is not None and b is not None]
    s2 = {"checks": {
        "stock run returns every block": stock["ok"],
        "oscillator 1 is non-silent when armed": V.peak(osc) > 0,
        "control: unarmed oscillator 1 is silent": V.peak(osc_off) == 0 and off["ok"],
        "its phase advances 2 x 32 x the armed increment every block": bool(advanced) and all(advanced)},
        "numbers": {"osc_peak_q31": V.peak(osc), "phase_in_out": [(hex(a or 0), hex(b or 0)) for a, b in stock["phases"]],
                    "phase_step_expected": hex(step), "zero_crossings": zero_crossings(osc),
                    "machine_peak": V.peak(stock["machine"]), "pre_amp_peak": V.peak(stock["pre_amp"]),
                    "chain_peak": V.peak(stock["chain"]),
                    "instructions_per_block": stock["instructions"] // max(stock["blocks"], 1),
                    "wall_s_per_block": round(stock["wall_s"] / max(stock["blocks"], 1), 2),
                    "halt": stock["halt"] or off["halt"]}}
    s2["ok"] = all(s2["checks"].values())
    results["2_stock"] = s2
    show(s2)

    print(f"\nstep 3: our reader at the WaveTone call site, {a.freq} Hz")
    positions = render.sweep(len(table), max(a.blocks, 2))
    reader = ReaderAtCallSite(a.freq, positions)
    sub = render_blocks(mach, init["runner"], a.blocks, {0: 1, **midi}, replace_wavetone=reader)
    nb = sub["blocks"]
    ref32 = render.render_blocks(table, reader.inc, positions[:nb], BLOCK, 0, "float32")
    ideal = render.render_blocks(table, reader.inc, positions[:nb], BLOCK, 0, "ideal")
    wav("m2_voice_reader.wav", sub["machine"], a.seconds, wavs,
        "our reader in place of WaveTone: the track buffer right after the call")
    wav("m2_voice_reader_pre_amp.wav", sub["pre_amp"], a.seconds, wavs,
        "our reader's block as the amp stage receives it (after the stages before it)")
    wav("m2_voice_reader_chain.wav", sub["chain"], a.seconds, wavs,
        "our reader's block at the end of the per-track chain")
    wav("m2_reference.wav", ideal, a.seconds, wavs,
        "dnfw.waverider.render, the same blocks, ideal precision")
    mism = sum(1 for x, y in zip(sub["machine"], ref32) if x != y)
    pre = V.fit_gain(sub["pre_amp"], ideal) if nb else None
    s3 = {"checks": {
        "substituted run returns every block": sub["ok"],
        "track buffer after the call = float32 reference, bit for bit": nb > 0 and mism == 0,
        "the stages before the amp keep our wavetable (correlation > 0.9)":
            pre is not None and pre.correlation > 0.9},
        "numbers": {"samples": len(sub["machine"]), "float32_mismatches": mism,
                    "pre_amp_fit": pre.__dict__ if pre else None,
                    "chain_peak": V.peak(sub["chain"]), "halt": sub["halt"]}}
    s3["ok"] = all(s3["checks"].values())
    results["3_reader"] = s3
    show(s3)
    if pre:
        print(f"  before the amp stage: gain {pre.gain:.4g}, correlation {pre.correlation:.4f}, "
              f"SNR {pre.snr_db and round(pre.snr_db, 1)} dB; after the chain peak {V.peak(sub['chain']):.3g}")

    print("\nstep 4: hooks")
    results["4_hooks"] = rank_hooks(results)
    for row in results["4_hooks"]["ranking"]:
        print(f"  {row['rank']}. {row['hook']}: {row['verdict']}")
    return finish(report, results, wavs)


def show(step: dict) -> None:
    for k, v in step["checks"].items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")


def rank_hooks(results: dict) -> dict:
    s1 = results.get("1_map", {}).get("checks", {})
    s3 = results.get("3_reader", {}).get("checks", {})
    return {"ok": True, "ranking": [
        {"rank": 1, "hook": "dispatch: the machine render call (0x1c9611, sw 0x1c8ef1 -> sw 0x1c6d4a)",
         "verdict": "measured: our block lands in the track buffer bit for bit and the per-track chain runs on it"
                    if s3.get("track buffer after the call = float32 reference, bit for bit") else "not demonstrated"},
        {"rank": 2, "hook": "selector: the clamp min(R2, 4) at 0x1c294c",
         "verdict": "needed for a sixth machine but hosts no DSP code: it only picks which of the "
                    "four renders (or MIDI) a track gets"},
        {"rank": 3, "hook": "output: the final scatter to the 16-channel lanes (0x1c9ae7)",
         "verdict": "reachable, but after the per-track filter, amp and pan -- a machine written there bypasses them"},
        {"rank": 4, "hook": "stage 5 (sw 0xb80f2e, table 0x26b3a8)",
         "verdict": "wrong place: one of the per-track filter renders; its table is a -1..1 shaper"
                    if s1.get("stage-5 table is a monotone -1..1 shaper, not a waveform") else "unmeasured"}]}


def finish(report: dict, results: dict, wavs: list) -> int:
    ok = bool(results) and all(r.get("ok") for r in results.values())
    report["steps"] = results
    report["wavs"] = wavs
    report["result"] = "PASS" if ok else "FAIL"
    (OUT / "m2_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n",
                                        encoding="utf-8")
    print("\nWAVs:")
    for w in wavs:
        loop = f" (looped from {w['rendered_samples']} samples)" if w["looped"] else ""
        print(f"  {w['file']}  {w['seconds']} s{loop}, peak {w['peak']:.4g} -- {w['what']}")
    print(f"\n  {report['result']}  (report: out/waverider/m2_report.json)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

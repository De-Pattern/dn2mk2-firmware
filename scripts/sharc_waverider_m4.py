"""Waverider Milestone 4 (offline): the per-track filters, an audible voice end to end, and the table baked into the DSP image.

    python scripts/sharc_waverider_m4.py \\
        --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \\
        --digikit ../digikit-wt-sharcemu [--assemble] [--blocks 16]

Every block runs the firmware's own per-block routine, `sw 0x1c2712`: the frame
unpack, the slot dispatch, the per-track chain. Nothing is poked into a track
record; the parameters arrive through a 2,688-byte frame image built by
`dnfw.waverider.frame` from the init sound's defaults in the firmware's own
parameter table (`dnfw.params`). Steps, each PASS/FAIL
(`docs/waverider-feasibility.md`, "Milestone 4"):

1. **map** -- the frame fields for the filter, amp and FX land where
   `frame.RECORD_FIELDS` says (one field changed at a time through the unpack),
   the filter type maps as `frame.FILTER_TO_DSP` says, and the per-track chain
   stages that touch a track buffer are listed, in order, from a traced block.
2. **voice** -- track 0 is machine type 5 (Waverider, Milestone 3's loop) in the
   frame, init sound, one note trigger. Its reader is audible at the end of the
   per-track chain (the amp's output) and correlates with the reference.
   Controls: FREQ 0 is quieter and darker; no trigger is silent.
3. **wavetone** -- the stock WaveTone voice through the same path, as far as
   the runner allows (report only; its decimator ringing is Milestone 2's [O]).
4. **baked** -- Part B: a wavetable directory and two tables baked into
   section 7 as boot-stream blocks; `machine5_dir.asm` resolves a voice's SLOT
   through the directory. Slot 0 and slot 1 are bit-exact to their references;
   without the directory the machine is silent. The modified section 7 is
   written under out/waverider/ and rebuilt in memory with `dnfw`'s own build
   and verify (no .syx is written).

Nothing is corrected in the Milestone 2 init snapshot. The per-track chain's
-24 dB (the DC blocker's feed-forward pair scaled by 0.0625 in the engine init)
is the firmware's own and is measured, not removed: see `dc_blocker`.

Every step writes WAVs under out/waverider/ (48 kHz, 16-bit mono, >= --seconds).
The runner renders ~3 blocks a minute here, so the rendered blocks are short:
looped files say so, and a slow PREVIEW from the bit-exact reference sits
beside them. `m4_report.json` has the numbers. Exit 0 when every step passes.
"""

from __future__ import annotations

import argparse
import cmath
import hashlib
import json
import math
import os
import pathlib
import struct
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_dn2_fixups as fx                                  # noqa: E402
import sharc_waverider_m3 as m3                                # noqa: E402
import sharc_waverider_render as m1                            # noqa: E402
import sharc_waverider_voice as m2                             # noqa: E402
from dnfw.cli.files import read_image                          # noqa: E402
from dnfw.firmware.build import build as rebuild, replacement  # noqa: E402
from dnfw.firmware.load import load                            # noqa: E402
from dnfw.firmware.verify import verify                        # noqa: E402
from dnfw.image import bootstream, sharc_object                # noqa: E402
from dnfw.image.coldfire import LoadedImage                    # noqa: E402
from dnfw.params import table as ptable                        # noqa: E402
from dnfw.waverider import frame as FR                         # noqa: E402
from dnfw.waverider import render, testtable, voice as V       # noqa: E402

OUT = ROOT / "out" / "waverider"
RATE, BLOCK = 48000, 32

UNPACK = 0x1C2712               # the per-block routine: frame unpack + dispatch + ...
UNPACK_RETURN = 0x1C3156        # its final RETURN
UNPACK_CALLER = 0x1C9FC2        # where sw 0x1c9e76 resumes after it
RX_BASE, RX_PAGE = 0x2C0478, 0x2C08E8     # the frame source R12, and the stack argument
RX_INDEX = 0x268A38             # the double-buffer index both are offset by
UNPACK_LOCAL = 0x284800         # a scratch stand-in for the caller's 10-word local
AMP_RETURN = 0x1C99D3           # the dispatch resumes here after the amp stage

MACHINE5D = ROOT / "csrc" / "waverider" / "sharc" / "machine5_dir.json"
MACHINE5D_SRC = ROOT / "csrc" / "waverider" / "sharc" / "machine5_dir.asm"
MACHINE5D_SW = 0x180200
DIR_DM = 0x28C000               # the baked wavetable directory
DIR_MAGIC = 0x57525431          # 'WRT1'
TABLE1_DM = 0x290000            # a second baked table
VBLOCK_DM, VBLOCK_STRIDE = 0x284300, 32   # machine5_dir's 8-word voice blocks

# the per-track DC blocker (engine +0xe088 + 0x70 t; kernel sw 0xb809f2, coefficient
# setup sw 0xb80b4b(block, sample rate)) -- see dc_blocker()
DCB_BASE, DCB_STRIDE, DCB_SETUP = 0xE088, 0x70, 0xB80B4B


# -- the image ------------------------------------------------------------------------------

def table1() -> list[list[int]]:
    """A second original table, distinct from the first: its frames in reverse order,
    each negated -- a saw fading to a sine, upside down. No Elektron data."""
    return [[-s if s > -32768 else 32767 for s in fr] for fr in reversed(testtable.table())]


class M4Machine:
    """DN2 1.11 with Milestone 3's code and table, plus Part B's directory, second table
    and machine5_dir, the type clamp raised and the machine lookup [5] = 5."""

    def __init__(self, dk, stream: bytes, reader: bytes, machine5: bytes, machine5d: bytes,
                 work: pathlib.Path, directory: bool = True):
        self.dk = dk
        t0, t1 = render.dsp_bytes(testtable.table()), render.dsp_bytes(table1())
        dir_bytes = struct.pack("<II", DIR_MAGIC, 2) + struct.pack("<II", m3.TABLE_DM, TABLE1_DM)
        spans = [("reader code", dk.ldr.sw_to_byte(m3.READER_SW), reader),
                 ("machine5 code", dk.ldr.sw_to_byte(m3.MACHINE5_SW), machine5),
                 ("machine5_dir code", dk.ldr.sw_to_byte(MACHINE5D_SW), machine5d),
                 ("wavetable 0", dk.ldr.SW_ALIAS_BASE + m3.TABLE_DM, t0),
                 ("wavetable 1", dk.ldr.SW_ALIAS_BASE + TABLE1_DM, t1)]
        if directory:
            spans.append(("wavetable directory", dk.ldr.SW_ALIAS_BASE + DIR_DM, dir_bytes))
        reserved = [("voice blocks", dk.ldr.SW_ALIAS_BASE + VBLOCK_DM, 16 * VBLOCK_STRIDE),
                    ("save area", dk.ldr.SW_ALIAS_BASE + m3.SAVE_DM, 0x100),
                    ("reader params", dk.ldr.SW_ALIAS_BASE + m1.PARAMS_DM, 64),
                    ("unpack local", dk.ldr.SW_ALIAS_BASE + UNPACK_LOCAL, 64)]
        base = dk.ldr.LoadedMemory.from_stream(stream)
        self.placement = []
        for name, at, size in [(n, a, len(b)) for n, a, b in spans] + reserved:
            owners = {o for _, _, o in base.owner_runs(at, size)}
            if owners != {None}:
                raise SystemExit(f"{name} at {at:#x}+{size:#x} overlaps DN2 block(s) {owners}")
            self.placement.append({"what": name, "load_address": f"{at:#010x}", "bytes": size})
        extra = b"".join(bootstream.block(at, payload) for _, at, payload in spans)
        stream = bootstream.insert_before_final(stream, extra)
        self.clamp = m3.M3Machine._raise_clamp(dk, stream, work)
        stream = self.clamp["stream"]
        stream, self.lookup = self._patch_word(dk, stream, V.MACHINE_LOOKUP + 4 * 5, 0, 5)
        self.stream = stream
        self.memory = dk.ldr.LoadedMemory.from_stream(stream)
        self.sha = hashlib.sha256(stream).hexdigest()

    @staticmethod
    def _patch_word(dk, stream: bytes, dm: int, old: int, new: int):
        blocks = dk.ldr.parse_blocks(stream)
        off = dk.ldr.offset_for_address(blocks, dk.ldr.SW_ALIAS_BASE + dm, space="byte")
        if off is None:
            raise SystemExit(f"no loaded block covers DM {dm:#x}")
        found = struct.unpack_from("<I", stream, off)[0]
        if found != old:
            raise SystemExit(f"DM {dm:#x} holds {found:#x}, not {old:#x}; refusing to patch")
        edited = bytearray(stream)
        struct.pack_into("<I", edited, off, new)
        return bytes(edited), {"dm": hex(dm), "from": old, "to": new, "stream_offset": off}


# -- the init sound, and the frame ------------------------------------------------------------

def init_sound(image: pathlib.Path) -> tuple[dict[int, int], dict[int, dict[int, int]]]:
    """The init sound from the firmware's own parameter table: indices 66..99, and the
    machine indices 25..64 per machine type (page groups 0..3)."""
    fw = load(read_image(image))
    sec = fw.container.find(3)
    tab = ptable.find(LoadedImage(dest=sec.dest, content=sec.unpack()), 15)[0]
    machines: dict[int, dict[int, int]] = {}
    for rec in tab.records:
        if rec.group in (0, 1, 2, 3) and rec.parameter_id is not None and 25 <= rec.parameter_id <= 65:
            machines.setdefault(rec.group, {}).setdefault(rec.parameter_id, rec.default & 0xFFFF)
    return FR.sound_defaults(tab.records), machines


def make_frame(sound: dict[int, int], machine: int, *, trig: bool, machine_params=None,
               overrides=None, cf_filter: int = 0) -> bytes:
    """Track 0 carries the sound (plus its machine page and OVERRIDES); tracks 1-15 are
    MIDI (no render) with init values: `frame.init_frame`, as `dnfw waverider frame`."""
    track0 = {**(machine_params or {}), **(overrides or {})}
    return FR.init_frame(sound, machine, cf_filter=cf_filter, trigger=trig, track0=track0).to_bytes()


# -- running the firmware's per-block routine ---------------------------------------------------

def fixups(hooks=None) -> fx.Fixups:
    f = fx.Fixups()
    f.hooks[fx.SIN] = fx.native_sin
    for pc in fx.ADDITIVE:
        f.hooks[pc] = fx.native_additive
    f.hooks.update(hooks or {})
    return f


def unpack_call(state_runner, frame: bytes):
    """A fresh call of sw 0x1c2712 the way sw 0x1c9e76 makes it (0x1c9fbc), with FRAME
    in the frame source it copies from."""
    s = state_runner.state
    idx = m2.word(s, RX_INDEX) or 0
    i7 = m2.word_reg(state_runner, "I7")
    rx = RX_BASE + (idx << 8)
    r = state_runner.fresh_call(UNPACK, regs={"R4": 0x268438, "R8": UNPACK_LOCAL, "R12": rx,
                                              "I6": i7, "I7": i7 - 16},
                                return_address=UNPACK_CALLER)
    for k in range(10):
        m2.poke(r.state, UNPACK_LOCAL + 4 * k, 0)
    m2.poke(r.state, i7 + 4, 0)
    m2.poke(r.state, i7 + 8, RX_PAGE + (idx << 11))
    for k in range(0, len(frame), 4):
        m2.poke(r.state, rx + k, struct.unpack_from("<I", frame, k)[0])
    return r


def run_blocks(init, blocks: int, frames, *, type5=None, type5_entry=m3.MACHINE5_SW,
               tracer=None, trace_block=None):
    """BLOCKS calls of sw 0x1c2712, state carried. FRAMES(b) -> frame bytes. TYPE5(state, b)
    prepares the type-5 voice blocks. Taps track 0's buffer after its machine render,
    at the amp's input and at the amp's output (the end of the per-track chain)."""
    state = init
    out = {"machine": [], "pre_amp": [], "amp_out": [], "pre_machine": []}
    instr, wall = 0, 0.0
    for b in range(blocks):
        tap, hold = {}, {}

        def at_dispatch(runner):
            hold["buf"] = m2.word(runner.state, V.TRACK_BUFFERS)
            if tracer is not None:
                tracer.buf = hold["buf"]

        def after_machine(runner):
            tap.setdefault("machine", m2.floats(runner.state, hold["buf"], BLOCK))

        def amp(runner):
            if m2.word_reg(runner, "R12") == hold.get("buf") and "pre_amp" not in tap:
                tap["pre_amp"] = m2.floats(runner.state, hold["buf"], BLOCK)

        def amp_ret(runner):
            if "pre_amp" in tap and "amp_out" not in tap:
                tap["amp_out"] = m2.floats(runner.state, hold["buf"], BLOCK)

        hooks = {m3.DISPATCH: at_dispatch, m3.WT_RESUME: after_machine,
                 m3.AMP_STAGE: amp, AMP_RETURN: amp_ret}
        if type5 is not None:
            def enter5(runner):
                tap.setdefault("pre_machine", m2.floats(runner.state, hold["buf"], BLOCK))
                type5(runner.state, b)
                runner.state.pc_sw = type5_entry
            hooks[m3.TYPE5_ENTRY] = enter5
            hooks[m3.TYPE5_RESUME] = after_machine
        if tracer is not None and b == trace_block:
            f = tracer
            f.hooks.update(hooks)
            f.active = True
        else:
            f = fixups(hooks)
        r = unpack_call(state, frames(b))
        t0 = time.perf_counter()
        res = fx.run(r, 8_000_000, f)
        wall += time.perf_counter() - t0
        if not (res[0] == "halt" and res[1].pc_sw == UNPACK_RETURN):
            halt = f"{res[1].reason} at {res[1].pc_sw:#x}" if res[0] == "halt" else res[0]
            return {"ok": False, "blocks": b, "halt": halt, **out}
        for k in out:
            out[k] += tap.get(k, [0.0] * BLOCK)
        instr += res[2]
        state = r
    return {"ok": True, "blocks": blocks, "instructions": instr, "wall_s": round(wall, 1),
            "state": state, **out}


class ChainTracer(fx.Fixups):
    """Records the calls sw 0x1c8ef1's body makes that change (or are handed) track 0's
    buffer: target, R4 (the stage's state), and the buffer's peak before and after."""

    BODY = (0x1C8EF1, 0x1C9C5D)

    def __init__(self):
        super().__init__()
        self.hooks[fx.SIN] = fx.native_sin
        for pc in fx.ADDITIVE:
            self.hooks[pc] = fx.native_additive
        self.buf, self.prev, self.open, self.calls, self.active = None, None, None, [], False

    def pre(self, runner, insn):
        pc = runner.state.pc_sw
        if self.active and self.buf is not None:
            inb = self.BODY[0] <= pc < self.BODY[1]
            pin = self.prev is not None and self.BODY[0] <= self.prev < self.BODY[1]
            if pin and not inb and self.open is None:
                self.open = {"from": hex(self.prev), "target": hex(pc),
                             "R4": hex(m2.word_reg(runner, "R4")),
                             "R12": m2.word_reg(runner, "R12"),
                             "before": m2.floats(runner.state, self.buf, BLOCK)}
            elif inb and not pin and self.open is not None:
                o = self.open
                after = m2.floats(runner.state, self.buf, BLOCK)
                if o["R12"] == self.buf or after != o["before"]:
                    self.calls.append({"from": o["from"], "target": o["target"], "R4": o["R4"],
                                       "peak_in": V.peak(o["before"]), "peak_out": V.peak(after),
                                       "changed": after != o["before"]})
                self.open = None
            self.prev = pc
        return super().pre(runner, insn)


# -- the per-track DC blocker's -24 dB -----------------------------------------------------------

def dc_blocker(init) -> dict:
    """Measure, do not correct: the per-track DC blocker (engine +0xe088 + 0x70 t, kernel
    sw 0xb809f2) is a one-pole high-pass whose feed-forward pair the engine init scales
    by 0.0625 after its own setup computes it (the SIMD multiply at 0x1c8cf6, one PE per
    coefficient): -24 dB on every track, by the firmware's design. Here: the snapshot's
    coefficients beside what the setup sw 0xb80b4b(block, 48000.0) gives unscaled."""
    rate = m2.word(init.state, V.ENGINE) or 0
    blk = V.ENGINE + DCB_BASE
    snap = [V.bits_f32(m2.word(init.state, blk + 4 * k) or 0) for k in (0x15, 0x16, 0x17)]
    scratch = 0x284A00
    r = init.fresh_call(DCB_SETUP, regs={"R4": scratch, "R12": rate, "MODE1": 0},
                        return_address=0x123456)
    fx.run(r, 5000, fx.Fixups(), stop_at=[0x123456])
    raw = [V.bits_f32(m2.word(r.state, scratch + 4 * k) or 0) for k in (0x15, 0x16, 0x17)]
    return {"rate": V.bits_f32(rate), "snapshot_a0_a1_b1": snap, "setup_a0_a1_b1": raw,
            "feed_forward_scale": snap[0] / raw[0] if raw[0] else None,
            "scaled_at": "0x1c8cf6 (f2 = f2 * 0.0625, SIMD: PEx a0, PEy a1), in the engine init",
            "cutoff_hz": round(-math.log(-snap[2]) * RATE / (2 * math.pi), 2) if snap[2] < 0 else None}


# -- signal measures ------------------------------------------------------------------------------

def centroid(samples: list[float], rate: int = RATE) -> float:
    """Spectral centroid (Hz) of SAMPLES, Hann window, plain DFT up to Nyquist."""
    n = len(samples)
    if n < 8 or not any(samples):
        return 0.0
    win = [samples[k] * (0.5 - 0.5 * math.cos(2 * math.pi * k / (n - 1))) for k in range(n)]
    num = den = 0.0
    for b in range(1, n // 2):
        c = sum(win[k] * cmath.exp(-2j * math.pi * b * k / n) for k in range(n))
        mag = abs(c)
        num += mag * b * rate / n
        den += mag
    return num / den if den else 0.0


# -- the steps --------------------------------------------------------------------------------------

def step_map(dk, init, sound) -> dict:
    """The field map re-measured (filter, amp, FX), the filter-type mapping, and the stages."""
    rec0 = V.track_record(0)
    got, bad = {}, []
    for index, (off, kind, what) in sorted(FR.RECORD_FIELDS.items()):
        f = FR.Frame()
        base_r = run_unpack_only(init, f.to_bytes())
        b0 = m2.word(base_r.state, rec0 + off)
        f.param(0, index, 0x4040)
        r = run_unpack_only(init, f.to_bytes())
        v = m2.word(r.state, rec0 + off)
        got[index] = {"record_offset": hex(off), "what": what, "changed": v != b0,
                      "value": V.bits_f32(v or 0) if kind in "utkv" else v}
        if v == b0:
            bad.append(index)
    ftypes = []
    for cf in range(8):
        f = FR.Frame()
        f.header(FR.FILTER, 0, cf)
        r = run_unpack_only(init, f.to_bytes())
        ftypes.append(m2.word(r.state, rec0 + 0x1DC))
    checks = {
        "every filter/amp/FX field lands in the record offset frame.RECORD_FIELDS records": not bad,
        "the filter type maps as frame.FILTER_TO_DSP": ftypes == [FR.dsp_filter(t) for t in range(8)],
        "FREQ 0x4040 unpacks to 0x4040/32768": abs(got[67]["value"] - 0x4040 / 32768) < 1e-6,
        "KEY.T scales by its own range (0x6400)": abs(got[79]["value"] - 0x4040 / 25600) < 1e-6,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"fields": got, "fields_not_landing": bad, "dsp_filter_for_cf_0_7": ftypes,
                        "init_sound_filter": {FR.RECORD_FIELDS[i][2]: hex(sound[i])
                                              for i in (66, 67, 68, 69, 76, 77, 78, 79)},
                        "init_sound_amp": {FR.RECORD_FIELDS[i][2]: hex(sound[i])
                                           for i in (81, 82, 83, 84, 85, 89, 90, 91)}}}


def run_unpack_only(init, frame: bytes):
    r = unpack_call(init, frame)
    fx.run(r, 2_000_000, fixups(), stop_at=[0x1C3044])       # before it calls the dispatch
    return r


def voice_prep(freq, positions, slot=None):
    """The type-5 voice block for track 0, per block: M3's 6-word block, or with SLOT the
    8-word block machine5_dir reads (phase carries; the table pointer is NOT written)."""
    def prep(state, b):
        pos = positions[min(b, len(positions) - 1)]
        if slot is None:
            m3.preset_voice_block(state, 0, freq, pos)
        else:
            base = VBLOCK_DM
            m2.poke(state, base + 8, render.increment(freq))
            m2.poke(state, base + 12, pos)
            m2.poke(state, base + 24, slot)
    return prep


def step_voice(init, sound, blocks, freq) -> dict:
    positions = render.sweep(len(testtable.table()), max(blocks, 2))
    prep = voice_prep(freq, positions)
    tr = ChainTracer()
    on = run_blocks(init, blocks, lambda b: make_frame(sound, 5, trig=(b == 1)), type5=prep,
                    tracer=tr, trace_block=blocks - 1)
    closed = run_blocks(init, blocks, lambda b: make_frame(sound, 5, trig=(b == 1), overrides={67: 0}),
                        type5=prep)
    silent = run_blocks(init, blocks, lambda b: make_frame(sound, 5, trig=False), type5=prep)
    table = testtable.table()
    inc = render.increment(freq)
    ref32 = render.render_blocks(table, inc, positions[:blocks], BLOCK, 0, "float32")
    ideal = render.render_blocks(table, inc, positions[:blocks], BLOCK, 0, "ideal")
    ok_runs = on["ok"] and closed["ok"] and silent["ok"]
    settle = BLOCK * min(4, blocks // 2)                    # after the attack
    fit = V.fit_gain(on["amp_out"][settle:], ideal[settle:]) if ok_runs else None
    mism = sum(1 for x, y in zip(on["machine"], ref32) if x != y) if on["ok"] else -1
    n = {"machine_peak": V.peak(on["machine"]), "pre_amp_peak": V.peak(on["pre_amp"]),
         "end_peak": V.peak(on["amp_out"][settle:]), "end_rms": V.rms(on["amp_out"][settle:]),
         "closed_rms": V.rms(closed["amp_out"][settle:]) if closed["ok"] else None,
         "silent_peak": V.peak(silent["amp_out"]) if silent["ok"] else None,
         "open_centroid_hz": centroid(on["amp_out"][settle:]) if on["ok"] else None,
         "closed_centroid_hz": centroid(closed["amp_out"][settle:]) if closed["ok"] else None,
         "machine_float32_mismatches": mism, "end_fit": fit.__dict__ if fit else None,
         "instructions_per_block": round(on.get("instructions", 0) / max(blocks, 1)),
         "wall_s": on.get("wall_s")}
    checks = {
        "the three runs (open, FREQ 0, no trigger) return every block": ok_runs,
        "type 5 via the frame renders our reader bit for bit (float32)": mism == 0,
        "audible at the end of the per-track chain (amp output peak > 0.02, -34 dBFS; the chain's own design gain is -20 dB)": n["end_peak"] > 0.02,
        "correlated with the reference through the chain (r > 0.9)": bool(fit) and fit.correlation > 0.9,
        "control: FREQ 0 is quieter (rms < half the open run's)":
            ok_runs and n["closed_rms"] < 0.5 * n["end_rms"],
        "control: FREQ 0 is darker (lower spectral centroid)":
            ok_runs and n["closed_centroid_hz"] < n["open_centroid_hz"],
        "control: no trigger is silent (peak < 0.01)": ok_runs and n["silent_peak"] < 0.01,
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": n, "stages": tr.calls,
            "on": on, "closed": closed, "silent": silent, "reference": ideal, "float32": ref32}


def step_wavetone(init, sound, machines, blocks) -> dict:
    """Report only: the stock WaveTone voice, init sound incl. its machine page, one trigger."""
    run = run_blocks(init, blocks, lambda b: make_frame(sound, 1, trig=(b == 1),
                                                        machine_params=machines.get(1)))
    ctrl = run_blocks(init, blocks, lambda b: make_frame(sound, 1, trig=False,
                                                         machine_params=machines.get(1)))
    zc = sum(1 for a, b in zip(run["machine"], run["machine"][1:]) if (a < 0) != (b < 0)) if run["ok"] else 0
    n = {"machine_peak": V.peak(run["machine"]), "end_peak": V.peak(run["amp_out"]),
         "machine_zero_crossings": zc, "control_end_peak": V.peak(ctrl["amp_out"]) if ctrl["ok"] else None,
         "halt": run.get("halt")}
    return {"ok": run["ok"], "report_only": True, "numbers": n, "run": run, "ctrl": ctrl}


def step_baked(dk, stream, reader, m5, m5d, work, blocks, freq) -> dict:
    with_dir = M4Machine(dk, stream, reader, m5, m5d, work, directory=True)
    no_dir = M4Machine(dk, stream, reader, m5, m5d, work, directory=False)
    positions = render.sweep(len(testtable.table()), max(blocks, 2))
    inc = render.increment(freq)
    res = {}
    for name, mach, slot, table in (("slot0", with_dir, 0, testtable.table()),
                                    ("slot1", with_dir, 1, table1()),
                                    ("no_directory", no_dir, 0, None)):
        init = load_init(dk, mach, stream, reader)
        run = run_blocks(init, blocks, lambda b: make_frame(SOUND, 5, trig=(b == 1)),
                         type5=voice_prep(freq, positions, slot), type5_entry=MACHINE5D_SW)
        ref = render.render_blocks(table, inc, positions[:blocks], BLOCK, 0, "float32") if table else None
        mism = sum(1 for x, y in zip(run["machine"], ref) if x != y) if (run["ok"] and ref) else None
        table_word = m2.word(run["state"].state, VBLOCK_DM) if run["ok"] else None
        untouched = run["ok"] and run["machine"] == run["pre_machine"]
        res[name] = {"run": run, "mismatches": mism, "voice_table_pointer": table_word,
                     "untouched": untouched,
                     "machine_peak": V.peak(run["machine"]), "end_peak": V.peak(run["amp_out"])}
    s7 = OUT / "m4_section7_waverider.bin"
    s7.write_bytes(with_dir.stream)
    rb = rebuild_check(with_dir.stream)
    checks = {
        "the three runs return every block": all(r["run"]["ok"] for r in res.values()),
        "slot 0: the directory's table 0 renders bit for bit": res["slot0"]["mismatches"] == 0,
        "slot 1: the directory's table 1 renders bit for bit": res["slot1"]["mismatches"] == 0,
        "the table pointer came from the directory, not the harness":
            res["slot1"]["voice_table_pointer"] == TABLE1_DM,
        "control: without the directory block the loop renders nothing (buffer untouched)":
            res["no_directory"]["untouched"],
        "section 7 rebuilds into an image that passes dnfw verify": rb["verify_ok"],
    }
    return {"ok": all(checks.values()), "checks": checks, "res": res,
            "numbers": {k: {kk: vv for kk, vv in v.items() if kk != "run"} for k, v in res.items()},
            "section7": {"file": str(s7), "bytes": len(with_dir.stream),
                         "sha256": with_dir.sha, "placement": with_dir.placement,
                         "lookup_patch": with_dir.lookup, "clamp": {k: v for k, v in with_dir.clamp.items()
                                                                    if k != "stream"},
                         "rebuild": rb}}


def rebuild_check(section7: bytes) -> dict:
    """What a real build needs, done in memory only: `dnfw build`'s own replacement() and
    build() with section 7 swapped, re-loaded and run through `dnfw`'s verify. No file."""
    fw = load(read_image(IMAGE))
    new = replacement(fw, 7, section7)
    out = rebuild(fw, {7: new})
    checked = load(out)
    rep = verify(checked)
    return {"verify_ok": rep.ok, "checks": len(rep.checks),
            "failed": [c.name for c in rep.checks if not c.ok],
            "stored": "compressed" if fw.container.find(7).unpack() is not None else "raw",
            "image_bytes": len(out), "signed": checked.key is not None,
            "written": False}


# -- plumbing -----------------------------------------------------------------------------------------

def load_init(dk, mach, stream, reader):
    return m3.load_init(dk, mach, stream, reader, testtable.table(), False)


def load_code(path, src, do_assemble, work, load_sw):
    code, offsets, info = m3.load_json(path, src, do_assemble, work)
    if do_assemble and not path.exists():
        be, _ = m3._selas(src, work)
        path.write_text(json.dumps({
            "source": src.relative_to(ROOT).as_posix(), "source_sha256": info["source_sha256"],
            "toolchain": "selache selas -proc ADSP-21569 (js216/selache 2b26d3b, GPL-3.0, WSL)",
            "section": "seg_pmco", "load_sw": hex(load_sw), "object_parcels_be": be.hex(),
            "instruction_offsets": offsets}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return code, offsets, info


def check_targets(dk, memory, load_sw, offsets):
    walk = dk.walk(memory, load_sw, load_sw + max(offsets) // 2 + 4)
    starts = [(sw - load_sw) * 2 for sw, _, _, _ in walk]
    bad = [f"{sw:#x} {form}" for sw, _, form, kind in walk
           if (form == "unknown" or kind == "uncertain") and (sw - load_sw) * 2 <= max(offsets)]
    return {"boundaries_match_assembler": all(o in starts for o in offsets), "unknown_or_uncertain": bad}


def wav(name, samples, seconds, wavs, what, looped_ok=True):
    n = int(seconds * RATE)
    looped = V.loop_to(list(samples), n)
    path = OUT / name
    m1.write_wav(path, looped, RATE)
    is_looped = 0 < len(samples) < n
    wavs.append({"file": str(path), "seconds": round(len(looped) / RATE, 3),
                 "rendered_samples": len(samples), "looped": is_looped,
                 "peak": V.peak(samples), "rms": V.rms(samples),
                 "what": (what + (" (LOOPED)" if is_looped else ""))})


def show(step):
    for k, v in step.get("checks", {}).items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")


IMAGE = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
SOUND: dict[int, int] = {}


def main(argv=None):
    global IMAGE, SOUND
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=pathlib.Path, default=IMAGE)
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--blocks", type=int, default=12)
    p.add_argument("--seconds", type=float, default=2.5)
    p.add_argument("--freq", type=float, default=375.0)
    p.add_argument("--assemble", action="store_true", help="reassemble with selas (WSL)")
    p.add_argument("--steps", default="map,voice,wavetone,baked")
    a = p.parse_args(argv)
    if a.seconds < 2:
        raise SystemExit("--seconds must be at least 2")
    IMAGE = a.image
    steps = set(a.steps.split(","))
    OUT.mkdir(parents=True, exist_ok=True)
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    stream = m1.dn2_section7(a.image)
    SOUND, machines = init_sound(a.image)
    wavs, results = [], {}
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        work = pathlib.Path(tmp)
        reader, _, r_prov = m1.reader_code(a.assemble, work)
        m5, _, m5_prov = m3.load_json(m3.MACHINE5, m3.MACHINE5_SRC, a.assemble, work)
        m5d, m5d_off, m5d_prov = load_code(MACHINE5D, MACHINE5D_SRC, a.assemble, work, MACHINE5D_SW)
        mach = M4Machine(dk, stream, reader, m5, m5d, work)
        m5d_prov["placement_check"] = check_targets(dk, mach.memory, MACHINE5D_SW, m5d_off)
        init = load_init(dk, mach, stream, reader)
        dcb = dc_blocker(init)
        print(f"  per-track DC blocker: feed-forward x{dcb['feed_forward_scale']:.4f} "
              f"(the firmware's own), cutoff ~{dcb['cutoff_hz']} Hz")
        report = {"digikit": {"path": str(a.digikit), "head": dk.head}, "image_sha256": mach.sha,
                  "reader": r_prov, "machine5": m5_prov, "machine5_dir": m5d_prov,
                  "placement": mach.placement, "lookup_patch": mach.lookup, "blocks": a.blocks,
                  "dc_blocker": dcb, "init_sound": {str(k): hex(v) for k, v in sorted(SOUND.items())}}

        if "map" in steps:
            print("\nstep 1: the frame's filter, amp and FX fields, and the chain")
            s1 = step_map(dk, init, SOUND)
            results["1_map"] = s1
            show(s1)

        if "voice" in steps:
            print("\nstep 2: an audible Waverider voice end to end (type 5, init sound, one trigger)")
            s2 = step_voice(init, SOUND, a.blocks, a.freq)
            results["2_voice"] = {k: v for k, v in s2.items()
                                  if k not in ("on", "closed", "silent", "reference", "float32")}
            show(s2)
            for c in s2["stages"]:
                print(f"    {c['from']} -> {c['target']}  R4 {c['R4']}  peak {c['peak_in']:.4f} -> {c['peak_out']:.4f}")
            wav("m4_waverider_voice_end_to_end.wav", s2["on"]["amp_out"], a.seconds, wavs,
                "KEY DELIVERABLE: type-5 Waverider voice at the end of the per-track chain (amp output), "
                "init sound, filter open, note triggered on block 1; runner blocks")
            pk = V.peak(s2["on"]["amp_out"])
            wav("m4_waverider_voice_end_to_end_normalised.wav",
                [x * (0.9 / pk) for x in s2["on"]["amp_out"]] if pk else s2["on"]["amp_out"], a.seconds, wavs,
                f"the key deliverable scaled by {0.9 / pk if pk else 1:.2f} to 0.9 peak, for listening; "
                "same runner blocks")
            wav("m4_filter_open.wav", s2["on"]["amp_out"], a.seconds, wavs,
                "filter open (init sound, FREQ 127) at the end of the chain; runner blocks")
            wav("m4_filter_closed.wav", s2["closed"]["amp_out"], a.seconds, wavs,
                "control: the same with FREQ 0, at the end of the chain; runner blocks")
            wav("m4_no_trigger.wav", s2["silent"]["amp_out"], a.seconds, wavs,
                "control: no note trigger, end of the chain: silent; runner blocks")
            wav("m4_type5_machine.wav", s2["on"]["machine"], a.seconds, wavs,
                "our reader straight out of track 0's buffer, bit-exact to the reference; runner blocks")
            slow = render.render_blocks(testtable.table(), render.increment(a.freq),
                                        render.sweep(len(testtable.table()), max(int(a.seconds * RATE) // BLOCK, 2)),
                                        BLOCK, 0, "float32")
            wav("m4_preview_reference_sweep.wav", slow, a.seconds, wavs,
                "PREVIEW, not the runner: the float32 reference (bit-exact to the runner's machine tap), "
                "the frame sweep 0->15->0 spread over the whole file")

        if "wavetone" in steps:
            print("\nstep 3: the stock WaveTone voice through the same path (report only)")
            s3 = step_wavetone(init, SOUND, machines, a.blocks)
            results["3_wavetone"] = {k: v for k, v in s3.items() if k not in ("run", "ctrl")}
            print(f"  {s3['numbers']}")
            wav("m4_wavetone_end_to_end.wav", s3["run"]["amp_out"], a.seconds, wavs,
                "stock WaveTone, init sound, one trigger, end of the per-track chain; runner blocks")
            wav("m4_wavetone_machine.wav", s3["run"]["machine"], a.seconds, wavs,
                "stock WaveTone: track buffer after its own render (M2's decimator ringing [O]); runner blocks")

        if "baked" in steps:
            print("\nstep 4: Part B, the table baked into section 7 and read through a directory")
            s4 = step_baked(dk, stream, reader, m5, m5d, work, a.blocks, a.freq)
            results["4_baked"] = {k: v for k, v in s4.items() if k != "res"}
            show(s4)
            for name in ("slot0", "slot1", "no_directory"):
                wav(f"m4_baked_{name}.wav", s4["res"][name]["run"]["machine"], a.seconds, wavs,
                    f"Part B, {name}: track 0's buffer after machine5_dir" + (" (untouched: it holds the previous block's chain output)" if name == "no_directory" else "") + "; runner blocks")
            slow1 = render.render_blocks(table1(), render.increment(a.freq),
                                         render.sweep(16, max(int(a.seconds * RATE) // BLOCK, 2)),
                                         BLOCK, 0, "float32")
            wav("m4_preview_table1_sweep.wav", slow1, a.seconds, wavs,
                "PREVIEW, not the runner: table 1's float32 reference, sweep over the whole file")

    ok = bool(results) and all(r.get("ok") for k, r in results.items() if not r.get("report_only"))
    report["steps"] = results
    report["wavs"] = wavs
    report["result"] = "PASS" if ok else "FAIL"
    (OUT / "m4_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print("\nWAVs:")
    for w_ in wavs:
        print(f"  {w_['file']}  {w_['seconds']} s, peak {w_['peak']:.4g} -- {w_['what']}")
    print(f"\n  {report['result']}  (report: out/waverider/m4_report.json)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

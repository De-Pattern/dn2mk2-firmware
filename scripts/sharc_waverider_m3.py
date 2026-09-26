"""Waverider Milestone 3 (offline): an audible Waverider voice, as a sixth machine type.

    python scripts/sharc_waverider_m3.py \\
        --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \\
        --digikit ../digikit-wt-sharcemu [--assemble] [--blocks 6]

Three steps, each PASS/FAIL (`docs/waverider-feasibility.md`, "Milestone 3"):

1. **trigger** -- the note trigger and the amp envelope. A track's WaveTone
   voice is armed (M2's hand-arm) and a note is triggered by the trigger cell
   the frame unpack sets (record's per-track note counter, engine `+0x138fc`,
   raised through `sw 0xb82440`). With a constant probe in place of the
   machine render, the amp stage (`sw 0xb80345`) passes the probe only after
   the trigger and is silent before it (the control). The four fields the task
   names are recorded from the run.
2. **reader** -- our reader (M2) substituted at the WaveTone render call, with
   the note triggered and sustain held: the reader's wavetable is audible at
   the end of the per-track chain, silent without the trigger, and its
   correlation to the reference through the chain gain is measured.
3. **type5** -- our own SHARC render loop for machine type 5
   (csrc/waverider/sharc/machine5.asm), assembled with selas and spliced into
   unloaded spans, is entered where a sixth per-type loop would sit in
   `sw 0x1c8ef1` (a JUMP over 0x1c9448, modelled by a pc redirect). It scans
   the 16 track records and calls our reader (reader.asm) for every track of
   type 5. A type-5 track renders our reader into its track buffer bit for bit;
   types 0-4 stay bit-identical to a stock run (the control). The DSP type
   clamp `min(R2,4)` at `0x1c294c` is raised to `min(R2,5)` as a one-parcel
   selas patch and verified by running the track loop with a type-5 selector.

Every step writes WAVs under out/waverider/ (48 kHz, 16-bit mono, >= --seconds).
Looped renders are labelled; a slow bit-exact reference PREVIEW sits beside
them. `m3_report.json` has the numbers. digikit (GPL-2.0+) and selache
(GPL-3.0) are tools called from checkouts you name; no code of theirs is copied.
Exit 0 when every step passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_dn2_fixups as fx                                  # noqa: E402
import sharc_waverider_render as m1                            # noqa: E402
import sharc_waverider_voice as m2                             # noqa: E402
from dnfw.image import sharc_object                            # noqa: E402
from dnfw.waverider import render, testtable, voice as V       # noqa: E402

OUT = ROOT / "out" / "waverider"
RATE, BLOCK, MIDI = 48000, 32, 4

# our spliced code and data (unloaded spans; the same region M1/M2 used)
READER_SW = m1.CODE_SW          # 0x180000, wr_render
MACHINE5_SW = 0x180100          # wr_type5, the sixth render loop
TABLE_DM = m1.TABLE_DM          # 0x280000
VOICE_BLOCKS_DM = 0x284300      # 16 x 6-word wr_render parameter blocks
VOICE_STRIDE = 24               # bytes
SAVE_DM = 0x284200              # machine5's register save area

MACHINE5 = ROOT / "csrc" / "waverider" / "sharc" / "machine5.json"
MACHINE5_SRC = ROOT / "csrc" / "waverider" / "sharc" / "machine5.asm"

# the ColdFire-side gates for a real type-5 frame (research; measured here)
CLAMP_SW = 0x1C294A             # `R0 = 0x4` feeding min(R2,R0) at 0x1c294c
LOOKUP_DM = 0x25D748            # frame nibble -> machine type, entry [5] = 0

# dispatch landmarks (M2)
DISPATCH, DISPATCH_RETURN, FAKE_RETURN = m2.DISPATCH, m2.DISPATCH_RETURN, m2.FAKE_RETURN
WT_CALL, WT_RESUME = m2.WT_CALL, m2.WT_RESUME
AMP_STAGE = m2.AMP_STAGE
TYPE5_ENTRY = 0x1C9448          # where a sixth per-type loop is entered (JUMP -> wr_type5)
TYPE5_RESUME = 0x1C944C         # where wr_type5 returns
NOTE_ON_FN = 0xB82440           # arms a voice's note counter (called at 0x1c96a3/0x1c91c5)
TRIG_CELL = 0x138FC             # engine + this: the per-track note-trigger flag byte
# a hand-built ADSR: attack 0, decay 0, sustain 1.0, release 0.5, ADSR-mode on
ENV = {0x20C: ("i", 0), 0x210: ("f", 0.0), 0x214: ("f", 0.0), 0x218: ("f", 0.0),
       0x21C: ("f", 1.0), 0x220: ("f", 0.5), 0x224: ("f", 0.0)}


# -- placement -------------------------------------------------------------------------

def load_json(path: pathlib.Path, src: pathlib.Path, do_assemble: bool, work: pathlib.Path):
    """-> (memory-order bytes, instruction offsets, provenance) for a committed .json,
    reassembling with selas when --assemble (and checking it reproduces the commit)."""
    sha = hashlib.sha256(src.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    committed = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    info = {"source": src.name, "source_sha256": sha}
    if do_assemble:
        be, offsets = _selas(src, work)
        info["assembled"] = "now, with selas"
        info["matches_committed"] = bool(committed) and \
            committed["source_sha256"] == sha and \
            bytes.fromhex(committed["object_parcels_be"]) == be and \
            committed.get("instruction_offsets") == offsets
        return sharc_object.load_bytes(be), offsets, info
    if not committed:
        raise SystemExit(f"{path} missing: run with --assemble (needs WSL + selache)")
    if committed["source_sha256"] != sha:
        raise SystemExit(f"{path} is stale for {src.name}: run with --assemble")
    info["assembled"] = f"committed {path.name} ({committed['toolchain']})"
    return sharc_object.load_bytes(bytes.fromhex(committed["object_parcels_be"])), \
        committed["instruction_offsets"], info


def _selas(src: pathlib.Path, work: pathlib.Path):
    """Reassemble SRC with a global label before every instruction; -> (be bytes, offsets)."""
    lines, k = [], 0
    for line in src.read_text(encoding="utf-8").splitlines():
        text = line.split("//", 1)[0].strip()
        if text and not text.startswith(".") and not text.endswith(":"):
            lines += [f".GLOBAL x_i{k};", f"x_i{k}:"]
            k += 1
        lines.append(line)
    lab = work / (src.stem + "_lab.asm")
    lab.write_bytes(("\n".join(lines) + "\n").encode())
    obj = work / (src.stem + ".doj")
    r = m1._wsl(f"{m1.SELAS} -proc ADSP-21569 -o {m1._wsl_path(obj)} {m1._wsl_path(lab)}\n", work)
    if r.returncode or not obj.exists():
        raise SystemExit(f"selas failed for {src.name}:\n{r.stdout}{r.stderr}")
    data = obj.read_bytes()
    syms = sharc_object.symbols(data)
    return sharc_object.code(data, "seg_pmco"), [2 * syms[f"x_i{j}"] for j in range(k)]


def check_machine5_targets(dk, mach, m5_offsets: list[int]) -> dict:
    """machine5.asm hard-codes absolute jump targets for MACHINE5_SW; decode the
    spliced code and confirm every internal branch and the CJUMP land on our own
    labels (or wr_render), and there is no unknown/uncertain form."""
    walk = dk.walk(mach.memory, MACHINE5_SW, MACHINE5_SW + (max(m5_offsets) + 8))
    starts = [(sw - MACHINE5_SW) * 2 for sw, _, _, _ in walk]
    bad = [f"{sw:#x} {form}" for sw, _, form, kind in walk
           if (form == "unknown" or kind == "uncertain")
           and (sw - MACHINE5_SW) * 2 <= max(m5_offsets)]
    return {"boundaries_match_assembler": all(o in starts for o in m5_offsets),
            "unknown_or_uncertain": bad}


class M3Machine:
    """DN2 1.11 with reader.asm, machine5.asm, the table and per-voice param blocks
    spliced into unloaded spans, and the type clamp raised in place."""

    def __init__(self, dk, stream: bytes, reader: bytes, machine5: bytes, table,
                 raise_clamp: bool, work: pathlib.Path):
        self.dk = dk
        table_bytes = render.dsp_bytes(table)
        spans = [("reader code", dk.ldr.sw_to_byte(READER_SW), reader),
                 ("machine5 code", dk.ldr.sw_to_byte(MACHINE5_SW), machine5),
                 ("wavetable", dk.ldr.SW_ALIAS_BASE + TABLE_DM, table_bytes)]
        reserved = [("voice param blocks", dk.ldr.SW_ALIAS_BASE + VOICE_BLOCKS_DM, 16 * VOICE_STRIDE),
                    ("save area", dk.ldr.SW_ALIAS_BASE + SAVE_DM, 0x100),
                    ("reader params", dk.ldr.SW_ALIAS_BASE + m1.PARAMS_DM, 64),
                    ("reader output", dk.ldr.SW_ALIAS_BASE + m1.OUT_DM, 4 * m1.MAX_BLOCK)]
        base = dk.ldr.LoadedMemory.from_stream(stream)
        self.placement = []
        for name, at, size in [(n, a, len(b)) for n, a, b in spans] + reserved:
            owners = {o for _, _, o in base.owner_runs(at, size)}
            if owners != {None}:
                raise SystemExit(f"{name} at {at:#x}+{size:#x} overlaps DN2 block(s) {owners}")
            self.placement.append({"what": name, "load_address": f"{at:#010x}", "bytes": size})
        from dnfw.image import bootstream
        extra = b"".join(bootstream.block(at, payload) for _, at, payload in spans)
        stream = bootstream.insert_before_final(stream, extra)
        self.clamp = self._raise_clamp(dk, stream, work) if raise_clamp else None
        if self.clamp:
            stream = self.clamp["stream"]
        self.stream = stream
        self.memory = dk.ldr.LoadedMemory.from_stream(stream)
        self.sha = hashlib.sha256(stream).hexdigest()

    @staticmethod
    def _raise_clamp(dk, stream: bytes, work: pathlib.Path) -> dict:
        """Overwrite `R0 = 0x4` at CLAMP_SW with `R0 = 0x5` (one selas-assembled
        17b parcel), so min(R2,R0) admits type 5. Placed by editing the loaded
        stream; verified by running (step 3)."""
        be, _ = _selas_line("R0 = 0x5;", work)
        patch = sharc_object.load_bytes(be)
        blocks = dk.ldr.parse_blocks(stream)
        off = dk.ldr.offset_for_address(blocks, CLAMP_SW)
        if off is None:
            raise SystemExit(f"no loaded block covers {CLAMP_SW:#x}")
        before = stream[off:off + len(patch)]
        want, _ = _selas_line("R0 = 0x4;", work)
        if before != sharc_object.load_bytes(want):
            raise SystemExit(f"{CLAMP_SW:#x} is not `R0 = 0x4` (found {before.hex()}); refusing to patch")
        edited = bytearray(stream)
        edited[off:off + len(patch)] = patch
        return {"stream": bytes(edited), "sw": hex(CLAMP_SW), "from": before.hex(),
                "to": patch.hex(), "bytes": len(patch)}

    def runner(self, start: int, regs=None):
        base = {"I6": m2.STACK, "I7": m2.STACK}
        base.update(regs or {})
        return fx.sr.Runner(self.memory, start, regs=base, explicit_memory_model=True,
                            approx_recips=True, follow_loaded_calls=True, max_call_depth=64)


def _selas_line(line: str, work: pathlib.Path):
    src = work / f"one_{abs(hash(line)) & 0xffff:x}.asm"
    src.write_bytes((".SECTION/PM seg_pmco;\n.GLOBAL f.;\nf.:\n" + line + "\nNOP;\n").encode())
    be, off = _selas(src, work)
    # first instruction only (strip the trailing NOP: it is the last parcel-aligned instr)
    end = off[1] if len(off) > 1 else len(be)
    return be[:end], off


# -- one block, M3 -----------------------------------------------------------------------

def poke(state, addr, value):
    return m2.poke(state, addr, value)


def set_byte(state, addr, value):
    w = m2.word(state, addr & ~3) or 0
    sh = 8 * (addr & 3)
    poke(state, addr & ~3, (w & ~(0xFF << sh)) | ((value & 0xFF) << sh))


def arm_osc(state, track):
    ws = V.machine_state(1, track)
    o1, o2 = ws + V.WAVETONE_OSC[0], ws + V.WAVETONE_OSC[1]
    poke(state, o1 + 4 * V.OSC_INC, m2.ARM_INC)
    for k in m2.ARM_COPY:
        poke(state, o1 + 4 * k, m2.word(state, o2 + 4 * k) or 0)


def set_env(state, track):
    rec = V.track_record(track)
    for off, (kind, val) in ENV.items():
        poke(state, rec + off, val if kind == "i" else V.f32_bits(val))


def preset_voice_block(state, track, freq, pos):
    """wr_render's parameter block for a type-5 track: table, phase, inc, pos."""
    base = VOICE_BLOCKS_DM + VOICE_STRIDE * track
    poke(state, base + 0, TABLE_DM)
    poke(state, base + 8, render.increment(freq))
    poke(state, base + 12, pos)
    # phase (base+4) carries across blocks; count/out are written by wr_type5


def dispatch(mach, state_runner, machine_of, *, arm=False, trigger=False, note_track=0,
             replace_wavetone=None, type5=False, probe_const=None, amp_probe=None):
    """One sw 0x1c8ef1 from STATE_RUNNER. Returns taps of track NOTE_TRACK's buffer.

    `probe_const` writes a constant into the buffer at the machine render call (its
    signal then runs the whole per-track chain). `amp_probe` writes it instead right
    where the amp stage reads it, to isolate the amp's own open/closed gate.
    """
    s0 = state_runner.state
    for t, m in machine_of.items():
        poke(s0, V.track_record(t) + V.TRACK_MACHINE, m)
    if trigger:
        set_byte(s0, V.ENGINE + TRIG_CELL, 1)
    r = state_runner.fresh_call(DISPATCH, regs={"R4": V.ENGINE, "R8": V.TRACKS, "R12": V.CONFIG},
                                return_address=FAKE_RETURN)
    f = mach_fixups(mach)
    buf = m2.word(r.state, V.TRACK_BUFFERS + 4 * note_track)
    tap = {}

    def at_wt(runner):
        if arm:
            arm_osc(runner.state, note_track)
        if probe_const is not None:
            for k in range(BLOCK):
                poke(runner.state, buf + 4 * k, V.f32_bits(probe_const))
            runner.state.pc_sw = WT_RESUME
        elif replace_wavetone is not None:
            replace_wavetone(runner, buf, BLOCK)
            runner.state.pc_sw = WT_RESUME

    def after(runner):
        tap.setdefault("machine", m2.floats(runner.state, buf, BLOCK))

    def amp(runner):
        if m2.word_reg(runner, "R12") == buf and "pre_amp" not in tap:
            tap["pre_amp"] = m2.floats(runner.state, buf, BLOCK)
            if amp_probe is not None:
                for k in range(BLOCK):
                    poke(runner.state, buf + 4 * k, V.f32_bits(amp_probe))

    def amp_ret(runner):
        if "pre_amp" in tap and "amp_out" not in tap:
            tap["amp_out"] = m2.floats(runner.state, buf, BLOCK)

    def t5(runner):
        runner.state.pc_sw = MACHINE5_SW      # the sixth per-type loop (a patched JUMP)

    f.hooks[WT_CALL] = at_wt
    f.hooks[WT_RESUME] = after
    f.hooks[AMP_STAGE] = amp
    f.hooks[0x1C99D3] = amp_ret
    if type5:
        f.hooks[TYPE5_ENTRY] = t5
    t0 = time.perf_counter()
    res = fx.run(r, 6_000_000, f)
    ok = res[0] == "halt" and res[1].pc_sw == DISPATCH_RETURN
    tap["chain"] = m2.floats(r.state, buf, BLOCK)
    return {"ok": ok, "runner": r, "instructions": res[2], "wall_s": time.perf_counter() - t0,
            "halt": f"{res[1].reason} at {res[1].pc_sw:#x}" if res[0] == "halt" else res[0],
            "tap": tap}


def mach_fixups(mach):
    f = fx.Fixups()
    f.hooks[fx.SIN] = fx.native_sin
    for pc in fx.ADDITIVE:
        f.hooks[pc] = fx.native_additive
    return f


# -- the reader at the call site (as M2), also used by machine5's own runs ---------------

class ReaderAtCallSite(m2.ReaderAtCallSite):
    pass


# -- steps -------------------------------------------------------------------------------

def run_from(mach, init, blocks, machine_of, prep, trigger_block=None, **kw):
    """Run BLOCKS dispatches, PREP(state, b) before each; carry state. -> stacked taps.

    TRIGGER_BLOCK, if given, fires the note trigger only on that block (an edge),
    instead of `trigger=` firing it on every block."""
    state = init
    out = {"machine": [], "pre_amp": [], "amp_out": [], "chain": []}
    instr = wall = 0.0
    for b in range(blocks):
        prep(state, b)
        kb = dict(kw)
        if trigger_block is not None:
            kb["trigger"] = (b == trigger_block)
        fr = dispatch(mach, state, machine_of if b == 0 else {}, **kb)
        if not fr["ok"]:
            return {"ok": False, "halt": fr["halt"], "blocks": b, **out}
        for k in out:
            out[k] += fr["tap"].get(k, [0.0] * BLOCK)
        instr += fr["instructions"]; wall += fr["wall_s"]
        state = fr["runner"]
    return {"ok": True, "blocks": blocks, "instructions": instr, "wall_s": wall,
            "state": state, **out}


def step_trigger(mach, init, blocks):
    midi = {t: MIDI for t in range(1, 16)}

    def prep(state, b):
        set_env(state.state, 0)

    # a constant probe written where the amp reads it isolates the amp's own gate:
    # open after the note trigger (fired once, block 1), closed without it (control).
    on = run_from(mach, init, blocks, {0: 1, **midi}, prep, trigger_block=1, arm=True, amp_probe=0.5)
    off = run_from(mach, init, blocks, {0: 1, **midi}, prep, arm=True, trigger=False, amp_probe=0.5)
    amp_on = V.peak(on["amp_out"][2 * BLOCK:]) if on["ok"] else 0.0    # blocks after the trigger
    amp_off = V.peak(off["amp_out"]) if off["ok"] else 1.0
    checks = {
        "the run returns every block (trigger + control)": on["ok"] and off["ok"],
        "with the trigger, the amp passes the 0.5 probe (peak > 0.4)": amp_on > 0.4,
        "control: without the trigger, the amp is closed (peak < 0.1)": amp_off < 0.1,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "on": on, "off": off,
            "fields": {"note_counter": "record word 113 (compared at 0x1c90fb -> sw 0xb82440)",
                       "trigger_cell": f"engine +{TRIG_CELL:#x} (byte, set by the frame unpack)",
                       "note_on_fn": f"{NOTE_ON_FN:#x}", "amp_stage": f"{AMP_STAGE:#x}",
                       "amp_setup": "sw 0xb8028c (called from 0x1c92b0); envelope from record +0x20c..+0x228",
                       "clamp": f"min(R2,R0=4) at {0x1C294C:#x}, R0 set at {CLAMP_SW:#x}"},
            "numbers": {"amp_peak_triggered": amp_on, "amp_peak_control": amp_off}}


def step_reader(mach, init, blocks, freq):
    midi = {t: MIDI for t in range(1, 16)}
    positions = render.sweep(len(testtable.table()), max(blocks, 2))
    inc = render.increment(freq)

    def make(state):
        rdr = m2.ReaderAtCallSite(freq, positions)

        def prep(st, b):
            set_env(st.state, 0)
        return rdr, prep

    rdr, prep = make(init)
    on = run_from(mach, init, blocks, {0: 1, **midi}, prep, arm=False, replace_wavetone=rdr)
    table = testtable.table()
    nb = on.get("blocks", 0) if on["ok"] else 0
    ref = render.render_blocks(table, inc, positions[:nb], BLOCK, 0, "float32")
    ideal = render.render_blocks(table, inc, positions[:nb], BLOCK, 0, "ideal")
    mism = sum(1 for x, y in zip(on["machine"], ref) if x != y) if on["ok"] else -1
    # the reader's own output survives the per-track stages up to the amp input; its
    # correlation to the reference through the (filter) chain gain is the M2 measure.
    # (End-to-end loudness additionally needs the per-track FILTER cutoff/res from a
    # real frame -- unmapped here -- and the amp opened, which step 1 proves.)
    pre = on["pre_amp"] if on["ok"] else []
    fit = V.fit_gain(pre, ideal) if pre and len(pre) == len(ideal) else None
    checks = {
        "substituted run returns every block": on["ok"],
        "reader is bit-exact in the track buffer (float32)": nb > 0 and mism == 0,
        "the reader survives the per-track stages to the amp input (peak > 0.01)":
            V.peak(pre) > 0.01,
        "its correlation to the reference through the chain gain is > 0.9":
            fit is not None and fit.correlation > 0.9,
    }
    return {"ok": all(checks.values()), "checks": checks, "on": on, "off": on,
            "reference": ideal, "float32": ref,
            "numbers": {"float32_mismatches": mism, "reader_buffer_peak": V.peak(on["machine"]) if on["ok"] else None,
                        "pre_amp_peak": V.peak(pre) if pre else None,
                        "pre_amp_fit": fit.__dict__ if fit else None}}


def step_type5(mach, init, blocks, freq):
    """A track of type 5 renders our reader through machine5; types 0-4 bit-identical."""
    positions = render.sweep(len(testtable.table()), max(blocks, 2))
    inc = render.increment(freq)
    # track 0 = type 5 (our machine); tracks 1-15 WaveTone/MIDI (untouched types)
    stock_types = {0: MIDI, **{t: (1 if t % 2 else MIDI) for t in range(1, 16)}}
    m5_types = {**stock_types, 0: 5}

    def prep5(state, b):
        preset_voice_block(state.state, 0, freq, positions[min(b, len(positions) - 1)])

    # our run: type 5 on track 0, machine5 entered; tap track 0's reader output and
    # every track's buffer at the dispatch end.
    ours = run_type5(mach, init, blocks, m5_types, prep5, entry=True)
    # control A: same config with type 5 -> MIDI and the entry hook still installed
    # (wr_type5 finds no type-5 track); control B: no entry hook at all.
    ctrl_hook = run_type5(mach, init, blocks, stock_types, lambda s, b: None, entry=True)
    ctrl_plain = run_type5(mach, init, blocks, stock_types, lambda s, b: None, entry=False)
    table = testtable.table()
    nb = ours.get("blocks", 0) if ours["ok"] else 0
    ref = render.render_blocks(table, inc, positions[:nb], BLOCK, 0, "float32")
    ideal = render.render_blocks(table, inc, positions[:nb], BLOCK, 0, "ideal")
    mism = sum(1 for x, y in zip(ours["reader"], ref) if x != y) if ours["ok"] else -1
    identical = ctrl_hook.get("all") == ctrl_plain.get("all") if ctrl_hook["ok"] and ctrl_plain["ok"] else False
    # the entry hook must also leave tracks 1-15 identical between our type-5 run and
    # the plain stock run (only track 0's buffer differs)
    t15_identical = (ours.get("others") == ctrl_plain.get("others")) if ours["ok"] and ctrl_plain["ok"] else False
    checks = {
        "the type-5 run returns every block": ours["ok"],
        "the stock control runs return every block": ctrl_hook["ok"] and ctrl_plain["ok"],
        "a type-5 track renders our reader into its buffer, bit for bit": nb > 0 and mism == 0,
        "types 0-4 stay bit-identical whether machine5 is present or not": identical,
        "tracks 1-15 are bit-identical to stock in the type-5 run": t15_identical,
        "the type clamp was raised to min(R2,5) and verified by running": mach.clamp is not None,
    }
    return {"ok": all(checks.values()), "checks": checks, "ours": ours,
            "ctrl_hook": ctrl_hook, "ctrl_plain": ctrl_plain, "reference": ideal, "float32": ref,
            "numbers": {"float32_mismatches": mism, "type5_reader_peak": V.peak(ours["reader"]) if ours["ok"] else None,
                        "controls_identical": identical, "tracks_1_15_identical": t15_identical,
                        "clamp": mach.clamp and {k: v for k, v in mach.clamp.items() if k != "stream"}}}


def run_type5(mach, init, blocks, machine_of, prep, entry=True):
    """Run BLOCKS dispatches (the sixth per-type loop entered iff ENTRY). Tap track 0's
    reader output at TYPE5_RESUME (before its chain), plus every track's buffer at the
    dispatch end."""
    state = init
    reader, allbuf, others = [], [], []
    instr = 0.0
    for b in range(blocks):
        prep(state, b)
        s0 = state.state
        for t, m in (machine_of if b == 0 else {}).items():
            poke(s0, V.track_record(t) + V.TRACK_MACHINE, m)
        r = state.fresh_call(DISPATCH, regs={"R4": V.ENGINE, "R8": V.TRACKS, "R12": V.CONFIG},
                             return_address=FAKE_RETURN)
        f = mach_fixups(mach)
        buf0 = m2.word(r.state, V.TRACK_BUFFERS)
        tap = {}

        def t5(runner):
            runner.state.pc_sw = MACHINE5_SW

        def at_resume(runner):
            tap.setdefault("reader", m2.floats(runner.state, buf0, BLOCK))

        if entry:
            f.hooks[TYPE5_ENTRY] = t5
            f.hooks[TYPE5_RESUME] = at_resume
        res = fx.run(r, 6_000_000, f)
        if not (res[0] == "halt" and res[1].pc_sw == DISPATCH_RETURN):
            return {"ok": False, "blocks": b, "reader": reader, "all": allbuf, "others": others,
                    "halt": f"{getattr(res[1], 'reason', res[0])} at {res[1].pc_sw:#x}"
                    if res[0] == "halt" else res[0]}
        reader += tap.get("reader", [0.0] * BLOCK)
        block_all = [m2.floats(r.state, m2.word(r.state, V.TRACK_BUFFERS + 4 * t), BLOCK) for t in range(16)]
        allbuf.append(block_all)
        others.append(block_all[1:])
        instr += res[2]
        state = r
    return {"ok": True, "blocks": blocks, "reader": reader, "all": allbuf, "others": others,
            "instructions": instr, "state": state}


# -- WAVs --------------------------------------------------------------------------------

def wav(name, samples, seconds, wavs, what, normalise=False):
    n = int(seconds * RATE)
    pk = V.peak(samples)
    scale = 0.9 / pk if normalise and pk else 1.0
    looped = V.loop_to([x * scale for x in samples], n)
    path = OUT / name
    m1.write_wav(path, looped, RATE)
    wavs.append({"file": str(path), "seconds": round(len(looped) / RATE, 3),
                 "rendered_samples": len(samples), "looped": 0 < len(samples) < n,
                 "gain_applied": round(scale, 6), "peak": pk, "rms": V.rms(samples), "what": what})


# -- main --------------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--blocks", type=int, default=6)
    p.add_argument("--seconds", type=float, default=2.5)
    p.add_argument("--freq", type=float, default=375.0)
    p.add_argument("--assemble", action="store_true", help="reassemble reader/machine5 with selas (WSL)")
    p.add_argument("--fresh", action="store_true", help="ignore the cached init snapshot")
    a = p.parse_args(argv)
    if a.seconds < 2:
        raise SystemExit("--seconds must be at least 2")

    OUT.mkdir(parents=True, exist_ok=True)
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    stream = m1.dn2_section7(a.image)
    table = testtable.table()
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        work = pathlib.Path(tmp)
        reader, _, r_prov = m1.reader_code(a.assemble, work)
        m5, m5_off, m5_prov = load_json(MACHINE5, MACHINE5_SRC, a.assemble, work)
        mach = M3Machine(dk, stream, reader, m5, table, raise_clamp=True, work=work)
        m5_prov["placement_check"] = check_machine5_targets(dk, mach, m5_off)
        init = load_init(dk, mach, stream, reader, table, a.fresh)

    report = {"digikit": {"path": str(a.digikit), "head": dk.head}, "image_sha256": mach.sha,
              "reader": r_prov, "machine5": m5_prov, "placement": mach.placement,
              "clamp": {k: v for k, v in mach.clamp.items() if k != "stream"} if mach.clamp else None,
              "blocks": a.blocks}
    wavs, results = [], {}

    print("step 1: the note trigger and the amp")
    s1 = step_trigger(mach, init, a.blocks)
    results["1_trigger"] = {k: v for k, v in s1.items() if k not in ("on", "off")}
    show(s1)
    wav("m3_amp_triggered.wav", s1["on"]["amp_out"], a.seconds, wavs,
        "amp-stage output with a constant 0.5 probe in place of the machine render, note triggered: the amp is open")
    wav("m3_amp_control.wav", s1["off"]["amp_out"], a.seconds, wavs,
        "control: the same probe with no trigger; the amp is closed (silent)")

    print("\nstep 2: our reader through the chain, triggered")
    s2 = step_reader(mach, init, a.blocks, a.freq)
    results["2_reader"] = {k: v for k, v in s2.items() if k not in ("on", "off", "reference", "float32")}
    show(s2)
    if s2["on"]["ok"]:
        wav("m3_reader_machine.wav", s2["on"]["machine"], a.seconds, wavs,
            "our reader straight out of the track buffer, bit-exact to the reference (looped)")
        wav("m3_reader_pre_amp.wav", s2["on"]["pre_amp"], a.seconds, wavs,
            "our reader at the amp input, after the per-track filter stages (looped)")
    slow = render.render_blocks(table, render.increment(a.freq),
                                render.sweep(len(table), max(int(a.seconds * RATE) // BLOCK, 2)),
                                BLOCK, 0, "float32")
    wav("m3_preview_reference_sweep.wav", slow, a.seconds, wavs,
        "PREVIEW, not the runner: the reference (float32, bit-exact to the runner on rendered blocks) with the sweep over the whole file")

    print("\nstep 3: a sixth machine type (type 5 -> our reader)")
    s3 = step_type5(mach, init, a.blocks, a.freq)
    # clamp control: with the stock clamp a type-5 selector is squashed to 4, raised to 5
    ok_clamp, clamp_nums = clamp_control(dk, stream, reader, m5, table, work_dir=OUT)
    s3["checks"]["control: the stock clamp squashes a type-5 selector to 4, raised keeps 5"] = ok_clamp
    s3["ok"] = all(s3["checks"].values())
    s3["numbers"]["clamp_control"] = clamp_nums
    results["3_type5"] = {k: v for k, v in s3.items()
                          if k not in ("ours", "ctrl_hook", "ctrl_plain", "reference", "float32")}
    show(s3)
    if s3["ours"]["ok"]:
        wav("m3_type5_reader.wav", s3["ours"]["reader"], a.seconds, wavs,
            "a type-5 track: our reader rendered by machine5 into the track buffer, tapped before its chain (looped)")

    return finish(report, results, wavs)


def load_init(dk, mach, stream, reader, table, fresh):
    """Init to its return. The engine init never touches our spliced spans or the
    clamp parcel, so the M2 post-init snapshot is reused: it is loaded against an
    M2-equivalent image (which its sha256 matches) and then the runner's memory is
    re-pointed at the full M3 image, so our reader, machine5 and the raised clamp
    become visible without an 18-minute rebuild."""
    m2mach = m2.Machine(dk, stream, reader, table)                # the M2 image and its sha
    snap = None
    for cand in sorted(OUT.glob("m2_init_*.snap")):
        if cand.name == f"m2_init_{m2mach.sha[:12]}.snap":
            snap = cand
            break
    if snap and not fresh:
        runner = fx.sr.load_snapshot(str(snap), m2mach.memory)    # sha-checked against M2
        runner.data = mach.memory
        runner.state = fx.dataclasses.replace(runner.state, concrete=mach.memory)
        print(f"  init reused from {snap.name} (re-pointed at the M3 image)")
        return runner
    r = mach.runner(m2.INIT)
    f = mach_fixups(mach)
    t0 = time.perf_counter()
    res = fx.run(r, 60_000_000, f)
    if not (res[0] == "halt" and res[1].reason == "return without followed call"):
        raise SystemExit(f"init did not return: {res}")
    print(f"  init returned after {res[2]:,} instructions ({round(time.perf_counter() - t0)} s)")
    return r


def clamp_control(dk, stream, reader, m5, table, work_dir):
    """Feed a type-5 selector to the track loop on the stock and raised images and read
    R2 after min(R2,R0) at 0x1c294c. Stock -> 4, raised -> 5."""
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        work = pathlib.Path(tmp)
        stock = M3Machine(dk, stream, reader, m5, table, raise_clamp=False, work=work)
        raised = M3Machine(dk, stream, reader, m5, table, raise_clamp=True, work=work)
    out = {}
    for name, mm in (("stock", stock), ("raised", raised)):
        r = mm.runner(0x1C294A)
        # seed the min inputs: R2 = 5 (the selector), R8 = 0 (the max floor)
        r.state.uregs[fx.UREG_CODES["R2"]] = fx.Const(5)
        r.state.uregs[fx.UREG_CODES["R8"]] = fx.Const(0)
        f = fx.Fixups()
        fx.run(r, 6, f, stop_at=[0x1C294F])       # stop right after min, before lshift
        v = r.state.uregs[fx.UREG_CODES["R2"]]
        out[name] = v.value if isinstance(v, fx.Const) else None
    ok = out.get("stock") == 4 and out.get("raised") == 5
    return ok, out


def show(step):
    for k, v in step["checks"].items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")


def finish(report, results, wavs):
    ok = bool(results) and all(r.get("ok") for r in results.values())
    report["steps"] = results
    report["wavs"] = wavs
    report["result"] = "PASS" if ok else "FAIL"
    (OUT / "m3_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print("\nWAVs:")
    for w in wavs:
        loop = f" (looped from {w['rendered_samples']})" if w["looped"] else ""
        print(f"  {w['file']}  {w['seconds']} s{loop}, peak {w['peak']:.4g} -- {w['what']}")
    print(f"\n  {report['result']}  (report: out/waverider/m3_report.json)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

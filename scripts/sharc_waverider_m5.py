"""The section 7 a flashable build ships, run in the SHARC runner (offline; Waverider M5 began it).

    python scripts/sharc_waverider_m5.py \\
        --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \\
        --digikit D:/01_Code/Z_Personal/digikit-wt-sharcemu \\
        [--blocks 8] [--frame FILE | --frame-be FILE | --frames PATTERN]

The image is `dnfw.waverider.dsp.section7(stock)` -- byte for byte what the mod
applies -- and nothing is poked or redirected: the type-5 loop is entered by the JUMP
in the image, and every voice parameter arrives through a 2,688-byte frame image run
through the firmware's own per-block routine `sw 0x1c2712` (frame unpack, slot
dispatch, per-track chain), as Milestone 4 does. Steps, each PASS/FAIL
(`docs/waverider-m5-dsp.md`):

1. **decode** -- the section 7 is the builder's; every instruction of our code (PERC in
   L2 included) reads the same to digikit's decoder and to selache's `selmap` as its
   source line says, on the assembler's boundaries; the entry decodes as a 48-bit jump.
2. **map** -- frame words land where the machines read them, the trig note in the note
   cell; a type-5 frame reaches record +0x1b4 as 5 (control: without the lookup patch it
   is squashed to 0); every span we add (L1 and L2) reads back as the image put it.
3. **PERC** (docs/perc.md) -- at PERC's entry every block, `dnfw.perc.program` is run on
   the DSP's own memory; every type-5 track's buffer and voice state when PERC hands on
   must be bit-exact to it. All 24 machines (eight tracks at a time), pitch, retrigger,
   TYPE turned mid-note, every parameter at its top and bottom, silence without a note.
4. **stock** -- types 0-4 are bit-identical: the same frames with no type-5 track on
   the modded and the stock image give identical buffers on all 16 tracks, and in a
   type-5 run tracks 1-15 match a stock run; the stock filter types likewise.
5. **frame** (with --frame/--frame-be/--frames) -- a caller's frame(s), used verbatim
   every block; every type-5 track bit-exact to the model.
6-7. **PING, SHFT, GRAN** -- removed (SHFT, GRAN v0.27; PING v0.45); their step functions are kept only where shared.
8. **The Monomachine machines** (v0.26) -- bit-exact to PERC's program, as PERC's voice.

Every step writes WAVs under out/waverider/m5_*.wav (48 kHz, 16-bit mono, >= 2 s).
Runner blocks are short, so a WAV made of them is LOOPED and says so.
`m5_report.json` has the numbers. Exit 0 when
every step passes.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import glob
import hashlib
import json
import math
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_dn2_fixups as fx                                  # noqa: E402
import sharc_waverider_m3 as m3                                # noqa: E402
import sharc_waverider_m4 as m4
from dnfw import voices as VOICES                                # noqa: E402
import sharc_waverider_render as m1                            # noqa: E402
import sharc_waverider_voice as m2                             # noqa: E402
from dnfw.image import bootstream, sharc_object                # noqa: E402
from dnfw.waverider import dsp, testtable                       # noqa: E402
from dnfw.perc import live as PL                                # noqa: E402
from dnfw.perc import machines as PM                            # noqa: E402
from dnfw.perc import program as PP                             # noqa: E402
from dnfw.sampler import live as SL                             # noqa: E402
from dnfw.sampler import machines as SM                         # noqa: E402
from dnfw.sampler import program as SP                          # noqa: E402
from dnfw.md import core as MDK                                 # noqa: E402
from dnfw.waverider import frame as FR                         # noqa: E402
from dnfw.waverider import voice as V                          # noqa: E402
from dnfw.fascia import program as FSP                          # noqa: E402  (v0.45: FASCIA's DSP program)
from dnfw.fascia import machines as FSM                         # noqa: E402

OUT = ROOT / "out" / "waverider"
SHARC = ROOT / "csrc" / "waverider" / "sharc"
RATE, BLOCK = 48000, 32
LOOP_RESUME = 0x1C944C          # where the chain after PERC (RESONATOR, CZ, PING) rejoins the per-track chain
AMP_RETURN = 0x1C99D3
SETUP_GUARD, SETUP_TABLE_READ, SETUP_NONE = 0x1C905D, 0x1C90A9, 0x1C90D4
CLAMP_MIN = 0x1C294C
NOTE_CELL = V.ENGINE + 0x1387C
WAV1, TBL1 = 26, 27             # WaveTone's Osc1 Waveform, Osc1 Wave Table
DRIF = 38                       # W5: WaveTone's Osc Drift, TBL on Waverider's page
TRIG_WORD = 0x25C4AC            # W5: the frame copy's word holding TRIG_NOTE (offset 34), high half
TUN1 = 25                       # WaveTone's Osc1 Tune (Milestone 6)
TUN1_ZERO = 0x4000              # the frame word for 0 semitones: the sound's own (probe, 2026-09-30)
FRAME_COPY = 0x25C48C           # where sw 0x1c2712 copies the frame image
PERC_L = PL.layout()            # where the build puts PERC (dnfw.waverider.dsp)
SMP_L = SL.layout()             # and the sample machines (v0.13)
SMP_RENDERED = tuple(SM.TYPE_OF[n] for n in SM.ENGINED)
FSC_L = FSP.layout()            # v0.45: and FASCIA


def fsc_base(t: int) -> int:
    """a FASCIA voice's state (dnfw.fascia.program.vbase)"""
    return (FSC_L.state if t < 8 else FSC_L.state2) + FSP.STRIDE * (t & 7)


# -- the machine ------------------------------------------------------------------------------

class Image:
    def __init__(self, dk, stream: bytes):
        self.stream = stream
        self.memory = dk.ldr.LoadedMemory.from_stream(stream)
        self.sha = hashlib.sha256(stream).hexdigest()


def snapshot_path(dk, stock: bytes, work: pathlib.Path) -> pathlib.Path:
    reader, _, _ = m1.reader_code(False, work)
    m2mach = m2.Machine(dk, stock, reader, testtable.table())
    snap = OUT / f"m2_init_{m2mach.sha[:12]}.snap"
    if not snap.exists():
        raise SystemExit(f"{snap.name} missing: run scripts/sharc_waverider_voice.py once "
                         "(it builds and caches the engine-init snapshot, ~18 min)")
    return snap, m2mach


def init_on(snap, m2mach, image: Image, warm: bool = False):
    """The Milestone 2 post-init snapshot, re-pointed at IMAGE (engine init never
    touches the spans we add or the two words we patch; step 2 checks the spans)."""
    runner = fx.sr.load_snapshot(str(snap), m2mach.memory)
    runner.data = image.memory
    runner.state = dataclasses.replace(runner.state, concrete=image.memory)
    # v0.17: the build ships an empty pool; the test sounds go in as the ColdFire's loader
    # would put samples there
    # (v0.19: BEAT with sixteen slices of its own, for SLICE)
    beat = len(SL.test_samples()[3])
    pool = SL.pool_bytes(SL.test_samples(), dsp.SMP_POOL_DDR, SL.test_rates(), SL.test_fmts(),
                         SL.TEST_NAMES, [(), (), (), [(beat * k // 16, beat * (k + 1) // 16, beat * k // 16)
                                                      for k in range(16)]])
    for k in range(0, len(pool), 4):
        m2.poke(runner.state, dsp.SMP_POOL_DDR + k, struct.unpack_from("<I", pool, k)[0])
    # v0.26: the tables the ColdFire sends over the link at power-on (the host's pitch table
    # and zpack, at the pool's table area), then the word that says they are whole
    Lm = PL.layout().md
    shipped = MDK.tables_bytes()
    for k in range(0, len(shipped), 4):
        m2.poke(runner.state, Lm.T[MDK.SHIPPED] + k, struct.unpack_from("<I", shipped, k)[0])
    m2.poke(runner.state, Lm.ready, SM.TABLE_MAGIC)
    if warm:
        # v0.17: the Machinedrum's sine and tables as the DSP has them 0.7 s after power-on
        # (it fills them itself, 32 blocks; the "sine" run checks that fill word for word),
        # so the machines' runs hear them from their first note
        from dnfw.md import bench as MDB
        L = PL.layout().md
        for a, w in MDB.table_mem(L).items():
            if L.tables <= a < L.T[MDK.SHIPPED]:
                m2.poke(runner.state, a, w)
        m2.poke(runner.state, L.C["fill"], MDK.Z_N)
        # v0.26: and the Digibank stand-in DENS and DDRW read, built (8 s after the tables)
        from dnfw.mnm import dpro as MNP
        for a, w in MNP.bench_words(L.mnm).items():
            m2.poke(runner.state, a, w)
    return runner


def fixups(hooks=None) -> fx.Fixups:
    return m4.fixups(hooks)


# -- frames --------------------------------------------------------------------------------------

def base_frame(sound, machines, *, t0=5, others=None, overrides=None, note=0x3C00,
               trigger=False, trigger_others=False) -> FR.Frame:
    """Track 0 on machine T0 with WaveTone's machine page (group 1) plus OVERRIDES;
    OTHERS = {track: machine type} for tracks 1-15 (default MIDI)."""
    # machines' defaults are the sound's scale, which is what the instrument's frame
    # carries (read through the USB probe, 2026-09-30)
    track0 = {**machines.get(1, {}), TUN1: TUN1_ZERO, **(overrides or {})}
    f = FR.init_frame(sound, t0, trigger=trigger, track0=track0)
    f.header(FR.NOTE, 0, note)
    for t, m in (others or {}).items():
        f.header(FR.MACHINE, t, m)
        f.sound(t, machines.get(m, {}) if m in machines else {})
        if trigger and trigger_others:
            f.trigger(t)
    return f


def swap16(data: bytes) -> bytes:
    out = bytearray(data)
    out[0::2], out[1::2] = data[1::2], data[0::2]
    return bytes(out)


def load_frames(a) -> list[bytes] | None:
    if a.frame:
        return [pathlib.Path(a.frame).read_bytes()]
    if a.frame_be:
        return [swap16(pathlib.Path(a.frame_be).read_bytes())]
    if a.frames:
        return [pathlib.Path(p).read_bytes() for p in sorted(glob.glob(a.frames))]
    return None


# -- running blocks ------------------------------------------------------------------------------

def run_blocks(init, frames, blocks: int, extra_hooks=None):
    """BLOCKS calls of sw 0x1c2712, FRAMES(b) -> frame bytes. Records, per block: every
    track buffer after the type-5 loop (at 0x1c944c) and at the end of the dispatch;
    track 0 at the amp's input and output; each type-5 track's inputs as the DSP holds
    them at PERC's entry, PERC's output and state against the model's (dnfw.perc.program
    run on the DSP's memory at that entry); loop entries."""
    state = init
    out = {"machine": [], "amp_in": [], "amp_out": [], "buffers": [], "buffer_bits": [], "t5_inputs": [],
           "perc": [], "smp": [], "fsc": [], "loop_entries": 0, "smp_entries": 0, "fsc_entries": 0,
           "setup": []}
    instr = wall = 0
    for b in range(blocks):
        tap = {}

        def at_dispatch(r):
            tap["bufs"] = [m2.word(r.state, V.TRACK_BUFFERS + 4 * t) for t in range(16)]

        def at_loop(r):
            # PERC's entry: each type-5 track's inputs, and the model (dnfw.perc.program,
            # the same program as the assembled code) run on the DSP's memory as it is here
            out["loop_entries"] += 1
            ins, model = {}, {}
            # wr_perc first fills more of the Machinedrum's sine and tables (until whole):
            # the model does the same on the memory here before its voices run
            from dnfw.perc.dsl import Mem as _Mem, Prog as _Prog
            st0 = r.state
            filled = _Mem(lambda a, st0=st0: m2.word(st0, a) or 0)
            fp = _Prog("run", mem=filled)
            fp.spill = PERC_L.md.C["ash"]
            MDK.table_fill(fp, PERC_L.md)
            from dnfw.mnm import dpro as MNP           # v0.26: and the Digibank stand-in's build
            MNP.build(fp, PERC_L.md.mnm)
            filled.put(PERC_L.C["mcost"], 0)           # and the Monomachine voices' cost, carried slot to slot
            PP.mnm_ages(fp, PERC_L)                    # v0.29: and their ages (the newest first)
            for t in range(16):
                rec = V.track_record(t)
                if (m2.word(r.state, rec + V.TRACK_MACHINE) == 5
                        and frame_word(r.state, FR.header_offset(FR.MACHINE, t))
                        in (PP.MACHINE_TYPE, *PP.MNM_TYPES)):         # v0.26: and the Monomachine's
                    ins[t] = {"note": V.bits_f32(m2.word(r.state, NOTE_CELL + 4 * t) or 0),
                              "trig": bool(((m2.word(r.state, TRIG_WORD) or 0) >> 16) & (1 << t)),
                              "type": frame_word(r.state, FR.slot_offset(t, PM.TYPE_REC[1])),
                              "params": [frame_word(r.state, FR.slot_offset(t, slot))
                                         for _rid, slot, _lo, _top in PM.PARAMS]}
                    st = r.state
                    if filled.get(PERC_L.md.C["fill"]) < MDK.Z_N:
                        # v0.26: wr_perc runs no voice until the tables are whole (perc.program):
                        # the slot's buffer and state stay as they are
                        buf = m2.word(st, PP.BUFFERS + 4 * t) or 0
                        model[t] = {"out": [filled.get(buf + 4 * k) for k in range(BLOCK)],
                                    "state": [filled.get(PERC_L.state + 128 * t + 4 * k)
                                              for k in range(PM.STATE_WORDS)],
                                    "steps": 0}
                        continue
                    p, mem = PP.run_voice(PERC_L, filled.get, t)
                    filled.put(PERC_L.C["mcost"], mem.get(PERC_L.C["mcost"]))
                    buf = m2.word(st, PP.BUFFERS + 4 * t) or 0
                    model[t] = {"out": [mem.get(buf + 4 * k) for k in range(BLOCK)],
                                "state": [mem.get(PERC_L.state + 128 * t + 4 * k)
                                          for k in range(PM.STATE_WORDS)],
                                "steps": p.steps}
            tap["t5_inputs"] = ins
            tap["perc_model"] = model

        def at_after_perc(r):
            # the sample machines' entry, PERC's tail: what PERC left in each type-5
            # track's buffer and state; then the sample machines' model (dnfw.sampler.program
            # run on the DSP's memory here) for every track on a rendered sample machine
            if "perc_dsp" in tap:
                return
            tap["perc_dsp"] = {t: {"out": [m2.word(r.state, tap["bufs"][t] + 4 * k) or 0 for k in range(BLOCK)],
                                   "state": [m2.word(r.state, PERC_L.state + 128 * t + 4 * k) or 0
                                             for k in range(PM.STATE_WORDS)]}
                               for t in tap.get("perc_model", {})}
            out["smp_entries"] += 1
            model = {}
            for t in range(16):
                ty = frame_word(r.state, FR.header_offset(FR.MACHINE, t))
                if ty in SMP_RENDERED:
                    st = r.state
                    p, mem = SP.run_voice(SMP_L, lambda a, st=st: m2.word(st, a) or 0, t, ty)
                    buf = m2.word(st, PP.BUFFERS + 4 * t) or 0
                    model[t] = {"type": ty, "out": [mem.get(buf + 4 * k) for k in range(BLOCK)],
                                "state": [mem.get(SMP_L.state + SP.STATE_STRIDE * t + 4 * k)
                                          for k in range(SP.STATE_STRIDE // 4)],
                                "steps": p.steps}
            tap["smp_model"] = model

        def at_after_smp(r):
            # RESONATOR's entry, the sample machines' tail
            if "smp_dsp" in tap:
                return
            tap["smp_dsp"] = {t: {"out": [m2.word(r.state, tap["bufs"][t] + 4 * k) or 0 for k in range(BLOCK)],
                                  "state": [m2.word(r.state, SMP_L.state + SP.STATE_STRIDE * t + 4 * k) or 0
                                            for k in range(SP.STATE_STRIDE // 4)]}
                              for t in tap.get("smp_model", {})}

        def at_fsc(r):
            # v0.45: FASCIA's entry, smp.asm's tail: the sample machines' outputs (as before at
            # PING_SW), then FASCIA's model (dnfw.fascia.program run on the DSP's memory here) for
            # every type-18 slot, in the order the DSP walks them (PERC's ORDER: the newest first)
            at_after_smp(r)
            if "fsc_model" in tap:
                return
            out["fsc_entries"] += 1
            from dnfw.perc.dsl import Mem as _Mem
            st = r.state
            mem = _Mem(lambda a, st=st: m2.word(st, a) or 0)
            order = [(m2.word(st, PP.ORDER + 4 * k) or 0) & 15 for k in range(16)]
            model = {}
            for t in order:
                if t in model or frame_word(st, FR.header_offset(FR.MACHINE, t)) != FSM.TYPE:
                    continue
                p_, mem = FSP.run_voice(FSC_L, None, t, mem)
                buf = m2.word(st, PP.BUFFERS + 4 * t) or 0
                model[t] = {"out": [mem.get(buf + 4 * k) for k in range(BLOCK)],
                            "state": [mem.get(fsc_base(t) + 4 * k) for k in range(FSP.VOICE_WORDS)],
                            "steps": p_.steps}
            tap["fsc_model"] = model

        def at_after_fsc(r):
            # the shared tail's entry, FASCIA's tail: what FASCIA left in each of its slots
            if "fsc_dsp" in tap:
                return
            tap["fsc_dsp"] = {t: {"out": [m2.word(r.state, tap["bufs"][t] + 4 * k) or 0 for k in range(BLOCK)],
                                  "state": [m2.word(r.state, fsc_base(t) + 4 * k) or 0
                                            for k in range(FSP.VOICE_WORDS)]}
                              for t in tap.get("fsc_model", {})}

        def at_resume(r):
            tap["machine"] = [m2.floats(r.state, tap["bufs"][t], BLOCK) for t in range(16)]

        def amp(r):
            if m2.word_reg(r, "R12") == tap["bufs"][0] and "amp_in" not in tap:
                tap["amp_in"] = m2.floats(r.state, tap["bufs"][0], BLOCK)

        def amp_ret(r):
            if "amp_in" in tap and "amp_out" not in tap:
                tap["amp_out"] = m2.floats(r.state, tap["bufs"][0], BLOCK)

        def guard(r):
            out["setup"].append(("guard", b, m2.word_reg(r, "R2")))

        def table_read(r):
            out["setup"].append(("table", b, m2.word_reg(r, "M4")))

        def none_arm(r):
            out["setup"].append(("none-arm", b, None))

        hooks = {m3.DISPATCH: at_dispatch, dsp.PERC_SW: at_loop, dsp.SMP_SW: at_after_perc,
                 dsp.FSC_SW: at_fsc, dsp.PING_SW: at_after_fsc,
                 LOOP_RESUME: at_resume,
                 m3.AMP_STAGE: amp, AMP_RETURN: amp_ret, SETUP_GUARD: guard,
                 SETUP_TABLE_READ: table_read, SETUP_NONE: none_arm}
        for k, fn in (extra_hooks or {}).items():
            if k in hooks:                      # both: ours first, then the step's
                hooks[k] = (lambda f0, f1: lambda r: (f0(r), f1(r)))(hooks[k], fn)
            else:
                hooks[k] = fn
        f = fixups(hooks)
        r = m4.unpack_call(state, frames(b))
        t0 = time.perf_counter()
        res = fx.run(r, 8_000_000, f)
        wall += time.perf_counter() - t0
        if not (res[0] == "halt" and res[1].pc_sw == m4.UNPACK_RETURN):
            halt = f"{res[1].reason} at {res[1].pc_sw:#x}" if res[0] == "halt" else f"{res[0]} at {res[1]:#x}"
            return {**out, "ok": False, "blocks": b, "halt": halt}
        out["machine"].append(tap.get("machine"))
        out["amp_in"] += tap.get("amp_in", [0.0] * BLOCK)
        out["amp_out"] += tap.get("amp_out", [0.0] * BLOCK)
        out["buffers"].append([m2.floats(r.state, tap["bufs"][t], BLOCK) for t in range(16)])
        out["buffer_bits"].append([[m2.word(r.state, tap["bufs"][t] + 4 * k) for k in range(BLOCK)]
                                   for t in range(16)])
        out["t5_inputs"].append(tap.get("t5_inputs", {}))
        model, got = tap.get("perc_model", {}), tap.get("perc_dsp", {})
        out["perc"].append({t: {"out_mismatches": sum(1 for x, y in zip(model[t]["out"], got.get(t, {}).get("out", [])) if x != y)
                                + (0 if t in got else BLOCK),
                                "state_mismatches": sum(1 for x, y in zip(model[t]["state"], got.get(t, {}).get("state", [])) if x != y)
                                + (0 if t in got else PM.STATE_WORDS),
                                "out": [V.bits_f32(x) for x in got.get(t, {}).get("out", [])],
                                "model_steps": model[t]["steps"]} for t in model})
        model, got = tap.get("smp_model", {}), tap.get("smp_dsp", {})
        out["smp"].append({t: {"type": model[t]["type"],
                               "out_mismatches": sum(1 for x, y in zip(model[t]["out"], got.get(t, {}).get("out", [])) if x != y)
                               + (0 if t in got else BLOCK),
                               "state_mismatches": sum(1 for x, y in zip(model[t]["state"], got.get(t, {}).get("state", [])) if x != y)
                               + (0 if t in got else SP.STATE_STRIDE // 4),
                               "out": [V.bits_f32(x) for x in got.get(t, {}).get("out", [])],
                               "model_steps": model[t]["steps"]} for t in model})
        model, got = tap.get("fsc_model", {}), tap.get("fsc_dsp", {})
        out["fsc"].append({t: {"out_mismatches": sum(1 for x, y in zip(model[t]["out"], got.get(t, {}).get("out", [])) if x != y)
                               + (0 if t in got else BLOCK),
                               "state_mismatches": sum(1 for x, y in zip(model[t]["state"], got.get(t, {}).get("state", [])) if x != y)
                               + (0 if t in got else FSP.VOICE_WORDS),
                               "out": [V.bits_f32(x) for x in got.get(t, {}).get("out", [])],
                               "bits": list(got.get(t, {}).get("out", [])),
                               "model_steps": model[t]["steps"]} for t in model})
        instr += res[2]
        state = r
    return {**out, "ok": True, "blocks": blocks, "instructions": instr, "wall_s": round(wall, 1),
            "state": state}


def frame_word(state, offset: int) -> int:
    """The 16-bit word at OFFSET of the frame copy the unpack made."""
    a = FRAME_COPY + offset
    w = m2.word(state, a & ~3) or 0
    return (w >> 16) & 0xFFFF if a & 2 else w & 0xFFFF


def track_series(run, t) -> list[float]:
    return [x for blk in run["machine"] if blk for x in blk[t]]


def mismatches(a, b) -> int:
    if len(a) != len(b):
        return -1
    return sum(1 for x, y in zip(a, b) if x != y)


def zero_crossings(s) -> int:
    return sum(1 for a, b in zip(s, s[1:]) if (a < 0) != (b < 0))


# -- step 1: decode --------------------------------------------------------------------------------

def norm(text: str) -> str:
    t = text.split("//", 1)[0].strip().rstrip(";").lower()
    t = re.sub(r"\bf(\d+)\b", r"r\1", t)
    t = re.sub(r"(?<![\w.])(-?)(\d+)\b(?!x)", lambda m: f"{m.group(1)}0x{int(m.group(2)):x}", t)
    t = re.sub(r"0x0*([0-9a-f]+)", r"0x\1", t)
    # an absolute DDR address the assembler takes signed (DM(-0x7c000000)) and selmap prints
    # unsigned (dm (0x84000000)): one 32-bit address either way
    t = re.sub(r"dm\((\s*)-0x([0-9a-f]{7,8})\)",
               lambda m: f"dm({(-int(m.group(2), 16)) & 0xFFFFFFFF:#x})", t)
    return re.sub(r"\s+", "", t)


def selmap_text(code: bytes, work: pathlib.Path) -> dict[int, tuple[int, str]]:
    blob = work / "walk.bin"
    blob.write_bytes(code)
    r = m1._wsl(f"{m1.SELMAP} < {m1._wsl_path(blob)}\n", work)
    out = {}
    for line in r.stdout.splitlines():
        p = line.split("\t", 2)
        if len(p) == 3:
            out[int(p[0])] = (int(p[1]), p[2])
    return out


def perc_links_ok() -> bool:
    """PERC: the block counter's jump into wr_perc (L2), wr_perc's tail into smp.asm's
    wr_smp, its tail into fascia.asm's wr_fsc (v0.45), and FASCIA's into ping.asm's shared tail
    (v0.26: RESONATOR and CZ gone): addresses, not labels."""
    count = (SHARC / "block_count.asm").read_text(encoding="utf-8")
    perc = (SHARC / "perc.asm").read_text(encoding="utf-8")
    return (f"JUMP {dsp.PERC_SW:#x};" in count
            and re.findall(r"JUMP (0x[0-9a-f]+);\s*// smp.asm's wr_smp", perc) == [f"{dsp.SMP_SW:#x}"]
            # v0.45: smp.asm's tail into fascia.asm's wr_fsc, and FASCIA's into the shared tail
            and re.findall(r"JUMP (0x[0-9a-f]+);\s*// fascia.asm's wr_fsc",
                           (SHARC / "smp.asm").read_text(encoding="utf-8")) == [f"{dsp.FSC_SW:#x}"]
            and re.findall(r"JUMP (0x[0-9a-f]+);\s*// the shared tail",
                           (SHARC / "fascia.asm").read_text(encoding="utf-8")) == [f"{dsp.PING_SW:#x}"])


def no_gran_link() -> bool:
    """v0.28: GRAN and SHFT removed: nothing in ping.asm jumps to their former code."""
    ping = (SHARC / "ping.asm").read_text(encoding="utf-8")
    return f"JUMP {dsp.GRAN_SW:#x};" not in ping and "wr_gran" not in ping and "wr_s_track" not in ping


def gran_links_ok() -> bool:
    """GRAN: ping.asm's jump into wr_gran, and wr_gran's back to ping's wr_p_next."""
    import sharc_resolve_jumps as R                      # noqa: PLC0415
    ping = (SHARC / "ping.asm").read_text(encoding="utf-8")
    spec = json.loads((SHARC / "ping.json").read_text(encoding="utf-8"))
    nxt = dsp.PING_SW + spec["instruction_offsets"][R.labels(ping)["wr_p_next"]] // 2
    g = (SHARC / "gran.asm").read_text(encoding="utf-8")
    back = re.compile(r"JUMP (0x[0-9a-f]+);\s*// ping.asm's wr_p_next")
    return (f"IF EQ JUMP {dsp.GRAN_SW:#x};" in ping
            and [int(x, 16) for x in back.findall(g)] == [nxt])


def decode_check(dk, image: Image, work: pathlib.Path, use_selmap: bool) -> dict:
    res = {}
    for name, load_sw in (("perc", dsp.PERC_SW), ("smp", dsp.SMP_SW), ("block_count", dsp.COUNT_SW),
                          ("ping", dsp.PING_SW), ("fascia", dsp.FSC_SW)):  # v0.28: GRAN removed; v0.45: FASCIA
        spec = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
        code = sharc_object.load_bytes(bytes.fromhex(spec["object_parcels_be"]))
        lines = [ln for ln in (SHARC / f"{name}.asm").read_text(encoding="utf-8").splitlines()
                 if (t := ln.split("//", 1)[0].strip()) and not t.startswith(".") and not t.endswith(":")]
        offsets = spec["instruction_offsets"]
        sel = selmap_text(code, work) if use_selmap else {}
        bad = []
        for k, off in enumerate(offsets):
            end = offsets[k + 1] if k + 1 < len(offsets) else len(code)
            insn = dk.st.decode_at(image.memory, None, load_sw + off // 2)
            if insn.kind in ("unknown", "uncertain") or (insn.length_bytes or 0) != end - off:
                bad.append(f"+{off} digikit {insn.type_name}/{insn.length_bytes} vs {end - off}")
            if use_selmap:
                n, text = sel.get(off, (0, "?"))
                want = norm(lines[k])
                got = norm(text)
                if "do" in want and "until" in want:
                    same = got.startswith(want.split("do")[0] + "do")
                else:
                    same = got == want
                if n != end - off or not same:
                    bad.append(f"+{off} selmap {n}B '{text}' vs source '{lines[k].strip()}'")
        # (a source committed with its branch targets unresolved decodes fine and jumps
        # to 0 -- PING's first block did, mid-way through a change: every target must be
        # filled, scripts/sharc_resolve_jumps.py)
        src = (SHARC / f"{name}.asm").read_text(encoding="utf-8")
        bad += [f"unresolved: {m.group(0)}" for m in re.finditer(r"JUMP\s+0x0;|=\s*0x0;\s*// return address", src)]
        res[name] = {"instructions": len(offsets), "bytes": len(code), "disagreements": bad,
                     "source_sha256_matches": spec["source_sha256"] == hashlib.sha256(
                         (SHARC / f"{name}.asm").read_bytes().replace(b"\r\n", b"\n")).hexdigest()}
    entry = dk.st.decode_at(image.memory, None, dsp.ENTRY_SW)
    nop = dk.st.decode_at(image.memory, None, dsp.ENTRY_SW + 3)
    nxt = dk.st.decode_at(image.memory, None, LOOP_RESUME)
    fields = entry.fields or {}
    res["entry"] = {"type": entry.type_name, "fields": {k: v for k, v in fields.items()},
                    "len": entry.length_bytes, "nop": nop.type_name, "after": nxt.type_name}
    ok = all(not res[n]["disagreements"] and res[n]["source_sha256_matches"]
             for n in ("perc", "smp", "block_count", "ping", "fascia")) \
        and perc_links_ok() and no_gran_link() and entry.type_name.startswith("8a") \
        and entry.length_bytes == 6 and nop.length_bytes == 2
    return {"ok": ok, "detail": res}


# -- WAVs ------------------------------------------------------------------------------------------

def wav(name, samples, seconds, wavs, what, normalise=False):
    n = int(seconds * RATE)
    pk = V.peak(samples)
    scale = 0.9 / pk if normalise and pk else 1.0
    looped = 0 < len(samples) < n
    data = V.loop_to([x * scale for x in samples], n) if looped else [x * scale for x in samples]
    path = OUT / name
    m1.write_wav(path, data, RATE)
    wavs.append({"file": str(path), "seconds": round(len(data) / RATE, 3),
                 "rendered_samples": len(samples), "looped": looped, "gain": round(scale, 4),
                 "peak": pk, "rms": V.rms(samples),
                 "what": what + (" -- LOOPED from %d rendered samples" % len(samples) if looped else "")})


# -- main ------------------------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--blocks", type=int, default=8)
    p.add_argument("--seconds", type=float, default=2.5)
    p.add_argument("--frame", help="a 2,688-byte frame in DSP memory order (dnfw.waverider.frame)")
    p.add_argument("--frame-be", help="a frame as the ColdFire holds it at 0x80005e60 (16-bit BE)")
    p.add_argument("--frames", help="a glob of per-block frames (DSP order), sorted")
    p.add_argument("--no-selmap", action="store_true", help="skip selmap (no WSL)")
    p.add_argument("--steps", default="decode,map,voice,guard,stress,chords,garbage,wipe,smp,link,rec,mainrec,recwhole,pvmix,tdm,stock,mnm,frame,fascia,fchords,fgarbage,fsilence,fstress")   # v0.27: shft, gran removed; v0.45: ping removed   # voice: PERC
    p.add_argument("--tag", default="", help="names this run's frame WAVs and report: m5_frame_TAG_*.wav, m5_report_TAG.json")
    a = p.parse_args(argv)
    if a.seconds < 2:
        raise SystemExit("--seconds must be at least 2")
    steps = set(a.steps.split(","))
    OUT.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    m4.IMAGE = a.image
    stock = m1.dn2_section7(a.image)
    sound, machines = m4.init_sound(a.image)
    m5 = Image(dk, dsp.section7(stock))
    stock_img = Image(dk, stock)
    s7 = OUT / "m5_section7_waverider.bin"
    s7.write_bytes(m5.stream)
    report = {"digikit": {"path": str(a.digikit), "head": dk.head}, "section7_sha256": m5.sha,
              "section7_bytes": len(m5.stream), "section7_file": str(s7),
              "placements": dsp.placements(), "blocks": a.blocks}
    results, wavs = {}, []
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        work = pathlib.Path(tmp)
        snap, m2mach = snapshot_path(dk, stock, work)

        if "decode" in steps:
            print("step 1: decode")
            s1 = decode_check(dk, m5, work, not a.no_selmap)
            s1["checks"] = {
                "section 7 is dnfw.waverider.dsp.section7(stock)": m5.sha == hashlib.sha256(dsp.section7(stock)).hexdigest(),
                "every instruction reads as its source to digikit and selmap, on selas's boundaries,"
                " sources match their objects; the entry decodes as a 48-bit jump + 16-bit nop": s1["ok"],
            }
            s1["ok"] = all(s1["checks"].values())
            results["1_decode"] = s1
            show(s1)
            for n in ("perc", "smp", "block_count", "ping", "fascia"):
                for d in s1["detail"][n]["disagreements"][:20]:
                    print("     ", n, d)

        init = init_on(snap, m2mach, m5)
        # v0.17: the same with the Machinedrum's sine and tables already filled, as 0.7 s after
        # power-on, for runs whose track 0 is a PERC voice heard from its first blocks (a
        # second image: the warm tables must not reach the cold runs' memory)
        warm_init = []

        def warm():
            if not warm_init:
                warm_init.append(init_on(snap, m2mach, Image(dk, m5.stream), warm=True))
            return warm_init[0]
        if "map" in steps:
            print("\nstep 2: map")
            results["2_map"] = step_map(dk, snap, m2mach, m5, stock, init, sound, machines)
            show(results["2_map"])

        if "voice" in steps:
            print("\nstep 3: PERC")
            s3 = step_perc(warm(), sound, machines,
                           a.blocks, cold=init)
            results["3_perc"] = {k: v for k, v in s3.items() if k != "runs"}
            show(s3)
            runs = s3["runs"]
            for k, name in enumerate(PM.NAMES):
                r = runs[f"g{k // 8}"]
                if r["ok"]:
                    wav(f"perc_{k:02d}_{name}.wav", perc_series(r, k % 8), a.seconds, wavs,
                        f"PERC {name} (the owner's defaults, note 60, trigger on block 1): track 0's "
                        "buffer as PERC left it, bit-exact to dnfw.perc.program")
            if runs["g0"]["ok"]:
                wav("perc_amp_out.wav", runs["g0"]["amp_out"], a.seconds, wavs,
                    "TRX-BD at the amp's output, the end of the per-track chain")
            del s3, runs                        # each run holds a whole DSP memory: free them
            gc.collect()

        if "guard" in steps:
            print("\nstep 3g: the frame-time guard")
            results["3g_guard"] = step_guard(warm(), sound, machines, a.blocks)
            show(results["3g_guard"])
            gc.collect()

        if "cost" in steps:
            print("\nstep 3c: each machine's cost, one voice (v0.33)")
            results["3c_cost"] = step_cost(warm(), sound, machines)
            show(results["3c_cost"])
            gc.collect()
        if "garbage" in steps:
            print("\nstep 3g: voice state and scratch full of garbage (v0.33)")
            results["3g_garbage"] = step_garbage(warm(), sound, machines)
            show(results["3g_garbage"])
            gc.collect()
        if "wipe" in steps:
            print("\nstep 3w: the output guard's wipe, a poisoned P-I voice (v0.34)")
            results["3w_wipe"] = step_wipe(warm(), sound, machines)
            show(results["3w_wipe"])
            gc.collect()
        if "chords" in steps:
            print("\nstep 3k: four-note chords on each Monomachine machine, the memory clock (v0.36); "
                  "and on the sample machines ONESHOT, WERP, SLICE (v0.38)")
            results["3k_chords"] = step_chords(warm(), sound, machines, cold=init)
            show(results["3k_chords"])
            gc.collect()
        if "mainsrc" in steps:
            print("\nstep (probe): the main mix as the recorder sees it")
            results["probe_mainsrc"] = step_mainsrc(warm(), sound, machines, a.blocks)
            show(results["probe_mainsrc"])
        for key, title, fn in (("fascia", "FASCIA bit-exact to live.py: the audition, idle, a steal, p-locks (v0.45)",
                                lambda: step_fascia(warm(), sound, machines)),
                               ("fchords", "FASCIA chords, and beside PERC, ONESHOT, a Monomachine voice (v0.45)",
                                lambda: step_fchords(warm(), sound, machines)),
                               ("fgarbage", "FASCIA on garbage state (v0.45)", lambda: step_fgarbage(warm(), sound, machines)),
                               ("fsilence", "FASCIA untriggered: silence, little cost (v0.45)",
                                lambda: step_fsilence(warm(), sound, machines)),
                               ("fstress", "sixteen FASCIA voices, the clock made to move (v0.45)",
                                lambda: step_fstress(warm(), sound, machines)),
                               ("fcost", "a FASCIA voice's cost, each audition patch (v0.45)",
                                lambda: step_fcost(warm(), sound, machines))):
            if key in steps:
                print(f"\nstep 3{key}: {title}")
                results[f"3_{key}"] = fn()
                show(results[f"3_{key}"])
                gc.collect()
        if "stress" in steps:
            print("\nstep 3s: the stress test (the clock made to move)")
            results["3s_stress"] = step_stress(warm(), sound, machines)
            show(results["3s_stress"])
            gc.collect()

        if "slicestatic" in steps:
            print("\nstep 3ss: SAMP onto an empty slot at a note (dreamsaremaps, v0.42)")
            sss = step_slicestatic(warm(), sound, machines, a.blocks)
            results["3ss_slicestatic"] = {k: v for k, v in sss.items() if k != "runs"}
            show(sss)
            print("     peaks:", sss["numbers"]["peaks"])
            del sss
            gc.collect()

        if "smp" in steps:
            print("\nstep 3b: the sample machines")
            s3b = step_smp(warm(), sound, machines, a.blocks)   # v0.26: PERC beside them needs its tables whole (as 0.7 s after power-on)
            results["3b_smp"] = {k: v for k, v in s3b.items() if k != "runs"}
            show(s3b)
            mr = s3b["runs"]["mixed"]
            if mr["ok"]:
                for t, what in ((0, "SNARE reversed"), (1, "GRID on BEAT"), (4, "HAT looping")):
                    wav(f"smp_{t}.wav", smp_series(mr, t), a.seconds, wavs,
                        f"the sample machines, mixed run, track {t}: {what}")
            del s3b, mr
            gc.collect()

        if "link" in steps:
            print("\nstep 3c: the sample link")
            results["3c_link"] = {k: v for k, v in step_link(snap, m2mach, m5, stock_img, sound, machines,
                                                             a.blocks).items() if k != "runs"}
            gc.collect()
            show(results["3c_link"])

        if "rec" in steps:
            print("\nstep 3d: the recorder")
            results["3d_rec"] = step_rec(init, sound, machines, a.blocks)
            gc.collect()
            show(results["3d_rec"])

        if "mainrec" in steps:
            print("\nstep 3m: MAIN recorded, previewed and played, in the instrument's order (v0.38)")
            results["3m_mainrec"] = step_mainrec(init, sound, machines, a.blocks)
            gc.collect()
            show(results["3m_mainrec"])

        if "recwhole" in steps:
            print("\nstep 3r: whole takes, the ColdFire's link at work while they record (v0.39)")
            results["3r_recwhole"] = step_recwhole(init, sound, machines, a.blocks)
            gc.collect()
            show(results["3r_recwhole"])

        if "pvmix" in steps:
            print("\nstep 3f: the recorder's preview (after the engine's mix)")
            results["3f_pvmix"] = step_pvmix(snap, m2mach, m5, stock_img)
            gc.collect()
            show(results["3f_pvmix"])

        if "tdm" in steps:
            print("\nstep 3e: the fast link (TDM)")
            results["3e_tdm"] = step_tdm(init, sound, machines, a.blocks)
            gc.collect()
            show(results["3e_tdm"])

        if "stock" in steps:
            print("\nstep 4: types 0-4 unchanged")
            results["4_stock"] = step_stock(snap, m2mach, m5, stock_img, sound, machines,
                                            max(3, a.blocks // 2))
            show(results["4_stock"])
            print("\nstep 4b: stock filter types 0-5 unchanged")
            results["4b_filters"] = step_filters_stock(snap, m2mach, m5, stock_img, sound, machines,
                                                       max(3, a.blocks // 2))
            show(results["4b_filters"])

        if "shft" in steps:
            print("\nstep 7: SHFT")
            results["7_shft"] = step_shft(warm(), sound, machines, a.blocks)     # (track 0 is PERC)
            show(results["7_shft"])

        if "gran" in steps:
            print("\nstep 7b: GRAN")
            results["7b_gran"] = step_gran(warm(), sound, machines)             # (track 0 is PERC)
            show(results["7b_gran"])

        if "mnm" in steps:
            print("\nstep 8: the Monomachine machines (v0.26)")
            results["8_mnm"] = step_mnm(warm(), sound, machines, a.blocks)
            show(results["8_mnm"])

        frames = load_frames(a)
        if frames and "frame" in steps:
            print("\nstep 5: the caller's frame(s)")
            sep = f"_{a.tag}_" if a.tag else "_"
            s5 = step_frame(init, frames, a.blocks)
            results["5_frame"] = {k: v for k, v in s5.items() if k != "run"}
            show(s5)
            run = s5["run"]
            if run["ok"] and s5["numbers"]["type5_tracks"]:
                t = s5["numbers"]["type5_tracks"][0]
                wav(f"m5_frame{sep}perc.wav", perc_series(run, t), a.seconds, wavs,
                    f"the caller's frame: track {t}'s buffer as PERC left it")
                wav(f"m5_frame{sep}amp_out.wav", run["amp_out"], a.seconds, wavs,
                    "the caller's frame: track 0 at the amp's output")

    ok = bool(results) and all(r.get("ok") for r in results.values())
    report["steps"] = results
    report["wavs"] = wavs
    report["wall_s"] = round(time.perf_counter() - t_start)
    report["result"] = "PASS" if ok else "FAIL"
    (OUT / (f"m5_report_{a.tag}.json" if a.tag else "m5_report.json")).write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print("\nWAVs:")
    for w in wavs:
        print(f"  {w['file']}  {w['seconds']} s, peak {w['peak']:.4g} -- {w['what']}")
    print(f"\n  {report['result']}  ({report['wall_s']} s; report: out/waverider/m5_report.json)")
    return 0 if ok else 1


def show(step):
    for k, v in step.get("checks", {}).items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")


# -- step 2 -------------------------------------------------------------------------------------------

def step_map(dk, snap, m2mach, m5: Image, stock: bytes, init, sound, machines) -> dict:
    rec0 = V.track_record(0)

    def unpack(runner, frame, hooks=None):
        r = m4.unpack_call(runner, frame)
        fx.run(r, 2_000_000, fixups(hooks), stop_at=[0x1C3044])
        return r

    got = {}
    window = None
    for t, idx, val in ((0, WAV1, 0x7812), (0, TBL1, 0x0100), (1, WAV1, 0x1234), (3, TBL1, 0x0100),
                        (15, WAV1, 0x4321)):
        f = base_frame(sound, machines, others={t: 5} if t else None,
                       overrides=None if t else {idx: val})
        if t:
            f.param(t, idx, val)
        r = unpack(init, f.to_bytes())
        got[f"track {t} param {idx} = {val:#06x} -> frame copy +{FR.slot_offset(t, idx)}"] = (
            frame_word(r.state, FR.slot_offset(t, idx)), val)
        if t == 0:
            w = [m2.word(r.state, rec0 + 4 * k) for k in range(0x9C // 4 + 1)]
            window = w if window is None else window
            got[f"track 0 param {idx} = {val:#06x}: record machine window unchanged"] = (w == window, True)
    notes = {}
    for note in (0x3C00, 0x4800, 0x3C80):
        r = unpack(init, base_frame(sound, machines, note=note).to_bytes())
        notes[hex(note)] = V.bits_f32(m2.word(r.state, NOTE_CELL) or 0)
    clamp = []
    r = unpack(init, base_frame(sound, machines).to_bytes(),
               {CLAMP_MIN: lambda rr: clamp.append((m2.word_reg(rr, "R2"), m2.word_reg(rr, "R0")))})
    type_m5 = m2.word(r.state, rec0 + V.TRACK_MACHINE)
    # field 84 + 2t is what the clamp sees: set it to 3 for track 0, and read R2 there
    f = base_frame(sound, machines)
    f.header(84, 0, 3)
    seen = []
    unpack(init, f.to_bytes(), {CLAMP_MIN: lambda rr: seen.append(m2.word_reg(rr, "R2"))})
    # control: the same frame on an image without the lookup patch
    nolook = bytearray(m5.stream)
    bootstream.write_span(nolook, dsp.dm_to_load(dsp.LOOKUP16_DM + 20), struct.pack("<I", 0))
    ctl = init_on(snap, m2mach, Image(dk, bytes(nolook)))
    type_ctl = m2.word(unpack(ctl, base_frame(sound, machines).to_bytes()).state, rec0 + V.TRACK_MACHINE)
    # our spans, as the runner's memory holds them after init
    spans = {}
    for what, at, payload in dsp.spans() + dsp.l2_spans():
        dm = at - dsp.LOAD_ALIAS if at >= dsp.LOAD_ALIAS else at
        words = [m2.word(init.state, dm + 4 * k) for k in range(len(payload) // 4)]
        want = [struct.unpack_from("<I", payload, 4 * k)[0] for k in range(len(payload) // 4)]
        spans[what] = sum(1 for x, y in zip(words, want) if x != y)
    clamp_imm = bootstream.read_span(m5.stream, dsp.sw_to_load(0x1C294A), 4).hex()
    checks = {
        "WAV1 and TBL1 are in the unpack's frame copy at 0x25c48c + 220/222 + 146t, verbatim; "
        "a type-5 record's machine window does not carry them": all(v == w for v, w in got.values()),
        "the trig note lands in the note cell as float semitones (60, 72, 60.5)":
            notes == {"0x3c00": 60.0, "0x4800": 72.0, "0x3c80": 60.5},
        "a type-5 frame reaches record +0x1b4 as 5, with the stock clamp": type_m5 == 5,
        "the stock clamp min(R2, 4) reads frame field 84 + 2t, not the machine type (3 in -> R2 = 3)":
            bool(seen) and seen[0] == 3 and bool(clamp) and clamp[0] == (0, 4),
        "control: without the lookup patch, type 5 is squashed to 0 (FM Tone)": type_ctl == 0,
        "every span we add reads back, after init, as the image put it": all(v == 0 for v in spans.values()),
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"fields": {k: {"got": v, "want": w} for k, (v, w) in got.items()},
                        "note_cell": notes, "clamp_R2_R0_track0_init_frame": clamp[:1],
                        "clamp_R2_with_field84_3": seen[:1], "type_with_lookup": type_m5,
                        "type_without_lookup": type_ctl, "span_word_mismatches": spans,
                        "clamp_parcel_at_0x1c294a": clamp_imm}}


# -- step 3: PERC (docs/perc.md) -------------------------------------------------------------------

PERC_TYPE_SLOT = PM.TYPE_REC[1]         # DRIF: TYPE
RETRIG = 4                              # the retrigger run's second note
FX_ON = (0.8, 0.6, 0.5, 0.9, 0.3, 0.4, 0.7)   # AMD AMF EQF EQG FLTF FLTW FLTQ, every effect on
LEAVE = (3, 5)                          # the leave run: FM Tone in the frames of blocks 3-4 (the
                                        # record follows a block later: PERC again from block 6)
TYPE_SWITCH = 3                         # the type-switch run turns TYPE at this block, no new note


def perc_type_word(k: int) -> int:
    """the frame word that selects machine K (as dnfw.perc.live.Harness sets it)"""
    knob = (k * 128 + 127) // PM.N
    while (knob * PM.N) >> 7 != k:
        knob -= 1
    return knob << 8


def perc_words(k: int, params=None, fx=None) -> dict:
    """frame slot -> word for machine K with PARAMS (eight 0..1, default the owner's) and
    the track effects FX (seven 0..1, default all off)"""
    params = PL.defaults(PM.NAMES[k]) if params is None else params
    out = {PERC_TYPE_SLOT: perc_type_word(k)}
    for (_rid, slot, lo, top), x in zip(PM.PARAMS + PM.FX_PARAMS, list(params) + list(fx or PL.FX_OFF)):
        out[slot] = PL.word_of(x, top, lo)
    return out


def perc_series(run, t) -> list[float]:
    return [x for blk in run["perc"] if t in blk for x in blk[t]["out"]]


def perc_exact(run) -> tuple[int, int, int]:
    """(type-5 voice-blocks checked, output words differing, state words differing)"""
    n = o = st = 0
    for blk in run["perc"]:
        for v in blk.values():
            n += 1
            o += v["out_mismatches"]
            st += v["state_mismatches"]
    return n, o, st


def step_perc(init, sound, machines, blocks, cold=None) -> dict:
    def frames(k, note=0x3C00, trig=(1,), params=None, others=None, other_words=None):
        def fb(b):
            f = base_frame(sound, machines, overrides=perc_words(k, params), note=note, trigger=b in trig,
                           others=others, trigger_others=True)
            for t, words in (other_words or {}).items():
                for slot, w in words.items():
                    f.param(t, slot, w)
            return f.to_bytes()
        return fb

    # the 25 Machinedrum machines (v0.17), eight tracks at a time (track t of group g plays
    # machine 8 g + t, all triggered on block 1): four runs, up to eight PERC slots busy
    runs = {}
    groups_n = (PM.N + 7) // 8
    for g in range(groups_n):
        t0 = time.perf_counter()
        n_g = min(8, PM.N - 8 * g)
        runs[f"g{g}"] = run_blocks(init, frames(8 * g, others={t: 5 for t in range(1, n_g)},
                                               other_words={t: perc_words(8 * g + t) for t in range(1, n_g)}),
                                   blocks)
        print(f"    machines {8 * g}-{8 * g + n_g - 1}: {round(time.perf_counter() - t0)} s", flush=True)
    rs = PM.NAMES.index("TRX-RS")
    sd = PM.NAMES.index("TRX-SD")
    hh = PM.NAMES.index("EFM-HH")
    runs["note60"] = run_blocks(init, frames(rs), blocks)
    runs["single_sd"] = run_blocks(init, frames(sd), blocks)
    runs["note72"] = run_blocks(init, frames(rs, note=0x4800), blocks)
    # v0.17: the Machinedrum's sine, which the DSP fills itself 1,024 words a block
    runs["sine"] = run_blocks(cold or init, frames(0, trig=()), MDK.Z_N // MDK.Z_PER_BLOCK + 1)
    runs["retrig"] = run_blocks(init, frames(sd, trig=(1, RETRIG)), blocks)
    runs["silent"] = run_blocks(init, frames(0, trig=()), blocks)
    # TYPE turned mid-note: the voice keeps the machine its note latched
    # (only TYPE moves: the parameters stay TRX-BD's, which the voice goes on reading)
    runs["type_switch"] = run_blocks(init, lambda b: base_frame(
        sound, machines, overrides={**perc_words(0), PERC_TYPE_SLOT: perc_type_word(0 if b < TYPE_SWITCH else hh)},
        trigger=b == 1).to_bytes(), blocks)
    # every parameter at its top, and at its bottom, on an FM machine and a TRX one
    # v0.12: the track effects, every one on (AM, EQ boost, high and low pass, resonance)
    runs["fx"] = run_blocks(init, lambda b: base_frame(
        sound, machines, overrides=perc_words(sd, fx=FX_ON), trigger=b == 1).to_bytes(), blocks)
    # v0.12: the track leaves PERC while it rings and comes back with no new note: silent
    runs["leave"] = run_blocks(init, lambda b: base_frame(
        sound, machines, t0=0 if LEAVE[0] <= b < LEAVE[1] else 5, overrides=perc_words(sd),
        trigger=b == 1).to_bytes(), blocks)
    runs["tops"] = run_blocks(init, frames(PM.NAMES.index("EFM-CB"), params=[1.0] * 8), blocks)
    runs["bottoms"] = run_blocks(init, frames(PM.NAMES.index("TRX-CY"), params=[0.0] * 8), blocks)
    # v0.31: a Machinedrum voice rests once the chain's block has stayed silent
    # PP.MNM_QUIET_BLOCKS blocks (as the Monomachine's, v0.29), and its next note wakes it.
    # GND-SN with every control at its top never decays; the chain's silence is made right
    # after track 0's amp, as in step_mnm's rest run. The control: the same without it.
    rest_at = PP.MNM_QUIET_BLOCKS + 4
    sn = PM.NAMES.index("GND-SN")
    hushed = {"on": True}

    def hush(r):
        if hushed["on"] and len(r_seen) < rest_at - 1:
            buf = m2.word(r.state, PP.BUFFERS) or 0
            for k in range(BLOCK):
                m2.poke(r.state, buf + 4 * k, 0)
    r_seen = []
    runs["rest"] = _slim(run_blocks(init, frames(sn, trig=(1, rest_at), params=[1.0] * 8), rest_at + 3,
                                    extra_hooks={dsp.SMP_SW: lambda r: r_seen.append(1), AMP_RETURN: hush}))
    hushed["on"] = False
    runs["rest_ctl"] = _slim(run_blocks(init, frames(sn, trig=(1,), params=[1.0] * 8), rest_at + 3))
    ok_runs = all(r["ok"] for r in runs.values())
    exact = {k: perc_exact(r) for k, r in runs.items() if r["ok"]}
    peaks = {PM.NAMES[k]: V.peak(perc_series(runs[f"g{k // 8}"], k % 8)) if runs[f"g{k // 8}"]["ok"] else None
             for k in range(PM.N)}
    m0 = runs["g0"]
    zc60 = zero_crossings(perc_series(runs["note60"], 0)) if runs["note60"]["ok"] else 0
    zc72 = zero_crossings(perc_series(runs["note72"], 0)) if runs["note72"]["ok"] else 0
    groups = [sorted({t for blk in runs[f"g{g}"]["perc"] for t in blk}) if runs[f"g{g}"]["ok"] else []
              for g in range(groups_n)]
    sine_ok = False
    if runs["sine"]["ok"]:
        st = runs["sine"]["state"].state
        L = PL.layout()
        got = [round(V.bits_f32(m2.word(st, L.md.T["sine"] + 4 * k) or 0) * 2 ** 23) for k in range(MDK.SINE_N)]
        sine_ok = got == MDK.md_sine_words()
        # and the packed tables, unpacked into their floats (unpack_fill), word for word
        from dnfw.md import bench as MDB
        want = MDB.table_mem(L.md)
        lo, hi = L.md.tables, L.md.tables + 4 * MDK.Z_N      # (v0.26: what ships is elsewhere)
        tables_ok = all((m2.word(st, a) or 0) == want.get(a, 0) for a in range(lo, hi, 4))
        sine_ok = sine_ok and tables_ok
    runs["sine"].pop("state", None)
    sw = runs["type_switch"]
    sw_state = [blk[0]["out"] for blk in sw["perc"] if 0 in blk] if sw["ok"] else []
    base = perc_series(runs["g0"], 0)
    sw_series = perc_series(sw, 0)
    rt = perc_series(runs["retrig"], 0)
    one = perc_series(runs["single_sd"], 0)
    silent = perc_series(runs["silent"], 0)
    trig_bits = [x[0]["trig"] for x in m0["t5_inputs"] if 0 in x] if m0["ok"] else []
    fxs = perc_series(runs["fx"], 0)
    def rest_pk(name, b):
        r = runs[name]
        return V.peak(r["perc"][b][0]["out"]) if r["ok"] and b < len(r["perc"]) and 0 in r["perc"][b] else None
    rest_quiet = rest_pk("rest", rest_at - 2)
    rest_ctl = rest_pk("rest_ctl", rest_at - 2)
    rest_wake = max((rest_pk("rest", b) or 0.0) for b in (rest_at, rest_at + 1))
    lv = runs["leave"]
    back = [x for b, blk in enumerate(lv["perc"]) if b >= LEAVE[1] and 0 in blk for x in blk[0]["out"]] if lv["ok"] else []
    before = [x for b, blk in enumerate(lv["perc"]) if b < LEAVE[0] and 0 in blk for x in blk[0]["out"]] if lv["ok"] else []
    n = {"perc_exact_voice_blocks_out_state_mismatches": exact,
         "peaks_by_machine": peaks,
         "loop_entries_m0": m0.get("loop_entries"),
         "trig_bits_m0": trig_bits,
         "zero_crossings_TRX-RS_note60_note72": (zc60, zc72),
         "tracks_rendered_per_group": groups,
         "model_steps_per_block": {k: max((v["model_steps"] for blk in r["perc"] for v in blk.values()), default=0)
                                   for k, r in runs.items() if r["ok"]},
         "amp_out_peak_m0": V.peak(m0["amp_out"]) if m0["ok"] else None,
         "silent_peak": V.peak(silent) if silent else 0.0,
         "rest_quiet_control_wake": (rest_quiet, rest_ctl, rest_wake),
         "instructions_per_block_m0": round(m0.get("instructions", 0) / max(blocks, 1)),
         "wall_s": {k: r.get("wall_s") for k, r in runs.items()},
         "halts": {k: r.get("halt") for k, r in runs.items() if not r["ok"]}}
    checks = {
        "every run returns every block": ok_runs,
        "PERC is entered by the image's own JUMP (the block counter's), once a block":
            m0.get("loop_entries") == blocks,
        "the trigger bit is seen on the trigger block only": trig_bits == [b == 1 for b in range(len(trig_bits))],
        "every type-5 track's buffer and state, every block of every run, are bit-exact to "
        "dnfw.perc.program run on the DSP's memory at PERC's entry":
            ok_runs and all(v[0] > 0 and v[1] == 0 and v[2] == 0 for k, v in exact.items() if k != "silent")
            and exact.get("silent", (0, 1, 1))[1:] == (0, 0),
        # (TRX-MA's shaker builds up over a second: 0.004 in its first 8 blocks, as the MD's)
        f"all {PM.N} Machinedrum machines sound at the Machinedrum's defaults (peak > 0.002 within {blocks} blocks)":
            all(v is not None and v > 0.002 for v in peaks.values()),
        "v0.17: the DSP's sine is the Machinedrum's own table, and its unpacked tables the firmware's, word for word, once filled": sine_ok,
        "nothing is non-finite or above 4.0 in any PERC buffer":
            ok_runs and all(math.isfinite(x) and abs(x) <= 4.0 for r in runs.values() for blk in r["perc"]
                            for v in blk.values() for x in v["out"]),
        "TRX-BD is heard at the amp's output (peak > 0.02)": bool(n["amp_out_peak_m0"]) and n["amp_out_peak_m0"] > 0.02,
        "v0.17: the note does not tune a Machinedrum machine (as on the Machinedrum): note 72 is note 60":
            zc72 == zc60 > 0,
        "up to eight PERC tracks at once are all rendered, in each group":
            groups == [list(range(min(8, PM.N - 8 * g))) for g in range(groups_n)],
        "TYPE turned mid-note leaves the note on its machine (track 0 identical to the untouched TRX-BD's)":
            bool(sw_series) and sw_series == base,
        "a second note restarts the voice (the retrigger run departs from the single note's at it)":
            bool(rt) and rt[:BLOCK * RETRIG] == one[:BLOCK * RETRIG] and rt[BLOCK * RETRIG:] != one[BLOCK * RETRIG:],
        "control: no trigger is silent (every PERC sample 0)": bool(silent) and all(x == 0.0 for x in silent),
        "v0.12: the track effects change the sound (every one on: the block differs from TRX-SD's own)":
            bool(fxs) and bool(one) and fxs != one and all(math.isfinite(x) for x in fxs),
        "v0.31: a Machinedrum voice whose sound has died away after the chain rests (renders nothing), "
        "its next note wakes it; the control, never hushed, still renders":
            rest_quiet == 0.0 and rest_ctl is not None and rest_ctl > 0.005 and rest_wake > 0.005,
        "v0.12: a track that leaves PERC while it rings is silent when it comes back with no note":
            bool(before) and V.peak(before) > 0.005 and len(back) >= BLOCK * 2
            and all(x == 0.0 for x in back),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": n, "runs": runs}


# -- step 3g: the frame-time guard (v0.27, dnfw.perc.guard) ---------------------------------------

def _after_emuclk(name: str) -> list[int]:
    """sw addresses of the instructions after each `R8 = EMUCLK;` in NAME.asm (its object's offsets)."""
    spec = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / f"{name}.asm").read_text().splitlines()]
    src = [c for c in src if c and not c.startswith(".") and not c.endswith(":")]
    offs = spec["instruction_offsets"]
    assert len(offs) == len(src), f"{name}: {len(offs)} offsets, {len(src)} instructions"
    base = int(spec["load_sw"], 0) if isinstance(spec["load_sw"], str) else spec["load_sw"]
    return [base + offs[k + 1] // 2 for k, c in enumerate(src) if c == "R8 = EMUCLK;"]


def step_guard(init, sound, machines, blocks) -> dict:
    """Two PERC tracks (0: TRX-SD, 1: EFM-SD), both struck on block 1. The runner's EMUCLK does
    not move, so the guard plays every voice (control run: every block bit-exact, no skip). Then
    the clock is fed as if the frame were spent before track 1's voice from block FORCE on: its
    buffer is all zeros there, its voice state is what it was at PERC's entry (kept, not run),
    the skip counter counts those blocks, and track 0 is bit-exact throughout."""
    from dnfw.perc import guard as G
    FORCE = 3
    sd, efm = PM.NAMES.index("TRX-SD"), PM.NAMES.index("EFM-SD")
    at = _after_emuclk("perc")

    def fb(b):
        f = base_frame(sound, machines, overrides=perc_words(sd), trigger=b == 1, others={1: 5},
                       trigger_others=True)
        for slot, w in perc_words(efm).items():
            f.param(1, slot, w)
        return f.to_bytes()

    seen = {"entry": [], "exit": [], "block": [0]}

    def runs(force):
        seen["entry"].clear()
        seen["exit"].clear()
        blk = {"b": -1}

        def at_perc(r):
            blk["b"] += 1
            seen["entry"].append([m2.word(r.state, PERC_L.state + 128 + 4 * k) or 0 for k in range(PM.STATE_WORDS)])

        def at_smp(r):
            if len(seen["exit"]) < len(seen["entry"]):
                seen["exit"].append([m2.word(r.state, PERC_L.state + 128 + 4 * k) or 0 for k in range(PM.STATE_WORDS)])

        def feed(r):
            t = m2.word(r.state, PERC_L.C["t"]) or 0
            if force and t == 1 and blk["b"] >= FORCE:
                mark0 = m2.word(r.state, G.MARK0) or 0
                r.state.uregs[fx.UREG_CODES["R8"]] = fx.Const((mark0 + 0x10000000) & 0xFFFFFFFF)
        return run_blocks(init, fb, blocks, extra_hooks={dsp.PERC_SW: at_perc, dsp.SMP_SW: at_smp, at[0]: feed})

    ctl = runs(False)
    ctl_skips = m2.word(ctl["state"].state, G.SKIPS) if ctl["ok"] else None
    ctl_exact = perc_exact(ctl) if ctl["ok"] else None
    fr = runs(True)
    skips = m2.word(fr["state"].state, G.SKIPS) if fr["ok"] else None
    t1 = [blk.get(1, {}).get("out", []) for blk in fr["perc"]] if fr["ok"] else []
    t0_bad = sum(blk[0]["out_mismatches"] + blk[0]["state_mismatches"] for blk in fr["perc"] if 0 in blk) if fr["ok"] else -1
    t1_early_bad = sum(blk[1]["out_mismatches"] + blk[1]["state_mismatches"]
                       for b, blk in enumerate(fr["perc"]) if b < FORCE and 1 in blk) if fr["ok"] else -1
    kept = fr["ok"] and all(seen["entry"][b] == seen["exit"][b] for b in range(FORCE, len(seen["exit"])))
    n = {"emuclk_reads": [hex(x) for x in at], "control_skips": ctl_skips, "control_exact": ctl_exact,
         "forced_skips": skips, "track1_peaks": [V.peak(o) if o else None for o in t1]}
    checks = {
        "the guard reads the clock twice a voice (before, after)": len(at) == 2,
        "control: with the clock still, no voice is skipped and every voice is bit-exact":
            ctl["ok"] and ctl_skips == 0 and ctl_exact[0] > 0 and ctl_exact[1:] == (0, 0),
        "fed past the limit: track 1 is silent from that block (its buffer all zeros)":
            fr["ok"] and len(t1) == blocks and all(all(x == 0.0 for x in t1[b]) for b in range(FORCE, blocks))
            and max(V.peak(t1[b]) for b in range(FORCE)) > 0.0,   # (it sounded before)
        "... its voice state kept as it was (not run)": kept,
        "... the skips counted, one a block": skips == blocks - FORCE,
        "... and track 0, and track 1 before it, bit-exact to the model": t0_bad == 0 and t1_early_bad == 0,
    }
    # v0.29: the voices newest first. TRX-SD on slots 0, 1, 2, each struck in turn (blocks 1,
    # 3, 5: dynamic allocation), the clock fed so that only the first voice a block fits:
    # that one is always the newest note, the older ones skipped (before, slot 0 kept it)
    def ob(b):
        f = base_frame(sound, machines, overrides=perc_words(sd), trigger=b == 1, others={1: 5, 2: 5})
        for t in (1, 2):
            for slot, w in perc_words(sd).items():
                f.param(t, slot, w)
            if b == 1 + 2 * t:
                f.trigger(t)
        return f.to_bytes()
    ran = {"n": 0}

    def o_entry(r):
        ran["n"] = 0

    def o_feed(r):
        if ran["n"] >= 1:
            mark0 = m2.word(r.state, G.MARK0) or 0
            r.state.uregs[fx.UREG_CODES["R8"]] = fx.Const((mark0 + 0x10000000) & 0xFFFFFFFF)
        ran["n"] += 1
    orr = run_blocks(init, ob, 7, extra_hooks={dsp.PERC_SW: o_entry, at[0]: o_feed})

    def opk(b, t):
        return V.peak(orr["perc"][b][t]["out"]) if orr["ok"] and t in orr["perc"][b] else 0.0
    n["order_peaks"] = [[round(opk(b, t), 3) for t in range(3)] for b in range(7)]
    checks["v0.29: newest first: with time for one voice a block, the newest note plays and the older are skipped"] = (
        orr["ok"] and opk(2, 0) > 0.005 and opk(4, 1) > 0.005 and opk(4, 0) == 0.0   # (a hit is heard
        and opk(6, 2) > 0.005 and opk(6, 0) == 0.0 and opk(6, 1) == 0.0)            # from the next block)
    orr.pop("state", None)
    for r in (ctl, fr):
        r.pop("state", None)
    # v0.32: the limit from the stock's measured tail (guard.tail_limit). Each block, before
    # PERC's entry, the clock's words are set as a 666,667-cycle frame would leave them (the
    # last MARK0 a frame back) and idle_load's AFTER moved on by our time (100,000) plus a
    # tail TAIL; LIMIT is read at the sample machines' entry, after PERC's
    P = 666_667

    def limit_of(tail_d, ours=100_000):
        def at_perc(r):
            mark0 = m2.word(r.state, G.MARK0) or 0
            m2.poke(r.state, G.PREV, (mark0 - P) & 0xFFFFFFFF)
            if tail_d is not None:
                pm = m2.word(r.state, G.PREV_MARK) or 0
                m2.poke(r.state, G.OURS_END, (pm + ours) & 0xFFFFFFFF)
                pa = m2.word(r.state, G.PREV_AFTER) or 0
                m2.poke(r.state, G.AFTER, (pa + ours + tail_d) & 0xFFFFFFFF)
        got = []
        rr = run_blocks(init, fb, 3, extra_hooks={dsp.PERC_SW: at_perc,
                                                  dsp.SMP_SW: lambda r: got.append(m2.word(r.state, G.LIMIT) or 0)})
        rr.pop("state", None)
        return got

    def want(tail_pk):
        six = (P >> 1) + (P >> 4) + (P >> 5) + (P >> 7)
        lim = max(P - tail_pk - (P >> 3), P >> 2)
        return min(six, lim)
    tl = limit_of(300_000)
    tl_ctl = limit_of(None)
    tl_bad = limit_of(500_000)                 # past 0.7 P: not a reading
    pk = 300_000 - (300_000 >> 12)             # held, eased once
    n["tail_limits"] = {"tail_300k": tl, "none": tl_ctl, "tail_500k": tl_bad}
    checks["v0.32: a measured stock tail of 300,000 cycles sets LIMIT = P - tail - P/8 (below 0.6 P)"] = (
        len(tl) == 3 and tl[-1] in (want(pk), want(pk - (pk >> 12))) and tl[-1] < want(0))
    checks["v0.32: ... no reading (the idle task did not run) leaves 0.6 P, as before"] = (
        len(tl_ctl) == 3 and all(x == want(0) for x in tl_ctl))
    checks["v0.32: ... a reading past 0.7 P is not taken: 0.6 P"] = (
        len(tl_bad) == 3 and all(x == want(0) for x in tl_bad))
    return {"ok": all(checks.values()), "checks": checks, "numbers": n}


# -- step 3s: the stress test (v0.32) -----------------------------------------------------------

def step_stress(init, sound, machines) -> dict:
    """v0.32: the DSP's time under load, with the clock made to move. The runner's EMUCLK
    stands still; here every read of it in our code (the guard's, our end mark, the meter)
    gets the block's start plus K x the instructions run in the block so far, MARK0 the
    block's start and MARK our entry, a frame P apart: the guard then works as on the unit,
    K standing for what a DN2 cycle costs an instruction (memory stalls: the unit's load is
    several times its instruction count; K = 3 here, past what v0.27..v0.31 were measured
    at). Scenario A (depaffect's): sixteen PERC voices, EFM-SD, a new note on the next voice
    each block (dynamic allocation). B: four Monomachine voices (VO-6, DDRW, DENS, SID) and
    four PERC. Each block must end, our voices done by 0.8 P (the guard checks before each
    voice; one voice may run past LIMIT by its own cost), the newest note heard, voices
    left out (and counted) when time is short, nothing non-finite."""
    from dnfw.perc import guard as G
    from dnfw.mnm import machines as MMx
    K, P = 3, 666_667
    sites = set(_after_emuclk("perc")) | set(_after_emuclk("smp")) | set(_after_emuclk("fascia"))   # v0.47: FASCIA runs last and writes OURS_END
    efm = PM.NAMES.index("EFM-SD")
    td = PM.NAMES.index("TRX-BD")
    res = {}
    # v0.34 (docs/timing-model.md): the clock charged by where each access lands, as the
    # unit does (cost is memory, not instructions: docs/others-dn2-research.md), instead of
    # K an instruction: cycles = instructions + MEM_SCALE x (4 x L2 + 10 x DDR), the weights
    # complex-ping's, MEM_SCALE from the silent frame (step 3c's calibration: the unit's
    # 416,000 cycles against the runner's counts). Scenario F runs C's worst case on it.
    counts, undo_counts = _count_memory()
    # (3c's calibration, 2026-10-31: the silent block is 170,461 instructions, 1,032 L2 and
    # 26,923 DDR accesses in the runner; the unit's 416,000 cycles give S = 0.898)
    MEM_SCALE = float(os.environ.get("DNFW_MEM_SCALE", "0.9"))

    def scenario(name, blocks, frame_of, memory_clock=False):
        b_now = {"b": 0}
        ends = []

        def cycles(r):
            n = getattr(r, "steps_n", 0)
            if not memory_clock:
                return K * n
            return int(n + MEM_SCALE * (4 * counts["L2"] + 10 * counts["DDR"]))

        def clock(r):
            base = (b_now["b"] + 1) * P
            r.state.uregs[fx.UREG_CODES["R8"]] = fx.Const((base + cycles(r)) & 0xFFFFFFFF)

        def at_dispatch(r):
            for k in ("L1", "L2", "DDR"):
                counts[k] = 0
            counts["on"] = memory_clock

        def at_perc(r):
            base = (b_now["b"] + 1) * P
            m2.poke(r.state, G.MARK0, base & 0xFFFFFFFF)
            m2.poke(r.state, G.MARK, (base + cycles(r)) & 0xFFFFFFFF)

        def at_end(r):
            pass
        hooks = {dsp.PERC_SW: at_perc, m3.DISPATCH: at_dispatch}
        hooks.update({s: clock for s in sites})
        got = {"limit": [], "end": [], "skips": []}

        def fb(b):
            b_now["b"] = b
            return frame_of(b)
        rr = run_blocks(init, fb, blocks, extra_hooks=hooks)
        st = rr.get("state")
        skips = m2.word(st.state, G.SKIPS) if rr["ok"] else None
        end = m2.word(st.state, G.OURS_END) if rr["ok"] else None
        mark0 = m2.word(st.state, G.MARK0) if rr["ok"] else None
        limit = m2.word(st.state, G.LIMIT) if rr["ok"] else None
        rr.pop("state", None)
        return rr, skips, ((end - mark0) & 0xFFFFFFFF) if end is not None else None, limit

    def a_frame(b):
        f = base_frame(sound, machines, overrides=perc_words(efm), trigger=False, others={t: 5 for t in range(1, 16)})
        for t in range(1, 16):
            for slot, w in perc_words(efm).items():
                f.param(t, slot, w)
        f.trigger(b % 16)
        return f.to_bytes()
    ra, sa, ea, la = scenario("A", 20, a_frame)
    names = ("VO-6", "DPRO-DDRW", "DPRO-DENS", "SID 6581")

    def b_frame(b):
        f = base_frame(sound, machines, overrides=perc_words(td), trigger=False,
                       others={**{t: MMx.TYPES[MMx.NAMES.index(n)] for t, n in zip(range(4), names)},
                               **{t: 5 for t in range(4, 8)}})
        for t, n in zip(range(4), names):
            for slot, w in mnm_words(MMx.NAMES.index(n)).items():
                f.param(t, slot, w)
        for t in range(4, 8):
            for slot, w in perc_words(td).items():
                f.param(t, slot, w)
        if b % 2 == 0:
            f.trigger((b // 2) % 8)
        return f.to_bytes()
    rb, sb, eb, lb = scenario("B", 16, b_frame)

    # v0.33, the worst cases (the owner's list): C, sixteen P-I voices (the heaviest
    # Machinedrum family), a new note on the next voice every block with every control
    # moving (p-locks on every step); D, sixteen Monomachine voices (VO-6 and DENS in
    # turn), the same; E, one track retriggered every block (zuzsw's RTRG at 1/80 and
    # faster) beside fifteen sounding EFM voices
    import random as _rr
    rnd = _rr.Random(80)
    pi = [k for k, n in enumerate(PM.NAMES) if n.startswith("PI-")]

    def c_frame(b):
        f = base_frame(sound, machines, overrides=perc_words(pi[0]), trigger=False, others={t: 5 for t in range(1, 16)})
        for t in range(16):
            k = pi[(t + b) % len(pi)]
            # (v0.33, Moog: a PERC track burst into noise, then all silent: the track effects
            # too, at random, the resonant filters included)
            for slot, w in perc_words(k, params=[rnd.random() for _ in range(8)],
                                      fx=[rnd.random() for _ in range(7)]).items():
                f.param(t, slot, w)
        f.trigger(b % 16)
        return f.to_bytes()
    rc, sc, ec, lc = scenario("C", 20, c_frame)
    mn = [MMx.NAMES.index("VO-6"), MMx.NAMES.index("DPRO-DENS")]

    def d_frame(b):
        f = base_frame(sound, machines, t0=MMx.TYPES[mn[0]], trigger=False,
                       others={t: MMx.TYPES[mn[t % 2]] for t in range(1, 16)})
        for t in range(16):
            for slot, w in mnm_words(mn[t % 2], [rnd.randrange(128) for _ in range(8)]).items():
                f.param(t, slot, w)
        f.trigger(b % 16)
        return f.to_bytes()
    rd, sd, ed, ld = scenario("D", 20, d_frame)

    def e_frame(b):
        f = base_frame(sound, machines, overrides=perc_words(td), trigger=False, others={t: 5 for t in range(1, 16)})
        for t in range(1, 16):
            for slot, w in perc_words(efm).items():
                f.param(t, slot, w)
        if b == 1:
            for t in range(1, 16):
                f.trigger(t)
        f.trigger(0)                            # track 0 again, every block
        return f.to_bytes()
    re_, se, ee, le = scenario("E", 16, e_frame)
    rf, sf, ef, lf = scenario("F", 20, c_frame, memory_clock=True)   # v0.34: C's worst case on the memory clock
    undo_counts()

    def newest_heard(rr, every):
        if not rr["ok"]:
            return 0.0
        hits = tot = 0
        for b in range(2, len(rr["perc"])):
            t = (b - 1) % every if every == 16 else None
            if t is None:
                continue
            tot += 1
            blk = rr["perc"][b]
            if t in blk and V.peak(blk[t]["out"]) > 0.001:
                hits += 1
        return hits / max(tot, 1)
    fin = all(math.isfinite(x) for rr in (ra, rb, rc, rd, re_) if rr["ok"] for blk in rr["perc"]
              for v in blk.values() for x in v["out"])
    fin_bufs = all(math.isfinite(x) for rr in (rc, rd, re_) if rr["ok"] for blk in rr["buffers"]
                   for t in range(16) for x in blk[t])
    n = {"K": K, "skips": {"A": sa, "B": sb}, "our_end_over_P": {"A": ea and round(ea / P, 3), "B": eb and round(eb / P, 3)},
         "limit": {"A": la, "B": lb}, "newest_heard_A": newest_heard(ra, 16),
         "instructions_per_block": {"A": ra.get("instructions", 0) // 20, "B": rb.get("instructions", 0) // 16}}
    n.update({"skips_worst": {"C": sc, "D": sd, "E": se, "F": sf},
              "our_end_over_P_worst": {k: v and round(v / P, 3) for k, v in (("C", ec), ("D", ed), ("E", ee), ("F", ef))},
              "memory_clock_scale": MEM_SCALE})
    fin_f = rf["ok"] and all(math.isfinite(x) for blk in rf["buffers"] for t in range(16) for x in blk[t])
    checks = {
        "every block of both returns": ra["ok"] and rb["ok"],
        "our voices done by 0.8 of the frame in both (the guard's limit holds under load)":
            ea is not None and eb is not None and ea <= 0.8 * P and eb <= 0.8 * P,
        "v0.33, the worst cases: every block of C (16 P-I, all controls and track effects moving), D (16 VO-6/DENS, "
        "all controls moving) and E (a retrigger every block beside 15 voices) returns":
            rc["ok"] and rd["ok"] and re_["ok"],
        "v0.33: in each, our voices done by 0.8 of the frame (the guard leaves voices out instead)":
            all(x is not None and x <= 0.8 * P for x in (ec, ed, ee)),
        "v0.33: in C and D, with time short, voices are left out and counted": bool(sc) and bool(sd),
        "v0.33: every track buffer finite, no NaN, in C, D and E": fin_bufs,
        "v0.34: F (C's case on the memory-cost clock): every block returns, our voices done by 0.8 of the "
        "frame, voices left out and counted, every buffer finite":
            rf["ok"] and ef is not None and ef <= 0.8 * P and bool(sf) and fin_f,
        "with time short, voices are left out and counted (A)": bool(sa),
        "A: the newest note is heard in most blocks (newest first)": n["newest_heard_A"] >= 0.8,
        "nothing non-finite": fin,
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": n}


def step_chords(init, sound, machines, need=4, cold=None) -> dict:
    """v0.36 (the owner and misterairplane: two voices at most on a Monomachine track, the
    oldest silenced). A chord: four notes of one Monomachine machine at once (four tracks,
    one note each, as dynamic allocation spreads a chord), held 24 blocks, for each machine,
    on the memory-cost clock (step 3s scenario F's: cycles = instructions + S x (4 L2 + 10
    DDR), EMUCLK moved by it, so the frame guard decides as on the unit). Counts the voices
    sounding in each block after the attack; NEED of them for every machine but DDRW
    (reported: its cost is the tables in DDR). Our voices done by 0.8 of the frame,
    everything finite.

    v0.38: then the sample machines in chords (step_smp_chords, on COLD: the cold init, as
    the standalone check that passed on v0.37 ran)."""
    from dnfw.perc import guard as G
    from dnfw.mnm import machines as MMx
    P = 666_667
    sites = set(_after_emuclk("perc")) | set(_after_emuclk("smp")) | set(_after_emuclk("fascia"))   # v0.47: FASCIA runs last and writes OURS_END
    counts, undo_counts = _count_memory()
    S = float(os.environ.get("DNFW_MEM_SCALE", "0.9"))
    notes = (0x3C00, 0x4000, 0x4300, 0x4800)      # C, E, G, C
    res, nums = {}, {}
    only = [x for x in os.environ.get("DNFW_CHORDS_ONLY", "").split(",") if x]   # (a quicker look at some)
    try:
        for name in [n for n in MMx.NAMES if not only or n in only]:
            k = MMx.NAMES.index(name)
            typ = MMx.TYPES[k]
            b_now = {"b": 0}
            hist_of, last_hist = [None], [None]

            def cycles(r):
                return int(getattr(r, "steps_n", 0) + S * (4 * counts["L2"] + 10 * counts["DDR"]))

            def clock(r):
                r.state.uregs[fx.UREG_CODES["R8"]] = fx.Const(((b_now["b"] + 1) * P + cycles(r)) & 0xFFFFFFFF)

            def at_dispatch(r):
                for x in ("L1", "L2", "DDR"):
                    counts[x] = 0
                counts["on"] = True
                counts["hist"] = {} if b_now["b"] == 12 else None    # one sustained block's DDR pages
                if b_now["b"] == 13:
                    hist_of[0] = dict(last_hist[0] or {})
                last_hist[0] = counts["hist"] if b_now["b"] == 12 else last_hist[0]

            trace = []

            def at_perc(r):
                base = (b_now["b"] + 1) * P
                if b_now["b"] <= 8:                 # the guard's view of the attack, for the numbers
                    trace.append({"b": b_now["b"], "limit": m2.word(r.state, G.LIMIT),
                                  "cost": [m2.word(r.state, G.COST_PERC + 4 * t) for t in range(4)],
                                  "skips": m2.word(r.state, G.SKIPS)})
                m2.poke(r.state, G.MARK0, base & 0xFFFFFFFF)
                m2.poke(r.state, G.MARK, (base + cycles(r)) & 0xFFFFFFFF)
            hooks = {dsp.PERC_SW: at_perc, m3.DISPATCH: at_dispatch}
            hooks.update({x: clock for x in sites})

            def fb(b, typ=typ, k=k):
                b_now["b"] = b
                f = base_frame(sound, machines, t0=typ, overrides=mnm_words(k), trigger=False,
                               others={t: typ for t in range(1, 4)})
                for t in range(4):
                    for slot, w in mnm_words(k).items():
                        f.param(t, slot, w)
                    f.header(FR.NOTE, t, notes[t])
                    if b == 1:
                        f.trigger(t)
                return f.to_bytes()
            rr = run_blocks(init, fb, 24, extra_hooks=hooks)
            st = rr.get("state")
            end = mark0 = None
            if rr["ok"]:
                end, mark0 = m2.word(st.state, G.OURS_END), m2.word(st.state, G.MARK0)
            rr.pop("state", None)
            sounding = []
            for b in range(4, len(rr.get("perc", []))):
                blk = rr["perc"][b]
                sounding.append(sum(1 for t in range(4) if t in blk and V.peak(blk[t]["out"]) > 1e-4))
            fin = rr["ok"] and all(math.isfinite(x) for blk in rr["buffers"] for t in range(16) for x in blk[t])
            over = ((end - mark0) & 0xFFFFFFFF) / P if end is not None else None
            top = sorted((hist_of[0] or {}).items(), key=lambda kv: -kv[1])[:6]
            nums[name] = {"ddr_pages_top": [(f"{pg << 12:#010x}", n) for pg, n in top],
                          "sounding_min": min(sounding) if sounding else 0,
                          "sounding_mean": round(sum(sounding) / max(len(sounding), 1), 2),
                          "our_end_over_P": over and round(over, 3)}
            print(f"    {name}: {nums[name]}", flush=True)
            want = need if name != "DPRO-DDRW" else 3      # (v0.37: DDRW skips its zero-weight level: three fit)
            flicker = any(b2 > a2 for a2, b2 in zip(sounding, sounding[1:]))    # a dropped voice back with no note
            nums[name]["flicker"] = flicker
            nums[name]["guard_attack"] = trace
            res[f"{name}: at least {want} of the chord's 4 voices sound in every block, a voice left out stays "
                f"out until its next note (no flicker), done by 0.8 of the frame, finite"] = (
                rr["ok"] and fin and over is not None and over <= 0.8 and not flicker
                and nums[name]["sounding_min"] >= want)
    finally:
        counts["hist"] = None
        undo_counts()
    # v0.38: the sample machines in chords (after the memory counters are undone: they run as
    # the standalone check did, without the cost clock)
    sres, snums = step_smp_chords(cold if cold is not None else init, sound, machines, only=only)
    res.update(sres)
    nums.update(snums)
    return {"ok": all(res.values()), "checks": res, "numbers": nums}


# v0.38: SLICE at NOTE plays slice (note - 24) mod slices (from C1). The test BEAT's 16 slices
# are its 16 steps, "K.H.SHH.K.HKS.HH" (src/dnfw/sampler/live.py): slices 0, 2, 4, 8 are kick,
# hat, snare, kick, none of them a rest
SMP_CHORD_SLICES = (0, 2, 4, 8)


def step_smp_chords(init, sound, machines, blocks=12, only=()) -> tuple[dict, dict]:
    """v0.38: sample machines in chords. Four voice slots of one sample machine at once (four
    tracks, one note each, as the DN2's allocation spreads a chord), triggered together, BLOCKS
    blocks. ONESHOT and WERP on SAMP 4 at notes C E G C; SLICE (SLCE NOTE) on BEAT, slices 0,
    2, 4, 8 by notes (24 + k) << 8. For each: every voice sounds in every block after the
    attack, the DSP equals its model (smp_exact: no output or state mismatch), everything
    finite; ONESHOT's and WERP's voices pairwise distinct (their own notes); SLICE's each equal
    to its slice played alone. -> (checks, numbers)"""
    notes = (0x3C00, 0x4000, 0x4300, 0x4800)      # C, E, G, C
    slice_notes = tuple((24 + k) << 8 for k in SMP_CHORD_SLICES)
    cases = {
        "ONESHOT": (SM.TYPE_OF["ONESHOT"], smp_words({SM.SAMP_REC: 4}), notes),
        "WERP": (SM.TYPE_OF["WERP"], smp_words({SM.SAMP_REC: 4}), notes),
        "SLICE": (SM.TYPE_OF["SLICE"], smp_words({SM.SAMP_REC: 4, SM.SLICE_REC: 0}), slice_notes),
    }
    res, nums = {}, {}
    for name, (typ, words, nts) in cases.items():
        if only and name not in only:
            continue
        t0 = time.perf_counter()

        def fb(b, typ=typ, words=words, nts=nts):
            f = base_frame(sound, machines, t0=typ, overrides=words, trigger=b == 1,
                           others={t: typ for t in range(1, 4)}, trigger_others=True)
            for t in range(4):
                for slot, w in words.items():
                    f.param(t, slot, w)
                f.header(FR.NOTE, t, nts[t])
            return f.to_bytes()
        rr = run_blocks(init, fb, blocks)
        rr.pop("state", None)
        sounding = [sum(1 for t in range(4) if t in blk and V.peak(blk[t]["out"]) > 1e-4)
                    for blk in rr.get("smp", [])[3:]]
        n, om, sm = smp_exact(rr) if rr["ok"] else (0, -1, -1)
        series = [smp_series(rr, t) for t in range(4)]
        fin = rr["ok"] and all(math.isfinite(x) for blk in rr["buffers"] for t in range(16) for x in blk[t])
        all_sound = bool(sounding) and min(sounding) == 4
        nums[f"smp {name}"] = {"sounding": sounding, "model_blocks": n, "out_mismatches": om,
                               "state_mismatches": sm}
        if name == "SLICE":                 # each voice is its slice as it plays alone (two are kicks)
            alone = []
            for t in range(4):
                def fs(b, typ=typ, words=words, t=t):
                    f = base_frame(sound, machines, t0=typ, overrides=words, trigger=b == 1)
                    f.header(FR.NOTE, 0, slice_notes[t])
                    return f.to_bytes()
                r1 = run_blocks(init, fs, blocks)
                r1.pop("state", None)
                alone.append(series[t] == smp_series(r1, 0))
            nums[f"smp {name}"]["each_as_alone"] = alone
            res[f"{name} (sample, SLCE NOTE): a chord of BEAT's slices {', '.join(map(str, SMP_CHORD_SLICES))} on "
                f"four voices: all four sound in every block after the attack, each is its slice played alone, "
                f"the DSP equals its model, finite"] = bool(rr["ok"] and fin and all_sound and om == 0 and sm == 0
                                                             and all(alone))
        else:
            same = [(i, j) for i in range(4) for j in range(i + 1, 4) if series[i] == series[j]]
            nums[f"smp {name}"]["same_pairs"] = same
            res[f"{name} (sample): a four-note chord (SAMP 4, C E G C) on four voices: all four sound in every "
                f"block after the attack, the voices differ, the DSP equals its model, finite"] = bool(
                    rr["ok"] and fin and all_sound and om == 0 and sm == 0 and not same)
        nums[f"smp {name}"]["seconds"] = round(time.perf_counter() - t0)
        print(f"    smp {name}: {nums[f'smp {name}']}", flush=True)
    return res, nums


def _count_memory():
    """wrap every module's DM read and write: -> (counts dict, undo). Counts by region:
    L1 (the core's own), L2 (0x20000000..), DDR (0x80000000..)"""
    counts = {"L1": 0, "L2": 0, "DDR": 0, "on": False}

    import sys as _s0
    conc = _s0.modules["sharc_core.memory"]._concrete_address

    def region(a):
        a = conc(a)
        if a is None:
            return None
        if a >= 0x80000000:
            h = counts.get("hist")              # v0.36: where in DDR, by 4 KB page, when asked
            if h is not None:
                h[a >> 12] = h.get(a >> 12, 0) + 1
            return "DDR"
        return "L2" if 0x20000000 <= a < 0x20200000 else "L1"
    import sys as _s
    orig_r, orig_w = fx._dm_read, fx._dm_write

    def rd(state, address, width, *a, **k):
        if counts["on"]:
            g = region(address)
            if g:
                counts[g] += 1
        return orig_r(state, address, width, *a, **k)

    def wr(state, address, width, value):
        if counts["on"]:
            g = region(address)
            if g:
                counts[g] += 1
        return orig_w(state, address, width, value)
    patched = []
    for m in list(_s.modules.values()):
        for name, new in (("_dm_read", rd), ("_dm_write", wr)):
            if getattr(m, name, None) in (orig_r, orig_w) and getattr(m, name) is (orig_r if name == "_dm_read" else orig_w):
                patched.append((m, name, getattr(m, name)))
                setattr(m, name, new)

    def undo():
        for m, name, f in patched:
            setattr(m, name, f)
    return counts, undo


def step_cost(init, sound, machines) -> dict:
    """v0.33: what each machine costs the DSP, one voice sounding: instructions of our code a
    block, and its memory accesses by region (on the unit an L2 access costs several times an
    instruction, a DDR one about ten: complex-ping's measurements). Six blocks after the note,
    less a run with nothing sounding. Written to the report; docs/dsp-cost.md reads it."""
    from dnfw.mnm import machines as MMx
    counts, undo = _count_memory()
    rows = {}

    def measure(name, fb):
        ins = {}

        def at_perc(r):
            ins["a"] = r.steps_n
            counts["on"] = True

        def at_ping(r):
            ins.setdefault("sum", 0)
            ins["sum"] += r.steps_n - ins.get("a", r.steps_n)
            counts["on"] = False
        for k in ("L1", "L2", "DDR"):
            counts[k] = 0
        rr = run_blocks(init, fb, 8, extra_hooks={dsp.PERC_SW: at_perc, dsp.PING_SW: at_ping})
        n = 8
        rows[name] = {"ok": rr["ok"], "instructions": ins.get("sum", 0) // n,
                      **{k: counts[k] // n for k in ("L1", "L2", "DDR")}}

    # v0.34 (docs/timing-model.md): the whole block too, nothing sounding -- the stock's
    # unpack, its machines' standing work, the mix -- to calibrate the cost clock against
    # the unit: its silent frame takes about 416,000 cycles (reply word 0, docs/sharc-load.md),
    # 62 % of the 666,667. cycles = instructions + S x (4 L2 + 10 DDR) solved for S
    whole = {}

    def whole_block(name, fb):
        for k in ("L1", "L2", "DDR"):
            counts[k] = 0
        counts["on"] = True
        rr = run_blocks(init, fb, 4)
        counts["on"] = False
        whole[name] = {"instructions": rr.get("instructions", 0) // 4, **{k: counts[k] // 4 for k in ("L1", "L2", "DDR")}}
    try:
        whole_block("silent", lambda b: base_frame(sound, machines, trigger=False).to_bytes())
        whole_block("fm_tone_note", lambda b: base_frame(sound, machines, t0=0, trigger=b == 1).to_bytes())
        for k in ("L1", "L2", "DDR"):
            counts[k] = 0
        measure("(nothing)", lambda b: base_frame(sound, machines, trigger=False).to_bytes())
        # v0.43: DNFW_COST_ONLY=mnm measures the Monomachine machines alone (the whole run is 2 h)
        only = os.environ.get("DNFW_COST_ONLY", "")
        for k, name in enumerate(PM.NAMES if only != "mnm" else ()):
            measure(name, (lambda k: lambda b: base_frame(sound, machines, overrides=perc_words(k), trigger=b == 1).to_bytes())(k))
        for k, name in enumerate(MMx.NAMES):
            def fb(b, k=k):
                f = base_frame(sound, machines, t0=MMx.TYPES[k], trigger=b == 1)
                for slot, w in mnm_words(k).items():
                    f.param(0, slot, w)
                return f.to_bytes()
            measure(name, fb)
        for name in (("ONESHOT", "WERP", "STRETCH", "REPITCH", "GRID", "SLICE") if only != "mnm" else ()):
            measure(name, (lambda ty: lambda b: base_frame(sound, machines, t0=ty, trigger=b == 1,
                                                          overrides=smp_words({SM.SAMP_REC: 4})).to_bytes())(SM.TYPE_OF[name]))
    finally:
        undo()
    base = rows["(nothing)"]
    table = {k: {"instructions": v["instructions"] - base["instructions"], "L1": v["L1"] - base["L1"],
                 "L2": v["L2"] - base["L2"], "DDR": v["DDR"] - base["DDR"],
                 "estimate": (v["instructions"] - base["instructions"]) + 4 * (v["L2"] - base["L2"])
                 + 10 * (v["DDR"] - base["DDR"]), "ok": v["ok"]} for k, v in rows.items() if k != "(nothing)"}
    ok = all(v["ok"] for v in rows.values())
    sil = whole.get("silent", {})
    mem = 4 * sil.get("L2", 0) + 10 * sil.get("DDR", 0)
    scale = round((416_000 - sil.get("instructions", 0)) / mem, 3) if mem else None
    return {"ok": ok, "checks": {"every machine measured (every block returned)": ok},
            "numbers": {"per_voice_block": table, "nothing": base, "whole_block": whole,
                        "unit_silent_cycles": 416_000, "memory_weight_scale": scale}}


def step_garbage(init, sound, machines) -> dict:
    """v0.33 (the freeze and silence reports; complex-ping: power-on memory holds garbage, NaN
    common, and one NaN in a feedback state silences the unit): every Machinedrum and
    Monomachine machine started on voice state that is not what a previous note left -- the
    sixteen 1 KB voice slots in L2 and the Monomachine's shared scratch (keys, costs, the
    voice order) filled with 0xFFFFFFFF (NaN) or random words before the first block. Each
    run must return every block (no halt, no stray jump), the machine's track must be
    finite from the note's block on, and PERC's bit-exact to its model (which reads the same
    memory at entry)."""
    import random as _r
    from dnfw.mnm import machines as MMx
    fills = {"nan": lambda k: 0xFFFFFFFF, "random": (lambda g: lambda k: g.getrandbits(32))(_r.Random(33))}
    spans = [(dsp.MD_STATE_L2, 16 * 1024), (dsp.MNM_SCRATCH_L2, dsp.MNM_SCRATCH_BYTES),
             (dsp.MNM_RENDER_DM, dsp.MNM_RENDER_BYTES)]          # v0.43: the render scratch in L1
    res, bad = {}, []

    def filled(fill):
        done = {"n": 0}

        def poke(r):
            if done["n"]:
                return
            done["n"] = 1
            for a, n in spans:
                for k in range(0, n, 4):
                    m2.poke(r.state, a + k, fill(k))
        return {dsp.PERC_SW: poke}

    def finite_from(rr, t, b0=1):
        return rr["ok"] and all(math.isfinite(x) for blk in rr["buffers"][b0:] for x in blk[t])
    for fname, fill in fills.items():
        for g in range((PM.N + 7) // 8):         # the Machinedrum machines, eight tracks a run
            n_g = min(8, PM.N - 8 * g)

            def fb(b, g=g, n_g=n_g):
                f = base_frame(sound, machines, overrides=perc_words(8 * g), trigger=b == 1,
                               others={t: 5 for t in range(1, n_g)}, trigger_others=True)
                for t in range(1, n_g):
                    for slot, w in perc_words(8 * g + t).items():
                        f.param(t, slot, w)
                return f.to_bytes()
            rr = run_blocks(init, fb, 6, extra_hooks=filled(fill))
            ok = rr["ok"] and all(finite_from(rr, t) for t in range(n_g)) and perc_exact(rr)[1:] == (0, 0)
            res[f"{fname}_md{g}"] = {"ok": ok, "halt": rr.get("halt")}
            if not ok:
                bad.append(f"{fname}_md{g}")
        for k, name in enumerate(MMx.NAMES):    # each Monomachine machine, beside a PERC voice
            def fb(b, k=k):
                f = base_frame(sound, machines, t0=MMx.TYPES[k], trigger=b == 1, others={1: 5}, trigger_others=True)
                for slot, w in mnm_words(k).items():
                    f.param(0, slot, w)
                for slot, w in perc_words(0).items():
                    f.param(1, slot, w)
                return f.to_bytes()
            rr = run_blocks(init, fb, 6, extra_hooks=filled(fill))
            ok = rr["ok"] and finite_from(rr, 0) and finite_from(rr, 1)
            res[f"{fname}_{name}"] = {"ok": ok, "halt": rr.get("halt")}
            if not ok:
                bad.append(f"{fname}_{name}")
        print(f"    garbage {fname}: {len([k for k in res if k.startswith(fname)])} runs", flush=True)
    checks = {"every Machinedrum and Monomachine machine, started on NaN or random voice state and "
              "scratch: every block returns, its track finite, PERC bit-exact": not bad}
    return {"ok": not bad, "checks": checks, "numbers": {"failing": bad, "runs": res}}


def step_wipe(init, sound, machines) -> dict:
    """v0.34 (the owner's O13: P-I machines silent on the same voices every time; the cause:
    v0.33's output guard stored its loop counter instead of zeros when it wiped a voice, so
    a voice that once went non-finite never reset). For PI-BD and PI-RS on track 0: a note on
    block 1; from block 4 the voice's P-I delay lines are all NaN (as poisoned memory on the
    unit); the guard must wipe the voice once (BLOWN_COUNT 1, its slot and type recorded,
    WHERE naming the delay lines), the tainted block must be silent, the voice's state must
    be all zeros after that block, and a new note on block 8 must sound, finite, with no
    second wipe. PERC bit-exact to its model throughout (the model, like the core, carries a
    NaN input through every float operation)."""
    from dnfw.perc import guard as G
    from dnfw.md import core as MDK
    res, bad = {}, []
    for name in ("PI-BD", "PI-RS"):
        k = PM.NAMES.index(name)
        done = {"poked": 0, "state_after": None}

        def at_dispatch(r, done=done):
            # block 4's dispatch, before PERC's entry (where run_blocks runs the model on the
            # DSP's memory, so the model sees the poison too): the delay lines all NaN
            done["blocks"] = done.get("blocks", 0) + 1
            if done["blocks"] == 5 and not done["poked"]:
                done["poked"] = 1
                base = dsp.MD_DELAY_DDR
                for j in range(MDK.PI_DELAY_WORDS):
                    m2.poke(r.state, base + 4 * j, 0xFFC00000)

        def at_perc(r, done=done):
            # block 5's entry: the state the wipe left, and the record
            if done.get("blocks") == 6:
                done["state_after"] = [m2.word(r.state, dsp.PERC_STATE_DM + 4 * j) for j in range(32)]
                done["count_after"] = m2.word(r.state, G.BLOWN_COUNT)
                done["info"] = m2.word(r.state, G.BLOWN_INFO)
                done["where"] = m2.word(r.state, G.BLOWN_WHERE)
                done["word"] = m2.word(r.state, G.BLOWN_WORD)

        def fb(b, k=k):
            return base_frame(sound, machines, overrides=perc_words(k), trigger=b in (1, 8)).to_bytes()
        rr = run_blocks(init, fb, 12, extra_hooks={m3.DISPATCH: at_dispatch, dsp.PERC_SW: at_perc})
        st = rr.get("state")
        count_end = m2.word(st.state, G.BLOWN_COUNT) if rr["ok"] else None
        mask = m2.word(st.state, G.BLOWN_MASK) if rr["ok"] else None
        rr.pop("state", None)
        # PERC's own output for track 0 (what the guard left), not the buffer after the stock chain
        outs = [blk[0]["out"] if 0 in blk else [] for blk in rr["perc"]] if rr["ok"] else []
        peak = lambda b0, b1: max((abs(x) for blk in outs[b0:b1] for x in blk), default=0.0)   # noqa: E731
        tainted_silent = rr["ok"] and len(outs[4]) == 32 and all(x == 0.0 for x in outs[4])
        after = rr["ok"] and all(math.isfinite(x) for blk in outs[5:] for x in blk)
        checks = {
            "the note sounds before the poison (blocks 1..3)": rr["ok"] and peak(1, 4) > 0.01,
            "the poisoned block is silent (block 4)": tainted_silent,
            "the guard wiped the voice once, at that block": done.get("count_after") == 1 and count_end == 1,
            # (BLOWN_MASK is sent and cleared by the link's idle packet every block: the
            # ColdFire's copy is checked in test_perc_live and the link's unit test)
            "the record: slot 0, this machine, the delay lines, the NaN": done.get("info") == k << 8
                and done.get("where") == G.WHERE_DELAY and done.get("word") == 0xFFC00000,
            "the voice's state is all zeros after the wipe": done.get("state_after") is not None
                and all(w == 0 for w in done["state_after"]),
            "the new note sounds (blocks 8..11), finite": rr["ok"] and peak(8, 12) > 0.01 and after,
            "PERC bit-exact to its model": rr["ok"] and perc_exact(rr)[1:] == (0, 0),
        }
        res[name] = {"ok": all(checks.values()), "checks": checks, "halt": rr.get("halt"),
                     "debug": {"done": {k: v for k, v in done.items() if k != "state_after"}, "state_after": done.get("state_after"),
                               "count_end": count_end, "mask": mask, "peaks": [peak(b, b + 1) for b in range(12)],
                               "perc": perc_exact(rr) if rr["ok"] else None,
                               "mism": [(b, {t: (v["out_mismatches"], v["state_mismatches"]) for t, v in blk.items()}) for b, blk in enumerate(rr.get("perc", []))]}}
        if not res[name]["ok"]:
            bad.append(name)
        print(f"    wipe {name}: {'ok' if res[name]['ok'] else 'FAIL'}", flush=True)
    checks = {f"{name}: {c}": v for name, r in res.items() for c, v in r["checks"].items()}
    return {"ok": not bad, "checks": checks, "numbers": {"failing": bad, "runs": res}}


# -- step 3b: the sample machines (v0.13, docs/sampler.md) ----------------------------------------

def smp_words(values: dict | None = None) -> dict:
    """frame slot -> word for a sample machine: SL.Harness.defaults() plus VALUES
    {record: knob value 0..top}"""
    v = {SM.TUNE_REC: 60, SM.PLAY_REC: 127, SM.SAMP_REC: 1, SM.LEV_REC: SM.LEV_UNITY,
         SM.STRT_REC: 0, SM.LEN_REC: 127, SM.LOOP_REC: 0, SM.SLEN_REC: 0, **(values or {})}
    out = {}
    for rec, x in v.items():
        slot, lo, top = SM.RECORDS[rec]
        out[slot] = (min(top, max(0, x)) + lo) << 8
    return out


def smp_series(run, t) -> list[float]:
    return [x for blk in run["smp"] if t in blk for x in blk[t]["out"]]


def smp_exact(run) -> tuple[int, int, int]:
    n = o = st = 0
    for blk in run["smp"]:
        for v in blk.values():
            n += 1
            o += v["out_mismatches"]
            st += v["state_mismatches"]
    return n, o, st


def step_slicestatic(init, sound, machines, blocks) -> dict:
    """dreamsaremaps (v0.42): a SLICE track playing; SAMP scrolled onto an EMPTY slot at the
    moment a trig plays -> a blast of static. Track 0 SLICE on SAMP 4 (BEAT, loaded), a note on
    block 1; at block K another note, with SAMP an empty slot (90) from block K - 1, K or K + 1.
    Also the same on ONESHOT. Every block's output must stay finite and no louder than the
    sample itself; the blocks after the empty slot's note silent."""
    SLC, ONE = SM.TYPE_OF["SLICE"], SM.TYPE_OF["ONESHOT"]
    K = 5

    def frames(t0, at, slot=90, extra=None):
        def fb(b):
            w = smp_words({SM.SAMP_REC: slot if b >= at else 4, SM.SLICE_REC: 6, **(extra or {})})
            return base_frame(sound, machines, t0=t0, overrides=w, trigger=b in (1, K)).to_bytes()
        return fb
    runs = {}
    for t0, nm in ((SLC, "slice"), (ONE, "one")):
        for at in (K - 1, K, K + 1):
            runs[f"{nm}_at{at - K:+d}"] = run_blocks(init, frames(t0, at), blocks)
        runs[f"{nm}_ref"] = run_blocks(init, frames(t0, 10 ** 6), blocks)   # never empty
    peaks = {k: [round(max((abs(x) for x in blk[0]["out"]), default=0.0), 3) if 0 in blk else None
                 for blk in r["smp"]] for k, r in runs.items() if r["ok"]}
    ref = {nm: max(peaks[f"{nm}_ref"][:K]) for nm in ("slice", "one")}
    checks = {
        "every run ran": all(r["ok"] for r in runs.values()),
        "nothing non-finite anywhere": all(math.isfinite(x) for r in runs.values() for blk in r["smp"]
                                           for v in blk.values() for x in v["out"]),
        "with SAMP on an empty slot a block before or at the note: the old note fades over the note's "
        "block, no louder than the sample itself, then silence; a block after it: the note keeps the "
        "sample it latched (as the reference run)":
            all(max(peaks[k][K - 1:K + 1]) <= ref[nm] * 1.001 and max(peaks[k][K + 1:]) == 0.0
                for nm in ("slice", "one") for k in (f"{nm}_at-1", f"{nm}_at+0"))
            and all(peaks[f"{nm}_at+1"] == peaks[f"{nm}_ref"] for nm in ("slice", "one")),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": {"peaks": peaks, "ref": ref}, "runs": runs}


def step_smp(init, sound, machines, blocks) -> dict:
    def rb(*args, **kw):                # a run without its final DSP memory: 12 runs, held at once
        r = run_blocks(*args, **kw)
        r.pop("state", None)
        return r

    ONE, GRID, WERP = SM.TYPE_OF["ONESHOT"], SM.TYPE_OF["GRID"], SM.TYPE_OF["WERP"]

    def frames(t0, words, others=None, other_words=None, trig=(1,), note=0x3C00):
        def fb(b):
            f = base_frame(sound, machines, t0=t0, overrides=words, note=note, trigger=b in trig,
                           others=others, trigger_others=True)
            for t, ws in (other_words or {}).items():
                for slot, w in ws.items():
                    f.param(t, slot, w)
            return f.to_bytes()
        return fb

    runs = {}
    t0 = time.perf_counter()
    runs["kick"] = rb(init, frames(ONE, smp_words()), blocks)
    runs["kick_up"] = rb(init, frames(ONE, smp_words({SM.TUNE_REC: 72})), blocks)
    # four sample voices, PERC and a machine with no renderer side by side: track 0 the
    # snare reversed, 1 GRID slicing BEAT, 2 PERC TRX-SD, 3 WERP (silent), 4 the hat
    # looping forward, 5 FM Tone
    sd = PM.NAMES.index("TRX-SD")
    runs["mixed"] = rb(init, frames(
        ONE, smp_words({SM.SAMP_REC: 2, SM.PLAY_REC: 0}),
        others={1: GRID, 2: 5, 3: WERP, 4: ONE, 5: 0},      # (3: WERP, on its defaults)
        other_words={1: smp_words({SM.SAMP_REC: 4, SM.GRID_REC: 48, SM.SLICE_REC: 40}),
                     2: perc_words(sd), 3: smp_words(),
                     4: smp_words({SM.SAMP_REC: 3, SM.PLAY_REC: 80, SM.LOOP_REC: 20})}), blocks)
    # v0.15, the time machines at 140 BPM: track 0 WERP on BEAT (1/8 bar, 64 segments,
    # FWD LOOP segments), 1 STRETCH on KICK (1/8 bar), 2 REPITCH on SNARE (1/4 bar)
    STR, REP = SM.TYPE_OF["STRETCH"], SM.TYPE_OF["REPITCH"]

    def timed(b):
        f = base_frame(sound, machines, t0=WERP, trigger=b == 1, others={1: STR, 2: REP},
                       trigger_others=True,
                       overrides=smp_words({SM.SAMP_REC: 4, SM.BARS_REC: 0, SM.SEG_REC: 20,
                                            SM.MODE_REC: 80}))
        for t, ws in ((1, smp_words({SM.SAMP_REC: 1, SM.BARS_REC: 0})),
                      (2, smp_words({SM.SAMP_REC: 2, SM.BARS_REC: 13}))):
            for slot, w in ws.items():
                f.param(t, slot, w)
        f.put(SP.TEMPO_OFFSET, 140 * 120)
        return f.to_bytes()
    runs["timed"] = rb(init, timed, blocks)
    # v0.14: CFAD, a short forward loop on the hat, with and without the crossfade
    loopw = {SM.SAMP_REC: 3, SM.PLAY_REC: 80, SM.LOOP_REC: 5, SM.LEN_REC: 10}
    runs["cfad"] = rb(init, frames(ONE, smp_words(loopw | {SM.CFAD_REC: 100})), blocks)
    runs["nocfad"] = rb(init, frames(ONE, smp_words(loopw)), blocks)
    runs["off"] = rb(init, frames(ONE, smp_words({SM.SAMP_REC: 0})), blocks)
    runs["empty_slot"] = rb(init, frames(ONE, smp_words({SM.SAMP_REC: 90})), blocks)
    runs["silent"] = rb(init, frames(ONE, smp_words(), trig=()), blocks)
    # v0.45: FASCIA (type 18) on track 1 beside ONESHOT on track 0, both triggered, its 24
    # controls at its defaults (and the zero ones at mid): smp.asm leaves it alone (a type-18 slot
    # is not a sample machine), and FASCIA's own program renders it (dnfw.fascia.program)
    from dnfw.fascia import machines as FSx    # noqa: PLC0415
    fsw = {FSx.SLOTS[c][1]: FSx.default_words()[c] or 0x4000 for c in FSx.CONTROLS}
    runs["fascia"] = rb(init, frames(ONE, smp_words(), others={1: FSx.TYPE}, other_words={1: fsw}), blocks)

    # v0.33: an entry that does not lie in the pool (half-written, stale, garbage) plays as
    # an empty slot: the hat's (SAMP 3) entry overwritten each block at PERC's entry, before
    # the sample machines (and their model) read it
    def bad_entry(base, frames_, fmt):
        def poke(r):
            ent = dsp.SMP_POOL_DDR + 8 + 16 * 2
            for k, w in enumerate((base, frames_, 48000, fmt)):
                m2.poke(r.state, ent + 4 * k, w & 0xFFFFFFFF)
        return {dsp.PERC_SW: poke}              # (before the machines' model reads it at SMP_SW)
    hat = smp_words({SM.SAMP_REC: 3})
    for name, args in (("bad_below", (0x80000000, 48000, 1)), ("bad_above", (dsp.SMP_POOL_DDR + SM.POOL_BYTES, 4800, 1)),
                       ("bad_long", (dsp.SMP_POOL_DDR + 0x1000, 0x7FFFFFFF, 1)),
                       ("bad_end", (dsp.SMP_POOL_DDR + SM.POOL_BYTES - 0x100, 4800, 1)),
                       ("bad_fmt", (dsp.SMP_POOL_DDR + 0x1000, 4800, 7)), ("bad_zero", (dsp.SMP_POOL_DDR + 0x1000, 0, 1))):
        runs[name] = rb(init, frames(ONE, hat), blocks, extra_hooks=bad_entry(*args))
    # (and on a SLICE track, with the bad entry claiming slices: none is read; the review's case)
    runs["bad_slices"] = rb(init, frames(SM.TYPE_OF["SLICE"], smp_words({SM.SAMP_REC: 3, SM.SLICE_REC: 6})), blocks,
                            extra_hooks=bad_entry(0x80000000, 48000, 1 | 8 << 8))
    runs["retrig"] = rb(init, frames(ONE, smp_words(), trig=(1, RETRIG)), blocks)
    runs["tops"] = rb(init, frames(GRID, smp_words({r: 127 for r in SM.RECORDS})), blocks)
    # v0.19, SLICE on BEAT's own sixteen slices: slice 3 and the next; NOTE, C1 + 5 (the sixth)
    SLC = SM.TYPE_OF["SLICE"]
    runs["slice"] = rb(init, frames(SLC, smp_words({SM.SAMP_REC: 4, SM.SLICE_REC: 6, SM.SLEN_REC: 2})), blocks)
    runs["slice_note"] = rb(init, frames(SLC, smp_words({SM.SAMP_REC: 4, SM.SLICE_REC: 0}),
                                         note=(24 + 5) << 8), blocks)
    runs["bottoms"] = rb(init, frames(ONE, smp_words({r: 0 for r in SM.RECORDS} | {SM.SAMP_REC: 1,
                                                                                       SM.LEV_REC: 100})), blocks)
    print(f"    sample machines: {round(time.perf_counter() - t0)} s", flush=True)
    ok_runs = all(r["ok"] for r in runs.values())
    exact = {k: smp_exact(r) for k, r in runs.items() if r["ok"]}
    mx = runs["mixed"]
    kick = smp_series(runs["kick"], 0)
    up = smp_series(runs["kick_up"], 0)
    # v0.18: the kick as the DSP played it against the DT2's own reader (the bit-exact model
    # of its code, outside the repository: ../dt2s117/research/tools/models_reader.py), times
    # LEV's make-up gain; 0.25 frames a 96 kHz sample
    kick_err = 1.0
    dt2_models = ROOT.parent / "dt2s117" / "research" / "tools"
    if (dt2_models / "models_reader.py").is_file():
        sys.path.insert(0, str(dt2_models))
        import models_reader as MR
        pcm = [max(-32768, min(32767, round(x * 32768))) for x in SL.test_samples()[0]]
        mv = MR.Voice(pcm, 0, 0, len(pcm) << 31, 1 << 29, 0)
        g = struct.unpack("<f", SP.tables_bytes()[-4:])[0]
        exp = []
        for _ in range(len(kick) // BLOCK - 1):
            exp += [g * float(x) for x in MR.read_block(mv, MR.load_polyphase())]
        kick_err = max((abs(a - b) for a, b in zip(kick[BLOCK:], exp)), default=1.0)
    werp_buf = [x for blk in mx["buffers"][1:] for x in blk[3]] if mx["ok"] else []
    rev = smp_series(mx, 0) if mx["ok"] else []
    rev_grows = len(rev) >= 4 * BLOCK and V.rms(rev[-2 * BLOCK:]) > V.rms(rev[BLOCK:3 * BLOCK])
    off = smp_series(runs["off"], 0)
    empty = smp_series(runs["empty_slot"], 0)
    silent = smp_series(runs["silent"], 0)
    rt, one = smp_series(runs["retrig"], 0), kick
    n = {"smp_exact_voice_blocks_out_state_mismatches": exact,
         "peaks_mixed": {t: V.peak(smp_series(mx, t)) for t in (0, 1, 4)} if mx["ok"] else None,
         "kick_vs_sample_max_err": kick_err,
         "zero_crossings_kick_kick_up": (zero_crossings(kick), zero_crossings(up)),
         "smp_entries_kick": runs["kick"].get("smp_entries"),
         "perc_in_mixed": perc_exact(mx) if mx["ok"] else None,
         "werp_peak": V.peak(werp_buf) if werp_buf else None,
         "timed_peaks": [V.peak(smp_series(runs["timed"], t)) for t in (0, 1, 2)] if runs["timed"]["ok"] else None,
         "model_steps_per_block": {k: max((v["model_steps"] for blk in r["smp"] for v in blk.values()), default=0)
                                   for k, r in runs.items() if r["ok"]},
         "instructions_per_block_mixed": round(mx.get("instructions", 0) / max(blocks, 1)),
         "halts": {k: r.get("halt") for k, r in runs.items() if not r["ok"]}}
    checks = {
        "every run returns every block": ok_runs,
        "the sample machines are entered from PERC's tail, once a block": runs["kick"].get("smp_entries") == blocks,
        "every rendered sample track's buffer and state, every block of every run, are bit-exact to "
        "dnfw.sampler.program run on the DSP's memory at its entry":
            ok_runs and all(v[0] > 0 and v[1] == 0 and v[2] == 0 for v in exact.values()),
        "v0.18: ONESHOT plays KICK from the pool as the DT2's reader does (max error < 2^-13)": kick_err < 2.0 ** -13,
        "TUNE +12 is higher (more zero crossings)": zero_crossings(up) > zero_crossings(kick) > 0,
        "in the mixed run, GRID's slice and the looping hat sound (peak > 0.05); the reversed "
        "snare, which starts at its quiet end, sounds (> 0.01) and grows":
            bool(n["peaks_mixed"]) and n["peaks_mixed"][1] > 0.05 and n["peaks_mixed"][4] > 0.05
            and n["peaks_mixed"][0] > 0.01 and rev_grows,
        "PERC beside them is bit-exact to its model and sounds":
            mx["ok"] and perc_exact(mx)[0] > 0 and perc_exact(mx)[1:] == (0, 0)
            and V.peak(perc_series(mx, 2)) > 0.05,
        "v0.15: WERP, STRETCH and REPITCH at 140 BPM sound (peak > 0.05), bit-exact (above)":
            runs["timed"]["ok"] and all(V.peak(smp_series(runs["timed"], t)) > 0.05 for t in (0, 1, 2)),
        "v0.18: CFAD is gone (the DT2's ONESHOT has no such control): its record changes nothing; the loop sounds":
            runs["cfad"]["ok"] and runs["nocfad"]["ok"]
            and V.peak(smp_series(runs["cfad"], 0)) > 0.01
            and smp_series(runs["cfad"], 0) == smp_series(runs["nocfad"], 0),
        "v0.19: SLICE plays BEAT's own slices, by SLCE and by the note (peak > 0.05; bit-exact above)":
            all(runs[k]["ok"] and V.peak(smp_series(runs[k], 0)) > 0.05 for k in ("slice", "slice_note")),
        "v0.33: an entry outside the pool (below, above, too long, past its end, an unknown format, no "
        "frames) plays as an empty slot: silent, finite, bit-exact (above)":
            all(runs[k]["ok"] and all(x == 0.0 for x in smp_series(runs[k], 0))
                for k in ("bad_below", "bad_above", "bad_long", "bad_end", "bad_fmt", "bad_zero", "bad_slices")),
        "SAMP 0 (OFF), an empty slot and no trigger are silent":
            all(s and all(x == 0.0 for x in s) for s in (off, empty, silent)),
        "v0.45: a FASCIA voice (type 18, triggered, its controls set) beside ONESHOT: FASCIA's buffer is "
        "FASCIA's program's (bit-exact to its model every block), ONESHOT sounds and is bit-exact":
            runs["fascia"]["ok"] and len(runs["fascia"]["fsc"]) > 0
            and fsc_exact(runs["fascia"])[0] == len(runs["fascia"]["fsc"])
            and fsc_exact(runs["fascia"])[1:] == (0, 0)
            and smp_exact(runs["fascia"])[1:] == (0, 0)
            and V.peak(smp_series(runs["fascia"], 0)) > 0.05,
        "a second note restarts the sample": bool(rt) and rt[:BLOCK * RETRIG] == one[:BLOCK * RETRIG]
            and rt[BLOCK * RETRIG:] != one[BLOCK * RETRIG:],
        "nothing non-finite or above 4.0 in any sample buffer":
            ok_runs and all(math.isfinite(x) and abs(x) <= 4.0 for r in runs.values() for blk in r["smp"]
                            for v in blk.values() for x in v["out"]),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": n, "runs": runs}


# -- step 3c: the sample link and the stock voices (v0.20, docs/sampler.md) ---------------------

def step_link(snap, m2mach, m5, stock, sound, machines, blocks) -> dict:
    """v0.20: the sample link's traffic leaves the stock voices alone. v0.14..v0.19 put
    packets in the frame's words 2650..2681, the DSP's per-track routing: WaveTone and FM
    buzzed after a sample track was used (the owner's report on v0.19). Now everything,
    commands too, comes over the TDM link (slots 8..15). Two runs on our image, track 0 a
    ONESHOT and WaveTone, FM Tone, FM Drum, Swarmer on tracks 1..4, all triggered: one with
    a packet every block (pool words, then MONITOR, VERIFY, ARM, STOP commands, each sent
    as the ColdFire sends them, several blocks running), one with stock's zeros in those
    slots; and the same tracks on the stock image. Tracks 1..15 must be bit-identical in
    all three; the frame's routing words are stock's in every frame (the runner's frame
    builder writes them as stock's does: nothing of ours touches them)."""
    import random
    rnd = random.Random(20)
    n = max(blocks, 16)
    ONE = SM.TYPE_OF["ONESHOT"]
    others = {1: 1, 2: 0, 3: 2, 4: 3}
    base_w = (SM.DATA_OFFSET + 0x30000) // 4
    cmds = {4: (1, SM.CMD_MONITOR, 0, 0, 1000, 0), 8: (2, SM.CMD_VERIFY, base_w, 124 * 3, 0, 0),
            11: (3, SM.CMD_ARM, 1, 0, 32000, (2 << 24) | 2000), 14: (4, SM.CMD_STOP, 1, 0, 0, 0)}

    def traffic(r, b):
        pg = (m2.word(r.state, SM.TDM_PAGE) or 0) & 1
        rx = SM.TDM_RX + (pg << 11) + 32
        live = [c for k, c in cmds.items() if k <= b < k + 3]
        if live:
            u = SL.rx_units(SM.CMD_OFFSET // 4, list(live[0]), b)
        else:
            u = SL.rx_units(base_w + 124 * (b % 3), [rnd.randrange(1 << 32) for _ in range(124)], b)
        for o, w in SL.rx_page(u, high=b % 2 == 0).items():
            m2.poke(r.state, rx + o, w)

    def frames(t0):
        return lambda b: base_frame(sound, machines, t0=t0, others=others, trigger=(b == 1),
                                    trigger_others=True,
                                    overrides=smp_words({SM.SAMP_REC: 1}) if t0 == ONE else None).to_bytes()
    state = {"b": 0}

    def at_dispatch(r):
        traffic(r, state["b"])
        state["b"] += 1
    runs = {"traffic": run_blocks(init_on(snap, m2mach, m5), frames(ONE), n,
                                  extra_hooks={m3.DISPATCH: at_dispatch}),
            "quiet": run_blocks(init_on(snap, m2mach, m5), frames(ONE), n),
            "stock": run_blocks(init_on(snap, m2mach, stock), frames(4), n)}
    ok_runs = all(r["ok"] for r in runs.values())

    def tail(r):
        return [blk[1:] for blk in r["buffer_bits"]]
    sounding = [t for t in (1, 2, 3, 4) if ok_runs and any(any(blk[t]) for blk in runs["stock"]["buffer_bits"])]
    stat = []
    if ok_runs:
        st = runs["traffic"]["state"].state
        for k in range(8):
            w = m2.word(st, SM.REPLY_PAGES[0] + SM.REPLY_TAIL + 4 * k) or 0
            stat += [w & 0xFFFF, w >> 16]
    for r in runs.values():
        r.pop("state", None)
    checks = {
        "the three runs return every block": ok_runs,
        "WaveTone, FM Tone, FM Drum and Swarmer sound in the stock run (tracks 1..4)":
            sorted(sounding) == [1, 2, 3, 4],
        f"with a link packet every block ({n} blocks: pool words and four commands), tracks "
        "1..15 bit-identical to the run without, and to the stock image's":
            ok_runs and tail(runs["traffic"]) == tail(runs["quiet"]) == tail(runs["stock"]),
        "the commands arrived by the TDM link: the status echoes the last (STOP, sequence 4)":
            ok_runs and stat[1] == 4 and stat[15] == (SM.LINK_SEED + sum(stat[:15])) & 0xFFFF,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"status": stat, "sounding": sounding,
                        "halts": {k: r.get("halt") for k, r in runs.items() if not r["ok"]}}}


# -- step 3d: the recorder (docs/sampler.md) ------------------------------------------------------

def step_rec(init, sound, machines, blocks) -> dict:
    """The recorder (v0.15), driven as the ColdFire drives it: commands written into the
    pool's command block (dnfw.sampler.machines.CMD_OFFSET). Run 1: RECORD NOW from IN
    (the engine's input block, poked in at the dispatch, as the per-block driver would
    have converted it) into SAMP 124, STOP, then SAMP 124 plays it back. Run 2: RECORD NOW
    from TRK6, MONO L, into SAMP 125: track 6's panned block (poked into its slot of the
    buffer 0x1c244d fills, its routing half set to 5). Both: the recorded int16 frames
    are the model's, the status in both reply pages checks out, every sample track is
    bit-exact."""
    import math as _m
    n = max(blocks, 12)
    sig = [0.6 * _m.sin(2 * _m.pi * 330 * k / 48000) for k in range(32 * n)]
    ONE = SM.TYPE_OF["ONESHOT"]
    cmd_at = dsp.SMP_POOL_DDR + SM.CMD_OFFSET

    def bits(x):
        return struct.unpack("<I", struct.pack("<f", x))[0]

    def command(r, seq, cmd, src=0, chan=0, dest=0, frames=SM.REC_FRAMES, place=0, thres=0):
        # v0.22: DEST the slot, PLACE where in the recordings' area (512-byte units)
        for k, w in enumerate((seq, cmd, src, chan | place << 8, thres, (SM.REC_FIRST + dest) << 24 | frames)):
            m2.poke(r.state, cmd_at + 4 * k, w)

    def status(st):
        out = []
        for page in SM.REPLY_PAGES:
            h = []
            for k in range(8):
                w = m2.word(st, page + SM.REPLY_TAIL + 4 * k) or 0
                h += [w & 0xFFFF, w >> 16]
            out.append(h)
        return out

    def ok_status(h):
        return h[15] == (SM.LINK_SEED + sum(h[:15])) & 0xFFFF and h[0] & 0xFF00 == SM.STATUS_MAGIC

    def recorded(st, slot):
        ent = dsp.SMP_POOL_DDR + 8 + 16 * (SM.REC_FIRST + slot)
        words = [m2.word(st, ent + 4 * k) or 0 for k in range(4)]
        got = []
        for k in range(words[1] // 2):
            w = m2.word(st, words[0] + 4 * k) or 0
            for h in (w & 0xFFFF, w >> 16):
                got.append((h - 65536 if h >= 32768 else h) / 32768.0)
        return words, got

    play = 4

    # run 1: IN
    def frames_1(b):
        w = smp_words({SM.SAMP_REC: 1}) if b < n else smp_words({SM.SAMP_REC: SM.REC_FIRST + 1})
        return base_frame(sound, machines, t0=ONE, trigger=(b == n), overrides=w).to_bytes()
    state = {"b": 0}

    def at_dispatch_1(r):
        b = state["b"]
        if b == 0:
            command(r, 1, SM.CMD_NOW, src=0, dest=0)
        if b == n:
            command(r, 2, SM.CMD_STOP)
        if b == n + 2:                       # v0.25: PREVIEW frames [11, 101) of it: [10, 101)
            command(r, 3, SM.CMD_PREVIEW, src=SM.REC_FIRST, chan=11, thres=101)
        for k in range(32):
            x = bits(sig[32 * b + k] if b < n else 0.0)
            m2.poke(r.state, SM.IN_BUF + 4 * k, x)
            m2.poke(r.state, SM.IN_BUF + 0x80 + 4 * k, x)
        state["b"] += 1
    rec = run_blocks(init, frames_1, n + play, extra_hooks={m3.DISPATCH: at_dispatch_1})
    ok1 = rec["ok"]
    st = rec["state"].state if ok1 else None
    words, got = recorded(st, 0) if ok1 else ([0] * 4, [])
    want = [max(-32768, min(32767, int(x * 32768.0))) / 32768.0 for x in sig[:words[1]]]
    stat1 = status(st) if ok1 else []
    back = smp_series(rec, 0)[-play * BLOCK:] if ok1 else []
    exact1 = smp_exact(rec) if ok1 else (0, 1, 1)
    C = SL.layout().C
    pv1 = (m2.word(st, C["pva"]), m2.word(st, C["pvn"])) if ok1 else None
    rec.pop("state", None)

    # v0.33: +DRIVE's preview, at an offset into the pool (PREVIEW_AT): 4,800 frames at 64 KB
    # in; then one past the pool's end and too long, held to its last ten seconds' room
    pv_at = {}
    for name, (off, fr) in (("at", (0x10000, 4800)), ("clamped", (0x7FFFFFF0, 0x7FFFFFFF))):
        def at_dispatch_p(r, off=off, fr=fr, seen={"b": 0}):
            if seen["b"] == 1:
                command(r, 9, SM.CMD_PREVIEW, src=SP.PREVIEW_AT, chan=off, thres=fr)
            seen["b"] += 1

        def frames_p(b):
            return base_frame(sound, machines, t0=ONE, trigger=False, overrides=smp_words({SM.SAMP_REC: 1})).to_bytes()
        rp = run_blocks(init, frames_p, 3, extra_hooks={m3.DISPATCH: at_dispatch_p})
        sp = rp["state"].state if rp["ok"] else None
        pv_at[name] = (m2.word(sp, C["pva"]), m2.word(sp, C["pvn"]), m2.word(sp, C["pvl0"])) if rp["ok"] else None
        rp.pop("state", None)

    # run 2: TRK6, MONO L
    g = SM.TRK_GAIN
    left = [0.3 * _m.sin(2 * _m.pi * 500 * k / 48000) for k in range(32 * n)]
    right = [-0.7] * (32 * n)
    state2 = {"b": 0}

    def at_dispatch_2(r):
        b = state2["b"]
        if b == 0:
            command(r, 7, SM.CMD_NOW, src=2 + 5, chan=1, dest=1, place=0x4000)
        # v0.22: track 6 is bucket 5 whatever the voices' routing says (here every voice
        # in reach plays track 10): the recorder reads the track's bucket, not route[t]'s
        route = SM.TRK_ROUTE + 2 * 4                     # voices 4, 5: halves of one word
        m2.poke(r.state, route, 9 | 9 << 16)
        for k in range(32):
            m2.poke(r.state, SM.TRK_BUF + SM.TRK_STRIDE * 5 + 4 * k, bits(left[32 * b + k] * g))
            m2.poke(r.state, SM.TRK_BUF + SM.TRK_STRIDE * 5 + 0x80 + 4 * k, bits(right[32 * b + k] * g))
        state2["b"] += 1

    def frames_2(b):
        return base_frame(sound, machines, t0=ONE, trigger=False, overrides=smp_words({SM.SAMP_REC: 1})).to_bytes()
    rec2 = run_blocks(init, frames_2, n, extra_hooks={m3.DISPATCH: at_dispatch_2})
    ok2 = rec2["ok"]
    st2 = rec2["state"].state if ok2 else None
    words2, got2 = recorded(st2, 1) if ok2 else ([0] * 4, [])
    want2 = []
    for k in range(words2[1]):
        x = min(0.999969, max(-1.0, (left[k] * g + left[k] * g) * 0.5 * (1.0 / g)))
        want2.append(max(-32768, min(32767, int(x * 32768.0))) / 32768.0)
    stat2 = status(st2) if ok2 else []
    exact2 = smp_exact(rec2) if ok2 else (0, 1, 1)
    rec2.pop("state", None)
    close2 = bool(got2) and max(abs(a - b) for a, b in zip(got2, want2)) <= 2 / 32768

    # run 3, v0.37: MAIN, L+R (the owner: resampling MAIN recorded an empty sample; MIX_BUF is
    # empty while our code runs, so MAIN reads the tap pvmix fills at the master mix call,
    # SM.MAIN_TAP: poked here as pvmix would leave it, and MIX_BUF itself left empty)
    mainL = [0.4 * _m.sin(2 * _m.pi * 220 * k / 48000) for k in range(32 * n)]
    mainR = [0.2] * (32 * n)
    state3 = {"b": 0}

    def at_dispatch_3(r):
        b = state3["b"]
        if b == 0:
            command(r, 11, SM.CMD_NOW, src=1, chan=0, dest=2, place=0x8000)
        for k in range(32):
            m2.poke(r.state, SM.MAIN_TAP + 4 * k, bits(mainL[32 * b + k]))
            m2.poke(r.state, SM.MAIN_TAP + 0x80 + 4 * k, bits(mainR[32 * b + k]))
            m2.poke(r.state, SM.MIX_BUF + 4 * k, 0)
            m2.poke(r.state, SM.MIX_BUF + 0x80 + 4 * k, 0)
        state3["b"] += 1
    rec3 = run_blocks(init, frames_2, n, extra_hooks={m3.DISPATCH: at_dispatch_3})
    ok3 = rec3["ok"]
    st3 = rec3["state"].state if ok3 else None
    words3, got3 = recorded(st3, 2) if ok3 else ([0] * 4, [])
    want3 = [max(-32768, min(32767, int(min(0.999969, max(-1.0, (a + b) * 0.5)) * 32768.0))) / 32768.0
             for a, b in zip(mainL, mainR)][:words3[1]]
    rec3.pop("state", None)
    close3 = bool(got3) and max(abs(a - b) for a, b in zip(got3, want3)) <= 2 / 32768

    # run 4, v0.38: ARM (blskk on v0.37: THRES 0 "catches everything"). IN carries a noise
    # floor at about -50 dB (a hiss with a DC offset: over v0.30's fixed -60 dB floor, as an
    # input with something plugged in can be) for the first `quiet` blocks, then a tone at
    # -14 dB. THRES 0 (the ColdFire's word, 33): armed through the noise, it starts on the
    # tone's first block. A set threshold (THRES 60, the word 16383, the DT2's plain
    # threshold): the same input, a -14 dB tone stays under it, so it waits; then a -4 dB
    # one starts it, on its first block
    quiet = n // 2

    def noise(k):
        return 0.0015 + 0.0012 * (((k * 2654435761) >> 7 & 0xFFFF) / 32768.0 - 1.0)

    def arm_run(thres, tone_at, tone, seq, dest, place, n=n):
        st4 = {"b": 0}
        sig4 = [noise(k) + (tone * _m.sin(2 * _m.pi * 440 * k / 48000) if k >= 32 * tone_at else 0.0)
                for k in range(32 * n)]

        def at_dispatch_4(r):
            b = st4["b"]
            if b == 0:
                command(r, seq, SM.CMD_ARM, src=0, chan=0, dest=dest, place=place, thres=thres)
            for k in range(32):
                x = bits(sig4[32 * b + k])
                m2.poke(r.state, SM.IN_BUF + 4 * k, x)
                m2.poke(r.state, SM.IN_BUF + 0x80 + 4 * k, x)
            st4["b"] += 1
        r4 = run_blocks(init, frames_2, n, extra_hooks={m3.DISPATCH: at_dispatch_4})
        if not r4["ok"]:
            return None
        w4, g4 = recorded(r4["state"].state, dest)
        r4.pop("state", None)
        want4 = [max(-32768, min(32767, int(min(0.999969, max(-1.0, x)) * 32768.0))) / 32768.0
                 for x in sig4[32 * tone_at:]][:w4[1]]
        return w4[1], bool(g4) and g4 == want4
    # (v0.39: THRES 0 learns the floor over its first REC_AUTO_LEARN blocks; the tone after them)
    quiet_a = getattr(SP, "REC_AUTO_LEARN", 0) + 2
    auto = arm_run(33, quiet_a, 0.2, 13, 3, 0xC000, n=quiet_a + 6)
    plain_low = arm_run(16383, quiet, 0.2, 14, 3, 0xC000)
    plain = arm_run(16383, quiet, 0.63, 15, 3, 0xC000)

    # run 5, v0.44 BOUNCE: RECORD NOW from IN into a buffer half (dest BUF_SLOT0: the buffer
    # directory's entry 0, SAMP 129), 4 steps, STOP after n blocks; then track 0 BOUNCE on
    # SAMP 129 at 120 BPM plays it back (STRETCH, fitted to its steps). The directory entry
    # is address, frames, steps (no rate, no format: int16 at 1.0), the playback bit-exact
    BNC = SM.TYPE_OF["BOUNCE"]
    steps5 = 4
    state5 = {"b": 0}

    def at_dispatch_5(r):
        b = state5["b"]
        if b == 0:
            command(r, 17, SM.CMD_NOW, src=0, dest=SM.BUF_SLOT0 - SM.REC_FIRST, place=0x5000, thres=steps5 << 16)
        if b == n:
            command(r, 18, SM.CMD_STOP)
        for k in range(32):
            x = bits(sig[32 * b + k] if b < n else 0.0)
            m2.poke(r.state, SM.IN_BUF + 4 * k, x)
            m2.poke(r.state, SM.IN_BUF + 0x80 + 4 * k, x)
        state5["b"] += 1

    def frames_5(b):
        if b < n:
            f = base_frame(sound, machines, t0=ONE, trigger=False, overrides=smp_words({SM.SAMP_REC: 1}))
        else:
            f = base_frame(sound, machines, t0=BNC, trigger=(b == n), overrides=smp_words({SM.SAMP_REC: SM.BUF_SAMP0}))
        f.put(SP.TEMPO_OFFSET, 120 * 120)
        return f.to_bytes()
    rec5 = run_blocks(init, frames_5, n + play, extra_hooks={m3.DISPATCH: at_dispatch_5})
    ok5 = rec5["ok"]
    st5 = rec5["state"].state if ok5 else None
    bent = dsp.SMP_POOL_DDR + SM.BUF_DIR
    words5 = [m2.word(st5, bent + 4 * k) or 0 for k in range(3)] if ok5 else [0, 0, 0]
    got5 = []
    if ok5:
        for k in range(words5[1] // 2):
            w = m2.word(st5, words5[0] + 4 * k) or 0
            for h in (w & 0xFFFF, w >> 16):
                got5.append((h - 65536 if h >= 32768 else h) / 32768.0)
    back5 = smp_series(rec5, 0)[-play * BLOCK:] if ok5 else []
    exact5 = smp_exact(rec5) if ok5 else (0, 1, 1)
    rec5.pop("state", None)

    # v0.22: the RAM check (CMD_PROBE) on the image's own code. Block 0 takes the command
    # and fills the low area's first 256 words; then the last chunk of phase 3 and of
    # phase 4 are set up (both areas' last 256 words as the fills would leave them; the
    # phases between are the same loop) and each runs in a block: the verdict is 1, and
    # 2 when one word of the high area is wrong
    pn = SM.PROBE_BYTES // 4
    lo, hi = dsp.SMP_POOL_DDR + SM.PROBE_LO, dsp.SMP_POOL_DDR + SM.PROBE_HI
    C = SMP_L.C

    def probe_run(bad):
        seen = {}

        def at_dispatch_p(r):
            b = seen.setdefault("b", 0)
            seen["b"] = b + 1
            if b == 0:
                command(r, 9, SM.CMD_PROBE)
            elif b == 1:
                seen["first"] = [m2.word(r.state, lo + 4 * k) for k in range(258)]
                seen["after0"] = (m2.word(r.state, C["pph"]), m2.word(r.state, C["pix"]))
                m2.poke(r.state, C["pph"], 3)
                m2.poke(r.state, C["pix"], pn - SM.PROBE_STEP)
                for k in range(pn - SM.PROBE_STEP, pn):
                    m2.poke(r.state, lo + 4 * k, SM.PROBE_PAT[0] + k)
            elif b == 2:
                seen["after1"] = (m2.word(r.state, C["pph"]), m2.word(r.state, C["pix"]))
                m2.poke(r.state, C["pix"], pn - SM.PROBE_STEP)
                for k in range(pn - SM.PROBE_STEP, pn):
                    m2.poke(r.state, hi + 4 * k, SM.PROBE_PAT[1] + k + (1 if bad and k == pn - 7 else 0))

        def frames_p(b):
            return base_frame(sound, machines, t0=ONE, trigger=False, overrides=smp_words({SM.SAMP_REC: 1})).to_bytes()
        rp = run_blocks(init, frames_p, 4, extra_hooks={m3.DISPATCH: at_dispatch_p})
        stp = status(rp["state"].state) if rp["ok"] else []
        pph = m2.word(rp["state"].state, C["pph"]) if rp["ok"] else None
        rp.pop("state", None)
        return rp["ok"], seen, stp, pph
    okp, seenp, statp, pphp = probe_run(False)
    okq, _seenq, statq, _ = probe_run(True)
    first_ok = okp and seenp.get("first", [None])[:256] == [SM.PROBE_PAT[0] + k for k in range(256)] \
        and all(not x for x in seenp["first"][256:]) and seenp.get("after0") == (1, SM.PROBE_STEP)
    checks = {
        "both runs return every block": ok1 and ok2,
        f"RECORD NOW records every block from the command ({n * 32} frames into slot 124's "
        "entry, int16 at 8 MB into the pool)": ok1 and words[1] == 32 * n
            and words[0] == dsp.SMP_POOL_DDR + SM.REC_OFFSET and words[3] == SM.FMT_I16,
        "the recorded frames are the input's, as the model converts them": ok1 and got == want,
        "STOP keeps the slot; the status says done (3), and (v0.25) a preview playing (+16), in both reply "
        "pages, checked":
            ok1 and all(ok_status(h) and h[0] == SM.STATUS_MAGIC | 3 | 16 and h[2] == (32 * n) >> 6 for h in stat1),
        "v0.25: PREVIEW of frames [11, 101): from frame 10 (on a word), 45 words, for pvmix":
            ok1 and pv1 == (words[0] + 20, 45),
        "v0.33: PREVIEW at an offset (+DRIVE's): 4,800 frames at 64 KB in, 2,400 words; past the "
        "pool's end and too long: held to the last ten seconds' room, ten seconds":
            pv_at.get("at") == (dsp.SMP_POOL_DDR + 0x10000, 2400, dsp.SMP_POOL_DDR + 0x10000)
            and pv_at.get("clamped") == (dsp.SMP_POOL_DDR + SM.POOL_BYTES - SP.PREVIEW_BYTES,
                                         SP.PREVIEW_BYTES // 4, dsp.SMP_POOL_DDR + SM.POOL_BYTES - SP.PREVIEW_BYTES),
        "SAMP 124 plays the recording back": ok1 and len(back) == play * BLOCK and V.peak(back) > 0.3,
        "TRK6, MONO L: track 6's bucket's left (the voices' routing elsewhere), back to its level, "
        "into SAMP 125 at 8 MB into the recordings' area (within 2 LSB)":
            ok2 and words2[1] == 32 * n and close2 and words2[0] == dsp.SMP_POOL_DDR + SM.REC_OFFSET + 0x4000 * 512,
        "v0.37: MAIN, L+R: the main mix as the master mix call takes it (the tap), into SAMP 126, "
        "not silence (within 2 LSB)":
            ok3 and words3[1] == 32 * n and close3 and max(abs(x) for x in got3) > 0.2,
        "the status while recording: state 2, the command's sequence, frames / 64, the peak":
            ok2 and all(ok_status(h) and h[0] == SM.STATUS_MAGIC | 2 and h[1] == 7 and h[2] == (32 * n) >> 6
                        and abs(h[3] / 32767 - max(abs(x) for x in left[-32:])) < 0.01 for h in stat2),
        "v0.38: ARM at THRES 0 waits through a -50 dB noise floor (over v0.30's -60 dB) and "
        "starts on the tone's first block, its frames the input's":
            auto is not None and auto[0] == 32 * 6 and auto[1],
        "v0.38: ARM at a set threshold (THRES 60) stays armed under it (a -14 dB tone), and "
        "starts on the first block that exceeds it (-4 dB)":
            plain_low is not None and plain_low[0] == 0
            and plain is not None and plain[0] == 32 * (n - quiet) and plain[1],
        "every sample track bit-exact to the model, every block of both runs":
            ok1 and ok2 and exact1[1] == exact1[2] == exact2[1] == exact2[2] == 0,
        "v0.44: RECORD NOW into a buffer half (dest 128): the buffer directory's entry 0 holds its "
        "address (PLACE), the input's frames and its 4 steps, the frames the model's":
            ok5 and words5 == [dsp.SMP_POOL_DDR + SM.REC_OFFSET + 0x5000 * 512, 32 * n, steps5] and got5 == want[:len(got5)]
            and len(got5) == 32 * n,
        "v0.44: a BOUNCE track on SAMP 129 plays the half back (STRETCH on its steps), bit-exact":
            ok5 and len(back5) == play * BLOCK and V.peak(back5) > 0.1 and exact5[1] == exact5[2] == 0,
        "v0.22: the RAM check takes its command and fills 256 words a block of the low area, "
        "no more": first_ok,
        "v0.22: the RAM check's last chunks: phase 3 on to 4, then the verdict 1 (status half 4, "
        "both pages), the check idle again; one wrong word: 2":
            okp and okq and seenp.get("after1") == (4, 0) and pphp == 0
            and all(ok_status(h) and h[4] == 1 for h in statp) and all(ok_status(h) and h[4] == 2 for h in statq),
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"entry": [hex(w) for w in words], "entry2": [hex(w) for w in words2],
                        "status1": stat1, "status2": stat2, "exact": (exact1, exact2, exact5),
                        "entry5": [hex(w) for w in words5], "back5": V.peak(back5) if back5 else None,
                        "probe": (seenp.get("after0"), seenp.get("after1"), [h[4] for h in statp],
                                  [h[4] for h in statq], pphp),
                        "halt": (rec.get("halt"), rec2.get("halt"))}}


# -- step 3e: the fast link (v0.16, docs/sampler.md) -------------------------------------------------

def step_pvmix(snap, m2mach, m5: Image, stock: Image) -> dict:
    """v0.25: the driver's call of 0x1c9d3f, run from its site (sw 0x1c9fd2) until it is
    back in the driver after the call (sw 0x1c9fdb), on the stock image and on the build: with no preview the two are identical in
    every register and every word written; with one, the build is exactly stock run on the
    block the model mixes (dnfw.sampler.program.pvmix: each of the 32 frames added on L
    and R), every register and every word, but the preview's own words; it ends after the
    words it has."""
    L = SL.layout()
    C = L.C
    REC_AT = dsp.SMP_POOL_DDR + SM.REC_OFFSET + 0x4000
    pairs = [((k * 1237) & 0xFFFF) | (((k * 7919 + 3) & 0xFFFF) << 16) for k in range(40)]
    regs = {f"R{k}": 0x01010101 * (k + 1) for k in range(16)}
    regs.update({"I1": 0x2DF000, "R2": 0x00C0FFEE})

    mix_in = [struct.unpack("<I", struct.pack("<f", 0.01 * k - 0.3))[0] for k in range(64)]

    def run(image, words_left, mix0=mix_in, loop=False):
        r = init_on(snap, m2mach, image).fresh_call(dsp.PVMIX_SITE_SW, regs=regs)
        for k in range(64):
            m2.poke(r.state, SM.MIX_BUF + 4 * k, mix0[k])
        for k, w in enumerate(pairs):
            m2.poke(r.state, REC_AT + 4 * k, w)
        m2.poke(r.state, C["pva"], REC_AT)
        m2.poke(r.state, C["pvn"], words_left)
        if loop:                                # v0.30: a looping preview (the slice editor's D)
            m2.poke(r.state, C["pvl0"], REC_AT)
            m2.poke(r.state, C["pvln"], words_left | SP.PV_LOOP)
        before = dict(r.state.overlay)
        # the call made, back in the driver. The emulator notes a CJUMP's return as the
        # instruction after its delay slots and checks the callee's return against it; the
        # callee returns through the C stack's word (the second push: 0x1c9fda, + 1), which
        # is stock's in both. From wr_pvmix the note is our tail's address, so at the call's
        # target it is set to the one stock's call notes, and the return itself is checked.
        how = fx.run(r, 200000, fx.Fixups(), stop_at=[0x1C9D3F])
        if how[0] == "stop":
            if r.state.call_stack and r.state.call_stack[-1] == dsp.PVMIX_SW + (len(dsp.pvmix_object()) - 6) // 2:
                r.state.call_stack[-1] = 0x1C9FDB
            how = fx.run(r, 200000, fx.Fixups(), stop_at=[0x1C9FDB])
        return r, how, before

    def mix(r):
        return [m2.word(r.state, SM.MIX_BUF + 4 * k) or 0 for k in range(64)]

    def model(words_left, mix0, loop=False):
        from dnfw.perc.dsl import Mem
        mem = Mem(lambda a: 0)
        for k in range(64):
            mem.put(SM.MIX_BUF + 4 * k, mix0[k])
        for k, w in enumerate(pairs):
            mem.put(REC_AT + 4 * k, w)
        mem.put(C["pva"], REC_AT)
        mem.put(C["pvn"], words_left)
        if loop:
            mem.put(C["pvl0"], REC_AT)
            mem.put(C["pvln"], words_left | SP.PV_LOOP)
        SP.pvmix_run(L, mem)
        return [mem.get(SM.MIX_BUF + 4 * k) for k in range(64)], mem.get(C["pva"]), mem.get(C["pvn"])

    own = {C[w] for w in ("pva", "pvn", "pvk", "pvs0", "pvs1", "pvs2", "pvs3", "pvs12", "pvs13", "pvsi", "pvsa",
                          "pvl0", "pvln")}
    own |= {SM.MAIN_TAP + 4 * k for k in range(64)}     # v0.37: the MAIN tap is the preview's too
    out, checks = {}, {}
    for name, left, loop in (("none", 0, False), ("full", 40, False), ("tail", 5, False), ("loop", 5, True)):
        want, pva, pvn = model(left, mix_in, loop)
        rs, hs, _ = run(stock, 0, want)        # stock, given the mix the preview makes
        rm, hm, _ = run(m5, left, loop=loop)
        ok = hs[0] == "stop" and hm[0] == "stop"
        same_regs = ok and rm.state.uregs == rs.state.uregs
        diff = sorted(a for a in set(rm.state.overlay) | set(rs.state.overlay)
                      if rm.state.overlay.get(a) != rs.state.overlay.get(a))
        mixr = range(SM.MIX_BUF, SM.MIX_BUF + 256)
        # the overlay holds load (byte) addresses: DM + 0x28000000
        stray = [a for a in diff if not any(o <= a - dsp.LOAD_ALIAS < o + 4 or o <= a < o + 4 for o in own)]
        got = mix(rm)
        checks[f"{name}: both make the call and come back after it"] = ok
        checks[f"{name}: every register as stock's"] = same_regs
        checks[f"{name}: every word written as stock's (given the mixed block), but the preview's own"] = ok and not stray
        checks[f"{name}: the mix as the model's ({min(left, 16)} words added)"] = ok and got == want
        tap = [m2.word(rm.state, SM.MAIN_TAP + 4 * k) or 0 for k in range(64)]
        checks[f"{name}: v0.37: the MAIN tap holds the mix as it came, before the preview"] = ok and tap == mix_in
        if left == 0:
            checks["none: the mix untouched"] = ok and got == mix_in
        if loop:                                # v0.30: at its end it starts again
            checks["loop: at its end the preview starts again (pva back at its start, pvn its length)"] = (
                (pva, pvn) == (REC_AT, left))
        checks[f"{name}: pva, pvn moved on as the model's"] = ok and (
            m2.word(rm.state, C["pva"]), m2.word(rm.state, C["pvn"])) == (pva, pvn)
        rd = {k: (rs.state.uregs.get(k), rm.state.uregs.get(k)) for k in set(rs.state.uregs) | set(rm.state.uregs)
              if rs.state.uregs.get(k) != rm.state.uregs.get(k)}
        out[name] = {"how": [str(x) for x in hm], "stray": [hex(a) for a in stray[:8]],
                     "regs_differing": {str(k): [str(a), str(b)] for k, (a, b) in list(rd.items())[:12]}}
        if os.environ.get("PVMIX_DEBUG"):
            print(name, out[name])
    return {"ok": all(checks.values()), "checks": checks, "numbers": out}


def step_mainrec(init, sound, machines, blocks) -> dict:
    """v0.38 (the testers: "the recorder with SRC MAIN gets no signal", "FUNC + YES in TRIM
    never plays", "what I record does not play"): the recorder, MAIN, its TRIM preview and
    its playback in the order the instrument runs them, block after block: the per-block
    routine (sw 0x1c2712: the voices, our code with the recorder, the stock's master mix),
    then the driver's master-mix call from its site (sw 0x1c9fd2: wr_pvmix, then the stock's
    0x1c9d3f into the SPORT page), the state carried from each to the next. The runner does
    not model the stock's FX and master path (docs/waverider-dsp-silence.md: its master goes
    NaN), so the master mix is poked into MIX_BUF where the stock leaves it whole (after sw
    0x1c1f1e returns, sw 0x1c3064): a known stereo signal, as a pattern's mix. RECORD NOW,
    MAIN L+R, into a regular slot (SAMP 6, as rec.c's first empty slot), STOP; then the
    TRIM preview (CMD_PREVIEW slot, first, end, as rec.c's preview(1)); then the slot on a
    ONESHOT track once the count covers it (link.c's K_HEAD). Checks: the recording is the
    mix (one block late: the tap is the last block's) within 2 LSB and not silence; the
    SPORT page carries the mix plus the preview at half level while it plays; the slot
    plays back."""
    import math as _m
    n = 10
    ONE = SM.TYPE_OF["ONESHOT"]
    slot = 5
    cmd_at = dsp.SMP_POOL_DDR + SM.CMD_OFFSET
    mixL = [0.4 * _m.sin(2 * _m.pi * 220 * k / 48000) for k in range(32 * (n + 8))]
    mixR = [0.3 * _m.cos(2 * _m.pi * 330 * k / 48000) for k in range(32 * (n + 8))]

    def bits(x):
        return struct.unpack("<I", struct.pack("<f", x))[0]

    def command(r, seq, cmd, src=0, chan=0, thres=0, last=0):
        for k, w in enumerate((seq, cmd, src, chan, thres, last)):
            m2.poke(r.state, cmd_at + 4 * k, w)
    cur = {"b": 0}

    def at_dispatch(r):
        b = cur["b"]
        if b == 0:                               # NOW, MAIN (1), L+R, into SAMP 6 at 0x8000 x 512
            command(r, 21, SM.CMD_NOW, src=1, chan=0 | 0x8000 << 8, last=slot << 24 | SM.REC_FRAMES)
        if b == n:
            command(r, 22, SM.CMD_STOP)
        if b == n + 1:                           # TRIM's FUNC + YES: the slot, START 0, END its frames
            command(r, 23, SM.CMD_PREVIEW, src=slot, chan=0, thres=32 * n)
        if b == n + 4:                           # the ColdFire's K_HEAD: the count covers the slot
            m2.poke(r.state, dsp.SMP_POOL_DDR + 4, max(slot + 1, m2.word(r.state, dsp.SMP_POOL_DDR + 4) or 0))

    def at_master(r):                            # the stock's master mix, whole: our known one
        b = cur["b"]
        for k in range(32):
            m2.poke(r.state, SM.MIX_BUF + 4 * k, bits(mixL[32 * b + k]))
            m2.poke(r.state, SM.MIX_BUF + 0x80 + 4 * k, bits(mixR[32 * b + k]))

    def frame(b):
        if b < n + 4:
            return base_frame(sound, machines, t0=0, trigger=b == 1).to_bytes()
        return base_frame(sound, machines, t0=ONE, trigger=b == n + 5,
                          overrides=smp_words({SM.SAMP_REC: slot + 1})).to_bytes()
    state, taps, dac, played, halt = init, [], [], [], None
    page_l = 0x2C0478
    for b in range(n + 8):
        cur["b"] = b
        rr = run_blocks(state, lambda _b, b=b: frame(b), 1,
                        extra_hooks={m3.DISPATCH: at_dispatch, 0x1C3064: at_master})
        if not rr["ok"]:
            halt = rr.get("halt")
            break
        if b >= n + 5:
            played += smp_series(rr, 0)
        st0 = rr["state"]
        idx = m2.word(st0.state, 0x268A38) or 0
        r = st0.fresh_call(dsp.PVMIX_SITE_SW, regs={"R4": page_l + (idx << 8), "R13": 4})
        how = fx.run(r, 400000, fx.Fixups(), stop_at=[0x1C9D3F])
        if how[0] == "stop":
            if r.state.call_stack and r.state.call_stack[-1] == dsp.PVMIX_SW + (len(dsp.pvmix_object()) - 6) // 2:
                r.state.call_stack[-1] = 0x1C9FDB
            how = fx.run(r, 400000, fx.Fixups(), stop_at=[0x1C9FDB])
        if how[0] != "stop":
            halt = f"the master-mix call: {how[0]} at block {b}"
            break
        taps.append([V.bits_f32(m2.word(r.state, SM.MAIN_TAP + 4 * k) or 0) for k in range(64)])
        base = page_l + (idx << 8)
        dac.append([((m2.word(r.state, base + 8 * k + 4 * c) or 0) ^ 0x80000000) - 0x80000000
                    for k in range(32) for c in (0, 1)])
        state = r
    ok = halt is None
    words, got = [0] * 4, []
    if ok:
        ent = dsp.SMP_POOL_DDR + 8 + 16 * slot
        words = [m2.word(state.state, ent + 4 * k) or 0 for k in range(4)]
        for k in range(words[1] // 2):
            w = m2.word(state.state, words[0] + 4 * k) or 0
            for h in (w & 0xFFFF, w >> 16):
                got.append((h - 65536 if h >= 32768 else h) / 32768.0)
    q = lambda x: max(-32768, min(32767, int(min(0.999969, max(-1.0, x)) * 32768.0))) / 32768.0   # noqa: E731
    # the tap the recorder reads in block b is block b - 1's mix: block 0 records the tap as
    # the snapshot left it, then the mix of blocks 0 .. n - 2
    want = [q((mixL[k] + mixR[k]) * 0.5) for k in range(32 * (n - 1))]
    close = ok and len(got) >= 32 * n and max(abs(a - b) for a, b in zip(got[32:32 * n], want)) <= 2 / 32768
    # the preview: frames [0, 32 n) at half level, 32 a block from block n + 1's master mix
    pv_ok = False
    if ok and len(dac) > n + 2:
        diffs = []
        for j, b in enumerate((n + 1, n + 2)):
            for k in range(32):
                f = 32 * j + k
                for c, mx in ((0, mixL), (1, mixR)):
                    heard = dac[b][2 * k + c] / 2147483648.0
                    diffs.append(abs(heard - mx[32 * b + k] - got[f] * 0.5))
        pv_ok = max(diffs) < 1e-4 and max(abs(x) for x in got[:64]) > 0.05
    f32 = lambda x: V.bits_f32(bits(x))         # noqa: E731  (as the DSP holds it)
    tap_ok = ok and all(all(t[k] == f32(mixL[32 * b + k]) and t[32 + k] == f32(mixR[32 * b + k])
                            for k in range(32)) for b, t in enumerate(taps))
    back = max((abs(x) for x in played), default=0.0)
    checks = {
        "every block ran, through the per-block routine and the driver's master-mix call": ok,
        "the MAIN tap is each block's whole master mix, as the master-mix call takes it": tap_ok,
        "MAIN, L+R, into SAMP 6 (a regular slot): its entry, 32 n frames, int16 in the recordings' area":
            ok and words[0] == dsp.SMP_POOL_DDR + SM.REC_OFFSET + 0x8000 * 512 and words[1] == 32 * n
            and words[3] & 0xFF == SM.FMT_I16,
        "the recording is the mix, one block late, within 2 LSB, and not silence":
            bool(close) and max(abs(x) for x in got[32:32 * n]) > 0.2,
        "TRIM's preview (FUNC + YES): the SPORT page carries the mix plus the recording at half level": pv_ok,
        "the slot plays on a ONESHOT track once the count covers it": back > 0.05,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"halt": halt, "entry": [hex(w) for w in words], "back_peak": round(back, 4),
                        "blocks": len(taps)}}


def step_recwhole(init, sound, machines, blocks, n=None) -> dict:
    """v0.39 (paQ and the owner on v0.38: "it only records one step and leaves the rest
    blank", MAIN or a track, the stored take the length asked for, its sound only in its
    first fraction; and "THRES 0 still triggers"). Every recording the runner made before
    ran 10..12 blocks with nothing else on the link and checked that it played: none ran
    while the ColdFire's loader worked. v0.38's count fix makes the loader work at every
    take's start (smp_count_cover: K_HEAD, 8 bytes, then checked by CMD_VERIFY), and the
    DSP took ANY new command's words 2..4 as the recorder's source, channel and threshold:
    VERIFY's (offset 0, 2 words, 0) made it IN, R, threshold 0 for the rest of the take, and
    an armed take started on the input's own hiss.

    Here each take runs as the instrument makes it, with the ColdFire's traffic as v0.38
    sends it (RECWHOLE_TRAFFIC=0: none, as before v0.38): the record command, K_HEAD's count
    and its VERIFY, a 64 KB chunk's VERIFY (LOAD TO PROJECT), a +DRIVE preview held and let
    go, a SCAN, then STOP and the save's SEND. The inputs are a real unit's: IN carries an
    input's hiss, DC offset and 50 Hz hum throughout (-45 dB, nothing played into it); MAIN idles on a
    reverb/delay tail with dither before the take's sound; every source has its own signal,
    so a take that changes source is caught wherever it does. Checks, per take, over its
    whole length: the entry's frame count is the take's, every frame its source's within
    2 LSB; an ARM starts on the sound's first block, not on the hiss or the tail. Takes of
    64 blocks here (the emulated SHARC's cost: about 10 s a block, the step an hour); the same takes 2 s long,
    and a second of hum or of a tail at THRES 0, run on the model (test_sampler.py, v039_*),
    which the runner holds this code to. On v0.38's code every take here keeps 96 frames of
    its source, then IN's right channel."""
    import math as _m
    n = n or int(os.environ.get("RECWHOLE_BLOCKS", "64"))
    traffic = os.environ.get("RECWHOLE_TRAFFIC", "1") != "0"
    quiet = 52                                       # ARM: blocks of idle input before the sound (v0.39's
                                                     # THRES 0 learns its floor over the first 48)
    cmd_at = dsp.SMP_POOL_DDR + SM.CMD_OFFSET
    ONE = SM.TYPE_OF["ONESHOT"]
    g = SM.TRK_GAIN
    main_tap = getattr(SM, "MAIN_TAP", SM.MIX_BUF)

    def bits(x):
        return struct.unpack("<I", struct.pack("<f", x))[0]

    def q(x):
        return max(-32768, min(32767, int(min(0.999969, max(-1.0, x)) * 32768.0))) / 32768.0

    def hiss(k, ch):                                 # an input's noise, DC and 50 Hz hum: about -45 dB
        return (0.0015 + 0.0012 * ((((k + 977 * ch) * 2654435761) >> 7 & 0xFFFF) / 32768.0 - 1.0)
                + 0.004 * _m.sin(2 * _m.pi * 50 * k / 48000))

    def tail(k, ch):                                 # MAIN idle: a reverb tail, dither (-50 dB)
        return (0.002 * _m.exp(-k / 20000.0) * _m.sin(2 * _m.pi * (90 + 7 * ch) * k / 48000)
                + 0.0004 * ((((k + 31 * ch) * 40503) >> 3 & 0xFF) / 128.0 - 1.0))

    def source(sid, k, ch, armed_take):
        """source SID's input, frame K, channel CH (as the DSP holds it, a track x TRK_GAIN
        undone). An armed take's sources are idle until block QUIET"""
        on = 1.0 if not armed_take or k >= 32 * quiet else 0.0
        z = 2 * _m.pi * (k - 32 * quiet) / 48000       # (the sound at its crest on its first frame)
        if sid == 0:
            return hiss(k, ch) + on * 0.45 * _m.cos((700 if ch == 0 else 1100) * z)
        if sid == 1:
            return tail(k, ch) + on * 0.6 * _m.cos((220 if ch == 0 else 330) * z)
        t = sid - 2
        return on * (0.62 + 0.01 * t) * _m.cos((150 + 40 * t) * z + (-0.5 if ch == 0 else 0.5))

    def frames_b(b):
        return base_frame(sound, machines, t0=ONE, trigger=False, overrides=smp_words({SM.SAMP_REC: 1})).to_bytes()

    def take(cmd, src, chan, thres, slot, place, armed_take):
        cur = {"b": 0, "seq": 40}

        def command(r, c, w2=0, w3=0, w4=0, w5=0):
            cur["seq"] += 1
            for k, w in enumerate((cur["seq"], c, w2, w3, w4, w5)):
                m2.poke(r.state, cmd_at + 4 * k, w)

        def at_dispatch(r):
            b = cur["b"]
            if b == 0:
                command(r, cmd, src, chan | place << 8, thres, slot << 24 | SM.REC_FRAMES)
            if traffic:
                if b == 2:                           # K_HEAD: the magic and the count, then its VERIFY
                    m2.poke(r.state, dsp.SMP_POOL_DDR + 4,
                            max(slot + 1, m2.word(r.state, dsp.SMP_POOL_DDR + 4) or 0))
                if b == 3:
                    command(r, SM.CMD_VERIFY, 0, 2)
                if b == n // 3:                      # LOAD TO PROJECT's chunk, checked
                    command(r, SM.CMD_VERIFY, SM.DATA_OFFSET // 4, 0x4000)
                if b == n // 2:                      # a +DRIVE preview held, and let go
                    command(r, SM.CMD_PREVIEW, SP.PREVIEW_AT, 0x10000, 4800)
                if b == n // 2 + 2:
                    command(r, SM.CMD_PREVIEW, SP.PREVIEW_AT, 0, 0)
                if b == 2 * n // 3:                  # a SCAN (tools/dn2diag.py)
                    command(r, SM.CMD_SCAN, dsp.SMP_POOL_DDR, 64)
            if b == n:
                command(r, SM.CMD_STOP, src, chan, thres)
            if traffic and b == n + 1:               # the save reads it back
                command(r, SM.CMD_SEND, (SM.REC_OFFSET + place * 512) // 4, 0x100)
            for k in range(32):
                x = 32 * b + k
                for ch in (0, 1):
                    m2.poke(r.state, SM.IN_BUF + 0x80 * ch + 4 * k, bits(source(0, x, ch, armed_take)))
                    m2.poke(r.state, main_tap + 0x80 * ch + 4 * k, bits(source(1, x, ch, armed_take)))
                    for t in range(16):
                        m2.poke(r.state, SM.TRK_BUF + SM.TRK_STRIDE * t + 0x80 * ch + 4 * k,
                                bits(source(2 + t, x, ch, armed_take) * g))
            cur["b"] += 1
        rr = run_blocks(init, frames_b, n + 3, extra_hooks={m3.DISPATCH: at_dispatch})
        if not rr["ok"]:
            return None, [], [], rr.get("halt")
        st = rr["state"].state
        ent = dsp.SMP_POOL_DDR + 8 + 16 * slot
        words = [m2.word(st, ent + 4 * k) or 0 for k in range(4)]
        got = []
        for k in range(words[1] // 2):
            w = m2.word(st, words[0] + 4 * k) or 0
            for h in (w & 0xFFFF, w >> 16):
                got.append((h - 65536 if h >= 32768 else h) / 32768.0)
        rr.pop("state", None)

        def want_frame(x):
            lft, rgt = source(src, x, 0, armed_take), source(src, x, 1, armed_take)
            if src >= 2:
                lft, rgt = lft * g * (1.0 / g), rgt * g * (1.0 / g)
            if chan == 1:
                rgt = lft
            elif chan == 2:
                lft = rgt
            return q((lft + rgt) * 0.5)
        start = 32 * quiet if armed_take else 0
        return words, got, [want_frame(x) for x in range(start, 32 * n)], None

    runs = (                                         # name, command, source, channel, THRES word, slot, place, armed
        ("MAIN L+R, RECORD NOW", SM.CMD_NOW, 1, 0, 33, 5, 0x0000, False),
        ("TRK3 MONO L, RECORD NOW", SM.CMD_NOW, 2 + 2, 1, 33, 6, 0x2000, False),
        ("IN L+R, RECORD NOW", SM.CMD_NOW, 0, 0, 33, 9, 0x8000, False),
        ("MAIN L+R, ARM at THRES 0", SM.CMD_ARM, 1, 0, 33, 7, 0x4000, True),
        ("IN L+R, ARM at THRES 0 (the input's hiss and DC)", SM.CMD_ARM, 0, 0, 33, 10, 0xA000, True),
        ("TRK3 L+R, ARM at THRES 60", SM.CMD_ARM, 2 + 2, 0, 16383, 8, 0x6000, True),
    )
    checks, numbers = {}, {}
    for name, cmd, src, chan, thres, slot, place, armed_take in runs:
        words, got, want, halt = take(cmd, src, chan, thres, slot, place, armed_take)
        if words is None:
            checks[f"{name}: ran"] = False
            numbers[name] = {"halt": halt}
            continue
        nw = len(want)
        bad = [k for k, (x, y) in enumerate(zip(got, want)) if abs(x - y) > 2 / 32768]
        late = got[-32 * 4:]
        what = (f"{name}: {nw} frames ({nw / 48000:.2f} s, the link at work throughout), every one its "
                "source's within 2 LSB, start to end")
        if armed_take:
            what += "; armed through the idle input, started on the sound's first block"
        checks[what] = words[1] == nw and len(got) == nw and not bad and max((abs(x) for x in late), default=0) > 0.1
        numbers[name] = {"entry": [hex(w) for w in words], "frames": words[1], "want": nw,
                         "wrong": len(bad), "first_wrong": bad[0] if bad else None,
                         "first_wrong_s": round(bad[0] / 48000, 4) if bad else None,
                         "late_peak": round(max((abs(x) for x in late), default=0), 4)}
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"blocks": n, "traffic": traffic, **numbers}}


def step_mainsrc(init, sound, machines, blocks) -> dict:
    """v0.37 (the owner: resampling MAIN L+R records an empty sample): the main mix buffer
    (MIX_BUF) as our recorder sees it (at our sampler's entry) and as the master mix call
    sees it (at the preview mixer's site), with a stock FM Tone track sounding"""
    seen = {"smp": [], "pvmix": []}

    def peak(r):
        return max(abs(V.bits_f32(m2.word(r.state, SM.MIX_BUF + 4 * k) or 0)) for k in range(64))

    def at_smp(r):
        seen["smp"].append(peak(r))

    def at_pv(r):
        seen["pvmix"].append(peak(r))

    def fb(b):
        return base_frame(sound, machines, t0=0, trigger=b == 1).to_bytes()
    rr = run_blocks(init, fb, 8, extra_hooks={dsp.SMP_SW: at_smp, dsp.PVMIX_SW: at_pv})
    nums = {k: [round(x, 5) for x in v] for k, v in seen.items()}
    print(f"    MIX_BUF peak at our sampler's entry: {nums['smp']}", flush=True)
    print(f"    MIX_BUF peak at the master mix call:  {nums['pvmix']}", flush=True)
    return {"ok": rr["ok"], "checks": {"ran": rr["ok"]}, "numbers": nums}


def step_tdm(init, sound, machines, blocks) -> dict:
    """The fast link's DSP end on the SHARC: the ColdFire's packets poked into slots 8..15
    of the TDM receive page the engine reads (DM 0x268a38 picks it), in both
    justifications, land in the pool, one a block; a packet with a wrong check, or one over
    the command block, writes nothing (the recorder's parts are written: v0.16); VERIFY's
    sums are the pool's; SEND streams the pool back through slots 14..15 of the transmit
    page, every word, decoded as the ColdFire decodes it; every sample track stays
    bit-exact.

    The transmit page is read right after the sample machines' program (at PING_SW, v0.26): the
    runner puts each block's frame where the codec's DAC page is (m4.unpack_call), which
    reaches over the transmit page's first 24 frames, before the next block's dispatch. On
    the instrument the frame arrives in its own SPI page (docs/link-research.md)."""
    import random
    rnd = random.Random(16)
    n = max(blocks, 12)
    base_w = (SM.DATA_OFFSET + 0x20000) // 4          # an unused stretch of the pool, words
    words = [rnd.randrange(1 << 32) for _ in range(SM.RX_WORDS * n)]
    ONE = SM.TYPE_OF["ONESHOT"]
    cmd_at = dsp.SMP_POOL_DDR + SM.CMD_OFFSET
    bad_at = 3                                        # the block whose packet's check is wrong
    cmd_blk = 5                                       # the block whose packet spans the command block
    verify_from, send_from = n + 2, n + 30
    total = send_from + (SM.RX_WORDS * n) // SM.TX_WORDS + 6
    state = {"b": 0, "pg": [], "tx": []}

    def command(r, rx, seq, cmd, a0, a1):         # v0.20: as the ColdFire sends it, by TDM
        for o, w in SL.rx_page(SL.rx_units(SM.CMD_OFFSET // 4, [seq, cmd, a0, a1, 0, 0], seq)).items():
            m2.poke(r.state, rx + o, w)

    def at_dispatch(r):
        b = state["b"]
        pg = (m2.word(r.state, SM.TDM_PAGE) or 0) & 1
        state["pg"].append(pg)
        rx = SM.TDM_RX + (pg << 11) + 32
        if b < n:
            off = base_w + SM.RX_WORDS * b
            u = SL.rx_units(off, words[SM.RX_WORDS * b:SM.RX_WORDS * (b + 1)], b)
            if b == bad_at:
                u[255] = (u[255] + 1) & 0xFFFF
            if b == cmd_blk:
                u = SL.rx_units(SM.CMD_OFFSET // 4 - 60, [0x5A5A5A5A] * SM.RX_WORDS, b)
            for o, w in SL.rx_page(u, high=b % 2 == 0).items():
                m2.poke(r.state, rx + o, w)
        else:
            for o in range(0, 32 * 64, 64):           # stock's zeros in slots 8..15
                for k in range(8):
                    m2.poke(r.state, rx + o + 4 * k, 0)
        if b == verify_from:
            command(r, rx, 21, SM.CMD_VERIFY, base_w, SM.RX_WORDS * n)
        if b == send_from:
            command(r, rx, 22, SM.CMD_SEND, base_w, SM.RX_WORDS * n)
        state["b"] += 1

    def after_smp(r):
        at = SM.TDM_TX + (state["pg"][-1] << 11) + 56
        state["tx"].append(SL.tx_decode(lambda o: m2.word(r.state, at + o) or 0))

    def frames(b):
        return base_frame(sound, machines, t0=ONE, trigger=(b == 1),
                          overrides=smp_words({SM.SAMP_REC: 1})).to_bytes()
    run = run_blocks(init, frames, total, extra_hooks={m3.DISPATCH: at_dispatch,
                                                       dsp.PING_SW: after_smp})
    ok = run["ok"]
    st = run["state"].state if ok else None

    def pool_word(w):
        return (m2.word(st, dsp.SMP_POOL_DDR + 4 * w) or 0) & 0xFFFFFFFF
    want = list(words)
    for blk in (bad_at, cmd_blk):                     # never written: the pool's zeros
        for k in range(SM.RX_WORDS * blk, SM.RX_WORDS * (blk + 1)):
            want[k] = 0
    got = [pool_word(base_w + k) for k in range(len(words))] if ok else []
    cmd_clean = ok and all(pool_word(SM.CMD_OFFSET // 4 - 60 + k) != 0x5A5A5A5A for k in range(SM.RX_WORDS))
    x = y = 0
    for w in want:
        x = (x + w) & 0xFFFFFFFF
        y = (y + x) & 0xFFFFFFFF
    stat = []
    if ok:
        for page in SM.REPLY_PAGES:
            h = []
            for k in range(8):
                w = m2.word(st, page + SM.REPLY_TAIL + 4 * k) or 0
                h += [w & 0xFFFF, w >> 16]
            stat.append(h)
    sent = {}
    for p in state["tx"]:
        if p:
            for k, w in enumerate(p[2:]):
                sent[p[0] + k] = w
    back = [sent.get(base_w + k) for k in range(len(words))]
    exact = smp_exact(run) if ok else (0, 1, 1)
    run.pop("state", None)
    checks = {
        "the run returns every block": ok,
        f"{n - 2} good packets (both justifications) put their words in the pool, one a block; "
        "the bad check's and the one over the command block wrote nothing": ok and got == want and cmd_clean,
        "VERIFY: the sums of the range, and its sequence, in both reply pages, checked": ok and all(
            h[15] == (SM.LINK_SEED + sum(h[:15])) & 0xFFFF and h[14] == 21
            and (h[10] | h[11] << 16) == x and (h[12] | h[13] << 16) == y for h in stat),
        "SEND: every word of the range back through slots 14..15, as the ColdFire decodes them":
            ok and back == want,
        "every sample track bit-exact to the model, every block": ok and exact[1] == exact[2] == 0,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"status": stat, "packets_back": sum(1 for p in state["tx"] if p),
                        "pages": sorted(set(state["pg"])), "exact": exact, "halt": run.get("halt")}}


# -- step 4 -------------------------------------------------------------------------------------------

# -- v0.45: FASCIA (type 18, docs/fascia.md) ---------------------------------------------------

FSC_OUT = ROOT / "out" / "fascia-dsp"


def fsc_audition():
    import fascia_audition as FA                 # noqa: PLC0415  (scripts/)
    return FA.PATCHES


def fsc_frame(sound, machines, tracks: dict, trig=(), others=None) -> bytes:
    """a frame: TRACKS = {t: (panel, note, vel)} on FASCIA, OTHERS = {t: (type, words)}; TRIG the
    tracks triggered this block"""
    from dnfw.fascia import bench as FB          # noqa: PLC0415
    t0 = min(tracks) if tracks else 0
    f = base_frame(sound, machines, t0=FSM.TYPE if 0 in tracks else (others or {}).get(0, (4, {}))[0],
                   trigger=False, others={t: ty for t, (ty, _w) in (others or {}).items() if t != 0})
    for t, (ty, words) in (others or {}).items():
        f.header(FR.MACHINE, t, ty)
        f.header(FR.NOTE, t, 0x3C00)             # C4, as base_frame gives track 0
        for slot, w in words.items():
            f.param(t, slot, w)
    for t, (panel, note, vel) in tracks.items():
        f.header(FR.MACHINE, t, FSM.TYPE)
        for c, word in FB.panel_words(panel).items():
            f.param(t, FSM.SLOTS[c][1], word)
        f.header(FR.NOTE, t, FB.note_word(note))
        f.header(FSP.VEL_OFFSET, t, FB.vel_word(vel))
    for t in trig:
        f.trigger(t)
    return f.to_bytes()


def fsc_live(panel, notes: dict, blocks: int, slot: int, controls=None):
    """live.py's voice for SLOT (seed slot + 1) on PANEL (or CONTROLS(b)), NOTES = {block: (note,
    vel)} as the frame carries them -> 32 float32 a block"""
    import numpy as np                           # noqa: PLC0415
    from dnfw.fascia import bench as FB, live as LV   # noqa: PLC0415
    v = LV.Voice(seed=slot + 1)
    out = []
    for b in range(blocks):
        if b in notes:
            n, vel = notes[b]
            v.note_on(FB.note_seen(n), FB.vel_seen(vel))
        out.append(v.block(FB.panel_seen(controls(b) if controls else panel)))
    return [np.asarray(x, np.float32) for x in out]


def fsc_exact(rr) -> tuple[int, int, int]:
    """(blocks with FASCIA voices, output words differing from the model, state words differing)"""
    n = om = sm = 0
    for blk in rr.get("fsc", []):
        for v in blk.values():
            n += 1
            om += v["out_mismatches"]
            sm += v["state_mismatches"]
    return n, om, sm


def fsc_bits(rr, t) -> list[list[int]]:
    return [blk[t]["bits"] if t in blk else None for blk in rr.get("fsc", [])]


def fsc_vs_live(rr, t, want) -> tuple[int, float]:
    """(blocks whose 32 words differ from live.py's, the max abs difference)"""
    import numpy as np                           # noqa: PLC0415
    bad, dmax = 0, 0.0
    for b, w in enumerate(want):
        got = fsc_bits(rr, t)[b] if b < len(rr.get("fsc", [])) else None
        if got is None:
            bad += 1
            continue
        g = np.array(got, np.uint32).view(np.float32)
        if not np.array_equal(g.view(np.uint32), w.view(np.uint32)):
            bad += 1
        dmax = max(dmax, float(np.max(np.abs(g.astype(np.float64) - w.astype(np.float64)))))
    return bad, dmax


def fsc_wav(path: pathlib.Path, x) -> None:
    import numpy as np                           # noqa: PLC0415
    import wave as _w                            # noqa: PLC0415
    x = np.asarray(x, np.float64)
    pk = float(np.max(np.abs(x))) or 1.0
    y = x / max(pk, 1.0) * 0.98
    path.parent.mkdir(parents=True, exist_ok=True)
    with _w.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((y * 32767).astype("<i2").tobytes())


def step_fascia(init, sound, machines, blocks=8) -> dict:
    """v0.45: FASCIA's assembled code against live.py, bit for bit. Two audition patches
    (scripts/fascia_audition.py) on track 0: its first note struck on block 1, then BLOCKS of its
    ring; FASCIA's buffer at its tail must be dnfw.fascia.program's model (run on the DSP's memory
    at FASCIA's entry) and live.Voice's block (the panel the frame carries) word for word. Then
    the idle rule: a short hit run until the voice rests (its buffer zeros, the model's and
    live's alike), a steal (a second note while it sounds: the fade, then the strike), and p-locks
    moving mid-note (TUNE and GEOM retune, MORPH ramps, a post stage switched on and off)."""
    import numpy as np                           # noqa: PLC0415
    res, bad = {}, []
    pats = fsc_audition()
    # (owner, 2026-11-08: the gate needs the bit-exact part, not the whole audition: two patches,
    # a struck bar and the costliest; test_fascia_program and fascia_dsp_compare hold the rest)
    for name in ("01_tubular_bell", "20_snare_wires"):
        panel, evs, secs, trem = pats[name]
        note, vel = evs[0][1], evs[0][2]
        n = blocks + 2
        rr = run_blocks(init, lambda b, panel=panel, note=note, vel=vel: fsc_frame(
            sound, machines, {0: (panel, note, vel)}, trig=(0,) if b == 1 else ()), n)
        want = fsc_live(panel, {1: (note, vel)}, n, 0)
        ex = fsc_exact(rr)
        lb, dmax = fsc_vs_live(rr, 0, want)
        ok = rr["ok"] and ex[0] == n and ex[1:] == (0, 0) and lb == 0
        got = [np.array(b_, np.uint32).view(np.float32) for b_ in fsc_bits(rr, 0) if b_ is not None]
        res[name] = {"ok": ok, "model_mismatch": ex[1:], "live_blocks_differing": lb, "max_abs_diff": dmax,
                     "peak": float(max((np.max(np.abs(g)) for g in got), default=0.0)), "halt": rr.get("halt")}
        if not ok:
            bad.append(name)
        print(f"    fascia {name}: {'ok' if ok else 'FAIL'} (max |dsp - live| {dmax:.3g})", flush=True)
    # the idle rule: a short hit until the voice rests
    short = dict(BODA=0, DAMP=127, MATL=0, HARD=127, MIX=0, DEC=0, LPG=0)
    n_idle = 120
    rr = run_blocks(init, lambda b: fsc_frame(sound, machines, {0: (short, 60, 1.0)}, trig=(0,) if b == 1 else ()),
                    n_idle)
    want = fsc_live(short, {1: (60, 1.0)}, n_idle, 0)
    ex = fsc_exact(rr)
    lb, dmax = fsc_vs_live(rr, 0, want)
    zeros_from = next((b for b in range(n_idle - 1, 0, -1) if np.any(want[b] != 0)), 0) + 1
    rested = rr["ok"] and all(not any(fsc_bits(rr, 0)[b]) for b in range(zeros_from, n_idle))
    idle = {"ok": rr["ok"] and ex[1:] == (0, 0) and lb == 0 and rested and zeros_from < n_idle,
            "rests_after_block": zeros_from, "model_mismatch": ex[1:], "live_blocks_differing": lb}
    # a steal: a second note on the sounding voice (the old sound faded over a block, the
    # strike the block after), then p-locks moving every few blocks
    pan = pats["03_vibraphone"][0]

    def moving(b):
        p_ = dict(pan)
        if b >= 6:
            p_["TUNE"] = 64 + 3 * (b - 6)
        if b >= 9:
            p_["GEOM"], p_["MORPH"] = 40 + b, 20 * (b % 3)
        if 11 <= b < 15:
            p_["SKIN"], p_["SHIFT"], p_["DRIVE"] = 100, 90, 100
        return p_
    n_st = 18
    rr = run_blocks(init, lambda b: fsc_frame(sound, machines, {0: (moving(b), 60 if b < 4 else 67, 0.8)},
                                              trig=(0,) if b in (1, 4) else ()), n_st)
    want = fsc_live(None, {1: (60, 0.8), 4: (67, 0.8)}, n_st, 0, controls=moving)
    ex = fsc_exact(rr)
    lb, dmax2 = fsc_vs_live(rr, 0, want)
    steal = {"ok": rr["ok"] and ex[1:] == (0, 0) and lb == 0, "model_mismatch": ex[1:], "live_blocks_differing": lb,
             "max_abs_diff": dmax2}
    checks = {
        "every audition patch: strike and ring bit-exact to the model and to live.py, every block": not bad,
        "the idle rule: a short hit rests (zeros from then on), bit-exact to the model and live.py": idle["ok"],
        "a steal (the fade, then the strike) and p-locks moving mid-note: bit-exact to the model and live.py":
            steal["ok"],
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"patches": res, "idle": idle, "steal": steal, "failing": bad}}


def step_fchords(init, sound, machines, blocks=8) -> dict:
    """v0.45: several FASCIA voices at once, and FASCIA beside the other machines of ours. A:
    four FASCIA voices, a chord (the audition's CHORD, four patches), struck together; B: FASCIA
    on track 0 beside PERC (track 1), ONESHOT (track 2) and a Monomachine voice (track 3), all
    struck on block 1. Every FASCIA voice bit-exact to its model and to live.py; PERC (and the
    Monomachine voice) to PERC's model; ONESHOT to the sample machines'."""
    from dnfw.mnm import machines as MMx         # noqa: PLC0415
    pats = fsc_audition()
    names = ["07_glass_bowl", "03_vibraphone", "10_steel_pan", "20_snare_wires"]
    chord = [(60, 0.9), (64, 0.9), (67, 0.9), (71, 0.9)]
    tracks = {t: (pats[names[t]][0], chord[t][0], chord[t][1]) for t in range(4)}
    n = blocks + 2
    ra = run_blocks(init, lambda b: fsc_frame(sound, machines, tracks, trig=tuple(range(4)) if b == 1 else ()), n)
    a_ok, a_n = ra["ok"], {}
    for t in range(4):
        want = fsc_live(tracks[t][0], {1: chord[t]}, n, t)
        lb, dmax = fsc_vs_live(ra, t, want)
        a_n[t] = {"patch": names[t], "live_blocks_differing": lb, "max_abs_diff": dmax}
        a_ok = a_ok and lb == 0
    ea = fsc_exact(ra)
    a_ok = a_ok and ea[1:] == (0, 0) and ea[0] == 4 * n
    sid = MMx.NAMES.index("SID 6581")
    others = {1: (5, perc_words(0)), 2: (SM.TYPE_OF["ONESHOT"], smp_words({SM.SAMP_REC: 4})),
              3: (MMx.TYPES[sid], mnm_words(sid))}
    pan = pats["13_tabla"][0]
    rb = run_blocks(init, lambda b: fsc_frame(sound, machines, {0: (pan, 48, 1.0)}, trig=(0, 1, 2, 3) if b == 1 else (),
                                              others=others), n)
    want = fsc_live(pan, {1: (48, 1.0)}, n, 0)
    lb, dmax = fsc_vs_live(rb, 0, want)
    eb = fsc_exact(rb)
    pe = perc_exact(rb)
    se = smp_exact(rb)
    # what each machine left in its slot at its program's tail (PERC's for 1 and 3, the sample
    # machines' for 2), as the chords steps hear them (the end-of-block buffers are the stock's)
    def _heard(key, t):
        return V.peak([x for blk in rb.get(key, [])[2:] if t in blk for x in blk[t]["out"]]) if rb["ok"] else 0.0
    peaks = {1: _heard("perc", 1), 2: _heard("smp", 2), 3: _heard("perc", 3)}
    others_heard = rb["ok"] and all(peaks[t] > 1e-4 for t in (1, 2, 3))
    checks = {
        "A: four FASCIA voices at once (a chord): every block returns, each bit-exact to its model and live.py": a_ok,
        "B: FASCIA beside PERC, ONESHOT and a Monomachine voice: FASCIA bit-exact to its model and live.py":
            rb["ok"] and eb[1:] == (0, 0) and eb[0] == n and lb == 0,
        "B: PERC and the Monomachine voice bit-exact to PERC's model, ONESHOT to the sample machines', all heard":
            pe[1:] == (0, 0) and se[1:] == (0, 0) and others_heard,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"A": {"voices": a_n, "exact": ea}, "B": {"fascia": {"live_blocks_differing": lb, "max_abs_diff": dmax},
                                                                "exact": eb, "perc_exact": pe, "smp_exact": se,
                                                                "peaks_PERC_ONESHOT_MnM": peaks}}}


def step_fgarbage(init, sound, machines) -> dict:
    """v0.45: FASCIA started on garbage: its sixteen voices' state (both L2 rooms), its block's
    scratch (L1) and its bookkeeping (the guard's costs, strikes, steals) filled with NaN
    (0xFFFFFFFF) or random words before the first block. FASCIA on tracks 0..3 (four patches,
    struck on block 2, a second note on block 4), the other twelve tracks FASCIA unstruck. Every
    block must return, every FASCIA buffer be finite (and within the knee), and from the strike on
    each voice bit-exact to its model (which reads the same memory at FASCIA's entry)."""
    import random as _r
    import numpy as np                           # noqa: PLC0415
    fills = {"nan": lambda k: 0xFFFFFFFF, "random": (lambda g: lambda k: g.getrandbits(32))(_r.Random(18))}
    spans = [(FSC_L.state, 8 * FSP.STRIDE), (FSC_L.state2, 8 * FSP.STRIDE),
             (FSC_L.scratch, FSC_L.scratch_end - FSC_L.scratch), (FSC_L.cost, 0x40), (FSC_L.strikes, 0x80)]
    pats = fsc_audition()
    names = ["01_tubular_bell", "23_bowed_string_resin", "29_water_droplet_vibe", "15_tzfm_clank"]
    res, bad = {}, []
    for fname, fill in fills.items():
        done = {"n": 0}

        def poke(r, fill=fill, done=done):
            if done["n"]:
                return
            done["n"] = 1
            for a, n in spans:
                for k in range(0, n, 4):
                    m2.poke(r.state, a + k, fill(k))
        tracks = {t: (pats[names[t]][0] if t < 4 else {}, 60 + t, 0.9) for t in range(16)}
        rr = run_blocks(init, lambda b: fsc_frame(sound, machines, tracks,
                                                  trig=tuple(range(4)) if b in (2, 4) else ()), 8,
                        extra_hooks={dsp.PERC_SW: poke})
        fin = rr["ok"] and all(blk is not None and all(math.isfinite(x) and abs(x) <= 0.7 for x in blk)
                               for t in range(16) for blk in [[V.bits_f32(w) for w in (b_ or [])] for b_ in fsc_bits(rr, t)])
        exact = rr["ok"] and all(v["out_mismatches"] == 0 and v["state_mismatches"] == 0
                                 for blk in rr["fsc"][2:] for t, v in blk.items() if t < 4)
        res[fname] = {"ok": rr["ok"] and fin and exact, "finite": fin, "exact_from_strike": exact,
                      "halt": rr.get("halt")}
        if not res[fname]["ok"]:
            bad.append(fname)
        print(f"    fgarbage {fname}: {res[fname]}", flush=True)
    checks = {"FASCIA on NaN or random voice state, scratch and bookkeeping: every block returns, every "
              "buffer finite, each struck voice bit-exact to its model from its strike": not bad}
    return {"ok": not bad, "checks": checks, "numbers": res}


def step_fsilence(init, sound, machines) -> dict:
    """v0.45: FASCIA on all sixteen tracks, no trig: every buffer zeros every block, and FASCIA's
    whole loop costs little (instructions from its entry to its tail, a block)"""
    ins = {"sum": 0, "n": 0}

    def at_in(r):
        ins["a"] = r.steps_n

    def at_out(r):
        if "a" in ins:
            ins["sum"] += r.steps_n - ins.pop("a")
            ins["n"] += 1
    tracks = {t: ({}, 60, 1.0) for t in range(16)}
    rr = run_blocks(init, lambda b: fsc_frame(sound, machines, tracks), 6,
                    extra_hooks={dsp.FSC_SW: at_in, dsp.PING_SW: at_out})
    zeros = rr["ok"] and all(not any(b_ or [1]) for t in range(16) for b_ in fsc_bits(rr, t))
    per = ins["sum"] // max(ins["n"], 1)
    checks = {"sixteen untriggered FASCIA tracks: every buffer zeros, every block": zeros,
              "and the whole FASCIA loop costs under 16,000 instructions a block (1,000 a slot)": per < 16_000}
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"instructions_per_block": per, "exact": fsc_exact(rr)}}


def step_fcost(init, sound, machines) -> dict:
    """v0.45: what a FASCIA voice costs, per audition patch, one voice sounding: instructions of
    FASCIA's loop a block (entry to tail, less the silent loop's), and its L2 and DDR accesses:
    the strike's block, the attack (the exciters running) and the ring. -> typical (median) and
    worst; and how many voices fit in the guard's 0.6 of a frame at K = 1 and K = 3"""
    import statistics as _st
    counts, undo = _count_memory()
    rows = {}

    def measure(name, panel, note, vel, n=10):
        per = []

        def at_in(r):
            per.append([r.steps_n, None, counts["L2"], counts["DDR"]])
            counts["on"] = True

        def at_out(r):
            if per and per[-1][1] is None:
                per[-1][1] = r.steps_n
                per[-1][2] = counts["L2"] - per[-1][2]
                per[-1][3] = counts["DDR"] - per[-1][3]
            counts["on"] = False
        rr = run_blocks(init, lambda b: fsc_frame(sound, machines, {0: (panel, note, vel)}, trig=(0,) if b == 1 else ()),
                        n, extra_hooks={dsp.FSC_SW: at_in, dsp.PING_SW: at_out})
        cost = [(b - a, l2, ddr) for a, b, l2, ddr in per if b is not None]
        return rr["ok"], cost
    try:
        ok0, base = measure("(nothing)", {}, 60, 1.0, 4)
        b0 = min(c[0] for c in base) if base else 0
        for name, (panel, evs, secs, trem) in fsc_audition().items():
            ok, cost = measure(name, panel, evs[0][1], evs[0][2])
            ins = [c[0] - b0 for c in cost]
            rows[name] = {"ok": ok, "strike": ins[1] if len(ins) > 1 else None,
                          "attack": max(ins[2:6]) if len(ins) > 5 else None,
                          "ring": ins[-1] if ins else None,
                          "L2_ring": cost[-1][1] if cost else None, "DDR_ring": cost[-1][2] if cost else None}
            print(f"    fcost {name}: {rows[name]}", flush=True)
    finally:
        undo()
    ok = all(r["ok"] for r in rows.values())
    vals = [r for r in rows.values() if r["ok"] and r["ring"] is not None]
    typical = {k: int(_st.median(r[k] for r in vals)) for k in ("strike", "attack", "ring")} if vals else {}
    worst = {k: max(r[k] for r in vals) for k in ("strike", "attack", "ring")} if vals else {}
    P = 666_667
    fit = {f"K{K}": {k: int(0.6 * P // (K * max(v, 1))) for k, v in (("typical_ring", typical.get("ring", 1)),
                                                                     ("typical_attack", typical.get("attack", 1)),
                                                                     ("worst_attack", worst.get("attack", 1)))}
           for K in (1, 3)}
    return {"ok": ok, "checks": {"every audition patch measured (every block returned)": ok},
            "numbers": {"per_patch": rows, "typical": typical, "worst": worst, "voices_in_0.6P": fit}}


def step_fstress(init, sound, machines) -> dict:
    """v0.45: sixteen FASCIA voices under the guard, the clock made to move (as step 3s: every
    read of EMUCLK in our code gets the block's start plus K = 3 x the instructions run so far).
    A new note on the next track every block (dynamic allocation) on a heavy patch (two coupled
    bodies with BUZZ and a click), then the same on the heaviest (WATR) patch. Every block must
    end, our voices done by 0.8 of the frame, voices left out (and counted) when time is short,
    the newest note heard in most blocks, every buffer finite."""
    from dnfw.perc import guard as G
    K, P = 3, 666_667
    sites = set(_after_emuclk("perc")) | set(_after_emuclk("smp")) | set(_after_emuclk("fascia"))
    pats = fsc_audition()
    out = {}
    for label, name in (("A", "20_snare_wires"), ("B", "29_water_droplet_vibe")):
        b_now = {"b": 0}

        def clock(r):
            base = (b_now["b"] + 1) * P
            r.state.uregs[fx.UREG_CODES["R8"]] = fx.Const((base + K * getattr(r, "steps_n", 0)) & 0xFFFFFFFF)

        def at_perc(r):
            base = (b_now["b"] + 1) * P
            m2.poke(r.state, G.MARK0, base & 0xFFFFFFFF)
            m2.poke(r.state, G.MARK, (base + K * getattr(r, "steps_n", 0)) & 0xFFFFFFFF)
        hooks = {dsp.PERC_SW: at_perc}
        hooks.update({s_: clock for s_ in sites})
        panel = pats[name][0]
        tracks = {t: (panel, 48 + (t * 5) % 24, 0.9) for t in range(16)}
        nb = 20

        def fb(b, tracks=tracks):
            b_now["b"] = b
            return fsc_frame(sound, machines, tracks, trig=(b % 16,))
        rr = run_blocks(init, fb, nb, extra_hooks=hooks)
        st = rr.get("state")
        skips = m2.word(st.state, G.SKIPS) if rr["ok"] else None
        end = m2.word(st.state, G.OURS_END) if rr["ok"] else None
        mark0 = m2.word(st.state, G.MARK0) if rr["ok"] else None
        rr.pop("state", None)
        heard = tot = 0
        for b in range(2, nb):
            t = b % 16
            tot += 1
            blk = rr["fsc"][b] if b < len(rr["fsc"]) else {}
            if t in blk and V.peak(blk[t]["out"]) > 1e-4:
                heard += 1
        fin = rr["ok"] and all(math.isfinite(x) for blk in rr["buffers"] for t in range(16) for x in blk[t])
        out[label] = {"ok": rr["ok"], "skips": skips, "our_end_over_P": round(((end - mark0) & 0xFFFFFFFF) / P, 3)
                      if end is not None else None, "newest_heard": heard / max(tot, 1), "finite": fin,
                      "instructions_per_block": rr.get("instructions", 0) // nb}
        print(f"    fstress {label} ({name}): {out[label]}", flush=True)
    checks = {
        "every block of A and B returns": all(o["ok"] for o in out.values()),
        "our voices done by 0.8 of the frame (the guard's limit holds)":
            all(o["our_end_over_P"] is not None and o["our_end_over_P"] <= 0.8 for o in out.values()),
        "with time short, voices are left out and counted": all(o["skips"] for o in out.values()),
        "the newest note heard in most blocks (newest first)": all(o["newest_heard"] >= 0.8 for o in out.values()),
        "every buffer finite": all(o["finite"] for o in out.values()),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": out}


def step_stock(snap, m2mach, m5: Image, stock: Image, sound, machines, blocks) -> dict:
    others = {1: 1, 2: 0, 3: 2, 4: 3}                       # WaveTone, FM Tone, FM Drum, Swarmer

    def frames(t0):
        return lambda b: base_frame(sound, machines, t0=t0, others=others, trigger=(b == 1),
                                    trigger_others=True).to_bytes()

    a = run_blocks(init_on(snap, m2mach, m5), frames(4), blocks)        # no type-5 track, M5 image
    b = run_blocks(init_on(snap, m2mach, stock), frames(4), blocks)     # the same, stock image
    c = run_blocks(init_on(snap, m2mach, m5), frames(5), blocks)        # track 0 type 5, M5 image
    d = run_blocks(init_on(snap, m2mach, m5), frames(SM.TYPE_OF["ONESHOT"]), blocks)   # track 0 ONESHOT
    e = run_blocks(init_on(snap, m2mach, m5), frames(SM.TYPE_OF["WERP"]), blocks)      # track 0 WERP
    # v0.33: each Monomachine machine on track 0 (the owner's v0.32 report: with one MnM track a
    # noise on every track's notes, the stock machines' and the input's): tracks 1-15 must stay
    # the stock run's, bit for bit, while it plays
    from dnfw.mnm import machines as MMx

    def mnm_frames(k):
        def f(b):
            fr = base_frame(sound, machines, t0=MMx.TYPES[k], others=others, trigger=(b == 1), trigger_others=True)
            for slot, w in mnm_words(k).items():
                fr.param(0, slot, w)
            return fr.to_bytes()
        return f
    mn = {MMx.NAMES[k]: run_blocks(init_on(snap, m2mach, m5), mnm_frames(k), blocks) for k in range(len(MMx.NAMES))}
    # v0.45: FASCIA on track 0 (struck with the others): tracks 1-15 stay the stock run's
    from dnfw.fascia import bench as _FB             # noqa: PLC0415

    def fsc_frames(b):
        fr = base_frame(sound, machines, t0=FSM.TYPE, others=others, trigger=(b == 1), trigger_others=True)
        for c_, w_ in _FB.panel_words({}).items():
            fr.param(0, FSM.SLOTS[c_][1], w_)
        fr.header(FSP.VEL_OFFSET, 0, _FB.vel_word(0.8))
        return fr.to_bytes()
    fs = run_blocks(init_on(snap, m2mach, m5), fsc_frames, blocks)
    mn["FASCIA"] = fs
    ok_runs = a["ok"] and b["ok"] and c["ok"] and d["ok"] and e["ok"] and all(x["ok"] for x in mn.values())
    mn_bad = {n: [t for t in range(1, 16) if any(blk[t] != sb[t] for blk, sb in zip(x["buffer_bits"], b["buffer_bits"]))]
              for n, x in mn.items()} if ok_runs else None
    # compared as bit patterns: the runner's FM Tone voice can produce NaN, and NaN != NaN
    all16 = ok_runs and a["buffer_bits"] == b["buffer_bits"]
    t1_15 = ok_runs and [blk[1:] for blk in c["buffer_bits"]] == [blk[1:] for blk in b["buffer_bits"]]
    active = [t for t in range(1, 16) if ok_runs and any(any(blk[t]) for blk in b["buffer_bits"])]
    nan = [t for t in range(16) if ok_runs and any(x != x for blk in b["buffers"] for x in blk[t])]
    checks = {
        "the five runs return every block": ok_runs,
        "no type-5 track: all 16 track buffers bit-identical, M5 image vs stock": all16,
        "track 0 type 5: tracks 1-15 bit-identical to the stock run": t1_15,
        "v0.13: track 0 ONESHOT (8), then WERP (9): tracks 1-15 bit-identical to the stock run":
            ok_runs and all([blk[1:] for blk in x["buffer_bits"]] == [blk[1:] for blk in b["buffer_bits"]]
                            for x in (d, e)),
        "v0.33: a Monomachine machine on track 0 (each of them), v0.45 FASCIA: tracks 1-15 bit-identical to "
        "the stock run":
            ok_runs and not any(mn_bad.values()),
        "v0.45: FASCIA on track 0 sounds, bit-exact to its model": ok_runs and fsc_exact(fs)[1:] == (0, 0)
            and fsc_exact(fs)[0] == len(fs["fsc"]) and any(any(b_["bits"]) for blk in fs["fsc"] for b_ in blk.values()),
        "stock machines wrote their tracks (non-zero bits on at least one of tracks 1-4)":
            bool(set(active) & {1, 2, 3, 4}),
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"others": others, "tracks_with_nonzero_bits_stock": active, "mnm_tracks_differing": mn_bad,
                        "tracks_with_nan_stock": nan,
                        "peaks_stock": [max((V.peak([x for x in blk[t] if x == x]) for blk in b["buffers"]), default=0)
                                        for t in range(16)] if ok_runs else None,
                        "loop_entries": {"m5_no_type5": a.get("loop_entries"), "stock": b.get("loop_entries"),
                                         "m5_type5": c.get("loop_entries")},
                        "halts": {k: r.get("halt") for k, r in (("a", a), ("b", b), ("c", c), ("d", d), ("e", e))
                                  if not r["ok"]}}}


# -- (step 6, PING, removed in v0.45; docs/ping.md) -----------------------------------------------------------------

PING_FIELDS = (0x1C8, 0x1CC, 0x1D0, 0x1EC, 0x1F0, 0x1F4, 0x1F8, 0x1FC, 0x204, 0x208)


def f32_of(word) -> float:
    return struct.unpack("<f", struct.pack("<I", (word or 0) & 0xFFFFFFFF))[0]


def bits_of(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


def ping_settings(kind: int, *, freq=0x4800, res=0x6000, drive=0x4000, atk=0x0300, dec=0x5800,
                  curve=0x6800, strike=0x7f00, depth=0x4000, keyt=0) -> dict:
    """Frame parameter words for a FLTR page set to PING: param index -> 16-bit value
    (the stock filter parameters 66..79, frame.RECORD_FIELDS)."""
    return {66: int((kind + 0.5) / 4 * 32512), 67: freq, 68: res, 69: depth, 70: drive,
            71: atk, 72: dec, 73: curve, 74: strike, 79: keyt}


# v0.45: PING removed (owner, 2026-11-08): run_ping and step_ping went with it. ping.asm is
# now the shared tail alone (the register restore and the rejoin at 0x1c944c), still entered
# at PING_SW; ping_settings, f32_of, bits_of and PING_FIELDS stay for the steps below.


# -- step 7: SHFT (docs/shft.md) -----------------------------------------------------------------

def shft_settings(mode: int, *, freq=0x5400, fdbk=0x0000, drive=0x3000, atk=0x0300, dec=0x5000,
                  mix=0x7f00, depth=0x4000, keyt=0) -> dict:
    """Frame parameter words for a FLTR page set to SHFT (the stock filter parameters)."""
    return {66: int((mode + 0.5) / 3 * 32512), 67: freq, 68: fdbk, 69: depth, 70: drive,
            71: atk, 72: dec, 73: mix, 79: keyt}


def run_filter_pair(init, sound, machines, blocks, ftypes, settings):
    """Track 0 (Waverider) and track 1 (WaveTone) on filter types FTYPES[0], FTYPES[1],
    with frame parameter words SETTINGS[0], SETTINGS[1], triggered on block 1; taps as
    run_ping's, at wr_ping's entry."""
    taps = []
    # v0.17: track 0's PERC voice is the Machinedrum's TRX-CY (a long ring, so a grain
    # scattered late still finds sound): its TYPE and its eight parameters, no effects
    cy = PM.NAMES.index("TRX-CY")
    source = {PERC_TYPE_SLOT: perc_type_word(cy)}
    for (_rid, slot, lo, top), x in zip(PM.PARAMS, PL.defaults("TRX-CY")):
        source[slot] = PL.word_of(x, top, lo)

    def at_entry(r):
        bufs = [m2.word(r.state, V.TRACK_BUFFERS + 4 * t) for t in range(16)]
        trig = (m2.word(r.state, TRIG_WORD) or 0) >> 16
        tap = {}
        for t in range(16):
            rec = V.track_record(t)
            tap[t] = {"before": [m2.word(r.state, bufs[t] + 4 * k) or 0 for k in range(BLOCK)],
                      "rec": {o: f32_of(m2.word(r.state, rec + o)) for o in PING_FIELDS},
                      "note": f32_of(m2.word(r.state, NOTE_CELL + 4 * t)),
                      "trig": bool(trig & (1 << t)),
                      "ftype": frame_word(r.state, FR.FILTER + 2 * t)}
        taps.append(tap)

    def frames(b):
        f = base_frame(sound, machines, t0=5, others={1: 1}, trigger=(b == 1), trigger_others=True,
                       overrides={WAV1: 0x3C00, **source, **settings[0]})
        f.header(FR.FILTER, 0, ftypes[0])
        f.header(FR.FILTER, 1, ftypes[1])
        f.sound(1, {**machines.get(1, {}), TUN1: TUN1_ZERO, **settings[1]})
        return f.to_bytes()
    run = run_blocks(init, frames, blocks, extra_hooks={dsp.PING_SW: at_entry})
    return run, taps


def step_shft(init, sound, machines, blocks) -> dict:
    """SHFT on its own (UP with feedback beside DOWN with the envelope), then beside PING
    (BOTH on track 0, PING VCFQ on track 1): every SHFT track bit-exact to
    dnfw.shft.live, every PING track still bit-exact to dnfw.ping.live."""
    from dnfw.ping import live as PL
    from dnfw.shft import live as SL
    PT, ST = PL.tables(), SL.tables()
    cases = {
        "UP+fdbk / DOWN+env": ((SL.FILTER_TYPE, SL.FILTER_TYPE),
                               (shft_settings(0, fdbk=0x7800), shft_settings(1, freq=0x3000, depth=0x7000))),
        "BOTH / PING VCFQ": ((SL.FILTER_TYPE, PL.FILTER_TYPE),
                             (shft_settings(2, freq=0x6000, mix=0x4000, keyt=0x7f00),
                              ping_settings(2, freq=0x3C00))),
    }
    results = {}
    for name, (ftypes, settings) in cases.items():
        run, taps = run_filter_pair(init, sound, machines, blocks, ftypes, settings)
        if not run["ok"] or len(taps) != blocks:
            results[name] = {"ok": False, "why": run.get("halt") or f"{len(taps)} entries"}
            continue
        sv = {t: SL.Voice() for t in range(16)}
        pv = {t: PL.Voice() for t in range(16)}
        mism, peaks, untouched, seen = {}, {}, True, set()
        for b, tap in enumerate(taps):
            after = run["machine"][b]
            for t in range(16):
                x = tap[t]
                if x["ftype"] == SL.FILTER_TYPE:
                    want = SL.block(sv[t], [f32_of(w) for w in x["before"]], x["rec"], x["note"], x["trig"], ST)
                elif x["ftype"] == PL.FILTER_TYPE:
                    want = PL.block(pv[t], [f32_of(w) for w in x["before"]], x["rec"], x["note"], x["trig"], PT)
                else:
                    untouched &= [bits_of(v) for v in after[t]] == x["before"]
                    continue
                seen.add((t, x["ftype"]))
                got = [bits_of(v) for v in after[t]]
                mism[t] = mism.get(t, 0) + sum(1 for g, w in zip(got, want) if g != bits_of(w))
                peaks[t] = max(peaks.get(t, 0.0), max(abs(v) for v in after[t] if v == v))
        results[name] = {"ok": True, "mismatches": mism, "peaks": peaks, "others_untouched": untouched,
                         "tracks": sorted(seen), "want": [(0, ftypes[0]), (1, ftypes[1])]}
    checks = {
        "SHFT runs on every track set to filter type 7, beside SHFT and beside PING":
            all(r.get("ok") and r["tracks"] == r["want"] for r in results.values()),
        "every SHFT track bit-exact to dnfw.shft.live, and PING beside it to dnfw.ping.live, "
        "fed the DSP's own inputs, in every block (UP, DOWN, BOTH)":
            all(r.get("ok") and not any(r["mismatches"].values()) for r in results.values()),
        "every SHFT / PING track is audible and bounded (0.001 < peak <= 1.0)":
            all(r.get("ok") and all(0.001 < p <= 1.0 + 1e-6 for p in r["peaks"].values())
                for r in results.values()),
        "tracks on other filter types pass through bit-identical":
            all(r.get("ok") and r["others_untouched"] for r in results.values()),
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {k: {kk: vv for kk, vv in v.items() if kk != "want"} for k, v in results.items()}}


# -- step 7b: GRAN (docs/gran.md) -----------------------------------------------------------------

GRAN_BLOCKS = 24                # 768 samples: grains start, overlap, end and read back the feedback


def gran_settings(mode: int, *, size=0x3000, dens=0x7f00, sprd=0x4000, drive=0x3000, fdbk=0,
                  mix=0x7f00) -> dict:
    """Frame parameter words for a FLTR page set to GRAN (the stock filter parameters)."""
    return {66: int((mode + 0.5) / 4 * 32512), 67: size, 68: dens, 69: sprd, 70: drive,
            71: fdbk, 73: mix}


def step_gran(init, sound, machines) -> dict:
    """GRAN in each mode, beside itself and beside SHFT: every GRAN track bit-exact to
    dnfw.grain.live (its buffer carried from block to block), SHFT beside it still
    bit-exact to dnfw.shft.live, every other track untouched."""
    from dnfw.grain import live as GL
    from dnfw.shft import live as SL
    GT, ST = GL.tables(), SL.tables()
    cases = {
        "NORM / UP+fdbk": ((GL.FILTER_TYPE, GL.FILTER_TYPE),
                           (gran_settings(0), gran_settings(1, size=0x1000, fdbk=0x6000, mix=0x5000))),
        "DOWN+sprd / REV": ((GL.FILTER_TYPE, GL.FILTER_TYPE),
                            # (v0.17: track 0's source is the MD's TRX-CY, which starts at the
                            # note: a spread of 0x7f00 put this case's one grain before it)
                            (gran_settings(2, sprd=0x2000, dens=0x2000), gran_settings(3, size=0x0800, dens=0))),
        "GRAN / SHFT": ((GL.FILTER_TYPE, SL.FILTER_TYPE),
                        (gran_settings(0, sprd=0x0400, fdbk=0x7f00), shft_settings(0, fdbk=0x7800))),
    }
    results = {}
    for name, (ftypes, settings) in cases.items():
        run, taps = run_filter_pair(init, sound, machines, GRAN_BLOCKS, ftypes, settings)
        if not run["ok"] or len(taps) != GRAN_BLOCKS:
            results[name] = {"ok": False, "why": run.get("halt") or f"{len(taps)} entries"}
            continue
        gv = {t: GL.Voice() for t in range(16)}
        sv = {t: SL.Voice() for t in range(16)}
        mism, peaks, untouched, seen = {}, {}, True, set()
        for b, tap in enumerate(taps):
            after = run["machine"][b]
            for t in range(16):
                x = tap[t]
                if x["ftype"] == GL.FILTER_TYPE:
                    want = GL.block(gv[t], [f32_of(w) for w in x["before"]], x["rec"], x["note"], x["trig"], GT)
                elif x["ftype"] == SL.FILTER_TYPE:
                    want = SL.block(sv[t], [f32_of(w) for w in x["before"]], x["rec"], x["note"], x["trig"], ST)
                else:
                    untouched &= [bits_of(v) for v in after[t]] == x["before"]
                    continue
                seen.add((t, x["ftype"]))
                got = [bits_of(v) for v in after[t]]
                mism[t] = mism.get(t, 0) + sum(1 for g, w in zip(got, want) if g != bits_of(w))
                peaks[t] = max(peaks.get(t, 0.0), max(abs(v) for v in after[t] if v == v))
        results[name] = {"ok": True, "mismatches": mism, "peaks": peaks, "others_untouched": untouched,
                         "tracks": sorted(seen), "want": [(0, ftypes[0]), (1, ftypes[1])],
                         "grains_started": {t: gv[t].idx for t, ft in enumerate(ftypes)
                                            if ft == GL.FILTER_TYPE}}
    checks = {
        "GRAN runs on every track set to filter type 8, beside GRAN and beside SHFT":
            all(r.get("ok") and r["tracks"] == r["want"] for r in results.values()),
        "every GRAN track bit-exact to dnfw.grain.live, fed the DSP's own inputs, in every block of "
        f"{GRAN_BLOCKS} (NORM, UP, DOWN, REV; feedback; scatter), and SHFT beside it to dnfw.shft.live":
            all(r.get("ok") and not any(r["mismatches"].values()) for r in results.values()),
        "every GRAN / SHFT track is audible and bounded (0.001 < peak <= 1.0), and grains start":
            all(r.get("ok") and all(0.001 < p <= 1.0 + 1e-6 for p in r["peaks"].values())
                and all(n > 0 for n in r["grains_started"].values()) for r in results.values()),
        "tracks on other filter types pass through bit-identical":
            all(r.get("ok") and r["others_untouched"] for r in results.values()),
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {k: {kk: vv for kk, vv in v.items() if kk != "want"} for k, v in results.items()}}


# -- step 8: the Monomachine machines (v0.26, docs/mnm.md) ---------------------------------------

def mnm_words(k: int, knobs=None) -> dict:
    """frame slot -> word for the Monomachine machine K's eight knobs (0..127, default its
    own defaults), on PERC's eight parameter records (as page.c's mnm_knob reads them)"""
    from dnfw.mnm import machines as MM
    knobs = MM.DEFAULTS[MM.NAMES[k]] if knobs is None else knobs
    return {slot: PL.knob_word(x, top, lo) for (_rid, slot, lo, top), x in zip(PM.PARAMS, knobs)}


def _slim(run: dict) -> dict:
    """a run without the emulator's state (the Monomachine step keeps 16 runs: memory)"""
    run.pop("state", None)
    return run


def step_mnm(init, sound, machines, blocks) -> dict:
    """Each Monomachine machine (its own machine type, PERC's voice) on track 0, beside the
    next one on track 1, and with every knob up: every such track's buffer and state
    bit-exact to dnfw.perc.program run on the DSP's memory at PERC's entry, every block;
    audible and bounded; an untriggered track silent; the DSP budget in track order. (Their
    pitch is test_perc_live's, on the same program in the model.)"""
    from dnfw.mnm import machines as MM
    types = {k: typ for typ, k in PP.MNM_TYPES.items()}

    def frames(k, note=0x3C00, trig=(1,), knobs=None, other=None):
        def fb(b):
            others = {1: types[other]} if other is not None else None
            f = base_frame(sound, machines, t0=types[k], overrides=mnm_words(k, knobs), note=note,
                           trigger=b in trig, others=others, trigger_others=True)
            if other is not None:
                f.header(FR.NOTE, 1, note)               # the same note on track 1
                for slot, w in mnm_words(other).items():
                    f.param(1, slot, w)
            return f.to_bytes()
        return fb

    runs = {}
    for k, name in enumerate(MM.NAMES):
        t0 = time.perf_counter()
        runs[f"{name}"] = _slim(run_blocks(init, frames(k, other=(k + 1) % len(MM.NAMES)), blocks))
        runs[f"{name}_tops"] = _slim(run_blocks(init, frames(k, knobs=[127] * 8), blocks))
        print(f"    {name}: {round(time.perf_counter() - t0)} s", flush=True)
    runs["silent"] = _slim(run_blocks(init, frames(0, trig=()), blocks))
    # the budget: SID on tracks 0..3 at once; those whose cost fits PP.MNM_BUDGET in track
    # order play, the rest are silent
    sid = MM.NAMES.index("SID 6581")
    fits = PP.MNM_BUDGET // PP.MNM_COST["SID 6581"]

    def four(b):
        f = base_frame(sound, machines, t0=types[sid], overrides=mnm_words(sid), trigger=b == 1,
                       others={t: types[sid] for t in (1, 2, 3)}, trigger_others=True)
        for t in (1, 2, 3):
            for slot, w in mnm_words(sid).items():
                f.param(t, slot, w)
        return f.to_bytes()
    runs["budget"] = _slim(run_blocks(init, four, blocks))

    # v0.29: dynamic voice allocation -- each new note on a new slot (0, 1, 2, 3 at blocks
    # 1, 3, 5, 7), the older voices still sounding: the newest always plays, and once more
    # than fit, the oldest are the ones silenced (before, the first slots kept the budget)
    def dyn(b):
        f = base_frame(sound, machines, t0=types[sid], overrides=mnm_words(sid), trigger=b == 1,
                       others={t: types[sid] for t in (1, 2, 3)})
        for t in (1, 2, 3):
            for slot, w in mnm_words(sid).items():
                f.param(t, slot, w)
            if b == 1 + 2 * t:
                f.trigger(t)
        return f.to_bytes()
    dyn_blocks = max(blocks, 9)
    runs["dynamic"] = _slim(run_blocks(init, dyn, dyn_blocks))

    # v0.29: a voice whose sound has died away after the chain rests after
    # PP.MNM_QUIET_BLOCKS blocks -- no cost -- and its next note wakes it. The runner's AMP
    # never closes (no note-off), so the chain's silence is made right after track 0's amp
    # (its buffer zeroed there, as an AMP envelope that has closed would leave it, which is
    # what PERC's entry reads next block); the voice's own render, taken at the sample
    # machines' entry, is what the check reads after the wake
    REST_AT = PP.MNM_QUIET_BLOCKS + 4
    seen_cost = {}

    def rest_frame(b):
        return base_frame(sound, machines, t0=types[sid], overrides=mnm_words(sid),
                          trigger=b in (1, REST_AT)).to_bytes()

    def rest_hook(r):
        seen_cost[len(seen_cost)] = m2.word(r.state, PERC_L.md.mnm.scratch + PP.MNM_COSTS_OFF) or 0

    def hush(r):                                # after the amp: the chain's block silent
        if len(seen_cost) <= REST_AT - 1:
            buf = m2.word(r.state, PP.BUFFERS) or 0
            for k in range(BLOCK):
                m2.poke(r.state, buf + 4 * k, 0)
    rr = run_blocks(init, rest_frame, REST_AT + 3, extra_hooks={dsp.SMP_SW: rest_hook, AMP_RETURN: hush})
    rest_peak_after = max(V.peak(rr["perc"][b][0]["out"]) for b in (REST_AT, REST_AT + 1, REST_AT + 2)) \
        if rr["ok"] and all(0 in rr["perc"][b] for b in (REST_AT, REST_AT + 1, REST_AT + 2)) else 0.0
    rest_ok = rr["ok"] and seen_cost.get(REST_AT - 2) == 0 and seen_cost.get(2, 0) > 0 and rest_peak_after > 0.01
    rr.pop("state", None)
    ok_runs = all(r["ok"] for r in runs.values())
    exact = {k: perc_exact(r) for k, r in runs.items() if r["ok"]}
    peaks = {name: V.peak(perc_series(runs[name], 0)) if runs[name]["ok"] else None for name in MM.NAMES}
    budget = [V.peak(perc_series(runs["budget"], t)) if runs["budget"]["ok"] else None for t in range(4)]
    # still sounding at the end (a voice that writes over its own words falls silent after
    # its first block, and its model with it: v0.26 WIP)
    late = {name: V.peak(perc_series(runs[name], 0)[-4 * BLOCK:]) if runs[name]["ok"] else None
            for name in MM.NAMES}
    other = {name: V.peak(perc_series(runs[name], 1)) if runs[name]["ok"] else None for name in MM.NAMES}
    silent = perc_series(runs["silent"], 0)
    n = {"exact_voice_blocks_out_state_mismatches": exact, "peaks": peaks, "peaks_track1": other,
         "instructions_per_block": {k: round(r.get("instructions", 0) / max(blocks, 1))
                                    for k, r in runs.items() if r["ok"]},
         "wall_s": {k: r.get("wall_s") for k, r in runs.items()},
         "halts": {k: r.get("halt") for k, r in runs.items() if not r["ok"]}}
    checks = {
        "every run returns every block": ok_runs,
        "every Monomachine track's buffer and state, every block of every run, are bit-exact to "
        "dnfw.perc.program run on the DSP's memory at PERC's entry":
            ok_runs and all(v[0] > 0 and v[1] == 0 and v[2] == 0 for k, v in exact.items() if k != "silent")
            and exact.get("silent", (0, 1, 1))[1:] == (0, 0),
        "each machine sounds on track 0 and beside it on track 1 (peak > 0.005; VO-6's onset is 0.009)":
            all(v is not None and v > 0.005 for v in list(peaks.values()) + list(other.values())),
        "each machine is still sounding in the run's last four blocks (peak > 0.005)":
            all(v is not None and v > 0.005 for v in late.values()),
        "nothing is non-finite or above 4.0 in any buffer":
            ok_runs and all(math.isfinite(x) and abs(x) <= 4.0 for r in runs.values() for blk in r["perc"]
                            for v in blk.values() for x in v["out"]),
        "control: no trigger is silent (every sample 0)": bool(silent) and all(x == 0.0 for x in silent),
        f"the budget: of four SID tracks the first {fits} play, the rest are silent":
            None not in budget and all(v > 0.01 for v in budget[:fits]) and all(v == 0.0 for v in budget[fits:]),
    }
    dynr = runs["dynamic"]

    def dpk(b, t):
        return V.peak(dynr["perc"][b][t]["out"]) if dynr["ok"] and t in dynr["perc"][b] else 0.0
    newest = [max(dpk(1 + 2 * k, k), dpk(2 + 2 * k, k)) for k in range(4)]   # (a SID note's onset can fall in the next block)
    last = [dpk(dyn_blocks - 1, t) for t in range(4)]
    checks["v0.29, dynamic allocation: each new note sounds by the block after its own; at the end the newest " \
           f"{fits} play and the oldest are silent"] = (
        all(v > 0.01 for v in newest) and all(v > 0.01 for v in last[4 - fits:])
        and all(v == 0.0 for v in last[:4 - fits]))
    n["dynamic_newest_peaks"], n["dynamic_last_peaks"] = newest, last
    checks["v0.29: a voice whose sound has died away rests (no cost) and its next note wakes it"] = rest_ok
    n["rest_costs"] = {k: seen_cost.get(k) for k in (2, REST_AT - 2, REST_AT + 1)}
    n["rest_peak_after"] = rest_peak_after
    n["budget_peaks"] = budget
    n["late_peaks"] = late
    return {"ok": all(checks.values()), "checks": checks, "numbers": n, "runs": runs}


def step_filters_stock(snap, m2mach, m5: Image, stock: Image, sound, machines, blocks) -> dict:
    """Tracks 1-6 on the six stock filter types (0..5), no PING: every track buffer and
    the amp's input and output bit-identical between the modified image and stock."""
    def frames(b):
        f = base_frame(sound, machines, t0=1, others={t: 1 for t in range(1, 7)}, trigger=(b == 1),
                       trigger_others=True)
        for t, ft in enumerate(range(6), start=1):
            f.header(FR.FILTER, t, ft)
        return f.to_bytes()
    a = run_blocks(init_on(snap, m2mach, m5), frames, blocks)
    b = run_blocks(init_on(snap, m2mach, stock), frames, blocks)
    ok = a["ok"] and b["ok"]
    checks = {
        "the two runs return every block": ok,
        "stock filter types 0-5 (tracks 1-6): every track buffer bit-identical, modified image vs stock":
            ok and a["buffer_bits"] == b["buffer_bits"],
        "the amp stage's input and output on track 0 bit-identical":
            ok and [bits_of(x) for x in a["amp_in"]] == [bits_of(x) for x in b["amp_in"]]
            and [bits_of(x) for x in a["amp_out"]] == [bits_of(x) for x in b["amp_out"]],
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"halts": {k: r.get("halt") for k, r in (("mod", a), ("stock", b)) if not r["ok"]}}}


# -- step 5 -------------------------------------------------------------------------------------------

def step_frame(init, frames, blocks) -> dict:
    for fr in frames:
        if len(fr) != FR.FRAME_BYTES:
            raise SystemExit(f"a frame is {len(fr)} bytes, not {FR.FRAME_BYTES}")
    run = run_blocks(init, lambda b: frames[min(b, len(frames) - 1)], blocks)
    types = sorted({t for i in run["t5_inputs"] for t in i}) if run["ok"] else []
    exact = perc_exact(run) if run["ok"] else (0, -1, -1)
    checks = {"the run returns every block": run["ok"],
              "at least one track is type 5": bool(types),
              "every type-5 track is bit-exact to dnfw.perc.program": exact[0] > 0 and exact[1:] == (0, 0)}
    if any(fr[FR.TRIG_NOTE] & 1 for fr in frames):
        # a frame that triggers track 0: it must be heard at the amp's output
        checks["triggered: track 0 audible at the amp's output (peak > 0.02)"] = (
            run["ok"] and V.peak(run["amp_out"]) > 0.02)
    return {"ok": all(checks.values()), "checks": checks, "run": run,
            "numbers": {"type5_tracks": types, "exact": exact,
                        "inputs_last_block": run["t5_inputs"][-1] if run["ok"] and run["t5_inputs"] else None,
                        "amp_out_peak": V.peak(run["amp_out"]) if run["ok"] else None,
                        "halt": run.get("halt")}}


if __name__ == "__main__":
    raise SystemExit(main())

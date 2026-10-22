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
6-9. **PING, SHFT, GRAN, RESONATOR, CZ** -- each bit-exact to its own model.

Every step writes WAVs under out/waverider/m5_*.wav (48 kHz, 16-bit mono, >= 2 s).
Runner blocks are short, so a WAV made of them is LOOPED and says so.
`m5_report.json` has the numbers. Exit 0 when
every step passes.
"""

from __future__ import annotations

import argparse
import dataclasses
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
from dnfw.waverider import frame as FR                         # noqa: E402
from dnfw.waverider import voice as V                          # noqa: E402

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


def init_on(snap, m2mach, image: Image):
    """The Milestone 2 post-init snapshot, re-pointed at IMAGE (engine init never
    touches the spans we add or the two words we patch; step 2 checks the spans)."""
    runner = fx.sr.load_snapshot(str(snap), m2mach.memory)
    runner.data = image.memory
    runner.state = dataclasses.replace(runner.state, concrete=image.memory)
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
           "perc": [], "smp": [], "loop_entries": 0, "smp_entries": 0, "setup": []}
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
            for t in range(16):
                rec = V.track_record(t)
                if (m2.word(r.state, rec + V.TRACK_MACHINE) == 5
                        and frame_word(r.state, FR.header_offset(FR.MACHINE, t)) == PP.MACHINE_TYPE):
                    ins[t] = {"note": V.bits_f32(m2.word(r.state, NOTE_CELL + 4 * t) or 0),
                              "trig": bool(((m2.word(r.state, TRIG_WORD) or 0) >> 16) & (1 << t)),
                              "type": frame_word(r.state, FR.slot_offset(t, PM.TYPE_REC[1])),
                              "params": [frame_word(r.state, FR.slot_offset(t, slot))
                                         for _rid, slot, _lo, _top in PM.PARAMS]}
                    st = r.state
                    p, mem = PP.run_voice(PERC_L, lambda a, st=st: m2.word(st, a) or 0, t)
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
                 dsp.RINGS_SW: at_after_smp,
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
    """PERC: the block counter's jump into wr_perc (L2), and wr_perc's tail into
    rings.asm's wr_rings: addresses, not labels."""
    count = (SHARC / "block_count.asm").read_text(encoding="utf-8")
    perc = (SHARC / "perc.asm").read_text(encoding="utf-8")
    return (f"JUMP {dsp.PERC_SW:#x};" in count
            and re.findall(r"JUMP (0x[0-9a-f]+);\s*// smp.asm's wr_smp", perc) == [f"{dsp.SMP_SW:#x}"]
            and re.findall(r"JUMP (0x[0-9a-f]+);\s*// rings.asm's wr_rings",
                           (SHARC / "smp.asm").read_text(encoding="utf-8")) == [f"{dsp.RINGS_SW:#x}"])


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
                          ("ping", dsp.PING_SW), ("rings", dsp.RINGS_SW),
                          ("cz", dsp.CZ_SW), ("gran", dsp.GRAN_SW)):
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
             for n in ("perc", "smp", "block_count", "ping", "rings", "cz", "gran")) \
        and perc_links_ok() and gran_links_ok() and entry.type_name.startswith("8a") \
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
    p.add_argument("--steps", default="decode,map,voice,smp,stock,ping,shft,gran,rings,cz,frame")   # voice: PERC
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
            for n in ("perc", "smp", "block_count", "ping", "rings", "cz", "gran"):
                for d in s1["detail"][n]["disagreements"][:20]:
                    print("     ", n, d)

        init = init_on(snap, m2mach, m5)
        if "map" in steps:
            print("\nstep 2: map")
            results["2_map"] = step_map(dk, snap, m2mach, m5, stock, init, sound, machines)
            show(results["2_map"])

        if "voice" in steps:
            print("\nstep 3: PERC")
            s3 = step_perc(init, sound, machines, a.blocks)
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

        if "smp" in steps:
            print("\nstep 3b: the sample machines")
            s3b = step_smp(init, sound, machines, a.blocks)
            results["3b_smp"] = {k: v for k, v in s3b.items() if k != "runs"}
            show(s3b)
            mr = s3b["runs"]["mixed"]
            if mr["ok"]:
                for t, what in ((0, "SNARE reversed"), (1, "GRID on BEAT"), (4, "HAT looping")):
                    wav(f"smp_{t}.wav", smp_series(mr, t), a.seconds, wavs,
                        f"the sample machines, mixed run, track {t}: {what}")

        if "stock" in steps:
            print("\nstep 4: types 0-4 unchanged")
            results["4_stock"] = step_stock(snap, m2mach, m5, stock_img, sound, machines,
                                            max(3, a.blocks // 2))
            show(results["4_stock"])
            print("\nstep 4b: stock filter types 0-5 unchanged")
            results["4b_filters"] = step_filters_stock(snap, m2mach, m5, stock_img, sound, machines,
                                                       max(3, a.blocks // 2))
            show(results["4b_filters"])

        if "ping" in steps:
            print("\nstep 6: PING")
            results["6_ping"] = step_ping(init, sound, machines, a.blocks)
            show(results["6_ping"])

        if "shft" in steps:
            print("\nstep 7: SHFT")
            results["7_shft"] = step_shft(init, sound, machines, a.blocks)
            show(results["7_shft"])

        if "gran" in steps:
            print("\nstep 7b: GRAN")
            results["7b_gran"] = step_gran(init, sound, machines)
            show(results["7b_gran"])

        if "rings" in steps:
            print("\nstep 8: RESONATOR")
            results["8_rings"] = step_rings(init, sound, machines, a.blocks)
            show(results["8_rings"])

        if "cz" in steps:
            print("\nstep 9: CZ")
            results["9_cz"] = step_cz(init, sound, machines, a.blocks)
            show(results["9_cz"])

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


def step_perc(init, sound, machines, blocks) -> dict:
    def frames(k, note=0x3C00, trig=(1,), params=None, others=None, other_words=None):
        def fb(b):
            f = base_frame(sound, machines, overrides=perc_words(k, params), note=note, trigger=b in trig,
                           others=others, trigger_others=True)
            for t, words in (other_words or {}).items():
                for slot, w in words.items():
                    f.param(t, slot, w)
            return f.to_bytes()
        return fb

    # the 24 machines, eight tracks at a time (track t of group g plays machine 8 g + t,
    # all triggered on block 1): three runs, eight PERC slots busy at once
    runs = {}
    for g in range(PM.N // 8):
        t0 = time.perf_counter()
        runs[f"g{g}"] = run_blocks(init, frames(8 * g, others={t: 5 for t in range(1, 8)},
                                               other_words={t: perc_words(8 * g + t) for t in range(1, 8)}),
                                   blocks)
        print(f"    machines {8 * g}-{8 * g + 7}: {round(time.perf_counter() - t0)} s", flush=True)
    rs = PM.NAMES.index("TRX-RS")
    sd = PM.NAMES.index("TRX-SD")
    hh = PM.NAMES.index("EFM-HH")
    runs["note60"] = run_blocks(init, frames(rs), blocks)
    runs["single_sd"] = run_blocks(init, frames(sd), blocks)
    runs["note72"] = run_blocks(init, frames(rs, note=0x4800), blocks)
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
    ok_runs = all(r["ok"] for r in runs.values())
    exact = {k: perc_exact(r) for k, r in runs.items() if r["ok"]}
    peaks = {PM.NAMES[k]: V.peak(perc_series(runs[f"g{k // 8}"], k % 8)) if runs[f"g{k // 8}"]["ok"] else None
             for k in range(PM.N)}
    m0 = runs["g0"]
    zc60 = zero_crossings(perc_series(runs["note60"], 0)) if runs["note60"]["ok"] else 0
    zc72 = zero_crossings(perc_series(runs["note72"], 0)) if runs["note72"]["ok"] else 0
    groups = [sorted({t for blk in runs[f"g{g}"]["perc"] for t in blk}) if runs[f"g{g}"]["ok"] else []
              for g in range(PM.N // 8)]
    sw = runs["type_switch"]
    sw_state = [blk[0]["out"] for blk in sw["perc"] if 0 in blk] if sw["ok"] else []
    base = perc_series(runs["g0"], 0)
    sw_series = perc_series(sw, 0)
    rt = perc_series(runs["retrig"], 0)
    one = perc_series(runs["single_sd"], 0)
    silent = perc_series(runs["silent"], 0)
    trig_bits = [x[0]["trig"] for x in m0["t5_inputs"] if 0 in x] if m0["ok"] else []
    fxs = perc_series(runs["fx"], 0)
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
        f"all {PM.N} machines sound with the owner's defaults (peak > 0.05 within {blocks} blocks)":
            all(v is not None and v > 0.05 for v in peaks.values()),
        "nothing is non-finite or above 4.0 in any PERC buffer":
            ok_runs and all(math.isfinite(x) and abs(x) <= 4.0 for r in runs.values() for blk in r["perc"]
                            for v in blk.values() for x in v["out"]),
        "TRX-BD is heard at the amp's output (peak > 0.02)": bool(n["amp_out_peak_m0"]) and n["amp_out_peak_m0"] > 0.02,
        "note 72 is higher than note 60 on TRX-RS (more zero crossings)": zc72 > zc60 > 0,
        "eight PERC tracks at once are all rendered, in each of the three groups":
            groups == [list(range(8))] * (PM.N // 8),
        "TYPE turned mid-note leaves the note on its machine (track 0 identical to the untouched TRX-BD's)":
            bool(sw_series) and sw_series == base,
        "a second note restarts the voice (the retrigger run departs from the single note's at it)":
            bool(rt) and rt[:BLOCK * RETRIG] == one[:BLOCK * RETRIG] and rt[BLOCK * RETRIG:] != one[BLOCK * RETRIG:],
        "control: no trigger is silent (every PERC sample 0)": bool(silent) and all(x == 0.0 for x in silent),
        "v0.12: the track effects change the sound (every one on: the block differs from TRX-SD's own)":
            bool(fxs) and bool(one) and fxs != one and all(math.isfinite(x) for x in fxs),
        "v0.12: a track that leaves PERC while it rings is silent when it comes back with no note":
            bool(before) and V.peak(before) > 0.05 and len(back) >= BLOCK * 2
            and all(x == 0.0 for x in back),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": n, "runs": runs}


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


def step_smp(init, sound, machines, blocks) -> dict:
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
    runs["kick"] = run_blocks(init, frames(ONE, smp_words()), blocks)
    runs["kick_up"] = run_blocks(init, frames(ONE, smp_words({SM.TUNE_REC: 72})), blocks)
    # four sample voices, PERC and a machine with no renderer side by side: track 0 the
    # snare reversed, 1 GRID slicing BEAT, 2 PERC TRX-SD, 3 WERP (silent), 4 the hat
    # looping forward, 5 FM Tone
    sd = PM.NAMES.index("TRX-SD")
    runs["mixed"] = run_blocks(init, frames(
        ONE, smp_words({SM.SAMP_REC: 2, SM.PLAY_REC: 0}),
        others={1: GRID, 2: 5, 3: WERP, 4: ONE, 5: 0},
        other_words={1: smp_words({SM.SAMP_REC: 4, SM.GRID_REC: 48, SM.SLICE_REC: 40}),
                     2: perc_words(sd), 3: smp_words(),
                     4: smp_words({SM.SAMP_REC: 3, SM.PLAY_REC: 80, SM.LOOP_REC: 20})}), blocks)
    runs["off"] = run_blocks(init, frames(ONE, smp_words({SM.SAMP_REC: 0})), blocks)
    runs["empty_slot"] = run_blocks(init, frames(ONE, smp_words({SM.SAMP_REC: 90})), blocks)
    runs["silent"] = run_blocks(init, frames(ONE, smp_words(), trig=()), blocks)
    runs["retrig"] = run_blocks(init, frames(ONE, smp_words(), trig=(1, RETRIG)), blocks)
    runs["tops"] = run_blocks(init, frames(GRID, smp_words({r: 127 for r in SM.RECORDS})), blocks)
    runs["bottoms"] = run_blocks(init, frames(ONE, smp_words({r: 0 for r in SM.RECORDS} | {SM.SAMP_REC: 1,
                                                                                       SM.LEV_REC: 100})), blocks)
    print(f"    sample machines: {round(time.perf_counter() - t0)} s", flush=True)
    ok_runs = all(r["ok"] for r in runs.values())
    exact = {k: smp_exact(r) for k, r in runs.items() if r["ok"]}
    mx = runs["mixed"]
    kick = smp_series(runs["kick"], 0)
    up = smp_series(runs["kick_up"], 0)
    ref = SL.test_samples()
    # the kick as the DSP played it against the sample itself: 0.5 frames a sample, linear
    exp = [ref[0][k // 2] if k % 2 == 0 else 0.5 * (ref[0][k // 2] + ref[0][k // 2 + 1])
           for k in range(len(kick) - BLOCK)]
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
        "ONESHOT plays KICK from the pool as the sample is (max error < 1e-5)": kick_err < 1e-5,
        "TUNE +12 is higher (more zero crossings)": zero_crossings(up) > zero_crossings(kick) > 0,
        "in the mixed run, GRID's slice and the looping hat sound (peak > 0.05); the reversed "
        "snare, which starts at its quiet end, sounds (> 0.01) and grows":
            bool(n["peaks_mixed"]) and n["peaks_mixed"][1] > 0.05 and n["peaks_mixed"][4] > 0.05
            and n["peaks_mixed"][0] > 0.01 and rev_grows,
        "PERC beside them is bit-exact to its model and sounds":
            mx["ok"] and perc_exact(mx)[0] > 0 and perc_exact(mx)[1:] == (0, 0)
            and V.peak(perc_series(mx, 2)) > 0.05,
        "a sample machine with no renderer (WERP) leaves its buffer at 0": bool(werp_buf) and all(x == 0.0 for x in werp_buf),
        "SAMP 0 (OFF), an empty slot and no trigger are silent":
            all(s and all(x == 0.0 for x in s) for s in (off, empty, silent)),
        "a second note restarts the sample": bool(rt) and rt[:BLOCK * RETRIG] == one[:BLOCK * RETRIG]
            and rt[BLOCK * RETRIG:] != one[BLOCK * RETRIG:],
        "nothing non-finite or above 4.0 in any sample buffer":
            ok_runs and all(math.isfinite(x) and abs(x) <= 4.0 for r in runs.values() for blk in r["smp"]
                            for v in blk.values() for x in v["out"]),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": n, "runs": runs}


# -- step 4 -------------------------------------------------------------------------------------------

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
    ok_runs = a["ok"] and b["ok"] and c["ok"] and d["ok"] and e["ok"]
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
        "stock machines wrote their tracks (non-zero bits on at least one of tracks 1-4)":
            bool(set(active) & {1, 2, 3, 4}),
    }
    return {"ok": all(checks.values()), "checks": checks,
            "numbers": {"others": others, "tracks_with_nonzero_bits_stock": active,
                        "tracks_with_nan_stock": nan,
                        "peaks_stock": [max((V.peak([x for x in blk[t] if x == x]) for blk in b["buffers"]), default=0)
                                        for t in range(16)] if ok_runs else None,
                        "loop_entries": {"m5_no_type5": a.get("loop_entries"), "stock": b.get("loop_entries"),
                                         "m5_type5": c.get("loop_entries")},
                        "halts": {k: r.get("halt") for k, r in (("a", a), ("b", b), ("c", c), ("d", d), ("e", e))
                                  if not r["ok"]}}}


# -- step 6: PING (docs/ping.md) -----------------------------------------------------------------

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


def run_ping(init, sound, machines, blocks, kinds):
    """Track 0 (Waverider) and track 1 (WaveTone), both on filter type 6, with the
    PING sub-types KINDS[0] and KINDS[1], triggered on block 1. Records, per block, each
    track's buffer where wr_ping is entered and its inputs there (the record's filter
    floats, the note cell, the trigger bit); the buffers after it are the run's
    `machine` tap (0x1c944c)."""
    from dnfw.ping import live as PL
    taps = []

    def at_ping(r):
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
                       overrides={WAV1: 0x3C00, **ping_settings(kinds[0])})
        f.header(FR.FILTER, 0, PL.FILTER_TYPE)
        f.header(FR.FILTER, 1, PL.FILTER_TYPE)
        f.sound(1, {**machines.get(1, {}), TUN1: TUN1_ZERO, **ping_settings(kinds[1], freq=0x3C00)})
        return f.to_bytes()
    run = run_blocks(init, frames, blocks, extra_hooks={dsp.PING_SW: at_ping})
    return run, taps


def step_ping(init, sound, machines, blocks) -> dict:
    from dnfw.ping import live as PL
    T = PL.tables()
    results, numbers = {}, {}
    for kinds in ((2, 1), (3, 0)):                          # VCFQ + LADR, then LPG + SVF
        run, taps = run_ping(init, sound, machines, blocks, kinds)
        name = f"{PL.TYPES[kinds[0]]}+{PL.TYPES[kinds[1]]}"
        if not run["ok"] or len(taps) != blocks:
            results[name] = {"ok": False, "why": run.get("halt") or f"{len(taps)} PING entries"}
            continue
        voices = {t: PL.Voice() for t in range(16)}
        mism, peaks, untouched, ftypes = {0: 0, 1: 0}, {0: 0.0, 1: 0.0}, True, set()
        for b, tap in enumerate(taps):
            after = run["machine"][b]
            for t in range(16):
                x = tap[t]
                ftypes.add((t, x["ftype"]))
                if x["ftype"] != PL.FILTER_TYPE:
                    untouched &= [bits_of(v) for v in after[t]] == x["before"]
                    continue
                want = PL.block(voices[t], [f32_of(w) for w in x["before"]], x["rec"], x["note"],
                                x["trig"], T)
                got = [bits_of(v) for v in after[t]]
                mism[t] = mism.get(t, 0) + sum(1 for g, w in zip(got, want) if g != bits_of(w))
                peaks[t] = max(peaks.get(t, 0.0), max(abs(v) for v in after[t] if v == v))
        results[name] = {"ok": True, "mismatches": mism, "peaks": peaks, "others_untouched": untouched,
                         "ping_tracks": sorted(t for t, f in ftypes if f == PL.FILTER_TYPE)}
        numbers[name] = results[name]
    checks = {
        "PING runs on both tracks set to filter type 6, Waverider and WaveTone alike":
            all(r.get("ping_tracks") == [0, 1] for r in results.values()),
        "every PING track is bit-exact to dnfw.ping.live, fed the DSP's own inputs, in every block "
        "(VCFQ, LADR, LPG, SVF)":
            all(r.get("ok") and not any(r["mismatches"].values()) for r in results.values()),
        "every PING track is audible and bounded (0.001 < peak <= 0.9)":
            all(r.get("ok") and all(0.001 < p <= 0.9 + 1e-6 for p in r["peaks"].values())
                for r in results.values()),
        "tracks on other filter types pass through wr_ping bit-identical":
            all(r.get("ok") and r["others_untouched"] for r in results.values()),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": numbers}


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
                       overrides={WAV1: 0x3C00, **settings[0]})
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
                            (gran_settings(2, sprd=0x7f00, dens=0x2000), gran_settings(3, size=0x0800, dens=0))),
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


# -- step 8: RESONATOR (docs/rings.md) ------------------------------------------------------------

def run_rings(init, sound, machines, blocks, words0, words1, others=None, trig_every=0, ftype1=None):
    """Tracks 0 and 1 on machine 6 (RESONATOR) with frame words WORDS0 / WORDS1 (param slot
    -> 16-bit), the rest OTHERS ({track: machine}); triggered on block 1 (and every
    TRIG_EVERY blocks after, if set). Taps at wr_rings' entry: each track's buffer, the
    note, the trigger, its machine type and its eight control words."""
    from dnfw.rings import live as RL
    taps = []

    def at_entry(r):
        bufs = [m2.word(r.state, V.TRACK_BUFFERS + 4 * t) for t in range(16)]
        trig = (m2.word(r.state, TRIG_WORD) or 0) >> 16
        tap = {}
        for t in range(16):
            rec = V.track_record(t)
            words = {}
            for slot in RL.CONTROL_SLOTS:
                words[slot] = frame_word(r.state, RL.frame_offset(slot, t))
            tap[t] = {"before": [m2.word(r.state, bufs[t] + 4 * k) or 0 for k in range(BLOCK)],
                      "note": f32_of(m2.word(r.state, NOTE_CELL + 4 * t)),
                      "trig": bool(trig & (1 << t)),
                      "mtype": m2.word(r.state, rec + 0x1B4),
                      "words": words}
        taps.append(tap)

    def frames(b):
        hit = b == 1 or (trig_every and b > 1 and (b - 1) % trig_every == 0)
        f = base_frame(sound, machines, t0=RL.MACHINE_TYPE, others={1: RL.MACHINE_TYPE, **(others or {})},
                       trigger=hit, trigger_others=True, overrides=words0)
        for t in [1] + [t for t, m in (others or {}).items() if m == RL.MACHINE_TYPE]:
            f.sound(t, {**machines.get(1, {}), TUN1: TUN1_ZERO, **words1})
        if ftype1 is not None:
            f.header(FR.FILTER, 1, ftype1)
        return f.to_bytes()
    run = run_blocks(init, frames, blocks, extra_hooks={dsp.RINGS_SW: at_entry})
    return run, taps


def step_rings(init, sound, machines, blocks) -> dict:
    """RESONATOR on tracks 0 and 1 (machine 6), WaveTone on track 2, FM Tone on 3: every
    type-6 track bit-exact to dnfw.rings.live, audible and bounded, other tracks
    untouched by wr_rings; a second run with retriggers, the noise exciter and a plate."""
    from dnfw.rings import live as RL
    T = RL.tables()
    base = dict(RL.DEFAULTS)
    cases = {
        "defaults (harmonic, bright, long) + a bar": (
            base, {**base, RL.P_STRC: 0x3C00, RL.P_BRIT: 0x4000, RL.P_DAMP: 0x5000}, 0),
        "plate + noise exciter, retriggered every 6 blocks": (
            {**base, RL.P_STRC: 0x7800, RL.P_EXCT: 0x6400, RL.P_DAMP: 0x2000, RL.P_TUN: 0x4C00},
            {**base, RL.P_POS: 0x0000, RL.P_HIT: 0x7F00, RL.P_LEV: 0x7F00}, 6),
        "six machine-6 voices: the first four render, the rest are silent": (
            base, {**base, RL.P_STRC: 0x5000}, 0),
    }
    others = {"six machine-6 voices: the first four render, the rest are silent":
              {2: RL.MACHINE_TYPE, 3: RL.MACHINE_TYPE, 4: RL.MACHINE_TYPE, 5: RL.MACHINE_TYPE, 6: 1}}
    results = {}
    for name, (w0, w1, every) in cases.items():
        run, taps = run_rings(init, sound, machines, blocks, w0, w1,
                              others=others.get(name, {2: 1, 3: 0}), trig_every=every)
        if not run["ok"] or len(taps) != blocks:
            results[name] = {"ok": False, "why": run.get("halt") or f"{len(taps)} entries"}
            continue
        voices = {t: RL.Voice() for t in range(16)}
        mism, peaks, untouched, seen = {}, {}, True, set()
        for b, tap in enumerate(taps):
            after = run["machine"][b]
            keep = VOICES.plan({t: (tap[t]["trig"], bool(voices[t].active), voices[t].age)
                                for t in range(16) if tap[t]["mtype"] == RL.MACHINE_TYPE},
                               RL.MAX_VOICES)
            for t in range(16):
                x = tap[t]
                if x["mtype"] != RL.MACHINE_TYPE:
                    untouched &= [bits_of(v) for v in after[t]] == x["before"]
                    continue
                seen.add(t)
                want, did = RL.block(voices[t], keep[t], x["words"], x["note"], x["trig"], T)
                got = [bits_of(v) for v in after[t]]
                mism[t] = mism.get(t, 0) + sum(1 for g, w in zip(got, want) if g != bits_of(w))
                peaks[t] = max(peaks.get(t, 0.0), max(abs(v) for v in after[t] if v == v))
        results[name] = {"ok": True, "mismatches": mism, "peaks": peaks,
                         "others_untouched": untouched, "tracks": sorted(seen)}
    six = results.get("six machine-6 voices: the first four render, the rest are silent", {})
    checks = {
        "RESONATOR runs on every machine-6 track, and only on them":
            all(r.get("ok") for r in results.values())
            and all(r["tracks"] == [0, 1] for k, r in results.items() if r is not six)
            and six.get("tracks") == [0, 1, 2, 3, 4, 5],
        "with six machine-6 voices the first four sound and the fifth and sixth are silent":
            bool(six.get("ok")) and all(six["peaks"][t] > 0.001 for t in (0, 1, 2, 3))
            and all(six["peaks"][t] == 0.0 for t in (4, 5)),
        "every RESONATOR track bit-exact to dnfw.rings.live, fed the DSP's own inputs, in every "
        "block (harmonic, bar, plate; mallet and noise; retriggers)":
            all(r.get("ok") and not any(r["mismatches"].values()) for r in results.values()),
        "every rendered RESONATOR voice is audible and bounded (0.001 < peak <= 0.9)":
            all(r.get("ok") and all(0.001 < p <= 0.9 + 1e-6 for t, p in r["peaks"].items()
                                    if not (r is six and t in (4, 5)))
                for r in results.values()),
        "WaveTone, FM Tone and the MIDI tracks pass through wr_rings bit-identical":
            all(r.get("ok") and r["others_untouched"] for r in results.values()),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": results}


# -- step 9: CZ (docs/cz.md) -----------------------------------------------------------------------

def _cz_wave_word(index: int) -> int:
    """the WAVE frame word whose 33-way choice is INDEX"""
    return int((index + 0.5) * 0x7800 / 33)


def _cz_sus_word(step: int) -> int:
    """the SUS frame word for sustain step 0..7, or 8 for none"""
    return int((step + 0.5) * 0x7800 / 9)


def run_cz(init, sound, machines, blocks, words, others=None, trig_every=0, off_at=None,
           trig_at=None):
    """WORDS = {track: frame words (param slot -> 16-bit)} for the machine-7 tracks (track
    0 among them), the rest OTHERS ({track: machine}); triggered on block 1 (and every
    TRIG_EVERY blocks after, if set). Taps at wr_cz's entry: each track's buffer, note,
    trigger, machine type and control words."""
    from dnfw.cz import live as CL
    taps = []

    def at_entry(r):
        bufs = [m2.word(r.state, V.TRACK_BUFFERS + 4 * t) for t in range(16)]
        trig = (m2.word(r.state, TRIG_WORD) or 0) >> 16
        off = (m2.word(r.state, TRIG_WORD + 4) or 0) & 0xFFFF       # mask 36: the note-off
        tap = {}
        for t in range(16):
            rec = V.track_record(t)
            tap[t] = {"before": [m2.word(r.state, bufs[t] + 4 * k) or 0 for k in range(BLOCK)],
                      "note": f32_of(m2.word(r.state, NOTE_CELL + 4 * t)),
                      "trig": bool(trig & (1 << t)),
                      "off": bool(off & (1 << t)),
                      "mtype": m2.word(r.state, rec + 0x1B4),
                      "words": {slot: frame_word(r.state, CL.frame_offset(slot, t))
                                for slot in CL.CONTROL_SLOTS}}
        taps.append(tap)

    mtypes = {**{t: CL.MACHINE_TYPE for t in words if t}, **(others or {})}

    def frames(b):
        hit = b == 1 or (trig_every and b > 1 and (b - 1) % trig_every == 0)
        if trig_at is not None:
            hit = False
        f = base_frame(sound, machines, t0=CL.MACHINE_TYPE, others=mtypes,
                       trigger=hit, trigger_others=True, overrides=words[0])
        for t in (trig_at or {}).get(b, ()):
            f.trigger(t, masks=(34,))
        for t, w in words.items():
            if t:
                f.sound(t, {**machines.get(1, {}), TUN1: TUN1_ZERO, **w})
        for t in (off_at or {}).get(b, ()):
            f.trigger(t, masks=(36,))
        return f.to_bytes()
    run = run_blocks(init, frames, blocks, extra_hooks={dsp.CZ_SW: at_entry})
    return run, taps


def step_cz(init, sound, machines, blocks) -> dict:
    """CZ (machine 7) on several tracks beside WaveTone and FM Tone: every type-7 track
    bit-exact to dnfw.cz.live in every block -- all eight waves, wave pairs, the four
    SELECTs, ring and noise, the octaves, key follow, sustain steps and none, the DCW
    envelope through its steps, retriggers -- audible and bounded; the voice cap; other
    tracks untouched by wr_cz."""
    from dnfw.cz import live as CL
    T = CL.tables()
    blocks = max(blocks, 16)
    base = dict(CL.DEFAULTS)
    fast = {**{p: 0x6400 for p in CL.P_RATES[:4]}, **{p: 0x7F00 for p in CL.P_RATES[4:]}}
    levels = dict(zip(CL.P_LEVELS, (0x7F00, 0x3400, 0x6800, 0x1000, 0x7F00, 0x4000, 0x0000,
                                    0x400 + int(0.7 * 0x7800))))
    W, S = _cz_wave_word, _cz_sus_word
    cases = {
        "saw and square, the DCW envelope through all eight steps (no sustain); 1+1' detuned": (
            {0: {**base, **fast, **levels, CL.P_WAVE: W(0), CL.P_SUS: S(8), CL.P_DCW: 0x7F00},
             1: {**base, **levels, CL.P_WAVE: W(1), CL.P_SEL: 0x200, CL.P_DET: 0x5E00,
                 CL.P_SUS: S(2), CL.P_RATES[0]: 0x6000, CL.P_RATES[1]: 0x5800}},
            {2: 1, 3: 0}, 0),
        "pulse and saw-pulse, 1+2' ring an octave up, key follow, retriggered every 5 blocks": (
            {0: {**base, **fast, **levels, CL.P_WAVE: W(2), CL.P_SEL: 0x300, CL.P_MOD: 0,
                 CL.P_OCT: 0x100, CL.P_KF: 0x100, CL.P_SUS: S(3)},
             1: {**base, **fast, CL.P_WAVE: W(4), CL.P_SEL: 0x300, CL.P_MOD: 0x100,
                 CL.P_OCT: 0x200, CL.P_DET: 0x2800, CL.P_SUS: S(8)}},
            {2: 1, 3: 0}, 5),
        "resonant pairs and double: 1+2' noise, line 2 alone; pairs alternate by cycle": (
            {0: {**base, **fast, **levels, CL.P_WAVE: W(28), CL.P_SEL: 0x300, CL.P_MOD: 0x200,
                 CL.P_SUS: S(8)},
             1: {**base, **fast, **levels, CL.P_WAVE: W(31), CL.P_SUS: S(5), CL.P_KF: 0x100},
             2: {**base, **fast, **levels, CL.P_WAVE: W(29), CL.P_SEL: 0x100, CL.P_SUS: S(8)}},
            {3: 1, 4: 0}, 0),
        "eight machine-7 voices: the first six render, the rest are silent": (
            {t: {**base, **fast, **levels, CL.P_WAVE: W(30 if t % 2 else 9 + t)}
             for t in range(8)},
            {8: 1}, 0),
    }
    rel = "the note-off: sustain on step 2, key-up at block 8 (a released and a held voice)"
    cases[rel] = ({0: {**base, **levels, CL.P_RATES[0]: 0x6400, CL.P_RATES[1]: 0x6400,
                       **{p: 0x7F00 for p in CL.P_RATES[4:]}, CL.P_RATES[2]: 0x6400,
                       CL.P_RATES[3]: 0x6400, CL.P_SUS: S(1), CL.P_DCW: 0x7F00},
                   1: {**base, **fast, **levels, CL.P_SUS: S(1), CL.P_WAVE: W(3)}},
                  {2: 1, 3: 0}, 0)
    offs = {rel: {8: (0,), 12: (1,)}}
    steal = "voice stealing: eight notes one after another on slots 0-7: the newest six sound"
    cases[steal] = ({t: {**base, **fast, **levels, CL.P_WAVE: W(t)} for t in range(8)}, {8: 1}, 0)
    trig_ats = {steal: {1 + 2 * t: (t,) for t in range(8)}}
    cap = "eight machine-7 voices: the first six render, the rest are silent"
    results = {}
    for name, (words, others, every) in cases.items():
        run, taps = run_cz(init, sound, machines, blocks, words, others=others, trig_every=every,
                           off_at=offs.get(name), trig_at=trig_ats.get(name))
        if not run["ok"] or len(taps) != blocks:
            results[name] = {"ok": False, "why": run.get("halt") or f"{len(taps)} entries"}
            continue
        voices = {t: CL.Voice() for t in range(16)}
        mism, peaks, untouched, seen, steps, offs_seen = {}, {}, True, set(), {}, set()
        sounding = {}
        for b, tap in enumerate(taps):
            after = run["machine"][b]
            keep = VOICES.plan({t: (tap[t]["trig"], bool(voices[t].active), voices[t].age)
                                for t in range(16) if tap[t]["mtype"] == CL.MACHINE_TYPE},
                               CL.MAX_VOICES)
            for t in range(16):
                x = tap[t]
                if x["mtype"] != CL.MACHINE_TYPE:
                    untouched &= [bits_of(v) for v in after[t]] == x["before"]
                    continue
                seen.add(t)
                want, did = CL.block(voices[t], keep[t], x["words"], x["note"], x["trig"], T,
                                     off=x["off"])
                sounding.setdefault(b, set()).update({t} if did else set())
                steps[t] = max(steps.get(t, 0), voices[t].step)
                if x["off"]:
                    offs_seen.add((b, t))
                got = [bits_of(v) for v in after[t]]
                mism[t] = mism.get(t, 0) + sum(1 for g, w in zip(got, want) if g != bits_of(w))
                peaks[t] = max(peaks.get(t, 0.0), max(abs(v) for v in after[t] if v == v))
        results[name] = {"ok": True, "mismatches": mism, "peaks": peaks, "steps": steps,
                         "others_untouched": untouched, "tracks": sorted(seen),
                         "offs": sorted(offs_seen),
                         "last_sounding": sorted(sounding.get(blocks - 1, set()))}
    six = results.get(cap, {})
    first = results.get(next(iter(cases)), {})
    checks = {
        "CZ runs on every machine-7 track, and only on them":
            all(r.get("ok") for r in results.values())
            and all(r["tracks"] == sorted(cases[k][0]) for k, r in results.items()),
        "with eight machine-7 voices the first six sound and the seventh and eighth are silent":
            bool(six.get("ok")) and all(six["peaks"][t] > 0.001 for t in range(6))
            and all(six["peaks"][t] == 0.0 for t in (6, 7)),
        "every CZ track bit-exact to dnfw.cz.live, fed the DSP's own inputs, in every block":
            all(r.get("ok") and not any(r["mismatches"].values()) for r in results.values()),
        "every rendered CZ voice is audible and bounded (0.01 < peak <= 1.0)":
            all(r.get("ok") and all(0.01 < p <= 1.0 for t, p in r["peaks"].items()
                                    if not (r is six and t in (6, 7)))
                for r in results.values()),
        "the DCW envelope reached its last step on the no-sustain voice":
            bool(first.get("ok")) and first["steps"].get(0) == 7,
        "the note-off reaches wr_cz on its track and block, and sends both sustained voices "
        "on past their sustain step":
            bool(results.get(rel, {}).get("ok"))
            # block 1's trigger carries all four masks (base_frame), so 36 rides along with
            # the note-on there: the contract lets the trigger win, and the DSP agreed
            and {(8, 0), (12, 1)} <= set(results[rel]["offs"])
            and all(b in (1, 8, 12) for b, _ in results[rel]["offs"])
            and results[rel]["steps"].get(0, 0) >= 2 and results[rel]["steps"].get(1, 0) >= 2,
        "voice stealing: with notes on eight slots in turn the six newest sound at the end "
        "(slots 2-7) and the two oldest were stolen, whatever their slot":
            bool(results.get(steal, {}).get("ok")) and results[steal]["last_sounding"] == [2, 3, 4, 5, 6, 7],
        "WaveTone, FM Tone and the MIDI tracks pass through wr_cz bit-identical":
            all(r.get("ok") and r["others_untouched"] for r in results.values()),
    }
    return {"ok": all(checks.values()), "checks": checks, "numbers": results}


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

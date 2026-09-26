"""Waverider Milestone 5 (offline): the section 7 a flashable build ships, run in the runner.

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

1. **decode** -- the section 7 is the builder's; every instruction of our code reads
   the same to digikit's decoder and to selache's `selmap` as its source line says,
   on the assembler's boundaries; the entry JUMP decodes as `jump 0x180200`.
2. **map** -- WAV1 (param 26) lands in record +0x4, TBL1 (27) in +0x8, the trig note
   in the note cell; a type-5 frame reaches record +0x1b4 as 5 with the stock clamp
   (the clamp reads frame field 84, not the machine type); control: without the
   lookup patch the type is squashed to 0; our spans read back as the image put them.
3. **voice** -- the init Waverider sound (WaveTone's machine defaults, WAV1 0, TBL1 0,
   note 60), a trigger on block 1: the type-5 loop is entered from the image's JUMP,
   the per-type setup is the no-setup arm, the machine tap is bit-exact to
   `dnfw.waverider.live` fed the DSP's own unpacked inputs, audible and correlated at
   the amp's output. Controls: POS 120 (darker), TBL1 1 (the other table, bit-exact),
   note 72 (an octave up), no trigger (silent).
4. **stock** -- types 0-4 are bit-identical: the same frames with no type-5 track on
   the M5 and the stock image give identical buffers on all 16 tracks, and in a
   type-5 run tracks 1-15 match a stock run.
5. **frame** (with --frame/--frame-be/--frames) -- a caller's frame(s), used verbatim
   every block; every type-5 track's buffer checked against the reference.

Every step writes WAVs under out/waverider/m5_*.wav (48 kHz, 16-bit mono, >= 2 s).
Runner blocks are short, so a WAV made of them is LOOPED and says so, with a PREVIEW
beside it: `dnfw.waverider.live`'s float32 reference -- bit-exact to the runner's
machine tap -- over the whole file. `m5_report.json` has the numbers. Exit 0 when
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
import sharc_waverider_m4 as m4                                # noqa: E402
import sharc_waverider_render as m1                            # noqa: E402
import sharc_waverider_voice as m2                             # noqa: E402
from dnfw.image import bootstream, sharc_object                # noqa: E402
from dnfw.waverider import dsp, live, render, testtable        # noqa: E402
from dnfw.waverider import frame as FR                         # noqa: E402
from dnfw.waverider import voice as V                          # noqa: E402

OUT = ROOT / "out" / "waverider"
SHARC = ROOT / "csrc" / "waverider" / "sharc"
RATE, BLOCK = 48000, 32
LOOP_RESUME = 0x1C944C          # where machine5_live rejoins the per-track chain
AMP_RETURN = 0x1C99D3
SETUP_GUARD, SETUP_TABLE_READ, SETUP_NONE = 0x1C905D, 0x1C90A9, 0x1C90D4
CLAMP_MIN = 0x1C294C
NOTE_CELL = V.ENGINE + 0x1387C
WAV1, TBL1 = 26, 27             # WaveTone's Osc1 Waveform, Osc1 Wave Table
FRAME_COPY = 0x25C48C           # where sw 0x1c2712 copies the frame image


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
    track0 = {**machines.get(1, {}), **(overrides or {})}
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
    them at the loop's entry; the reader blocks the loop filled; loop entries."""
    state = init
    out = {"machine": [], "amp_in": [], "amp_out": [], "buffers": [], "buffer_bits": [], "t5_inputs": [],
           "reader_blocks": [], "loop_entries": 0, "setup": []}
    instr = wall = 0
    for b in range(blocks):
        tap = {}

        def at_dispatch(r):
            tap["bufs"] = [m2.word(r.state, V.TRACK_BUFFERS + 4 * t) for t in range(16)]

        def at_loop(r):
            out["loop_entries"] += 1
            ins = {}
            for t in range(16):
                rec = V.track_record(t)
                if m2.word(r.state, rec + V.TRACK_MACHINE) == 5:
                    ins[t] = {"note": V.bits_f32(m2.word(r.state, NOTE_CELL + 4 * t) or 0),
                              "wav1": frame_word(r.state, FR.slot_offset(t, WAV1)),
                              "tbl1": frame_word(r.state, FR.slot_offset(t, TBL1))}
            tap["t5_inputs"] = ins

        def at_resume(r):
            tap["machine"] = [m2.floats(r.state, tap["bufs"][t], BLOCK) for t in range(16)]
            tap["reader_blocks"] = {t: [m2.word(r.state, dsp.READER_BLOCKS_DM + 32 * t + 4 * k) or 0
                                        for k in range(6)] for t in tap.get("t5_inputs", {})}

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

        hooks = {m3.DISPATCH: at_dispatch, dsp.LOOP_SW: at_loop, LOOP_RESUME: at_resume,
                 m3.AMP_STAGE: amp, AMP_RETURN: amp_ret, SETUP_GUARD: guard,
                 SETUP_TABLE_READ: table_read, SETUP_NONE: none_arm}
        hooks.update(extra_hooks or {})
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
        out["reader_blocks"].append(tap.get("reader_blocks", {}))
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


def reference_for(run, t, tables, precision="float32") -> list[float]:
    """live.render_blocks fed the DSP's own unpacked inputs for track T, block by block."""
    seq = [(i[t]["note"], i[t]["wav1"], i[t]["tbl1"]) for i in run["t5_inputs"] if t in i]
    return live.render_blocks(tables, seq, BLOCK, 0, precision)[0]


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


def decode_check(dk, image: Image, work: pathlib.Path, use_selmap: bool) -> dict:
    res = {}
    for name, load_sw in (("reader_m5", dsp.READER_SW), ("machine5_live", dsp.LOOP_SW)):
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
             for n in ("reader_m5", "machine5_live")) and entry.type_name.startswith("8a") \
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


def preview(tables, note, wav1_from, wav1_to, tbl1, seconds):
    blocks = int(seconds * RATE) // BLOCK
    seq = [(note, round(wav1_from + (wav1_to - wav1_from) * k / max(blocks - 1, 1)), tbl1)
           for k in range(blocks)]
    return live.render_blocks(tables, seq, BLOCK, 0, "float32")[0]


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
    p.add_argument("--steps", default="decode,map,voice,stock,frame")
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
    tables = dsp.tables()
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
            for n in ("reader_m5", "machine5_live"):
                for d in s1["detail"][n]["disagreements"][:20]:
                    print("     ", n, d)

        init = init_on(snap, m2mach, m5)
        if "map" in steps:
            print("\nstep 2: map")
            results["2_map"] = step_map(dk, snap, m2mach, m5, stock, init, sound, machines)
            show(results["2_map"])

        if "voice" in steps:
            print("\nstep 3: voice")
            s3 = step_voice(init, sound, machines, a.blocks, tables)
            results["3_voice"] = {k: v for k, v in s3.items() if k != "runs"}
            show(s3)
            runs = s3["runs"]
            if runs["init"]["ok"]:
                wav("m5_voice_amp_out.wav", runs["init"]["amp_out"], a.seconds, wavs,
                    "the init Waverider sound (saw, note 60, trigger on block 1) at the amp's output, "
                    "end of the per-track chain", normalise=False)
                wav("m5_voice_amp_out_normalised.wav", runs["init"]["amp_out"], a.seconds, wavs,
                    "the same, scaled to 0.9 peak for listening", normalise=True)
                wav("m5_voice_machine.wav", track_series(runs["init"], 0), a.seconds, wavs,
                    "track 0's buffer after the type-5 loop, bit-exact to the reference (init sound)")
                wav("m5_preview_init_sound.wav", preview(tables, 60.0, 0, 0, 0, a.seconds), a.seconds, wavs,
                    "PREVIEW, not the runner: the reference for the init sound, note 60, POS 0, slot 0 (the saw)")
            for key, what, pv in (
                    ("pos120", "POS (WAV1) 120: slot 0's last frame, the sine", (60.0, 0x7800, 0x7800, 0)),
                    ("slot1", "TBL1 1, WAV1 64: the overtone table, partials 9-10", (60.0, 0x4000, 0x4000, 0x100)),
                    ("note72", "note 72, POS 120: the sine an octave up", (72.0, 0x7800, 0x7800, 0))):
                if runs[key]["ok"]:
                    wav(f"m5_{key}_machine.wav", track_series(runs[key], 0), a.seconds, wavs,
                        f"track 0's buffer, {what}")
                    wav(f"m5_preview_{key}.wav", preview(tables, *pv[:1], pv[1], pv[2], pv[3], a.seconds),
                        a.seconds, wavs, f"PREVIEW, not the runner: the reference for {what}")
            if runs["silent"]["ok"]:
                wav("m5_no_trigger.wav", runs["silent"]["amp_out"], a.seconds, wavs,
                    "control: no trigger, amp output (silent)")
            wav("m5_demo_pos_sweep_preview.wav", preview(tables, 48.0, 0, 0x7800, 0, 4.0), 4.0, wavs,
                "DEMO PREVIEW, not the runner: slot 0 at note 48, POS swept 0 -> 120 over 4 s: "
                "a buzzy saw darkening to a sine")
            wav("m5_demo_harmonic_climb_preview.wav", preview(tables, 48.0, 0, 0x7800, 0x100, 4.0), 4.0, wavs,
                "DEMO PREVIEW, not the runner: slot 1 at note 48, POS swept 0 -> 120 over 4 s: "
                "the overtone series climbing, partial 1 to 16")

        if "stock" in steps:
            print("\nstep 4: types 0-4 unchanged")
            results["4_stock"] = step_stock(snap, m2mach, m5, stock_img, sound, machines,
                                            max(3, a.blocks // 2))
            show(results["4_stock"])

        frames = load_frames(a)
        if frames and "frame" in steps:
            print("\nstep 5: the caller's frame(s)")
            s5 = step_frame(init, frames, a.blocks, tables)
            results["5_frame"] = {k: v for k, v in s5.items() if k != "run"}
            show(s5)
            run = s5["run"]
            if run["ok"] and s5["numbers"]["type5_tracks"]:
                t = s5["numbers"]["type5_tracks"][0]
                wav("m5_frame_machine.wav", track_series(run, t), a.seconds, wavs,
                    f"the caller's frame: track {t}'s buffer after the type-5 loop")
                wav("m5_frame_amp_out.wav", run["amp_out"], a.seconds, wavs,
                    "the caller's frame: track 0 at the amp's output")
                i0 = run["t5_inputs"][-1][t]
                wav("m5_preview_frame.wav", preview(tables, i0["note"], i0["wav1"], i0["wav1"],
                                                    i0["tbl1"], a.seconds), a.seconds, wavs,
                    "PREVIEW, not the runner: the reference for the caller's frame's last block inputs")

    ok = bool(results) and all(r.get("ok") for r in results.values())
    report["steps"] = results
    report["wavs"] = wavs
    report["wall_s"] = round(time.perf_counter() - t_start)
    report["result"] = "PASS" if ok else "FAIL"
    (OUT / "m5_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
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
    bootstream.write_span(nolook, dsp.dm_to_load(dsp.LOOKUP_DM + 20), struct.pack("<I", 0))
    ctl = init_on(snap, m2mach, Image(dk, bytes(nolook)))
    type_ctl = m2.word(unpack(ctl, base_frame(sound, machines).to_bytes()).state, rec0 + V.TRACK_MACHINE)
    # our spans, as the runner's memory holds them after init
    spans = {}
    for what, at, payload in dsp.spans():
        dm = at - dsp.LOAD_ALIAS
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


# -- step 3 -------------------------------------------------------------------------------------------

def step_voice(init, sound, machines, blocks, tables) -> dict:
    def frames(**kw):
        def fb(b):
            return base_frame(sound, machines, trigger=(b == 1), **kw).to_bytes()
        return fb

    runs = {"init": run_blocks(init, frames(), blocks),
            "pos120": run_blocks(init, frames(overrides={WAV1: 0x7800}), blocks),
            "slot1": run_blocks(init, frames(overrides={WAV1: 0x4000, TBL1: 0x0100}), blocks),
            "note72": run_blocks(init, frames(overrides={WAV1: 0x7800}, note=0x4800), blocks),
            "silent": run_blocks(init, lambda b: base_frame(sound, machines).to_bytes(), blocks)}
    ok_runs = all(r["ok"] for r in runs.values())
    n, mism = {}, {}
    for k, r in runs.items():
        if r["ok"]:
            mism[k] = mismatches(track_series(r, 0), reference_for(r, 0, tables))
    i = runs["init"]
    settle = BLOCK * min(3, blocks // 2)
    ideal = reference_for(i, 0, tables, "ideal") if i["ok"] else []
    fit = V.fit_gain(i["amp_out"][settle:], ideal[settle:]) if i["ok"] else None
    rb = {k: (r["reader_blocks"][-1].get(0) if r["ok"] and r["reader_blocks"] else None) for k, r in runs.items()}
    inc60, inc72 = (rb["pos120"] or [0] * 6)[2], (rb["note72"] or [0] * 6)[2]
    zc60 = zero_crossings(track_series(runs["pos120"], 0)) if runs["pos120"]["ok"] else 0
    zc72 = zero_crossings(track_series(runs["note72"], 0)) if runs["note72"]["ok"] else 0
    c0 = m4.centroid(track_series(i, 0)[settle:]) if i["ok"] else 0
    c120 = m4.centroid(track_series(runs["pos120"], 0)[settle:]) if runs["pos120"]["ok"] else 0
    setup = [e for e in i["setup"]] if i["ok"] else []
    # the guard sees each track's type in order; for track 0 (type 5) the next event
    # must be the no-setup arm, never the table read
    t0_events = []
    for k, e in enumerate(setup):
        if e[0] == "guard" and e[2] == 5:
            t0_events.append(setup[k + 1][0] if k + 1 < len(setup) else None)
    n = {"float32_mismatches_machine_tap": mism,
         "loop_entries_init_run": i.get("loop_entries"),
         "reader_block_last": rb,
         "expected_reader_block_init": [dsp.TABLES_DM[0], None, live.increment(60.0), live.position(0), BLOCK],
         "machine_peak": V.peak(track_series(i, 0)) if i["ok"] else None,
         "amp_in_peak": V.peak(i["amp_in"]) if i["ok"] else None,
         "amp_out_peak": V.peak(i["amp_out"][settle:]) if i["ok"] else None,
         "amp_out_rms": V.rms(i["amp_out"][settle:]) if i["ok"] else None,
         "fit_amp_out_vs_ideal": fit.__dict__ if fit else None,
         "centroid_pos0_hz": c0, "centroid_pos120_hz": c120,
         "inc_note60": inc60, "inc_note72": inc72, "inc_ratio": inc72 / inc60 if inc60 else None,
         "zero_crossings_note60": zc60, "zero_crossings_note72": zc72,
         "silent_amp_out_peak": V.peak(runs["silent"]["amp_out"]) if runs["silent"]["ok"] else None,
         "setup_events_after_type5_guard": t0_events,
         "instructions_per_block": round(i.get("instructions", 0) / max(blocks, 1)),
         "wall_s": {k: r.get("wall_s") for k, r in runs.items()},
         "halts": {k: r.get("halt") for k, r in runs.items() if not r["ok"]}}
    checks = {
        "the five runs return every block": ok_runs,
        "the type-5 loop is entered by the image's own JUMP, once a block": i.get("loop_entries") == blocks,
        "the per-type setup for type 5 is the no-setup arm 0x1c90d4 (the table is never read)":
            bool(t0_events) and all(e == "none-arm" for e in t0_events),
        "the machine tap is bit-exact to dnfw.waverider.live in all five runs":
            ok_runs and all(v == 0 for v in mism.values()),
        "the loop's reader block matches the contract (table, inc, pos, count)":
            bool(rb["init"]) and rb["init"][0] == dsp.TABLES_DM[0] and rb["init"][2] == live.increment(60.0)
            and rb["init"][3] == 0 and rb["init"][4] == BLOCK,
        "audible at the amp's output (peak > 0.02)": bool(n["amp_out_peak"]) and n["amp_out_peak"] > 0.02,
        "correlated with the ideal reference through the chain (r > 0.9)": bool(fit) and fit.correlation > 0.9,
        "POS 120 is darker than POS 0 (spectral centroid)": 0 < c120 < c0,
        "TBL1 1 plays the other table (reader block table pointer 0x306000)":
            bool(rb["slot1"]) and rb["slot1"][0] == dsp.TABLES_DM[1],
        "note 72 is an octave above note 60 (the DSP's increment ratio is 2 within 1e-6; "
        "more zero crossings in the same blocks)":
            bool(inc60) and abs(inc72 / inc60 - 2.0) < 1e-6 and zc72 > zc60 > 0,
        "control: no trigger is silent at the amp's output (peak < 0.01)":
            n["silent_amp_out_peak"] is not None and n["silent_amp_out_peak"] < 0.01,
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
    ok_runs = a["ok"] and b["ok"] and c["ok"]
    # compared as bit patterns: the runner's FM Tone voice can produce NaN, and NaN != NaN
    all16 = ok_runs and a["buffer_bits"] == b["buffer_bits"]
    t1_15 = ok_runs and [blk[1:] for blk in c["buffer_bits"]] == [blk[1:] for blk in b["buffer_bits"]]
    active = [t for t in range(1, 16) if ok_runs and any(any(blk[t]) for blk in b["buffer_bits"])]
    nan = [t for t in range(16) if ok_runs and any(x != x for blk in b["buffers"] for x in blk[t])]
    checks = {
        "the three runs return every block": ok_runs,
        "no type-5 track: all 16 track buffers bit-identical, M5 image vs stock": all16,
        "track 0 type 5: tracks 1-15 bit-identical to the stock run": t1_15,
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
                        "halts": {k: r.get("halt") for k, r in (("a", a), ("b", b), ("c", c)) if not r["ok"]}}}


# -- step 5 -------------------------------------------------------------------------------------------

def step_frame(init, frames, blocks, tables) -> dict:
    for fr in frames:
        if len(fr) != FR.FRAME_BYTES:
            raise SystemExit(f"a frame is {len(fr)} bytes, not {FR.FRAME_BYTES}")
    run = run_blocks(init, lambda b: frames[min(b, len(frames) - 1)], blocks)
    types = sorted({t for i in run["t5_inputs"] for t in i}) if run["ok"] else []
    mism = {t: mismatches(track_series(run, t), reference_for(run, t, tables)) for t in types} if run["ok"] else {}
    checks = {"the run returns every block": run["ok"],
              "at least one track is type 5": bool(types),
              "every type-5 track is bit-exact to the reference": bool(mism) and all(v == 0 for v in mism.values())}
    return {"ok": all(checks.values()), "checks": checks, "run": run,
            "numbers": {"type5_tracks": types, "mismatches": mism,
                        "inputs_last_block": run["t5_inputs"][-1] if run["ok"] and run["t5_inputs"] else None,
                        "amp_out_peak": V.peak(run["amp_out"]) if run["ok"] else None,
                        "halt": run.get("halt")}}


if __name__ == "__main__":
    raise SystemExit(main())

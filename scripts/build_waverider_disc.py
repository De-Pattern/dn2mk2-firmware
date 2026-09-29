"""Composable hardware discriminators on M5d's DSP code.

    python scripts/build_waverider_disc.py --m5b IMAGE.syx --out OUT.syx EDIT [EDIT ...]

Each EDIT is one source transform of M5d's `machine5_live.asm` (the loop) or
`reader_m5.asm` (the reader). They are applied in order, every absolute target is
re-resolved from selas's layout (`sharc_resolve_jumps`), and the result goes into
m5b's section 3 through `dnfw.waverider.dsp.section7`. Refuses an existing OUT.

Loop edits:
  constpitch      the pitch block becomes a constant increment (note 60): no note
                  read, no float operation, no conversion
  exit-<cut>      an early `JUMP -> wr_t5v_next.` after the line CUTS[<cut>], so the
                  type-5 tail runs only up to that line and the reader is never called

Reader edits:
  reader-scratch  the reader writes its 32 floats to 0x2de800 (our own padding),
                  not the track buffer
  reader-callonly the reader's second instruction jumps straight to its return
                  sequence: the call, both pushes, the return and RFRAME run, the
                  body does not
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.image import sharc_object  # noqa: E402
from dnfw.waverider import dsp  # noqa: E402

SHARC = ROOT / "csrc" / "waverider" / "sharc"

CUTS = {
    # the tail up to and including this line runs; then the loop moves to the next track
    "magic": "      IF NE JUMP 0x16ee29;              // -> wr_t5v_next. (no directory: render nothing)\n",
    "blockaddr": "      I4 = R2;                          // this track's reader block\n",
    "framecopy": "      R5 = R5 AND R6;                   // TBL1, 0x0000 or 0x0080\n",
    "directory": "      DM(0, I4) = R2;                   // the reader block's table pointer\n",
    "pos": "      DM(3, I4) = R4;                   // pos\n",
    "noteread": "      R8 = DM(0, I1);                   // note, float semitones\n",
    "notecheck": "      R8 = R8 - R8;                     // +0.0\n",       # see below: exit at note_ok
    "trunc": "      R0 = TRUNC F8;                    // k, 0..127\n",
    "float": "      F1 = FLOAT R0 BY R12;             // has FLOAT only with BY or with a parallel move)\n",
    "table": "      R2 = DM(1, I1);                   // T[k + 1]\n",
    "inc": "      DM(2, I4) = R1;                   // inc\n",
    "precall": "      R4 = DM(0x2dde84);                // wr_render5's argument: the reader block\n",
}
# `notecheck` exits at the join label, so both arms of the validation have run
NOTE_OK = ".GLOBAL wr_t5v_note_ok.;\nwr_t5v_note_ok.:\n"
EXIT = "      JUMP 0x0;                         // -> wr_t5v_next. (DISCRIMINATOR: early exit)\n"

PITCH_START = "      // pitch: this track's note cell, 0x254b14 + 4t\n"
PITCH_END = "      DM(2, I4) = R1;                   // inc\n"
CONST_PITCH = ("      // DISCRIMINATOR: a constant increment (note 60, dnfw.waverider.live.increment)\n"
               "      R1 = 23409860;\n" + PITCH_END)

OUT_LOAD = "      R0 = DM(5, I4);\n"
OUT_SCRATCH = "      R0 = 0x2de800;                    // DISCRIMINATOR: private scratch, not the track buffer\n"
READER_ENTRY = "      I4 = R4;                          // I4 -> parameter block\n"
READER_SKIP = "      JUMP 0x0;                         // -> wr5_done. (DISCRIMINATOR: body skipped)\n"


def _once(src: str, needle: str, what: str) -> int:
    if src.count(needle) != 1:
        raise SystemExit(f"{what}: {needle.strip()!r} is not exactly once in the source")
    return src.find(needle)


def edit_loop(src: str, edit: str) -> str:
    if edit == "constpitch":
        a, b = _once(src, PITCH_START, edit), _once(src, PITCH_END, edit)
        return src[:a] + CONST_PITCH + src[b + len(PITCH_END):]
    if edit.startswith("exit-"):
        cut = edit[5:]
        if cut == "notecheck":
            _once(src, NOTE_OK, edit)
            return src.replace(NOTE_OK, NOTE_OK + EXIT)
        line = CUTS.get(cut) or SystemExit(f"no cut {cut!r}")
        if isinstance(line, SystemExit):
            raise line
        _once(src, line, edit)
        return src.replace(line, line + EXIT)
    raise SystemExit(f"unknown loop edit {edit!r}")


def edit_reader(src: str, edit: str) -> str:
    if edit == "reader-scratch":
        _once(src, OUT_LOAD, edit)
        return src.replace(OUT_LOAD, OUT_SCRATCH)
    if edit == "reader-callonly":
        _once(src, READER_ENTRY, edit)
        return src.replace(READER_ENTRY, READER_ENTRY + READER_SKIP)
    raise SystemExit(f"unknown reader edit {edit!r}")


def build_objects(edits: list[str], work: pathlib.Path) -> dict[str, bytes]:
    import sharc_resolve_jumps as rj  # noqa: PLC0415  (WSL + selas)
    loop = (SHARC / "machine5_live.asm").read_text(encoding="utf-8")
    reader = (SHARC / "reader_m5.asm").read_text(encoding="utf-8")
    for e in edits:
        if e.startswith("reader-"):
            reader = edit_reader(reader, e)
        else:
            loop = edit_loop(loop, e)
    out = dict(dsp.objects())
    for key, src, sw in (("machine5_live", loop, dsp.LOOP_SW), ("reader", reader, dsp.READER_SW)):
        _, be, _ = rj.resolve(src, sw, work)
        obj = sharc_object.load_bytes(be)
        if len(obj) > dsp.CODE_SPAN - 64:
            raise SystemExit(f"the {key} object does not fit its span with 64 bytes of padding")
        out[key] = obj
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--m5b", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--stock", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("edits", nargs="+")
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists: never overwrite a build")
    import sharc_waverider_render as m1  # noqa: PLC0415
    from dnfw.cli.main import main as dnfw  # noqa: PLC0415
    stock = m1.dn2_section7(a.stock)
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        objs = build_objects(a.edits, work)
        dsp.objects = lambda: objs                                  # this build only
        s7 = dsp.section7(stock)
        p = work / "s7.bin"
        p.write_bytes(s7)
        print(f"section 7: {len(s7)} bytes, sha256 {hashlib.sha256(s7).hexdigest()}; "
              f"loop {len(objs['machine5_live'])} B, reader {len(objs['reader'])} B; edits {a.edits}")
        return dnfw(["build", "-o", str(a.out), "-s", f"7={p}", str(a.m5b)]) or 0


if __name__ == "__main__":
    raise SystemExit(main())

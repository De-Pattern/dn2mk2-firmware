"""Hardware discriminators on M5c's reader: D3 (scratch output) and D4 (sanitised output).

    python scripts/build_waverider_disc_scratch.py --m5b IMAGE.syx --out OUT.syx [--variant scratch|sanitise]

**D4, `--variant sanitise`**: the reader's value is sanitised before it is stored to
the track buffer. A NaN or Inf (exponent field 0xff) becomes 0; the value is
clamped to [-1, +1] and scaled by 0.5. If the silence is poisoning of the shared
chain by NaN/Inf/huge values, D4 plays a quiet saw.

**`--variant constpitch`** (on M5d's loop): the pitch block -- the note-cell read,
the integer validation, MIN, TRUNC, FLOAT and the table interpolation -- becomes a
constant increment (note 60). If M5d still dies and this plays, the pitch path is it.

**`--variant exit-<cut>`** (on M5d's loop): an early `JUMP` to `wr_t5v_next` after
one of `EXITS` -- `magic` (the directory magic matches, then nothing: nodir's work,
in block 1), `blockaddr`, `framecopy`, `directory`, `pos` -- a prefix bisection of
the tail that runs only on a trig.

**D3, `--variant scratch` (the default)**:

m5c silenced the instrument on a WAVERIDER trig (2026-09-27), and D2 (the reader never
called) did not. This build keeps everything m5c does -- the loop, the CJUMP, the
reader's code and all its reads -- and changes one thing: the reader writes its 32
floats to `SCRATCH_DM` in our own block-1 region (the directory's zero padding)
instead of the track buffer whose pointer the loop passes. WAVERIDER stays silent.

- plays through a trig  -> the fault is the track-buffer write;
- still dies            -> the reader call or its reads.

The reader source is derived from `csrc/waverider/sharc/reader_m5.asm` at build time
(one line: the `out` load becomes `R0 = SCRATCH_DM`), assembled with selas (WSL), its
two absolute jumps re-resolved for the new lengths. Refuses an existing OUT.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.image import sharc_object  # noqa: E402
from dnfw.waverider import dsp  # noqa: E402

SCRATCH_DM = 0x2DE800                         # 2 KB of the directory's padding, zeros at boot
OUT_LOAD = "      R0 = DM(5, I4);\n"
OUT_SCRATCH = f"      R0 = {SCRATCH_DM:#x};                 // DISCRIMINATOR: private scratch, not the track buffer\n"
STORE = "      DM(I2, M6) = F4;\n"
SANITISE = """      // DISCRIMINATOR D4: NaN/Inf -> 0, clamp to [-1, 1], scale by 0.5
      R0 = LSHIFT R4 BY -23;
      R1 = 0xff;
      R0 = R0 AND R1;                   // the exponent field
      COMP(R0, R1);
      IF EQ R4 = R4 - R4;               // NaN or Inf -> +0 (a fixed-point subtract of the bits)
      R0 = 0x3f800000;                  // 1.0
      F4 = MIN(F4, F0);
      R0 = 0xbf800000;                  // -1.0
      F4 = MAX(F4, F0);
      R0 = 0x3f000000;                  // 0.5
      F4 = F4 * F0;
      DM(I2, M6) = F4;
"""


def labels(text: str) -> dict[str, int]:
    out, k, pend = {}, 0, []
    for line in text.splitlines():
        t = line.split("//", 1)[0].strip()
        if not t or t.startswith("."):
            continue
        if t.endswith(":"):
            pend.append(t[:-1].rstrip("."))
            continue
        for p in pend:
            out[p] = k
        pend = []
        k += 1
    return out


def scratch_reader(work: pathlib.Path, variant: str = "scratch") -> bytes:
    import sharc_waverider_m3 as m3  # noqa: PLC0415  (WSL + selas)
    src = (ROOT / "csrc/waverider/sharc/reader_m5.asm").read_text(encoding="utf-8")
    old, new = (OUT_LOAD, OUT_SCRATCH) if variant == "scratch" else (STORE, SANITISE)
    if src.count(old) != 1:
        raise SystemExit(f"reader_m5.asm's {old.strip()!r} is not where this expects it")
    src = src.replace(old, new)
    jumps = re.findall(r"IF (?:EQ|NE) JUMP (0x[0-9a-f]+);", src)
    if len(jumps) != 2:
        raise SystemExit(f"expected the reader's two absolute jumps, found {jumps}")
    lab = labels(src)
    for _ in range(3):                         # re-resolve until the lengths are stable
        (work / "rs.asm").write_text(src, encoding="utf-8", newline="\n")
        be, offs = m3._selas(work / "rs.asm", work)
        want = {"wr5_done": dsp.READER_SW + offs[lab["wr5_done"]] // 2,
                "wr5_loop": dsp.READER_SW + offs[lab["wr5_loop"]] // 2}
        new = re.sub(r"IF EQ JUMP 0x[0-9a-f]+;", f"IF EQ JUMP {want['wr5_done']:#x};", src)
        new = re.sub(r"IF NE JUMP 0x[0-9a-f]+;", f"IF NE JUMP {want['wr5_loop']:#x};", new)
        if new == src:
            return sharc_object.load_bytes(be)
        src = new
    raise SystemExit("the reader's jump targets did not settle")


PITCH_START = "      // pitch: this track's note cell, 0x254b14 + 4t\n"
PITCH_END = "      DM(2, I4) = R1;                   // inc\n"
CONST_PITCH = """      // DISCRIMINATOR: a constant increment (note 60, dnfw.waverider.live.increment),
      // no note read, no float operation, no conversion
      R1 = 23409860;
      DM(2, I4) = R1;                   // inc
"""


def constpitch_loop(work: pathlib.Path) -> bytes:
    """machine5_live.asm with the pitch block replaced by a constant increment."""
    import sharc_resolve_jumps as rj  # noqa: PLC0415
    src = (ROOT / "csrc/waverider/sharc/machine5_live.asm").read_text(encoding="utf-8")
    a, b = src.find(PITCH_START), src.find(PITCH_END)
    if a < 0 or b < a:
        raise SystemExit("machine5_live.asm's pitch block is not where this expects it")
    src = src[:a] + CONST_PITCH + src[b + len(PITCH_END):]
    _, be, _ = rj.resolve(src, dsp.LOOP_SW, work)
    return sharc_object.load_bytes(be)


# Early-exit cut points in M5d's loop tail (machine5_live.asm). Each `exit-<name>`
# variant inserts `JUMP -> wr_t5v_next.` right after the named line, so the build runs
# the tail only up to it: a prefix bisection of the trig-only code.
EXITS = {
    "magic": "      IF NE JUMP 0x16ee29;              // -> wr_t5v_next. (no directory: render nothing)\n",
    "blockaddr": "      I4 = R2;                          // this track's reader block\n",
    "framecopy": "      R5 = R5 AND R6;                   // TBL1, 0x0000 or 0x0080\n",
    "directory": "      DM(0, I4) = R2;                   // the reader block's table pointer\n",
    "pos": "      DM(3, I4) = R4;                   // pos\n",
}
EXIT_JUMP = "      JUMP 0x0;                         // -> wr_t5v_next. (DISCRIMINATOR: early exit)\n"


def exit_loop(work: pathlib.Path, name: str) -> bytes:
    """machine5_live.asm with an early exit to wr_t5v_next after EXITS[name]."""
    import sharc_resolve_jumps as rj  # noqa: PLC0415
    src = (ROOT / "csrc/waverider/sharc/machine5_live.asm").read_text(encoding="utf-8")
    at = EXITS[name]
    if src.count(at) != 1:
        raise SystemExit(f"machine5_live.asm's cut point {at.strip()!r} is not unique")
    src = src.replace(at, at + EXIT_JUMP)
    _, be, _ = rj.resolve(src, dsp.LOOP_SW, work)
    return sharc_object.load_bytes(be)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--m5b", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--variant", choices=("scratch", "sanitise", "constpitch", *(f"exit-{k}" for k in EXITS)), default="scratch")
    ap.add_argument("--stock", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists: never overwrite a build")
    import sharc_waverider_render as m1  # noqa: PLC0415
    from dnfw.cli.main import main as dnfw  # noqa: PLC0415
    stock = m1.dn2_section7(a.stock)
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        base = dsp.objects()
        if a.variant == "constpitch":
            key, obj = "machine5_live", constpitch_loop(work)
        elif a.variant.startswith("exit-"):
            key, obj = "machine5_live", exit_loop(work, a.variant[5:])
        else:
            key, obj = "reader", scratch_reader(work, a.variant)
        if len(obj) > dsp.CODE_SPAN - 64:
            raise SystemExit(f"the {key} object does not fit its span with 64 bytes of padding")
        dsp.objects = lambda: {**base, key: obj}                  # this build only
        s7 = dsp.section7(stock)
        p = work / "s7.bin"
        p.write_bytes(s7)
        print(f"section 7: {len(s7)} bytes, sha256 {hashlib.sha256(s7).hexdigest()}; {key} {len(obj)} B, "
              f"variant {a.variant}")
        return dnfw(["build", "-o", str(a.out), "-s", f"7={p}", str(a.m5b)]) or 0


if __name__ == "__main__":
    raise SystemExit(main())

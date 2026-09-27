"""Hardware discriminator: M5c with the reader's output sent to a private scratch buffer.

    python scripts/build_waverider_disc_scratch.py --m5b IMAGE.syx --out OUT.syx

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


def scratch_reader(work: pathlib.Path) -> bytes:
    import sharc_waverider_m3 as m3  # noqa: PLC0415  (WSL + selas)
    src = (ROOT / "csrc/waverider/sharc/reader_m5.asm").read_text(encoding="utf-8")
    if src.count(OUT_LOAD) != 1:
        raise SystemExit("reader_m5.asm's out load is not where this expects it")
    src = src.replace(OUT_LOAD, OUT_SCRATCH)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--m5b", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
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
        reader = scratch_reader(work)
        base = dsp.objects()
        if len(reader) > dsp.CODE_SPAN - 64:
            raise SystemExit("the scratch reader does not fit its span with 64 bytes of padding")
        dsp.objects = lambda: {**base, "reader": reader}          # this build only
        s7 = dsp.section7(stock)
        p = work / "s7.bin"
        p.write_bytes(s7)
        print(f"section 7: {len(s7)} bytes, sha256 {hashlib.sha256(s7).hexdigest()}; reader {len(reader)} B, "
              f"output -> {SCRATCH_DM:#x}")
        return dnfw(["build", "-o", str(a.out), "-s", f"7={p}", str(a.m5b)]) or 0


if __name__ == "__main__":
    raise SystemExit(main())

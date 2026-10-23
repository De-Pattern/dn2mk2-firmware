"""Write `csrc/waverider/sharc/comb.asm`: COMB- and COMB+ (filter types 9, 10; docs/comb.md).

    python scripts/gen_comb_asm.py [--no-resolve]

The program is `dnfw.comb.program.program`: the same calls that, run in Python, are its
model. Entered from PING's track loop; back to PING's `wr_p_next`, read from ping.asm's
committed object (refused when stale).
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.comb import program as P     # noqa: E402
from dnfw.waverider import dsp         # noqa: E402

OUT = ROOT / "csrc" / "waverider" / "sharc" / "comb.asm"


def build() -> str:
    import gen_gran_asm as G           # noqa: PLC0415
    return P.program(P.layout(), G.ping_next())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-resolve", action="store_true")
    a = ap.parse_args(argv)
    text = build()
    if not a.no_resolve:
        import sharc_resolve_jumps as R  # noqa: PLC0415  (selas)
        with tempfile.TemporaryDirectory() as tmp:
            text, be, offs = R.resolve(text, dsp.COMB_SW, pathlib.Path(tmp))
        print(f"resolved at sw {dsp.COMB_SW:#x}: {len(offs)} instructions, {len(be)} bytes")
    OUT.write_text(text, encoding="utf-8", newline="\n")
    n = sum(1 for ln in text.splitlines() if ln.startswith("      ") and not ln.strip().startswith("//"))
    print(f"wrote {OUT.relative_to(ROOT)}: {n} instructions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

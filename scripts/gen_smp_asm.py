"""Write the sample machines' SHARC source, csrc/waverider/sharc/smp.asm (docs/sampler.md).

    python scripts/gen_smp_asm.py [--no-resolve]

The program is `dnfw.sampler.program.program`: the same calls that, run in Python, are the
model the SHARC runner holds the assembled code to (scripts/sharc_waverider_m5.py, step
smp). This writes its assembly text, then fills in every branch target with selas's own
layout at its L2 load address (scripts/sharc_resolve_jumps.py), unless --no-resolve.
Assemble it with `scripts/gen_waverider_sharc.py --assemble`.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.sampler import live as SL       # noqa: E402
from dnfw.sampler import program as P     # noqa: E402
from dnfw.waverider import dsp            # noqa: E402

OUT = ROOT / "csrc" / "waverider" / "sharc" / "smp.asm"


def build() -> str:
    return P.program(SL.layout(), dsp.RINGS_SW)    # entered from PERC's tail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-resolve", action="store_true")
    a = ap.parse_args(argv)
    text = build()
    if not a.no_resolve:
        import sharc_resolve_jumps as R  # noqa: PLC0415  (selas)
        with tempfile.TemporaryDirectory() as tmp:
            text, be, offs = R.resolve(text, dsp.SMP_SW, pathlib.Path(tmp))
        print(f"resolved at sw {dsp.SMP_SW:#x}: {len(offs)} instructions, {len(be)} bytes")
    OUT.write_text(text, encoding="utf-8", newline="\n")
    n = sum(1 for ln in text.splitlines() if ln.startswith("      ") and not ln.strip().startswith("//"))
    print(f"wrote {OUT.relative_to(ROOT)}: {n} instructions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

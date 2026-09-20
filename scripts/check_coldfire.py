"""Refuse any build that contains an instruction the ColdFire cannot run.

    python scripts/check_coldfire.py out/lfo4-bridge/code.bin [--base 0x46800000]

`lfo4-bridge` faulted on the instrument at boot with **`V03 M0 P468004FC`** --
an address error at an instruction GCC had written for us:

    468004fc:  2381 0e00   movel %d1,%a1@(0,%d0:l:8)

A **scale factor of 8**, which the ColdFire V4e does not implement. Nothing in
the toolchain objects: GCC emits it under `-mcpu=5475`, gas assembles it, and
Unicorn's generic m68k core executes it, so every test this project has passes
and the instrument alone says no. Elektron's own compiler never emits one --
stock 1.11 uses scale 2 in 524 places and scale 4 in 1,368, and scale 8
nowhere at all.

The array is fixed (`csrc/lfo4/carry.c`), but a fix to one array is not what
this needs. Any 8-byte-strided structure indexed by a variable can bring it
back, silently, in a build that passes everything. So this is a gate over the
*encoding*: every scaled-index extension word with `scale == 3` is a build
failure, wherever it came from.

It scans the disassembly rather than the bytes, so it sees exactly what the
CPU would decode and not a pattern that happens to appear inside data.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.patch.cbuild import SCALE8, find_toolchain            # noqa: E402


def offenders(image: pathlib.Path, base: int, tool):
    """-> the disassembled lines using a scale the ColdFire has no encoding for.

    The toolchain comes from `dnfw.patch.cbuild`, which already knows how to
    reach an m68k objdump through WSL on this machine. A first version looked
    only on `PATH`, found nothing, and reported "cannot check" for every build
    -- which is the honest answer to the wrong question.
    """
    r = tool.run(tool.objdump, ["-D", "-b", "binary", "-m", "m68k:cfv4e",
                                f"--adjust-vma={base:#x}", tool.path_for(image)])
    if r.returncode:
        raise SystemExit(f"  objdump failed: {r.stderr.strip()[:200]}")
    return [line.rstrip() for line in r.stdout.splitlines() if SCALE8.search(line)]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image", type=pathlib.Path, help="a linked, raw binary")
    p.add_argument("--base", type=lambda x: int(x, 0), default=0x46800000)
    args = p.parse_args()

    tool = find_toolchain()
    if tool is None or not tool.objdump:
        print("  no m68k objdump reachable -- cannot check, and an unchecked "
              "build is not a passing one.", file=sys.stderr)
        return 2

    bad = offenders(args.image.resolve(), args.base, tool)
    if not bad:
        print(f"  {args.image.name}: no scale-8 addressing. Safe on this point.")
        return 0
    print(f"  {len(bad)} instruction(s) the ColdFire V4e cannot execute:\n")
    for line in bad:
        print(f"    {line}")
    print("\n  A scale factor of 8 is a 68020 addressing mode. GCC emits it for any\n"
          "  8-byte-strided array indexed by a variable; split it into parallel\n"
          "  arrays, or index through an explicit pointer. This faults on the\n"
          "  instrument and nowhere else -- see csrc/lfo4/carry.c.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

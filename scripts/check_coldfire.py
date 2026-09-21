"""Refuse any build that contains an instruction the ColdFire cannot run.

    python scripts/check_coldfire.py out/lfo4-bridge/code.bin
    python scripts/check_coldfire.py out/lfo4-page/section_3_MAIN_OS.bin \
        --base 0x40000400 --against out/stock/section_3_MAIN_OS.bin

`lfo4-bridge` faulted on the instrument at boot with **`V03 M0 P468004FC`** --
an address error at an instruction GCC had written for us:

    468004fc:  2381 0e00   movel %d1,%a1@(0,%d0:l:8)

A **scale factor of 8**, which the ColdFire V4e does not implement. Nothing in
the toolchain objects: GCC emits it under `-mcpu=5475`, gas assembles it, and
Unicorn's generic m68k core executes it, so every test this project has passes
and the instrument alone says no.

The array is fixed (`csrc/lfo4/carry.c`), but a fix to one array is not what
this needs. Any 8-byte-strided structure indexed by a variable can bring it
back, silently, in a build that passes everything. So this is a gate over the
*encoding*: every scaled-index extension word with `scale == 3` is a build
failure, wherever it came from.

It scans the disassembly rather than the bytes, so it sees exactly what the
CPU would decode and not a pattern that happens to appear inside data --

**except that a whole MAIN OS section is mostly not code.** Disassembling all
3 MB of stock 1.11 linearly finds **1,539** of these, every one inside strings
and tables: `7570 4669` is `"up Fi"`. So a section is only meaningful against a
baseline, and `--against` supplies one: with the two images aligned, which they
are for every mod this project builds, anything the baseline does not already
have is ours. Without it a section is scanned bare and the count is noise.

The build-time guard in `dnfw.patch.cbuild` needs none of this: it disassembles
the linked ELF, which is code and only code.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.patch.cbuild import SCALE8, find_toolchain            # noqa: E402

AT = re.compile(r"^\s*([0-9a-f]+):")


def offenders(image: pathlib.Path, base: int, tool):
    """-> {address: the disassembled line} using a scale the ColdFire has not.

    The toolchain comes from `dnfw.patch.cbuild`, which already knows how to
    reach an m68k objdump through WSL on this machine. A first version looked
    only on `PATH`, found nothing, and reported "cannot check" for every build
    -- which is the honest answer to the wrong question.
    """
    r = tool.run(tool.objdump, ["-D", "-b", "binary", "-m", "m68k:cfv4e",
                                f"--adjust-vma={base:#x}", tool.path_for(image)])
    if r.returncode:
        raise SystemExit(f"  objdump failed: {r.stderr.strip()[:200]}")
    found = {}
    for line in r.stdout.splitlines():
        if not SCALE8.search(line):
            continue
        m = AT.match(line)
        if m:
            found[int(m.group(1), 16)] = line.rstrip()
    return found


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image", type=pathlib.Path, help="a linked, raw binary")
    p.add_argument("--base", type=lambda x: int(x, 0), default=0x46800000)
    p.add_argument("--against", type=pathlib.Path,
                   help="a baseline at the same base: report only what it does not have")
    args = p.parse_args()

    tool = find_toolchain()
    if tool is None or not tool.objdump:
        print("  no m68k objdump reachable -- cannot check, and an unchecked "
              "build is not a passing one.", file=sys.stderr)
        return 2

    bad = offenders(args.image.resolve(), args.base, tool)
    if args.against:
        base = offenders(args.against.resolve(), args.base, tool)
        shared = len(set(bad) & set(base))
        bad = {a: line for a, line in bad.items() if a not in base}
        print(f"  {shared} shared with {args.against.name} -- those are its data, "
              f"not this build's code.")
    if not bad:
        print(f"  {args.image.name}: no scale-8 addressing. Safe on this point.")
        return 0
    print(f"  {len(bad)} instruction(s) the ColdFire V4e cannot execute:\n")
    for address in sorted(bad):
        print(f"    {bad[address]}")
    print("\n  A scale factor of 8 is a 68020 addressing mode. GCC emits it for any\n"
          "  8-byte-strided array indexed by a variable; split it into parallel\n"
          "  arrays, or index through an explicit pointer. This faults on the\n"
          "  instrument and nowhere else -- see csrc/lfo4/carry.c.\n"
          "  If an address is past the end of stock MAIN OS it is in the appended\n"
          "  area, which is data the loader copies and nothing executes.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

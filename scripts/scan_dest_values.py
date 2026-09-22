"""Which sites turn a parameter entry into a stored `DEST` value?

    python scripts/scan_dest_values.py [--window 64]

`docs/fx-master-modulation.md` §10 asked this and answered **two**, by looking
for `jsr 0x400dbcc4` with an **adjacent** `lsl.l #8`. `fxbrowser` was built on
that count and half-worked on the instrument, because the real answer is
**six**: four of the sites put a call to `0x401880cc` between the conversion and
the shift, and an adjacent-pair scan walks straight past them.

So this is the scan in the form that cannot miss one for being spelled
differently, and the rule it encodes is the one to reason with:

> **A site that shifts `0x400dbcc4`'s result left by 8 is producing a `DEST`
> *value*, and a value must carry the route A code (`slot + 76` for an FX
> record). A site that does not shift is using `record+12` as an **index** —
> into a page, a table, a slot space — and must keep the raw number.**

That is decidable by reading, which is the point. `docs/PRINCIPLES.md` §19 is
about negatives produced by instruments that could not have found the thing;
this is the positive-side twin — a count produced by a scan whose window was
too narrow, reported as if it were the number of sites rather than the number
of sites *of one spelling*.

The window is a parameter because the right value is not obvious and a reader
should be able to widen it and see the count stop changing.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.firmware.load import load

BASE = 0x40000400
CONVERT = 0x400DBCC4                     # entry -> record+12, the ParameterSet slot
CALL = bytes.fromhex("4eb9400dbcc4")     # jsr 0x400dbcc4
STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")

# lsl.l #8,%dN is 0xe188 | N
SHIFTS = {0xE188 | reg: reg for reg in range(8)}


def sites(content: bytes) -> list[int]:
    out, offset = [], 0
    while True:
        i = content.find(CALL, offset)
        if i < 0:
            return out
        out.append(BASE + i)
        offset = i + 2


def shifted(content: bytes, site: int, window: int):
    """-> (address, register, distance) of the first `lsl.l #8` within `window`."""
    start = site - BASE + len(CALL)
    for step in range(0, window, 2):
        if start + step + 2 > len(content):
            return None
        word = struct.unpack_from(">H", content, start + step)[0]
        if word in SHIFTS:
            return BASE + start + step, SHIFTS[word], step + len(CALL)
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--window", type=int, default=64,
                   help="bytes to look forward for the shift (default 64)")
    p.add_argument("--image", type=pathlib.Path, default=STOCK)
    args = p.parse_args()

    content = load(read_image(args.image)).container.find(3).unpack()
    found = sites(content)
    print(f"  {len(found)} `jsr {CONVERT:#010x}` site(s) in MAIN OS")
    print(f"  looking {args.window} bytes forward for `lsl.l #8,%dN`\n")

    value_sites = []
    for site in found:
        hit = shifted(content, site, args.window)
        if hit:
            at, reg, distance = hit
            value_sites.append(site)
            print(f"    {site:#010x}  -> lsl.l #8,%d{reg} at {at:#010x}  "
                  f"({distance} bytes later)")
    print(f"\n  {len(value_sites)} of {len(found)} produce `slot << 8` -- a DEST value.")
    print(f"  the other {len(found) - len(value_sites)} use record+12 as an index and "
          f"must keep the raw number.")

    # The window is a judgement call, so show where the count settles.
    print("\n  the count against the window, so the choice is visible:")
    for window in (8, 12, 16, 24, 32, 48, 64, 96, 128):
        n = sum(1 for s in found if shifted(content, s, window))
        note = "   <- what section 10 used; it is why fxbrowser half-worked" if window == 12 else ""
        print(f"    {window:4} bytes: {n}{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

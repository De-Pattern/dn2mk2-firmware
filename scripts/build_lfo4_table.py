"""LFO4 step 4b, part 1: the parameter table moves and grows, and nothing changes.

    python scripts/build_lfo4_table.py

A fourth `MOD` page needs ten parameter records, and the table they belong in
is 320 records of 60 bytes **inside the firmware image**, with another array
starting at the byte after it. It cannot grow where it is. So this build copies
it into the appended area with LFO4's ten records after it, moves its 321-entry
runtime companion into our own BSS, and rewrites the 117 literals that reach
either one: 56 pre-biased bases, 6 runtime bases and 55 bounds.

**This build is meant to be invisible.** No page names the new records and no
mask admits them, so every screen, every knob and every saved sound must behave
exactly as `lfo4-slots` does. That is the point of shipping it on its own: the
relocation is the large mechanical change, the page on top of it is small, and
a fault in either would otherwise be indistinguishable from a fault in the
other.

What a mistake here looks like is worth knowing before flashing it. The copy is
byte-identical for all 320 stock records, so a base site this build failed to
find keeps reading the old table and keeps being right; a bound it failed to
find clamps an entry the firmware never asks for. Neither can make a stock
parameter wrong. The failure that *can* happen is the opposite one -- rewriting
a literal that was not this table -- and every site is asserted to hold its
stock value before it is touched.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import build_lfo4_bridge as bridge                         # noqa: E402
import build_lfo4_slots as slots                           # noqa: E402
from dnfw.patch import area, lfo4records, paramtable       # noqa: E402

BASE = 0x40000400
TABLE_VA = 0x46900000             # clear of the C at 0x46800000 (docs/memory-map.md)
ADDED = lfo4records.GROUP_SIZE
OUT = ROOT / "out/lfo4-table"
SYX = ROOT / "00_Resources/02_Builds/lfo4-table_DN2_1.11.syx"

SOURCES = bridge.SOURCES
ENTRIES = slots.ENTRIES

# The table's own chunk carries one string after the records: the page label
# the ten new ones point at. It is four characters and the image has no `LFO4`
# in it, so it has to come from somewhere -- and the chunk it is used from is
# the honest place for it.
PAGE_NAME = b"LFO4\x00"


def _records(stock: bytes) -> bytes:
    """The relocated table: 320 stock records, LFO4's ten, then the label."""
    name_va = TABLE_VA + paramtable.RECORD * (paramtable.COUNT + ADDED)
    blob = paramtable.records(stock, BASE)
    blob += lfo4records.build(stock, BASE, page_name_va=name_va)
    return blob + PAGE_NAME


def chunks(stock: bytes):
    blob = _records(stock)
    return [(area.CODE, area.CodeChunk(TABLE_VA, blob).pack())]


def relocate(content, code):
    """Repoint the table and widen the entry space, then say what it did."""
    del code
    sites = paramtable.relocate(content, BASE, table_va=TABLE_VA, added=ADDED)
    kinds = {}
    for site in sites:
        kinds[site.what.split(",")[0]] = kinds.get(site.what.split(",")[0], 0) + 1
    print("part 5 -- the parameter table")
    print(f"  60-byte records {paramtable.TABLE:#010x} -> {TABLE_VA:#010x}, "
          f"{paramtable.COUNT} + {ADDED} records")
    print(f"  entry space {paramtable.COUNT + 1} -> {paramtable.COUNT + ADDED + 1}, "
          "except at the two sites it must not be")
    for kind, n in sorted(kinds.items()):
        print(f"    {n:>3}  {kind}")
    for va, why in sorted(paramtable.NOT_THIS_TIME.items()):
        print(f"    {va:#010x} left at {paramtable.COUNT + 1}: {why}")


def describe(stock: bytes) -> None:
    name_va = TABLE_VA + paramtable.RECORD * (paramtable.COUNT + ADDED)
    print(f"  LFO4's ten records, at entries {paramtable.COUNT + 1}.."
          f"{paramtable.COUNT + ADDED}, label {name_va:#010x} {PAGE_NAME[:4].decode()!r}")
    for line in lfo4records.describe(lfo4records.build(stock, BASE, page_name_va=name_va)):
        print(line)


if __name__ == "__main__":
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    describe(load(read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, relocate], chunks=chunks))

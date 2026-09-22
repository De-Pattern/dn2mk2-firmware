"""LFO4: the fourth page is in the list from the first frame, not the second.

    python scripts/build_lfo4_pagelist.py

From the instrument, 2026-09-22:

> "when the device opens, only 3 dots are shown to the right of the mod page
> (as my project opens in the mod page). The Fourth do appears as soon as I
> press MOD once."

`page.c` swaps the mode's page vector the first time a **mode header is
drawn**, and a project that opens on the MOD page draws its dots before that
happens. The boot gate had already said as much without anyone reading it that
way: after 450 M instructions from reset to a drawn frame, `lfo4_pages` was in
the NOT EXERCISED list.

So the fourth id is added where the vector is **born** instead:

```
40061558  moveq #3,%d1              <- the count
4006155c  movel %d1,%sp@-
40061562  movel #0x401e0048,%d0     <- the list of page ids
40061568  movel %d0,%sp@-
4006156c  jsr %a5@                  <- vector<int>(vector, list, count)
```

The list is `{4, 5, 6}` and `0x401e0054` is `16`, the next registration's, in a
packed pool with no gaps -- so it is rehoused rather than extended, which is
what `docs/lfo4-build-plan.md` predicted when this route was first read and set
aside. Two literals: the count, and the pointer.

**It is the safer of the two mechanisms as well as the earlier one.** The
constructor copies the list into the vector's own storage, so afterwards
nothing points at memory the firmware's allocator never handed out -- the one
thing `page.c` admits it cannot prove about its swap. The swap stays in the
build and simply declines, because the vector it inspects already holds four.
"""

from __future__ import annotations

import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import build_lfo4_bridge as bridge                         # noqa: E402
import build_lfo4_page as page                             # noqa: E402
import build_lfo4_slots as slots                           # noqa: E402
import build_lfo4_table as table                           # noqa: E402
import build_lfo4_ui as ui                                 # noqa: E402
import build_lfo4_value as value                           # noqa: E402

BASE = 0x40000400
OUT = ROOT / "out/lfo4-pagelist"
SYX = ROOT / "00_Resources/02_Builds/lfo4-pagelist_DN2_1.11.syx"

SOURCES = ui.SOURCES + ("pagelist.c",)
ENTRIES = ui.ENTRIES + ["lfo4_mod_pages"]

COUNT_AT = 0x40061558            # moveq #3,%d1
COUNT_STOCK = bytes.fromhex("7203")
LIST_AT = 0x40061562             # movel #0x401e0048,%d0
LIST_STOCK = bytes.fromhex("203c401e0048")
STOCK_LIST = 0x401E0048
NEIGHBOUR = 0x401E0054           # the next registration's id, proving no gap


def pagelist(content, code):
    """Build the mode's page vector with four ids instead of three."""
    print("part 12 -- the page list, at startup")

    # The pool has no gap: assert it, because the whole reason for rehousing
    # the list is that the longword after it belongs to somebody else.
    ids = struct.unpack_from(">4I", content, STOCK_LIST - BASE)
    if ids != (4, 5, 6, 16):
        raise SystemExit(f"the page list at {STOCK_LIST:#010x} is {ids}, not (4, 5, 6) "
                         f"followed by another registration")

    at = ui._at(content, COUNT_AT, COUNT_STOCK, "the page count")
    content[at + 1] = 4
    print(f"  {COUNT_AT:#010x}  moveq #3 -> #4")

    at = ui._at(content, LIST_AT, LIST_STOCK, "the page list")
    content[at + 2:at + 6] = struct.pack(">I", code["lfo4_mod_pages"])
    mine = struct.unpack_from(">4I", code.image,
                              code["lfo4_mod_pages"] - bridge.CODE_VA)
    if mine[:3] != ids[:3]:
        raise SystemExit(f"our list starts {mine[:3]}, the firmware's is {ids[:3]}")
    print(f"  {LIST_AT:#010x}  {STOCK_LIST:#010x} -> {code['lfo4_mod_pages']:#010x}, {mine}")


if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        ui.slew, ui.dest, pagelist],
                                 chunks=table.chunks))

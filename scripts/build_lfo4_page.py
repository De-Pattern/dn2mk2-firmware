"""LFO4 step 4b, part 2: the fourth MOD page.

    python scripts/build_lfo4_page.py

`build_lfo4_table.py` put ten parameter records where the firmware can reach
them and changed nothing anybody can see. This is the half that shows: a page
record for an id the firmware's table has no room for, and a fourth entry in
the MOD mode's page vector, so `[MOD]` cycles `LFO1 LFO2 LFO3 LFO4` and the
header reads `MOD (4/4)`.

Both structures are built by the UI at startup and neither can be written at
build time, so this adds two stubs instead:

| site | what it does |
|---|---|
| `0x400c2474` | `id -> record`: answers for LFO4's id, which its table cannot |
| `0x40063f5c` | the mode-header renderer: gives the MOD mode a fourth page, once |

The record is assembled from LFO3's the first time a MOD header is drawn --
its fields are pointers to string objects the UI made, so copying is the only
way to get one that is right, and the only edit is `LFO3` -> `LFO4` and the
eight parameter entries.

**The destination list needs no change.** The per-page filter is a mask
against each record's capability field, and the staircase `0x1e00 / 0x0e00 /
0x0600` already continues to `0x0200` on LFO3's eight records -- a bit the
shipping firmware never asks for. LFO4's own records carry no bits at all, so
no existing page can target them and the modulation graph stays acyclic
without anything here enforcing it.
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
import build_lfo4_slots as slots                           # noqa: E402
import build_lfo4_table as table                           # noqa: E402

BASE = 0x40000400
OUT = ROOT / "out/lfo4-page"
SYX = ROOT / "00_Resources/02_Builds/lfo4-page_DN2_1.11.syx"

SOURCES = table.SOURCES + ("page.c", "pagehooks.S")
ENTRIES = table.ENTRIES + ["lfo4_pages", "lfo4_page_for",
                           "lfo4_page_stub", "lfo4_mode_stub"]

# (name, the site, the stub, the symbol holding the bytes it replays, width).
# The same shape as `build_lfo4_ext.SITES`, and checked the same way: a stub
# that does not replay exactly what its jump displaces is refused.
SITES = (("page record", 0x400C2474, "lfo4_page_stub", "lfo4_page_displaced", 6),
         ("mode header", 0x40063F5C, "lfo4_mode_stub", "lfo4_mode_displaced", 6))


def hooks(content, code):
    print("part 6 -- the fourth page")
    for name, va, stub, replay, n in SITES:
        at = va - BASE
        mine = code.image[code[replay] - bridge.CODE_VA:code[replay] - bridge.CODE_VA + n]
        if bytes(content[at:at + n]) != mine:
            raise SystemExit(f"{name}: the stub replays {mine.hex()}, the site holds "
                             f"{bytes(content[at:at + n]).hex()}")
        content[at:at + n] = b"\x4e\xf9" + struct.pack(">I", code[stub])
        print(f"  {va:#010x}  {name} -> {stub} {code[stub]:#010x}")


if __name__ == "__main__":
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, hooks],
                                 chunks=table.chunks))

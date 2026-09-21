"""LFO4 step 4c: the page shows the value the knob set.

    python scripts/build_lfo4_value.py

`lfo4-page` draws a fourth MOD page with LFO4's names, and the numbers beside
them are wrong -- a parameter's displayed value comes from the sound at
`+0x14 + slot*2`, and slot 101 is `+0xDE`, the machine-type byte. The knob turn
lands in LFO4's table (step 4a); the screen reads somewhere else entirely.

This is the other half of that divert, and it is the same six bytes in mirror:

| step | site | stock | above 100 |
|---|---|---|---|
| 4a, write | `0x40037bd0` | `moveq #100,%d0 ; cmp.l %d2,%d0 ; blt` | writes nothing |
| 4c, read | `0x4003717c` | `moveq #100,%d0 ; cmp.l %d2,%d0 ; blt` | returns zero |

**The site was found by running, not by reading.** 119 instructions in the
image address the sound value array's shape -- displacement 20, long index,
scale 2. `scripts/emu_value_reads.py` hooks all of them and opens the MOD
pages: **two** fire, and one of those clamps its index to 0..15 before it gets
there. No amount of staring at the image would have picked those two out of a
hundred and nineteen.
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

BASE = 0x40000400
OUT = ROOT / "out/lfo4-value"
SYX = ROOT / "00_Resources/02_Builds/lfo4-value_DN2_1.11.syx"

SOURCES = page.SOURCES + ("getter.c", "widget.c", "valuehooks.S")
ENTRIES = page.ENTRIES + ["lfo4_on_get", "lfo4_get_stub",
                          "lfo4_companion", "lfo4_comp_stub"]

# Stock 1.11, checked rather than trusted. Like step 4a's, this replaces
# instructions it does not replay, so a changed image must not be patched.
BOUND = 0x4003717C
STOCK = bytes.fromhex("7064b0826d18")      # moveq #100,d0 ; cmp.l d2,d0 ; blt.s +0x18


def divert(content, code):
    """Replace the read's slot bound with the stub that decides instead."""
    at = BOUND - BASE
    here = bytes(content[at:at + len(STOCK)])
    if here != STOCK:
        raise SystemExit(f"the read bound at {BOUND:#010x} is {here.hex()}, not {STOCK.hex()}")
    content[at:at + len(STOCK)] = b"\x4e\xf9" + struct.pack(">I", code["lfo4_get_stub"])
    print("part 7 -- the read side")
    print(f"  {BOUND:#010x}  slot > 100 -> lfo4_get_stub {code['lfo4_get_stub']:#010x}")


# The companion table's accessor: ten bytes, two whole instructions, and the
# stub replays both. Without this the page draws eight empty dials -- it asks
# for entries 321 to 329, the right ones, and the accessor's bound clamps every
# answer to the fallback row (`scripts/emu_lfo4_widget.py`).
COMPANION = 0x400C2418
COMPANION_STOCK = bytes.fromhex("202f00040c8000000141")   # movel 4(sp),d0 ; cmpil #321,d0


def companion(content, code):
    """Give LFO4's entries a companion row, so its page draws real widgets."""
    at = COMPANION - BASE
    here = bytes(content[at:at + len(COMPANION_STOCK)])
    if here != COMPANION_STOCK:
        raise SystemExit(f"the companion accessor at {COMPANION:#010x} is {here.hex()}, "
                         f"not {COMPANION_STOCK.hex()}")
    start = code["lfo4_comp_displaced"] - bridge.CODE_VA
    mine = code.image[start:start + len(COMPANION_STOCK)]
    if mine != COMPANION_STOCK:
        raise SystemExit(f"the stub replays {mine.hex()}, the site holds {here.hex()}")
    jump = b"\x4e\xf9" + struct.pack(">I", code["lfo4_comp_stub"])
    content[at:at + len(COMPANION_STOCK)] = (
        jump + b"\x4e\x71" * ((len(COMPANION_STOCK) - len(jump)) // 2))
    print("part 8 -- the companion rows")
    print(f"  {COMPANION:#010x}  entries 321..330 -> lfo4_comp_stub "
          f"{code['lfo4_comp_stub']:#010x}")


if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks, divert,
                                        companion],
                                 chunks=table.chunks))

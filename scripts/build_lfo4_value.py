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

SOURCES = page.SOURCES + ("getter.c",)
ENTRIES = page.ENTRIES + ["lfo4_on_get", "lfo4_get_stub"]

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


if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks, divert],
                                 chunks=table.chunks))

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
                          "lfo4_companion", "lfo4_comp_stub",
                          "lfo4_wave_stub", "lfo4_wave_four"]

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


# The waveform preview is re-coded per LFO: three blocks at `0x4010e1f4`,
# `0x4010e22e` and `0x4010e27e`, each calling `0x4006538e` five times with its
# own entry numbers as literals, chosen by an index the dispatch already
# computes as 3 for LFO4. There is no block for 3, so the page drew no preview
# and `SPH` came out a plain dial.
WAVE_FALLBACK = 0x4010E2F0
WAVE_STOCK = bytes.fromhex("2f0a4eb94006597a")          # movel a2,-(sp) ; jsr 0x4006597a
LFO3_BLOCK = (0x4010E27E, 0x4010E2C6)                   # the block this one transcribes
# (LFO3's literal, LFO4's) in the order the block calls for them.
SUBSTITUTIONS = ((99, 325), (101, 327), (102, 328), (95, 321), (103, 329))


def waveform(content, code):
    """Add the fourth block, and assert it is the third with five constants changed."""
    at = WAVE_FALLBACK - BASE
    here = bytes(content[at:at + len(WAVE_STOCK)])
    if here != WAVE_STOCK:
        raise SystemExit(f"the preview fallback at {WAVE_FALLBACK:#010x} is {here.hex()}, "
                         f"not {WAVE_STOCK.hex()}")

    # What the firmware's own block is, and what ours must be: the same bytes
    # with five 16-bit immediates substituted. Checked rather than trusted,
    # because a transcription that has drifted into a paraphrase would still
    # assemble and would draw something subtly wrong.
    lo, hi = LFO3_BLOCK
    theirs = bytes(content[lo - BASE:hi - BASE])
    wanted = bytearray(theirs)
    for was, now in SUBSTITUTIONS:
        pea = bytes.fromhex("4878") + struct.pack(">H", was)
        if wanted.count(pea) != 1:
            raise SystemExit(f"LFO3's block holds {wanted.count(pea)} `pea {was}`, expected one")
        wanted[wanted.index(pea) + 2:wanted.index(pea) + 4] = struct.pack(">H", now)
    start = code["lfo4_wave_four"] - bridge.CODE_VA
    mine = code.image[start:start + len(theirs)]
    if mine != bytes(wanted):
        raise SystemExit("the fourth preview block is not the third with five constants "
                         "changed. firmware " + bytes(wanted).hex()
                         + ", ours " + mine.hex())

    jump = bytes.fromhex("4ef9") + struct.pack(">I", code["lfo4_wave_stub"])
    nop = bytes.fromhex("4e71")
    content[at:at + len(WAVE_STOCK)] = jump + nop * ((len(WAVE_STOCK) - len(jump)) // 2)
    print("part 9 -- the waveform preview")
    print(f"  {WAVE_FALLBACK:#010x}  index {3} -> lfo4_wave_stub {code['lfo4_wave_stub']:#010x}")
    print(f"  the block is LFO3's {len(theirs)} bytes with "
          + ", ".join(f"{a}->{b}" for a, b in SUBSTITUTIONS))


if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks, divert,
                                        companion, waveform],
                                 chunks=table.chunks))

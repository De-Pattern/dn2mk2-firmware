"""LFO4: the three things the instrument found in `lfo4-ui`, as far as they go.

    python scripts/build_lfo4_ui2.py

From the instrument, 2026-09-22, after flashing `lfo4-ui`:

> "when the device opens, only 3 dots are shown to the right of the mod page
> ... The Fourth do appears as soon as I press MOD once."
> "RND wave still shows phase."
> "The modulation destination window doesn't pop up yet but now the order
> reads correct I think."

Two of the three are fixed here. The third -- the modal browser -- is not: the
mask work landed (the order is right because the list is right) but whatever
opens the window is a decision this project has not found, and guessing at it
would be the third wrong model of that browser.

| what | where | why it was missed |
|---|---|---|
| the fourth page dot at boot | `0x40061558` / `0x40061562` | the vector was swapped on the first header draw, one frame too late |
| `RND` shows `SLEW` | `0x4003662c`, `0x40036a76` | **a second kind of site**, found by the `WAVE` entries rather than the `SPH` ones |

**The `RND` lesson is the one worth keeping.** `lfo4-ui` extended the gate that
picks *which entry a column draws* and the emulator confirmed it: LFO4 accepted
the gate 11 times and the table handed back entry 326. The screen still said
`SPH`, because two other routines separately decide *whether the waveform is
`RND`*, each by naming its own LFO's `WAVE` entry as a `pea` immediate. Counting
hits proved the patch worked and proved nothing about the outcome.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import build_lfo4_bridge as bridge                         # noqa: E402
import build_lfo4_page as page                             # noqa: E402
import build_lfo4_pagelist as pagelist                     # noqa: E402
import build_lfo4_slots as slots                           # noqa: E402
import build_lfo4_table as table                           # noqa: E402
import build_lfo4_ui as ui                                 # noqa: E402
import build_lfo4_value as value                           # noqa: E402

BASE = 0x40000400
OUT = ROOT / "out/lfo4-ui2"
SYX = ROOT / "00_Resources/02_Builds/lfo4-ui2_DN2_1.11.syx"

SOURCES = pagelist.SOURCES + ("rndhooks.S",)
ENTRIES = pagelist.ENTRIES + ["lfo4_rnd_a_stub", "lfo4_rnd_b_stub"]

# `moveb #81,%d0 ; cmpl %d2,%d0 ; bne <decline>` -- the last of three compares,
# and the only eight contiguous bytes of the gate holding both exits. The two
# sites are byte-identical, displacement included.
RND_STOCK = bytes.fromhex("103c0051b0826646")
RND_SITES = ((0x4003662C, "lfo4_rnd_a_stub"), (0x40036A76, "lfo4_rnd_b_stub"))


def rnd(content, code):
    """Teach both "is the waveform RND?" routines about LFO4's WAVE entry."""
    print("part 13 -- is the waveform RND, asked twice")
    for va, stub in RND_SITES:
        ui._jump(content, va, RND_STOCK, code[stub], "the RND waveform test")
        print(f"  {va:#010x}  SPH 81/91/101 -- and 327 -> {stub} {code[stub]:#010x}")


if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        ui.slew, ui.dest, pagelist.pagelist, rnd],
                                 chunks=table.chunks))

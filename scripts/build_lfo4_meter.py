"""LFO4 with three of its own dials turned into instruments pointed at itself.

    python scripts/build_lfo4_meter.py

**This build is not a fix and is not meant to sound better.** It is the browser
build with three columns of LFO4's page displaying a measurement instead of a
value, so that the one open question can be *read off the glass* while the
instrument is played.

**Why measuring beats another bisect.** Three flashes -- `browser`, `keeprow`,
`keepall` -- each answered one binary question, and between them they closed the
whole removal branch: with every route by which a row can disappear switched
off, the modulation is still erratic. Continuing that way costs one flash per
bit. Meanwhile the *state* that would settle it exists on the instrument and
nowhere else: the emulator runs neither the sequencer nor a pattern load, so it
cannot be asked what key the panel wrote under while a pattern played.

**And the suspect is already narrowed to the lookup, by a result in the
record.** `lfo4-tick7` drove the same two evaluator indices with a **static**
sixteen-row table in the image and modulated *reliably* on hardware on
2026-09-20, each track reading its own row. Every build after it replaced that
static table with `lfo4_refresh(track)` -- a **lookup** -- and every one has
been erratic. So the engine path is not the suspect; the join between the key
the panel writes under and the key the tick asks under is.

**What the three columns say**, and every one of them is a needle at a stop or
at centre, never a number to be interpreted (`csrc/lfo4/meter.c` explains why):

| column | full right | full left | centre |
|---|---|---|---|
| `SPD` | the tick's last lookup **found** a row | it found nothing and took the defaults | it has never looked |
| `FADE` | the sound the knob wrote under **is** one of the sixteen the tick asks about | it is **not** -- and that alone is the entire fault | -- |
| `DEP` | not a needle: the depth **the engine is holding right now** | | |

`MULT`, `DEST`, `WAVE`, `SPH` and `MODE` are untouched, so a destination can
still be chosen and the LFO still runs while the three are read.

**The values are not affected.** Only the display is diverted: the knob still
writes the table and the save path still reads it, so a metered build stores
exactly what `lfo4-browser` would.

**How to read a session.** Set `DEST` and turn `DEP` to its stop, then play the
track and watch:

  * `FADE` **left** -- found it. The panel is editing a sound the engine never
    asks about, and the next build keys by something both sides agree on.
  * `FADE` right, `SPD` flicking left as you trig -- the keys agree but the
    table loses the row at tick time, and the search moves inside `ext_find`.
  * `FADE` right, `SPD` right, `DEP` holding your value, and still no
    modulation -- then tick7's result and this one disagree, and the engine
    path is back on the table after all.
  * `DEP` **falling back to 0 on its own** -- that is the bug happening, live,
    and whatever you were doing at that moment is what causes it.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import build_lfo4_bridge as bridge                         # noqa: E402
import build_lfo4_browser as browser                       # noqa: E402
import build_lfo4_page as page                             # noqa: E402
import build_lfo4_pagelist as pagelist                     # noqa: E402
import build_lfo4_slots as slots                           # noqa: E402
import build_lfo4_table as table                           # noqa: E402
import build_lfo4_ui as ui                                 # noqa: E402
import build_lfo4_ui2 as ui2                               # noqa: E402
import build_lfo4_value as value                           # noqa: E402

OUT = ROOT / "out/lfo4-meter"
SYX = ROOT / "00_Resources/02_Builds/lfo4-meter_DN2_1.11.syx"

# `lfo4-forcerow` was rebuilt over a filename that already meant something
# else, the owner flashed what he thought was the gated build, and an evening
# of results had to be thrown away. A build script refuses to overwrite.
SOURCES = ui2.SOURCES + ("meter.c",)

if __name__ == "__main__":
    if SYX.exists():
        raise SystemExit(f"{SYX} exists -- move it aside; this script never overwrites a build")
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ui2.ENTRIES,
                                 out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        ui.slew, ui.dest, pagelist.pagelist, ui2.rnd,
                                        browser.browser],
                                 chunks=table.chunks,
                                 defines={"LFO4_METER": 1}))

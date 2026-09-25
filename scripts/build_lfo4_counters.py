"""LFO4 with the lookup counters on the page, and SPD/DEP left honest.

    python scripts/build_lfo4_counters.py

**What the two-knob test settled, 2026-09-23.** With LFO3 audible on the same
destination as a control, the owner raised and lowered LFO4's `DEP`:

  *"it changes on some trigs, not in others. When it does, it sounds like I
  would expect for the LFO4 contribution working as it should."*

That kills three readings at once. LFO4 **reaches the cell the voice reads**, so
it is not a wrong cell and not different memory; and it is **correct when
present**, so it is not a depth, scale or phase error. The contribution is
wholly there or wholly absent, per note -- which is exactly what a row holding
`ext_default` looks like, because that default's `DEST` is None and a None
destination is silent and total.

**Why no offline harness could have found this.** `lfo4_refresh` re-resolves
only when the sound pointer or the generation changes:

    if (sound == seen_sound[track] && generation == seen_generation[track])
        return row;

so a miss can only happen where something changes -- at note-on. Every emulator
harness in this repo runs on a snapshot that has booted and never plays a note,
which is why `emu_lfo4_uikey.py` could prove the keys agree *at rest* and prove
nothing about the moment that matters. `lfo4_hits`, `lfo4_misses` and
`lfo4_refreshes` have been in the bridge since it was written and have **never
been read on hardware**. This build reads them.

**The two columns, and the reason they are these two.**

    WAVE -> lfo4_misses     climbs when ext_find came back empty
    SPH  -> lfo4_refreshes  climbs on every tick -- the liveness control

`SPD` and `DEP` are left alone deliberately: the test still turns them, and
`docs/lfo4-build-plan.md` already records the cost of diverting a column whose
value has to be right -- the owner read a diverted `FADE` as real and set LFO3
to match it. `WAVE` and `SPH` keep their values; only their display lies.

**What a pass looks like.** Set the sound up first, then leave WAVE and SPH
alone and watch them while trigs play:

  * `refreshes` climbing and `misses` climbing in step with the **silent** trigs
    -> the row is missing at note time. The fault is the cache or the key, and
    both are small.
  * `refreshes` climbing and `misses` **flat** while trigs are still silent
    -> the row is right and something downstream drops it. A different problem,
    but a bounded one.
  * `refreshes` **frozen** -> the tick is not running and `misses` means
    nothing. That is the control failing, and it is the outcome to report first.
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

SOURCES = ui2.SOURCES + ("meter.c",)

OUT = ROOT / "out/lfo4-counters"
SYX = ROOT / "00_Resources/02_Builds/lfo4-counters_DN2_1.11.syx"

if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ui2.ENTRIES,
                                 out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        ui.slew, ui.dest, pagelist.pagelist, ui2.rnd,
                                        browser.browser],
                                 chunks=table.chunks,
                                 defines={"LFO4_KEEP_ROWS": 1, "LFO4_KEEP_ALL": 1,
                                          "LFO4_METER": 1, "LFO4_COUNTERS": 1}))

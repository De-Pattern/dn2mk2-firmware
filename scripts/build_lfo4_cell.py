"""Does LFO4's contribution actually arrive in the mirror on the instrument?

    python scripts/build_lfo4_cell.py

**This is the one question left, and only the instrument can answer it.**

By 2026-09-23 everything measurable about LFO4 has been measured and none of it
explains the fault. The row the engine holds is correct and continuously
present; nothing removes it, proved with a control; and driving evaluator A in
the emulator with **LFO3 configured beside it** produces two trajectories that
are *byte-identical* over 240 frames (`scripts/emu_lfo4_vs_lfo3.py`). Yet on
the instrument LFO3 sweeps every time and LFO4 about one trig in fifteen.

So the next thing to look at is not a setting or a table -- it is **the cell**:
the place in the per-track parameter mirror where an LFO's contribution lands,
and which the DSP reads. Two columns of LFO4's page now show it live:

| column | shows |
|---|---|
| `SPD` | the mirror cell **LFO4** is aiming at |
| `DEP` | the mirror cell **LFO3** is aiming at |

`mirror[track][slot] = 0x800068e4 + 34 + 202*track + 2*slot`, the firmware's own
arithmetic, confirmed by construction when a hand-computed cell in block 16
turned out to be the parameter the formula named.

**Set the two LFOs to different destinations**, or they stack into one cell and
both columns show the same number.

**How to read it, and every outcome says something:**

| on the glass | what it means |
|---|---|
| **both numbers moving** | LFO4's contribution reaches the mirror exactly as LFO3's does, continuously. Then the fault is downstream of the mirror -- in what a voice does with it at note-on -- and the sequencer has to be driven after all |
| **`DEP` moves, `SPD` sits still** | LFO4's contribution never arrives. The evaluator's fourth iteration is not running on the instrument although it runs in the emulator, and the difference is in how the evaluator is *called*, not in what it does |
| **`SPD` moves only when a trig sounds** | the fourth iteration is gated by something per-note, and whatever is on screen at that moment is the lead |
| **neither moves** | the setup is wrong -- most likely both LFOs aiming at the same slot, or depth at centre. Fix before reading anything |

It is an instrument, not a fix. `FADE` and every other column behave normally;
the removal paths stay off, as in `lfo4-meterkeep`, so nothing can drop a row
while the reading is taken.
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

OUT = ROOT / "out/lfo4-cell"
SYX = ROOT / "00_Resources/02_Builds/lfo4-cell_DN2_1.11.syx"

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
                                 defines={"LFO4_METER": 1, "LFO4_KEEP_ROWS": 1, "LFO4_KEEP_ALL": 1}))

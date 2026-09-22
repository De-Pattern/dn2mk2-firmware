"""LFO4: `lfo4-ui2` with nothing allowed to remove a row. A bisect, not a fix.

    python scripts/build_lfo4_keeprow.py

From the instrument, 2026-09-22:

> "The intermittency ringing actual modulation is rare, most of the time I
> trigger there is no modulation but 1 every 15 or 20 actuations some
> modulation rings ... it plays it until I release the track trigger. Then if I
> play the track trigger again it doesn't play the modulation."

The reading that fits: a copy or a clear of the live sound removes the row.
`csrc/lfo4/ext.c` explains which three places do it and why each is correct as
mirroring. This build defines `LFO4_KEEP_ROWS`, which turns all three off.

**Why it is a build and not a probe.** The emulator runs neither the sequencer
nor the pattern load. `scripts/emu_lfo4_trig.py` wrote a value on the fourth
MOD page, pressed TRIG 1 -- code 25, read out of the firmware's own control
table -- and saw the entry survive with `ext_copy` and `ext_drop` called zero
times and no 1,163-byte copy at all. That is a harness that never reached the
path, not an acquittal, and no amount of further reading settles it.

**What each outcome means**, and they are not symmetric:

| on the instrument | conclusion |
|---|---|
| modulation persists from one trig to the next | the drop path is the cause; the fix belongs in how a row is carried, not in whether it is dropped |
| still about one press in fifteen | the drop path is innocent and a whole branch closes |

It is **not a candidate fix**: keeping a row whose sound really was overwritten
leaves a stale value behind, which is a different bug of the same shape. If it
passes, the fix is to make the panel's edit and the engine's read agree about
which sound owns the values, so a copy carries them the way it carries every
parameter Elektron put inside the sound.
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

OUT = ROOT / "out/lfo4-keeprow"
SYX = ROOT / "00_Resources/02_Builds/lfo4-keeprow_DN2_1.11.syx"

if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=ui2.SOURCES, entries=ui2.ENTRIES,
                                 out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        ui.slew, ui.dest, pagelist.pagelist, ui2.rnd,
                                        browser.browser],
                                 chunks=table.chunks,
                                 defines={"LFO4_KEEP_ROWS": 1}))

"""LFO4 with **every** route by which a row can disappear switched off.

    python scripts/build_lfo4_keepall.py

`lfo4-keeprow` turns off three of them -- the drops inside `ext_copy`,
`ext_carry` and `ext_clear`, which fire when a sound is copied or cleared. It
was built and gated that way and it stays that way; this is a separate build
with a separate define, so neither changes under the other.

**The fourth is the busiest and it was missed.** `lfo4_on_load` drops the live
entry whenever the stored sound it is loading carries no LFO4 values, and a
single boot runs it **2,192 times**. If sounds reload while a pattern plays,
an LFO4 edit that has not been saved is wiped by the next load of that sound --
and trigging faster gives more chances to land between one load and the next,
which is exactly the shape the instrument reports:

> "the faster I press the trigger the more frequent I can hear the modulation
> happening ... at a fast speed of triggering the modulation might come every
> other 4 trigs but at a slower triggering it might come every 14 trigs"

So this build defines `LFO4_KEEP_ROWS` **and** `LFO4_KEEP_ALL`. Nothing removes
a row: not a copy, not a clear, not a load.

**What each outcome means**, and one flash gives one of them:

| on the instrument | conclusion |
|---|---|
| modulation on every trig | a removal path is the cause. Which one is then a cheap follow-up, because they can be re-enabled one at a time |
| still about one trig in fifteen | nothing is removing the row -- it never arrives under the key the engine asks for at note-on, and the search moves to `ext_find`'s key |

**It is a question, not a fix**, and it will misbehave on purpose: a sound that
genuinely should lose its LFO4 settings will keep them, so expect settings to
bleed between sounds and patterns. That is the experiment working. If it
passes, the fix is not "stop dropping" -- it is to make the row travel with the
sound the way the parameters Elektron put *inside* the sound already do.
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

OUT = ROOT / "out/lfo4-keepall"
SYX = ROOT / "00_Resources/02_Builds/lfo4-keepall_DN2_1.11.syx"

if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=ui2.SOURCES, entries=ui2.ENTRIES,
                                 out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        ui.slew, ui.dest, pagelist.pagelist, ui2.rnd,
                                        browser.browser],
                                 chunks=table.chunks,
                                 defines={"LFO4_KEEP_ROWS": 1, "LFO4_KEEP_ALL": 1}))

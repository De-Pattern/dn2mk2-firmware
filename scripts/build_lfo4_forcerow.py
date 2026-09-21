"""The bisect build: LFO4 with the table lookup's answer thrown away.

    python scripts/build_lfo4_forcerow.py

`lfo4-value` gives a fourth MOD page that draws correctly, takes knob turns,
reads them back and saves them -- and on the instrument modulates nothing at
any depth or destination. Two halves can produce that and no harness here can
separate them:

1. the **lookup**: the panel writes into the extension table under the sound
   the firmware hands the setter, and the tick reads it back under a sound the
   bridge works out from the track. If those disagree, every read misses and
   the row is defaults.
2. the **engine path**: the evaluator stubs turning a row into audible
   modulation. `tick7` proved that on hardware with a fixed table, and the
   bridge then replaced the fixed table with a call -- which has never produced
   an audible sweep on the instrument, because the bridge's own hardware test
   ran with an empty table and passing meant silence.

This build is identical to `lfo4-value` except that `lfo4_refresh` overwrites
the row it just filled with **tick7's row**, the one combination already proved
audible. Every track, every sound.

- **It sweeps** -> the engine path is fine and the lookup is the fault.
- **It does not** -> the engine path broke when the bridge replaced tick7's
  table with a call, and the page is a red herring.

Either answer halves the search, and it costs one flash. The lookup still runs
first, so a build that crashed in `ext_find` would not be exonerated by
skipping it.
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
import build_lfo4_slots as slots                           # noqa: E402
import build_lfo4_table as table                           # noqa: E402
import build_lfo4_value as value                           # noqa: E402

OUT = ROOT / "out/lfo4-forcerow"
SYX = ROOT / "00_Resources/02_Builds/lfo4-forcerow_DN2_1.11.syx"


if __name__ == "__main__":
    raise SystemExit(bridge.main(
        sources=value.SOURCES, entries=value.ENTRIES, out=OUT, syx=SYX,
        extra=[slots.divert, table.relocate, page.hooks, value.divert,
               value.companion, value.waveform],
        chunks=table.chunks, defines={"LFO4_FORCE_ROW": 1}))

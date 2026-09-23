"""`lfo4-meter3`, plus every route by which a row can disappear switched off.

    python scripts/build_lfo4_meterkeep.py

**Why the removal branch is being reopened.** `docs/lfo4-build-plan.md` records
it as closed: `browser` (all drop paths on), `keeprow` (three off) and
`keepall` (all four off) were each flashed and each came back erratic, and the
conclusion written down was that removing a row is not the cause.

**Every one of those three readings was taken on a stage nobody had
controlled.** On 2026-09-22 the owner ran LFO3 beside LFO4 for the first time,
and the evening's findings were: a destination can be inert on the machine in
use (slot 26 is `Ratio C` in one group and `Osc1 Waveform`, `Sweep Time` or
`Swarm Detune` in the others); the mirror clamps at `0x7f00`, so full depth
into a parameter already at its end is silence; and fade near maximum makes an
LFO *"almost just a blip"* on a trig while at 0 it sweeps normally. None of
those three was held fixed for `browser`, `keeprow` or `keepall`.

So "still erratic" may have been measuring the stage, not the row. A negative
taken without a control is not evidence, and three of them are not three pieces
of evidence -- they are the same untested assumption three times.

**This build asks the question again on a stage that can be trusted**, and it
asks it with the instrumentation attached rather than by ear alone:

  * `LFO4_KEEP_ROWS` + `LFO4_KEEP_ALL` -- nothing removes a row: not a copy,
    not a clear, and not `lfo4_on_load`, which runs 2,192 times in a boot;
  * `SPD` shows the destination in the row the engine is holding, so the stage
    is visible rather than assumed -- `Filter Frequency` must read `+3.00`;
  * `DEP` shows that row's depth;
  * every other column, `FADE` included, is itself.

**It will misbehave on purpose.** A sound that should lose its LFO4 settings
keeps them, so expect settings to bleed between sounds and patterns. That is
the experiment working, not a fault.

Two outcomes and one flash:

| on the instrument | conclusion |
|---|---|
| modulation on every trig, with LFO3 sweeping beside it | a removal path is the cause after all, and the three earlier readings were measuring an uncontrolled stage. The fix is to make the row travel with the sound the way the parameters Elektron put *inside* the sound already do |
| still erratic on a stage where LFO3 sweeps | removal really is not the cause, the earlier conclusion stands, and it now stands on evidence instead of on an assumption |
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

OUT = ROOT / "out/lfo4-meterkeep"
SYX = ROOT / "00_Resources/02_Builds/lfo4-meterkeep_DN2_1.11.syx"

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

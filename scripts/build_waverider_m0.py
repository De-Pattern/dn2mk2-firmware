"""Waverider Milestone 0: one baked wavetable, read back over telemetry.

    python scripts/build_waverider_m0.py [--name waverider-m0]

`docs/waverider-feasibility.md`, "Milestone 0": bake one table (16 frames x
512 int16, 16 KB) into the firmware's own space, have the firmware read it back
at run time, and report it over the telemetry channel, so the delivery chain --
reduce, bake, load, address, read -- is proven end to end.

**What it is built on, and why.** The telemetry build (`build_lfo4_tlm.py
--persist`): LFO4 with release semantics and the persistence counters, and
**no** page column diverted. That is a configuration already gated and flashed,
so the only thing this image adds is Milestone 0 itself:

  * `csrc/waverider/table.c` -- the table as `const` data, linked into the
    `CODE` chunk the loader copies to `0x46800000`, plus one reader;
  * one call, `wr_m0_report()`, inside the LFO4 telemetry burst right after
    `probe_a` = 99 (`csrc/lfo4/bridge.c`, under `WAVERIDER_M0`).

It touches **no** machine, selector, machine-list ceiling or engine code: the
burst it rides already exists, and what it adds reads only its own data.

**The data is generated here, at build time**, by `dnfw.waverider` from an
original formula (`dnfw.waverider.testtable`), into `out/<name>/gen/`. The
header is output, not source. `dnfw waverider expect` prints what the
instrument must report from the very same generator.

**Placement is checked, not assumed.** The C image grows by the table, and the
chunk it lives in must still end below `0x46900000`, where step 4b's relocated
parameter table is loaded (`build_lfo4_table.TABLE_VA`).
"""

from __future__ import annotations

import json
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
import build_lfo4_tlm as tlm                               # noqa: E402
import build_lfo4_ui as ui                                 # noqa: E402
import build_lfo4_ui2 as ui2                               # noqa: E402
import build_lfo4_value as value                           # noqa: E402
from dnfw.waverider import bake, expect, reduce, testtable   # noqa: E402

SOURCES = tlm.SOURCES + ("waverider/table.c",)
ENTRIES = ui2.ENTRIES + ["wr_m0_report", "wr_table"]
EXTRA = [slots.divert, table.relocate, page.hooks, value.divert, value.companion,
         value.waveform, ui.slew, ui.dest, pagelist.pagelist, ui2.rnd, browser.browser]
# `build_lfo4_tlm.py --persist`, exactly: release semantics, no page diversion.
DEFINES = {"LFO4_PERSIST": 1, "LFO4_TELEMETRY": 1, "WAVERIDER_M0": 1}


def placement(content, code) -> None:
    """Refuse a C image that would run into the relocated parameter table."""
    at, n = code["wr_table"], reduce.FRAMES * reduce.POINTS * 2
    if code.end > table.TABLE_VA:
        raise SystemExit(f"the C chunk ends at {code.end:#010x}, past {table.TABLE_VA:#010x} "
                         f"where the relocated parameter table loads")
    print(f"  waverider: table {n:,} B at {at:#010x}..{at + n:#010x}; the C chunk "
          f"(image {len(code.image):,} B + BSS {code.bss:,} B) ends at {code.end:#010x}, "
          f"{table.TABLE_VA - code.end:,} B below {table.TABLE_VA:#010x}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Waverider Milestone 0")
    ap.add_argument("--name", default="waverider-m0",
                    help="build name: out/<name> and 00_Resources/02_Builds/<name>_DN2_1.11.syx")
    # **Local testing only.** A WAV that is not ours -- Elektron's factory set,
    # a third-party pack -- may be baked to try it on the owner's own instrument,
    # never into a build this project ships or offers. The default is the
    # original table, and the build says loudly when it is not.
    ap.add_argument("--wav", type=pathlib.Path, default=None,
                    help="LOCAL TESTING ONLY: bake this WAV instead of the original table")
    cli = ap.parse_args()
    out = ROOT / f"out/{cli.name}"
    syx = ROOT / f"00_Resources/02_Builds/{cli.name}_DN2_1.11.syx"
    if syx.exists():
        raise SystemExit(f"  {syx.name} already exists. Pick another --name, or "
                         f"delete it deliberately if this is a rebuild of the same thing.")

    gen = out / "gen"
    gen.mkdir(parents=True, exist_ok=True)
    baked = reduce.from_wav(cli.wav.read_bytes()) if cli.wav else testtable.table()
    if cli.wav:
        print(f"  ** LOCAL TESTING ONLY: baking {cli.wav.name}, not the original table. "
              f"Do not ship or offer this build. **")
    (gen / "wr_table_data.h").write_text(bake.header(baked, expect.PROBES, expect.SLICE),
                                         encoding="utf-8", newline="\n")
    print(f"part 0 -- baked {len(baked)} x {len(baked[0])} int16, checksum "
          f"{bake.checksum(baked):#06x}, into {gen.relative_to(ROOT)}")
    # What was baked, so the emulator check can be pointed at the same source.
    (out / "waverider.json").write_text(json.dumps({
        "source": str(cli.wav.resolve()) if cli.wav else "dnfw.waverider.testtable",
        "local_testing_only": bool(cli.wav),
        "checksum": f"{bake.checksum(baked):#06x}"}, indent=1) + "\n", newline="\n")

    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=out, syx=syx,
                                 extra=[*EXTRA, placement], chunks=table.chunks,
                                 defines=DEFINES,
                                 include=[ROOT / "csrc" / "waverider", gen],
                                 exports=("wr_",)))

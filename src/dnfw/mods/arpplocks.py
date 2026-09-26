"""P-locks for the arpeggiator: MODE, SPEED, RANGE and N.LEN per trig.

Stock Digitone II firmware keeps the ARPEGGIATOR settings on the sound only.
With this mod, holding a trig in grid recording and turning a value in the
ARPEGGIATOR menu locks it to that trig, like any parameter: the value shows
inverted while the trig is held, the trig blinks, the lock is saved with the
pattern, and trigless lock trigs change a running arp. **Passed on the
instrument on 2026-09-19.** `docs/ideas-backlog.md` §18 carries the history,
and `scripts/build_arp_plocks.py` the design, assembly and evidence.

A MODE lock stops where the menu stops: its ceiling is read from setMode's own
clamp (the immediate at `0x4004bf01`), 4 (CYCL) on stock and 6 (RAND) with
`arpmodes`. That read was added on 2026-09-26, after the hardware pass. It
shifts the UI cave by 10 bytes, and it is checked in the emulator
(`scripts/emu_arp_modes.py`, `scripts/emu_arp_plocks.py`), not yet on the
instrument.

## How it applies

The code is assembled ahead of time (`scripts/gen_arpplocks_code.py` ->
`arpplocks_code.json`), so the bytes applied are exactly those tested:

1. every guard and every edit's stock bytes are checked -- an image that
   differs is refused;
2. the edits are written: four code caves, the hooks and a few byte patches.

It writes only inside section 3, changes no length and appends nothing. Its
largest cave sits in the run the boot screen starts, past the boot screen's
366 bytes, so the two combine. RAM: 16 shadow sounds from `0x467c0000`.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result

ID = "arpplocks"
NAME = "Arpeggiator p-locks"
SUMMARY = "MODE, SPEED, RANGE and N.LEN of the arpeggiator lockable per trig."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("arpplocks_code.json")).read_text())


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    # Longer is fine: data appended after the stock end (lfowaves, bootscreen)
    # moves no address this mod writes or reads.
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11, or another mod already wrote there")
    for e in SPEC["edits"]:
        want = bytes.fromhex(e["stock"])
        if original[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11, or another mod already wrote there")

    content = bytearray(original)
    for e in SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["hold a trig in grid recording, turn MODE / SPEED / RANGE / N.LEN "
                         "in the ARPEGGIATOR menu: a p-lock",
                         f"{len(SPEC['edits'])} edits in section 3, nothing appended"])

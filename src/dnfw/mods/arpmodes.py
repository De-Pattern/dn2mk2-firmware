"""Two more arpeggiator modes: SHUF and RAND, whose names the firmware already has.

Stock Digitone II 1.11 names eight arp modes, `OFF TRUE UP DOWN CYCL SHUF RAND
CHRD`, offers five, and plays CYCL for anything above DOWN
(`docs/arp-hidden-modes.md`). This mod gives SHUF and RAND real code and
widens the MODE menu to them; CHRD (7) stays out, and a 7 still plays CYCL.

- **SHUF**: every note of the range (the held notes x RNG + 1 octaves) once per
  cycle, in a new random order each cycle; the note that ends one cycle never
  starts the next.
- **RAND**: a random note of the range on every step, repeats allowed.

SPD, LEN, the step mask (a muted step rests and does not advance), the step
offsets and N.LEN behave as in every other mode: the new code only chooses the
note and octave and hands them to the step's own tail.

`scripts/build_arpmodes.py` has the design, the RAM layout and the choice of
random source (a private xorshift32, stirred with the millisecond tick when an
arp starts; the firmware's shared `rand()` is not touched).

## How it applies

The code is assembled ahead of time (`scripts/gen_arpmodes_code.py` ->
`arpmodes_code.json`, which is checked to reproduce the build byte for byte):

1. every guard and every edit's stock bytes are checked -- an image that
   differs is refused;
2. the edits are written: two code caves, the dispatch hook, five bounds.

It writes only inside section 3, changes no length and appends nothing. RAM:
2,320 bytes at `0x467a0000`, above BSS.

## A sound saved with SHUF or RAND

Saved as MODE 5 or 6. On stock firmware (or any build without this mod) it
loads with its arp **OFF**: the stock LOAD bound turns anything above 4 into 0.

## With arpplocks

arpplocks' MODE lock takes its ceiling from the menu edit's own clamp (the
immediate of `0x4004bf00`), so with this mod a MODE lock reaches RAND, and
without it the lock stops at CYCL as before. Nothing here writes arpplocks'
bytes, and the two apply in either order.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result

ID = "arpmodes"
NAME = "Arpeggiator SHUF and RAND"
SUMMARY = "Two more arp modes: SHUF (each note once per cycle, shuffled) and RAND."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("arpmodes_code.json")).read_text())


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    if original is None:
        raise ModError("MAIN OS did not depack")
    # Longer is fine: data appended after the stock end (lfowaves, bootscreen)
    # moves no address this mod writes or reads. The guards identify the build.
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        at = g["va"] - BASE
        if original[at:at + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} ({g['what']}) is not stock; this mod is "
                           "for unmodified Digitone II 1.11")
    for e in SPEC["edits"]:
        want = bytes.fromhex(e["stock"])
        at = e["va"] - BASE
        if original[at:at + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} ({e['what']}) is not stock; this mod is "
                           "for unmodified Digitone II 1.11, or another mod already "
                           "wrote there")

    content = bytearray(original)
    for e in SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["the ARPEGGIATOR MODE menu offers SHUF and RAND after CYCL, "
                         "and stops there",
                         f"{len(SPEC['edits'])} edits in section 3, nothing appended"])

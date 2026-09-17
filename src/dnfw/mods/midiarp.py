"""The arpeggiator on MIDI tracks: a MIDI track with the arp on arpeggiates over MIDI.

Stock Digitone II firmware hides the ARPEGGIATOR menu on MIDI tracks, and the
arp itself lives only on the synth voice path, so a MIDI track's notes never
meet it. This mod opens the menu, sends an arp-enabled MIDI track's notes
through the ISR's arpeggiator, and turns each note it plays into a MIDI record
on the batch the ISR already hands the MIDI task. **Passed on the instrument on
2026-09-17** as `arp-midi-play4`: offsets, velocity, SPD, RNG and N.LEN (1/32 to
1/4 within a millisecond), no stuck notes. `docs/ideas-backlog.md` §10 carries the
whole history, and `scripts/build_arp_midi_play.py` the assembly and evidence.

## How it applies

The code is assembled ahead of time (`scripts/gen_midiarp_code.py` ->
`midiarp_code.json`), so the browser applies exactly these bytes:

1. every guard (whole instructions and the code the hooks rely on) and every
   edit's stock bytes are checked -- an image that differs is refused;
2. the edits are written: two menu bytes, five hooks, and the code cave;
3. the cave's N.LEN lookup is rebuilt from this image's own length tables.

It writes only inside section 3, changes no length, and appends nothing, so it
does not compete for the appended area or the startup hook.
"""

from __future__ import annotations

import json
import pathlib
import struct

from . import Extent, ModError, Result

ID = "midiarp"
NAME = "Arpeggiator on MIDI tracks"
SUMMARY = "The arpeggiator on MIDI tracks: the menu opens, and the arp plays out over MIDI."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("midiarp_code.json")).read_text())
LUT_BYTES = 128


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]


def nlen_lut(content: bytes) -> bytes:
    """For each N.LEN, the trig length index nearest in duration (ties shorter);
    INF becomes 126, the longest finite trig length. The MIDI task times notes
    only through the trig table."""
    def table(va: int) -> list[int]:
        at = va - BASE
        return list(struct.unpack(">128i", content[at:at + 512]))
    trig = table(SPEC["trig_lengths_va"])[:127]
    return bytes(126 if want < 0 else
                 min(range(127), key=lambda i: (abs(trig[i] - want), trig[i]))
                 for want in table(SPEC["arp_lengths_va"]))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    # Longer is fine: data appended after the stock end (lfowaves, bootscreen)
    # moves no address this mod writes or reads. The guards below are what
    # identify the build.
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11")
    for e in SPEC["edits"]:
        want = bytes.fromhex(e["stock"])
        if original[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11, or another mod already wrote there")

    content = bytearray(original)
    for e in SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    lut = SPEC["lut_va"] - BASE
    content[lut:lut + LUT_BYTES] = nlen_lut(original)

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["ARPEGGIATOR menu opens on MIDI tracks",
                         "an arp-enabled MIDI track plays its arp out over MIDI",
                         f"{len(SPEC['edits'])} edits in section 3, nothing appended"])

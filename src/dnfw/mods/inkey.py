"""v0.70: the arp's offsets and the track's transpose in key: w-winter's `arpscale` and
`degreetranspose`, from upstream (angellinares/dn2_firmware_explore, AGPL-3.0, pull requests #212,
#214 and #278; upstream commit 5923e1b), applied inside the DN2 mk2 build as midiarp is (v0.67).

- **arpscale** (SETTINGS > PERSONALIZE > ARP OFS IN SCALE, off by default): each arp step's
  offset counts degrees of the track's KEYBOARD SETUP scale from its root, not semitones; [UP]
  on an active step in the ARPEGGIATOR menu marks it to move in semitones. Confirmed on
  upstream's unit 2026-10-14, and on w-winter's.
- **degreetranspose**: [KEYBOARD] + [FUNC] + [+]/[-] (or [KEYBOARD] + [TRK] + [+]/[-]) moves the
  active track by degrees of its scale, -7..+7, kept per track in each pattern, MIDI tracks
  included. Reported working on w-winter's unit (upstream docs/flashing.md, 2026-10-12..14).

The 1.11 specs (`arpscale_code.json`, `degreetranspose_code.json`) are upstream's, byte for byte:
each edit's stock bytes and every guard are checked in the image first (none of them is a site
the DN2 mk2 mod writes), the edits written, and each CODE chunk loaded at its own address
(0x467A8000, 0x467B8000), clear of ours. The sources that assembled them are in
`scripts/upstream_inkey/` (upstream's, unchanged). `docs/inkey.md`.
"""
from __future__ import annotations

import json
import pathlib

from . import Extent, ModError

BASE = 0x40000400
SECTION = 3
HERE = pathlib.Path(__file__).resolve().parent
SPECS = {m: json.loads((HERE / f"{m}_code.json").read_text()) for m in ("arpscale", "degreetranspose")}
FLAG = 0x405CD8AF                     # ARP OFS IN SCALE (arpscale's toggle, the settings block's tail)


def extents() -> list[Extent]:
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, f"v0.70 {m}: {e['what']}")
            for m, s in SPECS.items() for e in s["edits"]]


def check(content: bytes) -> None:
    """every guard and every edit's stock bytes, in CONTENT (MAIN OS) -> ModError when not"""
    for m, s in SPECS.items():
        for g in s["guards"]:
            want = bytes.fromhex(g["bytes"])
            if content[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
                raise ModError(f"0x{g['va']:08x} is not stock ({m}'s guard)")
        for e in s["edits"]:
            want = bytes.fromhex(e["stock"])
            if content[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
                raise ModError(f"0x{e['va']:08x} is not stock ({m}'s edit)")


def write(content: bytearray) -> None:
    for s in SPECS.values():
        for e in s["edits"]:
            new = bytes.fromhex(e["new"])
            content[e["va"] - BASE:e["va"] - BASE + len(new)] = new


def chunks() -> list[tuple[int, bytes]]:
    """(load address, code) of each mod's CODE chunk"""
    return [(s["code"]["va"], bytes.fromhex(s["code"]["blob"])) for s in SPECS.values()]

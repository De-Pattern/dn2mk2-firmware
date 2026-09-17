"""Seven new LFO waveforms, and three wavetables the user can swap for their own.

After RAND: STEP, PULS, NOIS, TRAP, WTB1, WTB2, WTB3 -- each with a glyph drawn
from the waveform itself and SPH renamed for what it does (STPS, WDTH, TYPE,
SLOP, POS). **Passed on the instrument on 2026-09-17** as `lfo-waves` (and with
TRAP's linear edge as `lfo-waves2`); `docs/ideas-backlog.md` §8 and §14 carry the
whole history.

## What the user chooses

Each of the three wavetables: ours (basic shapes, harmonic sweep, vowels), or a
file of their own -- a WAV wavetable or a JSON table (`dnfw.wavetable`), reduced
to 7 frames of 32 points. SPH (`POS`) sweeps through the table at run time.

## How it applies

The code is assembled ahead of time (`scripts/gen_lfo_waves_code.py` ->
`lfowaves_code.json`), so the browser applies exactly these bytes:

1. every in-image edit is checked against the stock bytes it expects, then
   written -- hooks, repoints, clamps, vtable slots, and the 46-byte boot copy
   stub in a cave;
2. the appended blob is filled: the stock entries of each relocated table are
   copied from this image, and each wavetable's 224 bytes are ours or the user's;
3. the blob is appended to MAIN OS, where the boot stub copies it to RAM.

Like the boot-screen mod it grows MAIN OS through the appended area and claims the
startup hook, so the two are alternatives until a shared area registry exists --
`check_compatible` reports the overlap.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result

ID = "lfowaves"
NAME = "New LFO waveforms"
SUMMARY = "STEP, PULS, NOIS, TRAP and three swappable wavetables as LFO waveforms, with glyphs."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("lfowaves_code.json")).read_text())
TABLE_BYTES = 7 * 32


def extents(firmware, blob_length: int | None = None) -> list[Extent]:
    out = [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, "LFO waves edit") for e in SPEC["edits"]]
    length = len(SPEC["blob"]) // 2 if blob_length is None else blob_length
    out.append(Extent(SECTION, SPEC["area_va"] - BASE, length, "appended data area"))
    return out


def default_tables() -> list[bytes]:
    blob = bytes.fromhex(SPEC["blob"])
    return [blob[t["offset"]:t["offset"] + TABLE_BYTES] for t in SPEC["tables"]]


def apply(firmware, tables: list[bytes | None] | None = None) -> Result:
    """`tables`: three entries, each 224 bytes (7 x 32 signed) or None for ours."""
    tables = list(tables or [None, None, None])
    if len(tables) != 3:
        raise ModError("give three tables (None keeps ours)")
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    content = bytearray(section.unpack())
    if len(content) != SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(content):,} B, not {SPEC['stock_length']:,}: either not "
                       "Digitone II 1.11, or another mod has already appended data")
    for e in SPEC["edits"]:
        at = e["va"] - BASE
        have = bytes(content[at:at + len(e["stock"]) // 2]).hex()
        if have != e["stock"]:
            raise ModError(f"0x{e['va']:08x} is not stock ({have[:24]}...); "
                           "this mod is for unmodified Digitone II 1.11")

    blob = bytearray.fromhex(SPEC["blob"])
    for f in SPEC["fills"]:
        src = f["from_va"] - BASE
        blob[f["offset"]:f["offset"] + 4 * f["count"]] = content[src:src + 4 * f["count"]]
    custom = []
    for t, table in zip(SPEC["tables"], tables):
        if table is None:
            continue
        if len(table) != TABLE_BYTES:
            raise ModError(f"{t['name']}: a table is {TABLE_BYTES} bytes, got {len(table)}")
        blob[t["offset"]:t["offset"] + TABLE_BYTES] = table
        custom.append(t["name"])

    for e in SPEC["edits"]:
        at = e["va"] - BASE
        new = bytes.fromhex(e["new"])
        content[at:at + len(new)] = new
    content += blob + bytes(-len(blob) % 4)

    notes = [f"waves after RAND: {' '.join(SPEC['waves'])}",
             "wavetables: " + ", ".join(f"{t['name']} {'custom' if t['name'] in custom else 'ours'}"
                                        for t in SPEC["tables"]),
             f"appended data {len(blob):,} B; MAIN OS {len(content):,} B"]
    return Result({SECTION: bytes(content)}, extents(firmware, len(blob)), notes)

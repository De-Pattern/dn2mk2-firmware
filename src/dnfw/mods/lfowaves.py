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
3. the blob goes into the platform's appended area (`dnfw.mods.platform`) as a
   `CODE` chunk loaded at `0x46780000`, where it was assembled to run.

The build this was packaged from installed its own start-up hook and a 46-byte
stub at `0x402cf52c` that copied the blob to `0x46780000` and did nothing else
(`scripts/build_lfo_waves.py`, `boot_source`). The platform loader makes the
same copy, so those edits are left out (`STUB`) and the cave stays free; the
rest of the edits, and the blob, are the passed build's.

The `getShortName` hook (SPH's label) displaces the accessor's first two
instructions, `move.l 8(%sp),%d0 ; cmpi.l #321,%d0`, and replays them unchanged
before jumping back. It records them (`platform.displace`), so a mod that
widens that bound -- lfo4, to 331 -- edits the replayed copy.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform

ID = "lfowaves"
NAME = "New LFO waveforms"
SUMMARY = "STEP, PULS, NOIS, TRAP and three swappable wavetables as LFO waveforms, with glyphs."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("lfowaves_code.json")).read_text())
TABLE_BYTES = 7 * 32
RUNTIME_VA = SPEC["runtime_va"]
# The packaged build's own copy stub, replaced by the platform loader.
STUB = (0x402CF52C, 46)
NOISE_RAM, NOISE_BYTES = 0x46740000, 1024 * 8     # NOIS per-LFO state
TILE_RAM, TILE_BYTES = 0x46750000, 7 * 112         # a rendered glyph tile per new wave
# Bytes in the blob that only look like RAM above BSS (`dnfw.mods.ramcheck`):
# 0x467805f4 is `not.l %d0 ; subi.l #0x40000000,%d0` (46 80 04 80 40 00 ...).
NOT_RAM = (0x467805F4,)


def _own(e: dict) -> bool:
    lo, hi = e["va"] - BASE, e["va"] - BASE + len(e["new"]) // 2
    stub_lo = STUB[0] - BASE
    return not (any(x.start < hi and lo < x.end for x in platform.extents())
                or (stub_lo < hi and lo < stub_lo + STUB[1]))


EDITS = [e for e in SPEC["edits"] if _own(e)]

# getShortName's first two instructions, replayed by the hook and then a jump back.
SHORT_NAME, SHORT_NAME_DISPLACED = 0x400372DA, 10


def _displaced_copy(blob: bytes) -> int:
    """Where in RAM the hook replays the displaced instructions."""
    stock = bytes.fromhex(next(e["stock"] for e in SPEC["edits"] if e["va"] == SHORT_NAME))
    replay = stock[:SHORT_NAME_DISPLACED] + bytes.fromhex("4ef9") + (SHORT_NAME + SHORT_NAME_DISPLACED).to_bytes(4, "big")
    found = blob.find(replay)
    if found < 0 or blob.find(replay, found + 1) >= 0:
        raise ModError("lfowaves_code.json is damaged: getShortName's replay is not found once")
    return RUNTIME_VA + found


def extents(firmware, blob_length: int | None = None) -> list[Extent]:
    out = [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, "LFO waves edit",
                  displaced=e["va"] == SHORT_NAME) for e in EDITS]
    length = len(SPEC["blob"]) // 2 if blob_length is None else blob_length
    return out + platform.extents(16 + length)


def ram(blob_length: int | None = None) -> list[Extent]:
    length = len(SPEC["blob"]) // 2 if blob_length is None else blob_length
    return [Extent(RAM, RUNTIME_VA, length, "the waves' code, names, tables and wavetables"),
            Extent(RAM, NOISE_RAM, NOISE_BYTES, "NOIS per-LFO state"),
            Extent(RAM, TILE_RAM, TILE_BYTES, "the rendered glyph tiles")]


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
    base, others = platform.split(section.unpack())
    content = bytearray(base)
    for e in EDITS:
        at = e["va"] - BASE
        have = bytes(content[at:at + len(e["stock"]) // 2]).hex()
        if have != e["stock"]:
            hint = ("; lfo4 widens this bound: apply lfowaves first, then lfo4"
                    if e["va"] == SHORT_NAME else "; this mod is for unmodified Digitone II 1.11")
            raise ModError(f"0x{e['va']:08x} is not stock ({have[:24]}...){hint}")

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

    for e in EDITS:
        at = e["va"] - BASE
        new = bytes.fromhex(e["new"])
        content[at:at + len(new)] = new
    chunk = platform.area.CodeChunk(RUNTIME_VA, bytes(blob)).pack()
    content = platform.join(bytes(content), others + [
        (platform.area.CODE, chunk),
        platform.displace(SHORT_NAME, SHORT_NAME_DISPLACED, _displaced_copy(bytes(blob)))])

    notes = [f"waves after RAND: {' '.join(SPEC['waves'])}",
             "wavetables: " + ", ".join(f"{t['name']} {'custom' if t['name'] in custom else 'ours'}"
                                        for t in SPEC["tables"]),
             f"a {len(blob):,} B CODE chunk at 0x{RUNTIME_VA:08x} in the platform's area; "
             f"MAIN OS {len(content):,} B"]
    return Result({SECTION: bytes(content)}, extents(firmware, len(blob)), notes)

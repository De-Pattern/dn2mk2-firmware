"""Waverider: a sixth machine, a wavetable oscillator with two baked tables.

**Not yet on the instrument.** Milestone 5 of `docs/waverider-feasibility.md`:
the first build with modified SHARC code. Everything here passed in the
emulators (ColdFire: digikit's; DSP: digikit's SHARC runner), nothing on silicon.

## What it is

MACHINE SEL offers **WAVERIDER** after SWARMER. A Waverider track is machine
type 5 in the sound and in the frame, and WaveTone everywhere else on the
ColdFire: its SYN pages are WaveTone's, and two of their knobs drive it --

- `WAV1` is the **frame position** (POS) across the table;
- `TBL1` is the **table** (SLOT): 0 a saw that darkens to a sine, 1 the
  overtone series, partial 1 to 16.

Pitch follows the trig note. The rest of WaveTone's page (osc 2, noise, PD,
the levels) is shown and saved but not rendered.

## How it applies

Two sections, both from committed data:

- **MAIN OS (3):** `waverider_code.json`, written by
  `scripts/gen_waverider_code.py` from `dnfw.waverider.coldfire` (the list,
  the names, the permission rows, the WaveTone clone). Every edit's stock
  bytes are checked first. Four clean in-image caves, nothing appended.
- **The DSP boot stream (7):** `dnfw.waverider.dsp.section7`, from the
  committed SHARC objects. It refuses a section 7 that is not stock.

## A sound or project saved with a Waverider track

Saved as machine type 5 by the stock SAVE. This build keeps 5 on LOAD; stock
firmware (and any build without this mod) loads it as **FM Tone**, the stock
LOAD bound's own fallback (`0x400dd286`), with its parameters as they were.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result
from ..waverider import dsp

ID = "waverider"
NAME = "Waverider, a sixth machine"
SUMMARY = ("A wavetable machine, WAVERIDER in MACHINE SEL: WAV1 sweeps the frame, "
           "TBL1 picks one of two baked tables. First build with modified DSP code.")
DEVICE = 0x15                      # Digitone II
MAIN_OS, DSP_STREAM = 3, 7
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("waverider_code.json")).read_text())


def extents(firmware=None) -> list[Extent]:
    out = [Extent(MAIN_OS, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]
    size = None
    if firmware is not None:
        section = firmware.container.find(DSP_STREAM)
        content = section.unpack() if section is not None else None
        size = len(content) if content is not None else None
    # The boot stream is rebuilt as a whole (blocks inserted before its final
    # block), so the whole of it is declared: nothing else may write it too.
    out.append(Extent(DSP_STREAM, 0, size or 836_956,
                      "the DSP boot stream, rebuilt: Waverider's code, state and two "
                      "tables in L1 block 2, the entry jump, the machine lookup"))
    return out


def _main_os(original: bytes) -> bytes:
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        at = g["va"] - BASE
        if original[at:at + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} ({g['what']}) is not stock; this mod is "
                           "for unmodified Digitone II 1.11")
    content = bytearray(original)
    for e in SPEC["edits"]:
        old, new = bytes.fromhex(e["stock"]), bytes.fromhex(e["new"])
        at = e["va"] - BASE
        if bytes(content[at:at + len(old)]) != old:
            raise ModError(f"0x{e['va']:08x} ({e['what']}) is not stock; this mod is for "
                           "unmodified Digitone II 1.11, or another mod already wrote there")
        content[at:at + len(new)] = new
    return bytes(content)


def apply(firmware) -> Result:
    cf = firmware.container.find(MAIN_OS)
    ds = firmware.container.find(DSP_STREAM)
    if cf is None or ds is None:
        raise ModError("image has no MAIN OS or no DSP boot stream")
    main_os, stream = cf.unpack(), ds.unpack()
    if main_os is None or stream is None:
        raise ModError("MAIN OS or the DSP boot stream did not depack")
    try:
        section7 = dsp.section7(stream)
    except dsp.DspError as exc:
        raise ModError(f"the DSP boot stream: {exc}") from exc
    return Result(payloads={MAIN_OS: _main_os(main_os), DSP_STREAM: section7},
                  extents=extents(firmware),
                  notes=[f"MACHINE SEL offers {SPEC['names'][0].upper()} after SWARMER "
                         f"(type {SPEC['new_type']}; WaveTone's pages)",
                         f"{len(SPEC['edits'])} edits in section 3, nothing appended; "
                         f"section 7 {len(stream):,} -> {len(section7):,} B"])

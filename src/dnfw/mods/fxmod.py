"""FX modulation: an LFO can be aimed at a Chorus, Delay or Reverb parameter.

Stock Digitone II firmware offers an LFO a hundred destinations and every one of
them is inside the voice. The global effects are not among them: the `DEST` list
never enumerates them, the evaluator's bound stops at 100, and the code that
turns a list entry into a stored `DEST` value has no way to spell one. This mod
opens all three halves at once, and **24 destinations appear in the `DEST` list
and modulate**.

**Passed on the instrument on 2026-09-23** as `fxbrowser2`, in the owner's
words: *"works :) I can modulate with the LFOs the parameters."*
`docs/fx-master-modulation.md` carries the whole history, §12 for the engine
half, §15 and §18 for the browser half, and §23 for the group-name fix this mod
also carries — stock firmware names group 16 `ERR`, because Elektron's own
group -> short-name table holds the out-of-range fallback in Chorus's slot.

## What it changes

| # | what | why |
|---|---|---|
| 1 | the evaluator's `DEST` bound, 100 -> 127 | so a code above 100 is evaluated at all |
| 2 | a hook into a code cave | codes 101..127 read the global FX mirror block |
| 3 | a hook into the same cave | slots 101..124 resolve through the FX set's own table |
| 4 | the enumeration walk, 0..100 -> 0..124 | so the `DEST` list offers them |
| 5 | seven `jsr` targets | entry -> code, `+76` for an FX record |
| 6 | ten records' `+44` | Chorus ships closed under every `want` mask |
| 7 | one longword | group 16's short name, `ERR` -> `CHR` |

The cave is 128 bytes inside a free run this project has flashed successfully
before; nothing is appended and no section changes length, so this mod does not
compete for the appended area or the startup hook.

## What it does not do

**Master stays out.** Its slots need codes 136..145 and the firmware widens a
`DEST` byte with `mvs.b`, which makes anything above 127 negative. That is a
different edit and it is not in here.

**Sixteen tracks' LFOs can all aim at the same global cell, and they stack** —
every evaluator reads the cell and adds to it before the clamp. That is not a
fault, it is what "global" means, and it only becomes visible once the list can
offer these codes.

## How it applies

The code is assembled ahead of time (`scripts/gen_fxmod_code.py` ->
`fxmod_code.json`) from `scripts/build_fxbrowser.compose`, so this applies
exactly the bytes that were gated and flashed:

1. all 26 guards -- whole instructions around each edit, the enumeration loop,
   the sort comparator, and the three group-name slots with the three records
   whose short names they share -- and every edit's own stock bytes are checked;
   an image that differs anywhere is refused;
2. the edits are written.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result

ID = "fxmod"
NAME = "LFO modulation of the FX"
SUMMARY = ("An LFO can be aimed at a Chorus, Delay or Reverb parameter: "
           "24 new destinations in the DEST list.")
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads(pathlib.Path(__file__).with_name("fxmod_code.json").read_text())


def destinations() -> list[tuple[str, list[str]]]:
    """-> [(group, [short + name, ...])] — what the `DEST` list gains."""
    return [(d["group"], d["parameters"]) for d in SPEC["destinations"]]


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"])
            for e in SPEC["edits"]]


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

    count = sum(len(g["parameters"]) for g in SPEC["destinations"])
    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=[f"{count} FX destinations appear in the LFO DEST list",
                         "Chorus, Delay and Reverb parameters follow the LFO",
                         "the Chorus group reads CHR, not ERR",
                         f"{len(SPEC['edits'])} edits in section 3, nothing appended"])

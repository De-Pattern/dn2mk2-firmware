"""`fxbrowser`, with the four `entry -> slot << 8` sites its predecessor missed.

    python scripts/build_fxbrowser2.py

`fxbrowser` was flashed on 2026-09-23 and half-worked: the 24 FX destinations
are in the list — `emu_destlist.py` measured +24 and -0 for all three `want`
masks — but stepping onto the first of them sends the cursor back to the top of
the list, and the 22 stock entries that used to follow `OVR Routing` became
unreachable with them. `docs/fx-master-modulation.md` §16, §17.

## The root cause, and it is a counting error in §10

§10 asked how many sites convert a list entry into a stored `DEST` value, and
answered **two** by scanning for `jsr 0x400dbcc4` with an **adjacent**
`lsl.l #8`. That window was too narrow. Scanning 64 bytes forward instead finds
**six**:

| site | the shift | distance | in `fxbrowser`? |
|---|---|---|---|
| `0x4003985e` | `lsl.l #8,%d3` at `0x40039868` | 10 B | patched |
| **`0x40039a72`** | `lsl.l #8,%d2` at `0x40039a84` | **18 B** | **missed** |
| **`0x40039c94`** | `lsl.l #8,%d2` at `0x40039ca6` | **18 B** | **missed** |
| **`0x40039e92`** | `lsl.l #8,%d2` at `0x40039ea4` | **18 B** | **missed** |
| **`0x40063df2`** | `lsl.l #8,%d0` at `0x40063e06` | **20 B** | **missed** |
| `0x400c2a36` | `lsl.l #8,%d0` at `0x400c2a3e` | 8 B | patched |

The four missed ones all have the same shape — `jsr`, `movel %d0,%d2`, a call
to `0x401880cc` in between, then the shift — so an adjacent-pair scan walks
straight past them. Two instructions of separation was the whole difference
between a working build and a half-working one.

## The criterion, stated so it is checkable

**A site that shifts the converter's result left by 8 is producing a `DEST`
*value*, and a value must carry the route A code.** A site that does not shift
is using `record+12` as an index — into a page, a table or a slot space — and
must keep the raw number. So: patch exactly the six shifted sites, leave the
other twenty-eight alone. That rule is decidable by scanning, which is what the
table above is, and it replaces §10's "count the pairs" with something that
cannot miss a site for being spelled differently.

`scripts/scan_dest_values.py` is that scan, so the next person does not have to
trust this docstring.

## Why the missed sites produce exactly the reported symptom

`0x40039a72` sits inside `0x40039904`, which is `ParameterSet`'s vtable `+0x24`
and is unambiguously on the `DEST` path: it fetches the record's `+44` through
`0x400dc30e`, `btst`s bits 18/17/16 to pick the `want` mask, shifts the current
value **right** by 8 to recover the code, and resolves it through `+0x50`. It is
the inverse of the very conversion this work added — and it was still handing
back `record+12` with no `+76`.

So stepping onto Chorus `Depth` stored **25** where **101** was meant. The
redraw read 25 back, `+0x50` resolved it to a sound entry that is not in the
list, the search failed, and the cursor reset to the first element: "the list
goes to the very top again", and nothing beyond that point is ever reachable.

## What this build changes

`fxbrowser`'s eight edits, unchanged, plus **four more four-byte `jsr` target
rewrites** onto the same cave helper. Nothing new is added to the cave, no new
bytes are displaced, and `0x400dbcc4` itself is still untouched for the 28
callers that use it as an index.

## What still cannot be gated here

The browser does not run in the emulator — no panel, no page view, no encoder —
so *"the cursor now steps onto Chorus Depth and stays there"* remains the
instrument's question. What is gated is that the four new sites convert exactly
as the two already-patched ones do, and that nothing below code 101 moved.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_fxbrowser as one                                 # noqa: E402

# The four sites `fxbrowser` missed, with the distance to their shift. They are
# appended to its three rather than replacing them, so this build is a strict
# superset and the diff against `fxbrowser` is four longwords.
MISSED = (
    (0x40039A72, "ParameterSet +0x24's DEST path -- `lsl.l #8,%d2` 18 B later"),
    (0x40039C94, "the sibling on the other set -- `lsl.l #8,%d2` 18 B later"),
    (0x40039E92, "and its setter -- `lsl.l #8,%d2` 18 B later"),
    (0x40063DF2, "the sixth -- `lsl.l #8,%d0` 20 B later"),
)

if __name__ == "__main__":
    anchor = one.ANCHORS[3_192_192]
    anchor["convert"] = anchor["convert"] + MISSED
    one.OUT = pathlib.Path("00_Resources/02_Builds/fxbrowser2_DN2_1.11.syx")
    one.SECTION_OUT = pathlib.Path("out/fxbrowser2/section_3_MAIN_OS.bin")
    raise SystemExit(one.main())

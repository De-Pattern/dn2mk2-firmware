"""LFO4 step 4a: parameter ids 101-108 reach the extension table.

    python scripts/build_lfo4_slots.py

This is `scripts/build_lfo4_bridge.py` plus one site. The bridge already gives
a fourth LFO that each track owns, saves and loads; what it has no way to do is
**take a value from the front panel**, because nothing in the firmware writes
to an LFO4 parameter id.

`docs/lfo4-build-plan.md` §"Step 4" found the one routine that writes a value,
by watching the live sound's array while the panel was driven:
`values[d2] = d3` at 0x40037be8, guarded six bytes earlier by `slot > 100 ->
skip the write entirely`. Those six bytes are the width of a `jmp <abs.l>`
exactly, and above 100 stock firmware does nothing at all -- so the divert
cannot corrupt a value the firmware owns, whatever it gets wrong.

`csrc/lfo4/hooks.S`'s `lfo4_set_stub` takes the decision over: 0-100 go on to
the firmware's own write, 101-108 come to `lfo4_on_set`, and anything else is
skipped as before.

The page that *shows* those ids is step 4b. This build is the half that can be
verified without one: a harness drives the setter directly and reads the table.
"""

from __future__ import annotations

import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import build_lfo4_bridge as bridge                         # noqa: E402

BASE = 0x40000400
OUT = ROOT / "out/lfo4-slots"
SYX = ROOT / "00_Resources/02_Builds/lfo4-slots_DN2_1.11.syx"

SOURCES = bridge.SOURCES[:-1] + ("setter.c", "hooks.S")
ENTRIES = bridge.ENTRIES + ["lfo4_on_set", "lfo4_set_stub"]

# The bound, as stock 1.11 holds it. Checked rather than trusted: this is the
# one site in the project that replaces instructions it does not replay, so if
# the image ever differs the patch must not be applied at all.
BOUND = 0x40037BD0
STOCK = bytes.fromhex("7064b0826d72")      # moveq #100,d0 ; cmp.l d2,d0 ; blt.s +0x72


def divert(content, code):
    """Replace the slot bound with a jump to the stub that decides instead."""
    at = BOUND - BASE
    here = bytes(content[at:at + len(STOCK)])
    if here != STOCK:
        raise SystemExit(f"the slot bound at {BOUND:#010x} is {here.hex()}, not {STOCK.hex()}")
    content[at:at + len(STOCK)] = b"\x4e\xf9" + struct.pack(">I", code["lfo4_set_stub"])
    print(f"part 3b -- the slot bound\n"
          f"  {BOUND:#010x}  slot > 100 -> lfo4_set_stub {code['lfo4_set_stub']:#010x}")


if __name__ == "__main__":
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES,
                                 out=OUT, syx=SYX, extra=[divert]))

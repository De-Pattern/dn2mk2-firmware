"""LFO4: the per-LFO hard-coding in the UI, extended from three to four.

    python scripts/build_lfo4_ui.py

`lfo4-value` draws a fourth MOD page with real names, real widgets, real
values and the waveform preview. Two things on it are still LFO3's or nobody's,
and the instrument reported both:

> "random wave have phase instead of slew in LFO4"
> "browsing destinations doesn't open the destination UI ... 49 reads err"

Both are the same shape -- a parameter's entry number compared against three
literals ten apart -- and `scripts/scan_lfo_triples.py` is what made them
findable rather than stumbled on. Seven windows in the whole image hold
`78/88/98`; six are code; **one of those six runs.**

| site | stock | this build |
|---|---|---|
| `0x4010db18` | `SPH` is 81, 91 or 101 | and 327 |
| `0x4010dbc6/cc` | the page index clamps to 2 | to 3 |
| `0x4010dbce` | three `SLEW` entries `{80, 90, 100}` | four, `{..., 326}` |
| `0x40039aba` | `DEST` is 78, 88 or 98 | and 324 |
| `0x40039ad4` | the mask is `0x1e00`, `0x0e00` or `0x0600` | and `0x0200` |

**The `DEST` half may not be cosmetic.** With no browser the value is dialled
raw, past every slot that has no parameter -- which is what `49 reads err` is --
so a destination that was set on the instrument may never have been a
destination at all. "LFO4 doesn't modulate anything, no matter the DEP or
destination" was reported from a page that could not select one.
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
import build_lfo4_page as page                             # noqa: E402
import build_lfo4_slots as slots                           # noqa: E402
import build_lfo4_table as table                           # noqa: E402
import build_lfo4_value as value                           # noqa: E402

BASE = 0x40000400
OUT = ROOT / "out/lfo4-ui"
SYX = ROOT / "00_Resources/02_Builds/lfo4-ui_DN2_1.11.syx"

SOURCES = value.SOURCES + ("slew.c", "slewhooks.S", "desthooks.S")
ENTRIES = value.ENTRIES + ["lfo4_slew_stub", "lfo4_slew_entries",
                           "lfo4_dest_stub", "lfo4_dest_mask"]

NOP = b"\x4e\x71"


def _at(content, va, stock, what):
    """-> the offset of `va`, once the bytes there are the ones expected.

    Asserted, never assumed: every site here replaces instructions it does
    **not** replay, so an image that is not the one these were read from must
    be refused rather than patched.
    """
    at = va - BASE
    here = bytes(content[at:at + len(stock)])
    if here != stock:
        raise SystemExit(f"{what} at {va:#010x} is {here.hex()}, not {stock.hex()}")
    return at


def _jump(content, va, stock, target, what):
    """Replace `stock` at `va` with a jump to `target`, padded with `nop`."""
    at = _at(content, va, stock, what)
    jump = b"\x4e\xf9" + struct.pack(">I", target)
    if len(jump) > len(stock) or (len(stock) - len(jump)) % 2:
        raise SystemExit(f"{what}: {len(stock)} bytes cannot hold a jump")
    content[at:at + len(stock)] = jump + NOP * ((len(stock) - len(jump)) // 2)


# --- `RND` shows `SLEW` ------------------------------------------------------
# moveq #81,%d0 ; cmpl %d2,%d0 ; beq ; moveq #91,%d1 ; cmpl %d2,%d1 ; beq ;
# moveb #101,%d0 ; cmpl %d2,%d0 ; bne  -- 22 bytes, both exits inside them.
SLEW_GATE = 0x4010DB18
SLEW_GATE_STOCK = bytes.fromhex("7051b0826710725bb282670a103c0065b0826600 00ae".replace(" ", ""))
SLEW_CLAMP = 0x4010DBC6          # moveq #2,%d1 -- the ceiling the index is tested against
SLEW_CLAMPED = 0x4010DBCC        # moveq #2,%d0 -- what a larger index becomes
SLEW_TABLE = 0x4010DBCE          # lea 0x40205454,%a0
SLEW_TABLE_STOCK = bytes.fromhex("41f940205454")
SLEW_ENTRIES = 0x40205454        # {80, 90, 100}, with a mangled RTTI string behind it


def slew(content, code):
    """Accept LFO4's `SPH`, and give the substitution a fourth row to find."""
    print("part 10 -- the SLEW substitution")
    _jump(content, SLEW_GATE, SLEW_GATE_STOCK, code["lfo4_slew_stub"], "the SLEW gate")
    print(f"  {SLEW_GATE:#010x}  entry 81/91/101 -- and 327 -> lfo4_slew_stub "
          f"{code['lfo4_slew_stub']:#010x}")

    for va, name in ((SLEW_CLAMP, "the ceiling"), (SLEW_CLAMPED, "the clamp")):
        at = va - BASE
        here = bytes(content[at:at + 2])
        if here[0] not in (0x70, 0x72) or here[1] != 2:
            raise SystemExit(f"{name} at {va:#010x} is {here.hex()}, not a `moveq #2`")
        content[at + 1] = 3
        print(f"  {va:#010x}  {name}: moveq #2 -> #3")

    # And the table itself, checked against the one it replaces: the first
    # three longwords must be the firmware's own, or LFO1, LFO2 and LFO3 would
    # stop reading what they have always read.
    theirs = bytes(content[SLEW_ENTRIES - BASE:SLEW_ENTRIES - BASE + 12])
    start = code["lfo4_slew_entries"] - bridge.CODE_VA
    mine = code.image[start:start + 16]
    if mine[:12] != theirs:
        raise SystemExit(f"the four-entry SLEW table starts {mine[:12].hex()}, "
                         f"the firmware's three are {theirs.hex()}")
    _jump(content, SLEW_TABLE, SLEW_TABLE_STOCK,
          code["lfo4_slew_entries"], "the SLEW table")
    # `lea imm,%a0` is not a jump: put the instruction back with our address.
    at = SLEW_TABLE - BASE
    content[at:at + 6] = b"\x41\xf9" + struct.pack(">I", code["lfo4_slew_entries"])
    print(f"  {SLEW_TABLE:#010x}  lea {SLEW_ENTRIES:#010x} -> "
          f"{code['lfo4_slew_entries']:#010x}, {struct.unpack('>4I', mine)}")


# --- the `DEST` browser ------------------------------------------------------
# moveb #98,%d1 ; cmpl %d0,%d1 ; bne -- the last of three compares woven
# through the prologue, and the only eight contiguous bytes holding both exits.
DEST_GATE = 0x40039ABA
DEST_GATE_STOCK = bytes.fromhex("123c0062b280664c")
DEST_MASK = 0x40039AD4
DEST_MASK_STOCK = bytes.fromhex(
    "203c00001e00"      # movel #0x1e00,%d0
    "08010012 6616"     # btst #18,%d1 ; bne
    "303c0e00"          # movew #0x0e00,%d0
    "08010011 660c"     # btst #17,%d1 ; bne
    "303c0600"          # movew #0x0600,%d0
    "08010010 6602"     # btst #16,%d1 ; bne
    "4280".replace(" ", ""))                                   # clrl %d0


def dest(content, code):
    """Let LFO4's `DEST` past the gate, and give the mask a fourth step."""
    print("part 11 -- the destination browser")
    _jump(content, DEST_GATE, DEST_GATE_STOCK, code["lfo4_dest_stub"], "the DEST gate")
    print(f"  {DEST_GATE:#010x}  entry 78/88/98 -- and 324 -> lfo4_dest_stub "
          f"{code['lfo4_dest_stub']:#010x}")
    _jump(content, DEST_MASK, DEST_MASK_STOCK, code["lfo4_dest_mask"], "the DEST mask")
    print(f"  {DEST_MASK:#010x}  mask 0x1e00/0x0e00/0x0600 -- and 0x0200 -> "
          f"lfo4_dest_mask {code['lfo4_dest_mask']:#010x}")


if __name__ == "__main__":
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        slew, dest],
                                 chunks=table.chunks))

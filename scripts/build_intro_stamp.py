"""A mod stamp on the start-up screen: `MOD` and a version, beside the logo.

`docs/ideas-backlog.md` §13, asked for by the owner on 2026-09-16: an instrument
running a modified image currently looks exactly like one running stock, and the
person who has to know the difference is whoever flashed it.

## How the intro works, which is what makes this small

Traced 2026-09-17 (`docs/display-path.md`, "The intro is a displacement map over
a static logo"). The start-up animation is one copy loop: every panel pixel
samples a **static source bitmap** at a coordinate from an animated offset table.
The logo lives in that source; the motion is data.

So the stamp is written **into the source bitmap**, not onto the panel. It is
then scattered and reassembled with the logo by the firmware's own effect, for
free — it arrives the way the logo arrives, which is the honest way to put a
mark beside someone else's logo: visibly separate, visibly part of the boot.

## The hook

The copy routine starts at `0x400d3886` on Digitone II 1.11 (`dnfw fn entry`
reports `0x400d3876`, which is a separate four-instruction routine ending in
`rts` at `0x400d3884` — checked by disassembly). Its first eight bytes are the
frame setup:

    0x400d3886  lea     %sp@(-60),%sp
    0x400d388a  moveml  %d2-%d7/%a2-%fp,%sp@

They become `jmp stamp`. The stub ORs a precomputed list of (offset, mask) pairs
into the source bitmap's pixel data, replays the two instructions, and jumps back
to `0x400d388e`. It runs every frame, so it does not matter when the logo is
drawn into the source or whether anything clears it: the OR is idempotent.

A `Bitmap` is `+4 width, +8 height, +12 stride, +16 data`, and pixel `(x, y)` is
bit `31 - (y & 31)` of the long at `data + 4 * (x * stride + (y >> 5))`. The
source is at `0x42c4567c`, so its data pointer is read at run time from
`0x42c4568c`; if it is still zero the stamp is skipped that frame.

## What must not happen

The stamp must not imply Elektron authorship and must not pretend to be a stock
version string. It says `MOD`, in a font the firmware does not use.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400

HOOK_VA = 0x400D3886
HOOK_STOCK = bytes.fromhex("4fefffc4" "48d77cfc")   # lea -60(sp),sp ; moveml
RESUME_VA = 0x400D388E
SOURCE_DATA_PTR = 0x42C4567C + 16

# Measured from the 400M snapshot with scripts/dump_bitmap.py.
SOURCE_W, SOURCE_H, SOURCE_STRIDE = 128, 64, 2

CAVE, CAVE_CAP = 0x402DFA1C, 896

# A 3 x 5 font. Deliberately not the firmware's own face.
FONT = {
    "M": ["101", "111", "111", "101", "101"],
    "O": ["111", "101", "101", "101", "111"],
    "D": ["110", "101", "101", "101", "110"],
    "V": ["101", "101", "101", "101", "010"],
    ".": ["000", "000", "000", "000", "010"],
    " ": ["000", "000", "000", "000", "000"],
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
}

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/intro-stamp_DN2_1.11.syx")


def render(text: str) -> list[tuple[int, int]]:
    """Lit (x, y) pixels for `text`, top-left at the origin, one column of gap."""
    out, cx = [], 0
    for ch in text.upper():
        glyph = FONT.get(ch)
        if glyph is None:
            raise SystemExit(f"no glyph for {ch!r}; the font has {''.join(sorted(FONT))}")
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    out.append((cx + gx, gy))
        cx += 4
    return out


def pairs(pixels: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """(byte offset into bitmap data, OR mask), merged per longword."""
    merged: dict[int, int] = {}
    for x, y in pixels:
        if not (0 <= x < SOURCE_W and 0 <= y < SOURCE_H):
            raise SystemExit(f"pixel ({x}, {y}) is off the {SOURCE_W} x {SOURCE_H} source")
        off = 4 * (x * SOURCE_STRIDE + (y >> 5))
        merged[off] = merged.get(off, 0) | (0x80000000 >> (y & 31))
    return sorted(merged.items())


def source(table_va: int) -> str:
    return f"""
    .text
stamp:
    move.l  {SOURCE_DATA_PTR:#010x},%d0     | the source bitmap's pixel data
    beq.s   2f                              | not built yet: skip this frame
    movea.l %d0,%a0
    lea     {table_va:#010x},%a1
1:  move.l  %a1@+,%d0                       | offset, or -1 to stop
    bmi.s   2f
    move.l  %a1@+,%d1                       | mask
    or.l    %d1,%a0@(0,%d0:l)
    bra.s   1b
2:  lea     %sp@(-60),%sp                   | the two displaced instructions
    moveml  %d2-%d7/%a2-%fp,%sp@
    jmp     {RESUME_VA:#010x}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text", default="MOD", help="what the stamp says (default MOD)")
    ap.add_argument("--x", type=int, required=True, help="left edge on the 128 x 64 source")
    ap.add_argument("--y", type=int, required=True, help="top edge on the 128 x 64 source")
    args = ap.parse_args()

    if not available():
        raise SystemExit("no m68k assembler found (WSL is fine)")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    block = content[CAVE - BASE:CAVE - BASE + CAVE_CAP]
    if any(block):
        raise SystemExit(f"cave at {CAVE:#010x} is not free")
    have = bytes(content[HOOK_VA - BASE:HOOK_VA - BASE + len(HOOK_STOCK)])
    if have != HOOK_STOCK:
        raise SystemExit(f"{HOOK_VA:#010x}: expected {HOOK_STOCK.hex()}, found {have.hex()}")

    lit = [(args.x + x, args.y + y) for x, y in render(args.text)]
    table = pairs(lit)
    print(f"part 1 -- {args.text!r} at ({args.x}, {args.y}): "
          f"{len(lit)} pixels in {len(table)} longwords")

    # Size the stub with a placeholder that is a real 32-bit address. Sizing it
    # with 0 let the assembler pick the short `lea 0.w` form, the stub came out
    # two bytes short, and the table was placed over the tail of the return jump
    # -- `jmp 0x400d388e` became `jmp 0x400d0000`. Caught by disassembling the
    # build. The length check makes the same mistake impossible to repeat.
    sized = assemble(source(CAVE + 0x100), base=CAVE)
    table_va = (CAVE + len(sized) + 3) & ~3
    code = assemble(source(table_va), base=CAVE)
    if len(code) != len(sized):
        raise SystemExit(f"stub changed size between passes: {len(sized)} -> {len(code)}")
    blob = b"".join(struct.pack(">II", off, mask) for off, mask in table)
    blob += struct.pack(">I", 0xFFFFFFFF)
    used = (table_va - CAVE) + len(blob)
    if used > CAVE_CAP:
        raise SystemExit(f"cave overflows: {used} > {CAVE_CAP}")
    content[CAVE - BASE:CAVE - BASE + len(code)] = code
    content[table_va - BASE:table_va - BASE + len(blob)] = blob
    print(f"part 2 -- stub {len(code)} B at {CAVE:#010x}, table {len(blob)} B at {table_va:#010x}")

    jump = b"\x4e\xf9" + struct.pack(">I", CAVE) + b"\x4e\x71"
    content[HOOK_VA - BASE:HOOK_VA - BASE + len(jump)] = jump
    print(f"part 3 -- {HOOK_VA:#010x}  {HOOK_STOCK.hex()} -> {jump.hex()}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"part 4 -- wrote {OUT} ({OUT.stat().st_size} bytes), {used}/{CAVE_CAP} cave bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

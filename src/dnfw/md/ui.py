"""The Machinedrum's screen graphics, read from the owner's MD OS 1.63 when the build is made.

The PERC page draws itself as the Machinedrum's main screen (docs/md.md, "The page"): its
knob, the knob's 128 pointer pictures, the "clip" that ties two parameters, its three
fonts, and which of each machine's eight parameters exist and which are tied. Those are
Elektron's, so they are never committed: `blob()` reads them from the OS image
(`dnfw.md.rom`, `MD_OS_BIN`) and the mod places the blob in RAM beside the page code
(`dnfw.mods.waverider`), where `csrc/waverider/md_page.c` reads it.

Read [E] by running the MD's own screen code in an m68k emulator (2026-10-23): the draw
of a parameter (0x228a24), of the eight (0x229dd2), of the machine line (0x22801c), the
kit box (0x227cbe) and the level bar (0x219316), with every blit and text call logged.

Formats in the OS:

- a bitmap is five longs: columns, rows, longs a column, data, mask. Column c's long k
  holds rows 32k.. with row 0 (the bottom) in bit 31. A blit clears the mask's pixels,
  then sets the data's (0x21124c).
- a font is five longs: default width, rows, a width a character (bytes, 0 = default),
  an offset a character (u16, negative = none), the data: one byte a column, the bottom
  row in bit 7 (0x211384).
- a machine's record (0x252092 + 4 id) holds, at +0x32, a nibble a parameter: bit 0
  the parameter exists, bit 1 a clip ties it to the next, bit 2 it is bipolar.

The blob (big-endian, BLOB_BYTES long) is laid out as the C side reads it:

    0      'MDUI', version (u16), 0 (u16)
    8      the knob: 11 columns of (data u16, mask u16), rows 0..12 in bits 0..12
    52     the clip: COLS columns of (data u16, mask u16)
    84     128 pointers: 7 columns of (data u8, mask u8), rows 0..6 in bits 0..6
    1876   3 fonts (SMALL, SYM, BIG): rows (u8), then 96 characters (32..127) of a
           width (u8) and 15 column bytes, the bottom row in bit 0
    6488   the machines, in dnfw.perc.machines.NAMES order: 8 nibbles (u32), the
           Machinedrum's short id ("TRX", "BD", u8 x 6)
"""

from __future__ import annotations

import struct

from . import rom

OS_VMA = 0x200000
KNOB, POINTERS, CLIP = 0x2599E0, 0x259B0C, 0x259AF8
FONTS = {"SMALL": 0x259954, "SYM": 0x25997C, "BIG": 0x259990}
RECORDS = 0x252092
NIBBLES = 0x32
KNOB_COLS, KNOB_ROWS, PTR_COLS, PTR_ROWS = 11, 13, 7, 7
CLIP_COLS = 8
FONT_STRIDE = 16
MAGIC, VERSION = b"MDUI", 1

O_KNOB = 8
O_CLIP = O_KNOB + 4 * KNOB_COLS
O_PTR = O_CLIP + 4 * CLIP_COLS
O_FONT = O_PTR + 128 * 2 * PTR_COLS
FONT_BYTES = 1 + 96 * FONT_STRIDE
O_MACH = O_FONT + 3 * FONT_BYTES
MACH_BYTES = 10


def _os() -> bytes:
    return rom.blocks()[0]


def _long(a: int) -> int:
    return struct.unpack_from(">I", _os(), a - OS_VMA)[0]


def _u16(a: int) -> int:
    return struct.unpack_from(">H", _os(), a - OS_VMA)[0]


def bitmap(addr: int) -> tuple[int, int, list[int], list[int]]:
    """-> (columns, rows, data, mask): a column's rows as an int, bit r = row r from the
    bottom."""
    cols, rows, stride, data, mask = (_long(addr + 4 * k) for k in range(5))
    if not (0 < cols <= 32 and 0 < rows <= 32 * stride and stride == 1):
        raise rom.RomError(f"bitmap at {addr:#x} is not one this build knows ({cols}x{rows}, {stride})")

    def col(base: int, c: int) -> int:
        w = _long(base + 4 * c)
        return sum(1 << r for r in range(rows) if w >> (31 - r) & 1)
    return cols, rows, [col(data, c) for c in range(cols)], [col(mask, c) for c in range(cols)]


def font(addr: int) -> tuple[int, dict[int, list[int]]]:
    """-> (rows, {character: its columns}), a column's bit r = row r from the bottom."""
    width, rows, widths, offsets, data = (_long(addr + 4 * k) for k in range(5))
    out = {}
    for ch in range(32, 128):
        off = _u16(offsets + 2 * ch)
        if off & 0x8000:
            continue
        w = _os()[widths - OS_VMA + ch] if widths else 0
        w = w or width
        cols = []
        for c in range(w):
            b = _os()[data - OS_VMA + off + c]
            cols.append(sum(1 << r for r in range(rows) if b >> (7 - r) & 1))
        out[ch] = cols
    return rows, out


def machines() -> dict[str, tuple[int, str, str]]:
    """{"TRX-BD": (nibbles, synth, machine)} for every machine record in the OS."""
    out = {}
    for m in range(128):
        p = _long(RECORDS + 4 * m)
        if not OS_VMA <= p < OS_VMA + len(_os()) - 0x40:
            continue
        o = p - OS_VMA
        rec = _os()[o:o + 0x40]
        synth, mach = rec[5:8].decode("latin-1"), rec[8:10].decode("latin-1")
        if not (synth.isalnum() and mach.isalnum()):
            continue
        out.setdefault(f"{synth}-{mach}", (struct.unpack_from(">I", rec, NIBBLES)[0], synth, mach))
    return out


def blob() -> bytes:
    """The blob md_page.c reads (the layout above)."""
    from ..perc import machines as PM
    out = bytearray(MAGIC + struct.pack(">HH", VERSION, 0))
    cols, rows, data, mask = bitmap(KNOB)
    if (cols, rows) != (KNOB_COLS, KNOB_ROWS):
        raise rom.RomError(f"the knob is {cols}x{rows}, not {KNOB_COLS}x{KNOB_ROWS}")
    for d, m in zip(data, mask):
        out += struct.pack(">HH", d, m)
    cols, rows, data, mask = bitmap(CLIP)
    if cols > CLIP_COLS or rows > 16:
        raise rom.RomError(f"the clip is {cols}x{rows}")
    for c in range(CLIP_COLS):
        out += struct.pack(">HH", data[c] if c < cols else 0, mask[c] if c < cols else 0)
    for v in range(128):
        cols, rows, data, mask = bitmap(POINTERS + 20 * v)
        if (cols, rows) != (PTR_COLS, PTR_ROWS):
            raise rom.RomError(f"pointer {v} is {cols}x{rows}")
        for d, m in zip(data, mask):
            out += struct.pack(">BB", d, m)
    for name in ("SMALL", "SYM", "BIG"):
        rows, glyphs = font(FONTS[name])
        if rows > 8:
            raise rom.RomError(f"font {name} has {rows} rows")
        out.append(rows)
        for ch in range(32, 128):
            g = glyphs.get(ch, [])[:FONT_STRIDE - 1]
            out += bytes([len(g)]) + bytes(g) + bytes(FONT_STRIDE - 1 - len(g))
    table = machines()
    for name in PM.NAMES:
        nib, synth, mach = table[name]
        out += struct.pack(">I", nib) + (synth + mach).encode().ljust(6, b"\0")[:6]
    assert len(out) == O_MACH + MACH_BYTES * len(PM.NAMES), len(out)
    return bytes(out)


def blob_bytes() -> int:
    from ..perc import machines as PM
    return O_MACH + MACH_BYTES * PM.N


def c_header() -> str:
    """The blob's offsets for md_page.c (no Elektron data: where things are, not what)."""
    return (f"#define MDUI_KNOB {O_KNOB}\n#define MDUI_CLIP {O_CLIP}\n#define MDUI_PTR {O_PTR}\n"
            f"#define MDUI_FONT {O_FONT}\n#define MDUI_FONT_BYTES {FONT_BYTES}\n"
            f"#define MDUI_FONT_STRIDE {FONT_STRIDE}\n#define MDUI_MACH {O_MACH}\n"
            f"#define MDUI_MACH_BYTES {MACH_BYTES}\n#define MDUI_KNOB_COLS {KNOB_COLS}\n"
            f"#define MDUI_CLIP_COLS {CLIP_COLS}\n#define MDUI_PTR_COLS {PTR_COLS}\n"
            f"#define MDUI_VERSION {VERSION}\n")

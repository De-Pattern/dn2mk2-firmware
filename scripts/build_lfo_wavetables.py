"""Three wavetable LFO waveforms -- WTB1 basic shapes, WTB2 harmonics, WTB3 vowels.

    python scripts/build_lfo_wavetables.py

Supersedes `build_lfo_wavetable.py`'s single trapezoid. The owner, 2026-09-17:
*"a wavetable option should be richer in the transition between waves"* -- and
the trapezoid moves to the waveshapes build as TRAP.

## What SPH does

**SPH is the position in the table** (label `POS`). Each table holds 7 key frames
of 32 samples (`scripts/wavetables.py`); the generator blends the two frames
either side of the position and the two samples either side of the phase, so a
sweep of POS morphs smoothly from the first frame to the last.

```
pos    = min(SPH * 49, 6 * 1024)          frame 0..6 in 10-bit fixed point
f, ff  = pos >> 10, pos & 1023            (f = 6 folds to f = 5, ff = 1024)
s, sf  = phase >> 27, (phase >> 17) & 1023
row(f) = T[f][s] * 1024 + (T[f][s+1] - T[f][s]) * sf
out    = (row(f) * 1024 + (row(f+1) - row(f)) * ff) << 4
```

`|out|` peaks at 127 * 2^20 * 16, just inside 2^31. `scripts/wavetables.py`
carries the same arithmetic in Python (`reference`), and
`scripts/check_lfo_wavetables.py` runs the assembled bytes against it.

Everything else -- names, clamps, formatters, the [MOD] glyph rendered from the
generator, the renamed SPH -- is the shared machinery of the single-table build.
"""

from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

import lfo_wave_glyph as glyph
import lfo_wave_ui as ui
import wavetables as wt

MAIN_OS = 3
BASE = 0x40000400

CAVE_CODE, CAVE_CODE_CAP = 0x402CF52C, 896
CAVE_DATA, CAVE_DATA_CAP = 0x402D0664, 896

STOCK_NAMES = 0x401D3574
STOCK_TABLES = (0x4020B2EC, 0x4020B308, 0x4020B324, 0x4020B340)
STOCK_ENTRIES = 7
ENTRIES = STOCK_ENTRIES + len(wt.TABLES)

REPOINTS = {
    0x4020B2EC: ((0x401374DE, b"\x41\xf9"), (0x401378E2, b"\x41\xf9")),
    0x4020B308: ((0x40137514, b"\x43\xf9"), (0x40137916, b"\x43\xf9")),
    0x4020B324: ((0x40137508, b"\x41\xf9"), (0x4013790C, b"\x43\xf9")),
    0x4020B340: ((0x401375EE, b"\x43\xf9"),),
}
HOOKS = (
    (0x401379FA, b"\x41\xf9\x40\x20\xb3\x40", "a_call"),
    (0x4013760C, b"\x2f\x41\x00\x30\x4e\x91", "b_call"),
    (0x4013788E, b"\x75\x6c\x00\x4e\x9e\x80", "no_phase"),
    (ui.SHORT_FMT, ui.FMT_ENTRY_STOCK, "fmt_short"),
    (ui.LONG_FMT, ui.FMT_ENTRY_STOCK, "fmt_long"),
)
GENERATORS = ("wt1", "wt2", "wt3")
LABELS = GENERATORS + ("a_call", "b_call", "no_phase") + ui.LABELS + glyph.LABELS
SPH_LABELS = ["POS"] * len(wt.TABLES)

WAVE_MAX_FIELDS = (0x401F9224, 0x401F947C, 0x401F96D4)
STOCK_WAVE_MAX = 6

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo-wavetables_DN2_1.11.syx")


def source(fn_table: int, tables: list[int], short_names: int, long_names: int,
           glyph_sets: int, label_table: int) -> str:
    return f"""
    .text

""" + wt.generator_source(tables) + f"""
| ---- the two call sites carry SPH in %d1 -------------------------------------
a_call:
    lea     {fn_table:#010x},%a0
    mvs.b   %a4@(78),%d1
    jmp     0x40137a00

b_call:
    move.l  %d1,%sp@(48)
    mvs.b   %a4@(44),%d1
    jsr     %a1@
    jmp     0x40137612

| ---- SPH stops being a start phase on the new slots -------------------------
no_phase:
    mvs.b   %a4@(76),%d2
    subq.l  #{STOCK_WAVE_MAX + 1},%d2
    bmi.s   1f
    clr.l   %d2
    bra.s   2f
1:  mvs.w   %a4@(78),%d2
2:  sub.l   %d0,%d7
    jmp     0x40137894
""" + ui.formatter_source(ENTRIES - 1, short_names, long_names) + glyph.source(
        glyph_sets, fn_table, len(wt.TABLES), label_table)


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found -- patch/assemble.py needs "
                         "m68k-linux-gnu-as (WSL is fine)")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    require_zero(content, CAVE_CODE, CAVE_CODE_CAP, "code cave")
    require_zero(content, CAVE_DATA, CAVE_DATA_CAP, "data cave")

    print("part 1 -- the tables and the glyph data, in the data cave")
    cursor, table_vas = CAVE_DATA, []
    for long_name, _, make in wt.TABLES:
        data = wt.table_bytes(make())
        write(content, cursor, data)
        table_vas.append(cursor)
        print(f"  {long_name}  {len(data)} bytes at {cursor:#010x}")
        cursor += len(data)
    glyph_va = (cursor + 3) & ~3
    glyph_bytes, glyph_sets, label_table = glyph.blob(glyph_va, SPH_LABELS)
    data_used = glyph_va + len(glyph_bytes) - CAVE_DATA
    if data_used > CAVE_DATA_CAP:
        raise SystemExit(f"data cave overflows: {data_used} > {CAVE_DATA_CAP}")
    write(content, glyph_va, glyph_bytes)

    print("part 2 -- names and relocated tables, then the stubs, in the code cave")
    cursor, short_vas, long_vas = CAVE_CODE, [], []
    for long_name, short_name, _ in wt.TABLES:
        short_vas.append(cursor)
        write(content, cursor, short_name.encode() + b"\x00")
        cursor += len(short_name) + 1
        long_vas.append(cursor)
        write(content, cursor, long_name.encode() + b"\x00")
        cursor += len(long_name) + 1
    cursor = (cursor + 3) & ~3
    names_va, cursor = cursor, cursor + 4 * ENTRIES
    long_names_va, cursor = cursor, cursor + 4 * ENTRIES
    fn_vas = {}
    for old in STOCK_TABLES:
        fn_vas[old], cursor = cursor, cursor + 4 * ENTRIES
    stub_va = cursor

    payload, offsets = assemble_stubs(
        source(fn_vas[0x4020B340], table_vas, names_va, long_names_va, glyph_sets, label_table),
        stub_va)
    used = (stub_va - CAVE_CODE) + len(payload)
    if used > CAVE_CODE_CAP:
        raise SystemExit(f"code cave overflows: {used} > {CAVE_CODE_CAP}")
    write(content, stub_va, payload)
    for label in LABELS:
        print(f"  {label:<10} {offsets[label]:#010x}")

    print(f"part 3 -- the {ENTRIES}-entry copies")
    write(content, names_va, b"".join(
        be32(v) for v in read_longs(content, STOCK_NAMES, STOCK_ENTRIES) + short_vas))
    write(content, long_names_va, b"".join(
        be32(v) for v in read_longs(content, ui.LONG_NAMES, STOCK_ENTRIES) + long_vas))
    extras = {0x4020B2EC: [0] * 3, 0x4020B308: [0] * 3, 0x4020B324: [0] * 3,
              0x4020B340: [offsets[g] for g in GENERATORS]}
    for old in STOCK_TABLES:
        write(content, fn_vas[old], b"".join(
            be32(v) for v in read_longs(content, old, STOCK_ENTRIES) + extras[old]))

    print("part 4 -- repoint and hook")
    for old, sites in REPOINTS.items():
        for va, prefix in sites:
            poke(content, va, prefix + be32(old), prefix + be32(fn_vas[old]),
                 f"{old:#010x} -> {fn_vas[old]:#010x}")
    for va, stock, label in HOOKS:
        poke(content, va, stock, b"\x4e\xf9" + be32(offsets[label]), f"jmp -> {label}")
    for va, stock, new, why in glyph.clamp_edits(ENTRIES - 1) + glyph.hooks(offsets):
        poke(content, va, stock, new, why)
    for va, stock, new, why in ui.clamp_edits(ENTRIES - 1):
        poke(content, va, stock, new, why)
    for va in WAVE_MAX_FIELDS:
        poke(content, va, be32(STOCK_WAVE_MAX << 8), be32((ENTRIES - 1) << 8),
             "LFO Waveform max")

    print("part 5 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes), "
          f"{used}/{CAVE_CODE_CAP} code and {data_used}/{CAVE_DATA_CAP} data cave bytes")
    return 0


def assemble_stubs(text: str, base: int) -> tuple[bytes, dict[str, int]]:
    table = "\n".join(f"    .long {n}" for n in LABELS)
    blob = assemble(text + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    return blob[:-width], dict(zip(LABELS, struct.unpack(f">{len(LABELS)}I", blob[-width:])))


def be32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def read_longs(content: bytearray, va: int, n: int) -> list[int]:
    return list(struct.unpack_from(f">{n}I", content, va - BASE))


def write(content: bytearray, va: int, data: bytes) -> None:
    content[va - BASE:va - BASE + len(data)] = data


def require_zero(content: bytearray, va: int, n: int, what: str) -> None:
    block = content[va - BASE:va - BASE + n]
    if any(block):
        raise SystemExit(f"{what} at {va:#010x} is not free: "
                         f"{sum(1 for b in block if b)} non-zero bytes")


def poke(content: bytearray, va: int, stock: bytes, new: bytes, why: str) -> None:
    off = va - BASE
    have = bytes(content[off:off + len(stock)])
    if have != stock:
        raise SystemExit(f"{va:#010x}: expected {stock.hex()}, found {have.hex()} ({why})")
    content[off:off + len(new)] = new
    print(f"  {va:#010x}  {stock.hex():<14} -> {new.hex():<14}  {why}")


if __name__ == "__main__":
    raise SystemExit(main())

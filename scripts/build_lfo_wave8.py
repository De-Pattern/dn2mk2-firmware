"""An eighth LFO waveform: STP, an eight-level staircase ramp.

**What this adds.** The Digitone II's LFOs offer seven waveforms -- `TRI SIN SQR
SAW EXP RMP RND`. This build adds an eighth, `STP`, on every LFO of every track:
the ramp quantised to eight levels, so a pitch destination steps instead of
gliding and a filter destination clicks through a fixed ladder. It is the one
shape the stock set does not contain, and it is unmistakable against all seven
of them, which is also what makes it a good first new waveform to test.

## What made it cheap, and it was not a search

`docs/ideas-backlog.md` section 8 said for a week that the waveform table was
**not located** -- the same gap the Octatrack researchers record for their own
device. It turned up while reading the two LFO evaluators for LFO4
(`docs/lfo4-build-plan.md` section 5k), as four consecutive seven-entry tables:

| table | what | index 7 gets |
|---|---|---|
| `0x4020b2ec` | per-waveform hold value, used when the LFO is held | `0`, as `SAW` has |
| `0x4020b308` | start value, positive phase | `0` |
| `0x4020b324` | start value, negative phase | `0` |
| `0x4020b340` | **the generator function pointers** | our routine |

and a fifth table one layer up: `0x401d3574`, the seven **name** pointers
`TRI SIN SQR SAW EXP RMP RND`, in exactly the generator table's order. The `MODE`
list `FRE TRG HLD ONE HLF` starts at the next longword, so none of the five has
any slack and all five are copied out rather than extended in place.

Each of the four value tables has exactly **two** `lea` sites, one per evaluator,
and the name list has exactly **one** `pea`. Nine pointer edits, three record
maxima, one 18-byte routine.

## Why index 7 is reachable, which was the question that mattered

Index 6, `RND`, has a **NULL** generator, so the obvious worry was that an eighth
index would fall into whatever handles it. It does not: `0x401379e8` compares the
waveform against 6 **by value** and branches away before the indexed `jsr`, so
the NULL entry is never called and index 7 reaches the call like indices 0-5.

Had that test been a bound rather than an equality, this build would not exist.
It was read before anything was written.

## The generator

Every generator is a leaf taking a 32-bit phase in `%sp@(4)` and returning a
32-bit signed level in `%d0`. `SAW` is the whole of `eori.l #0x7fffffff,%d0`, so
`STP` is that plus a mask:

    move.l  %sp@(4),%d0
    eori.l  #0x7fffffff,%d0     | the SAW ramp
    andi.l  #0xe0000000,%d0     | keep three bits: eight levels
    rts

## The risk to watch on the instrument, stated plainly

The `[MOD]` page draws a small waveform graph for the `WAVE` column through a
virtual call (`%a1@(180)`, `0x4010e1a0`) whose renderer was **not** read. It may
draw nothing for an unknown waveform, or it may index a glyph table by the value.
**Select `STP` while watching for a freeze**, and if the page hangs, power-cycle
and reflash stock by the route in `docs/flashing.md`. The sound itself does not
depend on the page: an LFO already set to `STP` will run whether or not the page
is open.

Nothing here touches the sound format, the pattern format or any stored value --
`WAVE` is one existing slot whose maximum goes from 6 to 7.
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

MAIN_OS = 3
BASE = 0x40000400

# One of the three 896-byte runs that pass both of `dnfw cave scan`'s checks.
CAVE = 0x402CF52C
CAVE_CAP = 896

STOCK_NAMES = 0x401D3574
STOCK_TABLES = (0x4020B2EC, 0x4020B308, 0x4020B324, 0x4020B340)

# The index-7 entry for each of the four value tables, in the order above.
# The generator pointer is filled in once the stub's address is known.
NEW_ENTRIES = [0, 0, 0, None]

NEW_NAME = b"STP\x00"

# Every `lea`/`pea` that names one of the five tables, with its opcode prefix.
SITES = {
    0x401D3574: ((0x40007688, b"\x48\x79"),),
    0x4020B2EC: ((0x401374DE, b"\x41\xf9"), (0x401378E2, b"\x41\xf9")),
    0x4020B308: ((0x40137514, b"\x43\xf9"), (0x40137916, b"\x43\xf9")),
    0x4020B324: ((0x40137508, b"\x41\xf9"), (0x4013790C, b"\x43\xf9")),
    0x4020B340: ((0x401375EE, b"\x43\xf9"), (0x401379FA, b"\x41\xf9")),
}

# LFO1/2/3 `Waveform`, maximum field.  6 -> 7.
WAVE_MAX_FIELDS = (0x401F9224, 0x401F947C, 0x401F96D4)

GENERATOR = """
    .text
step8:
    move.l  %sp@(4),%d0
    eori.l  #0x7fffffff,%d0
    andi.l  #0xe0000000,%d0
    rts
"""

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo-wave8_DN2_1.11.syx")


def be32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found -- patch/assemble.py needs "
                         "m68k-linux-gnu-as (WSL is fine)")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    require_zero(content, CAVE, CAVE_CAP, "cave region")

    # --- layout ----------------------------------------------------------
    name_va = CAVE
    names_va = CAVE + len(NEW_NAME)
    tables_va = [names_va + 32 + 32 * i for i in range(4)]
    stub_va = tables_va[-1] + 32
    used = stub_va - CAVE

    print("part 1 -- the generator")
    payload = assemble(GENERATOR, base=stub_va)
    used += len(payload)
    if used > CAVE_CAP:
        raise SystemExit(f"cave overflows: {used} > {CAVE_CAP}")
    write(content, stub_va, payload)
    print(f"  {len(payload)} bytes at {stub_va:#010x}")
    NEW_ENTRIES[3] = stub_va

    print("part 2 -- the eight-entry copies")
    write(content, name_va, NEW_NAME)
    print(f"  {NEW_NAME[:-1].decode()!r} at {name_va:#010x}")

    old_names = read_longs(content, STOCK_NAMES, 7)
    write(content, names_va, b"".join(be32(v) for v in old_names + [name_va]))
    print(f"  names   {STOCK_NAMES:#010x} -> {names_va:#010x}  "
          + " ".join(cstr(content, v) or "?" for v in old_names + [name_va]))

    for old, new_va, extra in zip(STOCK_TABLES, tables_va, NEW_ENTRIES):
        entries = read_longs(content, old, 7)
        write(content, new_va, b"".join(be32(v) for v in entries + [extra]))
        print(f"  {old:#010x} -> {new_va:#010x}  "
              f"[{', '.join(f'{v:#x}' for v in entries)}] + {extra:#x}")

    print("part 3 -- repoint every site")
    for old, new_va in zip((STOCK_NAMES,) + STOCK_TABLES, [names_va] + tables_va):
        for va, prefix in SITES[old]:
            poke(content, va, prefix + be32(old), prefix + be32(new_va),
                 f"{old:#010x} -> {new_va:#010x}")

    print("part 4 -- WAVE's maximum, 6 -> 7")
    for va in WAVE_MAX_FIELDS:
        poke(content, va, be32(6 << 8), be32(7 << 8), "LFO Waveform max")

    print("part 5 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes), "
          f"{used} of {CAVE_CAP} cave bytes used")
    return 0


def read_longs(content: bytearray, va: int, n: int) -> list[int]:
    off = va - BASE
    return list(struct.unpack_from(f">{n}I", content, off))


def write(content: bytearray, va: int, data: bytes) -> None:
    off = va - BASE
    content[off:off + len(data)] = data


def cstr(content: bytearray, va: int) -> str | None:
    off = va - BASE
    if not 0 <= off < len(content):
        return None
    end = content.find(b"\0", off)
    text = bytes(content[off:end])
    return text.decode("latin1") if 0 < len(text) < 24 else None


def require_zero(content: bytearray, va: int, n: int, what: str) -> None:
    block = content[va - BASE:va - BASE + n]
    if any(block):
        raise SystemExit(f"{what} at {va:#010x} is not free: "
                         f"{sum(1 for b in block if b)} non-zero bytes")


def poke(content: bytearray, va: int, stock: bytes, new: bytes, why: str) -> None:
    off = va - BASE
    have = bytes(content[off:off + len(stock)])
    if have != stock:
        raise SystemExit(f"{va:#010x}: expected {stock.hex()}, found {have.hex()} -- "
                         f"not the image this patch was written against ({why})")
    content[off:off + len(new)] = new
    print(f"  {va:#010x}  {stock.hex():<14} -> {new.hex():<14}  {why}")


if __name__ == "__main__":
    raise SystemExit(main())

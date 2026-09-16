"""A wavetable LFO waveform, from the shape bench's own export.

`docs/ideas-backlog.md` §14 delivered the bench and left its firmware half
unbuilt. This is that half: it takes the JSON the bench exports and turns it into
a real waveform slot, so a shape that cannot be written as four ColdFire
instructions still reaches the instrument.

    python scripts/build_lfo_wavetable.py shape.json
    python scripts/build_lfo_wavetable.py            # the built-in example

## Why a table at all

Every stock generator is a handful of instructions over the phase, which is why
`SQR` is four and `SAW` is one. That works for shapes with closed forms and
nothing else. A table works for **any** shape, at a fixed price: 256 signed words
is 512 bytes, and the generator that indexes it is twelve instructions.

## Where the 512 bytes go, and why not eight bands

The bench exports eight tables, one per `SPH` band, which is 4,096 bytes. **The
largest verified-free run in the image is 896 bytes** (`docs/code-caves.md`), and
the 25.3 MB above BSS is runtime-only — it holds nothing that ships. So eight
bands do not fit anywhere today, and §1/§6's "get shipped bytes into the image"
is the blocker.

One band does fit, and `SPH` still has a job: it becomes the **read stride**.

    index = ((phase >> 24) * (1 + SPH/16)) & 255

Stride 1 plays the table as drawn; stride 2 plays it twice per cycle, stride 3
three times, up to eight. So one 512-byte table gives eight related shapes, and
the parameter still means something on this waveform. It is a smaller idea than
the bench's eight independent bands and it is the one that fits.

## What it takes from the bench

The `Builder JSON` button's output. Only `name` and `bands[0]` are read -- the
other seven bands are ignored, with a note printed, because of the space above.

The table is 256 signed 16-bit values. At run time each is shifted left 16 to
become the 32-bit level the evaluators expect, so the table's full-scale is
+-32767 and the generator's is +-2147483647.
"""

from __future__ import annotations

import argparse
import json
import math
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

# Two runs, because the table alone is 512 of the 896 a single run offers and the
# stubs plus the five relocated tables do not fit beside it.
CAVE_CODE, CAVE_CODE_CAP = 0x402CF52C, 896
CAVE_DATA, CAVE_DATA_CAP = 0x402D0664, 896

STOCK_NAMES = 0x401D3574
STOCK_TABLES = (0x4020B2EC, 0x4020B308, 0x4020B324, 0x4020B340)
STOCK_ENTRIES = 7
ENTRIES = STOCK_ENTRIES + 1

REPOINTS = {
    0x401D3574: ((0x40007688, b"\x48\x79"),),
    0x4020B2EC: ((0x401374DE, b"\x41\xf9"), (0x401378E2, b"\x41\xf9")),
    0x4020B308: ((0x40137514, b"\x43\xf9"), (0x40137916, b"\x43\xf9")),
    0x4020B324: ((0x40137508, b"\x41\xf9"), (0x4013790C, b"\x43\xf9")),
    0x4020B340: ((0x401375EE, b"\x43\xf9"),),
}
HOOKS = (
    (0x401379FA, b"\x41\xf9\x40\x20\xb3\x40", "a_call"),
    (0x4013760C, b"\x2f\x41\x00\x30\x4e\x91", "b_call"),
    (0x4013788E, b"\x75\x6c\x00\x4e\x9e\x80", "no_phase"),
)
LABELS = ("wtb", "a_call", "b_call", "no_phase")

WAVE_MAX_FIELDS = (0x401F9224, 0x401F947C, 0x401F96D4)
STOCK_WAVE_MAX = 6

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo-wavetable_DN2_1.11.syx")


def example_table() -> list[int]:
    """A trapezoid with soft shoulders -- a shape the stock seven do not contain.

    Ships as the default so the build is runnable without the bench, and so the
    pipeline is exercised end to end by `python scripts/build_lfo_wavetable.py`
    with no arguments.
    """
    # Each shoulder is a half-cosine spanning the whole range, -1 -> +1 and
    # +1 -> -1, so the shape is continuous everywhere including the wrap.  The
    # first version used quarter-waves that only reached 0, which left two
    # half-scale jumps -- at 65% of the cycle and at the wrap -- and would have
    # clicked on any filter or pitch destination.  Caught by reading the built
    # table, not the formula.
    out = []
    for i in range(256):
        p = i / 256.0
        if p < 0.15:
            v = -math.cos(p / 0.15 * math.pi)            # -1 -> +1
        elif p < 0.5:
            v = 1.0
        elif p < 0.65:
            v = math.cos((p - 0.5) / 0.15 * math.pi)     # +1 -> -1
        else:
            v = -1.0
        out.append(max(-32767, min(32767, int(round(v * 32767)))))
    return out


def source(fn_table: int, wave_table: int) -> str:
    return f"""
    .text

| ---- WTB: 256 signed words, SPH is the read stride ----------------------
| index = ((phase >> 24) * (1 + SPH/16)) & 255, so stride runs 1..8 and one
| table gives eight related shapes.  The table holds 16-bit levels; the
| evaluators want 32, so the fetched word is shifted left 16.
wtb:
    move.l  %d2,%sp@-
    andi.l  #0x7f,%d1
    lsr.l   #4,%d1
    addq.l  #1,%d1                  | stride 1..8
    move.l  %sp@(8),%d0             | the phase, one push deep
    lsr.l   #8,%d0
    lsr.l   #8,%d0
    lsr.l   #8,%d0                  | 0..255
    muls.l  %d1,%d0
    andi.l  #0xff,%d0
    add.l   %d0,%d0                 | word index
    lea     {wave_table:#010x},%a0
    mvs.w   %a0@(0,%d0:l),%d0
    moveq   #16,%d2
    lsl.l   %d2,%d0
    move.l  %sp@+,%d2
    rts

| ---- the two call sites carry SPH in %d1, as the shapes build does ------
a_call:
    lea     {fn_table:#010x},%a0
    mvs.b   %a4@(78),%d1
    jmp     0x40137a00

b_call:
    move.l  %d1,%sp@(48)
    mvs.b   %a4@(44),%d1
    jsr     %a1@
    jmp     0x40137612

| ---- SPH stops being a start phase on the new slot ----------------------
no_phase:
    mvs.b   %a4@(76),%d2
    subq.l  #{STOCK_WAVE_MAX + 1},%d2
    bmi.s   1f
    clr.l   %d2
    bra.s   2f
1:  mvs.w   %a4@(78),%d2
2:  sub.l   %d0,%d7
    jmp     0x40137894
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("shape", nargs="?", type=pathlib.Path,
                    help="the bench's Builder JSON; omit for the built-in example")
    ap.add_argument("--name", help="three characters; overrides the JSON's name")
    args = ap.parse_args()

    if not available():
        raise SystemExit("no m68k assembler found -- patch/assemble.py needs "
                         "m68k-linux-gnu-as (WSL is fine)")

    if args.shape:
        doc = json.loads(args.shape.read_text())
        name = (args.name or doc.get("name") or "WTB")
        bands = doc.get("bands") or []
        if not bands:
            raise SystemExit(f"{args.shape}: no 'bands' in the export")
        table = list(bands[0])
        if len(bands) > 1:
            print(f"  note: {len(bands)} bands in the export, using band 0 only "
                  "-- there is no room in the image for eight (see the docstring)")
    else:
        name, table = (args.name or "TRP"), example_table()
        print("  no shape given: using the built-in trapezoid")

    name = name.upper()[:3].ljust(3)
    if len(table) != 256:
        raise SystemExit(f"table has {len(table)} entries, expected 256")
    if any(not -32768 <= v <= 32767 for v in table):
        raise SystemExit("table values must fit a signed 16-bit word")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    require_zero(content, CAVE_CODE, CAVE_CODE_CAP, "code cave")
    require_zero(content, CAVE_DATA, CAVE_DATA_CAP, "data cave")

    print(f"part 1 -- the table: {name!r}, 256 words at {CAVE_DATA:#010x}")
    blob = struct.pack(">256h", *table)
    write(content, CAVE_DATA, blob)
    print(f"  {len(blob)} bytes, peak {max(abs(v) for v in table)} of 32767")

    # Layout in the code cave: the name, then the five tables, then the stubs.
    name_va, cursor = CAVE_CODE, CAVE_CODE + 4
    names_va, cursor = cursor, cursor + 4 * ENTRIES
    table_vas = {}
    for old in STOCK_TABLES:
        table_vas[old], cursor = cursor, cursor + 4 * ENTRIES
    stub_va = cursor

    print("part 2 -- the generator and the hook stubs")
    payload, offsets = assemble_stubs(source(table_vas[0x4020B340], CAVE_DATA), stub_va)
    used = (stub_va - CAVE_CODE) + len(payload)
    if used > CAVE_CODE_CAP:
        raise SystemExit(f"code cave overflows: {used} > {CAVE_CODE_CAP}")
    write(content, stub_va, payload)
    for label in LABELS:
        print(f"  {label:<9} {offsets[label]:#010x}")

    print(f"part 3 -- the {ENTRIES}-entry copies")
    write(content, name_va, name.encode("ascii") + b"\x00")
    old_names = read_longs(content, STOCK_NAMES, STOCK_ENTRIES)
    write(content, names_va, b"".join(be32(v) for v in old_names + [name_va]))
    print(f"  names {STOCK_NAMES:#010x} -> {names_va:#010x}  "
          + " ".join(cstr(content, v) or "?" for v in old_names + [name_va]))
    extras = {0x4020B2EC: 0, 0x4020B308: 0, 0x4020B324: 0, 0x4020B340: offsets["wtb"]}
    for old in STOCK_TABLES:
        entries = read_longs(content, old, STOCK_ENTRIES) + [extras[old]]
        write(content, table_vas[old], b"".join(be32(v) for v in entries))
        print(f"  {old:#010x} -> {table_vas[old]:#010x}  "
              + ", ".join(f"{v:#x}" for v in entries))

    print("part 4 -- repoint and hook")
    resolved = {STOCK_NAMES: names_va, **table_vas}
    for old, sites in REPOINTS.items():
        for va, prefix in sites:
            poke(content, va, prefix + be32(old), prefix + be32(resolved[old]),
                 f"{old:#010x} -> {resolved[old]:#010x}")
    for va, stock, label in HOOKS:
        poke(content, va, stock, b"\x4e\xf9" + be32(offsets[label]), f"jmp -> {label}")

    print(f"part 5 -- WAVE's maximum, {STOCK_WAVE_MAX} -> {ENTRIES - 1}")
    for va in WAVE_MAX_FIELDS:
        poke(content, va, be32(STOCK_WAVE_MAX << 8), be32((ENTRIES - 1) << 8),
             "LFO Waveform max")

    print("part 6 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes), "
          f"{used}/{CAVE_CODE_CAP} code and {len(blob)}/{CAVE_DATA_CAP} data cave bytes")
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


def cstr(content: bytearray, va: int) -> str | None:
    off = va - BASE
    if not 0 <= off < len(content):
        return None
    text = bytes(content[off:content.find(b"\0", off)])
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
        raise SystemExit(f"{va:#010x}: expected {stock.hex()}, found {have.hex()} ({why})")
    content[off:off + len(new)] = new
    print(f"  {va:#010x}  {stock.hex():<14} -> {new.hex():<14}  {why}")


if __name__ == "__main__":
    raise SystemExit(main())

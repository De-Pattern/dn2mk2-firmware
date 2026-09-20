"""Which code touches each address of a fixed structure, and how.

    python scripts/sram_field_map.py <image.syx|zip> 0x80005340 0x800053e0
    python scripts/sram_field_map.py <image> 0x80005340 0x800053e0 --min 3

A block like the DSP's control area (`docs/dsp-control-block.md`) is a struct
with no declaration: fixed addresses, each touched from a handful of sites. This
walks the section for absolute-addressing instructions that name an address in
the range and reports, per address, the **width**, the **direction** and the
sites -- which is the shape of the field and who owns it.

It reads the instruction word *before* the address, so it distinguishes
`moveb <abs>,%d0` from `moveb %d0,<abs>`. Anything it cannot name is reported
as `?` with its opcode word rather than dropped: an unrecognised encoding is a
fact about the image, not something to hide.

One subject: counting references. What a field means is read in the
disassembly; `dnfw disasm` is two lines below every row this prints.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                      # noqa: E402
from dnfw.firmware.load import load                        # noqa: E402

# What the instruction word before an absolute long address does with it.
# `r` reads the address, `w` writes it, `a` takes the address itself.
WIDTH = {1: "b", 3: "w", 2: "l"}
ABS_LONG = 0o71                       # mode 111, register 001

OTHER = {0x4879: ("-", "a"),                                          # pea <abs>
         0x4A39: ("b", "r"), 0x4A79: ("w", "r"), 0x4AB9: ("l", "r"),  # tst
         0x4239: ("b", "w"), 0x4279: ("w", "w"), 0x42B9: ("l", "w"),  # clr
         0x52B9: ("l", "w"), 0x53B9: ("l", "w")}                      # addq/subq #1,<abs>
for reg in range(8):
    OTHER[0x41F9 | (reg << 9)] = ("-", "a")                           # lea <abs>,An
    OTHER[0x7139 | (reg << 9)] = ("b", "r")                           # mvs.b <abs>,Dn
    OTHER[0x7179 | (reg << 9)] = ("w", "r")                           # mvs.w
    OTHER[0x71B9 | (reg << 9)] = ("b", "r")                           # mvz.b
    OTHER[0x71F9 | (reg << 9)] = ("w", "r")                           # mvz.w
    for op in (0x8039, 0x9039, 0xB039, 0xC039, 0xD039):               # or/sub/cmp/and/add .b
        OTHER[op | (reg << 9)] = ("b", "r")
    for op in (0x8079, 0x9079, 0xB079, 0xC079, 0xD079):               # .w
        OTHER[op | (reg << 9)] = ("w", "r")
    for op in (0x80B9, 0x90B9, 0xB0B9, 0xC0B9, 0xD0B9):               # .l
        OTHER[op | (reg << 9)] = ("l", "r")
    for op in (0x81B9, 0x91B9, 0xB1B9, 0xC1B9, 0xD1B9):               # .l, into <abs>
        OTHER[op | (reg << 9)] = ("l", "w")


def classify(word: int):
    """-> (width, direction) for the instruction word before an abs.l address."""
    size = (word >> 12) & 3
    if word >> 14 == 0 and size in WIDTH:                  # a MOVE of some size
        # A move's destination is stored reg-then-mode, the reverse of its source.
        destination = (((word >> 6) & 7) << 3) | ((word >> 9) & 7)
        if destination == ABS_LONG:
            return WIDTH[size], "w"
        if (word & 0o77) == ABS_LONG:
            return WIDTH[size], "r"
    return OTHER.get(word, ("?", f"{word:04x}"))


def fields(content: bytes, base: int, low: int, high: int):
    """-> {address: {(width, direction): [sites]}}"""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for address in range(low, high):
        for m in re.finditer(re.escape(struct.pack(">I", address)), content):
            at = m.start()
            if at < 2:
                continue
            word = struct.unpack_from(">H", content, at - 2)[0]
            kind = classify(word)
            out[address][kind].append(base + at - 2)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("low", type=lambda s: int(s, 0))
    p.add_argument("high", type=lambda s: int(s, 0))
    p.add_argument("--section", type=int, default=3)
    p.add_argument("--min", type=int, default=1, help="only addresses with at least this many sites")
    args = p.parse_args(argv)

    section = load(read_image(args.image)).container.find(args.section)
    content = section.unpack()
    found = fields(content, section.dest, args.low, args.high)

    print(f"{args.image.name} section {args.section}, 0x{args.low:08x}..0x{args.high:08x}\n")
    total = 0
    for address, kinds in sorted(found.items()):
        sites = sum(len(v) for v in kinds.values())
        if sites < args.min:
            continue
        total += sites
        shape = " ".join(f"{w}{d}x{len(v)}" for (w, d), v in sorted(kinds.items()))
        first = sorted(s for v in kinds.values() for s in v)[:4]
        print(f"  0x{address:08x}  {sites:3} site(s)  {shape:28} {' '.join(f'{s:#010x}' for s in first)}")
    print(f"\n{len(found)} address(es) touched, {total} site(s)")
    print("widths b/w/l, directions r read, w write, a taken as an address")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

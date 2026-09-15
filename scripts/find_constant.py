"""Find every place a 32-bit constant appears, and say how it is used.

`mmio_window_map.py` answers "who touches this address", but only for absolute
addressing -- `movel 0x80005e60,%d0`. A buffer base is not used that way: it is
loaded as an **immediate** into a register and then walked, which is a
different encoding entirely and invisible to that tool.

    movel #0x80005e60,%d0      0x203c | reg<<9
    moveal #0x80005e60,%a0     0x207c | reg<<9
    pea 0x80005e60             0x4879
    lea 0x80005e60,%a0         0x41f9 | reg<<9

So this reports every occurrence of the four bytes and classifies the two
opcode bytes in front. An occurrence with no recognised opcode in front is
still printed -- it may be a pointer sitting in a data table, which is exactly
what you want to know when hunting for who owns a buffer.

    python scripts/find_constant.py <image.syx> 0x80005e60 [more...]
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import load_section  # noqa: E402
from dnfw.image import functions  # noqa: E402

MAIN_OS = 3

# (mask, value, name). Register-bearing forms are masked so every spelling
# matches -- the lesson from the `0x23C0` vs `0x23C1` undercount recorded in
# `docs/sharc-image.md`.
FORMS = (
    (0xF1FF, 0x203C, "movel #imm,dN"),
    (0xF1FF, 0x207C, "moveal #imm,aN"),
    (0xFFFF, 0x4879, "pea imm"),
    (0xF1FF, 0x41F9, "lea imm,aN"),
    (0xF1FF, 0x2F3C, "movel #imm,-(sp)"),
    (0xFFFF, 0x0C80, "cmpil #imm,d0"),
    (0xF1FF, 0x0680, "addil #imm,dN"),
)


def classify(word: int) -> str | None:
    for mask, value, name in FORMS:
        if word & mask == value:
            return name
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=pathlib.Path)
    parser.add_argument("constants", nargs="+")
    parser.add_argument("--section", type=int, default=MAIN_OS)
    args = parser.parse_args()

    image = load_section(args.image, args.section)
    graph = functions.build(image)
    data, base = image.content, image.dest

    for text in args.constants:
        value = int(text, 0)
        needle = struct.pack(">I", value)
        start, hits = 0, []
        while True:
            i = data.find(needle, start)
            if i < 0:
                break
            hits.append(i)
            start = i + 1

        print(f"=== {value:#010x}: {len(hits)} occurrence(s) ===")
        for i in hits:
            word = struct.unpack_from(">H", data, i - 2)[0] if i >= 2 else 0
            form = classify(word)
            if form is None:
                print(f"  {base + i:#010x}  (not an immediate load -- "
                      f"preceding word {word:#06x}; possibly a data pointer)")
                continue
            site = base + i - 2
            fn = graph.containing(site)
            where = f" in {fn:#010x}" if fn is not None else ""
            print(f"  {site:#010x}  {form:<18}{where}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

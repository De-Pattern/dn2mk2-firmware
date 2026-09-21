"""Find the places the firmware writes the same LFO code three times over.

    python scripts/scan_lfo_triples.py <image.syx> [--span 10] [--window 96]

Three findings this project made separately are one finding: the waveform
preview is three code blocks with LFO1's, LFO2's and LFO3's entry numbers as
literals; the `SLEW` substitution gates on the literals **81, 91, 101**; the
`SLEW` entries themselves are a three-word table **80, 90, 100**. Each was
found by hand, and each cost an evening. A fourth LFO needs every one of them.

The shape is always the same -- three small immediates ten apart, close
together, because an LFO's ten parameter records sit ten apart in the table.
So this walks every small immediate in the section, classified by the opcode
that carries it, and reports each window holding `v`, `v+span` and `v+2*span`.

It is a **candidate list, not an answer**: ten apart happens by accident too.
What it buys is that the accidents can be read in an afternoon, where the image
cannot.
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import load_section  # noqa: E402

MAIN_OS = 3

# (mask, value, name, how many bytes of immediate follow the opcode word).
# A moveq carries its immediate inside the opcode word, so it is `0`.
FORMS = (
    (0xF100, 0x7000, "moveq", 0),
    (0xF1FF, 0x103C, "moveb #imm,dN", 2),
    (0xF1FF, 0x303C, "movew #imm,dN", 2),
    (0xF1FF, 0x203C, "movel #imm,dN", 4),
    (0xFFFF, 0x4878, "pea imm", 2),
    (0xFFC0, 0x0C00, "cmpib #imm", 2),
    (0xFFC0, 0x0C40, "cmpiw #imm", 2),
    (0xFFC0, 0x0C80, "cmpil #imm", 4),
)


def literals(span: bytes, base: int, ceiling: int):
    """Every small immediate in the section, as (va, value, form).

    Values above `ceiling` are dropped: this is hunting parameter entry
    numbers, and the image is full of addresses and sizes that are not.
    """
    found = []
    for at in range(0, len(span) - 6, 2):
        word = struct.unpack_from(">H", span, at)[0]
        for mask, value, name, width in FORMS:
            if word & mask != value:
                continue
            if width == 0:
                imm = word & 0xFF
                if imm > 127:                      # moveq is signed
                    continue
            elif width == 2:
                imm = struct.unpack_from(">H", span, at + 2)[0]
            else:
                imm = struct.unpack_from(">I", span, at + 2)[0]
            if imm <= ceiling:
                found.append((base + at, imm, name))
            break
    return found


def triples(found, span_between: int, window: int):
    """Windows holding `v`, `v+span` and `v+2*span`. -> (va, v, [sites])."""
    out = []
    for i, (va, value, _form) in enumerate(found):
        wanted = {value + span_between, value + 2 * span_between}
        near = [s for s in found[i:] if s[0] - va <= window]
        have = {s[1] for s in near}
        if wanted <= have:
            out.append((va, value, [s for s in near if s[1] in wanted | {value}]))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=pathlib.Path)
    parser.add_argument("--section", type=int, default=MAIN_OS)
    parser.add_argument("--span", type=int, default=10, help="records per LFO group")
    parser.add_argument("--window", type=int, default=96, help="bytes the three must share")
    parser.add_argument("--ceiling", type=int, default=320, help="highest plausible entry")
    parser.add_argument("--only", type=int, default=None,
                        help="report only the group whose first value is this")
    args = parser.parse_args(argv)

    image = load_section(args.image, args.section)
    base = image.dest
    found = literals(image.content, base, args.ceiling)
    print(f"{len(found):,} small immediates at or below {args.ceiling}")

    hits = triples(found, args.span, args.window)
    if args.only is not None:
        hits = [h for h in hits if h[1] == args.only]
    print(f"{len(hits)} window(s) holding v, v+{args.span}, v+{2 * args.span}\n")
    for va, value, sites in hits:
        rendered = ", ".join(f"{s[1]}@{s[0]:#010x} ({s[2]})" for s in sites)
        print(f"{va:#010x}  {value}/{value + args.span}/{value + 2 * args.span}: {rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

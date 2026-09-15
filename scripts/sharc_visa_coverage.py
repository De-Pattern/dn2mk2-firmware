"""Decode SHARC+ VISA code with the PRM tables, and report instruction coverage.

Coverage is the fraction of decode attempts that match a known instruction
form. It is the number that says whether an opcode table is usable: a table
that covers 60% of a real image is not "mostly right", it is desynchronised,
because a missed instruction takes the wrong number of bytes and every
instruction after it is read at the wrong offset.

## How VISA sits in memory

Instructions are streams of 16-bit shorts. A 48-bit form occupies three of
them, and the PRM's figure rows map straight onto that: bits 47..32 are the
first short, 31..16 the second, 15..0 the third. A 32-bit form is two shorts
(31..16 then 15..0) and a 16-bit form is one (15..0). So a form's width tells
you both how many shorts to fetch and which bit positions they carry -- and
aligning a 32-bit pattern as though it were the top of a 48-bit word is the
mistake that makes a correct table look broken.

## Decode order is load-bearing

Patterns nest: a form with few fixed bits subsumes stricter forms inside its
pattern space. Tested first, the loose one wins and swallows instructions that
belong to the strict one, and because the forms differ in length the walk
desynchronises from there. So candidates are tried **most-specific first**,
by number of fixed bits.

`Compute`, `ShortCompute` and `ShiftImm` are excluded: they are operand
encodings embedded inside other instructions, not dispatch targets, and
`Compute` has no fixed bits at all -- as a top-level candidate it would match
every word in the image.

Takes the depacked section 7 (`dnfw extract` writes it as
`section_7_blob.aplib.bin`) rather than the `.syx`, so the same run can be
pointed at any image's DSP program without re-extracting.

Usage:
    dnfw extract <image.syx> -o out/
    python scripts/sharc_visa_coverage.py visa.json out/section_7_blob.aplib.bin
    python scripts/sharc_visa_coverage.py visa.json out/section_7_blob.aplib.bin --mode ISA
"""

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dnfw.image import bootstream                       # noqa: E402

# Operand encodings, not instructions. Never dispatch targets.
NOT_DISPATCHABLE = {"Compute", "ShortCompute", "ShiftImm"}


def patterns(path, mode):
    """-> [(fixed-bit count, width, mask, value, name)], most specific first."""
    forms = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["forms"]
    out = []
    for form in forms:
        if form["name"] in NOT_DISPATCHABLE or not form["fixed"]:
            continue
        declared = form["mode"] or ""
        if mode not in declared:
            continue
        mask = value = 0
        for bit, bit_value in form["fixed"].items():
            mask |= 1 << int(bit)
            if bit_value:
                value |= 1 << int(bit)
        out.append((len(form["fixed"]), form["width"], mask, value, form["name"]))
    # Most fixed bits first, so a nested pattern is reached before the pattern
    # that subsumes it.
    out.sort(key=lambda entry: -entry[0])
    return out


def word_of(data, offset, width):
    """Assemble `width` bits from shorts at `offset`, as the figures number them.

    Returns None if the stream runs out -- a truncated tail is not a failure to
    decode, and counting it as one would understate coverage.
    """
    shorts = width // 16
    if offset + shorts * 2 > len(data):
        return None
    word = 0
    for index in range(shorts):
        position = offset + index * 2
        short = data[position] | (data[position + 1] << 8)
        # The first short carries the highest bits of the form.
        word |= short << (width - 16 * (index + 1))
    return word


def sweep(data, table, start=0):
    """Linear decode from `start`. -> (decoded, unknown, Counter of names)."""
    offset, decoded, unknown = start, 0, 0
    names = collections.Counter()
    while offset < len(data):
        hit = None
        for _bits, width, mask, value, name in table:
            word = word_of(data, offset, width)
            if word is None:
                continue
            if word & mask == value:
                hit = (width, name)
                break
        if hit is None:
            unknown += 1
            offset += 2                       # resynchronise on the next short
            continue
        width, name = hit
        names[name] += 1
        decoded += 1
        offset += width // 8
    return decoded, unknown, names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tables", type=pathlib.Path, help="visa.json")
    parser.add_argument("section7", type=pathlib.Path,
                        help="depacked section 7, e.g. section_7_blob.aplib.bin")
    parser.add_argument("--mode", default="VISA", choices=["VISA", "ISA"])
    args = parser.parse_args(argv)

    table = patterns(args.tables, args.mode)
    print(f"{len(table)} dispatchable {args.mode} forms "
          f"({min(t[0] for t in table)}-{max(t[0] for t in table)} fixed bits)\n")

    regions = bootstream.load_regions(args.section7.read_bytes())

    total_decoded = total_unknown = 0
    print(f"{'region':>12} {'bytes':>10} {'decoded':>9} {'unknown':>8} {'coverage':>9}")
    for address, blob in sorted(regions):
        if len(blob) < 64:
            continue
        decoded, unknown, _names = sweep(blob, table)
        attempts = decoded + unknown
        if not attempts:
            continue
        total_decoded += decoded
        total_unknown += unknown
        share = 100.0 * decoded / attempts
        print(f"  0x{address:08x} {len(blob):>10,} {decoded:>9,} "
              f"{unknown:>8,} {share:>8.2f}%")

    attempts = total_decoded + total_unknown
    if attempts:
        print(f"\nTOTAL  {total_decoded:,} decoded, {total_unknown:,} unknown, "
              f"coverage {100.0 * total_decoded / attempts:.2f}%  "
              f"(unknown {100.0 * total_unknown / attempts:.2f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

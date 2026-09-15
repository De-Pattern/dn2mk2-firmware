"""Read the classic SHARC PGR's opcode tables, for cross-checking Rev 1.5.

**INCOMPLETE -- this does not work yet, and its output must not be used.** The
document is identified and its layout understood (both below), but the
positional reader still picks up page furniture: types 1a, 8a, 13a and 14a all
come out with the identical bit set `11,10,1,0`, which is a page number read as
opcode bits. A cross-check whose second source is misread is worse than no
cross-check, so no numbers from this are reported anywhere until it is right.

**A second source is the only thing that catches a wrong figure.** The digikit
author's notes record that in the SHARC+ manual "printed digits in gray cells
are not always right: several figures keep a template's default digits or copy
another figure", and her Type 2b resolution turns on exactly that. No amount of
care with one document finds an error the document itself contains.

The classic manual --- **SHARC Processor Programming Reference, Rev 2.4, April
2013, Part Number 82-000500-01**, 694 pages,
`sha256 0b40637d05c7f33bc8e39235ee8a9d2c734b12c0372aff1eeac56a7554895869` ---
covers ADSP-2136x/2137x/214xx, the classic core rather than SHARC+. Its
Group I--IV types are the ancestors of the SHARC+ `a` forms, so their fixed
opcode bits should agree where both define a type.

Its chapter 10, "Instruction Set Opcodes" (from page 447), lays each type out
as **flat text** rather than as the shaded vector cells Rev 1.5 uses:

    Type 1a
    47 46 45 44 43 42 41 40 39 ...
    001
    D  M  D  DMI  DMM  P  M  D  DM DREG ...

so none of `prm_opcode_figures.py`'s geometry applies --- different cell pitch
(~12.5pt against 9), different grey (0.902 against 0.8235), grid drawn as
stroked lines rather than filled cells, and the fixed bits printed as digits
rather than shaded. Returning zero rows there says the conventions differ, not
that the figures are absent.

This reads the digits positionally: a bit number sits above its cell, so text
below at the same x belongs to that bit.

Usage:
    python scripts/pgr_opcode_text.py <pgr.pdf> -o classic.json
"""

import argparse
import collections
import json
import pathlib
import re
import sys

try:
    import pymupdf
except ImportError:  # pragma: no cover
    sys.exit("needs pymupdf:  python -m pip install pymupdf")

CHAPTER = (445, 500)
TYPE_HEADING = re.compile(r"^Type\s?(\d+[a-z]?)$")
BITS_ONLY = re.compile(r"^[01]+$")


def words_on(page):
    return page.get_text("words")


def bit_rows(words):
    """-> [(y, {bit number: centre x})] for each run of descending bit numbers."""
    by_line = collections.defaultdict(list)
    for x0, y0, x1, _y1, text, *_ in words:
        if text.isdigit() and 0 <= int(text) <= 47:
            by_line[round(y0, 0)].append((int(text), (x0 + x1) / 2))
    rows = []
    for y, items in sorted(by_line.items()):
        items.sort(key=lambda t: t[1])
        numbers = [n for n, _x in items]
        if len(numbers) < 6:
            continue
        descending = sum(1 for a, b in zip(numbers, numbers[1:]) if b == a - 1)
        if descending >= len(numbers) - 2:
            rows.append((y, {n: x for n, x in items}))
    return rows


def digits_under(words, y, columns, depth=26.0):
    """-> {bit: '0'|'1'} for printed opcode digits below a bit-number row.

    A run like `001` is one text item spanning three cells, so its characters
    are distributed across the cells its box covers rather than assigned whole.
    """
    pitch = None
    ordered = sorted(columns.items(), key=lambda kv: kv[1])
    if len(ordered) >= 2:
        pitch = abs(ordered[1][1] - ordered[0][1])
    out = {}
    for x0, y0, x1, _y1, text, *_ in words:
        if not (y < y0 <= y + depth) or not BITS_ONLY.match(text):
            continue
        span = max(len(text), 1)
        width = (x1 - x0) / span
        for index, char in enumerate(text):
            centre = x0 + width * (index + 0.5)
            best, best_d = None, 1e9
            for bit, bit_x in columns.items():
                d = abs(bit_x - centre)
                if d < best_d:
                    best, best_d = bit, d
            if best is not None and (pitch is None or best_d <= pitch * 0.75):
                out.setdefault(best, char)
    return out


def harvest(path, lo=CHAPTER[0], hi=CHAPTER[1]):
    document = pymupdf.open(path)
    hi = min(hi, len(document))
    types: dict[str, dict[int, str]] = {}

    for number in range(lo, hi + 1):
        page = document[number - 1]
        words = words_on(page)
        headings = []
        for x0, y0, x1, _y1, text, *_ in words:
            match = TYPE_HEADING.match(text)
            if match:
                headings.append((y0, match.group(1)))
        # "Type 1a" is often split as two words; catch that too.
        for index, (x0, y0, x1, _y1, text, *_rest) in enumerate(words):
            if text == "Type" and index + 1 < len(words):
                nxt = words[index + 1][4]
                if re.match(r"^\d+[a-z]?$", nxt):
                    headings.append((y0, nxt))
        if not headings:
            continue
        headings.sort()

        for y, columns in bit_rows(words):
            digits = digits_under(words, y, columns)
            if not digits:
                continue
            # The types named most recently above this row share the figure.
            owners = [name for hy, name in headings if hy < y]
            if not owners:
                continue
            # A page lists its types together, then draws one grid per group.
            for name in owners:
                entry = types.setdefault(name, {})
                for bit, char in digits.items():
                    entry.setdefault(bit, char)
    return types


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pgr", type=pathlib.Path)
    parser.add_argument("-o", "--out", type=pathlib.Path)
    args = parser.parse_args(argv)

    types = harvest(args.pgr)
    print(f"{len(types)} instruction types with printed opcode bits\n")
    print(f"{'type':>7}  {'bits':>4}  fixed bits, high to low")
    for name in sorted(types, key=lambda s: (int(re.match(r'\d+', s).group()), s)):
        bits = types[name]
        shown = " ".join(f"{b}={bits[b]}" for b in sorted(bits, reverse=True)[:12])
        print(f"{name:>7}  {len(bits):>4}  {shown}")

    if args.out:
        args.out.write_text(
            json.dumps({k: {str(b): v for b, v in sorted(s.items(), reverse=True)}
                        for k, s in types.items()}, indent=2),
            encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

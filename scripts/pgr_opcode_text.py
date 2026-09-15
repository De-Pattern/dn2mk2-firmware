"""Read the classic SHARC PGR's opcode tables, for cross-checking Rev 1.5.

**INCOMPLETE -- this does not work yet, and its output must not be used.** The
document is identified and its layout understood (both below), and two real
bugs are fixed, but the digits are still not landing on the right bits. A
cross-check whose second source is misread is worse than no cross-check, so no
numbers from this are reported anywhere until it is right.

Fixed so far, both worth keeping:

- **The figure was reading its own axis.** The bit-number row is keyed on a
  rounded y while its own words sit a fraction lower, so a window starting at
  `y` admitted the row itself -- and `11`, `10`, `1` and `0` are all valid bit
  strings. That is exactly why types 1a, 8a, 13a and 14a first came out with
  the identical set `11,10,1,0`.
- **One heading was owning every row below it.** A page carries several types,
  each with its own grid; a heading owns only the rows before the next
  heading.

Still wrong: **Type 1a extracts one fixed bit where the page plainly prints
`001` across bits 47..45.** The digit run extracts as a single compact word
about one cell wide, so neither splitting its box evenly nor using the
per-character boxes from `rawdict` places the three digits in three columns.
Whatever positions those digits, it is not in the text layer where it has been
looked for. The next thing to try is the stroked grid itself -- deriving cell
boundaries from the vertical rules and assigning digits to the cell they fall
inside -- rather than matching against bit-number centres.

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


def character_index(page):
    """-> {(rounded y, text): [(char, centre x)]} from character-level boxes.

    `get_text("words")` gives one box per word, and in this manual a run of
    opcode digits is one word whose box is roughly a single cell wide even
    when the digits are drawn across several cells. Only the per-character
    boxes say where each digit actually sits.
    """
    index = {}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.get("chars") or []
                if not chars:
                    continue
                text = "".join(c["c"] for c in chars).strip()
                if not text:
                    continue
                key = (round(chars[0]["bbox"][1], 1), text)
                index.setdefault(key, [
                    (c["c"], (c["bbox"][0] + c["bbox"][2]) / 2) for c in chars
                ])
    return index


CHAR_INDEX: dict = {}


def char_centres(text, x0, x1):
    """-> [(char, centre x)] preferring real character boxes over a split box."""
    for (_y, key), chars in CHAR_INDEX.items():
        if key == text:
            placed = [(c, x) for c, x in chars if not c.isspace()]
            if len(placed) == len(text) and x0 - 2 <= placed[0][1] <= x1 + 2:
                return placed
    span = max(len(text), 1)
    width = (x1 - x0) / span
    return [(c, x0 + width * (i + 0.5)) for i, c in enumerate(text)]


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


def field_bounds(page, y, depth=60.0):
    """-> sorted x of the FIELD boundaries under a bit-number row.

    The manual draws two heights of vertical rule: short ones (~16pt) between
    the bit numbers, and tall ones (~50pt) separating the named fields in the
    row beneath. The tall ones are what matter, because a digit run is
    **centred in its field**, not placed per cell -- `001` is one centred label
    spanning bits 47..45, which is why every attempt to position individual
    characters failed. Read the field, then hand its digits to its cells in
    order.
    """
    out = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width <= 2 and 30 <= rect.height <= 80 and y < rect.y0 <= y + depth:
            out.append(rect.x0)
    return sorted(out)


def digits_by_field(page, words, y, columns, skip=8.0, depth=60.0):
    """-> {bit: '0'|'1'} by assigning each centred digit run to its field."""
    bounds = field_bounds(page, y)
    if not bounds:
        return {}
    ordered = sorted(columns.items(), key=lambda kv: kv[1], reverse=True)  # high bit first
    out = {}
    for x0, y0, x1, _y1, text, *_ in words:
        if not (y + skip <= y0 <= y + depth) or not BITS_ONLY.match(text):
            continue
        centre = (x0 + x1) / 2
        # The field this label sits in, from the tall rules around it.
        lower = max([b for b in bounds if b <= centre], default=None)
        upper = min([b for b in bounds if b > centre], default=None)
        if lower is None or upper is None:
            continue
        cells = [bit for bit, bit_x in ordered if lower < bit_x < upper]
        if len(cells) != len(text):
            continue                    # not a clean field-wide run; skip it
        for bit, char in zip(cells, text):
            out.setdefault(bit, char)
    return out


def digits_under(words, y, columns, skip=8.0, depth=30.0):
    """-> {bit: '0'|'1'} for printed opcode digits below a bit-number row.

    A run like `001` is one text item spanning three cells, so its characters
    are distributed across the cells its box covers rather than assigned whole.

    `skip` matters more than it looks. The bit-number row is keyed on a rounded
    y, while its own words sit a fraction lower, so a window starting at `y`
    admits the row itself -- and the labels `11`, `10`, `1` and `0` are all
    valid bit strings. That is precisely how types 1a, 8a, 13a and 14a came out
    with the identical set 11,10,1,0: the figure was reading its own axis.
    """
    pitch = None
    ordered = sorted(columns.items(), key=lambda kv: kv[1])
    if len(ordered) >= 2:
        pitch = abs(ordered[1][1] - ordered[0][1])
    out = {}
    left = min(columns.values())
    right = max(columns.values())
    for x0, y0, x1, _y1, text, *_ in words:
        if not (y + skip <= y0 <= y + depth) or not BITS_ONLY.match(text):
            continue
        # Page furniture sits outside the grid; the grid is what the bit
        # numbers span.
        if x1 < left - 10 or x0 > right + 10:
            continue
        # Each character has to be placed by its OWN position. A run like
        # `001` extracts as one compact word whose box is about a single cell
        # wide, so dividing the box evenly puts all three characters in the
        # same column and the first one wins -- which is why Type1a came out
        # with one fixed bit instead of three.
        for char, centre in char_centres(text, x0, x1):
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
        CHAR_INDEX.clear()
        CHAR_INDEX.update(character_index(page))
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

        rows = bit_rows(words)
        if not rows:
            continue
        # One heading owns the rows between it and the NEXT heading, not every
        # row below it. A page carries several types, each with its own grid,
        # and giving every heading every row merges unrelated figures --
        # which is what made Type1a come out with bits from Type3a's grid.
        bounds = [hy for hy, _n in headings] + [float("inf")]
        for index, (hy, name) in enumerate(headings):
            upper = bounds[index + 1]
            mine = [(y, cols) for y, cols in rows if hy < y < upper]
            if not mine:
                continue
            entry = types.setdefault(name, {})
            for y, columns in mine:
                found = digits_by_field(page, words, y, columns)
                if not found:
                    found = digits_under(words, y, columns)
                for bit, char in found.items():
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

"""Extract SHARC+ instruction opcode figures from Analog Devices' PRM.

The SHARC+ VISA encodings are published as *figures*: a row of bit cells, each
carrying its bit number above and its fixed value inside, with cells belonging
to no named field drawn shaded. Reading them by eye is the bottleneck in every
attempt to build a SHARC disassembler, and it is where `m-dwyer/digikit` lost
most of its decoder to one misread figure -- "Type5b_move, eight gray cells
recorded as none", which suppressed 88-93% of all instruction walks.

**The shading is data, not a picture.** Each cell is a vector rectangle with a
fill colour in the PDF's content stream, and every bit number and value is real
text at a known position. So the figures can be read mechanically, exactly, and
reproducibly -- no OCR, no vision model, no 400-DPI squinting.

## The trap that makes this worth automating

A shaded *run* is ONE rectangle spanning several cells, not one rectangle per
cell. The seven shaded cells at bits 22..16 of Type5b_move are a single
63-point box. Count boxes instead of cells and you get 2 where the answer is 8,
which is exactly the "recorded as none" failure -- and it is not carelessness,
it is the file's structure inviting the error. This script converts each filled
rectangle's width back into a cell count, so the run can only be read one way.

## Which document

Measured against **SHARC+ Core Programming Reference, Part Number
82-100131-01, Revision 1.5**, 798 pages, `sha256
a3edf83beb75b44a77f8366cf54c0353083ab49a1c69d8179d2b727ba7ba1470`.

Revision matters: an earlier copy in circulation has 771 pages and carries the
instruction set in chapter 12 rather than 14-15. Tables extracted from
different revisions are not comparable, and a disagreement between them is not
evidence that either is wrong.

## Self-check

Bit labels are read from the page rather than assumed, so a mis-mapped cell row
shows up as a bit sequence that is not a clean descending run. `--check`
reports any such row. All 136 rows of Rev 1.5 pass.

Usage:
    python scripts/prm_opcode_figures.py <prm.pdf> --pages 300-440
    python scripts/prm_opcode_figures.py <prm.pdf> --pages 343 --check
"""

import argparse
import collections
import pathlib
import sys

try:
    import pymupdf
except ImportError:  # pragma: no cover - dependency is optional and external
    sys.exit("needs pymupdf:  python -m pip install pymupdf")

CELL_WIDTH = 9.0          # points; every bit cell in the PRM is exactly this
SHADE = 0.8235            # the grey ADI fills non-field cells with
SHADE_TOLERANCE = 0.05
MIN_TICKS = 4             # cell dividers, to tell a bit row from any other box


def parse_pages(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = (int(v) for v in part.split("-", 1))
            out.extend(range(lo, hi + 1))
        elif part:
            out.append(int(part))
    return out


def cell_rows(page):
    """-> {y0: {'frame': Rect, 'fills': [Rect], 'ticks': int}} for bit rows only.

    A bit row is a stroked frame at least two cells wide, with the vertical
    dividers between cells drawn as zero-width strokes at the same y.
    """
    found = collections.defaultdict(lambda: {"frame": None, "fills": [], "ticks": 0})
    for drawing in page.get_drawings():
        rect, kind, fill = drawing["rect"], drawing.get("type"), drawing.get("fill")
        slot = found[round(rect.y0, 1)]
        if kind == "s" and rect.width == 0:
            slot["ticks"] += 1
        elif kind == "s" and rect.width >= 2 * CELL_WIDTH and 8 <= rect.height <= 10:
            if slot["frame"] is None or rect.width > slot["frame"].width:
                slot["frame"] = rect
        elif kind == "f" and fill and all(
            abs(c - SHADE) < SHADE_TOLERANCE for c in fill[:3]
        ):
            slot["fills"].append(rect)
    return {
        y: slot for y, slot in found.items()
        if slot["frame"] is not None and slot["ticks"] >= MIN_TICKS
    }


def word_at(words, centre_x, y_low, y_high):
    for item in words:
        x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], item[4]
        if y_low <= y0 <= y_high and x0 - 2.5 <= centre_x <= x1 + 2.5:
            return text
    return "?"


def read_row(y, row, words):
    """-> (cell count, [(bit label, printed value, shaded)])."""
    frame = row["frame"]
    count = int(round(frame.width / CELL_WIDTH))

    shaded: set[int] = set()
    for fill in row["fills"]:
        first = int(round((fill.x0 - frame.x0) / CELL_WIDTH))
        # A run is one rectangle spanning several cells -- this is the bit that
        # is misread by hand. Width, not rectangle count, gives the answer.
        span = max(1, int(round(fill.width / CELL_WIDTH)))
        shaded.update(k for k in range(first, first + span) if 0 <= k < count)

    cells = []
    for k in range(count):
        centre = frame.x0 + (k + 0.5) * CELL_WIDTH
        cells.append((
            word_at(words, centre, y - 13, y - 1),          # bit number, above
            word_at(words, centre, y - 0.5, y + CELL_WIDTH),  # value, inside
            k in shaded,
        ))
    return count, cells


def descending(cells) -> bool:
    labels = [b for b, _, _ in cells]
    if any(not b.isdigit() for b in labels):
        return False
    numbers = [int(b) for b in labels]
    return all(b == a - 1 for a, b in zip(numbers, numbers[1:]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=pathlib.Path)
    parser.add_argument("--pages", default="300-440",
                        help="page numbers or ranges, e.g. 343 or 300-440")
    parser.add_argument("--check", action="store_true",
                        help="report only rows whose bit labels are not a clean "
                             "descending run -- a mis-mapped row cannot hide")
    args = parser.parse_args(argv)

    document = pymupdf.open(args.pdf)
    rows_seen = bad = 0

    for number in parse_pages(args.pages):
        if not 1 <= number <= len(document):
            continue
        page = document[number - 1]
        rows = cell_rows(page)
        if not rows:
            continue
        words = page.get_text("words")
        heading = (page.get_text().strip().splitlines() or ["?"])[0]
        printed = False

        for y in sorted(rows):
            count, cells = read_row(y, rows[y], words)
            rows_seen += 1
            ok = descending(cells)
            if not ok:
                bad += 1
            if args.check and ok:
                continue
            if not printed:
                print(f"===== page {number}   [{heading[:60]}] =====")
                printed = True
            bits = " ".join(f"{b:>2}" for b, _, _ in cells)
            values = " ".join(f"{v:>2}" for _, v, _ in cells)
            mask = " ".join(" #" if s else " ." for _, _, s in cells)
            flag = "" if ok else "   <- BIT LABELS NOT A DESCENDING RUN"
            print(f"  row y={y}  {count} cells{flag}")
            print(f"    bit   {bits}")
            print(f"    value {values}")
            print(f"    fixed {mask}      ('#' = shaded, i.e. not a field bit)")
            fixed = [b for b, _, s in cells if s]
            print(f"    shaded bits: {', '.join(fixed) or '(none)'}   ({len(fixed)} cells)")
        if printed:
            print()

    print(f"{rows_seen} cell rows read, {bad} failed the descending-bit check")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

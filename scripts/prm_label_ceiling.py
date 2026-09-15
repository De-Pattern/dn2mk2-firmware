"""How much of the SHARC+ encoding can be recovered from the figures at all?

`prm_visa_tables.py` accounts for a bit when it is either a fixed opcode bit or
inside a named field. It reaches 87.64%. The obvious question is whether the
remainder is our extractor or the document, and the answer decides whether
chasing 100% is work or wishful thinking.

It is answerable directly. A field is named by a bracket drawn beneath its bit
row; where a row has **no brackets beneath it at all**, the PRM does not name
those bits in the figure, and no amount of geometry will recover them. Their
names, where they exist, are in the syntax tables instead.

This script separates the two. Rows with brackets that we failed to read are
our problem; rows with no brackets are the document's, and together they give
the ceiling on figure-only extraction.

Usage:
    python scripts/prm_label_ceiling.py <prm.pdf>
"""

import argparse
import collections
import pathlib
import sys

try:
    import pymupdf
except ImportError:  # pragma: no cover
    sys.exit("needs pymupdf:  python -m pip install pymupdf")

CELL_WIDTH = 9.0
SHADE = 0.8235
SHADE_TOLERANCE = 0.05
MIN_TICKS = 4
PAGES = (308, 425)
BRACKET_BAND = 40.0     # points below a row within which its brackets sit


def cell_rows(page):
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=pathlib.Path)
    args = parser.parse_args(argv)

    document = pymupdf.open(args.pdf)
    total = fixed_bits = labelled_rows_bits = unlabelled_rows_bits = 0
    unlabelled_rows = []

    for number in range(PAGES[0], min(PAGES[1], len(document)) + 1):
        page = document[number - 1]
        rows = cell_rows(page)
        if not rows:
            continue
        strokes = [d for d in page.get_drawings()
                   if d.get("type") == "s" and d["rect"].width > 0]
        for y in sorted(rows):
            row = rows[y]
            frame = row["frame"]
            count = int(round(frame.width / CELL_WIDTH))
            shaded = set()
            for fill in row["fills"]:
                first = int(round((fill.x0 - frame.x0) / CELL_WIDTH))
                span = max(1, int(round(fill.width / CELL_WIDTH)))
                shaded.update(k for k in range(first, first + span) if 0 <= k < count)

            bottom = y + CELL_WIDTH
            # The NEXT bit row's own frame sits inside this row's bracket band
            # and is the same shape as a long bracket, so counting it marks
            # every row as labelled and overstates the ceiling. Exclude any
            # stroke that is itself a row frame.
            frames = {round(other["frame"].y0, 1) for other in rows.values()}
            has_bracket = any(
                bottom - 1 <= d["rect"].y0 <= bottom + BRACKET_BAND
                and round(d["rect"].y0, 1) not in frames
                and frame.x0 - 12 <= d["rect"].x1
                and d["rect"].x0 <= frame.x1 + 12
                for d in strokes
            )
            total += count
            fixed_bits += len(shaded)
            free = count - len(shaded)
            if has_bracket:
                labelled_rows_bits += free
            else:
                unlabelled_rows_bits += free
                if free:
                    unlabelled_rows.append((number, y, free))

    ceiling = 100.0 * (fixed_bits + labelled_rows_bits) / total
    print(f"bits across all figure rows            : {total:,}")
    print(f"  fixed (shaded) bits                  : {fixed_bits:,}")
    print(f"  free bits on rows that HAVE brackets : {labelled_rows_bits:,}")
    print(f"  free bits on rows with NO brackets   : {unlabelled_rows_bits:,}")
    print()
    print(f"CEILING on figure-only bit accounting  : {ceiling:.2f}%")
    print(f"  the remaining {100 - ceiling:.2f}% is unnamed in the figures; those "
          f"names live in the syntax tables")
    print(f"\n{len(unlabelled_rows)} rows carry no brackets at all:")
    for number, y, free in unlabelled_rows[:16]:
        print(f"    p{number}  row y={y:<7} {free:>3} unnamed bits")
    if len(unlabelled_rows) > 16:
        print(f"    ... and {len(unlabelled_rows) - 16} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

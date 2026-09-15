"""Build a machine-readable SHARC+ VISA opcode table from Analog Devices' PRM.

`prm_opcode_figures.py` prints the figures for a human. This emits them as JSON
for a decoder: one entry per instruction form, carrying the name, the ISA/VISA
mode, the encoding width, and the fixed-bit mask and value.

Three things the figures do not say out loud, all of which a decoder needs:

**Forms are 16, 32 or 48 bits.** VISA is variable, and a figure's width is the
number of bit cells it draws. Slicing "the top 8 bits" at 47..40 is meaningless
for a form whose figure starts at bit 31 or 15.

**ISA and VISA never share a decode context.** The processor runs one or the
other, so a 48-bit ISA form and a 32-bit VISA form of the same instruction are
not competing interpretations of the same bytes. Comparing across the two
measures nothing; the `mode` field is here so callers can partition first.

**Patterns nest.** A form with few fixed bits subsumes stricter forms inside
its pattern space, so decode order is load-bearing: test most-specific first.
`--subsume` reports every such pair. Getting this wrong is not a cosmetic
error -- an over-permissive pattern consumes instructions belonging to a
narrower one, and because the forms differ in length, the walk desynchronises
from there on.

Measured against **Part Number 82-100131-01, Revision 1.5**, 798 pages,
sha256 a3edf83beb75b44a77f8366cf54c0353083ab49a1c69d8179d2b727ba7ba1470.
An earlier 771-page revision carries the instruction set in chapter 12 rather
than 14-15; tables from different revisions are not comparable.

Usage:
    python scripts/prm_visa_tables.py <prm.pdf> -o visa.json
    python scripts/prm_visa_tables.py <prm.pdf> --subsume
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

CELL_WIDTH = 9.0
SHADE = 0.8235
SHADE_TOLERANCE = 0.05
MIN_TICKS = 4
FIGURE_PAGES = (308, 425)     # the instruction-set chapters in Rev 1.5


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


def word_at(words, centre_x, y_low, y_high):
    for item in words:
        if y_low <= item[1] <= y_high and item[0] - 2.5 <= centre_x <= item[2] + 2.5:
            return item[4]
    return None


# Caption tails are not consistent in the PRM: "... Instruction", "... Syntax",
# "... Opcode", "... Instruction Opcode", "... Computation Opcode". Capture
# everything after the number and strip whichever tail is present, rather than
# matching one of them and silently dropping the other figures.
CAPTION = re.compile(r"Figure\s+\d+-\d+:\s*(.+?)\s*$")
CAPTION_TAIL = re.compile(
    r"\s+(?:Computation\s+Opcode|Instruction\s+Opcode|Instruction|Computation|Opcode|Syntax)\s*$",
    re.IGNORECASE,
)


def captions(page):
    """-> [(y, name)] for every figure caption, in page order.

    The caption below a figure is the only naming that is present for *every*
    one of them. The `TypeNa_form` token drawn to the left of the first row is
    absent on about a third -- including every 16-bit form -- and keying on it
    silently merged those figures into whichever one preceded them.

    Captions also carry names that are not `TypeN` at all, such as
    `ShortCompute`, which a `Type\\d` pattern could never have matched.
    """
    found = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", [])).strip()
            match = CAPTION.match(text)
            if match:
                name = CAPTION_TAIL.sub("", match.group(1)).strip()
                if name:
                    found.append((line["bbox"][1], name))
    return sorted(found)


def caption_for(caption_list, y):
    """The first caption below this row -- a figure is captioned underneath."""
    for caption_y, name in caption_list:
        if caption_y > y:
            return name
    return None


def declared_modes(document, lo, hi):
    """-> {'5b': 'VISA', '9a': 'ISA/VISA', ...} from the section headings."""
    modes = {}
    for number in range(lo, hi + 1):
        text = document[number - 1].get_text()
        for match in re.finditer(r"Type\s?(\d+[a-z]?)\s+(ISA/VISA|VISA|ISA)\b", text):
            modes.setdefault(match.group(1), match.group(2))
    return modes


def read_row(y, row, words):
    frame = row["frame"]
    count = int(round(frame.width / CELL_WIDTH))
    shaded = set()
    for fill in row["fills"]:
        first = int(round((fill.x0 - frame.x0) / CELL_WIDTH))
        # A shaded RUN is one rectangle over several cells -- width, not
        # rectangle count, gives the answer. This is the trap.
        span = max(1, int(round(fill.width / CELL_WIDTH)))
        shaded.update(k for k in range(first, first + span) if 0 <= k < count)

    bits, fixed = [], {}
    for k in range(count):
        centre = frame.x0 + (k + 0.5) * CELL_WIDTH
        label = word_at(words, centre, y - 13, y - 1)
        value = word_at(words, centre, y - 0.5, y + CELL_WIDTH)
        if label is not None and label.isdigit():
            bit = int(label)
            bits.append(bit)
            if k in shaded and value in ("0", "1"):
                fixed[bit] = int(value)
    return bits, fixed


def extract(path, lo=FIGURE_PAGES[0], hi=FIGURE_PAGES[1]):
    document = pymupdf.open(path)
    hi = min(hi, len(document))
    modes = declared_modes(document, 1, len(document))
    forms, order = {}, []

    for number in range(lo, hi + 1):
        page = document[number - 1]
        rows = cell_rows(page)
        if not rows:
            continue
        words = page.get_text("words")
        page_captions = captions(page)
        current = None
        for y in sorted(rows):
            row = rows[y]
            bits, fixed = read_row(y, row, words)
            if not bits:
                continue
            # Rows belong to the figure whose caption sits below them, so two
            # figures on one page separate correctly and none is left unnamed.
            label = caption_for(page_captions, y) or f"unnamed@p{number}"
            if label != current:
                key = label
                suffix = 2
                while key in forms:
                    key = f"{label}#{suffix}"
                    suffix += 1
                family_match = re.match(r"^Type\s?(\d+[a-z]?)", label)
                forms[key] = {
                    "name": label,
                    "family": family_match.group(1) if family_match else None,
                    "mode": modes.get(family_match.group(1)) if family_match else None,
                    "page": number,
                    "width": 0,
                    "fixed": {},
                    "rows": [],
                }
                order.append(key)
                current = label
                current_key = key
            entry = forms[current_key]
            entry["width"] += len(bits)
            entry["rows"].append([max(bits), min(bits)])
            entry["fixed"].update({str(b): v for b, v in fixed.items()})

    return [forms[k] for k in order]


def descending_ok(entry) -> bool:
    return all(hi > lo for hi, lo in entry["rows"])


def pattern(entry):
    """-> (mask, value) as integers over the instruction word."""
    mask = value = 0
    for bit, bit_value in entry["fixed"].items():
        position = int(bit)
        mask |= 1 << position
        if bit_value:
            value |= 1 << position
    return mask, value


def subsumptions(entries):
    """(loose, strict) pairs: every word matching `strict` also matches `loose`."""
    pairs = []
    prepared = [(e, *pattern(e)) for e in entries]
    for loose, loose_mask, loose_value in prepared:
        if loose_mask == 0:
            continue
        for strict, strict_mask, strict_value in prepared:
            if loose is strict or loose["mode"] != strict["mode"]:
                continue
            if loose_mask & strict_mask != loose_mask:
                continue                       # loose is not a subset
            if strict_value & loose_mask != loose_value:
                continue                       # they disagree where they overlap
            if loose_mask == strict_mask:
                continue                       # identical, not nested
            pairs.append((loose, strict))
    return pairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=pathlib.Path)
    parser.add_argument("-o", "--out", type=pathlib.Path)
    parser.add_argument("--subsume", action="store_true",
                        help="report patterns that swallow others, and the decode "
                             "order that follows")
    args = parser.parse_args(argv)

    entries = extract(args.pdf)
    bad = [e for e in entries if not descending_ok(e)]

    print(f"{len(entries)} instruction forms from {args.pdf.name}")
    widths = collections.Counter(e["width"] for e in entries)
    print("  widths: " + ", ".join(f"{w}-bit x{c}" for w, c in sorted(widths.items())))
    modes = collections.Counter(e["mode"] for e in entries)
    print("  modes:  " + ", ".join(f"{m}: {c}" for m, c in sorted(
        modes.items(), key=lambda kv: str(kv[0]))))
    print(f"  rows failing the descending-bit check: {len(bad)}")

    if args.subsume:
        pairs = subsumptions(entries)
        print(f"\n{len(pairs)} subsumption pairs, same mode (loose -> strict)")
        print("A decoder must test the strict pattern FIRST.\n")
        print(f"{'loose':<22}{'bits':>5}{'len':>5}   swallows   {'strict':<22}{'bits':>5}{'len':>5}")
        for loose, strict in sorted(pairs, key=lambda p: len(p[0]["fixed"])):
            print(f"{loose['name']:<22}{len(loose['fixed']):>5}{loose['width']:>5}"
                  f"      ->      {strict['name']:<22}{len(strict['fixed']):>5}{strict['width']:>5}")
        worst = collections.Counter(loose["name"] for loose, _ in pairs)
        if worst:
            print("\nmost permissive patterns:")
            for name, count in worst.most_common(6):
                entry = next(e for e in entries if e["name"] == name)
                print(f"  {name}: {len(entry['fixed'])} fixed bits, "
                      f"{entry['width']}-bit form, swallows {count}")

    if args.out:
        payload = {
            "source": {
                "document": "SHARC+ Core Programming Reference",
                "part_number": "82-100131-01",
                "revision": "1.5",
                "pages": 798,
                "sha256": "a3edf83beb75b44a77f8366cf54c0353083ab49a1c69d8179d2b727ba7ba1470",
            },
            "forms": entries,
        }
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

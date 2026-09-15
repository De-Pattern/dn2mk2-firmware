"""Extract the SHARC+ compute-field encoding tables from the PRM.

The opcode figures give each instruction's skeleton, and for the multifunction
forms that skeleton is nearly all operand: Type1a fixes **three bits out of
forty-eight**. On its own such a pattern matches one word in eight, which is
why a table built from figures alone scores about as well on random bytes as on
real code.

What makes those words instructions is the **compute field** they carry. Chapter
18 lists which compute operations exist, as ordinary text tables:

    Table 18-1   SINGLEFN coding      MF bit [22], CU bits [21:20], opcode [19:12]
    Table 18-4   MULTIFN coding       MF bit [22], opcode [21:16]
    Table 18-5   ALUOP encoding       opcode [19:12] -> operation
    Table 18-7   MULOP encoding
    Table 18-9   SHIFTOP / SHIFTIMM encoding

A compute field whose opcode is not in these tables is not a compute field, so
the instruction that claimed to hold it is a mis-decode. That is the constraint
that separates real code from noise, and it lives in text rather than in the
figures -- which is the reason a figures-only table plateaus.

Usage:
    python scripts/prm_compute_tables.py <prm.pdf> -o compute.json
"""

import argparse
import json
import pathlib
import re
import sys

try:
    import pymupdf
except ImportError:  # pragma: no cover
    sys.exit("needs pymupdf:  python -m pip install pymupdf")

CHAPTER = (420, 440)
CAPTION = re.compile(r"Table\s+(\d+-\d+):\s*(.+)")
# "opcode (bits 19-12)". The dash is U+2212 MINUS SIGN here, not the hyphen or
# the en dash it looks like -- matching only those finds nothing at all, which
# reads as "the tables are not there" rather than "the regex is wrong".
DASH = "-‐‑‒–—―−"
# A column header naming a bit range. The field is not always called "opcode":
# Table 18-9 carries TWO encodings side by side, headed "shiftimm (bits 21-16)"
# and "shiftop (bits 19-12)". Matching the literal word "opcode" finds neither,
# which reads as the SHIFTOP tables being absent from the document.
HEADER = re.compile(rf"([A-Za-z][A-Za-z0-9_]*)\s*\(bits\s*(\d+)\s*[{DASH}]\s*(\d+)\)",
                    re.I)
# An opcode cell is a MASKED PATTERN, not a value, and the three families write
# it differently:
#
#   ALUOP     00011000     plain bits
#   MULOP     0000 F00x    space-grouped, letters for variable bits (F, x, y, r)
#   SHIFTOP   11 0 0 __ __ space-grouped, underscores for variable bits
#
# So the rule is: 0 and 1 are fixed, every other character is one wildcard bit,
# and spaces are grouping. Reading these as values -- requiring ^[01]+$ --
# accepts ALUOP and silently discards every MULOP and SHIFTOP row, which reads
# as "those tables are not in the document".
BITS = re.compile(r"^[01A-Za-z_]+$")


def as_pattern(cell: str):
    """-> (width, mask, value) for an opcode cell, or None if it is not one."""
    text = cell.replace(" ", "").replace(" ", "")
    if not text or not BITS.match(text):
        return None
    if not any(c in "01" for c in text):
        return None                      # all wildcards names nothing
    mask = value = 0
    for char in text:
        mask <<= 1
        value <<= 1
        if char in "01":
            mask |= 1
            if char == "1":
                value |= 1
    return len(text), mask, value

FAMILIES = {
    "ALUOP": re.compile(r"\bALUOP\b", re.I),
    "MULOP": re.compile(r"\bMULOP\b", re.I),
    "SHIFTOP": re.compile(r"SHIFTOP|SHIFTIMM", re.I),
    "DUALADDSUB": re.compile(r"Dual add/subtract", re.I),
}


def captions_on(page):
    """-> [(y, number, text)] positioned, so a table can be paired with the
    caption above it.

    Pages carry several tables. Keying a whole page to one family drops every
    table on any page that mixes them -- which silently lost MULOP and SHIFTOP
    while ALUOP came through, and looked like those tables were missing from
    the document.
    """
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", [])).strip()
            match = CAPTION.match(text)
            if match:
                out.append((line["bbox"][1], match.group(1), match.group(2).strip()))
    return sorted(out)


def caption_above(caption_list, y):
    best = None
    for caption_y, _number, text in caption_list:
        if caption_y <= y + 2:
            best = text
    return best


def family_of(caption):
    for name, pattern in FAMILIES.items():
        if pattern.search(caption):
            return name
    return None


def harvest(path, lo=CHAPTER[0], hi=CHAPTER[1]):
    document = pymupdf.open(path)
    hi = min(hi, len(document))
    found = {name: {} for name in FAMILIES}
    carried = None

    for number in range(lo, hi + 1):
        page = document[number - 1]
        page_captions = captions_on(page)
        if not any(family_of(text) for _y, _n, text in page_captions):
            continue
        try:
            tables = page.find_tables()
        except Exception:
            continue

        for table in tables:
            rows_preview = table.extract()
            # Three ways a table announces its family, in order of reliability:
            # its own first row (the PRM often puts the caption inside the
            # table), the caption positioned above it, and -- for a
            # "(Continued)" table whose caption is on the previous page --
            # whichever family was last seen.
            inline = " ".join(c or "" for c in (rows_preview[0] if rows_preview else []))
            family = (family_of(inline)
                      or family_of(caption_above(page_captions, table.bbox[1]) or "")
                      or carried)
            if family:
                carried = family
            rows = table.extract()
            if len(rows) < 2:
                continue

            # EVERY column that declares a bit range, not just the first.
            # Table 18-9 puts shiftimm (21-16) and shiftop (19-12) side by side
            # in one table, so reading column 0 alone loses half the encoding
            # and mislabels the other half.
            columns = {}
            header_index = None
            for index, row in enumerate(rows[:3]):
                for column, cell in enumerate(row):
                    match = HEADER.search(cell or "")
                    if match:
                        columns[column] = (
                            match.group(1).lower(),
                            (int(match.group(2)), int(match.group(3))),
                        )
                if columns:
                    header_index = index
                    break
            if not columns or family is None:
                continue

            for row in rows[header_index + 1:]:
                cells = [(c or "").strip() for c in row]
                for column, (field, span) in columns.items():
                    if column >= len(cells):
                        continue
                    pattern = as_pattern(cells[column])
                    if pattern is None:
                        continue
                    width, mask, value = pattern
                    # Two encodings in one table are two families, not one.
                    target = family
                    if field in ("shiftimm", "shiftop"):
                        target = field.upper()
                        found.setdefault(target, {})
                    # The syntax sits in the column right of its own opcode.
                    syntax = cells[column + 1] if column + 1 < len(cells) else ""
                    found[target].setdefault(
                        cells[column],
                        {
                            "field": field,
                            "bits": list(span),
                            "width": width,
                            "mask": mask,
                            "value": value,
                            "syntax": syntax,
                            "instruction": cells[-1] if len(cells) > 2 else "",
                            "page": number,
                        },
                    )
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=pathlib.Path)
    parser.add_argument("-o", "--out", type=pathlib.Path)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)

    found = harvest(args.pdf)
    total = 0
    for name, codes in found.items():
        if not codes:
            print(f"{name:<12} none found")
            continue
        widths = sorted({len(c) for c in codes})
        spans = sorted({tuple(v["bits"]) for v in codes.values()})
        total += len(codes)
        print(f"{name:<12} {len(codes):>4} encodings, "
              f"code widths {widths}, bit spans {spans}")
        if args.show:
            for code, entry in sorted(codes.items()):
                print(f"    {code}  {entry['instruction'][:60]}")

    print(f"\n{total} compute encodings in total")
    # Patterns carry wildcards, so what matters is how much of the value space
    # they admit between them -- not how many rows there are.
    for name, codes in found.items():
        by_width = {}
        for entry in codes.values():
            by_width.setdefault(entry["width"], []).append(entry)
        for width, entries in sorted(by_width.items()):
            space = 1 << width
            admitted = set()
            for entry in entries:
                free = [b for b in range(width) if not (entry["mask"] >> b) & 1]
                for combination in range(1 << len(free)):
                    candidate = entry["value"]
                    for index, bit in enumerate(free):
                        if (combination >> index) & 1:
                            candidate |= 1 << bit
                    admitted.add(candidate)
            print(f"  {name} {width}-bit: {len(entries)} patterns admitting "
                  f"{len(admitted)} of {space} values "
                  f"({100 * len(admitted) / space:.1f}%)")

    if args.out:
        args.out.write_text(json.dumps(found, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

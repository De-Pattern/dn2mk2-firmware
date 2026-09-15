"""Extract the SHARC+ register-class OPCODES from the PRM's chapter 27.

**This corrects `prm_register_classes.py`, and the correction matters.** That
script reads Table 2-1 (pages 53-55), which lists each class's membership by
name, and concluded from it that the PRM publishes no register encodings and
that the classes therefore constrain nothing. Both halves were wrong, because
the encodings are in a chapter nobody had looked at.

Chapter 27, "Register (reg) Opcodes", from page 536, gives each class its own
`Code | Syntax` table:

    B1REG Register Class
    Code   Syntax
    100    b12
    101    b13

That is the mnemonic-to-bits mapping, per class, and it is what makes a
register field able to reject a value. The earlier conclusion came from
searching pages 308-425 -- the instruction figures -- and generalising from
Table 2-1 without asking whether another chapter carried the codes. It did.

Chapter 26 from page 531 does the same for immediate and constant types.

Usage:
    python scripts/prm_register_opcodes.py <prm.pdf> -o register_opcodes.json
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

CHAPTER = (531, 566)
CLASS_HEADING = re.compile(r"^([A-Z][A-Z0-9]*)\s+(?:Register\s+Class|Register\s+Type)\s*$")
CODE = re.compile(r"^[01]+$")


def headings(page):
    """-> [(y, class name)] for each 'XXX Register Class' heading on the page."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", [])).strip()
            match = CLASS_HEADING.match(text)
            if match:
                out.append((line["bbox"][1], match.group(1)))
    return sorted(out)


def owner(heading_list, y, carried):
    """The class whose heading most recently precedes this table."""
    best = carried
    for heading_y, name in heading_list:
        if heading_y <= y + 2:
            best = name
    return best


def harvest(path, lo=CHAPTER[0], hi=CHAPTER[1]):
    document = pymupdf.open(path)
    hi = min(hi, len(document))
    classes: dict[str, dict[str, str]] = {}
    carried = None

    for number in range(lo, hi + 1):
        page = document[number - 1]
        heading_list = headings(page)
        try:
            finder = page.find_tables()
        except Exception:
            continue
        for table in finder:
            rows = table.extract()
            if len(rows) < 2:
                continue
            # Only inherit the previous page's class when this page declares no
            # class at all -- a genuine continuation. Carrying it into a page
            # that has headings lets one class absorb another's codes, which
            # showed up as SYSREG holding 142 codes for a 7-bit field.
            if heading_list:
                name = owner(heading_list, table.bbox[1], None)
            else:
                name = carried
            if not name:
                continue
            carried = name
            # The table is a plain Code | Syntax pair. Its header may or may
            # not be captured as a row, so accept any row whose first cell is
            # a run of bits.
            for row in rows:
                cells = [(c or "").replace("\n", " ").strip() for c in row]
                if len(cells) < 2:
                    continue
                code, syntax = cells[0], cells[1]
                if not CODE.match(code) or not syntax:
                    continue
                classes.setdefault(name, {}).setdefault(code, syntax)
    return classes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=pathlib.Path)
    parser.add_argument("-o", "--out", type=pathlib.Path)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)

    classes = harvest(args.pdf)
    total = sum(len(v) for v in classes.values())
    print(f"{len(classes)} register classes with opcodes, {total} codes\n")
    print(f"{'class':<16}{'codes':>7}{'width':>7}{'space':>7}  admitted   constrains?")
    suspect = []
    for name, codes in sorted(classes.items(), key=lambda kv: -len(kv[1])):
        widths = {len(c) for c in codes}
        # Codes of mixed width in one class mean the attribution is wrong, not
        # that the class is odd. Say so rather than reporting a percentage of
        # the wrong denominator.
        if len(widths) > 1:
            suspect.append((name, sorted(widths), len(codes)))
            continue
        width = widths.pop()
        space = 1 << width
        share = 100 * len(codes) / space
        verdict = "no" if share >= 99.9 else f"yes, rejects {space - len(codes)}"
        print(f"{name:<16}{len(codes):>7}{width:>7}{space:>7}  {share:>6.1f}%   {verdict}")
    if suspect:
        print(f"\n{len(suspect)} classes hold codes of MIXED width -- attribution "
              f"is wrong for these, not reported above:")
        for name, widths, count in suspect:
            print(f"  {name:<16} widths {widths}, {count} codes")
        if args.show:
            for code in sorted(codes):
                print(f"      {code}  {codes[code]}")

    if args.out:
        args.out.write_text(json.dumps(classes, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

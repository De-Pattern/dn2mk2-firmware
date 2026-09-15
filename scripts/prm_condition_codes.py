"""Extract the SHARC+ IF condition mnemonics, and measure whether `cond` constrains.

`cond` is a 5-bit field carried by a large share of the instruction forms, so
if only some of its 32 values named a real condition it would be a useful
constraint on a decoder. Table 4-20, "IF Condition Mnemonics" (pages 156-157),
is where the conditions are defined.

**It gives mnemonics, not encodings** -- the same shape as Table 2-1 for the
register classes. Nothing in the PRM maps a condition mnemonic to the bits that
select it. So, as with the registers, cardinality is all that is recoverable,
and cardinality is the question that matters anyway: a field whose values are
all legal rejects nothing.

The per-type tables do not help either. Each instruction's "opcode field values
(cond)" table carries exactly two rows -- `11111` for the unconditional form
and `-----` for "any condition" -- across all 19 pages that have one. They say
which syntax a value selects, never which values exist.

Usage:
    python scripts/prm_condition_codes.py <prm.pdf>
"""

import argparse
import pathlib
import re
import sys

try:
    import pymupdf
except ImportError:  # pragma: no cover
    sys.exit("needs pymupdf:  python -m pip install pymupdf")

TABLE_PAGES = (156, 158)
COND_FIELD_BITS = 5
# Mnemonics are short, upper-case, and may carry a NOT prefix.
MNEMONIC = re.compile(r"^(NOT\s+)?[A-Z][A-Z0-9_]{0,11}$")
NOT_MNEMONICS = {"MNEMONIC", "TRUE", "IF", "SIMD", "SISD", "ALU", "TABLE"}


def harvest(path, lo=TABLE_PAGES[0], hi=TABLE_PAGES[1]):
    document = pymupdf.open(path)
    found = []
    for number in range(lo, min(hi, len(document)) + 1):
        page = document[number - 1]
        try:
            finder = page.find_tables()
        except Exception:
            continue
        for table in finder:
            rows = table.extract()
            if len(rows) < 3:
                continue
            header = " ".join(c or "" for c in rows[1])
            if "Mnemonic" not in header:
                continue
            for row in rows[2:]:
                cells = [(c or "").replace("\n", " ").strip() for c in row]
                if not cells:
                    continue
                mnemonic = cells[-1]
                if not mnemonic or not MNEMONIC.match(mnemonic):
                    continue
                if mnemonic.upper() in NOT_MNEMONICS:
                    continue
                description = cells[1] if len(cells) > 1 else ""
                if not any(m["mnemonic"] == mnemonic for m in found):
                    found.append({"mnemonic": mnemonic, "description": description,
                                  "page": number})
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=pathlib.Path)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)

    conditions = harvest(args.pdf)
    space = 1 << COND_FIELD_BITS
    print(f"{len(conditions)} IF condition mnemonics from Table 4-20")
    if args.show:
        for entry in conditions:
            print(f"    {entry['mnemonic']:<10} {entry['description'][:56]}")

    print(f"\ncond is a {COND_FIELD_BITS}-bit field: {space} values")
    print(f"  mnemonics defined      : {len(conditions)}")
    print(f"  share of the field used : {100 * len(conditions) / space:.1f}%")
    if len(conditions) >= space - 2:
        print("\n  The field is effectively full, so `cond` rejects nothing and")
        print("  is no constraint on a decoder -- the same answer the register")
        print("  classes gave.")
    print("\nNo encodings: Table 4-20 names conditions and says when each is true.")
    print("Nothing in the PRM maps a mnemonic to the bits that select it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

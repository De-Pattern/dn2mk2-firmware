"""Extract the SHARC+ register classes and their membership from the PRM.

The opcode figures name their operand fields by class -- `srcureghigh[4:0]`,
`dstureg[6:0]`, `cond[4:0]` -- and a field is only as constraining as the
number of values its class actually admits. A 7-bit `ureg` field spans 128
values; if the UREG class holds 120 registers it constrains almost nothing,
and if it holds 60 it halves the space.

**The PRM does not publish the bit encodings.** Table 2-1, "SHARC+ Core
Register Types and Classes" (pages 53-55), gives each class its *membership by
name* -- `RREG = r0 - r15` -- and nothing anywhere in the document maps a
register name to the code that selects it. Those codes live in the assembler,
not the manual. So what is recoverable here is cardinality, not encoding, and
this script says so rather than implying more.

Cardinality is still worth having: it is what says whether a field is a real
constraint or a formality, and it is the difference between a table that can
reject a mis-decode and one that cannot.

Usage:
    python scripts/prm_register_classes.py <prm.pdf> -o registers.json
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

TABLE_PAGES = (53, 56)
# "r0 - r15", "i8 - i15", "r1:0 - r15:14". Found rather than split on, because
# a cell can hold several ranges separated only by a space -- RFREG's is
# "r0 - r15 f0 - f15", and splitting on commas reads that as one unparsable
# token and yields a class with one member instead of thirty-two.
RANGE = re.compile(r"([a-z]+)(\d+)(?::(\d+))?\s*[-‐-―−]\s*"
                   r"([a-z]+)(\d+)(?::(\d+))?", re.I)
BARE = re.compile(r"^[a-z][a-z0-9]*$", re.I)
CLASS_NAME = re.compile(r"^([A-Z][A-Z0-9]*(?:REG|DBL)[A-Z0-9]*)")


def members(cell: str) -> list[str]:
    """Expand one Registers cell into individual register names."""
    out: list[str] = []
    rest = cell
    for match in RANGE.finditer(cell):
        stem, first, last = match.group(1), int(match.group(2)), int(match.group(5))
        step = 2 if match.group(3) is not None else 1   # pair form r1:0 - r15:14
        for value in range(first, last + 1, step):
            out.append(f"{stem}{value}")
        rest = rest.replace(match.group(0), " ")
    # Whatever is not part of a range is a register named outright.
    for token in re.split(r"[,\s]+", rest):
        token = token.strip()
        if token and BARE.match(token):
            out.append(token)
    return out


def harvest(path, lo=TABLE_PAGES[0], hi=TABLE_PAGES[1]):
    document = pymupdf.open(path)
    classes: dict[str, dict] = {}
    current = None

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
            head = " ".join(c or "" for c in rows[1])
            if "Register Classes" not in head:
                continue
            for row in rows[2:]:
                cells = [(c or "").replace("\n", " ").strip() for c in row]
                if len(cells) < 3:
                    continue
                kind, class_cell, registers = cells[0], cells[1], cells[2]
                # A class cell names one or more classes; a blank one continues
                # the class above, because the PRM spreads a long membership
                # list over several rows.
                names = [n.strip().rstrip("*123456789")
                         for n in class_cell.split(",") if n.strip()]
                names = [n for n in names if CLASS_NAME.match(n)]
                if names:
                    for name in names:
                        classes.setdefault(name, {"type": kind, "members": [],
                                                  "pages": []})
                        if number not in classes[name]["pages"]:
                            classes[name]["pages"].append(number)
                    current = names
                if current and registers:
                    for name in current:
                        for member in members(registers):
                            if member not in classes[name]["members"]:
                                classes[name]["members"].append(member)
    return classes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=pathlib.Path)
    parser.add_argument("-o", "--out", type=pathlib.Path)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)

    classes = harvest(args.pdf)
    print(f"{len(classes)} register classes from Table 2-1\n")
    print(f"{'class':<14}{'members':>9}  {'bits needed':>12}  {'field span':>11}   type")
    for name, entry in sorted(classes.items(), key=lambda kv: -len(kv[1]["members"])):
        count = len(entry["members"])
        bits = max(1, (count - 1).bit_length())
        span = 1 << bits
        print(f"{name:<14}{count:>9}  {bits:>12}  {count}/{span:<8}   "
              f"{entry['type'][:28]}")
        if args.show:
            print(f"    {', '.join(entry['members'][:24])}")

    print("\nNo bit encodings: Table 2-1 gives membership by NAME, and nothing")
    print("in the PRM maps a register name to the code that selects it. Those")
    print("codes are the assembler's, so cardinality is the whole constraint.")

    # And the answer that decides whether any of this helps a decoder.
    full = [n for n, e in classes.items()
            if len(e["members"]) == 1 << max(1, (len(e["members"]) - 1).bit_length())]
    print(f"\n{len(full)} of {len(classes)} classes EXACTLY fill their field width:")
    print(f"  {', '.join(sorted(full))}")
    print("\nA class that fills its field rejects nothing, so it is no constraint")
    print("at all. UREG is worse than the count above suggests: the PRM says it")
    print("'includes almost all processor core registers' and that the data and")
    print("system registers are subgroups of it, so the 7-bit ureg fields are")
    print("close to fully populated. Only SYSREG and the UREGXDAG variants")
    print("reject anything, and they appear in few forms.")

    if args.out:
        args.out.write_text(json.dumps(classes, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

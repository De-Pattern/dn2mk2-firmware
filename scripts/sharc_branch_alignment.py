"""Measure SHARC+ VISA decode quality by where its branches point.

Match rate is not a quality metric. A table built from the opcode figures alone
matches 63% of real SHARC code, 53% of *ColdFire* code, and 47% of random
bytes, because forms like Type1a fix three bits out of forty-eight by design.
Anything that scores high by matching more is measuring entropy.

**Branch alignment is the metric that discriminates.** A PC-relative branch in
correctly-decoded code points at another instruction: inside the same region,
and on a boundary the decode actually produced. In mis-decoded bytes the
displacement is arbitrary, so targets scatter out of range or into the middle
of something. digikit reports 92-99% on real firmware against 0.4-3.6% for
noise -- a separation of about thirty times, where match rate gives 1.2.

So every figure here is printed next to the same measurement on random bytes.
A number without that control says nothing, which is the lesson this repository
keeps relearning (`docs/pcm-hunt.md`).

Displacements are taken from the `reladdr` fields recovered from the figures'
bracket geometry (`prm_visa_tables.py`). Whether a displacement counts from the
branch or from the instruction after it, and whether its unit is a 16-bit word,
are not assumed: each convention is measured and reported, and the control says
which -- if any -- is real rather than fitted.

Usage:
    python scripts/sharc_branch_alignment.py visa.json out/section_7_blob.aplib.bin
"""

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dnfw.image import bootstream                       # noqa: E402

NOT_DISPATCHABLE = {"Compute", "ShortCompute", "ShiftImm"}
CODE_REGIONS = (0x20000000, 0x283825C4, 0x28380000)


def load_forms(path, mode="VISA"):
    forms = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["forms"]
    table = []
    for form in forms:
        if form["name"] in NOT_DISPATCHABLE or not form["fixed"]:
            continue
        if mode not in (form["mode"] or ""):
            continue
        mask = value = 0
        for bit, bit_value in form["fixed"].items():
            mask |= 1 << int(bit)
            if bit_value:
                value |= 1 << int(bit)
        rel = [f for f in form["fields"]
               if f["name"] and "reladdr" in f["name"].lower()]
        table.append({
            "name": form["name"], "width": form["width"], "bits": len(form["fixed"]),
            "mask": mask, "value": value, "reladdr": rel,
        })
    table.sort(key=lambda entry: -entry["bits"])
    return table


def word_of(data, offset, width):
    shorts = width // 16
    if offset + shorts * 2 > len(data):
        return None
    word = 0
    for index in range(shorts):
        position = offset + index * 2
        short = data[position] | (data[position + 1] << 8)
        word |= short << (width - 16 * (index + 1))
    return word


def displacement(word, fields):
    """Assemble a signed displacement from its (possibly split) bit ranges."""
    total = 0
    width = 0
    for field in sorted(fields, key=lambda f: -f["high"]):
        span = field["high"] - field["low"] + 1
        part = (word >> field["low"]) & ((1 << span) - 1)
        total = (total << span) | part
        width += span
    if total >> (width - 1):                       # sign-extend
        total -= 1 << width
    return total


def decode(data, table):
    """-> (boundaries set, [(offset, width, displacement)] for branches)."""
    offset = 0
    boundaries = set()
    branches = []
    while offset < len(data):
        hit = None
        for entry in table:
            word = word_of(data, offset, entry["width"])
            if word is None or word & entry["mask"] != entry["value"]:
                continue
            hit = entry
            break
        if hit is None:
            offset += 2
            continue
        boundaries.add(offset)
        if hit["reladdr"]:
            word = word_of(data, offset, hit["width"])
            branches.append((offset, hit["width"], displacement(word, hit["reladdr"])))
        offset += hit["width"] // 8
    return boundaries, branches


def alignment(data, table, unit, from_next):
    boundaries, branches = decode(data, table)
    if not branches:
        return 0, 0, 0
    inside = aligned = 0
    for offset, width, disp in branches:
        base = offset + (width // 8 if from_next else 0)
        target = base + disp * unit
        if 0 <= target < len(data):
            inside += 1
            if target in boundaries:
                aligned += 1
    return len(branches), inside, aligned


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tables", type=pathlib.Path)
    parser.add_argument("section7", type=pathlib.Path)
    parser.add_argument("--mode", default="VISA")
    args = parser.parse_args(argv)

    table = load_forms(args.tables, args.mode)
    with_rel = [e for e in table if e["reladdr"]]
    print(f"{len(table)} dispatchable {args.mode} forms, "
          f"{len(with_rel)} carrying a reladdr field: "
          f"{', '.join(e['name'] for e in with_rel)}\n")

    regions = dict(bootstream.load_regions(args.section7.read_bytes()))
    code = b"".join(regions[a] for a in CODE_REGIONS if a in regions)
    noise = os.urandom(len(code))
    print(f"code under test: {len(code):,} bytes from "
          f"{sum(1 for a in CODE_REGIONS if a in regions)} regions\n")

    print(f"{'convention':<26}{'branches':>10}{'in range':>18}{'on a boundary':>20}")
    for unit, from_next in ((2, False), (2, True), (1, False), (1, True)):
        label = f"{'next' if from_next else 'self'}-relative, x{unit}"
        for what, blob in (("code", code), ("noise", noise)):
            total, inside, aligned = alignment(blob, table, unit, from_next)
            if not total:
                continue
            print(f"  {label:<24}{what:<6}{total:>8,}"
                  f"{inside:>10,} ({100 * inside / total:5.1f}%)"
                  f"{aligned:>10,} ({100 * aligned / total:5.1f}%)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

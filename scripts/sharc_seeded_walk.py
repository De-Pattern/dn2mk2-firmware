"""Decode SHARC+ VISA by following control flow from the entry point.

A linear sweep decodes every offset in a region, including its data, and
resynchronises by stepping two bytes whenever nothing matches. That produces
false branch instructions whose displacements are arbitrary, which is why
`sharc_branch_alignment.py` measures only 50% of targets landing in range: the
denominator is full of things that are not branches.

**A recursive-descent walk decodes only what is reachable as code.** Start at
the entry point the boot stream declares, decode forwards, and queue the target
of every branch. Bytes nothing ever jumps to are never decoded, so data cannot
contribute false branches. digikit's handover says the same thing from the
other direction -- "auto-analysis alone finds nothing; seeds are required".

## Addresses

The boot stream's entry point is in SHARC exec space, and
`docs/sharc-code-map.md` establishes `load = exec * 2 + 0x28000000`. For OS
1.11 the entry is `0x001c12e2`, which maps to load `0x283825c4` -- exactly the
base of a code region, so the entry sits at offset 0 of it. That the two agree
is a check on the mapping, not an assumption of it.

Displacements are in exec units, so one unit is two bytes in the file.

## The metric

Of the branches actually reached, what share point at an offset the walk also
decoded as an instruction start. In correctly-decoded code that is nearly all
of them; in noise it is nearly none. Random bytes are seeded and walked the
same way, and reported alongside, because a number without its control says
nothing (`docs/pcm-hunt.md`).

Usage:
    python scripts/sharc_seeded_walk.py visa.json out/section_7_blob.aplib.bin
"""

import argparse
import collections
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dnfw.image import bootstream                       # noqa: E402

NOT_DISPATCHABLE = {"Compute", "ShortCompute", "ShiftImm"}
EXEC_TO_LOAD_BASE = 0x28000000


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
            "name": form["name"], "width": form["width"],
            "bits": len(form["fixed"]), "mask": mask, "value": value,
            "reladdr": rel,
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
    total = width = 0
    for field in sorted(fields, key=lambda f: -f["high"]):
        span = field["high"] - field["low"] + 1
        total = (total << span) | ((word >> field["low"]) & ((1 << span) - 1))
        width += span
    if total >> (width - 1):
        total -= 1 << width
    return total


def match(data, offset, table):
    for entry in table:
        word = word_of(data, offset, entry["width"])
        if word is not None and word & entry["mask"] == entry["value"]:
            return entry, word
    return None, None


def walk(data, table, seeds, max_steps=4_000_000):
    """Recursive descent. -> (boundaries, branches, steps, dead_ends)."""
    queue = collections.deque(seeds)
    seen = set()
    boundaries = set()
    branches = []
    dead_ends = 0
    steps = 0

    while queue and steps < max_steps:
        offset = queue.popleft()
        while 0 <= offset < len(data) and offset not in seen:
            seen.add(offset)
            steps += 1
            entry, word = match(data, offset, table)
            if entry is None:
                dead_ends += 1
                break
            boundaries.add(offset)
            if entry["reladdr"]:
                disp = displacement(word, entry["reladdr"])
                target = offset + disp * 2
                branches.append((offset, target))
                if 0 <= target < len(data):
                    queue.append(target)
            offset += entry["width"] // 8
    return boundaries, branches, steps, dead_ends


def report(label, data, table, seeds):
    boundaries, branches, steps, dead_ends = walk(data, table, seeds)
    print(f"  {label:<22} decoded {len(boundaries):>7,} instructions over "
          f"{steps:>7,} steps, {dead_ends:>5,} dead ends")
    if not branches:
        print(f"  {'':<22} no branch instruction reached")
        return
    in_range = [t for _o, t in branches if 0 <= t < len(data)]
    aligned = [t for t in in_range if t in boundaries]
    print(f"  {'':<22} branches {len(branches):>6,}   "
          f"in range {len(in_range):>6,} ({100 * len(in_range) / len(branches):5.1f}%)   "
          f"on a boundary {len(aligned):>6,} "
          f"({100 * len(aligned) / len(branches):5.1f}%)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tables", type=pathlib.Path)
    parser.add_argument("section7", type=pathlib.Path)
    parser.add_argument("--mode", default="VISA")
    args = parser.parse_args(argv)

    table = load_forms(args.tables, args.mode)
    raw = args.section7.read_bytes()
    regions = dict(bootstream.load_regions(raw))
    stream = bootstream.walk(raw)
    entry = getattr(stream, "entry", None) or getattr(stream, "entry_point", None)

    print(f"{len(table)} dispatchable {args.mode} forms")
    print(f"boot-stream entry point: "
          f"{'0x%08x' % entry if entry else 'not reported'}")

    if entry:
        load = entry * 2 + EXEC_TO_LOAD_BASE
        print(f"  exec 0x{entry:08x} -> load 0x{load:08x}")
    else:
        load = None

    for base in sorted(regions):
        data = regions[base]
        if len(data) < 1024:
            continue
        seeds = [0]
        note = "offset 0"
        if load is not None and base <= load < base + len(data):
            seeds = [load - base]
            note = f"entry at offset {load - base}"
        print(f"\nregion 0x{base:08x}  {len(data):,} bytes   seed: {note}")
        report("code", data, table, seeds)
        report("random control", os.urandom(len(data)), table, seeds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

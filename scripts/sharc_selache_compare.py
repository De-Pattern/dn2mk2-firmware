"""Score two SHARC+ VISA decoders against the firmware's own instruction starts.

    python scripts/sharc_selache_compare.py <image.syx|.zip>
    python scripts/sharc_selache_compare.py <image> --selmap "wsl -e /root/selmap-target/release/selmap"
    python scripts/sharc_selache_compare.py <image> --digikit ../digikit-wt/tools --no-selache

The decoders are digikit's `tools/sharc_disasm.py` and, through
`tools/selmap`, the one in `js216/selache` (GPL-3.0; built out of tree,
never vendored -- `docs/sharc-selache.md`).

## The oracle, and why it can say "wrong"

Every absolute `cjump` site and every `cjump` target is a known instruction
start, found by a byte scan that needs no decoder (`sharc_callgraph.py`).
Between two consecutive known starts, correct lengths sum **exactly** to the
distance. A walk can stop, land, or overshoot, so the test has an outcome that
means "wrong" -- which a "percent decoded" figure does not.

VISA resynchronises within a few instructions, so landing is easier than it
looks. Every landing figure is printed beside a **control**: the same walk
started 2 bytes late. Only the margin over the control is evidence.

## What it prints

- `spans`: consecutive known starts the walk lands on exactly, stops before,
  or overshoots; the control for selache.
- `functions`: a walk from each function entry, and how many in-function cjump
  sites it lands on (the metric `sharc_decode.py` uses).
- `branches`: selache's relative-branch targets that fall on an instruction
  start, against random targets.
- `disagree`: where the two give different lengths along digikit's walk, both
  are tried, and the walk to the next known start decides -- by digikit form.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import random
import re
import shlex
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import sharc_callgraph as CG                    # noqa: E402
from dnfw.cli.files import read_image           # noqa: E402
from dnfw.firmware.load import load             # noqa: E402
from dnfw.image import bootstream               # noqa: E402

BLOB = 7
DEFAULT_DIGIKIT = HERE.parent.parent / "digikit" / "tools"
DEFAULT_SELMAP = "wsl -e /root/selmap-target/release/selmap"
PC_REL = re.compile(r"\(pc,(-?0x[0-9a-f]+|-?\d+)\)")


def oracle(image: pathlib.Path):
    """-> (code regions, function entries, {cjump site: target load address})."""
    section = load(read_image(image)).container.find(BLOB)
    regions = bootstream.load_regions(section.unpack() or section.raw_payload)
    code = CG.code_regions(regions)
    loaded = [(b, b + len(x)) for b, x in regions]
    sites = {s: CG.exec_to_load(t, loaded) for b, x in code for s, t in CG.call_sites(b, x)}
    return code, CG.build(regions)["entries"], sites


def selache_map(cmd: str, blob: bytes) -> dict:
    """-> {offset: (length, text)} for every even offset, from tools/selmap."""
    out = subprocess.run(shlex.split(cmd), input=blob, capture_output=True, check=True).stdout
    m = {}
    for line in out.decode().splitlines():
        off, n, text = line.split("\t", 2)
        m[int(off)] = (int(n), text)
    return m


def walk_selache(m, start, stop):
    """-> (offsets walked, where it ended, stopped)."""
    off, seen = start, []
    while off < stop:
        seen.append(off)
        off += m[off][0]
    return seen, off, False


def walk_digikit(disassemble):
    def walk(blob, start, stop):
        seen, off = [], start
        try:
            for ins in disassemble(blob[:stop], start_offset=start):
                if ins.kind == "unknown":
                    return seen, off, True
                seen.append(ins.offset)
                off = ins.offset + ins.length_bytes
        except TypeError:        # m-dwyer/digikit#7: a truncated tail
            return seen, off, True
        return seen, off, False
    return walk


def spans(code, entries, sites, walker, shift=0):
    c = collections.Counter()
    for base, blob in code:
        hi = base + len(blob)
        known = sorted({e for e in entries if base <= e < hi} | {s for s in sites if base <= s < hi})
        for a, b in zip(known, known[1:]):
            _, end, stopped = walker(base, blob, a - base + shift, b - base)
            c["stopped" if stopped else "exact" if end == b - base else "overshoot"] += 1
    return c


def functions(code, entries, sites, walker, shift=0):
    c = collections.Counter()
    for base, blob in code:
        hi = base + len(blob)
        local = [e for e in entries if base <= e < hi]
        for i, e in enumerate(local):
            end = local[i + 1] if i + 1 < len(local) else hi
            seen, _, _ = walker(base, blob, e - base + shift, end - base)
            seen = set(seen)
            inside = [s for s in sites if e < s < end]
            c["sites"] += len(inside)
            c["landed"] += sum(1 for s in inside if s - base in seen)
    return c


def branches(code, entries, maps, seed=1):
    """selache's pc-relative targets on a walked instruction start, vs random."""
    rng, c = random.Random(seed), collections.Counter()
    for base, blob in code:
        m, hi = maps[base], base + len(blob)
        local = [e for e in entries if base <= e < hi]
        starts = set()
        for i, e in enumerate(local):
            end = local[i + 1] if i + 1 < len(local) else hi
            starts |= set(walk_selache(m, e - base, end - base)[0])
        for off in starts:
            hit = PC_REL.search(m[off][1])
            if not hit:
                continue
            target = off + 2 * int(hit.group(1), 0)
            if not 0 <= target < len(blob):
                continue
            c["on" if target in starts else "off"] += 1
            c["random_on" if rng.randrange(len(blob) // 2) * 2 in starts else "random_off"] += 1
    return c


def disagreements(code, entries, sites, maps, disassemble):
    """Where lengths differ along digikit's walk, which one reaches the next start."""
    def reaches(m, off, goal):
        while off < goal:
            off += m[off][0]
        return off == goal

    by_form = collections.defaultdict(collections.Counter)
    for base, blob in code:
        m, hi = maps[base], base + len(blob)
        local = [e for e in entries if base <= e < hi]
        for i, e in enumerate(local):
            end = local[i + 1] if i + 1 < len(local) else hi
            known = sorted({s - base for s in sites if e < s < end} | {end - base})
            try:
                for ins in disassemble(blob[:end - base], start_offset=e - base):
                    if ins.kind == "unknown":
                        break
                    theirs = m[ins.offset][0]
                    if theirs == ins.length_bytes:
                        by_form["(agree)"]["same"] += 1
                        continue
                    goal = next((k for k in known if k >= ins.offset + 6), None)
                    if goal is None:
                        continue
                    d = reaches(m, ins.offset + ins.length_bytes, goal)
                    s = reaches(m, ins.offset + theirs, goal)
                    by_form[ins.type_name]["both" if d and s else "digikit" if d
                                           else "selache" if s else "neither"] += 1
            except TypeError:
                pass
    return by_form


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "-"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("--digikit", type=pathlib.Path, default=DEFAULT_DIGIKIT,
                   help="digikit's tools/ directory (default: a sibling checkout)")
    p.add_argument("--selmap", default=DEFAULT_SELMAP, help="command that runs tools/selmap")
    p.add_argument("--no-selache", action="store_true", help="score digikit alone")
    args = p.parse_args(argv)

    sys.path.insert(0, str(args.digikit))
    from sharc_disasm import disassemble        # noqa: E402

    code, entries, sites = oracle(args.image)
    dk = walk_digikit(disassemble)
    dk_walk = lambda base, blob, a, b: dk(blob, a, b)      # noqa: E731
    print(f"{args.image.name}: {len(sites)} cjump sites, {len(entries)} entries, "
          f"{sum(len(x) for _, x in code):,} B of code")

    rows = [("digikit", dk_walk, 0)]
    maps = {}
    if not args.no_selache:
        maps = {base: selache_map(args.selmap, blob) for base, blob in code}
        sel_walk = lambda base, blob, a, b: walk_selache(maps[base], a, b)   # noqa: E731
        rows += [("selache", sel_walk, 0), ("selache, 2 B late", sel_walk, 2)]

    print("\nspans between consecutive known starts")
    for name, walker, shift in rows:
        c = spans(code, entries, sites, walker, shift)
        n = sum(c.values())
        print(f"  {name:18} exact {c['exact']:5} ({pct(c['exact'], n)})  "
              f"stopped {c['stopped']:4}  overshoot {c['overshoot']:4}  of {n}")

    print("\nwalk from each function entry: in-function cjump sites landed on")
    for name, walker, shift in rows:
        c = functions(code, entries, sites, walker, shift)
        print(f"  {name:18} {c['landed']:5} of {c['sites']} ({pct(c['landed'], c['sites'])})")

    if maps:
        c = branches(code, entries, maps)
        print(f"\nselache pc-relative targets on an instruction start: "
              f"{pct(c['on'], c['on'] + c['off'])} (random targets: "
              f"{pct(c['random_on'], c['random_on'] + c['random_off'])})")
        by_form = disagreements(code, entries, sites, maps, disassemble)
        same = by_form.pop("(agree)")["same"]
        total = same + sum(sum(v.values()) for v in by_form.values())
        print(f"\nlength disagreements along digikit's walks: {total - same} of {total}")
        print("  form            decided: digikit  selache   undecided  neither")
        for form, v in sorted(by_form.items(), key=lambda kv: -(kv[1]["digikit"] + kv[1]["selache"])):
            if v["digikit"] + v["selache"] == 0:
                continue
            print(f"  {form:16} {v['digikit']:16} {v['selache']:8} {v['both']:11} {v['neither']:8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

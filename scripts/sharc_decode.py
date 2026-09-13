"""How well does the SHARC disassembler actually decode this image?

## Why "81% confident" is not the answer

`docs/sharc-disassembly.md` reports 3,249 confident instructions against 480
unknown over the L2 code region, and then records the reason that number cannot
be taken at face value: **an all-zero 48-bit word satisfies Type21a's mask**, so
padding decodes as confident code. A rate computed that way counts its own false
positives as successes, and *a decoder that never fails on zeros cannot tell you
it has left the code*.

Worse, a linear walk can silently desync. Started at an arbitrary address in the
`xTaskCreate` call site at `0x28394000`, the walk produced eight consecutive
"confident" instructions and stepped straight **over** a cjump that the byte
scan finds at `0x28394026` -- because `t21a` matched the two bytes before it.
Every line looked fine. None of them was.

## The oracle

The cjump scan is independent of the walk and is already validated
(`docs/sharc-code-map.md`): 1,606 sites, concentrated entirely in the two code
regions, zero across 6.2 MB of data and DDR fill. So every cjump site is a known
instruction boundary that the walk never saw.

That makes a test with a real control:

- walk each function from its entry, which is a boundary by definition;
- for every cjump site inside that function, ask whether the walk **landed on
  it**.

A walk that is correctly aligned lands on all of them. A walk that desynced
lands on none after the point it slipped. The measurement can come out either
way, which the "confident %" cannot: *it has no outcome that means "wrong"*.

The result is per function, so the output is not one number but a partition:
the functions that decode cleanly, and the ones that do not. Only the first
kind should be read.

    python scripts/sharc_decode.py <image.syx|.zip>
    python scripts/sharc_decode.py <image.syx|.zip> --at 0x28393fce --listing
"""

import argparse
import collections
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from dnfw.cli.files import read_image          # noqa: E402
from dnfw.firmware.load import load            # noqa: E402
from dnfw.image import bootstream              # noqa: E402

sys.path.append(str(pathlib.Path.home() / "digikit" / "tools"))
for candidate in (r"C:\ZZ_Code\ZZ_Personal\digikit\tools",
                  str(pathlib.Path.home() / "digikit" / "tools")):
    if pathlib.Path(candidate).is_dir():
        sys.path.insert(0, candidate)
        break

try:
    from sharc_disasm import disassemble       # noqa: E402
except ImportError:                            # pragma: no cover
    raise SystemExit(
        "digikit's tools/sharc_disasm.py is not importable.\n"
        "Clone m-dwyer/digikit and point at it -- see docs/emulator.md.")

BLOB = 7
L1_BASE = 0x20000000
L2_BASE = 0x28000000


def exec_to_load(target: int):
    space = target >> 16
    if space == 0x1C:
        return target * 2 + L2_BASE
    if space == 0xB8:
        return (target & 0xFFFF) * 2 + L1_BASE
    return None


def call_sites(base: int, blob: bytes):
    for off in range(0, len(blob) - 6, 2):
        w0, w1, w2 = struct.unpack_from("<HHH", blob, off)
        insn = (w0 << 32) | (w1 << 16) | w2
        if (insn >> 24) & 0xFFFFFF == 0x180400:
            yield base + off, insn & 0xFFFFFF


def load_regions(image: pathlib.Path, section_id: int):
    fw = load(read_image(image))
    section = fw.container.find(section_id)
    if section is None:
        raise SystemExit(f"image has no section id={section_id}")
    return bootstream.load_regions(section.unpack() or section.raw_payload)


def code_regions(regions):
    out = []
    for base, blob in regions:
        if sum(1 for _ in call_sites(base, blob)) >= 100:
            out.append((base, blob))
    return out


def walk(blob: bytes, start: int, end: int):
    """-> (boundaries, kinds, lines) for a linear walk of [start, end).

    The TypeError guard is an upstream bug, not ours, and is reported as
    `m-dwyer/digikit#7`: when word0 matches a multi-word group but word1 could
    not be read -- which happens at every truncated buffer end, and this walks
    one buffer per function -- `disassemble` builds its diagnostic with
    `f"word1={word1:#06x}"` while word1 is still None. The message's own text
    says "if read", so the author saw the case; the format string did not. It
    means "length unresolvable here", which is what it is recorded as.
    """
    boundaries, kinds, lines = set(), collections.Counter(), []
    stream = disassemble(blob[:end], start_offset=start)
    while True:
        try:
            ins = next(stream)
        except StopIteration:
            break
        except TypeError:
            kinds["unknown"] += 1
            break
        boundaries.add(ins.offset)
        kinds[ins.kind] += 1
        lines.append(ins)
        if ins.kind == "unknown":
            break
    return boundaries, kinds, lines


def analyse(regions, only=None):
    code = code_regions(regions)
    sites = {}
    for base, blob in code:
        for site, target in call_sites(base, blob):
            sites[site] = target
    entries = sorted({a for a in (exec_to_load(t) for t in sites.values())
                      if a is not None})

    rows = []
    for base, blob in code:
        region_end = base + len(blob)
        local = [e for e in entries if base <= e < region_end]
        for i, entry in enumerate(local):
            end = local[i + 1] if i + 1 < len(local) else region_end
            if only is not None and entry != only:
                continue
            expected = {s for s in sites if entry < s < end}
            bounds, kinds, lines = walk(blob, entry - base, end - base)
            hit = {s for s in expected if (s - base) in bounds}
            walked = 0
            if lines:
                last = lines[-1]
                walked = last.offset + (last.length_bytes or 0) - (entry - base)
            rows.append({
                "entry": entry, "size": end - entry,
                "cjumps": len(expected), "landed": len(hit),
                "walked": max(walked, 0), "kinds": kinds,
                "stopped_unknown": kinds.get("unknown", 0) > 0,
            })
    return rows, code, sites


def listing(regions, entry: int, limit: int):
    for base, blob in code_regions(regions):
        if not (base <= entry < base + len(blob)):
            continue
        sites = {s for s, _ in call_sites(base, blob)}
        _, _, lines = walk(blob, entry - base, len(blob))
        for ins in lines[:limit]:
            addr = base + ins.offset
            n = ins.length_bytes or 2
            raw = blob[ins.offset:ins.offset + n].hex(" ")
            mark = "  <- cjump site" if addr in sites else ""
            print(f"0x{addr:08x}  {raw:<18} {str(ins.type_name):<10}"
                  f" {ins.kind:<11}{mark}")
        return
    print("address is not in a code region")


def score_ghidra(regions, listing_path: pathlib.Path) -> None:
    """Score Ghidra's flow-following disassembly on the same oracle.

    Ghidra addresses the flat space the SLEIGH module's own relocation implies
    (scripts/export_sharc_regions.py), so a load address is compared after the
    same mapping the exporter used -- L2 minus 0x28000000, L1 at 0xb8<<17.

    This is the comparison worth making because the two disassemblers share
    digikit's instruction tables and differ only in method: one walks linearly,
    the other follows flow from the 461 known entries. Whatever separates them
    is the method, not the ISA description.
    """
    starts = set()
    covered = 0
    for line in listing_path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            starts.add(int(parts[0], 16))
            covered += int(parts[1])
        except ValueError:
            continue

    def flat(addr):
        if L1_BASE <= addr < L2_BASE:
            return (0xB8 << 17) + (addr - L1_BASE)
        return addr - L2_BASE

    sites = []
    for base, blob in code_regions(regions):
        sites.extend(flat(s) for s, _ in call_sites(base, blob))

    hit = sum(1 for s in sites if s in starts)
    print(f"Ghidra listing: {len(starts):,} instructions, {covered:,} bytes.\n")
    print(f"  {hit:,} of {len(sites):,} known call boundaries have an "
          f"instruction starting exactly there ({100 * hit / max(len(sites), 1):.1f}%).")
    print("\nSame oracle as the linear walk above, so the two numbers are "
          "comparable:\nboth are scored against boundaries neither disassembler "
          "chose.")


def unresolved(regions, top: int) -> None:
    """Which first words the length decoder cannot resolve, by frequency.

    397 of 440 walks end on an unresolvable length rather than at the function
    end, so the limit on reading this image is not the *semantics* of the
    instruction set -- it is that some encodings have no length rule at all.
    A length rule is all a walk needs to stay in step.

    This counts the word0 values the walk died on. If a handful of values
    account for most of the stops, the gap is small and nameable rather than
    diffuse, and that is a thing to hand upstream rather than work around.
    """
    stops = collections.Counter()
    notes = {}
    code = code_regions(regions)
    sites_all = {}
    for base, blob in code:
        for site, target in call_sites(base, blob):
            sites_all[site] = target
    entries = sorted({a for a in (exec_to_load(t) for t in sites_all.values())
                      if a is not None})

    for base, blob in code:
        region_end = base + len(blob)
        local = [e for e in entries if base <= e < region_end]
        for i, entry in enumerate(local):
            end = local[i + 1] if i + 1 < len(local) else region_end
            _, _, lines = walk(blob, entry - base, end - base)
            if not lines:
                continue
            last = lines[-1]
            if last.kind != "unknown":
                continue
            w0 = last.raw if isinstance(last.raw, int) else None
            if w0 is None:
                continue
            stops[w0] += 1
            notes.setdefault(w0, (last.note or "").split(";")[0])

    print(f"Words the length decoder gives up on -- {sum(stops.values())} "
          f"stops over {len(stops)} distinct first words\n")
    print(f"  {'word0':<10}{'stops':>7}   why")
    for w0, n in stops.most_common(top):
        print(f"  0x{w0:04x}{n:>10}   {notes.get(w0, '')[:88]}")
    shown = sum(n for _, n in stops.most_common(top))
    print(f"\n  the top {min(top, len(stops))} account for {shown} of "
          f"{sum(stops.values())} stops "
          f"({100 * shown / max(sum(stops.values()), 1):.0f}%).")


def blame(regions, top: int) -> None:
    """Which instruction straddles a known boundary, and what preceded it.

    A linear walk desyncs on exactly one wrong length and never recovers, so
    counting desynced *functions* says nothing about the cause. What is
    diagnostic is the instruction that steps **over** a cjump site: it starts
    before the site and ends after it, which is only possible if its own length,
    or one shortly before it, is too long.

    Both are recorded. If one word0 dominates the straddler column, its length
    rule is wrong -- and a cjump site is ground truth the decoder never saw, so
    this can be wrong in a way the decoder's own confidence cannot.
    """
    straddler = collections.Counter()
    predecessor = collections.Counter()
    code = code_regions(regions)
    sites_all = {}
    for base, blob in code:
        for site, target in call_sites(base, blob):
            sites_all[site] = target
    entries = sorted({a for a in (exec_to_load(t) for t in sites_all.values())
                      if a is not None})

    for base, blob in code:
        region_end = base + len(blob)
        local = [e for e in entries if base <= e < region_end]
        for i, entry in enumerate(local):
            end = local[i + 1] if i + 1 < len(local) else region_end
            expected = sorted(s for s in sites_all if entry < s < end)
            if not expected:
                continue
            _, _, lines = walk(blob, entry - base, end - base)
            prev = None
            for ins in lines:
                n = ins.length_bytes or 2
                lo = base + ins.offset
                hi = lo + n
                over = [s for s in expected if lo < s < hi]
                if over:
                    straddler[(str(ins.type_name), n)] += 1
                    if prev is not None:
                        predecessor[(str(prev.type_name),
                                     prev.length_bytes or 2)] += 1
                    break
                prev = ins

    print("Instructions that step OVER a known cjump boundary\n")
    print(f"  {'type':<14}{'len':>4}{'times':>8}")
    for (name, n), c in straddler.most_common(top):
        print(f"  {name:<14}{n:>4}{c:>8}")
    print("\nAnd what immediately preceded the straddle "
          "(the likelier culprit, since\na length that is too long shows up on "
          "the NEXT instruction):\n")
    print(f"  {'type':<14}{'len':>4}{'times':>8}")
    for (name, n), c in predecessor.most_common(top):
        print(f"  {name:<14}{n:>4}{c:>8}")


def report(rows) -> None:
    scored = [r for r in rows if r["cjumps"]]
    clean = [r for r in scored if r["landed"] == r["cjumps"]]
    partial = [r for r in scored if 0 < r["landed"] < r["cjumps"]]
    lost = [r for r in scored if r["landed"] == 0]

    print(f"{len(rows):,} functions, {len(scored):,} of them containing a "
          f"cjump the walk can be checked against.\n")
    print(f"  walk landed on every cjump   {len(clean):>5}   "
          f"{100 * len(clean) / max(len(scored), 1):5.1f}%")
    print(f"  landed on some               {len(partial):>5}")
    print(f"  landed on none (desynced)    {len(lost):>5}")

    tot = sum(r["cjumps"] for r in scored)
    got = sum(r["landed"] for r in scored)
    print(f"\n  {got:,} of {tot:,} known instruction boundaries were hit "
          f"({100 * got / max(tot, 1):.1f}%).")

    # How far a walk gets before it gives up is the other half of the story:
    # a walk that stops early is not wrong about what it decoded, it simply
    # never reaches the call sites the oracle could check it against.
    covered = sum(r["walked"] for r in rows)
    total = sum(r["size"] for r in rows)
    died = sum(1 for r in rows if r["stopped_unknown"])
    print(f"\n  the walk covered {covered:,} of {total:,} bytes "
          f"({100 * covered / max(total, 1):.1f}%) before stopping;")
    print(f"  {died} of {len(rows)} walks ended on an unresolvable length "
          f"rather than at the function end.")

    kinds = collections.Counter()
    for r in rows:
        kinds.update(r["kinds"])
    print("\n  instruction kinds over the same walks: "
          + ", ".join(f"{k} {v:,}" for k, v in kinds.most_common()))
    print("\nThe percentage above is the honest one: it is computed against "
          "boundaries\nfound by a test the walk had no part in. The 'confident' "
          "count is not,\nbecause an all-zero word decodes as a confident "
          "Type21a.")

    if partial or lost:
        print("\nWorst functions -- do not read a listing from these:")
        for r in sorted(partial + lost, key=lambda r: -r["cjumps"])[:12]:
            print(f"  0x{r['entry']:08x}  {r['size']:>6} bytes  "
                  f"{r['landed']:>3}/{r['cjumps']:<3} cjumps hit")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("--section", type=int, default=BLOB)
    p.add_argument("--at", help="one function entry, as a load address")
    p.add_argument("--listing", action="store_true",
                   help="print the walk for --at rather than scoring it")
    p.add_argument("--limit", type=int, default=80)
    p.add_argument("--ghidra", metavar="LISTING",
                   help="score a Ghidra listing (ghidra/SharcImport.java) "
                        "on the same oracle")
    p.add_argument("--unresolved", action="store_true",
                   help="which first words have no length rule")
    p.add_argument("--blame", action="store_true",
                   help="which instruction length is desynchronising the walk")
    args = p.parse_args(argv)

    regions = load_regions(args.image, args.section)
    if args.ghidra:
        score_ghidra(regions, pathlib.Path(args.ghidra))
        return 0
    if args.blame:
        blame(regions, 15)
        return 0
    if args.unresolved:
        unresolved(regions, 20)
        return 0
    if args.listing:
        if not args.at:
            raise SystemExit("--listing needs --at")
        listing(regions, int(args.at, 0), args.limit)
        return 0

    rows, _, _ = analyse(regions, int(args.at, 0) if args.at else None)
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

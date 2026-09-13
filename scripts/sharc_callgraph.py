"""The SHARC program's functions and who calls whom, from its own call sites.

## What this is, and why it is not a disassembly

`docs/sharc-code-map.md` established which bytes are code and what the processor
calls them, using one instruction form: the absolute `cjump`, which is how ADI's
compiler emits a call. That gave 1,616 call sites and 1,616 resolved targets,
and then stopped -- a list of edges with no vertices.

This closes it. **Every cjump target is a function entry**, because that is what
being called means. Sorting the targets partitions the code into functions
without disassembling a single instruction, and the call sites then say which
function calls which. The result is a call graph over ~240 KB of otherwise
anonymous code.

The SHARC image carries **no symbols** -- `docs/sharc-reading.md` records that
its only strings are seven FreeRTOS source paths and `Audio Task`. So names have
to come from somewhere else, and they come from those eight strings: a function
that references the `freertos-sharc/tasks.c` path is in `tasks.c`, because that
is what `configASSERT` puts there. Eight strings name 65 functions, and every
one of them is in L1 -- which is the point, since it says the application, and
so anything that makes sound, is the *other* region.

## How a data reference is recognised

Not the way it was first tried. A 48-bit VISA instruction is three little-endian
16-bit words assembled **MSB word first**, so a 32-bit operand sits in memory
with its halves in the opposite order to a plain little-endian long. Searching
for the plain layout found **zero** references to any of the eight strings, in
6.4 MB, which is not a firmware without references -- it is the wrong needle.

The layout that works is `LE(hi) || LE(lo)` of `addr - 0x28000000`, and the
evidence it is right is not that it produced hits but the *shape* of them:

- all 105 hits land inside the two code regions, none in the 6.2 MB outside;
- the other nineteen candidate encodings produce zero hits anywhere;
- the counts are semantically right -- `queue.c` 45 and `tasks.c` 40, the two
  biggest FreeRTOS files and the ones thickest with `configASSERT`, against
  `heap_4.c` 5 -- and `Audio Task` exactly **once**, which is what a task name
  passed to `xTaskCreate` should be.

A needle that matched noise would not concentrate in the code regions, and would
not count assert macros correctly.

## What it does not claim

Nothing here says what any function *computes*. A call graph is a shape; reading
an instruction is `docs/sharc-disassembly.md`'s job. Functions are also only as
real as their callers -- code reached solely by a computed jump, a jump table or
an interrupt vector has no cjump pointing at it and will be merged into whatever
function precedes it. That undercount is why `--gaps` exists.

    python scripts/sharc_callgraph.py <image.syx|.zip> --json out/sharc-graph.json
"""

import argparse
import collections
import json
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image          # noqa: E402
from dnfw.firmware.load import load            # noqa: E402
from dnfw.image import bootstream              # noqa: E402

BLOB = 7

# docs/sharc-code-map.md, both spaces solved 2026-09-14.
L1_BASE = 0x20000000
L2_BASE = 0x28000000

# The eight strings the image has. Anything else is float data that happens to
# be printable, so this list is deliberately closed rather than a scan.
LANDMARKS = {
    0x28268A78: "Audio Task",
    0x2826EE10: "event_groups.c",
    0x2826EE50: "queue.c",
    0x2826EEC0: "stream_buffer.c",
    0x2826EF40: "port.c",
    0x282D0738: "tasks.c",
    0x282D0848: "timers.c",
    0x282DD0E0: "heap_4.c",
}


def exec_to_load(target: int):
    """Execution address -> load address, or None if in neither space.

    Both spaces count 16-bit words, which is VISA's instruction granularity;
    the `0xb8` factor of two was settled by 47.2% of its targets being odd
    (docs/sharc-code-map.md), since an odd byte address cannot begin an
    instruction.
    """
    space = target >> 16
    if space == 0x1C:
        return target * 2 + L2_BASE
    if space == 0xB8:
        return (target & 0xFFFF) * 2 + L1_BASE
    return None


def operand_bytes(addr: int) -> bytes:
    """A load address as it appears in an instruction's operand field."""
    v = (addr - L2_BASE) & 0xFFFFFFFF
    return struct.pack("<H", (v >> 16) & 0xFFFF) + struct.pack("<H", v & 0xFFFF)


def code_regions(regions):
    """Regions that hold instructions, by the cjump-density test."""
    out = []
    for base, blob in regions:
        if sum(1 for _ in call_sites(base, blob)) >= 100:
            out.append((base, blob))
    return out


def call_sites(base: int, blob: bytes):
    """-> (site_load_addr, target_exec_addr) for every absolute cjump."""
    for off in range(0, len(blob) - 6, 2):
        w0, w1, w2 = struct.unpack_from("<HHH", blob, off)
        insn = (w0 << 32) | (w1 << 16) | w2
        if (insn >> 24) & 0xFFFFFF == 0x180400:
            yield base + off, insn & 0xFFFFFF


def build(regions):
    code = code_regions(regions)
    spans = [(b, b + len(x)) for b, x in code]

    edges = []          # (site, target_load)
    unresolved = 0
    for base, blob in code:
        for site, target in call_sites(base, blob):
            load_addr = exec_to_load(target)
            if load_addr is None:
                unresolved += 1
                continue
            edges.append((site, load_addr))

    entries = sorted({t for _, t in edges})
    # A target outside every code region would mean the mapping is wrong; it is
    # checked rather than assumed.
    stray = [e for e in entries
             if not any(lo <= e < hi for lo, hi in spans)]

    def owner(addr):
        """The entry of the function containing addr -- nearest entry at or
        below it, and only if no region boundary intervenes."""
        i = _bisect(entries, addr)
        if i == 0:
            return None
        cand = entries[i - 1]
        for lo, hi in spans:
            if lo <= cand < hi:
                return cand if addr < hi else None
        return None

    graph = collections.defaultdict(collections.Counter)
    orphan_sites = 0
    for site, target in edges:
        home = owner(site)
        if home is None:
            orphan_sites += 1
            continue
        graph[home][target] += 1

    # Landmark strings -> the functions that reference them.
    refs = collections.defaultdict(set)
    for addr, name in LANDMARKS.items():
        needle = operand_bytes(addr)
        for base, blob in code:
            start = 0
            while True:
                i = blob.find(needle, start)
                if i < 0:
                    break
                home = owner(base + i)
                if home is not None:
                    refs[home].add(name)
                start = i + 1

    return {
        "code_regions": [{"base": b, "end": b + len(x), "bytes": len(x)}
                         for b, x in code],
        "call_sites": len(edges) + unresolved,
        "unresolved_targets": unresolved,
        "stray_targets": stray,
        "orphan_sites": orphan_sites,
        "entries": entries,
        "graph": {k: dict(v) for k, v in graph.items()},
        "named": {k: sorted(v) for k, v in refs.items()},
        "spans": spans,
    }


def _bisect(seq, x):
    lo, hi = 0, len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if seq[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def sizes(entries, spans):
    """-> {entry: bytes} using the next entry, or the region end."""
    out = {}
    for i, e in enumerate(entries):
        end = None
        for lo, hi in spans:
            if lo <= e < hi:
                end = hi
                break
        if end is None:
            continue
        if i + 1 < len(entries) and e < entries[i + 1] < end:
            end = entries[i + 1]
        out[e] = end - e
    return out


def report(g, top: int) -> None:
    entries = g["entries"]
    spans = g["spans"]
    size = sizes(entries, spans)
    callers = collections.Counter()
    for _, outs in g["graph"].items():
        for t, n in outs.items():
            callers[t] += n

    print("code regions")
    for r in g["code_regions"]:
        print(f"  0x{r['base']:08x} .. 0x{r['end']:08x}   {r['bytes']:>8,} bytes")
    print(f"\n{g['call_sites']:,} call sites, "
          f"{g['unresolved_targets']} with an unmapped target, "
          f"{len(entries):,} distinct functions")
    if g["stray_targets"]:
        print(f"  *** {len(g['stray_targets'])} targets outside every code "
              f"region -- the address mapping is not clean ***")
    else:
        print("  every target lands inside a code region")
    if g["orphan_sites"]:
        print(f"  {g['orphan_sites']} call sites sit below the first entry "
              f"(region head, before any called function)")

    named = g["named"]
    print(f"\n{len(named)} function(s) reference a landmark string:")
    for e in sorted(named, key=lambda a: -callers[a]):
        print(f"  0x{e:08x}  {callers[e]:>4} callers  {size.get(e, 0):>6} bytes"
              f"   {', '.join(named[e])}")

    print(f"\nmost-called functions (the hot core):")
    print(f"  {'entry':<12}{'callers':>8}{'bytes':>8}   name")
    for e, n in callers.most_common(top):
        tag = ", ".join(named.get(e, [])) or ""
        print(f"  0x{e:08x}{n:>8}{size.get(e, 0):>8}   {tag}")

    # No "never called" count is printed, because there cannot be one: every
    # entry in this list IS a call target, so the statistic is true by
    # construction and could not come out any other way. The functions that
    # really are never called -- task bodies, ISRs, jump-table targets -- are
    # precisely the ones missing from `entries` altogether, and the honest
    # thing to report is how much code they might account for.
    covered = sum(size.values())
    total = sum(hi - lo for lo, hi in spans)
    print(f"\nThese functions span {covered:,} of {total:,} bytes of code. "
          f"Anything reached\nonly by a computed jump, a jump table or an "
          f"interrupt vector has no cjump\npointing at it, so it is merged "
          f"into whatever function precedes it rather\nthan appearing here -- "
          f"the audio task body is one such, reached only\nthrough the "
          f"scheduler (docs/sharc-reading.md).")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("--section", type=int, default=BLOB)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--json")
    args = p.parse_args(argv)

    fw = load(read_image(args.image))
    section = fw.container.find(args.section)
    if section is None:
        raise SystemExit(f"image has no section id={args.section}")
    data = section.unpack() or section.raw_payload
    g = build(bootstream.load_regions(data))
    report(g, args.top)

    if args.json:
        out = pathlib.Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "code_regions": g["code_regions"],
            "call_sites": g["call_sites"],
            "entries": [f"0x{e:08x}" for e in g["entries"]],
            "graph": {f"0x{k:08x}": {f"0x{t:08x}": n for t, n in v.items()}
                      for k, v in g["graph"].items()},
            "named": {f"0x{k:08x}": v for k, v in g["named"].items()},
        }, indent=2) + "\n")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

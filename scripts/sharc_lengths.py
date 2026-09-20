"""Resolve the one length ambiguity that stops the SHARC disassembler, from code.

## The gap, as its author states it

digikit's `sharc_visa_tables.py` marks `GROUP_5A_5B_MOVE` an *honestly named
gap*: Type5a_move is 48 bits and Type5b_move is 32, they share their word-0
opcode bits, and the transcription found no fixed bit in Type5b_move's second
word to test for. Its note gives two possibilities and asserts neither: the pair
may be genuinely undecidable from opcode bits, or the 400-DPI crop may have
missed a gray cell.

`scripts/sharc_decode.py` measures what that costs on our image. **378 of 396
linear-walk failures are this one group** -- not a diffuse lack of ISA coverage,
one rule. A walk needs nothing but lengths to stay in step, so resolving it is
the difference between 6.9% of the code readable and most of it.

## What this repository has that a transcription does not

1,606 verified instruction boundaries in a real firmware. Every absolute cjump
site is a point where an instruction provably starts (`docs/sharc-code-map.md`),
and function entries are boundaries by definition. Between two boundaries the
instruction lengths must sum **exactly** to the distance -- so where a 4/6 choice
would overshoot or undershoot, the code itself decides.

That is the method here: enumerate every assignment of 4 or 6 bytes to the
ambiguous instructions in a span, keep those that land exactly on the far
boundary, and record a decision only when **every** surviving assignment agrees.
A span with two self-consistent readings teaches nothing and is discarded rather
than resolved by preference.

## The control that makes the answer checkable

A forced decision is evidence about that instruction, not yet a rule. The rule
is only worth proposing if the forced decisions are *predictable* -- so the
bits of word1 are tested against the outcome, and the report says whether any
single bit separates the 32-bit cases from the 48-bit ones across every forced
decision. If one does, that is the gray bit the transcription is missing, stated
as a testable claim. If none does, the honest answer is the author's first
possibility, and the report says that instead.

    python scripts/sharc_lengths.py <image.syx|.zip>
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

for candidate in (r"D:_Code\Z_Personal\digikit\tools",
                  str(pathlib.Path.home() / "digikit" / "tools")):
    if pathlib.Path(candidate).is_dir():
        sys.path.insert(0, candidate)
        break

try:
    import sharc_disasm as SD                  # noqa: E402
except ImportError:                            # pragma: no cover
    raise SystemExit("digikit's tools/sharc_disasm.py is not importable.")

BLOB = 7
L1_BASE = 0x20000000
L2_BASE = 0x28000000
AMBIGUOUS = "GROUP_5A_5B_MOVE"
MAX_PATHS = 20000        # a span that explodes is skipped, not guessed at


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


def length_at(blob: bytes, off: int):
    """-> (bytes, ambiguous) for the instruction at off, or (None, False)."""
    if off + 2 > len(blob):
        return None, False
    w0 = struct.unpack_from("<H", blob, off)[0]
    bits = SD.decode_length_multiword(w0)
    if bits is None and off + 4 <= len(blob):
        w1 = struct.unpack_from("<H", blob, off + 2)[0]
        bits = SD.decode_length_multiword(w0, w1)
    if bits is not None:
        return SD._BYTES_FOR_BITS[bits], False
    if SD._which_group(w0) == AMBIGUOUS:
        return None, True
    return None, False


def solve(blob: bytes, start: int, stop: int, why=None):
    """Every length assignment walking start -> stop exactly.

    -> (solutions, exploded) where a solution is a list of (offset, length)
    for the ambiguous instructions only.

    `why`, when given, is a Counter that records why dead ends died. A span
    with no solution is not self-explanatory: it can mean an encoding with no
    length rule at all (a gap that is NOT the 5a/5b one), or that every
    assignment overshoots the far boundary -- which would instead suggest the
    boundary itself is wrong, or that something between them is data rather
    than code. Those have opposite implications for whether the solver can be
    trusted, so they are counted separately rather than lumped as "failed".
    """
    solutions = []
    budget = [MAX_PATHS]

    def walk(off, chosen):
        if budget[0] <= 0:
            return
        budget[0] -= 1
        if off == stop:
            solutions.append(list(chosen))
            return
        if off > stop:
            if why is not None:
                why["overshot"] += 1
            return
        n, amb = length_at(blob, off)
        if amb:
            for cand in (4, 6):
                chosen.append((off, cand))
                walk(off + cand, chosen)
                chosen.pop()
            return
        if n is None:
            if why is not None:
                w0 = struct.unpack_from("<H", blob, off)[0] \
                    if off + 2 <= len(blob) else None
                group = SD._which_group(w0) if w0 is not None else None
                why["no_length_rule"] += 1
                why[f"  word0=0x{w0:04x} group={group}"] += 1
            return
        walk(off + n, chosen)

    walk(start, [])
    return solutions, budget[0] <= 0


def gather(regions):
    code = [(b, x) for b, x in regions
            if sum(1 for _ in call_sites(b, x)) >= 100]
    sites = {}
    for base, blob in code:
        for site, target in call_sites(base, blob):
            sites[site] = target
    entries = sorted({a for a in (exec_to_load(t) for t in sites.values())
                      if a is not None})

    forced = []          # (word0, word1, length)
    stats = collections.Counter()
    reasons = collections.Counter()
    for base, blob in code:
        region_end = base + len(blob)
        known = sorted({a for a in entries if base <= a < region_end}
                       | {s for s in sites if base <= s < region_end})
        for a, b in zip(known, known[1:]):
            if b - a > 400:              # long spans explode; skip honestly
                stats["span_too_long"] += 1
                continue
            why = collections.Counter()
            sols, blew = solve(blob, a - base, b - base, why)
            if blew:
                stats["exploded"] += 1
                continue
            if not sols:
                stats["no_solution"] += 1
                # Classify the span by the dead end it ran into, so the 792
                # failures are explained rather than merely counted.
                if why["no_length_rule"] and not why["overshot"]:
                    stats["why_no_rule_only"] += 1
                elif why["overshot"] and not why["no_length_rule"]:
                    stats["why_overshot_only"] += 1
                elif why["no_length_rule"]:
                    stats["why_both"] += 1
                else:
                    stats["why_nothing"] += 1
                reasons.update({k: v for k, v in why.items() if k.startswith("  ")})
                continue
            if len(sols) == 1:
                stats["unique"] += 1
            else:
                stats["multiple"] += 1
            # A decision counts only where every surviving reading agrees.
            per_off = collections.defaultdict(set)
            for sol in sols:
                for off, n in sol:
                    per_off[off].add(n)
            for off, lens in per_off.items():
                if len(lens) != 1:
                    stats["undecided"] += 1
                    continue
                n = lens.pop()
                w0 = struct.unpack_from("<H", blob, off)[0]
                w1 = struct.unpack_from("<H", blob, off + 2)[0]
                # `sole` marks a decision from a span that had exactly one
                # possible reading end to end. Those are the only ones a
                # contradiction may be built from: in a span with several
                # readings, agreement between them is weaker evidence than it
                # looks, because all of them could be wrong together.
                forced.append((w0, w1, n, len(sols) == 1, base + off))
                stats[f"forced_{n}"] += 1
    return forced, stats, reasons


def report(forced, stats, reasons=None) -> None:
    print("spans between known boundaries")
    for k in ("unique", "multiple", "no_solution", "exploded",
              "span_too_long"):
        print(f"  {k:<16}{stats.get(k, 0):>7}")

    ns = stats.get("no_solution", 0)
    if ns:
        print(f"\nwhy those {ns} spans have no solution")
        print(f"  ran into an encoding with NO length rule   "
              f"{stats.get('why_no_rule_only', 0):>6}")
        print(f"  every assignment overshoots the boundary   "
              f"{stats.get('why_overshot_only', 0):>6}")
        print(f"  both happen on different branches         "
              f"{stats.get('why_both', 0):>6}")
        if reasons:
            print("\n  the encodings with no length rule at all:")
            for k, v in reasons.most_common(10):
                print(f"  {k}  x{v}")

    n4 = stats.get("forced_4", 0)
    n6 = stats.get("forced_6", 0)
    print(f"\n{len(forced)} ambiguous instructions were forced by the code: "
          f"{n4} are 32-bit (5b), {n6} are 48-bit (5a).")
    print(f"{stats.get('undecided', 0)} stayed ambiguous and are discarded.")

    if not forced:
        print("\nNothing was forced -- no claim can be made.")
        return

    # Does any single bit of word1 separate the two outcomes?
    print("\nDoes one bit of word1 predict the length?")
    perfect = []
    for bit in range(16):
        ones = collections.Counter()
        for _w0, w1, n, _sole, _at in forced:
            ones[((w1 >> bit) & 1, n)] += 1
        a = ones[(0, 4)], ones[(0, 6)], ones[(1, 4)], ones[(1, 6)]
        clean = (a[0] and a[3] and not a[1] and not a[2]) or \
                (a[1] and a[2] and not a[0] and not a[3])
        if clean:
            perfect.append((bit, a))
    if perfect:
        for bit, a in perfect:
            print(f"  bit {bit:>2} separates them perfectly "
                  f"(0->4:{a[0]} 0->6:{a[1]} 1->4:{a[2]} 1->6:{a[3]})")
        print("\n  That is a candidate for the gray bit the transcription "
              "did not catch.\n  It is a claim about this firmware's encoder, "
              "and it predicts: the same\n  bit should separate them in any "
              "other SHARC+ image.")
    else:
        print("  No single bit of word1 does. Tested all 16.")
        print("\n  That supports the author's first possibility -- the pair is "
              "not separable\n  from this word alone -- and means a decoder "
              "needs the surrounding\n  boundaries, which is exactly what this "
              "script uses.")

    # The decisive test the author's note leaves open. If one (word0, word1)
    # pair is forced BOTH ways by surrounding boundaries, then no rule over
    # those two words can exist -- it is not a missing gray bit, it is
    # information that is not in the words. One counterexample settles it;
    # absence of one leaves the question open rather than answering it the
    # other way, which is why both outcomes are reported in those terms.
    sole = [f for f in forced if f[3]]
    both = collections.defaultdict(dict)
    for w0, w1, n, _s, at in sole:
        both[(w0, w1)].setdefault(n, at)
    contradictions = {k: v for k, v in both.items() if len(v) > 1}
    print(f"\n{len(sole)} of {len(forced)} decisions come from a span with "
          f"exactly one\npossible reading; only those are used below.")
    print(f"\nSame (word0, word1) forced to different lengths: "
          f"{len(contradictions)} pair(s) of {len(both)} distinct.")
    if contradictions:
        for (w0, w1), where in list(contradictions.items())[:8]:
            spots = "  ".join(f"{n}B at 0x{a:08x}"
                              for n, a in sorted(where.items()))
            print(f"  word0=0x{w0:04x} word1=0x{w1:04x} -> {spots}")
        print("\n  A rule over word0 and word1 cannot exist: the same two words\n"
              "  are a 32-bit instruction in one place and a 48-bit one in\n"
              "  another. The missing information is not a gray bit that was\n"
              "  cropped away -- it is not in these words at all.")
    else:
        print("  None. Every pair seen is consistent, so a rule over word0 and\n"
              "  word1 is still POSSIBLE -- not demonstrated. With "
              f"{len(both)} distinct\n  pairs over {len(forced)} decisions, most "
              "pairs are seen once, which is\n  weak evidence either way.")

    print("\nMost common word0 among the forced decisions:")
    by_w0 = collections.Counter()
    for w0, _w1, n, _s, _at in forced:
        by_w0[(w0, n)] += 1
    for (w0, n), c in by_w0.most_common(12):
        print(f"  0x{w0:04x}  {n} bytes  x{c}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("--section", type=int, default=BLOB)
    args = p.parse_args(argv)

    fw = load(read_image(args.image))
    section = fw.container.find(args.section)
    if section is None:
        raise SystemExit(f"image has no section id={args.section}")
    regions = bootstream.load_regions(section.unpack() or section.raw_payload)
    forced, stats, reasons = gather(regions)
    report(forced, stats, reasons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

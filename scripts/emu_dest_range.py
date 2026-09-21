"""How far does DEST go on each LFO page, and what stops it?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_dest_range.py

The owner: the destination list **grows** as you advance the MOD pages -- LFO2
can modulate LFO1, LFO3 can modulate LFO1 and LFO2. That is an acyclic rule,
LFO N may target LFO 1..N-1, and it is what makes a fourth LFO safe to add at
the end.

`docs/engine-index-map.md` already covers the *conversion* side: a DEST value
is itself a slot number, so it needs translating, and the converter hardcodes
the three DEST slots {4, 12, 20} in two places. That is priced -- `~8` becomes
`~24` and all four LFOs are covered, two bytes at two sites.

**This asks the other half: what the page lets you pick.** The converter
translates whatever value is there; it does not decide the list. So turn DEST
to its ceiling on each page and read where it stops. Three ceilings that differ
by a fixed step say the bound is computed from the LFO index, and LFO4's list
would follow from the page alone. Three that do not say it is enumerated, and
there is a fourth enumeration to add -- another site list, belonging in the
same patch as the records rather than a later one.

DEST is encoder D on every LFO page, and its mirror slots are LFO1 4, LFO2 12,
LFO3 20 -- the same three the converter hardcodes, which is the cross-check
that the page under the cursor is the one being measured.
"""

from __future__ import annotations

import argparse
import collections
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import DOWN, MOD, Panel                      # noqa: E402

KIT = 0x4210C08C
VALUES = KIT + 52 + 0x14
DEST_SLOT = {1: 4, 2: 12, 3: 20}           # LFO1, LFO2, LFO3
DEST_ENCODER = 3                            # D, the fourth on the top row


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--turns", type=int, default=6)
    p.add_argument("--delta", type=int, default=30)     # the firmware clamps here
    args = p.parse_args()

    machine = Machine(args.snapshot)
    writes = collections.defaultdict(list)
    writers = collections.defaultdict(set)

    def note(pc, address, value, size):
        slot = (address - VALUES) // 2
        writes[slot].append(value)
        writers[slot].add(pc)

    machine.watch_writes(VALUES, VALUES + 201, note)

    panel = Panel(machine, png_dir="out/dest-range")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print(f"  warmed up; turning DEST (encoder D) to its ceiling on each page\n")

    seen = {}
    for page in (1, 2, 3):
        if page > 1:
            panel.tap(DOWN)
        slot = DEST_SLOT[page]
        before = len(writes[slot])
        panel.push_and_turn(DEST_ENCODER, args.delta, times=args.turns)
        vals = writes[slot][before:]
        shot = panel.screen(f"lfo{page}-dest")
        if not vals:
            print(f"  page {page} (LFO{page}, slot {slot}): nothing written -- the cursor "
                  f"is not on DEST, or this is not that page")
            print(f"    {shot}")
            continue
        top = max(vals)
        seen[page] = top >> 8                      # DEST is read as the high byte
        print(f"  page {page} (LFO{page}, slot {slot}): {len(vals)} write(s), "
              f"ceiling {top:#06x} -> destination {top >> 8}")
        print(f"    writers {[hex(w) for w in sorted(writers[slot])]}")
        print(f"    {shot}")

    print()
    if len(seen) < 2:
        print("  not enough pages answered to compare. Check the screens: the cursor\n"
              "  must be on DEST, and each page must be the LFO it is taken for.")
        return 1
    steps = sorted(seen.items())
    print(f"  ceilings: " + ", ".join(f"LFO{k} {v}" for k, v in steps))
    diffs = {b - a for (_, a), (_, b) in zip(steps, steps[1:])}
    if diffs == {8}:
        print("  Each page offers exactly 8 more than the one before -- one LFO's worth.\n"
              "  That is the rule computed, not enumerated, and LFO4 would want 24 more\n"
              "  than LFO1. Read the instruction that clamps it to see if the 8 comes\n"
              "  from the LFO index or from three constants that happen to differ by 8.")
    elif len(diffs) == 1:
        print(f"  The pages differ by a constant {diffs.pop()}, which is not 8 -- so the\n"
              "  list is not simply one LFO's parameters per page. Read the clamp.")
    else:
        print(f"  The steps are uneven ({sorted(diffs)}), which argues for three separate\n"
              "  bounds rather than one computed from the index. Expect a site list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

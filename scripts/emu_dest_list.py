"""What destinations does each LFO page offer? Read the list, not the ceiling.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_dest_list.py

`emu_dest_range.py` measured the wrong thing and the screen said so. Turning
DEST with its push held does not nudge a number: it opens a **modal browser**
with a category column, a scrolling list of destination names, and a
`Confirm? Yes/No` prompt. LFO1's ceiling came out at 99, one below the
evaluator's bound of 100, so the list is **not** bounded at the top by which
LFO you are on -- and the growth the owner describes has to be *which entries
the list contains*, not how far the value goes.

So this reads the list. On each LFO page it opens the browser, walks it with
`DOWN`, and keeps every frame. An `LFO1` category appearing on LFO2's page and
not on LFO1's own is the rule made visible; the same list on all three pages
would mean the rule lives somewhere else entirely.

It dismisses the browser with `NO` before paging, which is the mistake the last
probe made: a modal swallows the page keys, and then two pages report nothing
and look like a broken encoder.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                        # noqa: E402
from emulib.panel import DOWN, MOD, NO, Panel                   # noqa: E402

DEST_ENCODER = 3                     # D, the fourth on the top row


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--scroll", type=int, default=6, help="DOWN taps inside the browser")
    args = p.parse_args()

    machine = Machine(args.snapshot)
    panel = Panel(machine, png_dir="out/dest-list")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print("  warmed up; opening the DEST browser on each LFO page\n")

    for page in range(1, args.pages + 1):
        if page > 1:
            panel.tap(DOWN)                       # now safe: the modal is dismissed
        print(f"  --- LFO{page} ---")
        print(f"    page:    {panel.screen(f'lfo{page}-0-page')}")
        # Scroll to the TOP of the list, not down it. The LFO slots are 1-24,
        # the low end of the slot space, and LFO1 already reaches 99 at the
        # ceiling -- so if LFO2's list carries extra entries they sit at the
        # bottom. Comparing the three pages at the same scroll step compares
        # nothing, because each starts from its own current DEST value.
        panel.push_and_turn(DEST_ENCODER, 1, times=1)
        print(f"    opened:  {panel.screen(f'lfo{page}-1-opened')}")
        panel.push_and_turn(DEST_ENCODER, -30, times=args.scroll)
        print(f"    top:     {panel.screen(f'lfo{page}-2-top')}")
        panel.push_and_turn(DEST_ENCODER, 30, times=1)
        print(f"    top + 1: {panel.screen(f'lfo{page}-3-topplus')}")
        panel.tap(NO)                             # leave the browser, do not commit
        print(f"    after NO: {panel.screen(f'lfo{page}-9-closed')}")

    print("\n  Read the PNGs side by side. The question is whether an LFO category\n"
          "  appears on LFO2's list and not on LFO1's, and LFO1+LFO2 on LFO3's.\n"
          "  If all three lists are identical, the per-LFO rule is not in this UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

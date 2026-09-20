"""Which code writes a sound's parameter value, and which page moves which slot?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \\
        /root/dn2-emu-venv/bin/python -u scripts/emu_param_setter.py

LFO4's step 4 needs the point where a turn lands in the live sound. The getter
was known (`0x4006408a`); the static hunt for its counterpart went through
several plausible candidates without deciding, so this asks the machine: drive
the panel and watch track 1's value array.

Two things it has to get right, both learnt the hard way and both now living in
`scripts/emulib/panel.py` rather than here:

- **push and turn.** A plain turn does nothing in a menu. The first version
  turned without holding the push and reported zero writes -- a clean-looking
  null that meant nothing at all.
- **paging.** The `[MOD]` pages move on a *tap* or with **up / down**;
  `[PAGE]` opens the page settings, a different thing. The second version held
  `[MOD]`, never left the first LFO page, and wrote slot 1 four times -- which
  looks exactly like four successful page edits until the slot is read. This
  one pages with **DOWN**.

So it reports **the slot** and **archives the screen** at every step. A count
says a value moved, the slot says which parameter, the picture says which page
was open; any two of them disagreeing is the interesting case.
"""

from __future__ import annotations

import argparse
import collections
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import DOWN, MOD, UP, Panel                      # noqa: E402
from emulib.report import check, report                        # noqa: E402

KIT = 0x4210C08C
SOUND = KIT + 52                       # track 1's live sound
VALUES, VALUES_LEN = SOUND + 0x14, 202


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--delta", type=int, default=10)
    p.add_argument("--walk", default="down,down,up",
                   help="keys pressed between edits: the MOD pages move with up/down")
    p.add_argument("--png-dir", default="out/setter-screens")
    args = p.parse_args()

    machine = Machine(args.snapshot)
    panel = Panel(machine, png_dir=args.png_dir)

    writes = collections.Counter()
    seen = []

    def note(pc, address, value, size):
        writes[pc] += 1
        seen.append(((address - VALUES) // 2, value, pc))

    machine.watch_writes(VALUES, VALUES + VALUES_LEN - 1, note)

    print(f"watching {VALUES:#010x}..{VALUES + VALUES_LEN - 1:#010x}, track 1's values\n")
    panel.settle(args.warmup)
    print(f"  warmed up, {panel.frames()} frame(s) composed")

    before = len(seen)
    panel.settle()
    check("the array is quiet with no input", len(seen) == before,
          f"{len(seen) - before} write(s)")

    panel.tap(MOD)
    steps = [None] + [{"down": DOWN, "up": UP}[k] for k in args.walk.split(",") if k]
    for page, key in enumerate(steps, start=1):
        if key is not None:
            panel.tap(key)
        shot = panel.screen(f"page-{page}")
        mark = len(seen)
        panel.push_and_turn(0, args.delta)
        moved = sorted({slot for slot, _v, _pc in seen[mark:]})
        lfo = [f"LFO{(s - 1) // 8 + 1} slot {s}" for s in moved]
        print(f"  step {page}: {len(seen) - mark} write(s), {moved} -- {', '.join(lfo) or 'nothing'}")
        print(f"    {shot}")
        print(f"    {panel.screen(f'page-{page}-turned')}")

    print()
    if not seen:
        print("  nothing wrote the array. Check the input arrived before reading\n"
              "  anything into that -- scripts/drive.py tells the three cases apart.")
        return 1
    writers = sorted(writes)
    slots = sorted({slot for slot, _v, _pc in seen})
    print(f"  writers: {' '.join(f'{w:#010x}' for w in writers)}")
    print(f"  slots touched: {slots}\n")
    check("exactly one routine writes parameter values", len(writers) == 1,
          " ".join(f"{w:#010x}" for w in writers))
    check("the pages moved: more than one slot was touched", len(slots) > 1,
          f"slots {slots} -- one slot for every page means the paging did not work")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

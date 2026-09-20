"""How far does one press of DOWN move the MOD pages, and does the dwell decide?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_page_timing.py

`emu_param_setter.py` walked the pages and found LFO1 on the first page and
**LFO3** on the second -- two pages of travel for one press. Two readings fit
that equally well and they want different fixes:

- the press is registered **twice**, because the dwell spans more than one key
  scan, so one tap advances two pages and later taps only look stuck because
  LFO3 is the last page;
- the press is registered once and the pages genuinely run 1, 3, ..., which
  would mean the page list is not what we think it is.

The mapping is not a third reading: the firmware's own name tables were read
with `emu_panel_map.py` and agree with `emulib.panel` on all three codes.

So this measures the **step**, not one landing: it taps DOWN several times and
reports the slot after each. `1, 9, 17` is one page per press. `1, 17, 17` is
two per press and then the end of the list. The same walk runs at more than one
dwell, because if the dwell is what doubles the press, a shorter one stops it.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                   # noqa: E402
from emulib.panel import DOWN, MOD, Panel                   # noqa: E402

KIT = 0x4210C08C
SOUND = KIT + 52                       # track 1's live sound
VALUES, VALUES_LEN = SOUND + 0x14, 202


def lfo_of(slot):
    """-> the LFO a value slot belongs to, or None. Slots are 8*lfo+1..8*lfo+8."""
    return f"LFO{(slot - 1) // 8 + 1}" if 1 <= slot <= 24 else None


def walk(dwell, args):
    """Tap DOWN `args.taps` times at this dwell. -> the slot seen at each page."""
    machine = Machine(args.snapshot)
    panel = Panel(machine, png_dir=f"{args.png_dir}/dwell-{dwell}")

    seen = []
    machine.watch_writes(VALUES, VALUES + VALUES_LEN - 1,
                         lambda pc, address, value, size: seen.append((address - VALUES) // 2))

    panel.settle(args.warmup)
    panel.tap(MOD)

    slots = []
    for page in range(args.taps + 1):
        if page:
            panel.tap(DOWN, after=args.after)
        mark = len(seen)
        panel.push_and_turn(0, args.delta)
        moved = sorted(set(seen[mark:]))
        slots.append(moved[0] if len(moved) == 1 else moved)
        panel.screen(f"page-{page + 1}")
    return slots


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--delta", type=int, default=10)
    p.add_argument("--taps", type=int, default=3)
    p.add_argument("--after", type=int, default=10_000_000)
    p.add_argument("--dwells", default="500000,2000000",
                   help="how long DOWN is held, in instructions")
    p.add_argument("--png-dir", default="out/page-timing")
    args = p.parse_args()

    rows = []
    for dwell in [int(d) for d in args.dwells.split(",") if d]:
        slots = walk(dwell, args)
        names = [lfo_of(s) if isinstance(s, int) else s for s in slots]
        print(f"  dwell {dwell:>9}: slots {slots}  -- {' -> '.join(str(n) for n in names)}")
        rows.append((dwell, slots))

    print()
    for dwell, slots in rows:
        plain = [s for s in slots if isinstance(s, int)]
        if len(plain) < 2:
            verdict = "no clean reading -- a page wrote more than one slot"
        else:
            steps = {(b - a) // 8 for a, b in zip(plain, plain[1:]) if b != a}
            verdict = ("one page per press" if steps == {1}
                       else "two pages per press" if steps == {2}
                       else f"pages did not move" if not steps
                       else f"uneven travel: {sorted(steps)} page(s) per press")
        print(f"  dwell {dwell:>9}: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

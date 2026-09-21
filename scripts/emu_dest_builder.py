"""Who fills the destination vector, and does it read the LFO index?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_dest_builder.py

`emu_dest_vector.py` showed the list is produced when the browser opens: LFO2
and LFO3 rendered from the same buffer while LFO1 used another, so the storage
is reused rather than three lists sitting in memory. 55, 62 and 69 entries,
growing by exactly seven per preceding LFO.

That leaves one question, and it is the last one on DEST: is the per-page block
**computed from the LFO index** -- in which case LFO4's 21 extra entries follow
from the page existing -- or **enumerated three times**, in which case there is
a fourth enumeration to write and three existing ones to leave alone.

A write watch answers it. The instructions that fill the vector are the
builder; one routine filling it on every page is a filter, and three routines,
or one routine reached from three different sites, is an enumeration. The
watch also reports the **first** write of each page, because the entry count
is decided before the entries are.
"""

from __future__ import annotations

import argparse
import collections
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                        # noqa: E402
from emulib.panel import DOWN, MOD, NO, Panel                   # noqa: E402

SPAN = 0x447F0000, 0x44800000      # the region both reused buffers live in
DEST_ENCODER = 3


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--show", type=int, default=10)
    args = p.parse_args()

    machine = Machine(args.snapshot)
    armed = [False]
    writes = []

    def wrote(pc, address, value, size):
        if armed[0]:
            writes.append((pc, address, value, size))

    machine.watch_writes(SPAN[0], SPAN[1] - 1, wrote)

    panel = Panel(machine, png_dir="out/dest-builder")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print(f"  warmed up; watching writes to {SPAN[0]:#010x}..{SPAN[1] - 1:#010x}\n")

    for page in range(1, args.pages + 1):
        if page > 1:
            panel.tap(DOWN)
        writes.clear()
        armed[0] = True
        panel.push_and_turn(DEST_ENCODER, 1, times=1)
        armed[0] = False
        panel.tap(NO)

        # Entries look like small parameter indices; the rest is bookkeeping.
        entryish = [w for w in writes if w[3] == 4 and 1 <= w[2] <= 400]
        by_pc = collections.Counter(pc for pc, _a, _v, _s in entryish)
        print(f"  LFO{page}: {len(writes)} write(s) in the region, "
              f"{len(entryish)} that look like entries")
        for pc, n in by_pc.most_common(args.show):
            vals = [v for p_, _a, v, _s in entryish if p_ == pc]
            print(f"    {pc:#010x}  x{n:<5} values {vals[:10]}{' ...' if len(vals) > 10 else ''}")
        if entryish:
            pc, addr, val, _ = entryish[0]
            print(f"    first entry write: {pc:#010x} -> {addr:#010x} = {val}")

    print("\n  One PC filling the vector on all three pages is a filter, and the\n"
          "  question becomes what it tests. Different PCs per page, or one PC\n"
          "  reached from three call sites, is an enumeration -- and then LFO4\n"
          "  needs a fourth, which is a site list and belongs in the same patch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

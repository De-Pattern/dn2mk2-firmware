"""What holds the MOD pages, and is there room for a fourth?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_mod_pagelist.py

The header the screens showed -- `MOD (3/3)` -- is **not** drawn from a
constant. At `0x40063f84` the renderer computes

    count = (object@(128) - object@(124)) / 4        the total
    index =  object@(144) + 1                        the current, 1-based

which is a begin/end pair over four-byte entries: a vector, not a literal. It
also skips the `(n/m)` suffix entirely when the range is 8 bytes or less, so a
one-page mode shows only its name.

That changes what step 4b is. Nothing has to be taught that there are four
pages; a fourth **entry** makes the count, the header and -- if the paging
bounds read the same range -- the navigation all follow. What this reads is
whether that is true and what it would cost: the container's base, its three
entries, and whether the storage it sits in has room for a fourth or has to
move.

`a2` is the object the renderer was called with, so it is taken from a live
render rather than guessed: the probe opens the MOD page and watches the
instruction that loads it.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import DOWN, MOD, Panel                      # noqa: E402

RENDER = 0x40063F84            # movel %a2@(128),%d0 -- the end pointer
BEGIN, END, INDEX = 124, 128, 144


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    args = p.parse_args()

    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A2

    machine = Machine(args.snapshot)
    seen = []

    def at_render(uc, address, size, user):
        a2 = uc.reg_read(UC_M68K_REG_A2)
        if a2 not in seen:
            seen.append(a2)

    machine.uc.hook_add(UC_HOOK_CODE, at_render, begin=RENDER, end=RENDER)

    panel = Panel(machine, png_dir="out/mod-pagelist")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print(f"  {panel.screen('mod-1')}")
    panel.tap(DOWN)
    print(f"  {panel.screen('mod-2')}\n")

    if not seen:
        print("  the header renderer never ran -- no MOD page was drawn.")
        return 1

    print(f"  {len(seen)} mode object(s) rendered a header\n")
    for obj in seen:
        begin, end, index = (machine.long(obj + BEGIN), machine.long(obj + END),
                             machine.long(obj + INDEX))
        count = (end - begin) // 4
        print(f"  object {obj:#010x}: begin {begin:#010x} end {end:#010x} "
              f"-> {count} page(s), current {index}")
        for i in range(max(count, 0)):
            entry = machine.long(begin + 4 * i)
            print(f"      [{i}] {entry:#010x}")
        # What sits immediately after the last entry decides whether a fourth
        # can simply be appended or whether the whole array has to be rehoused.
        after = [machine.long(end + 4 * i) for i in range(4)]
        print(f"      the 16 bytes after the end: {' '.join(f'{w:#010x}' for w in after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

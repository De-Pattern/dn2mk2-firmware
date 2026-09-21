"""Who pushes the LFO destinations into the list?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_dest_pushers.py

Two instructions looked like the builder and neither was. `0x400392fc` writes
entry values because it is the **swap inside a sort partition**, comparator
called through `jsr %a0@`; `0x40193f38` writes them because it is
**`std::vector::push_back`** -- `end == capacity`, store, `++end`, tail-call to
the grow path. In a C++ image every instruction that touches an entry is a
container primitive, so the producer is whoever *calls* one.

So hook `push_back` at its entry, where `%sp@(0)` is still the return address,
and record that address whenever the value pushed is a parameter index in the
LFO groups (74-103). The return addresses are the builder's call sites.

**One call site reached on both LFO2 and LFO3, pushing seven then fourteen, is
a loop over preceding LFOs -- computed, and LFO4's 21 follow from the page.
Different sites per page are three enumerations, and LFO4 needs a fourth.**
That is the distinction the whole question rests on and neither probe so far
could see it, because both were watching the wrong end.
"""

from __future__ import annotations

import argparse
import collections
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                        # noqa: E402
from emulib.panel import DOWN, MOD, NO, Panel                   # noqa: E402

PUSH_BACK = 0x40193F1E          # movel %a2,%sp@- : sp@(0) is the return address
LFO_RECORDS = (74, 104)         # LFO1 74-83, LFO2 84-93, LFO3 94-103
DEST_ENCODER = 3


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--pages", type=int, default=3)
    args = p.parse_args()

    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A7

    machine = Machine(args.snapshot)
    armed = [False]
    pushes = []

    def at_push(uc, address, size, user):
        if not armed[0]:
            return
        sp = uc.reg_read(UC_M68K_REG_A7)
        try:
            ret = int.from_bytes(bytes(uc.mem_read(sp, 4)), "big")
            valptr = int.from_bytes(bytes(uc.mem_read(sp + 8, 4)), "big")
            value = int.from_bytes(bytes(uc.mem_read(valptr, 4)), "big")
        except Exception:                                        # noqa: BLE001
            return
        pushes.append((ret, value))

    machine.uc.hook_add(UC_HOOK_CODE, at_push, begin=PUSH_BACK, end=PUSH_BACK)

    panel = Panel(machine, png_dir="out/dest-pushers")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print("  warmed up; hooking push_back while each browser opens\n")

    for page in range(1, args.pages + 1):
        if page > 1:
            panel.tap(DOWN)
        pushes.clear()
        armed[0] = True
        panel.push_and_turn(DEST_ENCODER, 1, times=1)
        armed[0] = False
        panel.tap(NO)

        lfo = [(r, v) for r, v in pushes if LFO_RECORDS[0] <= v < LFO_RECORDS[1]]
        by_site = collections.Counter(r for r, _v in lfo)
        print(f"  LFO{page}: {len(pushes)} push(es), {len(lfo)} with an LFO-group value")
        for site, n in by_site.most_common(6):
            vals = sorted({v for r, v in lfo if r == site})
            print(f"    from {site:#010x}  x{n:<4} values {vals}")
        if not lfo:
            print("    none -- this page pushes no LFO parameter as a destination")

    print("\n  Same call site on LFO2 and LFO3, seven values then fourteen: a loop\n"
          "  over preceding LFOs, and LFO4's 21 follow from the page existing.\n"
          "  Different sites per page: three enumerations, and a fourth to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

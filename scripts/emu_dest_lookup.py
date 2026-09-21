"""Do all three LFO pages share one slot-lookup, or one each?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_dest_lookup.py

The destination list is built by one loop, for every page, over slots 0..100
(`0x4003958a`). What differs per page is `obj->vtable[80](slot)`, which returns
the entry for a slot or zero -- so that lookup is where "LFO2 may target LFO1
and not LFO3" has to live.

Everything about LFO4's destination list rests on which of two shapes this is:

- **one function for all three pages**, deciding from the page's own index --
  then a fourth page inherits the rule and its 21 entries come for free;
- **three functions**, one per page -- then there is a fourth to write, and it
  is the difference between LFO4's list working and coming out empty.

So hook the call at `0x40039594`, where `%a0` holds the target, and record the
target and the object for each page. This is the hypothesis the build would
otherwise rest on, tested before building rather than after.
"""

from __future__ import annotations

import argparse
import collections
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                        # noqa: E402
from emulib.panel import DOWN, MOD, NO, Panel                   # noqa: E402

CALL = 0x40039594            # jsr %a0@ -- the page's slot lookup
DEST_ENCODER = 3


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--pages", type=int, default=3)
    args = p.parse_args()

    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A0, UC_M68K_REG_A5, UC_M68K_REG_D2

    machine = Machine(args.snapshot)
    armed = [False]
    calls = []

    def at_call(uc, address, size, user):
        if armed[0]:
            calls.append((uc.reg_read(UC_M68K_REG_A0),
                          uc.reg_read(UC_M68K_REG_A5),
                          uc.reg_read(UC_M68K_REG_D2)))

    machine.uc.hook_add(UC_HOOK_CODE, at_call, begin=CALL, end=CALL)

    panel = Panel(machine, png_dir="out/dest-lookup")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print("  warmed up; hooking the slot lookup while each browser opens\n")

    targets = {}
    for page in range(1, args.pages + 1):
        if page > 1:
            panel.tap(DOWN)
        calls.clear()
        armed[0] = True
        panel.push_and_turn(DEST_ENCODER, 1, times=1)
        armed[0] = False
        panel.tap(NO)

        by_target = collections.Counter(t for t, _o, _s in calls)
        objs = sorted({o for _t, o, _s in calls})
        slots = sorted({s for _t, _o, s in calls})
        print(f"  LFO{page}: {len(calls)} lookup(s), slots {slots[0]}..{slots[-1] if slots else '-'}")
        for target, n in by_target.most_common(4):
            print(f"    target {target:#010x}  x{n}")
        print(f"    object(s) {[hex(o) for o in objs][:4]}")
        targets[page] = set(by_target)

    print()
    shared = set.intersection(*targets.values()) if len(targets) == args.pages else set()
    allsame = len({frozenset(v) for v in targets.values()}) == 1
    if allsame and shared:
        print(f"  All three pages call the SAME lookup {[hex(t) for t in sorted(shared)]}.\n"
              "  So the rule is inside one function, deciding from the page it is given,\n"
              "  and a fourth LFO page inherits it. LFO4's 21 entries come for free --\n"
              "  read that function to see what it keys on before relying on it.")
    else:
        print("  The pages call DIFFERENT lookups:")
        for page, ts in targets.items():
            print(f"    LFO{page}: {[hex(t) for t in sorted(ts)]}")
        print("  So there is a fourth to write, and LFO4's list would otherwise be\n"
              "  empty. It belongs in the same patch as the records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Who reads a parameter record, and how is its address formed?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_param_reader.py

`docs/lfo4-build-plan.md` says a page record's eight entries are parameter
table indices plus one, on the strength of the names lining up. Three static
reads since say the mechanism is unread: the table at `0x401f7fc8` has **no
literal reference anywhere in the image**, no record boundary from -2 to +39
does either, and the snapshot holds **no RAM copy** of a record. They are read
in place, by code that never names the base.

Static scanning has now failed at this three times, so ask the machine: open
the LFO3 MOD page and watch **reads** of the table. A read tells us the record
and the instruction that fetched it, and the instruction says how the address
was formed -- which is the whole question.

The watch is armed only for the page tap. Hooking 19 KB of reads across a 60 M
warmup would call back on everything the boot touches and drown the answer.
"""

from __future__ import annotations

import argparse
import collections
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import DOWN, MOD, Panel                      # noqa: E402

TABLE, REC, COUNT = 0x401F7FC8, 60, 320


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--show", type=int, default=14)
    args = p.parse_args()

    from unicorn import UC_HOOK_MEM_READ
    from unicorn.m68k_const import UC_M68K_REG_PC

    machine = Machine(args.snapshot)
    armed = [False]
    reads = []

    def was_read(uc, access, address, size, value, user):
        if armed[0]:
            reads.append((uc.reg_read(UC_M68K_REG_PC), address, size))

    machine.uc.hook_add(UC_HOOK_MEM_READ, was_read,
                        begin=TABLE, end=TABLE + REC * COUNT - 1)

    panel = Panel(machine, png_dir="out/param-reads")
    panel.settle(args.warmup)
    print(f"  warmed up; watching {TABLE:#010x}..{TABLE + REC * COUNT - 1:#010x}\n")

    armed[0] = True
    panel.tap(MOD)
    panel.tap(DOWN)           # LFO3's page: the one whose records we named
    armed[0] = False
    print(f"  {panel.screen('lfo3')}")
    print(f"  {len(reads)} read(s) of the parameter table while the page drew\n")

    if not reads:
        print("  Nothing read the table. Then the page is not drawn from it at all,\n"
              "  and the eight entries mean something else entirely -- which would be\n"
              "  a bigger correction than the one already recorded.")
        return 1

    by_pc = collections.Counter(pc for pc, _a, _s in reads)
    print("  the instructions that read it, hottest first:")
    for pc, n in by_pc.most_common(args.show):
        addrs = sorted({a for p_, a, _s in reads if p_ == pc})
        recs = sorted({(a - TABLE) // REC for a in addrs})
        off = sorted({(a - TABLE) % REC for a in addrs})
        print(f"    {pc:#010x}  x{n:<5} records {recs[:8]}{' ...' if len(recs) > 8 else ''}"
              f"  field offsets {off[:6]}")

    touched = sorted({(a - TABLE) // REC for _p, a, _s in reads})
    print(f"\n  records touched: {touched[:16]}{' ...' if len(touched) > 16 else ''}")
    print("  LFO3's group is records 94..103; if those are the ones read while its\n"
          "  page drew, the entries do index this table and only the arithmetic is\n"
          "  left to read -- in the instruction above that fetched them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

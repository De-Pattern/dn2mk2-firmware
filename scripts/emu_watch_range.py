"""Boot from reset and report every write into a RAM range, and every entry to an address.

    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_watch_range.py IMAGE --lo 0x46700000 --len 320 --entry 0x46700000

For a fault on the instrument whose PC is in RAM a mod put code in: was the code
there when it was entered, and who wrote over it first. Stops at the first entry
to --entry, or at the limit.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE           # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC                 # noqa: E402

SYX = ("/mnt/d/01_Code/Z_Personal/dn2_firmware/00_Resources/00_Firmware/"
       "Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--lo", type=lambda s: int(s, 0), required=True)
    p.add_argument("--len", type=lambda s: int(s, 0), required=True)
    p.add_argument("--entry", type=lambda s: int(s, 0))
    p.add_argument("--limit", type=int, default=2_500_000_000)
    args = p.parse_args()
    writes, seen = [], {}

    def pre_start(m):
        def on_write(uc, access, address, size, value, user):
            pc = uc.reg_read(UC_M68K_REG_PC)
            seen[pc] = seen.get(pc, 0) + 1
            if seen[pc] <= 2:
                writes.append((pc, address, size, value))

        m.uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=args.lo, end=args.lo + args.len - 1)
        if args.entry is not None:
            def at_entry(uc, address, size, user):
                code = bytes(uc.mem_read(args.lo, 16)).hex()
                print(f"  ENTRY 0x{address:08x}; the range starts {code}")
                uc.emu_stop()
            m.uc.hook_add(UC_HOOK_CODE, at_entry, begin=args.entry, end=args.entry)

    m, st, stop = dspboot.run(SYX, open(args.image, "rb").read(), limit=args.limit,
                              machine_out={}, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    for pc, address, size, value in writes[:60]:
        print(f"  write pc=0x{pc:08x} -> 0x{address:08x} ({size} B) = 0x{value & 0xffffffff:x}")
    print(f"  {sum(seen.values())} writes from {len(seen)} PC(s): "
          + ", ".join(f"0x{k:08x} x{v}" for k, v in sorted(seen.items())))
    print(f"  the range now starts {bytes(m.uc.mem_read(args.lo, 16)).hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

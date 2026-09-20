"""Watch the transport's 32-bit marks change, instead of inferring what they are.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_timebase.py [--limit 60000000]

`docs/dsp-control-block.md` reads `0x80005394` / `0x80005398` three times from
the instruction stream and gets three answers, because `movea.l` does not prove
a pointer and an unsigned range test does not prove memory. A static read cannot
settle what a number *is*; watching it move can.

So this boots and hooks **writes** to the transport's four longwords at
`0x42c4e900` and to the two block fields, recording the value, the writer and
the instruction count. Beside them it counts three references with known
meaning:

- the **audio ISR** (`0x400d0f90`), one entry per DMA half-buffer;
- the **eDMA channel 50 SADDR** register reads (`0xfc045640`), the same cadence;
- the **30 Hz tick** whose ISR posts to the main task's queue.

If a mark advances once per audio interrupt, its unit is a frame; if it tracks
the tick, it is a tick; if it never moves while both fire, it is neither and the
static reading was measuring something the emulator does not drive -- which is
also an answer, and the honest one to report.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot  # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC  # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"

WATCH = {0x42C4E900: "cursor +0", 0x42C4E904: "cursor +4",
         0x42C4E908: "cursor +8", 0x42C4E90C: "cursor +c",
         0x80005394: "block 5394", 0x80005398: "block 5398"}
MARKS = {"audio ISR": 0x400D0F90, "transport stop": 0x400D97CE,
         "queue insert": 0x40138B5C, "sequencer start": 0x400D93F0}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=60_000_000)
    p.add_argument("--max-events", type=int, default=40)
    args = p.parse_args()

    events, counts, holder = [], collections.Counter(), {}

    def pre_start(m):
        st = holder["st"]

        def wrote(uc, access, address, size, value, user):
            if address in WATCH:
                events.append((st["n"], uc.reg_read(UC_M68K_REG_PC), address, value, size))

        for low in sorted(WATCH):
            m.uc.hook_add(UC_HOOK_MEM_WRITE, wrote, begin=low, end=low + 3)
        for name, addr in MARKS.items():
            def hit(uc, address, size, user, name=name):
                counts[name] += 1
            m.uc.hook_add(UC_HOOK_CODE, hit, begin=addr, end=addr)

    image = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
    print(f"stock MAIN OS, {args.limit:,} instructions from reset")
    m, st, stop = dspboot.run(SYX, open(image, "rb").read(), limit=args.limit,
                              machine_out=holder, pre_start=pre_start)

    print(f"\n  reference points: {dict(counts) or 'none fired'}")
    print(f"  {len(events)} write(s) to the watched words\n")
    previous = {}
    for n, pc, address, value, size in events[:args.max_events]:
        delta = value - previous.get(address, value)
        previous[address] = value
        print(f"    n={n:>12,}  {WATCH[address]:12} <- {value:#010x} ({value:>12,})"
              + (f"  +{delta:,}" if delta else "") + f"   from {pc:#010x}")
    if len(events) > args.max_events:
        print(f"    ... {len(events) - args.max_events} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The destination list as a vector: what is in it, per LFO page.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_dest_vector.py

Reading the browser screen by screen settled the *rule* -- LFO N offers LFO
1..N-1 minus DEST, seven entries each -- but not the mechanism. The renderer at
0x40106546 walks a vector through `a0@(0)` and `a0@(4)` and emits a category
header whenever `group_of(entry)` changes, so the list is already built by the
time it is drawn.

This captures that vector. At `0x40106556`, `%a5` is begin and `%fp@(-108)` is
end, both live. Dumping the entries gives each page's list exactly -- as
parameter indices, which are the same numbers the page records hold -- and the
lengths answer directly whether LFO3 carries seven more than LFO2 or fourteen
more than LFO1.

A vector built per open is a filter somewhere; three vectors that already exist
are three enumerations. Either way the next step is a write watch on the
storage this reports, which is why it prints the address and not only the
contents.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                        # noqa: E402
from emulib.panel import DOWN, MOD, NO, Panel                   # noqa: E402

AT = 0x40106556               # cmpal %fp@(-108),%a5 -- begin in a5, end on the frame
DEST_ENCODER = 3


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--pages", type=int, default=3)
    args = p.parse_args()

    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A5, UC_M68K_REG_A6

    machine = Machine(args.snapshot)
    grabbed = []

    def at_walk(uc, address, size, user):
        begin = uc.reg_read(UC_M68K_REG_A5)
        fp = uc.reg_read(UC_M68K_REG_A6)
        try:
            end = int.from_bytes(bytes(uc.mem_read((fp - 108) & 0xFFFFFFFF, 4)), "big")
        except Exception:                                        # noqa: BLE001
            return
        if begin and end and end >= begin and (end - begin) % 4 == 0 and end - begin < 0x4000:
            grabbed.append((begin, end))

    machine.uc.hook_add(UC_HOOK_CODE, at_walk, begin=AT, end=AT)

    panel = Panel(machine, png_dir="out/dest-vector")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print("  warmed up; opening the DEST browser on each page\n")

    for page in range(1, args.pages + 1):
        if page > 1:
            panel.tap(DOWN)
        mark = len(grabbed)
        panel.push_and_turn(DEST_ENCODER, 1, times=1)
        seen = grabbed[mark:]
        if not seen:
            print(f"  LFO{page}: the renderer never walked a vector here")
            panel.tap(NO)
            continue
        begin, end = max(seen, key=lambda be: be[1] - be[0])
        n = (end - begin) // 4
        entries = [machine.long(begin + 4 * i) for i in range(min(n, 400))]
        print(f"  LFO{page}: vector {begin:#010x}..{end:#010x}, {n} entr(ies)")
        print(f"     first 12: {entries[:12]}")
        print(f"     last 12:  {entries[-12:]}")
        panel.tap(NO)

    print("\n  The entries are parameter indices, the same numbers a page record\n"
          "  holds. LFO1's group is 74-83 and LFO2's 84-93, so LFO1's records\n"
          "  appearing in LFO2's vector and not in LFO1's own is the rule, in the\n"
          "  data rather than on the screen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

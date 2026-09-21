"""What mask does each LFO page pass to the destination builder?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_dest_mask.py

`emu_dest_lookup.py` ruled out the lookup: all three pages call the same
`0x40036720` **and pass the same object** `0x446ce950`, so it cannot be what
differs between them. That leaves the builder's second filter --

    jsr 0x400dc30e        ; the entry's flags, record field +32
    notl %d0
    andl %sp@(56),%d0     ; a MASK from the caller's frame
    bnes skip             ; a required bit is missing

-- which is the only per-page input left in the loop.

So read it: hook `0x400395a4`, where the mask is on the stack, and print it for
each page. Three masks that differ by one bit per LFO is a rule a fourth page
can extend; three unrelated constants are three constants, and LFO4 needs a
fourth. This is the same question as before, asked of the input that actually
varies.
"""

from __future__ import annotations

import argparse
import collections
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                        # noqa: E402
from emulib.panel import DOWN, MOD, NO, Panel                   # noqa: E402

AT = 0x400395A4              # andl %sp@(56),%d0
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
    masks = []

    def at_and(uc, address, size, user):
        if not armed[0]:
            return
        sp = uc.reg_read(UC_M68K_REG_A7)
        try:
            masks.append(int.from_bytes(bytes(uc.mem_read(sp + 56, 4)), "big"))
        except Exception:                                        # noqa: BLE001
            pass

    machine.uc.hook_add(UC_HOOK_CODE, at_and, begin=AT, end=AT)

    panel = Panel(machine, png_dir="out/dest-mask")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print("  warmed up; reading the filter mask on each page\n")

    seen = {}
    for page in range(1, args.pages + 1):
        if page > 1:
            panel.tap(DOWN)
        masks.clear()
        armed[0] = True
        panel.push_and_turn(DEST_ENCODER, 1, times=1)
        armed[0] = False
        panel.tap(NO)
        counts = collections.Counter(masks)
        print(f"  LFO{page}: {len(masks)} filtered, mask(s) "
              f"{[f'{m:#010x} x{n}' for m, n in counts.most_common(4)]}")
        if counts:
            seen[page] = counts.most_common(1)[0][0]

    print()
    if len(seen) == args.pages:
        vals = [seen[k] for k in sorted(seen)]
        print("  masks: " + ", ".join(f"LFO{k} {v:#010x}" for k, v in sorted(seen.items())))
        if len(set(vals)) == 1:
            print("  All three are the SAME, so the mask is not the differentiator either,\n"
                  "  and the per-page rule is somewhere neither probe has looked.")
        else:
            diffs = [b ^ a for a, b in zip(vals, vals[1:])]
            print(f"  consecutive XOR: {[hex(x) for x in diffs]}")
            print("  One bit per LFO is a rule a fourth page extends by one more bit.\n"
                  "  Unrelated values are three constants, and LFO4 needs a fourth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

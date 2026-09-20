"""Does anything overwrite our code chunk during a boot from reset?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_boot_codeguard.py --build out/lfo4-bridge

`lfo4-bridge` faults at boot on the instrument. One hypothesis is specific
enough to test on its own: the build's C lives at `0x46800000`, chosen as
"above BSS, clear of every tenant" -- and if the firmware's heap or BSS reaches
that far **later in boot than step 1's 60 M-instruction test ever ran**, then a
`jsr` into our code lands in memory something else has since taken.

That hypothesis predicts a *writer that is not ours*, so this watches the whole
chunk -- code and BSS -- from reset and reports the first few writes by anyone
but our own loader and our own routines.

It is worth separating from `emu_boot_fault.py` because the two fail
differently: that one says *where it died*, this one says *what broke it*, and
a fault with no foreign write means the cause is elsewhere and this hypothesis
is closed rather than merely unproven.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_MEM_WRITE                         # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC                 # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
CODE_VA = 0x46800000


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-bridge")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--span", type=lambda x: int(x, 0), default=0x4000,
                   help="bytes of our region to watch (code + BSS, with room)")
    p.add_argument("--show", type=int, default=12)
    args = p.parse_args()

    build = os.path.join(ROOT, args.build)
    sym = {k: int(v, 16) for k, v in json.load(open(f"{build}/symbols.json")).items()}
    ours = sorted(v for v in sym.values() if CODE_VA <= v < CODE_VA + args.span)
    lo, hi = CODE_VA, CODE_VA + args.span - 1

    holder, foreign, mine = {}, [], [0]

    def pre_start(m):
        st = holder["st"]

        def wrote(uc, access, address, size, value, user):
            pc = uc.reg_read(UC_M68K_REG_PC)
            if CODE_VA <= pc < CODE_VA + args.span:     # our own code writing its own state
                mine[0] += 1
                return
            foreign.append((st["n"], pc, address, size, value))

        m.uc.hook_add(UC_HOOK_MEM_WRITE, wrote, begin=lo, end=hi)

    print(f"  watching {lo:#010x}..{hi:#010x} through a boot from reset\n")
    m, st, stop = dspboot.run(SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)

    print(f"  ran {st['n']:,} instruction(s), stop {stop!r}")
    print(f"  writes from inside our own region: {mine[0]:,}")
    print(f"  writes from anywhere else: {len(foreign):,}\n")
    if not foreign:
        print("  nothing outside our code ever wrote to it. The chunk survives the boot,\n"
              "  so being overwritten is NOT why the instrument faulted -- look elsewhere.")
        return 0

    by_pc = {}
    for n, pc, address, size, value in foreign:
        by_pc.setdefault(pc, []).append((n, address, size, value))
    print("  writers, first instruction first:")
    for pc in sorted(by_pc, key=lambda k: by_pc[k][0][0])[:args.show]:
        rows = by_pc[pc]
        n, address, size, value = rows[0]
        print(f"    {pc:#010x}  x{len(rows):<6} first at {n:>13,}  "
              f"{address:#010x} <- {value:#x} ({size} B)")
    first = foreign[0]
    print(f"\n  the first foreign write is at instruction {first[0]:,}, from {first[1]:#010x}.\n"
          f"  That is the thing to read: our chunk is at {CODE_VA:#010x} because\n"
          f"  docs/memory-map.md called it clear, and this says it is not.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

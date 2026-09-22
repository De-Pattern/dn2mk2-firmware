"""Is the MOD mode's page vector built with four ids, from reset?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_pagelist.py \
        [out/lfo4-ui2/section_3_MAIN_OS.bin]

From the instrument, 2026-09-22:

> "when the device opens, only 3 dots are shown to the right of the mod page
> ... The Fourth do appears as soon as I press MOD once."

`pagelist.c` answers it where the vector is constructed, at startup. **No
snapshot harness can check that.** `ui1200M` has already booted, so its vector
was built by stock code before any patch of ours could apply -- which is why
`emu_lfo4_screens.py` still reports `before any tap: pages [4, 5, 6]` on a
build that fixes exactly this. The same blind spot hid the live-container bug.

So this boots from reset and hooks the constructor's own call site:

```
40061558  moveq #3,%d1          ; the count
4006155c  movel %d1,%sp@-
40061562  movel #0x401e0048,%d0 ; the list
40061568  movel %d0,%sp@-
4006156a  movel %d6,%sp@-       ; the vector
4006156c  jsr %a5@              <- here: sp@ = vector, sp@(4) = list, sp@(8) = count
```

A pass is `count = 4` and a list address in the appended area. The vector's own
contents are read afterwards, because a constructor that was handed four ids
and stored three would look identical at the call.
"""

from __future__ import annotations

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/root/digikit/src")

import emu_boot_check as boot                                  # noqa: E402
from emulib.report import check, report                        # noqa: E402
from unicorn import UC_HOOK_CODE                               # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7                  # noqa: E402

CALL = 0x4006156C               # jsr %a5@ -- the vector constructor
STOCK_LIST = 0x401E0048         # the firmware's three ids
STOCK_END = 0x4030B980          # past this is the appended area: ours
# 450 M is what the boot gate uses and it is **not enough**: at that point the
# machine has drawn one frame and the MOD mode's page vector does not exist
# yet, so the constructor has not run. The mode object is built lazily, and how
# late is itself the finding -- `DT2_LIMIT` raises it.
LIMIT = int(os.environ.get("DT2_LIMIT", 450_000_000))
DEFAULT = "out/lfo4-ui2/section_3_MAIN_OS.bin"


def main(argv=None) -> int:
    path = (argv or sys.argv[1:] or [DEFAULT])[0]
    calls = []

    # `pre_start` is handed the machine; keep it rather than guessing which key
    # `machine_out` files it under.
    kept = {}

    def pre_start(m):
        kept["m"] = m

        def at_call(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            words = bytes(uc.mem_read(sp, 12))
            calls.append(tuple(int.from_bytes(words[i:i + 4], "big") for i in (0, 4, 8)))

        m.uc.hook_add(UC_HOOK_CODE, at_call, begin=CALL, end=CALL)

    holder = {}
    from emu import dspboot
    dspboot.run(str(boot.SYX), open(path, "rb").read(), limit=LIMIT,
                machine_out=holder, pre_start=pre_start)
    machine = kept["m"]

    print(f"  the constructor at {CALL:#010x} ran {len(calls)} time(s)")
    for vector, lst, count in calls:
        where = "the firmware's" if lst < STOCK_END else "**ours**"
        print(f"    vector {vector:#010x}  list {lst:#010x} ({where})  count {count}")

    if not calls:
        # **Not a pass.** An earlier version returned `report()` here, which
        # printed "all checks pass" having checked nothing at all -- the exact
        # false green `docs/PRINCIPLES.md` is about. A run that never reached
        # the thing it exists to measure has failed to measure it.
        check("the constructor ran at all", False,
              f"never, in {LIMIT:,} instruction(s) -- the MOD mode's pages are "
              f"built later than this boot gets, or somewhere else entirely")
        return report()

    vector, lst, count = calls[-1]
    begin = int.from_bytes(bytes(machine.uc.mem_read(vector, 4)), "big")
    end = int.from_bytes(bytes(machine.uc.mem_read(vector + 4, 4)), "big")
    held = [int.from_bytes(bytes(machine.uc.mem_read(begin + 4 * i, 4)), "big")
            for i in range((end - begin) // 4)] if begin and end > begin else []
    print(f"\n  the vector holds {held}")

    check("the constructor was handed four ids", count == 4, f"count {count}")
    check("from a list this build owns", lst >= STOCK_END,
          f"{lst:#010x}, stock's is {STOCK_LIST:#010x}")
    check("and the vector really holds four", len(held) == 4, f"{held}")
    check("which are the three MOD pages and ours", held[:3] == [4, 5, 6] if held else False,
          f"{held}")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

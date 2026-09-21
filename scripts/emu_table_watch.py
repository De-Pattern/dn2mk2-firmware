"""After the move, is the parameter table read where it used to be?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_table_watch.py [--build out/lfo4-table]

`build_lfo4_table.py` moves the 320-record parameter table into the appended
area and rewrites the 117 literals that reach it. The site lists are derived
from the image and their counts asserted, but a derivation can be complete in
its own terms and still miss a site -- and this relocation is deliberately
built so that a missed one **keeps working**: the old table is still there and
still correct for every record that already existed.

That safety is exactly what makes a missed site invisible. So this watches both
address ranges for reads while the firmware boots and then answers 330 accessor
calls, and the two counts together say what happened:

- reads of the **new** range prove the watch is armed and the relocation took.
  This is the control, and it is in the same run rather than a second boot of
  stock: a probe that reports "no reads of the old table" while watching
  nothing at all would look exactly like a pass.
- reads of the **old** range are sites that were not found.

The accessor calls are what force the issue. A boot exercises the table heavily
-- the last one made 2,192 kit loads -- but only `0x400dbeb6` is guaranteed to
run for every entry in the widened space, including the ten that did not exist
before.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emu import dspboot                                        # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ             # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A2                  # noqa: E402

from emu_boot_engine import After, REPORTER, ROOT, SYX         # noqa: E402
from emulib.image import code_chunks, load_build               # noqa: E402
from emulib.report import check, report                        # noqa: E402

TABLE, RECORD, STOCK_COUNT = 0x401F7FC8, 60, 320
RUNTIME, RUNTIME_STRIDE = 0x4243325C, 68
ACCESSOR = 0x400DBEB6                  # entry -> record[entry - 1] + 8, the group
GROUP = 8


def ranges(image, sym, added):
    """-> {name: (lo, hi)} for the two tables, before and after the move."""
    new_table = next(load for load, _n, _b, _i, _d in code_chunks(image)
                     if load != code_chunks(image)[0][0])
    return {
        "old 60-byte": (TABLE, TABLE + RECORD * STOCK_COUNT - 1),
        "new 60-byte": (new_table, new_table + RECORD * (STOCK_COUNT + added) - 1),
        "old 68-byte": (RUNTIME, RUNTIME + RUNTIME_STRIDE * (STOCK_COUNT + 1) - 1),
        "new 68-byte": (sym["lfo4_prm68"],
                        sym["lfo4_prm68"] + RUNTIME_STRIDE * (STOCK_COUNT + added + 1) - 1),
    }, new_table


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-table")
    p.add_argument("--limit", type=int, default=450_000_000)
    p.add_argument("--added", type=int, default=10)
    args = p.parse_args()

    build = os.path.join(ROOT, args.build)
    image, sym = load_build(build)
    spans, new_table = ranges(image, sym, args.added)
    entries = list(range(1, STOCK_COUNT + args.added + 1))
    for name, (lo, hi) in spans.items():
        print(f"  {name}: {lo:#010x}..{hi + 1:#010x}")
    print(f"  {len(entries)} accessor call(s) into {ACCESSOR:#010x} after the boot\n")

    holder, hits, fault = {}, {name: 0 for name in spans}, {}

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            if not fault:
                fault.update(at=st["n"], a2=uc.reg_read(UC_M68K_REG_A2))
            uc.emu_stop()

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        for name, (lo, hi) in spans.items():
            def read(uc, access, address, size, value, user, name=name):
                hits[name] += 1
            m.uc.hook_add(UC_HOOK_MEM_READ, read, begin=lo, end=hi)

    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    during = dict(hits)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    if fault:
        print(f"\n  FAULT at {fault['at']:,} -- nothing else this run says anything.")
        return 1
    for name in spans:
        print(f"    during boot, {name}: {during[name]:,} read(s)")

    after = After(m.uc)
    answers = [after.call(ACCESSOR, e) & 0xFFFFFFFF for e in entries]
    print("")
    for name in spans:
        print(f"    with the accessor calls, {name}: {hits[name]:,} read(s)")

    # What the accessor should have answered, read out of the build's own
    # relocated table rather than recomputed: the question is whether the
    # firmware reaches those bytes, not whether this script can do arithmetic.
    want = [int.from_bytes(bytes(m.uc.mem_read(new_table + RECORD * (e - 1) + GROUP, 4)), "big")
            for e in entries]
    tail = answers[STOCK_COUNT:]
    print(f"\n  entries {STOCK_COUNT + 1}..{STOCK_COUNT + args.added} answer {tail}")

    check("the watch is armed and the move took", hits["new 60-byte"] > 0,
          f"{hits['new 60-byte']:,} read(s) of the relocated table")
    check("nothing reads the 60-byte table where it used to be",
          hits["old 60-byte"] == 0, f"{hits['old 60-byte']:,} read(s)")
    check("nothing reads the 68-byte table where it used to be",
          hits["old 68-byte"] == 0, f"{hits['old 68-byte']:,} read(s)")
    check("the firmware filled the relocated runtime table", hits["new 68-byte"] > 0,
          f"{hits['new 68-byte']:,} read(s)")
    check("every entry answers what the relocated table holds", answers == want,
          f"{sum(1 for a, b in zip(answers, want) if a != b)} differ")
    check("the ten new entries carry LFO4's group",
          len(set(tail)) == 1 and tail[0] == want[STOCK_COUNT], f"{tail}")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

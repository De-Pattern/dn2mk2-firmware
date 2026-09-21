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
from unicorn import (UC_HOOK_CODE, UC_HOOK_MEM_READ,           # noqa: E402
                     UC_HOOK_MEM_WRITE)
from unicorn.m68k_const import (UC_M68K_REG_A2, UC_M68K_REG_D7,  # noqa: E402
                                UC_M68K_REG_PC)

from emu_boot_engine import After, REPORTER, ROOT, SYX         # noqa: E402
from emulib.image import code_chunks, load_build               # noqa: E402
from emulib.report import check, report                        # noqa: E402

TABLE, RECORD, STOCK_COUNT = 0x401F7FC8, 60, 320
RUNTIME, RUNTIME_STRIDE = 0x4243325C, 68
# `0x400dc11a(entry)` -> `record[entry - 1] + 40`, and that field is **unique
# across all 320 records**, so a wrong answer names the record it came from.
# The first version of this probe used `0x400dbeb6`, which looks like a field
# accessor and is not: it reads `+8` and then returns `5 <= group <= 10` as a
# 0 or 1. Every answer was "wrong" against the group, and the fault was the
# expectation. A probe whose expected value is read from the same bytes the
# firmware reads is only as good as its model of what the routine returns.
ACCESSOR = 0x400DC11A
FIELD = 40

# `param_set_tables_build` files each record's entry number into a table
# indexed by the record's **value slot**, at three sites, one per group of
# parameters. Each of those tables is 404 bytes -- 101 longwords, slots 0..100
# -- and the byte after the first is the filter table the same routine zeroed
# two calls earlier. So the slot in `%d7` at these three instructions is a
# bound this build must not exceed, and it is watched rather than argued about:
# raising the wrong bound made all three file slots 101-108, which boots, draws
# and corrupts.
FILING = (0x400DC6D6, 0x400DC6F2, 0x400DC716)
SLOT_LIMIT = 100


def ranges(image, added):
    """-> {name: (lo, hi)} for the 60-byte table either side of the move, and
    for the companion that stays put."""
    new_table = next(load for load, _n, _b, _i, _d in code_chunks(image)
                     if load != code_chunks(image)[0][0])
    return {
        "old 60-byte": (TABLE, TABLE + RECORD * STOCK_COUNT - 1),
        "new 60-byte": (new_table, new_table + RECORD * (STOCK_COUNT + added) - 1),
        "the 68-byte companion": (RUNTIME,
                                  RUNTIME + RUNTIME_STRIDE * (STOCK_COUNT + 1) - 1),
    }, new_table


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-table")
    p.add_argument("--limit", type=int, default=450_000_000)
    p.add_argument("--added", type=int, default=10)
    args = p.parse_args()

    build = os.path.join(ROOT, args.build)
    image, _sym = load_build(build)
    spans, new_table = ranges(image, args.added)
    entries = list(range(1, STOCK_COUNT + args.added + 1))
    for name, (lo, hi) in spans.items():
        print(f"  {name}: {lo:#010x}..{hi + 1:#010x}")
    print(f"  {len(entries)} accessor call(s) into {ACCESSOR:#010x} after the boot\n")

    holder, fault, filed, culprits = {}, {}, [], {}
    # Reads and writes are counted apart, because they answer different
    # questions and this probe's first run confused them: a table being
    # *filled* is written, not read, so "0 reads of the relocated runtime
    # table" was reported as a failure when it is the expected shape of a
    # registration loop that has not been asked for anything yet.
    hits = {(name, kind): 0 for name in spans for kind in ("read", "write")}

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            if not fault:
                fault.update(at=st["n"], a2=uc.reg_read(UC_M68K_REG_A2))
            uc.emu_stop()

        def count(name, kind):
            def hook(uc, *rest):
                hits[(name, kind)] += 1
            return hook

        def at_filing(uc, address, size, user):
            filed.append(uc.reg_read(UC_M68K_REG_D7))

        def at_old_write(uc, access, address, size, value, user):
            pc = uc.reg_read(UC_M68K_REG_PC)
            culprits[pc] = culprits.get(pc, 0) + 1

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        for site in FILING:
            m.uc.hook_add(UC_HOOK_CODE, at_filing, begin=site, end=site)
        for name, (lo, hi) in spans.items():
            m.uc.hook_add(UC_HOOK_MEM_READ, count(name, "read"), begin=lo, end=hi)
            m.uc.hook_add(UC_HOOK_MEM_WRITE, count(name, "write"), begin=lo, end=hi)
        # A write to a table that has moved is a site this build did not find,
        # and the only useful thing to report about it is where it came from.
        lo, hi = spans["old 60-byte"]
        m.uc.hook_add(UC_HOOK_MEM_WRITE, at_old_write, begin=lo, end=hi)

    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    during = dict(hits)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    if fault:
        print(f"  FAULT at {fault['at']:,} -- nothing else this run says anything.")
        return 1
    for name in spans:
        print(f"    during boot, {name}: {during[(name, 'read')]:,} read(s), "
              f"{during[(name, 'write')]:,} write(s)")

    after = After(m.uc)
    answers = [after.call(ACCESSOR, e) & 0xFFFFFFFF for e in entries]
    print("")
    for name in spans:
        print(f"    the accessor calls alone, {name}: "
              f"{hits[(name, 'read')] - during[(name, 'read')]:,} read(s), "
              f"{hits[(name, 'write')] - during[(name, 'write')]:,} write(s)")

    # What the accessor should have answered, read out of the build's own
    # relocated table rather than recomputed: the question is whether the
    # firmware reaches those bytes, not whether this script can do arithmetic.
    want = [int.from_bytes(bytes(m.uc.mem_read(new_table + RECORD * (e - 1) + FIELD, 4)), "big")
            for e in entries]
    tail = answers[STOCK_COUNT:]
    print("")
    print(f"  entries {STOCK_COUNT + 1}..{STOCK_COUNT + args.added} answer {tail}")

    touched = {name: hits[(name, "read")] + hits[(name, "write")] for name in spans}
    check("the watch is armed and the move took", touched["new 60-byte"] > 0,
          f"{touched['new 60-byte']:,} access(es) to the relocated table")
    check("nothing touches the 60-byte table where it used to be",
          touched["old 60-byte"] == 0, f"{touched['old 60-byte']:,}")
    # The companion table does not move -- its initialiser is unrolled and
    # writes 902 absolute addresses -- so it must still be *used*, in place.
    # A build that moved it would read an empty one here.
    check("the 68-byte companion is still written where it lives",
          touched["the 68-byte companion"] > 0,
          f"{touched['the 68-byte companion']:,} access(es)")
    if culprits:
        print("")
        print(f"  {sum(culprits.values()):,} write(s) to the old 60-byte table, from "
              f"{len(culprits)} instruction(s):")
        for pc in sorted(culprits, key=culprits.get, reverse=True)[:12]:
            print(f"    {pc:#010x}  x{culprits[pc]:,}")
    over = [v for v in filed if v > SLOT_LIMIT]
    print(f"  param_set_tables_build filed {len(filed):,} slot(s), highest "
          f"{max(filed) if filed else '-'}")
    check("nothing was filed past the slot tables' 101 entries", not over,
          f"{len(over)} write(s) past the end: {sorted(set(over))}")
    check("every entry answers what the relocated table holds", answers == want,
          f"{sum(1 for a, b in zip(answers, want) if a != b)} differ")
    check("the ten new entries answer with ids no stock record holds",
          len(set(tail)) == len(tail) and not (set(tail) & set(want[:STOCK_COUNT])),
          f"{tail}")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

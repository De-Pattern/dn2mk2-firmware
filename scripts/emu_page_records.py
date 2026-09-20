"""What a page record holds, read by comparing the three that differ least.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_page_records.py

The MOD pages are **ids 4, 5, 6** -- small integers in a vector at the mode
object's `+124`/`+128`, not pointers (`scripts/emu_mod_pagelist.py`). The
accessor at `0x400c2474` turns an id into a record:

    id > 36  ->  id = -1                      the fallback record
    record   =  0x42432C00 + 44 * id

So the id space already runs 0..36 and a fourth MOD page needs a **record**,
not a new mechanism. This dumps them.

LFO1, LFO2 and LFO3 are the same page three times over, differing only in which
LFO they address -- so the bytes that differ between records 4, 5 and 6 are
exactly the ones a fourth would have to change, and the bytes they share are
the ones it would copy. That comparison is the point; a single record read on
its own says very little.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402

BASE, STRIDE, LAST = 0x42432C00, 44, 36


def record(machine, i):
    return machine.read(BASE + STRIDE * i, STRIDE)


def words(blob):
    return [int.from_bytes(blob[i:i + 4], "big") for i in range(0, len(blob), 4)]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--ids", default="4,5,6", help="the records to compare closely")
    args = p.parse_args()

    machine = Machine(args.snapshot)
    # Nothing is executed. `ui1200M` is a snapshot of the UI already
    # running, so the table is long since built and reading it needs no
    # instructions -- which also means the snapshot's deferred timers stay
    # unclaimed, and `longrun.spin` rightly refuses to run a machine in
    # that state. A probe that only reads should not have to start one.
    print(f"  records at {BASE:#010x}, {STRIDE} B each, ids 0..{LAST} "
          f"(read from the snapshot, nothing executed)")

    ids = [int(x) for x in args.ids.split(",") if x]
    blobs = {i: record(machine, i) for i in ids}
    for i in ids:
        print(f"  id {i:>2}: {blobs[i].hex()}")

    print("\n  word by word, and whether the compared records agree:")
    print("   off  " + "  ".join(f"id {i:<8}" for i in ids) + "  same?")
    for w in range(STRIDE // 4):
        col = [words(blobs[i])[w] for i in ids]
        same = "yes" if len(set(col)) == 1 else "NO <-"
        print(f"   +{w * 4:<3} " + "  ".join(f"{c:#010x}" for c in col) + f"  {same}")

    # The fallback, and the neighbours, for the shape of the table as a whole.
    print(f"\n  the fallback record (id -1, {BASE - STRIDE:#010x}): "
          f"{machine.read(BASE - STRIDE, STRIDE).hex()}")
    print(f"  one past the last (id {LAST + 1}, would need the bound raised): "
          f"{machine.read(BASE + STRIDE * (LAST + 1), STRIDE).hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Is `track = 16` a rejected value, or a lane the firmware already has?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lane16_maps.py

DNX measured the instrument clearing a lock record with `track = 16`, and the
first reading of that was "the sentinel is dead". A static read of the two
p-lock translators says something different and much better:

    0x400dccc0   arg0 == 16 -> id  must be <= 45, index 0x401fce68
                 arg0 <  16 -> id  must be <= 106, index 0x401fd0b0
    0x400dccfa   arg0 == 16 -> slot must be <= 69, index its own table
                 arg0 <  16 -> slot must be <= 99, index 0x401fcf20

So lane 16 is not out of range. It is a **case**, with its own id space and its
own tables -- and 0x401fce68 maps ids 1..45 onto slots 25..69, which is exactly
the FX and Master block. DNX's probe used id 92, which is a *lane 0* id and is
out of range for lane 16, so a clear is what that record should get.

That is a static read, and three of them in a row have gone well, which is when
this project has been wrong before. So call both routines directly and read the
answers off the machine:

  * every id 0..120 in lane 16 and in lane 5, and every slot likewise;
  * the bound is where the result goes to zero, not where the disassembly says;
  * lane 17 as a control -- if it behaves like lane 5 the `== 16` is exact, and
    if it behaves like lane 16 the test is `>= 16` and the reading is wrong.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine  # noqa: E402

ID_TO_SLOT = 0x400DCCC0
SLOT_TO_ID = 0x400DCCFA


def sweep(machine, fn, lane, limit):
    """-> {index: result} for every index the routine answers non-zero."""
    return {i: machine.call(fn, lane, i) for i in range(limit)}


def report(name, got, lane):
    live = {i: v for i, v in got.items() if v != 0}
    if not live:
        print(f"  lane {lane:2d}  {name}: nothing answered")
        return None
    top = max(live)
    print(f"  lane {lane:2d}  {name}: {len(live)} live, highest input {top}, "
          f"outputs {min(live.values())}..{max(live.values())}")
    return top


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--limit", type=int, default=121)
    args = p.parse_args()

    machine = Machine(args.snapshot)

    print("id -> slot   (0x400dccc0)")
    tops = {}
    for lane in (5, 16, 17):
        tops[("id", lane)] = report("id->slot", sweep(machine, ID_TO_SLOT, lane, args.limit), lane)

    print("slot -> id   (0x400dccfa)")
    for lane in (5, 16, 17):
        tops[("slot", lane)] = report("slot->id", sweep(machine, SLOT_TO_ID, lane, args.limit), lane)

    print()
    print("the prediction, written before the run:")
    print("  id->slot   lane 16 stops at 45,  lane 5 stops at 106, lane 17 answers nothing")
    print("  slot->id   lane 16 stops at 69,  lane 5 stops at  99, lane 17 answers nothing")
    ok = (tops[("id", 16)] == 45 and tops[("id", 5)] == 106 and tops[("id", 17)] is None
          and tops[("slot", 16)] == 69 and tops[("slot", 5)] == 99
          and tops[("slot", 17)] is None)
    print(f"  -> {'CONFIRMED' if ok else 'NOT CONFIRMED -- the static read is wrong somewhere'}")

    if tops[("id", 16)] == 45:
        print()
        print("lane 16, every id and the slot it names:")
        got = sweep(machine, ID_TO_SLOT, 16, 47)
        for i in sorted(k for k, v in got.items() if v):
            print(f"    id {i:3d} -> slot {got[i]:3d}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

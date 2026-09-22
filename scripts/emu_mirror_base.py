"""Is the mirror the evaluator writes the same memory the page reads?

    DT2_SECTIONS=/root/dn2-sections-111 \
        /root/dn2-emu-venv/bin/python -u scripts/emu_mirror_base.py

**Why this exists.** `lfo4-cell` put two live mirror cells on LFO4's page and
the owner watched LFO4's cell sweep a full triangle with LFO3's depth at centre
-- so LFO4 alone was writing it -- while the filter did not move. Two measured
facts that cannot both be about the same memory.

Reading the caller settles what to check. The audio ISR loads the evaluator's
mirror argument from a **pointer**, not from a constant:

    40027120  moveal 0x4058f39c,%a2      ; the mirror base, read from a global
    400272d2  movel  %a2,%sp@-           ; -> the evaluator's first argument
    400272d4  jsr    0x40137726

and `csrc/lfo4/meter.c` reads the **fixed** `0x800068e4`, the base five
independent reads of ColdFire code agreed on and `fxblock16` proved audible.
If `*(0x4058f39c)` is that same address and never moves, the two are one memory
and this reading is closed. If it alternates -- a double buffer -- then a
fixed-address reader sees a sweep while the voice reads the other half, and
that alone would explain every symptom without anything upstream being wrong.

It asks three things and none of them needs a build:

  1. what `*(0x4058f39c)` holds, and whether it equals `0x800068e4`;
  2. whether it ever changes -- sampled across many audio frames;
  3. whether anything writes to it, caught with a write hook rather than by
     sampling, because a pointer that flips and flips back between samples
     would read as constant.

**A null here is only evidence if the ISR actually ran**, so it reports how
many times the frame handler was entered. Zero entries means the harness never
reached the path, which is not the same as the pointer being stable -- the
mistake `emu_lfo4_trig.py` made and the reason this prints it.
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.machine import SNAP, Machine

POINTER = 0x4058F39C          # the global the ISR reads its mirror base from
EXPECTED = 0x800068E4         # what five reads of the code say the mirror is
ISR = 0x40025E36              # the frame handler that calls the evaluator
EVAL_A = 0x40137726


def main() -> int:
    m = Machine(SNAP)

    held = m.long(POINTER)
    print(f"  *(0x4058f39c) = {held:#010x}")
    print(f"  the page reads 0x800068e4")
    if held == EXPECTED:
        print("  -> the same address. One memory, and the double-buffer reading is closed.")
    else:
        delta = held - EXPECTED
        print(f"  -> DIFFERENT, by {delta:+#x} ({delta:+d} bytes).")
        print("     The evaluator and the page are not looking at the same mirror.")

    # Does it move? Watch the pointer itself, not a sample of it: a value that
    # flips and flips back between reads is indistinguishable from a constant.
    writes: list[tuple[int, int]] = []
    try:
        m.watch_write(POINTER, 4, lambda addr, size, value: writes.append((addr, value)))
        watched = True
    except AttributeError:
        watched = False
        print("\n  (no write hook on this Machine; falling back to sampling)")

    seen = {held}
    entries = 0
    for _ in range(64):
        try:
            m.call(ISR)
            entries += 1
        except Exception as exc:                     # noqa: BLE001
            print(f"\n  the ISR could not be called directly: {exc}")
            break
        seen.add(m.long(POINTER))

    print(f"\n  frame handler entered {entries} time(s)")
    if entries == 0:
        print("  **The harness never reached the path.** That is not evidence that")
        print("  the pointer is stable -- it is evidence of nothing. Drive the ISR")
        print("  another way before reading anything into this.")
        return 2
    print(f"  distinct values seen: {', '.join(f'{v:#010x}' for v in sorted(seen))}")
    if watched:
        print(f"  writes to the pointer caught: {len(writes)}")
    if len(seen) > 1:
        print("\n  **It moves.** The mirror is not one buffer, and a reader at a fixed")
        print("  address sees only part of what the evaluator writes.")
        return 1
    print("\n  One value throughout. On this path the pointer is stable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

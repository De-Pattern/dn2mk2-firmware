"""Do the save and load leave the LFO4 table alone for sounds with no LFO4?

    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_lfo4_pollution.py --build out/lfo4-everyvoice2

**Why this exists.** Until 2026-09-25 `lfo4_on_save` wrote LFO4's default row
into every sound that had no LFO4 (`csrc/lfo4/store.c`, `is_default`). Every
sound in the owner's saved project came back carrying
`7000 0300 4000 0000 0000 0000 0000 4000`, the next load inserted an entry per
sound into a 256-slot table, the table filled, and LFO4's knobs stopped doing
anything. `emu_boot_engine.py` did not catch it: it only round-trips a sound
that *does* carry LFO4 values.

**Three checks, each with its own expected answer**, in one boot of the build:

1. **A polluted sound loads as no LFO4.** A stored sound whose lane is the
   default row goes through the stock LOAD; the table must stay empty.
2. **A sound with no entry saves as zeros.** A live sound with no table entry
   goes through the stock SAVE; its lane must be all zeros.
3. **The control: a real LFO4 still round-trips.** A live sound with eight
   recognisable values saves them, and loading that stored sound brings them
   back. Without this, 1 and 2 would also pass on a build whose hooks never ran.

Exit status 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import emu_boot_engine as eng                                  # noqa: E402
from emu import dspboot                                        # noqa: E402

DEFAULT_ROW = [0x7000, 0x0300, 0x4000, 0x0000, 0x0000, 0x0000, 0x0000, 0x4000]
MARKS = [0x2A01, 0x2A02, 0x2A03, 0x2A04, 0x2A05, 0x2A06, 0x2A07, 0x2A08]


def lane(after, stored):
    return [int.from_bytes(bytes(after.uc.mem_read(stored + eng.VALUES_AT + 2 * i, 2)), "big")
            for i in eng.LFO4_IDS]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-everyvoice2")
    p.add_argument("--limit", type=int, default=400_000_000)
    args = p.parse_args()

    build = os.path.join(eng.ROOT, args.build)
    sym = {k: int(v, 16) for k, v in json.load(open(f"{build}/symbols.json")).items()}
    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(eng.SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out={})
    after = eng.After(m.uc)
    live_n = lambda: after.long(sym["ext_live"])
    print(f"  ran {st['n']:,}, stop {stop!r}; table entries after boot: {live_n()}")
    fails = []

    # 1. polluted sound -> LOAD -> no entry
    src = eng.stored_sound(after, DEFAULT_ROW)
    live = after.alloc(eng.SOUND_BYTES)
    before = live_n()
    after.call(eng.LOAD, live, src)
    got = live_n() - before
    ok = got == 0 and eng.table_read(after, sym, live, 0) is None
    print(f"\n  1. load a sound whose lane is the default row: {got} new entr(y/ies) "
          f"-> {'PASS' if ok else 'FAIL'}")
    if not ok:
        fails.append("polluted load")

    # 2. live sound with no entry -> SAVE -> zeros
    live2 = after.alloc(eng.SOUND_BYTES)
    after.write(live2, bytes(after.uc.mem_read(live, eng.SOUND_BYTES)))
    out = after.alloc(eng.STORED + 16)
    after.write(out, bytes([0xBE, 0xEF, 0xBA, 0xCE]) + bytes(eng.STORED - 4))
    after.call(eng.SAVE, out, live2, 0)
    ln = lane(after, out)
    ok = ln == [0] * 8
    print(f"  2. save a sound with no LFO4 entry: lane {[hex(v) for v in ln]} "
          f"-> {'PASS' if ok else 'FAIL'}")
    if not ok:
        fails.append("no-entry save")

    # 3. control: a real LFO4 round-trips
    live3 = after.alloc(eng.SOUND_BYTES)
    after.write(live3, bytes(after.uc.mem_read(live, eng.SOUND_BYTES)))
    for k, v in enumerate(MARKS):
        after.call(sym["ext_set"], live3, k, v)
    out3 = after.alloc(eng.STORED + 16)
    after.write(out3, bytes([0xBE, 0xEF, 0xBA, 0xCE]) + bytes(eng.STORED - 4))
    after.call(eng.SAVE, out3, live3, 0)
    saved = lane(after, out3)
    live4 = after.alloc(eng.SOUND_BYTES)
    after.call(eng.LOAD, live4, out3)
    back = [eng.table_read(after, sym, live4, k) for k in range(8)]
    ok = saved == MARKS and back == MARKS
    print(f"  3. control, a real LFO4: saved {[hex(v) for v in saved]}, "
          f"loaded back {[hex(v) if v is not None else None for v in back]} "
          f"-> {'PASS' if ok else 'FAIL'}")
    if not ok:
        fails.append("real LFO4 round trip")

    print(f"\n  {'all three pass' if not fails else 'FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

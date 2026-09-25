"""Does the firmware's own working-state save carry LFO4?

    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_lfo4_persist.py --build out/lfo4-everyvoice

**The symptom.** LFO4 settings never survive a reboot, while every other page's
do (owner, 2026-09-22 and 2026-09-25). LFO4's values live in a side table keyed
by the live sound's address, and they reach storage only through our hook on the
sound converter `SAVE` (`0x400dd6a6`). Everything Elektron stores is inside the
sound's own bytes, so any save path that copies sounds raw -- or that never
calls `SAVE` -- persists every page but ours.

**Why this runs instead of reading.** The working state is written by a queued
job named *"Write project MRAM"* (invoker `0x4002c694`, which calls
`0x400e1494(0x405cd96c, project, ...)`), and a second one named
*"saveProjectToMmc(tempProject)"* (invoker `0x4004029c`). Between them and
`SAVE` sit vtable calls and register-indirect `jsr %aN@`, which `dnfw fn
callers` and `refscan.py` both miss -- the kit SAVE at `0x400dde9e` reaches
`SAVE` through `lea %pc@(0x400dd6a6),%a4`, invisible to either. Static
reachability from here has already returned one wrong answer today (the only
statically visible route serialises *default* sounds, `0x4004c53a`). So: call
the firmware's own writer and count what arrives at our hook.

**What it does.** Boot from reset; give track 7's live sound an LFO4 entry with
eight recognisable values; call the MRAM writer; record every `lfo4_on_save` --
how many, which live pointers, and whether each was one of the sixteen live
sounds. Then read the stored sound it produced for track 7's marks.

**Three outcomes, all useful:**

- `lfo4_on_save` never runs -> the working-state save does not use `SAVE`; LFO4
  must be carried some other way (the finding).
- it runs, but never with track 7's live pointer -> it serialises a copy, and
  the side table misses under the copy's address.
- it runs with track 7's pointer and the marks land -> the save side is fine,
  and the loss is on the restore side at boot.

**Read-only against the firmware:** the only writes are the harness's own
scratch and one LFO4 table entry, exactly what a knob turn makes.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import emu_boot_engine as eng                                  # noqa: E402
from emu import dspboot                                        # noqa: E402
from unicorn import UC_HOOK_CODE, UcError                      # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7                  # noqa: E402

MRAM_WRITE = 0x4002C694          # invoker of the "Write project MRAM" job
MMC_WRITE = 0x4004029C           # invoker of "saveProjectToMmc(tempProject)"
LIVE_CONTAINER = 0x800052A0
SOUND_AT, STRIDE = 52, 1163
TRACK = 6                        # track 7
MARKS = [0x2A01, 0x2A02, 0x2A03, 0x2A04, 0x2A05, 0x2A06, 0x2A07, 0x2A08]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-everyvoice")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--writer", choices=("mram", "mmc"), default="mram")
    args = p.parse_args()

    build = os.path.join(eng.ROOT, args.build)
    sym = {k: int(v, 16) for k, v in json.load(open(f"{build}/symbols.json")).items()}
    holder, saves, loads = {}, [], []

    def pre_start(m):
        def at_save(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            stored, live = struct.unpack(">II", bytes(uc.mem_read(sp + 4, 8)))
            saves.append((stored, live))

        def at_load(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            live, stored = struct.unpack(">II", bytes(uc.mem_read(sp + 4, 8)))
            loads.append((live, stored))

        m.uc.hook_add(UC_HOOK_CODE, at_save, begin=sym["lfo4_on_save"], end=sym["lfo4_on_save"])
        m.uc.hook_add(UC_HOOK_CODE, at_load, begin=sym["lfo4_on_load"], end=sym["lfo4_on_load"])

    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(eng.SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}; boot made {len(saves)} save(s), {len(loads)} load(s)")

    after = eng.After(m.uc)
    base = after.long(LIVE_CONTAINER)
    lives = {base + SOUND_AT + STRIDE * t: t for t in range(16)} if base else {}
    target = base + SOUND_AT + STRIDE * TRACK if base else 0
    print(f"  live container {base:#010x}; track 7's live sound {target:#010x}")
    if not base:
        print("  ** no live container after boot: nothing to save. **")
        return 1

    for k, v in enumerate(MARKS):
        after.call(sym["ext_set"], target, k, v)
    got = [eng.table_read(after, sym, target, k) for k in range(len(MARKS))]
    print(f"  LFO4 entry for track 7 now holds {[hex(g) if g is not None else None for g in got]}")

    saves.clear()
    loads.clear()
    fn = MRAM_WRITE if args.writer == "mram" else MMC_WRITE
    print(f"\n  calling the firmware's own {args.writer.upper()} writer at {fn:#010x}")
    storage = after.alloc(16)
    try:
        after.call(fn, storage, 0, 0, masked=False)
    except UcError as exc:
        print(f"  ** the writer stopped: {exc} **")

    print(f"  lfo4_on_save ran {len(saves)} time(s) during the write")
    kinds = collections.Counter("live track %d" % lives[l] if l in lives else "NOT a live sound"
                                for _, l in saves)
    for k, n in kinds.most_common():
        print(f"     {n:4d}  {k}")
    hit = [(s, l) for s, l in saves if l == target]
    if not saves:
        print("\n  ** the working-state write never reached SAVE: LFO4 cannot be persisted "
              "by the converter hook on this path. **")
    elif not hit:
        print("\n  ** SAVE ran, but never with track 7's live sound: it serialises a copy, "
              "and the side table misses under the copy's address. **")
    else:
        stored = hit[-1][0]
        vals = [int.from_bytes(bytes(after.uc.mem_read(stored + 28 + 2 * i, 2)), "big")
                for i in (4, 8, 12, 16, 20, 24, 28, 32)]
        ok = vals == MARKS
        print(f"\n  track 7 was saved into {stored:#010x}; its LFO4 ids hold "
              f"{[hex(v) for v in vals]} -> {'the marks landed' if ok else 'NOT the marks'}")
        if ok:
            print("  ** the save side carries LFO4; the loss is on the restore side at boot. **")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

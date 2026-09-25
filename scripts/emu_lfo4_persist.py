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
MEMCPY = 0x40134490
PROJECT_HOLDER = 0x4018A97A      # -> the object whose vtable +40 yields the project
SERIALISE = 0x400E1494           # (image, project, 0, flags, progress)
MRAM_IMAGE = 0x405CD96C          # the image the MRAM job serialises into
KITS_AT, KIT_BYTES = 0xEF371C, 23921   # the project's 129 kits, from 0x400e1646
LIVE_CONTAINER = 0x800052A0
SOUND_AT, STRIDE = 52, 1163
TRACK = 6                        # track 7
MARKS = [0x2A01, 0x2A02, 0x2A03, 0x2A04, 0x2A05, 0x2A06, 0x2A07, 0x2A08]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-everyvoice")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--writer", choices=("mram", "mmc"), default="mram")
    p.add_argument("--boot-only", action="store_true",
                   help="report the boot's own SAVE/LOAD keys and stop; no writer call")
    p.add_argument("--direct", action="store_true",
                   help="call the serialiser 0x400e1494 itself, with the job's own project")
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

    # **The boot already ran the serialiser, 2,192 times.** 2,192 is exactly
    # 129 kits x 16 + 128 pool sounds, so the boot builds the project's stored
    # image through SAVE -- and the live pointer each call carried says whether
    # that image is serialised from the live container (our table's keys) or
    # from a copy. This needs no writer call, and no singleton the emulator's
    # boot never gets as far as building (0x4018a97a, 2026-09-25).
    in_live = collections.Counter(lives[l] for _, l in saves if l in lives)
    others = [l for _, l in saves if l not in lives]
    print(f"\n  boot SAVEs keyed on a live-container sound: {sum(in_live.values())} "
          f"(tracks {sorted(in_live)})")
    print(f"  boot SAVEs keyed elsewhere: {len(others)}")
    if others:
        kitish = collections.Counter(((l - SOUND_AT) - base) % 23921 // STRIDE
                                     for l in others if (l - SOUND_AT - base) % 23921 % STRIDE == 0)
        lo_, hi_ = min(others), max(others)
        print(f"    range {lo_:#010x}..{hi_:#010x}; on the 23,921-byte kit grid from the "
              f"live container: {sum(kitish.values())} of {len(others)}")
        print(f"    first few: {[hex(x) for x in others[:6]]}")
    boot_loads_live = sum(1 for l, _ in loads if l in lives)
    print(f"  boot LOADs keyed on a live-container sound: {boot_loads_live} of {len(loads)}")

    # **The table after the boot.** Stored id 32 is a stock parameter (slot 3),
    # not a free hole (emu_sound_roundtrip.py, 2026-09-25), and LFO4's DEP was
    # stored there -- so nearly every stock sound looks as if it carries an LFO4
    # on load, and 2,192 loads compete for a 256-entry table.
    counters = {n: after.long(sym[n]) for n in ("ext_live", "ext_inserts", "ext_drops", "ext_full",
                                                "ext_overflow", "lfo4_loads", "lfo4_loads_carrying")
                if n in sym}
    print("  after boot: " + ", ".join(f"{k}={v}" for k, v in counters.items()))
    track7 = [eng.table_read(after, sym, target, k) for k in range(len(MARKS))]
    print(f"  track 7's table entry after boot: {track7}")
    if args.boot_only:
        return 0

    # **Is the live container one of the project's 129 kits?** The MRAM
    # serialiser (0x400e1494, component bit 1) saves kit i from
    # `project + 0xef371c + 23921*i` through the kit SAVE at 0x400dde44. Our
    # table is keyed on the live container's sounds, so LFO4 reaches storage
    # only if the live container is one of those kits. The project is fetched
    # the way the MRAM job itself does: 0x4018a97a(), then its vtable slot +40.
    project = 0
    try:
        obj = after.call(PROJECT_HOLDER)
        project = after.call(after.long(after.long(obj) + 40), obj) if obj else 0
    except UcError as exc:
        print(f"  could not fetch the project: {exc}")
    kits = project + KITS_AT if project else 0
    print(f"  project {project:#010x}; its 129 kits start at {kits:#010x}")
    if project:
        rel = base - kits
        if 0 <= rel and rel % KIT_BYTES == 0 and rel // KIT_BYTES < 129:
            print(f"  ** the live container IS project kit {rel // KIT_BYTES}: the MRAM save "
                  f"serialises the addresses our table is keyed on **")
        else:
            print(f"  ** the live container is NOT one of the project's kits (offset "
                  f"{rel:+#x}): the MRAM save serialises a copy, and the side table misses "
                  f"every LFO4 value under the copy's addresses **")

    for k, v in enumerate(MARKS):
        after.call(sym["ext_set"], target, k, v)
    got = [eng.table_read(after, sym, target, k) for k in range(len(MARKS))]
    print(f"  LFO4 entry for track 7 now holds {[hex(g) if g is not None else None for g in got]}")

    saves.clear()
    loads.clear()
    # **The control beside the negative.** A writer that returns early -- the
    # project not dirty, a queue not yet running -- reports zero saves exactly
    # like one that saves raw. So count what it actually does: instructions,
    # and every memcpy with its source, so a raw copy of track 7's sound shows.
    work = {"n": 0, "copies": []}

    def count(uc, address, size, user):
        work["n"] += 1

    def at_memcpy(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        dst, src, n = struct.unpack(">III", bytes(uc.mem_read(sp + 4, 12)))
        work["copies"].append((dst, src, n))

    h1 = m.uc.hook_add(UC_HOOK_CODE, count)
    h2 = m.uc.hook_add(UC_HOOK_CODE, at_memcpy, begin=MEMCPY, end=MEMCPY)
    fn = MRAM_WRITE if args.writer == "mram" else MMC_WRITE
    storage = after.alloc(16)
    try:
        if args.direct and project:
            # The serialiser itself, with the job's own project:
            # (image, project, 0, flags = -1 for every component, progress).
            prog = after.alloc(16)
            print(f"\n  calling the serialiser {SERIALISE:#010x} directly on project {project:#010x}")
            after.call(SERIALISE, MRAM_IMAGE, project, 0, 0xFFFFFFFF, prog, masked=False)
        else:
            print(f"\n  calling the firmware's own {args.writer.upper()} writer at {fn:#010x}")
            after.call(fn, storage, 0, 0, masked=False)
    except UcError as exc:
        print(f"  ** the writer stopped: {exc} **")

    m.uc.hook_del(h1)
    m.uc.hook_del(h2)
    print(f"  the writer executed {work['n']:,} instruction(s) and made {len(work['copies'])} memcpy call(s)")
    lo, hi = base + SOUND_AT, base + SOUND_AT + 16 * STRIDE
    raw = [(d, s, n) for d, s, n in work["copies"] if s < hi and s + n > lo]
    for d, s, n in raw[:8]:
        print(f"     memcpy({d:#010x}, {s:#010x}, {n}) -- overlaps the live sounds "
              f"{'INCLUDING track 7' if s <= target < s + n else ''}")
    big = sorted(work["copies"], key=lambda c: -c[2])[:5]
    print("  largest copies: " + ", ".join(f"{n}B {s:#x}->{d:#x}" for d, s, n in big))
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

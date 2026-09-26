"""Boot from reset, then run the engine: the combination nothing has tested.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_boot_engine.py [--build out/lfo4-bridge] [--frames 8] \
        [--arp-mode 5 --arp-mode 6 --arp-max 6]

`lfo4-bridge` boots here for 400 M instructions and never faults -- and
`emu_boot_fault.py` also reported `lfo4_refresh` **zero times**. The audio
engine does not run in this emulator, so the boot never executes the one thing
the build added. That is why a clean boot and a faulting instrument are not a
contradiction.

Two harnesses already exist and each misses half of it:

- the snapshot harnesses call the evaluators, but **install the code chunk
  themselves** into an already-booted `ui1200M`, so the real loader never runs;
- the boot harness runs the real loader, but **never calls the evaluators**.

The instrument does both. So this boots from reset -- the firmware's own
loader copies our chunk, zeroes its BSS and calls its init -- and *then* enters
evaluator A the way `emu_lfo4_tick.py` does, with the exception reporter hooked
throughout. If the loader leaves the code in a state the direct-install path
never produces, this is where it shows.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UC_PROT_ALL, UcError        # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A2, UC_M68K_REG_A6,   # noqa: E402
                                UC_M68K_REG_A7, UC_M68K_REG_D0,
                                UC_M68K_REG_PC, UC_M68K_REG_SR)

from emu_lfo4_tick import (EVAL_A, MIRROR_AT, MIRROR_BYTES, RATE, REST,   # noqa: E402
                           SET_FRAC, STATE, STATE_LEN, TRACKS)

LOAD, SAVE = 0x400DD1EA, 0x400DD6A6     # (live, stored) and (stored, live, flag)
SOUND_BYTES, STORED, VALUES_AT = 1163, 359, 28
LFO4_IDS = [4, 8, 12, 16, 20, 24, 28, 32]          # the reserved p-lock ranks
MARKS = [0x2A01, 0x2A02, 0x2A03, 0x2A04, 0x2A05, 0x2A06, 0x2A07, 0x2A08]
EXT_SLOTS, EXT_PARAMS = 256, 8

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
REPORTER = 0x4011EA6A
STACK, SCRATCH = 0x46A00000, 0x46A10000       # above BSS end 0x466b74d0


class After:
    """The machine a boot left behind, with just enough to call into it."""

    def __init__(self, uc):
        self.uc = uc
        self.ret = STACK + 0x800
        self.at = SCRATCH

    def write(self, va, data):
        try:
            self.uc.mem_write(va, data)
        except UcError:
            for page in range(va & ~0xFFFFF, va + len(data) + 0x100000, 0x100000):
                try:
                    self.uc.mem_map(page, 0x100000, UC_PROT_ALL)
                except UcError:
                    pass
            self.uc.mem_write(va, data)

    def alloc(self, n):
        va = (self.at + 15) & ~15
        self.at = va + n
        self.write(va, bytes(n))
        return va

    def long(self, va):
        return struct.unpack(">I", bytes(self.uc.mem_read(va, 4)))[0]

    def call(self, fn, *args, masked=True):
        """Call a routine in the booted machine. -> d0.

        `masked` raises the interrupt level to 7 for the duration, and it is
        the default because **a call that gets interrupted returns a plausible
        lie**. A booted machine has live timers; an interrupt vectors away,
        `emu_start` stops on its instruction count instead of at the return
        address, and d0 holds whatever the handler left -- which came back as
        **0**, for 330 calls in a row, in `emu_table_watch.py`'s first run. The
        project had already recorded this exact failure once
        (`docs/lfo4-build-plan.md` §"Step 4a result") and the answer there was
        to read memory instead. That works when the value is in memory; when
        what is being tested *is* the routine's answer, the fix is to stop the
        interrupt instead. Pass `masked=False` for a call that needs the
        scheduler to run underneath it.
        """
        frame = struct.pack(">I", self.ret) + b"".join(
            struct.pack(">I", a & 0xFFFFFFFF) for a in args)
        self.write(STACK, frame)
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A6, 0)
        sr = self.uc.reg_read(UC_M68K_REG_SR)
        if masked:
            self.uc.reg_write(UC_M68K_REG_SR, (sr & ~0x0700) | 0x2700)
        try:
            self.uc.emu_start(fn, self.ret, count=20_000_000)
            return self.uc.reg_read(UC_M68K_REG_D0)
        finally:
            if masked:
                self.uc.reg_write(UC_M68K_REG_SR, sr)


def table_read(after, sym, key, param):
    """-> `ext_val[key][param]` out of memory, or None.

    Not `call(ext_get, ...)`: a call into firmware-resident code can be
    interrupted, and then `emu_start` stops on its instruction count and hands
    back whatever d0 holds -- which came back as 0 once and read exactly like
    "the value never arrived" (`docs/lfo4-build-plan.md` §"Step 4a result").
    """
    for i in range(EXT_SLOTS):
        if after.long(sym["ext_key"] + 4 * i) == key:
            return int.from_bytes(bytes(after.uc.mem_read(
                sym["ext_val"] + 2 * (i * EXT_PARAMS + param), 2)), "big")
    return None


def stored_sound(after, marks):
    """A stored track the converter will accept: magic, version, name, values."""
    at = after.alloc(STORED + 16)
    after.write(at, bytes([0xbe, 0xef, 0xba, 0xce]) + (3).to_bytes(4, 'big'))
    after.write(at + 12, b"LFO4 TEST" + bytes(1))
    for i in range(107):                       # a distinct value per id, so a
        after.write(at + VALUES_AT + 2 * i, bytes([0x40, i]))   # stray word shows
    for k, v in enumerate(marks):
        after.write(at + VALUES_AT + 2 * LFO4_IDS[k], v.to_bytes(2, "big"))
    return at


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-bridge")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--arp-mode", type=int, action="append", default=[],
                   help="after the engine, SAVE and LOAD a sound with this arp MODE; repeatable")
    p.add_argument("--arp-max", type=int, default=4,
                   help="the highest MODE the build's LOAD keeps (4 stock, 6 arpmodes)")
    args = p.parse_args()

    build = os.path.join(ROOT, args.build)
    # **A build with no symbols still needs its engine run.** This harness grew
    # around LFO4 and read `symbols.json` unconditionally, so a plain code-cave
    # build -- which exports nothing and therefore writes no such file -- could
    # not be engine-gated at all: it died on FileNotFoundError before booting.
    # That is a hole in the shipping gate rather than a property of the build,
    # because a cave hooked into the frame path touches the engine exactly as
    # much as LFO4 does. Without symbols the LFO4-specific coverage is skipped
    # and everything that does not depend on them still runs.
    symbols = pathlib.Path(f"{build}/symbols.json")
    sym = ({k: int(v, 16) for k, v in json.loads(symbols.read_text()).items()}
           if symbols.exists() else {})
    if not sym:
        print(f"  no symbols.json in {args.build}: running the engine anyway, "
              f"with no per-routine coverage to report")
    watch = {n: sym[n] for n in ("dnfw_boot", "lfo4_init", "lfo4_refresh") if n in sym}

    holder, counts, fault = {}, {}, {}

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            if not fault:
                a2 = uc.reg_read(UC_M68K_REG_A2)
                try:
                    fault.update(at=st["n"], a2=a2, record=bytes(uc.mem_read(a2, 16)).hex())
                except Exception:                              # noqa: BLE001
                    fault.update(at=st["n"], a2=a2, record="")
            uc.emu_stop()

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        for name, addr in watch.items():
            def hit(uc, address, size, user, name=name):
                counts[name] = counts.get(name, 0) + 1
            m.uc.hook_add(UC_HOOK_CODE, hit, begin=addr, end=addr)

    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}; reached {counts}")
    if fault:
        print(f"\n  FAULT during boot at {fault['at']:,}: record {fault['record']}")
        return 1

    after = After(m.uc)
    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf = after.alloc(span)
    after.write(buf, struct.pack(">H", REST) * (span // 2))
    for base in STATE:
        after.write(base, bytes(STATE_LEN))
    frac = after.alloc(len(SET_FRAC))
    after.write(frac, SET_FRAC)
    after.call(frac)

    before = counts.get("lfo4_refresh", 0)
    rate = after.long(RATE)
    out1, out2 = after.alloc(256), after.alloc(256)
    print(f"\n  entering evaluator A at {EVAL_A:#010x}, {args.frames} frame(s), "
          f"scale {rate:#06x}")
    try:
        for _ in range(args.frames):
            after.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)
    except UcError as exc:
        pc = after.uc.reg_read(UC_M68K_REG_PC)
        print(f"\n  ** the evaluator faulted: {exc} at pc {pc:#010x} **")
        print(f"  lfo4_refresh ran {counts.get('lfo4_refresh', 0) - before} time(s) first")
        return 1

    ran = counts.get("lfo4_refresh", 0) - before
    print(f"  lfo4_refresh ran {ran} time(s) during {args.frames} frame(s)")
    if fault:
        print(f"\n  ** the firmware drew EXCEPTION: record {fault['record']} **")
        return 1
    if not ran and watch:
        print("\n  the engine ran and never called our code: this proves nothing.\n"
              "  Check that the build's stubs are actually in the path entered here.")
        return 1
    # Without symbols there is nothing of the build's to watch for (`watch` is
    # empty), so `ran` is 0 whatever happens. Refusing on it made the no-symbols
    # branch below unreachable -- every cave build failed here, engine clean or not.
    print("  the engine path ran clean under a real loader boot"
          + ("." if watch else " (this build puts nothing of its own on it)."))

    # A sound's arp MODE through the stock converters, in the booted machine:
    # arpmodes widens the LOAD bound (0x400dd530), and a snapshot harness never
    # ran that converter in a machine our image booted.
    fails = []
    if args.arp_mode:
        base = after.long(0x800052A0)
        real = bytes(after.uc.mem_read(base + 52, SOUND_BYTES)) if base else bytes(SOUND_BYTES)
        print("")
        for v in args.arp_mode:
            live = after.alloc(SOUND_BYTES + 16)
            s = bytearray(real)
            s[351] = v & 0xFF
            after.write(live, bytes(s))
            stored = after.alloc(STORED + 16)
            after.call(SAVE, stored, live, 0)
            on_disk = bytes(after.uc.mem_read(stored + 331, 1))[0]
            back = after.alloc(SOUND_BYTES + 16)
            after.call(LOAD, back, stored)
            got = bytes(after.uc.mem_read(back + 351, 1))[0]
            again = after.alloc(STORED + 16)
            after.call(SAVE, again, back, 0)
            same = bytes(after.uc.mem_read(again, STORED)) == bytes(after.uc.mem_read(stored, STORED))
            want = v if 0 <= v <= args.arp_max else 0
            ok = on_disk == v and got == want and (same or want != v)
            print(f"  {'ok  ' if ok else 'FAIL'}  arp MODE {v}: saved {on_disk}, loaded {got} "
                  f"(want {want}); saved again {'identical' if same else 'differs'}")
            if not ok:
                fails.append(f"arp MODE {v} did not round-trip as {want}")

    # The save/load path, in the same boot. It is the one piece the gate
    # cannot see from a boot alone: no kit loads at reset, so the two
    # converter stubs never run, and until now they had only ever been
    # exercised from `ui1200M` -- a machine our loader never booted.
    if not sym:
        # Nothing to convert and no counters to read. The engine half above has
        # already run, which is the part a cave build needs; saying so beats
        # dying on a KeyError and beats pretending the build was fully gated.
        print("")
        print("  save/load: skipped -- this build exports no LFO4 symbols, so")
        print("  there are no converters to exercise. The boot and the engine")
        print("  above did run; the save/load path is untested here"
              + (", beyond the arp MODE round trip." if args.arp_mode else "."))
        if fault:
            print(f"\n  ** the firmware drew EXCEPTION during save/load: {fault} **")
            return 1
        for f in fails:
            print("  FAIL  " + f)
        return 1 if fails else 0

    src = stored_sound(after, MARKS)
    live = after.alloc(SOUND_BYTES)
    loads_before = after.long(sym["lfo4_loads"])
    after.call(LOAD, live, src)
    got = [table_read(after, sym, live, k) for k in range(EXT_PARAMS)]
    print("")
    print(f"  load: the table holds {[hex(v) if v is not None else None for v in got]}")
    if got != MARKS:
        fails.append("the load did not put the eight marks in the table")
    if after.long(sym["lfo4_loads"]) - loads_before != 1:
        fails.append("the load was not counted once")

    back = after.alloc(STORED + 16)
    saves_before = after.long(sym["lfo4_saves"])
    after.call(SAVE, back, live, 0)
    ids = [int.from_bytes(bytes(after.uc.mem_read(back + VALUES_AT + 2 * i, 2)), 'big')
           for i in LFO4_IDS]
    print(f"  save: the stored ids hold {[hex(v) for v in ids]}")
    if ids != MARKS:
        fails.append("the save did not write the eight back to their ids")
    if after.long(sym["lfo4_saves"]) - saves_before != 1:
        fails.append("the save was not counted once")

    if fault:
        print("")
        print(f"  ** the firmware drew EXCEPTION during save/load: {fault} **")
        return 1
    if fails:
        print("")
        for f in fails:
            print("  FAIL  " + f)
        return 1
    print("")
    print("  boot from reset, the engine, and save/load: all three in one machine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

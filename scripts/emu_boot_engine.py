"""Boot from reset, then run the engine: the combination nothing has tested.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_boot_engine.py [--build out/lfo4-bridge] [--frames 8]

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
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UC_PROT_ALL, UcError        # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A2, UC_M68K_REG_A6,   # noqa: E402
                                UC_M68K_REG_A7, UC_M68K_REG_D0,
                                UC_M68K_REG_PC)

from emu_lfo4_tick import (EVAL_A, MIRROR_AT, MIRROR_BYTES, RATE, REST,   # noqa: E402
                           SET_FRAC, STATE, STATE_LEN, TRACKS)

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

    def call(self, fn, *args):
        frame = struct.pack(">I", self.ret) + b"".join(
            struct.pack(">I", a & 0xFFFFFFFF) for a in args)
        self.write(STACK, frame)
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A6, 0)
        self.uc.emu_start(fn, self.ret, count=20_000_000)
        return self.uc.reg_read(UC_M68K_REG_D0)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-bridge")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--frames", type=int, default=8)
    args = p.parse_args()

    build = os.path.join(ROOT, args.build)
    sym = {k: int(v, 16) for k, v in json.load(open(f"{build}/symbols.json")).items()}
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
    if not ran:
        print("\n  the engine ran and never called our code: this proves nothing.\n"
              "  Check that the build's stubs are actually in the path entered here.")
        return 1
    print("\n  booted by the real loader, and the engine path ran clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

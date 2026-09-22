"""Does `fxblock16`'s cave run, and does it move the halfword it claims to?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_fxblock16.py

**Why this exists, instead of `emu_boot_engine.py`.** That gate asks the right
question for the LFO4 ladder and is the wrong instrument for this build: it
loads `out/<build>/symbols.json` and counts `lfo4_refresh`, so it can only run
against a build that carries a compiled chunk. `fxblock16` carries a 62-byte
cave and no chunk at all, and pointing that script at it fails on a missing
file rather than reporting anything. Recording "not applicable" and moving on
is how this project has produced its expensive negatives (`docs/PRINCIPLES.md`
section 19), so the same question is asked here in the form this build can
answer.

**What the emulator can and cannot settle.** It does not model the DSP, so it
cannot say whether the sound chip acts on mirror block 16 -- that is what the
flash is for. It also does not run the audio engine, so the vector-191 handler
this cave is hooked into never fires during a boot; `emu_boot_engine.py`'s own
docstring records the same fact about `lfo4_refresh`. What it *can* settle is
everything short of the wire:

1. the image boots from reset with the hook and the cave in it -- that is
   `emu_boot_check.py`, run separately, and it is not repeated here;
2. the cave's bytes, as the real loader placed them, **execute** without
   faulting;
3. the counter address above BSS accepts a read-modify-write;
4. the store lands on `0x800075ec` and walks the whole `0x0000`..`0x7f00`
   triangle over 2,048 calls, which is the claim the build rests on.

It runs the payload directly -- `emu_start` from the cave's first instruction
to the first displaced stock instruction -- rather than the whole detour,
because the detour ends by jumping back into the middle of an ISR that is not
running here. That is the same trade `emu_boot_engine.py` makes when it calls
evaluator A by hand.

**A watch must be able to produce a different answer for each outcome**
(`docs/code-caves.md`). A triangle is exactly that: a cell that only ever reads
zero is a failure here, not an ambiguity.
"""

from __future__ import annotations

import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UC_PROT_ALL, UcError        # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A7, UC_M68K_REG_PC,   # noqa: E402
                                UC_M68K_REG_SR)

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
SECTION = f"{ROOT}/out/fxblock16/section_3_MAIN_OS.bin"

REPORTER = 0x4011EA6A            # the firmware's own EXCEPTION formatter
CAVE = 0x4028EA02                # the payload's first instruction
PAYLOAD_END = 0x4028EA40         # the first displaced stock instruction
TARGET = 0x800075EC              # mirror[16][35] -- Delay Feedback Gain
COUNTER = 0x46704000             # the payload's own counter, above BSS
STACK = 0x46A00000               # scratch stack, as emu_boot_engine.py uses
PERIOD = 2048                    # ISR calls in one full triangle
FULL_SCALE = 0x7F00
LIMIT = 400_000_000


def ensure(uc, address: int, size: int = 4) -> None:
    """Map the page holding `address` if the boot has not already.

    `0x46704000` is above the BSS end and the emulator has no reason to have
    mapped it; the instrument does, which `lfo4-tick6a` established on hardware
    with a 12 KB block at `0x46700000`. Mapping it here tests the payload, not
    the address -- that part is hardware's answer, already given.
    """
    for page in range(address & ~0xFFFFF,
                      address + size + 0x100000, 0x100000):
        try:
            uc.mem_read(page, 1)
        except UcError:
            try:
                uc.mem_map(page, 0x100000, UC_PROT_ALL)
            except UcError:
                pass


def main() -> int:
    holder, fault = {}, {}
    entries = {"cave": 0}

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            if not fault:
                fault.update(at=st["n"])
            uc.emu_stop()

        def at_cave(uc, address, size, user):
            entries["cave"] += 1

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        m.uc.hook_add(UC_HOOK_CODE, at_cave, begin=CAVE, end=CAVE)

    print(f"  booting fxblock16 from reset, {LIMIT:,} instructions")
    m, st, stop = dspboot.run(SYX, open(SECTION, "rb").read(),
                              limit=LIMIT, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    if fault:
        print(f"  ** the firmware drew EXCEPTION at {fault['at']:,} **")
        return 1
    print(f"  the cave was entered {entries['cave']} time(s) during the boot --")
    print("  expected 0: the audio engine does not run in this emulator")

    uc = m.uc
    ensure(uc, COUNTER)
    ensure(uc, TARGET)
    ensure(uc, STACK - 0x2000, 0x4000)
    uc.mem_write(COUNTER, struct.pack(">I", 0))
    uc.mem_write(TARGET, struct.pack(">H", 0))

    sr = uc.reg_read(UC_M68K_REG_SR)
    uc.reg_write(UC_M68K_REG_SR, (sr & ~0x0700) | 0x2700)

    print(f"  running the payload {2 * PERIOD} times, "
          f"{CAVE:#010x}..{PAYLOAD_END:#010x}")
    seen = []
    try:
        for _ in range(2 * PERIOD):
            uc.reg_write(UC_M68K_REG_A7, STACK)
            uc.emu_start(CAVE, PAYLOAD_END, count=64)
            pc = uc.reg_read(UC_M68K_REG_PC)
            if pc != PAYLOAD_END:
                print(f"  ** the payload did not reach {PAYLOAD_END:#010x}: "
                      f"pc is {pc:#010x} **")
                return 1
            seen.append(struct.unpack(">H", bytes(uc.mem_read(TARGET, 2)))[0])
    except UcError as exc:
        print(f"  ** the payload faulted: {exc} at pc "
              f"{uc.reg_read(UC_M68K_REG_PC):#010x} **")
        return 1
    finally:
        uc.reg_write(UC_M68K_REG_SR, sr)

    first, second = seen[:PERIOD], seen[PERIOD:]
    print(f"  {TARGET:#010x} reached {min(seen):#06x}..{max(seen):#06x}, "
          f"{len(set(seen))} distinct values")
    print("  every 128th call: " + " ".join(f"{v:#06x}" for v in first[::128]))

    fails = []
    if min(seen) != 0 or max(seen) != FULL_SCALE:
        fails.append(f"the sweep is {min(seen):#06x}..{max(seen):#06x}, not "
                     f"0x0000..{FULL_SCALE:#06x} -- it is not full range")
    if first != second:
        fails.append(f"the triangle does not repeat with period {PERIOD}")
    counted = struct.unpack(">I", bytes(uc.mem_read(COUNTER, 4)))[0]
    if counted != 2 * PERIOD:
        fails.append(f"the counter above BSS holds {counted}, not {2 * PERIOD}")
    if fails:
        for f in fails:
            print("  FAIL  " + f)
        return 1
    print(f"  the cave executes, the counter at {COUNTER:#010x} holds, and the store")
    print(f"  walks the full range on {TARGET:#010x} with period {PERIOD}.")
    print("  Everything short of the wire.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

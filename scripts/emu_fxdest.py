"""Does a `DEST` of 101..127 land in mirror block 16, and does 1..100 still land where it did?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_fxdest.py

**Why this exists rather than `emu_boot_engine.py`.** That gate loads
`out/<build>/symbols.json` and counts `lfo4_refresh`, so it only means anything
for a build carrying a compiled chunk. `fxdest` is one byte and one cave and
has no chunk, and pointing that script at it fails on a missing file before it
boots anything. Writing "n/a" against a gate is how this project has produced
its expensive negatives (`docs/PRINCIPLES.md` §19), so the same question is
asked here in the form this build can answer.

**What it does.** Boots the patched image from reset, then calls **evaluator
A's destination write by hand** — `0x40137a8a`, the `mvs.b` that reads `DEST`,
through to `0x40137ad2`, the instruction after the store — with the registers
the tick would have held: `%a4` the per-LFO mirror pointer, `%sp@(52)` the
track's mirror base, `%a5` the track counter, `%sp@(48)` the inner counter
(2 = LFO3, 1 = LFO2, 0 = LFO1), `%d0` the LFO's value.

Both candidate cells — the track's and block 16's — are pre-loaded with a
sentinel before every case, and the depth is set to full positive with a large
LFO value so a cell that *is* written clamps to `0x7f00` and a cell that is not
still reads the sentinel, whichever end of the `0..0x7f00` clamp the MAC lands
on. A watch has to be able to produce a different answer for each outcome; this
one can.

**The stock section is run as a control, case for case.** Without it, "code 111
wrote block 16" could be a property of the harness rather than of the patch.
Stock must write nothing at all for a code above 100, and must agree with the
patched build everywhere below it.

**What it cannot settle.** It does not model the DSP, so it cannot say the
sound changes — `docs/fx-master-modulation.md` §9 is where that was answered,
on the instrument. And the audio ISR does not run in this emulator, so the tick
never fires during a boot; that is why the evaluator is called directly.
"""

from __future__ import annotations

import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UC_PROT_ALL, UcError        # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A0, UC_M68K_REG_A2,   # noqa: E402
                                UC_M68K_REG_A3, UC_M68K_REG_A4,
                                UC_M68K_REG_A5, UC_M68K_REG_A6,
                                UC_M68K_REG_A7, UC_M68K_REG_D0,
                                UC_M68K_REG_D7, UC_M68K_REG_PC,
                                UC_M68K_REG_SR)

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
SECTION = f"{ROOT}/out/fxdest/section_3_MAIN_OS.bin"
STOCK_SECTION = f"{ROOT}/out/ext111/section_3_MAIN_OS.aplib.bin"

REPORTER = 0x4011EA6A            # the firmware's own EXCEPTION formatter
ENTRY = 0x40137A8A               # mvs.b %a4@(74),%d2 -- DEST
EXIT = 0x40137AD2                # the instruction after the store
CAVE = 0x4028EA02

MIRROR = 0x800068E4              # B, confirmed on hardware (fx-master-modulation §9)
FX_SLOT0 = MIRROR + 34 + 202 * 16          # 0x800075a6
TRACK_BASE = MIRROR + 34                   # block 0, slot 0

SCRATCH = 0x46A40000             # %a2 / %a3 / %a4, well above BSS
STACK = 0x46A00000
SENTINEL = 0x1234
FULL = 0x7F00
DEP_MAX = 0x7F00                 # bipolar depth at its positive stop
LFO_VALUE = 0x40000000           # large and positive, so a written cell clamps
LIMIT = 400_000_000

# name, DEST byte, track (%a5), inner counter, the cell route A should write
CASES = (
    ("a sound destination, slot 5",      5,   3, 1, "track"),
    ("the top sound slot, 100",          100, 2, 2, "track"),
    ("no destination, track 2 LFO1",     0,   1, 0, "track"),
    ("no destination, track 1 LFO2",     0,   0, 1, "track"),
    ("no destination, track 1 LFO3",     0,   0, 2, "track"),
    ("THE DEMO: no dest, track 1 LFO1",  0,   0, 0, "fx35"),
    ("code 101 -- Chorus Depth",         101, 4, 0, "fx25"),
    ("code 111 -- Delay Feedback Gain",  111, 7, 2, "fx35"),
    ("code 124 -- Reverb FX Routing",    124, 9, 1, "fx48"),
    ("code 127 -- the top of the range", 127, 5, 1, "fx51"),
    ("a negative DEST byte",             0xFF, 6, 1, None),
)

CELLS = {
    "track": lambda dest: TRACK_BASE + 2 * dest,
    "fx25": lambda dest: FX_SLOT0 + 2 * 25,
    "fx35": lambda dest: FX_SLOT0 + 2 * 35,
    "fx48": lambda dest: FX_SLOT0 + 2 * 48,
    "fx51": lambda dest: FX_SLOT0 + 2 * 51,
}


def ensure(uc, address: int, size: int = 4) -> None:
    """Map the 1 MB page holding `address` if the boot has not already."""
    for page in range(address & ~0xFFFFF, address + size + 0x100000, 0x100000):
        try:
            uc.mem_read(page, 1)
        except UcError:
            try:
                uc.mem_map(page, 0x100000, UC_PROT_ALL)
            except UcError:
                pass


def boot(section: str, label: str, entries: dict | None) -> tuple[object, bool]:
    holder, fault = {}, {}

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            if not fault:
                fault.update(at=st["n"])
            uc.emu_stop()

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        if entries is not None:
            def at_cave(uc, address, size, user):
                entries["cave"] += 1
            m.uc.hook_add(UC_HOOK_CODE, at_cave, begin=CAVE, end=CAVE)

    print(f"  booting {label} from reset, {LIMIT:,} instructions")
    m, st, stop = dspboot.run(SYX, open(section, "rb").read(),
                              limit=LIMIT, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    if fault:
        print(f"  ** the firmware drew EXCEPTION at {fault['at']:,} **")
        return m, False
    return m, True


def prepare(uc) -> None:
    for address, size in ((MIRROR, 0x1000), (SCRATCH, 0x1000),
                          (STACK - 0x4000, 0x8000)):
        ensure(uc, address, size)


def run_case(uc, dest: int, track: int, inner: int) -> tuple[int, dict]:
    """Call the evaluator's destination write once; return the pc and the cells."""
    watched = {name: fn(dest) for name, fn in CELLS.items()}
    watched["track"] = TRACK_BASE + 2 * (dest & 0x7F)
    for address in set(watched.values()):
        uc.mem_write(address, struct.pack(">H", SENTINEL))

    # %a4 is the per-LFO mirror pointer: DEST at +74, DEP at +82.
    a4 = SCRATCH
    uc.mem_write(a4 + 64, b"\x00" * 32)
    uc.mem_write(a4 + 74, bytes([dest & 0xFF]))
    uc.mem_write(a4 + 82, struct.pack(">H", DEP_MAX))

    uc.reg_write(UC_M68K_REG_A7, STACK)
    uc.mem_write(STACK + 48, struct.pack(">I", inner))
    uc.mem_write(STACK + 52, struct.pack(">I", TRACK_BASE))
    uc.reg_write(UC_M68K_REG_A4, a4)
    uc.reg_write(UC_M68K_REG_A5, track)
    uc.reg_write(UC_M68K_REG_A2, SCRATCH + 0x200)
    uc.reg_write(UC_M68K_REG_A3, SCRATCH + 0x400)
    uc.reg_write(UC_M68K_REG_A0, 0)
    uc.reg_write(UC_M68K_REG_A6, 0)
    uc.reg_write(UC_M68K_REG_D0, LFO_VALUE)
    uc.reg_write(UC_M68K_REG_D7, 0)

    uc.emu_start(ENTRY, EXIT, count=64)
    pc = uc.reg_read(UC_M68K_REG_PC)
    read = {name: struct.unpack(">H", bytes(uc.mem_read(address, 2)))[0]
            for name, address in watched.items()}
    return pc, read


def sweep(uc, label: str) -> dict:
    sr = uc.reg_read(UC_M68K_REG_SR)
    uc.reg_write(UC_M68K_REG_SR, (sr & ~0x0700) | 0x2700)
    out = {}
    try:
        for name, dest, track, inner, _ in CASES:
            pc, read = run_case(uc, dest, track, inner)
            written = sorted(k for k, v in read.items() if v != SENTINEL)
            out[name] = (pc, tuple(written), read)
            marks = ", ".join(f"{k}={read[k]:#06x}" for k in written) or "nothing"
            print(f"    {label:<8} {name:<34} pc {pc:#010x}  wrote {marks}")
    finally:
        uc.reg_write(UC_M68K_REG_SR, sr)
    return out


def main() -> int:
    entries = {"cave": 0}
    patched, ok = boot(SECTION, "fxdest", entries)
    if not ok:
        return 1
    print(f"  the cave was entered {entries['cave']} time(s) during the boot --")
    print("  expected 0: the audio engine does not run in this emulator\n")

    prepare(patched.uc)
    print("  calling evaluator A's destination write directly:")
    got = sweep(patched.uc, "fxdest")

    control, ok = boot(STOCK_SECTION, "stock (control)", None)
    if not ok:
        return 1
    prepare(control.uc)
    print()
    stock = sweep(control.uc, "stock")

    print()
    fails = []
    for name, dest, track, inner, expect in CASES:
        pc, written, read = got[name]
        if pc != EXIT:
            fails.append(f"{name}: the evaluator stopped at {pc:#010x}, not {EXIT:#010x}")
            continue
        want = () if expect is None else (expect,)
        if written != want:
            fails.append(f"{name}: wrote {written or ('nothing',)}, expected "
                         f"{want or ('nothing',)}")
            continue
        if expect is not None and read[expect] not in (0, FULL):
            fails.append(f"{name}: {expect} holds {read[expect]:#06x}, which is "
                         f"neither clamp endpoint -- the write is not the evaluator's")
        # The control: stock must agree below 101 and write nothing above it.
        spc, swritten, _ = stock[name]
        if dest <= 100 and dest != 0:
            if swritten != written:
                fails.append(f"{name}: stock wrote {swritten}, the build wrote {written}")
        elif dest > 100 and dest < 0x80:
            if swritten:
                fails.append(f"{name}: stock wrote {swritten} for a code above 100, "
                             f"so the harness is not measuring the patch")

    demo = got["THE DEMO: no dest, track 1 LFO1"]
    other = got["no destination, track 2 LFO1"]
    if demo[1] == other[1]:
        fails.append("the demonstration does not distinguish track 1 from track 2")
    if stock["THE DEMO: no dest, track 1 LFO1"][1] != ("track",):
        fails.append("stock does not write the sink for DEST 0 -- the control is wrong")

    if fails:
        for f in fails:
            print("  FAIL  " + f)
        return 1
    print("  codes 1..100 land exactly where stock lands them; codes 101..127 land")
    print(f"  in mirror block 16 at {FX_SLOT0:#010x} + 2*(code-76); stock writes")
    print("  nothing at all above 100. The demonstration fires on track 1 LFO1 only.")
    print("  Everything short of the wire.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

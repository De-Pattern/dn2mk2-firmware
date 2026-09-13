"""Prove that a code cave actually executes on the device.

**Why this exists.** Nothing in this project has ever shown a cave *running*.
Gate E proved a same-length **data** edit reaches the screen. Every cave since
has been verified offline — bytes diffed, disassembly read, 21/21 integrity
checks — and **none of that tests execution**. Four builds were flashed on the
assumption that it does, and `docs/lfo4-slot-plan.md` records how that ended: the
hooked function turned out to be a vtable slot with **no direct callers**, so it
never ran, and four silent results were read as four different problems.

This build tests the mechanism and nothing else.

**The target, chosen by the check that was missing.** Before hooking anything,
ask whether the address is actually reached:

    parameter_value_getter  0x4006408a   direct calls: 2    <- runs on the normal path
    the function hooked before           direct calls: 0    <- vtable only, never ran

`parameter_value_getter` is called whenever the UI needs a parameter's value, it
has two direct call sites, and this project already anchored it
(`docs/version-anchors.md`).

**The hook.** Its single exit:

    4006414c:  mvsw %a0@(14,%d2:l:2),%d0   ; d0 = the value being returned
    40064150:  moveml %sp@(16),%d2-%d4/%a2 ; <- hook here, 6 bytes, straight-line
    40064156:  lea %sp@(32),%sp
    4006415a:  rts

`%d0` holds the return value at that point, so the payload is one instruction:
add a constant before the epilogue replays.

**What to look for.** `OFFSET` is `16 << 8` because values are carried as
`stored << 8`, so every parameter on a page reads **16 higher than it should**.
Not subtle, not a judgement call, and nothing else on the instrument would do it.

    every parameter reads +16   -> caves execute; the mechanism is sound, and the
                                   LFO4 failures were target selection
    nothing changes             -> caves do not run as built, and the fault is the
                                   hook, the cave region, or patch/cave.py --
                                   which would explain every silent result so far

**Safety.** One 6-byte hook, one cave, both asserted before writing. The
displaced instruction is a register restore — straight-line, no PC-relative
branch. Every parameter *displays* wrong while this is flashed; nothing is
written to the +Drive by it, and reflashing stock 1.11 reverts it
(`docs/flashing.md`).

No firmware bytes live in this repository: everything is read from the user's own
local image at build time. Output is a .syx under 00_Resources/02_Builds/
(gitignored).
"""

import hashlib
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.image.coldfire import LoadedImage
from dnfw.patch.assemble import assemble, available
from dnfw.patch.cave import Cave, CaveHook, apply

MAIN_OS = 3
BASE = 0x40000400

ANCHORS = {
    3_192_192: {                      # DN2 1.11
        "hook": 0x40064150,           # parameter_value_getter's single exit
        "stock": "4cef041c0010",      # moveml %sp@(16),%d2-%d4/%a2
        "cave": (0x4028EA02, 170),    # `dnfw cave scan`, inside the safe region
        "callers": 2,                 # measured -- the check that was missing before
    },
}

OFFSET = 16 << 8          # +16 as displayed; values are carried as stored << 8

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/cave-proof_DN2_1.11.syx")


def main() -> int:
    if not available():
        raise SystemExit(
            "no m68k assembler found -- patch/assemble.py needs m68k-linux-gnu-as "
            "(WSL). See docs/code-caves.md."
        )

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = section.unpack()

    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no hook anchored for this build "
            f"(docs/version-anchors.md)."
        )

    site = anchor["hook"]
    stock = bytes.fromhex(anchor["stock"])
    cave = Cave(*anchor["cave"])

    _check_callers(content, site_fn=0x4006408a, expected=anchor["callers"])

    source = (
        "| cave proof: bias the returned parameter value so the change is unmissable\n"
        f"    addi.l  #{OFFSET},%d0      | +16 as displayed\n"
    )
    payload = assemble(source)
    print(source)

    hook = CaveHook(id="cave-proof", site=site, stock=stock, payload=payload, cave=cave)
    edited = apply(LoadedImage(dest=section.dest, content=content), hook)
    _verify(content, edited, site, len(stock), cave)

    syx = fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, edited)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)

    print(f"wrote {OUT}  ({len(syx):,} bytes)")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    print("\nOn the device: open any parameter page and read the values.")
    print(f"  every parameter +{OFFSET >> 8} -> CAVES EXECUTE. The mechanism is sound.")
    print("  nothing changed        -> caves do not run as built; the fault is the")
    print("                            hook, the cave region, or patch/cave.py.")
    return 0


def _check_callers(content: bytes, site_fn: int, expected: int) -> None:
    """Refuse to build for a function nothing calls directly.

    The check this project did not make before hooking a vtable slot that never
    ran (`docs/lfo4-slot-plan.md`). An indirect-only function *may* still run,
    but it must not be assumed to.
    """
    direct = 0
    for off in range(0, len(content) - 5, 2):
        op = struct.unpack_from(">H", content, off)[0]
        if op in (0x4EB9, 0x4EF9):
            if struct.unpack_from(">I", content, off + 2)[0] == site_fn:
                direct += 1
        elif op in (0x4EBA, 0x6100, 0x4EFA):
            disp = struct.unpack_from(">h", content, off + 2)[0]
            if BASE + off + 2 + disp == site_fn:
                direct += 1
    if direct == 0:
        raise SystemExit(
            f"0x{site_fn:08x} has NO direct callers -- it is reached indirectly if at "
            f"all, and a cave there cannot be assumed to run. Refusing to build."
        )
    if direct != expected:
        raise SystemExit(
            f"0x{site_fn:08x} has {direct} direct callers, expected {expected} -- "
            f"the image is not the one this hook was anchored against."
        )
    print(f"  caller check: 0x{site_fn:08x} is called directly from {direct} sites\n")


def _verify(before: bytes, after: bytes, site: int, stock_len: int, cave: Cave) -> None:
    if len(before) != len(after):
        raise SystemExit("length changed -- a cave patch must not resize the section")
    diffs = [i for i in range(len(before)) if before[i] != after[i]]
    hook_lo, hook_hi = site - BASE, site - BASE + stock_len
    cave_lo, cave_hi = cave.address - BASE, cave.address - BASE + cave.capacity
    stray = [i for i in diffs if not (hook_lo <= i < hook_hi or cave_lo <= i < cave_hi)]
    if stray:
        raise SystemExit(f"{len(stray)} bytes changed outside the hook and cave")
    in_hook = sum(1 for i in diffs if hook_lo <= i < hook_hi)
    print(f"  verified: {len(diffs)} bytes changed -- {in_hook} at the hook, "
          f"{len(diffs) - in_hook} in the cave, 0 elsewhere")
    op, target = struct.unpack_from(">HI", after, hook_lo)
    if op != 0x4EF9 or target != cave.address:
        raise SystemExit(f"hook is not `jmp 0x{cave.address:08x}`")
    print(f"  hook reads jmp 0x{cave.address:08x}")


if __name__ == "__main__":
    raise SystemExit(main())

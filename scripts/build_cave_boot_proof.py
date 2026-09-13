"""Do caves execute? Test it from the boot path, where nothing is assumed.

**Why a third attempt.** `build_cave_proof.py` hooked
`parameter_value_getter`'s exit and nothing changed — read at the time as
"caves do not execute". `build_flash_control.py` then showed that reading was
wrong twice over:

* `DNFW ALIVE!` appeared in SETTINGS, so **flashing works** and our images run;
* `AMP VOL` still read 110 from the *same* inline edit, so
  **`parameter_value_getter` is not the display path at all**.

The cave test had hooked a function that is never reached for the thing being
observed. It was **invalid, not negative**, and whether caves execute is still
unknown.

**This build removes every assumption that failed.**

*Where to hook* — the boot path. The device boots, so the code runs; no
reachability argument is required. The site is `0x40000546`, immediately after
the `.data` copy and BSS clear, a straight-line `lea 0xfc044000,%a0`.

*What to observe* — the SETTINGS menu string, which `build_flash_control.py`
just proved is visible on this instrument. The image keeps the stock
`PERSONALIZE`; the **cave overwrites it in RAM at boot** with `CAVE RAN!!!`.
MAIN OS is loaded into SDRAM at `0x40000400`, so its string pool is writable at
runtime.

So the question stops being "did the value change" — which needs a correct
model of the display path — and becomes "did this text change", which needs
nothing but eyes.

    SETTINGS shows CAVE RAN!!!   -> caves execute, from a cave in the constants
                                    region, and every earlier cave failure was
                                    the target, not the mechanism
    SETTINGS shows PERSONALIZE   -> caves do NOT execute. The constants region is
                                    not executed by the running image, exactly as
                                    octabam warned, and caves must move into code

Both outcomes are load-bearing and neither can be reached by argument.

**Safety.** One 6-byte hook in the boot path and one cave, both asserted before
writing. The displaced instruction is a `lea` — straight-line, no PC-relative
branch — replayed in the cave before it returns. If the cave does not execute
the instrument behaves exactly as stock. Reflashing stock 1.11 reverts it.

No firmware bytes live in this repository. Output is a .syx under
00_Resources/02_Builds/ (gitignored).
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
        "hook": 0x40000546,           # boot path, just after the .data copy + BSS clear
        "stock": "41f9fc044000",      # lea 0xfc044000,%a0
        "cave": (0x4028EA02, 170),
    },
}

FIND = b"PERSONALIZE\x00"
WRITE = b"CAVE RAN!!!\x00"     # same length, written by the cave at runtime

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/cave-boot-proof_DN2_1.11.syx")


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler -- see docs/code-caves.md")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = section.unpack()

    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(f"MAIN OS is {len(content):,} bytes -- not anchored")

    hits = [i for i in range(len(content) - len(FIND) + 1)
            if content[i:i + len(FIND)] == FIND]
    if len(hits) != 1:
        raise SystemExit(f"{FIND!r} occurs {len(hits)} times, expected 1")
    target = BASE + hits[0]
    assert len(FIND) == len(WRITE)

    # Three long stores cover the twelve bytes. Written as immediates so the cave
    # carries no data section and needs no position-independence.
    # ColdFire has no `move.l #imm,abs.l`, so the address goes in %a0 and each
    # long through %d0. Both are safe here: the replayed `lea` restores %a0, and
    # the boot code after the hook writes %d0 before it reads it.
    words = [struct.unpack_from(">I", WRITE, i)[0] for i in (0, 4, 8)]
    lines = [f"| cave: stamp {WRITE[:-1].decode()!r} over the menu string in RAM",
             f"    lea     {target},%a0"]
    for i, w in enumerate(words):
        lines.append(f"    move.l  #{w},%d0")
        lines.append(f"    move.l  %d0,%a0@({i * 4})")
    source = "\n".join(lines) + "\n"
    payload = assemble(source)
    print(source)
    print(f"  string at 0x{target:08x}: {FIND[:-1].decode()!r} -> {WRITE[:-1].decode()!r} (at runtime)")

    site = anchor["hook"]
    stock = bytes.fromhex(anchor["stock"])
    if bytes(content[site - BASE:site - BASE + len(stock)]) != stock:
        raise SystemExit(f"0x{site:08x} is not {stock.hex(' ')} -- refusing")

    cave = Cave(*anchor["cave"])
    hook = CaveHook(id="cave-boot-proof", site=site, stock=stock,
                    payload=payload, cave=cave)
    edited = apply(LoadedImage(dest=section.dest, content=content), hook)

    diffs = [i for i in range(len(content)) if content[i] != edited[i]]
    hook_lo, hook_hi = site - BASE, site - BASE + len(stock)
    cave_lo, cave_hi = cave.address - BASE, cave.address - BASE + cave.capacity
    stray = [i for i in diffs if not (hook_lo <= i < hook_hi or cave_lo <= i < cave_hi)]
    if stray:
        raise SystemExit(f"{len(stray)} bytes changed outside the hook and cave")
    print(f"  verified: {len(diffs)} bytes changed, {sum(1 for i in diffs if hook_lo <= i < hook_hi)} "
          f"at the hook, rest in the cave, 0 elsewhere")
    print(f"  the image still contains {FIND[:-1].decode()!r} -- only the cave changes it")

    syx = fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, edited)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    print("\nOn the device, SETTINGS:")
    print("  CAVE RAN!!!   -> caves EXECUTE; earlier failures were the target, not the mechanism")
    print("  PERSONALIZE   -> caves DO NOT execute; the constants region is not run,")
    print("                   and caves must move into the code region")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Is the flash landing at all? The control four builds should have carried.

**Why.** Four builds today produced no observable change: the LFO4 shadow, the
canary, the cave proof, and the inline proof. Each was investigated as a separate
failure — wrong destination, wrong target function, a cave that does not execute,
an anchor that is wrong. Every one of those investigations **assumed the flashed
image was running on the device**, and nothing today has tested that assumption.

It is the one variable common to all four results, and it was never controlled.

**What this build does.** Two edits in one image:

1. **The known-good control.** `PERSONALIZE` at `0x402193f4` -> `DNFW ALIVE!`,
   eleven bytes for eleven. This is the Gate E patch, whose 1.10E form is
   **confirmed working on this device** (`docs/flashing.md`, 2026-09-11). It
   proves the image on the instrument is ours.
2. **The experiment.** The same inline edit as `build_inline_proof.py`:
   `parameter_value_getter`'s return-value load becomes `moveq #127,%d0 ; nop`,
   so every parameter drawn through it reads 0.

**How to read it** -- `SETTINGS` is two button presses:

    SETTINGS shows DNFW ALIVE!  and AMP VOL reads 0
        -> flashing works, the hook site is reached, and the earlier cave
           failures are about cave placement

    SETTINGS shows DNFW ALIVE!  and AMP VOL reads 110
        -> flashing works, and parameter_value_getter is NOT the display path.
           The anchor in docs/version-anchors.md is wrong about that function.

    SETTINGS still shows PERSONALIZE
        -> **the flash is not landing.** Every result today is explained at a
           stroke, no conclusion drawn from them survives, and the next question
           is about the transfer, not the firmware.

The third outcome would retire four separate "findings" in one go, which is
exactly why the control belongs in every build rather than in a special one.

**Safety.** Two same-length edits, no cave, no relocation. Every parameter
*displays* wrongly if the second edit takes; nothing is written to the +Drive;
reflashing stock 1.11 reverts both.

No firmware bytes live in this repository. Output is a .syx under
00_Resources/02_Builds/ (gitignored).
"""

import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load

MAIN_OS = 3
BASE = 0x40000400

# The control is located by searching for the string, never by address -- an
# offset stops being true the moment anything earlier in the image changes.
CONTROL_FIND = b"PERSONALIZE\x00"
CONTROL_REPLACE = b"DNFW ALIVE!\x00"

ANCHORS = {
    3_192_192: {                     # DN2 1.11
        "site": 0x4006414C,          # parameter_value_getter's return-value load
        "stock": "71702a14",         # mvsw %a0@(14,%d2:l:2),%d0
        "patch": "707f4e71",         # moveq #127,%d0 ; nop
    },
}

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/flash-control_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    original = section.unpack()
    content = bytearray(original)

    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- not anchored for this build."
        )

    # 1. the control
    hits = [i for i in range(len(content) - len(CONTROL_FIND) + 1)
            if content[i:i + len(CONTROL_FIND)] == CONTROL_FIND]
    if len(hits) != 1:
        raise SystemExit(f"{CONTROL_FIND!r} occurs {len(hits)} times, expected exactly 1")
    assert len(CONTROL_FIND) == len(CONTROL_REPLACE), "the control must be same-length"
    at = hits[0]
    content[at:at + len(CONTROL_REPLACE)] = CONTROL_REPLACE
    print(f"  control : 0x{BASE + at:08x}  PERSONALIZE -> DNFW ALIVE!")

    # 2. the experiment
    off = anchor["site"] - BASE
    stock = bytes.fromhex(anchor["stock"])
    patch = bytes.fromhex(anchor["patch"])
    if bytes(content[off:off + len(stock)]) != stock:
        raise SystemExit(f"0x{anchor['site']:08x} is not {stock.hex(' ')} -- refusing")
    content[off:off + len(patch)] = patch
    print(f"  test    : 0x{anchor['site']:08x}  {stock.hex(' ')} -> {patch.hex(' ')}")

    diffs = [i for i in range(len(original)) if original[i] != content[i]]
    expected = set(range(at, at + len(CONTROL_REPLACE))) | set(range(off, off + len(patch)))
    if set(diffs) - expected:
        raise SystemExit("bytes changed outside the two edits")
    print(f"\n  verified: {len(diffs)} bytes changed, all within the two edits")

    syx = fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, bytes(content))})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"  wrote {OUT}  ({len(syx):,} bytes)")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")

    print("\nOn the device, SETTINGS is two presses:")
    print("  'DNFW ALIVE!' + AMP VOL 0    -> flashing works, hook reached, caves misplaced")
    print("  'DNFW ALIVE!' + AMP VOL 110  -> flashing works, the getter anchor is wrong")
    print("  still 'PERSONALIZE'          -> THE FLASH IS NOT LANDING; today's four")
    print("                                  results are all explained and none stand")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

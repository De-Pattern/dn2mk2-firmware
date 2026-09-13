"""Separate "the cave does not run" from "the hook site is not reached".

`scripts/build_cave_proof.py` was flashed and changed nothing: seven parameters
across three pages all read their stock defaults. The image was verified correct
after a full encode/decode round trip — the hook decodes as `jmp 0x4028ea02` and
the cave holds the payload, the replayed instruction and the jump back. So the
bytes are right and the code has no effect.

Two causes remain and they need different fixes:

  A. the cave does not execute  -- it sits at 0x4028ea02, in the **read-only data**
     region; MAIN OS code ends around 0x401d0000, and there is **no zero run of
     32+ bytes anywhere inside the code region** to put a cave in. An MCF5441x has
     an MMU, so a non-executable mapping over the constants region would do this.
  B. the hook site is never reached -- `parameter_value_getter` has two direct
     callers, but it is also referenced from twelve data locations, so the display
     path may dispatch through a vtable to a different reader entirely.

**This build tells them apart with no cave and no jump.** It patches the value
getter's own return instruction in place, same length:

    4006414c:  mvsw %a0@(14,%d2:l:2),%d0     7170 2a14   read the value
                              ->
               moveq #127,%d0 ; nop          707f 4e71   return a constant

Four bytes for four. This is the *same class of edit* as Gate E and the
modulation-mask flips — both of which are confirmed working on this device — so
it removes every variable except whether this code runs.

**What to look for.** `%d0` becomes 127, and a displayed value is the raw word
`>> 8`, so **127 >> 8 = 0**: every parameter drawn through this function reads
**0** (or -64 where the display subtracts an offset). `AMP VOL` should fall from
110 to 0. Nothing subtle.

    values collapse to 0   -> the hook site IS reached. Cause A: the cave does not
                              execute, and the fix is where caves live, not how
                              they are built.
    values unchanged       -> the hook site is NOT reached. Cause B: this function
                              is not the display path, and the anchor named in
                              docs/version-anchors.md is wrong about what it does.

Either answer is worth more than another LFO4 build, because one of them says the
cave mechanism is fine and the other says the anchor is wrong.

**Safety.** One four-byte, same-length instruction replacement. No cave, no jump,
no relocation. Every parameter *displays* wrongly while flashed; nothing is
written to the +Drive, and reflashing stock 1.11 reverts it.

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

MAIN_OS = 3
BASE = 0x40000400

ANCHORS = {
    3_192_192: {                     # DN2 1.11
        "site": 0x4006414C,          # the getter's own return-value load
        "stock": "71702a14",         # mvsw %a0@(14,%d2:l:2),%d0
        "patch": "707f4e71",         # moveq #127,%d0 ; nop
    },
}

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/inline-proof_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no site anchored for this build "
            f"(docs/version-anchors.md)."
        )

    off = anchor["site"] - BASE
    stock = bytes.fromhex(anchor["stock"])
    patch = bytes.fromhex(anchor["patch"])
    assert len(stock) == len(patch), "the replacement must be the same length"

    found = bytes(content[off:off + len(stock)])
    if found != stock:
        raise SystemExit(
            f"0x{anchor['site']:08x} holds {found.hex(' ')}, expected {stock.hex(' ')} "
            f"-- refusing to write"
        )
    content[off:off + len(patch)] = patch

    syx = fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, bytes(content))})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)

    _verify(section.unpack(), bytes(content), off, len(patch))
    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    print("\nOn the device: read AMP VOL on a new sound (stock reads 110).")
    print("  collapses to 0   -> the hook site IS reached; the CAVE is what fails")
    print("  still reads 110  -> the hook site is NOT reached; the anchor is wrong")
    return 0


def _verify(before: bytes, after: bytes, off: int, n: int) -> None:
    if len(before) != len(after):
        raise SystemExit("length changed -- this patch must be same-length")
    diffs = [i for i in range(len(before)) if before[i] != after[i]]
    if diffs != list(range(off, off + n)):
        raise SystemExit(f"expected exactly bytes {off}..{off+n-1} to change, got {diffs}")
    print(f"  verified: {len(diffs)} bytes changed, all at 0x{BASE+off:08x}, none elsewhere")
    print(f"    {before[off:off+n].hex(' ')}  ->  {after[off:off+n].hex(' ')}")


if __name__ == "__main__":
    raise SystemExit(main())

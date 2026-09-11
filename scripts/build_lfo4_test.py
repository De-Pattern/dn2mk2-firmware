"""Build a test firmware that inserts a 4th LFO parameter block into the DN2.

This is the first, verifiable increment toward a fourth LFO (docs/lfo4-feasibility.md):
it **repurposes ten unused "ERR" records** in the parameter table into a fourth
LFO's parameter block, cloned from LFO3. Same-length edits -- no table
relocation, no bound changes -- exactly the approach that doc settles on.

What it does and does not do, stated plainly:
- DOES insert ten LFO-shaped parameter records at ids 1-5,7-9,11,12 (dead ERR
  slots, none referenced by address -- verified), cloned from LFO3 (ids 95-104),
  with the MIDI controller and NRPN numbers cleared so nothing collides.
- Does NOT yet show them (no page-view / MOD-nav -- that stage needs a code cave)
  and does NOT prove they modulate (the engine gate is unresolved). So flashing
  this is a **safety and mechanism test**: it confirms repurposing dead slots
  keeps the image valid and, on hardware, that the device still boots and its
  existing pages are unchanged.

No firmware bytes live in this repository: the record bytes are read from the
user's own local image at build time and written back. Output is a .syx under
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
TABLE = 0x401E29D0  # record[id] = TABLE + id*60  (docs/parameter-table-consumer.md)
RECORD = 60
CTRL_OFF = 40  # MIDI controller field (0xffffffff = unassigned)
NRPN_OFF = 44
PAGE_OFF = 56  # page-label string pointer (="LFO3" in a cloned LFO3 record)

# A safe slot for a new "LFO4" string: 16 zero bytes of unreferenced padding in
# the data region (before the BSS at 0x402e1bf4), verified to have no code
# references. Writing 5 bytes here relabels the block without a code cave.
LFO4_STR_ADDR = 0x4026EFF6

LFO3_IDS = list(range(95, 105))          # the block we clone
TARGET_IDS = [1, 2, 3, 4, 5, 7, 8, 9, 11, 12]  # dead ERR slots to repurpose

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo4-test_DN2_1.10E.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    def rec_offset(param_id: int) -> int:
        return (TABLE - BASE) + param_id * RECORD

    # Guard: every target must currently be an ERR record and unreferenced by
    # construction (docs confirm no direct refs); we re-check the ERR name here.
    for tid in TARGET_IDS:
        name_ptr = struct.unpack_from(">I", content, rec_offset(tid))[0]
        name = _cstr(content, name_ptr - BASE)
        if name != "ERR":
            raise SystemExit(f"id {tid} is {name!r}, not ERR -- refusing to overwrite")

    for tid, src in zip(TARGET_IDS, LFO3_IDS):
        clone = bytearray(content[rec_offset(src): rec_offset(src) + RECORD])
        struct.pack_into(">I", clone, CTRL_OFF, 0xFFFFFFFF)  # clear MIDI CC
        struct.pack_into(">I", clone, NRPN_OFF, 0xFFFFFFFF)  # clear NRPN
        struct.pack_into(">I", clone, PAGE_OFF, LFO4_STR_ADDR)  # relabel page -> "LFO4"
        content[rec_offset(tid): rec_offset(tid) + RECORD] = clone

    # Write the "LFO4" string into the unreferenced padding slot.
    so = LFO4_STR_ADDR - BASE
    if content[so: so + 8] != bytes(8):
        raise SystemExit(f"string slot 0x{LFO4_STR_ADDR:08x} is not free -- refusing")
    content[so: so + 5] = b"LFO4" + bytes(1)

    replacement = compress(section.id, section.dest, bytes(content))
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"wrote {OUT}  ({len(syx):,} bytes)")
    print(f"  inserted a 4th LFO block at ids {TARGET_IDS} (cloned from LFO3 {LFO3_IDS[0]}-{LFO3_IDS[-1]})")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    return 0


def _cstr(buf: bytes, off: int) -> str | None:
    end = buf.find(b"\x00", off, off + 40)
    if end < 0:
        return None
    s = buf[off:end]
    return s.decode() if s and all(0x20 <= c < 0x7F for c in s) else None


if __name__ == "__main__":
    raise SystemExit(main())

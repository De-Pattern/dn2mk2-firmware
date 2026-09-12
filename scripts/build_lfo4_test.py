"""Build a test firmware that inserts a 4th LFO parameter block into the DN2.

This is the first, verifiable increment toward a fourth LFO (docs/lfo4-feasibility.md):
it **repurposes ten unused "ERR" records** in the parameter table into a fourth
LFO's parameter block, cloned from LFO3. Same-length edits -- no table
relocation, no bound changes -- exactly the approach that doc settles on.

What it does and does not do, stated plainly:
- DOES insert ten LFO-shaped parameter records at the dead ERR ids, cloned from
  LFO3 (ids 95-104), with the MIDI controller and NRPN numbers cleared so
  nothing collides and the modulation mask set to LFO4's predicted values.
- Does NOT yet show them (no page-view / MOD-nav -- that stage needs a code cave)
  and does NOT prove they modulate (the engine gate is unresolved). So flashing
  this is a **safety and mechanism test**: it confirms repurposing dead slots
  keeps the image valid and, on hardware, that the device still boots and its
  existing pages are unchanged.

**Corrected 2026-09-12.** The previous version anchored a record at
``TABLE + id*60`` where ``TABLE`` is the *short-name* pointer. That address is
0x38 bytes into the record, so every other field it edited belonged to ``id+1``
and every 60-byte clone straddled two records -- which would have overwritten
the live parameters Machine Type (6), Track Level (10) and Solo/Mute/Pattern
Mute (7-9). The build was never flashed. See docs/modulation-mask.md for the
record layout this version uses, and the guard in ``_check_geometry`` which
refuses to run if the layout does not resolve to known names.

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
RECORD = 60

# The accessor base -- the address the ~44 `lea` sites load (docs/version-anchors.md).
# A record starts 8 bytes below it: record(id) = ACCESSOR_BASE - 8 + id*60.
# Keyed by decoded MAIN OS size, which is a clean discriminator and makes the
# script refuse an image it has not been anchored against.
ACCESSOR_BASE = {
    3_085_696: 0x401E29A0,  # DN2 1.10E
    3_192_192: 0x401F7F94,  # DN2 1.11
}

# Field offsets from the start of a record. docs/modulation-mask.md.
F_PAGE_ID = 0x08
F_CC = 0x20  # MIDI controller   (0xffffffff = unassigned)
F_NRPN = 0x24  # NRPN             (0xffffffff = unassigned)
F_ORDINAL = 0x28  # dense ordinal -- every record has one; do NOT clear it
F_MODMASK = 0x2C  # modulation mask
F_LONG = 0x30  # long-name string pointer
F_PAGE = 0x34  # page-label string pointer
F_SHORT = 0x38  # short-name string pointer

# LFO4's predicted mask values (docs/modulation-mask.md, "The fourth bit").
# LFO4 sits at the end of the chain, so nothing may modulate its parameters;
# its DEST takes an unused marker bit rather than duplicating LFO3's 0x10000.
LFO4_PARAM_MASK = 0x0
LFO4_DEST_MASK = 0x8000
LFO3_DEST_MASK = 0x10000

# A safe slot for a new "LFO4" string: 16 zero bytes of unreferenced padding in
# the data region (before the BSS at 0x402e1bf4), verified to have no code
# references. Writing 5 bytes here relabels the block without a code cave.
LFO4_STR_ADDR = 0x4026EFF6

LFO3_IDS = list(range(95, 105))  # the block we clone
# The genuinely dead records: long name "Error", short name "ERR", no page.
# id 0 is the table's own unused slot and is left alone. Ten usable slots for
# ten parameters -- there is no spare, so the list is not a preference.
TARGET_IDS = [1, 2, 3, 4, 5, 11, 12, 13, 14, 17]

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo4-test_DN2_1.10E.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    accessor_base = ACCESSOR_BASE.get(len(content))
    if accessor_base is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no parameter-table anchor is "
            f"recorded for this build. Re-anchor it (docs/version-anchors.md) "
            f"before building."
        )

    def record(param_id: int) -> int:
        """File offset of the first byte of record[param_id]."""
        return (accessor_base - 8 - BASE) + param_id * RECORD

    def field(param_id: int, off: int) -> int:
        return struct.unpack_from(">I", content, record(param_id) + off)[0]

    def name(param_id: int, off: int) -> str | None:
        return _cstr(content, field(param_id, off) - BASE)

    _check_geometry(name)

    # Every target must be a genuinely dead record: "Error"/"ERR" and no page.
    # Checking the short name alone is what let the previous version aim at
    # Solo/Mute/Pattern Mute, whose short name is also "ERR".
    for tid in TARGET_IDS:
        long_name, short_name = name(tid, F_LONG), name(tid, F_SHORT)
        if (long_name, short_name) != ("Error", "ERR"):
            raise SystemExit(
                f"id {tid} is {long_name!r}/{short_name!r}, not a dead ERR "
                f"record -- refusing to overwrite"
            )

    for tid, src in zip(TARGET_IDS, LFO3_IDS):
        clone = bytearray(content[record(src): record(src) + RECORD])
        is_dest = struct.unpack_from(">I", clone, F_MODMASK)[0] == LFO3_DEST_MASK
        struct.pack_into(">I", clone, F_CC, 0xFFFFFFFF)
        struct.pack_into(">I", clone, F_NRPN, 0xFFFFFFFF)
        struct.pack_into(">I", clone, F_PAGE, LFO4_STR_ADDR)
        struct.pack_into(
            ">I", clone, F_MODMASK, LFO4_DEST_MASK if is_dest else LFO4_PARAM_MASK
        )
        content[record(tid): record(tid) + RECORD] = clone

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
    print(f"  table anchored at 0x{accessor_base:08x} for a {len(content):,}-byte MAIN OS")
    print(f"  4th LFO block at ids {TARGET_IDS} (cloned from LFO3 {LFO3_IDS[0]}-{LFO3_IDS[-1]})")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    return 0


def _check_geometry(name) -> None:
    """Refuse to run unless the record layout resolves to names we know.

    The bug this guards against is an anchor that is off by a fixed amount:
    a wrong base still produces plausible-looking strings, because the table is
    dense and every record holds three string pointers. These four probes
    straddle page boundaries, where an off-by-one-record anchor stops agreeing.
    """
    probes = [
        (6, F_LONG, "Machine Type"),
        (10, F_LONG, "Track Level"),
        (75, F_PAGE, "LFO1"),  # first LFO1 record
        (84, F_PAGE, "LFO1"),  # last LFO1 record -- id 85 is LFO2
        (104, F_PAGE, "LFO3"),  # last LFO3 record -- id 106 is Chorus
    ]
    for param_id, off, expected in probes:
        got = name(param_id, off)
        if got != expected:
            raise SystemExit(
                f"parameter-table geometry check failed: id {param_id} field "
                f"+0x{off:02x} is {got!r}, expected {expected!r}. The table "
                f"anchor or the record layout is wrong -- see "
                f"docs/modulation-mask.md before changing anything."
            )


def _cstr(buf: bytes, off: int) -> str | None:
    end = buf.find(b"\x00", off, off + 40)
    if end < 0:
        return None
    s = buf[off:end]
    return s.decode() if s and all(0x20 <= c < 0x7F for c in s) else None


if __name__ == "__main__":
    raise SystemExit(main())

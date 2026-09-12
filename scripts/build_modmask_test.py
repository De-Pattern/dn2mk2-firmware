"""Build a test firmware that opens two closed parameters to LFO modulation.

**The experiment.** `docs/modulation-mask.md` claims a parameter appears in an
LFO's destination list iff the modulation mask at `record+0x24` contains every
bit of that LFO's filter. Nothing has tested it on hardware. This build flips
exactly two masks from `0x0` (closed to all modulation) to `0x1e00` (open to
all four modulator slots) and changes nothing else:

    id 34  Portamento / Portamento Time / PTIM   (page 0x0e)
    id 61  Amp        / Delay Time       / DEL   (page 0x0b, the AMP envelope
                                                  delay -- not the FX delay)

Both are parameters of a synth track's own pages, so they are certainly
enumerated by the track's ParameterSet. That is the point: it isolates the
mask as the only variable.

**What to look for on the device.** Open LFO1 (or 2 or 3), select `DEST`, and
scroll the destination list. If `PTIM` and the AMP `DEL` now appear there, the
mask is confirmed as the gate and `docs/modulation-mask.md` stands -- including
its prediction that `0x0200` is a fourth modulator's filter. If they do not
appear, the mask is necessary but not sufficient and the model needs the
`ParameterSet` enumeration read before anything else is attempted.

**Why not the FX delay, which is what was actually asked for.** The FX Delay
page's parameters (ids 113-122) *already* carry `0x1e00`, so there is no mask
edit to make -- they are excluded somewhere else. `SoundParameterSet`'s
slot-to-id mapping (`FUN_400dc02a` on 1.11) indexes a table the code `lea`s at
`0x42c64b3c`, which is outside the MAIN OS image, so it cannot be patched by
editing section 3. Opening an FX parameter needs that enumeration understood
first; this build is the step that has to come before it.

Safety: two 4-byte writes, same length, no relocation, no code change, and
nothing that alters how the image loads. Fully reversible by reflashing stock.

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

# record(id) = ACCESSOR_BASE + id*60, keyed by decoded MAIN OS size so the
# script refuses an image it has not been anchored against.
ACCESSOR_BASE = {
    3_085_696: 0x401E29A0,  # DN2 1.10E
    3_192_192: 0x401F7F94,  # DN2 1.11
}

F_MODMASK = 0x24
F_LONG = 0x28
F_PAGE = 0x2C
F_SHORT = 0x30
F_HANDLER = 0x34

OPEN_TO_ALL = 0x1E00  # every modulator slot, MOD1's own filter value

# (id, expected long name, expected short name) -- asserted before writing, so
# a build against a firmware whose ids moved refuses rather than corrupting.
TARGETS = [
    (34, "Portamento Time", "PTIM"),
    (61, "Delay Time", "DEL"),
]

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/modmask-test_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    accessor_base = ACCESSOR_BASE.get(len(content))
    if accessor_base is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no parameter-table anchor is "
            f"recorded for this build (docs/version-anchors.md)."
        )

    def record(param_id: int) -> int:
        return (accessor_base - BASE) + param_id * RECORD

    def field(param_id: int, off: int) -> int:
        return struct.unpack_from(">I", content, record(param_id) + off)[0]

    def name(param_id: int, off: int) -> str | None:
        return _cstr(content, field(param_id, off) - BASE)

    _check_geometry(name, field)

    for param_id, long_name, short_name in TARGETS:
        got = (name(param_id, F_LONG), name(param_id, F_SHORT))
        if got != (long_name, short_name):
            raise SystemExit(
                f"id {param_id} is {got}, expected {(long_name, short_name)} -- "
                f"refusing to write"
            )
        mask = field(param_id, F_MODMASK)
        if mask != 0:
            raise SystemExit(
                f"id {param_id} ({short_name}) already has mask 0x{mask:x}, not "
                f"0x0 -- it is not a closed parameter, refusing to write"
            )
        struct.pack_into(">I", content, record(param_id) + F_MODMASK, OPEN_TO_ALL)
        print(f"  id {param_id:3d}  {short_name:<6s} mask 0x0 -> 0x{OPEN_TO_ALL:04x}")

    replacement = compress(section.id, section.dest, bytes(content))
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"wrote {OUT}  ({len(syx):,} bytes)")
    print(f"  table anchored at 0x{accessor_base:08x} for a {len(content):,}-byte MAIN OS")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    return 0


def _check_geometry(name, field) -> None:
    """Refuse to run unless the record layout resolves the way it should.

    Same guard as scripts/build_lfo4_test.py, and for the same reason: a wrong
    anchor into a dense table still yields plausible strings. See
    docs/lfo4-feasibility.md, "The Stage 1 corrections".
    """
    for param_id, off, expected in [
        (6, F_LONG, "Machine Type"),
        (10, F_LONG, "Track Level"),
        (84, F_PAGE, "LFO1"),   # last LFO1 record -- id 85 is LFO2
        (104, F_PAGE, "LFO3"),  # last LFO3 record -- id 106 is Chorus
    ]:
        got = name(param_id, off)
        if got != expected:
            raise SystemExit(
                f"geometry check failed: id {param_id} field +0x{off:02x} is "
                f"{got!r}, expected {expected!r}"
            )
    blocks = [
        [field(i, F_HANDLER) for i in range(start, start + 10)]
        for start in (75, 85, 95)
    ]
    if not (blocks[0] == blocks[1] == blocks[2]):
        raise SystemExit(
            "geometry check failed: the LFO1/LFO2/LFO3 blocks disagree, so the "
            "record boundary is wrong"
        )


def _cstr(buf: bytes, off: int) -> str | None:
    end = buf.find(b"\x00", off, off + 40)
    if end < 0:
        return None
    s = buf[off:end]
    return s.decode() if s and all(0x20 <= c < 0x7F for c in s) else None


if __name__ == "__main__":
    raise SystemExit(main())

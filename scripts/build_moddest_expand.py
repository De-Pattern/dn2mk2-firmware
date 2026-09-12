"""Open every closed parameter to modulation, in three labelled groups.

Follow-up to `scripts/build_modmask_test.py`, whose two-byte change was
confirmed on hardware 2026-09-12: Portamento Time both appeared as a MOD1
destination and actually modulated. That proved the engine's apply path is
generic over the parameter index. This build widens it into a real experiment.

It sets `record+0x24` from `0x0` to `0x1e00` on **all 32** parameters that the
stock firmware marks closed to modulation, grouped so the results can be read
apart. Nothing else changes -- same length, no relocation, no code.

**Group A -- per-voice sound parameters (13).** SYN, Amp and Portamento. Same
class as the confirmed Portamento Time: parameters the engine already computes
for every voice. *Expect these to appear and to modulate.* If any of them
appears but does not move, that is a per-parameter exception worth knowing
about.

**Group B -- Chorus (8).** The decisive test of mask-versus-enumeration.
`docs/modulation-mask.md` argues FX settings are excluded by the `ParameterSet`
enumeration, not the mask -- the evidence being that Delay and Reverb already
carry a full mask and still cannot be reached. If Chorus now appears in the
destination list, that argument is wrong and the mask was the gate after all.
*Expect these NOT to appear.* Their not appearing is the informative result.

**Group C -- Master (11).** The same test against a different global object,
the master compressor and pattern volume.

Between them, B and C settle whether the FX-modulation idea
(`docs/ideas-backlog.md` §4) is a mask problem or an enumeration problem.

**Safety.** 32 four-byte writes into a lookup table. Every one of these
parameters except two already has a MIDI CC and NRPN assignment, so each is
already writable from outside the box -- an LFO writing the same slot is not a
new kind of access. A parameter the engine cannot modulate simply does not
move. Reversible by reflashing stock 1.11.

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

ACCESSOR_BASE = {
    3_085_696: 0x401E29A0,  # DN2 1.10E
    3_192_192: 0x401F7F94,  # DN2 1.11
}

F_MODMASK = 0x24
F_LONG = 0x28
F_PAGE = 0x2C
F_SHORT = 0x30
F_HANDLER = 0x34

OPEN_TO_ALL = 0x1E00

# (id, expected short name). Asserted before writing, so a build against a
# firmware whose ids moved refuses rather than corrupting.
GROUPS = {
    "A  per-voice sound parameters -- expect these to work": [
        (221, "ATRG"), (222, "ARST"), (224, "BTRG"), (225, "BRST"),
        (226, "PHRT"), (235, "KSA"), (236, "KSB1"), (237, "KSB2"),
        (61, "DEL"), (73, "MODE"), (74, "RSET"),
        (34, "PTIM"), (35, "PORT"),
    ],
    "B  Chorus -- expect these NOT to appear (enumeration test)": [
        (105, "DPTH"), (106, "SPD"), (107, "HPF"), (108, "WDTH"),
        (109, "DEL"), (110, "REV"), (111, "CHR"), (112, "VOL"),
    ],
    "C  Master -- the same test, a different global object": [
        (149, "MOVD"), (150, "THR"), (151, "ATK"), (152, "REL"),
        (153, "MUP"), (154, "RAT"), (155, "SCS"), (156, "SCS"),
        (157, "SCF"), (158, "MIX"), (159, "VOL"),
    ],
}

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/moddest-expand_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    accessor_base = ACCESSOR_BASE.get(len(content))
    if accessor_base is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no parameter-table anchor "
            f"recorded for this build (docs/version-anchors.md)."
        )

    def record(param_id: int) -> int:
        return (accessor_base - BASE) + param_id * RECORD

    def field(param_id: int, off: int) -> int:
        return struct.unpack_from(">I", content, record(param_id) + off)[0]

    def name(param_id: int, off: int) -> str | None:
        return _cstr(content, field(param_id, off) - BASE)

    _check_geometry(name, field)

    written = 0
    for group, targets in GROUPS.items():
        print(f"\nGroup {group}")
        for param_id, short_name in targets:
            got = name(param_id, F_SHORT)
            if got != short_name:
                raise SystemExit(
                    f"id {param_id} short name is {got!r}, expected "
                    f"{short_name!r} -- refusing to write"
                )
            mask = field(param_id, F_MODMASK)
            if mask != 0:
                raise SystemExit(
                    f"id {param_id} ({short_name}) already has mask 0x{mask:x} "
                    f"-- it is not a closed parameter, refusing to write"
                )
            struct.pack_into(">I", content, record(param_id) + F_MODMASK, OPEN_TO_ALL)
            print(f"   id {param_id:3d}  {name(param_id, F_PAGE) or '-':<11s} "
                  f"{name(param_id, F_LONG):<22s} {short_name}")
            written += 1

    replacement = compress(section.id, section.dest, bytes(content))
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  {written} parameters opened; table anchored at 0x{accessor_base:08x}")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    return 0


def _check_geometry(name, field) -> None:
    """Same guard as the other build scripts -- docs/lfo4-feasibility.md."""
    for param_id, off, expected in [
        (6, F_LONG, "Machine Type"),
        (10, F_LONG, "Track Level"),
        (84, F_PAGE, "LFO1"),
        (104, F_PAGE, "LFO3"),
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
        raise SystemExit("geometry check failed: the LFO blocks disagree")


def _cstr(buf: bytes, off: int) -> str | None:
    end = buf.find(b"\x00", off, off + 40)
    if end < 0:
        return None
    s = buf[off:end]
    return s.decode() if s and all(0x20 <= c < 0x7F for c in s) else None


if __name__ == "__main__":
    raise SystemExit(main())

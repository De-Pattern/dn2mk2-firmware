"""Probe whether the audio engine implements a fourth LFO.

**Why this build exists.** `docs/engine-index-map.md` §9 established that the
audio engine's code is **not in this firmware file** -- the ColdFire does no DSP
(582,407 instructions, zero FPU, 50 MAC) and no section carries a DSP
instruction stream. So the engine cannot be modified, and a fourth LFO is
possible if and only if the engine **already implements one**.

The evidence that it might is the reserved lane: the control side addresses the
engine through a static map, and that map's LFO block is `4*param + lfo` with
lfo 1..3 used and the whole `lfo == 4` lane -- engine indices 4, 8, 12, 16, 20,
24, 28, 32 -- reserved and reaching no slot. The same fourth slot is reserved in
the persisted sound format and in the pattern p-lock ids, both measured by DNX
from hardware. Three independent structures, one shape.

**The experiment.** Do not build a fourth LFO -- that is blocked on the runtime
slot shortage (`docs/engine-index-map.md` §6b: one repairable free slot against
eight needed). Instead, **re-point LFO3 at the reserved lane** and listen. LFO3's
eight parameters keep their records, their page, their UI and their slots; only
the engine indices those slots mirror to change.

    slot 17..24  (LFO3 SPD MULT FADE DEST WAVE SPH MODE DEP)
      was ->  engine  3,  7, 11, 15, 19, 23, 27, 31     (4*param + 3)
      now ->  engine  4,  8, 12, 16, 20, 24, 28, 32     (4*param + 4)

**How to read the result** -- the two outcomes are cleanly distinguishable,
which is the whole point of driving a complete LFO rather than one parameter:

  * **LFO3 still modulates, and its controls still work.** The engine has a
    fourth LFO and we have just driven it. The lane is live, and LFO4 becomes a
    control-side problem only.
  * **LFO3 stops modulating entirely.** The engine ignores the lane. It has
    three LFOs and the reserved indices are layout, not capability.

A false negative is possible and worth stating: an engine that *has* a fourth
LFO but does not sum its output into the modulation path would look identical to
one that has none. A positive result is therefore conclusive; a negative one is
strong but not proof.

**Both tables must move together.** `0x400dd25e` is a reverse copy that walks the
inverse table for all 107 engine indices and writes `mirror[0x1c + i*2]` back
into `sound[0x14 + slot*2]`. Changing only the forward map would leave that loop
copying a stale `mirror[3]` over LFO3's Speed on every pass. So this build
rewrites the forward map, points the lane's inverse entries at LFO3's slots, and
clears the entries LFO3 vacated -- keeping `inverse[forward[slot]] == slot`
exactly, the same invariant `scripts/dump_engine_map.py` checks.

**Safety.** 24 four-byte writes into two lookup tables. No code, no relocation,
no length change. The worst case is that LFO3 stops modulating, which is
audible, harmless and reversible by reflashing stock 1.11.

No firmware bytes live in this repository: the tables are read from the user's
own local image at build time and written back. Output is a .syx under
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

# Keyed by decoded MAIN OS size so the script refuses an image it has not been
# anchored against (docs/version-anchors.md).
ANCHORS = {
    3_192_192: {                 # DN2 1.11
        "forward": 0x401FCF20,   # slot -> engine index, 100 entries, bound slot <= 99
        "inverse": 0x401FD0B0,   # engine index -> slot, 107 entries used
    },
}

N_SLOTS = 100
N_ENGINE = 107
LANES = 4
LFO_PARAMS = ["SPD", "MULT", "FADE", "DEST", "WAVE", "SPH", "MODE", "DEP"]

LFO3_SLOT0 = 17          # LFO3 occupies slots 17..24
SOURCE_LANE = 3          # LFO3 is lane 3: engine = 4*param + 3
TARGET_LANE = 4          # the reserved lane: engine = 4*param + 4

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo4-probe_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- the mapping tables have not "
            f"been anchored for this build (docs/version-anchors.md)."
        )
    fwd_off = anchor["forward"] - BASE
    inv_off = anchor["inverse"] - BASE

    forward = [struct.unpack_from(">I", content, fwd_off + i * 4)[0] for i in range(N_SLOTS)]
    inverse = [struct.unpack_from(">I", content, inv_off + i * 4)[0] for i in range(N_ENGINE)]
    _check_geometry(forward, inverse)

    writes = 0
    print("re-pointing LFO3 from lane 3 to the reserved lane 4\n")
    print(f"  {'param':<6}{'slot':>6}{'was':>6}{'now':>6}")
    for param in range(len(LFO_PARAMS)):
        slot = LFO3_SLOT0 + param
        was = LANES * param + SOURCE_LANE
        now = LANES * param + TARGET_LANE
        if forward[slot] != was:
            raise SystemExit(
                f"slot {slot} maps to engine {forward[slot]}, expected {was} "
                f"-- refusing to write"
            )
        if inverse[now] != 0:
            raise SystemExit(
                f"engine index {now} is not reserved -- inverse says slot "
                f"{inverse[now]}. Refusing to write."
            )
        struct.pack_into(">I", content, fwd_off + slot * 4, now)      # slot -> lane 4
        struct.pack_into(">I", content, inv_off + now * 4, slot)      # lane 4 -> slot
        struct.pack_into(">I", content, inv_off + was * 4, 0)         # vacate lane 3
        writes += 3
        print(f"  {LFO_PARAMS[param]:<6}{slot:6d}{was:6d}{now:6d}")

    _check_round_trip(content, fwd_off, inv_off)

    replacement = compress(section.id, section.dest, bytes(content))
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)

    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  {writes} four-byte writes, {writes * 4} bytes, two tables, no code")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    print("\nOn the device: pick a sound, set LFO3 to a fast obvious destination")
    print("(pitch or filter cutoff) with plenty of depth, and listen.")
    print("  modulates -> the engine HAS a fourth LFO; the lane is live")
    print("  silent    -> the engine ignores the lane; three LFOs is the truth")
    return 0


def _check_geometry(forward: list[int], inverse: list[int]) -> None:
    """Refuse to run unless the tables are the ones we think they are.

    The round-trip is the real guard: two plausible-looking neighbouring tables
    will not round-trip into each other. Same discipline as the other build
    scripts (docs/lfo4-feasibility.md, "The Stage 1 corrections").
    """
    for slot in range(1, N_SLOTS):
        engine = forward[slot]
        if engine == 0:
            continue
        if engine >= len(inverse) or inverse[engine] != slot:
            raise SystemExit(
                f"geometry check failed: slot {slot} -> engine {engine} -> "
                f"{inverse[engine] if engine < len(inverse) else 'out of range'}"
            )
    # the three shipping LFOs must sit at 4*param + lfo exactly
    for lfo, first in ((1, 1), (2, 9), (3, 17)):
        for param in range(len(LFO_PARAMS)):
            want = LANES * param + lfo
            got = forward[first + param]
            if got != want:
                raise SystemExit(
                    f"geometry check failed: LFO{lfo} {LFO_PARAMS[param]} "
                    f"(slot {first + param}) maps to {got}, expected {want}"
                )
    # and the target lane must be entirely unreached
    reached = set(forward)
    lane = [LANES * p + TARGET_LANE for p in range(len(LFO_PARAMS))]
    if reached & set(lane):
        raise SystemExit(f"geometry check failed: lane {lane} is not free")


def _check_round_trip(content: bytes, fwd_off: int, inv_off: int) -> None:
    """After editing, the invariant must still hold for every mapped slot."""
    fwd = [struct.unpack_from(">I", content, fwd_off + i * 4)[0] for i in range(N_SLOTS)]
    inv = [struct.unpack_from(">I", content, inv_off + i * 4)[0] for i in range(N_ENGINE)]
    for slot in range(1, N_SLOTS):
        e = fwd[slot]
        if e and inv[e] != slot:
            raise SystemExit(
                f"post-edit round-trip broken: slot {slot} -> engine {e} -> {inv[e]}"
            )
    print("\n  round-trip verified after the edit: inverse[forward[slot]] == slot")


if __name__ == "__main__":
    raise SystemExit(main())

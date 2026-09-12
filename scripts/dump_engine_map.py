"""Dump the runtime-slot <-> engine-index mapping tables.

`Sound::updateMirror` (1.11 `0x4004cae0`-ish) copies changed parameter values
from the live sound object into the mirror the audio engine reads. It does not
copy slot-for-slot: every index passes through `slot_to_engine_index`
(1.11 `0x400dccfa`), which is a pair of **static lookup tables in read-only
data** -- so the engine has its own index space, distinct from MAIN OS's
runtime slot space, and the translation between them is editable data.

    forward  0x401fcf20   100 entries   runtime slot  -> engine index
    inverse  0x401fd0b0   112+ entries  engine index  -> runtime slot

The reason to look: the engine's LFO block is `4*param + lfo` for param 0..7,
and **the whole `lfo == 0` lane is reserved and zero-filled** -- engine indices
0, 4, 8, 12, 16, 20, 24, 28 map to no slot, and the inverse table's lfo=0
column is eight literal zeros. That is a complete, correctly-sized lane for a
fourth LFO, sitting unused in the shipped firmware, matching what DNX measured
independently in the persisted sound format and the pattern p-lock ids.

`docs/engine-index-map.md` is the full reading. This script re-derives it from
a local image so the claim is checkable rather than asserted, and prints the
LFO block as a grid.

No firmware bytes live in this repository: the tables are read from the user's
own local image at run time.
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.firmware.load import load

MAIN_OS = 3
BASE = 0x40000400

# Keyed by decoded MAIN OS size, so the script refuses an image it has not been
# anchored against (docs/version-anchors.md).
ANCHORS = {
    3_192_192: {  # DN2 1.11
        "forward": 0x401FCF20,
        "inverse": 0x401FD0B0,
        "forward_max": 99,  # the bound in slot_to_engine_index
    },
}

LFO_PARAMS = ["SPD", "MULT", "FADE", "DEST", "WAVE", "SPH", "MODE", "DEP"]
N_LFO_PARAMS = 8
LANES = 4  # the engine's LFO block is 4 wide: lfo 0..3

STOCK = {"1.11": "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"}


def read_table(content: bytes, addr: int, count: int) -> list[int]:
    off = addr - BASE
    return [struct.unpack_from(">I", content, off + i * 4)[0] for i in range(count)]


def check_round_trip(forward: list[int], inverse: list[int]) -> list[str]:
    """Every slot that maps somewhere must map back. Catches a wrong anchor."""
    bad = []
    for slot, engine in enumerate(forward):
        if slot == 0 or engine == 0:
            continue
        if engine >= len(inverse):
            bad.append(f"slot {slot} -> engine {engine}, past the inverse table")
        elif inverse[engine] != slot:
            bad.append(f"slot {slot} -> engine {engine} -> slot {inverse[engine]}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", nargs="?", help="firmware .syx or _dist.zip")
    ap.add_argument("--full", action="store_true", help="print both tables entire")
    args = ap.parse_args()

    path = pathlib.Path(args.image) if args.image else pathlib.Path(STOCK["1.11"])
    if not path.exists():
        raise SystemExit(f"{path} not found")

    content = load(read_image(path)).container.find(MAIN_OS).unpack()
    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- the mapping tables have not been "
            f"anchored for this build (docs/version-anchors.md). Re-find them from "
            f"slot_to_engine_index rather than extrapolating an offset."
        )

    n_slots = anchor["forward_max"] + 1
    forward = read_table(content, anchor["forward"], n_slots)
    inverse = read_table(content, anchor["inverse"], 112)

    bad = check_round_trip(forward, inverse)
    if bad:
        raise SystemExit("round-trip check failed -- wrong anchor?\n  " + "\n  ".join(bad))
    print(f"{path.name}  round-trip verified over all {n_slots} slots\n")

    print("The engine's LFO block -- engine index = 4*param + lfo, entries are slots")
    header = "".join(f"{'lfo=' + str(l):>8}" for l in range(LANES))
    print(f"  {'param':<6}{header}")
    for p in range(N_LFO_PARAMS):
        row = inverse[p * LANES:(p + 1) * LANES]
        cells = "".join(f"{('-' if v == 0 else str(v)):>8}" for v in row)
        print(f"  {LFO_PARAMS[p]:<6}{cells}")

    reserved = [p * LANES for p in range(N_LFO_PARAMS) if inverse[p * LANES] == 0]
    print(f"\n  reserved lane (lfo=0), engine indices mapping to no slot: {reserved}")
    print(f"  lane is complete: {len(reserved) == N_LFO_PARAMS}")

    unreachable = sorted(set(range(max(forward) + 1)) - set(forward))
    print(f"  engine indices no slot reaches: {unreachable}")

    free = [s for s in range(n_slots) if forward[s] == 0 and s != 0]
    print(f"\n  runtime slots that map nowhere: {free or '(none)'}")
    print(f"  -> {len(free)} free slot(s) against {N_LFO_PARAMS} a fourth LFO needs")

    if args.full:
        print("\nforward: slot -> engine")
        for i in range(0, n_slots, 10):
            print(f"  {i:3d}: " + " ".join(f"{v:4d}" for v in forward[i:i + 10]))
        print("\ninverse: engine -> slot")
        for i in range(0, len(inverse), 10):
            print(f"  {i:3d}: " + " ".join(f"{v:4d}" for v in inverse[i:i + 10]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

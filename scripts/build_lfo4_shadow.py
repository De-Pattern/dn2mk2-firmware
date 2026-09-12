"""Drive the engine's fourth LFO from a code cave -- the first real LFO4 build.

**Where this sits.** The engine side is finished (`docs/engine-index-map.md`
§§11, 14): the DN2's SHARC implements a fourth LFO, lane 4 is a separate
generator, and four run at once. Everything left is control-side, and
`docs/lfo4-slot-plan.md` recorded a fork -- store LFO4's values in the sound
object (blocked on slots) or hold them outside it (cheap). The owner chose:
prove the cheap one works, then do the persistent one properly.

This is the smallest build that proves it, and it deliberately avoids every
unsettled question at once.

**What it does.** `Sound::updateMirror` (`0x4004ca80`) copies changed parameter
values into the mirror the engine reads, with the mirror pointer live in `%a3`
right up to the epilogue. A detour at the epilogue copies **lane 3's eight
mirror words into lane 4**, with the speed offset so the two run at different
rates:

    engine e  ->  mirror offset 0x1c + 2e

    SPD  lane3 e=3  0x22  ->  lane4 e=4   0x24   (+ a speed offset)
    MULT       e=7  0x2a  ->        e=8   0x2c
    FADE       e=11 0x32  ->        e=12  0x34
    DEST       e=15 0x3a  ->        e=16  0x3c
    WAVE       e=19 0x42  ->        e=20  0x44
    SPH        e=23 0x4a  ->        e=24  0x4c
    MODE       e=27 0x52  ->        e=28  0x54
    DEP        e=31 0x5a  ->        e=32  0x5c

So LFO4 becomes a shadow of LFO3, running at a different rate on the same
destination.

**Why copy LFO3 rather than hardcode values.** The encodings are not
established -- what a speed word means, how a waveform enum is numbered, how a
destination is represented. Hardcoding eight guesses would most likely produce
silence, and silence would be uninformative: we could not tell a bad guess from
a dead lane. Copying values the firmware itself just wrote means **every field
is valid by construction**, and the only variable is whether lane 4 runs.

**What to expect.** Set LFO3 to an obvious destination with depth. You should
hear **two** modulations at different rates on that one destination -- a
compound wobble rather than a single one. Change LFO3's destination and both
follow, because LFO4 is copying it.

    heard, and clearly two rates  -> the cave drives lane 4; the design works
    heard, but only one rate      -> the copy ran but the offset did not take
    nothing changes               -> the hook did not run, or lane 4 needs
                                     something not carried in these eight words

**What this does NOT do**, deliberately: no parameter records, no page view, no
`[MOD]` navigation, no slots, no storage. LFO4 has no UI and its settings are
not saved. It is a mechanism test, not the feature.

**Safety.** One 8-byte hook and one cave, both asserted before writing. The
displaced instructions are the function epilogue -- straight-line, no PC-relative
branch -- replayed verbatim. `%d0` is saved and restored around the only
register the payload needs, because the epilogue restores `%d2-%d5/%a2-%a5` and
says nothing about `%d0`. Worst case is a boot fault, recoverable by reflashing
stock 1.11 (`docs/flashing.md`).

No firmware bytes live in this repository: everything is read from the user's
own local image at build time. Output is a .syx under 00_Resources/02_Builds/
(gitignored).
"""

import argparse
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

# Anchors, keyed by decoded MAIN OS size so the script refuses an unknown build.
ANCHORS = {
    3_192_192: {                        # DN2 1.11
        "hook": 0x4004CBFE,             # Sound::updateMirror epilogue, %a3 still the mirror
        "stock": "4cd73c3c4fef0040",    # moveml %sp@,%d2-%d5/%a2-%a5 ; lea %sp@(64),%sp
        "cave": (0x4028EA02, 170),      # from `dnfw cave scan`, inside the safe region
    },
}

MIRROR_BASE = 0x1C      # mirror[engine] is at a3 + 0x1c + engine*2
LANES = 4
SRC_LANE = 3            # copy LFO3 ...
DST_LANE = 4            # ... into the reserved lane
LFO_PARAMS = ["SPD", "MULT", "FADE", "DEST", "WAVE", "SPH", "MODE", "DEP"]

# Added to the copied speed word so the two LFOs run at visibly different rates.
# Mirror words are `value << 8`, so this is +12 in parameter units.
SPEED_OFFSET = 0x0C00

# A mirror DEST word is `engine_index << 8` -- updateMirror computes it as
# `map(0, stored >> 8) << 8`. Engine index 3 is LFO3's own Speed, so pointing
# LFO4 there makes it modulate LFO3's rate: audible, unambiguous, and it uses
# only an index this project has measured rather than a guessed encoding.
DEST_LFO3_SPEED = 3

# Engine 58 is SYN slot 50 -- `PITCH Pitch All` on page-0 machines.
DEST_PITCH_ALL = 58

# FADE's neutral, settled by two independent sources.
#
# The device displays FADE as -64..63, so its neutral is the displayed 0
# (owner, reading the instrument). DNX decoded the stored form from hardware
# captures and states the rule outright (`DNX/docs/dn2-format.md`):
#
#     | bipolar | value + 64 |
#     Verified on the LFO depths: 32 stored 80, 56 stored 92.
#
# So displayed 0 is **stored 64**, and a mirror word is `stored << 8`:
#
#     neutral = 64 << 8 = 16384
#
# Which is exactly the parameter record's own default field for FADE, read
# independently from the image. Two sources, one answer. A raw 0 would be
# displayed -64 -- full fade, not neutral.
#
# One loose end kept rather than smoothed over: FADE's `+0x14` flag is 0 while
# DEP's is 1, yet the owner reports both display signed. So `+0x14` is not
# "display bipolar", and this project's label for it is wrong or incomplete.
# That does not affect the value above, which rests on the default field and on
# DNX, not on the flag.
FADE_NEUTRAL = 16384

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo4-shadow_DN2_1.11.syx")
OUT_DEST = "00_Resources/02_Builds/lfo4-dest{d}_DN2_1.11.syx"


def mirror_offset(engine_index: int) -> int:
    return MIRROR_BASE + engine_index * 2


def build_payload(own_dest: int | None, fade: int) -> tuple[str, bytes]:
    """The detour body: copy lane 3 -> lane 4, then replay the epilogue."""
    src = [mirror_offset(LANES * p + SRC_LANE) for p in range(len(LFO_PARAMS))]
    dst = [mirror_offset(LANES * p + DST_LANE) for p in range(len(LFO_PARAMS))]

    lines = [
        "| LFO4 shadow: copy lane 3's mirror words into lane 4",
        "| %a3 is the mirror; %d0 is saved because the epilogue does not restore it",
        "    move.l  %d0,%sp@-",
        f"    move.w  %a3@({src[0]}),%d0            | LFO3 {LFO_PARAMS[0]}",
        # ColdFire has no addi.w -- only the long form. Harmless here: move.w
        # leaves the upper half of %d0 stale, and only the low word is stored.
        f"    addi.l  #{SPEED_OFFSET},%d0           | offset so the rates differ",
        f"    move.w  %d0,%a3@({dst[0]})            | LFO4 {LFO_PARAMS[0]}",
        "    move.l  %sp@+,%d0",
    ]
    for p in range(1, len(LFO_PARAMS)):
        if own_dest is not None and LFO_PARAMS[p] == "DEST":
            lines.append(
                f"    move.w  #{own_dest << 8},%a3@({dst[p]})   | DEST -> engine {own_dest}"
            )
        elif LFO_PARAMS[p] == "FADE":
            lines.append(
                f"    move.w  #{fade},%a3@({dst[p]})   | FADE -> {fade} (neutral)"
            )
        else:
            lines.append(f"    move.w  %a3@({src[p]}),%a3@({dst[p]})   | {LFO_PARAMS[p]}")
    # No epilogue and no return jump here: patch/cave.py appends the displaced
    # stock and the jump back itself. Emitting them in the payload too would
    # leave a dead second copy in the cave.
    source = "\n".join(lines) + "\n"
    return source, assemble(source)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fade", type=int, default=FADE_NEUTRAL, metavar="RAW",
                    help=f"raw FADE word for LFO4 (default {FADE_NEUTRAL}). The device "
                         "shows -64..63; 16384 is the record's default field, which "
                         "does not obviously reconcile -- see the note in the source.")
    ap.add_argument("--dest", type=int, default=None, metavar="ENGINE",
                    help="give LFO4 its own destination (an engine index) instead of "
                         f"copying LFO3's. {DEST_LFO3_SPEED} is LFO3's Speed.")
    args = ap.parse_args()
    if not available():
        raise SystemExit(
            "no m68k assembler found -- patch/assemble.py needs "
            "m68k-linux-gnu-as (WSL). See docs/code-caves.md."
        )

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = section.unpack()

    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no hook anchored for this "
            f"build (docs/version-anchors.md)."
        )

    site = anchor["hook"]
    stock = bytes.fromhex(anchor["stock"])
    cave = Cave(*anchor["cave"])
    return_to = site + len(stock)

    source, payload = build_payload(args.dest, args.fade)
    print(source)
    print(f"payload {len(payload)} bytes; cave {cave.capacity} bytes at 0x{cave.address:08x}")
    if len(payload) + len(stock) + 6 > cave.capacity:
        raise SystemExit("payload does not fit the cave")

    hook = CaveHook(id="lfo4-shadow", site=site, stock=stock, payload=payload, cave=cave)
    edited = apply(LoadedImage(dest=section.dest, content=content), hook)

    _verify(content, edited, site, cave)

    replacement = compress(section.id, section.dest, edited)
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})
    out = OUT if args.dest is None else pathlib.Path(OUT_DEST.format(d=args.dest))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(syx)

    print(f"\nwrote {out}  ({len(syx):,} bytes)")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")
    if args.dest is None:
        print("\nOn the device: set LFO3 to an obvious destination with depth.")
        print("  Two LFOs on ONE destination COMPETE rather than sum -- stock DN2")
        print("  behaviour, confirmed on hardware with untouched LFO1+LFO2. That")
        print("  makes this variant hard to read; prefer --dest.")
    else:
        print(f"\nLFO4 modulates engine index {args.dest}, independent of LFO3 --")
        print("  nothing is shared, so nothing competes.")
        if args.dest == DEST_PITCH_ALL:
            print("  Engine 58 is SYN slot 50: `PITCH Pitch All` ONLY on page-0")
            print("  machines. On page-2 machines the same slot is `Op C Phase`.")
            print("  Use a page-0 machine or the test is misleading.")
            print("  Set LFO3 to cutoff so the two are separately audible.")
        elif args.dest == DEST_LFO3_SPEED:
            print("  Engine 3 is LFO3's own Speed: LFO3 wobbles your destination")
            print("  while LFO4 speeds that wobble up and down.")
    return 0


def _verify(before: bytes, after: bytes, site: int, cave: Cave) -> None:
    """Everything that changed must be the hook or the cave, and nothing else."""
    if len(before) != len(after):
        raise SystemExit("length changed -- a cave patch must not resize the section")
    diffs = [i for i in range(len(before)) if before[i] != after[i]]
    hook_lo, hook_hi = site - BASE, site - BASE + 8
    cave_lo, cave_hi = cave.address - BASE, cave.address - BASE + cave.capacity
    stray = [i for i in diffs
             if not (hook_lo <= i < hook_hi or cave_lo <= i < cave_hi)]
    if stray:
        raise SystemExit(f"{len(stray)} bytes changed outside the hook and cave")
    in_hook = sum(1 for i in diffs if hook_lo <= i < hook_hi)
    in_cave = len(diffs) - in_hook
    print(f"  verified: {len(diffs)} bytes changed -- {in_hook} at the hook, "
          f"{in_cave} in the cave, 0 elsewhere")
    jmp = struct.unpack_from(">HI", after, hook_lo)
    if jmp[0] != 0x4EF9 or jmp[1] != cave.address:
        raise SystemExit(f"hook is not `jmp 0x{cave.address:08x}` -- got {jmp}")
    print(f"  hook reads jmp 0x{cave.address:08x}")


if __name__ == "__main__":
    raise SystemExit(main())

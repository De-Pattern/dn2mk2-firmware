"""Route A, the engine half: an LFO destination code that lands in mirror block 16.

    python scripts/build_fxdest.py

`docs/fx-master-modulation.md` §9 closed the question this depends on: a store
into `mirror[16]` at `B = 0x800068e4` is **audible** — `fxblock16` swept Delay
Feedback Gain on the instrument on 2026-09-22 and the owner heard it sustain.
§10 then read route A's sites and found the evaluator's destination write is a
read-modify-write whose cell address is `%a0 + 2*DEST`, so retargeting it is a
change of **one base register** for one range of codes.

This build is that change, and the proof that it works, and nothing else.

## What it patches — two edits, both asserted against the stock image

| # | at | stock | becomes |
|---|---|---|---|
| 1 | `0x40137a8e` | `72 64` — `moveq #100,%d1` | `72 7f` — `moveq #127,%d1` |
| 2 | `0x40137a9e` | `73 6c 00 52 4d f0 7a 00` | `jmp <cave>` + `nop` |

**Edit 1 raises evaluator A's destination bound from 100 to 127.** `DEST` is
read with `mvs.b`, so it can never exceed 127 and a negative value still fails
the unsigned compare exactly as it does in stock. No parameter record carries a
`+12` above 99 (measured over all 320), so codes 101..127 are unclaimed and
nothing stock can produce one.

**Edit 2 is the cave**, hooked at the `mvs.w %a4@(82),%d1` that loads `DEP`,
two instructions after `%a0` is loaded from `%sp@(52)` — the track's mirror
base. The payload overwrites `%a0` with

    0x800068e4 + 34 + 202*16 - 2*76  =  0x8000750e

for codes 101..127, so the `lea %a0@(0,%d7:l:2),%fp` that the cave replays
resolves to `mirror[16][DEST - 76]`. FX slot = code − 76, so 101 → slot 25
(Chorus Depth) and 124 → slot 48. Everything after the hook — the depth
multiply, the accumulate, the `0..0x7f00` clamp, the store — is stock code
doing exactly what it already does, which is why this is two edits and not a
rewrite.

The displaced pair is straight-line (`mvs.w` and `lea`), nothing in the image
branches into `0x40137a9e..0x40137aa5`, and no longword anywhere in the section
holds one of those addresses. All three are checked below before anything is
written.

**Evaluator B is deliberately untouched, re-verified here.** `0x40137698` has
the same shape but keeps its own `moveq #100,%d6` (`0x4013769c`) *and* a second
bound at `0x401376c2` — `moveq #7,%d2 ; cmpl %a0,%d2 ; bcs` with `%a0 = DEST-1`
— so B writes only for `DEST` 1..8 and can never see a code of 101..127. It
also writes into `%sp@(56)`, the `0x4463fc18` array, not the mirror at all.

## The proof, and why it is hard-coded

Nothing on the instrument can *produce* a code of 101..127 yet: the destination
browser enumerates a `ParameterSet`'s 101 slots and the FX records live in a
different set. That is route A item 3, and reading it tonight showed it is a
matched pair of patches rather than one cave — see `docs/fx-master-modulation.md`
§11. So this build carries a demonstration, the way `lfo4-tick7` and
`fxblock16` did:

> **On track 1 only, on LFO1 only, and only while its `DEST` reads "none",**
> the code is substituted with **111** — block-16 slot 35, **Delay Feedback
> Gain**, the exact cell the instrument was heard to sweep on 2026-09-22.

Every other track, every other LFO and every other `DEST` value is stock. The
condition is read out of registers the evaluator already holds — `%a5` is the
track counter, `%sp@(48)` is the inner counter (2 = LFO3, 1 = LFO2, 0 = LFO1)
— so it needs no absolute address and cannot drift with the mirror base.

**Why "DEST = none" is the trigger:** it is the power-on default, the owner
does not have to reach anything the UI cannot offer, and `DEP` defaults to
centre so nothing moves until the owner turns it. Turning `DEP` up on track 1's
LFO1 is then the whole test, with `SPD`, `MULT` and `WAVE` all live.

## The one thing to say out loud

**Sixteen tracks' LFOs can all target the same global FX cell and they will
stack**, because every evaluator reads the cell and adds to it. That is what
the FX parameters being global means, and it is not a defect to fix in the
engine. This build only exposes one LFO, so it cannot be seen here; it will be
the first surprise the moment the browser can offer these codes.

**Master (slots 60..69) is not reachable by this build.** It needs codes
136..145, and a code above 127 cannot survive the evaluator's `mvs.b` read of
`DEST` — that read would have to be widened to `mvz.b`. Chorus, Delay and
Reverb (slots 25..48, codes 101..124) are the whole of what 101..127 buys.

**Safety.** One 6-byte hook plus a nop, one cave in the region with the only
hardware-confirmed cave success (`0x4028ea02`, `docs/code-caves.md`), and one
byte of immediate. Nothing is written to the +Drive; reflashing stock 1.11
reverts it (`docs/flashing.md`).

No firmware bytes live in this repository: everything is read from the user's
own local image at build time. Output is a .syx under `00_Resources/02_Builds/`
(gitignored), and the patched section alone under `out/fxdest/` for the gates.
"""

from __future__ import annotations

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

# The mirror, as docs/fx-master-modulation.md §4c derives it and §9 confirmed on
# hardware. Re-derived below rather than trusted as a literal.
MIRROR_BASE = 0x800068E4          # `lea 0x800068e4,%a2` at 0x400db14a
HEADER = 34                       # bytes before block 0
BLOCK = 202                       # bytes per block
FX_BLOCK = 16                     # the seventeenth block: FX and Master

# Route A's code range. `code = slot + CODE_BIAS`, so 101 -> slot 25.
CODE_BIAS = 76
CODE_LO = 101                     # slot 25, Chorus Depth
CODE_HI = 127                     # the ceiling a signed byte read can carry

# The demonstration: track 1, LFO1, DEST "none" -> this code.
DEMO_SLOT = 35                    # Delay Feedback Gain -- the cell fxblock16 swept
DEMO_CODE = DEMO_SLOT + CODE_BIAS  # 111

ANCHORS = {
    3_192_192: {                                  # DN2 1.11, MAIN OS
        # Edit 1: evaluator A's destination bound.
        "bound": (0x40137A8E, "7264", "7f", "moveq #100,%d1 -> moveq #127,%d1"),
        # Edit 2: the cave hook. Both displaced instructions are straight-line.
        "hook": 0x40137A9E,
        "stock": "736c00524df07a00",   # mvsw %a4@(82),%d1 ; lea %a0@(0,%d7:l:2),%fp
        "cave": (0x4028EA02, 170),     # the cave that ran on hardware
        # Nothing may branch or point into the bytes we replace.
        "sealed": (0x40137A9E, 8),
        "controls": (
            (0x40137A8A, "752c004a", "mvsb %a4@(74),%d2 -- DEST, evaluator A"),
            (0x40137A92, "25470068", "movel %d7,%a2@(104) -- the DEST copy, untouched"),
            (0x40137A96, "b2876538", "cmpl %d7,%d1 ; bcss 0x40137ad2 -- the bound test"),
            (0x40137A9A, "206f0034", "moveal %sp@(52),%a0 -- the track's mirror base"),
            (0x40137AA6, "0681ffffc000", "addil #-16384,%d1 -- DEP is bipolar"),
            (0x40137AC2, "0c8000007f00", "cmpil #32512,%d0 -- the clamp we inherit"),
            (0x40137AD0, "3c80", "movew %d0,%fp@ -- the store we inherit"),
            # The loop registers the demonstration reads.
            (0x40137798, "49ecffde", "lea %a4@(-34),%a4 -- %a4 = B + 202*track"),
            (0x401377A0, "2f410030", "movel %d1,%sp@(48) -- the inner counter, 2..0"),
            (0x40137AF0, "49ecfff0", "lea %a4@(-16),%a4 -- one LFO per inner pass"),
            (0x40137B18, "7010", "moveq #16,%d0 -- sixteen tracks in the outer loop"),
            # Evaluator B, re-verified rather than trusted: it cannot see 101..127.
            (0x4013769C, "7c64", "moveq #100,%d6 -- evaluator B keeps its own bound"),
            (0x401376C2, "7407", "moveq #7,%d2 -- and a second one: DEST-1 > 7 skips"),
            (0x401376C4, "b4886526", "cmpl %a0,%d2 ; bcss 0x401376ee -- B stops at 8"),
            # The mirror base itself, the anchor the whole formula hangs on.
            (0x400DB14A, "45f9800068e4", "lea 0x800068e4,%a2 -- the mirror base"),
            (0x400275BA, "486a0d02", "pea %a2@(3330) -- the frame builder reads block 16"),
        ),
    },
}

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/fxdest_DN2_1.11.syx")
SECTION_OUT = pathlib.Path("out/fxdest/section_3_MAIN_OS.bin")


def fx_base() -> int:
    """The base a code of 101..127 must be indexed off.

    The stock `lea %a0@(0,%d7:l:2),%fp` adds `2*code`, and the FX slot is
    `code - 76`, so the base is block 16's slot 0 less `2*76`.
    """
    return MIRROR_BASE + HEADER + BLOCK * FX_BLOCK - 2 * CODE_BIAS


def payload_source(base: int) -> str:
    """Choose the mirror base for this destination code.

    Entered with `%d7` = DEST (sign-extended), `%a0` = the track's mirror base
    as the stock instruction two back loaded it, `%a5` = the track counter and
    `%sp@(48)` = the inner counter. `%d1` is dead: the replayed `mvs.w` that
    follows this payload reloads it.
    """
    return f"""    | -- the demonstration: track 1, LFO1, DEST "none" --
    tst.l   %d7                    | a destination is already chosen?
    bne.s   1f
    move.l  %a5,%d1                | %a5 is the track counter, 0 = track 1
    bne.s   1f
    tst.l   %sp@(48)               | the inner counter: 2 = LFO3, 1 = LFO2, 0 = LFO1
    bne.s   1f
    moveq   #{DEMO_CODE},%d7       | -> FX slot {DEMO_SLOT}, Delay Feedback Gain
    | -- route A: codes {CODE_LO}..{CODE_HI} name mirror block {FX_BLOCK} --
1:  moveq   #100,%d1
    cmp.l   %d7,%d1
    bcc.s   2f                     | DEST <= 100 -> the track's own block, stock
    lea     {base:#010x},%a0        | block {FX_BLOCK}: B + {HEADER} + {BLOCK}*{FX_BLOCK} - 2*{CODE_BIAS}
2:"""


def main() -> int:
    if not available():
        raise SystemExit(
            "no m68k assembler found -- patch/assemble.py needs m68k-linux-gnu-as "
            "(WSL). See docs/code-caves.md."
        )
    if OUT.exists():
        raise SystemExit(
            f"{OUT} already exists. A build is never rebuilt under a name the owner "
            f"may already have flashed -- give this one a new name instead."
        )

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    stock_bytes = section.unpack()
    content = bytearray(stock_bytes)

    anchor = ANCHORS.get(len(content))
    if anchor is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no hook anchored for this build "
            f"(docs/version-anchors.md)."
        )

    _check_controls(content, anchor["controls"])
    _check_sealed(content, *anchor["sealed"])

    base = fx_base()
    print(f"  block {FX_BLOCK} slot 0 = {MIRROR_BASE:#010x} + {HEADER} + {BLOCK}*{FX_BLOCK} "
          f"= {MIRROR_BASE + HEADER + BLOCK * FX_BLOCK:#010x}")
    print(f"  indexed base  = that - 2*{CODE_BIAS} = {base:#010x}")
    if base != 0x8000750E:
        raise SystemExit(f"base arithmetic gives {base:#010x}, expected 0x8000750e")
    demo_cell = base + 2 * DEMO_CODE
    if demo_cell != 0x800075EC:
        raise SystemExit(f"demo cell is {demo_cell:#010x}, not the cell fxblock16 swept")
    print(f"  code {DEMO_CODE} -> slot {DEMO_SLOT} at {demo_cell:#010x}  "
          f"(Delay Feedback Gain -- the cell heard sweeping on 2026-09-22)\n")

    # Edit 1: the bound, one byte.
    address, stock_hex, new_byte, why = anchor["bound"]
    off = address - BASE
    want = bytes.fromhex(stock_hex)
    if bytes(content[off:off + len(want)]) != want:
        raise SystemExit(
            f"{address:#010x}: expected {want.hex(' ')} ({why}) but found "
            f"{content[off:off + len(want)].hex(' ')}"
        )
    content[off + 1] = int(new_byte, 16)
    print(f"  edit 1  {address:#010x}  {want.hex(' ')} -> "
          f"{bytes(content[off:off + len(want)]).hex(' ')}   {why}")

    # Edit 2: the cave.
    source = payload_source(base)
    print("\n" + source + "\n")
    payload = assemble(source)

    hook = CaveHook(id="fxdest", site=anchor["hook"],
                    stock=bytes.fromhex(anchor["stock"]),
                    payload=payload, cave=Cave(*anchor["cave"]))
    edited = apply(LoadedImage(dest=section.dest, content=bytes(content)), hook)
    _verify(stock_bytes, edited, hook, off)

    SECTION_OUT.parent.mkdir(parents=True, exist_ok=True)
    SECTION_OUT.write_bytes(edited)
    print(f"  wrote {SECTION_OUT}  ({len(edited):,} bytes)")

    syx = fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, edited)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"  wrote {OUT}  ({len(syx):,} bytes)")
    print(f"  sha256 {hashlib.sha256(syx).hexdigest()}")

    print("\nOn the device: INIT a pattern on track 1, turn its DEL send up and")
    print("hold a note so the delay is audible. Then on LFO1 (page one of [MOD]),")
    print("leave DEST at its default, set MULT and SPD so the LFO is clearly")
    print("moving, WAVE to TRI, and turn DEP to its stop.")
    print("  the delay feedback surges and collapses with the LFO")
    print("                          -> route A's engine half works")
    print("  nothing moves           -> the code never reaches the cave, or DEP is centred")
    print("  (the Delay page on screen does not move -- the UI reads the control side.)")
    return 0


def _check_controls(content, controls) -> None:
    """Assert every address this build reasons from, before writing anything.

    `docs/PRINCIPLES.md` §19: an address taken on trust from a document is not
    an instrument. Each of these is one `dnfw disasm` away by hand.
    """
    for address, expected, why in controls:
        want = bytes.fromhex(expected)
        off = address - BASE
        found = bytes(content[off:off + len(want)])
        if found != want:
            raise SystemExit(
                f"{address:#010x}: expected {want.hex(' ')} ({why}) but found "
                f"{found.hex(' ')} -- wrong build or wrong address"
            )
        print(f"  control {address:#010x}  {want.hex(' '):<14}  {why}")


def _check_sealed(content, address: int, length: int) -> None:
    """Nothing in the image may branch into, or point at, the bytes we replace.

    Replaying displaced instructions is only correct if nothing else enters the
    middle of them. The branch check is a grep over the disassembly; this is the
    stronger half of it -- a scan for any longword in the whole section holding
    one of the addresses about to be overwritten, which catches a jump table a
    disassembly listing would not show as a branch.
    """
    targets = {address + i for i in range(0, length, 2)}
    hits = []
    for off in range(0, len(content) - 4, 2):
        value = struct.unpack_from(">I", content, off)[0]
        if value in targets:
            hits.append((BASE + off, value))
    if hits:
        raise SystemExit(
            "a longword in the section points into the bytes to be replaced: "
            + ", ".join(f"{a:#010x} -> {v:#010x}" for a, v in hits[:8])
        )
    print(f"  sealed  {address:#010x}+{length}: no longword in the section points into it")


def _verify(before: bytes, after: bytes, hook: CaveHook, bound_off: int) -> None:
    if len(before) != len(after):
        raise SystemExit("length changed -- a cave patch must not resize the section")
    diffs = [i for i in range(len(before)) if before[i] != after[i]]
    hook_lo, hook_hi = hook.site - BASE, hook.site - BASE + len(hook.stock)
    cave_lo = hook.cave.address - BASE
    cave_hi = cave_lo + hook.cave.capacity
    stray = [i for i in diffs
             if not (hook_lo <= i < hook_hi or cave_lo <= i < cave_hi
                     or bound_off <= i < bound_off + 2)]
    if stray:
        raise SystemExit(f"{len(stray)} bytes changed outside the two edits")
    in_hook = sum(1 for i in diffs if hook_lo <= i < hook_hi)
    in_cave = sum(1 for i in diffs if cave_lo <= i < cave_hi)
    print(f"  verified: {len(diffs)} bytes changed -- {len(diffs) - in_hook - in_cave} "
          f"at the bound, {in_hook} at the hook, {in_cave} in the cave, 0 elsewhere")
    op, destination = struct.unpack_from(">HI", after, hook_lo)
    if op != 0x4EF9 or destination != hook.cave.address:
        raise SystemExit(f"hook is not `jmp {hook.cave.address:#010x}`")
    print(f"  hook reads jmp {hook.cave.address:#010x}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Route A's browser half: choose an FX parameter from the `DEST` list.

    python scripts/build_fxbrowser.py

`docs/fx-master-modulation.md` §14: `fxdest` was flashed and an LFO modulated
Delay Feedback Gain, responding to `DEP` and `SPD`. The engine accepts `DEST`
codes 101..127; **nothing could choose one.** This build is the other half, and
it carries `fxdest`'s two edits as well, because the browser is useless without
the engine and the engine is unreachable without the browser.

## What §11 specified, and what reading it again changed

§11 said: extend `SoundParameterSet`'s `+0x50`, raise the enumeration bound,
and teach three entry->slot sites the `+76`. All three hold. Three things came
out of reading it a second time, and two of them are the reason this build is
smaller than it looked:

**1. The ordering map already ranks the FX groups.** The 26-entry table at
`0x4028bfc4` is a list of group ids in **display order**:

    30, 12, 5, 6, 7, 8, 9, 10, 13, 11, 15, 16, 17, 18, 19, 20, 21, 29, 14, 22..28

Chorus (16), Reverb (17) and Delay (18) are at ranks 11, 12 and 13, between
group 15 and group 19. The comparator at `0x4003907e` sorts by
`map[group(entry)]` and breaks ties by entry number, reaching the map through
`0x40193cf8` — `operator[]`, which would default-insert 0 for a missing key
rather than fault. **So the hang this was flagged as risking cannot happen
here, and the FX destinations land in a sensible place with no work at all.**

**2. The `+0x50` virtual is reached through one shared helper.** The sound
set's vtable slot ends `jsr 0x400dc02a` at `0x40036758`, passing
`(slot, machineA, machineB)`; the FX set's is a two-instruction thunk at
`0x40036768` into `0x400dc0b0`. Hooking `0x400dc02a` fixes **all four** callers
of the virtual at once — the enumeration loop, the group-step's current-slot
lookup, and the browser's two — without touching the other sets, whose own
bounds (100, 100, 25) already reject a code above 100.

**3. Item 4 is three `jsr` targets, not three caves.** All three sites are
`4e b9 40 0d bc c4`. Rewriting the four-byte address to a helper of our own
leaves `0x400dbcc4` itself untouched for its other **31** callers, displaces
nothing, and needs no hook.

## What `+44` actually carries, measured rather than assumed

The enumeration keeps an entry when `want` is a **subset** of the record's
`+44`. Measured on this image:

- the three `DEST` records yield **different** `want` masks through the cascade
  at `0x400397f2` — LFO1 (entry 78) `0x1e00`, LFO2 (88) `0x0e00`, LFO3 (98)
  `0x0600` — and the browser's list path passes `0x200` (`0x40107ab0`);
- **every Delay and Reverb record the FX slot table selects carries `0x1e00`**,
  which is a superset of all four masks, so all seventeen pass for all three
  LFOs with no record edit whatever;
- **every Chorus record carries `0`**, so Chorus is blocked under every mask.

So §6 item 5 is needed only for Chorus. This build sets `0x1e00` on Chorus's
eight, **plus the two blocked `Mix Volume` duplicates** (entries 120 and 129):
slots 31, 39 and 47 each have two records, and which one the boot-time table
keeps decides whether that slot is reachable. Setting both members of each pair
makes the build correct whichever one wins, instead of resting on a derivation.

Setting `+44` low bits cannot disturb the three "is this a `DEST` record" tests
(`andil #0x70000`, bits 16-18) and the same edit was already flashed on
2026-09-12 with no ill effect — it did nothing then, because the enumeration
was the real gate, which is exactly what this build changes.

## The edits

| # | at | stock | becomes |
|---|---|---|---|
| 1 | `0x40137a8e` | `72 64` | `72 7f` — `fxdest`: the evaluator's bound |
| 2 | `0x40137a9e` | `73 6c 00 52 4d f0 7a 00` | `jmp` — `fxdest`: block 16 for codes 101..127 |
| 3 | `0x400dc02a` | `2f 02 72 64 20 6f 00 08` | `jmp` — slots 101..124 answer from the FX set's table |
| 4 | `0x400395b8` | `72 65` | `72 7d` — the enumeration walks 0..124, not 0..100 |
| 5 | `0x4003985e` | `4e b9 40 0d bc c4` | `jsr <helper>` — entry -> code, the randomiser |
| 6 | `0x400c2a36` | `4e b9 40 0d bc c4` | `jsr <helper>` — entry -> code, the group step |
| 7 | `0x40107b0e` | `4e b9 40 0d bc c4` | `jsr <helper>` — entry -> code, the browser's confirm |
| 8 | ten records | `+44` = `0` | `+44` = `0x1e00` — Chorus, and the two blocked duplicates |

The helper is `0x400dbcc4`'s five instructions plus a group test: it returns
`record+12`, and `record+12 + 76` when the record's group is 16, 17 or 18. The
`+0x50` hook is its exact inverse, so a code round-trips to the entry it came
from, which is what the browser's confirm path at `0x40107b0e` needs.

## What this build cannot be gated on, said before it is built

**The emulator runs no destination browser.** It has no panel, no page view and
no encoder, so "the list shows Delay Time and turning the encoder selects it"
is the instrument's question and nothing here can answer it.

What *can* be exercised, and what `scripts/emu_fxbrowser.py` does, is every
piece the browser is built out of, called directly on a booted machine with the
stock image as a control: the boot-time FX slot table, the `+0x50` helper over
every slot 0..130, and the entry -> code helper over every entry 1..320 against
`0x400dbcc4`'s own answer. That is the difference between "the arithmetic is
right" and "it was never run".

## The consequence to warn about, now that it becomes visible

**Sixteen tracks' LFOs can all aim at the same global FX cell and they stack**,
because every evaluator reads the cell and adds to it before the clamp.
`fxdest` exposed one LFO so it could not be seen. The moment the list offers
these codes it can be, and it is not a fault: it is what "global" means.

**Master (slots 60..69) stays out.** It needs codes 136..145 and `mvs.b` makes
any byte above 127 negative. That is the `mvz.b` widening, a third build.

No firmware bytes live in this repository: everything is read from the user's
own local image at build time. Output is a .syx under `00_Resources/02_Builds/`
(gitignored), and the patched section alone under `out/fxbrowser/`.
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

RECORDS = 0x401F7FC8        # the 320-record table
RECORD_BASE = 0x401F7F94    # the pre-biased base the accessors use: table - 60 + 8
RECORD_SIZE = 60
SLOT_WORD = 3               # params/record.py PARAMETER_ID -- byte 12
GROUP_WORD = 2              # params/record.py GROUP        -- byte 8
MASK_WORD = 11              # the capability field this file calls `+44`

FX_SLOT_TABLE = 0x42C649A8  # FxParameterSet's slot -> entry table, built at boot
CODE_BIAS = 76
CODE_LO, CODE_HI = 101, 124
FX_GROUPS = (16, 17, 18)    # Chorus, Reverb, Delay
OPEN_MASK = 0x1E00

MIRROR_BASE = 0x800068E4
HEADER, BLOCK, FX_BLOCK = 34, 202, 16

CAVE = (0x4028EA02, 170)    # the one cave with a hardware-confirmed success

# The ten records whose `+44` is opened: Chorus's eight, and the two blocked
# `Mix Volume` duplicates, so the build does not rest on which of a slot's two
# records the boot-time table keeps.
OPEN_RECORDS = (105, 106, 107, 108, 109, 110, 111, 112, 120, 129)

ANCHORS = {
    3_192_192: {
        # fxdest, carried forward unchanged.
        "eval_bound": (0x40137A8E, "7264", "7f", "moveq #100,%d1 -> #127, evaluator A"),
        "eval_hook": (0x40137A9E, "736c00524df07a00", 0x40137AA6),
        # The browser half.
        "slot_hook": (0x400DC02A, "2f02726420 6f0008".replace(" ", ""), 0x400DC032),
        "enum_bound": (0x400395B8, "7265", "7d", "moveq #101,%d1 -> #125, the 0..100 walk"),
        "convert": (
            (0x4003985E, "the randomiser, with `lsl.l #8` at 0x40039868"),
            (0x400C2A36, "the group step, with `lsl.l #8` at 0x400c2a3e"),
            (0x40107B0E, "the browser's confirm path, which carries no shift"),
        ),
        "sealed": ((0x40137A9E, 8), (0x400DC02A, 8)),
        "controls": (
            (0x400DC032, "202f000c226f", "movel %sp@(12),%d0 -- the resume point"),
            (0x400DC062, "43f942c64b3c", "lea 0x42c64b3c,%a1 -- the sound set's own table"),
            (0x400DC0B0, "7264", "moveq #100,%d1 -- FxParameterSet keeps its bound"),
            (0x400DC0BE, "41f942c649a8", "lea 0x42c649a8,%a0 -- the FX slot table"),
            (0x40036768, "2f6f000800044ef9400dc0b0", "FxParameterSet::slot_to_entry"),
            (0x40036758, "4eb9400dc02a", "jsr 0x400dc02a -- the sound set's vtable +0x50"),
            (0x400395BA, "b2826 6cc".replace(" ", ""), "cmpl %d2,%d1 ; bnes -- the loop"),
            (0x4003958E, "2f0d", "movel %a5,%sp@- -- the set, into the +0x50 call"),
            (0x40039590, "20680050", "moveal %a0@(80),%a0 -- vtable +0x50"),
            (0x400395A4, "c0af0038", "andl %sp@(56),%d0 -- the `want` subset test"),
            (0x400DBCC4, "202f0004", "movel %sp@(4),%d0 -- entry -> +12, left untouched"),
            (0x400DBCE8, "202f0004", "movel %sp@(4),%d0 -- entry -> +8, left untouched"),
            (0x4003907E, "4fefffe4", "the sort comparator, which reads the group"),
            (0x4028BFC4, "0000001e", "the ordering table's first entry, group 30"),
            # fxdest's own anchors, re-asserted.
            (0x40137A8A, "752c004a", "mvsb %a4@(74),%d2 -- DEST, evaluator A"),
            (0x40137AD0, "3c80", "movew %d0,%fp@ -- the store we inherit"),
            (0x400DB14A, "45f9800068e4", "lea 0x800068e4,%a2 -- the mirror base"),
        ),
    },
}

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/fxbrowser_DN2_1.11.syx")
SECTION_OUT = pathlib.Path("out/fxbrowser/section_3_MAIN_OS.bin")

# Longwords a *later* build in this family rewrites, as
# (address, stock hex, new hex, why). Empty here: `fxbrowser` itself changes
# nothing outside its hooks, its six conversions and its ten record masks.
# A successor appends to this rather than copying `main()`, so the stock-byte
# assertion and the "nothing changed outside a declared edit" check keep
# covering every edit in the build. See `build_fxbrowser3.py`.
EXTRA_LONGWORDS: list[tuple[int, str, str, str]] = []


def fx_mirror_base() -> int:
    """What `fxdest`'s cave loads into `%a0` for a code of 101..127."""
    return MIRROR_BASE + HEADER + BLOCK * FX_BLOCK - 2 * CODE_BIAS


def helper_source() -> str:
    """entry -> `DEST` code: `0x400dbcc4`'s answer, plus 76 for an FX record.

    The out-of-range fold is `0x400dbcc4`'s own, spelled as a branch rather
    than its `scs`/`mvs.b`/`and` idiom: an entry of 321 or more resolves to
    entry 0, exactly as the routine this stands in for does.
    """
    return f"""    move.l  %sp@(4),%d0            | the entry
    cmpi.l  #321,%d0
    bcs.s   1f
    clr.l   %d0                    | out of range -> entry 0, as 0x400dbcc4 folds it
1:  move.l  %d0,%d1
    lsl.l   #2,%d1
    lsl.l   #6,%d0
    sub.l   %d1,%d0                | 60 * entry
    lea     {RECORD_BASE:#010x},%a0
    lea     %a0@(0,%d0:l),%a0      | the pre-biased record
    move.l  %a0@(4),%d0            | +12 : the ParameterSet slot
    move.l  %a0@(0),%d1            | +8  : the page group
    subi.l  #{FX_GROUPS[0]},%d1
    cmpi.l  #{len(FX_GROUPS) - 1},%d1
    bhi.s   2f                     | not Chorus 16 / Reverb 17 / Delay 18
    addi.l  #{CODE_BIAS},%d0       | -> the route A code, {CODE_LO}..{CODE_HI}
2:  rts"""


def slot_payload() -> str:
    """Answer slots 101..124 from the FX set's own table; everything else stock.

    Entered before the function has pushed anything, so `%sp@(4)` is its first
    argument and an `rts` here returns to its caller. `%d0`, `%d1` and `%a0` are
    call-clobbered and are what the stock routine uses as scratch anyway.
    """
    indexed = FX_SLOT_TABLE - 4 * CODE_BIAS
    return f"""    move.l  %sp@(4),%d0            | the slot
    moveq   #100,%d1
    cmp.l   %d0,%d1
    bcc.s   1f                     | slot <= 100 -> the stock lookup
    moveq   #{CODE_HI},%d1
    cmp.l   %d0,%d1
    bcs.s   1f                     | above {CODE_HI} -> stock, which returns 0
    lea     {indexed:#010x},%a0     | {FX_SLOT_TABLE:#010x} - 4*{CODE_BIAS}
    move.l  %a0@(0,%d0:l:4),%d0    | the FX set's own entry for this slot
    rts
1:"""


def eval_payload(base: int) -> str:
    """`fxdest`'s cave, carried forward without its hard-coded demonstration.

    The demonstration existed because nothing could choose a code. This build
    is the thing that can, so it goes; leaving it in would silently steal
    track 1's LFO1 from the owner the moment he sets its `DEST` to none.
    """
    return f"""    moveq   #100,%d1
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
    for address, length in anchor["sealed"]:
        _check_sealed(content, address, length)
    _check_geometry(content)
    _check_masks(content)

    # --- the two byte edits -------------------------------------------------
    for key in ("eval_bound", "enum_bound"):
        address, stock_hex, new_byte, why = anchor[key]
        _poke_byte(content, address, stock_hex, new_byte, why)

    # --- the cave layout ----------------------------------------------------
    cave_address, cave_capacity = CAVE
    helper = assemble(helper_source())
    if len(helper) % 2:
        helper += b"\x00"
    helper_address = cave_address
    print(f"\n  helper at {helper_address:#010x}, {len(helper)} bytes -- "
          f"entry -> code, +{CODE_BIAS} for groups {FX_GROUPS}")

    image = LoadedImage(dest=section.dest, content=bytes(content))
    offset = image.offset_of(helper_address)
    if any(image.content[offset:offset + len(helper)]):
        raise SystemExit(f"the cave at {helper_address:#010x} is not free")
    content[offset:offset + len(helper)] = helper

    used = len(helper)
    hooks = []
    for key, payload_source, why in (
        ("eval_hook", eval_payload(fx_mirror_base()), "fxdest: block 16 for 101..127"),
        ("slot_hook", slot_payload(), "the FX set's table for slots 101..124"),
    ):
        site, stock_hex, resume = anchor[key]
        payload = assemble(payload_source)
        body = len(payload) + len(bytes.fromhex(stock_hex)) + 6
        here = cave_address + used
        if used + body > cave_capacity:
            raise SystemExit(
                f"the cave holds {cave_capacity} bytes; this build needs "
                f"{used + body}. Chain a second run (docs/code-caves.md)."
            )
        hook = CaveHook(id=key, site=site, stock=bytes.fromhex(stock_hex),
                        payload=payload, cave=Cave(here, cave_capacity - used))
        content[:] = apply(LoadedImage(dest=section.dest, content=bytes(content)), hook)
        print(f"  {key:10} hook {site:#010x} -> cave {here:#010x}, {body} bytes "
              f"(resume {resume:#010x})  {why}")
        hooks.append((hook, here, body))
        used += body
    print(f"  cave used {used} of {cave_capacity} bytes\n")

    # --- the three conversion sites ----------------------------------------
    for address, why in anchor["convert"]:
        _repoint(content, address, 0x400DBCC4, helper_address, why)

    # --- the ten record masks ----------------------------------------------
    print()
    for entry in OPEN_RECORDS:
        _open_mask(content, entry)

    # --- whatever a successor adds -----------------------------------------
    if EXTRA_LONGWORDS:
        print()
    for address, stock_hex, new_hex, why in EXTRA_LONGWORDS:
        _poke_longword(content, address, stock_hex, new_hex, why)

    _verify(stock_bytes, content, anchor, helper_address, used)

    edited = bytes(content)
    SECTION_OUT.parent.mkdir(parents=True, exist_ok=True)
    SECTION_OUT.write_bytes(edited)
    print(f"\n  wrote {SECTION_OUT}  ({len(edited):,} bytes)")

    syx = fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, edited)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"  wrote {OUT}  ({len(syx):,} bytes)")
    print(f"  sha256 {hashlib.sha256(syx).hexdigest()}")

    print("\nOn the device: on a synth track, [MOD], LFO1, turn DEST.")
    print("  partway through the list -- ranks 11..13 of 26, after group 15 --")
    print("  24 entries: Chorus, then Reverb, then Delay. Pick 'Feedback Gain',")
    print("  set WAVE and SPD, turn DEP up from centre, with the track's DEL")
    print("  send up and a note held.")
    print("  the delay feedback moves with the LFO   -> the round trip works")
    print("  the names appear but nothing moves      -> selection stores the wrong code")
    print("  no FX names in the list                 -> enumeration, not selection")
    return 0


# --------------------------------------------------------------------------
# guards


def _record(content, entry: int) -> tuple[int, ...]:
    off = RECORDS - BASE + RECORD_SIZE * (entry - 1)
    return struct.unpack_from(">15I", content, off)


def _name(content, pointer: int) -> str:
    if not (BASE <= pointer < BASE + len(content)):
        return "?"
    off = pointer - BASE
    end = content.index(b"\x00", off)
    return bytes(content[off:end]).decode("latin1")


def _check_controls(content, controls) -> None:
    """Assert every address this build reasons from, before writing anything."""
    for address, expected, why in controls:
        want = bytes.fromhex(expected)
        off = address - BASE
        found = bytes(content[off:off + len(want)])
        if found != want:
            raise SystemExit(
                f"{address:#010x}: expected {want.hex(' ')} ({why}) but found "
                f"{found.hex(' ')} -- wrong build or wrong address"
            )
        print(f"  control {address:#010x}  {want.hex(' '):<26}  {why}")


def _check_sealed(content, address: int, length: int) -> None:
    """Nothing may enter the *interior* of bytes that are about to move.

    The first address is excluded deliberately. When the hook sits at a
    function's entry every reference to it is a **caller**, and routing those
    through the cave is the whole point; it is a reference two bytes in that
    would land in the middle of a replaced instruction. So the entry is
    counted and reported, and only the interior is sealed.
    """
    entry = [BASE + off for off in range(0, len(content) - 4, 2)
             if struct.unpack_from(">I", content, off)[0] == address]
    interior = {address + i for i in range(2, length, 2)}
    hits = [(BASE + off, struct.unpack_from(">I", content, off)[0])
            for off in range(0, len(content) - 4, 2)
            if struct.unpack_from(">I", content, off)[0] in interior]
    if hits:
        raise SystemExit(
            "a longword points into the interior of bytes to be replaced: "
            + ", ".join(f"{a:#010x} -> {v:#010x}" for a, v in hits[:8])
        )
    note = (f"; {len(entry)} longword(s) name the entry itself -- its callers, "
            f"which is what the hook is for") if entry else ""
    print(f"  sealed  {address:#010x}+{length}: nothing points into its interior{note}")


def _check_geometry(content) -> None:
    """A wrong anchor into a dense table still yields plausible records.

    So the records this build reasons about are checked by name, group and
    slot together -- `docs/FEATURE-PLAYBOOK.md` §3.
    """
    expect = {
        78: ("Destination", 26, 4), 88: ("Destination", 27, 12),
        98: ("Destination", 28, 20),
        105: ("Depth", 16, 25), 112: ("Mix Volume", 16, 31),
        116: ("Feedback Gain", 18, 35), 121: ("Mix Volume", 18, 39),
        124: ("Decay Time", 17, 42), 131: ("Reverb FX Routing", 17, 48),
    }
    for entry, (name, group, slot) in expect.items():
        w = _record(content, entry)
        got = (_name(content, w[12]), w[GROUP_WORD], w[SLOT_WORD])
        if got != (name, group, slot):
            raise SystemExit(
                f"entry {entry}: expected {(name, group, slot)} but found {got} -- "
                f"the record table is not where this build thinks it is"
            )
    print(f"  geometry {len(expect)} records resolve to their expected name, group and slot")


def _check_masks(content) -> None:
    """Report what `+44` carries across slots 25..48, and which `want` passes.

    This is the measurement §6 item 5 was guessing at, and it decides how many
    records the build has to touch. It is printed rather than asserted, because
    the useful form of it is the table.
    """
    table = {}
    for index in range(320):
        w = _record(content, index + 1)
        if w[GROUP_WORD] != 0xFFFFFFFF and 16 <= w[GROUP_WORD] <= 21 \
                and w[SLOT_WORD] != 0xFFFFFFFF:
            table[w[SLOT_WORD]] = index + 1
    blocked = []
    for slot in range(25, 49):
        entry = table.get(slot)
        if entry is None:
            raise SystemExit(f"FX slot {slot} has no record -- the derivation is wrong")
        w = _record(content, entry)
        if (~w[MASK_WORD] & OPEN_MASK) != 0:
            blocked.append((slot, entry, _name(content, w[12])))
    print(f"  masks    slots 25..48 resolve to 24 records; {24 - len(blocked)} already "
          f"pass a `want` of {OPEN_MASK:#06x}")
    for slot, entry, name in blocked:
        print(f"           slot {slot:3} code {slot + CODE_BIAS:3} entry {entry:3} "
              f"{name!r} is blocked and is opened below")


def _poke_byte(content, address: int, stock_hex: str, new_byte: str, why: str) -> None:
    want = bytes.fromhex(stock_hex)
    off = address - BASE
    if bytes(content[off:off + len(want)]) != want:
        raise SystemExit(f"{address:#010x}: expected {want.hex(' ')} ({why})")
    content[off + 1] = int(new_byte, 16)
    print(f"  edit    {address:#010x}  {want.hex(' ')} -> "
          f"{bytes(content[off:off + len(want)]).hex(' ')}   {why}")


def _poke_longword(content, address: int, stock_hex: str, new_hex: str, why: str) -> None:
    """Replace one longword, refusing unless the stock one is exactly there."""
    want, new = bytes.fromhex(stock_hex), bytes.fromhex(new_hex)
    if len(want) != 4 or len(new) != 4:
        raise SystemExit(f"{address:#010x}: a longword edit is four bytes")
    off = address - BASE
    if bytes(content[off:off + 4]) != want:
        raise SystemExit(
            f"{address:#010x}: expected {want.hex(' ')} ({why}) but found "
            f"{bytes(content[off:off + 4]).hex(' ')}"
        )
    content[off:off + 4] = new
    print(f"  poke    {address:#010x}  {want.hex(' ')} -> {new.hex(' ')}   {why}")


def _repoint(content, address: int, old: int, new: int, why: str) -> None:
    """Send one `jsr` somewhere else, leaving the routine it called untouched."""
    off = address - BASE
    opcode, target = struct.unpack_from(">HI", content, off)
    if opcode != 0x4EB9 or target != old:
        raise SystemExit(
            f"{address:#010x}: expected `jsr {old:#010x}` but found "
            f"opcode {opcode:#06x} target {target:#010x}"
        )
    struct.pack_into(">I", content, off + 2, new)
    print(f"  repoint {address:#010x}  jsr {old:#010x} -> jsr {new:#010x}   {why}")


def _open_mask(content, entry: int) -> None:
    w = _record(content, entry)
    if w[MASK_WORD] == OPEN_MASK:
        print(f"  mask    entry {entry:3} already {OPEN_MASK:#07x}, left alone")
        return
    if w[MASK_WORD] != 0:
        raise SystemExit(
            f"entry {entry}: `+44` is {w[MASK_WORD]:#010x}, not 0 -- this build only "
            f"opens records that are closed, so it cannot quietly clear a flag"
        )
    off = RECORDS - BASE + RECORD_SIZE * (entry - 1) + 4 * MASK_WORD
    struct.pack_into(">I", content, off, OPEN_MASK)
    print(f"  mask    entry {entry:3} {_name(content, w[12])!r:22} group {w[GROUP_WORD]:2} "
          f"slot {w[SLOT_WORD]:2}: +44 0x0 -> {OPEN_MASK:#07x}")


def _verify(before: bytes, after, anchor, helper_address: int, used: int) -> None:
    after = bytes(after)
    if len(before) != len(after):
        raise SystemExit("length changed -- a cave patch must not resize the section")
    allowed = []
    for key in ("eval_bound", "enum_bound"):
        allowed.append((anchor[key][0] - BASE, 2))
    for key in ("eval_hook", "slot_hook"):
        allowed.append((anchor[key][0] - BASE, len(bytes.fromhex(anchor[key][1]))))
    for address, _ in anchor["convert"]:
        allowed.append((address - BASE + 2, 4))
    allowed.append((helper_address - BASE, used))
    for entry in OPEN_RECORDS:
        allowed.append((RECORDS - BASE + RECORD_SIZE * (entry - 1) + 4 * MASK_WORD, 4))
    for address, _stock, _new, _why in EXTRA_LONGWORDS:
        allowed.append((address - BASE, 4))

    diffs = [i for i in range(len(before)) if before[i] != after[i]]
    stray = [i for i in diffs if not any(lo <= i < lo + n for lo, n in allowed)]
    if stray:
        raise SystemExit(
            f"{len(stray)} bytes changed outside the declared edits, first at "
            f"{BASE + stray[0]:#010x}"
        )
    print(f"\n  verified: {len(diffs)} bytes changed, every one inside a declared edit")
    for key in ("eval_hook", "slot_hook"):
        site = anchor[key][0]
        op, _ = struct.unpack_from(">HI", after, site - BASE)
        if op != 0x4EF9:
            raise SystemExit(f"{site:#010x} is not a `jmp`")
    print("  both hooks read `jmp`")


if __name__ == "__main__":
    raise SystemExit(main())

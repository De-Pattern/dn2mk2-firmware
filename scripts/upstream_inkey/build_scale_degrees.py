"""Where a voice's scale is in the playing pattern, and a move by its degrees.

Assembly shared by the mods that move notes by degrees of the track's KEYBOARD
SETUP scale (arpscale). Each mod assembles these into its own CODE chunk.

## The move

`degree_move` moves a note by a number of degrees of the scale `s` with root `r`:

1. The note's place in the scale: its octave above the root and its degree. A
   note outside the scale is first moved to the nearest scale note, the lower
   one on a tie (the firmware's own order, `0x4015003a`: 0, -1, +1, -2, +2).
2. The degree plus the move, carried into octaves by the scale's length (a
   pentatonic octave is 5 degrees, a whole-tone one 6).

`scale_lookup` finds `s` and `r`, and fails, so the caller keeps stock
behaviour, whenever the scale says nothing about degrees: SCALE CHROMATIC, MODE
CHORD MEMORY (where the firmware's own getter `0x4003bdb2` treats the scale as
chromatic), and a value out of range.

## Where the scale is, while the pattern plays

`locate` runs inside the frame ISR `0x40025e36` (`link.w %fp,#-236`, and
nothing after it moves `%a6`), which keeps its voice record at `-36(%fp)`; a
caller makes sure it is there (arpscale checks the arp step's caller). In the
record, `+16` is the track and `+44` the track's part of the
**playback copy** of the pattern, written at `0x400d8a2e` as `L + 1701 x track`
(`0x400d8654`, `L = *0x42c5a9a0`). A note played live (the KEYBOARD page,
sequencer running or not) has a record with `+44` zero, so for it `locate`
reads `*0x42c5a9a0`, the current playback copy, and adds the track's part
itself. The copy is double-buffered: a pattern change (`0x400d99a4`) moves the
old pointer to `0x42c5a9a8` and the cued one to `0x42c5a9a0`, so a trig keeps
the pattern it came from and a live note gets the pattern playing now. A
layered copy (TRACK WILL TRIGGER, `0x400255b4`, `+56` bit 17) keeps its
source's `+44` while `+16` names its destination, so `locate` finds the copy's
start through the source track (`+92`) and takes the destination's part of it.
`0x400de616` builds the copy from the stored pattern:

| stored (DNX `docs/dn2-pattern-format.md`) | playback copy | read here |
|---|---|---|
| track `+4 + 1187 t`, settings `+0x480` | track `L + 1701 t`, same offsets for these | SCALE `+1170`, MODE `+1171`, ROOT `+1172` (`0x400ddf8a`) |
| header `+0x15AD4` | header `L + 0x1DD40` (`0x400dd97c`, field by field) | SCALE `+29` (0..34, else chromatic), MODE `+30`, ROOT `+31` (0..11), the per-track switch `+33` |

The switch byte selects per bit, as the UI getters do (`0x4003aa9e`,
`0x4003ab54`, `0x4003ac0c`): bit 0 MODE, bit 1 ROOT, bit 2 SCALE from the track,
else from the pattern. The scale tables are the firmware's: `0x4020ec20` (13
bytes a scale: semitone above the root -> degree + 1, 0 when not in it) and
`0x4020dea0` (8 longs a scale: degree -> semitone, -1 past its length). Every
scale holds its root, which the build asserts, so the search for the nearest
scale note ends.

"""

from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw import osport  # noqa: E402

BASE = 0x40000400

RECORD = -36                    # the frame ISR's voice record, -36(%fp)
REC_TRACK, REC_COPY = 16, 44
REC_FLAGS, REC_SOURCE = 56, 92  # a layered copy (TRACK WILL TRIGGER): +56 bit 17, its source track +92
LAYERED_BIT = 17
PLAYBACK = 0x42C5A9A0           # -> the current playback copy (L), for a live note's record
TRACK_STRIDE = 1701             # the playback copy's tracks
HEADER = 0x1DD40                # the playback copy's pattern header
T_SCALE, T_MODE, T_ROOT = 1170, 1171, 1172
H_SCALE, H_MODE, H_ROOT, H_SWITCH = 29, 30, 31, 33
CHORD_MEMORY = 5
SCALE_MAX, ROOT_MAX = 34, 11
DEGREES = 0x4020EC20            # 13 bytes a scale: semitone -> degree + 1, 0 = not in it
SEMITONES = 0x4020DEA0          # 8 longs a scale: degree -> semitone, -1 past the last
DEGREE_ROW, SEMITONE_ROW = 13, 32


def scale_lookup(fail: str, os: str = "1.11") -> str:
    """Assembly, for code running inside the frame ISR (`%a6` its frame): the SCALE
    and ROOT of the voice record's track in the playing pattern. -> `%d6` SCALE
    (0..SCALE_MAX), `%d7` ROOT (0..ROOT_MAX), or a branch to FAIL when the track
    has no scale (CHROMATIC, CHORD MEMORY, a value out of range, or no playback
    copy). Uses `%d3`-`%d5` and `%a2`-`%a4`. OS: the stock addresses' version (issue #382)."""
    return locate(fail, os) + resolve(fail)


def locate(fail: str, os: str = "1.11") -> str:
    """Assembly, inside the frame ISR (`%a6` its frame): where the voice record's
    track is in the playing pattern. -> `%a3` the track's part of the playback copy,
    `%a4` the pattern's header, or a branch to FAIL when there is no playback copy.
    A trig's record holds the playback copy of the track that made it (`+44`); a
    layered copy keeps its source's, so the pattern's start is found from the
    source track, then the record's own track (`+16`) is taken from it. Uses
    `%d3`-`%d5` and `%a2`."""
    return osport.render("""    move.l  {RECORD}(%a6),%a2           | the voice record
    move.l  {REC_COPY}(%a2),%d3         | the playback copy of the track that made it
    bne.s   1f
    move.l  {PLAYBACK:#x},%d3           | a live note's record has none: the
    beq.w   {fail}                   | current copy's start
    bra.s   3f
1:  move.l  {REC_TRACK}(%a2),%d4        | that track: the record's own, or a
    btst    #{LAYERED_BIT % 8},{REC_FLAGS + 3 - LAYERED_BIT // 8}(%a2)   | layered copy's source
    beq.s   2f
    move.l  {REC_SOURCE}(%a2),%d4
2:  move.l  #{TRACK_STRIDE},%d5
    muls.l  %d5,%d4
    sub.l   %d4,%d3                     | the copy's start
3:  move.l  {REC_TRACK}(%a2),%d4        | the record's track's part, and the header
    move.l  #{TRACK_STRIDE},%d5
    muls.l  %d5,%d4
    move.l  %d3,%a4
    adda.l  #{HEADER:#x},%a4
    add.l   %d3,%d4
    move.l  %d4,%a3
""", {**globals(), **locals()}, os)


def resolve(fail: str) -> str:
    """Assembly: `%a3` and `%a4` as `locate` leaves them. -> `%d6` SCALE and `%d7`
    ROOT, as `scale_lookup` gives them, or a branch to FAIL. Uses `%d3`-`%d5`."""
    return f"""    mvz.b   {H_SWITCH}(%a4),%d5         | which values are the track's
    btst    #0,%d5
    beq.s   2f
    mvs.b   {T_MODE}(%a3),%d3
    bra.s   3f
2:  mvs.b   {H_MODE}(%a4),%d3
3:  moveq   #{CHORD_MEMORY},%d4
    cmp.l   %d4,%d3
    beq.w   {fail}                   | CHORD MEMORY: no scale
    btst    #2,%d5
    beq.s   2f
    mvs.b   {T_SCALE}(%a3),%d6
    bra.s   3f
2:  mvs.b   {H_SCALE}(%a4),%d6
3:  tst.l   %d6
    bmi.w   {fail}                   | CHROMATIC
    moveq   #{SCALE_MAX},%d4
    cmp.l   %d4,%d6
    bgt.w   {fail}
    btst    #1,%d5
    beq.s   2f
    mvz.b   {T_ROOT}(%a3),%d7
    bra.s   3f
2:  mvz.b   {H_ROOT}(%a4),%d7
3:  moveq   #{ROOT_MAX},%d4
    cmp.l   %d4,%d7
    bhi.w   {fail}
"""


def degree_move(prefix: str, os: str = "1.11") -> str:
    """Assembly: `%d0` a note, `%d2` a move in degrees (not 0), `%d6` SCALE and `%d7`
    ROOT as `scale_lookup` leaves them. -> `%d0` the note moved by `%d2` degrees of the
    scale (a note outside it first moves to the nearest note in it, the lower one on a
    tie). Uses `%d3`-`%d5` and `%a0`-`%a2`; keeps `%d1` and `%d2`. PREFIX names its
    labels."""
    return osport.render("""| The held note's place: %d3 its semitone above the root (0..11), %a1 its
| octave above the root. %d0 is free from here on.
    move.l  %d0,%d3
    sub.l   %d7,%d3
    addi.l  #12,%d3                     | held - root + 12 > 0
    moveq   #12,%d4
    move.l  %d3,%d5
    divu.l  %d4,%d5
    move.l  %d5,%a1
    subq.l  #1,%a1
    muls.l  %d4,%d5
    sub.l   %d5,%d3
    move.l  %d6,%d4                     | the scale's degree row
    moveq   #{DEGREE_ROW},%d5
    muls.l  %d5,%d4
    lea     {DEGREES:#x},%a0
    adda.l  %d4,%a0
    mvz.b   (0,%a0,%d3.l),%d4
    tst.l   %d4
    bne.s   {prefix}_found

| Not in the scale: the nearest note that is, the lower one first. The root is
| in every scale (asserted by the build), so this ends within six semitones.
    moveq   #1,%d5
{prefix}_near:
    move.l  %d3,%d0
    sub.l   %d5,%d0
    bpl.s   4f
    addi.l  #12,%d0
    mvz.b   (0,%a0,%d0.l),%d4
    tst.l   %d4
    beq.s   5f
    move.l  %d0,%d3
    subq.l  #1,%a1
    bra.s   {prefix}_found
4:  mvz.b   (0,%a0,%d0.l),%d4
    tst.l   %d4
    beq.s   5f
    move.l  %d0,%d3
    bra.s   {prefix}_found
5:  move.l  %d3,%d0
    add.l   %d5,%d0
    moveq   #12,%d4
    cmp.l   %d4,%d0
    blt.s   6f
    subi.l  #12,%d0
    mvz.b   (0,%a0,%d0.l),%d4
    tst.l   %d4
    beq.s   7f
    move.l  %d0,%d3
    addq.l  #1,%a1
    bra.s   {prefix}_found
6:  mvz.b   (0,%a0,%d0.l),%d4
    tst.l   %d4
    beq.s   7f
    move.l  %d0,%d3
    bra.s   {prefix}_found
7:  addq.l  #1,%d5
    bra.s   {prefix}_near

| %d4 the degree + 1. Add the offset in degrees and carry octaves by the
| scale's length (%d5), counted from its semitone row (%a2).
{prefix}_found:
    subq.l  #1,%d4
    add.l   %d2,%d4
    lea     {SEMITONES:#x},%a2
    move.l  %d6,%d5
    lsl.l   #5,%d5
    adda.l  %d5,%a2
    moveq   #0,%d5
8:  moveq   #8,%d0
    cmp.l   %d0,%d5
    beq.s   9f
    move.l  (0,%a2,%d5.l*4),%d0
    bmi.s   9f
    addq.l  #1,%d5
    bra.s   8b
9:  move.l  %d4,%d0                     | floor(%d4 / length), and the degree left
    divs.l  %d5,%d0
    move.l  %d0,%d3
    muls.l  %d5,%d3
    sub.l   %d3,%d4
    bpl.s   1f
    add.l   %d5,%d4
    subq.l  #1,%d0
1:  add.l   %a1,%d0                     | octaves above the root
    moveq   #12,%d3
    muls.l  %d3,%d0
    add.l   (0,%a2,%d4.l*4),%d0
    add.l   %d7,%d0
""", {**globals(), **locals()}, os)


# Read, not written: where `scale_lookup` finds a voice's scale, and the scale tables
# `degree_move` reads.
SCALE_CONTEXT = (
    (0x40025E36, bytes.fromhex("4e56ff14"), "the frame ISR: link %a6, its frame to the calls"),
    (0x400D8A2A, bytes.fromhex("41f2d8002748002c"), "record +44 = the playback pattern + the track's part"),
    (0x400255E2, bytes.fromhex("70024840256f001c001081aa0038256b0010005c"),
     "a layered copy: +16 the destination, +56 bit 17 set, +92 the source's track"),
    (0x400D8666, bytes.fromhex("246f003c"), "... the playback pattern, the second argument"),
    (0x400D907E, bytes.fromhex("2f3942c5a9a02f024ebaf5cc"),
     "... which a trig's caller reads from 0x42c5a9a0, before the track"),
    (0x400D99E8, bytes.fromhex("23ca42c5a9a0"), "a pattern change: the cued copy becomes current"),
    (0x400D866A, bytes.fromhex("223c000006a5"), "... the track's part: 1701 ..."),
    (0x400D8672, bytes.fromhex("4c041800"), "... x the track"),
    (0x400DE646, bytes.fromhex("06830001dd40"), "the playback header at +0x1dd40"),
    (0x400DDAA2, bytes.fromhex("102b001d"), "the header converter: SCALE at +29"),
    (0x400DDAB8, bytes.fromhex("102b001e"), "... MODE at +30"),
    (0x400DDAD8, bytes.fromhex("102b001f"), "... ROOT at +31"),
    (0x400DDB14, bytes.fromhex("102b0021"), "... the per-track switch at +33"),
    (0x400DE0B0, bytes.fromhex("10290492"), "the track converter: SCALE at +1170"),
    (0x400DE0C6, bytes.fromhex("10290493"), "... MODE at +1171"),
    (0x400DE0F8, bytes.fromhex("10290494"), "... ROOT at +1172"),
    (0x4003AC32, bytes.fromhex("71a80021e488"), "the scale getter: switch bit 2"),
    (0x4003AB7A, bytes.fromhex("71a80021e288"), "the root getter: switch bit 1"),
    (0x4003AAC4, bytes.fromhex("10280021"), "the mode getter: switch bit 0"),
    (0x4014FEB8, bytes.fromhex("d1fc4020ec20"), "in_scale: the degree table"),
    (0x401500E0, bytes.fromhex("41f94020dea0"), "the semitone table"),
)


def scales(content: bytes, os: str = "1.11") -> list[list[int]]:
    """The firmware's 35 scales as semitone lists, read from both tables (at OS's
    addresses), which must agree. Every scale holds its root (the nearest-note search
    relies on it)."""
    out = []
    for s in range(SCALE_MAX + 1):
        at = osport.addr(os, SEMITONES) - BASE + SEMITONE_ROW * s
        row = struct.unpack(">8i", content[at:at + SEMITONE_ROW])
        semis = [x for x in row if x >= 0]
        if row[:len(semis)] != tuple(semis) or not semis or semis[0] != 0:
            raise SystemExit(f"scale {s}: semitone row {row} is not a list from the root")
        at = osport.addr(os, DEGREES) - BASE + DEGREE_ROW * s
        want = bytes(semis.index(pc) + 1 if pc in semis else 0 for pc in range(12))
        if content[at:at + 12] != want:
            raise SystemExit(f"scale {s}: the degree table {content[at:at + 12].hex()} "
                             f"disagrees with the semitone row {semis}")
        out.append(semis)
    return out


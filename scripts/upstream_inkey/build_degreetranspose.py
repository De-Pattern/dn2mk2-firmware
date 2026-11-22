"""Degree transpose: move the active track by degrees of its scale, as stock moves it by semitones.

    python scripts/build_degreetranspose.py [--out PATH]

Stock 1.11 transposes the active track in semitones with [FUNC] + [+]/[-] or
[TRK] + [+]/[-]. In C major, C E G up 2 plays D F# A. This build adds the same
move in degrees of the track's KEYBOARD SETUP scale and root: C E G up 1 degree
plays D F A.

- [KEYBOARD] + [FUNC] + [+]/[-], or [KEYBOARD] + [TRK] + [+]/[-]: the active
  track, one degree a press.
- [KEYBOARD] + [TRK] + [FUNC] + [+]/[-]: stock's octave transpose of the track,
  changing the semitone amount by 12, as without [KEYBOARD].

As with stock's transpose, the degree amount is pending while the keys are held,
blinking where stock shows its own, and takes effect when [FUNC], [TRK] or
[KEYBOARD] is released. [PTN] with [KEYBOARD] held, and every key without
[KEYBOARD] held, works as stock.

## The rule

At each note, the track's degrees give `k`. With `k = 0` the note is stock's.
Otherwise the recorded, live or arp note moves `k` degrees by
`build_scale_degrees.degree_move`, the rule of ARP OFS IN SCALE: a note outside
the scale first moves to the nearest note in it (the lower one on a tie), and
octaves carry by the scale's length. Stock's transposes, in semitones, are added
after. A track with no scale (CHROMATIC, or MODE CHORD MEMORY) moves `k`
semitones, the chromatic scale's degrees. The notes in the pattern are never
rewritten, so `k = 0` plays them as recorded.

## Where the note gets its pitch

The frame ISR (`0x40025e36`) plays each entry of a voice record (a trig's notes,
a live key's, the arp's step, `docs/layer-midi.md`) in one loop. At `0x40026980`
it reads the entry's note into `%d0` and adds the track's transpose
(`0x80005381 + track`) and, when PTN TRANSPOSE CONFIG selects the track, the
pattern's (`0x80005380`), into `%d2`. `0x400269a4` checks `%d2` is 0..127. Then
the voice is allocated by `%d0`, the note as recorded (`0x400269e2`), and `%d2`
goes to the DSP as the pitch (`0x400269b8`). So releases find their voice
whatever `%d2` was, which is why stock's transposes are added only to `%d2`, and
why this build changes only `%d2`.

The hook replaces the range check's first 6 bytes (`0x400269a4`; layermidi hooks
`0x40026980`). The voice record is `-36(%fp)`, as for the arp step, so
`build_scale_degrees.locate` finds the track's part of the playing pattern, which
holds the amount, and `build_scale_degrees.resolve` the track's scale and root. A
layered copy (TRACK WILL TRIGGER, `0x400255b4`) is voiced here for its
destination track (`+16`) and moves by that track's degrees, as stock adds that
track's transpose; `locate` finds the pattern through its source track (`+92`),
whose playback copy the copy keeps in `+44`.

## A MIDI track's notes

A MIDI track's notes are not voiced: the sequencer (`0x400d8b5a`, for the tracks
in the kit's mask `+0x5cda`) and the live keys (`0x4012b8b0`) build MIDI
records, and the MIDI task (`0x4012a9a8`) sends them. Its note-on adds stock's
transposes from its own copies, set with the pattern: `0x4012b16e` takes the
entry's note (`%a3 +2`), adds the track's (`0x4461723c + 4 * track`) and, when
its PTN TRANSPOSE CONFIG copy (`0x44617234`) selects the track, the pattern's
(`0x44617238`), and `0x4012b1b0` checks 0..127. A live key's release
(`0x4012b362..0x4012b37c`) works out the note to turn off the same way, so a
transpose changed while the key is held leaves the old note on (stock does this
with its semitones; checked in the emulator).

The hooks replace both range checks' first 6 bytes, and `midi_degrees` moves the
note as the synth's is moved. A MIDI record's track is its `+8`; its `+44`
can be another track's playback copy (a layered note keeps its source's), so
the track's amount, scale and root are read from the current playback copy
(`0x42c5a9a0`) by the track, as stock keeps its MIDI transposes per track.

## The keys: pending while held, applied on release

The main screen's key handler (`0x4005ed12`, the view in `%a2`, the key event in
`%d2`: its key code at `+12`, and at `+16` flags whose bit 0 is set while the key
is pressed and bit 1 when [FUNC] came with it) dispatches on the key code. Stock's
transposes are pending in the view: [TRK] or [FUNC] pressed copies the track's
applied amount to `+536`; [+] (52) and [-] (54), at `0x4005fb62`, set the flag
`+545` and add 1 (12 with [FUNC] for an octave) through `0x4011f7e4(code)`, "is
that key held": [PTN] (23) held moves the pattern instead, else [TRK] (16) held or
[FUNC] with the key the track (`0x4005fbd0`); the release of [FUNC] (`0x4006067c`)
applies the amount and clears the flag.

This build keeps its own pending amount, a flag and a value with the track it is
for, in its code chunk:

- `0x4005fb76`, after [+]/[-]'s key code is read: with [KEYBOARD] (18) held and
  [TRK] held or [FUNC] with the key (stock's order), the key starts the pending
  amount from the applied one if none is pending, adds 1 or -1 within
  MAX_DEGREES, and leaves through stock's redraw (`0x4005fc24`), which marks the
  key used (`0x4005ef52`). Every other combination goes to stock: [KEYBOARD] not
  held, [PTN] held, [TRK] and [FUNC] together (the octave), or neither [TRK] nor
  [FUNC]. Stock's pending amounts are untouched.
- `0x4005ed2c`, at the head of the handler, after any key's code is read: the
  release of [FUNC], [TRK] or [KEYBOARD] applies the pending amount, then stock
  handles the key as before.

The active track is `0x40046bfe(*(view +152) + 48)`, as stock's own transpose
finds it (`0x4003efde`). The amount is read and written through the current
pattern's objects, as stock's transposes are: `0x4003efa8(project)` is the
pattern's and `0x4003b2ea(pattern, track)` a track's, and each object's vtable
`+40` gives its part of the pattern in RAM. After writing, this build calls the
stock setter of the same byte with the stock bits as they are, so the change is
announced as stock's own edits are.

## The display

Stock draws its two transposes in `0x4005c9f8(view, canvas, x, y)`: the
pattern's on the title bar, then, from `0x4005ca66`, the track's in the header of
the track box, where SYN is, cleared (`0x40114842(canvas, 1, 43, 13, 49, 0)`),
drawn as `%+d` in the small font (`0x44507eb8`) centred on x 7 (flags 2) and
inverted (mode -1). A pending amount is drawn only while the view's `+548` is 1;
a timer (`0x4005bcf6`) flips `+548` while a pending flag is set, and redraws,
which is the blink.

- `0x4005ca66`, where the track's part begins: this build draws the track box
  itself, then leaves through the routine's epilogue (`0x4005cb4a`). It shows, in
  order: stock's pending amount (blinking); this build's (blinking, with the
  degree mark); else the applied amounts, the degrees with the mark and the
  semitones as stock. A box that has both alternates between them, each shown
  for ALTERNATE_TICKS ticks of the timer.
- `0x4005beb6`, in the timer: this build's pending flag blinks as stock's do, and
  while the box alternates, every ALTERNATE_TICKS ticks it redraws.

## Where the amount lives

In the pattern, as stock's transpose is: each track of each pattern of each
project keeps its own, saved, loaded, copied and cleared with it. It is a signed
4-bit field in bits 2..5 of the track's byte `+1187` in RAM, bits stock's
converters drop. Its bits 0..1 are a stock setting (0..3; getter `0x40050430`,
setter `0x40050460`). Stored, the byte is the track's `+1176`, whose bit 7 is a
flag (`+1176` in RAM).

- Stock's load keeps bits 0..1 (`0x400de1ec`) and its save writes them back with
  bit 7, clearing bits 2..6 (`0x400de28c`). This build widens both masks to bits
  0..5.
- The getter masks the stock setting, and the setter keeps the degrees.
- The track default (`0x400e75a4`), which clearing a track or a pattern runs,
  keeps them, as it keeps the semitone transpose (`+1156`); stock's reset of that
  transpose (`0x400e7408`) resets them.

The range is MAX_DEGREES: 7 degrees reach every note of the longest scale (8
notes) up or down, and anything further is an octave, which stock's octave
gesture moves. Bit 6 stays unused.

The instrument's own saves leave these bits at 0: in a +Drive backup of seven
projects (2026-10-12), every track record that loads (version 2 or 3) has
`+1176` bits 2..6 clear. So a project saved before this build opens with no
degrees. Stock firmware, given a stored track byte with degrees in it, as this
build saves it (`scripts/emu_degreetranspose.py`'s `reload`), keeps bits 0..1
and plays the notes as recorded; its next save of that pattern writes bits 2..5
as 0, so the degrees are gone (`stock-load`).

The pending amount lives in the code chunk and is not saved.

## Code and RAM

One platform `CODE` chunk at `0x467b8000`, in the free run between lfolength's
code (`0x467b0000`, 260 B) and arpplocks (`0x467c0000`) (`docs/mod-memory-regions.md`).
Its pending state lives at the chunk's end.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from build_arpscale import MAIN_OS, STOCKS, assemble_stubs  # noqa: F401  (STOCKS: the generator's)
from build_scale_degrees import (BASE, HEADER, PLAYBACK, SCALE_CONTEXT, TRACK_STRIDE, degree_move, locate,
                                 resolve, scales)
from dnfw import osport
from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.mods import platform
from dnfw.patch.assemble import available

CODE_VA = 0x467B8000            # between lfolength's code (0x467b0000, 260 B) and arpplocks (0x467c0000)
MAX_DEGREES = 7                 # every degree of an 8-note scale, up or down; a signed 4-bit field

# Where the amount lives, in the pattern in RAM.
TRACK_FLAGS = 1187              # a track's byte: a stock setting in bits 0..1, its degrees in 2..5
TRACK_SHIFT, TRACK_MASK = 2, 0x3C
LIVE_TRANSPOSE = 1156           # a track's semitone transpose
PATTERN_OBJECT = 0x4003EFA8     # (project) -> the current pattern's object
TRACK_OF = 0x4003B2EA           # (pattern object, track) -> the track's object
STORAGE = 40                    # vtable slot: (object) -> its part of the pattern in RAM, or 0
FLAGS_SET = 0x40050460          # (track object, 0..3): the stock setting in TRACK_FLAGS, announced

# Stock's load and save of that byte, widened in place: (va, stock, new, why).
PATCHES = (
    (0x400DE1EC, bytes.fromhex("7203"), bytes.fromhex("723f"),
     "load: a stored track's +1176 bits 0..5 to +1187 (stock: bits 0..1)"),
    (0x400DE28C, bytes.fromhex("7403"), bytes.fromhex("743f"),
     "save: +1187 bits 0..5 to the stored track's +1176 (stock: bits 0..1)"),
)

# The stock setting's getter and setter, the track default, and the transpose's reset.
GET_SITE = 0x40050454
GET_DISPLACED = bytes.fromhex("102804a3" "6002")            # move.b 1187(%a0),%d0; bra.s 0x4005045c
GET_BACK = 0x4005045C
SET_SITE = 0x4005049C
SET_DISPLACED = bytes.fromhex("114104a3" "4def0010")        # move.b %d1,1187(%a0); lea 16(%sp),%fp
SET_BACK = 0x400504A4
DEFAULT_SITE = 0x400E75A4
DEFAULT_DISPLACED = bytes.fromhex("154104a3" "3540049d")    # move.b %d1,1187(%a2); move.w %d0,1181(%a2)
DEFAULT_BACK = 0x400E75AC
RESET_SITE = 0x400E7408
RESET_DISPLACED = bytes.fromhex("11400484" "700e")          # move.b %d0,1156(%a0); moveq #14,%d0
RESET_BACK = 0x400E740E
NOP = bytes.fromhex("4e71")

# The note's pitch, in the frame ISR.
VOICE_SITE = 0x400269A4
VOICE_DISPLACED = bytes.fromhex("727f" "c282" "b481")   # moveq #127,%d1; and.l %d2,%d1; cmp.l %d1,%d2
VOICE_BACK = 0x400269AA         # bne.w 0x40026ca0: out of 0..127, no voice

# A MIDI track's note, in the MIDI task: its note-on and a live key's release.
MIDI_ON_SITE = 0x4012B1B0
MIDI_ON_DISPLACED = bytes.fromhex("727f" "c280" "2841")    # moveq #127,%d1; and.l %d0,%d1; movea.l %d1,%a4
MIDI_ON_BACK = 0x4012B1B6       # cmp.l %d1,%d0; bne.w: out of 0..127, not sent
MIDI_OFF_SITE = 0x4012B37C
MIDI_OFF_DISPLACED = bytes.fromhex("7a7f" "ca80" "b085")   # moveq #127,%d5; and.l %d0,%d5; cmp.l %d5,%d0
MIDI_OFF_BACK = 0x4012B382      # beq.s: in 0..127, find it on its channels
MIDI_TRACK = 8                  # a MIDI record's track

# [+] and [-], in the main screen's key handler.
KEY_SITE = 0x4005FB76
KEY_DISPLACED = bytes.fromhex("49f9" "4011f7e4")       # lea 0x4011f7e4,%a4
KEY_BACK = 0x4005FB7C
KEY_DONE = 0x4005FC24           # redraw the view; the key is used
HELD = 0x4011F7E4               # (code) -> nonzero while that key is held
FUNC_WITH = 0x401160AC          # (event) -> nonzero when [FUNC] was held with it
ACTIVE_TRACK = 0x40046BFE       # (*(view + VIEW_PROJECT) + TRACK_FIELD) -> the active track
VIEW_PROJECT, TRACK_FIELD = 152, 48
KEYBOARD, PTN, FUNC, TRK, PLUS, MINUS = 18, 23, 17, 16, 52, 54

# Any key, at the head of the main screen's key handler: a release applies.
RELEASE_SITE = 0x4005ED2C
RELEASE_DISPLACED = bytes.fromhex("588f" "2800" "7035")   # addq.l #4,%sp; move.l %d0,%d4; moveq #53,%d0
RELEASE_BACK = 0x4005ED32
EVENT_PRESSED = 16 + 3          # the key event's flags, +16: bit 0 of its low byte while pressed
REDRAW = 0x4011C7BA             # (view): draw it again

# The track's transposition spot, in the main screen's drawing (0x4005c9f8).
DRAW_SITE = 0x4005CA66
DRAW_DISPLACED = bytes.fromhex("2f2a0098" "4eb94003efde")   # move.l 152(%a2),-(%sp); jsr 0x4003efde
DRAW_DONE = 0x4005CB4A          # the routine's epilogue
TEXT = 0x4011545C               # (canvas, font, x, y, flags, format, ...)
RECT = 0x40114842               # (canvas, x0, y0, x1, y1, mode): 0 clears, -1 inverts
SMALL_FONT = 0x44507EB8
TRACK_OBJECT = 0x4003EFDE       # (*(view + VIEW_PROJECT)) -> the active track's object
TRACK_TRANSPOSE = 0x40050A1E    # (track object) -> its transpose, in semitones
PENDING_TRACK = 536             # stock's pending track amount, in the view
PATTERN_PENDING, TRACK_PENDING = 544, 545   # stock's pending flags
BLINK = 548                     # 0 or 1: a pending amount is drawn only while 1
SEMITONES_FORMAT = 0x40215CCA   # "%+d"
DEGREE_MARK = "'"               # after a degree amount, to tell it from semitones

# The blink timer (0x4005bcf6), %a0 the view.
BLINK_SITE = 0x4005BEB6
BLINK_DISPLACED = bytes.fromhex("4a28" "0220" "6606")  # tst.b 544(%a0); bne.s 0x4005bec2
BLINK_FLIP = 0x4005BEC2         # flip +548, then redraw
BLINK_REDRAW = 0x4005BED0       # redraw
BLINK_LEAVE = 0x4005BEE0        # return
ALTERNATE_TICKS = 4             # timer ticks (about 0.23 s each) a value of an alternating box is shown

ALTERNATE_BIT = ALTERNATE_TICKS.bit_length() - 1
assert ALTERNATE_TICKS == 1 << ALTERNATE_BIT, "ALTERNATE_TICKS is a power of two"

LABELS = ("voice", "keys", "release", "draw", "blink", "flags_get", "flags_set", "flags_default",
          "transpose_reset", "midi_on", "midi_off")


def degrees_of(base: str, reg: str) -> str:
    """Assembly: the track's degrees, the signed 4-bit field in TRACK_FLAGS(BASE) -> REG."""
    return f"""    mvz.b   {TRACK_FLAGS}({base}),{reg}
    lsl.l   #{4 - TRACK_SHIFT},{reg}
    mvs.b   {reg},{reg}
    asr.l   #4,{reg}"""

SOURCE = """
| The note's pitch, after stock adds its transposes (0x400269a4), reached by jmp
| from the frame ISR. %d0 the entry's note (kept: the voice is found by it), %d2
| that note plus the transposes. Out: %d2 moved by the track's degrees, then the
| displaced range check, at 0x400269aa.
voice:
    lea     -44(%sp),%sp
    movem.l %d0/%d3-%d7/%a0-%a4,(%sp)
{locate("voice_done", OS)}
{degrees_of("%a3", "%d3")}
    move.l  %d3,%d1
    beq.w   voice_done
    sub.l   %d0,%d2                     | the transposes, in semitones
    move.l  %d2,-(%sp)
    move.l  %d1,%d2                     | the move, in degrees
{resolve("voice_semitones")}
{degree_move("voice", OS)}
    bra.s   2f
voice_semitones:
    add.l   %d2,%d0                     | no scale: a degree is a semitone
2:  move.l  (%sp)+,%d2
    add.l   %d0,%d2                     | the note moved, plus the transposes
voice_done:
    movem.l (%sp),%d0/%d3-%d7/%a0-%a4
    lea     44(%sp),%sp
    moveq   #127,%d1                    | the displaced instructions
    and.l   %d2,%d1
    cmp.l   %d1,%d2
    jmp     {VOICE_BACK:#x}

| A MIDI track's note-on, in the MIDI task (0x4012b1b0), reached by jmp, and a
| live key's release there (0x4012b37c), which finds the note to turn off the
| same way. Each moves %d0 by midi_degrees, then replays its range check.
midi_on:
    bsr.w   midi_degrees
    moveq   #127,%d1                    | the displaced instructions
    and.l   %d0,%d1
    movea.l %d1,%a4
    jmp     {MIDI_ON_BACK:#x}

midi_off:
    bsr.w   midi_degrees
    moveq   #127,%d5                    | the displaced instructions
    and.l   %d0,%d5
    cmp.l   %d5,%d0
    jmp     {MIDI_OFF_BACK:#x}

| %d0 the entry's note plus stock's transposes, %a2 the MIDI record, %a3 the
| entry. -> %d0 the entry's note moved by the track's degrees, plus the
| transposes. The amount and the scale are the track's in the current playback
| copy, found by the record's track (+8): a layered note's record keeps its
| source's +44, and stock's own MIDI transposes are per track too. Keeps every
| other register.
midi_degrees:
    lea     -48(%sp),%sp
    movem.l %d1-%d7/%a0-%a4,(%sp)
    move.l  %d0,%d2
    mvs.b   2(%a3),%d0                  | the entry's note
    sub.l   %d0,%d2                     | the transposes, in semitones
    move.l  %d2,-(%sp)
    move.l  {MIDI_TRACK}(%a2),%d1
    move.l  {PLAYBACK:#x},%d3
    beq.w   midi_keep
    move.l  %d3,%a4
    adda.l  #{HEADER:#x},%a4            | the header
    move.l  #{TRACK_STRIDE},%d4
    muls.l  %d1,%d4
    add.l   %d3,%d4
    move.l  %d4,%a3                     | the track's part
{degrees_of("%a3", "%d3")}
    move.l  %d3,%d2                     | the move, in degrees
    beq.w   midi_keep
{resolve("midi_semitones")}
{degree_move("midi", OS)}
    bra.s   midi_keep
midi_semitones:
    add.l   %d2,%d0                     | no scale: a degree is a semitone
midi_keep:
    add.l   (%sp)+,%d0                  | plus the transposes
    movem.l (%sp),%d1-%d7/%a0-%a4
    lea     48(%sp),%sp
    rts

| [+] or [-] in the main screen's key handler (0x4005fb76), reached by jmp. %d0
| the key, %d2 the key event, %a2 the view, and one long of stock's on the stack
| (the event, pushed at 0x4005fb72, popped at 0x4005fb94). %d5-%d7 and %a3 are
| the handler's, saved by its prologue and unused on this path.
keys:
    lea     {HELD:#x},%a4               | the displaced instruction
    move.l  %d0,%d6                     | the key
    pea     {KEYBOARD}
    jsr     (%a4)
    addq.l  #4,%sp
    tst.l   %d0
    beq.w   keys_stock                  | [KEYBOARD] not held: stock
    pea     {PTN}
    jsr     (%a4)
    addq.l  #4,%sp
    tst.l   %d0
    bne.w   keys_stock                  | [PTN] held: stock's pattern transpose
    move.l  %d2,-(%sp)
    jsr     {FUNC_WITH:#x}
    addq.l  #4,%sp
    move.b  %d0,%d5                     | [FUNC] with the key
    pea     {TRK}
    jsr     (%a4)
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   1f
    tst.b   %d5
    bne.w   keys_stock                  | [TRK] and [FUNC]: stock's octave
    bra.s   2f
1:  tst.b   %d5
    beq.w   keys_stock                  | neither [TRK] nor [FUNC]: stock
2:  move.l  {VIEW_PROJECT}(%a2),%a0     | the active track, as stock's own
    pea     {TRACK_FIELD}(%a0)          | transpose finds it (0x4003efde)
    jsr     {ACTIVE_TRACK:#x}
    addq.l  #4,%sp
    move.l  %d0,%d7
    lea     track_state,%a3
    bsr.w   track_applied               | its applied amount
    tst.b   (%a3)                       | not pending: start from the applied amount
    bne.s   3f
    move.b  %d0,1(%a3)
    move.b  %d7,2(%a3)                  | (the track it is for)
    move.b  #1,(%a3)
3:  mvs.b   1(%a3),%d5
    moveq   #1,%d0
    moveq   #{PLUS},%d1
    cmp.l   %d1,%d6
    beq.s   5f
    moveq   #-1,%d0
5:  add.l   %d0,%d5
    moveq   #{MAX_DEGREES},%d0
    cmp.l   %d0,%d5
    ble.s   6f
    move.l  %d0,%d5
6:  neg.l   %d0
    cmp.l   %d0,%d5
    bge.s   4f
    move.l  %d0,%d5
4:  move.b  %d5,1(%a3)
    addq.l  #4,%sp                      | stock's long (it pops it at 0x4005fb94)
    jmp     {KEY_DONE:#x}

keys_stock:
    move.l  %d6,%d0                     | the key, for stock
    jmp     {KEY_BACK:#x}

| Any key, at the head of the main screen's key handler (0x4005ed2c), reached by
| jmp. %d0 the key, %d2 the key event, %a2 the view, the code getter's argument
| still on the stack. The release of [FUNC], [TRK] or [KEYBOARD] applies the
| pending amount; then stock goes on.
release:
    addq.l  #4,%sp                      | the displaced instructions, the last
    move.l  %d0,%d4                     | (moveq #53,%d0) at the end
    move.l  %d2,%a0
    btst    #0,{EVENT_PRESSED}(%a0)
    bne.s   release_done                | pressed: nothing to apply
    moveq   #{FUNC},%d0
    cmp.l   %d0,%d4
    beq.s   1f
    moveq   #{TRK},%d0
    cmp.l   %d0,%d4
    beq.s   1f
    moveq   #{KEYBOARD},%d0
    cmp.l   %d0,%d4
    bne.s   release_done
1:  tst.b   track_state
    beq.s   release_done
    clr.b   track_state
    mvz.b   track_state+2,%d0
    mvs.b   track_state+1,%d1
    bsr.w   track_write
    move.l  %a2,-(%sp)
    jsr     {REDRAW:#x}
    addq.l  #4,%sp
release_done:
    moveq   #53,%d0
    jmp     {RELEASE_BACK:#x}

| The track's spot, in the main screen's drawing (0x4005ca66), reached by jmp
| after stock has drawn the pattern's. %a2 the view, %d2 the canvas. Leaves
| through the epilogue.
draw:
    lea     -12(%sp),%sp
    movem.l %d5-%d7,(%sp)
    clr.b   alternate
    move.l  {VIEW_PROJECT}(%a2),-(%sp)  | the displaced instructions
    jsr     {TRACK_OBJECT:#x}
    move.l  %d0,(%sp)
    jsr     {TRACK_TRANSPOSE:#x}
    mvs.b   %d0,%d5                     | its semitones, applied
    move.l  {VIEW_PROJECT}(%a2),%a0
    pea     {TRACK_FIELD}(%a0)
    jsr     {ACTIVE_TRACK:#x}
    addq.l  #8,%sp
    move.l  %d0,%d7
    bsr.w   track_applied               | ... and degrees
    move.l  %d0,%d6
    tst.b   {TRACK_PENDING}(%a2)
    beq.s   1f
    move.l  {PENDING_TRACK}(%a2),%d1    | stock's pending amount, blinking
    lea     {SEMITONES_FORMAT:#x},%a3
    bra.s   2f
1:  tst.b   track_state
    beq.s   3f
    mvz.b   track_state+2,%d0
    cmp.l   %d7,%d0
    bne.s   3f
    mvs.b   track_state+1,%d1           | this build's, blinking
    lea     degree_format,%a3
2:  tst.l   {BLINK}(%a2)
    bne.s   4f
    suba.l  %a3,%a3                     | the blink's off half: an empty box
    bra.s   4f
3:  bsr.w   choose                      | the applied amounts
    beq.s   9f
    move.l  %a0,%a3
4:  move.l  %d1,-(%sp)
    clr.l   -(%sp)                      | the box, cleared
    pea     49
    pea     13
    pea     43
    pea     1
    move.l  %d2,-(%sp)
    jsr     {RECT:#x}
    lea     24(%sp),%sp
    move.l  %a3,%d0
    beq.s   6f
    move.l  (%sp),-(%sp)                | the amount, centred on x 7
    move.l  %a3,-(%sp)
    pea     2
    pea     44
    pea     7
    pea     {SMALL_FONT:#x}
    move.l  %d2,-(%sp)
    jsr     {TEXT:#x}
    lea     28(%sp),%sp
6:  pea     -1                          | the box, inverted
    pea     49
    pea     13
    pea     43
    pea     1
    move.l  %d2,-(%sp)
    jsr     {RECT:#x}
    lea     28(%sp),%sp                 | and the amount
9:  movem.l (%sp),%d5-%d7
    lea     12(%sp),%sp
    jmp     {DRAW_DONE:#x}

| (%d5 semitones, %d6 degrees, applied) -> %d1 the amount to show and %a0 its
| format, Z clear; Z set when both are 0. Both set: they alternate, and the
| timer is told to redraw.
choose:
    tst.l   %d6
    beq.s   2f
    tst.l   %d5
    beq.s   1f
    moveq   #1,%d0
    move.b  %d0,alternate
    move.l  ticks,%d0
    btst    #{ALTERNATE_BIT},%d0
    bne.s   2f
1:  move.l  %d6,%d1
    lea     degree_format,%a0
    moveq   #1,%d0
    rts
2:  move.l  %d5,%d1
    lea     {SEMITONES_FORMAT:#x},%a0
    tst.l   %d5
    rts

| The blink timer (0x4005beb6), reached by jmp. %a0 the view. Stock's pending
| flags and this build's flip +548 and redraw; else, while the box alternates,
| every ALTERNATE_TICKS ticks it redraws.
blink:
    tst.b   {PATTERN_PENDING}(%a0)      | the displaced test, and the next
    bne.s   1f
    tst.b   {TRACK_PENDING}(%a0)
    bne.s   1f
    tst.b   track_state
    bne.s   1f
    clr.l   {BLINK}(%a0)
    tst.b   alternate
    beq.s   2f
    move.l  ticks,%d0
    addq.l  #1,%d0
    move.l  %d0,ticks
    andi.l  #{ALTERNATE_TICKS - 1},%d0
    bne.s   2f
    jmp     {BLINK_REDRAW:#x}
2:  jmp     {BLINK_LEAVE:#x}
1:  jmp     {BLINK_FLIP:#x}

| The stock setting's getter (0x40050454), reached by jmp. %a0 the track in RAM.
| -> its bits 0..1, without the degrees above them.
flags_get:
    mvz.b   {TRACK_FLAGS}(%a0),%d0
    moveq   #3,%d1
    and.l   %d1,%d0
    jmp     {GET_BACK:#x}

| Its setter (0x4005049c), reached by jmp. %a0 the track in RAM, %d1 the setting
| (0..3); %d2, saved by the setter, is free. The degrees are kept.
flags_set:
    mvz.b   {TRACK_FLAGS}(%a0),%d2
    andi.l  #{TRACK_MASK:#x},%d2
    or.l    %d2,%d1
    move.b  %d1,{TRACK_FLAGS}(%a0)
    lea     16(%sp),%fp                 | the second displaced instruction
    jmp     {SET_BACK:#x}

| The track default (0x400e75a4), which a clear runs, reached by jmp. %a2 the
| track in RAM, the setting's default (0) in %d1's low byte, %d0 127. The degrees
| are kept, as the semitone transpose is.
flags_default:
    move.l  %d2,-(%sp)
    mvz.b   {TRACK_FLAGS}(%a2),%d2
    andi.l  #{TRACK_MASK:#x},%d2
    or.l    %d1,%d2
    move.b  %d2,{TRACK_FLAGS}(%a2)
    move.l  (%sp)+,%d2
    move.w  %d0,1181(%a2)               | the second displaced instruction
    jmp     {DEFAULT_BACK:#x}

| Stock's reset of the semitone transpose (0x400e7408), reached by jmp. %a0 the
| track in RAM, %d0 0. The degrees are reset with it.
transpose_reset:
    move.b  %d0,{LIVE_TRANSPOSE}(%a0)
    mvz.b   {TRACK_FLAGS}(%a0),%d0
    andi.l  #{0xFF & ~TRACK_MASK:#x},%d0
    move.b  %d0,{TRACK_FLAGS}(%a0)
    moveq   #14,%d0                     | the second displaced instruction
    jmp     {RESET_BACK:#x}

| The amount in the current pattern, for the key handler and the drawing. Each
| takes %a2 the view, keeps %d2-%d7 and %a2-%a6 as stock's routines do, and uses
| %d0, %d1, %a0 and %a1.

| (%d0 a track) -> %d0 that track's object.
track_object:
    move.l  %d0,-(%sp)
    move.l  {VIEW_PROJECT}(%a2),-(%sp)
    jsr     {PATTERN_OBJECT:#x}
    move.l  %d0,(%sp)
    jsr     {TRACK_OF:#x}
    addq.l  #8,%sp
    rts

| (%d0 an object) -> %d0 its part of the pattern in RAM; Z set when it has none,
| which stock's getter and setter of the same byte read as 0 and as nothing to
| write (0x40050442, 0x40050478).
storage:
    move.l  %d0,-(%sp)
    move.l  %d0,%a0
    move.l  (%a0),%a0
    move.l  {STORAGE}(%a0),%a0
    jsr     (%a0)
    addq.l  #4,%sp
    tst.l   %d0
    rts

| (%d0 a track) -> %d0 its degrees.
track_applied:
    bsr.w   track_object
    bsr.w   storage
    beq.s   1f
    move.l  %d0,%a0
{degrees_of("%a0", "%d0")}
1:  rts

| (%d0 a track, %d1 degrees): written, then the stock setting set to itself
| (flags_set keeps the degrees), which announces the change.
track_write:
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    move.l  %d1,%d3
    bsr.w   track_object
    move.l  %d0,%d2                     | the track's object
    bsr.w   storage
    beq.s   1f
    move.l  %d0,%a0
    lsl.l   #{TRACK_SHIFT},%d3
    andi.l  #{TRACK_MASK:#x},%d3
    mvz.b   {TRACK_FLAGS}(%a0),%d0
    andi.l  #{0xFF & ~TRACK_MASK:#x},%d0
    or.l    %d3,%d0
    move.b  %d0,{TRACK_FLAGS}(%a0)
    moveq   #3,%d1
    and.l   %d1,%d0
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    jsr     {FLAGS_SET:#x}
    addq.l  #8,%sp
1:  movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts

degree_format:
    .asciz  "%+d{DEGREE_MARK}"

| Pending state, in RAM: a flag (1 while pending), the amount, and the track it
| is for.
    .align  4
ticks:
    .long   0
track_state:
    .byte   0, 0, 0
alternate:
    .byte   0
"""

# (va, stock bytes, label): each site becomes `jmp label`, then `nop`s to the end of
# the displaced instructions.
HOOKS = (
    (VOICE_SITE, VOICE_DISPLACED, "voice"),
    (KEY_SITE, KEY_DISPLACED, "keys"),
    (RELEASE_SITE, RELEASE_DISPLACED, "release"),
    (DRAW_SITE, DRAW_DISPLACED, "draw"),
    (BLINK_SITE, BLINK_DISPLACED, "blink"),
    (GET_SITE, GET_DISPLACED, "flags_get"),
    (SET_SITE, SET_DISPLACED, "flags_set"),
    (DEFAULT_SITE, DEFAULT_DISPLACED, "flags_default"),
    (RESET_SITE, RESET_DISPLACED, "transpose_reset"),
    (MIDI_ON_SITE, MIDI_ON_DISPLACED, "midi_on"),
    (MIDI_OFF_SITE, MIDI_OFF_DISPLACED, "midi_off"),
)

# Read, not written: the code the hooks rely on.
CONTEXT = SCALE_CONTEXT + (
    (0x40026986, bytes.fromhex("41f98000538075303801c285712a0002d4804a816708733980005380d481"),
     "the note: %d2 = the entry's note (%d0) + 0x80005381[track] + 0x80005380 if the mask selects it"),
    (VOICE_BACK, bytes.fromhex("660002f4"), "out of 0..127: no voice"),
    (0x400269B8, bytes.fromhex("48424242"), "%d2, the pitch, to the DSP as note << 16"),
    (0x400269E2, bytes.fromhex("2f002f034eb94002a6a2"), "the voice is allocated by %d0, the note as recorded"),
    (0x4005ED12, bytes.fromhex("4e56ff9848d73cfc242e000c4bf940116018246e00082f024e95"),
     "the key handler: %d2 the event, %a2 the view, the key code through %a5"),
    (RELEASE_BACK, bytes.fromhex("5384b0846500"), "... then the switch on the key code - 1"),
    (0x40116018, bytes.fromhex("206f00042028000c4e75"), "the event's key code is its +12"),
    (0x40116070, bytes.fromhex("206f00047001c0a800104e75"), "pressed: bit 0 of the event's +16"),
    (0x4006067C, bytes.fromhex("4a2a02216700f5ce"), "[FUNC]'s release, stock's pending track transpose (+545)"),
    (0x4005EDAA, bytes.fromhex("0e1e"), "the key switch: [+] (52) -> 0x4005fb62"),
    (0x4005EDAE, bytes.fromhex("0e1e"), "the key switch: [-] (54) -> 0x4005fb62"),
    (0x4005FB62, bytes.fromhex("2f024eb940116070588f4a006700f3e22f024e95"),
     "[+]/[-]: pressed (0x40116070), then the key code, with the event left on the stack"),
    (KEY_BACK, bytes.fromhex("47f9401160ac7234b28056c370017703868070172e804e94588f4a80"),
     "stock: +1 or -1, then held(23) through %a4, on the event's slot, popped after"),
    (0x4005FBD0, bytes.fromhex("487800104e94588f4a80671a"), "... then held(16): [TRK] moves the track"),
    (KEY_DONE, bytes.fromhex("2f0a4eb94011c7ba588f6000f322"), "redraw, then 0x4005ef52"),
    (0x4005EF52, bytes.fromhex("76016000"), "the key is used: %d3 = 1"),
    (0x40060300, bytes.fromhex("2f2a00984eb94003efde"), "stock's track transpose: its track from view +152"),
    (0x4003EFE2, bytes.fromhex("246f000c486a00304eb940046bfe"), "... the active track: 0x40046bfe(obj + 48)"),
    (0x4005C9F8, bytes.fromhex("4fefffec48d70c1c246f0018242f001c"),
     "the spots' routine: %d2-%d4/%a2-%a3 saved, %a2 the view, %d2 the canvas"),
    (0x4005CA70, bytes.fromhex("2f004eb940050a1e"), "the track's applied transpose, of the active track's object"),
    (0x4005CA80, bytes.fromhex("42a7487800314878000d4878002b487800012f0247f940114842"),
     "the track's box cleared: (1, 43, 13, 49)"),
    (0x4005CAA6, bytes.fromhex("2f2a0218487940215cca487800024878002c48780007487944507eb82f02"),
     "the track's amount: %+d centred on x 7, y 44"),
    (DRAW_DONE, bytes.fromhex("4cd70c1c4fef00144e75"), "the routine's epilogue"),
    (SEMITONES_FORMAT, bytes.fromhex("252b6400"), '"%+d"'),
    (0x4005BEB4, bytes.fromhex("2052"), "the timer: %a0 the view"),
    (0x4005BEBC, bytes.fromhex("4a280221671a"), "... a pending track transpose, or else"),
    (BLINK_FLIP, bytes.fromhex("2028022472015280c28021410224"), "... +548 flipped"),
    (BLINK_REDRAW, bytes.fromhex("2f520008245f4ef94011c7ba"), "... and the view redrawn"),
    (0x4005BEDC, bytes.fromhex("42a80224245f4e75"), "... else +548 cleared, no redraw"),
    (0x4003EFF0, bytes.fromhex("2f0a24004ebaffb22f022f004eb94003b2ea"),
     "the active track's object: 0x4003b2ea(0x4003efa8(project), track)"),
    (0x4003EFC8, bytes.fromhex("223c000009544c010800068000004414d0af00044e75"),
     "0x4003efa8: the current pattern's object, from the project"),
    (0x4003B2EA, bytes.fromhex("202f00086c0442806008720fb2806c02700f"), "0x4003b2ea: (pattern, track 0..15)"),
    (0x40050446, bytes.fromhex("20522f0a206800284e90588f2040"),
     "the stock setting's getter: the track in RAM through vtable +40, in %a0"),
    (GET_BACK, bytes.fromhex("245f4e75"), "... returns %d0"),
    (0x4005048C, bytes.fromhex("6c04428160087403b4816c0272032040"),
     "its setter: %d1 clamped to 0..3, %a0 the track in RAM; %d2 free"),
    (SET_BACK, bytes.fromhex("2d3c401de848"), "... then the change announced"),
    (0x400E7592, bytes.fromhex("42054201707f"), "the track default: %d1's low byte 0, %d0 127"),
    (DEFAULT_BACK, bytes.fromhex("3540049f"), "... then 1183"),
    (0x400E7406, bytes.fromhex("4200"), "the transpose's reset: %d0 0"),
    (RESET_BACK, bytes.fromhex("11400489"), "... then 1161"),
    (0x400DE1EE, bytes.fromhex("10290498c081114004a3"), "load: stored +1176, masked by %d1, to +1187"),
    (0x400DE32A, bytes.fromhex("122804a371280498ef88c282808113400498"),
     "save: (+1176 << 7) | (+1187 & %d2) to the stored +1176"),
    (FLAGS_SET, bytes.fromhex("4feffff048d74404246f0014"), "the stock setting's setter: (object, value)"),
    (0x4012AC34, bytes.fromhex("242a0008"), "the MIDI task: a record's track is its +8"),
    (0x4012B16E, bytes.fromhex("73f944617234712b0002226f003cc283d0b69c004a816706d0b944617238"),
     "note-on: %d0 = the entry's note (%a3 +2) + the track's MIDI transpose + the pattern's if selected"),
    (MIDI_ON_BACK, bytes.fromhex("b08166000152"), "... then 0..127, else not sent"),
    (0x4012B362, bytes.fromhex("73f944617234712b0002c284d0b62c004a816706d0b944617238"),
     "a live key's release: the note to turn off, worked out the same way"),
    (MIDI_OFF_BACK, bytes.fromhex("671c"), "... then, in 0..127, found on its channels"),
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
OUT = ROOT / "00_Resources/02_Builds/degreetranspose_DN2_1.11.syx"


def source(os: str = "1.11") -> str:
    """The routines for OS (issue #382): their stock addresses through `dnfw.osport`"""
    return osport.render(SOURCE, globals(), os)


def compose(stock: bytes, log=print, os: str = "1.11") -> dict:
    """Apply the build to a stock MAIN OS. -> {content, blob, labels}: the hooked
    image and the code, 4-padded, for a platform `CODE` chunk at CODE_VA.

    OS is STOCK's version (issue #382): every guard, hook and patch site goes
    through `dnfw.osport.site`."""
    def site(va, want, why):
        try:
            return osport.site(os, va, want, stock, BASE)
        except osport.NotPorted as exc:
            raise SystemExit(f"{why}: {exc}") from None
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)

    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        va, want = site(va, want, why)
        log(f"  {va:#010x}  {want.hex():<28}  {why}")
    log(f"  {len(scales(content, os))} scales, each holding its root, the two tables agreeing")

    log(f"part 2 -- the code, from {CODE_VA:#010x}")
    payload, at = assemble_stubs(source(os), CODE_VA, LABELS)
    blob = payload + bytes(-len(payload) % 4)
    log(f"  {len(payload)} bytes: " + ", ".join(f"{k} {v:#010x}" for k, v in at.items()))

    log("part 3 -- the hooks")
    for va, stock_bytes, label in HOOKS:
        va, stock_bytes = site(va, stock_bytes, label)
        new = bytes.fromhex("4ef9") + struct.pack(">I", at[label])
        new += NOP * ((len(stock_bytes) - len(new)) // len(NOP))
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  jmp {label}")

    log("part 4 -- stock's masks, widened")
    for va, stock_bytes, new, why in PATCHES:
        va, stock_bytes = site(va, stock_bytes, why)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {why}")

    return {"content": bytes(content), "blob": blob, "labels": at}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=pathlib.Path, default=OUT)
    a = p.parse_args()
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    built = compose(section.unpack())
    chunk = platform.area.CodeChunk(CODE_VA, built["blob"]).pack()
    content = platform.join(built["content"], [(platform.area.CODE, chunk)])

    print("part 5 -- repack")
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, content)
    a.out.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {a.out} ({a.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

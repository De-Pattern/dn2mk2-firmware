"""Arp offsets in scale: the arpeggiator's step offsets move by degrees of the track's scale.

    python scripts/build_arpscale.py [--out PATH]

Stock 1.11 adds each arp step's OFFSET in semitones, after the keyboard's SCALE
and ROOT have done their work, so an offset leaves the scale: in C major, E plus
2 plays F#. This build adds **SETTINGS > PERSONALIZE > ARP OFS IN SCALE**. Off
(the default, and what a fresh instrument reads) the arp is stock. On, a step's
offset counts degrees of the track's KEYBOARD SETUP scale from its root: in C
major, E plus 2 plays G, and plus 7 is the octave.

## The rule

For a held note and a step offset `k`:

1. `k = 0`: the held note, unchanged, as stock (even a note outside the scale).
2. Otherwise the note moves `k` degrees of the track's scale from its root
   (`scripts/build_scale_degrees.py`, "The move").
3. The arp's octave (RANGE) is added in semitones after, as stock.

Stock behaviour is kept whenever the scale says nothing about degrees (SCALE
CHROMATIC, MODE CHORD MEMORY), and for an arp step reached from anywhere but the
two stock callers (below). A note below 0 rests, as a stock offset's does.

## Steps in semitones

With the toggle on, a step can be **marked** to move in semitones, for an
accidental in an otherwise in-scale sequence. In the ARPEGGIATOR menu, `[UP]` on
an active step marks it, `[DOWN]` on a marked step clears the mark, and `[DOWN]`
again mutes the step as in stock; unmuting a step gives an unmarked one. The step
graph draws a marked step as a plus in the box where stock draws its square. With
the toggle off, the keys and the graph are stock's, the keys leave the marks as
they are, and every step moves in semitones, marked or not.

The marks are a sound's, as its offsets are: 16 bits, bit n for step n.

- **In RAM**, the sound's value slot 100 (`+0xDC`). No parameter is filed at
  slot 100 (`docs/parameter-set-tables.md` section 6), so nothing but this mod
  reads it for its value. Stock's copies of a whole sound (pattern and kit
  copies, preset copy) carry it, and initializing a sound (`0x400e7d4c`) writes
  every slot from its parameter's default, 0 for slot 100.
- **Stored**, bytes 242..243 of the 359-byte sound. Stock's load (`0x400dd1ea`)
  reads the value words at 28..241 and the bytes from 244, and clears slots
  0..100 first (`0x400dd24a`); its save (`0x400dd6a6`) zeroes 28..243
  (`0x400dd6ec`) and writes value words up to 241. So stock loads a sound with
  marks as it always did, and its next save clears them, as w-winter's Digitone
  II showed (`docs/flashing.md`, 2026-10-26). Older stored formats reach the
  load with zeros there: the format 0 upgrade writes 0 into bytes 238..243
  (`0x400e0fde`..`0x400e0fe6`), and the format 1 and 2 upgrades copy them
  (`0x400e0504`, `0x400e0596`). The load's and the save's last field copy, the
  step mask (`0x400dd5a0`, `0x400dd8c8`), each become `jmp` to a routine that
  also copies the marks.

The menu's code (`0x40019716`, the view's key handler, and the methods beside it
in its vtable `0x401d4c78`) reaches the arp only through calls, and seven of them
become calls of a routine that runs the stock one and then keeps the marks with
the steps:

| call | stock | the routine |
|---|---|---|
| `0x400197e8` | `setStepEnabled(model, step, up)`, for `[UP]`/`[DOWN]` | `step_key`: with the toggle on, `[UP]` on an active step marks it and `[DOWN]` on a marked one unmarks it; anything else is stock's mute or unmute, which leaves the step unmarked. With the toggle off, stock's call alone, and the marks stay as they are |
| `0x40019992` | `getMask(model)`, once in the rotate (`[FUNC]` + `[LEFT]`/`[RIGHT]`), after the offsets move and before the mask does | `rotate_marks`: the marks move the same way within LEN (`%d2` the key, `%d7` LEN - 1, the rotate's) |
| `0x4001949c` | `copy(model)` | `copy_marks`: the copy's marks |
| `0x400195dc` | `clear(model, 1)` | `clear_marks`: no marks; the undo's are the steps' before |
| `0x400196b2` | `paste(model)` | `paste_marks`: the copy's marks; the undo's are the steps' before |
| `0x400195aa`, `0x40019684` | `undo(model, kind)`, which a repeated clear or paste runs first | `undo_marks`: the undo's marks |

Stock keeps one copy and one undo record (slots 0 and 1 of the history object
`0x4018d6b2`), each a 28-byte object only copy, clear and paste build
(`0x4019986a`), so two words in the chunk follow them. Each routine acts only when
stock reports success, as the menu does.

The step graph's loop (`0x40018ad0`) draws an active step's box with
`0x40114842` (filled, for an offset of whole octaves) or `0x40114510` (hollow),
chosen at `0x40018b4a`; that choice becomes `jmp draw_step`.

In the arp step's tail, `%d3` is the step (`0x4002a388 adda.l %d3,%a1`), so the
sound is `%a1 - %d3`, and a marked step takes stock's sum.

## Where the step adds the offset (`docs/arp-hidden-modes.md`)

The step `0x4002a0bc(track, arp id)` ends, for every mode, in one tail:
`0x4002a38c mvs.b 358(%a1),%d2` (the step's offset), then `0x4002a390 add.l
%d1,%d0; add.l %d2,%d0; bra 0x4002a39c`. At `0x4002a390` `%d0` is the held
note, `%d1` 12 x the arp's octave and `%d2` the offset; `0x4002a39c` restores
`%d2-%d7/%a2-%a4` and returns `%d0`. Those six bytes become `jmp arp`. arpmodes
guards `0x4002a38c` and `0x4002a39a` and enters the tail at `0x4002a376`, so
its SHUF and RAND go through this hook too.

## Where the scale is

The step's two callers, `0x400266e0` and `0x4002686e`, are in the frame ISR
`0x40025e36`, which keeps its voice record at `-36(%fp)`; the step leaves `%a6`
alone and calls nothing. So when the step's return address is one of the two,
`build_scale_degrees.scale_lookup` finds the record's track's SCALE and ROOT in
the playing pattern (`scripts/build_scale_degrees.py`, "Where the scale is,
while the pattern plays").

## The toggle and the PERSONALIZE item

As reloadconfirm's (`scripts/build_reload_confirm.py`): one byte in the settings
block's unaddressed tail, saved and restored with the block, zero on a fresh
instrument, ignored by stock. reloadconfirm has `0x405cd8ae`; this is the next
byte, `0x405cd8af`. Only 1 means on. Written only through the stock setting
writer `0x400bb4f8`.

The item is `scripts/build_personalize_toggle.py`'s, as reloadconfirm's is,
appended from a different site, so the two mods do not hook the same bytes:
after the last stock item is appended, `0x40098630 jsr (%a3); move.l
%d3,-(%sp); jsr (%a3)`, three of the destructor calls, replayed unchanged.
reloadconfirm hooks the epilogue (`0x4009863e`) and guards `0x4009862c`, so
with both, RELOAD CONFIRM comes after this item.

## Code and RAM

One platform `CODE` chunk at `0x467a8000`, in the free run between arpmodes'
RAM (`0x467a0000`, 2,320 B) and `0x467b0000` (`docs/mod-memory-regions.md`),
holding the copy's and the undo record's marks after the code. No other RAM but
the toggle's byte; the marks themselves are in each sound.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.mods import platform
from dnfw.patch.assemble import assemble, available

import build_personalize_toggle as toggle
from build_scale_degrees import (BASE, SCALE_CONTEXT, degree_move, scale_lookup,
                                 scales)

MAIN_OS = 3

CODE_VA = 0x467A8000            # past arpmodes' RAM (0x467a0000, 2,320 B), below 0x467b0000
FLAG = 0x405CD8AF               # the toggle: reloadconfirm's 0x405cd8ae, plus one
SETTINGS = 0x405CD85C           # the settings block: FLAG is its byte +0x53, in the unaddressed tail

# The arp step's tail.
ARP_SITE = 0x4002A390
ARP_DISPLACED = bytes.fromhex("d081" "d082" "6006")   # add.l %d1,%d0; add.l %d2,%d0; bra 0x4002a39c
STEP_EXIT = 0x4002A39C          # restores the step's registers, returns %d0
CALLER_RETURNS = (0x400266E6, 0x40026874)    # after the two stock calls of the step
CALLER_RETURN_1, CALLER_RETURN_2 = CALLER_RETURNS   # named, so that `osport.render` moves them
STEP_FRAME = 36                 # the step's own frame: its return address is at 36(%sp)
MENU_SITE = 0x40098630          # PersonalizeMenuView's constructor, after the last stock append
MENU_DISPLACED = bytes.fromhex("4e93" "2f03" "4e93")  # jsr (%a3); move.l %d3,-(%sp); jsr (%a3)
MENU_BACK = MENU_SITE + len(MENU_DISPLACED)

NAME = "ARP OFS IN SCALE"       # 16 characters, as LIVE REC OVERDUB

# Steps in semitones: the marks, bit n for step n.
MARKS = 0xDC                    # a sound's value slot 100, which no parameter uses
STORED_MARKS = 242              # the stored sound's bytes 242..243, which stock zeroes on save
STEP_MASK, STORED_MASK = 356, 336
SOUND_OF = 40                   # the arp model's vtable: -> its sound
NOTIFY = 16                     # the arp model's vtable: (model, &event), after an edit
ARP_EDITED = 0x401DDDEC         # the event stock's step setters send

LOAD_SITE, SAVE_SITE = 0x400DD5A0, 0x400DD8C8
LOAD_DISPLACED = bytes.fromhex("356b01500164")      # move.w 336(%a3),356(%a2): the stored mask
SAVE_DISPLACED = bytes.fromhex("356b01640150")      # move.w 356(%a3),336(%a2)
DRAW_SITE = 0x40018B4A
DRAW_DISPLACED = bytes.fromhex("4a876612" "48780001")   # tst.l %d7; bne.s 0x40018b60; pea 1
DRAW_HOLLOW, DRAW_FILLED, DRAW_NEXT = 0x40018B60, 0x40018B52, 0x40018B90
SET_STEP, GET_MASK = 0x4004BD52, 0x4004BDE6
COPY, CLEAR, PASTE, UNDO = 0x4004CEC4, 0x4004D25E, 0x4004D3E0, 0x4004D108
KEY_LEFT = 13

LABELS = ("arp", "menu_hook", "load_marks", "save_marks", "step_key", "draw_step",
          "rotate_marks", "copy_marks", "clear_marks", "paste_marks", "undo_marks")



SOURCE = """
| The arp step's tail (0x4002a390), reached by jmp. %d0 the held note, %d1 12 x
| the arp's octave, %d2 the step's offset, %d3 the step, %a1 the sound + the
| step; out: %d0 the note, at 0x4002a39c, which restores %d2-%d7/%a2-%a4. %d0
| and %d1 are kept until stock is ruled out.
arp:
    tst.l   %d2
    beq.w   arp_stock                   | offset 0: the held note
    movea.l %a1,%a0
    suba.l  %d3,%a0                     | the sound
    move.w  {MARKS}(%a0),%d4
    btst    %d3,%d4
    bne.w   arp_stock                   | a marked step: semitones
    mvz.b   {FLAG:#x},%d3
    moveq   #1,%d4
    cmp.l   %d4,%d3
    bne.w   arp_stock                   | the toggle is off
    move.l  {STEP_FRAME}(%sp),%d3       | the step's caller: only the frame ISR's
    cmpi.l  #{CALLER_RETURN_1:#x},%d3 | two calls have the record at -36(%fp)
    beq.s   1f
    cmpi.l  #{CALLER_RETURN_2:#x},%d3
    bne.w   arp_stock
1:
{scale_lookup("arp_stock", OS)}
{degree_move("arp", OS)}
    add.l   %d1,%d0                     | the arp's octave
    jmp     {STEP_EXIT:#x}

arp_stock:
    add.l   %d1,%d0                     | the displaced instructions
    add.l   %d2,%d0
    jmp     {STEP_EXIT:#x}

| The stored sound's load (0x400dd1ea) at its step mask (0x400dd5a0) and the
| save (0x400dd6a6) at the same field (0x400dd8c8), reached by jmp. In the load
| %a3 is the stored sound and %a2 the one in RAM, in the save the other way.
load_marks:
    move.w  {STORED_MASK}(%a3),{STEP_MASK}(%a2)     | the displaced instruction
    move.w  {STORED_MARKS}(%a3),{MARKS}(%a2)
    jmp     {LOAD_SITE + 6:#x}

save_marks:
    move.w  {STEP_MASK}(%a3),{STORED_MASK}(%a2)     | the displaced instruction
    move.w  {MARKS}(%a3),{STORED_MARKS}(%a2)
    jmp     {SAVE_SITE + 6:#x}

| (model) -> %d0 its sound, 0 if none: the model's vtable +40. C convention.
sound_of:
    movea.l 4(%sp),%a0
    movea.l (%a0),%a1
    move.l  %a0,-(%sp)
    movea.l {SOUND_OF}(%a1),%a1
    jsr     (%a1)
    addq.l  #4,%sp
    rts

| (model): tell the model's listeners the arp changed, with the event stock's
| step setters send (0x4004bdba). C convention.
notify:
    lea     -8(%sp),%sp
    move.l  #{ARP_EDITED:#x},(%sp)
    move.b  #1,4(%sp)
    move.l  %sp,-(%sp)                  | &event
    move.l  16(%sp),-(%sp)              | the model
    movea.l (%sp),%a0
    movea.l (%a0),%a0
    movea.l {NOTIFY}(%a0),%a0
    jsr     (%a0)
    lea     16(%sp),%sp
    rts

| [UP]/[DOWN] on a step, called in place of the menu's setStepEnabled(model,
| step, up) (0x400197e8). With the toggle on, [UP] on an active step marks it
| and [DOWN] on a marked step clears the mark. Anything else is stock's mute or
| unmute, and leaves the step unmarked. With the toggle off, it is stock's call
| alone, and the marks stay as they are.
step_key:
    lea     -8(%sp),%sp
    movem.l %d2/%a2,(%sp)
    move.l  12(%sp),-(%sp)              | the model
    bsr.w   sound_of
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   8f
    movea.l %d0,%a2
    move.l  16(%sp),%d2                 | the step (0..15, the menu's)
    mvz.b   {FLAG:#x},%d0
    moveq   #1,%d1
    cmp.l   %d1,%d0
    bne.s   8f                          | the toggle is off: stock, the marks as they are
    tst.b   23(%sp)                     | up?
    beq.s   5f
    move.w  {STEP_MASK}(%a2),%d0
    btst    %d2,%d0
    beq.s   7f                          | a muted step: stock unmutes it
    move.w  {MARKS}(%a2),%d0
    bset    %d2,%d0
    bra.s   6f
5:  move.w  {MARKS}(%a2),%d0
    btst    %d2,%d0
    beq.s   7f                          | an unmarked step: stock mutes it
    bclr    %d2,%d0
6:  move.w  %d0,{MARKS}(%a2)
    move.l  12(%sp),-(%sp)
    bsr.w   notify
    addq.l  #4,%sp
    bra.s   9f
7:  move.w  {MARKS}(%a2),%d0
    bclr    %d2,%d0
    move.w  %d0,{MARKS}(%a2)
8:  move.l  20(%sp),-(%sp)              | stock: setStepEnabled(model, step, up)
    move.l  20(%sp),-(%sp)
    move.l  20(%sp),-(%sp)
    jsr     {SET_STEP:#x}
    lea     12(%sp),%sp
9:  movem.l (%sp),%d2/%a2
    lea     8(%sp),%sp
    rts

| The step graph, where stock chooses the filled square or the hollow one
| (0x40018b4a), reached by jmp. %d1, %a4, %a0, %a1 the step's box (x0, y0, x1,
| y1), %d2 the canvas, %d3 the model, %d4 the step, %a5 the box filler
| 0x40114842. With the toggle on, a marked step gets a plus in the box and the
| loop goes on at 0x40018b90; %d6, %d7, %a3 and %a4 are free there.
draw_step:
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    mvz.b   {FLAG:#x},%d0
    moveq   #1,%d1
    cmp.l   %d1,%d0
    bne.s   8f                          | the toggle is off
    move.l  %d3,-(%sp)
    bsr.w   sound_of
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   8f
    movea.l %d0,%a0
    move.w  {MARKS}(%a0),%d0
    btst    %d4,%d0
    beq.s   8f
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    move.l  %d1,%d6                     | x0
    move.l  %a0,%d7                     | x1
    movea.l %a1,%a3                     | y1; %a4 is y0
    move.l  %a4,%d0
    add.l   %a3,%d0
    asr.l   #1,%d0                      | the middle row
    pea     1                           | the row: (canvas, x0, y, x1, y, 1)
    move.l  %d0,-(%sp)
    move.l  %d7,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d2,-(%sp)
    jsr     (%a5)
    lea     24(%sp),%sp
    move.l  %d6,%d0
    add.l   %d7,%d0
    asr.l   #1,%d0                      | the middle column
    pea     1                           | the column: (canvas, x, y0, x, y1, 1)
    move.l  %a3,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %a4,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    jsr     (%a5)
    lea     24(%sp),%sp
    jmp     {DRAW_NEXT:#x}
8:  movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    tst.l   %d7                         | the displaced instructions
    beq.s   1f
    jmp     {DRAW_HOLLOW:#x}
1:  pea     1
    jmp     {DRAW_FILLED:#x}

| The rotate's getMask(model) (0x40019992), called after it moves the offsets
| and before it moves the mask: the marks move the same way, within LEN, then
| stock's getMask. The rotate's %d2 is the key, %d7 LEN - 1.
rotate_marks:
    lea     -16(%sp),%sp
    movem.l %d3-%d5/%a2,(%sp)
    move.l  20(%sp),-(%sp)              | the model
    bsr.w   sound_of
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   9f
    movea.l %d0,%a2
    moveq   #0,%d3
    move.w  {MARKS}(%a2),%d3
    moveq   #1,%d4
    lsl.l   %d7,%d4
    add.l   %d4,%d4
    subq.l  #1,%d4                      | the steps within LEN
    move.l  %d3,%d5
    and.l   %d4,%d5                     | their marks
    eor.l   %d5,%d3                     | the marks past LEN, kept
    moveq   #{KEY_LEFT},%d0
    cmp.l   %d2,%d0
    bne.s   2f
    moveq   #1,%d0                      | LEFT: step i takes step i + 1's mark
    and.l   %d5,%d0
    lsl.l   %d7,%d0                     | and the last takes the first's
    lsr.l   #1,%d5
    bra.s   3f
2:  move.l  %d5,%d0                     | RIGHT: step i takes step i - 1's mark
    lsr.l   %d7,%d0                     | and the first takes the last's
    add.l   %d5,%d5
    and.l   %d4,%d5
3:  or.l    %d0,%d5
    or.l    %d5,%d3
    move.w  %d3,{MARKS}(%a2)
9:  movem.l (%sp),%d3-%d5/%a2
    lea     16(%sp),%sp
    jmp     {GET_MASK:#x}

| The menu's copy(model), clear(model, 1), paste(model) and undo(model, kind),
| each called in place of stock's and acting only when stock's returns nonzero.
| They keep the copy's and the undo record's marks (clip, undone) with stock's.
copy_marks:
    move.l  4(%sp),-(%sp)
    jsr     {COPY:#x}
    addq.l  #4,%sp
    tst.b   %d0
    beq.s   9f
    move.l  %d0,-(%sp)
    move.l  8(%sp),-(%sp)
    bsr.w   sound_of
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   8f
    movea.l %d0,%a0
    lea     clip,%a1
    move.w  {MARKS}(%a0),(%a1)
8:  move.l  (%sp)+,%d0
9:  rts

clear_marks:
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     {CLEAR:#x}
    addq.l  #8,%sp
    tst.b   %d0
    beq.s   9f
    move.l  %d0,-(%sp)
    move.l  8(%sp),-(%sp)
    bsr.w   sound_of
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   8f
    movea.l %d0,%a0
    lea     undone,%a1
    move.w  {MARKS}(%a0),(%a1)          | stock's clear leaves them: the steps' before
    clr.w   {MARKS}(%a0)
8:  move.l  (%sp)+,%d0
9:  rts

paste_marks:
    move.l  4(%sp),-(%sp)
    jsr     {PASTE:#x}
    addq.l  #4,%sp
    tst.b   %d0
    beq.s   9f
    move.l  %d0,-(%sp)
    move.l  8(%sp),-(%sp)
    bsr.w   sound_of
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   8f
    movea.l %d0,%a0
    lea     undone,%a1
    move.w  {MARKS}(%a0),(%a1)          | stock's paste leaves them: the steps' before
    lea     clip,%a1
    move.w  (%a1),{MARKS}(%a0)
8:  move.l  (%sp)+,%d0
9:  rts

undo_marks:
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     {UNDO:#x}
    addq.l  #8,%sp
    tst.b   %d0
    beq.s   9f
    move.l  %d0,-(%sp)
    move.l  8(%sp),-(%sp)
    bsr.w   sound_of
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   8f
    movea.l %d0,%a0
    lea     undone,%a1
    move.w  (%a1),{MARKS}(%a0)
8:  move.l  (%sp)+,%d0
9:  rts

{toggle.routines(FLAG, OS)}
| PersonalizeMenuView's constructor, after its last stock item is appended,
| reached by jmp: the displaced destructor calls, then append this item. %a4 is
| the view; %a3 (the destructor) and %d6 are the constructor's, so kept.
menu_hook:
    jsr     (%a3)                       | the displaced instructions
    move.l  %d3,-(%sp)
    jsr     (%a3)
    lea     -8(%sp),%sp
    movem.l %d6/%a3,(%sp)
{toggle.append_item(OS)}
    movem.l (%sp),%d6/%a3
    lea     8(%sp),%sp
    jmp     {MENU_BACK:#x}

item_name:
    .asciz  "{NAME}"

| The copy's and the undo record's marks.
    .align  2
clip:
    .word   0
undone:
    .word   0
"""

JMP, JSR = bytes.fromhex("4ef9"), bytes.fromhex("4eb9")


def call(target: int) -> bytes:
    """The stock `jsr target` a call site holds"""
    return JSR + struct.pack(">I", target)


# (va, stock bytes, label, opcode): each site becomes `jmp label`, nop-padded, or
# a stock `jsr` becomes `jsr label`.
HOOKS = (
    (ARP_SITE, ARP_DISPLACED, "arp", JMP),
    (MENU_SITE, MENU_DISPLACED, "menu_hook", JMP),
    (LOAD_SITE, LOAD_DISPLACED, "load_marks", JMP),
    (SAVE_SITE, SAVE_DISPLACED, "save_marks", JMP),
    (DRAW_SITE, DRAW_DISPLACED, "draw_step", JMP),
    (0x400197E8, call(SET_STEP), "step_key", JSR),
    (0x40019992, call(GET_MASK), "rotate_marks", JSR),
    (0x4001949C, call(COPY), "copy_marks", JSR),
    (0x400195DC, call(CLEAR), "clear_marks", JSR),
    (0x400196B2, call(PASTE), "paste_marks", JSR),
    (0x400195AA, call(UNDO), "undo_marks", JSR),
    (0x40019684, call(UNDO), "undo_marks", JSR),
)

# Read, not written: the code the hooks rely on.
CONTEXT = (
    (0x4002A0BC, bytes.fromhex("4fefffdc48d71cfc"), "the step: a 36-byte frame, %d2-%d7/%a2-%a4 saved"),
    (0x4002A0F4, bytes.fromhex("22680020"), "the step: %a1 = its sound (+32)"),
    (0x4002A38C, bytes.fromhex("75290166"), "the step: %d2 = the step's offset (+358)"),
    (0x4002A37E, bytes.fromhex("2401e58a"), "the step: %d2 = octave x 4 ..."),
    (0x4002A386, bytes.fromhex("e989d3c39282"), "... %d1 = octave x 12"),
    (STEP_EXIT, bytes.fromhex("4cd71cfc4fef00244e75"), "the step's exit: restore, return %d0"),
    (0x400266D8, bytes.fromhex("2f2800602f2800104eb94002a0bc"),
     "the ISR's first call: step(record +16, record +96)"),
    (0x40026868, bytes.fromhex("2f052f2800104eb94002a0bc"), "the ISR's second call: step(record +16, ...)"),
    (0x400266C2, bytes.fromhex("206effdc"), "the first call's record: -36(%fp)"),
    (0x40026848, bytes.fromhex("206effdc"), "the second call's record: -36(%fp)"),
) + SCALE_CONTEXT + (
    (0x40098638, bytes.fromhex("4e932f044e93"),
     "constructor: the last destructor calls (reloadconfirm hooks the epilogue after them)"),
) + toggle.CONTEXT + (
    (0x4002A388, bytes.fromhex("d3c3"), "the step: %a1 = the sound + %d3, the step"),
    (0x400DD1EA, bytes.fromhex("4fefffe048d77c1c246f0024266f0028"),
     "the load: %a2 = the sound in RAM, %a3 = the stored one"),
    (0x400DD24A, bytes.fromhex("487800ca42a7486a0014"), "the load: clear the value slots 0..100"),
    (LOAD_SITE + 6, bytes.fromhex("48780010486b0152"), "the load, after the mask: the offsets"),
    (0x400DD6A6, bytes.fromhex("4fefffdc48d77c3c246f0028266f002c"),
     "the save: %a2 = the stored sound, %a3 = the one in RAM"),
    (0x400DD6EC, bytes.fromhex("487800d842a7486a001c"), "the save: zero the stored bytes 28..243"),
    (SAVE_SITE + 6, bytes.fromhex("48780010486b0166"), "the save, after the mask: the offsets"),
    (0x4004BD24, bytes.fromhex("20680028"), "isStepEnabled: the model's sound, vtable +40"),
    (0x4004BD52, bytes.fromhex("4e56ffec48d7040c162e0013"), "setStepEnabled: up = the third argument's low byte"),
    (0x4004BD98, bytes.fromhex("34280164"), "setStepEnabled: the step mask, +356"),
    (0x4004BDBA, bytes.fromhex("203c401dddec"), "setStepEnabled: the event it sends"),
    (0x4004BDD0, bytes.fromhex("20680010"), "setStepEnabled: the model's notify, vtable +16"),
    (0x400197D6, bytes.fromhex("720bb28057c071004480" "2f002f2a022c2f02"),
     "the keys: up = (key == UP), the step at view +556, the model in %d2"),
    (0x40018ACA, bytes.fromhex("4bf940114842"), "the step graph: %a5 = the box filler"),
    (0x40018AD8, bytes.fromhex("2f042f034eb94004bd06"), "the step graph: step %d4 of model %d3"),
    (0x40018B32, bytes.fromhex("43f4b80099cb"), "the step graph: %a1 = y + h, %a4 = y - h"),
    (0x40018B3E, bytes.fromhex("206f0034d1cb222f0034928b"), "the step graph: %a0 = x + h, %d1 = x - h"),
    (DRAW_FILLED, bytes.fromhex("2f092f082f0c2f012f024e95"), "the step graph: the filled box, after its pea 1"),
    (DRAW_HOLLOW, bytes.fromhex("48780001" "2f092f082f0c2f012f024e96"), "the step graph: the hollow box"),
    (DRAW_NEXT, bytes.fromhex("71af003b"), "the step graph: the next part, the LEN row"),
    (0x40019884, bytes.fromhex("4eb94004bba0"), "the rotate: LEN - 1 ..."),
    (0x4001989E, bytes.fromhex("2e00"), "... in %d7"),
    (0x400199A2, bytes.fromhex("700db0826706"), "the rotate: %d2 the key, LEFT 13"),
    (0x400195D6, bytes.fromhex("487800012f00"), "the menu's clear: clear(model, 1)"),
    (0x4004CEE0, call(0x4019986A), "copy builds the 28-byte arp object"),
    (0x4004D282, call(0x4019986A), "clear builds one, the undo record"),
    (0x4004D400, call(0x4019986A), "paste builds one, the undo record"),
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
STOCKS = {"1.11": "00_Firmware/Digitone_II_OS1.11_dist.zip",       # under 00_Resources (issue #382)
          "1.12": "00_Firmware/Digitone_II_OS1.12.syx"}


def overrides(os: str) -> dict:
    """What the map cannot place: FLAG, which no instruction names, moves with the settings block,
    and MENU_BACK is the hooked site's next instruction"""
    return {"FLAG": osport.addr(os, SETTINGS) + (FLAG - SETTINGS),
            "MENU_BACK": osport.addr(os, MENU_SITE) + len(MENU_DISPLACED)}


def source(os: str = "1.11") -> str:
    """The routines for OS (issue #382): their stock addresses through `dnfw.osport`"""
    return osport.render(SOURCE, globals(), os, None if os == "1.11" else overrides(os))
OUT = ROOT / "00_Resources/02_Builds/arpscale_DN2_1.11.syx"


def assemble_stubs(source: str, base: int, labels: tuple[str, ...]) -> tuple[bytes, dict[str, int]]:
    """Assemble once and read each of LABELS' addresses off a trailing table."""
    table = "\n".join(f"    .long {name}" for name in labels)
    blob = assemble(source + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(labels)
    addrs = struct.unpack(">%dI" % len(labels), blob[-width:])
    return blob[:-width], dict(zip(labels, addrs))


def compose(stock: bytes, log=print, os: str = "1.11") -> dict:
    """Apply the build to a stock MAIN OS. -> {content, blob, labels, flag}: the hooked
    image and the code, 4-padded, for a platform `CODE` chunk at CODE_VA.

    OS is STOCK's version (issue #382): every guard and hook site goes through
    `dnfw.osport.site`, and the toggle's byte moves with the settings block."""
    def site(va, want, why):
        try:
            return osport.site(os, va, want, stock, BASE)
        except osport.NotPorted as exc:
            raise SystemExit(f"{why}: {exc}") from None
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)
    flag = FLAG if os == "1.11" else overrides(os)["FLAG"]
    if flag - BASE < len(content) and content[flag - BASE]:
        raise SystemExit("the toggle's byte is not zero in the image")

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
    for va, stock_bytes, label, opcode in HOOKS:
        va, stock_bytes = site(va, stock_bytes, label)
        new = opcode + struct.pack(">I", at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {'jmp' if opcode == JMP else 'jsr'} {label}")

    return {"content": bytes(content), "blob": blob, "labels": at, "flag": flag}


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

    print("part 4 -- repack")
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, content)
    a.out.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {a.out} ({a.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

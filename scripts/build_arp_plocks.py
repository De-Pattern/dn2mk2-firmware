"""P-locks for the arpeggiator: every ARPEGGIATOR setting, per trig.

    python scripts/build_arp_plocks.py

Writes `00_Resources/02_Builds/arp-plocks_DN2_1.11.syx`. `docs/ideas-backlog.md`
section 18 has the history; the design, as of 2026-09-19:

## Where a lock lives

A pattern holds 80 lock records, `{id, track, u16[128]}`, shared by all tracks.
Stock records name one of 101 per-track mirror slots and are found through a
track x slot index; there is no free slot for 23 arp settings. So an arp lock is
a record of its own, which the stock index never sees:

| k | setting | sound byte | range | stored id |
|---|---|---|---|---|
| 0 | MODE | 351 | 0..4 | 107 |
| 1 | RNG | 353 | 0..7 | 108 |
| 2 | SPEED | 352 | 0..22 | 109 |
| 3 | N.LEN | 354 | 0..127 | 110 |
| 4 | LEN | 355 | 0..15 | 111 |
| 5 + n | offset of arp step n | 358 + n | -64..63 | 112 + n |
| 21 / 22 | step mask, low / high byte | 357 / 356 | bits | 128 / 129 |

In RAM its header is `(k, track | 0x20)`. Every stock loop that looks a record
up by track (0..15) -- recording, clearing, the index, the note's lock list --
passes over it. Saved as `(107 + k, track)`; the pattern load turns it back.
Values sit in the low byte (`00vv`), so the recount's "negative is no lock"
never trips.

## How it reaches the arp

The lock-list builder (`0x400d85e8`) runs for every note (its `beq` past, when
the step has no stock lock, is a `nop`); `build_hook` wraps it and leaves the
step's arp locks past the list's stock entries (a mask at +828, a byte per k
from +832; the pool allocates 202 entries of which stock uses at most 101).
The note set's hook (`0x40026762`) copies the sound into a per-track shadow
(16 x 1,164 bytes at `0x467c0000`), writes the locked bytes and hands the note
set the shadow, in the argument (the arp step reads MODE, RNG, LEN, the mask and
the offsets from it) and in d2 (the caller files d2 in the per-track table
`0x4058e8d8` that the ISR reads SPEED and N.LEN from).

## Recording and the screen

In the ARPEGGIATOR menu, with a trig held: the setters' calls go to `ui_*`,
which lock (lock, or the sound's value, + the knob's delta) on every held step
and run the stock recount so the trig blinks; UP/DOWN on an arp step locks the
mask. The draw's getters go to `disp_*`: the first held step's lock if it has
one, shown inverted for the four top values. No trig held: all stock.

## Limits

- Removing a trig leaves its arp locks; copy/paste of whole pages or tracks
  may not carry them (copying trigs does, owner 2026-09-19).
- The cave at `0x402dfa1c` is the boot screen's too.
"""

from __future__ import annotations

import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400
SHADOW = 0x467C0000                     # 16 x SHADOW_STRIDE, above BSS
SOUND_STRIDE = 1163
SHADOW_STRIDE = 1164                    # word-aligned per track

# The arp settings, k in order: (name, sound byte, lo, hi).
PARAMS = ([("MODE", 351, 0, 4), ("RNG", 353, 0, 7), ("SPEED", 352, 0, 22),
           ("N.LEN", 354, 0, 127), ("LEN", 355, 0, 15)]
          + [(f"OFFSET{n + 1}", 358 + n, -64, 63) for n in range(16)]
          + [("MASK_LO", 357, 0, 255), ("MASK_HI", 356, 0, 255)])
K_MODE, K_RNG, K_SPD, K_NLEN, K_LEN, K_OFF, K_MASK = 0, 1, 2, 3, 4, 5, 21
EXT_COUNT = len(PARAMS)                 # 23
ID_FIRST = 107                          # stored id = 107 + k; MODE / RNG kept theirs
EXT_TAG = 0x20                          # RAM track byte = track | EXT_TAG
EXT_MASK, EXT_VALUES = 828, 832         # a lock list: 20 + 101 x 8 stock, 202 allocated
SOUND_BASE = 350                        # the byte table below is offset from here
OFF_FLAG = 1                            # a descriptor's k takes the arp step argument

# The stock code this hooks into.
ID_TO_SLOT = 0x400DCCC0                 # (table, id) -> slot
NOTE_SET = 0x40029CD4
NOTE_SET_CALL = 0x40026762
BUILD = 0x400D85E8                      # lock-list builder (track, list, table, ?, step)
BUILD_GATE = 0x400D89B0                 # `beq` past it when the step has no stock lock
RECOUNT = 0x4003CE3C                    # (model, track, step): lock count, the blink
RECOUNT_MATCH = 0x4003CE9E              # its `mvs.b rec+1, d0; cmp.l d0, d3`
SAVE_REC = 0x400DE75E                   # pattern save: inline slot -> id, 18 bytes
LOAD_MAX = 0x400DE594                   # pattern load: `moveq #106` bounds the id
LOAD_INDEX = 0x400DE5E6                 # pattern load: the index byte, 16 bytes

# Recording, read 2026-09-18 by recording a real p-lock under the emulator.
APP = 0x4018A97A               # the app singleton
TRACK_CTX = 0x4003EFDE         # (app) -> the active track's context
PATTERN_LEN = 0x4004F896       # (ctx) -> steps
CTX_MODEL, CTX_TRACK = 44, 60  # the context's pattern model and track
HELD = 0x446478C8              # the held-trig object
HELD_BITS, HELD_ANY = 600, 616 # its 128-bit held-step set, and "any held"
BIT_TEST = 0x4019C40C          # (bits, step) -> bool

# ArpSetupMenuView: the setters its edits call, and where.
SET_MODE, SET_RNG, SET_SPD = 0x4004BEA4, 0x4004C0DA, 0x4004C03C
SET_NLEN, SET_LEN, SET_OFF, SET_MASK = 0x4004C178, 0x4004BBD0, 0x4004BC84, 0x4004BD52
EDITS = (  # (va, setter, label, descriptor k / flags)
    (0x40018EEE, SET_MODE, "ui_mode", K_MODE, 0),
    (0x40018FBE, SET_RNG, "ui_rng", K_RNG, 0),
    (0x40018F56, SET_SPD, "ui_spd", K_SPD, 0),
    (0x40019026, SET_NLEN, "ui_nlen", K_NLEN, 0),
    (0x4001910C, SET_LEN, "ui_len", K_LEN, 0),
    (0x400190AE, SET_OFF, "ui_off", K_OFF, OFF_FLAG),   # (model, arp step, value)
)
MASK_EDIT = 0x400197E8         # UP / DOWN on an arp step: setStepOn(model, step, on)
# ... and the getters its draw calls.
GET_MODE, GET_RNG, GET_SPD, GET_NLEN = 0x4004BE74, 0x4004C0AA, 0x4004C00C, 0x4004C148
GET_LEN, GET_OFF, GET_STEP_ON = 0x4004BBA0, 0x4004BC3C, 0x4004BD06
DRAWS = (  # (va, stock getter, how it is reached, label)
    (0x400188DE, GET_MODE, "jsr", "disp_mode"),
    (0x40018972, GET_RNG, "jsr", "disp_rng"),
    (0x40018928, GET_SPD, "jsr", "disp_spd"),
    (0x400189BE, GET_NLEN, "jsr", "disp_nlen"),
    (0x40018A2E, GET_LEN, "jsr", "disp_len"),
    (0x40018832, GET_OFF, "lea_a4", "disp_off"),     # the bars' scale loop
    (0x40018A98, GET_OFF, "lea_a4", "disp_off"),     # the sixteen bars
    (0x40018B2A, GET_OFF, "jsr", "disp_off"),        # a bar's height
    (0x40018C72, GET_OFF, "jsr", "disp_off"),        # the selected step's value
    (0x40018A26, GET_STEP_ON, "lea_a3", "disp_mask"),
    (0x40018ADC, GET_STEP_ON, "jsr", "disp_mask"),
)
FLAGS_PLAIN, FLAGS_LOCKED = 2, 10  # text draw 0x4011545c: 2 centred, 8 inverts the box
TEXT_FLAGS = (0x400188F0, 0x40018986, 0x4001893A, 0x400189D4)  # `pea 2`: MODE RNG SPD N.LEN


def desc(k: int, flags: int = 0) -> int:
    """A hook's descriptor word: flags, k, then the value's signed bounds."""
    _, _, lo, hi = PARAMS[k]
    return (flags << 24) | (k << 16) | ((lo & 0xFF) << 8) | (hi & 0xFF)


OFFSETS = ", ".join(str(byte - SOUND_BASE) for _, byte, _, _ in PARAMS)

# ---------------------------------------------------------------------------
# The caves, assembled in this order. A later cave calls an earlier one's
# routines as `@name@`, replaced by its address before assembling.
CAVE_LOOK = (0x40295698, 203)          # dnfw cave scan: clean, no code reference
CAVE_CORE = (0x402DFA1C, 896)          # clean; the boot screen's too: not combinable yet
CAVE_UI = (0x402CF560, 844)            # LFO Waves' run past its stub (ends 0x402cf55a)

LOOK = f"""
| Pattern load, lock id -> slot, (table, id). An arp lock: 0x80 | k, which
| idx_hook turns into its header. Table 16 and every other id: stock.
load_hook:
    move.l  %sp@(4),%d1
    moveq   #16,%d0
    cmp.l   %d1,%d0
    beq.s   2f
    move.l  %sp@(8),%d0
    subi.l  #{ID_FIRST},%d0
    bcs.s   2f
    moveq   #{EXT_COUNT},%d1
    cmp.l   %d1,%d0
    bcc.s   2f
    ori.l   #0x80,%d0
    rts
2:  move.l  %d2,%sp@-                   | the stock entry, replayed
    moveq   #16,%d2
    move.l  %sp@(8),%d1
    jmp     {ID_TO_SLOT + 8:#010x}

| Pattern load, after the header and step copy (d0 the slot, d4 the track, d2
| the record, a3 it in RAM): an arp lock gets header (k, track | {EXT_TAG:#x}) and
| no index byte; a stock one its index byte as before.
idx_hook:
    btst    #7,%d0
    beq.s   1f
    andi.l  #0x7f,%d0
    move.b  %d0,%a3@
    move.b  %a3@(1),%d1
    ori.l   #{EXT_TAG},%d1
    move.b  %d1,%a3@(1)
    rts
1:  moveq   #101,%d1
    muls.l  %d1,%d4
    lea     %a2@(0,%d4:l),%a0
    adda.l  %d0,%a0
    move.b  %d2,%a0@(20640)
    rts

| Pattern save, the inline slot -> id of its record loop (d1 the slot, d3 the
| track byte, d2 it raw, a0 the stored record, a3 / a4 the stock tables): an
| arp lock is stored (107 + k, track).
save_rec:
    btst    #5,%d3
    beq.s   9f
    moveq   #{ID_FIRST},%d4
    add.l   %d4,%d1
    andi.l  #0x1f,%d2
    bra.s   3f
9:  moveq   #16,%d4
    cmp.l   %d3,%d4
    bne.s   4f
    move.l  %a4@(0,%d1:l:4),%d1
    bra.s   3f
4:  move.l  %a3@(0,%d1:l:4),%d1
3:  move.b  %d1,%a0@
    rts

| The recount's record match: the tag cleared, so arp locks make a trig blink.
trk_cmp:
    mvs.b   %a3@(1,%d0:l),%d0
    bclr    #5,%d0
    cmp.l   %d0,%d3
    rts
"""
LOOK_LABELS = ("load_hook", "idx_hook", "save_rec", "trk_cmp")

CORE = f"""
| The note set, (track, ..., sound at +32, ...): a note with arp locks plays a
| per-track shadow of its sound carrying them.
note_hook:
    move.l  %fp@(-36),%a0               | the ISR's note record
    move.l  %a0@(84),%d0                | its lock list
    beq.s   9f
    lea     %sp@(-12),%sp
    moveml  %d4/%a2-%a3,%sp@            | track +16, sound +44
    movea.l %d0,%a3
    move.l  %a3@({EXT_MASK}),%d4
    beq.s   8f
    move.l  %sp@(16),%d0
    muls.w  #{SHADOW_STRIDE},%d0
    addi.l  #{SHADOW:#010x},%d0
    movea.l %d0,%a2                     | the shadow
    movea.l %sp@(44),%a0
    movea.l %a2,%a1
    move.l  #{SOUND_STRIDE},%d1
1:  move.b  %a0@+,%a1@+
    subq.l  #1,%d1
    bne.s   1b
    lea     %a3@({EXT_VALUES}),%a1
    moveq   #0,%d1
2:  btst    %d1,%d4
    beq.s   3f
    move.l  %d1,%d0
    bsr     sound_off
    movea.l %a2,%a0
    adda.l  %d0,%a0
    move.b  %a1@(0,%d1:l),%a0@
3:  addq.l  #1,%d1
    moveq   #{EXT_COUNT},%d0
    cmp.l   %d0,%d1
    blt.s   2b
    move.l  %a2,%sp@(44)
8:  moveml  %sp@,%d4/%a2-%a3
    lea     %sp@(12),%sp
9:  move.l  %sp@(32),%d2                | the caller files d2 in 0x4058e8d8 (SPD, N.LEN)
    jmp     {NOTE_SET:#010x}

| The lock-list builder, then this step's arp locks into the list's spare half.
build_hook:
    move.l  %sp@(20),%sp@-
    move.l  %sp@(20),%sp@-
    move.l  %sp@(20),%sp@-
    move.l  %sp@(20),%sp@-
    move.l  %sp@(20),%sp@-
    jsr     build_stock
    lea     %sp@(20),%sp
    lea     %sp@(-20),%sp
    moveml  %d2-%d5/%a2,%sp@            | track +24, list +28, table +32, step +40
    movea.l %sp@(28),%a2
    moveq   #0,%d5
    move.l  %sp@(24),%d2
    ori.l   #{EXT_TAG},%d2
    move.l  %sp@(40),%d3
    add.l   %d3,%d3
    movea.l %sp@(32),%a0
    lea     %a2@({EXT_VALUES}),%a1
    moveq   #80,%d1
1:  move.b  %a0@(1),%d0
    cmp.b   %d2,%d0
    bne.s   2f
    moveq   #0,%d0
    move.b  %a0@,%d0
    moveq   #{EXT_COUNT},%d4
    cmp.l   %d4,%d0
    bcc.s   2f
    mvz.w   %a0@(2,%d3:l),%d4
    cmpi.l  #0xffff,%d4
    beq.s   2f
    bset    %d0,%d5
    move.b  %d4,%a1@(0,%d0:l)
2:  lea     %a0@(258),%a0
    subq.l  #1,%d1
    bne.s   1b
    move.l  %d5,%a2@({EXT_MASK})
    moveml  %sp@,%d2-%d5/%a2
    lea     %sp@(20),%sp
    rts
build_stock:
    lea     %sp@(-24),%sp
    moveq   #101,%d0
    jmp     {BUILD + 6:#010x}

| k -> its byte in the sound. In and out d0 only.
sound_off:
    move.l  %a0,%sp@-
    lea     %pc@(offsets),%a0
    move.b  %a0@(0,%d0:l),%d0
    andi.l  #0xff,%d0
    addi.l  #{SOUND_BASE},%d0
    movea.l %sp@+,%a0
    rts
offsets:
    .byte   {OFFSETS}
    .align  2

| A trig held? d0 1 with a3 the held object, a2 the track context, d3 the
| pattern length; else 0. Z follows d0.
held_ctx:
    move.l  {HELD:#010x},%d0
    beq.s   9f
    movea.l %d0,%a3
    tst.b   %a3@({HELD_ANY})
    beq.s   9f
    jsr     {APP:#010x}
    move.l  %d0,%sp@-
    jsr     {TRACK_CTX:#010x}
    addq.l  #4,%sp
    movea.l %d0,%a2
    move.l  %a2,%sp@-
    jsr     {PATTERN_LEN:#010x}
    addq.l  #4,%sp
    move.l  %d0,%d3
    moveq   #1,%d0
    rts
9:  moveq   #0,%d0
    rts

| The first held step at or after d2 -> d2; Z set when none (d2 = d3).
next_held:
1:  cmp.l   %d3,%d2
    bge.s   9f
    move.l  %d2,%sp@-
    pea     %a3@({HELD_BITS})
    jsr     {BIT_TEST:#010x}
    addq.l  #8,%sp
    tst.b   %d0
    bne.s   8f
    addq.l  #1,%d2
    bra.s   1b
8:  moveq   #1,%d0
    rts
9:  moveq   #0,%d0
    rts

| a2's pattern lock table -> a0.
ctx_table:
    movea.l %a2@({CTX_MODEL}),%a0
    move.l  %a0,%sp@-
    movea.l %a0@,%a1
    movea.l %a1@(40),%a1
    jsr     %a1@
    addq.l  #4,%sp
    movea.l %d0,%a0
    rts

| Model a0 -> its sound (vt[40]) in a1 and d0, 0 if none; Z follows.
model_sound:
    move.l  %a0,%sp@-
    movea.l %a0@,%a1
    movea.l %a1@(40),%a1
    jsr     %a1@
    addq.l  #4,%sp
    movea.l %d0,%a1
    tst.l   %d0
    rts

| Table a0, header word d1 -> the record in a1 and d0, 0 if none.
ext_find:
    movea.l %a0,%a1
    moveq   #80,%d0
1:  cmp.w   %a1@,%d1
    beq.s   2f
    lea     %a1@(258),%a1
    subq.l  #1,%d0
    bne.s   1b
    suba.l  %a1,%a1
2:  move.l  %a1,%d0
    rts

| Table a0, header word d1, step d2 -> the lock's byte (0..255) in d0, or -1.
ext_get:
    bsr.s   ext_find
    beq.s   1f
    move.l  %d2,%d0
    add.l   %d0,%d0
    mvz.w   %a1@(2,%d0:l),%d0
    cmpi.l  #0xffff,%d0
    bne.s   2f
1:  moveq   #-1,%d0
2:  rts

| Table a0, header word d1, step d2: lock byte d0 there, claiming a free record
| (header 0xff) if the parameter has none. Keeps d1-d7 / a0.
ext_put:
    move.l  %d3,%sp@-
    move.l  %d0,%d3                     | the value
    bsr.s   ext_find
    bne.s   2f
    move.l  %d4,%sp@-
    movea.l %a0,%a1
    moveq   #80,%d0
1:  mvs.b   %a1@,%d4
    addq.l  #1,%d4
    beq.s   3f
    lea     %a1@(258),%a1
    subq.l  #1,%d0
    bne.s   1b
    move.l  %sp@+,%d4
    bra.s   9f                          | full: nothing recorded
3:  move.l  %sp@+,%d4
    move.w  %d1,%a1@                    | claimed
2:  move.l  %d2,%d0
    add.l   %d0,%d0
    andi.l  #0xff,%d3
    move.w  %d3,%a1@(2,%d0:l)
9:  move.l  %sp@+,%d3
    rts

| Table a0, low byte's header d7, step d2, the sound's mask d5 -> the mask the
| step plays (each byte the lock's if locked) in d0.
mask_at:
    move.l  %d3,%sp@-
    move.l  %d7,%d1
    bsr     ext_get
    move.l  %d0,%d3
    move.l  %d7,%d1
    addi.l  #0x100,%d1
    bsr     ext_get
    tst.l   %d0
    bpl.s   1f
    move.l  %d5,%d0
    lsr.l   #8,%d0
1:  lsl.l   #8,%d0
    tst.l   %d3
    bpl.s   2f
    move.l  %d5,%d3
    andi.l  #0xff,%d3
2:  andi.l  #0xffff,%d0
    or.l    %d3,%d0
    move.l  %sp@+,%d3
    rts

| The draw's getters: the first held step's lock if it has one, else the
| sound's value; d1 the text flags where the draw now takes them from d1.
disp_mode:
    move.l  #{desc(K_MODE)},%sp@-
    bra.s   disp_ext
disp_rng:
    move.l  #{desc(K_RNG)},%sp@-
    bra.s   disp_ext
disp_spd:
    move.l  #{desc(K_SPD)},%sp@-
    bra.s   disp_ext
disp_nlen:
    move.l  #{desc(K_NLEN)},%sp@-
    bra.s   disp_ext
disp_len:
    move.l  #{desc(K_LEN)},%sp@-
    bra.s   disp_ext
disp_off:
    move.l  #{desc(K_OFF, OFF_FLAG)},%sp@-
disp_ext:                               | +0 desc, +4 ret, +8 model, +12 arp step
    lea     %sp@(-32),%sp
    moveml  %d2-%d7/%a2-%a3,%sp@        | desc +32, model +40, arp step +44
    moveq   #0,%d6
    move.b  %sp@(33),%d6                | k
    tst.b   %sp@(32)
    beq.s   1f
    add.l   %sp@(44),%d6
1:  moveq   #0,%d4
    moveq   #{FLAGS_PLAIN},%d5
    movea.l %sp@(40),%a0
    bsr     model_sound
    beq.s   80f
    move.l  %d6,%d0
    bsr     sound_off
    move.b  %a1@(0,%d0:l),%d4
    extb.l  %d4                         | the sound's value
    bsr     held_ctx
    beq.s   80f
    moveq   #0,%d2
    bsr     next_held
    beq.s   80f
    bsr     ctx_table
    move.l  %a2@({CTX_TRACK}),%d1
    ori.l   #{EXT_TAG},%d1
    lsl.l   #8,%d6
    or.l    %d6,%d1
    bsr     ext_get
    tst.l   %d0
    bmi.s   80f
    extb.l  %d0
    move.l  %d0,%d4
    moveq   #{FLAGS_LOCKED},%d5
80: move.l  %d4,%d0
    move.l  %d5,%d1
    moveml  %sp@,%d2-%d7/%a2-%a3
    lea     %sp@(36),%sp
    rts

| The graph's step-on getter (model, arp step) -> 0 / 1, from the held step's
| mask lock if it has one.
disp_mask:
    lea     %sp@(-32),%sp
    moveml  %d2-%d7/%a2-%a3,%sp@        | model +36, arp step +40
    moveq   #0,%d5
    movea.l %sp@(36),%a0
    bsr     model_sound
    beq.s   1f
    mvz.w   %a1@(356),%d5
1:  bsr     held_ctx
    beq.s   80f
    moveq   #0,%d2
    bsr     next_held
    beq.s   80f
    bsr     ctx_table
    move.l  %a2@({CTX_TRACK}),%d7
    ori.l   #{EXT_TAG | (K_MASK << 8)},%d7
    bsr     mask_at
    move.l  %d0,%d5
80: move.l  %sp@(40),%d0
    btst    %d0,%d5
    sne     %d0
    andi.l  #1,%d0
    moveml  %sp@,%d2-%d7/%a2-%a3
    lea     %sp@(32),%sp
    rts
"""
CORE_LABELS = ("note_hook", "build_hook", "sound_off", "held_ctx", "next_held",
               "ctx_table", "model_sound", "ext_get", "ext_put", "mask_at",
               "disp_mode", "disp_rng", "disp_spd", "disp_nlen", "disp_len",
               "disp_off", "disp_mask")


def ui_source() -> str:
    stubs = []
    for _, setter, label, k, flags in EDITS:
        stubs.append(f"""{label}:
    pea     {setter:#010x}
    move.l  #{desc(k, flags)},%sp@-
    bra     ui_ext""")
    return "\n".join(stubs) + f"""

| An edit, replacing `jsr setter(model, value)` or, for an offset,
| `jsr setter(model, arp step, value)`. With a trig held: lock (the lock, or the
| sound's value, + the knob's delta) on every held step and recount so the trig
| blinks. Otherwise the stock setter.
ui_ext:                                 | +0 desc, +4 setter, +8 ret, +12 model, +16 +20
    lea     %sp@(-32),%sp
    moveml  %d2-%d7/%a2-%a3,%sp@        | desc +32, setter +36, model +44, args +48 +52
    jsr     @held_ctx@
    beq     90f
    moveq   #0,%d4
    move.b  %sp@(33),%d4                | k
    move.l  %sp@(48),%d6                | the menu's new value
    tst.b   %sp@(32)
    beq.s   1f
    add.l   %sp@(48),%d4                | an offset: k + the arp step
    move.l  %sp@(52),%d6
1:  movea.l %sp@(44),%a0
    jsr     @model_sound@
    beq     90f
    move.l  %d4,%d0
    jsr     @sound_off@
    move.b  %a1@(0,%d0:l),%d5
    extb.l  %d5                         | the sound's value
    sub.l   %d5,%d6                     | the knob's delta
    move.l  %a2@({CTX_TRACK}),%d7
    ori.l   #{EXT_TAG},%d7
    lsl.l   #8,%d4
    or.l    %d4,%d7                     | the record header word
    moveq   #0,%d2
2:  jsr     @next_held@
    beq.s   80f
    jsr     @ctx_table@
    move.l  %d7,%d1
    jsr     @ext_get@
    tst.l   %d0
    bmi.s   3f
    extb.l  %d0
    bra.s   4f
3:  move.l  %d5,%d0
4:  add.l   %d6,%d0
    move.b  %sp@(34),%d1
    extb.l  %d1
    cmp.l   %d1,%d0
    bge.s   5f
    move.l  %d1,%d0
5:  move.b  %sp@(35),%d1
    extb.l  %d1
    cmp.l   %d1,%d0
    ble.s   6f
    move.l  %d1,%d0
6:  move.l  %d7,%d1
    jsr     @ext_put@
    bsr     recount
    addq.l  #1,%d2
    bra.s   2b
80: moveml  %sp@,%d2-%d7/%a2-%a3
    lea     %sp@(40),%sp
    rts
90: moveml  %sp@,%d2-%d7/%a2-%a3
    lea     %sp@(32),%sp
    movea.l %sp@(4),%a0
    lea     %sp@(8),%sp
    jmp     %a0@

| UP / DOWN on an arp step, replacing `jsr setStepOn(model, step, on)`: with a
| trig held, the step's bit set or cleared in each held step's mask lock.
ui_mask:
    lea     %sp@(-32),%sp
    moveml  %d2-%d7/%a2-%a3,%sp@        | model +36, arp step +40, on +47
    jsr     @held_ctx@
    beq     90f
    movea.l %sp@(36),%a0
    jsr     @model_sound@
    beq     90f
    mvz.w   %a1@(356),%d5               | the sound's mask
    moveq   #1,%d6
    move.l  %sp@(40),%d0
    lsl.l   %d0,%d6                     | the step's bit
    move.l  %a2@({CTX_TRACK}),%d7
    ori.l   #{EXT_TAG | (K_MASK << 8)},%d7
    moveq   #0,%d2
1:  jsr     @next_held@
    beq.s   80f
    jsr     @ctx_table@
    jsr     @mask_at@
    tst.b   %sp@(47)
    beq.s   2f
    or.l    %d6,%d0
    bra.s   3f
2:  move.l  %d6,%d1
    not.l   %d1
    and.l   %d1,%d0
3:  move.l  %d0,%d4
    move.l  %d7,%d1
    jsr     @ext_put@
    move.l  %d4,%d0
    lsr.l   #8,%d0
    move.l  %d7,%d1
    addi.l  #0x100,%d1
    jsr     @ext_put@
    bsr     recount
    addq.l  #1,%d2
    bra.s   1b
80: moveml  %sp@,%d2-%d7/%a2-%a3
    lea     %sp@(32),%sp
    rts
90: moveml  %sp@,%d2-%d7/%a2-%a3
    lea     %sp@(32),%sp
    jmp     {SET_MASK:#010x}

| The stock recount for step d2 of a2's track: the lock count, the blink.
recount:
    move.l  %d2,%sp@-
    move.l  %a2@({CTX_TRACK}),%sp@-
    move.l  %a2@({CTX_MODEL}),%sp@-
    jsr     {RECOUNT:#010x}
    lea     %sp@(12),%sp
    rts
"""


UI_LABELS = tuple(e[2] for e in EDITS) + ("ui_mask",)

CAVES = ((CAVE_LOOK, lambda: LOOK, LOOK_LABELS),
         (CAVE_CORE, lambda: CORE, CORE_LABELS),
         (CAVE_UI, ui_source, UI_LABELS))

# (va, stock bytes, how, label) -- replaced by jmp / jsr / lea to the label.
HOOKS = [
    (ID_TO_SLOT, bytes.fromhex("2f027410222f0008"), "jmp", "load_hook"),
    (LOAD_INDEX, bytes.fromhex("72654c01480041f24800d1c0114250a0"), "jsr", "idx_hook"),
    (SAVE_REC, bytes.fromhex("7810b883660622341c00600422331c001081"), "jsr", "save_rec"),
    (RECOUNT_MATCH, bytes.fromhex("71330801b680"), "jsr", "trk_cmp"),
    (BUILD, bytes.fromhex("4fefffe87065"), "jmp", "build_hook"),
    (NOTE_SET_CALL, bytes.fromhex("4eb940029cd4"), "jsr", "note_hook"),
    (MASK_EDIT, bytes.fromhex("4eb94004bd52"), "jsr", "ui_mask"),
]
HOOKS += [(va, bytes.fromhex("4eb9") + struct.pack(">I", setter), "jsr", label)
          for va, setter, label, _, _ in EDITS]
HOOKS += [(va, bytes.fromhex({"jsr": "4eb9", "lea_a4": "49f9", "lea_a3": "47f9"}[how])
           + struct.pack(">I", getter), how, label) for va, getter, how, label in DRAWS]
OPCODE = {"jmp": "4ef9", "jsr": "4eb9", "lea_a4": "49f9", "lea_a3": "47f9"}

# Plain byte patches: (va, stock, new, why).
PATCHES = [
    (LOAD_MAX, bytes.fromhex("786a"), bytes.fromhex("7881"),
     "pattern load: every id reaches the lookup (moveq #-127; free records fail the track check)"),
    (BUILD_GATE, bytes.fromhex("6730"), bytes.fromhex("4e71"),
     "note records: build the lock list for every note, for the arp block"),
]
PATCHES += [(va, bytes.fromhex("48780002"), bytes.fromhex("2f014e71"),
             "arp menu: a value's text flags from disp_*'s d1") for va in TEXT_FLAGS]

# Read, not written: what the hooks rely on.
CONTEXT = (
    (0x40026C24, bytes.fromhex("20280054"), "the ISR's note record: its lock list at +84"),
    (0x40026748, bytes.fromhex("2f02"), "the note set's sound argument, pushed 8th, from d2"),
    (0x4002683C, bytes.fromhex("21820c00"), "...and d2 filed per track after the note set"),
    (0x40026762 + 6, bytes.fromhex("4fef0028"), "the call pops 40 bytes"),
    (0x4002A114, bytes.fromhex("1029015f"), "the arp step reads MODE from its sound"),
    (0x4002A108, bytes.fromhex("71e90164"), "...the step mask"),
    (0x40026A6E, bytes.fromhex("73280162"), "the ISR reads an arp note's N.LEN per track"),
    (0x4002553E, bytes.fromhex("487800ca"), "lock lists hold 202 entries"),
    (0x400DE59E, bytes.fromhex("183c000f"), "pattern load: tracks <= 15 only"),
    (0x40055BBE, bytes.fromhex("10280268"), "held object: any trig held at +616"),
    (0x4005693C, bytes.fromhex("486b0258"), "held object: the held-step set at +600"),
    (0x40019734, bytes.fromhex("700d"), "arp menu keys: 11 UP (step on), 14 DOWN (off)"),
    (0x4004BD98, bytes.fromhex("34280164"), "setStepOn edits the mask at +356"),
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/arp-plocks_DN2_1.11.syx")


def be32(v: int) -> bytes:
    return struct.pack(">I", v)


def check(content: bytes, va: int, want: bytes, why: str) -> None:
    have = bytes(content[va - BASE:va - BASE + len(want)])
    if have != want:
        raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({why})")


def compose(stock: bytes, log=print) -> dict:
    if not available():
        raise SystemExit("no m68k assembler found (m68k-linux-gnu-as; WSL is fine)")
    content = bytearray(stock)
    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        check(content, va, want, why)
        log(f"  {va:#010x}  {want.hex():<14}  {why}")

    log("part 2 -- the caves")
    at, caves = {}, []
    for (cave, cap), source, labels in CAVES:
        if any(content[cave - BASE:cave - BASE + cap]):
            raise SystemExit(f"cave at {cave:#010x} is not free")
        text = re.sub(r"@(\w+)@", lambda m: f"{at[m.group(1)]:#010x}", source())
        table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in labels) + "\n"
        blob = assemble(text + table, base=cave)
        payload = blob[:-4 * len(labels)]
        at.update(zip(labels, struct.unpack(f">{len(labels)}I", blob[-4 * len(labels):])))
        if len(payload) > cap:
            raise SystemExit(f"cave at {cave:#010x} overflows: {len(payload)} > {cap}")
        content[cave - BASE:cave - BASE + len(payload)] = payload
        caves.append((cave, len(payload)))
        log(f"  {len(payload)} bytes at {cave:#010x}: " + ", ".join(labels))

    log("part 3 -- the hooks")
    for va, stock_bytes, how, label in HOOKS:
        check(content, va, stock_bytes, f"{how} -> {label}")
        new = bytes.fromhex(OPCODE[how]) + be32(at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex():<16} -> {new.hex():<16}  {how} {label}")

    log("part 4 -- byte patches")
    for va, stock_bytes, new, why in PATCHES:
        check(content, va, stock_bytes, why)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {why}")
    return {"content": bytes(content), "caves": caves, "at": at}


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = compose(section.unpack())["content"]
    print("part 5 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, content)}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Waverider's own SYN pages (Milestone 7): the page count, the page descriptors and the
knob labels a Waverider track shows. `docs/waverider-m7-pages.md` has the evidence.

A Waverider track is WaveTone to most of the UI (`coldfire`, M5): the SYN page readers
are asked about type 1, whatever the track. So these routines do not trust the type
they are handed. They ask whether the **active track** (the byte `0x42431a6c`, whose
sound is `[0x800052a0] + 52 + 1163 * t`) is a Waverider (`sound+0xDE` = 5), and only
then answer with Waverider's pages and labels:

- `wr_count`, entered by `jsr` from the page-count reader `0x400c24d2` (in place of M5's
  `canon_arg` there): 2 pages; otherwise exactly what `canon_arg` does.
- `wr_page`, entered by `jsr` from the page reader `0x400c24ee` at `0x400c24f2` (in
  place of M5's `canon_page`): our descriptor for pages 0-1, the stock empty page past
  them; otherwise exactly what `canon_page` does.
- `wr_label`, entered by `jsr` from the SYN page's label fetch at `0x40064622` (in place
  of `jsr getShortName`): the record ids Waverider relabels get our labels; every
  other id, and every other track, goes to the stock `getShortName` `0x400372da`
  unchanged (a tail jump, so the stack is the caller's own).

The labels and the page layout are the owner's (2026-10-01), from the Waverider mockup,
with our own names:

    page 1, OSC 1   A TUNE  B LEV   C POS   D TBL   E RATE  F MPOS  G MLEV  H MOVE
    page 2, OSC 2   A DETN  B LEV   C POS   D TBL   E RATE  F MPOS  G MLEV  H MOVE

Only TUNE, POS and TBL work in M7 (the loop reads TUN1, WAV1 and TBL1); every other
place is an empty entry (0), drawn as an empty box, until its milestone.

The code, the descriptors and the strings run from RAM as one platform `CODE` chunk at
`LOAD` (`dnfw.mods.platform`): the caves Waverider already uses are full.

This module is pure: it builds the source; `coldfire.compose` assembles and places it.
"""

from __future__ import annotations

LOAD = 0x4670C000                 # RAM above BSS, clear of every declared range (docs/mods-compatibility.md)
ACTIVE_TRACK = 0x42431A6C         # byte: the UI's active track, 0..15
KIT_POINTER = 0x800052A0          # the live kit; sound t at + 52 + 1163 t
SOUND_BASE, SOUND_STRIDE, SOUND_TYPE = 52, 1163, 0xDE
NEW_TYPE, CLONE = 5, 1
GET_SHORT_NAME = 0x400372DA
EMPTY_PAGE = 0x42432BD4           # the readers' own empty-page fallback
TAG = 10                          # the tag every stock SYN descriptor ends with

# WaveTone's page titles (DN2 1.11 strings), reused: they are page ids, not drawn text
TITLES = (0x4021A667, 0x4021A678)  # "DN VA 1", "DN VA 2"
SUBTITLE = "Waverider"             # where WaveTone's say "WaveTone"

# record id -> Waverider's label (the records stay WaveTone's: their slots are the
# frame's params 25..27, which the SHARC loop reads)
LABELS = {238: "TUNE", 239: "POS", 247: "TBL"}

# the two pages, encoders A..H; 0 is an empty place
PAGES = (
    (238, 0, 239, 247, 0, 0, 0, 0),   # OSC 1: TUNE - POS TBL - - - -
    (0, 0, 0, 0, 0, 0, 0, 0),         # OSC 2: all to come (M9)
)

LABELS_OUT = ("is_wr", "wr_count", "wr_page", "wr_label", "descriptors")


def source() -> str:
    """The chunk's assembly (GNU as, ColdFire), linked at LOAD."""
    table = "\n".join(f"    .long {rid}, lab_{rid}" for rid in LABELS)
    strings = "\n".join(f'lab_{rid}: .asciz "{name}"' for rid, name in LABELS.items())
    pages = []
    for k, entries in enumerate(PAGES):
        pages.append(f"    .long {TITLES[k]:#010x}, subtitle\n"
                     f"    .long {', '.join(str(e) for e in entries)}\n"
                     f"    .long {TAG}")
    page_data = "\n".join(pages)
    return f"""
| -- is the active track a Waverider? d0 = 1 if so, else 0; every other register kept
is_wr:
    move.l  %a0,%sp@-
    move.l  %d1,%sp@-
    moveq   #0,%d1
    move.b  {ACTIVE_TRACK:#010x},%d1
    mulu.w  #{SOUND_STRIDE},%d1
    movea.l {KIT_POINTER:#010x},%a0
    adda.l  %d1,%a0
    mvs.b   %a0@({SOUND_BASE + SOUND_TYPE}),%d1
    moveq   #0,%d0
    subq.l  #{NEW_TYPE},%d1
    bne.s   1f
    moveq   #1,%d0
1:  move.l  %sp@+,%d1
    movea.l %sp@+,%a0
    rts

| -- 0x400c24d2 pages(type), from its first instruction by jsr. The stack: our return
| into the reader, the caller's return, the type. A Waverider track: 2, straight back
| to the caller. Otherwise M5's canon_arg: the displaced loads, 5 read as 1.
wr_count:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   1f
    addq.l  #4,%sp
    moveq   #{len(PAGES)},%d0
    rts
1:  move.l  %sp@(8),%d0
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    bne.s   2f
    moveq   #{CLONE},%d0
2:  moveq   #4,%d1
    rts

| -- 0x400c24ee page(type, n), from 0x400c24f2 by jsr (after its own push of d2). The
| stack: our return, the saved d2, the caller's return, the type, the page. A Waverider
| track: our descriptor n (0..1) or the stock empty page, and back to the caller with d2
| restored. Otherwise M5's canon_page.
wr_page:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   3f
    move.l  %sp@(16),%d0
    moveq   #{len(PAGES)},%d1
    cmp.l   %d1,%d0
    bcs.s   1f
    move.l  #{EMPTY_PAGE:#010x},%d0
    bra.s   2f
1:  moveq   #44,%d1
    mulu.w  %d1,%d0
    addi.l  #descriptors,%d0
2:  addq.l  #4,%sp
    move.l  %sp@+,%d2
    rts
3:  move.l  %sp@(12),%d1
    move.l  %sp@(16),%d0
    subq.l  #{NEW_TYPE},%d1
    bne.s   4f
    moveq   #{CLONE},%d1
    rts
4:  addq.l  #{NEW_TYPE},%d1
    rts

| -- the SYN page's label fetch at 0x40064622 (jsr getShortName(this, id)), now jsr
| here. A Waverider track and a relabelled id: our label. Anything else: the stock
| getShortName, by a tail jump, so it returns to the page itself.
wr_label:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    move.l  %sp@(8),%d0
    lea     labels,%a0
1:  move.l  %a0@+,%d1
    beq.s   9f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a0
    bra.s   1b
2:  move.l  %a0@,%d0
    rts
9:  jmp     {GET_SHORT_NAME:#010x}

    .align 2
labels:
{table}
    .long 0
descriptors:
{page_data}
subtitle: .asciz "{SUBTITLE}"
{strings}
    .align 2
"""

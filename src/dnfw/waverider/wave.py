"""Waverider's waveform display (Milestone 8): the wave the oscillator plays, drawn in
the POS cell of the first SYN page, with a bar under it that shows where POS sits in
the table.

Where it is drawn. The SYN page draw (`0x40018118`) draws a type-1 page's grid, then,
on WaveTone's OSC page (page id 7), WaveTone's two oscillator icons. A Waverider track
is type 1 to it, so `pages.wr_icons` takes that test: WaveTone's icons are skipped, and
on Waverider's first page (the same id, 7) `wr_wave` draws in their place. The record
in cell C (`WAV1`, labelled POS) draws no widget of its own; WaveTone always left that
to its overlay, so the cell is ours.

What is drawn. The frame the SHARC reader plays for the current TBL and POS
(`TBL1 >> 8` picks the table, `min(WAV1, 0x7800)` the position across the 16 frames),
interpolated between the two frames on either side, as the reader does. The tables are
`dsp.tables()`, the ones baked into section 7.

A column is the **span** the frame covers there (its minimum to its maximum over the
32 of 512 points the column stands for), joined to the column before, as a sample
editor's overview draws. Point samples cannot show this machine's tables: the 16th
partial of the overtone table has 32 points a cycle, and sampling one point a column
lands every sample on a zero crossing, so it drew a flat line (emulator, 2026-10-01).
As spans it is a solid band, which is what 16 cycles in 16 pixels look like.

    per frame: 16 minima, then 16 maxima, signed bytes (-127..127)
    2 tables x 16 frames x 32 bytes = 1 KB in the chunk

When tables move to the +Drive (`docs/waverider-tables.md`), this copy moves with them.

    cell C (x 77..94)   wave: 16 columns, x 78..93
                        bar:  a dotted line, and a 3-pixel marker at POS

The values come from the page's own value getter `0x4006538e(this, id, &flag)`, the
call WaveTone's icons are drawn from. Pixels go through `setPixel` `0x40113b90`
`(canvas, x, y, on)`.

This module is pure: it builds the source; `coldfire.compose` assembles it with the
pages chunk.
"""

from __future__ import annotations

from . import dsp

GET_VALUE = 0x4006538E            # page view: the value of record id (this, id, &flag)
SET_PIXEL = 0x40113B90            # (canvas, x, y, on)
POS_ID, TBL_ID = 239, 247         # WAV1 (POS) and TBL1 (TBL)
POS_MAX = 0x7800                  # the reader's clamp on WAV1
TABLES = 2
FRAMES = 16

# the drawing, in the canvas's coordinates (y counts up from the bottom edge, as the
# SYN page's own blits do: cell row 0 spans y 34..51)
X0, WIDTH = 78, 16                # inside cell C's box (x 77..94)
CY, AMP = 45, 6                   # the wave: y 39..51
BAR_Y = 35                        # the bar: y 35 (dotted), the marker y 35..36
MARK = 3


def _byte(v: int) -> int:
    return max(-127, min(127, round(v * 127 / 32767)))


def spans() -> list[list[tuple[list[int], list[int]]]]:
    """-> [table][frame] = (minima, maxima), WIDTH signed bytes each: column c covers
    points c*n .. (c+1)*n of the frame (n = points / WIDTH), the last one shared with
    the next column so neighbours meet."""
    out = []
    for table in dsp.tables():
        points = len(table[0])
        n = points // WIDTH
        rows = []
        for frame in table:
            cols = [[frame[(c * n + k) % points] for k in range(n + 1)] for c in range(WIDTH)]
            rows.append(([_byte(min(col)) for col in cols], [_byte(max(col)) for col in cols]))
        out.append(rows)
    return out


def _data() -> str:
    return "\n".join("    .byte " + ", ".join(str(v) for v in lo + hi)
                     for table in spans() for lo, hi in table)


def source() -> str:
    """The display routine and its tables (GNU as, ColdFire), to be linked into the
    pages chunk. Entry: `wr_wave`, with a2 = the page view and d2 = the canvas; every
    register but d0/d1/a0/a1 is kept."""
    assert len(spans()) == TABLES and len(spans()[0]) == FRAMES
    assert (FRAMES - 1) * 256 * 8 == POS_MAX   # the frame position is pos >> 3
    frame = 2 * WIDTH
    return f"""
| -- Waverider's wave in cell C (docs in dnfw.waverider.wave). a2 = this, d2 = canvas.
| Locals: 40 bytes of saved registers, then the value getter's flag byte at 40(sp).
wr_wave:
    lea     %sp@(-44),%sp
    movem.l %d2-%d7/%a2-%a5,%sp@
    movea.l %d2,%a4
    pea     %sp@(40)
    pea     {TBL_ID}
    move.l  %a2,%sp@-
    jsr     {GET_VALUE:#010x}
    lea     %sp@(12),%sp
    move.l  %d0,%d7
    pea     %sp@(40)
    pea     {POS_ID}
    move.l  %a2,%sp@-
    jsr     {GET_VALUE:#010x}
    lea     %sp@(12),%sp
| pos in d6, clamped to 0..POS_MAX; frame in d0, fraction (/256) in d5
    tst.l   %d0
    bpl.s   1f
    moveq   #0,%d0
1:  cmpi.l  #{POS_MAX},%d0
    ble.s   2f
    move.l  #{POS_MAX},%d0
2:  move.l  %d0,%d6
    lsr.l   #3,%d0                  | pos * 15 * 256 / POS_MAX, exactly
    moveq   #0,%d5
    move.b  %d0,%d5
    lsr.l   #8,%d0
| the table: TBL1 >> 8, anything but 0 read as 1; a3 = the frame, a5 = the next one
    lsr.l   #8,%d7
    beq.s   3f
    moveq   #1,%d7
3:  lsl.l   #4,%d7
    add.l   %d0,%d7
    lsl.l   #5,%d7
    lea     waves,%a3
    adda.l  %d7,%a3
    movea.l %a3,%a5
    moveq   #{FRAMES - 1},%d1
    cmp.l   %d1,%d0
    beq.s   4f
    lea     %a3@({frame}),%a5
| the wave: column x in d4; the last column's y span in d3 (low) and a2 (high)
4:  moveq   #0,%d4
5:  move.l  %d4,%d1
    bsr.w   wave_y
    move.l  %d0,%sp@-
    moveq   #{WIDTH},%d1
    add.l   %d4,%d1
    bsr.w   wave_y
    move.l  %sp@+,%d1
    tst.l   %d4
    bne.s   6f
    move.l  %d1,%d3
    movea.l %d0,%a2
| drawn: min(low, last high) .. max(high, last low), so neighbours always meet
6:  move.l  %a2,%d2
    cmp.l   %d2,%d1
    bge.s   7f
    move.l  %d1,%d2
7:  move.l  %d3,%d7
    cmp.l   %d7,%d0
    ble.s   8f
    move.l  %d0,%d7
8:  move.l  %d1,%d3
    movea.l %d0,%a2
9:  pea     1
    move.l  %d2,%sp@-
    move.l  %d4,%d0
    addi.l  #{X0},%d0
    move.l  %d0,%sp@-
    move.l  %a4,%sp@-
    jsr     {SET_PIXEL:#010x}
    lea     %sp@(16),%sp
    addq.l  #1,%d2
    cmp.l   %d7,%d2
    ble.s   9b
    addq.l  #1,%d4
    moveq   #{WIDTH},%d0
    cmp.l   %d0,%d4
    blt.s   5b
| the bar: every other pixel of y BAR_Y
    moveq   #0,%d4
10: pea     1
    pea     {BAR_Y}
    move.l  %d4,%d0
    addi.l  #{X0},%d0
    move.l  %d0,%sp@-
    move.l  %a4,%sp@-
    jsr     {SET_PIXEL:#010x}
    lea     %sp@(16),%sp
    addq.l  #2,%d4
    moveq   #{WIDTH},%d0
    cmp.l   %d0,%d4
    blt.s   10b
| the marker: MARK x 2 pixels at x0 + pos * (WIDTH - MARK) / POS_MAX
    move.l  %d6,%d4
    mulu.w  #{WIDTH - MARK},%d4
    divu.w  #{POS_MAX},%d4
    mvz.w   %d4,%d4
    addi.l  #{X0},%d4
    moveq   #{MARK - 1},%d3
11: moveq   #1,%d2
12: pea     1
    move.l  %d2,%d0
    addi.l  #{BAR_Y},%d0
    move.l  %d0,%sp@-
    move.l  %d4,%d0
    add.l   %d3,%d0
    move.l  %d0,%sp@-
    move.l  %a4,%sp@-
    jsr     {SET_PIXEL:#010x}
    lea     %sp@(16),%sp
    subq.l  #1,%d2
    bpl.s   12b
    subq.l  #1,%d3
    bpl.s   11b
    movem.l %sp@,%d2-%d7/%a2-%a5
    lea     %sp@(44),%sp
    rts

| -- the y of byte d1 of the frame, between a3 and a5 by d5/256: d0 (d2 scratch)
wave_y:
    mvs.b   %a3@(0,%d1.l),%d0
    mvs.b   %a5@(0,%d1.l),%d2
    sub.l   %d0,%d2
    muls.l  %d5,%d2
    asr.l   #8,%d2
    add.l   %d2,%d0
    muls.w  #{AMP},%d0
    asr.l   #7,%d0
    addi.l  #{CY},%d0
    rts

waves:
{_data()}
    .align 2
"""

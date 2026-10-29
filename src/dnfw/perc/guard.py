"""v0.27: the frame-time guard (docs/sharc-load.md, "The frame-time guard").

The owner's v0.26 report: two PERC tracks p-locked with a sample track and an FM track
gave a loud click and then no audio at all until a reboot. Each of our voices runs inside
the SHARC's per-frame work (the per-block routine, after the stock machines), and an
exact Machinedrum voice costs up to about 40,000 instructions a block. If the frame's
work runs past the frame, the audio stops.

So before each of our voices the loop asks the core's cycle counter how far into the
frame it is, and plays the voice only if its expected cost still fits under a limit;
a voice that does not fit is silent for that block (its buffer zeroed, its state kept)
and counted. The time a frame has is measured: entry_mark.asm stores EMUCLK as the
handler calls the per-block routine (MARK0), once a frame, so the difference between
two frames' MARK0 is the frame's length in cycles; the limit is about 0.6 of it (the
stock work after our voices, the effects and the mix, took about 0.29 of a frame on the
instrument, docs/sharc-load.md). Each voice's own cost is measured too, around its
render, and the next block expects one and a half times it (at least FLOOR).

Emit only: the DSP code, not the model. The runner's EMUCLK does not move, so there the
guard always plays the voice (and the checks hold every voice to the model as before);
the runner's guard step feeds the clock to make it skip.
"""

from __future__ import annotations

MARK0 = 0x2DE13C                 # entry_mark.asm: EMUCLK as the handler calls the per-block routine
GUARD = 0x2DE000                 # free words between PERC's scratch (to 0x2ddfc8) and idle_load's state (0x2de100)
LIMIT = GUARD + 0x00             # cycles after MARK0 by which our voices must be done
PREV = GUARD + 0x04              # the last frame's MARK0
SKIPS = GUARD + 0x08             # voices left silent, cumulative
START = GUARD + 0x0C             # EMUCLK as the current voice began
PERIOD = GUARD + 0x10            # the last frame's length, cycles
COUNT = GUARD + 0x14             # the zeroing loop's counter
SKIPMASK = GUARD + 0x18          # v0.30: the slots skipped since the ColdFire last heard (bit t), sent and cleared by smp's idle packet
# v0.32: the limit from what the stock does after our voices, measured (the owner's dropouts
# with many voices: the fixed 0.6 of a frame assumed the stock's tail -- the voice chain,
# FX, mix -- took 0.29 of it, as measured with few voices; with sixteen it takes more)
TAIL = GUARD + 0x1C              # the stock's tail after our voices, cycles, held at its peak
PREV_AFTER = GUARD + 0x20        # idle_load's AFTER total at the last entry
PREV_MARK = GUARD + 0x24         # MARK (our entry, block_count.asm) at the last entry
OURS_END = GUARD + 0x28          # EMUCLK as our voices finished (smp.asm's tail)
METER_NOW = GUARD + 0x2C         # v0.32, the load meter: EMUCLK and the idle total at the
METER_IDLE = GUARD + 0x30        # last idle packet (dnfw.sampler.program)
AFTER = 0x2DE12C                 # idle_load.asm: AFTER, cumulative (MARK to the busy stretch's end)
MARK = 0x2DE124                  # block_count.asm: EMUCLK at our entry
IDLE_TOTAL = 0x2DE110            # idle_load.asm: the idle task's cycles, cumulative
COST_PERC = GUARD + 0x40         # 16 words: each PERC slot's last cost, cycles
COST_SMP = GUARD + 0x80          # 16 words: each sample slot's
END = GUARD + 0xC0
LIMIT_DEFAULT = 400_000          # until a frame has been measured: 0.6 of 666,667 (1 GHz, 1,500 frames a second)
FLOOR = 60_000                   # what a voice is expected to cost at least
PERIOD_MIN, PERIOD_MAX = 300_000, 3_000_000


def entry(p) -> None:
    """Once a frame, at PERC's entry: the frame's length, and the limit from it."""
    p.comment("v0.27: the frame's length (MARK0 - the last MARK0) and the limit, 0.6 of it")
    keep = p.label("gkeep")
    ok = p.label("gok")
    p.ld(8, MARK0)
    p.ld(9, PREV)
    p.st(PREV, 8)
    p.e("R9 = R8 - R9;", "the frame's length")
    p.iconst(10, PERIOD_MIN)
    p.e("COMP(R9, R10);")
    p.jump("LT", keep)
    p.iconst(10, PERIOD_MAX)
    p.e("COMP(R9, R10);")
    p.jump("GT", keep)
    p.st(PERIOD, 9)
    p.lsh(8, 9, -1)                            # 1/2 + 1/16 + 1/32 + 1/128 = 0.6016
    p.lsh(10, 9, -4)
    p.iop(8, 8, "+", 10)
    p.lsh(10, 9, -5)
    p.iop(8, 8, "+", 10)
    p.lsh(10, 9, -7)
    p.iop(8, 8, "+", 10)
    p.st(LIMIT, 8)
    tail_limit(p)
    p.place(keep)
    p.ld(8, LIMIT)
    p.e("R8 = PASS R8;")
    p.jump("NE", ok)
    p.iconst(8, LIMIT_DEFAULT)
    p.st(LIMIT, 8)
    p.place(ok)


def tail_limit(p) -> None:
    """v0.32: LIMIT = min(0.6 P, max(P - TAIL - P/8, P/4)), P the frame's length (R9 on entry).
    TAIL: the last frame's busy stretch after our entry (idle_load's AFTER moved on: the idle
    task ran since) less our own time then (OURS_END - PREV_MARK), held at its peak and eased
    by 1/4096 a frame; a reading that is not between 0 and 0.7 P is not taken. With no reading
    (the runner, or no idle time at all) TAIL stays 0 and the limit 0.6 P, as before.
    Emit only (as the rest of the guard). Clobbers R8, R10-R13."""
    p.comment("v0.32: the stock's tail after our voices, measured, sets the limit")
    no = p.label("tno")
    done = p.label("tdone")
    p.e("R13 = PASS R9;", "P")
    p.ld(8, AFTER)
    p.ld(10, PREV_AFTER)
    p.st(PREV_AFTER, 8)
    p.e("R8 = R8 - R10;", "AFTER's move: the last stretch from our entry")
    p.jump("EQ", no)
    p.ld(10, OURS_END)
    p.ld(11, PREV_MARK)
    p.e("R10 = R10 - R11;", "our own time then")
    p.e("R8 = R8 - R10;", "the stock's tail")
    p.jump("LE", no)
    p.lsh(10, 13, -1)                          # 0.7 P = P/2 + P/8 + P/16 (0.6875)
    p.lsh(11, 13, -3)
    p.iop(10, 10, "+", 11)
    p.lsh(11, 13, -4)
    p.iop(10, 10, "+", 11)
    p.e("COMP(R8, R10);")
    p.jump("GE", no)
    p.ld(10, TAIL)
    p.iop(8, 8, "MAX", 10)
    p.st(TAIL, 8)
    p.place(no)
    p.ld(8, TAIL)
    p.lsh(10, 8, -12)
    p.e("R8 = R8 - R10;", "eased by 1/4096 (about 3 s)")
    p.st(TAIL, 8)
    p.ld(10, MARK)
    p.st(PREV_MARK, 10)
    p.e("R10 = R13 - R8;", "P - TAIL")
    p.lsh(11, 13, -3)
    p.e("R10 = R10 - R11;", "less P/8")
    p.lsh(11, 13, -2)
    p.e("COMP(R10, R11);")
    p.jump("GE", done)
    p.e("R10 = PASS R11;", "at least P/4")
    p.place(done)
    keep = p.label("tkeep")
    p.ld(8, LIMIT)
    p.e("COMP(R10, R8);")
    p.jump("GE", keep)
    p.st(LIMIT, 10)
    p.place(keep)


def meter(p, dst: int) -> None:
    """v0.32, the load meter: DST = the DSP's load since the last call, in permille: 1000 -
    1000 x (idle cycles / cycles), idle_load's total against EMUCLK, held to 0..1000; 0 when no
    time passed (the runner's clock does not move) or more than 2^31 cycles (over two
    seconds). Emit only (the runner's model never builds the idle packet). Clobbers R8,
    R10-R13."""
    from .machines import _recip_inline
    p.comment("v0.32: the DSP's load since the last idle packet, permille")
    zero = p.label("mzero")
    done = p.label("mdone")
    p.e("R8 = EMUCLK;")
    p.ld(10, METER_NOW)
    p.st(METER_NOW, 8)
    p.e("R8 = R8 - R10;", "cycles since")
    p.jump("LE", zero)
    p.ld(11, IDLE_TOTAL)
    p.ld(10, METER_IDLE)
    p.st(METER_IDLE, 11)
    p.e("R11 = R11 - R10;", "idle cycles since")
    p.iconst(12, 0)
    p.float_(8, 8, 12)
    p.float_(11, 11, 12)
    _recip_inline(p, 10, 8, 13)                # F10 = 1 / cycles (clobbers R12, R13)
    p.fop(11, 11, "*", 10)                     # idle share
    p.fconst(12, 1000.0)
    p.fop(11, 11, "*", 12)
    p.fop(11, 12, "-", 11)                     # 1000 - 1000 x idle share
    p.fconst(12, 0.0)
    p.fop(11, 11, "MAX", 12)
    p.fconst(12, 1000.0)
    p.fop(11, 11, "MIN", 12)
    p.trunc(8, 11)
    p.st(dst, 8)
    p.jump("", done)
    p.place(zero)
    p.iconst(8, 0)
    p.st(dst, 8)
    p.place(done)


def end_mark(p) -> None:
    """v0.32: OURS_END = EMUCLK, as our voices finish (smp.asm's tail). Clobbers R8."""
    p.e("R8 = EMUCLK;", "v0.32: our voices are done")
    p.st(OURS_END, 8)


def around(p, t_word: int, cost: int, buffers: int, voice) -> None:
    """VOICE() if it fits, else the slot's buffer zeroed and the skip counted. T_WORD:
    the scratch word holding the slot; COST: the slots' cost words; BUFFERS: the track
    buffers' pointers (0x254a60)."""
    skip = p.label("gskip")
    done = p.label("gdone")
    p.e("R8 = EMUCLK;")
    p.st(START, 8)
    p.ld(9, MARK0)
    p.e("R8 = R8 - R9;", "how far into the frame")
    p.ld(9, t_word)
    p.lsh(9, 9, 2)
    p.iconst(10, cost)
    p.iop(9, 10, "+", 9)
    p.seti(5, 9)
    p.ldi(9, 0, 5, "this slot's last cost")
    p.lsh(10, 9, -1)
    p.iop(9, 9, "+", 10)                       # x 1.5
    p.iconst(10, FLOOR)
    p.iop(9, 9, "MAX", 10)
    p.iop(8, 8, "+", 9)
    p.ld(10, LIMIT)
    p.e("COMP(R8, R10);")
    p.jump("GT", skip)
    voice()
    p.e("R8 = EMUCLK;")
    p.ld(9, START)
    p.e("R8 = R8 - R9;", "what the voice cost")
    p.ld(9, t_word)
    p.lsh(9, 9, 2)
    p.iconst(10, cost)
    p.iop(9, 10, "+", 9)
    p.seti(5, 9)
    p.sti(0, 5, 8)
    p.jump("", done)
    p.place(skip)
    p.comment("no time left in this frame: the voice is silent this block (its state kept),")
    p.comment("and its expected cost eased by a quarter, so it is tried again")
    p.ldi(9, 0, 5)                             # I5: the slot's cost word, still
    p.lsh(10, 9, -2)
    p.e("R9 = R9 - R10;")
    p.sti(0, 5, 9)
    p.ld(8, SKIPS)
    p.iconst(9, 1)
    p.iop(8, 8, "+", 9)
    p.st(SKIPS, 8)
    p.ld(9, t_word)                            # v0.30: and which slot, for the page's CPU flag
    p.iconst(10, 1)
    p.e("R10 = LSHIFT R10 BY R9;")
    if p.run:
        p.setR(10, 1 << (p.r[9] & 31))
    p.ld(8, SKIPMASK)
    p.iop(8, 8, "OR", 10)
    p.st(SKIPMASK, 8)
    p.ld(9, t_word)
    p.lsh(9, 9, 2)
    p.iconst(10, buffers)
    p.iop(9, 10, "+", 9)
    p.seti(5, 9)
    p.ldi(9, 0, 5)
    # I4, not I5: I5 is the DT2 decimator's, used only pre-modified (its L5 may be a
    # circular length on the unit, which a post-modify would wrap into stock memory)
    p.seti(4, 9, "the slot's buffer")
    p.iconst(8, 0)
    p.loop(COUNT, 8, lambda: [p.stpost(4, 8) for _ in range(4)])
    p.place(done)

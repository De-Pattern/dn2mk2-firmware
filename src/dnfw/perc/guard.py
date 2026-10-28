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
    p.place(keep)
    p.ld(8, LIMIT)
    p.e("R8 = PASS R8;")
    p.jump("NE", ok)
    p.iconst(8, LIMIT_DEFAULT)
    p.st(LIMIT, 8)
    p.place(ok)


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

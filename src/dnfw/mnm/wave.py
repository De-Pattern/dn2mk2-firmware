"""DPRO-WAVE (docs/mnm.md): one of 32 single-cycle waves of 512 12-bit samples, read with
linear interpolation at four times the rate through a window of 512..1023 samples (WP, and
its sweep WPM, slide the window into the next wave: the morph), hard sync to an oscillator
of its own or to the previous track's pitch, then the decimator.

State: S0 the phase (sample index << 21), S1 the WP sweep (24-bit), S2 the sync counter,
S3..S7 the decimator. Parameters: WAVE WP WPM WPRS SYNC SFRQ --- TUNE.
"""

from __future__ import annotations

from . import core as C
from . import dec
from ..md import core as K
from ..perc.dsl import Prog

NAME, ID = "DPRO-WAVE", 6
PNAMES = ("WAVE", "WP", "WPM", "WPRS", "SYNC", "SFRQ", "---", "TUNE")
DEFAULTS = (0, 0, 0, 96, 0, 0, 0, 64)
COEF = (0x3CE85F, 0xF9F156, 0x939958, 0x04D33E, 0x36F789, 0x11B451, 0x9023EC, 0xEE4BAF,
        0xC652AD, 0x0D1E2D)
GAIN = 0x6186
FRAC = 21                                    # the phase's fraction bits
S_PH, S_POS, S_SYNC, S_DEC = 0, 1, 2, 3


def s24(v: int) -> int:
    v &= 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


def coefs(p: Prog, L: C.Layout, coef, gain, inner, shift) -> None:
    """The decimator's set-up: its coefficients at COEF, I1 on them, the gain in F11, the
    inner count and the output shift. Clobbers R12, R13."""
    for k, c in enumerate(coef):
        p.fconst(13, s24(c) * C.Q23)
        p.st(L.COEF + 4 * k, 13)
    p.iconst(13, L.COEF)
    p.seti(1, 13)
    p.fconst(dec.X1, gain * C.Q23)
    p.iconst(13, 10 - inner)
    p.st(L.W["inner"], 13)
    p.fconst(13, float(1 << shift))
    p.st(L.W["shift"], 13)


def init(p: Prog, L: C.Layout) -> None:
    p.iconst(0, 0)
    for k in (S_PH, S_POS):
        C.sts(p, k, 0)


def trig(p: Prog, L: C.Layout) -> None:
    p.iconst(0, 0)
    C.sts(p, S_SYNC, 0)
    C.par(p, 1, 3)                               # WPRS
    p.fconst(12, 0.5)
    p.if_(1, "GE", 12, lambda: C.sts(p, S_POS, 0))


def sync_period(p: Prog, L: C.Layout, f: int) -> None:
    """R4 = the sync period in blocks for the pitch word in Rf (0..0x5800): the render's
    44100 / (the exp table's word x 0x20B40 / 2^11, at most 2^23 - 1) << 12, truncated.
    Clobbers R0-R4, R12-R15, I1, I12."""
    from ..perc import machines as PM
    p.iconst(12, 0)
    p.float_(4, f, 12)
    p.fconst(12, 1.0 / 2048.0)
    p.fop(4, 4, "*", 12)
    PM.exp2(p, L.perc, 4, 4)                    # 2^(F / 2048)
    p.fconst(12, 4096.0 * 0x20B40 / 2048.0)
    p.fop(4, 4, "*", 12)
    p.fconst(12, float(0x7FFFFF))
    p.fop(4, 4, "MIN", 12)
    p.trunc(4, 4)
    p.iconst(12, 0)
    p.float_(4, 4, 12)                          # x0, a whole number
    PM.recip(p, 4, 4)
    p.fconst(12, 44100.0 * 4096.0)
    p.fop(4, 4, "*", 12)
    p.trunc(4, 4)


def sync(p: Prog, L: C.Layout) -> None:
    """SYNC (OFF, SFRQ, PRCH): every PERIOD blocks the phase restarts (the Monomachine
    counts blocks, not samples). SFRQ's pitch is 52 SFRQ + 0x1000; PRCH's the previous
    track's (VW pre, 0 if none). -> VW i2 (0: none). Clobbers R0-R4, R12-R15, I1, I12."""
    p.iconst(0, 0)
    C.vws(p, "i2", 0)
    C.par(p, 1, 4)
    p.fconst(12, 0x2AAAAA * C.Q23)

    def on():
        C.par(p, 1, 4)
        p.fconst(12, 0x555555 * C.Q23)

        def prch():
            C.vw(p, 2, "pre")
            sync_period(p, L, 2)
            C.vws(p, "i2", 4)

        def sfrq():
            C.knob(p, 2, 5)

            def go():
                p.lsh(3, 2, 2)                  # 52 k = 32 k + 16 k + 4 k
                p.lsh(4, 2, 4)
                p.ipass(12, 3)
                p.iop(3, 12, "+", 4)
                p.lsh(4, 2, 5)
                p.ipass(12, 3)
                p.iop(2, 12, "+", 4)
                p.iconst(12, 0x1000)
                p.iop(2, 12, "+", 2)
                sync_period(p, L, 2)
                C.vws(p, "i2", 4)
            p.ifz(2, "NE", go)
        p.if_(1, "GE", 12, prch, sfrq)
    p.if_(1, "GE", 12, on)


def count(p: Prog) -> None:
    """the block counter against the period (VW i2, > 0): at it, both restart"""
    C.vw(p, 4, "i2")
    C.st(p, 0, S_SYNC)
    p.ipass(12, 0)
    p.iconst(13, 1)
    p.iop(0, 12, "+", 13)

    def restart():
        p.iconst(0, 0)
        C.sts(p, S_PH, 0)
    p.if_(0, "GE", 4, restart, kind="i")
    C.sts(p, S_SYNC, 0)


def pitch(p: Prog, L: C.Layout) -> None:
    """The increments from the pitch (VW A, pre) and the parameters: VW i1 the phase's (A x
    0x2f8e, the render's DMACSS, in samples << FRAC), i2 the sync period (blocks, 0 none)."""
    C.vw(p, 1, "A")
    p.fconst(12, 0x2F8E * 2.0 ** (FRAC - 23))
    p.fop(1, 1, "*", 12)
    p.trunc(1, 1)
    C.vws(p, "i1", 1)
    sync(p, L)


def exact(A: int, F: int, knobs, pre: int = 0) -> dict:
    """the same, in the Monomachine's integer arithmetic (the tests)"""
    from . import exact as X
    return {"i1": X.wave_inc(A, FRAC), "i2": X.wave_sync(knobs, pre)}


def half(p: Prog, L: C.Layout) -> None:
    """One Monomachine block: 64 samples into IN, decimated to 16 at I4."""
    W = L.W
    C.vw(p, 1, "i1")
    p.st(W["inc"], 1)
    C.vw(p, 4, "i2")
    p.ifz(4, "GT", lambda: count(p))
    # WP and its sweep: pos += WPM << 6 (24 bits); x = pos + WP << 16, folded below 2^23
    C.knob(p, 2, 2)
    p.lsh(2, 2, 6)
    C.st(p, 3, S_POS)
    p.ipass(12, 3)
    p.iop(3, 12, "+", 2)
    p.iconst(12, 0xFFFFFF)
    p.iop(3, 3, "AND", 12)
    C.sts(p, S_POS, 3)
    C.knob(p, 2, 1)
    p.lsh(2, 2, 16)
    p.ipass(12, 3)
    p.iop(3, 12, "+", 2)                          # pos + WP (< 2^25)
    p.iconst(12, 0x7FFFFF)

    def fold():                                   # |0xffffff - x|
        p.iconst(12, 0xFFFFFF)
        p.iop(3, 12, "-", 3)
        p.ifz(3, "LT", lambda: (p.iconst(12, 0), p.iop(3, 12, "-", 3)))
    p.if_(3, "GT", 12, fold, kind="i")
    p.lsh(3, 3, -14)
    p.iconst(12, 0x200)
    p.iop(3, 12, "+", 3)                          # the window's end, 512..1023 samples
    p.lsh(4, 3, -1)
    p.st(W["hlf"], 4)
    p.lsh(3, 3, FRAC)
    p.st(W["len"], 3)
    # the wave: WAVE >> 2, 512 samples each, in the table (floats)
    C.knob(p, 2, 0)
    p.lsh(2, 2, -2)
    p.lsh(2, 2, 9 + 2)
    p.iconst(12, L.tables)
    p.iop(2, 12, "+", 2)
    p.st(W["base"], 2)
    # 64 samples into IN
    p.iconst(12, L.IN)
    p.seti(5, 12)

    def one():
        C.st(p, 1, S_PH)
        p.lsh(2, 1, -FRAC)                        # i, the sample index
        p.iconst(12, 1)
        p.iop(3, 2, "AND", 12)                    # h
        p.lsh(4, 2, -1)                           # n0
        p.ipass(12, 4)
        p.iop(4, 12, "+", 3)                      # nb = n0 + h
        p.ld(6, W["hlf"])

        def wrap():
            p.iconst(12, -256)
            p.iop(4, 12, "+", 4)
        p.if_(4, "GE", 6, wrap, kind="i")
        p.lsh(4, 4, 1)
        p.ipass(12, 4)
        p.iconst(6, 1)
        p.iop(4, 12, "+", 6)
        p.ipass(12, 4)
        p.iop(4, 12, "-", 3)                      # s1 = 2 nb + 1 - h
        p.ld(6, W["base"])
        p.lsh(7, 2, 2)
        p.ipass(12, 6)
        p.iop(7, 12, "+", 7)
        p.seti(1, 7)
        p.ldi(8, 0, 1)                            # T[s0]
        p.lsh(7, 4, 2)
        p.ipass(12, 6)
        p.iop(7, 12, "+", 7)
        p.seti(1, 7)
        p.ldi(9, 0, 1)                            # T[s1]
        p.iconst(12, (1 << FRAC) - 1)
        p.iop(7, 1, "AND", 12)
        p.iconst(12, -FRAC)
        p.float_(7, 7, 12)                        # f
        p.fop(9, 9, "-", 8)
        p.fop(9, 9, "*", 7)
        p.fop(8, 8, "+", 9)                       # T[s0] + (T[s1] - T[s0]) f
        p.fop(8, 8, "+", 8)                       # x 2: MPYSU's unsigned weights are Q23 (up to 2)
        C.sat(p, 8)
        p.stpost(5, 8)
        # the phase moves on, back 512 samples past the window's end
        p.ld(2, W["inc"])
        p.ipass(12, 1)
        p.iop(1, 12, "+", 2)
        p.ld(2, W["len"])

        def back():
            p.iconst(12, -(512 << FRAC))
            p.iop(1, 12, "+", 1)
        p.if_(1, "GE", 2, back, kind="i")
        C.sts(p, S_PH, 1)
    p.loop(W["n4"], 64, one)
    # decimate
    coefs(p, L, COEF, GAIN, 2, 5)
    p.iconst(12, L.IN)
    p.seti(5, 12)
    p.ld(12, L.md.C["mdb"])
    p.iconst(13, 4 * (K.S0 + S_DEC))
    p.ipass(14, 12)
    p.iconst(12, 4 * (K.S0 + S_DEC))
    p.iop(13, 12, "+", 14)
    p.seti(2, 13)
    dec.decimate(p, L)

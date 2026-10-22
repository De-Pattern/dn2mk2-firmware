"""TRX, first half: the Machinedrum's analog-modelled kick, snare, toms, clave and rim shot
(docs/md.md), from DSP2's TRX-BD, TRX-B2, TRX-SD, TRX-XT, TRX-XC, TRX-CL, TRX-RS and their
host scale functions.

Each machine is four steps on the slot's words (core.py), as in gnd.py. The firmware works
a block in several passes over its 32-sample buffer; here the passes are one loop a sample
(each pass only reads its own sample and carries its own state, so the order of operations
for every sample is the firmware's). Loop-carried state lives in registers the loop body
leaves alone (out_loop takes R0 and R12; core.sine and core.table_f take R12, R13, I1).

Words. A word that the DSP uses as a Q23 fraction is a float (w / 2^23); a word it uses as
an integer (a pitch, a count, a table index, a shift) is an int. The host's integer
products are made exact (`imul`): there is no integer multiply, and a float product of two
14-bit inputs is not exact.
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .gnd import out_loop, pitch_word
from ..perc.dsl import Prog

Q = K.Q23
ATTACK = 0x50C335 * Q                         # the amp env's restart, on top of its level
FADE = 0x733333 * Q                           # 0.9: the previous note's fade-out a sample
TROUGH = -1.0 + 12.25 * Q                     # see TRXRS
IDX_LO = 0x1FFFF                            # a phase's fraction (below the sine index)


# -- helpers ---------------------------------------------------------------------------
def fl(p: Prog, d: int, a: int, sh: int = 0) -> None:
    """Fd = Ra * 2^sh. Clobbers R12."""
    p.iconst(12, sh)
    p.float_(d, a, 12)


def iadd_k(p: Prog, d: int, a: int, k: int) -> None:
    """Rd = Ra + k. Clobbers R12."""
    p.iconst(12, k)
    p.iop(d, 12, "+", a)


def imul(p: Prog, d: int, x: int, k: int | None = None, y: int | None = None) -> None:
    """Rd = Rx * (k or Ry), exact (Rx 0..16383; k or Ry 0..2^17): Rx in two 7-bit halves,
    whose float products are exact. Clobbers R12, R13, R14 (x, y not among them)."""
    p.iconst(12, 127)
    p.iop(13, x, "AND", 12)
    p.lsh(14, x, -7)
    p.iconst(12, 0)
    p.float_(13, 13, 12)
    p.float_(14, 14, 12)
    if k is not None:
        p.fconst(12, float(k))
    else:
        p.iconst(12, 0)
        p.float_(12, y, 12)
    p.fop(13, 13, "*", 12)
    p.fop(14, 14, "*", 12)
    p.trunc(13, 13)
    p.trunc(14, 14)
    p.lsh(14, 14, 7)
    p.iop(d, 14, "+", 13)


def grid(p: Prog, x: int, t: int = 13) -> None:
    """Fx = Fx truncated to the Q23 grid (the 56300 storing a product), Fx >= 0. Where an
    envelope is multiplied by its coefficient every sample this sets its tail. Clobbers
    R12, Rt."""
    p.fconst(12, 2.0 ** 23)
    p.fop(x, x, "*", 12)
    p.trunc(t, x)
    p.iconst(12, -23)
    p.float_(x, t, 12)


def ffloor(p: Prog, x: int, t: int = 13, u: int = 14) -> None:
    """Fx = floor(Fx) (Fx of either sign). Clobbers R12, Rt, Ru."""
    p.trunc(t, x)
    p.iconst(12, 0)
    p.float_(u, t, 12)
    p.if_(u, "GT", x, lambda: (p.iconst(12, -1), p.iop(t, 12, "+", t)))
    p.iconst(12, 0)
    p.float_(x, t, 12)


def one_minus(p: Prog, r: int) -> None:
    """Fr = 1 - Fr (exact for a Q23 coefficient). Clobbers R12."""
    p.fconst(12, 1.0)
    p.fop(r, 12, "-", r)


def env_mul(p: Prog, x: int, dd: int, t: int, u: int, v: int) -> None:
    """Fx = floor(Fx (1 - Fdd)) on the Q23 grid, Fx >= 0 on the grid, 1 - Fdd a Q23
    coefficient: as Fx - ceil(Fx Fdd), whose small product a float holds (all but)
    exactly where Fx (1 - Fdd) itself would round before the floor -- an envelope that
    holds (1 - 2^-20 a sample) loses 0.25 LSB a sample to that. Clobbers R12, Rt, Ru,
    Rv."""
    p.fop(v, x, "*", dd)
    K.mul_k(p, v, v, -(2.0 ** 23))
    ffloor(p, v, t, u)
    K.mul_k(p, v, v, Q)
    p.fop(x, x, "+", v)


def smpy(p: Prog, d: int, a: int, b: int, s1: int, s2: int, s3: int) -> None:
    """Fd = the 56300's product of the Q23 words Fa, Fb through the limiter's truncation,
    signed: core.mpy_floor on the magnitudes, then floor(-x) = -floor(x) - 2^-23 for a
    negative product (a product that is a whole Q23 word is taken as not one: 2^-23 of
    the cases). A filter's coefficients come out exact, where a float product is a LSB
    off often enough to move a resonance. Clobbers R0-R3, R12-R15, Rs1-Rs3."""
    p.fop(s3, a, "*", b)
    K.mul_k(p, s1, a, -1.0)
    p.fop(s1, s1, "MAX", a)
    K.mul_k(p, s2, b, -1.0)
    p.fop(s2, s2, "MAX", b)
    K.mpy_floor(p, d, s1, s2)
    p.ifz(s3, "LT", lambda: (K.mul_k(p, d, d, -1.0), K.add_k(p, d, d, -Q)), kind="f")


def sgrid(p: Prog, x: int, t: int = 13, u: int = 14) -> None:
    """Fx = Fx floored to the Q23 grid (either sign). Clobbers R12, Rt, Ru."""
    K.mul_k(p, x, x, 2.0 ** 23)
    ffloor(p, x, t, u)
    K.mul_k(p, x, x, Q)


def restart_amp(p: Prog, k: int) -> None:
    """S[k] = sat(0.63 + S[k]): the TRX amp env on a note. Clobbers R4, R5, R12."""
    s(p, 4, k)
    p.fconst(5, ATTACK)
    p.fop(4, 4, "+", 5)
    K.sat(p, 4)
    ss(p, k, 4)


def zero(p: Prog, ks, f: bool = False) -> None:
    if f:
        p.fconst(0, 0.0)
    else:
        p.iconst(0, 0)
    for k in ks:
        ss(p, k, 0)


def tbl_int(p: Prog, L: K.Layout, d: int, name: str, idx: int) -> None:
    """Rd = TABLE[name][Ridx] as the integer it is (a Q23-float table). Clobbers R12, R13,
    I1."""
    K.table_f(p, L, d, name, idx)
    K.mul_k(p, d, d, 2.0 ** 23)
    p.trunc(d, d)


def quirk(p: Prog, L: K.Layout, d: int, ph: int, lo: int, hi_addr: int) -> None:
    """One sample of the TRX-XT/XC/CL sine (md_models.quirk_osc): Fd = sine(Rph); then
    Rph += hi + Rlo, and Rlo = the sample as the 48-bit increment's low word (the firmware
    loads the sample into X0, the increment's own low word). Clobbers R8, R9, R12, R13, I1."""
    K.sine(p, L, d, ph)
    p.ld(8, hi_addr)
    p.iop(8, 8, "+", lo)
    p.iop(ph, 8, "+", ph)
    K.mul_k(p, 9, d, 2.0 ** 16)               # u24(v) >> 7: v in phase units, mod an index
    p.trunc(lo, 9)
    p.iconst(12, IDX_LO)
    p.iop(lo, lo, "AND", 12)


def split_inc(p: Prog, inc: int, lo: int) -> None:
    """Rlo = Rinc's fraction (below the sine index), Rinc = its whole indices."""
    p.iconst(12, IDX_LO)
    p.iop(lo, inc, "AND", 12)
    p.iconst(12, ~IDX_LO & 0xFFFFFFFF)
    p.iop(inc, inc, "AND", 12)


def trig_count(p: Prog, k: int, first: int, fade, rest, body) -> None:
    """The TRX trigger phase: if S[k] != 0, S[k] -= 1 and the block is FADE (S[k] was
    FIRST + 1) or rest(R0 = the new count); else body()."""
    s(p, 0, k)

    def phase():
        iadd_k(p, 0, 0, -1)
        ss(p, k, 0)
        p.iconst(12, first)
        p.if_(0, "EQ", 12, fade, lambda: rest(), kind="i")
    p.ifz(0, "NE", phase, body)


def fade_block(p: Prog, L: K.Layout, last: int) -> None:
    """The first block after a note: the previous note's last sample, x0.9 a sample."""
    s(p, 6, last)
    p.fconst(7, FADE)
    out_loop(p, L, lambda: (p.fop(6, 6, "*", 7), p.fpass(4, 6)))


def resonance(p: Prog, L: K.Layout, x: int, y1: int, y2: int, C) -> None:
    """TRX-SD's two-pole resonator, one sample: Fx = sat(2 (c1 y2 + g y1 + c0 Fx));
    y2, y1 = y1, Fx. c0, c1, g in C['d'], C['e'], C['f']. Clobbers R12, R14."""
    p.ld(14, C["d"])
    p.fop(x, x, "*", 14)
    p.ld(14, C["e"])
    p.fop(14, 14, "*", y2)
    p.fop(x, x, "+", 14)
    p.ld(14, C["f"])
    p.fop(14, 14, "*", y1)
    p.fop(x, x, "+", 14)
    p.fop(x, x, "+", x)
    K.sat(p, x)
    p.fpass(y2, y1)
    p.fpass(y1, x)


def x14(p: Prog, L: K.Layout, d: int, idx: int, off: int) -> None:
    """Fd = X:$140000[off + Ridx] (the filter tables). Clobbers R12, R13, I1, R15."""
    iadd_k(p, 15, idx, off)
    K.table_f(p, L, d, "X140000", 15)


# =====================================================================================
class TRXBD:
    """TRX-BD: the analog-style kick (md_models.TRXBD). Words: W1 amp decay, W2 click level,
    W3 pitch (int), W4 ramp depth (int), W5 ramp decay, W6/W7 slew thresholds, W8/W9
    clipper knees, W10 clipper gain, W11 noise level, W12 noise decay, W13 HARM.
    State: the amp env, the trigger count, the ramp env, the slew state, the two phases,
    the last sample, the click offset, the thresholds, the noise generator and env, the
    harmonic's env; S[48..80] the block's noise (each value three times)."""
    NAME, ID = "TRX-BD", 16
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "STRT", "NOIS", "HARM", "CLIP")
    AMP, CNT, RAMP, Y0, Y1, PH1, LAST, CLK, THI, TLO, F1, F2, NENV, PH2, HARM = range(15)
    NZ = 48

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                    # PTCH
        p.lsh(0, 0, -6)
        iadd_k(p, 0, 0, 64)
        pitch_word(p, L, 4, 0)
        K.mul_k(p, 4, 4, 0.5)
        p.trunc(4, 4)
        ws(p, 3, 4)
        inp(p, 0, 1)                                    # DEC
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, 80.0)
        p.trunc(1, 4)
        p.lsh(1, 1, -12)
        iadd_k(p, 1, 1, 120)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 1, 4)
        inp(p, 0, 2)                                    # RAMP: ((r^2 >> 18) r >> 14) + 3
        imul(p, 1, 0, y=0)
        p.lsh(1, 1, -18)
        fl(p, 4, 1)
        fl(p, 5, 0)
        p.fop(4, 4, "*", 5)                             # < 2^24: exact
        p.trunc(1, 4)
        p.lsh(1, 1, -14)
        iadd_k(p, 1, 1, 3)
        ws(p, 4, 1)
        inp(p, 0, 3)                                    # RDEC
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, 70.0)
        p.trunc(1, 4)
        p.lsh(1, 1, -12)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 5, 4)
        inp(p, 0, 4)                                    # STRT
        fl(p, 4, 0, -14)
        ws(p, 2, 4)
        inp(p, 0, 6)                                    # HARM
        fl(p, 4, 0, -14)
        ws(p, 13, 4)
        inp(p, 0, 5)                                    # NOIS

        def quiet():
            fl(p, 4, 0, -15)
            ws(p, 11, 4)
            p.iconst(1, 0)
            K.table_f(p, L, 4, "hostD", 1)
            ws(p, 12, 4)

        def loud():
            p.fconst(4, 0.25)
            ws(p, 11, 4)
            fl(p, 4, 0)
            K.mul_k(p, 4, 4, 40.0)
            K.add_k(p, 4, 4, -327680.0)
            p.trunc(1, 4)
            p.lsh(1, 1, -12)
            K.table_f(p, L, 4, "hostD", 1)
            ws(p, 12, 4)
        p.iconst(12, 8191)
        p.if_(0, "LE", 12, quiet, loud, kind="i")
        inp(p, 0, 7)                                    # CLIP
        fl(p, 4, 0)
        K.mul_k(p, 5, 4, 125.0)
        p.fconst(12, float(0x1FFFFF))
        p.fop(6, 12, "-", 5)
        K.mul_k(p, 6, 6, Q)
        ws(p, 8, 6)
        K.add_k(p, 6, 5, -float(0x200000))
        K.mul_k(p, 6, 6, Q)
        ws(p, 9, 6)
        imul(p, 1, 0, y=0)
        p.lsh(1, 1, -14)
        fl(p, 6, 1)
        K.mul_k(p, 6, 6, 511 * Q)
        ws(p, 10, 6)

        def open_():
            p.fconst(6, K.TOP)
            ws(p, 6, 6)
            p.fconst(6, -1.0)
            ws(p, 7, 6)

        def narrow():
            K.mul_k(p, 5, 4, 100.0)
            p.fconst(12, float(0x1C7FFF))
            p.fop(6, 12, "-", 5)
            K.mul_k(p, 6, 6, Q)
            ws(p, 6, 6)
            K.add_k(p, 6, 5, -float(0x1C8000))
            K.mul_k(p, 6, 6, Q)
            ws(p, 7, 6)
        p.iconst(12, 8191)
        p.if_(0, "LE", 12, open_, narrow, kind="i")

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        M = TRXBD
        p.iconst(0, 0)
        ss(p, M.F1, 0)
        p.iconst(0, 1)
        ss(p, M.F2, 0)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        M = TRXBD
        restart_amp(p, M.AMP)
        p.iconst(0, 10)
        ss(p, M.CNT, 0)
        p.fconst(0, 0x7FFCB9 * Q)
        ss(p, M.RAMP, 0)
        zero(p, (M.PH1, M.PH2, M.CLK))
        w(p, 0, 6)
        ss(p, M.THI, 0)
        ss(p, M.Y0, 0)
        w(p, 0, 7)
        ss(p, M.TLO, 0)
        ss(p, M.Y1, 0)
        w(p, 0, 11)
        ss(p, M.NENV, 0)
        w(p, 0, 13)
        ss(p, M.HARM, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        M, C = TRXBD, L.C
        NZ = K.S0 + M.NZ - K.OUT0                   # the noise, from the output pointer
        # the noise: 11 values, each held three samples, times the env (which then decays)
        s(p, 4, M.NENV)
        p.st(C["e"], 4)
        w(p, 5, 12)
        K.mpy_floor(p, 6, 5, 4)
        ss(p, M.NENV, 6)
        p.ld(0, C["mdb"])
        iadd_k(p, 0, 0, 4 * (K.S0 + M.NZ))
        p.seti(5, 0)

        def nz():
            K.fib(p, L, M.F1, M.F2, 4)
            p.ld(5, C["e"])
            p.fop(4, 4, "*", 5)
            for _ in range(3):
                p.stpost(5, 4)
        p.loop(C["n2"], 11, nz)

        def click(_n=None):
            s(p, 6, M.CLK)
            iadd_k(p, 7, 6, 32)
            ss(p, M.CLK, 7)
            w(p, 7, 2)
            K.mul_k(p, 7, 7, 4.0)
            p.st(C["a"], 7)

            def one():
                K.table_f(p, L, 4, "TRXBD_CLICK2", 6)
                p.ld(7, C["a"])
                p.fop(4, 4, "*", 7)
                K.table_f(p, L, 5, "TRXBD_CLICK1", 6)
                K.mul_k(p, 5, 5, 0x7FFCB9 * Q)
                p.fop(4, 4, "+", 5)
                p.ldi(5, NZ, 5)
                p.fop(4, 4, "+", 5)
                K.sat(p, 4)
                iadd_k(p, 6, 6, 1)
            out_loop(p, L, one)

        def body():
            # the increments (sine indices << 17), from the ramp before its decay
            s(p, 4, M.RAMP)
            w(p, 5, 4)
            fl(p, 5, 5)
            p.fop(5, 5, "*", 4)
            K.mul_k(p, 5, 5, 2.0 ** 16)             # ramp * depth / 2, in phase units
            p.trunc(5, 5)
            w(p, 6, 3)
            p.lsh(8, 6, 11)
            p.iop(7, 8, "+", 5)
            p.st(C["a"], 7)
            p.lsh(8, 6, 10)
            p.iop(7, 8, "+", 5)
            p.st(C["b"], 7)
            w(p, 5, 5)
            K.mpy_floor(p, 6, 4, 5)
            ss(p, M.RAMP, 6)
            s(p, 4, M.HARM)                          # the harmonic's level, then its decay
            p.st(C["c"], 4)
            p.fconst(5, 0x7FDBB4 * Q)
            K.mpy_floor(p, 6, 4, 5)
            ss(p, M.HARM, 6)
            s(p, 4, M.THI)                           # this block's thresholds; they widen
            p.st(C["d"], 4)
            K.add_k(p, 4, 4, 50 * Q)
            K.sat(p, 4)
            ss(p, M.THI, 4)
            s(p, 4, M.TLO)
            p.st(C["f"], 4)
            K.add_k(p, 4, 4, -50 * Q)
            K.sat(p, 4)
            ss(p, M.TLO, 4)
            s(p, 1, M.PH1)
            s(p, 2, M.PH2)
            s(p, 3, M.Y0)
            s(p, 5, M.Y1)
            s(p, 6, M.AMP)

            def one():
                K.sine(p, L, 4, 1)                   # osc1 = sine >> 2
                p.ld(8, C["a"])
                p.iop(1, 8, "+", 1)
                K.mul_k(p, 4, 4, 0.25)
                K.sine(p, L, 7, 2)                   # osc2 = sat(2 sine)
                p.ld(8, C["b"])
                p.iop(2, 8, "+", 2)
                p.fop(7, 7, "+", 7)
                K.sat(p, 7)
                p.ld(8, C["c"])                      # x = sat(osc1 + osc2 harm / 16)
                p.fop(7, 7, "*", 8)
                K.mul_k(p, 7, 7, 1.0 / 16)
                p.fop(4, 4, "+", 7)
                K.sat(p, 4)
                K.mul_k(p, 7, 4, -0.5)               # the slew stage, on -x/2
                p.ld(8, C["d"])
                p.ld(9, C["f"])
                p.fconst(10, 50 * Q)

                def above():
                    p.fop(7, 3, "-", 10)
                    p.fpass(5, 9)
                    p.fpass(3, 7)
                    K.sat(p, 3)

                def below():
                    p.fop(7, 5, "+", 10)
                    p.fpass(3, 8)
                    p.fpass(5, 7)
                    K.sat(p, 5)
                p.if_(7, "GT", 8, above, lambda: p.if_(7, "LT", 9, below))
                p.fop(4, 7, "+", 7)
                K.sat(p, 4)
                p.ldi(9, NZ, 5)                      # x = sat(env x + noise env)
                p.fop(9, 9, "*", 6)
                p.fop(4, 4, "*", 6)
                p.fop(4, 4, "+", 9)
                K.sat(p, 4)
                w(p, 8, 1)
                one_minus(p, 8)
                env_mul(p, 6, 8, 9, 10, 8)
                w(p, 8, 8)                           # the soft clipper
                w(p, 10, 9)
                p.fpass(9, 4)

                def over():
                    p.fop(9, 4, "-", 8)
                    K.sat(p, 9)
                    p.fop(9, 9, "*", 8)
                    p.fop(9, 9, "+", 8)

                def under():
                    p.fop(9, 4, "-", 10)
                    K.sat(p, 9)
                    p.fop(9, 9, "*", 8)
                    p.fop(9, 9, "+", 10)
                p.if_(4, "GE", 8, over, lambda: p.if_(4, "LE", 10, under))
                p.fpass(11, 9)
                K.sat(p, 11)
                w(p, 8, 10)
                p.fop(11, 11, "*", 8)
                p.fop(9, 9, "+", 11)
                K.sat(p, 9)
                p.fop(4, 4, "+", 9)                  # out = sat(2 (y + x))
                p.fop(4, 4, "+", 4)
                K.sat(p, 4)
            out_loop(p, L, one)
            ss(p, M.PH1, 1)
            ss(p, M.PH2, 2)
            ss(p, M.Y0, 3)
            ss(p, M.Y1, 5)
            ss(p, M.AMP, 6)
            ss(p, M.LAST, 4)
        trig_count(p, M.CNT, 9, lambda: fade_block(p, L, M.LAST), click, body)


# =====================================================================================
class TRXB2:
    """TRX-B2: the phase-distortion kick (md_models.TRXB2). Words: W1 pitch (int), W2 ramp
    start (int), W3 decay, W4 hold decay, W5..W8 the warp's slopes, W9 the crusher's shift
    (int), W10 its offset, W11 noise level, W12 tick level.
    State: the ramp env (int), the phase (int, 23 bits), the attack add, the noise env and
    generator, the hold env, the amp env, the tick env."""
    NAME, ID = "TRX-B2", 28
    PNAMES = ("PTCH", "DEC", "RAMP", "HOLD", "TICK", "NOIS", "DIRT", "DIST")
    RAMP, PH, ATK, NENV, F1, F2, HOLD, AMP, TICK = range(9)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                     # PTCH: 9 (tblP - 2048) + 1902
        p.lsh(0, 0, -7)
        K.table_f(p, L, 1, "hostP", 0)
        iadd_k(p, 1, 1, -2048)
        p.lsh(8, 1, 3)
        p.iop(1, 8, "+", 1)
        iadd_k(p, 1, 1, 1902)
        ws(p, 1, 1)
        inp(p, 0, 2)                                     # RAMP
        imul(p, 1, 0, k=76087)
        p.lsh(1, 1, -14)
        ws(p, 2, 1)
        inp(p, 0, 1)                                     # DEC
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, 3.0)
        p.trunc(1, 4)
        p.lsh(1, 1, -7)
        iadd_k(p, 1, 1, 100)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 3, 4)
        inp(p, 0, 3)                                     # HOLD
        p.lsh(1, 0, -6)
        iadd_k(p, 1, 1, 200)
        K.table_f(p, L, 4, "hostQ", 1)
        ws(p, 4, 4)
        inp(p, 0, 7)                                     # DIST: q = DIST^2 >> 12
        imul(p, 1, 0, y=0)
        p.lsh(1, 1, -12)
        fl(p, 4, 1)
        for k, (a, b) in zip((5, 6, 7, 8), ((-60, -32768), (70, 32768), (-50, -32768), (40, 32768))):
            K.mul_k(p, 5, 4, a * Q)
            K.add_k(p, 5, 5, b * Q)
            ws(p, k, 5)
        inp(p, 0, 6)                                     # DIRT: 24 tblR / 158987
        p.lsh(0, 0, -7)
        K.table_f(p, L, 4, "hostR", 0)
        K.mul_k(p, 4, 4, 24.0 * 2.0 ** 23)               # r (exact)
        K.mul_k(p, 5, 4, 1.0 / 158987)
        p.trunc(1, 5)
        for _ in range(2):                               # the quotient, made exact
            iadd_k(p, 2, 1, 1)
            fl(p, 5, 2)
            K.mul_k(p, 5, 5, 158987.0)
            p.if_(5, "LE", 4, lambda: p.ipass(1, 2))
        fl(p, 5, 1)
        K.mul_k(p, 5, 5, 158987.0)
        p.if_(5, "GT", 4, lambda: iadd_k(p, 1, 1, -1))
        ws(p, 9, 1)

        def off():                                       # 2^(n-1) (n = 0: 0), a Q23 word
            iadd_k(p, 2, 1, -24)
            p.iconst(3, 1)
            p.float_(4, 3, 2)
            ws(p, 10, 4)
        p.ifz(1, "NE", off, lambda: (p.fconst(4, 0.0), ws(p, 10, 4)))
        inp(p, 0, 5)                                     # NOIS
        fl(p, 4, 0, -14)
        ws(p, 11, 4)
        inp(p, 0, 4)                                     # TICK
        fl(p, 4, 0, -15)
        ws(p, 12, 4)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        M = TRXB2
        p.iconst(0, 0x12E70C)
        ss(p, M.F1, 0)
        p.iconst(0, 0x1914A5)
        ss(p, M.F2, 0)
        p.fconst(0, K.TOP)
        ss(p, M.HOLD, 0)
        zero(p, (M.AMP, M.NENV, M.ATK), f=True)
        zero(p, (M.RAMP, M.PH))

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        M = TRXB2
        w(p, 0, 2)
        ss(p, M.RAMP, 0)
        p.fconst(0, 0x147AE * Q)
        ss(p, M.ATK, 0)
        w(p, 0, 11)
        ss(p, M.NENV, 0)
        w(p, 0, 12)
        ss(p, M.TICK, 0)
        p.fconst(0, K.TOP)
        ss(p, M.HOLD, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        M, C = TRXB2, L.C
        s(p, 4, M.NENV)                                  # the noise env decays first
        p.fconst(5, 0x75C28F * Q)
        K.mpy_floor(p, 6, 4, 5)
        ss(p, M.NENV, 6)
        p.st(C["f"], 6)
        s(p, 4, M.HOLD)                                  # the hold env picks the decay
        w(p, 5, 4)
        K.mpy_floor(p, 6, 4, 5)
        ss(p, M.HOLD, 6)
        p.fconst(7, 0x147AE * Q)
        p.if_(6, "GE", 7, lambda: p.fconst(4, 0x7FFFF8 * Q), lambda: w(p, 4, 3))
        p.fconst(12, 1.0)
        p.fop(4, 12, "-", 4)                             # 1 - dec (exact)
        p.st(C["c"], 4)
        w(p, 0, 9)                                       # the crusher's scales 2^(23-n), 2^(n-23)
        p.iconst(2, 1)
        p.iconst(12, 23)
        p.iop(1, 12, "-", 0)
        p.float_(4, 2, 1)
        p.st(C["d"], 4)
        iadd_k(p, 1, 0, -23)
        p.float_(4, 2, 1)
        p.st(C["e"], 4)
        s(p, 1, M.PH)
        s(p, 2, M.RAMP)
        s(p, 3, M.AMP)
        s(p, 5, M.ATK)
        s(p, 6, M.TICK)
        p.iconst(7, 0)

        def seg(word, oa, neg, add):
            """R10 = the sine index of the warp's segment: floor(+-max(Wq (ph - oa), -8191))
            + add."""
            w(p, 9, word)
            fl(p, 10, 1)
            if oa:
                K.add_k(p, 10, 10, -float(oa))
            p.fop(10, 10, "*", 9)
            p.fconst(12, -8191.0)
            p.fop(10, 10, "MAX", 12)
            if neg:
                K.mul_k(p, 10, 10, -1.0)
                p.trunc(10, 10)
                iadd_k(p, 10, 10, add)
            else:
                K.add_k(p, 10, 10, 8192.0)
                p.trunc(10, 10)
                iadd_k(p, 10, 10, add - 8192)

        def one():
            fl(p, 8, 2)                                  # ramp env (a sample): y0 - ceil(y0 d)
            K.mul_k(p, 8, 8, -0x1062 * Q)
            ffloor(p, 8, 9, 10)
            p.trunc(9, 8)
            p.iop(2, 9, "+", 2)
            w(p, 8, 1)
            p.iop(1, 8, "+", 1)
            p.ipass(8, 2)
            p.iop(1, 8, "+", 1)
            p.iconst(12, 0x7FFFFF)
            p.iop(1, 1, "AND", 12)
            p.iconst(12, 0x400000)                       # the warp
            p.iop(8, 1, "AND", 12)

            def upper():
                p.iconst(12, 0x200000)
                p.iop(8, 1, "AND", 12)
                p.ifz(8, "NE", lambda: seg(8, 1 << 23, False, 0x8000),
                      lambda: seg(7, 1 << 22, True, 0x4000))

            def lower():
                p.iconst(12, 0x200000)
                p.iop(8, 1, "AND", 12)
                p.ifz(8, "NE", lambda: seg(6, 1 << 22, False, 0x4000),
                      lambda: seg(5, 0, True, 0))
            p.ifz(8, "NE", upper, lower)
            p.iconst(12, 0x7FFF)
            p.iop(10, 10, "AND", 12)
            K.table_f(p, L, 4, "sine", 10)
            w(p, 9, 10)                                  # the crusher
            p.fop(4, 4, "+", 9)
            p.ld(9, C["d"])
            p.fop(4, 4, "*", 9)
            ffloor(p, 4)
            p.ld(9, C["e"])
            p.fop(4, 4, "*", 9)
            K.sat(p, 4)
            p.iconst(12, 3)                              # noise: a value every 4th sample
            p.iop(8, 7, "AND", 12)
            p.ifz(8, "EQ", lambda: K.fib(p, L, M.F1, M.F2, 9), lambda: p.fconst(9, 0.0))
            iadd_k(p, 7, 7, 1)
            p.ld(10, C["c"])                             # amp env: attack until 0.5, decay
            env_mul(p, 3, 10, 11, 13, 14)
            p.fop(3, 3, "+", 5)
            p.fconst(12, 0.5)
            p.if_(3, "GE", 12, lambda: p.fconst(5, 0.0))
            K.sat(p, 3)
            p.fop(4, 4, "*", 3)
            p.fconst(12, FADE)                           # the tick
            p.fop(10, 6, "*", 12)
            p.fpass(6, 10)
            grid(p, 6)
            K.mul_k(p, 10, 10, 8.0)
            p.fop(4, 4, "+", 10)
            p.ld(11, C["f"])
            p.fop(9, 9, "*", 11)
            p.fop(4, 4, "+", 9)
            K.sat(p, 4)
        out_loop(p, L, one)
        ss(p, M.PH, 1)
        ss(p, M.RAMP, 2)
        ss(p, M.AMP, 3)
        K.sat(p, 5)
        ss(p, M.ATK, 5)
        ss(p, M.TICK, 6)


# =====================================================================================
class TRXSD:
    """TRX-SD: the analog-style snare (md_models.TRXSD). Words: W1 amp decay, W2 noise
    decay, W3/W4 osc levels, W5 snap level, W6 noise mix, W7/W8 osc increments (int), W9
    drive decay, W10 bump rate, W11 noise filter index (int), W12 bump decay.
    State: amp env, noise env, bump, sample count (int), two phases, last sample, noise
    generator, the two resonators' outputs, the drive env."""
    NAME, ID = "TRX-SD", 17
    PNAMES = ("PTCH", "DEC", "BUMP", "BENV", "SNAP", "TONE", "TUNE", "CLIP")
    AMP, NENV, BUMP, CNT, PH1, PH2, LAST, F1, F2, RA2, RA1, RB2, RB1, DRIVE = range(14)
    CNT_MAX = 0x10000            # the count stops here (the firmware's wraps at 2^23)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                     # PTCH
        p.lsh(0, 0, -2)
        iadd_k(p, 1, 0, 4096)
        ws(p, 7, 1)
        p.lsh(2, 0, -3)
        iadd_k(p, 2, 2, 1024)
        ws(p, 11, 2)
        p.lsh(1, 1, -6)                                  # TUNE: (W7 >> 6)((TUNE >> 9) + 185) >> 1
        fl(p, 4, 1)
        inp(p, 3, 6)
        p.lsh(3, 3, -9)
        iadd_k(p, 3, 3, 185)
        fl(p, 5, 3)
        p.fop(4, 4, "*", 5)
        p.trunc(1, 4)
        p.lsh(1, 1, -1)
        ws(p, 8, 1)
        inp(p, 0, 1)                                     # DEC
        p.lsh(0, 0, -7)
        iadd_k(p, 1, 0, 220)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 1, 4)
        p.lsh(1, 0, -1)
        iadd_k(p, 1, 1, 232)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 2, 4)
        inp(p, 0, 4)                                     # SNAP
        fl(p, 4, 0, -14)
        ws(p, 5, 4)

        def mix():
            iadd_k(p, 1, 0, -8192)
            imul(p, 2, 1, y=1)
            p.lsh(2, 2, -14)
            fl(p, 4, 2, -13)
            ws(p, 6, 4)
        p.iconst(12, 8191)
        p.if_(0, "LE", 12, lambda: (p.fconst(4, 0.0), ws(p, 6, 4)), mix, kind="i")
        inp(p, 0, 5)                                     # TONE
        fl(p, 4, 0, -15)
        ws(p, 4, 4)
        p.fconst(12, K.TOP)
        p.fop(5, 12, "-", 4)
        ws(p, 3, 5)
        inp(p, 0, 2)                                     # BUMP
        imul(p, 1, 0, y=0)
        p.lsh(1, 1, -18)
        fl(p, 4, 1, -23)
        ws(p, 10, 4)
        inp(p, 0, 3)                                     # BENV
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, 5.0)
        p.trunc(1, 4)
        p.lsh(1, 1, -10)
        iadd_k(p, 1, 1, 15)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 12, 4)
        inp(p, 0, 7)                                     # CLIP
        imul(p, 1, 0, k=25267)
        p.lsh(1, 1, -21)
        iadd_k(p, 1, 1, 120)
        K.table_f(p, L, 4, "hostQ", 1)
        ws(p, 9, 4)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        M = TRXSD
        p.iconst(0, 0x29A)
        ss(p, M.F1, 0)
        p.iconst(0, 1)
        ss(p, M.F2, 0)
        zero(p, (M.RA2, M.RA1, M.RB2, M.RB1), f=True)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        M = TRXSD
        restart_amp(p, M.AMP)
        p.fconst(0, 0x7EB852 * Q)
        ss(p, M.DRIVE, 0)
        s(p, 4, M.LAST)                                  # noise env: 0.6 + 16 |last|
        K.mul_k(p, 5, 4, -1.0)
        p.fop(4, 4, "MAX", 5)
        K.mul_k(p, 4, 4, 16.0)
        K.add_k(p, 4, 4, 0x4CCCCD * Q)
        K.sat(p, 4)
        ss(p, M.NENV, 4)
        zero(p, (M.BUMP,), f=True)
        zero(p, (M.CNT, M.PH1, M.PH2))

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        M, C = TRXSD, L.C
        s(p, 4, M.BUMP)                                  # increments: (W7/2 + bump) / 16 indices
        K.mul_k(p, 4, 4, 2.0 ** 36)
        p.trunc(5, 4)
        w(p, 6, 7)
        p.lsh(8, 6, 12)
        p.iop(7, 8, "+", 5)
        p.st(C["a"], 7)
        w(p, 6, 8)
        p.lsh(8, 6, 12)
        p.iop(7, 8, "+", 5)
        p.st(C["b"], 7)

        def attack():
            s(p, 4, M.BUMP)
            w(p, 5, 10)
            p.fop(4, 4, "+", 5)
            p.fop(4, 4, "+", 5)
            K.sat(p, 4)
            ss(p, M.BUMP, 4)

        def decay():
            s(p, 4, M.BUMP)
            w(p, 5, 12)
            K.mpy_floor(p, 6, 5, 4)
            ss(p, M.BUMP, 6)
        s(p, 0, M.CNT)
        p.iconst(12, 320)
        p.if_(0, "LE", 12, attack, decay, kind="i")
        s(p, 4, M.DRIVE)                                 # the drive, then its decay
        p.st(C["c"], 4)
        w(p, 5, 9)
        K.mpy_floor(p, 6, 5, 4)
        ss(p, M.DRIVE, 6)
        w(p, 0, 11)                                      # the resonators' coefficients
        x14(p, L, 4, 0, 0x900 - 3)                       # t1
        x14(p, L, 5, 0, 0x1900 - 0x241)                  # t2
        K.mul_k(p, 6, 5, -1.0)
        smpy(p, 7, 5, 6, 8, 9, 10)
        K.sat(p, 7)                                      # c1 = sat(-t2^2)
        p.st(C["e"], 7)
        K.mul_k(p, 6, 5, 2.0)
        smpy(p, 8, 4, 6, 9, 10, 11)
        K.sat(p, 8)                                      # g = sat(A0), A0 = 2 t1 t2
        p.st(C["f"], 8)
        K.mul_k(p, 6, 5, -2.0)
        smpy(p, 9, 4, 6, 8, 10, 11)                      # floor(-A0)
        K.add_k(p, 9, 9, 0.5)
        p.fop(9, 9, "-", 7)
        K.sat(p, 9)                                      # c0 = sat(0.5 - A0 - c1)
        p.st(C["d"], 9)
        s(p, 0, M.CNT)                                   # the snap table, for 4128 samples
        p.iconst(12, 0xFE0)
        p.if_(0, "LE", 12, lambda: (w(p, 4, 5), p.st(C["g"], 4), p.ipass(10, 0)),
              lambda: (p.fconst(4, 0.0), p.st(C["g"], 4), p.iconst(10, 0)), kind="i")
        iadd_k(p, 0, 0, 32)
        p.iconst(12, M.CNT_MAX)
        p.iop(0, 0, "MIN", 12)
        ss(p, M.CNT, 0)
        s(p, 1, M.PH1)
        s(p, 2, M.PH2)
        s(p, 3, M.AMP)
        s(p, 5, M.NENV)
        s(p, 6, M.RA1)
        s(p, 7, M.RA2)
        s(p, 8, M.RB1)
        s(p, 9, M.RB2)

        def one():
            K.sine(p, L, 4, 1)                           # o1
            w(p, 11, 3)
            p.fop(4, 4, "*", 11)
            p.ld(14, C["a"])
            p.iop(1, 14, "+", 1)
            K.sine(p, L, 11, 2)                          # o2
            w(p, 14, 4)
            p.fop(11, 11, "*", 14)
            p.ld(14, C["b"])
            p.iop(2, 14, "+", 2)
            p.ld(14, C["c"])                             # x = sat(o1 + o2 + 64 drive (o1 + o2))
            p.fop(15, 4, "*", 14)
            p.fop(14, 11, "*", 14)
            p.fop(15, 15, "+", 14)
            K.mul_k(p, 15, 15, 64.0)
            p.fop(4, 4, "+", 11)
            p.fop(15, 15, "+", 4)
            K.sat(p, 15)
            p.fop(15, 15, "*", 3)                        # amp env
            w(p, 14, 1)
            one_minus(p, 14)
            env_mul(p, 3, 14, 4, 11, 14)
            K.fib(p, L, M.F1, M.F2, 11)                  # noise -> two resonators
            resonance(p, L, 11, 6, 7, C)
            resonance(p, L, 11, 8, 9, C)
            p.fop(11, 11, "*", 5)                        # noise env
            w(p, 14, 2)
            one_minus(p, 14)
            env_mul(p, 5, 14, 4, 13, 14)
            w(p, 14, 6)
            p.fop(11, 11, "*", 14)
            p.fop(15, 15, "+", 11)
            K.sat(p, 15)
            K.table_f(p, L, 11, "SNAP100881", 10)        # the snap
            p.ld(14, C["g"])
            p.fop(11, 11, "*", 14)
            p.fop(4, 15, "+", 11)
            K.sat(p, 4)
            iadd_k(p, 10, 10, 1)
        out_loop(p, L, one)
        ss(p, M.PH1, 1)
        ss(p, M.PH2, 2)
        ss(p, M.AMP, 3)
        ss(p, M.NENV, 5)
        ss(p, M.RA1, 6)
        ss(p, M.RA2, 7)
        ss(p, M.RB1, 8)
        ss(p, M.RB2, 9)
        ss(p, M.LAST, 4)


# =====================================================================================
class TRXXT:
    """TRX-XT: the analog-style tom (md_models.TRXXT). Words: W1 amp decay, W2 pitch (int),
    W3 ramp depth (int), W4/W5 slew thresholds, W6 slew step, W7 ramp decay; on a note also
    W8 the start level (the amp env itself: render writes it back) and W9 the click level.
    State: the trigger count, the ramp env, the slew state, the phase, the last sample."""
    NAME, ID = "TRX-XT", 18
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "DAMP", "DIST", "DTYP", "-")
    CNT, RAMP, Y0, Y1, PH, LAST = range(6)
    OCT, PADD, DMUL = 0, 96, 55.0
    CLICK1, CLICK2 = "TRXXT_CLICK1", "TRXXT_CLICK2"

    @classmethod
    def host(cls, p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                     # PTCH
        p.lsh(0, 0, -6)
        if cls.PADD:
            iadd_k(p, 0, 0, cls.PADD)
        pitch_word(p, L, 4, 0, cls.OCT)
        p.trunc(4, 4)
        ws(p, 2, 4)
        inp(p, 0, 1)                                     # DEC
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, cls.DMUL)
        p.trunc(1, 4)
        p.lsh(1, 1, -12)
        iadd_k(p, 1, 1, 200)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 1, 4)
        inp(p, 0, 2)                                     # RAMP
        iadd_k(p, 1, 0, 3)
        p.lsh(1, 1, -6)
        ws(p, 3, 1)
        inp(p, 0, 3)                                     # RDEC
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, 15.0)
        K.add_k(p, 4, 4, 8134709.0)
        K.mul_k(p, 4, 4, Q)
        ws(p, 7, 4)
        inp(p, 0, 5)                                     # DIST
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, 384 * Q)
        p.fconst(12, K.TOP)
        p.fop(5, 12, "-", 4)
        ws(p, 4, 5)
        p.fop(5, 4, "-", 12)
        ws(p, 5, 5)
        inp(p, 0, 6)                                     # DTYP
        imul(p, 1, 0, y=0)
        p.lsh(1, 1, -13)
        p.iconst(12, -2)
        p.iop(1, 1, "AND", 12)
        fl(p, 4, 1, -23)
        ws(p, 6, 4)

        def damp():                                      # DAMP: on a note only
            inp(p, 0, 4)
            fl(p, 4, 0, -15)
            p.fconst(12, K.TOP)
            p.fop(5, 12, "-", 4)
            ws(p, 8, 5)
            K.add_k(p, 5, 4, 0.5)
            ws(p, 9, 5)
        K.vw(p, 0, "trg")
        p.ifz(0, "NE", damp)

    @classmethod
    def init(cls, p: Prog, L: K.Layout) -> None:
        pass

    @classmethod
    def trig(cls, p: Prog, L: K.Layout) -> None:
        p.iconst(0, 3)
        ss(p, cls.CNT, 0)
        p.fconst(0, 0x7FFCB9 * Q)
        ss(p, cls.RAMP, 0)
        p.iconst(0, 0)
        ss(p, cls.PH, 0)
        w(p, 0, 4)
        ss(p, cls.Y0, 0)
        w(p, 0, 5)
        ss(p, cls.Y1, 0)

    @classmethod
    def render(cls, p: Prog, L: K.Layout) -> None:
        M, C = cls, L.C

        def click_block(name):
            if name is None:
                out_loop(p, L, lambda: p.fconst(4, 0.0))
                return
            p.iconst(6, 0)
            w(p, 7, 9)

            def one():
                K.table_f(p, L, 4, name, 6)
                p.fop(4, 4, "*", 7)
                iadd_k(p, 6, 6, 1)
            out_loop(p, L, one)

        def rest():
            p.iconst(12, 1)
            p.if_(0, "EQ", 12, lambda: click_block(M.CLICK1), lambda: click_block(M.CLICK2),
                  kind="i")

        def body():
            s(p, 4, M.RAMP)                              # inc = W2/64 + ramp W3 indices
            w(p, 5, 3)
            fl(p, 5, 5)
            p.fop(5, 5, "*", 4)
            K.mul_k(p, 5, 5, 2.0 ** 17)
            p.trunc(5, 5)
            w(p, 6, 2)
            p.lsh(8, 6, 11)
            p.iop(5, 8, "+", 5)
            split_inc(p, 5, 6)
            p.st(C["a"], 5)
            p.st(C["b"], 6)
            w(p, 5, 7)                                   # the ramp decays (a block)
            K.mpy_floor(p, 6, 4, 5)
            ss(p, M.RAMP, 6)
            w(p, 4, 1)                                   # 1 - the amp decay
            p.fconst(12, 1.0)
            p.fop(4, 12, "-", 4)
            p.st(C["c"], 4)
            s(p, 1, M.PH)
            p.ld(3, C["b"])
            w(p, 2, 8)
            s(p, 5, M.Y0)
            s(p, 6, M.Y1)

            def one():
                quirk(p, L, 4, 1, 3, C["a"])
                p.fop(4, 4, "*", 2)                      # amp env (in W8)
                p.ld(8, C["c"])
                env_mul(p, 2, 8, 9, 10, 8)
                K.mul_k(p, 7, 4, -1.0)                   # the slew stage, on -x
                w(p, 8, 4)
                w(p, 9, 5)
                w(p, 10, 6)

                def above():
                    p.fop(7, 5, "-", 10)
                    p.fpass(6, 9)
                    p.fpass(5, 7)
                    K.sat(p, 5)

                def below():
                    p.fop(7, 6, "+", 10)
                    p.fpass(5, 8)
                    p.fpass(6, 7)
                    K.sat(p, 6)
                p.if_(7, "GE", 8, above, lambda: p.if_(7, "LE", 9, below))
                p.fpass(4, 7)
                K.sat(p, 4)
            out_loop(p, L, one)
            ss(p, M.PH, 1)
            ws(p, 8, 2)
            ss(p, M.Y0, 5)
            ss(p, M.Y1, 6)
            ss(p, M.LAST, 4)
        trig_count(p, M.CNT, 2, lambda: fade_block(p, L, M.LAST), rest, body)


class TRXXC(TRXXT):
    """TRX-XC: the TRX-XT engine, a pitch an octave and a half lower, its own decay scale,
    and a silent first click block then its own click (md_models.TRXXC)."""
    NAME, ID = "TRX-XC", 27
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "DAMP", "DIST", "DTYP", "-")
    OCT, PADD, DMUL = 1, 0, 40.0
    CLICK1, CLICK2 = None, "TRXXC_CLICK"


# =====================================================================================
def hp_stage(p: Prog, C, x: int, d: int, Y1: int, Y2: int, u1: int, u2: int) -> None:
    """One sample of TRX-CL's high-pass biquad (md_models.biquad_hp): Fd = sat(2 (cb y2 +
    g y1 + u2/2 - u1 + x/2)), cb and g in C['c'], C['d'], the outputs y1, y2 in state
    words Y1, Y2, the inputs u1, u2 in registers. Clobbers R12-R15."""
    s(p, 14, Y2)
    p.ld(13, C["c"])
    p.fop(13, 13, "*", 14)
    s(p, 14, Y1)
    p.ld(15, C["d"])
    p.fop(15, 15, "*", 14)
    p.fop(13, 13, "+", 15)
    p.fconst(12, 0.5)
    p.fop(15, u2, "*", 12)
    p.fop(13, 13, "+", 15)
    p.fop(13, 13, "-", u1)
    p.fop(15, x, "*", 12)
    p.fop(13, 13, "+", 15)
    p.fop(d, 13, "+", 13)
    K.sat(p, d)


class TRXCL:
    """TRX-CL: the analog-style clave (md_models.TRXCL). Words (on a note only): W1 amp
    decay, W2 the DUAL delay (int, counted down in place), W3/W4 osc increments (int),
    W5/W6 the filter's tune and index (int), W7 osc2 level, W8 the click level.
    State: amp env, the two phases, the filter's history."""
    NAME, ID = "TRX-CL", 26
    PNAMES = ("PTCH", "DEC", "DUAL", "ENH", "TUNE", "CLIC", "-", "-")
    AMP, PH1, PH2, H1, H2, G1, G2, U1, U2 = range(9)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        def words():
            inp(p, 0, 0)                                 # PTCH
            imul(p, 1, 0, k=52429)
            p.lsh(1, 1, -18)
            iadd_k(p, 1, 1, 1400)
            ws(p, 3, 1)
            imul(p, 1, 0, k=36765)                       # q
            p.lsh(1, 1, -16)
            p.iop(2, 0, "-", 1)                          # ((x - q) >> 1) + q
            p.lsh(2, 2, -1)
            p.ipass(12, 1)
            p.iop(2, 12, "+", 2)
            p.lsh(2, 2, -5)
            iadd_k(p, 2, 2, 1112)
            ws(p, 5, 2)
            inp(p, 0, 1)                                 # DEC
            fl(p, 4, 0)
            K.mul_k(p, 4, 4, 40.0)
            p.trunc(1, 4)
            p.lsh(1, 1, -12)
            iadd_k(p, 1, 1, 200)
            K.table_f(p, L, 4, "hostD", 1)
            ws(p, 1, 4)
            inp(p, 0, 2)                                 # DUAL
            iadd_k(p, 1, 0, 500)
            p.lsh(1, 1, -5)
            ws(p, 2, 1)
            inp(p, 0, 3)                                 # ENH
            p.lsh(1, 0, -8)
            iadd_k(p, 1, 1, 64)
            ws(p, 6, 1)
            inp(p, 0, 4)                                 # TUNE
            imul(p, 1, 0, k=52429)
            p.lsh(1, 1, -18)
            iadd_k(p, 1, 1, 1400)
            ws(p, 4, 1)
            fl(p, 4, 0, -15)
            K.add_k(p, 4, 4, 0.125)
            ws(p, 7, 4)
            inp(p, 0, 5)                                 # CLIC
            fl(p, 4, 0, -14)
            K.mul_k(p, 4, 4, -1.0)
            ws(p, 8, 4)
        K.vw(p, 0, "trg")
        p.ifz(0, "NE", words)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        M = TRXCL
        zero(p, (M.AMP, M.H1, M.H2, M.G1, M.G2, M.U1, M.U2), f=True)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        M = TRXCL
        restart_amp(p, M.AMP)
        zero(p, (M.PH1, M.PH2))

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        M, C = TRXCL, L.C
        w(p, 0, 6)                                       # the biquad's coefficients
        K.table_f(p, L, 4, "X140000", 0)
        K.mul_k(p, 4, 4, 2.0 ** 23)
        p.trunc(1, 4)
        w(p, 8, 5)
        p.iop(1, 8, "+", 1)                              # r1 = W5 + T[W6]
        x14(p, L, 6, 1, 0x900)                           # t1
        iadd_k(p, 2, 0, 0x80)
        K.table_f(p, L, 4, "X140000", 2)
        K.mul_k(p, 4, 4, 2.0 ** 23)
        p.trunc(1, 4)
        w(p, 8, 5)
        p.iop(1, 8, "+", 1)                              # r2 = W5 + T[$80 + W6]
        x14(p, L, 7, 1, 0x1900)                          # t2
        K.mul_k(p, 8, 7, -1.0)
        smpy(p, 4, 7, 8, 9, 10, 11)
        K.sat(p, 4)
        p.st(C["c"], 4)                                  # cb = sat(-t2^2)
        K.mul_k(p, 8, 7, 2.0)
        smpy(p, 4, 6, 8, 9, 10, 11)
        K.sat(p, 4)
        p.st(C["d"], 4)                                  # g = sat(2 t1 t2)
        w(p, 0, 2)                                       # osc1: the DUAL delay

        def delayed():
            p.ipass(7, 0)
            p.st(C["g"], 7)
            p.iconst(12, 32)
            p.iop(1, 12, "-", 0)                         # (32 - d) indices, fraction 0
            p.lsh(1, 1, 17)
            p.st(C["a"], 1)
            p.iconst(3, 0)
            p.st(C["e"], 3)
            iadd_k(p, 2, 0, -32)
            p.iconst(12, 0)
            p.iop(2, 2, "MAX", 12)
            ws(p, 2, 2)

        def free():
            p.iconst(7, 0)
            p.st(C["g"], 7)
            w(p, 1, 3)
            p.lsh(1, 1, 16)
            split_inc(p, 1, 3)
            p.st(C["a"], 1)
            p.st(C["e"], 3)
        p.ifz(0, "NE", delayed, free)
        w(p, 1, 4)                                       # osc2
        p.lsh(1, 1, 16)
        split_inc(p, 1, 5)
        p.st(C["b"], 1)
        p.ld(7, C["g"])
        p.ld(3, C["e"])
        s(p, 1, M.PH1)
        s(p, 2, M.PH2)
        s(p, 6, M.AMP)

        def one():
            def const():
                w(p, 4, 8)
                iadd_k(p, 7, 7, -1)
            p.ifz(7, "GT", const, lambda: quirk(p, L, 4, 1, 3, C["a"]))
            quirk(p, L, 11, 2, 5, C["b"])
            w(p, 8, 7)
            p.fop(11, 11, "*", 8)
            p.fop(4, 4, "+", 11)
            K.sat(p, 4)
            p.fop(4, 4, "*", 6)                          # amp env, / 8
            K.mul_k(p, 4, 4, 0.125)
            w(p, 8, 1)
            one_minus(p, 8)
            env_mul(p, 6, 8, 9, 10, 8)
            s(p, 9, M.U1)                                # stage 1: in u, out H
            s(p, 10, M.U2)
            hp_stage(p, C, 4, 11, M.H1, M.H2, 9, 10)
            ss(p, M.U2, 9)
            ss(p, M.U1, 4)
            s(p, 9, M.H1)                                # stage 2: in H, its history
            s(p, 10, M.H2)                               # stage 1's outputs
            ss(p, M.H2, 9)
            ss(p, M.H1, 11)
            hp_stage(p, C, 11, 8, M.G1, M.G2, 9, 10)
            s(p, 4, M.G2)                                # out: G two samples ago
            s(p, 9, M.G1)
            ss(p, M.G2, 9)
            ss(p, M.G1, 8)
        out_loop(p, L, one)
        ss(p, M.PH1, 1)
        ss(p, M.PH2, 2)
        ss(p, M.AMP, 6)


# =====================================================================================
class TRXRS:
    """TRX-RS: the analog-style rim shot (md_models.TRXRS). Words: W1 amp decay, W2 pitch
    (int), W3 the shaper's threshold, W4 its ramp step.
    State: amp env, the phase (free running), the click count (int), the shaper's ramp,
    the two accumulating biquads' accumulators A, B (48-bit in the firmware: floats here)
    and histories.

    The shaper flips where the sine reaches its threshold, and with DIST 0 the threshold is
    1 - 2^-23, which DSP2's sine reaches only at its trough: there its table is exactly -1
    (k = 24573..24577, the recursion's limiter), where core.sine_fill gives -1 + 11..13 LSB.
    So a sine at or below TROUGH (exactly those five words) is taken as -1 here."""
    NAME, ID = "TRX-RS", 20
    PNAMES = ("PTCH", "DEC", "DIST", "-", "-", "-", "-", "-")
    AMP, PH, CNT, RAMP, A, B, H1, H2, G1, G2, U1, U2 = range(12)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)
        p.lsh(0, 0, -2)
        iadd_k(p, 0, 0, 4096)
        ws(p, 2, 0)
        inp(p, 0, 1)
        fl(p, 4, 0)
        K.mul_k(p, 4, 4, 40.0)
        p.trunc(1, 4)
        p.lsh(1, 1, -12)
        iadd_k(p, 1, 1, 220)
        K.table_f(p, L, 4, "hostD", 1)
        ws(p, 1, 4)
        inp(p, 0, 2)
        fl(p, 4, 0, -18)
        p.fconst(12, K.TOP)
        p.fop(5, 12, "-", 4)
        ws(p, 3, 5)
        K.mul_k(p, 4, 4, 0.5)
        ws(p, 4, 4)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        M = TRXRS
        zero(p, (M.AMP,), f=True)
        p.iconst(0, 0x2000 << K.SINE_SHIFT)
        ss(p, M.PH, 0)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        M = TRXRS
        restart_amp(p, M.AMP)
        zero(p, (M.CNT,))
        zero(p, (M.RAMP, M.H1, M.H2, M.G1, M.G2, M.U1, M.U2), f=True)
        for k in (M.A, M.B):                            # the accumulator's low word stays
            s(p, 4, k)
            p.fpass(5, 4)
            sgrid(p, 5)
            p.fop(4, 4, "-", 5)
            ss(p, k, 4)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        M, C = TRXRS, L.C
        p.iconst(0, 0)                                   # the coefficients (fixed indices)
        K.table_f(p, L, 4, "X140000", 0)
        K.mul_k(p, 4, 4, 2.0 ** 23)
        p.trunc(1, 4)
        x14(p, L, 6, 1, 0x200 + 0x900)                   # t1
        p.iconst(0, 0x80)
        K.table_f(p, L, 4, "X140000", 0)
        K.mul_k(p, 4, 4, 2.0 ** 23)
        p.trunc(1, 4)
        x14(p, L, 7, 1, 0x200 + 0x1900)                  # t2
        K.mul_k(p, 8, 7, -2.0)
        smpy(p, 4, 7, 8, 9, 10, 11)
        K.sat(p, 4)
        p.st(C["c"], 4)                                  # cb = sat(-2 t2^2)
        K.mul_k(p, 8, 7, 2.0)
        smpy(p, 4, 6, 8, 9, 10, 11)
        K.add_k(p, 4, 4, -0.5)
        K.sat(p, 4)
        p.fop(4, 4, "+", 4)
        p.st(C["d"], 4)                                  # 2 g, g = sat(2 t1 t2 - 0.5)
        w(p, 4, 1)                                       # 1 - the amp decay
        p.fconst(12, 1.0)
        p.fop(4, 12, "-", 4)
        p.st(C["e"], 4)
        w(p, 0, 2)
        p.lsh(0, 0, 12)                                  # W2 / 32 indices
        p.st(C["a"], 0)
        s(p, 0, M.CNT)                                   # the click, for 768 samples

        def clicking():
            p.ipass(11, 0)
            iadd_k(p, 0, 0, 32)
            ss(p, M.CNT, 0)
            p.fconst(4, 1.0)
            p.st(C["g"], 4)

        def done():
            p.iconst(11, 0)
            p.fconst(4, 0.0)
            p.st(C["g"], 4)
        p.iconst(12, 0x300)
        p.if_(0, "LT", 12, clicking, done, kind="i")
        s(p, 1, M.PH)
        s(p, 2, M.RAMP)
        s(p, 3, M.AMP)
        s(p, 5, M.A)
        s(p, 6, M.B)
        s(p, 7, M.H1)
        s(p, 8, M.H2)
        s(p, 9, M.G1)
        s(p, 10, M.G2)

        def one():
            K.sine(p, L, 4, 1)
            p.fconst(13, TROUGH)                         # DSP2's table is -1 at its trough
            p.if_(4, "LE", 13, lambda: p.fconst(4, -1.0))
            p.ld(14, C["a"])
            p.iop(1, 14, "+", 1)
            w(p, 13, 3)                                  # the flip shaper

            def up():
                p.fconst(4, 0x7EB852 * Q)
                p.fop(4, 4, "-", 2)
                w(p, 14, 4)
                p.fop(2, 2, "+", 14)

            def down():
                p.fconst(4, -0x7EB852 * Q)
                p.fop(4, 4, "+", 2)
                w(p, 14, 4)
                p.fop(2, 2, "+", 14)

            def low():
                K.mul_k(p, 14, 4, -1.0)
                p.if_(14, "GE", 13, down, lambda: p.fconst(2, 0.0))
            p.if_(4, "GE", 13, up, low)
            K.sat(p, 4)
            K.mul_k(p, 4, 4, 0.5)
            K.table_f(p, L, 14, "TRXRS_CLICK", 11)       # + the click
            p.ld(15, C["g"])
            p.fop(14, 14, "*", 15)
            p.fop(4, 4, "+", 14)
            K.sat(p, 4)
            iadd_k(p, 11, 11, 1)
            p.fop(4, 4, "*", 3)                          # u = amp env x
            sgrid(p, 4)
            p.ld(15, C["e"])
            env_mul(p, 3, 15, 13, 14, 15)
            # stage 1: A += cb H2 + 2g H1 + u2/2 - u1 + u/2; H = floor(sat A)
            s(p, 14, M.U1)
            s(p, 15, M.U2)
            p.ld(13, C["c"])
            p.fop(13, 13, "*", 8)
            p.fop(5, 5, "+", 13)
            p.ld(13, C["d"])
            p.fop(13, 13, "*", 7)
            p.fop(5, 5, "+", 13)
            K.mul_k(p, 15, 15, 0.5)
            p.fop(5, 5, "+", 15)
            p.fop(5, 5, "-", 14)
            K.mul_k(p, 13, 4, 0.5)
            p.fop(5, 5, "+", 13)
            ss(p, M.U2, 14)
            ss(p, M.U1, 4)
            p.fpass(15, 5)
            K.sat(p, 15)
            sgrid(p, 15)                                 # H (= the raw A1 below 1.0)
            # stage 2: B += cb G2 + 2g G1 + H/2 - H1 + H2/2
            p.ld(13, C["c"])
            p.fop(13, 13, "*", 10)
            p.fop(6, 6, "+", 13)
            p.ld(13, C["d"])
            p.fop(13, 13, "*", 9)
            p.fop(6, 6, "+", 13)
            p.fconst(12, 0.5)
            p.fop(13, 15, "*", 12)
            p.fop(6, 6, "+", 13)
            p.fop(6, 6, "-", 7)
            p.fop(13, 8, "*", 12)
            p.fop(6, 6, "+", 13)
            p.fpass(8, 7)
            p.fpass(7, 15)
            p.fpass(4, 6)
            K.sat(p, 4)
            sgrid(p, 4)                                  # G
            p.fop(13, 10, "+", 10)                       # out: 2 G two samples ago
            p.fpass(10, 9)
            p.fpass(9, 4)
            K.sat(p, 13)
            p.fpass(4, 13)
        out_loop(p, L, one)
        ss(p, M.PH, 1)
        K.sat(p, 2)
        ss(p, M.RAMP, 2)
        ss(p, M.AMP, 3)
        K.sat(p, 5)
        ss(p, M.A, 5)
        K.sat(p, 6)
        ss(p, M.B, 6)
        ss(p, M.H1, 7)
        ss(p, M.H2, 8)
        ss(p, M.G1, 9)
        ss(p, M.G2, 10)


MACHINES = (TRXBD, TRXB2, TRXSD, TRXXT, TRXXC, TRXCL, TRXRS)

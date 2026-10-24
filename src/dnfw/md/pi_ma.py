"""P-IMA: the Machinedrum's maraca (a physical model; docs/md.md), from DSP2's P-IMA and
its host scale function.

Each sample: the additive Fibonacci noise; a grain envelope that decays by GLEN a sample
and is kicked by an energy envelope (decaying by DEC) whenever the noise is under the
GRNS threshold; noise x grain x gain into a two-pole resonator (HARD sets its tuning, the
host's input 5 its radius), whose output is differenced.

Exact: every step is the 56300's arithmetic on integer words (pi_ml.xmul, with its
convergent rounding where the firmware rounds), so the machine is bit-exact.

The host's quirks kept: the resonator's radius (and HARD's scale) comes from input 5,
which is not one of P-IMA's parameters (the DN2 passes its sixth knob there); SIZE (input
3) is not used at all.

The host's tables T0..T3 (OS $2462E8, 4 x 128 longs) are `hostA` (rom.HOST_TABLES
"A": (0x2462E8, 512)).
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .pi_ml import clamp, to_word, xmul
from ..perc.dsl import Prog

HALF = 1 << 22


def _a_word(p: Prog, L: K.Layout, d: int, k: int, idx: int) -> None:
    """Rd = the host's table T_k[Ridx] (an integer). Clobbers R12, R13, R14, I1."""
    p.iconst(12, 128 * k)
    p.iop(14, 12, "+", idx)
    K.table_f(p, L, d, "hostA", 14)
    to_word(p, d, d)


class PIMA:
    """Words (integers, 24-bit): W1 GRNS (the noise threshold), W2 the gain (T1[GRNS]
    T2[GLEN]), W3 DEC (the energy's decay a sample), W4 GLEN (the grain's decay a sample),
    W5 the resonator's tuning, W6 its radius squared.
    State: the noise generator, the energy, the grain, the resonator's two words, the
    differencer's word (ints)."""
    NAME, ID = "PI-MA", 68
    PNAMES = ("GRNS", "DEC", "GLEN", "SIZE", "HARD", "-", "-", "-")
    F1, F2, EN, GR, Y1, Y2, YD = range(7)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                    # GRNS
        p.lsh(0, 0, -7)
        _a_word(p, L, 4, 0, 0)
        ws(p, 1, 4)
        _a_word(p, L, 4, 1, 0)
        inp(p, 1, 2)                                    # GLEN
        p.lsh(1, 1, -7)
        _a_word(p, L, 5, 2, 1)
        p.iconst(12, 0)
        p.float_(4, 4, 12)
        p.float_(5, 5, 12)
        p.fop(4, 4, "*", 5)                             # < 2^24: exact
        p.trunc(4, 4)
        ws(p, 2, 4)
        p.iconst(12, 128)
        p.iop(1, 12, "+", 1)
        K.table_f(p, L, 4, "hostD", 1)
        to_word(p, 4, 4)
        ws(p, 4, 4)
        inp(p, 0, 1)                                    # DEC
        p.lsh(0, 0, -7)
        p.iconst(12, 511)
        p.iop(0, 0, "AND", 12)
        p.iconst(12, 256)
        p.iop(0, 12, "+", 0)
        K.table_f(p, L, 4, "hostD", 0)
        to_word(p, 4, 4)
        ws(p, 3, 4)
        inp(p, 0, 5)                                    # input 5: d = tblD[in >> 8] >> 8
        p.lsh(0, 0, -8)
        K.table_f(p, L, 4, "hostD", 0)
        to_word(p, 4, 4)
        p.lsh(4, 4, -8)
        p.lsh(6, 4, -8)                                 # dh
        p.iconst(12, 255)
        p.iop(7, 4, "AND", 12)                          # dl
        inp(p, 0, 4)                                    # HARD: (T3[in >> 7] d) >> 8
        p.lsh(0, 0, -7)
        _a_word(p, L, 4, 3, 0)
        p.iconst(12, 0)
        p.float_(4, 4, 12)
        p.float_(6, 6, 12)
        p.float_(7, 7, 12)
        p.fop(8, 4, "*", 6)                             # T3 dh (exact)
        p.trunc(8, 8)
        p.fop(9, 4, "*", 7)                             # T3 dl (exact)
        p.trunc(9, 9)
        p.ash(9, 9, -8)
        p.iop(8, 8, "+", 9)
        ws(p, 5, 8)
        # d^2 >> 7 = dh^2 2^9 + dh dl 2^2 + (dl^2 >> 7)
        p.fop(8, 6, "*", 6)
        p.trunc(8, 8)
        p.lsh(8, 8, 9)
        p.fop(9, 6, "*", 7)
        p.trunc(9, 9)
        p.lsh(9, 9, 2)
        p.iop(8, 8, "+", 9)
        p.fop(9, 7, "*", 7)
        p.trunc(9, 9)
        p.lsh(9, 9, -7)
        p.iop(8, 8, "+", 9)
        ws(p, 6, 8)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        M = PIMA
        p.iconst(0, 0x2228)
        ss(p, M.F1, 0)
        p.iconst(0, 0x442)
        ss(p, M.F2, 0)
        p.iconst(0, 0)
        for k in (M.EN, M.GR, M.Y1, M.Y2, M.YD):
            ss(p, k, 0)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        p.iconst(0, 0x66666)
        ss(p, PIMA.EN, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        M, C = PIMA, L.C
        p.ld(0, C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(0, 12, "+", 0)
        p.seti(5, 0)

        def one():
            K.fib(p, L, M.F1, M.F2, 4)
            to_word(p, 6, 4)                            # N
            p.iconst(3, 0)
            w(p, 4, 4)
            s(p, 5, M.GR)
            xmul(p)                                     # grain *= GLEN
            p.ipass(7, 6)
            p.ifz(7, "LT", lambda: (p.iconst(12, 0), p.iop(7, 12, "-", 6)))
            w(p, 0, 1)
            p.e("COMP(R7, R0);")

            def kick():
                s(p, 8, M.EN)
                p.iop(2, 8, "+", 2)
            p._branch(lambda: p.r[7] <= p.r[0], "LE", kick, None)   # |N| <= GRNS
            clamp(p, 2)
            ss(p, M.GR, 2)
            p.iconst(3, HALF)
            p.ipass(4, 2)
            p.ipass(5, 6)
            xmul(p, rne=True)                           # u = rnd(grain N)
            w(p, 4, 2)
            p.ipass(5, 2)
            xmul(p, rne=True)                           # b = rnd(W2 u)
            p.lsh(6, 2, 2)                              # 4 b
            w(p, 4, 5)
            s(p, 5, M.Y1)
            xmul(p, rne=True)
            p.iop(6, 6, "-", 2)
            p.lsh(6, 6, 1)                              # 2 (4 b - rnd(W5 y1))
            w(p, 4, 6)
            s(p, 5, M.Y2)
            xmul(p, rne=True)
            p.iop(6, 6, "-", 2)
            clamp(p, 6)                                 # the new y1
            s(p, 7, M.Y1)
            s(p, 8, M.YD)
            p.iop(0, 7, "-", 8)
            clamp(p, 0)
            ss(p, M.YD, 7)
            ss(p, M.Y2, 7)
            ss(p, M.Y1, 6)
            p.iconst(12, -23)
            p.float_(0, 0, 12)
            p.stpost(5, 0)
            p.iconst(3, 0)
            s(p, 4, M.EN)
            w(p, 5, 3)
            xmul(p)                                     # energy *= DEC
            ss(p, M.EN, 2)
        p.loop(C["n2"], 32, one)


MACHINES = (PIMA,)

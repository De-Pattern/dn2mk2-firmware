"""GND: the Machinedrum's basic generators (docs/md.md), from DSP2's GND-SN, GND-NS and
GND-IM and their host scale functions.

Each machine is four steps on the slot's words (core.py):
  host(p, L)    the eight inputs -> the host's words W (as the OS's scale function)
  init(p, L)    the machine was just put on the track
  trig(p, L)    a note
  render(p, L)  32 samples at 44.1 kHz into the stream at OUT0 (I5 is free to use)
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from ..perc.dsl import Prog


def out_loop(p: Prog, L: K.Layout, body) -> None:
    """for each of the block's 32 samples: body() leaves the sample in F4, stored at
    OUT0 + i (I5 walks it). The loop takes R0 and R12 each time round."""
    p.ld(0, L.C["mdb"])
    p.iconst(12, 4 * K.OUT0)
    p.iop(0, 12, "+", 0)
    p.seti(5, 0)

    def one():
        body()
        p.stpost(5, 4)
    p.loop(L.C["n1"], 32, one)


def pitch_word(p: Prog, L: K.Layout, d: int, x: int, extra: int = 0) -> None:
    """Fd = tblP[x & 127] << ((x >> 7) + extra), the scale functions' pitch idiom, as a
    float (Rx an integer). Clobbers R12, R13, R14, I1."""
    p.iconst(12, 127)
    p.iop(14, x, "AND", 12)
    K.table_f(p, L, d, "hostP", 14, 12)       # an int: the table holds integers
    p.lsh(14, x, -7)
    if extra:
        p.iconst(12, extra)
        p.iop(14, 12, "+", 14)
    p.float_(d, d, 14)                         # tblP[...] * 2^(x >> 7 + extra)


def decay_word(p: Prog, L: K.Layout, d: int, x: int, shift: int) -> None:
    """Fd = tblD[Rx >> shift] (a Q23 coefficient). Clobbers R12, R13, R14, I1."""
    p.lsh(14, x, -shift)
    K.table_f(p, L, d, "hostD", 14, 12)


def square_shift(p: Prog, d: int, x: int, shift: int) -> None:
    """Fd = (Rx * Rx) >> shift, as a float (Rx 0..16383). Clobbers R12."""
    p.iconst(12, 0)
    p.float_(d, x, 12)
    p.fop(d, d, "*", d)
    p.fconst(12, 2.0 ** -shift)
    p.fop(d, d, "*", 12)
    p.trunc(d, d)                              # the shift truncates
    p.iconst(12, 0)
    p.float_(d, d, 12)


class GNDSN:
    """A sine with an exponential pitch ramp and an exponential decay.
    W1 the pitch (sine indices << 6), W2 the decay a sample, W3 the ramp's depth
    (RAMP^2 >> 7), W4 the ramp's decay a block. State: S0 the ramp envelope, S1 the
    phase, S2 the amplitude envelope."""
    NAME, ID = "GND-SN", 1
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "-", "-", "-", "-")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)
        p.lsh(0, 0, -4)
        pitch_word(p, L, 4, 0)
        ws(p, 1, 4)
        inp(p, 0, 1)
        decay_word(p, L, 4, 0, 5)
        ws(p, 2, 4)
        inp(p, 0, 2)
        square_shift(p, 4, 0, 7)
        ws(p, 3, 4)
        inp(p, 0, 3)
        decay_word(p, L, 4, 0, 5)
        ws(p, 4, 4)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        pass

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        p.fconst(0, 0x7FFFF8 * K.Q23)
        ss(p, 0, 0)
        ss(p, 2, 0)
        p.iconst(0, 0)
        ss(p, 1, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        # the block's increment: (pitch + ramp depth * ramp) / 64 sine indices
        s(p, 4, 0)
        w(p, 5, 3)
        p.fop(5, 5, "*", 4)
        w(p, 6, 1)
        p.fop(5, 6, "+", 5)
        K.mul_k(p, 5, 5, 1.0 / 64.0)
        K.phase_inc(p, 6, 5)
        p.st(L.C["a"], 6)
        w(p, 5, 4)                              # the ramp decays once a block (truncated)
        K.mpyf_any(p, 6, 4, 5)
        ss(p, 0, 6)

        def one():
            s(p, 6, 1)                          # the phase
            K.sine(p, L, 4, 6)
            p.ld(7, L.C["a"])
            p.ipass(12, 7)
            p.iop(6, 12, "+", 6)
            ss(p, 1, 6)
            K.mul_k(p, 4, 4, 0.25)              # >> 2
            s(p, 7, 2)                          # the envelope
            p.fop(4, 4, "*", 7)
            K.sat(p, 4)
            w(p, 8, 2)
            p.fop(7, 7, "*", 8)
            ss(p, 2, 7)
        out_loop(p, L, one)


class GNDNS:
    """Noise: the additive Fibonacci generator, under an exponential decay.
    W1 the decay a sample. State: S0, S1 the generator, S2 the envelope."""
    NAME, ID = "GND-NS", 2
    PNAMES = ("DEC", "-", "-", "-", "-", "-", "-", "-")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)
        decay_word(p, L, 4, 0, 5)
        ws(p, 1, 4)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        p.iconst(0, 0)
        ss(p, 0, 0)
        p.iconst(0, 1)
        ss(p, 1, 0)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        p.fconst(0, 0x7FFCB9 * K.Q23)
        ss(p, 2, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        def one():
            K.fib(p, L, 0, 1, 4)
            s(p, 7, 2)
            p.fop(4, 4, "*", 7)
            K.sat(p, 4)
            w(p, 8, 1)
            p.fop(7, 7, "*", 8)
            ss(p, 2, 7)
        out_loop(p, L, one)


class GNDIM:
    """Impulses: UP samples of UVAL, then DOWN samples of DVAL, then silence.
    W1/W3 the counts, W2/W4 the values (Q23). State: S0/S1 the counts left, S2/S3 the
    values."""
    NAME, ID = "GND-IM", 3
    PNAMES = ("UP", "UVAL", "DOWN", "DVAL", "-", "-", "-", "-")

    @staticmethod
    def _updown(p: Prog, d: int, x: int) -> None:
        """Rd = x >> 7 (x <= 8191), else ((x - 8192)^2 >> 14) + 64. Clobbers R12, R13."""
        p.iconst(12, 8191)

        def low():
            p.lsh(d, x, -7)

        def high():
            p.iconst(12, -8192)
            p.iop(13, 12, "+", x)
            p.iconst(12, 0)
            p.float_(d, 13, 12)
            p.fop(d, d, "*", d)
            p.fconst(12, 2.0 ** -14)
            p.fop(d, d, "*", 12)
            p.trunc(d, d)
            p.iconst(12, 64)
            p.iop(d, 12, "+", d)
        p.if_(x, "LE", 12, low, high, kind="i")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        for k, word in ((0, 1), (2, 3)):
            inp(p, 0, k)
            GNDIM._updown(p, 4, 0)
            ws(p, word, 4)
        for k, word in ((1, 2), (3, 4)):
            inp(p, 0, k)
            square_shift(p, 4, 0, 5)
            K.mul_k(p, 4, 4, K.Q23)
            ws(p, word, 4)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        pass

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        for k in range(4):
            w(p, 0, k + 1)
            ss(p, (0, 2, 1, 3)[k], 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        def one():
            s(p, 0, 0)

            def up():
                p.iconst(12, -1)
                s(p, 13, 0)
                p.iop(13, 13, "+", 12)
                ss(p, 0, 13)
                s(p, 4, 2)

            def rest():
                s(p, 1, 1)

                def down():
                    p.iconst(12, -1)
                    s(p, 13, 1)
                    p.iop(13, 13, "+", 12)
                    ss(p, 1, 13)
                    s(p, 4, 3)
                p.ifz(1, "NE", down, lambda: p.fconst(4, 0.0))
            p.ifz(0, "NE", up, rest)
        out_loop(p, L, one)


MACHINES = (GNDSN, GNDNS, GNDIM)

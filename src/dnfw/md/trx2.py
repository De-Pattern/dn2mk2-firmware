"""TRX, second half: the Machinedrum's TRX-CP, CB, CH, OH, CY, MA and S2 (docs/md.md), from
DSP2's code (the integer models in md_models.py) and the OS's scale functions.

Each machine is four steps on the slot's words, as in gnd.py. The firmware runs each stage
over a 32-word buffer; every stage here is causal, so a block runs its stages sample by
sample in one loop (the same arithmetic in the same order), with a buffer only where the
firmware reads one out of order (TRX-MA's reversed noise, TRX-CP's two noise blocks).

Filters (the X:$140000 tables). Two kinds, both with table coefficients:
  hp1   y = sat(2 (cb y[-2] + g y[-1] + u[-2]/2 - u[-1] + u/2))    (a high-pass biquad)
  res2  y = sat(2 (c1 y[-2] + g y[-1] + c0 x))                     (TRX-SD's resonator)
`hpc` is two hp1 in cascade and the firmware's two-sample delay (its in-place buffers make
the next stage read [G-2, G-1, G0 .. G29]); `res4` is two res2. They are leaf subroutines
(one copy of the code for every machine) on a block of state words at I1. The
coefficients come from the tables and the host's words only, so `host` and `trig` work them
out (exactly: 12-bit halves, as core.mpy_floor) and keep them beside the filter's state.

`sat` after a filter's sum floors to the Q23 grid (`qf`), as the 56300's limiter does: the
recursions would otherwise drift by half a word a sample.
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .gnd import out_loop
from ..perc.dsl import Prog

Q = K.Q23
X = "X140000"


# -- integer helpers (host side) ---------------------------------------------------------
def iadd(p: Prog, d: int, a: int, b: int) -> None:
    """Rd = Ra + Rb (whichever order the adder takes). May clobber R14."""
    if 8 <= a <= 15:
        p.iop(d, a, "+", b)
    elif 8 <= b <= 15:
        p.iop(d, b, "+", a)
    else:
        p.ipass(14, a)
        p.iop(d, 14, "+", b)


def iaddk(p: Prog, d: int, a: int, k: int) -> None:
    """Rd = Ra + k. Clobbers R12 (a != 12)."""
    assert a != 12
    p.iconst(12, k)
    p.iop(d, 12, "+", a)


def isubk(p: Prog, d: int, k: int, a: int) -> None:
    """Rd = k - Ra. Clobbers R12."""
    assert a != 12
    p.iconst(12, k)
    p.iop(d, 12, "-", a)


def imul_k(p: Prog, d: int, x: int, c: int) -> None:
    """Rd = Rx * c exactly (Rx in 0..2^14, c >= 0, the product < 2^31): 10-bit pieces of c,
    whose products a float holds exactly. Clobbers R12-R14 (d, x not among them)."""
    assert d not in (12, 13, 14) and x not in (12, 13, 14) and d != x
    p.iconst(12, 0)
    p.float_(14, x, 12)
    p.iconst(d, 0)
    j = 0
    while c >> (10 * j):
        piece = (c >> (10 * j)) & 1023
        if piece:
            p.fconst(13, float(piece))
            p.fop(13, 14, "*", 13)
            p.trunc(13, 13)
            if j:
                p.lsh(13, 13, 10 * j)
            p.iop(d, 13, "+", d)
        j += 1


def imul_small(p: Prog, d: int, a: int, b: int) -> None:
    """Rd = Ra * Rb for a small product (|product| < 2^24: a float holds it). Clobbers R12-R14."""
    p.iconst(12, 0)
    p.float_(13, a, 12)
    p.float_(14, b, 12)
    p.fop(13, 13, "*", 14)
    p.trunc(d, 13)


def imul_var(p: Prog, d: int, a: int, b: int) -> None:
    """Rd = Ra * Rb exactly, Ra, Rb in 0..2^14 (7-bit halves of Rb). Clobbers R12-R14."""
    assert d not in (12, 13, 14, a, b)
    p.iconst(12, 127)
    p.iop(13, b, "AND", 12)
    p.lsh(14, b, -7)
    p.iconst(12, 0)
    p.float_(13, 13, 12)
    p.float_(14, 14, 12)
    p.float_(d, a, 12)
    p.fop(13, 13, "*", d)
    p.fop(14, 14, "*", d)
    p.trunc(13, 13)
    p.trunc(14, 14)
    p.lsh(14, 14, 7)
    p.iop(d, 13, "+", 14)


def idiv(p: Prog, d: int, n: int, m: int) -> None:
    """Rd = Rn / Rm, truncated (Rn in 0..2^24, Rm in 1..2^16; the 68k's DIVS for these):
    a reciprocal by Newton's method from the float's bits, then corrected to the exact
    quotient. Clobbers R5-R7, R12-R14 (d, n, m not among them)."""
    assert not {d, n, m} & {5, 6, 7, 12, 13, 14}
    p.iconst(12, 0)
    p.float_(5, m, 12)                       # F5 = m
    p.float_(6, n, 12)                       # F6 = n
    p.iconst(12, 0x7EF311C3)
    p.iop(7, 12, "-", 5)                     # F7 ~ 1/m (to 12%)
    for _ in range(4):                       # y (2 - m y)
        p.fop(13, 5, "*", 7)
        p.fconst(12, 2.0)
        p.fop(13, 12, "-", 13)
        p.fop(7, 7, "*", 13)
    p.fop(7, 6, "*", 7)
    p.trunc(d, 7)                            # q, within one of the quotient
    p.iconst(12, 0)
    p.float_(7, d, 12)
    p.fop(7, 7, "*", 5)
    p.fop(7, 6, "-", 7)                      # r = n - q m (exact: < 2^24)
    p.fconst(12, 0.0)
    p.if_(7, "LT", 12, lambda: (p.iconst(12, -1), p.iop(d, 12, "+", d)))
    p.if_(7, "GE", 5, lambda: (p.iconst(12, 1), p.iop(d, 12, "+", d)))


def wsf(p: Prog, k: int, r: int) -> None:
    """W[k] = Rr (an integer word) as a Q23 float. Clobbers R12, R13."""
    p.iconst(12, -23)
    p.float_(13, r, 12)
    ws(p, k, 13)


def wsi(p: Prog, k: int, r: int) -> None:
    """W[k] = Rr, an integer word."""
    ws(p, k, r)


def note_only(p: Prog, body) -> None:
    """body() only when the host block is a note (VW['trg'])."""
    K.vw(p, 0, "trg")
    p.ifz(0, "NE", body)


# -- Q23 arithmetic ------------------------------------------------------------------------
def qf(p: Prog, x: int, clamp: bool = True) -> None:
    """Fx = the 56300's store of an accumulator: Fx floored to the Q23 grid, through the
    limiter. Clobbers R12-R14."""
    assert x not in (12, 13, 14)
    p.fconst(12, 2.0 ** 23)
    p.fop(x, x, "*", 12)
    p.trunc(13, x)
    p.iconst(12, 0)
    p.float_(14, 13, 12)
    p.if_(x, "LT", 14, lambda: (p.iconst(12, -1), p.iop(13, 12, "+", 13)))
    if clamp:
        p.iconst(12, 0x7FFFFF)
        p.iop(13, 13, "MIN", 12)
        p.iconst(12, -0x800000)
        p.iop(13, 13, "MAX", 12)
    p.iconst(12, -23)
    p.float_(x, 13, 12)


def mpyq(p: Prog, d: int, a: int, b: int, clamp: bool = False) -> None:
    """Fd = sat(mpy(Fa, Fb)): the product floored to the grid (a float product, then the
    floor; exact but where the product's rounding crosses a grid line). Clobbers R12-R14."""
    p.fop(d, a, "*", b)
    qf(p, d, clamp)


def umulq(p: Prog, a: int, b: int, k: int) -> None:
    """R3 = floor(Ra Rb / 2^k) and R4 nonzero iff that floor dropped something (Ra, Rb
    integer words in 0..2^23, k 22 or 23), exactly. Clobbers R5-R8, R12-R14."""
    assert not {a, b} & {3, 4, 5, 6, 7, 8, 12, 13, 14}
    p.iconst(12, 4095)
    p.iop(5, a, "AND", 12)                   # al
    p.lsh(6, a, -12)                         # ah
    p.iop(7, b, "AND", 12)                   # bl
    p.lsh(8, b, -12)                         # bh
    p.iconst(12, 0)
    for r in (5, 6, 7, 8):
        p.float_(r, r, 12)
    p.fop(13, 6, "*", 7)                     # ah bl
    p.fop(14, 5, "*", 8)                     # al bh
    p.trunc(13, 13)
    p.trunc(14, 14)
    p.iop(13, 13, "+", 14)                   # m
    p.fop(14, 5, "*", 7)
    p.trunc(14, 14)                          # n = al bl
    p.iconst(12, 4095)
    p.iop(4, 14, "AND", 12)
    p.lsh(14, 14, -12)
    p.iop(13, 13, "+", 14)                   # m + (n >> 12)
    p.iconst(12, (1 << (k - 12)) - 1)
    p.iop(12, 13, "AND", 12)
    p.iop(4, 4, "OR", 12)
    p.lsh(13, 13, -(k - 12))
    p.fop(14, 6, "*", 8)                     # ah bh
    p.trunc(14, 14)
    p.lsh(14, 14, 24 - k)
    p.iop(3, 13, "+", 14)


# -- the filters ---------------------------------------------------------------------------
HPC_N, RES4_N = 14, 10


def state_base(p: Prog, L: K.Layout) -> None:
    """R11 = the address of the state words (S0). Clobbers R12."""
    p.ld(11, L.C["mdb"])
    p.iconst(12, 4 * K.S0)
    p.iop(11, 12, "+", 11)


def at(p: Prog, off: int) -> None:
    """I1 = state word OFF (R11 the state base). Clobbers R13."""
    p.iconst(13, 4 * off)
    p.iop(13, 13, "+", 11)
    p.seti(1, 13)


def _hp1_body(p: Prog) -> None:
    # I1: [cb, g, y2, y1, u2, u1]; F4 the input -> F4 the output
    p.ldi(5, 0, 1)
    p.ldi(6, 2, 1)
    p.fop(5, 5, "*", 6)                      # cb y[-2]
    p.ldi(7, 1, 1)
    p.ldi(8, 3, 1)
    p.fop(7, 7, "*", 8)                      # g y[-1]
    p.fop(5, 5, "+", 7)
    p.fop(5, 5, "+", 5)
    p.sti(2, 1, 8)
    p.ldi(7, 4, 1)
    p.fop(5, 5, "+", 7)                      # + u[-2]
    p.ldi(7, 5, 1)
    p.fop(5, 5, "-", 7)
    p.fop(5, 5, "-", 7)                      # - 2 u[-1]
    p.sti(4, 1, 7)
    p.sti(5, 1, 4)
    p.fop(4, 5, "+", 4)                      # + u
    qf(p, 4)
    p.sti(3, 1, 4)


def _res2_body(p: Prog) -> None:
    # I1: [c1, g, c0, y2, y1]; F4 the input -> F4 the output
    p.ldi(5, 0, 1)
    p.ldi(6, 3, 1)
    p.fop(5, 5, "*", 6)                      # c1 y[-2]
    p.ldi(7, 1, 1)
    p.ldi(8, 4, 1)
    p.fop(7, 7, "*", 8)                      # g y[-1]
    p.fop(5, 5, "+", 7)
    p.ldi(7, 2, 1)
    p.fop(7, 7, "*", 4)                      # c0 x
    p.fop(4, 5, "+", 7)
    p.fop(4, 4, "+", 4)
    qf(p, 4)
    p.sti(3, 1, 8)
    p.sti(4, 1, 4)


def hp1(p: Prog, off: int) -> None:
    """F4 = one sample through the hp1 at state words OFF.. (R11 the state base).
    Clobbers F5-F8, R12-R14, I1."""
    at(p, off)
    p.call("trx_hp1", lambda: _hp1_body(p))


def res2(p: Prog, off: int) -> None:
    at(p, off)
    p.call("trx_res2", lambda: _res2_body(p))


def delay2(p: Prog, off: int) -> None:
    """F4 = the input of two samples ago (state words OFF, OFF + 1). Clobbers F5, F6."""
    s(p, 5, off)
    s(p, 6, off + 1)
    ss(p, off, 6)
    ss(p, off + 1, 4)
    p.fpass(4, 5)


def hpc(p: Prog, off: int) -> None:
    """The high-pass cascade (md_models.hp_cascade) at state words OFF..OFF+13: hp1, hp1,
    then the two-sample delay. F4 in, F4 out."""
    hp1(p, off)
    hp1(p, off + 6)
    delay2(p, off + 12)


def res4(p: Prog, off: int) -> None:
    """Two res2 (md_models.resonator4) at state words OFF..OFF+9."""
    res2(p, off)
    res2(p, off + 5)


def hpc_clear(p: Prog, off: int) -> None:
    p.fconst(0, 0.0)
    for k in (2, 3, 4, 5, 8, 9, 10, 11, 12, 13):
        ss(p, off + k, 0)


def res4_clear(p: Prog, off: int) -> None:
    p.fconst(0, 0.0)
    for k in (3, 4, 8, 9):
        ss(p, off + k, 0)


# -- coefficients (host and trig) ------------------------------------------------------------
def xint(p: Prog, L: K.Layout, d: int, idx: int, off: int) -> None:
    """Rd = X:$140000[OFF + Ridx] as an integer word. Clobbers R12-R14, I1."""
    assert d not in (12, 13) and idx not in (12, 13, 14)
    iaddk(p, 14, idx, off)
    K.table_f(p, L, d, X, 14, 12)
    p.fconst(12, 2.0 ** 23)
    p.fop(d, d, "*", 12)
    p.trunc(d, d)


def coefs(p: Prog, L: K.Layout) -> None:
    """From R9 (the tune word) and R10 (the table index word): R9 = c1 (= cb), R15 = g,
    R10 = c0, integer words (md_models.sd_coefs; hp_cascade's cb, g are c1, g).
    Clobbers R1-R8, R12-R14, I1."""
    xint(p, L, 5, 10, 0)
    iadd(p, 5, 9, 5)
    xint(p, L, 1, 5, 0x900)                  # t1
    xint(p, L, 6, 10, 0x80)
    iadd(p, 6, 9, 6)
    xint(p, L, 2, 6, 0x1900)                 # t2 (> 0)
    umulq(p, 2, 2, 23)                       # t2^2
    p.ipass(9, 3)
    p.ifz(4, "NE", lambda: (p.iconst(12, 1), p.iop(9, 12, "+", 9)))
    p.iconst(12, 0)
    p.iop(9, 12, "-", 9)                     # c1 = floor(-t2^2)

    def pos():
        umulq(p, 1, 2, 22)                   # 2 t1 t2
        p.ipass(15, 3)                       # floor
        p.ipass(10, 3)
        p.ifz(4, "NE", lambda: (p.iconst(12, 1), p.iop(10, 12, "+", 10)))   # ceil

    def neg():
        p.iconst(12, 0)
        p.iop(1, 12, "-", 1)
        umulq(p, 1, 2, 22)
        p.iconst(12, 0)
        p.iop(10, 12, "-", 3)                # ceil = -floor|.|
        p.ipass(15, 3)
        p.ifz(4, "NE", lambda: (p.iconst(12, 1), p.iop(15, 12, "+", 15)))
        p.iconst(12, 0)
        p.iop(15, 12, "-", 15)               # floor = -ceil|.|
    p.ifz(1, "LT", neg, pos)
    p.iconst(12, 0x400000)
    p.iop(10, 12, "-", 10)
    p.iop(10, 10, "-", 9)                    # c0 = 1/2 - ceil(2 t1 t2) - c1


def _sf(p: Prog, k: int, r: int) -> None:
    """S[k] = Rr (an integer word) as a Q23 float. Clobbers R12, R13."""
    p.iconst(12, -23)
    p.float_(13, r, 12)
    ss(p, k, 13)


def set_hpc(p: Prog, L: K.Layout, off: int) -> None:
    """The hpc at OFF: its coefficients from R9 (tune), R10 (index)."""
    coefs(p, L)
    for k in (0, 6):
        _sf(p, off + k, 9)
        _sf(p, off + k + 1, 15)


def set_hp1(p: Prog, L: K.Layout, off: int) -> None:
    coefs(p, L)
    _sf(p, off, 9)
    _sf(p, off + 1, 15)


def set_res4(p: Prog, L: K.Layout, off: int) -> None:
    coefs(p, L)
    for k in (0, 5):
        _sf(p, off + k, 9)
        _sf(p, off + k + 1, 15)
        _sf(p, off + k + 2, 10)


def wint(p: Prog, d: int, k: int) -> None:
    """Rd = W[k] (an integer word)."""
    w(p, d, k)


def const_i(p: Prog, d: int, v: int) -> None:
    p.iconst(d, v)


# =========================================================================== TRX-CB
class TRXCB:
    """Cowbell (md_models.TRXCB): two sines with opposite pitch bumps, each squared by a
    limiter, levelled, through its own hpc; summed / 4. A note: one block fading the last
    sample, two silent, then the sound.
    W1 amp decay (a block), W2 bump decay, W3/W4 increments (int), W5/W6 levels, W7/W8
    limiter thresholds, W9/W10 filter tunes (int), W11 the bump (a word, as Q23; notes only).
    State: S0 the note's block count, S1 amp, S2/S3 phases (int), S4 the last sample,
    S5.. / S19.. the two hpc."""
    NAME, ID = "TRX-CB", 21
    PNAMES = ("PTCH", "DEC", "ENH", "DAMP", "TONE", "BUMP", "-", "-")
    F1, F2 = 5, 5 + HPC_N

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                  # PTCH
        imul_k(p, 1, 0, 20945)
        p.lsh(1, 1, -16)                              # q
        p.iop(2, 0, "-", 1)
        p.iconst(12, 0xFFFF)
        p.iop(2, 2, "AND", 12)
        p.lsh(2, 2, -1)
        iadd(p, 2, 2, 1)
        p.lsh(2, 2, -6)
        iaddk(p, 2, 2, 711)
        wsi(p, 3, 2)
        p.lsh(1, 0, -1)
        imul_k(p, 2, 1, 51151)
        p.lsh(2, 2, -21)
        iaddk(p, 2, 2, 983)
        wsi(p, 4, 2)
        inp(p, 0, 1)                                  # DEC
        p.iconst(1, 45)
        imul_small(p, 2, 0, 1)
        p.lsh(2, 2, -12)
        iaddk(p, 2, 2, 220)
        K.table_f(p, L, 4, "hostQ", 2, 12)
        ws(p, 1, 4)
        inp(p, 0, 2)                                  # ENH
        p.lsh(0, 0, -7)
        isubk(p, 2, 1250, 0)
        wsi(p, 9, 2)
        wsi(p, 10, 2)
        inp(p, 0, 4)                                  # TONE
        p.lsh(0, 0, 8)
        isubk(p, 2, 6291455, 0)
        wsf(p, 5, 2)
        iaddk(p, 2, 0, 2097152)
        wsf(p, 6, 2)
        inp(p, 0, 3)                                  # DAMP
        p.iconst(1, 384)
        imul_small(p, 2, 0, 1)
        iaddk(p, 2, 2, 1966080)
        wsf(p, 7, 2)
        wsf(p, 8, 2)
        inp(p, 0, 5)                                  # BUMP
        p.iconst(1, 36)
        imul_small(p, 2, 0, 1)
        p.lsh(2, 2, -12)
        iaddk(p, 2, 2, 100)
        K.table_f(p, L, 4, "hostQ", 2, 12)
        ws(p, 2, 4)

        def bump():
            inp(p, 0, 5)
            imul_k(p, 2, 0, 43691)
            p.lsh(2, 2, -17)
            wsf(p, 11, 2)
        note_only(p, bump)
        # the filters (index $7F)
        for k, off in ((9, TRXCB.F1), (10, TRXCB.F2)):
            wint(p, 9, k)
            p.iconst(10, 0x7F)
            set_hpc(p, L, off)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        p.iconst(0, 0)
        ss(p, 2, 0)
        ss(p, 3, 0)
        hpc_clear(p, TRXCB.F1)
        hpc_clear(p, TRXCB.F2)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        s(p, 0, 1)
        K.add_k(p, 0, 0, 0x50C335 * Q)
        K.sat(p, 0)
        ss(p, 1, 0)
        p.iconst(0, 3)
        ss(p, 0, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        s(p, 0, 0)

        def counting():
            p.iconst(12, -1)
            s(p, 1, 0)
            p.iop(1, 12, "+", 1)
            ss(p, 0, 1)
            p.iconst(12, 2)
            p.e("COMP(R1, R12);")

            def fade():
                s(p, 9, 4)                            # (S4 is only the body's)

                def one():
                    p.fconst(5, 0x733333 * Q)
                    mpyq(p, 4, 9, 5)
                    p.fpass(9, 4)
                out_loop(p, L, one)

            def silent():
                out_loop(p, L, lambda: p.fconst(4, 0.0))
            p._branch(lambda: p.r[1] == p.r[12], "EQ", fade, silent)

        def body():
            # the bump: the increments (W3 - B) / 2 and (W4 + B) / 2 sine indices
            w(p, 4, 11)
            p.fconst(12, 2.0 ** 23)
            p.fop(5, 4, "*", 12)
            p.trunc(5, 5)                             # B
            w(p, 6, 3)
            p.iop(6, 6, "-", 5)
            p.lsh(6, 6, 16)
            p.st(L.C["a"], 6)
            w(p, 6, 4)
            iadd(p, 6, 6, 5)
            p.lsh(6, 6, 16)
            p.st(L.C["b"], 6)
            w(p, 5, 2)
            K.mpy_floor(p, 6, 5, 4)
            ws(p, 11, 6)
            # the levels, then the amp's decay (a block)
            s(p, 4, 1)
            w(p, 5, 5)
            K.mpy_floor(p, 6, 4, 5)
            p.st(L.C["c"], 6)
            w(p, 5, 6)
            K.mpy_floor(p, 6, 4, 5)
            p.st(L.C["d"], 6)
            w(p, 5, 1)
            K.mpy_floor(p, 6, 4, 5)
            ss(p, 1, 6)
            state_base(p, L)

            def osc(ph, inc, thr, lvl, off):
                s(p, 6, ph)
                K.sine(p, L, 4, 6)
                p.ld(10, L.C[inc])
                p.iop(6, 10, "+", 6)
                ss(p, ph, 6)
                w(p, 5, thr)
                p.if_(4, "GT", 5, lambda: p.fconst(4, 0x7FFCB9 * Q))
                p.fconst(6, 0.0)
                p.fop(6, 6, "-", 4)
                p.if_(6, "GT", 5, lambda: p.fconst(4, -0x7FFCB9 * Q))
                p.ld(5, L.C[lvl])
                mpyq(p, 4, 4, 5)
                hpc(p, off)

            def one():
                osc(2, "a", 7, "c", TRXCB.F1)
                p.fpass(9, 4)
                osc(3, "b", 8, "d", TRXCB.F2)
                p.fop(4, 4, "+", 9)
                K.mul_k(p, 4, 4, 0.25)
                qf(p, 4, clamp=False)
                ss(p, 4, 4)
            out_loop(p, L, one)
        p.ifz(0, "NE", counting, body)


MACHINES = (TRXCB,)

# the host's words as each machine keeps them: 'f' a Q23 float, 'i' an integer word
WORDS = {
    "TRX-CB": "ffiiffffiif",
}

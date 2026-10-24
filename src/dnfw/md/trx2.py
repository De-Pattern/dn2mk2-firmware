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
    quotient. Clobbers R5-R7, R12-R14 (d, n, m not among them), and I12 (v0.24: one
    shared copy, a subroutine, except inside another)."""
    assert not {d, n, m} & {5, 6, 7, 12, 13, 14}
    p.ipass(5, m)
    p.ipass(6, n)
    if p.in_sub:
        _idiv_body(p)
    else:
        p.call("md_idiv", lambda: _idiv_body(p))
    p.ipass(d, 14)


def _idiv_body(p: Prog) -> None:
    """R14 = R6 / R5 (integers), truncated; F5 = R5, F6 = R6 as floats after."""
    p.iconst(12, 0)
    p.float_(5, 5, 12)                       # F5 = m
    p.float_(6, 6, 12)                       # F6 = n
    p.iconst(12, 0x7EF311C3)
    p.iop(7, 12, "-", 5)                     # F7 ~ 1/m (to 12%)
    for _ in range(4):                       # y (2 - m y)
        p.fop(13, 5, "*", 7)
        p.fconst(12, 2.0)
        p.fop(13, 12, "-", 13)
        p.fop(7, 7, "*", 13)
    p.fop(7, 6, "*", 7)
    p.trunc(14, 7)                           # q, within one of the quotient
    p.iconst(12, 0)
    p.float_(7, 14, 12)
    p.fop(7, 7, "*", 5)
    p.fop(7, 6, "-", 7)                      # r = n - q m (exact: < 2^24)
    p.fconst(12, 0.0)
    p.if_(7, "LT", 12, lambda: (p.iconst(12, -1), p.iop(14, 12, "+", 14)))
    p.if_(7, "GE", 5, lambda: (p.iconst(12, 1), p.iop(14, 12, "+", 14)))


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


# -- exact word arithmetic in the sample loops ----------------------------------------------
# Signals, states and host words are the firmware's 24-bit words, as integers. A product of
# two words is 48 bits, more than a float holds; split into 12-bit pieces (the high one
# signed) every partial product is exact, and the integer sums floor exactly as the
# 56300's limiter does. Subroutines (one copy for all machines) take R4 / R5 / R6 and
# clobber R3-R10, R12-R15, I1; a sample loop keeps what it needs in R1, R2, R11.

def _wmul_body(p: Prog, k: int = 23, flag: bool = False) -> None:
    # R4 = floor(R5 R6 / 2^k) through the limiter: sat(mpy(a, b)) (k 23), or of 2 mpy (k 22)
    p.ash(7, 5, -12)
    p.ash(8, 6, -12)
    p.iconst(12, 4095)
    p.iop(5, 5, "AND", 12)
    p.iop(6, 6, "AND", 12)
    p.iconst(12, 0)
    for r in (5, 6, 7, 8):
        p.float_(r, r, 12)
    p.fop(13, 7, "*", 8)                     # ah bh
    p.fop(14, 7, "*", 6)
    p.fop(9, 5, "*", 8)
    p.fop(14, 14, "+", 9)                    # ah bl + al bh (< 2^24: exact)
    p.fop(9, 5, "*", 6)                      # al bl
    p.trunc(13, 13)
    p.trunc(14, 14)
    p.trunc(9, 9)
    if flag:                                 # R3: nonzero iff the floor dropped something
        p.iconst(12, 4095)
        p.iop(3, 9, "AND", 12)
    p.lsh(9, 9, -12)
    p.iop(14, 14, "+", 9)
    if flag:
        p.iconst(12, (1 << (k - 12)) - 1)
        p.iop(12, 14, "AND", 12)
        p.iop(3, 3, "OR", 12)
    p.ash(14, 14, -(k - 12))
    p.lsh(13, 13, 24 - k)
    p.iop(4, 13, "+", 14)
    if k == 23:
        p.iconst(12, 0x7FFFFF)
        p.iop(4, 4, "MIN", 12)


def wmul(p: Prog) -> None:
    """R4 = sat(mpy(R5, R6)), exactly. Clobbers R3-R10, R12-R15, I1."""
    p.call("trx_wmul", lambda: _wmul_body(p))


def wmulr(p: Prog) -> None:
    """wmul, and R3 nonzero iff the product had bits below the word (it was not exact)."""
    p.call("trx_wmulr", lambda: _wmul_body(p, 23, True))


def wmul4(p: Prog) -> None:
    """R4 = floor(4 mpy(R5, R6)) as a word (no limiter), exactly."""
    p.call("trx_wmul21", lambda: _wmul_body(p, 21))


def wmul2(p: Prog) -> None:
    """R4 = floor(2 mpy(R5, R6)) as a word (no limiter), exactly."""
    p.call("trx_wmul22", lambda: _wmul_body(p, 22))


def _term(p: Prog, ch: int, cl: int, first: bool) -> None:
    """The accumulators R9 (hh), R10 (mid), R15 (ll) += the coefficient at I1 + ch, cl
    (its 12-bit pieces, floats) times the word R4."""
    p.ash(5, 4, -12)
    p.iconst(12, 4095)
    p.iop(6, 4, "AND", 12)
    p.iconst(12, 0)
    p.float_(5, 5, 12)
    p.float_(6, 6, 12)
    p.ldi(7, ch, 1)
    p.ldi(8, cl, 1)
    p.fop(13, 7, "*", 5)
    p.fop(14, 7, "*", 6)
    p.fop(7, 8, "*", 5)
    p.fop(14, 14, "+", 7)
    p.fop(8, 8, "*", 6)
    p.trunc(13, 13)
    p.trunc(14, 14)
    p.trunc(8, 8)
    if first:
        p.ipass(9, 13)
        p.ipass(10, 14)
        p.ipass(15, 8)
    else:
        p.iop(9, 13, "+", 9)
        p.iop(10, 14, "+", 10)
        p.iop(15, 15, "+", 8)


def _sum22(p: Prog) -> None:
    """R9 = floor(the accumulated sum / 2^22) (the products' sum, << 1, through A1)."""
    p.lsh(15, 15, -12)
    p.iop(10, 10, "+", 15)
    p.ash(10, 10, -10)
    p.lsh(9, 9, 2)
    p.iop(9, 9, "+", 10)


def _clamp(p: Prog, r: int) -> None:
    p.iconst(12, 0x7FFFFF)
    p.iop(r, r, "MIN", 12)
    p.iconst(12, -0x800000)
    p.iop(r, r, "MAX", 12)


def _hp1_body(p: Prog) -> None:
    # I1: [cbh, cbl, gh, gl, y2, y1, u2, u1]; R4 the input -> R4 the output
    p.ipass(3, 4)
    p.ldi(4, 4, 1)
    _term(p, 0, 1, True)                     # cb y[-2]
    p.ldi(4, 5, 1)
    _term(p, 2, 3, False)                    # g y[-1]
    p.sti(4, 1, 4)
    _sum22(p)
    p.ldi(5, 6, 1)
    p.iop(9, 9, "+", 5)                      # + u[-2]
    p.ldi(5, 7, 1)
    p.iop(9, 9, "-", 5)
    p.iop(9, 9, "-", 5)                      # - 2 u[-1]
    p.iop(9, 9, "+", 3)                      # + u
    p.sti(6, 1, 5)
    p.sti(7, 1, 3)
    _clamp(p, 9)
    p.sti(5, 1, 9)
    p.ipass(4, 9)


def _res2_body(p: Prog) -> None:
    # I1: [c1h, c1l, gh, gl, c0h, c0l, y2, y1]; R4 the input -> R4 the output
    p.ipass(3, 4)
    p.ldi(4, 6, 1)
    _term(p, 0, 1, True)                     # c1 y[-2]
    p.ldi(4, 7, 1)
    _term(p, 2, 3, False)                    # g y[-1]
    p.sti(6, 1, 4)
    p.ipass(4, 3)
    _term(p, 4, 5, False)                    # c0 x
    _sum22(p)
    _clamp(p, 9)
    p.sti(7, 1, 9)
    p.ipass(4, 9)


HP1_N, RES2_N = 8, 8
HPC_N, RES4_N = 2 * HP1_N + 2, 2 * RES2_N


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


def hp1(p: Prog, off: int) -> None:
    """R4 = one word through the hp1 at state words OFF.. (R11 the state base)."""
    at(p, off)
    p.call("trx_hp1", lambda: _hp1_body(p))


def res2(p: Prog, off: int) -> None:
    at(p, off)
    p.call("trx_res2", lambda: _res2_body(p))


def delay2(p: Prog, off: int) -> None:
    """R4 = the input of two samples ago (state words OFF, OFF + 1). Clobbers R5, R6."""
    s(p, 5, off)
    s(p, 6, off + 1)
    ss(p, off, 6)
    ss(p, off + 1, 4)
    p.ipass(4, 5)


def hpc(p: Prog, off: int) -> None:
    """The high-pass cascade (md_models.hp_cascade) at state words OFF..: hp1, hp1, then
    the two-sample delay. R4 in, R4 out."""
    hp1(p, off)
    hp1(p, off + HP1_N)
    delay2(p, off + 2 * HP1_N)


def res4(p: Prog, off: int) -> None:
    """Two res2 (md_models.resonator4) at state words OFF.."""
    res2(p, off)
    res2(p, off + RES2_N)


def clear(p: Prog, offs) -> None:
    p.iconst(0, 0)
    for k in offs:
        ss(p, k, 0)


def hp1_clear(p: Prog, off: int) -> None:
    clear(p, range(off + 4, off + 8))


def hpc_clear(p: Prog, off: int) -> None:
    hp1_clear(p, off)
    hp1_clear(p, off + HP1_N)
    clear(p, (off + 2 * HP1_N, off + 2 * HP1_N + 1))


def res4_clear(p: Prog, off: int) -> None:
    clear(p, (off + 6, off + 7, off + RES2_N + 6, off + RES2_N + 7))


def to_word(p: Prog, d: int, f: int) -> None:
    """Rd = the Q23 float Ff as its word (Ff on the grid). Clobbers R12."""
    p.fconst(12, 2.0 ** 23)
    p.fop(d, f, "*", 12)
    p.trunc(d, d)


def to_q23(p: Prog, d: int, r: int) -> None:
    """Fd = the word Rr as a Q23 float. Clobbers R12."""
    p.iconst(12, -23)
    p.float_(d, r, 12)


def fibw(p: Prog, k1: int, k2: int, d: int) -> None:
    """The additive Fibonacci noise (md_models.fib_noise) in state words K1, K2: Rd = the
    new value as a signed word. Clobbers R12, R13."""
    assert d not in (12, 13)
    s(p, 12, k1)
    s(p, 13, k2)
    ss(p, k1, 13)
    p.iop(13, 12, "+", 13)
    p.iconst(12, 0xFFFFFF)
    p.iop(13, 13, "AND", 12)
    ss(p, k2, 13)
    p.lsh(d, 13, 8)
    p.ash(d, d, -8)


def out_ints(p: Prog, L: K.Layout, body) -> None:
    """gnd.out_loop for a body that leaves a word in R4: stored as a Q23 float."""
    def one():
        body()
        to_q23(p, 4, 4)
    out_loop(p, L, one)


def floorw(p: Prog, d: int, f: int) -> None:
    """Rd = floor(Ff) (Ff a product in word units). Clobbers R12, R14."""
    assert d not in (12, 14) and f not in (12, 14)
    p.trunc(d, f)
    p.iconst(12, 0)
    p.float_(14, d, 12)
    p.if_(f, "LT", 14, lambda: (p.iconst(12, -1), p.iop(d, 12, "+", d)))


WAVES = ("TRXCH_W0", "TRXCH_W1", "TRXCH_W2", "TRXCH_W3", "TRXCH_W4", "TRXCH_W5")
WAVE_N = (114, 102, 86, 80, 58, 52)
WLVL = ("a", "b", "c", "d", "e", "f")         # the six levels' scratch words (floats)
POSR = (1, 2, 3, 5, 6, 7)                     # the six read positions' registers


def wavetables(p: Prog, L: K.Layout, pos: int, noise=None) -> None:
    """The six cyclic "metal" ROM wavetables (md_models.wavetable_sum), each times its
    level (scratch WLVL, the level word as a float), summed with NOISE (state words of a
    generator and the level's scratch word) into the block's 32 words at OUT0. The read
    positions are state words POS..POS+5. Every product is floored to its word (a float
    product: it may be one word off where its rounding crosses a word)."""
    C = L.C
    for j, r in enumerate(POSR):
        s(p, r, pos + j)
        p.lsh(r, r, 2)
        iaddk(p, r, r, L.T[WAVES[j]])
    p.iconst(15, 4)

    def one():
        if noise:
            k1, k2, lvl = noise
            fibw(p, k1, k2, 9)
            p.iconst(12, 0)
            p.float_(8, 9, 12)
            p.ld(10, C[lvl])
            p.fop(8, 8, "*", 10)
            floorw(p, 9, 8)
        else:
            p.iconst(9, 0)
        for j, r in enumerate(POSR):
            p.seti(1, r)
            p.ldi(8, 0, 1)
            p.ld(10, C[WLVL[j]])
            p.fop(8, 8, "*", 10)
            floorw(p, 13, 8)
            p.iop(9, 9, "+", 13)
            p.iop(r, 15, "+", r)
            p.iconst(12, L.T[WAVES[j]] + 4 * WAVE_N[j])
            p.if_(r, "EQ", 12, lambda j=j, r=r: p.iconst(r, L.T[WAVES[j]]), kind="i")
        p.ipass(4, 9)
    out_loop(p, L, one)
    for j, r in enumerate(POSR):
        iaddk(p, r, r, -L.T[WAVES[j]])
        p.lsh(r, r, -2)
        ss(p, pos + j, r)


def level_f(p: Prog, L: K.Layout, name: str, r: int) -> None:
    """Scratch NAME = the word Rr as a float (its integer value). Clobbers R12."""
    p.iconst(12, 0)
    p.float_(r, r, 12)
    p.st(L.C[name], r)


# -- coefficients (host and trig) ------------------------------------------------------------
def xint(p: Prog, L: K.Layout, d: int, idx: int, off: int) -> None:
    """Rd = X:$140000[OFF + Ridx] as an integer word. Clobbers R12-R14, I1."""
    assert d not in (12, 13) and idx not in (12, 13, 14)
    iaddk(p, 14, idx, off)
    K.table_f(p, L, d, X, 14, 12)
    to_word(p, d, d)


def table_word(p: Prog, L: K.Layout, d: int, name: str, idx: int) -> None:
    """Rd = a host table's word (a Q23 table) at Ridx. Clobbers R12, R13, I1."""
    K.table_f(p, L, d, name, idx, 12)
    to_word(p, d, d)


def coefs(p: Prog, L: K.Layout) -> None:
    """From R9 (the tune word) and R10 (the table index word): R9 = c1 (= cb), R15 = g,
    R10 = c0, integer words (md_models.sd_coefs; hp_cascade's cb, g are c1, g).
    A leaf subroutine. Clobbers R1-R8, R12-R14, I1."""
    p.call("trx_coefs", lambda: _coefs_body(p, L))


def _coefs_body(p: Prog, L: K.Layout) -> None:
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


def _pieces(p: Prog, k: int, r: int) -> None:
    """S[k], S[k + 1] = the word Rr's 12-bit pieces (high signed), as floats.
    Clobbers R12-R14."""
    p.ash(13, r, -12)
    p.iconst(12, 4095)
    p.iop(14, r, "AND", 12)
    p.iconst(12, 0)
    p.float_(13, 13, 12)
    p.float_(14, 14, 12)
    ss(p, k, 13)
    ss(p, k + 1, 14)


def set_hp1(p: Prog, L: K.Layout, off: int) -> None:
    """The hp1 at OFF: its coefficients from R9 (tune), R10 (index)."""
    coefs(p, L)
    _pieces(p, off, 9)
    _pieces(p, off + 2, 15)


def set_hpc(p: Prog, L: K.Layout, off: int) -> None:
    coefs(p, L)
    for k in (off, off + HP1_N):
        _pieces(p, k, 9)
        _pieces(p, k + 2, 15)


def set_res4(p: Prog, L: K.Layout, off: int) -> None:
    coefs(p, L)
    for k in (off, off + RES2_N):
        _pieces(p, k, 9)
        _pieces(p, k + 2, 15)
        _pieces(p, k + 4, 10)


# =========================================================================== TRX-CP
class TRXCP:
    """Clap (md_models.TRXCP): noise under a four-burst envelope through an hpc and a res4,
    plus a room (noise through a res4) at a level decaying a block; (clap + room) / 4.
    The host sends words only with a note; the burst counters W12-W14 and the levels W1,
    W2, W11 change in place.
    W1/W2 burst levels, W3 decay, W4 room decay, W5/W6 hpc tune/index, W7/W8 and W9/W10
    res4 tune/index (clap, room), W11 room level, W12-W14 burst lengths (blocks).
    State: S0 env, S1/S2 burst levels 3/4, S3-S5 burst decays, S6/S7 noise, S8.. hpc,
    S26.. clap res4, S42.. room res4."""
    NAME, ID = "TRX-CP", 19
    PNAMES = ("CLPY", "TONE", "HARD", "RICH", "RATE", "ROOM", "RSIZ", "RTUN")
    HP, RC, RR = 8, 8 + HPC_N, 8 + HPC_N + RES4_N

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        def words():
            inp(p, 0, 0)                              # CLPY
            p.iconst(1, 281)
            imul_small(p, 2, 0, 1)
            iaddk(p, 3, 2, 3774873)
            ws(p, 1, 3)
            p.lsh(2, 2, -1)
            iaddk(p, 3, 2, 3355443)
            ws(p, 2, 3)
            inp(p, 0, 1)                              # TONE
            p.lsh(2, 0, -8)
            iaddk(p, 2, 2, 1696)
            ws(p, 7, 2)
            p.lsh(2, 0, -5)
            iaddk(p, 2, 2, 704)
            ws(p, 5, 2)
            inp(p, 0, 2)                              # HARD
            iaddk(p, 2, 0, 48)
            p.lsh(2, 2, -8)
            ws(p, 6, 2)
            ws(p, 8, 2)
            inp(p, 0, 5)                              # ROOM
            p.lsh(2, 0, 9)
            ws(p, 11, 2)
            inp(p, 0, 3)                              # RICH
            p.lsh(2, 0, -7)
            iaddk(p, 2, 2, 144)
            table_word(p, L, 3, "hostD", 2)
            ws(p, 3, 3)
            inp(p, 0, 6)                              # RSIZ
            p.lsh(2, 0, -8)
            iaddk(p, 2, 2, 85)
            table_word(p, L, 3, "hostD", 2)
            ws(p, 4, 3)
            inp(p, 0, 7)                              # RTUN
            p.lsh(2, 0, -5)
            iaddk(p, 2, 2, 1024)
            ws(p, 9, 2)
            p.iconst(2, 64)
            ws(p, 10, 2)
            inp(p, 0, 4)                              # RATE
            for k, c in ((12, 49181), (14, 32721)):
                imul_k(p, 1, 0, c)
                p.lsh(1, 1, -16)                      # q
                p.iop(2, 0, "-", 1)
                p.iconst(12, 0xFFFF)
                p.iop(2, 2, "AND", 12)
                p.lsh(2, 2, -1)
                iadd(p, 2, 2, 1)
                if k == 12:
                    p.iconst(12, 0xFFFF)
                    p.iop(2, 2, "AND", 12)
                p.lsh(2, 2, -9)
                iaddk(p, 2, 2, 1)
                ws(p, k, 2)
            imul_k(p, 1, 0, 16811)
            p.lsh(1, 1, -23)
            iaddk(p, 1, 1, 1)
            ws(p, 13, 1)
            for k, off in ((5, TRXCP.HP), (7, TRXCP.RC), (9, TRXCP.RR)):
                w(p, 9, k)
                w(p, 10, k + 1)
                (set_hpc if k == 5 else set_res4)(p, L, off)
        note_only(p, words)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        p.iconst(0, 0x29A)
        ss(p, 6, 0)
        p.iconst(0, 1)
        ss(p, 7, 0)
        hpc_clear(p, TRXCP.HP)
        res4_clear(p, TRXCP.RC)
        res4_clear(p, TRXCP.RR)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        clear(p, (0,))
        w(p, 0, 2)
        ss(p, 1, 0)
        p.iconst(0, 0x333333)
        ss(p, 2, 0)
        w(p, 0, 3)
        for k in (3, 4, 5):
            ss(p, k, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        C = L.C
        state_base(p, L)
        # the room: noise -> res4, times the room level (this block's); the level decays
        w(p, 0, 11)
        p.st(C["a"], 0)
        p.ipass(5, 0)
        w(p, 6, 4)
        wmul(p)
        ws(p, 11, 4)

        def room():
            fibw(p, 6, 7, 4)
            res4(p, TRXCP.RR)
            p.ipass(6, 4)
            p.ld(5, C["a"])
            wmul(p)                                   # (stored as a word, read back below)
        out_loop(p, L, room)
        # the burst: a level added at the block's start, and its decay
        s(p, 1, 0)                                    # b = env

        def burst(cnt, lvl_get, lvl_clear, dec_get):
            def go():
                w(p, 0, cnt)
                p.iconst(12, -1)
                p.iop(0, 12, "+", 0)
                ws(p, cnt, 0)
                lvl_get()
                iadd(p, 1, 1, 0)
                p.iconst(0, 0)
                lvl_clear()
                dec_get()
            return go

        def last():
            s(p, 0, 2)
            iadd(p, 1, 1, 0)
            clear(p, (2,))
            s(p, 2, 5)

        def third():
            w(p, 0, 14)
            p.ifz(0, "NE", burst(14, lambda: s(p, 0, 1), lambda: ss(p, 1, 0), lambda: s(p, 2, 4)), last)

        def second():
            w(p, 0, 13)
            p.ifz(0, "NE", burst(13, lambda: w(p, 0, 2), lambda: ws(p, 2, 0), lambda: s(p, 2, 3)), third)
        w(p, 0, 12)
        p.ifz(0, "NE", burst(12, lambda: w(p, 0, 1), lambda: ws(p, 1, 0), lambda: w(p, 2, 3)), second)
        _clamp(p, 1)                                  # e = sat(b)
        p.st(C["b"], 2)                               # the decay

        def clap():
            fibw(p, 6, 7, 6)
            s(p, 5, 0)                                # e (S0)
            wmul(p)
            p.st(C["c"], 4)                           # sat(mpy(e, v))
            s(p, 5, 0)
            p.ld(6, C["b"])
            wmul(p)
            ss(p, 0, 4)                               # e = sat(mpy(dec, e))
            p.ld(4, C["c"])
            hpc(p, TRXCP.HP)
            res4(p, TRXCP.RC)
            p.ldi(5, 0, 5)                            # the room's word
            iadd(p, 4, 4, 5)
            p.ash(4, 4, -2)
        ss(p, 0, 1)
        out_ints(p, L, clap)


# =========================================================================== TRX-CB
class TRXCB:
    """Cowbell (md_models.TRXCB): two sines with opposite pitch bumps, each squared by a
    limiter, levelled, through its own hpc; summed / 4. A note: one block fading the last
    sample, two silent, then the sound.
    W1 amp decay (a block), W2 bump decay, W3/W4 increments, W5/W6 levels, W7/W8 limiter
    thresholds, W9/W10 filter tunes, W11 the bump (notes only; decays in place).
    State: S0 the note's block count, S1 amp, S2/S3 phases, S4 the last sample,
    S5.. / S23.. the two hpc."""
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
        ws(p, 3, 2)
        p.lsh(1, 0, -1)
        imul_k(p, 2, 1, 51151)
        p.lsh(2, 2, -21)
        iaddk(p, 2, 2, 983)
        ws(p, 4, 2)
        inp(p, 0, 1)                                  # DEC
        p.iconst(1, 45)
        imul_small(p, 2, 0, 1)
        p.lsh(2, 2, -12)
        iaddk(p, 2, 2, 220)
        table_word(p, L, 4, "hostQ", 2)
        ws(p, 1, 4)
        inp(p, 0, 2)                                  # ENH
        p.lsh(0, 0, -7)
        isubk(p, 2, 1250, 0)
        ws(p, 9, 2)
        ws(p, 10, 2)
        inp(p, 0, 4)                                  # TONE
        p.lsh(0, 0, 8)
        isubk(p, 2, 6291455, 0)
        ws(p, 5, 2)
        iaddk(p, 2, 0, 2097152)
        ws(p, 6, 2)
        inp(p, 0, 3)                                  # DAMP
        p.iconst(1, 384)
        imul_small(p, 2, 0, 1)
        iaddk(p, 2, 2, 1966080)
        ws(p, 7, 2)
        ws(p, 8, 2)
        inp(p, 0, 5)                                  # BUMP
        p.iconst(1, 36)
        imul_small(p, 2, 0, 1)
        p.lsh(2, 2, -12)
        iaddk(p, 2, 2, 100)
        table_word(p, L, 4, "hostQ", 2)
        ws(p, 2, 4)

        def bump():
            inp(p, 0, 5)
            imul_k(p, 2, 0, 43691)
            p.lsh(2, 2, -17)
            ws(p, 11, 2)
        note_only(p, bump)
        for k, off in ((9, TRXCB.F1), (10, TRXCB.F2)):   # the filters (index $7F)
            w(p, 9, k)
            p.iconst(10, 0x7F)
            set_hpc(p, L, off)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        clear(p, (2, 3))
        hpc_clear(p, TRXCB.F1)
        hpc_clear(p, TRXCB.F2)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        s(p, 0, 1)
        iaddk(p, 0, 0, 0x50C335)
        _clamp(p, 0)
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
                s(p, 1, 4)                            # (S4 is only the body's)

                def one():
                    p.ipass(5, 1)
                    p.iconst(6, 0x733333)
                    wmul(p)
                    p.ipass(1, 4)
                    to_q23(p, 4, 4)
                out_loop(p, L, one)

            def silent():
                out_loop(p, L, lambda: p.fconst(4, 0.0))
            p._branch(lambda: p.r[1] == p.r[12], "EQ", fade, silent)

        def body():
            # the increments (W3 - B) / 2, (W4 + B) / 2 sine indices; then B decays
            w(p, 1, 11)
            w(p, 2, 3)
            p.iop(2, 2, "-", 1)
            p.lsh(2, 2, 16)
            p.st(L.C["a"], 2)
            w(p, 2, 4)
            iadd(p, 2, 2, 1)
            p.lsh(2, 2, 16)
            p.st(L.C["b"], 2)
            w(p, 5, 2)
            p.ipass(6, 1)
            wmul(p)
            ws(p, 11, 4)
            # the levels, then the amp's decay (a block)
            for k, c in ((5, "c"), (6, "d"), (1, None)):
                s(p, 5, 1)
                w(p, 6, k)
                wmul(p)
                if c:
                    p.st(L.C[c], 4)
                else:
                    ss(p, 1, 4)
            state_base(p, L)

            def osc(ph, inc, thr, lvl, off):
                s(p, 6, ph)
                K.sine(p, L, 4, 6)
                p.ld(10, L.C[inc])
                p.iop(6, 10, "+", 6)
                ss(p, ph, 6)
                to_word(p, 5, 4)
                w(p, 6, thr)
                p.if_(5, "GT", 6, lambda: p.iconst(5, 0x7FFCB9), kind="i")
                p.iconst(12, 0)
                p.iop(7, 12, "-", 5)
                p.if_(7, "GT", 6, lambda: p.iconst(5, -0x7FFCB9), kind="i")
                p.ld(6, L.C[lvl])
                wmul(p)
                hpc(p, off)

            def one():
                osc(2, "a", 7, "c", TRXCB.F1)
                p.ipass(1, 4)
                osc(3, "b", 8, "d", TRXCB.F2)
                iadd(p, 4, 4, 1)
                p.ash(4, 4, -2)
                ss(p, 4, 4)
                to_q23(p, 4, 4)
            out_loop(p, L, one)
        p.ifz(0, "NE", counting, body)


# =========================================================================== TRX-CH / OH
class TRXCH:
    """Closed hat (md_models.TRXCH): noise and the six metal wavetables -> res4 (LPF) ->
    hp1 (HPF) -> a fixed hp1 (indices $30/0); a hold / linear / exponential envelope;
    out = env x / 2. TRX-OH is the same DSP code with its own scale function.
    W1 linear step, W2 exponential decay, W3/W4 LPF, W5 noise level, W6/W7 HPF, W8 osc
    level; with a note W9 hold blocks, W10 linear blocks (counted down in place).
    State: S0 env, S1-S5 latched osc levels, S6/S7 noise, S8-S13 wavetable positions,
    S14.. res4, S30.. hp1, S38.. the fixed hp1."""
    NAME, ID = "TRX-CH", 22
    PNAMES = ("GAP", "DEC", "HPF", "LPF", "MTAL", "-", "-", "-")
    RS, HP, FX = 14, 14 + RES4_N, 14 + RES4_N + HP1_N

    @staticmethod
    def _gap(p: Prog) -> None:
        inp(p, 0, 0)
        p.lsh(2, 0, -8)

    @staticmethod
    def _dec(p: Prog) -> None:
        inp(p, 0, 1)
        p.lsh(2, 0, -6)

    @classmethod
    def host(cls, p: Prog, L: K.Layout) -> None:
        cls._gap(p)                                   # GAP
        iaddk(p, 2, 2, 227)
        table_word(p, L, 3, "hostD", 2)
        ws(p, 2, 3)
        inp(p, 0, 3)                                  # LPF
        imul_k(p, 2, 0, 44151)
        p.lsh(2, 2, -22)
        iaddk(p, 2, 2, 1664)
        ws(p, 3, 2)
        inp(p, 0, 2)                                  # HPF
        imul_k(p, 2, 0, 11651)
        p.lsh(2, 2, -20)
        iaddk(p, 2, 2, 1536)
        ws(p, 6, 2)
        p.iconst(2, 70)
        ws(p, 4, 2)
        ws(p, 7, 2)
        inp(p, 0, 4)                                  # MTAL
        p.iconst(1, 25)
        imul_small(p, 2, 0, 1)
        isubk(p, 2, 0x80000, 2)
        ws(p, 5, 2)
        p.iconst(1, 14)
        imul_small(p, 2, 0, 1)
        iaddk(p, 2, 2, 65536)
        ws(p, 8, 2)
        p.iconst(2, 294)
        ws(p, 1, 2)

        def note():
            p.iconst(2, 1)
            ws(p, 9, 2)
            cls._dec(p)                               # DEC
            ws(p, 10, 2)
        note_only(p, note)
        w(p, 9, 3)
        w(p, 10, 4)
        set_res4(p, L, cls.RS)
        w(p, 9, 6)
        w(p, 10, 7)
        set_hp1(p, L, cls.HP)
        p.iconst(9, 0x30)
        p.iconst(10, 0)
        set_hp1(p, L, cls.FX)

    @classmethod
    def init(cls, p: Prog, L: K.Layout) -> None:
        clear(p, (0, 6, 8, 9, 10, 11, 12, 13))
        p.iconst(0, 1)
        ss(p, 7, 0)

    @classmethod
    def trig(cls, p: Prog, L: K.Layout) -> None:
        s(p, 0, 0)
        iaddk(p, 0, 0, 0x6CCCCD)
        _clamp(p, 0)
        ss(p, 0, 0)
        w(p, 0, 8)
        for k in range(1, 6):
            ss(p, k, 0)
        res4_clear(p, cls.RS)
        hp1_clear(p, cls.HP)
        hp1_clear(p, cls.FX)

    @classmethod
    def render(cls, p: Prog, L: K.Layout) -> None:
        C = L.C
        w(p, 1, 8)
        level_f(p, L, "a", 1)
        for j in range(1, 6):
            s(p, 1, j)
            level_f(p, L, WLVL[j], 1)
        w(p, 1, 5)
        to_q23(p, 1, 1)
        p.st(C["h"], 1)
        wavetables(p, L, 8, (6, 7, "h"))
        # the envelope's phase this block: 0 hold, 1 linear, 2 exponential
        s(p, 1, 0)                                    # e (R1 through the loop)

        def phase(k, mode, other):
            def go():
                w(p, 0, k)
                p.iconst(12, -1)
                p.iop(0, 12, "+", 0)
                ws(p, k, 0)
                p.iconst(0, mode)
                p.st(C["g"], 0)
            w(p, 0, k)
            p.ifz(0, "NE", go, other)

        def exp_():
            p.iconst(0, 2)
            p.st(C["g"], 0)
        phase(9, 0, lambda: phase(10, 1, exp_))
        state_base(p, L)

        def one():
            p.ldi(4, 0, 5)
            res4(p, cls.RS)
            hp1(p, cls.HP)
            hp1(p, cls.FX)
            p.ipass(6, 4)
            p.ipass(5, 1)
            wmul(p)
            p.ash(2, 4, -1)                           # sat(mpy(e, x) >> 1)
            p.ld(0, C["g"])
            p.iconst(12, 1)
            p.e("COMP(R0, R12);")

            def linear():
                w(p, 5, 1)
                p.iop(1, 1, "-", 5)

            def expo():
                w(p, 5, 2)
                p.ipass(6, 1)
                wmul(p)
                p.ipass(1, 4)
            p._branch(lambda: p.r[0] == 1, "EQ", linear,
                      lambda: p.ifz(0, "NE", expo))
            p.ipass(4, 2)
        out_ints(p, L, one)
        p.ld(0, C["g"])
        p.ifz(0, "NE", lambda: ss(p, 0, 1))


class TRXOH(TRXCH):
    """Open hat: TRX-CH's DSP code, the OS's TRX-OH scale function (GAP, DEC)."""
    NAME, ID = "TRX-OH", 23

    @staticmethod
    def _gap(p: Prog) -> None:
        inp(p, 0, 0)
        p.lsh(2, 0, -7)
        p.iconst(12, 0x1FF)
        p.iop(2, 2, "AND", 12)

    @staticmethod
    def _dec(p: Prog) -> None:
        inp(p, 0, 1)
        imul_k(p, 2, 0, 34953)
        p.lsh(2, 2, -19)
        iaddk(p, 2, 2, 37)


# =========================================================================== TRX-CY
class TRXCY:
    """Cymbal (md_models.TRXCY): the six metal wavetables at RICH's levels, then two paths:
    hpc ($680 / PEAK) -> res4 (TTUN / PEAK) times env1 and TOP, and hpc (SIZE / PEAK) ->
    res4 (SIZE / PEAK) times env2 and 1/2; out = the sum / 2.
    W1/W13 env decays (a block), W2-W7 wavetable levels, W8 TTUN, W9/W10 SIZE, W11 TOP,
    W12 the table index (PEAK; latched at a note for three of the four filters).
    State: S0/S1 envs, S2-S4 latched PEAK, S5-S10 positions, S11.. hpc A, S29.. res4 B,
    S45.. hpc C, S63.. res4 D."""
    NAME, ID = "TRX-CY", 24
    PNAMES = ("RICH", "DEC", "TOP", "TTUN", "SIZE", "PEAK", "-", "-")
    FA, FB = 11, 11 + HPC_N
    FC = FB + RES4_N
    FD = FC + HPC_N

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        def q(d, x):                                   # ((x >> 2) 18725) >> 17
            p.lsh(14, x, -2)
            p.ipass(15, 14)
            imul_k(p, d, 15, 18725)
            p.lsh(d, d, -17)

        def mulk_shift(d, x, c, n):
            imul_k(p, d, x, c)
            p.lsh(d, d, -n)

        def pick(limit, lo, hi, d):
            """Rd = lo() if x <= LIMIT else hi() (x in R0)."""
            p.iconst(12, limit)
            p.if_(0, "LE", 12, lo, hi, kind="i")

        inp(p, 0, 0)                                  # RICH
        p.lsh(9, 0, -5)                               # x >> 5
        p.iconst(15, 0)
        # d7 (R1), d4 (R4), d6 (R6), d5 (R5), d2 (R2), d1 (R7)
        pick(8191, lambda: p.ipass(1, 9), lambda: isubk(p, 1, 512, 9), 1)
        iaddk(p, 4, 9, -256)
        pick(10799, lambda: (q(6, 0), iaddk(p, 6, 6, -123)),
             lambda: (p.lsh(8, 0, -1), mulk_shift(6, 8, 49933, 20), isubk(p, 6, 512, 6)), 6)
        pick(13409, lambda: (q(5, 0), iaddk(p, 5, 5, -215)),
             lambda: (mulk_shift(5, 0, 57457, 22), isubk(p, 5, 441, 5)), 5)
        pick(2239, lambda: (mulk_shift(2, 0, 48211, 22), isubk(p, 2, -230, 2)),
             lambda: (mulk_shift(2, 0, 18079, 19), iaddk(p, 2, 2, -333)), 2)

        def a52():
            mulk_shift(7, 0, 23705, 16)               # t
            p.iop(8, 0, "-", 7)
            p.iconst(12, 0xFFFF)
            p.iop(8, 8, "AND", 12)
            p.lsh(8, 8, -1)
            p.iop(7, 8, "+", 7)
            p.lsh(7, 7, -5)
            isubk(p, 7, -154, 7)
        pick(4849, a52, lambda: (q(7, 0), iaddk(p, 7, 7, -428)), 7)
        p.lsh(3, 0, -3)
        isubk(p, 3, 2048, 3)                          # d3
        for k, r in ((2, 1), (3, 6), (4, 5), (5, 4), (6, 2), (7, 7)):
            imul_small(p, 8, r, 3)
            iaddk(p, 8, 8, 409532)
            ws(p, k, 8)
        inp(p, 0, 1)                                  # DEC
        p.lsh(1, 0, 1)
        iaddk(p, 2, 1, 8349693)
        ws(p, 1, 2)
        iaddk(p, 2, 1, 8332859)
        ws(p, 13, 2)
        inp(p, 0, 2)                                  # TOP
        p.iconst(1, 384)
        imul_small(p, 2, 0, 1)
        iaddk(p, 2, 2, 2097152)
        ws(p, 11, 2)
        inp(p, 0, 3)                                  # TTUN
        p.lsh(2, 0, -6)
        iaddk(p, 2, 2, 1536)
        ws(p, 8, 2)
        inp(p, 0, 4)                                  # SIZE
        p.lsh(1, 0, -6)
        iaddk(p, 2, 1, 1024)
        ws(p, 9, 2)
        iaddk(p, 2, 1, 1536)
        ws(p, 10, 2)
        inp(p, 0, 5)                                  # PEAK
        imul_k(p, 2, 0, 43691)
        p.lsh(2, 2, -24)
        iaddk(p, 2, 2, 32)
        ws(p, 12, 2)
        TRXCY._coefs(p, L)

    @staticmethod
    def _coefs(p: Prog, L: K.Layout) -> None:
        p.iconst(9, 0x680)
        w(p, 10, 12)
        set_hpc(p, L, TRXCY.FA)
        w(p, 9, 8)
        s(p, 10, 2)
        set_res4(p, L, TRXCY.FB)
        w(p, 9, 9)
        s(p, 10, 3)
        set_hpc(p, L, TRXCY.FC)
        w(p, 9, 10)
        s(p, 10, 4)
        set_res4(p, L, TRXCY.FD)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        clear(p, range(5, 11))
        hpc_clear(p, TRXCY.FA)
        res4_clear(p, TRXCY.FB)
        hpc_clear(p, TRXCY.FC)
        res4_clear(p, TRXCY.FD)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        for k in (0, 1):
            s(p, 0, k)
            iaddk(p, 0, 0, 0x50C335)
            _clamp(p, 0)
            ss(p, k, 0)
        w(p, 0, 12)
        for k in (2, 3, 4):
            ss(p, k, 0)
        TRXCY._coefs(p, L)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        C = L.C
        for j in range(6):
            w(p, 1, 2 + j)
            level_f(p, L, WLVL[j], 1)
        wavetables(p, L, 5)
        # this block's envs, then their decays
        for k, dk in ((0, 13), (1, 1)):
            s(p, 5, k)
            p.st(C["g" if k == 0 else "h"], 5)
            w(p, 6, dk)
            wmul(p)
            ss(p, k, 4)
        state_base(p, L)

        def one():
            p.ldi(4, 0, 5)
            p.ipass(1, 4)
            hpc(p, TRXCY.FA)
            res4(p, TRXCY.FB)
            p.ipass(2, 4)                             # path 1
            p.ipass(4, 1)
            hpc(p, TRXCY.FC)
            res4(p, TRXCY.FD)
            p.ipass(1, 4)                             # path 2
            p.ipass(5, 2)
            p.ld(6, C["g"])
            wmul(p)
            p.ipass(2, 4)                             # p1 env1
            p.ipass(5, 1)
            p.ld(6, C["h"])
            wmul(p)
            p.ipass(1, 4)                             # p2 env2
            p.ipass(5, 2)
            w(p, 6, 11)
            wmul2(p)                                  # floor(2 mpy(p1, TOP))
            iadd(p, 4, 4, 1)
            p.ash(4, 4, -2)
        out_ints(p, L, one)


# =========================================================================== TRX-MA
class TRXMA:
    """Maracas (md_models.TRXMA): noise through an hpc (RTYP) is the body; the same noise
    block read backwards drives a bead model (a rise from -$347 by 1.54 a sample until it
    passes -|noise|, then +|noise| decaying by 0.955) -> hpc (TONE/HARD) / 8 -> hpc (REV
    tone); mixed with the body times a ramp (RATL a block); an attack / sustain / release
    envelope; out = x env / 4. The host sends words only with a note.
    FIRMWARE BUG kept: the shaker's first filter reads its last two inputs past the end
    of the bead buffer (X:$42/$43, which nothing in TRX-MA writes; the golden vectors
    have 0, 0): here two words after the buffer, kept 0.
    W1/W3/W4 phase lengths (blocks, counted down in place), W2/W5 slopes, W6 threshold,
    W7/W8 TONE/HARD, W9 REV tone, W10 RTYP, W11 RATL.
    State: S0 env, S1 ramp, S2 bead, S3 bead target, S4 bead factor, S5/S6 noise,
    S7.. / S25.. / S43.. the three hpc, S61..S94 the bead buffer (32 + the two stale)."""
    NAME, ID = "TRX-MA", 25
    PNAMES = ("ATT", "SUS", "REV", "DAMP", "RATL", "RTYP", "TONE", "HARD")
    F1, F2, F3 = 7, 7 + HPC_N, 7 + 2 * HPC_N
    SH = 7 + 3 * HPC_N
    K_DECAY, K_GROW = 0x7A3E22, 0x450D02

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        def words():
            inp(p, 0, 0)                              # ATT
            p.lsh(1, 0, -6)
            iaddk(p, 9, 1, 10)
            ws(p, 1, 9)
            p.lsh(1, 0, -1)
            iaddk(p, 1, 1, 42)
            p.iconst(2, 8388608)
            idiv(p, 3, 2, 1)
            ws(p, 2, 3)
            inp(p, 0, 1)                              # SUS
            p.lsh(1, 0, -6)
            iaddk(p, 10, 1, 1)
            ws(p, 3, 10)
            inp(p, 0, 2)                              # REV
            p.lsh(1, 0, -6)
            iaddk(p, 11, 1, 10)
            ws(p, 4, 11)
            p.lsh(1, 0, -3)
            iaddk(p, 1, 1, 16)
            p.iconst(2, 8388608)
            idiv(p, 3, 2, 1)
            ws(p, 5, 3)
            inp(p, 0, 3)                              # DAMP
            p.lsh(1, 0, 7)
            isubk(p, 1, 7879228, 1)
            ws(p, 6, 1)
            inp(p, 0, 4)                              # RATL
            p.lsh(2, 0, 6)
            iadd(p, 1, 9, 10)
            iadd(p, 1, 1, 11)
            idiv(p, 3, 2, 1)
            ws(p, 11, 3)
            inp(p, 0, 5)                              # RTYP
            p.lsh(1, 0, -4)
            iaddk(p, 1, 1, 1024)
            ws(p, 10, 1)
            inp(p, 0, 6)                              # TONE
            p.lsh(1, 0, -6)
            iaddk(p, 2, 1, 1536)
            ws(p, 7, 2)
            iaddk(p, 2, 1, 1504)
            ws(p, 9, 2)
            inp(p, 0, 7)                              # HARD
            p.lsh(1, 0, -8)
            ws(p, 8, 1)
            for tw, iw, off in ((10, None, TRXMA.F1), (7, 8, TRXMA.F2), (9, None, TRXMA.F3)):
                w(p, 9, tw)
                if iw:
                    w(p, 10, iw)
                else:
                    p.iconst(10, 0x7F if off == TRXMA.F1 else 0)
                set_hpc(p, L, off)
        note_only(p, words)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        p.iconst(0, 0x29A)
        ss(p, 5, 0)
        p.iconst(0, 1)
        ss(p, 6, 0)
        for off in (TRXMA.F1, TRXMA.F2, TRXMA.F3):
            hpc_clear(p, off)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        clear(p, (0, 1, 2))

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        C = L.C
        out_loop(p, L, lambda: fibw(p, 5, 6, 4))      # the noise block (words, at OUT0)
        # ---- the bead, on the noise block backwards, into the bead buffer
        p.ld(11, C["mdb"])
        iaddk(p, 11, 11, 4 * (K.OUT0 + 31))
        p.ld(1, C["mdb"])
        iaddk(p, 1, 1, 4 * (K.S0 + TRXMA.SH))
        p.seti(5, 1)
        s(p, 1, 3)                                    # b
        s(p, 2, 2)                                    # x0

        def bead():
            p.seti(1, 11)
            p.ldi(4, 0, 1)                            # v
            p.iconst(12, -4)
            p.iop(11, 12, "+", 11)
            w(p, 5, 6)

            def start():
                p.iconst(2, -0x347)
                p.iconst(12, 0)
                p.iop(1, 12, "-", 4)
                p.iconst(5, TRXMA.K_GROW)
                ss(p, 4, 5)
            p.if_(4, "GE", 5, start, kind="i")

            def idle():
                s(p, 5, 4)
                p.ipass(6, 2)
                wmul(p)
                p.ipass(2, 4)
                p.ipass(8, 4)

            def track():
                s(p, 5, 4)
                p.ipass(6, 2)
                wmulr(p)
                iadd(p, 4, 4, 2)                      # X0 + floor(mpy(x1, x0))
                p.ipass(8, 4)
                _clamp(p, 8)                          # sat(a)
                p.ipass(2, 8)

                def flip():
                    p.iconst(12, 0)
                    p.iop(1, 12, "-", 1)
                    p.ipass(2, 1)
                    _clamp(p, 2)
                    p.iconst(1, 0)
                    p.iconst(5, TRXMA.K_DECAY)
                    ss(p, 4, 5)
                # a <= b: below b, or level with it and nothing below the word
                p.if_(4, "LT", 1, flip,
                      lambda: p.if_(4, "EQ", 1, lambda: p.ifz(3, "EQ", flip), kind="i"), kind="i")
            p.ifz(1, "NE", track, idle)
            p.stpost(5, 8)
        p.loop(C["n1"], 32, bead)
        _clamp(p, 1)
        ss(p, 3, 1)
        ss(p, 2, 2)
        clear(p, (TRXMA.SH + 32, TRXMA.SH + 33))     # the two stale words
        # ---- the ramp (a block), the envelope's phase
        s(p, 0, 1)
        w(p, 1, 11)
        iadd(p, 0, 0, 1)
        _clamp(p, 0)
        ss(p, 1, 0)
        p.st(C["a"], 0)
        s(p, 0, 0)
        p.st(C["k"], 0)                               # the envelope accumulator

        def phase(k, mode, other):
            def go():
                w(p, 0, k)
                p.iconst(12, -1)
                p.iop(0, 12, "+", 0)
                ws(p, k, 0)
                p.iconst(0, mode)
                p.st(C["g"], 0)
            w(p, 0, k)
            p.ifz(0, "NE", go, other)

        def silent():
            p.iconst(0, 0)
            p.st(C["g"], 0)
        phase(1, 1, lambda: phase(3, 2, lambda: phase(4, 3, silent)))
        state_base(p, L)
        p.ld(1, C["mdb"])
        iaddk(p, 1, 1, 4 * (K.S0 + TRXMA.SH + 2))

        def one():
            p.ldi(4, 0, 5)
            hpc(p, TRXMA.F1)
            p.ipass(2, 4)                             # the body
            p.seti(1, 1)
            p.ldi(4, 0, 1)                            # the bead, two words on
            p.iconst(12, 4)
            p.iop(1, 12, "+", 1)
            hpc(p, TRXMA.F2)
            p.ash(4, 4, -3)
            hpc(p, TRXMA.F3)
            p.ipass(5, 2)
            p.ipass(2, 4)
            p.ld(6, C["a"])
            wmul(p)                                   # body ramp
            iadd(p, 4, 4, 2)
            _clamp(p, 4)
            p.ld(0, C["g"])

            def env(slope, sign):
                def go():
                    p.ld(3, C["k"])
                    w(p, 5, slope)
                    p.iop(3, 3, sign, 5) if sign == "-" else iadd(p, 3, 3, 5)
                    p.st(C["k"], 3)
                    _clamp(p, 3)
                    p.ipass(5, 4)
                    p.ipass(6, 3)
                    wmul(p)
                    p.ash(4, 4, -2)
                return go

            def rest():
                p.iconst(12, 2)
                p.e("COMP(R0, R12);")
                p._branch(lambda: p.r[0] == 2, "EQ", lambda: p.ash(4, 4, -2),
                          lambda: p.ifz(0, "NE", env(5, "-"), lambda: p.iconst(4, 0)))
            p.iconst(12, 1)
            p.e("COMP(R0, R12);")
            p._branch(lambda: p.r[0] == 1, "EQ", env(2, "+"), rest)
        out_ints(p, L, one)
        p.ld(0, C["g"])
        p.iconst(12, 2)
        p.e("COMP(R0, R12);")

        def store():
            p.ld(0, C["k"])
            _clamp(p, 0)
            ss(p, 0, 0)
        p._branch(lambda: p.r[0] != 2, "NE", lambda: (p.ld(0, C["g"]), p.ifz(0, "NE", store)), None)


# =========================================================================== TRX-S2
class TRXS2:
    """Snare 2 (md_models.TRXS2): a note's first block is a "power" click only (and the
    last block's noise again); then two bumped sines plus the power's decay, under an amp
    envelope, and 96 noise words a block: 32 drive a crackle envelope gating the next
    32, 16 more are mixed in, the rest only move the generator (stored swapped) -> hpc
    (NTUN) -> res4 (1900 / 0) -> the noise envelope; out = 2 (body amp + noise).
    FIRMWARE BUG kept: the scale function never writes W14/W15 (the bump decays), which
    init sets; every later host block overwrites them with the host buffer's leftovers
    (0, host_scale.UNWRITTEN), so only the first note after the machine is chosen has the
    intended decays. (S12 marks a fresh init, so the voice's init-then-host order keeps
    them for that note as the Machinedrum's host-then-init does.)
    W1 noise tune, W2 decay, W3/W4 osc levels, W5 DEC blocks, W6 POWR, W7/W8 osc pitch,
    W9 noise mix, W10/W11 bump rates, W12 noise attack, W13 noise decay, W14/W15 bump
    decays, W16 0, W17 1900, W18 crackle threshold, W19 0, W20 NDEC blocks.
    State: S0/S1 bumps, S2 noise env, S3/S4 phases, S5 the last sample, S6/S7 noise,
    S8 power, S9 block count, S10 amp, S11 crackle env, S12 fresh, S13.. hpc, S31.. res4,
    S47..S78 the noise block (kept for a note's first block)."""
    NAME, ID = "TRX-S2", 29
    PNAMES = ("PTCH", "DEC", "NOIS", "NDEC", "POWR", "TUNE", "NTUN", "NTYP")
    HP, RS = 13, 13 + HPC_N
    XA = 13 + HPC_N + RES4_N
    K39, K59, K40 = 0x7FFB11, 0x7FA33A, 0x7CE567
    K57, K58 = 0x0A3D71, 0x79999A

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                  # PTCH
        p.lsh(1, 0, -2)
        iaddk(p, 1, 1, 2000)
        ws(p, 7, 1)
        p.iconst(1, 3)
        imul_small(p, 2, 0, 1)
        p.lsh(2, 2, -4)                               # t
        p.iconst(1, 1495)
        imul_small(p, 3, 2, 1)
        iaddk(p, 3, 3, 3061760)
        p.ash(3, 3, -10)
        ws(p, 8, 3)

        def two_part(k, base, tw, nw):
            inp(p, 0, k)
            p.iconst(12, 8191)

            def lo():
                p.iconst(1, base)
                table_word(p, L, 2, "hostD", 1)
                ws(p, tw, 2)
                p.lsh(1, 0, -6)
                ws(p, nw, 1)

            def hi():
                iaddk(p, 1, 0, -8192)
                p.lsh(1, 1, -6)
                iaddk(p, 1, 1, base)
                table_word(p, L, 2, "hostD", 1)
                ws(p, tw, 2)
                p.iconst(1, 128)
                ws(p, nw, 1)
            p.if_(0, "LE", 12, lo, hi, kind="i")
        two_part(1, 130, 2, 5)                        # DEC
        two_part(3, 45, 13, 20)                       # NDEC
        inp(p, 0, 2)                                  # NOIS
        p.lsh(1, 0, 6)
        p.iconst(12, 0x3FFFC0)
        p.iop(1, 1, "AND", 12)
        ws(p, 12, 1)
        inp(p, 0, 4)                                  # POWR
        p.lsh(1, 0, 7)
        ws(p, 6, 1)
        imul_var(p, 1, 0, 0)
        p.lsh(2, 1, -23)
        ws(p, 10, 2)
        p.lsh(2, 1, -22)
        ws(p, 11, 2)
        inp(p, 0, 7)                                  # NTYP
        p.lsh(1, 0, 7)
        isubk(p, 2, 7500000, 1)
        ws(p, 18, 2)
        p.iconst(12, 8191)
        p.if_(0, "LE", 12, lambda: ws(p, 9, 1),
              lambda: (p.lsh(1, 0, 9), iaddk(p, 1, 1, -3145728), ws(p, 9, 1)), kind="i")
        inp(p, 0, 5)                                  # TUNE
        p.lsh(1, 0, 7)
        isubk(p, 2, 0x7FFFFF, 1)
        p.ash(2, 2, -1)
        ws(p, 3, 2)
        p.lsh(1, 1, -1)
        ws(p, 4, 1)
        inp(p, 0, 6)                                  # NTUN
        p.lsh(1, 0, -4)
        iaddk(p, 1, 1, 1024)
        ws(p, 1, 1)
        p.iconst(1, 1900)
        ws(p, 17, 1)
        p.iconst(1, 0)
        ws(p, 16, 1)
        ws(p, 19, 1)
        s(p, 2, 12)                                   # W14/W15: the leftovers (0), but
        p.ifz(2, "EQ", lambda: (ws(p, 14, 1), ws(p, 15, 1)))   # not over a fresh init's
        w(p, 9, 1)
        w(p, 10, 16)
        set_hpc(p, L, TRXS2.HP)
        w(p, 9, 17)
        w(p, 10, 19)
        set_res4(p, L, TRXS2.RS)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        for k, v in ((6, 0x29A), (7, 1), (11, 0x7EB852), (12, 1)):
            p.iconst(0, v)
            ss(p, k, 0)
        for k, v in ((14, 0x74CB2B), (15, 0x75FC33)):
            p.iconst(0, v)
            ws(p, k, 0)
        # (the DSP leaves the filters and the noise block as they were; here they start
        # clear, as the golden vectors have them, not as another machine left them)
        hpc_clear(p, TRXS2.HP)
        res4_clear(p, TRXS2.RS)
        clear(p, range(TRXS2.XA, TRXS2.XA + 32))

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        p.iconst(0, 0x50C335)
        ss(p, 10, 0)
        clear(p, (8, 2, 0, 1, 9, 3, 4, 12))

    @staticmethod
    def _osc(p: Prog, L: K.Layout, k: int) -> None:
        """The increment of osc K (0, 1) this block into scratch a / b, then its bump."""
        C = L.C
        w(p, 1, 7 + k)
        p.lsh(1, 1, 12)
        s(p, 2, k)
        p.lsh(3, 2, 13)
        iadd(p, 1, 1, 3)
        p.st(C["ab"[k]], 1)
        s(p, 0, 9)
        p.iconst(12, 12)

        def decay():
            w(p, 5, 14 + k)
            p.ipass(6, 2)
            wmul(p)
            ss(p, k, 4)

        def rise():
            w(p, 1, 10 + k)
            p.lsh(1, 1, 1)
            iadd(p, 1, 1, 2)
            _clamp(p, 1)
            ss(p, k, 1)
        p.if_(0, "GT", 12, decay, rise, kind="i")

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        C = L.C
        S = TRXS2

        def power_block():
            s(p, 1, 8)                                # x1

            def one():
                p.iconst(5, S.K40)
                p.ipass(6, 1)
                wmul2(p)                              # floor(2 mpy(k40, x1))
                w(p, 5, 6)
                p.ash(1, 4, -1)
                iadd(p, 1, 1, 5)
                _clamp(p, 1)                          # x1 = sat(a)
                p.lsh(5, 5, 1)
                iadd(p, 4, 4, 5)
                _clamp(p, 4)                          # sat(2 a)
            out_loop(p, L, one)
            ss(p, 8, 1)

        def body_block():
            S._osc(p, L, 0)
            S._osc(p, L, 1)
            # noise words 0..31: the crackle envelope (at OUT0)
            s(p, 1, 11)
            w(p, 2, 18)

            def crackle():
                fibw(p, 6, 7, 4)
                p.if_(4, "GT", 2, lambda: iaddk(p, 1, 1, S.K57), kind="i")
                _clamp(p, 1)
                p.ipass(9, 1)
                p.st(C["c"], 9)
                p.ipass(6, 1)
                p.iconst(5, S.K58)
                wmul(p)                               # (R2 is kept: wmul leaves it)
                p.ipass(1, 4)
                p.ld(4, C["c"])
            out_loop(p, L, crackle)
            _clamp(p, 1)
            ss(p, 11, 1)
            # 32..63: gated by it
            p.ld(1, C["mdb"])
            iaddk(p, 1, 1, 4 * K.OUT0)

            def gate():
                fibw(p, 6, 7, 5)
                p.seti(1, 1)
                p.ldi(6, 0, 1)
                wmul(p)
                p.seti(1, 1)
                p.sti(0, 1, 4)
                p.iconst(12, 4)
                p.iop(1, 12, "+", 1)
            p.loop(C["n1"], 32, gate)
            # 64..79: mixed in, each into a pair
            p.ld(1, C["mdb"])
            iaddk(p, 1, 1, 4 * K.OUT0)

            def mix():
                fibw(p, 6, 7, 6)
                w(p, 5, 9)
                wmul(p)
                p.seti(1, 1)
                p.ldi(5, 0, 1)
                iadd(p, 4, 4, 5)
                p.ash(4, 4, -1)
                p.sti(0, 1, 4)
                p.sti(1, 1, 4)
                p.iconst(12, 8)
                p.iop(1, 12, "+", 1)
            p.loop(C["n1"], 16, mix)
            p.loop(C["n1"], 16, lambda: fibw(p, 6, 7, 4))    # 80..95
            s(p, 0, 6)
            s(p, 1, 7)
            ss(p, 6, 1)
            ss(p, 7, 0)                               # stored swapped
            # the noise envelope (a block)
            s(p, 1, 2)
            s(p, 0, 9)
            p.iconst(12, 32)
            p.if_(0, "LE", 12, lambda: (w(p, 2, 12), iadd(p, 1, 1, 2)), kind="i")
            _clamp(p, 1)
            w(p, 2, 20)
            p.if_(0, "LE", 2, lambda: p.iconst(5, S.K59), lambda: w(p, 5, 13), kind="i")
            p.ipass(6, 1)
            wmul(p)
            ss(p, 2, 4)
            p.st(C["d"], 4)
            # the samples: noise -> hpc -> res4 -> * noise env (kept); the body
            state_base(p, L)
            p.ld(1, C["mdb"])
            iaddk(p, 1, 1, 4 * (K.S0 + S.XA))

            def one():
                p.ldi(4, 0, 5)
                hpc(p, S.HP)
                res4(p, S.RS)
                p.ipass(5, 4)
                p.ld(6, C["d"])
                wmul(p)
                p.seti(1, 1)
                p.sti(0, 1, 4)                        # the noise, kept (S47..)
                p.iconst(12, 4)
                p.iop(1, 12, "+", 1)
                for k in (0, 1):
                    s(p, 6, 3 + k)
                    K.sine(p, L, 4, 6)
                    p.ld(10, C["ab"[k]])
                    p.iop(6, 10, "+", 6)
                    ss(p, 3 + k, 6)
                    to_word(p, 5, 4)
                    w(p, 6, 3 + k)
                    wmul(p)
                    if k == 0:
                        p.ipass(2, 4)
                    else:
                        iadd(p, 2, 2, 4)              # o1 + o2
                p.iconst(5, S.K40)
                s(p, 6, 8)
                wmul4(p)                              # floor(4 mpy(k40, x0))
                iadd(p, 2, 2, 4)
                p.ash(4, 4, -2)
                ss(p, 8, 4)                           # x0 = sat(mpy(k40, x0))
                p.ash(4, 2, -1)
                _clamp(p, 4)                          # the body
            out_loop(p, L, one)

        s(p, 0, 9)
        p.ifz(0, "LE", power_block, body_block)
        # the amp envelope (DEC blocks of $7FFB11, then W2) and the sum with the noise
        s(p, 0, 9)
        w(p, 1, 5)
        p.if_(0, "GT", 1, lambda: w(p, 2, 2), lambda: p.iconst(2, S.K39), kind="i")
        p.st(C["e"], 2)
        iaddk(p, 0, 0, 1)
        ss(p, 9, 0)
        s(p, 2, 10)
        p.ld(1, C["mdb"])
        iaddk(p, 1, 1, 4 * (K.S0 + S.XA))

        def out():
            p.ldi(5, 0, 5)
            p.ipass(6, 2)
            wmul(p)
            p.st(C["c"], 4)
            p.ipass(5, 2)
            p.ld(6, C["e"])
            wmul(p)
            p.ipass(2, 4)
            p.ld(4, C["c"])
            p.seti(1, 1)
            p.ldi(5, 0, 1)
            iadd(p, 4, 4, 5)
            p.lsh(4, 4, 1)
            _clamp(p, 4)
            p.iconst(12, 4)
            p.iop(1, 12, "+", 1)
        out_ints(p, L, out)
        ss(p, 10, 2)


MACHINES = (TRXCP, TRXCB, TRXCH, TRXOH, TRXCY, TRXMA, TRXS2)

"""P-I BD (and, with its own words, P-I MT): the Machinedrum's physical-model drums
(docs/md.md), from DSP2's P-IBD / P-IMT and their host scale functions.

The model, as DSP2 computes it each 32-sample block:
  - an excitation table read at a pitch-dependent rate (a 48-bit position: an integer
    offset and a 24-bit fraction, linear interpolation with weights in [0, 2)), the rate
    PTCH x (1/2 + TENS x a per-block decay) (MT: the decay's depth from HARD);
  - a one-pole "hammer" filter (HAMR) on it: h;
  - three 512-word delay lines, each read at a tap and through a one-pole damping filter
    (DAMP): L0, L1, L2; a scattering junction writes h k + g L0, h k + c (L1 + L2) and
    h k - c L1 + c L2 back (g from DEC's gain table, c = g / sqrt 2);
  - the output 4 (h + a high-pass of L0 - L1 + L2), plus eight two-pole resonators on h
    whose frequencies follow the excitation's rate and whose radii and gains DEC sets.

What feeds back from block to block (the decay, the excitation position, the resonators'
coefficients and every index) is computed exactly as the 56300 does, in integers (`_mac`
and `_floor`: products in 12-bit halves a float holds exactly, then the 56300's floor);
the per-sample loops are float32 (signal-to-error over 80 dB on every golden case).

State (S words): 0 the decay (Q23), 1/2 the excitation position (offset, 24-bit
fraction), 3 the hammer filter, 4..6 the damping filters, 7/8 the high-pass, 9 the
lines' write position (0..511, a multiple of 32), 10 + 2i / 11 + 2i resonator i's y[n-1]
and y[n-2]. The delay area (core.delay_base): lines at words 0, 512, 1024; the block's
scratch from word 1536 (H, L0, L1, L2: 32 each; the resonators' coefficients, three
each, from 1664; MT's interpolated multipliers from 1688).
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .gnd import pitch_word
from ..perc.dsl import Prog

Q = K.Q23
TOP = K.TOP

# the delay area's words
LINE = 512
SCR_H = 1536                       # H, then L0, L1, L2 (32 each)
SCR_CO = 1664                      # c0, c1, c2 a resonator
SCR_MUL = 1688                     # MT: frequency, curve, gain multipliers (8 each)


# -- exact 56300 products ----------------------------------------------------------------
# P = A B for the Q23 words A, B (floats a 2^23 exact), as hh 2^24 + m 2^12 + n with the
# 12-bit halves' products (each exact in a float): sums of products in R8 (hh), R9 (m),
# R10 (n); `_floor` is floor(P / 2^s), the 56300's product through its limiter (s = 23:
# mpy, 22: mpy then asl).

def _clear(p: Prog) -> None:
    p.iconst(8, 0)
    p.iconst(9, 0)
    p.iconst(10, 0)


def _split(p: Prog, x: int, hi: int, lo: int) -> None:
    p.fconst(12, 2.0 ** 23)
    p.fop(hi, x, "*", 12)
    p.trunc(hi, hi)
    p.iconst(12, 4095)
    p.iop(lo, hi, "AND", 12)
    p.ash(hi, hi, -12)
    p.iconst(12, 0)
    p.float_(hi, hi, 12)
    p.float_(lo, lo, 12)


def _mac(p: Prog, a: int, b: int, neg: bool = False) -> None:
    """R8..R10 += the parts of (-)Fa Fb. Clobbers R0-R3, R12, R13 (a, b not among them,
    nor R8-R10)."""
    if neg:
        p.fconst(12, -1.0)
        p.fop(13, a, "*", 12)
        a = 13
    _split(p, a, 0, 1)
    _split(p, b, 2, 3)
    for x, y, acc in ((0, 2, 8), (0, 3, 9), (1, 2, 9), (1, 3, 10)):
        p.fop(13, x, "*", y)
        p.trunc(13, 13)
        p.iop(acc, acc, "+", 13)


def _floor(p: Prog, d: int, sh: int) -> None:
    """Rd = floor(P / 2^sh) (12 < sh <= 24). Clobbers R12, R13 (d not R12, R13)."""
    p.ash(13, 10, -12)
    p.iop(13, 9, "+", 13)
    p.ash(13, 13, -(sh - 12))
    p.lsh(d, 8, 24 - sh)
    p.iop(d, 13, "+", d)


def _q(p: Prog, d: int, r: int) -> None:
    """Fd = Rr through the limiter, as a Q23 float. Clobbers R12 (and Rr)."""
    p.iconst(12, (1 << 23) - 1)
    p.iop(r, r, "MIN", 12)
    p.iconst(12, -(1 << 23))
    p.iop(r, r, "MAX", 12)
    p.iconst(12, -23)
    p.float_(d, r, 12)


def _prod(p: Prog, d: int, a: int, b: int, add: int = 0, sh: int = 23, neg: bool = False) -> None:
    """Fd = the limited floor((-)Fa Fb / 2^sh 2^23) + add (an integer word). Clobbers R0-R3,
    R8-R13."""
    _clear(p)
    _mac(p, a, b, neg)
    _floor(p, 11, sh)
    if add:
        p.iconst(12, add)
        p.iop(11, 12, "+", 11)
    _q(p, d, 11)


def _clamp(p: Prog, x: int, top: int, bot: int) -> None:
    p.fop(x, x, "MIN", top)
    p.fop(x, x, "MAX", bot)


def _dbase(p: Prog, L: K.Layout, d: int, word: int) -> None:
    """Rd = the delay area's word WORD (an address), from C['c'] (the area's base)."""
    p.ld(d, L.C["c"])
    if word:
        p.iconst(12, 4 * word)
        p.iop(d, 12, "+", d)


# -- the two machines' differences --------------------------------------------------------
class _Cfg:
    def __init__(self, mt: bool):
        self.mt = mt
        self.env_k = 0x7EF9DB if mt else 0x7C28F6
        self.exc = "PIMT_EXC" if mt else "PIBD_EXC"
        self.zi = 1675 if mt else 1356          # the excitation's first word of its zero tail
        self.lim = 1676 if mt else 1480         # the position's clamp (an offset)
        self.gmul = 0x1FF if mt else 0x42       # DEC -> the gain table's index
        self.kj = 0x28F5C3 if mt else 0x051EB8  # the excitation into the junction
        self.taps = (0x1D2, 0x136, 0xE8) if mt else (0x10B, 0xFF, 0xB5)
        self.damp = 8 if mt else 6              # the damping word


BD, MT = _Cfg(False), _Cfg(True)


def _tbl_s(p: Prog, L: K.Layout, d: int, x: int) -> None:
    """Fd = tblS[Rx] (a Q23 word). Clobbers R12, R13, I1."""
    K.table_f(p, L, d, "hostS", x, 12)


def _host(p: Prog, L: K.Layout, cfg: _Cfg) -> None:
    inp(p, 0, 0)                               # PTCH: tblP[p & 127] << ((p >> 7) + 10) - 1000
    p.lsh(0, 0, -6)
    pitch_word(p, L, 4, 0, 10)
    p.fconst(12, -1000.0)
    p.fop(4, 4, "+", 12)
    K.mul_k(p, 4, 4, Q)
    ws(p, 1, 4)

    def shl9(k, word):                         # in << 9
        inp(p, 0, k)
        K.to_float(p, 4, 0, 9 - 23)
        ws(p, word, 4)
    shl9(1, 2)                                 # DEC
    inp(p, 0, 2)                               # HARD: (in << 7) + 0x80000
    K.to_float(p, 4, 0, 7 - 23)
    K.add_k(p, 4, 4, 0x80000 * Q)
    ws(p, 3, 4)
    inp(p, 0, 3)                               # HAMR: tblS[(in >> 9) + 223]
    p.lsh(0, 0, -9)
    p.iconst(12, 223)
    p.iop(0, 12, "+", 0)
    _tbl_s(p, L, 4, 0)
    ws(p, 4, 4)
    shl9(4, 5)                                 # TENS / TUNE
    if not cfg.mt:
        inp(p, 0, 5)                           # DAMP: tblS[in >> 6]
        p.lsh(0, 0, -6)
        _tbl_s(p, L, 4, 0)
        ws(p, 6, 4)
        return
    shl9(7, 6)                                 # POS (input 7)
    shl9(6, 7)                                 # SIZE (input 6)
    inp(p, 0, 6)                               # DAMP: tblS[min((SIZE >> 10) + (DAMP >> 9) + 223, 255)]
    p.lsh(0, 0, -10)
    inp(p, 1, 5)
    p.lsh(1, 1, -9)
    p.iconst(12, 223)
    p.iop(0, 12, "+", 0)
    p.ipass(12, 1)
    p.iop(0, 12, "+", 0)
    p.iconst(12, 255)
    p.iop(0, 0, "MIN", 12)
    _tbl_s(p, L, 4, 0)
    ws(p, 8, 4)


def _init(p: Prog, L: K.Layout, cfg: _Cfg) -> None:
    p.fconst(0, 0.0)
    for k in list(range(3, 9)) + list(range(10, 26)):
        ss(p, k, 0)
    p.iconst(0, 0)
    ss(p, 9, 0)
    if not cfg.mt:                             # P-IBD's init overwrites three host words
        p.fconst(0, 0x7FDF3B * Q)
        ws(p, 2, 0)
        p.fconst(0, 0.0)
        ws(p, 3, 0)
        p.fconst(0, 0x733333 * Q)
        ws(p, 6, 0)


def _trig(p: Prog, L: K.Layout, cfg: _Cfg) -> None:
    p.fconst(0, 0x7FFFAC * Q)
    ss(p, 0, 0)
    p.iconst(0, 0)
    ss(p, 1, 0)
    ss(p, 2, 0)


def _render(p: Prog, L: K.Layout, cfg: _Cfg) -> None:
    C = L.C
    K.delay_base(p, L, 0)
    p.st(C["c"], 0)
    # -- the block's words: the decay, the excitation's rate, the resonators' frequency
    s(p, 4, 0)                                 # the decay (its old value drives this block)
    p.fconst(5, cfg.env_k * Q)
    _prod(p, 6, 4, 5)
    ss(p, 0, 6)
    if cfg.mt:                                 # the depth: HARD x 0.4 - 0.05
        w(p, 5, 3)
        p.fconst(6, 0x333333 * Q)
        _prod(p, 5, 5, 6, add=-0x66666)
    else:
        w(p, 5, 5)                             # TENS
    _prod(p, 5, 5, 4, add=0x400000)            # M = depth x decay + 1/2
    w(p, 4, 1)                                 # PTCH
    _clear(p)
    _mac(p, 4, 5)
    _floor(p, 6, 20)                           # the increment: 48 bits, (offset, fraction)
    _floor(p, 7, 22)                           # F (the resonators' frequency scale)
    _q(p, 4, 7)
    p.st(C["e"], 4)
    p.lsh(7, 6, -24)
    p.st(C["a"], 7)
    p.iconst(12, 0xFFFFFF)
    p.iop(6, 6, "AND", 12)
    p.st(C["b"], 6)
    # -- the excitation and the hammer filter -> H
    p.fconst(2, TOP)
    p.fconst(3, -1.0)
    s(p, 6, 1)
    s(p, 7, 2)
    p.ld(8, C["a"])
    p.ld(9, C["b"])
    p.iconst(10, 0xFFFFFF)
    p.iconst(11, L.T[cfg.exc])
    s(p, 4, 3)
    w(p, 5, 4)                                 # HAMR
    _dbase(p, L, 0, SCR_H)
    p.seti(1, 0)

    def exc():
        p.iop(7, 9, "+", 7)                    # the fraction
        p.lsh(13, 7, -24)
        p.iop(7, 7, "AND", 10)
        p.iop(6, 8, "+", 6)                    # the offset, and the carry
        p.iop(6, 13, "+", 6)
        p.iconst(12, cfg.zi)                   # past the table's end it is all zeros
        p.iop(13, 6, "MIN", 12)
        p.lsh(13, 13, 2)
        p.iop(13, 11, "+", 13)
        p.seti(2, 13)
        p.ldpost(14, 2)
        p.ldi(15, 0, 2)
        p.iconst(12, -23)
        p.float_(13, 7, 12)                    # f
        p.fop(15, 15, "*", 13)
        p.iop(13, 10, "-", 7)                  # 1 - f (2^24 - 1 - f)
        p.float_(13, 13, 12)
        p.fop(14, 14, "*", 13)
        p.fop(14, 14, "+", 15)
        _clamp(p, 14, 2, 3)                    # e
        p.fop(13, 4, "MIN", 2)                 # h = the filter's (limited) value
        p.fop(13, 13, "MAX", 3)
        p.stpost(1, 13)
        p.fop(14, 14, "-", 13)
        p.fop(14, 5, "*", 14)
        p.fop(4, 4, "+", 14)
    p.loop(C["n1"], 32, exc)
    ss(p, 3, 4)
    p.iconst(12, cfg.lim)
    p.if_(6, "GE", 12, lambda: (p.iconst(6, cfg.lim), p.iconst(7, 0)), kind="i")
    ss(p, 1, 6)
    ss(p, 2, 7)
    # -- the junction's gains: g = GAIN[DEC x m], c = g / sqrt 2
    w(p, 4, 2)
    p.fconst(5, cfg.gmul * Q)
    _clear(p)
    _mac(p, 4, 5)
    _floor(p, 6, 23)
    K.table_f(p, L, 7, "PIBD_GAIN", 6, 12)
    p.st(C["f"], 7)
    p.fconst(5, 0x5A827A * Q)
    _prod(p, 4, 7, 5)
    p.st(C["g"], 4)
    # -- the three lines through their damping filters -> L0, L1, L2
    if cfg.mt:                                 # the taps scale with SIZE: 0.2 + 0.8 SIZE
        w(p, 4, 7)
        p.fconst(5, 0x666666 * Q)
        _prod(p, 4, 4, 5, add=0x19999A)
        p.st(C["h"], 4)
    for i in range(3):
        s(p, 6, 9)                             # the write position
        if cfg.mt:
            p.ld(4, C["h"])
            p.fconst(5, cfg.taps[i] * Q)
            _clear(p)
            _mac(p, 4, 5)
            _floor(p, 7, 23)
            p.iop(6, 6, "-", 7)
        else:
            p.iconst(12, cfg.taps[i])
            p.iop(6, 12, "+", 6)
        p.iconst(10, LINE - 1)
        p.iop(6, 6, "AND", 10)
        _dbase(p, L, 11, LINE * i)
        _dbase(p, L, 0, SCR_H + 32 * (i + 1))
        p.seti(1, 0)
        s(p, 4, 4 + i)
        w(p, 5, cfg.damp)
        p.fconst(2, TOP)
        p.fconst(3, -1.0)

        def damp():
            p.lsh(13, 6, 2)
            p.iop(13, 11, "+", 13)
            p.seti(2, 13)
            p.ldi(14, 0, 2)                    # the line's sample
            p.fop(13, 4, "MIN", 2)
            p.fop(13, 13, "MAX", 3)
            p.stpost(1, 13)
            p.fop(14, 14, "-", 13)
            p.fop(14, 5, "*", 14)
            p.fop(4, 4, "+", 14)
            p.iconst(12, 1)
            p.iop(6, 12, "+", 6)
            p.iop(6, 6, "AND", 10)
        p.loop(C["n1"], 32, damp)
        ss(p, 4 + i, 4)
    # -- the junction, back into the lines
    _dbase(p, L, 0, SCR_H)
    p.seti(1, 0)
    s(p, 6, 9)
    p.lsh(6, 6, 2)
    p.ld(12, C["c"])
    p.iop(6, 12, "+", 6)
    p.seti(0, 6)
    p.ld(5, C["f"])
    p.ld(6, C["g"])
    p.fconst(7, cfg.kj * Q)
    p.fconst(2, TOP)
    p.fconst(3, -1.0)

    def junction():
        p.ldi(9, 32, 1)                        # L0
        p.ldi(10, 64, 1)                       # L1
        p.ldi(11, 96, 1)                       # L2
        p.ldpost(8, 1)                         # h
        p.fop(8, 8, "*", 7)
        p.fop(13, 5, "*", 9)
        p.fop(13, 8, "+", 13)
        _clamp(p, 13, 2, 3)
        p.sti(2 * LINE, 0, 13)
        p.fop(14, 6, "*", 10)
        p.fop(15, 6, "*", 11)
        p.fop(13, 8, "+", 14)
        p.fop(13, 13, "+", 15)
        _clamp(p, 13, 2, 3)
        p.sti(LINE, 0, 13)
        p.fop(13, 8, "-", 14)
        p.fop(13, 13, "+", 15)
        _clamp(p, 13, 2, 3)
        p.stpost(0, 13)
    p.loop(C["n1"], 32, junction)
    s(p, 6, 9)
    p.iconst(12, 32)
    p.iop(6, 12, "+", 6)
    p.iconst(12, LINE - 1)
    p.iop(6, 6, "AND", 12)
    ss(p, 9, 6)
    # -- the output: 4 (h + a high-pass of L0 - L1 + L2)
    _dbase(p, L, 0, SCR_H)
    p.seti(1, 0)
    p.ld(0, C["mdb"])
    p.iconst(12, 4 * K.OUT0)
    p.iop(0, 12, "+", 0)
    p.seti(5, 0)
    s(p, 4, 7)
    s(p, 5, 8)
    p.fconst(6, 0x59999A * Q)
    p.fconst(7, 0.5)
    p.fconst(2, TOP)
    p.fconst(3, -1.0)

    def hp():
        p.ldi(9, 32, 1)
        p.ldi(10, 64, 1)
        p.ldi(13, 96, 1)
        p.fop(13, 13, "-", 10)
        p.fop(13, 13, "+", 9)                  # s
        p.ldpost(8, 1)
        p.fop(14, 4, "MIN", 2)
        p.fop(14, 14, "MAX", 3)                # the filter's limited value
        p.fop(15, 14, "*", 6)
        p.fop(4, 7, "*", 5)
        p.fop(4, 15, "-", 4)
        p.fop(8, 8, "+", 14)
        p.fconst(12, 4.0)
        p.fop(8, 8, "*", 12)
        _clamp(p, 8, 2, 3)
        p.stpost(5, 8)
        p.fop(5, 13, "MIN", 2)
        p.fop(5, 5, "MAX", 3)
        p.fop(15, 7, "*", 5)
        p.fop(4, 4, "+", 15)
    p.loop(C["n1"], 32, hp)
    ss(p, 7, 4)
    ss(p, 8, 5)
    # -- MT: the multipliers, interpolated by TUNE (frequency) and POS (curve, gain)
    if cfg.mt:
        p.iconst(0, 0)
        p.st(C["k"], 0)

        def mul():
            for arr, (off, word) in enumerate(((0, 5), (16, 6), (32, 6))):
                p.ld(0, C["k"])
                p.lsh(0, 0, 2)
                p.iconst(12, L.T["PIMT_COEF"] + 4 * off)
                p.iop(0, 12, "+", 0)
                p.seti(2, 0)
                p.ldi(14, 0, 2)
                p.ldi(15, 8, 2)
                w(p, 7, word)                  # p
                p.fconst(12, TOP)
                p.fop(6, 12, "-", 7)           # q = 1 - p (exact)
                _clear(p)
                _mac(p, 6, 14)
                _mac(p, 7, 15)
                _floor(p, 11, 23)
                _q(p, 4, 11)
                p.ld(0, C["k"])
                p.lsh(0, 0, 2)
                p.ld(12, C["c"])
                p.iop(0, 12, "+", 0)
                p.seti(2, 0)
                p.sti(SCR_MUL + 8 * arr, 2, 4)
            p.ld(0, C["k"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(C["k"], 0)
        p.loop(C["n2"], 8, mul)
        _dbase(p, L, 0, SCR_MUL)
    else:
        p.iconst(0, L.T["PIBD_COEF"])
    p.st(C["d"], 0)
    # -- the resonators' coefficients: c0 = -r^2, c1 = 2 r C - 1, c2 = 2 G (2 r C - 1 - r^2)
    #    with C ~ cos(w sqrt 2) (1 - w^2 + w^4 / 6) and r = CURVE[DEC x m]
    p.iconst(0, 0)
    p.st(C["k"], 0)

    def coef():
        p.ld(0, C["k"])
        p.lsh(0, 0, 2)
        p.ld(13, C["d"])
        p.iop(13, 13, "+", 0)
        p.seti(2, 13)
        p.ldi(4, 0, 2)                         # the frequency multiplier
        p.ldi(5, 8, 2)                         # the curve's
        p.ldi(6, 16, 2)                        # the gain
        p.ld(7, C["e"])
        _prod(p, 4, 4, 7)                      # w
        _prod(p, 14, 4, 4, neg=True)           # -w^2
        p.fconst(15, 0x155555 * Q)
        _prod(p, 15, 14, 15)                   # -w^2 / 6
        _clear(p)
        _mac(p, 4, 4, neg=True)
        _mac(p, 15, 14)
        _floor(p, 11, 23)
        p.iconst(12, 0x7FFFFF)
        p.iop(11, 12, "+", 11)
        _q(p, 4, 11)                           # C
        w(p, 7, 2)
        _clear(p)
        _mac(p, 5, 7)
        _floor(p, 11, 23)
        K.table_f(p, L, 5, "PIBD_CURVE", 11, 12)    # r
        _prod(p, 7, 5, 4, sh=22, add=-0x800000)     # c1
        _prod(p, 14, 5, 5, neg=True)                # c0
        _clear(p)
        _mac(p, 5, 4)
        _mac(p, 5, 4)
        _mac(p, 5, 5, neg=True)
        _floor(p, 11, 23)
        p.iconst(12, -0x800000)
        p.iop(11, 12, "+", 11)
        _q(p, 15, 11)
        _prod(p, 15, 6, 15, sh=22)                  # c2
        p.ld(0, C["k"])
        p.lsh(1, 0, 3)
        p.lsh(0, 0, 2)
        p.ipass(12, 1)
        p.iop(0, 12, "+", 0)                        # 12 k (bytes of three words)
        p.ld(12, C["c"])
        p.iop(0, 12, "+", 0)
        p.seti(2, 0)
        p.sti(SCR_CO, 2, 14)
        p.sti(SCR_CO + 1, 2, 7)
        p.sti(SCR_CO + 2, 2, 15)
        p.ld(0, C["k"])
        p.iconst(12, 1)
        p.iop(0, 12, "+", 0)
        p.st(C["k"], 0)
    p.loop(C["n2"], 8, coef)
    # -- the resonators, added into the output
    p.iconst(0, 0)
    p.st(C["k"], 0)

    def res():
        p.ld(0, C["k"])
        p.lsh(1, 0, 3)                         # 8 k: two state words
        p.ld(12, C["mdb"])
        p.iop(1, 12, "+", 1)
        p.iconst(12, 4 * (K.S0 + 10))
        p.iop(1, 12, "+", 1)
        p.seti(0, 1)
        p.lsh(1, 0, 3)
        p.lsh(0, 0, 2)
        p.ipass(12, 1)
        p.iop(0, 12, "+", 0)
        p.ld(12, C["c"])
        p.iop(0, 12, "+", 0)
        p.iconst(12, 4 * SCR_CO)
        p.iop(0, 12, "+", 0)
        p.seti(5, 0)
        p.ldi(6, 0, 5)
        p.ldi(7, 1, 5)
        p.ldi(8, 2, 5)
        p.ldi(4, 0, 0)                         # y[n-1]
        p.ldi(5, 1, 0)                         # y[n-2] (limited)
        _dbase(p, L, 1, SCR_H)
        p.seti(1, 1)
        p.ld(1, C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(1, 12, "+", 1)
        p.seti(2, 1)
        p.fconst(9, TOP)
        p.fconst(10, -1.0)

        def one():
            p.ldpost(11, 1)                    # h
            p.fop(13, 4, "MIN", 9)
            p.fop(13, 13, "MAX", 10)
            p.fop(14, 5, "*", 6)
            p.fop(4, 4, "+", 14)
            p.fop(14, 13, "*", 7)
            p.fop(4, 4, "+", 14)
            p.fop(14, 8, "*", 11)
            p.fop(4, 4, "+", 14)
            p.fpass(5, 13)
            p.ldi(14, 0, 2)
            p.fop(14, 14, "+", 4)
            p.fop(14, 14, "MIN", 9)
            p.fop(14, 14, "MAX", 10)
            p.stpost(2, 14)
        p.loop(C["n1"], 32, one)
        _clamp(p, 4, 9, 10)                    # stored through the limiter
        p.sti(0, 0, 4)
        p.sti(1, 0, 5)
        p.ld(0, C["k"])
        p.iconst(12, 1)
        p.iop(0, 12, "+", 0)
        p.st(C["k"], 0)
    p.loop(C["n2"], 8, res)


class PIBD:
    """P-I BD: a struck membrane (three delay lines and eight resonators). W1 PTCH, W2
    DEC, W3 HARD (unused by DSP2's render), W4 HAMR, W5 TENS, W6 DAMP (init sets W2, W3,
    W6: the first hit after the machine is chosen has DSP2's constants)."""
    NAME, ID = "PI-BD", 64
    PNAMES = ("PTCH", "DEC", "HARD", "HAMR", "TENS", "DAMP", "-", "-")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        _host(p, L, BD)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        _init(p, L, BD)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        _trig(p, L, BD)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        _render(p, L, BD)


MACHINES = (PIBD,)

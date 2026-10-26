"""VO-6 (docs/mnm.md): the Monomachine's vowel/consonant voice, at the Monomachine's own rate
(16 samples a block, no decimator).

Per block: a band-limited pulse train (32-tap pulses from the kernel's table, at w Hz, w the
increment's word: the period 44100 / w samples, kept as whole samples and 24 fraction bits)
plus a noise word stream (VOIC mixes them) excites four resonators in series (the formants:
F1, F2 from VOC1, VOC2; F3 = max(0x6277C6, F2 + 0x1A52F); F4 0x679171; bandwidths 50, 75, 100,
150 Hz); the same four in parallel filter the unvoiced source (noise / 8, or a consonant's
biquad on it); an AGC (1 / RMS of the voiced output, from the Monomachine's log and exp tables)
and three per-block envelopes (the onset y35, the consonant's transition y31, the vowel gate
y39) set the mix, and a fixed biquad shapes the output. CONS picks one of 21 consonant
set-ups (a table row at the trig) and renderers (formant offsets, the source's biquad).

Numbers. The per-block decisions are the Monomachine's exactly: the envelopes, counters,
offsets and the pulse phase (24.24) are its 24-bit words (ints here), their products exact
(`mul`: 12-bit halves, each partial product exact in float, summed as ints). Where a float's
one-LSB slip would grow -- the series resonators (a high-Q formant rings it up ~35 LSB, and
the voiced path is amplified 4096 times), the formant ramps, the consonant biquad on the
excitation and its crossfade, the pulse taps -- the arithmetic is the 56300's exactly, the
same way. Elsewhere it is float, each limited store floored as the 56300's (`_floor`).
test/test_mnm.py holds it to the Monomachine's output (its code in an emulator).

y:(r6+175), the Monomachine kernel's AMP envelope level, gates the voiced path. The DN2 has no
such envelope here: the level is that of an AMP attack of 0 (S_LEV): 0 at the trig, then after
each block min(level + 0x400000, 0x7FFFFF).

State (S): the envelopes' words (x31..x40, y31..y40), the consonant (x54) and the trill
(y54, x55, y55), the pulse phase, the ring position, the noise words, the frozen formants and
pitch (x49.., y51: the pre-delay's), the resonators', biquads' and ramps' states (floats), the
level follower, the AMP level. The pulse ring (64 floats): the slot's delay area
(dnfw.md.core.delay_base). Parameters: VOC1 VOC2 V-SW VOIC CONS CLEN CVOL TUNE.
"""

from __future__ import annotations

import math

from . import core as C
from ..md import core as K
from ..perc.dsl import Prog

NAME, ID = "VO-6", 11
PNAMES = ("VOC1", "VOC2", "V-SW", "VOIC", "CONS", "CLEN", "CVOL", "TUNE")
DEFAULTS = (64, 64, 96, 0, 0, 64, 64, 64)
M24 = 0xFFFFFF
Q23 = C.Q23

_S = ("x31", "y31", "x32", "y32", "x33", "y33", "x34", "x35", "y35", "x36", "y36", "x37", "y37",
      "x39", "y39", "x40", "y40", "k", "y54", "x55", "y55",
      "pi", "pf", "rp", "nb", "nx", "z0", "z1", "z2", "z3", "zw", "zp", "zq", "lev",
      # floats
      "pb", "pa", "g", "t31", "cb", "ob")
S = {n: k for k, n in enumerate(_S)}
S["cb"] = len(_S) - 2                        # the consonant biquad: x1, x2, y1, y2
S["ob"] = S["cb"] + 4                        # the output biquad
S["ser"] = S["ob"] + 4                       # the series resonators: y1, y2 each
S["par"] = S["ser"] + 8
S["tx"] = S["par"] + 8                       # the series targets: c1, c2 each
S["ty"] = S["tx"] + 8
NSTATE = S["ty"] + 8
assert NSTATE <= K.NS

FORM = ((0x8074B7, 0x7F1766), (0x80AF13, 0x7EA3B7), (0x80E96E, 0x7E3072), (0x815E23, 0x7D4B22))
OUT_EQ = (0x3FFFD6, 0x941206, 0x2E6F69, 0x8B8D50, 0x372839)
LEV_STEP, LEV_TOP = 0x400000, 0x7FFFFF

# scratch in the shared IN buffer (floats unless said)
EXC, UNV, C30, RAMP, CO, WRD = 0, 16, 32, 48, 80, 96
_WORDS = ("F0", "F1", "F2", "F3", "O0", "O1", "O2", "O3", "O4", "O5", "O6", "O7", "w", "P", "Q",
          "p", "rb", "x1", "y0", "q0", "f", "n1", "n2", "n3", "vn", "vp", "st", "sto", "R", "g",
          "x37", "c1", "step1", "step2", "src", "dst", "kk", "x1t", "stt", "skip", "go",
          "m0", "m1", "m2", "m3", "r0", "r1", "r2", "r3", "n4", "R0i", "R1i", "R2i", "R3i",
          "dt", "step", "row", "opp", "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "xk",
          "kind")


def _a(L: C.Layout, name: str) -> int:
    if name in _WORDS:
        return L.IN + 4 * (WRD + _WORDS.index(name))
    return L.IN + 4 * {"EXC": EXC, "UNV": UNV, "C30": C30, "RAMP": RAMP, "CO": CO}[name]


def s24(v: int) -> int:
    v &= M24
    return v - (1 << 24) if v & 0x800000 else v


# -- small emitters ------------------------------------------------------------------------
def ls(p: Prog, d: int, name: str, off: int = 0) -> None:
    K.s(p, d, S[name] + off)


def ss(p: Prog, name: str, r: int, off: int = 0) -> None:
    K.ss(p, S[name] + off, r)


def setk(p: Prog, name: str, v: int, t: int = 0) -> None:
    p.iconst(t, v)
    ss(p, name, t)


def add(p: Prog, d: int, a: int, b: int) -> None:
    if 8 <= a <= 15:
        p.iop(d, a, "+", b)
    else:
        assert b != 12
        p.ipass(12, a)
        p.iop(d, 12, "+", b)


def addk(p: Prog, d: int, a: int, k: int) -> None:
    assert a != 12
    p.iconst(12, k)
    p.iop(d, 12, "+", a)


def limi(p: Prog, r: int) -> None:
    """Rr = the 24-bit limiter (ints)"""
    p.iconst(12, 0x7FFFFF)
    p.iop(r, r, "MIN", 12)
    p.iconst(12, -0x800000)
    p.iop(r, r, "MAX", 12)


def i2f(p: Prog, d: int, r: int) -> None:
    """Fd = the Q23 word Rr as a fraction. Clobbers R12."""
    p.iconst(12, -23)
    p.float_(d, r, 12)


def _mulq_body(p: Prog) -> None:
    """R1 = floor(R1 x R2 / 2^23) exactly (the 56300's MPY then a1), R2 >= 0, R1 >= 0 (or R2 = 0);
    R3 = the product's low 23 bits (0: exact). Clobbers R4-R7, R12, R13."""
    p.lsh(3, 1, -12)
    p.iconst(12, 0xFFF)
    p.iop(4, 1, "AND", 12)
    p.lsh(5, 2, -12)
    p.iop(6, 2, "AND", 12)
    p.iconst(12, 0)
    for r in (3, 4, 5, 6):
        p.float_(r, r, 12)
    p.fop(7, 3, "*", 5)
    p.trunc(7, 7)                              # hh
    p.fop(13, 3, "*", 6)
    p.trunc(13, 13)
    p.fop(3, 4, "*", 5)
    p.trunc(3, 3)
    p.iop(13, 13, "+", 3)                      # m
    p.fop(4, 4, "*", 6)
    p.trunc(4, 4)                              # l
    p.lsh(3, 13, 12)
    p.ipass(12, 3)
    p.iop(3, 12, "+", 4)
    p.iconst(12, 0x7FFFFF)
    p.iop(3, 3, "AND", 12)                     # the low 23 bits
    p.lsh(4, 4, -12)
    p.iop(13, 13, "+", 4)
    p.lsh(13, 13, -11)
    p.lsh(7, 7, 1)
    p.iop(1, 13, "+", 7)


def _mul_body(p: Prog) -> None:
    """R1 = floor(R1 R2 / 2^23) (the 56300's MPY, a1), any signs; R3 = |R1 R2|'s low 23 bits.
    Clobbers R2, R4-R8, R12, R13."""
    p.iconst(8, 0)
    p.ifz(2, "LT", lambda: (p.iconst(12, 0), p.iop(2, 12, "-", 2), p.iop(1, 12, "-", 1)))
    p.ifz(1, "LT", lambda: (p.iconst(12, 0), p.iop(1, 12, "-", 1), p.iconst(8, 1)))
    _mulq_body(p)

    def neg():
        p.iconst(12, 0)
        p.iop(1, 12, "-", 1)
        p.ifz(3, "NE", lambda: (p.iconst(12, 1), p.iop(1, 1, "-", 12)))
    p.ifz(8, "NE", neg)


def mul(p: Prog) -> None:
    p.call("vo6_mul", lambda: _mul_body(p))


mulq = mulqs = mul


def mulc(p: Prog, r: int, c: int, neg: bool = False) -> None:
    """R1 = floor(+-Rr x c / 2^23), c a 24-bit constant (signed). Clobbers R2-R8, R12, R13."""
    if r != 1:
        p.ipass(1, r)
    p.iconst(2, -c if neg else c)
    mul(p)


# -- init, trig ------------------------------------------------------------------------------
def _f2(p: Prog, d: int) -> None:
    """Rd = F2 = 0x49F427 + MPY(0x19AA73, VOC2 << 16). Clobbers R1-R8, R12, R13."""
    C.knob(p, 1, 1)
    p.lsh(1, 1, 16)
    p.iconst(2, 0x19AA73)
    mulq(p)
    addk(p, d, 1, 0x49F427)


def init(p: Prog, L: C.Layout) -> None:
    from . import exact as X
    p.ld(1, L.md.C["mdb"])
    addk(p, 1, 1, 4 * K.S0)
    p.seti(5, 1)
    p.iconst(6, 0)
    p.loop(_a(L, "n1"), NSTATE, lambda: p.stpost(5, 6))
    setk(p, "rp", 48)
    setk(p, "nb", 0xA)
    setk(p, "nx", 1)
    setk(p, "y35", s24(0xC8192D))              # the kernel's y0 at the 56300's call
    setk(p, "z0", 0x6277C6)                    # (the Monomachine's init loses F1: F3's word)
    _f2(p, 0)
    ss(p, "z1", 0)
    setk(p, "z2", 0x6277C6)
    setk(p, "z3", 0x679171)
    setk(p, "zw", 0x64)
    per = X.vo6_period(0x64)
    setk(p, "zp", per >> 24)
    setk(p, "zq", per & M24)
    # the ring, in the slot's delay area
    K.delay_base(p, L.md, 0)
    p.seti(5, 0)
    p.iconst(6, 0)
    p.loop(_a(L, "n1"), 64, lambda: p.stpost(5, 6))


def _tab(p: Prog, L: C.Layout, d: int, name: str, idx: int) -> None:
    """Rd = table NAME's word at Ridx (an int; the tables hold them as Q23 floats). Clobbers
    R12, R13, I1."""
    p.lsh(13, idx, 2)
    p.iconst(12, L.VO[name])
    p.iop(13, 12, "+", 13)
    p.seti(1, 13)
    p.ldi(d, 0, 1)
    p.fconst(12, 2.0 ** 23)
    p.fop(d, d, "*", 12)
    p.trunc(d, d)


def trig(p: Prog, L: C.Layout) -> None:
    # the level follower's power doubles (asl, limited)
    ls(p, 1, "pb")
    p.fop(1, 1, "+", 1)
    p.fconst(12, C.TOP)
    p.fop(1, 1, "MIN", 12)
    ss(p, "pb", 1)
    for name, v in (("x31", 1), ("y31", 0), ("x35", 2), ("y37", 0), ("x39", 3), ("y39", 0x7FFFF8),
                    ("y40", 1), ("y54", 1), ("x55", 0), ("y55", 0xF), ("y32", 0), ("lev", 0)):
        setk(p, name, v)
    # the consonant: k = CONS x 21 / 128; its row
    C.knob(p, 1, 4)
    p.ipass(12, 1)
    p.lsh(2, 1, 2)
    p.iop(2, 12, "+", 2)                       # 5 CONS
    p.lsh(3, 1, 4)
    p.ipass(12, 3)
    p.iop(2, 12, "+", 2)                       # 21 CONS
    p.lsh(2, 2, -7)
    ss(p, "k", 2)
    # x1 = the CLEN term
    C.knob(p, 3, 5)
    _tab(p, L, 9, "clen", 3)
    p.st(_a(L, "x1t"), 9)
    # the row: field f at trig + 4 (21 f + k) (field-major), read in order
    p.lsh(3, 2, 2)
    p.iconst(12, L.VO["trig"])
    p.iop(3, 12, "+", 3)
    p.seti(1, 3)
    field = [0]

    def nxt(d):
        p.ldi(d, 21 * field[0], 1)
        field[0] += 1
        _word(p, d, d)

    def plus_x1(name):                         # c, then (+ x1?)
        nxt(9)
        nxt(10)
        p.ifz(10, "NE", lambda: (p.ld(11, _a(L, "x1t")), p.iop(9, 9, "+", 11)))
        ss(p, name, 9)
    nxt(9)
    ss(p, "x32", 9)
    nxt(10)
    p.ifz(10, "NE", lambda: (p.ld(9, _a(L, "x1t")), ss(p, "y32", 9)))
    for name in ("x33", "y33", "x34", "x35"):
        nxt(9)
        ss(p, name, 9)
    plus_x1("x36")
    nxt(9)
    ss(p, "y36", 9)
    nxt(10)                                    # x37: c, or c0 + MPY(kk, CVOL << 16)
    nxt(9)
    nxt(2)

    def cvol():
        p.st(_a(L, "kk"), 9)
        C.knob(p, 1, 6)
        p.lsh(1, 1, 16)
        mul(p)
        p.ld(9, _a(L, "kk"))
        p.iop(9, 9, "+", 1)
    p.ifz(10, "NE", cvol)
    ss(p, "x37", 9)
    plus_x1("x40")
    nxt(9)                                     # V-SW below 64: the vowel ends (x39 = 1)
    nxt(11)                                    # B: then y39 = 0x770A3D

    def vsw():
        C.knob(p, 10, 2)
        p.iconst(12, 64)

        def off():
            setk(p, "x39", 1)
            p.ifz(11, "NE", lambda: setk(p, "y39", 0x770A3D))
        p.if_(10, "LT", 12, off, kind="i")
    p.ifz(9, "NE", vsw)


# -- the pitch ----------------------------------------------------------------------------
def exact(A: int, F: int, knobs, pre: int = 0) -> dict:
    from . import exact as X
    return X.vo6_incs(A)


def pitch(p: Prog, L: C.Layout) -> None:
    """VW i3 = w = the increment's word (Hz); i1, i2 = the period 44100 / w, whole samples and
    24 fraction bits. Clobbers R0-R4, R12-R15, I12."""
    from ..perc import machines as PM
    C.vw(p, 1, "A")
    p.trunc(1, 1)
    p.iconst(12, 1)
    p.iop(1, 1, "MAX", 12)
    C.vws(p, "i3", 1)
    p.iconst(12, 0)
    p.float_(2, 1, 12)
    PM.recip(p, 2, 2)
    p.fconst(12, 44100.0)
    p.fop(2, 2, "*", 12)
    p.trunc(3, 2)
    C.vws(p, "i1", 3)
    p.iconst(12, 0)
    p.float_(4, 3, 12)
    p.fop(2, 2, "-", 4)
    p.fconst(12, 2.0 ** 24)
    p.fop(2, 2, "*", 12)
    p.trunc(2, 2)
    p.iconst(12, M24)
    p.iop(2, 2, "AND", 12)
    C.vws(p, "i2", 2)


# -- the block -----------------------------------------------------------------------------
def _formants(p: Prog, L: C.Layout) -> None:
    """F0..F3 (ints) and w, P, Q: the knobs', or the frozen ones (x35 <= 1)"""
    C.knob(p, 1, 0)
    p.lsh(1, 1, 16)
    p.iconst(2, 0x1300A8)
    mulq(p)
    addk(p, 9, 1, 0x3C0D29)
    p.st(_a(L, "F0"), 9)
    _f2(p, 9)
    p.st(_a(L, "F1"), 9)
    p.iconst(10, 0x6277C6)
    p.ipass(12, 10)
    p.iop(11, 12, "-", 9)
    p.iconst(12, 0x1A52F)
    p.if_(11, "LT", 12, lambda: addk(p, 10, 9, 0x1A52F), kind="i")
    p.st(_a(L, "F2"), 10)
    p.iconst(9, 0x679171)
    p.st(_a(L, "F3"), 9)
    for k, v in enumerate(("i3", "i1", "i2")):
        C.vw(p, 9, v)
        p.st(_a(L, ("w", "P", "Q")[k]), 9)
    ls(p, 1, "x35")
    p.iconst(12, 1)
    pairs = (("F0", "z0"), ("F1", "z1"), ("F2", "z2"), ("F3", "z3"), ("w", "zw"), ("P", "zp"),
             ("Q", "zq"))

    def frozen():
        for w, z in pairs:
            ls(p, 9, z)
            p.st(_a(L, w), 9)

    def keep():
        for w, z in pairs:
            p.ld(9, _a(L, w))
            ss(p, z, 9)
    p.if_(1, "LE", 12, frozen, keep, kind="i")


def _ring_addr(p: Prog, L: C.Layout, d: int, r: int) -> None:
    """Rd = the ring word (Rr & 63)'s address. Clobbers R12."""
    p.iconst(12, 63)
    p.iop(d, r, "AND", 12)
    p.lsh(d, d, 2)
    p.ld(12, _a(L, "rb"))
    p.iop(d, 12, "+", d)


def _pulses(p: Prog, L: C.Layout) -> None:
    """The ring moves on 16, the 16 behind it cleared; every pulse due in this block (phase
    <= 16 samples) adds the 32-tap shape at its position and fraction."""
    K.delay_base(p, L.md, 0)
    p.st(_a(L, "rb"), 0)
    ls(p, 1, "rp")
    addk(p, 1, 1, 16)
    p.iconst(12, 63)
    p.iop(1, 1, "AND", 12)
    ss(p, "rp", 1)
    p.st(_a(L, "p"), 1)
    addk(p, 2, 1, 48)
    _ring_addr(p, L, 3, 2)
    p.seti(5, 3)
    p.iconst(6, 0)
    p.loop(_a(L, "n1"), 16, lambda: p.stpost(5, 6))

    def one():
        ls(p, 1, "pi")
        ls(p, 2, "pf")
        p.iconst(12, 16)

        def due():
            p.ld(3, _a(L, "p"))
            add(p, 3, 3, 1)
            addk(p, 3, 3, -1)
            p.st(_a(L, "q0"), 3)
            p.lsh(4, 2, -19)
            p.st(_a(L, "f"), 4)                # the shape's phase, 0..31
            p.iconst(12, 0x7FFFF)
            p.iop(1, 2, "AND", 12)
            p.lsh(1, 1, 5)                     # y0 of MPYSU (0x10, b0): the weight << 5
            p.iconst(2, 0xCCCCD)
            mulq(p)                            # floor(0xCCCCD w / 2^23), R3 its low 23 bits
            p.iconst(12, 1)
            p.iop(4, 1, "AND", 12)
            p.lsh(4, 4, 23)
            p.iop(3, 3, "OR", 4)               # the low 24 bits of 0xCCCCD w
            p.lsh(1, 1, -1)
            p.st(_a(L, "x1"), 1)               # x1 = floor(0xCCCCD w / 2^24)
            p.iconst(2, 0xCCCCD)
            p.iop(2, 2, "-", 1)
            p.ifz(3, "NE", lambda: (p.iconst(12, 1), p.iop(2, 2, "-", 12)))
            p.st(_a(L, "y0"), 2)               # y0 = floor(0xCCCCD - 0xCCCCD w / 2^24)
            _blit(p, L)
            # the phase moves on a period
            ls(p, 1, "pi")
            ls(p, 2, "pf")
            p.ld(3, _a(L, "Q"))
            add(p, 2, 2, 3)
            p.iconst(12, 1 << 24)

            def carry():
                p.iop(2, 2, "-", 12)
                addk(p, 1, 1, 1)
            p.if_(2, "GE", 12, carry, kind="i")
            p.ld(3, _a(L, "P"))
            add(p, 1, 1, 3)
            ss(p, "pi", 1)
            ss(p, "pf", 2)

        def at16():
            p.ifz(2, "EQ", due)
        p.if_(1, "LT", 12, due, lambda: p.if_(1, "EQ", 12, at16, kind="i"), kind="i")
    p.loop(_a(L, "n2"), 7, one)
    ls(p, 1, "pi")
    addk(p, 1, 1, -16)
    ss(p, "pi", 1)




def _tap_body(p: Prog, L: C.Layout) -> None:
    """ring[R3] = lim(ring[R3] + floor((x1 T[R4] + y0 T[R4 + dt]) / 2^23)), exactly; then R3 + 1,
    R4 + step (the words dt, step: bytes). Clobbers R1, R2, R5-R15, I0-I2."""
    p.ld(9, _a(L, "x1"))
    _split(p, 9, 1, 2)
    p.ld(9, _a(L, "y0"))
    _split(p, 9, 5, 6)
    p.iconst(14, 0)
    p.iconst(15, 0)
    p.iconst(13, 0)
    p.seti(1, 4)
    p.ld(9, _a(L, "dt"))
    p.iop(9, 9, "+", 4)
    p.seti(0, 9)
    for i, fv in ((1, 1), (0, 5)):
        p.ldi(7, 0, i)
        _word(p, 9, 7)
        _split(p, 9, 7, 8)
        _prod(p, fv, fv + 1, 7, 8, False)
    _sum(p, 23)                                # floor((x1 T + y0 T') / 2^23)
    _ring_addr(p, L, 7, 3)
    p.seti(2, 7)
    p.ldi(10, 0, 2)
    _word(p, 10, 10)
    p.iop(14, 14, "+", 10)
    limi(p, 14)
    i2f(p, 10, 14)
    p.sti(0, 2, 10)
    addk(p, 3, 3, 1)
    p.ld(9, _a(L, "step"))
    p.ipass(12, 9)
    p.iop(4, 12, "+", 4)


def _blit(p: Prog, L: C.Layout) -> None:
    """ring[q0 + 17 + k] += x1 T[0x312 + f - 32k] + y0 T[0x311 + f - 32k], then
    ring[q0 + 1 + k] += x1 T[0x152 - f + 32k] + y0 T[0x153 - f + 32k] (k = 0..15): the
    kernel's P:0x3AA, its two arms (T: y:$131..$333, VO 'blit'), exactly"""
    base = L.VO["blit"] - 4 * 0x131
    for arm in (0, 1):
        p.ld(3, _a(L, "q0"))
        addk(p, 3, 3, 17 if arm == 0 else 1)
        p.ld(4, _a(L, "f"))
        if arm == 0:
            addk(p, 4, 4, 0x312)
        else:
            p.iconst(12, 0x152)
            p.iop(4, 12, "-", 4)
        p.lsh(4, 4, 2)
        addk(p, 4, 4, base)
        p.iconst(9, -4 if arm == 0 else 4)
        p.st(_a(L, "dt"), 9)
        p.iconst(9, -128 if arm == 0 else 128)
        p.st(_a(L, "step"), 9)
        p.loop(_a(L, "n3"), 16, lambda: p.call("vo6_tap", lambda: _tap_body(p, L)))


# -- the envelopes ----------------------------------------------------------------------------
def _envelopes(p: Prog, L: C.Layout) -> None:
    """x35/y35 the onset, x31/y31 the transition, x39/y39 the vowel gate (146A79..146B2C)"""
    STT, SKIP, GO = _a(L, "stt"), _a(L, "skip"), _a(L, "go")

    def stt(v):
        p.iconst(9, v)
        p.st(STT, 9)

    def when(v, body):
        p.ld(9, STT)
        p.iconst(12, v)
        p.if_(9, "EQ", 12, body, kind="i")

    p.iconst(9, 0)
    p.st(SKIP, 9)
    stt(0)
    ls(p, 9, "x35")
    p.iconst(12, 2)

    def pre():                                 # 1: the pre-delay
        ls(p, 1, "y35")
        ls(p, 2, "lev")
        mulqs(p)
        p.iconst(12, 0x147AE)

        def big():
            addk(p, 1, 1, -0xEDC6)
            ss(p, "y35", 1)
            p.iconst(9, 1)
            p.st(SKIP, 9)

        def small():
            setk(p, "y35", 0)
            ls(p, 2, "y37")

            def count():
                addk(p, 2, 2, -1)
                ss(p, "y37", 2)
                p.iconst(9, 1)
                p.st(SKIP, 9)
            p.ifz(2, "GT", count, lambda: (setk(p, "x35", 2), stt(2)))
        p.if_(1, "GT", 12, big, small, kind="i")

    p.if_(9, "LT", 12, pre, lambda: p.if_(9, "EQ", 12, lambda: stt(2), lambda: stt(3), kind="i"),
          kind="i")

    def rest():
        def hold():
            ls(p, 2, "x36")

            def count():
                addk(p, 2, 2, -1)
                ss(p, "x36", 2)
                stt(0)
            p.ifz(2, "GT", count, lambda: (setk(p, "x35", 3), stt(3)))
        when(2, hold)

        def rise():
            ls(p, 1, "y35")
            p.iconst(12, 0x7EB852)

            def top():
                setk(p, "y35", 0x7FFFAC)
                setk(p, "x35", 4)

            def up():
                ls(p, 2, "y36")
                add(p, 1, 1, 2)
                limi(p, 1)
                ss(p, "y35", 1)
            p.if_(1, "GT", 12, top, up, kind="i")
        when(3, rise)
        # x31: 1 rise by x32, 2 hold y32, 3 fall by y33 for x33 blocks, 4 fall by x34, 5
        ls(p, 9, "x31")
        p.iconst(12, 2)
        p.if_(9, "LT", 12, lambda: stt(1), lambda: (
            p.iconst(12, 2), p.if_(9, "EQ", 12, lambda: stt(2), lambda: (
                p.iconst(12, 3), p.if_(9, "EQ", 12, lambda: stt(3), lambda: stt(4), kind="i")),
                kind="i")), kind="i")

        def s1():
            ls(p, 1, "y31")
            p.iconst(12, 0x7EB852)

            def up():
                ls(p, 2, "x32")
                add(p, 1, 1, 2)
                limi(p, 1)
                ss(p, "y31", 1)
                stt(0)
            p.if_(1, "GT", 12, lambda: (setk(p, "x31", 2), stt(2)), up, kind="i")

        def s2():
            ls(p, 2, "y32")
            p.ifz(2, "GT", lambda: (addk(p, 2, 2, -1), ss(p, "y32", 2), stt(0)),
                  lambda: (setk(p, "x31", 3), stt(3)))

        def s3():
            ls(p, 2, "x33")

            def fall():
                addk(p, 2, 2, -1)
                ss(p, "x33", 2)
                ls(p, 1, "y31")
                ls(p, 3, "y33")
                p.iop(1, 1, "-", 3)
                limi(p, 1)
                ss(p, "y31", 1)
                stt(0)
            p.ifz(2, "GT", fall, lambda: (setk(p, "x31", 4), stt(4)))

        def s4():
            ls(p, 1, "y31")
            p.iconst(12, 0x147AE)

            def fall():
                ls(p, 2, "x34")
                p.iop(1, 1, "-", 2)
                limi(p, 1)
                ss(p, "y31", 1)
            p.if_(1, "GE", 12, fall, lambda: (setk(p, "y31", 0), setk(p, "x31", 5)), kind="i")
        when(1, s1)
        when(2, s2)
        when(3, s3)
        when(4, s4)
        # x39: 1 wait x40 blocks, 2 fade y39 by 0x2526E, 3 on
        p.iconst(9, 0)
        p.st(GO, 9)
        ls(p, 9, "x39")
        p.iconst(12, 2)

        def wait():
            ls(p, 2, "x40")

            def next_():
                ls(p, 3, "x39")
                addk(p, 3, 3, 1)
                ss(p, "x39", 3)
                p.iconst(9, 1)
                p.st(GO, 9)
            p.ifz(2, "GT", lambda: (addk(p, 2, 2, -1), ss(p, "x40", 2)), next_)
        p.if_(9, "LT", 12, wait, lambda: p.if_(9, "EQ", 12, lambda: (p.iconst(9, 1), p.st(GO, 9)),
                                                 kind="i"), kind="i")

        def fade():
            ls(p, 1, "y39")
            p.iconst(12, 0x147AE)

            def down():
                addk(p, 1, 1, -0x2526E)
                ss(p, "y39", 1)

            def off():
                ls(p, 3, "x39")
                addk(p, 3, 3, 1)
                ss(p, "x39", 3)
                setk(p, "y39", 0)
            p.if_(1, "GE", 12, down, off, kind="i")
        p.ld(9, GO)
        p.ifz(9, "NE", fade)
    p.ld(9, SKIP)
    p.ifz(9, "EQ", rest)


# -- the consonants' renderers -----------------------------------------------------------------
def _copy(p, L, src, dst):
    p.iconst(12, _a(L, src))
    p.seti(5, 12)
    p.iconst(12, _a(L, dst))
    p.seti(2, 12)
    p.call("vo6_copy", lambda: p.loop(_a(L, "n4"), 16, lambda: (p.ldpost(1, 5), p.stpost(2, 1))))


def _qconsts(p: Prog) -> None:
    """the floor quantizer's constants: F8 2^23, R9 -23, F11 2^100, F13 -2^-23, F14 0"""
    p.fconst(8, 2.0 ** 23)
    p.iconst(9, -23)
    p.fconst(11, 2.0 ** 100)
    p.fconst(13, -Q23)
    p.fconst(14, 0.0)


def _floor(p: Prog, x: int, t: int, u: int) -> None:
    """Fx = floor(Fx 2^23) / 2^23 (the 56300's a1: a word's value, the limiter's truncation), no
    branch: trunc, then one LSB down where that went up (Fx - trunc < 0). Clobbers Ft, Fu."""
    p.fop(t, x, "*", 8)
    p.trunc(t, t)
    p.float_(t, t, 9)
    p.fop(u, x, "-", t)
    p.fop(u, u, "*", 11)
    p.fop(u, u, "MIN", 14)
    p.fop(u, u, "MAX", 13)
    p.fop(x, t, "+", u)


def _bq_body(p: Prog, L: C.Layout) -> None:
    """y = 2 (c0 x + c1 x1 + c2 x2 - c3 y1 - c4 y2), limited, the limited y fed back: I5 the
    input, I2 the output, I0 the state (x1, x2, y1, y2), CO the coefficients (0x1471AC/0x1471CB)"""
    _qconsts(p)
    p.ldi(2, 0, 0)
    p.ldi(3, 1, 0)
    p.ldi(4, 2, 0)
    p.ldi(5, 3, 0)

    def one():
        p.ldpost(1, 5)
        p.ld(10, _a(L, "CO"))
        p.fop(6, 10, "*", 1)
        p.ld(10, _a(L, "CO") + 4)
        p.fop(7, 10, "*", 2)
        p.fop(6, 6, "+", 7)
        p.ld(10, _a(L, "CO") + 8)
        p.fop(7, 10, "*", 3)
        p.fop(6, 6, "+", 7)
        p.ld(10, _a(L, "CO") + 12)
        p.fop(7, 10, "*", 4)
        p.fop(6, 6, "-", 7)
        p.ld(10, _a(L, "CO") + 16)
        p.fop(7, 10, "*", 5)
        p.fop(6, 6, "-", 7)
        p.fop(6, 6, "+", 6)
        _floor(p, 6, 7, 15)
        C.sat(p, 6)
        p.stpost(2, 6)
        p.fpass(3, 2)
        p.fpass(2, 1)
        p.fpass(5, 4)
        p.fpass(4, 6)
    p.loop(_a(L, "n4"), 16, one)
    p.sti(0, 0, 2)
    p.sti(1, 0, 3)
    p.sti(2, 0, 4)
    p.sti(3, 0, 5)


def _bqx_body(p: Prog, L: C.Layout) -> None:
    """The consonant biquad in the 56300's arithmetic, exactly: y = lim(floor(2 (c0 x + c1 x1 +
    c2 x2 - c3 y1 - c4 y2) / 2^23)) on the words; the coefficients' 12-bit halves at CO (10
    floats). I5 the input, I2 the output, I0 the state (x1, x2, y1, y2)."""
    for k, (h, l) in enumerate(((3, 4), (5, 6), (7, 8), (9, 10))):
        p.ldi(1, k, 0)
        _word(p, 13, 1)
        _split(p, 13, h, l)

    def one():
        p.ldpost(1, 5)
        _word(p, 13, 1)
        _split(p, 13, 1, 2)
        p.iconst(14, 0)
        p.iconst(15, 0)
        p.iconst(13, 0)
        for k, (h, l), sub in ((0, (1, 2), False), (1, (3, 4), False), (2, (5, 6), False),
                               (3, (7, 8), True), (4, (9, 10), True)):
            p.ld(0, _a(L, "CO") + 8 * k)
            p.ld(11, _a(L, "CO") + 8 * k + 4)
            _prod(p, 0, 11, h, l, sub, t=12)
        _sum(p, 22)
        limi(p, 14)
        p.fpass(5, 3)
        p.fpass(6, 4)
        p.fpass(3, 1)
        p.fpass(4, 2)
        p.fpass(9, 7)
        p.fpass(10, 8)
        _split(p, 14, 7, 8)
        i2f(p, 0, 14)
        p.stpost(2, 0)
    p.loop(_a(L, "n4"), 16, one)
    p.ldi(1, -1, 5)
    p.sti(0, 0, 1)
    p.ldi(1, -2, 5)
    p.sti(1, 0, 1)
    p.ldi(1, -1, 2)
    p.sti(2, 0, 1)
    p.ldi(1, -2, 2)
    p.sti(3, 0, 1)


def _biquad(p, L, coefs, src, dst, state):
    """the output biquad (state 'ob', COEFS constants, float) or the consonant's (state 'cb',
    exact: CO already holds its coefficients' halves, COEFS None)"""
    exact = state == "cb"
    if not exact:
        for k, c in enumerate(coefs):
            p.fconst(1, s24(c) * Q23)
            p.st(_a(L, "CO") + 4 * k, 1)
    p.iconst(12, _a(L, src))
    p.seti(5, 12)
    p.iconst(12, _a(L, dst))
    p.seti(2, 12)
    p.ld(1, L.md.C["mdb"])
    addk(p, 1, 1, 4 * (K.S0 + S[state]))
    p.seti(0, 1)
    if exact:
        p.call("vo6_bqx", lambda: _bqx_body(p, L))
    else:
        p.call("vo6_bq", lambda: _bq_body(p, L))


def _crossfade(p, L):
    """EXC = lim(floor((y31 UNV + lim(y31 + xk) EXC) / 2^23)) exactly (xk: L -0x800000 = -1.0,
    M N Z -0x7FFFF8)"""
    ls(p, 9, "y31")
    _split(p, 9, 1, 2)
    p.ld(10, _a(L, "xk"))
    p.iop(9, 9, "+", 10)
    limi(p, 9)
    _split(p, 9, 3, 4)
    p.iconst(12, _a(L, "UNV"))
    p.seti(5, 12)
    p.iconst(12, _a(L, "EXC"))
    p.seti(2, 12)

    def one():
        p.iconst(14, 0)
        p.iconst(15, 0)
        p.iconst(13, 0)
        p.ldpost(5, 5)
        _word(p, 9, 5)
        _split(p, 9, 5, 6)
        _prod(p, 1, 2, 5, 6, False)
        p.ldi(7, 0, 2)
        _word(p, 9, 7)
        _split(p, 9, 7, 8)
        _prod(p, 3, 4, 7, 8, False)
        _sum(p, 23)
        limi(p, 14)
        i2f(p, 7, 14)
        p.stpost(2, 7)
    p.loop(_a(L, "n3"), 16, one)


def _trill(p, L):
    """RR: y54 the phase; x55 up by 0x28F5C a block to 0x7FFFAC, held 15 blocks (y55), down to 0,
    held 15, again (146C3B..146C88)"""
    STT = _a(L, "stt")

    def stt(v):
        p.iconst(9, v)
        p.st(STT, 9)

    def when(v, body):
        p.ld(9, STT)
        p.iconst(12, v)
        p.if_(9, "EQ", 12, body, kind="i")
    ls(p, 9, "y54")
    p.iconst(12, 2)
    p.if_(9, "LT", 12, lambda: stt(1), lambda: (
        p.iconst(12, 2), p.if_(9, "EQ", 12, lambda: stt(2), lambda: (
            p.iconst(12, 3), p.if_(9, "EQ", 12, lambda: stt(3), lambda: stt(4), kind="i")),
            kind="i")), kind="i")

    def s1():
        ls(p, 1, "x55")
        p.iconst(12, 0x7EB852)
        p.if_(1, "GE", 12, lambda: (setk(p, "x55", 0x7FFFAC), setk(p, "y54", 2), stt(2)),
              lambda: (addk(p, 1, 1, 0x28F5C), ss(p, "x55", 1), stt(0)), kind="i")

    def hold(nxt):
        def body():
            ls(p, 1, "y55")
            p.ifz(1, "GT", lambda: (addk(p, 1, 1, -1), ss(p, "y55", 1), stt(0)),
                  lambda: (setk(p, "y55", 0xF), setk(p, "y54", nxt), stt(nxt if nxt == 3 else 0)))
        return body

    def s3():
        ls(p, 1, "x55")
        p.iconst(12, 0x28F5C)
        p.if_(1, "GT", 12, lambda: (addk(p, 1, 1, -0x28F5C), ss(p, "x55", 1), stt(0)),
              lambda: (setk(p, "x55", 0), setk(p, "y54", 4), stt(4)), kind="i")
    when(1, s1)
    when(2, hold(3))
    when(3, s3)
    when(4, hold(1))


def _store_mask(p: Prog, L: C.Layout) -> None:
    """O[d] = R6 for each bit d of R5. Clobbers R5, R7, R12, I2."""
    p.iconst(7, _a(L, "O0"))

    def one():
        p.iconst(12, 1)
        p.iop(12, 5, "AND", 12)
        p.ifz(12, "NE", lambda: (p.seti(2, 7), p.sti(0, 2, 6)))
        p.lsh(5, 5, -1)
        addk(p, 7, 7, 4)
    p.loop(_a(L, "n3"), 8, one)


def _vals(p: Prog, L: C.Layout, d: int, r: int) -> None:
    """Rd = V[Rr] (V: 0, F0..F3, y35, y31, x55 at v0..). Clobbers R12, I1."""
    p.lsh(d, r, 2)
    p.iconst(12, _a(L, "v0"))
    p.iop(d, 12, "+", d)
    p.seti(1, d)
    p.ldi(d, 0, 1)


def _op(p: Prog, L: C.Layout) -> None:
    """one offset op at I0 (8 fields, 21 words apart): O[m1] = MPY(lim(C - V[v]), W),
    O[m2] = MPY(that, g2)"""
    regs = (9, 10, 11, 4, 13, 5, 14, 15)       # v, C, wm, wv, wc, m1, m2, g2 (ints)
    for i, r in enumerate(regs):
        p.ldi(r, 21 * i, 0)
        _word(p, r, r)
    for r, name in ((13, "kk"), (14, "src"), (15, "dst")):
        p.st(_a(L, name), r)

    def go():
        p.st(_a(L, "c1"), 5)
        p.st(_a(L, "g"), 10)
        _vals(p, L, 1, 9)
        p.ld(10, _a(L, "g"))
        p.iop(1, 10, "-", 1)
        limi(p, 1)
        p.st(_a(L, "x1"), 1)                   # lim(C - V)
        # W by its mode (R11): 0 V[wv], 1 wv, 2 -MPY(V[wv], wc), 3 MPY(V[wv], V[wc])
        p.ipass(2, 4)
        p.iconst(12, 1)

        def m0():
            _vals(p, L, 2, 4)

        def m23():
            _vals(p, L, 1, 4)
            p.ld(13, _a(L, "kk"))
            p.iconst(12, 3)
            p.if_(11, "EQ", 12, lambda: _vals(p, L, 2, 13), lambda: p.ipass(2, 13), kind="i")
            mul(p)
            p.iconst(12, 2)
            p.if_(11, "EQ", 12, lambda: (p.iconst(12, 0), p.iop(1, 12, "-", 1)), kind="i")
            p.ipass(2, 1)
        p.ifz(11, "EQ", m0, lambda: p.if_(11, "GT", 12, m23, kind="i"))
        p.ld(1, _a(L, "x1"))
        mul(p)
        p.ipass(6, 1)
        p.ld(5, _a(L, "c1"))
        p.st(_a(L, "x1"), 1)
        _store_mask(p, L)

        def second():
            p.ld(1, _a(L, "x1"))
            p.ld(2, _a(L, "dst"))
            mul(p)
            p.ipass(6, 1)
            p.ld(5, _a(L, "src"))
            _store_mask(p, L)
        p.ld(14, _a(L, "src"))
        p.ifz(14, "NE", second)
    p.ifz(5, "NE", go)


def _render(p: Prog, L: C.Layout) -> None:
    """CONS's renderer from its row (rom.VO_CONS): offsets, the unvoiced source, y40"""
    row = 4 * (4 * 8 + 8)
    ls(p, 1, "k")                              # field f of consonant k at cons + 4 (21 f + k)
    p.lsh(1, 1, 2)
    p.iconst(12, L.VO["cons"])
    p.iop(1, 12, "+", 1)
    p.st(_a(L, "row"), 1)
    p.seti(0, 1)
    for f, name in ((32, "kind"), (33, "xk"), (39, "st")):     # st: y40's rule
        p.ldi(3, 21 * f, 0)
        _word(p, 3, 3)
        p.st(_a(L, name), 3)
    # the coefficients' 12-bit halves (CO, floats) for the exact biquad
    p.iconst(12, _a(L, "CO"))
    p.seti(2, 12)
    for f in range(34, 39):
        p.ldi(3, 21 * f, 0)
        _word(p, 3, 3)
        _split(p, 3, 4, 5)
        p.stpost(2, 4)
        p.stpost(2, 5)
    p.ld(9, _a(L, "kind"))
    p.iconst(12, 4)
    p.if_(9, "EQ", 12, lambda: _trill(p, L), kind="i")
    # V: 0, F0..F3, y35, y31, x55
    p.iconst(3, 0)
    p.st(_a(L, "v0"), 3)
    for k in range(4):
        p.ld(3, _a(L, f"F{k}"))
        p.st(_a(L, f"v{k + 1}"), 3)
    for k, name in ((5, "y35"), (6, "y31"), (7, "x55")):
        ls(p, 3, name)
        p.st(_a(L, f"v{k}"), 3)
    p.ld(1, _a(L, "row"))
    p.st(_a(L, "opp"), 1)

    def op():
        p.ld(1, _a(L, "opp"))
        p.seti(0, 1)
        _op(p, L)
        p.ld(1, _a(L, "opp"))
        addk(p, 1, 1, 4 * 21 * 8)
        p.st(_a(L, "opp"), 1)
    p.loop(_a(L, "n2"), 4, op)
    # the source: 0 the noise / 8; 1 its biquad; 2 the excitation's biquad and the crossfade;
    # 3 Z: noise / 16 + the excitation, its biquad, the crossfade; 4 RR: the excitation scaled
    p.ld(9, _a(L, "kind"))

    def copy():
        _copy(p, L, "C30", "UNV")

    def bq(src):
        return lambda: _biquad(p, L, None, src, "UNV", "cb")

    def k2():
        bq("EXC")()

    def k3():
        _zmix(p, L)
        bq("C30")()

    def k4():
        _rrscale(p, L)
        copy()

    def kind(n, then, else_):
        p.ld(9, _a(L, "kind"))
        p.iconst(12, n)
        p.if_(9, "EQ", 12, then, else_, kind="i")
    kind(0, copy, lambda: kind(1, bq("C30"), lambda: kind(2, k2, lambda: kind(3, k3, k4))))
    p.ld(9, _a(L, "xk"))                       # kinds 2, 3: the crossfade (xk != 0)
    p.ifz(9, "NE", lambda: _crossfade(p, L))
    # y40 = 2 when: 1 x35 > 3; 2 x31 > 4; 3 x31 == 5
    p.ld(9, _a(L, "st"))

    def y40(name, cond, v):
        ls(p, 10, name)
        p.iconst(12, v)
        p.if_(10, cond, 12, lambda: setk(p, "y40", 2), kind="i")

    def rule(n, then, else_=None):
        p.ld(9, _a(L, "st"))
        p.iconst(12, n)
        p.if_(9, "EQ", 12, then, else_, kind="i")
    rule(1, lambda: y40("x35", "GT", 3), lambda: rule(2, lambda: y40("x31", "GT", 4),
                                                       lambda: rule(3, lambda: y40("x31", "EQ", 5))))


def _zmix(p: Prog, L: C.Layout) -> None:
    """Z: C30 = lim(C30 / 2 + EXC) (exact in float)"""
    p.iconst(12, _a(L, "C30"))
    p.seti(5, 12)
    p.iconst(12, _a(L, "EXC"))
    p.seti(2, 12)
    p.fconst(3, 0.5)

    def one():
        p.ldi(1, 0, 5)
        p.fop(1, 1, "*", 3)
        p.ldpost(2, 2)
        p.fop(1, 1, "+", 2)
        C.sat(p, 1)
        p.stpost(5, 1)
    p.loop(_a(L, "n3"), 16, one)


def _rrscale(p: Prog, L: C.Layout) -> None:
    """RR: EXC = lim(MPY(EXC, lim(0x7FFFAC - MPY(0x59999A, y31))))"""
    ls(p, 1, "y31")
    mulc(p, 1, 0x59999A)
    p.iconst(12, 0x7FFFAC)
    p.iop(1, 12, "-", 1)
    limi(p, 1)
    i2f(p, 1, 1)
    _qconsts(p)
    p.iconst(12, _a(L, "EXC"))
    p.seti(5, 12)

    def one():
        p.ldi(2, 0, 5)
        p.fop(2, 2, "*", 1)
        _floor(p, 2, 0, 15)
        C.sat(p, 2)
        p.stpost(5, 2)
    p.loop(_a(L, "n3"), 16, one)


def _consonants(p: Prog, L: C.Layout) -> None:
    """x35 == 1 or y40 > 1: none (the noise / 8 is the unvoiced source); else CONS's renderer"""
    p.iconst(0, 0)
    for d in range(8):
        p.st(_a(L, f"O{d}"), 0)
    ls(p, 9, "x35")
    p.iconst(12, 1)

    def maybe():
        ls(p, 9, "y40")
        p.iconst(12, 1)
        p.if_(9, "GT", 12, lambda: _copy(p, L, "C30", "UNV"), lambda: _render(p, L), kind="i")
    p.if_(9, "EQ", 12, lambda: _copy(p, L, "C30", "UNV"), maybe, kind="i")


# -- the resonators ------------------------------------------------------------------------
def _res_body(p: Prog, L: C.Layout, parallel: bool) -> None:
    """y = c1 x - c2 y1 - c2 y1 - R y2 (y1, y2 the limited outputs), c1/c2 ramped (RAMP); series:
    the limited y to I2; parallel: I2's word + y, limited. I5 the input, I0 the state (y1, y2), R"""
    _qconsts(p)
    p.ld(10, _a(L, "R"))
    p.ldi(2, 0, 0)
    p.ldi(3, 1, 0)
    p.iconst(12, _a(L, "RAMP"))
    p.seti(1, 12)

    def one():
        p.ldpost(1, 5)
        p.ldpost(4, 1)
        p.ldpost(5, 1)
        p.fop(6, 4, "*", 1)
        p.fop(7, 5, "*", 2)
        p.fop(6, 6, "-", 7)
        p.fop(6, 6, "-", 7)
        p.fop(7, 10, "*", 3)
        p.fop(6, 6, "-", 7)
        if parallel:
            p.ldi(7, 0, 2)
            p.fop(7, 7, "+", 6)
            _floor(p, 7, 0, 15)
            C.sat(p, 7)
            p.stpost(2, 7)
        p.fpass(3, 2)
        p.fpass(2, 6)
        _floor(p, 2, 0, 15)
        C.sat(p, 2)
        if not parallel:
            p.stpost(2, 2)
    p.loop(_a(L, "n4"), 16, one)
    p.sti(0, 0, 2)
    p.sti(1, 0, 3)


def _split(p: Prog, r: int, fh: int, fl: int) -> None:
    """Ffh, Ffl = the int word Rr's halves as floats: r = fh 4096 + fl, fl 0..4095 (fh not r).
    Clobbers R12."""
    assert r != fh
    p.ash(fh, r, -12)
    p.iconst(12, 0xFFF)
    p.iop(fl, r, "AND", 12)
    p.iconst(12, 0)
    p.float_(fh, fh, 12)
    p.float_(fl, fl, 12)


def _word(p: Prog, d: int, f: int) -> None:
    """Rd = the Q23 word the float Ff holds (exactly). Clobbers R12."""
    p.fconst(12, 2.0 ** 23)
    p.fop(d, f, "*", 12)
    p.trunc(d, d)


def _prod(p: Prog, uh: int, ul: int, vh: int, vl: int, sub: bool, twice: bool = False,
          t: int = 11) -> None:
    """A (R14), M (R15), W (R13) +-= u x v's partial products (12-bit halves, exact in float):
    u v = A 2^24 + M 2^12 + W. Clobbers Rt."""
    op = "-" if sub else "+"
    for a, b, r in ((uh, vh, 14), (uh, vl, 15), (ul, vh, 15), (ul, vl, 13)):
        p.fop(t, a, "*", b)
        p.trunc(t, t)
        if twice:
            p.lsh(t, t, 1)
        p.iop(r, r, op, t)


def _sum(p: Prog, k: int) -> None:
    """R14 = floor((A 2^24 + M 2^12 + W) / 2^k), k = 23 (a MPY's a1) or 22 (after an ASL)"""
    p.ash(13, 13, -12)
    p.iop(15, 15, "+", 13)
    p.ash(15, 15, -(k - 12))
    p.lsh(14, 14, 24 - k)
    p.iop(14, 14, "+", 15)


def _ser_body(p: Prog, L: C.Layout) -> None:
    """The series resonator in the 56300's arithmetic, exactly: y = lim(floor((c1 x - c2 y1 -
    c2 y1 - R y2) / 2^23)) on the words (a high-Q formant rings a float's one-LSB slip up to
    ~35 LSB, and the voiced path is amplified 4096 times). I5 the input, I2 the output, I0 the
    state (y1, y2), I1 the ramps (c1, c2), the word 'R' (int)."""
    p.ldi(1, 0, 0)
    _word(p, 7, 1)
    _split(p, 7, 1, 2)                         # y1
    p.ldi(3, 1, 0)
    _word(p, 7, 3)
    _split(p, 7, 3, 4)                         # y2
    p.ld(7, _a(L, "R"))
    _split(p, 7, 5, 6)
    p.iconst(12, _a(L, "RAMP"))
    p.seti(1, 12)

    def one():
        p.iconst(14, 0)
        p.iconst(15, 0)
        p.iconst(13, 0)
        p.ldpost(9, 5)
        _word(p, 9, 9)
        _split(p, 9, 7, 8)                     # x
        p.ldpost(10, 1)
        _word(p, 10, 10)
        _split(p, 10, 9, 10)                   # c1
        _prod(p, 9, 10, 7, 8, False)
        p.ldpost(7, 1)
        _word(p, 7, 7)
        _split(p, 7, 9, 10)                    # c2
        _prod(p, 9, 10, 1, 2, True, twice=True)
        _prod(p, 5, 6, 3, 4, True)
        _sum(p, 23)
        limi(p, 14)
        p.fpass(3, 1)
        p.fpass(4, 2)
        _split(p, 14, 1, 2)
        i2f(p, 7, 14)
        p.stpost(2, 7)
    p.loop(_a(L, "n4"), 16, one)
    p.ldi(7, -1, 2)
    p.sti(0, 0, 7)
    p.ldi(7, -2, 2)
    p.sti(1, 0, 7)


def _formant_loop(p: Prog, L: C.Layout) -> None:
    """k = 0..7: formant k & 3's targets (series for k < 4, parallel after), ramps, filter"""
    for k, (m, r) in enumerate(FORM):
        p.iconst(1, -s24(m))
        p.st(_a(L, f"m{k}"), 1)
        p.fconst(1, s24(r) * Q23)
        p.st(_a(L, f"r{k}"), 1)
        p.iconst(1, s24(r))
        p.st(_a(L, f"R{k}i"), 1)
    p.iconst(0, 0)
    p.st(_a(L, "kk"), 0)

    def one():
        p.ld(8, _a(L, "kk"))
        p.iconst(12, 3)
        p.iop(9, 8, "AND", 12)                 # fk
        p.st(_a(L, "f"), 9)
        # x1 = lim(F + O)
        p.lsh(10, 9, 2)
        p.iconst(12, _a(L, "F0"))
        p.iop(10, 12, "+", 10)
        p.seti(1, 10)
        p.ldi(1, 0, 1)
        p.lsh(10, 8, 2)
        p.iconst(12, _a(L, "O0"))
        p.iop(10, 12, "+", 10)
        p.seti(1, 10)
        p.ldi(2, 0, 1)
        add(p, 1, 1, 2)
        limi(p, 1)
        p.st(_a(L, "x1"), 1)
        p.iconst(2, 0x614)
        mulq(p)
        p.st(_a(L, "q0"), 1)                   # i
        p.ld(1, _a(L, "x1"))
        p.iconst(2, 0x620)
        mulq(p)                                # j
        # c1 = C1[fk][j]
        _c1_addr(p, L)
        # c2 = MPY(cos[i], M[fk]) exactly: floor(-cos x |M|), M < 0
        p.ld(3, _a(L, "q0"))
        _tab(p, L, 1, "cos", 3)
        p.iconst(12, 0)
        p.iop(1, 12, "-", 1)
        p.ld(9, _a(L, "f"))
        p.lsh(9, 9, 2)
        p.iconst(12, _a(L, "m0"))
        p.iop(9, 12, "+", 9)
        p.seti(1, 9)
        p.ldi(2, 0, 1)
        mulqs(p)
        i2f(p, 5, 1)                           # c2
        p.ld(9, _a(L, "f"))
        p.lsh(9, 9, 2)
        p.iconst(12, _a(L, "r0"))
        p.iop(9, 12, "+", 9)
        p.seti(1, 9)
        p.ldi(6, 0, 1)
        p.st(_a(L, "R"), 6)
        # the targets' state: tx + 2 k
        p.ld(1, L.md.C["mdb"])
        p.ld(8, _a(L, "kk"))
        p.lsh(8, 8, 3)
        p.iop(1, 8, "+", 1)
        addk(p, 1, 1, 4 * (K.S0 + S["tx"]))
        p.seti(0, 1)
        p.ld(4, _a(L, "c1"))
        p.ldi(1, 0, 0)                         # old c1
        p.ldi(2, 1, 0)                         # old c2
        p.sti(0, 0, 4)
        p.sti(1, 0, 5)
        # the ramps, exactly: floor(old + n lim(new - old) / 16), n = 0..15
        _word(p, 6, 4)
        _word(p, 7, 5)
        _word(p, 1, 1)
        _word(p, 2, 2)
        p.iop(6, 6, "-", 1)
        limi(p, 6)
        p.iop(7, 7, "-", 2)
        limi(p, 7)
        p.lsh(1, 1, 4)
        p.lsh(2, 2, 4)
        p.iconst(12, _a(L, "RAMP"))
        p.seti(2, 12)

        def ramp():
            for acc_r, d in ((1, 6), (2, 7)):
                p.ash(3, acc_r, -4)
                limi(p, 3)
                i2f(p, 3, 3)
                p.stpost(2, 3)
                p.iop(acc_r, acc_r, "+", d) if 8 <= acc_r <= 15 else (p.ipass(12, d), p.iop(acc_r, 12, "+", acc_r))
        p.loop(_a(L, "n3"), 16, ramp)
        # the filter: its state at ser + 2 k (par follows ser)
        p.ld(1, L.md.C["mdb"])
        p.ld(8, _a(L, "kk"))
        p.lsh(8, 8, 3)
        p.iop(1, 8, "+", 1)
        addk(p, 1, 1, 4 * (K.S0 + S["ser"]))
        p.seti(0, 1)
        p.ld(8, _a(L, "kk"))
        p.iconst(12, 4)

        def series():
            # EXC -> C30 -> EXC -> C30 -> EXC
            p.iconst(12, 1)
            p.iop(9, 8, "AND", 12)
            p.ifz(9, "EQ", lambda: (p.iconst(12, _a(L, "EXC")), p.seti(5, 12),
                                    p.iconst(12, _a(L, "C30")), p.seti(2, 12)),
                  lambda: (p.iconst(12, _a(L, "C30")), p.seti(5, 12),
                           p.iconst(12, _a(L, "EXC")), p.seti(2, 12)))
            p.ld(9, _a(L, "f"))
            p.lsh(9, 9, 2)
            p.iconst(12, _a(L, "R0i"))
            p.iop(9, 12, "+", 9)
            p.seti(1, 9)
            p.ldi(9, 0, 1)
            p.st(_a(L, "R"), 9)
            p.call("vo6_ser", lambda: _ser_body(p, L))

        def parallel():
            p.iconst(12, 4)

            def clear():
                p.iconst(12, _a(L, "C30"))
                p.seti(5, 12)
                p.iconst(6, 0)
                p.loop(_a(L, "n3"), 16, lambda: p.stpost(5, 6))
            p.ld(8, _a(L, "kk"))
            p.if_(8, "EQ", 12, clear, kind="i")
            p.iconst(12, _a(L, "UNV"))
            p.seti(5, 12)
            p.iconst(12, _a(L, "C30"))
            p.seti(2, 12)
            p.call("vo6_par", lambda: _res_body(p, L, True))
        p.if_(8, "LT", 12, series, parallel, kind="i")
        p.ld(8, _a(L, "kk"))
        addk(p, 8, 8, 1)
        p.st(_a(L, "kk"), 8)
    p.loop(_a(L, "n2"), 8, one)


def _c1_addr(p: Prog, L: C.Layout) -> None:
    """c1 = C1[0x620 fk + j] (R1 = j, word f = fk) -> word c1. Clobbers R2, R3, R9, R12, I1."""
    p.ld(9, _a(L, "f"))
    p.iconst(2, 0)
    for b in (5, 9, 10):                       # 0x620 = 2^10 + 2^9 + 2^5
        p.lsh(3, 9, b)
        p.ipass(12, 3)
        p.iop(2, 12, "+", 2)
    p.ipass(12, 2)
    p.iop(2, 12, "+", 1)
    p.lsh(2, 2, 2)
    p.iconst(12, L.VO["c1"])
    p.iop(2, 12, "+", 2)
    p.seti(1, 2)
    p.ldi(3, 0, 1)
    p.st(_a(L, "c1"), 3)


# -- the source ------------------------------------------------------------------------------
def _source(p: Prog, L: C.Layout) -> None:
    """16 noise words (s = b + x, t = x + s, mod 2^24, eight times) -> C30; EXC = noise VOIC / 2^16
    + ring (VOIC / 256 - 1/2), limited; C30 = noise / 8"""
    ls(p, 1, "nb")
    ls(p, 2, "nx")
    p.iconst(12, _a(L, "C30"))
    p.seti(5, 12)

    def one():
        add(p, 3, 1, 2)
        p.iconst(12, M24)
        p.iop(3, 3, "AND", 12)                  # s
        add(p, 4, 2, 3)
        p.iconst(12, M24)
        p.iop(4, 4, "AND", 12)                  # t
        p.ipass(1, 3)
        p.ipass(2, 4)
        for r in (3, 4):
            p.lsh(5, r, 8)
            p.iconst(12, -31)
            p.float_(5, 5, 12)
            p.stpost(5, 5)
    p.loop(_a(L, "n1"), 8, one)
    ss(p, "nb", 2)
    ss(p, "nx", 1)
    C.knob(p, 1, 3)
    p.iconst(12, -16)
    p.float_(2, 1, 12)                          # VOIC / 2^16
    p.iconst(12, -8)
    p.float_(3, 1, 12)
    p.fconst(12, 0.5)
    p.fop(3, 3, "-", 12)                        # VOIC / 256 - 1/2
    p.ld(1, _a(L, "p"))
    p.lsh(1, 1, 2)
    p.ld(12, _a(L, "rb"))
    p.iop(1, 12, "+", 1)
    p.seti(2, 1)
    p.iconst(12, _a(L, "C30"))
    p.seti(5, 12)
    p.iconst(12, _a(L, "EXC"))
    p.seti(1, 12)

    _qconsts(p)

    def exc():
        p.ldi(4, 0, 5)
        p.ldpost(6, 2)
        p.fop(7, 4, "*", 2)
        p.fop(6, 6, "*", 3)
        p.fop(7, 7, "+", 6)
        _floor(p, 7, 10, 15)
        C.sat(p, 7)
        p.stpost(1, 7)
        p.fconst(12, 0.125)
        p.fop(4, 4, "*", 12)
        _floor(p, 4, 10, 15)
        p.stpost(5, 4)
    p.loop(_a(L, "n1"), 16, exc)


# -- the level, the AGC, the gain, the mix ---------------------------------------------------
def _follower(p: Prog, L: C.Layout) -> None:
    """on the voiced output (EXC): power b += x^2 - lim(b) y0, level a += (lim(b) - lim(a)) y0,
    y0 = w + 0x20C5 (Q23); lim the limited words (floored)"""
    C.vw(p, 1, "i3")
    addk(p, 1, 1, 0x20C5)
    i2f(p, 10, 1)
    _qconsts(p)
    ls(p, 2, "pb")
    ls(p, 3, "pa")
    p.iconst(12, _a(L, "EXC"))
    p.seti(5, 12)

    def one():
        p.ldpost(1, 5)
        p.fpass(4, 2)
        _floor(p, 4, 5, 7)
        C.sat(p, 4)                             # x1 = lim(b)
        p.fop(5, 1, "*", 1)
        p.fop(2, 2, "+", 5)
        p.fop(5, 4, "*", 10)
        p.fop(2, 2, "-", 5)
        p.fpass(6, 3)
        _floor(p, 6, 5, 7)
        C.sat(p, 6)                             # lim(a)
        p.fop(5, 4, "*", 10)
        p.fop(3, 3, "+", 5)
        p.fop(5, 6, "*", 10)
        p.fop(3, 3, "-", 5)
    p.loop(_a(L, "n1"), 16, one)
    ss(p, "pb", 2)
    ss(p, "pa", 3)


def _exp2_poly() -> tuple[float, ...]:
    """2^x on [0, 1], degree 7 (least squares on Chebyshev nodes), low order first"""
    import numpy as np
    x = 0.5 + 0.5 * np.cos(np.pi * (np.arange(64) + 0.5) / 64)
    return tuple(float(c) for c in np.polyfit(x, 2.0 ** x, 7)[::-1])


def _agc(p: Prog, L: C.Layout) -> None:
    """g = 2^(k / 2048 - 1) 2^(12 - e2), k = 2047 - (X & 0x7FF), e2 = X >> 11, X = max(0, 49152 +
    1024 e - LOG[m]) for the level a (its low Q23 bit set: 'or #1') = 1.m x 2^(e - 1), m its top
    8 mantissa bits: the render's clb / log table / exp table (P:0x14712B..0x147146)"""
    ls(p, 1, "pa")
    p.fconst(12, 2.0 ** 23)
    p.fop(2, 1, "*", 12)
    p.trunc(2, 2)
    p.iconst(12, 1)
    p.iop(2, 2, "AND", 12)
    p.ifz(2, "EQ", lambda: (p.fconst(12, Q23), p.fop(1, 1, "+", 12)))
    p.lsh(2, 1, -23)
    p.iconst(12, 0xFF)
    p.iop(2, 2, "AND", 12)                      # the biased exponent
    p.lsh(3, 1, -15)
    p.iop(3, 3, "AND", 12)                      # m
    _tab(p, L, 4, "log", 3)
    p.lsh(2, 2, 10)
    addk(p, 2, 2, 49152 - 126 * 1024)
    p.iop(2, 2, "-", 4)
    p.iconst(12, 0)
    p.iop(2, 2, "MAX", 12)                      # X
    p.lsh(3, 2, -11)                            # e2
    p.iconst(12, 0x7FF)
    p.iop(4, 2, "AND", 12)
    p.iconst(5, 0x7FF)
    p.iop(4, 5, "-", 4)                         # k
    p.iconst(12, -11)
    p.float_(4, 4, 12)                          # k / 2048
    cs = _exp2_poly()
    p.fconst(5, cs[-1])
    for c in reversed(cs[:-1]):
        p.fop(5, 5, "*", 4)
        p.fconst(12, c)
        p.fop(5, 5, "+", 12)                    # 2^(k / 2048)
    p.fconst(12, 2.0 ** 29)
    p.fop(5, 5, "*", 12)
    p.trunc(5, 5)
    p.iconst(12, -18)
    p.iop(3, 12, "-", 3)                        # 2^(11 - e2) / 2^29
    p.float_(5, 5, 3)
    p.fconst(12, C.TOP)
    p.fop(5, 5, "MIN", 12)
    p.st(_a(L, "g"), 5)


def _gain_mix(p: Prog, L: C.Layout) -> None:
    """y35 = MPY(y39, MPY(y35, L)), L = 0x7FFFF8 (x35 == 1) or lim(level << 8); G = g y35;
    G and y31 ramped; mix (UNV) = (G voiced) << 12 + y31 lim(unvoiced x37)"""
    p.iconst(2, 0x7FFFF8)
    ls(p, 9, "x35")
    p.iconst(12, 1)

    def lev():
        ls(p, 2, "lev")
        p.lsh(2, 2, 8)
        p.iconst(12, 0x7FFFFF)
        p.iop(2, 2, "MIN", 12)
    p.if_(9, "NE", 12, lev, kind="i")
    ls(p, 1, "y35")
    mulqs(p)
    ls(p, 2, "y39")
    mulqs(p)
    ss(p, "y35", 1)
    i2f(p, 1, 1)
    p.ld(2, _a(L, "g"))
    p.fop(1, 1, "*", 2)                         # G
    ls(p, 3, "y31")
    i2f(p, 3, 3)
    ls(p, 4, "g")                               # the old targets
    ls(p, 5, "t31")
    ss(p, "g", 1)
    ss(p, "t31", 3)
    p.fop(1, 1, "-", 4)
    C.sat(p, 1)
    p.fop(3, 3, "-", 5)
    C.sat(p, 3)
    p.fconst(12, 1.0 / 16.0)
    p.fop(1, 1, "*", 12)
    p.fop(3, 3, "*", 12)
    ls(p, 6, "x37")
    i2f(p, 6, 6)
    p.iconst(12, _a(L, "EXC"))
    p.seti(5, 12)
    p.iconst(12, _a(L, "C30"))
    p.seti(1, 12)
    p.iconst(12, _a(L, "UNV"))
    p.seti(2, 12)

    _qconsts(p)

    def one():
        p.fpass(7, 4)
        _floor(p, 7, 12, 15)
        C.sat(p, 7)                             # G[n]
        p.fpass(2, 5)
        _floor(p, 2, 12, 15)
        C.sat(p, 2)                             # y31[n]
        p.ldpost(0, 5)
        p.fop(0, 0, "*", 7)
        p.fconst(12, 4096.0)
        p.fop(0, 0, "*", 12)
        p.ldpost(10, 1)
        p.fop(10, 10, "*", 6)
        _floor(p, 10, 12, 15)
        C.sat(p, 10)
        p.fop(10, 10, "*", 2)
        p.fop(0, 0, "+", 10)
        _floor(p, 0, 12, 15)
        C.sat(p, 0)
        p.stpost(2, 0)
        p.fop(4, 4, "+", 1)
        p.fop(5, 5, "+", 3)
    p.loop(_a(L, "n1"), 16, one)


def half(p: Prog, L: C.Layout) -> None:
    """One Monomachine block: 16 samples at I4."""
    _formants(p, L)
    _pulses(p, L)
    _source(p, L)
    _envelopes(p, L)
    _consonants(p, L)
    _formant_loop(p, L)
    _follower(p, L)
    _agc(p, L)
    _gain_mix(p, L)
    _biquad(p, L, OUT_EQ, "UNV", "C30", "ob")
    p.iconst(12, _a(L, "C30"))
    p.seti(5, 12)
    p.loop(_a(L, "n1"), 16, lambda: (p.ldpost(1, 5), p.stpost(4, 1)))
    ls(p, 1, "lev")
    addk(p, 1, 1, LEV_STEP)
    p.iconst(12, LEV_TOP)
    p.iop(1, 1, "MIN", 12)
    ss(p, "lev", 1)

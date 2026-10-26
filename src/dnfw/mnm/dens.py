"""DPRO-DENS (docs/mnm.md; the Monomachine's P:0x147D01/1C/1D): four oscillators reading one
Digibank wave (WAVE: knob >> 1, here n & 31 of the stand-in) at 2x, three of them at PCH2..4's
ratios (x:0x101AFB: semitones -12..+12 and just intervals; the middle, 1.0, is OFF), each
band-limited by mip level with a crossfade over each octave's top 1/16 toward the low-byte
partner sample of the finer level (`dpro`), mixed at 0x510625 (0.633) each -- an oscillator at
or above 20 kHz, or at the same whole Hz as the first, is silent -- then the 2:1 decimator.
CHRL/CHRW: the Monomachine's chorus after the machine (x:(r6-28) = P:0x145C48), not modelled.

State: S0..S3 the oscillators' phases (top-level samples, 22 fraction bits), S4..S21 the
decimator. VW i1..i4: the increments b (`exact.dens_incs`), i5: the silent ones (bit k).
"""

from __future__ import annotations

from . import core as C
from . import dpro as D
from ..md import core as K
from ..perc.dsl import Prog

NAME, ID = "DPRO-DENS", 33
PNAMES = ("PCH2", "PCH3", "PCH4", "WAVE", "---", "CHRL", "CHRW", "TUNE")
DEFAULTS = (63, 63, 63, 0, 0, 0, 0, 64)
S_PH, S_DEC = 0, 4
SUB = 0x17C70
GAIN = 0x510625


def init(p: Prog, L: C.Layout) -> None:
    D.zero(p, L, S_PH, 4 + D.DEC_WORDS)


def trig(p: Prog, L: C.Layout) -> None:
    pass


def exact(A: int, F: int, knobs, pre: int = 0) -> dict:
    from . import exact as X
    return X.dens_incs(A, knobs)


def pitch(p: Prog, L: C.Layout) -> None:
    """VW i1..i4: A x 4 r_k x 2 x 0x17C70 (r_1 = 1/4), i5: the silent ones. Clobbers R0-R9,
    R12, R13, I1."""
    W = L.W
    C.vw(p, 1, "A")
    p.fconst(12, 2.0 * SUB)
    p.fop(2, 1, "*", 12)
    D.unsigned(p, 3, 2)
    C.vws(p, "i1", 3)
    p.trunc(4, 1)                               # osc 1's whole Hz
    p.iconst(0, 0)
    p.st(W["m"], 0)
    p.iconst(0, 2)
    p.st(W["bit"], 0)
    p.iconst(0, 0)
    p.st(W["x1"], 0)

    def one():
        p.ld(5, L.md.C["mdb"])
        p.ld(6, W["x1"])
        D.addr(p, 5, 5, 6)
        p.seti(1, 5)
        p.ldi(7, C.P0, 1)                       # PCH (knob / 128)
        p.fconst(12, 128.0)
        p.fop(7, 7, "*", 12)
        p.trunc(7, 7)
        p.lsh(7, 7, 2)
        p.iconst(12, L.DT["pch"])
        p.iop(7, 12, "+", 7)
        p.seti(1, 7)
        p.ldi(8, 0, 1)                          # r
        p.fconst(12, 4.0)
        p.fop(8, 8, "*", 12)
        p.fop(8, 8, "*", 1)                     # Hz
        p.trunc(9, 8)
        p.ld(6, W["bit"])
        p.ld(5, W["m"])

        def silent():
            p.iop(5, 5, "OR", 6)
        p.if_(9, "EQ", 4, silent, kind="i")
        p.iconst(12, 0x4E20)
        p.if_(9, "GE", 12, silent, kind="i")
        p.st(W["m"], 5)
        p.fconst(12, 2.0 * SUB)
        p.fop(8, 8, "*", 12)
        D.unsigned(p, 9, 8)
        p.ld(5, L.md.C["mdb"])
        p.ld(6, W["x1"])
        D.addr(p, 5, 5, 6)
        p.seti(1, 5)
        p.sti(C.VW["i2"], 1, 9)
        p.ld(6, W["bit"])
        D.addr(p, 6, 6, 6)
        p.st(W["bit"], 6)
        p.ld(6, W["x1"])
        p.iconst(12, 4)
        p.iop(6, 12, "+", 6)
        p.st(W["x1"], 6)
    p.loop(W["osc"], 3, one)
    p.ld(0, W["m"])
    C.vws(p, "i5", 0)


def half(p: Prog, L: C.Layout) -> None:
    D.ready(p, L, lambda: _half(p, L))


def _half(p: Prog, L: C.Layout) -> None:
    W = L.W
    C.knob(p, 1, 3)                             # WAVE
    p.lsh(1, 1, -1)
    p.iconst(12, 31)
    p.iop(1, 1, "AND", 12)
    p.lsh(1, 1, 13)                             # x 2048 words
    p.iconst(12, L.DIGI)
    p.iop(1, 12, "+", 1)
    p.st(W["wb"], 1)
    p.iconst(0, 1)
    p.st(W["bit"], 0)
    p.iconst(0, 0)
    p.st(W["x1"], 0)

    def osc():
        p.ld(1, L.md.C["mdb"])
        p.ld(2, W["x1"])
        D.addr(p, 1, 1, 2)
        p.seti(1, 1)
        p.ldi(2, C.VW["i1"], 1)
        p.st(W["b"], 2)
        p.st(W["bs"], 2)
        p.ldi(3, K.S0 + S_PH, 1)
        p.st(W["u"], 3)
        C.vw(p, 5, "i5")
        p.ld(4, W["bit"])
        p.iop(5, 5, "AND", 4)
        p.ifz(5, "EQ", lambda: render(p, L))
        # the phase moves 32 b a block (u: >> 2)
        p.ld(1, L.md.C["mdb"])
        p.ld(2, W["x1"])
        D.addr(p, 1, 1, 2)
        p.seti(1, 1)
        p.ld(2, W["b"])
        p.lsh(2, 2, 3)
        p.ld(3, W["u"])
        D.addr(p, 3, 3, 2)
        p.sti(K.S0 + S_PH, 1, 3)
        p.ld(4, W["bit"])
        D.addr(p, 4, 4, 4)
        p.st(W["bit"], 4)
        p.ld(2, W["x1"])
        p.iconst(12, 4)
        p.iop(2, 12, "+", 2)
        p.st(W["x1"], 2)
    p.loop(W["osc"], 4, osc)
    D.state_ptr(p, L, 2, S_DEC)
    D.dec2(p, L)


def render(p: Prog, L: C.Layout) -> None:
    """one oscillator into MIX (W b, u, bit set)"""
    W = L.W
    p.fconst(1, 0.5)
    p.st(W["hf"], 1)
    D.start(p, L)
    p.ld(1, W["wx"])
    p.ld(2, W["sh"])
    p.ifz(2, "EQ", lambda: p.fconst(1, 0.0))
    p.st(W["y1"], 1)
    p.fconst(2, C.TOP)
    p.fop(2, 2, "-", 1)
    p.st(W["w"], 2)
    # this level (cb) and the finer one (fb: 2 size words before; at the top level, cb: y1 = 0)
    p.ld(1, W["boff"])
    p.lsh(1, 1, 2)
    p.ld(2, W["wb"])
    D.addr(p, 1, 1, 2)
    p.st(W["cb"], 1)
    p.ld(3, W["msk"])
    p.lsh(3, 3, 3)
    p.iconst(12, 8)
    p.iop(3, 12, "+", 3)
    p.iop(3, 1, "-", 3)
    p.ld(2, W["sh"])
    p.ifz(2, "EQ", lambda: p.ipass(3, 1))
    p.st(W["fb"], 3)
    p.iconst(12, L.BUF)
    p.seti(5, 12)

    def one():
        p.ld(1, W["i0"])
        p.ld(2, W["msk"])
        p.iop(2, 1, "AND", 2)
        p.iconst(12, 1)
        p.iop(1, 12, "+", 1)
        p.st(W["i0"], 1)
        p.lsh(3, 2, 2)
        p.ld(4, W["cb"])
        D.addr(p, 3, 3, 4)
        p.seti(1, 3)
        p.ldi(4, 0, 1)
        D.q23(p, 4, 4)                          # this level's word
        p.lsh(3, 2, 3)
        p.ld(6, W["fb"])
        D.addr(p, 3, 3, 6)
        p.seti(1, 3)
        p.iconst(12, 0xFF)
        p.ldi(6, 0, 1)
        p.iop(6, 6, "AND", 12)
        p.ldi(7, 1, 1)
        p.iop(7, 7, "AND", 12)
        p.lsh(6, 6, 24)
        p.lsh(7, 7, 16)
        p.iop(6, 6, "OR", 7)
        p.iconst(12, -31)
        p.float_(6, 6, 12)                      # the partner: the finer level's low bytes
        p.ld(7, W["w"])
        p.fop(4, 4, "*", 7)
        p.ld(7, W["y1"])
        p.fop(6, 6, "*", 7)
        p.fop(4, 4, "+", 6)
        C.sat(p, 4)
        p.stpost(5, 4)
    p.loop(W["j"], D.NBUF, one)
    p.iconst(1, L.MIX)
    p.st(W["out"], 1)
    p.ld(1, W["bit"])
    p.iconst(12, -1)
    p.iop(1, 12, "+", 1)
    p.st(W["m"], 1)                             # added to MIX but for oscillator 1
    p.fconst(1, GAIN * C.Q23)
    p.st(W["g"], 1)
    D.interp(p, L)

"""SID 6581 (docs/mnm.md): the Monomachine's model of the C64's sound chip voice, at twelve
times the rate (192 samples a block), then the decimator.

Two 24-bit phase accumulators: the oscillator (the note) and a second one (MFRQ, or the
previous track's pitch: MSRC). MOD: OFF; RING (|osc x osc2|, whatever WAVE says); SYNC (the
second oscillator restarts the first: its phase runs at the second's rate and restarts at the
note's); R+S both. WAVE: TRI, SAW, PULS (PW, swept by PWAD, restarted by PWRS), MIX (the
chip's combined waveforms, a 4096-entry table from the Monomachine's firmware, read for every
other sample), NOIS (two linked 24-bit shift registers, clocked at 16 times the note, sampled
when the phase wraps, every fourth sample).

State: S0, S1 the two phases (y:(r6+23), y:(r6+24)), S2 the pulse sweep, S3/S4 the noise
registers, S5 the last phase seen by the noise, S6 its held value, S7..S11 the decimator.
Parameters: PW PWAD PWRS WAVE MOD MSRC MFRQ TUNE.
"""

from __future__ import annotations

from . import core as C
from . import dec
from .wave import coefs, sync_period
from ..md import core as K
from ..perc.dsl import Prog

NAME, ID = "SID 6581", 3
PNAMES = ("PW", "PWAD", "PWRS", "WAVE", "MOD", "MSRC", "MFRQ", "TUNE")
# v0.33: MACHINE SEL's start (the owner: at the shared record's MIX, PW 0, it was silent at
# first): WAVE on TRI, its first choice (knob 12, where its detents put it: people turn
# clockwise from there), PW at the middle for when PULS is chosen, PWRS ON (95, its detent)
DEFAULTS = (64, 0, 95, 12, 0, 0, 64, 64)
COEF = (0x3EF3C2, 0xFE01EB, 0x82F338, 0x01D9BC, 0x3CD5C5, 0x0650D5, 0x8400A4, 0xF9AF2B,
        0xC22E5F, 0x04866C)
GAIN = 0x6186
S_A, S_B, S_PW, S_NA, S_NB, S_HX, S_HV, S_DEC = 0, 1, 2, 3, 4, 5, 6, 7
M24 = 0xFFFFFF
TAPS = 0x658100


def init(p: Prog, L: C.Layout) -> None:
    p.iconst(0, 0)
    for k in (S_A, S_B, S_PW):
        C.sts(p, k, 0)
    p.iconst(0, 0x19B5)
    C.sts(p, S_NA, 0)


def trig(p: Prog, L: C.Layout) -> None:
    C.par(p, 1, 2)                              # PWRS
    p.fconst(12, 0.5)
    p.if_(1, "GE", 12, lambda: (p.iconst(0, 0), C.sts(p, S_PW, 0)))


def _q23(p: Prog, d: int, r: int) -> None:
    """Fd = the 24-bit word in Rr (0..2^24 - 1) as a signed Q23 fraction. Clobbers R12."""
    p.lsh(d, r, 8)
    p.iconst(12, -31)
    p.float_(d, d, 12)


def exact(A: int, F: int, knobs, pre: int = 0) -> dict:
    from . import exact as X
    i1, i2 = X.sid_incs(A, knobs, pre)
    return {"i1": i1, "i2": i2}


def pitch(p: Prog, L: C.Layout) -> None:
    """VW i1: the note's increment a sample (x 16 for NOIS); i2: the second oscillator's."""
    C.vw(p, 1, "A")
    p.fconst(12, 0xFD9FB3 / 2.0 ** 19)
    p.fop(1, 1, "*", 12)
    C.par(p, 2, 3)
    p.fconst(12, 0x666666 * C.Q23)
    p.if_(2, "GE", 12, lambda: (p.fconst(12, 16.0), p.fop(1, 1, "*", 12)))
    p.fconst(12, float(0x7FFFFF))
    p.fop(1, 1, "MIN", 12)
    p.trunc(1, 1)
    C.vws(p, "i1", 1)
    C.par(p, 1, 5)                              # MSRC
    p.fconst(12, 0.5)

    def prch():
        C.vw(p, 2, "pre")

    def mfrq():
        C.knob(p, 2, 6)
        p.lsh(2, 2, 6)
        p.iconst(12, 0x800)
        p.iop(2, 12, "+", 2)
    p.if_(1, "GE", 12, prch, mfrq)
    from ..perc import machines as PM
    p.iconst(12, 0)
    p.float_(4, 2, 12)
    p.fconst(12, 1.0 / 2048.0)
    p.fop(4, 4, "*", 12)
    PM.exp2(p, L.perc, 4, 4)
    p.fconst(12, 4096.0 * 0x20B40 * 0xFD9FB3 / 2.0 ** 42)
    p.fop(4, 4, "*", 12)
    p.fconst(12, float(0x7FFFFF))
    p.fop(4, 4, "MIN", 12)
    p.trunc(4, 4)
    C.vws(p, "i2", 4)


def phases(p: Prog, L: C.Layout) -> None:
    """192 of each phase into XB (the one the wave reads) and YB."""
    W = L.W
    p.iconst(12, L.XB)
    p.seti(5, 12)
    p.iconst(12, L.YB)
    p.seti(2, 12)
    C.par(p, 1, 4)                              # MOD
    p.fconst(12, 0.5)

    def synced():                               # b (S_B) the note, a (S_A) the second, reset at b's wrap
        def one():
            C.st(p, 1, S_B)
            p.ld(2, W["x0"])
            p.ipass(12, 1)
            p.iop(1, 12, "+", 2)
            C.st(p, 3, S_A)
            p.ld(2, W["minc"])
            p.ipass(12, 3)
            p.iop(3, 12, "+", 2)
            p.iconst(12, M24)

            def wrapped():
                p.iop(1, 1, "AND", 12)
                p.iconst(3, 0)
            p.if_(1, "GT", 12, wrapped, kind="i")
            p.iconst(12, M24)
            p.iop(3, 3, "AND", 12)
            C.sts(p, S_B, 1)
            C.sts(p, S_A, 3)
            p.stpost(2, 1)
            p.stpost(5, 3)
        p.loop(W["n4"], 192, one)

    def free():                                 # a the note, b the second
        def one():
            C.st(p, 1, S_B)
            C.st(p, 3, S_A)
            p.stpost(2, 1)
            p.stpost(5, 3)
            p.ld(2, W["minc"])
            p.ipass(12, 1)
            p.iop(1, 12, "+", 2)
            p.ld(2, W["x0"])
            p.ipass(12, 3)
            p.iop(3, 12, "+", 2)
            p.iconst(12, M24)
            p.iop(1, 1, "AND", 12)
            p.iop(3, 3, "AND", 12)
            C.sts(p, S_B, 1)
            C.sts(p, S_A, 3)
        p.loop(W["n4"], 192, one)
    p.if_(1, "GE", 12, synced, free)


def wave_(p: Prog, L: C.Layout) -> None:
    """XB, YB -> IN (floats)."""
    W = L.W
    p.iconst(12, L.IN)
    p.seti(5, 12)
    p.iconst(12, L.XB)
    p.seti(1, 12)
    C.knob(p, 1, 4)                             # MOD's knob: bit 5 (0x200000 of its word) = RING, R+S
    p.iconst(12, 32)
    p.iop(1, 1, "AND", 12)

    def ring():                                 # IN[i] = |X[i] Y[max(i - 2, 0)]| (the 56300's pipeline)
        p.iconst(12, L.YB)
        p.seti(2, 12)

        def one():
            p.ldpost(3, 1)
            _q23(p, 3, 3)
            p.ldi(4, 0, 2)
            _q23(p, 4, 4)
            p.fop(3, 3, "*", 4)
            _abs(p, 3)
            C.sat(p, 3)
            p.stpost(5, 3)
            p.ld(0, W["n4"])
            p.iconst(12, 190)
            p.if_(0, "LE", 12, lambda: p.ldpost(13, 2), kind="i")
        p.loop(W["n4"], 192, one)

    def plain():
        C.par(p, 1, 3)                          # WAVE
        p.fconst(12, 0x199999 * C.Q23)
        p.if_(1, "LT", 12, lambda: _tri(p, L), lambda: (
            p.fconst(12, 0x333333 * C.Q23),
            p.if_(1, "LT", 12, lambda: _saw(p, L), lambda: (
                p.fconst(12, 0x4CCCCC * C.Q23),
                p.if_(1, "LT", 12, lambda: _puls(p, L), lambda: (
                    p.fconst(12, 0x666666 * C.Q23),
                    p.if_(1, "LT", 12, lambda: _mix(p, L), lambda: _noise(p, L))))))))
    p.ifz(1, "NE", ring, plain)


def _abs(p: Prog, x: int) -> None:
    p.fconst(12, 0.0)
    p.fop(13, 12, "-", x)
    p.fop(x, x, "MAX", 13)


def _tri(p: Prog, L: C.Layout) -> None:
    def one():
        p.ldpost(3, 1)
        _q23(p, 3, 3)
        _abs(p, 3)
        p.fconst(12, 0.5)
        p.fop(3, 3, "-", 12)
        p.fop(3, 3, "+", 3)
        C.sat(p, 3)
        p.stpost(5, 3)
    p.loop(L.W["n4"], 192, one)


def _saw(p: Prog, L: C.Layout) -> None:
    def one():
        p.ldpost(3, 1)
        _q23(p, 3, 3)
        p.stpost(5, 3)
    p.loop(L.W["n4"], 192, one)


def _puls(p: Prog, L: C.Layout) -> None:
    W = L.W
    C.knob(p, 2, 1)                             # PWAD: the sweep += PWAD << 7 (24 bits)
    p.lsh(2, 2, 7)
    C.st(p, 3, S_PW)
    p.ipass(12, 3)
    p.iop(3, 12, "+", 2)
    p.iconst(12, M24)
    p.iop(3, 3, "AND", 12)
    C.sts(p, S_PW, 3)
    C.knob(p, 2, 0)                             # the threshold: |sweep + 2 PW << 16| (24 bits)
    p.lsh(2, 2, 17)
    p.ipass(12, 3)
    p.iop(3, 12, "+", 2)
    _q23(p, 3, 3)
    _abs(p, 3)
    C.sat(p, 3)
    p.st(W["thr"], 3)

    def one():
        p.ldpost(3, 1)
        _q23(p, 3, 3)
        p.ld(4, W["thr"])
        p.fop(3, 3, "-", 4)
        p.fconst(12, 128.0)
        p.fop(3, 3, "*", 12)
        C.sat(p, 3)
        p.stpost(5, 3)
    p.loop(W["n4"], 192, one)


def _mix(p: Prog, L: C.Layout) -> None:
    """48 rounds of four samples: T[X[4j] >> 12] twice, T[X[4j + 2] >> 12] twice, with
    j = max(round - 1, 0) (the 56300's lagging pipeline: the first pair comes twice)."""
    W = L.W
    p.iconst(12, 0)
    p.st(W["c"], 12)

    def one():
        p.ld(6, W["c"])
        p.iconst(12, 1)
        p.iop(7, 6, "-", 12)
        p.ifz(7, "LT", lambda: p.iconst(7, 0))
        p.lsh(7, 7, 4)
        p.iconst(12, L.XB)
        p.iop(7, 12, "+", 7)
        p.seti(2, 7)
        for off in (0, 2):
            p.ldi(8, off, 2)
            p.lsh(8, 8, -12)
            p.lsh(8, 8, 2)
            p.iconst(12, L.COMB)
            p.iop(8, 12, "+", 8)
            p.seti(3, 8)
            p.ldi(9, 0, 3)
            p.fconst(12, 65536.0)                 # the tables hold the words >> 16
            p.fop(9, 9, "*", 12)
            p.stpost(5, 9)
            p.stpost(5, 9)
        p.ld(6, W["c"])
        p.ipass(12, 6)
        p.iconst(13, 1)
        p.iop(6, 12, "+", 13)
        p.st(W["c"], 6)
    p.loop(W["n4"], 48, one)


def _rol(p: Prog, r: int) -> None:
    """Rr = (Rr << 1 | C) & M24, C (R3) = its old bit 23; then the taps if C (EOR leaves C).
    Clobbers R4-R6, R12."""
    p.lsh(4, r, -23)
    p.lsh(r, r, 1)
    p.ipass(12, r)
    p.iop(r, 12, "+", 3)
    p.iconst(12, M24)
    p.iop(r, r, "AND", 12)
    p.ipass(3, 4)

    def taps():
        p.iconst(5, TAPS)
        p.xor(r, r, 5, 6)
    p.ifz(3, "NE", taps)


def _noise(p: Prog, L: C.Layout) -> None:
    """The two registers clocked 48 times each, alternately, the carry passing from one to
    the other; each one's value before its clocking stored every fourth sample, where the
    second 24 rounds' stay. Then, every fourth sample, a phase that went down (a wrap) takes
    the stored value there, held for four samples."""
    W = L.W
    C.st(p, 1, S_NA)
    C.st(p, 2, S_NB)
    p.iconst(3, 0)                              # C, clear on the way in
    p.iconst(12, L.YB)
    p.seti(2, 12)

    def one():
        p.ld(0, W["n4"])
        p.iconst(12, 24)

        def keep():
            p.stpost(2, 1)
            for _ in range(3):
                p.ldpost(13, 2)
            p.stpost(2, 2)
            for _ in range(3):
                p.ldpost(13, 2)
        p.if_(0, "LE", 12, keep, kind="i")
        _rol(p, 1)
        _rol(p, 2)
    p.loop(W["n4"], 48, one)
    C.sts(p, S_NA, 1)
    C.sts(p, S_NB, 2)
    p.iconst(12, L.XB)
    p.seti(1, 12)
    p.iconst(12, L.YB)
    p.seti(2, 12)
    p.iconst(12, L.IN)
    p.seti(5, 12)

    def hold():
        p.ldi(3, 0, 1)
        _q23(p, 3, 3)                           # the phase
        C.st(p, 7, S_HX)
        _q23(p, 7, 7)                           # the last
        p.fop(4, 3, "-", 7)
        p.ldi(8, 0, 1)
        C.sts(p, S_HX, 8)

        def take():
            p.ldi(8, 0, 2)
            _q23(p, 9, 8)
            C.sts(p, S_HV, 9)
        p.fconst(12, 0.0)
        p.if_(4, "LT", 12, take)
        C.st(p, 9, S_HV)
        for _ in range(4):
            p.stpost(5, 9)
            p.ldpost(13, 1)
            p.ldpost(13, 2)
    p.loop(W["n4"], 48, hold)


def half(p: Prog, L: C.Layout) -> None:
    W = L.W
    C.vw(p, 1, "i1")
    p.st(W["x0"], 1)
    C.vw(p, 1, "i2")
    p.st(W["minc"], 1)
    phases(p, L)
    wave_(p, L)
    coefs(p, L, COEF, GAIN, 10, 6)
    p.iconst(12, L.IN)
    p.seti(5, 12)
    p.ld(14, L.md.C["mdb"])
    p.iconst(12, 4 * (K.S0 + S_DEC))
    p.iop(13, 12, "+", 14)
    p.seti(2, 13)
    dec.decimate(p, L)

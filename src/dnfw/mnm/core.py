"""The Monomachine machines' common ground on the DN2's DSP (docs/mnm.md).

They run inside PERC's voice (dnfw.md.voice): a slot's words at I3 as the Machinedrum
machines', the 44.1 kHz stream and its resampler shared. The Monomachine renders 16 frames a
block (2,756.25 blocks a second); a PERC block is 32 samples, so `render` is two of them.

Numbers. The Monomachine's DSP56303 works in 24-bit fractions; here a Q23 word is the float
w / 2^23, as for the Machinedrum (dnfw.md.core). Its phases are kept as 32-bit integers where
the 56300 keeps 48-bit ones (the fraction's low bits dropped), and its rounding (MACR) and
truncations are not reproduced bit for bit: test/test_mnm.py holds every machine to the
Monomachine's own output (its DSP code in an emulator) within a bound.

A slot's words (dnfw.md.core): W[1..8] the eight parameters, each knob / 128 (the
Monomachine's word, knob << 16, as a Q23 fraction); S0.. the machine's state; and the
voice's words below. The parameters are those of the knob positions 0..127.
"""

from __future__ import annotations

from ..md import core as K
from ..perc.dsl import Prog

Q23 = K.Q23
TOP = K.TOP
RATE = 44100.0
FRAMES = 16                                   # a Monomachine block
# the voice's own words for these machines (dnfw.md.core.VW ends at 245)
VW = dict(A=246, F=247, pre=248, pitch=249, i1=250, i2=251, i3=252)
P0 = 1                                        # W[1..8]: the parameters


def par(p: Prog, d: int, k: int) -> None:
    """Fd = parameter k (0..7) as the Monomachine's Q23 word."""
    K.w(p, d, P0 + k)


def st(p: Prog, d: int, k: int) -> None:
    K.s(p, d, k)


def sts(p: Prog, k: int, s: int) -> None:
    K.ss(p, k, s)


def vw(p: Prog, d: int, name: str) -> None:
    p.ldi(d, VW[name], 3)


def vws(p: Prog, name: str, s: int) -> None:
    p.sti(VW[name], 3, s)


def knob(p: Prog, d: int, k: int, t: int = 12) -> None:
    """Rd = parameter k's knob position (0..127), an integer."""
    par(p, d, k)
    p.fconst(t, 128.0)
    p.fop(d, d, "*", t)
    p.trunc(d, d)


def sat(p: Prog, x: int, t: int = 12) -> None:
    K.sat(p, x, t)


class Layout:
    """Where the Monomachine voices' shared buffers and tables are (DDR): IN, a render's
    internal samples (up to 192); C, the decimators' coefficients; the tables (`tables`)."""

    def __init__(self, perc, scratch: int, tables: int):
        self.perc, self.md = perc, perc.md          # PERC's layout (its EXP2, RECIP) and its MD voices'
        self.scratch, self.tables = scratch, tables
        self.IN = scratch                           # 192 floats: the decimator's input
        self.XB = scratch + 4 * 192                 # 192 ints: SID's phases
        self.YB = scratch + 4 * 384                 # 192 ints
        self.COEF = scratch + 4 * 576               # 10 floats
        self.W = {name: scratch + 4 * (592 + k) for k, name in enumerate(SC_WORDS)}
        self.COMB = tables + 4 * 33 * 512           # SID's combined waveforms (floats), after the waves


SC_WORDS = ("n4", "n5", "half", "inner", "shift", "tmp", "tmp2", "ph", "inc", "len", "hlf", "base",
            "minc", "thr", "c", "x0", "bv")

"""P-I RS: the Machinedrum's physical-model rim shot (docs/md.md), from DSP2's P-IRS and its
host scale function: P-ISD's model (pi_sd.py) with its own strike (a fixed pitch, plain
linear interpolation, x 16 HARD), the integrator's output as the modes' input, a lighter
leak (0.1), and its own mode gains."""

from __future__ import annotations

from . import core as K
from .core import ws
from .pi_sd import Q, _PI
from ..perc.dsl import Prog


class PIRS(_PI):
    """P-I RS (DSP2's P-IRS). W1 pitch, W2 DEC, W3 HARD, W4 = W5 = 0, W6 RVOL, W7 RDEC,
    W8 RING."""
    NAME, ID = "PI-RS", 69
    PNAMES = ("PTCH", "DEC", "HARD", "RING", "RVOL", "RDEC", "-", "-")
    RS = True
    TAB = "PIRS_TAB"
    START = 0x18
    CLAMP = 0x262
    PAR = 0
    GAINK = 100
    LEAK = 0x0CCCCD

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        _PI._pitch(p, L)
        _PI._q(p, 2, 1, -14)                       # DEC << 9
        _PI._q(p, 3, 2, -16, 0x80000 * Q)          # (HARD << 7) + $80000
        p.fconst(4, 0.0)
        ws(p, 4, 4)
        ws(p, 5, 4)
        _PI._sq(p, 6, 4)                           # RVOL^2 >> 5
        _PI._tq(p, L, 7, 5, 8, 292, "hostQ")       # RDEC
        _PI._sq(p, 8, 3)                           # RING^2 >> 5

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        PIRS._init(p, L)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        PIRS._trig(p, L)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        PIRS._render(p, L)


MACHINES = (PIRS,)

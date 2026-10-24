"""P-I MT: the Machinedrum's physical-model tom (docs/md.md), from DSP2's P-IMT and its
host scale function: P-I BD's model (pi_bd.py) with the excitation's pitch depth from
HARD, the delay taps scaled by SIZE, and the resonators' multipliers interpolated by TUNE
(frequency) and POS (radius, gain)."""

from __future__ import annotations

from . import core as K
from .pi_bd import MT, _host, _init, _render, _trig
from ..perc.dsl import Prog


class PIMT:
    """W1 PTCH, W2 DEC, W3 HARD, W4 HAMR, W5 TUNE, W6 POS, W7 SIZE, W8 DAMP (with SIZE)."""
    NAME, ID = "PI-MT", 66
    PNAMES = ("PTCH", "DEC", "HARD", "HAMR", "TUNE", "DAMP", "SIZE", "POS")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        _host(p, L, MT)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        _init(p, L, MT)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        _trig(p, L, MT)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        _render(p, L, MT)


MACHINES = (PIMT,)

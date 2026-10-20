"""PERC's machines (docs/perc.md), on dnfw.perc.machines' primitives.

Each machine is a SETUP (its controls from its eight parameters, into the scratch words,
with its output trim in `gain` and its variant in `fl`) and a LOOP over the block's 32
samples, shared by the machines of a family (BD/B2, XT/XC, RS/CL, CH/OH/CY, the EFMs):
the code holds one copy of each loop. The C each mirrors is rv_perc.c's perc_machine.
"""

from __future__ import annotations

import math

from .dsl import Prog
from .machines import (DT, GAIN, NAMES, R44, Layout, adv, c, coef_, coefc, cs, dec_, env_mul,
                       env_mulc, exp2, frac, noise, out, param, pc, pitch, rand_bits, recip,
                       samples, sat, sin_, svf_set, svf_tick, tick_t, v, vs)


def _gain(p: Prog, L: Layout, name: str, fl: int = 0) -> None:
    p.fconst(4, GAIN[name]); cs(p, L, "gain", 4)
    p.iconst(4, fl); cs(p, L, "fl", 4)


def _flag(p: Prog, L: Layout, then, else_=None) -> None:
    c(p, L, 0, "fl")
    p.ifz(0, "NE", then, else_)


def _mul(p: Prog, d: int, k: float) -> None:
    p.fconst(12, k); p.fop(d, d, "*", 12)


def _add(p: Prog, d: int, k: float) -> None:
    p.fconst(12, k); p.fop(d, d, "+", 12)


def _penv_freq(p: Prog, L: Layout, d: int, ramp: str, f0: str) -> None:
    """Fd = f0 (1 + ramp penv). Clobbers R5, R12."""
    v(p, d, "penv"); c(p, L, 5, ramp); p.fop(d, d, "*", 5); p.fconst(12, 1.0); p.fop(d, 12, "+", d)
    c(p, L, 5, f0); p.fop(d, 5, "*", d)


def _decoef(p: Prog, L: Layout, k: int, lo: float, hi: float, word: str) -> None:
    """word = pk_coef(pk_dec(p[k], lo, hi))."""
    param(p, L, 4, k); dec_(p, L, 5, 4, lo, hi); coef_(p, L, 6, 5); cs(p, L, word, 6)


def _drive(p: Prog, L: Layout, k: int, span: float, word: str, inv: str) -> None:
    """word = 1 + p[k] span; inv = 1 / sat(word)."""
    param(p, L, 4, k); _mul(p, 4, span); _add(p, 4, 1.0); cs(p, L, word, 4)
    sat(p, 5, 4); recip(p, 6, 5); cs(p, L, inv, 6)


# -- TRX-BD, TRX-B2 -----------------------------------------------------------------------------
def bd_setup(p: Prog, L: Layout, name: str) -> None:
    b2 = name == "TRX-B2"
    _gain(p, L, name, int(b2))
    param(p, L, 4, 0); pitch(p, L, 5, 28.0, 4, 2.4); cs(p, L, "c0", 5)                 # f0
    _decoef(p, L, 1, 0.04, 2.5, "c1")                                                   # ca
    param(p, L, 4, 2); _mul(p, 4, 5.0); cs(p, L, "c2", 4)                               # ramp
    if b2:
        coefc(p, 6, 0.035); cs(p, L, "c3", 6)
        param(p, L, 4, 3); _mul(p, 4, 0.25); cs(p, L, "c4", 4)                          # hold
        p.iconst(4, 0); cs(p, L, "c6", 4)                                               # harm 0
        param(p, L, 4, 6); cs(p, L, "c7", 4)                                            # dirt
        _mul(p, 4, -9.0); _add(p, 4, 12.0); exp2(p, L, 5, 4); cs(p, L, "c8", 5)         # q
        recip(p, 6, 5); cs(p, L, "c9", 6)                                               # 1/q
    else:
        _decoef(p, L, 3, 0.004, 0.2, "c3")                                              # cp
        p.iconst(4, 0); cs(p, L, "c4", 4); cs(p, L, "c7", 4)
        param(p, L, 4, 6); cs(p, L, "c6", 4)
    param(p, L, 4, 5); _mul(p, 4, 0.6); cs(p, L, "c5", 4)                               # nois
    _drive(p, L, 7, 9.0, "c10", "c11")


def bd_loop(p: Prog, L: Layout) -> None:
    def body():
        _penv_freq(p, L, 4, "c2", "c0"); _mul(p, 4, DT)
        adv(p, "ph0", 4)
        v(p, 4, "ph0"); sin_(p, L, 6, 4)                                    # y
        c(p, L, 7, "c6"); p.iconst(12, 0)

        def harm():
            v(p, 4, "ph0"); p.fop(4, 4, "+", 4); frac(p, 4); sin_(p, L, 8, 4); _mul(p, 8, 0.4)
            v(p, 4, "ph0"); _mul(p, 4, 3.0); frac(p, 4); sin_(p, L, 9, 4); _mul(p, 9, 0.25)
            p.fop(8, 8, "+", 9); c(p, L, 7, "c6"); p.fop(8, 7, "*", 8); p.fop(6, 6, "+", 8)
        p.if_(7, "GT", 12, harm)
        v(p, 4, "t"); p.fconst(12, 0.004)

        def click():
            _mul(p, 4, 250.0); p.fconst(12, 1.0); p.fop(4, 12, "-", 4)
            param(p, L, 5, 4); p.fop(4, 5, "*", 4)
            _flag(p, L, lambda: (noise(p, 5), _mul(p, 5, 0.6), _add(p, 5, 0.8)),
                  lambda: p.fconst(5, 1.2))
            p.fop(4, 4, "*", 5); p.fop(6, 6, "+", 4)
        p.if_(4, "LT", 12, click)
        noise(p, 4); c(p, L, 5, "c5"); p.fop(4, 4, "*", 5); v(p, 5, "nenv"); p.fop(4, 4, "*", 5)
        p.fop(6, 6, "+", 4)
        v(p, 5, "aenv"); p.fop(6, 6, "*", 5)
        c(p, L, 7, "c7"); p.iconst(12, 0)

        def dirt():
            c(p, L, 5, "c8"); p.fop(4, 6, "*", 5); _add(p, 4, 0.5)
            p.fpass(8, 4); frac(p, 8); p.fop(4, 4, "-", 8)                  # floor(y q + 0.5)
            c(p, L, 5, "c9"); p.fop(6, 4, "*", 5)
        p.if_(7, "GT", 12, dirt)
        c(p, L, 5, "c10"); p.fop(7, 6, "*", 5)                              # y drv
        _flag(p, L, lambda: (p.fop(8, 6, "*", 6), p.fconst(12, 0.15), p.fop(8, 12, "*", 8),
                             c(p, L, 5, "c10"), p.fop(8, 8, "*", 5), p.fop(7, 7, "+", 8)))
        sat(p, 9, 7); c(p, L, 5, "c11"); p.fop(9, 9, "*", 5)
        out(p, L, 9)
        c(p, L, 5, "c3"); env_mul(p, "penv", 5)
        env_mulc(p, "nenv", pc(0.9985))
        v(p, 4, "t"); c(p, L, 5, "c4")
        p.if_(4, "GE", 5, lambda: (c(p, L, 5, "c1"), env_mul(p, "aenv", 5)))
        tick_t(p)
    samples(p, L, body)


# -- TRX-SD -------------------------------------------------------------------------------------
def sd_setup(p: Prog, L: Layout, name: str) -> None:
    _gain(p, L, name)
    param(p, L, 4, 0); pitch(p, L, 5, 110.0, 4, 2.0); cs(p, L, "c0", 5)
    _decoef(p, L, 1, 0.04, 0.8, "c1")
    param(p, L, 4, 2); _mul(p, 4, 1.5); cs(p, L, "c2", 4)
    _decoef(p, L, 3, 0.003, 0.08, "c3")
    param(p, L, 4, 6); _mul(p, 4, 0.6); _add(p, 4, 1.3); cs(p, L, "c4", 4)             # tune
    _drive(p, L, 7, 8.0, "c5", "c6")
    _decoef(p, L, 1, 0.06, 0.6, "c7")
    param(p, L, 4, 5); _mul(p, 4, 3.2); exp2(p, L, 5, 4); _mul(p, 5, 1500.0)
    svf_set(p, L, 1, 5, qc=0.9)


def sd_loop(p: Prog, L: Layout) -> None:
    def body():
        _penv_freq(p, L, 4, "c2", "c0")                                    # f
        p.fconst(12, DT); p.fop(5, 4, "*", 12); adv(p, "ph0", 5)
        c(p, L, 6, "c4"); p.fop(5, 4, "*", 6); _mul(p, 5, DT); adv(p, "ph1", 5)
        v(p, 4, "ph0"); sin_(p, L, 6, 4)
        v(p, 4, "ph1"); sin_(p, L, 7, 4); _mul(p, 7, 0.55); p.fop(6, 6, "+", 7)
        v(p, 5, "aenv"); p.fop(6, 6, "*", 5); _mul(p, 6, 0.7)
        noise(p, 0); cs(p, L, "ns", 0)
        svf_tick(p, L, 1)
        _mul(p, 2, 0.7)
        c(p, L, 3, "ns"); _mul(p, 3, 0.3); p.fop(2, 2, "+", 3)
        param(p, L, 5, 4); p.fop(2, 2, "*", 5); v(p, 5, "nenv"); p.fop(2, 2, "*", 5)
        p.fop(6, 6, "+", 2)
        c(p, L, 5, "c5"); p.fop(7, 6, "*", 5); sat(p, 9, 7); c(p, L, 5, "c6"); p.fop(9, 9, "*", 5)
        out(p, L, 9)
        c(p, L, 5, "c3"); env_mul(p, "penv", 5)
        c(p, L, 5, "c1"); env_mul(p, "aenv", 5)
        c(p, L, 5, "c7"); env_mul(p, "nenv", 5)
        tick_t(p)
    samples(p, L, body)


# -- TRX-XT, TRX-XC -----------------------------------------------------------------------------
def xt_setup(p: Prog, L: Layout, name: str) -> None:
    conga = name == "TRX-XC"
    _gain(p, L, name, int(conga))
    param(p, L, 4, 0); pitch(p, L, 5, 140.0 if conga else 55.0, 4, 2.5); cs(p, L, "c0", 5)
    param(p, L, 4, 1); dec_(p, L, 5, 4, 0.05, 1.2 if conga else 2.0); cs(p, L, "c8", 5)
    coef_(p, L, 6, 5); cs(p, L, "c1", 6)                                    # ca
    param(p, L, 4, 4); _mul(p, 4, -0.85); _add(p, 4, 1.0)
    c(p, L, 5, "c8"); p.fop(5, 5, "*", 4); coef_(p, L, 6, 5); cs(p, L, "c2", 6)   # cd (DAMP)
    param(p, L, 4, 2); _mul(p, 4, 1.5); cs(p, L, "c3", 4)
    _decoef(p, L, 3, 0.005, 0.4, "c4")
    _drive(p, L, 5, 10.0, "c5", "c6")


def xt_loop(p: Prog, L: Layout) -> None:
    def body():
        _penv_freq(p, L, 4, "c3", "c0"); cs(p, L, "tmp", 4)
        p.fconst(12, DT); p.fop(5, 4, "*", 12); adv(p, "ph0", 5)
        v(p, 4, "ph0"); sin_(p, L, 6, 4)

        def conga():
            c(p, L, 4, "tmp"); p.fconst(12, 1.59 * DT); p.fop(5, 4, "*", 12); adv(p, "ph1", 5)
            v(p, 4, "ph1"); sin_(p, L, 7, 4)
            _mul(p, 7, 0.3); v(p, 5, "xenv"); p.fop(7, 7, "*", 5); p.fop(6, 6, "+", 7)
            v(p, 4, "t"); p.fconst(12, 0.003)
            p.if_(4, "LT", 12, lambda: (noise(p, 7), _mul(p, 7, 0.5), p.fop(6, 6, "+", 7)))
        _flag(p, L, conga)
        v(p, 5, "aenv"); p.fop(6, 6, "*", 5)
        c(p, L, 5, "c5"); p.fconst(12, 1.01)

        def dist():
            c(p, L, 5, "c5"); p.fop(7, 6, "*", 5); cs(p, L, "tmp", 7)
            sat(p, 9, 7); c(p, L, 5, "c6"); p.fop(9, 9, "*", 5); cs(p, L, "y", 9)
            c(p, L, 7, "tmp"); _mul(p, 7, 1.2 / (2 * math.pi))
            sin_(p, L, 8, 7, wrap=True)                                     # fm_sinf(y drv 1.2)
            c(p, L, 9, "y"); p.fop(8, 8, "-", 9); param(p, L, 5, 6); p.fop(8, 8, "*", 5)
            p.fop(6, 9, "+", 8)
        p.if_(5, "GT", 12, dist)
        out(p, L, 6)
        c(p, L, 5, "c4"); env_mul(p, "penv", 5)
        v(p, 4, "aenv"); p.fconst(12, 0.3)
        p.if_(4, "GT", 12, lambda: c(p, L, 5, "c1"), lambda: c(p, L, 5, "c2"))
        p.fop(4, 4, "*", 5); vs(p, "aenv", 4)
        _flag(p, L, lambda: env_mulc(p, "xenv", pc(0.9992)))
        tick_t(p)
    samples(p, L, body)


# -- TRX-CP -------------------------------------------------------------------------------------
def cp_setup(p: Prog, L: Layout, name: str) -> None:
    _gain(p, L, name)
    param(p, L, 4, 0); _mul(p, 4, 5.0); p.trunc(4, 4)
    p.iconst(12, 2); p.iop(4, 12, "+", 4); cs(p, L, "c0", 4)                      # claps (int)
    param(p, L, 4, 4); dec_(p, L, 5, 4, 0.004, 0.03); cs(p, L, "c1", 5)           # rate
    _decoef(p, L, 6, 0.05, 0.8, "c2")                                             # rdec
    param(p, L, 4, 2); _mul(p, 4, -0.008); _add(p, 4, 0.012)
    coef_(p, L, 6, 4); cs(p, L, "c3", 6)                                          # cc
    coefc(p, 6, 0.12); cs(p, L, "c4", 6)                                          # cl
    param(p, L, 4, 1); _mul(p, 4, 2.0); exp2(p, L, 5, 4); _mul(p, 5, 700.0)
    param(p, L, 6, 3); _mul(p, 6, -2.4); _add(p, 6, 3.0)
    svf_set(p, L, 1, 5, q=6)
    param(p, L, 4, 7); _mul(p, 4, 4.0); exp2(p, L, 5, 4); _mul(p, 5, 500.0)
    svf_set(p, L, 2, 5, qc=0.8)


def cp_loop(p: Prog, L: Layout) -> None:
    def body():
        noise(p, 4); cs(p, L, "ns", 4)
        v(p, 4, "cnt"); c(p, L, 5, "c0")

        def maybe():
            v(p, 6, "t"); v(p, 7, "next")

            def clap():
                v(p, 4, "cnt"); p.iconst(12, 1); p.iop(4, 12, "+", 4); vs(p, "cnt", 4)
                noise(p, 8); _mul(p, 8, 0.5); p.fop(8, 8, "+", 12)
                _mul(p, 8, 0.4); p.fconst(12, 0.8); p.fop(8, 12, "+", 8)
                c(p, L, 9, "c1"); p.fop(8, 9, "*", 8); v(p, 6, "t"); p.fop(8, 6, "+", 8); vs(p, "next", 8)
                c(p, L, 5, "c0"); v(p, 4, "cnt")
                p.if_(4, "EQ", 5, lambda: p.fconst(9, 1.0), lambda: p.fconst(9, 0.8), kind="i")
                vs(p, "aenv", 9)
            p.if_(6, "GE", 7, clap)
        p.if_(4, "LT", 5, maybe, kind="i")
        c(p, L, 0, "ns"); svf_tick(p, L, 1)
        v(p, 5, "aenv"); p.fop(6, 2, "*", 5)
        c(p, L, 0, "ns"); svf_tick(p, L, 2)
        param(p, L, 5, 5); p.fop(2, 2, "*", 5); v(p, 5, "nenv"); p.fop(2, 2, "*", 5)
        _mul(p, 2, 0.6); p.fop(6, 6, "+", 2)
        _mul(p, 6, 1.4)
        out(p, L, 6)
        v(p, 4, "cnt"); c(p, L, 5, "c0")
        p.if_(4, "EQ", 5, lambda: c(p, L, 6, "c4"), lambda: c(p, L, 6, "c3"), kind="i")
        env_mul(p, "aenv", 6)
        v(p, 4, "cnt"); p.iconst(5, 1)
        p.if_(4, "GE", 5, lambda: (c(p, L, 6, "c2"), env_mul(p, "nenv", 6)), kind="i")
        tick_t(p)
    samples(p, L, body)


# -- TRX-RS, TRX-CL -----------------------------------------------------------------------------
def rs_setup(p: Prog, L: Layout, name: str) -> None:
    cl = name == "TRX-CL"
    _gain(p, L, name)
    param(p, L, 4, 0); pitch(p, L, 5, 1300.0 if cl else 420.0, 4, 2.0, centre=0.5)
    _mul(p, 5, DT); cs(p, L, "c0", 5)                                         # inc0
    if cl:
        param(p, L, 4, 4); _mul(p, 4, 2.0); _add(p, 4, 1.5)
    else:
        p.fconst(4, 2.27)
    p.fop(5, 5, "*", 4); cs(p, L, "c1", 5)                                     # inc1
    _decoef(p, L, 1, 0.008, 0.25 if cl else 0.15, "c2")
    if cl:
        p.fconst(4, 1.0); cs(p, L, "c3", 4); sat(p, 5, 4); recip(p, 6, 5); cs(p, L, "c4", 6)
        param(p, L, 4, 2); cs(p, L, "c5", 4)                                   # dual
        param(p, L, 4, 3); cs(p, L, "c6", 4)                                   # enh
        param(p, L, 4, 5); cs(p, L, "c7", 4)                                   # clic
    else:
        _drive(p, L, 2, 10.0, "c3", "c4")
        p.iconst(4, 0); cs(p, L, "c5", 4)
        p.fconst(4, 0.6); cs(p, L, "c6", 4); cs(p, L, "c7", 4)


def rs_loop(p: Prog, L: Layout) -> None:
    def body():
        c(p, L, 5, "c0"); adv(p, "ph0", 5)
        c(p, L, 5, "c1"); adv(p, "ph1", 5)
        v(p, 4, "ph0"); sin_(p, L, 6, 4)
        v(p, 4, "ph1"); sin_(p, L, 7, 4); c(p, L, 5, "c6"); p.fop(7, 5, "*", 7); p.fop(6, 6, "+", 7)
        v(p, 5, "aenv"); p.fop(6, 6, "*", 5)
        v(p, 4, "t"); p.fconst(12, 0.0015)
        p.if_(4, "LT", 12, lambda: (noise(p, 7), _mul(p, 7, 0.5), _add(p, 7, 0.7), c(p, L, 5, "c7"),
                                    p.fop(7, 5, "*", 7), p.fop(6, 6, "+", 7)))
        c(p, L, 5, "c5"); p.iconst(12, 0)

        def dual():
            v(p, 4, "t"); p.fconst(12, 0.012)

            def win():
                p.fconst(12, 0.0125)
                p.if_(4, "LT", 12, lambda: (v(p, 7, "aenv"), c(p, L, 5, "c5"),
                                            p.fop(7, 7, "MAX", 5), vs(p, "aenv", 7)))
            p.if_(4, "GT", 12, win)
        p.if_(5, "GT", 12, dual)
        c(p, L, 5, "c3"); p.fop(7, 6, "*", 5); sat(p, 9, 7); c(p, L, 5, "c4"); p.fop(9, 9, "*", 5)
        out(p, L, 9)
        c(p, L, 5, "c2"); env_mul(p, "aenv", 5)
        tick_t(p)
    samples(p, L, body)


# -- TRX-CB -------------------------------------------------------------------------------------
def cb_setup(p: Prog, L: Layout, name: str) -> None:
    _gain(p, L, name)
    param(p, L, 4, 0); pitch(p, L, 5, 560.0, 4, 2.0, centre=0.5); cs(p, L, "c0", 5)
    param(p, L, 4, 1); dec_(p, L, 5, 4, 0.03, 1.0); cs(p, L, "c8", 5)
    _mul(p, 5, 0.25); coef_(p, L, 6, 5); cs(p, L, "c1", 6)                       # ca
    param(p, L, 4, 3); _mul(p, 4, -0.9); _add(p, 4, 1.0)
    c(p, L, 5, "c8"); p.fop(5, 5, "*", 4); coef_(p, L, 6, 5); cs(p, L, "c2", 6)   # ct
    param(p, L, 4, 5); _mul(p, 4, 0.5); cs(p, L, "c3", 4)                         # bump
    param(p, L, 4, 4); _mul(p, 4, 2.0); exp2(p, L, 5, 4); _mul(p, 5, 900.0)
    svf_set(p, L, 1, 5, qc=1.6)


def _square(p: Prog, ph: str, acc: int) -> None:
    """Facc += +1 below half a turn of state[ph], -1 above."""
    v(p, 4, ph); p.fconst(12, 0.5)
    p.if_(4, "LT", 12, lambda: (p.fconst(12, 1.0), p.fop(acc, acc, "+", 12)),
          lambda: (p.fconst(12, 1.0), p.fop(acc, acc, "-", 12)))


def cb_loop(p: Prog, L: Layout) -> None:
    def body():
        _penv_freq(p, L, 4, "c3", "c0"); _mul(p, 4, DT); cs(p, L, "tmp", 4)
        adv(p, "ph0", 4)
        c(p, L, 4, "tmp"); _mul(p, 4, 1.48); adv(p, "ph1", 4)
        p.iconst(0, 0)
        _square(p, "ph0", 0)
        _square(p, "ph1", 0)
        svf_tick(p, L, 1)
        param(p, L, 5, 2); p.fconst(12, -0.5); p.fop(6, 5, "*", 12); _add(p, 6, 1.0)
        v(p, 7, "aenv"); p.fop(6, 7, "*", 6)
        v(p, 7, "nenv"); p.fop(7, 7, "*", 5); p.fop(6, 6, "+", 7)            # ENH: the longer tail
        p.fop(6, 2, "*", 6); _mul(p, 6, 0.6)
        out(p, L, 6)
        c(p, L, 5, "c1"); env_mul(p, "aenv", 5)
        c(p, L, 5, "c2"); env_mul(p, "nenv", 5)
        env_mulc(p, "penv", pc(0.997))
        tick_t(p)
    samples(p, L, body)


# -- TRX-CH, TRX-OH, TRX-CY ---------------------------------------------------------------------
METAL = (1.0, 1.483, 1.801, 2.546, 2.630, 3.897)


def hh_setup(p: Prog, L: Layout, name: str) -> None:
    cy, oh = name == "TRX-CY", name == "TRX-OH"
    _gain(p, L, name, int(cy))
    if cy:
        param(p, L, 4, 4); _add(p, 4, -0.5); _mul(p, 4, -1.5)
        param(p, L, 5, 3); _add(p, 5, -0.5); p.fop(4, 4, "+", 5)
        exp2(p, L, 5, 4); _mul(p, 5, 220.0)                                   # base (SIZE, TTUN)
        param(p, L, 6, 0); _mul(p, 6, 0.3); _add(p, 6, 1.0)                   # gap
        param(p, L, 4, 0); _mul(p, 4, 0.3); _add(p, 4, 0.6); cs(p, L, "c7", 4)   # mtal
        param(p, L, 4, 2); cs(p, L, "c8", 4)                                  # top
    else:
        p.fconst(5, 330.0)
        param(p, L, 6, 0); _mul(p, 6, 0.6); _add(p, 6, 0.7)
        param(p, L, 4, 4); cs(p, L, "c7", 4)
    c(p, L, 12, "tr"); p.fop(5, 5, "*", 12); _mul(p, 5, DT)                   # base tr dt
    for k, m in enumerate(METAL):                                             # incs c0..c5
        p.fconst(12, m - 1.0); p.fop(7, 6, "*", 12); _add(p, 7, 1.0)
        p.fop(7, 5, "*", 7); cs(p, L, f"c{k}", 7)
    lo, hi = (0.2, 4.0) if cy else (0.06, 1.5) if oh else (0.01, 0.25)
    _decoef(p, L, 1, lo, hi, "c6")
    if cy:
        p.fconst(5, 3000.0)
        param(p, L, 6, 5); _mul(p, 6, 6.0); _add(p, 6, 0.7)
        svf_set(p, L, 1, 5, q=6)
        param(p, L, 4, 3); _add(p, 4, -0.5); exp2(p, L, 5, 4); _mul(p, 5, 9000.0)
    else:
        param(p, L, 4, 2); _mul(p, 4, 3.0); exp2(p, L, 5, 4); _mul(p, 5, 2000.0)
        svf_set(p, L, 1, 5, qc=0.8)
        param(p, L, 4, 3); _mul(p, 4, 2.6); exp2(p, L, 5, 4); _mul(p, 5, 3000.0)
    svf_set(p, L, 2, 5, qc=0.7)


def hh_loop(p: Prog, L: Layout) -> None:
    def body():
        p.iconst(6, 0)
        for k in range(6):
            c(p, L, 5, f"c{k}"); adv(p, f"ph{k}", 5)
            _square(p, f"ph{k}", 6)
        noise(p, 7)
        _mul(p, 6, 1.0 / 6.0); c(p, L, 5, "c7"); p.fop(6, 6, "*", 5)
        _mul(p, 5, -0.7); _add(p, 5, 1.0)
        p.fop(7, 7, "*", 5); p.fop(0, 6, "+", 7)
        svf_tick(p, L, 1, hp=True)
        _flag(p, L, lambda: (c(p, L, 5, "c8"), p.fop(3, 3, "*", 5), p.fconst(12, 1.0), p.fop(5, 12, "-", 5),
                             p.fop(2, 2, "*", 5), p.fop(0, 2, "+", 3)),
              lambda: p.fpass(0, 3))
        svf_tick(p, L, 2)
        v(p, 5, "aenv"); p.fop(6, 1, "*", 5); _mul(p, 6, 1.3)
        out(p, L, 6)
        c(p, L, 5, "c6"); env_mul(p, "aenv", 5)
        tick_t(p)
    samples(p, L, body)


# -- TRX-MA -------------------------------------------------------------------------------------
def ma_setup(p: Prog, L: Layout, name: str) -> None:
    _gain(p, L, name)
    param(p, L, 4, 0); dec_(p, L, 5, 4, 0.001, 0.1); cs(p, L, "c0", 5)          # att
    recip(p, 6, 5); cs(p, L, "c1", 6)                                           # 1/att
    _decoef(p, L, 1, 0.01, 0.5, "c2")                                           # the decay
    param(p, L, 4, 3); _mul(p, 4, 200.0); p.trunc(4, 4); cs(p, L, "c3", 4)      # DAMP x 200
    param(p, L, 4, 4); _mul(p, 4, 40.0); p.trunc(4, 4); cs(p, L, "c4", 4)       # RATL x 40
    param(p, L, 4, 6); _mul(p, 4, 2.5); exp2(p, L, 5, 4); _mul(p, 5, 2500.0)
    param(p, L, 6, 7); _mul(p, 6, 3.0); _add(p, 6, 1.0)
    svf_set(p, L, 1, 5, q=6)
    param(p, L, 4, 5); _mul(p, 4, 3.0); exp2(p, L, 5, 4); _mul(p, 5, 1500.0)
    svf_set(p, L, 2, 5, qc=6.0)


def ma_loop(p: Prog, L: Layout) -> None:
    def body():
        v(p, 4, "t"); c(p, L, 5, "c0")

        def attack():
            c(p, L, 5, "c1"); p.fop(6, 4, "*", 5)
            param(p, L, 5, 2); p.fconst(12, 0.5)
            p.if_(5, "GT", 12, lambda: p.fop(6, 6, "*", 6))

        def decay():
            v(p, 6, "menv"); param(p, L, 5, 2); _mul(p, 5, -0.5); _add(p, 5, 1.0); p.fop(6, 6, "*", 5)
            c(p, L, 5, "c2"); env_mul(p, "menv", 5)
        p.if_(4, "LT", 5, attack, decay)
        cs(p, L, "m", 6)                                                       # e
        noise(p, 4); cs(p, L, "ns", 4)
        c(p, L, 5, "c3"); p.iconst(12, 0)

        def damp():
            rand_bits(p, 4); p.iconst(12, 255); p.iop(4, 4, "AND", 12); c(p, L, 5, "c3")
            p.if_(4, "LT", 5, lambda: (c(p, L, 6, "ns"), _mul(p, 6, 0.1), cs(p, L, "ns", 6)), kind="i")
        p.if_(5, "GT", 12, damp, kind="i")
        c(p, L, 0, "ns"); svf_tick(p, L, 1, hp=True)
        c(p, L, 5, "m"); p.fop(6, 3, "*", 5); cs(p, L, "y", 6)
        rand_bits(p, 4); p.iconst(12, 1023); p.iop(4, 4, "AND", 12); c(p, L, 5, "c4")
        p.if_(4, "LT", 5, lambda: (p.fconst(6, 1.0), vs(p, "xenv", 6)), kind="i")
        noise(p, 0); v(p, 5, "xenv"); p.fop(0, 0, "*", 5)
        svf_tick(p, L, 2)
        param(p, L, 5, 4); p.fop(2, 2, "*", 5); c(p, L, 5, "m"); p.fop(2, 2, "*", 5)
        _mul(p, 2, 0.8); c(p, L, 6, "y"); p.fop(6, 6, "+", 2)
        env_mulc(p, "xenv", pc(0.993))
        _mul(p, 6, 1.2)
        out(p, L, 6)
        c(p, L, 5, "m"); vs(p, "aenv", 5)
        tick_t(p)
    samples(p, L, body)


# -- EFM: a carrier and a modulator, the modulator feeding back on itself ----------------------
EFM_LO = {"EFM-BD": 28.0, "EFM-SD": 90.0, "EFM-XT": 55.0, "EFM-CP": 200.0, "EFM-RS": 200.0,
          "EFM-CB": 300.0, "EFM-HH": 400.0, "EFM-CY": 300.0}
EFM_DEC = {"EFM-BD": 2.5, "EFM-SD": 0.8, "EFM-XT": 2.0, "EFM-CP": 0.6, "EFM-RS": 0.4,
           "EFM-CB": 1.2, "EFM-HH": 1.5, "EFM-CY": 4.0}
# controls: c0 f0, c1 ca, c2 ramp, c3 cp, c4 modd, c5 ratio, c6 cm, c7 fb, c8 hpf, c9 nois,
# c10 cn, c11 clic, c12 trem, c13 tfrq, c14 snar, c15 sptc dt, c16 cs, c17 smod, c18 claps,
# c19 cdec; fl: 1 CP, 2 the carrier's own feedback, 4 HH's high-pass


def efm_setup(p: Prog, L: Layout, name: str) -> None:
    p.iconst(4, 0)
    for w in ("c2", "c7", "c8", "c9", "c11", "c12", "c13", "c14", "c15", "c17", "c19"):
        cs(p, L, w, 4)
    p.fconst(4, 1.0)
    for w in ("c3", "c10", "c16"):
        cs(p, L, w, 4)
    p.iconst(4, 1); cs(p, L, "c18", 4)
    param(p, L, 4, 0); pitch(p, L, 5, EFM_LO[name], 4, 3.0); cs(p, L, "c0", 5)
    _decoef(p, L, 1, 0.02, EFM_DEC[name], "c1")
    param(p, L, 4, 4); _mul(p, 4, 6.0); cs(p, L, "c4", 4)
    param(p, L, 4, 5); _mul(p, 4, 6.0); exp2(p, L, 5, 4); _mul(p, 5, 0.25); cs(p, L, "c5", 5)
    _decoef(p, L, 6, 0.003, 1.5, "c6")
    flags = 0

    def raw(k, w):
        param(p, L, 4, k); cs(p, L, w, 4)
    if name == "EFM-BD":
        param(p, L, 4, 2); _mul(p, 4, 5.0); cs(p, L, "c2", 4)
        _decoef(p, L, 3, 0.004, 0.25, "c3")
        raw(7, "c7")
    elif name == "EFM-SD":
        raw(2, "c9")
        _decoef(p, L, 3, 0.02, 0.6, "c10")
        raw(7, "c8")
    elif name == "EFM-XT":
        param(p, L, 4, 2); _mul(p, 4, 1.5); cs(p, L, "c2", 4)
        _decoef(p, L, 3, 0.005, 0.4, "c3")
        raw(7, "c11")
    elif name == "EFM-CP":
        flags |= 1
        param(p, L, 4, 2); _mul(p, 4, 6.0); p.trunc(4, 4)
        p.iconst(12, 1); p.iop(4, 12, "+", 4); cs(p, L, "c18", 4)
        param(p, L, 4, 3); dec_(p, L, 5, 4, 0.003, 0.03); _add(p, 5, 0.004); cs(p, L, "c19", 5)
        raw(7, "c8")
    elif name == "EFM-RS":
        param(p, L, 4, 2); _mul(p, 4, 6.0); cs(p, L, "c4", 4)
        raw(3, "c8"); raw(4, "c14")
        param(p, L, 4, 5); pitch(p, L, 5, 150.0, 4, 3.0); _mul(p, 5, DT); cs(p, L, "c15", 5)
        _decoef(p, L, 6, 0.01, 0.4, "c16")
        param(p, L, 4, 7); _mul(p, 4, 6.0); cs(p, L, "c17", 4)
        p.fconst(4, 1.6); cs(p, L, "c5", 4)
        coefc(p, 4, 0.02); cs(p, L, "c6", 4)
    elif name == "EFM-CB":
        flags |= 2
        raw(2, "c11"); raw(3, "c7")
    elif name == "EFM-HH":
        flags |= 2 | 4
        raw(2, "c12")
        param(p, L, 4, 3); _mul(p, 4, 7.0); exp2(p, L, 5, 4); _mul(p, 5, 2.0); cs(p, L, "c13", 5)
        raw(7, "c7")
    else:                                                                       # EFM-CY
        flags |= 2
        raw(2, "c7"); raw(3, "c8")
    _gain(p, L, name, flags)


def efm_loop(p: Prog, L: Layout) -> None:
    def flag(bit, then):
        c(p, L, 5, "fl"); p.iconst(12, bit); p.iop(5, 5, "AND", 12)
        p.ifz(5, "NE", then)

    def body():
        _penv_freq(p, L, 4, "c2", "c0"); _mul(p, 4, DT); cs(p, L, "tmp", 4)       # f dt
        c(p, L, 5, "c5"); p.fop(5, 4, "*", 5); adv(p, "ph1", 5)
        v(p, 4, "fbv"); c(p, L, 5, "c7"); p.fop(4, 5, "*", 4); _mul(p, 4, 0.5)
        v(p, 5, "ph1"); p.fop(4, 5, "+", 4); sin_(p, L, 6, 4, wrap=True)            # mo
        vs(p, "fbv", 6)
        c(p, L, 5, "tmp"); adv(p, "ph0", 5)
        c(p, L, 4, "c4"); _mul(p, 4, 0.16); v(p, 5, "menv"); p.fop(4, 4, "*", 5)
        p.fop(4, 4, "*", 6); v(p, 5, "ph0"); p.fop(4, 5, "+", 4)
        flag(2, lambda: (c(p, L, 6, "c7"), _mul(p, 6, 0.3), v(p, 7, "last"), p.fop(6, 6, "*", 7),
                         p.fop(4, 4, "+", 6)))
        sin_(p, L, 6, 4, wrap=True); vs(p, "last", 6)                                # y

        def clap():
            v(p, 4, "cnt"); c(p, L, 5, "c18")

            def maybe():
                v(p, 7, "t"); v(p, 8, "next")

                def go():
                    v(p, 4, "cnt"); p.iconst(12, 1); p.iop(4, 12, "+", 4); vs(p, "cnt", 4)
                    c(p, L, 8, "c19"); p.fop(8, 7, "+", 8); vs(p, "next", 8)
                    p.fconst(8, 1.0); vs(p, "xenv", 8)
                p.if_(7, "GE", 8, go)
            p.if_(4, "LT", 5, maybe, kind="i")
            v(p, 7, "xenv"); p.fop(6, 6, "*", 7)
            v(p, 4, "cnt"); c(p, L, 5, "c18")
            p.if_(4, "LT", 5, lambda: env_mulc(p, "xenv", pc(0.995)), kind="i")
        flag(1, clap)
        cs(p, L, "y", 6)
        c(p, L, 4, "c14"); p.iconst(12, 0)

        def snare():
            c(p, L, 5, "c15"); adv(p, "ph2", 5)
            _mul(p, 5, 2.31); adv(p, "ph3", 5)
            v(p, 4, "ph3"); sin_(p, L, 7, 4)
            c(p, L, 5, "c17"); _mul(p, 5, 0.16); p.fop(7, 5, "*", 7)
            v(p, 4, "ph2"); p.fop(4, 4, "+", 7); sin_(p, L, 8, 4, wrap=True)
            c(p, L, 5, "c14"); p.fop(8, 5, "*", 8); v(p, 5, "nenv"); p.fop(8, 8, "*", 5)
            c(p, L, 6, "y"); p.fop(6, 6, "+", 8); cs(p, L, "y", 6)
            c(p, L, 5, "c16"); env_mul(p, "nenv", 5)
        p.if_(4, "GT", 12, snare)
        noise(p, 4); cs(p, L, "ns", 4)
        c(p, L, 5, "c9"); p.iconst(12, 0)
        p.if_(5, "GT", 12, lambda: (c(p, L, 4, "ns"), c(p, L, 5, "c9"), p.fop(4, 4, "*", 5),
                                    v(p, 5, "nenv"), p.fop(4, 4, "*", 5), c(p, L, 6, "y"),
                                    p.fop(6, 6, "+", 4), cs(p, L, "y", 6),
                                    c(p, L, 5, "c10"), env_mul(p, "nenv", 5)))
        c(p, L, 5, "c11"); p.iconst(12, 0)

        def clic():
            v(p, 4, "t"); p.fconst(12, 0.002)
            p.if_(4, "LT", 12, lambda: (c(p, L, 4, "ns"), _mul(p, 4, 0.5), _add(p, 4, 0.8),
                                        c(p, L, 5, "c11"), p.fop(4, 5, "*", 4), c(p, L, 6, "y"),
                                        p.fop(6, 6, "+", 4), cs(p, L, "y", 6)))
        p.if_(5, "GT", 12, clic)
        c(p, L, 6, "y"); v(p, 5, "aenv"); p.fop(6, 6, "*", 5)
        c(p, L, 5, "c12"); p.iconst(12, 0)

        def trem():
            cs(p, L, "y", 6)
            v(p, 4, "t"); c(p, L, 5, "c13"); p.fop(4, 4, "*", 5); sin_(p, L, 7, 4, wrap=True)
            _mul(p, 7, 0.5); p.fop(7, 7, "+", 12)
            c(p, L, 5, "c12"); p.fop(7, 5, "*", 7); p.fconst(12, 1.0); p.fop(7, 12, "-", 7)
            c(p, L, 6, "y"); p.fop(6, 6, "*", 7)
        p.if_(5, "GT", 12, trem)
        flag(4, lambda: (v(p, 7, "hps2"), p.fop(8, 6, "-", 7), p.fconst(12, 1.0 - 0.75 ** R44),
                         p.fop(8, 8, "*", 12), p.fop(7, 7, "+", 8), vs(p, "hps2", 7),
                         p.fop(6, 6, "-", 7)))
        c(p, L, 5, "c8"); p.iconst(12, 0)

        def hpf():
            p.fop(7, 5, "*", 5); _mul(p, 7, 0.9)
            p.iconst(12, 0); p.fop(7, 7, "MAX", 12); p.fconst(12, 0.95); p.fop(7, 7, "MIN", 12)
            p.fconst(12, 1.0); p.fop(7, 12, "-", 7)
            v(p, 8, "hps"); p.fop(9, 6, "-", 8); p.fop(9, 9, "*", 7); p.fop(8, 8, "+", 9); vs(p, "hps", 8)
            p.fconst(12, 0.7); p.fop(9, 5, "*", 12); p.fconst(12, 0.3); p.fop(9, 12, "+", 9)
            p.fop(9, 8, "*", 9); p.fop(6, 6, "-", 9)
        p.if_(5, "GT", 12, hpf)
        out(p, L, 6)
        c(p, L, 5, "c3"); env_mul(p, "penv", 5)
        c(p, L, 5, "c6"); env_mul(p, "menv", 5)
        c(p, L, 5, "c1"); env_mul(p, "aenv", 5)
        tick_t(p)
    samples(p, L, body)


# -- GND ----------------------------------------------------------------------------------------
def sn_setup(p: Prog, L: Layout, name: str) -> None:
    _gain(p, L, name)
    param(p, L, 4, 0); pitch(p, L, 5, 30.0, 4, 7.0); _mul(p, 5, DT); cs(p, L, "c0", 5)
    _decoef(p, L, 1, 0.01, 4.0, "c1")
    param(p, L, 4, 2); _mul(p, 4, 4.0); cs(p, L, "c2", 4)
    _decoef(p, L, 3, 0.003, 0.5, "c3")


def sn_loop(p: Prog, L: Layout) -> None:
    def body():
        _penv_freq(p, L, 4, "c2", "c0"); adv(p, "ph0", 4)
        v(p, 4, "ph0"); sin_(p, L, 6, 4); v(p, 5, "aenv"); p.fop(6, 6, "*", 5)
        out(p, L, 6)
        c(p, L, 5, "c1"); env_mul(p, "aenv", 5)
        c(p, L, 5, "c3"); env_mul(p, "penv", 5)
        tick_t(p)
    samples(p, L, body)


def ns_setup(p: Prog, L: Layout, name: str) -> None:
    _gain(p, L, name)
    _decoef(p, L, 0, 0.005, 4.0, "c1")


def ns_loop(p: Prog, L: Layout) -> None:
    def body():
        noise(p, 6); v(p, 5, "aenv"); p.fop(6, 6, "*", 5); _mul(p, 6, 0.8)
        out(p, L, 6)
        c(p, L, 5, "c1"); env_mul(p, "aenv", 5)
        tick_t(p)
    samples(p, L, body)


def im_setup(p: Prog, L: Layout, name: str) -> None:
    _gain(p, L, name)
    for k, w in ((0, "c0"), (2, "c1")):
        param(p, L, 4, k); p.fop(4, 4, "*", 4); _mul(p, 4, 0.02); _add(p, 4, 0.00005); cs(p, L, w, 4)
    c(p, L, 4, "c0"); c(p, L, 5, "c1"); p.fop(5, 4, "+", 5); cs(p, L, "c2", 5)


def im_loop(p: Prog, L: Layout) -> None:
    def body():
        v(p, 4, "t"); c(p, L, 5, "c0")

        def later():
            c(p, L, 5, "c2")
            p.if_(4, "LT", 5, lambda: (param(p, L, 6, 3), p.iconst(12, 0), p.fop(6, 12, "-", 6)),
                  lambda: p.iconst(6, 0))
        p.if_(4, "LT", 5, lambda: param(p, L, 6, 1), later)
        out(p, L, 6)
        tick_t(p)
    samples(p, L, body)
    v(p, 4, "t"); c(p, L, 5, "c2")
    p.if_(4, "LT", 5, lambda: p.fconst(6, 1.0), lambda: p.iconst(6, 0))
    vs(p, "aenv", 6)


# name -> (setup, the loop it shares)
MACHINE = {
    "TRX-BD": (bd_setup, "bd"), "TRX-B2": (bd_setup, "bd"), "TRX-SD": (sd_setup, "sd"),
    "TRX-XT": (xt_setup, "xt"), "TRX-XC": (xt_setup, "xt"), "TRX-CP": (cp_setup, "cp"),
    "TRX-RS": (rs_setup, "rs"), "TRX-CL": (rs_setup, "rs"), "TRX-CB": (cb_setup, "cb"),
    "TRX-CH": (hh_setup, "hh"), "TRX-OH": (hh_setup, "hh"), "TRX-CY": (hh_setup, "hh"),
    "TRX-MA": (ma_setup, "ma"),
    **{n: (efm_setup, "efm") for n in NAMES if n.startswith("EFM")},
    "GND-SN": (sn_setup, "sn"), "GND-NS": (ns_setup, "ns"), "GND-IM": (im_setup, "im"),
}
LOOPS = {"bd": bd_loop, "sd": sd_loop, "xt": xt_loop, "cp": cp_loop, "rs": rs_loop, "cb": cb_loop,
         "hh": hh_loop, "ma": ma_loop, "efm": efm_loop, "sn": sn_loop, "ns": ns_loop, "im": im_loop}

"""PERC's drum machines, written once in the DSL (dsl.Prog): the SHARC code and its model.

The machines are the owner's own, from his Ravel firmware (github.com/De-Pattern/Ravel_FM1,
firmware/app/rv_perc.c, GPL-3.0): designs after the Elektron Machinedrum's TRX, EFM and GND
machines, built from its manual. This is that C, machine by machine, re-expressed for the
DN2's DSP (docs/perc.md):

- 48 kHz instead of 44.1 kHz: every per-sample constant is re-derived for the new rate;
- exp2, tan and sin come from tables (EXP2, TAN here; SHFT's sine) instead of libm;
- a division is a reciprocal (three Newton steps from the classic seed);
- the noise is the same xorshift32, its XORs written as (a | b) - (a & b);
- each voice owns one DSP voice slot; its eight parameters and TYPE sit on WaveTone
  records (PARAMS), read from the frame each block.

P-I (the modal machines) is not ported yet.
"""

from __future__ import annotations

import math

from . import dsl
from .dsl import Prog

RATE = 48000.0
DT = 1.0 / RATE
R44 = 44100.0 / RATE            # a per-sample constant c at 44.1 kHz is c ** R44 here
LOG2E = 1.0 / math.log(2.0)

# -- the machines, in TYPE order: the Machinedrum's own since v0.17 (dnfw.md, docs/md.md) --
from ..md import machines as _MD                                  # noqa: E402

NAMES = _MD.NAMES
N = len(NAMES)
PNAMES = {M.NAME: M.PNAMES for M in _MD.MACHINES}

# -- where the controls come from: WaveTone records (id, frame slot, value low, top) -----
# p = clamp((word >> 8) - low, 0, top) / top. TYPE spreads the 0..127 knob over the N
# machines; every record here is p-lockable and an LFO destination like any other.
TYPE_REC = (252, 38)                      # DRIF: 0..0x7f00, default 0 (TRX-BD)
PARAMS = ((238, 25, 4, 120),              # TUN1: 0x400..0x7c00, default 0x4000 (0.5)
          (242, 31, 4, 120),              # TUN2: the same
          (254, 41, 0, 127),              # HOLD: default 0x7f00
          (241, 30, 0, 127),              # LEV1: default 0x6400 (v0.12; ATK until v0.11, now FLTQ's)
          (256, 43, 0, 127),              # NLEV: default 0
          (257, 44, 0, 127),              # BASE: default 0
          (260, 47, 0, 127),              # CHAR: default 0
          (240, 29, 0, 100))              # PD1: 0..0x6400, default 0x3200 (0.5)
# the Machinedrum's track effects (Ravel's SRC_PERC_FX, rv_perc.c perc_render), page 2:
# AM depth and rate, a one-band EQ, a band filter (base, width, resonance). The same for
# every machine; all off at the records' defaults.
FX_PARAMS = ((239, 26, 0, 120),           # AMD: WAV1, 0..0x7800, default 0 (off)
             (246, 28, 0, 100),           # AMF: OFS1, 0..0x6400, default 0x3200
             (250, 34, 0, 100),           # EQF: OFS2, 0..0x6400, default 0x3200
             (244, 35, 0, 100),           # EQG: PD2, 0..0x6400, default 0x3200 (0 dB)
             (243, 32, 0, 120),           # FLTF: WAV2, 0..0x7800, default 0 (no high pass)
             (258, 45, 0, 127),           # FLTW: WDTH, 0..0x7f00, default 0x7f00 (no low pass)
             (253, 40, 0, 127))           # FLTQ: ATK, 0..0x7f00, default 0
FX_NAMES = (("AMD", "Amp Mod Depth"), ("AMF", "Amp Mod Rate"), ("EQF", "EQ Freq"),
            ("EQG", "EQ Gain"), ("FLTF", "Filter Base"), ("FLTW", "Filter Width"),
            ("FLTQ", "Filter Q"))
FRAME = 0x25C48C


def frame_offset(slot: int) -> int:
    return 168 + 2 * slot


# -- tables (DDR) ------------------------------------------------------------------------
EXP2_LO, EXP2_STEPS = -16.0, 16           # 2^x for x in -16..16, 1/16 apart (-32..32 until v0.16)
EXP2_N = int(-2 * EXP2_LO * EXP2_STEPS) + 1
TAN_TOP, TAN_N = 0.45, 512                # tan(pi u) for u = f / fs in 0..0.45


def table_exp2() -> list[float]:
    return [dsl.f32(2.0 ** (EXP2_LO + k / EXP2_STEPS)) for k in range(EXP2_N)]


def table_tan() -> list[float]:
    return [dsl.f32(math.tan(math.pi * TAN_TOP * k / TAN_N)) for k in range(TAN_N + 2)]


TABLES = (("exp2", table_exp2), ("tan", table_tan))


def tables_bytes() -> tuple[bytes, dict[str, int]]:
    import struct
    out, at = b"", {}
    for name, build in TABLES:
        at[name] = len(out)
        t = build()
        out += struct.pack("<%df" % len(t), *t)
    return out, at


# -- voice state (I2: 32 words a slot, L1) and the block's scratch (absolute) ------------
V = dict(on=0, rng=1, t=2, aenv=3, penv=4, nenv=5, menv=6, xenv=7, cnt=8, next=9, fbv=10,
         last=11, hps=12, hps2=13, ph0=14, ph1=15, ph2=16, ph3=17, ph4=18, ph5=19,
         f1a=20, f1b=21, f2a=22, f2b=23, mach=24,
         f3a=25, f3b=26, f4a=27, f4b=28, f5a=29, f5b=30, amph=31)   # the track effects' (v0.12)
STATE_WORDS = 32
SC_WORDS = ("t", "count", "out", "tr", "type", "note", "trig", "sbase",
            "p0", "p1", "p2", "p3", "p4", "p5", "p6", "p7",
            "s1k", "s1a1", "s1a2", "s1a3", "s2k", "s2a1", "s2a2", "s2a3",
            *(f"c{k}" for k in range(24)), "y", "ns", "tmp", "tmp2", "m", "gain", "fl",
            # v0.12: the track effects -- their seven controls, three filters, the block's set-up
            *(f"q{k}" for k in range(7)),
            "s3k", "s3a1", "s3a2", "s3a3", "s4k", "s4a1", "s4a2", "s4a3",
            "s5k", "s5a1", "s5a2", "s5a3", "buf", "amd", "amdt", "eqm", "fxam", "fxeq", "fxhp", "fxlp", "fxy")


class Layout:
    """Addresses the program is built for (dnfw.waverider.dsp provides them)."""

    def __init__(self, state, scratch, tables, sin, md_state=None, md_tables=None):
        self.state, self.tables, self.sin = state, tables, sin
        self.C = {w: scratch + 4 * k for k, w in enumerate(SC_WORDS)}
        _, at = tables_bytes()
        self.T = {name: tables + off for name, off in at.items()}
        # the Machinedrum voices (v0.17, docs/md.md): their words, their tables, and their
        # scratch in the words the Ravel machines' controls had (c0..c23)
        from ..md import core as MDK
        assert len(MDK.SC_WORDS) <= 24
        self.md = MDK.Layout(md_state if md_state is not None else 0, self.C["c0"],
                             md_tables if md_tables is not None else 0)


# -- primitives -----------------------------------------------------------------------------
def c(p: Prog, L: Layout, d: int, word: str) -> None:
    p.ld(d, L.C[word], word)


def cs(p: Prog, L: Layout, word: str, s: int) -> None:
    p.st(L.C[word], s, word)


def v(p: Prog, d: int, word: str) -> None:
    p.ldi(d, V[word], 2, word)


def vs(p: Prog, word: str, s: int) -> None:
    p.sti(V[word], 2, s, word)


def interp(p: Prog, d: int, x: int, base: int, top: float, scale: float) -> None:
    """Fd = table[base] at index clamp(Fx * scale, 0, top), linear. Clobbers R0-R3, R12,
    I1, Fx; d is not x."""
    p.fconst(12, scale)
    p.fop(x, x, "*", 12)
    p.iconst(12, 0)
    p.fop(x, x, "MAX", 12)
    p.fconst(12, top)
    p.fop(x, x, "MIN", 12)
    p.trunc(0, x)
    p.iconst(12, 0)
    p.float_(1, 0, 12)
    p.fop(1, x, "-", 1)
    p.lsh(0, 0, 2)
    p.iconst(12, base)
    p.iop(0, 12, "+", 0)
    p.seti(1, 0)
    p.ldi(2, 0, 1)
    p.ldi(3, 1, 1)
    p.fop(3, 3, "-", 2)
    p.fop(3, 1, "*", 3)
    p.fop(d, 2, "+", 3)


# Every heavy primitive is one leaf subroutine (Prog.call), its argument and result in F15:
# EXP2, SIN, SINW (any phase), NOISE, RECIP, SAT, COEF, and each filter's SET and TICK.

def _exp2_body(p: Prog, L: Layout) -> None:
    p.fconst(12, -EXP2_LO)
    p.fop(15, 15, "+", 12)
    interp(p, 15, 15, L.T["exp2"], float(EXP2_N - 1) - 0.001, float(EXP2_STEPS))


def _io(p: Prog, d: int, x: int | None, name: str, body) -> None:
    if x is not None and x != 15:
        p.fpass(15, x)
    p.call(name, body)
    if d != 15:
        p.fpass(d, 15)


def exp2(p: Prog, L: Layout, d: int, x: int) -> None:
    """Fd = 2^Fx (EXP2, -16..16). Clobbers R0-R3, R12, R15, I1, I12."""
    _io(p, d, x, "exp2", lambda: _exp2_body(p, L))


def frac(p: Prog, x: int) -> None:
    """Fx = x - floor(x). Clobbers R0, R1, R12."""
    p.trunc(0, x)
    p.iconst(12, 0)
    p.float_(1, 0, 12)
    p.if_(x, "LT", 1, lambda: (p.fconst(12, 1.0), p.fop(1, 1, "-", 12)))
    p.fop(x, x, "-", 1)


def sin_(p: Prog, L: Layout, d: int, ph: int, wrap: bool = False) -> None:
    """Fd = sin(2 pi Fph), SHFT's sine table (256 a turn). Fph in 0..1 unless WRAP.
    Clobbers R0-R3, R12, R15, I1, I12."""
    def body():
        if wrap:
            frac(p, 15)
        interp(p, 15, 15, L.sin, 256.0 - 0.001, 256.0)
    _io(p, d, ph, "sinw" if wrap else "sin", body)


def wrap1(p: Prog, x: int) -> None:
    """Fx -= 1 once it reaches 1 (a phase advanced by less than a turn). Clobbers R12."""
    p.fconst(12, 1.0)
    p.if_(x, "GE", 12, lambda: p.fop(x, x, "-", 12))


def _recip_inline(p: Prog, d: int, x: int, t: int) -> None:
    p.iconst(12, 0x7EF311C7)
    p.iop(d, 12, "-", x)
    for _ in range(3):
        p.fop(t, x, "*", d)
        p.fconst(12, 2.0)
        p.fop(t, 12, "-", t)
        p.fop(d, d, "*", t)


def recip(p: Prog, d: int, x: int, t: int = 13) -> None:
    """Fd = 1 / Fx (Fx > 0): the seed 0x7ef311c7 - bits, then three Newton steps.
    Clobbers R12-R15, I12."""
    def body():
        _recip_inline(p, 14, 15, 13)
        p.fpass(15, 14)
    _io(p, d, x, "recip", body)


def _noise_body(p: Prog) -> None:
    v(p, 0, "rng")
    p.lsh(1, 0, 13)
    p.xor(0, 0, 1, 12)
    p.lsh(1, 0, -17)
    p.xor(0, 0, 1, 12)
    p.lsh(1, 0, 5)
    p.xor(0, 0, 1, 12)
    vs(p, "rng", 0)


def noise(p: Prog, d: int) -> None:
    """Fd = the voice's xorshift32, as a signed fraction (xs_bi). Clobbers R0, R1, R12,
    R15, I12."""
    def body():
        _noise_body(p)
        p.iconst(12, -31)
        p.float_(15, 0, 12)
    _io(p, d, None, "noise", body)


def rand_bits(p: Prog, d: int) -> None:
    """Rd = the next xorshift32 value (xs32). Clobbers R0, R1, R12, I12."""
    p.call("bits", lambda: _noise_body(p))
    p.ipass(d, 0)


def _sat_body(p: Prog) -> None:
    def mid():
        p.fop(13, 15, "*", 15)
        p.fconst(12, 27.0)
        p.fop(14, 12, "+", 13)
        p.fop(14, 15, "*", 14)          # x (27 + x^2)
        p.fconst(12, 9.0)
        p.fop(13, 12, "*", 13)
        p.fconst(12, 27.0)
        p.fop(13, 12, "+", 13)          # 27 + 9 x^2
        _recip_inline(p, 15, 13, 0)
        p.fop(15, 14, "*", 15)
    p.fconst(12, 3.0)

    def notlo():
        p.fconst(12, -3.0)
        p.if_(15, "LT", 12, lambda: p.fconst(15, -1.0), mid)
    p.if_(15, "GT", 12, lambda: p.fconst(15, 1.0), notlo)


def sat(p: Prog, d: int, x: int) -> None:
    """Fd = rv_dsp.h sat(Fx): x (27 + x^2) / (27 + 9 x^2), +-1 beyond +-3.
    Clobbers R0, R12-R15, I12."""
    _io(p, d, x, "sat", lambda: _sat_body(p))


def dec_(p: Prog, L: Layout, d: int, x: int, lo: float, hi: float) -> None:
    """Fd = lo * 2^(Fx log2(hi / lo)) (pk_dec). Clobbers R0-R3, R12, R15, I1, I12, Fx."""
    p.fconst(12, math.log2(hi / lo))
    p.fop(x, x, "*", 12)
    exp2(p, L, d, x)
    p.fconst(12, lo)
    p.fop(d, d, "*", 12)


def _coef_body(p: Prog, L: Layout) -> None:
    p.fconst(12, 0.0005)
    p.fop(15, 15, "MAX", 12)
    _recip_inline(p, 14, 15, 13)
    p.fconst(12, -DT * LOG2E)
    p.fop(15, 14, "*", 12)
    _exp2_body(p, L)


def coef_(p: Prog, L: Layout, d: int, sec: int) -> None:
    """Fd = exp(-dt / max(Fsec, 0.0005)) (pk_coef). Clobbers R0-R3, R12-R15, I1, I12."""
    _io(p, d, sec, "coef", lambda: _coef_body(p, L))


def coefc(p: Prog, d: int, sec: float) -> None:
    """Fd = pk_coef(sec) for a constant SEC."""
    p.fconst(d, math.exp(-DT / max(sec, 0.0005)))


def pc(x: float) -> float:
    """A per-sample decay constant from rv_perc.c (44.1 kHz) at 48 kHz."""
    return x ** R44


def _svf_set_body(p: Prog, L: Layout, which: int) -> None:
    pre = f"s{which}"
    cs(p, L, f"{pre}k", 14)
    p.fconst(12, 10.0)
    p.fop(15, 15, "MAX", 12)
    p.fconst(12, RATE * 0.45)
    p.fop(15, 15, "MIN", 12)
    p.fconst(12, DT)
    p.fop(15, 15, "*", 12)
    interp(p, 13, 15, L.T["tan"], float(TAN_N), TAN_N / TAN_TOP)     # g
    c(p, L, 14, f"{pre}k")
    p.fop(14, 13, "+", 14)
    p.fop(14, 13, "*", 14)
    p.fconst(12, 1.0)
    p.fop(14, 12, "+", 14)              # 1 + g (g + k)
    _recip_inline(p, 15, 14, 0)
    cs(p, L, f"{pre}a1", 15)
    p.fop(15, 13, "*", 15)
    cs(p, L, f"{pre}a2", 15)
    p.fop(15, 13, "*", 15)
    cs(p, L, f"{pre}a3", 15)


def svf_set(p: Prog, L: Layout, which: int, hz: int, q: int | None = None, qc: float = 0.0) -> None:
    """svf_set(f{which}, Fhz, q): k = 1/q, a1 = 1/(1 + g(g + k)), a2 = g a1, a3 = g a2, with
    g = tan(pi hz dt) from TAN (hz clamped to 10 .. 0.9 nyquist). Q from Fq, or the
    constant QC. Clobbers R0-R3, R12-R15, I1, I12, Fhz, Fq."""
    if q is None:
        p.fconst(14, 1.0 / max(qc, 0.05))
    else:
        p.fconst(12, 0.05)
        p.fop(q, q, "MAX", 12)
        recip(p, 14, q)
    if hz != 15:
        p.fpass(15, hz)
    p.call(f"svfset{which}", lambda: _svf_set_body(p, L, which))


def _svf_tick_body(p: Prog, L: Layout, which: int, hp: bool) -> None:
    pre, a, b = f"s{which}", f"f{which}a", f"f{which}b"
    v(p, 12, a)                          # ic1
    v(p, 13, b)                          # ic2
    c(p, L, 14, f"{pre}a2")
    p.fop(15, 0, "-", 13)                # v3 = x - ic2
    p.fop(1, 14, "*", 12)
    p.fop(1, 13, "+", 1)                 # ic2 + a2 ic1
    c(p, L, 2, f"{pre}a1")
    p.fop(2, 2, "*", 12)                 # a1 ic1
    p.fop(14, 14, "*", 15)               # a2 v3
    p.fop(2, 2, "+", 14)                 # v1
    c(p, L, 14, f"{pre}a3")
    p.fop(14, 14, "*", 15)
    p.fop(1, 1, "+", 14)                 # v2 (low pass)
    p.fop(14, 2, "+", 2)
    p.fop(14, 14, "-", 12)
    vs(p, a, 14)                         # ic1 = 2 v1 - ic1
    p.fop(15, 1, "+", 1)
    p.fop(15, 15, "-", 13)
    vs(p, b, 15)                         # ic2 = 2 v2 - ic2
    if hp:
        c(p, L, 12, f"{pre}k")
        p.fop(3, 12, "*", 2)
        p.fop(3, 0, "-", 3)
        p.fop(3, 3, "-", 1)              # x - k v1 - v2


def svf_tick(p: Prog, L: Layout, which: int, hp: bool = False) -> None:
    """svf_tick(f{which}, F0): low pass -> F1, band pass -> F2, high pass -> F3 if HP.
    Clobbers R12-R15, I12."""
    p.call(f"svf{which}{'h' if hp else ''}", lambda: _svf_tick_body(p, L, which, hp))


def env_mul(p: Prog, word: str, creg: int, t: int = 12) -> None:
    """state[word] *= Fcreg."""
    v(p, t, word)
    p.fop(t, t, "*", creg)
    vs(p, word, t)


def env_mulc(p: Prog, word: str, k: float, t: int = 12, u: int = 13) -> None:
    v(p, t, word)
    p.fconst(u, k)
    p.fop(t, t, "*", u)
    vs(p, word, t)


def adv(p: Prog, ph: str, inc: int, t: int = 13) -> None:
    """state[ph] += Finc, wrapped below 1 (a per-sample advance under a turn)."""
    v(p, t, ph)
    p.fop(t, t, "+", inc)
    wrap1(p, t)
    vs(p, ph, t)


def tick_t(p: Prog) -> None:
    v(p, 12, "t")
    p.fconst(13, DT)
    p.fop(12, 12, "+", 13)
    vs(p, "t", 12)


def param(p: Prog, L: Layout, d: int, k: int) -> None:
    c(p, L, d, f"p{k}")


def out(p: Prog, L: Layout, y: int, name: str = "") -> None:
    """The sample, times the machine's trim (C gain), to the track buffer (I4 walks it)."""
    c(p, L, 12, "gain")
    p.fop(y, y, "*", 12)
    p.stpost(4, y)


def pitch(p: Prog, L: Layout, d: int, base: float, x: int, octs: float, centre: float = 0.0) -> None:
    """Fd = base * 2^((Fx - centre) octs) * tr. Clobbers R0-R3, R12, I1, Fx."""
    if centre:
        p.fconst(12, centre)
        p.fop(x, x, "-", 12)
    p.fconst(12, octs)
    p.fop(x, x, "*", 12)
    exp2(p, L, d, x)
    p.fconst(12, base)
    p.fop(d, d, "*", 12)
    c(p, L, 12, "tr")
    p.fop(d, d, "*", 12)


def samples(p: Prog, L: Layout, body) -> None:
    p.loop(L.C["count"], 32, body)



"""EFM: the Machinedrum's FM machines (docs/md.md), from DSP2's EFM-BD .. EFM-CY and their
host scale functions (the research's md_models.py / host_scale.py are the specification).

Numbers, beyond core.py's:
- a host word that is an integer in the firmware (a pitch, a ratio, a depth, a count) is
  an integer in W; a decay coefficient (from the host's tblD) is a Q23 float. `WF` lists a
  machine's float words.
- a phase is a 32-bit integer with the 15-bit sine index in bits 16..30 and 16 bits of
  fraction (`sine16` masks the index): an FM increment can be most of a turn, and this way
  any increment of under a turn either way is a 32-bit integer.
- the envelopes the firmware truncates every sample, E' = hi(E C), are kept exactly:
  E' = E - ceil(E (1 - C)) (`env_dec`), whose product is small and so exact enough in a
  float even where E C is not (a float cannot hold E C's fraction near full scale, and the
  truncation is what sets a slow decay's rate).
- the one-pole high-pass (onepole_hp) is a recursive sum the firmware truncates (or
  rounds) every sample; with its pole near 1 a float sum drifts, so it runs on integer
  words, with only the small products (x (1 - k), y (1 - c)) in floats (`hp`).
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .gnd import out_loop, pitch_word
from ..perc.dsl import Prog, bits

ONE_M = 1.0 - 2.0 ** -24                 # the largest float below 1
MAGIC = 1.5 * 2.0 ** 23                  # x + MAGIC - MAGIC: x rounded to an integer, ties even
Q23 = K.Q23


# -- arithmetic helpers -----------------------------------------------------------------
def ifloat(p: Prog, d: int, a: int, sc: int = 0, t: int = 12) -> None:
    """Fd = Ra * 2^sc."""
    p.iconst(t, sc)
    p.float_(d, a, t)


def ceil_i(p: Prog, d: int, y: int) -> None:
    """Rd = ceil(Fy) (Fy is changed; d != y). Clobbers R12."""
    p.trunc(d, y)
    ifloat(p, 12, d)
    p.fop(y, y, "-", 12)                       # the fraction, (-1, 1)
    p.fconst(12, ONE_M)
    p.fop(y, y, "+", 12)
    p.trunc(12, y)                             # 1 if the fraction was > 0
    p.iop(d, 12, "+", d)


def floor_i(p: Prog, d: int, y: int) -> None:
    """Rd = floor(Fy) (Fy is changed; d != y). Clobbers R12."""
    p.trunc(d, y)
    ifloat(p, 12, d)
    p.fop(y, y, "-", 12)
    p.fconst(12, ONE_M)
    p.fop(y, y, "-", 12)
    p.trunc(12, y)                             # -1 if the fraction was < 0
    p.iop(d, 12, "+", d)


def rne(p: Prog, x: int) -> None:
    """Fx = Fx rounded to an integer, ties to even (the 56300's convergent rounding), for
    |Fx| < 2^22. Clobbers R12."""
    p.fconst(12, MAGIC)
    p.fop(x, x, "+", 12)
    p.fop(x, x, "-", 12)


def to_word(p: Prog, d: int, x: int) -> None:
    """Rd = the Q23 float Fx as an integer word, rounded (Fx is changed). Clobbers R12."""
    p.fconst(12, 2.0 ** 23)
    p.fop(x, x, "*", 12)
    rne(p, x)
    p.trunc(d, x)


def env_dec(p: Prog, k: int, kd: int, a: int = 5, b: int = 9, c: int = 10) -> None:
    """S[k] = hi(mpy(C, S[k])) exactly: the Q23 envelope E (a float) becomes
    E - ceil(E D) 2^-23, D = (1 - C) 2^23 (S[kd], a float). Clobbers Ra, Rb, Rc, R12."""
    s(p, a, k)
    s(p, b, kd)
    p.fop(b, a, "*", b)
    ceil_i(p, c, b)
    ifloat(p, b, c, -23)
    p.fop(a, a, "-", b)
    ss(p, k, a)


def dec_d(p: Prog, d: int, k: int) -> None:
    """Fd = (1 - W[k]) 2^23 (W[k] a Q23 decay coefficient): env_dec's D. Clobbers R12."""
    w(p, d, k)
    p.fconst(12, 1.0)
    p.fop(d, 12, "-", d)
    p.fconst(12, 2.0 ** 23)
    p.fop(d, d, "*", 12)


def wf(p: Prog, d: int, k: int, sc: int) -> None:
    """Fd = W[k] (an integer) * 2^sc. Clobbers R12."""
    w(p, d, k)
    ifloat(p, d, d, sc)


def sine16(p: Prog, L: K.Layout, d: int, ph: int) -> None:
    """Fd = SINE[(Rph >> 16) & 0x7FFF]. Clobbers R12, R13, I1."""
    p.lsh(12, ph, -14)
    p.iconst(13, 0x1FFFC)
    p.iop(12, 12, "AND", 13)
    p.iconst(13, L.T["sine"])
    p.iop(d, 13, "+", 12)
    p.seti(1, d)
    p.ldi(d, 0, 1)


def sat_f(p: Prog, x: int) -> None:
    K.sat(p, x)


# -- the one-pole high-pass (md_models.onepole_hp) ----------------------------------------
def hp_coefs(p: Prog, k: int, ke: int, kd: int) -> None:
    """From the coefficient word W[k] = C (an integer): S[ke] = 1 - k (k = C/2 + 1/2, the
    filter's input gain as the DSP makes it) and S[kd] = 1 - C, both in Q23 floats."""
    w(p, 1, k)
    p.ash(2, 1, -1)
    p.iconst(12, 0x400000)
    p.iop(2, 12, "+", 2)                       # K = (C >> 1) + 0x400000
    p.iconst(3, 0x800000)
    p.iop(2, 3, "-", 2)
    ifloat(p, 2, 2, -23)
    ss(p, ke, 2)
    p.iop(1, 3, "-", 1)
    ifloat(p, 1, 1, -23)
    ss(p, kd, 1)


def hp(p: Prog, st: int, ke: int, kd: int, half: float | None) -> None:
    """One sample of the high-pass on the integer word R1: R2 = y (an integer word),
    F4 = y as Q23. State S[st] = hi(u[n-1]), S[st+1] = y[n-1] (integers).
      y = sat(x k - hi(u[n-1]) + c y[n-1])     u = x k
    with x k = x - x e and c y = y - y d, so y = (x - s + y) - ceil(x e + y d [- 1/2]) and
    the new state hi(x k) = x - ceil(x e). HALF: 0.5 for the rounded form (macr), None
    for the truncated (mac); 'reg' to take it from F3. Clobbers R1-R3, R5, R6, R9-R13."""
    ifloat(p, 5, 1)
    s(p, 6, ke)
    p.fop(5, 5, "*", 6)                        # x e
    s(p, 9, st + 1)
    ifloat(p, 6, 9)
    s(p, 10, kd)
    p.fop(6, 6, "*", 10)                       # y d
    p.fop(6, 5, "+", 6)
    if half == "reg":
        p.fop(6, 6, "-", 3)
    elif half:
        p.fconst(12, half)
        p.fop(6, 6, "-", 12)
    ceil_i(p, 10, 6)
    ceil_i(p, 11, 5)
    s(p, 2, st)
    p.iop(2, 1, "-", 2)
    p.iop(2, 9, "+", 2)                        # x - s + y
    p.iop(2, 2, "-", 10)
    p.iconst(12, 0x7FFFFF)
    p.iop(2, 2, "MIN", 12)
    p.iconst(12, -0x800000)
    p.iop(2, 2, "MAX", 12)
    ss(p, st + 1, 2)
    p.iop(1, 1, "-", 11)
    ss(p, st, 1)
    ifloat(p, 4, 2, -23)


# -- the FM operator pair ------------------------------------------------------------------
def pair(p: Prog, L: K.Layout, o: dict) -> None:
    """One sample of an EFM operator pair; F4 = the carrier's sine. O names state words:
      phm, phc            the phases
      fbm / fbc           the modulator's / carrier's feedback (phase units), with
      kfbm / kfbc         their gains (W 2^8, floats)
      menv, dmenv         the modulator envelope and its D (env_dec), if any
      ramp mode (ramp, dramp, P, P8, kmf): f = P + floor(ramp P / 2^20) every sample, the
                          ramp decaying (EFM-BD), inc_m = f MFRQ / 2^12 phase units
      fixed mode (incm, base, pf): the block's inc_m, f << 8 and f (a float)
      kmod                MOD / 2^12
    Leaves R14 = f << 8, F11 = f. Clobbers R1-R10, R12-R15, I1."""
    if "ramp" in o:
        s(p, 5, o["ramp"])
        s(p, 6, o["P8"])
        p.fop(6, 5, "*", 6)
        floor_i(p, 7, 6)
        s(p, 8, o["P"])
        p.iop(7, 8, "+", 7)                    # f
        ifloat(p, 11, 7)
        p.lsh(14, 7, 8)
        env_dec(p, o["ramp"], o["dramp"])
        s(p, 5, o["kmf"])
        p.fop(5, 11, "*", 5)
        p.trunc(15, 5)                         # inc_m
    else:
        s(p, 15, o["incm"])
        s(p, 14, o["base"])
        s(p, 11, o["pf"])
    # the modulator: index (phase + feedback), then phase += inc_m
    s(p, 8, o["phm"])
    idx = 8
    if "fbm" in o:
        s(p, 9, o["fbm"])
        p.iop(10, 8, "+", 9)
        idx = 10
    sine16(p, L, 4, idx)
    p.iop(8, 15, "+", 8)
    ss(p, o["phm"], 8)
    if "fbm" in o:
        s(p, 5, o["kfbm"])
        p.fop(5, 4, "*", 5)
        p.trunc(5, 5)
        ss(p, o["fbm"], 5)
    if "menv" in o:
        s(p, 5, o["menv"])
        p.fop(4, 4, "*", 5)                    # msig (not rounded: its rounding is below f's)
        env_dec(p, o["menv"], o["dmenv"])
    # the carrier: inc_c = f << 8 + round(msig f) MOD / 2^12
    p.fop(4, 4, "*", 11)
    rne(p, 4)                                  # mf
    s(p, 5, o["kmod"])
    p.fop(4, 4, "*", 5)
    p.trunc(3, 4)
    p.iop(3, 14, "+", 3)
    s(p, 8, o["phc"])
    idx = 8
    if "fbc" in o:
        s(p, 9, o["fbc"])
        p.iop(10, 8, "+", 9)
        idx = 10
    sine16(p, L, 4, idx)
    p.iop(8, 8, "+", 3)
    ss(p, o["phc"], 8)
    if "fbc" in o:
        s(p, 5, o["kfbc"])
        p.fop(5, 4, "*", 5)
        p.trunc(5, 5)
        ss(p, o["fbc"], 5)


def pair_fixed(p: Prog, o: dict, kp: int, kmf: int) -> None:
    """The block's constants of a fixed-pitch pair from the words: P = W[kp], MFRQ =
    W[kmf]. inc_m = P MFRQ / 2^12 (P MFRQ split so that each product is exact)."""
    w(p, 1, kp)
    p.lsh(2, 1, 8)
    ss(p, o["base"], 2)
    ifloat(p, 2, 1)
    ss(p, o["pf"], 2)
    # P = ph 2^12 + pl; MFRQ = m 2^7 (every MFRQ word is a multiple of 2^7)
    w(p, 3, kmf)
    p.lsh(3, 3, -7)
    ifloat(p, 3, 3)                            # m (< 2^16)
    p.lsh(5, 1, -12)
    ifloat(p, 5, 5)
    p.fop(5, 5, "*", 3)                        # ph m (exact)
    p.iconst(12, 4095)
    p.iop(6, 1, "AND", 12)
    ifloat(p, 6, 6)
    p.fop(6, 6, "*", 3)                        # pl m (< 2^28: split m)
    p.trunc(5, 5)
    p.lsh(5, 5, 7)                             # ph m 2^12 / 2^5
    # pl m / 2^5, truncated: pl m up to 2^28 in a float rounds; do it as pl (m >> 6) 2^6 +
    # pl (m & 63)
    w(p, 3, kmf)
    p.lsh(3, 3, -13)
    ifloat(p, 3, 3)
    p.iconst(12, 4095)
    p.iop(6, 1, "AND", 12)
    ifloat(p, 6, 6)
    p.fop(3, 6, "*", 3)                        # pl (m >> 6), exact
    p.trunc(3, 3)
    p.lsh(3, 3, 1)                             # * 2^6 / 2^5
    w(p, 7, kmf)
    p.lsh(7, 7, -7)
    p.iconst(12, 63)
    p.iop(7, 7, "AND", 12)
    ifloat(p, 7, 7)
    p.fop(6, 6, "*", 7)                        # pl (m & 63), exact
    p.fconst(12, 2.0 ** -5)
    p.fop(6, 6, "*", 12)
    p.trunc(6, 6)
    p.ipass(8, 5)
    p.iop(8, 8, "+", 3)
    p.iop(8, 8, "+", 6)
    ss(p, o["incm"], 8)


# -- host helpers ----------------------------------------------------------------------------
def scale_i(p: Prog, d: int, k: int, mul: int, sh: int, add: int = 0) -> None:
    """Rd = ((input k) * mul >> sh) + add (the product exact in a float)."""
    inp(p, d, k)
    ifloat(p, d, d)
    p.fconst(12, mul * 2.0 ** -sh)
    p.fop(d, d, "*", 12)
    p.trunc(d, d)
    if add:
        p.iconst(12, add)
        p.iop(d, 12, "+", d)


def decay_w(p: Prog, L: K.Layout, word: int, k: int, mul: int, sh: int, add: int) -> None:
    """W[word] = tblD[(input k * mul >> sh) + add] (a Q23 float)."""
    scale_i(p, 1, k, mul, sh, add)
    K.table_f(p, L, 4, "hostD", 1, 12)
    ws(p, word, 4)


def pitch_i(p: Prog, L: K.Layout, d: int, x: int, extra: int) -> None:
    """Rd = tblP[x & 127] << ((x >> 7) + extra). Clobbers R12-R14, I1."""
    pitch_word(p, L, d, x, extra)
    p.trunc(d, d)


def shl_w(p: Prog, word: int, k: int, n: int, mask: int | None = None) -> None:
    """W[word] = (input k << n) [& mask]."""
    inp(p, 1, k)
    p.lsh(1, 1, n)
    if mask is not None:
        p.iconst(12, mask)
        p.iop(1, 1, "AND", 12)
    ws(p, word, 1)


def mfrq_w(p: Prog, word: int, k: int, n: int = 9, least: int = 65536) -> None:
    """W[word] = max(input k << n, least)."""
    inp(p, 1, k)
    p.lsh(1, 1, n)
    p.iconst(12, least)
    p.iop(1, 1, "MAX", 12)
    ws(p, word, 1)


def const_w(p: Prog, word: int, v: int) -> None:
    p.iconst(1, v)
    ws(p, word, 1)


def amp_trig(p: Prog, k: int, add: int) -> None:
    """S[k] = sat(add + S[k]) (Q23)."""
    s(p, 1, k)
    p.fconst(12, add * Q23)
    p.fop(1, 1, "+", 12)
    p.fconst(12, K.TOP)
    p.fop(1, 1, "MIN", 12)
    ss(p, k, 1)


def zero(p: Prog, *ks: int) -> None:
    p.iconst(1, 0)
    for k in ks:
        ss(p, k, 1)


# -- EFM-BD, EFM-XT, EFM-CP: one operator pair with a pitch ramp ------------------------------
# state words (the three share them, and the pair's code)
BD = dict(phm=0, phc=1, fbm=2, ramp=3, menv=4, amp=5, P=6, P8=7, kmf=8, kmod=9, kfbm=10,
          dramp=11, dmenv=12, damp=13, hps=14, hpe=16, hpd=17, count=18, dsel=19, dc=20)


def bd_block(p: Prog) -> None:
    """The block's constants of the EFM-BD pair from W1..W8."""
    o = BD
    w(p, 1, 1)
    ss(p, o["P"], 1)
    ifloat(p, 1, 1, 3)
    ss(p, o["P8"], 1)
    wf(p, 1, 3, -12)
    ss(p, o["kmf"], 1)
    wf(p, 1, 4, -12)
    ss(p, o["kmod"], 1)
    wf(p, 1, 6, 8)
    ss(p, o["kfbm"], 1)
    dec_d(p, 1, 8)
    ss(p, o["dramp"], 1)
    dec_d(p, 1, 5)
    ss(p, o["dmenv"], 1)
    dec_d(p, 1, 2)
    ss(p, o["damp"], 1)


def bd_pair(p: Prog, L: K.Layout) -> None:
    p.call("efm_bd_pair", lambda: pair(p, L, BD))


def bd_trig(p: Prog, ph: int | None) -> None:
    """The pair's trig: phases (index PH, or W10 for EFM-XT's CLIC), feedback, ramp, mod env."""
    if ph is None:
        w(p, 1, 10)
        p.lsh(1, 1, 16)
    else:
        p.iconst(1, ph << 16)
    ss(p, BD["phm"], 1)
    ss(p, BD["phc"], 1)
    zero(p, BD["fbm"])
    wf(p, 1, 7, -23)
    ss(p, BD["ramp"], 1)
    p.fconst(1, K.TOP)
    ss(p, BD["menv"], 1)


class EFMBD:
    """EFM-BD: a 2-operator FM kick; the modulator with self-feedback, both operators
    under a decaying pitch ramp; a modulator envelope and an amplitude envelope.
    W1 pitch, W2 amp decay, W3 MFRQ, W4 MOD, W5 mod-env decay, W6 MFB, W7 ramp start,
    W8 ramp decay (W2, W5, W8 Q23 floats)."""
    NAME, ID = "EFM-BD", 32
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "MOD", "MFRQ", "MDEC", "MFB")
    WF = (2, 5, 8)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 0, 1, 5, 32)
        pitch_i(p, L, 4, 1, 1)
        ws(p, 1, 4)
        decay_w(p, L, 2, 1, 70, 12, 147)
        mfrq_w(p, 3, 5)
        shl_w(p, 4, 4, 9, 0x1FFFE00)
        decay_w(p, L, 5, 6, 82, 12, 147)
        shl_w(p, 6, 7, 9, 0x1FFFE00)
        inp(p, 1, 2)
        p.lsh(1, 1, 9)
        p.iconst(12, -0x100000)
        p.iop(1, 12, "+", 1)
        ws(p, 7, 1)
        decay_w(p, L, 8, 3, 75, 12, 147)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        zero(p, BD["amp"])

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        amp_trig(p, BD["amp"], 0x50C335)
        bd_trig(p, 0xFA0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        bd_block(p)

        def one():
            bd_pair(p, L)
            s(p, 5, BD["amp"])
            p.fop(4, 4, "*", 5)
            env_dec(p, BD["amp"], BD["damp"])
        out_loop(p, L, one)


class EFMXT:
    """EFM-XT: an FM tom: the EFM-BD pair (W1..W8 as EFM-BD's), started at the phase CLIC
    (W10), through the rounded one-pole high-pass (W9)."""
    NAME, ID = "EFM-XT", 34
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "MOD", "MFRQ", "MDEC", "CLIC")
    WF = (2, 5, 8)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 1, 0)
        p.lsh(1, 1, -6)
        pitch_i(p, L, 4, 1, 2)
        ws(p, 1, 4)
        decay_w(p, L, 2, 1, 70, 12, 147)
        mfrq_w(p, 3, 5)
        shl_w(p, 4, 4, 9, 0x1FFFE00)
        decay_w(p, L, 5, 6, 82, 12, 147)
        const_w(p, 6, 8000000)
        inp(p, 1, 2)
        p.lsh(1, 1, 9)
        p.iconst(12, -0x100000)
        p.iop(1, 12, "+", 1)
        ws(p, 7, 1)
        decay_w(p, L, 8, 3, 75, 12, 147)
        const_w(p, 9, 8250000)
        inp(p, 1, 7)
        p.lsh(1, 1, -1)
        ws(p, 10, 1)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        zero(p, BD["amp"])

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        amp_trig(p, BD["amp"], 0x400000)
        bd_trig(p, None)
        zero(p, BD["hps"], BD["hps"] + 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        bd_block(p)
        hp_coefs(p, 9, BD["hpe"], BD["hpd"])

        def one():
            bd_pair(p, L)
            s(p, 5, BD["amp"])
            p.fop(4, 4, "*", 5)
            to_word(p, 1, 4)
            env_dec(p, BD["amp"], BD["damp"])
            hp(p, BD["hps"], BD["hpe"], BD["hpd"], 0.5)
        out_loop(p, L, one)


class EFMCP:
    """EFM-CP: an FM clap: the EFM-BD pair (no ramp: W7 = W8 = 0) as a bare sine, under an
    envelope that restarts CLPS (W10) times at CDEC (W11) before the main decay (W2), then
    the truncated one-pole high-pass (W9)."""
    NAME, ID = "EFM-CP", 35
    PNAMES = ("PTCH", "DEC", "CLPS", "CDEC", "MOD", "MFRQ", "MDEC", "HPF")
    WF = (2, 5, 11)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 0, 11, 8, 64)
        pitch_i(p, L, 4, 1, 3)
        ws(p, 1, 4)
        decay_w(p, L, 2, 1, 70, 12, 147)
        mfrq_w(p, 3, 5, 7, 16384)
        shl_w(p, 4, 4, 9, 0x1FFFE00)
        decay_w(p, L, 5, 6, 82, 12, 147)
        const_w(p, 6, 8000000)
        const_w(p, 7, 0)
        p.fconst(1, 0.0)
        ws(p, 8, 1)
        inp(p, 1, 7)
        p.lsh(1, 1, 8)
        p.iconst(12, 0x7FFFFF)
        p.iop(1, 12, "-", 1)
        ws(p, 9, 1)
        inp(p, 1, 2)
        p.lsh(1, 1, -10)
        p.iconst(12, 63)
        p.iop(1, 1, "AND", 12)
        ws(p, 10, 1)
        decay_w(p, L, 11, 3, 40, 12, 70)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        zero(p, BD["amp"])

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        bd_trig(p, 0)
        p.fconst(1, 0x50C335 * Q23)
        ss(p, BD["amp"], 1)
        w(p, 1, 10)
        ss(p, BD["count"], 1)
        zero(p, BD["hps"], BD["hps"] + 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        o = BD
        bd_block(p)
        hp_coefs(p, 9, o["hpe"], o["hpd"])
        dec_d(p, 1, 11)
        ss(p, o["dc"], 1)
        s(p, 2, o["count"])                    # the block's decay: CDEC while claps remain
        p.ifz(2, "NE", lambda: (s(p, 1, o["dc"]), ss(p, o["dsel"], 1)),
              lambda: (s(p, 1, o["damp"]), ss(p, o["dsel"], 1)))

        def one():
            bd_pair(p, L)
            s(p, 5, o["amp"])
            p.fop(4, 4, "*", 5)
            to_word(p, 1, 4)
            p.ipass(7, 1)
            env_dec(p, o["amp"], o["dsel"])
            s(p, 2, o["count"])

            def claps():
                s(p, 5, o["amp"])
                p.fconst(12, 0x066666 * Q23)

                def again():
                    s(p, 2, o["count"])
                    p.iconst(12, -1)
                    p.iop(2, 12, "+", 2)
                    ss(p, o["count"], 2)
                    p.fconst(5, 0x50C335 * Q23)
                    ss(p, o["amp"], 5)
                    p.ifz(2, "EQ", lambda: (s(p, 5, o["damp"]), ss(p, o["dsel"], 5)))
                p.if_(5, "LT", 12, again)
            p.ifz(2, "NE", claps)
            p.ipass(1, 7)
            hp(p, o["hps"], o["hpe"], o["hpd"], None)
        out_loop(p, L, one)


# -- EFM-SD ----------------------------------------------------------------------------------
SD = dict(phm=0, phc=1, fbm=2, menv=4, amp=5, incm=6, base=7, pf=8, kmod=9, kfbm=10,
          dmenv=12, damp=13, nenv=21, dn=22, nlev=23, f1=24, f2=25, nhs=26, nhe=28, nhd=29,
          ohs=30, ohe=32, ohd=33)


class EFMSD:
    """EFM-SD: an FM snare: the EFM-BD pair at a fixed pitch, and high-passed Fibonacci
    noise under its own envelope, through the truncated one-pole high-pass.
    W1 pitch, W2 amp decay, W3 MFRQ, W4 MOD, W5 mod-env decay, W6 feedback (8000000),
    W7 noise level, W8 noise decay, W9 noise HP coefficient (4500000), W10 output HP."""
    NAME, ID = "EFM-SD", 33
    PNAMES = ("PTCH", "DEC", "NOIS", "NDEC", "MOD", "MFRQ", "MDEC", "HPF")
    WF = (2, 5, 8)

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 0, 5, 8, 64)
        pitch_i(p, L, 4, 1, 3)
        ws(p, 1, 4)
        decay_w(p, L, 2, 1, 70, 12, 147)
        mfrq_w(p, 3, 5)
        shl_w(p, 4, 4, 9, 0x1FFFE00)
        decay_w(p, L, 5, 6, 82, 12, 147)
        const_w(p, 6, 8000000)
        shl_w(p, 7, 2, 8, 0xFFFF00)
        decay_w(p, L, 8, 3, 50, 12, 147)
        const_w(p, 9, 4500000)
        inp(p, 1, 7)
        p.lsh(1, 1, 8)
        p.iconst(12, 0x7FFFFF)
        p.iop(1, 12, "-", 1)
        ws(p, 10, 1)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        o = SD
        zero(p, o["amp"], o["nenv"], o["f2"])
        p.iconst(1, 0x789ABC)
        ss(p, o["f1"], 1)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        o = SD
        amp_trig(p, o["amp"], 0x50C335)
        p.iconst(1, 0x1F4 << 16)
        ss(p, o["phm"], 1)
        ss(p, o["phc"], 1)
        zero(p, o["fbm"], o["nhs"], o["nhs"] + 1, o["ohs"], o["ohs"] + 1)
        p.fconst(1, K.TOP)
        ss(p, o["menv"], 1)
        ss(p, o["nenv"], 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        o = SD
        pair_fixed(p, o, 1, 3)
        wf(p, 1, 4, -12)
        ss(p, o["kmod"], 1)
        wf(p, 1, 6, 8)
        ss(p, o["kfbm"], 1)
        dec_d(p, 1, 5)
        ss(p, o["dmenv"], 1)
        dec_d(p, 1, 2)
        ss(p, o["damp"], 1)
        dec_d(p, 1, 8)
        ss(p, o["dn"], 1)
        wf(p, 1, 7, -23)
        ss(p, o["nlev"], 1)
        hp_coefs(p, 9, o["nhe"], o["nhd"])
        hp_coefs(p, 10, o["ohe"], o["ohd"])

        def one():
            K.fib(p, L, o["f1"], o["f2"], 4)
            p.ash(1, 12, -8)                   # the noise word
            hp(p, o["nhs"], o["nhe"], o["nhd"], None)
            s(p, 5, o["nenv"])
            p.fop(4, 4, "*", 5)                # noise * noise env
            s(p, 5, o["nlev"])
            p.fop(4, 4, "*", 5)
            p.sti(K.S0 + 95, 3, 4)             # (a word of scratch)
            env_dec(p, o["nenv"], o["dn"])
            pair(p, L, o)
            s(p, 5, o["amp"])
            p.fop(4, 4, "*", 5)
            p.ldi(5, K.S0 + 95, 3)
            p.fop(4, 4, "+", 5)
            K.sat(p, 4)
            to_word(p, 1, 4)
            p.ipass(7, 1)
            env_dec(p, o["amp"], o["damp"])
            p.ipass(1, 7)
            hp(p, o["ohs"], o["ohe"], o["ohd"], None)
        out_loop(p, L, one)


MACHINES = (EFMBD, EFMSD, EFMXT, EFMCP)

"""EFM: the Machinedrum's FM machines (docs/md.md), from DSP2's EFM-BD .. EFM-CY and their
host scale functions (the research's md_models.py / host_scale.py are the specification).

Every EFM operator pair feeds back on itself (the modulator, or the carrier), by up to a
whole turn: the oscillator is chaotic, and one LSB apart it is a different sound within a
few hundred samples. So the pairs are computed exactly as DSP2 computes them, in
integers: every host word is an integer in W (as the host sends it), and the 56300's
24 x 24-bit products are built from four 12 x 12-bit float products, each exact
(`xprod`: the 48-bit accumulator as two words; `xround`: hi(rnd(mpy)), convergent;
`xfloor`: a truncated product, the envelopes). A phase is two words, the 15-bit index's
integer and the accumulator's low 24 bits (`add2`, `index2`). Exactness also needs the
sine table to be DSP2's own word for word (see docs/md.md).

Outside the feedback loops (the output envelopes, the noise, the one-pole high-pass) the
arithmetic is float where a float follows the firmware closely enough:
- an envelope truncated every sample, E' = hi(E C), as E - ceil(E (1 - C)) (`env_dec`),
  whose product is small and so near exact in a float (the truncation sets a slow decay);
- the one-pole high-pass (onepole_hp), a recursive sum truncated (or rounded) every
  sample with its pole near 1, on integer words, only the small products x (1 - k) and
  y (1 - c) in floats (`hp`).
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .gnd import out_loop, pitch_word
from ..perc.dsl import Prog

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
    """Fd = 2^23 - W[k] (W[k] a decay coefficient word): env_dec's D. Clobbers R12."""
    w(p, d, k)
    p.iconst(12, 0x800000)
    p.iop(d, 12, "-", d)
    ifloat(p, d, d)


def wf(p: Prog, d: int, k: int, sc: int) -> None:
    """Fd = W[k] (an integer) * 2^sc. Clobbers R12."""
    w(p, d, k)
    ifloat(p, d, d, sc)


def sine16(p: Prog, L: K.Layout, d: int, ph: int) -> None:
    """Fd = SINE[(Rph >> 16) & 0x7FFF] (a one-word phase, 16 bits of fraction: EFM-HH's
    tremolo, whose increment is a multiple of 2^-16). Clobbers R12, R13, I1."""
    p.lsh(12, ph, -14)
    p.iconst(13, 0x1FFFC)
    p.iop(12, 12, "AND", 13)
    p.iconst(13, L.T["sine"])
    p.iop(d, 13, "+", 12)
    p.seti(1, d)
    p.ldi(d, 0, 1)


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


# -- exact products ----------------------------------------------------------------------------
# A float holds a 12-bit x 12-bit product exactly; these build the 56300's 24 x 24 products
# from four of them, in integers. Where an FM operator feeds back on itself (every EFM pair
# does, by up to a turn), the oscillator is chaotic: one LSB apart, it is a different sound
# within a few hundred samples. So the pair is computed exactly, as the firmware does.
M24 = 0xFFFFFF


def split(p: Prog, a: int, h: int, lo: int) -> None:
    """Fh = Ra >> 12, Flo = Ra & 4095 (floats; Ra >= 0). Clobbers R12."""
    p.lsh(h, a, -12)
    p.iconst(12, 4095)
    p.iop(lo, a, "AND", 12)
    p.iconst(12, 0)
    p.float_(h, h, 12)
    p.float_(lo, lo, 12)


def split_w(p: Prog, k: int, kh: int) -> None:
    """S[kh], S[kh + 1] = the halves of W[k] (an integer >= 0). Clobbers R1-R3, R12."""
    w(p, 1, k)
    split(p, 1, 2, 3)
    ss(p, kh, 2)
    ss(p, kh + 1, 3)


def xfloor(p: Prog, d: int, e: int, ch: int, cl: int, sh: int) -> None:
    """Rd = floor(Re C / 2^sh), exactly: Re a signed 24-bit integer, C = Fch 2^12 + Fcl
    (0 <= C < 2^24, halves as floats), 12 < sh <= 24. Clobbers R1-R3, R12, R13."""
    p.ash(1, e, -12)
    p.iconst(12, 4095)
    p.iop(2, e, "AND", 12)
    p.iconst(12, 0)
    p.float_(1, 1, 12)
    p.float_(2, 2, 12)
    p.fop(3, 1, "*", ch)                       # eh ch
    p.fop(1, 1, "*", cl)                       # eh cl
    p.fop(13, 2, "*", ch)                      # el ch
    p.fop(2, 2, "*", cl)                       # el cl
    for r in (3, 1, 13, 2):
        p.trunc(r, r)
    p.iop(13, 13, "+", 1)                      # m
    p.lsh(2, 2, -12)
    p.iop(13, 13, "+", 2)
    p.ash(13, 13, -(sh - 12))
    p.lsh(3, 3, 24 - sh)
    p.iop(d, 13, "+", 3)


def xprod(p: Prog, ah: int, al: int, b: int, sh: int) -> None:
    """R9:R10 = floor(A Rb / 2^sh) as (high, low 24 bits), exactly: A = Fah 2^12 + Fal
    (0 <= A < 2^24), Rb a signed 24-bit integer, 0 <= sh <= 12. With A = 2a, sh = 0 this is
    the 56300's accumulator after mpy(a, b): A1 = R9, A0 = R10. Clobbers R1-R3, R12."""
    p.ash(1, b, -12)
    p.iconst(12, 4095)
    p.iop(2, b, "AND", 12)
    p.iconst(12, 0)
    p.float_(1, 1, 12)
    p.float_(2, 2, 12)
    p.fop(9, ah, "*", 1)                       # q = ah bh
    p.fop(1, al, "*", 1)                       # al bh
    p.fop(10, ah, "*", 2)                      # ah bl
    p.fop(2, al, "*", 2)                       # n = al bl
    for r in (9, 1, 10, 2):
        p.trunc(r, r)
    p.iop(1, 10, "+", 1)                       # m (|m| < 2^25)
    p.iconst(12, (1 << (12 + sh)) - 1)
    p.iop(10, 1, "AND", 12)
    p.lsh(10, 10, 12 - sh)
    if sh:
        p.lsh(2, 2, -sh)
    p.iop(10, 10, "+", 2)
    if sh:
        p.iconst(12, (1 << sh) - 1)
        p.iop(3, 9, "AND", 12)
        p.lsh(3, 3, 24 - sh)
        p.iop(10, 10, "+", 3)
        p.ash(9, 9, -sh)
    p.ash(1, 1, -(12 + sh))
    p.iop(9, 9, "+", 1)
    p.lsh(3, 10, -24)
    p.iop(9, 9, "+", 3)
    p.iconst(12, M24)
    p.iop(10, 10, "AND", 12)


def xround(p: Prog, d: int, ah: int, al: int, b: int) -> None:
    """Rd = hi(rnd(mpy(a, Rb))) exactly, a >= 0 given as the halves of A = 2a (Fah 2^12 +
    Fal), Rb a signed 24-bit integer: round(A Rb / 2^24), a tie to even. d may be b.
    Clobbers R1-R3, R12, R13."""
    p.ash(1, b, -12)
    p.iconst(12, 4095)
    p.iop(2, b, "AND", 12)
    p.iconst(12, 0)
    p.float_(1, 1, 12)
    p.float_(2, 2, 12)
    p.fop(3, ah, "*", 1)                       # q
    p.fop(1, al, "*", 1)
    p.fop(13, ah, "*", 2)
    p.fop(2, al, "*", 2)                       # n
    for r in (3, 1, 13, 2):
        p.trunc(r, r)
    p.iop(13, 13, "+", 1)                      # m
    p.ash(1, 13, -12)
    p.iconst(12, 4095)
    p.iop(13, 13, "AND", 12)
    p.lsh(13, 13, 12)
    p.iop(13, 13, "+", 2)                      # low = (m & 4095) 2^12 + n  (< 2^25)
    p.iconst(12, 0x800000)
    p.iop(2, 13, "+", 12)
    p.lsh(2, 2, -24)
    p.ipass(12, 1)
    p.iop(1, 12, "+", 2)                       # (m >> 12) + carry
    p.ipass(12, 3)
    p.iop(d, 12, "+", 1)
    p.iconst(12, M24)
    p.iop(13, 13, "AND", 12)
    p.iconst(12, 0x800000)
    p.if_(13, "EQ", 12, lambda: (p.iconst(12, -2), p.iop(d, d, "AND", 12)), kind="i")


def ld(p: Prog, d: int, k: int, ix: int = 3) -> None:
    """Rd = state word k, through I3 (the slot) or I1 (a pair's base, C['b'])."""
    p.ldi(d, K.S0 + k, ix)


def st(p: Prog, k: int, r: int, ix: int = 3) -> None:
    p.sti(K.S0 + k, ix, r)


def rebase(p: Prog, L: K.Layout, ix: int) -> None:
    """I1 = C['b'] again (a table read takes I1). Clobbers R13."""
    if ix == 1:
        p.ld(13, L.C["b"])
        p.seti(1, 13)


def add2(p: Prog, k: int, ix: int = 3) -> None:
    """The two-word phase S[k] (whole), S[k + 1] (24-bit fraction) += R9:R10 (R10 may
    exceed 24 bits). Clobbers R3, R9-R11, R12."""
    ld(p, 11, k + 1, ix)
    p.iop(10, 10, "+", 11)
    p.lsh(3, 10, -24)
    p.iconst(12, M24)
    p.iop(10, 10, "AND", 12)
    st(p, k + 1, 10, ix)
    ld(p, 11, k, ix)
    p.iop(9, 9, "+", 11)
    p.iop(9, 9, "+", 3)
    st(p, k, 9, ix)


def index2(p: Prog, k: int, kf: int | None, ix: int = 3) -> None:
    """R2 = the sine index of the phase S[k]:S[k + 1] (+ the feedback S[kf]:S[kf + 1]).
    Clobbers R11-R13."""
    if kf is None:
        ld(p, 13, k, ix)
    else:
        ld(p, 11, k + 1, ix)
        ld(p, 13, kf + 1, ix)
        p.iop(13, 13, "+", 11)
        p.lsh(13, 13, -24)
        ld(p, 11, k, ix)
        p.iop(13, 13, "+", 11)
        ld(p, 11, kf, ix)
        p.iop(13, 13, "+", 11)
    p.iconst(12, 0x7FFF)
    p.iop(2, 13, "AND", 12)


def sine_i(p: Prog, L: K.Layout, d: int, f: int, idx: int) -> None:
    """Ff = SINE[Ridx], Rd = it as an integer word. Clobbers R12, R13, I1."""
    K.table_f(p, L, f, "sine", idx, 12)
    p.fconst(12, 2.0 ** 23)
    p.fop(d, f, "*", 12)
    p.trunc(d, d)


# -- the FM operator pair ------------------------------------------------------------------
def pair(p: Prog, L: K.Layout, o: dict, ix: int = 3) -> None:
    """One sample of an EFM operator pair, exactly as the firmware computes it; F4 = the
    carrier's sine (R7 = it as a word). O names state words (two-word values at k, k + 1:
    whole, then the 24-bit fraction, in 2^-47 accumulator units / 2^24 = sine indices),
    through I3 (IX 3) or relative to the base address in C['b'] (IX 1):
      phm, phc            the phases (two words)
      fbm, mfb / fbc, cfb the modulator's / carrier's self-feedback (two words) and the
                          halves of its gain W (fb = mpy(W, sine) >> 8)
      menv, mdec          the modulator envelope (an integer) and its decay's halves;
                          menv_shared: decayed by the caller
      ramp mode (ramp, rdec, P, Ph): f = P + floor(ramp P / 2^20) every sample, the
                          ramp decaying by rdec (EFM-BD); mfrq: the ratio's halves
      fixed mode (P, incm, f2): the block's f, inc_m (two words) and 2f's halves
      mod                 MOD's halves
    Leaves R8 = f. Clobbers R1-R3, R5-R15, I1."""
    rebase(p, L, ix)
    if "ramp" in o:
        ld(p, 7, o["ramp"], ix)
        ld(p, 5, o["Ph"], ix)
        ld(p, 6, o["Ph"] + 1, ix)
        xfloor(p, 8, 7, 5, 6, 20)
        ld(p, 11, o["P"], ix)
        p.iop(8, 11, "+", 8)                   # f
        ld(p, 5, o["rdec"], ix)
        ld(p, 6, o["rdec"] + 1, ix)
        xfloor(p, 7, 7, 5, 6, 23)
        st(p, o["ramp"], 7, ix)
        ld(p, 5, o["mfrq"], ix)
        ld(p, 6, o["mfrq"] + 1, ix)
        xprod(p, 5, 6, 8, 4)                   # inc_m = mpy(f, MFRQ) >> 5
        st(p, o["incm"], 9, ix)
        st(p, o["incm"] + 1, 10, ix)
        p.lsh(11, 8, 1)
        split(p, 11, 14, 15)
    else:
        ld(p, 8, o["P"], ix)
        ld(p, 14, o["f2"], ix)
        ld(p, 15, o["f2"] + 1, ix)
    # the modulator
    index2(p, o["phm"], o.get("fbm"), ix)
    ld(p, 9, o["incm"], ix)
    ld(p, 10, o["incm"] + 1, ix)
    add2(p, o["phm"], ix)
    sine_i(p, L, 7, 4, 2)                      # mo
    rebase(p, L, ix)
    if "fbm" in o:
        ld(p, 5, o["mfb"], ix)
        ld(p, 6, o["mfb"] + 1, ix)
        xprod(p, 5, 6, 7, 7)
        st(p, o["fbm"], 9, ix)
        st(p, o["fbm"] + 1, 10, ix)
    if "menv" in o:
        ld(p, 11, o["menv"], ix)
        p.lsh(11, 11, 1)
        split(p, 11, 5, 6)
        xround(p, 7, 5, 6, 7)                  # msig = hi(rnd(mpy(menv, mo)))
        if not o.get("menv_shared"):
            menv_dec(p, o, ix)
    # the carrier: inc_c = (mpy(mf, MOD) << 3 + f) >> 8, mf = hi(rnd(mpy(msig, f)))
    xround(p, 7, 14, 15, 7)
    ld(p, 5, o["mod"], ix)
    ld(p, 6, o["mod"] + 1, ix)
    xprod(p, 5, 6, 7, 4)
    p.iconst(12, 255)
    p.iop(3, 8, "AND", 12)
    p.lsh(3, 3, 16)
    p.iop(10, 10, "+", 3)
    p.ash(3, 8, -8)
    p.iop(9, 9, "+", 3)
    index2(p, o["phc"], o.get("fbc"), ix)
    add2(p, o["phc"], ix)
    sine_i(p, L, 7, 4, 2)                      # co
    if "fbc" in o:
        rebase(p, L, ix)
        ld(p, 5, o["cfb"], ix)
        ld(p, 6, o["cfb"] + 1, ix)
        xprod(p, 5, 6, 7, 7)
        st(p, o["fbc"], 9, ix)
        st(p, o["fbc"] + 1, 10, ix)


def pair_at(p: Prog, L: K.Layout, name: str, o: dict, base: int) -> None:
    """The pair O (offsets relative to state word BASE) as the shared subroutine NAME:
    one copy of the code for every pair laid out alike. Clobbers what pair() does."""
    p.ld(13, L.C["mdb"])
    p.iconst(12, 4 * base)
    p.iop(13, 12, "+", 13)
    p.st(L.C["b"], 13)
    p.call(name, lambda: pair(p, L, o, 1))


def menv_dec(p: Prog, o: dict, ix: int = 3) -> None:
    """menv = hi(mpy(MDEC, menv)). Clobbers R1-R3, R5, R6, R11-R13."""
    ld(p, 11, o["menv"], ix)
    ld(p, 5, o["mdec"], ix)
    ld(p, 6, o["mdec"] + 1, ix)
    xfloor(p, 11, 11, 5, 6, 23)
    st(p, o["menv"], 11, ix)


def edec(p: Prog, k: int, kd: int) -> None:
    """The integer envelope S[k] = hi(mpy(C, S[k])), C's halves at S[kd]. Clobbers R1-R3,
    R5, R6, R11-R13."""
    s(p, 11, k)
    s(p, 5, kd)
    s(p, 6, kd + 1)
    xfloor(p, 11, 11, 5, 6, 23)
    ss(p, k, 11)


def pair_fixed(p: Prog, o: dict, kp: int, kmf: int, base: int = 0) -> None:
    """A fixed-pitch pair's block constants (its words at BASE + O[.]): P = W[kp],
    inc_m = mpy(P, W[kmf]) >> 5, 2P's halves. Clobbers R1-R3, R5, R6, R8-R12."""
    w(p, 8, kp)
    ss(p, base + o["P"], 8)
    w(p, 1, kmf)
    split(p, 1, 5, 6)
    xprod(p, 5, 6, 8, 4)
    ss(p, base + o["incm"], 9)
    ss(p, base + o["incm"] + 1, 10)
    p.lsh(1, 8, 1)
    split(p, 1, 2, 3)
    ss(p, base + o["f2"], 2)
    ss(p, base + o["f2"] + 1, 3)


def phase_set(p: Prog, k: int, r: int) -> None:
    """The two-word phase S[k] = Rr (whole), fraction 0."""
    ss(p, k, r)
    p.iconst(r, 0)
    ss(p, k + 1, r)


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
    """W[word] = tblD[(input k * mul >> sh) + add] (an integer word)."""
    scale_i(p, 1, k, mul, sh, add)
    K.table_f(p, L, 4, "hostD", 1, 12)
    p.fconst(12, 2.0 ** 23)
    p.fop(4, 4, "*", 12)
    p.trunc(4, 4)
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
# state words (the three share them, and so the pair's code)
BD = dict(phm=0, phc=2, fbm=4, ramp=6, menv=7, amp=8, P=9, Ph=10, rdec=12, mfrq=14,
          mfb=16, mod=18, mdec=20, damp=22, incm=23, hps=25, hpe=27, hpd=28, count=29,
          env=30, dc=31, da=33, dsel=35)
TMP = 95                                 # a state word of scratch


def bd_block(p: Prog) -> None:
    """The block's constants of the EFM-BD pair from W1..W8."""
    o = BD
    w(p, 1, 1)
    ss(p, o["P"], 1)
    split(p, 1, 2, 3)
    ss(p, o["Ph"], 2)
    ss(p, o["Ph"] + 1, 3)
    split_w(p, 8, o["rdec"])
    split_w(p, 3, o["mfrq"])
    split_w(p, 6, o["mfb"])
    split_w(p, 4, o["mod"])
    split_w(p, 5, o["mdec"])
    dec_d(p, 1, 2)
    ss(p, o["damp"], 1)


def bd_pair(p: Prog, L: K.Layout) -> None:
    p.call("efm_bd_pair", lambda: pair(p, L, BD))


def bd_trig(p: Prog, ph: int | None) -> None:
    """The pair's trig: both phases at index PH (or W10, EFM-XT's CLIC), no feedback, the
    ramp at W7, the mod env full."""
    o = BD
    for k in (o["phm"], o["phc"]):
        if ph is None:
            w(p, 1, 10)
        else:
            p.iconst(1, ph)
        phase_set(p, k, 1)
    zero(p, o["fbm"], o["fbm"] + 1)
    w(p, 1, 7)
    ss(p, o["ramp"], 1)
    p.iconst(1, 0x7FFFFF)
    ss(p, o["menv"], 1)


def bd_host(p: Prog, L: K.Layout) -> None:
    """W2..W8 as EFM-BD and EFM-XT share them (W6 is EFM-BD's MFB)."""
    decay_w(p, L, 2, 1, 70, 12, 147)
    mfrq_w(p, 3, 5)
    shl_w(p, 4, 4, 9, 0x1FFFE00)
    decay_w(p, L, 5, 6, 82, 12, 147)
    inp(p, 1, 2)
    p.lsh(1, 1, 9)
    p.iconst(12, -0x100000)
    p.iop(1, 12, "+", 1)
    ws(p, 7, 1)
    decay_w(p, L, 8, 3, 75, 12, 147)


class EFMBD:
    """EFM-BD: a 2-operator FM kick; the modulator with self-feedback, both operators
    under a decaying pitch ramp; a modulator envelope and an amplitude envelope.
    W1 pitch, W2 amp decay, W3 MFRQ, W4 MOD, W5 mod-env decay, W6 MFB, W7 ramp start,
    W8 ramp decay."""
    NAME, ID = "EFM-BD", 32
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "MOD", "MFRQ", "MDEC", "MFB")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 0, 1, 5, 32)
        pitch_i(p, L, 4, 1, 1)
        ws(p, 1, 4)
        bd_host(p, L)
        shl_w(p, 6, 7, 9, 0x1FFFE00)

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
    """EFM-XT: an FM tom: the EFM-BD pair (W1..W8 as EFM-BD's, W6 = 8000000), started at
    the phase CLIC (W10), through the rounded one-pole high-pass (W9 = 8250000)."""
    NAME, ID = "EFM-XT", 34
    PNAMES = ("PTCH", "DEC", "RAMP", "RDEC", "MOD", "MFRQ", "MDEC", "CLIC")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 1, 0)
        p.lsh(1, 1, -6)
        pitch_i(p, L, 4, 1, 2)
        ws(p, 1, 4)
        bd_host(p, L)
        const_w(p, 6, 8000000)
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
            ss(p, TMP, 1)
            env_dec(p, BD["amp"], BD["damp"])
            s(p, 1, TMP)
            hp(p, BD["hps"], BD["hpe"], BD["hpd"], 0.5)
        out_loop(p, L, one)


class EFMCP:
    """EFM-CP: an FM clap: the EFM-BD pair (no ramp: W7 = W8 = 0) as a bare sine, under an
    envelope that restarts CLPS (W10) times at CDEC (W11) before the main decay (W2), then
    the truncated one-pole high-pass (W9)."""
    NAME, ID = "EFM-CP", 35
    PNAMES = ("PTCH", "DEC", "CLPS", "CDEC", "MOD", "MFRQ", "MDEC", "HPF")

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
        const_w(p, 8, 0)
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
        zero(p, BD["env"])

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        o = BD
        bd_trig(p, 0)
        p.iconst(1, 0x50C335)
        ss(p, o["env"], 1)
        w(p, 1, 10)
        ss(p, o["count"], 1)
        zero(p, o["hps"], o["hps"] + 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        o = BD
        bd_block(p)
        hp_coefs(p, 9, o["hpe"], o["hpd"])
        split_w(p, 11, o["dc"])
        split_w(p, 2, o["da"])

        def use(k):
            s(p, 1, k)
            ss(p, o["dsel"], 1)
            s(p, 1, k + 1)
            ss(p, o["dsel"] + 1, 1)
        s(p, 2, o["count"])                    # the block's decay: CDEC while claps remain
        p.ifz(2, "NE", lambda: use(o["dc"]), lambda: use(o["da"]))

        def one():
            bd_pair(p, L)
            s(p, 5, o["env"])
            ifloat(p, 5, 5, -23)
            p.fop(4, 4, "*", 5)
            to_word(p, 1, 4)
            ss(p, TMP, 1)
            edec(p, o["env"], o["dsel"])
            s(p, 2, o["count"])

            def claps():
                s(p, 5, o["env"])
                p.iconst(6, 0x066666)

                def again():
                    s(p, 2, o["count"])
                    p.iconst(12, -1)
                    p.iop(2, 12, "+", 2)
                    ss(p, o["count"], 2)
                    p.iconst(5, 0x50C335)
                    ss(p, o["env"], 5)
                    p.ifz(2, "EQ", lambda: use(o["da"]))
                p.if_(5, "LT", 6, again, kind="i")
            p.ifz(2, "NE", claps)
            s(p, 1, TMP)
            hp(p, o["hps"], o["hpe"], o["hpd"], None)
        out_loop(p, L, one)


# -- EFM-SD ----------------------------------------------------------------------------------
SD = dict(phm=0, phc=2, fbm=4, menv=7, amp=8, P=9, f2=10, mfb=16, mod=18, mdec=20, damp=22,
          incm=23, nenv=37, dn=38, nlev=39, f1=40, f2n=41, nhs=42, nhe=44, nhd=45, ohs=46,
          ohe=48, ohd=49)


class EFMSD:
    """EFM-SD: an FM snare: the EFM-BD pair at a fixed pitch, and high-passed Fibonacci
    noise under its own envelope, through the truncated one-pole high-pass.
    W1 pitch, W2 amp decay, W3 MFRQ, W4 MOD, W5 mod-env decay, W6 feedback (8000000),
    W7 noise level, W8 noise decay, W9 noise HP coefficient (4500000), W10 output HP."""
    NAME, ID = "EFM-SD", 33
    PNAMES = ("PTCH", "DEC", "NOIS", "NDEC", "MOD", "MFRQ", "MDEC", "HPF")

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
        zero(p, o["amp"], o["nenv"], o["f2n"])
        p.iconst(1, 0x789ABC)
        ss(p, o["f1"], 1)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        o = SD
        amp_trig(p, o["amp"], 0x50C335)
        for k in (o["phm"], o["phc"]):
            p.iconst(1, 0x1F4)
            phase_set(p, k, 1)
        zero(p, o["fbm"], o["fbm"] + 1, o["nhs"], o["nhs"] + 1, o["ohs"], o["ohs"] + 1)
        p.iconst(1, 0x7FFFFF)
        ss(p, o["menv"], 1)
        p.fconst(1, K.TOP)
        ss(p, o["nenv"], 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        o = SD
        pair_fixed(p, o, 1, 3)
        split_w(p, 6, o["mfb"])
        split_w(p, 4, o["mod"])
        split_w(p, 5, o["mdec"])
        dec_d(p, 1, 2)
        ss(p, o["damp"], 1)
        dec_d(p, 1, 8)
        ss(p, o["dn"], 1)
        wf(p, 1, 7, -23)
        ss(p, o["nlev"], 1)
        hp_coefs(p, 9, o["nhe"], o["nhd"])
        hp_coefs(p, 10, o["ohe"], o["ohd"])

        def one():
            K.fib(p, L, o["f1"], o["f2n"], 4)
            p.ash(1, 12, -8)                   # the noise word
            hp(p, o["nhs"], o["nhe"], o["nhd"], None)
            s(p, 5, o["nenv"])
            p.fop(4, 4, "*", 5)                # noise * noise env
            s(p, 5, o["nlev"])
            p.fop(4, 4, "*", 5)
            ss(p, TMP, 4)
            env_dec(p, o["nenv"], o["dn"])
            pair(p, L, o)
            s(p, 5, o["amp"])
            p.fop(4, 4, "*", 5)
            s(p, 5, TMP)
            p.fop(4, 4, "+", 5)
            K.sat(p, 4)
            to_word(p, 1, 4)
            ss(p, TMP, 1)
            env_dec(p, o["amp"], o["damp"])
            s(p, 1, TMP)
            hp(p, o["ohs"], o["ohe"], o["ohd"], None)
        out_loop(p, L, one)


# -- EFM-RS ----------------------------------------------------------------------------------
# a pair's words relative to its base (both of EFM-RS's at 0 and 20: one copy of the code)
RS_PAIR = dict(phm=0, phc=2, fbm=4, P=6, f2=7, incm=9, mfb=11, mod=13)
RS = dict(es=40, er=41, ds=42, dr=43, lvl=44, hps=45, hpe=47, hpd=48)


class EFMRS:
    """EFM-RS: an FM rimshot: two fixed-pitch pairs without modulator envelopes (snare:
    W1 pitch, W2 ratio, W3 MOD, W4 feedback; rim: W5..W8), each under its own decay (W9,
    W10); out = rim + SNAR (W11) * snare through the one-pole high-pass (W12), whose first
    two samples a block round and the rest truncate."""
    NAME, ID = "EFM-RS", 36
    PNAMES = ("PTCH", "DEC", "MOD", "HPF", "SNAR", "SPTC", "SDEC", "SMOD")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 5, 5, 8, 64)
        pitch_i(p, L, 4, 1, 3)
        ws(p, 1, 4)
        const_w(p, 2, 0x600000)
        mfrq_w(p, 3, 7)
        const_w(p, 4, 8000000)
        scale_i(p, 1, 0, 1, 5, 64)
        pitch_i(p, L, 4, 1, 4)
        ws(p, 5, 4)
        const_w(p, 6, 0x600000)
        shl_w(p, 7, 2, 7, 0x7FFF80)
        const_w(p, 8, 8000000)
        decay_w(p, L, 9, 6, 70, 12, 147)
        decay_w(p, L, 10, 1, 70, 12, 147)
        shl_w(p, 11, 4, 9, 0x1FFFE00)
        inp(p, 1, 3)
        p.lsh(1, 1, 8)
        p.iconst(12, 0x7FFFFF)
        p.iop(1, 12, "-", 1)
        ws(p, 12, 1)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        # (the firmware leaves the high-pass's state as the track's words held it)
        zero(p, RS["es"], RS["er"], RS["hps"], RS["hps"] + 1)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        o = RS_PAIR
        for base in (0, 20):
            for k in (o["phm"], o["phc"]):
                p.iconst(1, 0x2000)
                phase_set(p, base + k, 1)
            zero(p, base + o["fbm"], base + o["fbm"] + 1)
        p.fconst(1, 0x50C335 * Q23)
        ss(p, RS["es"], 1)
        ss(p, RS["er"], 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        o = RS_PAIR
        for base, k in ((0, 1), (20, 5)):
            pair_fixed(p, o, k, k + 1, base)
            split_w(p, k + 3, base + o["mfb"])
            split_w(p, k + 2, base + o["mod"])
        dec_d(p, 1, 9)
        ss(p, RS["ds"], 1)
        dec_d(p, 1, 10)
        ss(p, RS["dr"], 1)
        wf(p, 1, 11, -23)
        ss(p, RS["lvl"], 1)
        hp_coefs(p, 12, RS["hpe"], RS["hpd"])

        def one():
            pair_at(p, L, "efm_rs_pair", o, 0)
            s(p, 5, RS["es"])
            p.fop(4, 4, "*", 5)
            s(p, 5, RS["lvl"])
            p.fop(4, 4, "*", 5)
            ss(p, TMP, 4)
            env_dec(p, RS["es"], RS["ds"])
            pair_at(p, L, "efm_rs_pair", o, 20)
            s(p, 5, RS["er"])
            p.fop(4, 4, "*", 5)
            s(p, 5, TMP)
            p.fop(4, 4, "+", 5)
            K.sat(p, 4)
            to_word(p, 1, 4)
            ss(p, TMP, 1)
            env_dec(p, RS["er"], RS["dr"])
            s(p, 1, TMP)
            p.ld(12, L.C["n1"])                # 32 - the sample's number
            p.iconst(13, 31)
            p.if_(12, "GE", 13, lambda: p.fconst(3, 0.5), lambda: p.fconst(3, 0.0), kind="i")
            hp(p, RS["hps"], RS["hpe"], RS["hpd"], "reg")
        out_loop(p, L, one)


# -- EFM-CB, EFM-HH: pairs with carrier feedback ------------------------------------------------
# a pair's words relative to its base (EFM-CB's two at 0 and 20, EFM-HH's at 0); the
# modulator envelope is decayed by the machine (CF_ENV) and copied to the second pair
CF_PAIR = dict(phm=0, phc=2, fbc=4, menv=6, P=7, f2=8, incm=10, mod=12, cfb=14,
               menv_shared=True)
CF_ENV = dict(menv=6, mdec=40)
CB = dict(e1=46, e2=47, d1=48, d2=49, l1=50, l2=51)


def cf_block(p: Prog, bases, kmod: int, kcfb: int) -> None:
    """The carrier-feedback pairs' shared block words: MOD, the feedback gain and MDEC
    (W5) halves."""
    for base in bases:
        split_w(p, kmod, base + CF_PAIR["mod"])
        split_w(p, kcfb, base + CF_PAIR["cfb"])
    split_w(p, 5, CF_ENV["mdec"])


def cf_trig(p: Prog, bases) -> None:
    o = CF_PAIR
    for base in bases:
        zero(p, *(base + o[k] + j for k in ("phm", "phc", "fbc") for j in (0, 1)))
        p.iconst(1, 0x7FFFFF)
        ss(p, base + o["menv"], 1)


class EFMCB:
    """EFM-CB: an FM cowbell: two fixed-pitch pairs (W1, W2 = W1 379/256) sharing MFRQ
    (W3), MOD (W4), a modulator envelope (W5) and carrier feedback (W6); their mean under
    a sustain (W7, decay W8) and a snap (W9, decay W10) envelope."""
    NAME, ID = "EFM-CB", 37
    PNAMES = ("PTCH", "DEC", "SNAP", "FB", "MOD", "MFRQ", "MDEC", "-")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 0, 5, 8)
        pitch_i(p, L, 4, 1, 4)
        ws(p, 1, 4)
        ifloat(p, 4, 4)
        p.fconst(12, 379.0 / 256.0)
        p.fop(4, 4, "*", 12)
        p.trunc(4, 4)
        ws(p, 2, 4)
        mfrq_w(p, 3, 5)
        shl_w(p, 4, 4, 8, 0xFFFF00)
        decay_w(p, L, 5, 6, 82, 12, 147)
        scale_i(p, 1, 3, 192, 0)
        ws(p, 6, 1)
        scale_i(p, 1, 2, 420, 0)
        ws(p, 9, 1)
        p.iconst(12, 8388096)
        p.iop(1, 12, "-", 1)
        ws(p, 7, 1)
        decay_w(p, L, 8, 1, 70, 12, 147)
        decay_w(p, L, 10, 1, 19, 11, 100)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        zero(p, CB["e1"], CB["e2"])

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        cf_trig(p, (0, 20))
        p.fconst(1, 0x5A8279 * Q23)
        ss(p, CB["e1"], 1)
        ss(p, CB["e2"], 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        pair_fixed(p, CF_PAIR, 1, 3, 0)
        pair_fixed(p, CF_PAIR, 2, 3, 20)
        cf_block(p, (0, 20), 4, 6)
        dec_d(p, 1, 8)
        ss(p, CB["d1"], 1)
        dec_d(p, 1, 10)
        ss(p, CB["d2"], 1)
        wf(p, 1, 7, -23)
        ss(p, CB["l1"], 1)
        wf(p, 1, 9, -23)
        ss(p, CB["l2"], 1)

        def one():
            pair_at(p, L, "efm_cf_pair", CF_PAIR, 0)
            ss(p, TMP, 4)
            pair_at(p, L, "efm_cf_pair", CF_PAIR, 20)
            s(p, 5, TMP)
            p.fop(4, 4, "+", 5)
            K.mul_k(p, 4, 4, 0.5)
            ss(p, TMP, 4)
            menv_dec(p, CF_ENV)
            ss(p, 20 + CF_PAIR["menv"], 11)
            s(p, 4, CB["e1"])
            s(p, 5, CB["l1"])
            p.fop(4, 4, "*", 5)
            s(p, 6, CB["e2"])
            s(p, 5, CB["l2"])
            p.fop(6, 6, "*", 5)
            p.fop(4, 4, "+", 6)
            s(p, 5, TMP)
            p.fop(4, 4, "*", 5)
            ss(p, TMP, 4)
            env_dec(p, CB["e1"], CB["d1"])
            env_dec(p, CB["e2"], CB["d2"])
            s(p, 4, TMP)
        out_loop(p, L, one)


HH = dict(amp=20, damp=21, tph=22, tinc=23, tw9=24, tw10=25, hps=26, hpe=28, hpd=29)


class EFMHH:
    """EFM-HH: an FM hi-hat: a fixed-pitch pair (the modulator's feedback word W6 is
    always 0) with carrier feedback (W7), under an amplitude envelope doubled (W12 =
    $FFFFFF, mpysu) and a sine tremolo (depth W9, W10 = 1 - W9, rate W11), through the
    rounded one-pole high-pass (W8 = 1000000)."""
    NAME, ID = "EFM-HH", 38
    PNAMES = ("PTCH", "DEC", "TREM", "TFRQ", "MOD", "MFRQ", "MDEC", "FB")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 0, 5, 8, 64)
        pitch_i(p, L, 4, 1, 4)
        ws(p, 1, 4)
        decay_w(p, L, 2, 1, 70, 12, 147)
        mfrq_w(p, 3, 5)
        shl_w(p, 4, 4, 9, 0x1FFFE00)
        decay_w(p, L, 5, 6, 82, 12, 147)
        const_w(p, 6, 0)
        shl_w(p, 7, 7, 9, 0x1FFFE00)
        const_w(p, 8, 1000000)
        inp(p, 1, 2)
        p.lsh(1, 1, 8)
        ws(p, 9, 1)
        p.iconst(12, 0x7FFFFF)
        p.iop(1, 12, "-", 1)
        ws(p, 10, 1)
        scale_i(p, 1, 3, 12, 8, 64)
        pitch_i(p, L, 4, 1, 0)
        p.lsh(4, 4, -4)
        ws(p, 11, 4)
        const_w(p, 12, 0xFFFFFF)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        zero(p, HH["amp"])

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        amp_trig(p, HH["amp"], 0x50C335)
        cf_trig(p, (0,))
        zero(p, HH["hps"], HH["hps"] + 1)
        p.iconst(1, 0x2000 << 16)
        ss(p, HH["tph"], 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        pair_fixed(p, CF_PAIR, 1, 3, 0)
        cf_block(p, (0,), 4, 7)
        dec_d(p, 1, 2)
        ss(p, HH["damp"], 1)
        w(p, 1, 11)
        p.lsh(1, 1, 8)                         # acc24(W11) >> 8, in 2^-16 indices
        ss(p, HH["tinc"], 1)
        wf(p, 1, 9, -23)
        ss(p, HH["tw9"], 1)
        wf(p, 1, 10, -23)
        ss(p, HH["tw10"], 1)
        hp_coefs(p, 8, HH["hpe"], HH["hpd"])

        def one():
            pair_at(p, L, "efm_cf_pair", CF_PAIR, 0)
            menv_dec(p, CF_ENV)
            s(p, 5, HH["amp"])                 # sat(mpysu(amp, $FFFFFF)): 2 amp - 2^-23
            p.fop(5, 5, "+", 5)
            p.fconst(12, Q23)
            p.fop(5, 5, "-", 12)
            p.fconst(12, 0.0)
            p.fop(5, 5, "MAX", 12)
            p.fconst(12, K.TOP)
            p.fop(5, 5, "MIN", 12)
            p.fop(4, 4, "*", 5)                # tone
            ss(p, TMP, 4)
            env_dec(p, HH["amp"], HH["damp"])
            s(p, 6, HH["tph"])
            sine16(p, L, 4, 6)
            s(p, 13, HH["tinc"])
            p.iop(6, 13, "+", 6)
            ss(p, HH["tph"], 6)
            s(p, 5, HH["tw9"])
            p.fop(4, 4, "*", 5)
            s(p, 5, HH["tw10"])
            p.fop(4, 4, "+", 5)
            K.sat(p, 4)
            s(p, 5, TMP)
            p.fop(4, 4, "*", 5)
            to_word(p, 1, 4)
            hp(p, HH["hps"], HH["hpe"], HH["hpd"], 0.5)
        out_loop(p, L, one)


# -- EFM-CY ----------------------------------------------------------------------------------
# per operator k (0..3), at S[k + .]: the modulator's table offset, the carrier's phase (a
# sine index), the carrier's feedback; the rest shared
CY = dict(mph=0, cph=4, fb=8, menv=12, amp=13, hp1=14, hp2=16, hpe=18, hpd=19, w10=20,
          w12=22, env2=24, mdec=26, dec=28, sum=30)


def cy_base(p: Prog, L: K.Layout) -> None:
    """I1 = the slot + 4 k (operator k's words: W[1 + k], W[6 + k], S[CY[.] + k])."""
    p.ld(13, L.C["b"])
    p.seti(1, 13)


class EFMCY:
    """EFM-CY: an FM cymbal: four pairs at pitch ratios 1 : 361/256 : 461/256 : 691/256
    (carrier increments W1..W4, modulator increments W6..W9, sine indices). Each modulator is
    a sine read at a 15-bit offset, times MOD (W10, rounded), times the shared modulator
    envelope (decay W11, rounded); each carrier reads (phase + feedback + modulator) & $7FFF,
    its feedback round(FB (W12) * its sine). The four are averaged (>> 2), times the
    amplitude envelope (decay W5; W14 = $400000 makes the mpysu-and-shift x1), then through
    two rounded one-pole high-passes (W13) in series. All integer, as the firmware."""
    NAME, ID = "EFM-CY", 39
    PNAMES = ("PTCH", "DEC", "FB", "HPF", "MOD", "MFRQ", "MDEC", "-")

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        scale_i(p, 1, 0, 5, 8, 64)
        pitch_i(p, L, 7, 1, 0)                 # d1 (< 2^15)
        p.lsh(1, 7, -4)
        ws(p, 1, 1)
        inp(p, 8, 5)
        p.iconst(12, 1024)
        p.iop(8, 12, "+", 8)                   # m = MFRQ + 1024 (< 2^15)
        p.lsh(9, 8, -8)
        ifloat(p, 9, 9)                        # m >> 8
        p.iconst(12, 255)
        p.iop(10, 8, "AND", 12)
        ifloat(p, 10, 10)                      # m & 255

        def mulm(word, x):
            """W[word] = (Rx * m) >> 15, exact (Rx < 2^15). Clobbers R1-R3, R12."""
            ifloat(p, 1, x)
            p.fop(2, 1, "*", 9)
            p.fop(3, 1, "*", 10)
            p.trunc(2, 2)
            p.trunc(3, 3)
            p.lsh(2, 2, 8)
            p.ipass(12, 2)
            p.iop(2, 12, "+", 3)
            p.lsh(2, 2, -15)
            ws(p, word, 2)
        mulm(6, 7)
        for k, r in ((2, 361), (3, 461), (4, 691)):
            ifloat(p, 4, 7)
            p.fconst(12, float(r))
            p.fop(4, 4, "*", 12)
            p.trunc(11, 4)                     # r d1 (< 2^25: exact)
            p.lsh(1, 11, -12)
            ws(p, k, 1)
            p.lsh(11, 11, -8)
            mulm(k + 5, 11)
        decay_w(p, L, 5, 1, 70, 12, 147)
        scale_i(p, 1, 4, 3, 0, 3072)
        ws(p, 10, 1)
        decay_w(p, L, 11, 6, 40, 12, 350)
        scale_i(p, 1, 2, 205, 8)
        ws(p, 12, 1)
        scale_i(p, 1, 3, 186, 0)
        p.iconst(12, 8257534)
        p.iop(1, 12, "-", 1)
        ws(p, 13, 1)
        const_w(p, 14, 4194304)

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        zero(p, CY["amp"])

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        o = CY
        s(p, 1, o["amp"])
        p.iconst(12, 0x50C335)
        p.iop(1, 12, "+", 1)
        p.iconst(12, 0x7FFFFF)
        p.iop(1, 1, "MIN", 12)
        ss(p, o["amp"], 1)
        zero(p, *range(0, 12), o["hp1"], o["hp1"] + 1, o["hp2"], o["hp2"] + 1)
        p.iconst(1, 0x7FFFFF)
        ss(p, o["menv"], 1)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        o = CY
        for k, kk in ((10, o["w10"]), (12, o["w12"])):
            w(p, 1, k)
            p.lsh(1, 1, 1)
            split(p, 1, 2, 3)
            ss(p, kk, 2)
            ss(p, kk + 1, 3)
        split_w(p, 11, o["mdec"])
        split_w(p, 5, o["dec"])
        hp_coefs(p, 13, o["hpe"], o["hpd"])

        def op():
            cy_base(p, L)
            p.ldi(11, K.S0 + o["mph"], 1)      # the modulator's offset
            p.ldi(3, 6, 1)
            p.iop(13, 11, "+", 3)
            p.iconst(12, 0x7FFF)
            p.iop(13, 13, "AND", 12)
            p.sti(K.S0 + o["mph"], 1, 13)
            sine_i(p, L, 7, 4, 11)
            s(p, 5, o["w10"])
            s(p, 6, o["w10"] + 1)
            xround(p, 7, 5, 6, 7)              # round(MOD * sine)
            s(p, 5, o["env2"])
            s(p, 6, o["env2"] + 1)
            xround(p, 7, 5, 6, 7)              # * the mod env (rounded)
            cy_base(p, L)
            p.ldi(11, K.S0 + o["fb"], 1)
            p.iop(7, 11, "+", 7)               # b = fb + mod
            p.ldi(11, K.S0 + o["cph"], 1)
            p.iop(2, 11, "+", 7)
            p.iconst(12, 0x7FFF)
            p.iop(2, 2, "AND", 12)
            p.ldi(3, 1, 1)
            p.iop(13, 11, "+", 3)              # phase + inc
            p.sti(K.S0 + o["cph"], 1, 13)
            sine_i(p, L, 7, 4, 2)
            s(p, 11, o["sum"])
            p.iop(11, 11, "+", 7)
            ss(p, o["sum"], 11)
            s(p, 5, o["w12"])
            s(p, 6, o["w12"] + 1)
            xround(p, 7, 5, 6, 7)              # fb = round(FB * sine)
            cy_base(p, L)
            p.sti(K.S0 + o["fb"], 1, 7)
            p.ld(13, L.C["b"])
            p.iconst(12, 4)
            p.iop(13, 12, "+", 13)
            p.st(L.C["b"], 13)

        def one():
            zero(p, o["sum"])
            p.ld(13, L.C["mdb"])
            p.st(L.C["b"], 13)
            s(p, 11, o["menv"])
            p.lsh(11, 11, 1)
            split(p, 11, 2, 3)
            ss(p, o["env2"], 2)
            ss(p, o["env2"] + 1, 3)
            p.loop(L.C["n2"], 4, op)
            edec(p, o["menv"], o["mdec"])
            s(p, 7, o["sum"])
            p.ash(7, 7, -2)                    # the mix
            s(p, 11, o["amp"])
            p.lsh(11, 11, 1)
            split(p, 11, 5, 6)
            xround(p, 7, 5, 6, 7)
            ss(p, TMP, 7)
            edec(p, o["amp"], o["dec"])
            s(p, 1, TMP)
            hp(p, o["hp1"], o["hpe"], o["hpd"], 0.5)
            p.ipass(1, 2)
            hp(p, o["hp2"], o["hpe"], o["hpd"], 0.5)
        out_loop(p, L, one)


MACHINES = (EFMBD, EFMSD, EFMXT, EFMCP, EFMRS, EFMCB, EFMHH, EFMCY)

"""FASCIA as the DSP will compute it: the float32, DSP-order contract the PERC DSL program
will be held to, bit for bit (docs/fascia.md, docs/fascia-integration-plan.md).

`fascia/model.py` is the sound, approved by ear (float64, offline). This is the same design
made causal, streaming and block-wise, in float32, with only what the SHARC code can do in
the DSL's forms (`dnfw.perc.dsl`): add, subtract, multiply, MIN/MAX, compare, FLOAT/TRUNC,
shifts, table reads, structured if/loop. No division, no libm.

**Interface.** `Voice()` holds one voice. `note_on(note, vel)` arms it; the next
`block(controls)` strikes with that block's controls and returns 32 float32 samples; every
later `block(controls)` reads the controls again (p-locks, slides, LFOs). `idle` is True at
rest; `rest()` forces rest (a steal without a fade). A `note_on` on a sounding voice is a
steal: the next block is the old sound faded out over 32 samples, the strike is the block
after (one block, 0.67 ms, late; the DSP has one state per voice). `render_notes` mixes voices.
`cost_estimate(controls)` is a rough per-block instruction count.

**Every float is float32** (`F = np.float32`; numpy keeps float32 under NEP 50), and every
expression is evaluated in the order it is written: one rounding per operation, as the DSP.
Vector expressions over modes or bands are that many independent scalar chains; a sum over
modes is sequential in mode order (`seqsum`, numpy's add.accumulate). Exactly representable
integer arithmetic (counters, the xorshift, `expand`) is plain Python.

**The approximations** (each measured below; all are far under what float32 itself gives
a two-pole resonator in direct form, which is why the modes use another form):

- `exp2(x)`: x = i + f (FLOOR by TRUNC and a compare), 2^f by a degree-5 polynomial with
  c0 = 1 (max relative error 1.6e-7; exp2 of an integer exact), times 2^i by `FLOAT 1 BY i`
  (exact). x clamped to +-100.
- `sinp(h)`, `cosp(h)` on 0..pi/2: odd degree-9 and even degree-10 polynomials (relative
  error 1.7e-7, absolute 1.2e-7). Used where precision matters at small angles: a mode's
  half-angle, the SVF's tan, the MIX law.
- `sin_t`, `cos_t`: SHFT's sine table (256 points a turn, a quarter more, linear; absolute
  error 7.5e-5, -82 dB). Used for oscillators and shapes: PULSE, TZFM, the bow's speed, the
  RING and SHIFT oscillators, FOLD, the clicks, POS's |sin|.
- `expm1(y)`, |y| <= 0.144: Taylor to y^6 (error < 2e-10). Gives 1 - r for a mode's pole
  radius without the cancellation of 1 - exp(y).
- `recip(x)`, x > 0: the seed 0x7ef311c7 - bits, three Newton steps (PERC's; 4e-8).
- `rsqrt(x)`: the seed 0x5f3759df, three Newton steps; `sqrt(x) = x rsqrt(x)`.
- `tanh_r(x)`: the (7,6) Pade/Lambert rational, |x| clamped to 4.97 (where it reaches 1);
  error 1e-6 to |x| = 3, 1.5e-5 to 4, 1e-4 at the clamp; never above 1.

**The modes** are two-pole resonators in difference form: with y the output and
d = y[n-1] - y[n-2],

    d = d - m d - k y + b x,     y = y + d,      m = 1 - r^2,  k = (1 - r)^2 + 4 r sin^2(w/2)

which is exactly the model's y = 2 r cos w y1 - r^2 y2 + b x (2 r cos w = 1 + r^2 - k), but
with coefficients that keep their relative precision as w -> 0 and r -> 1. (Direct form in
float32: 2 r cos w at 40 Hz is 1.99989..., its last bit is 13 cents of pitch.) d is also the
contact velocity BOW and BLOW need (the model's y1 - y2), for free.

**Causal substitutions** (the model works on whole signals; this cannot):

- SHIFT: SHFT's IIR all-pass Hilbert pair (Niemitalo's coefficients) and a quadrature
  oscillator from the sine table, for scipy's FFT `hilbert`.
- ATK: the model's window convolution, exactly and causally: the window's moments in the
  samples' age, updated a sample at a time; a second generator, m samples behind, replays
  what leaves the window; two staggered sums bound the rounding (`Exciter`). Measured
  against an exact convolution of the same stream: 1e-7..8e-4 RMS, whatever the length.
- DUST (the exciter type): each grain is an impulse into four one-poles with the Hann
  pulse's variance (unit area), for the convolution with the pulse. (No audition patch uses
  it; with sparse grains a ring of active grains would be exact, at a cost.)
- WATR: the level match is running sums of skin^2 and wet^2 since the strike, the gain
  sqrt(sum skin^2 / sum wet^2) once a block, ramped across it, for the whole-signal RMS ratio.
  It converges on the model's constant as the voice's energy accumulates (within 3 dB by
  0.5 s), but at the strike it knows only the strike: the onset's wet skin is quieter than
  the model's (5..17 dB in the first 50 ms on the two WATR patches). For the owner's ear.
- Exciters are per-sample generators with multiplicative envelopes; the model's Gaussian
  noise is the sum of two of the xorshift's uniforms, of unit variance; per-hit variation draws
  from the voice's xorshift, so the hits vary as the model's do but are not the same draws
  (`draws=` lets a test give the model's).
- Twins (near-degenerate mode pairs) on TWINS = 8 of the 16 modes, the plan's cost cut: the
  eight that matter most at the strike (amplitude x sqrt T60, `twin_select`; on a bell its
  prominent upper partials, which the lowest eight would miss: the tower's pitch moved 4 cents
  through BEND's level-following glide). The other twins are folded into their primaries
  (a + b: the same onset and normalisation sums); those modes do not beat. With all 16
  (`twins=16`) and the model's draws, live matches the model to every measure's precision.

**Per-block modulation** (the model never changes a control mid-note; here every one can).
What is the model's exactly while a control holds still, and smooth while it moves:
- TUNE or GEOM moving re-expresses each mode's state for its new frequency (`Body.retune`,
  same amplitude and phase), and a mode pushed out of 15 Hz..0.45 fs dies in a millisecond
  instead of ringing on at the clamp.
- A post stage (RING, SHIFT, FORM, WATR, FOLD, CHAR, the VCA) switched on or off mid-note
  crossfades over FADE = 4 blocks and runs on its last settings until faded out.
- FORM's wet mix and WATR's amount ramp across the block; RING's depth and the VCA's level
  ramp, FOLD's and CHAR's outputs crossfade from the last block's setting to the new one;
  MORPH's depth slews (2.7 ms) and its weights ramp across a block while it moves.

**Robustness.** Controls are clamped to integers 0..127 (NaN or infinity is 0); velocity is
clamped to 0..1 (NaN is 1.0); a note that is NaN or infinite is 0. States below FLOOR are
flushed to zero every block (so no recurrence ever holds a denormal, as the SHARC would flush
them). The output passes the model's level guard and its tanh knee (|y| < 0.667). If a state
ever goes non-finite or out of range the voice rests (`faults` counts it; never seen).
"""

from __future__ import annotations

import math

import numpy as np

from . import model as M

F = np.float32
RATE = M.RATE
BLOCK = M.BLOCK
MODES = M.MODES
TWINS = 8                        # twins on 8 modes (the plan's cost cut; twin_select picks them)
FLOOR = 1.0e-10                  # a state under this is flushed to zero (-200 dB)
IDLE = F(M.IDLE)
OUT = F(M.OUT)
GUARD = 1.0e4                    # a state past this means a fault: the voice rests

_SQ3 = F(math.sqrt(3.0))
_SQ15 = F(math.sqrt(1.5))
LOG2E = F(1.0 / math.log(2.0))
INV127 = F(1.0 / 127.0)
INVR = F(1.0 / RATE)


def c32(x) -> np.float32:
    return np.float32(x)


def _fl(x):
    """a state under FLOOR is zero (the per-sample flush of a decaying envelope)"""
    return F(0.0) if -FLOOR < x < FLOOR else x


def _sc(r):
    """a 0-d result as a float32 scalar, arrays as they are"""
    return F(r) if np.ndim(r) == 0 else r


# -- arithmetic ---------------------------------------------------------------------------
EXP2_C = tuple(F(c) for c in (1.0, 0.6931513547897339, 0.2401641458272934,      # c0 = 1: exp2 of
                              0.05580046772956848, 0.009016658179461956,      # an integer is exact
                              0.0018671966390684247))
SIN_C = tuple(F(c) for c in (1.0, -0.16666658222675323, 0.0083330562338233,
                             -0.0001980914967134595, 2.6050893211504444e-06))
COS_C = tuple(F(c) for c in (1.0, -0.5, 0.04166664555668831, -0.0013888493413105607,
                             2.4767618015175685e-05, -2.6198048885817116e-07))
EXPM1_C = tuple(F(1.0 / math.factorial(k)) for k in range(1, 7))     # 1, 1/2, ..., 1/720
TANH_N = tuple(F(c / 135135.0) for c in (135135.0, 17325.0, 378.0, 1.0))
TANH_D = tuple(F(c / 135135.0) for c in (135135.0, 62370.0, 3150.0, 28.0))
TANH_TOP = F(4.97)


def exp2(x):
    """2^x: i = floor(x), f = x - i, poly(f) (Horner, highest first) x 2^i."""
    x = np.minimum(np.maximum(np.asarray(x, F), F(-100.0)), F(100.0))
    i = np.floor(x)
    f = x - i
    p = EXP2_C[5]
    for c in EXP2_C[4::-1]:
        p = p * f + c
    return _sc(np.ldexp(np.asarray(p, F), i.astype(np.int32)).astype(F))


def sinp(h):
    """sin h for h in 0..pi/2: h (c0 + h^2 (c1 + ...)), Horner from c4."""
    h = np.asarray(h, F)
    h2 = h * h
    p = SIN_C[4]
    for c in SIN_C[3::-1]:
        p = p * h2 + c
    return _sc(p * h)


def cosp(h):
    h = np.asarray(h, F)
    h2 = h * h
    p = COS_C[5]
    for c in COS_C[4::-1]:
        p = p * h2 + c
    return _sc(p)


def expm1(y):
    """e^y - 1 for small y: y (1 + y (1/2 + y (1/6 + ...)))"""
    y = np.asarray(y, F)
    p = EXPM1_C[5]
    for c in EXPM1_C[4::-1]:
        p = p * y + c
    return _sc(p * y)


def recip(x):
    """1/x for x > 0 (normal): seed 0x7ef311c7 - bits, then r = r (2 - x r) three times."""
    x = np.asarray(x, F)
    r = (np.uint32(0x7EF311C7) - x.view(np.uint32)).astype(np.uint32).view(F)
    for _ in range(3):
        r = r * (F(2.0) - x * r)
    return _sc(r)


def rsqrt(x):
    """1/sqrt(x) for x > 0: seed 0x5f3759df - (bits >> 1), then r = r (1.5 - (x/2) r^2) x3."""
    x = np.asarray(x, F)
    r = (np.uint32(0x5F3759DF) - (x.view(np.uint32) >> np.uint32(1))).astype(np.uint32).view(F)
    hx = x * F(0.5)
    for _ in range(3):
        r = r * (F(1.5) - (r * r) * hx)
    return _sc(r)


def sqrt(x):
    x = np.asarray(x, F)
    return _sc(np.where(x > F(0.0), x * rsqrt(np.maximum(x, F(1e-30))), F(0.0)).astype(F))


def tanh_r(x):
    """tanh by the (7,6) rational: x (n0 + x^2 (n1 + x^2 (n2 + x^2 n3))) / (d0 + ...), x
    clamped to +-4.97 first."""
    x = np.minimum(np.maximum(np.asarray(x, F), -TANH_TOP), TANH_TOP)
    x2 = x * x
    n = TANH_N[3]
    for c in TANH_N[2::-1]:
        n = n * x2 + c
    d = TANH_D[3]
    for c in TANH_D[2::-1]:
        d = d * x2 + c
    return _sc((x * n) * recip(d))


def frac(x):
    """x - floor(x)"""
    x = np.asarray(x, F)
    return _sc(x - np.floor(x))


def seqsum(v):
    """sum in index order, one rounding a step (the DSP's accumulation)"""
    v = np.asarray(v, F)
    return F(np.add.accumulate(v, dtype=F)[-1]) if v.ndim == 1 else np.add.accumulate(v, axis=0, dtype=F)[-1]


def _table_sin() -> np.ndarray:
    from ..shft import live as SL                # SHFT's sine: 256 a turn + a quarter + 2
    return np.array(SL.table_sin(), F)


SIN_T = _table_sin()
_TOP = F(len(SIN_T) - 2)


def _tab(x):
    x = np.minimum(np.maximum(np.asarray(x, F), F(0.0)), _TOP)
    i = np.trunc(x).astype(np.int32)
    f = x - i.astype(F)
    a = SIN_T[i]
    return _sc(a + f * (SIN_T[i + 1] - a))


def sin_t(ph):
    """sin(2 pi ph), ph in 0..1 (turns)"""
    return _tab(np.asarray(ph, F) * F(256.0))


def cos_t(ph):
    return _tab(np.asarray(ph, F) * F(256.0) + F(64.0))


def u(v: int) -> np.float32:
    """a 0..127 control as 0..1: clamp(v, 0, 127) x (1/127) (model.u; expand can make 128:
    ATK at HARD 0)"""
    return F(min(max(v, 0), 127)) * INV127


def expmap(v: int, lo: float, hi: float) -> np.float32:
    """lo (hi/lo)^u: lo x 2^(u log2(hi/lo))"""
    return F(lo) * exp2(u(v) * F(math.log2(hi / lo)))


def onepole_inv(inv_seconds, samples: int = 1) -> np.float32:
    """exp(-samples / (tau RATE)) from 1/tau: exp2(-(samples log2e / RATE) / tau)"""
    return exp2(F(-samples * (1.0 / math.log(2.0)) / RATE) * F(inv_seconds))


def smear_pole(var: float, stages: int) -> np.float32:
    """the one-pole coefficient a for which STAGES unit-gain one-poles (y += (1-a)(x - y))
    have impulse-response variance VAR (samples^2): each stage a / (1 - a)^2 = s, so
    a = 2 s / ((1 + 2 s) + sqrt(1 + 4 s))  (the stable root)."""
    s = F(var) * F(1.0 / stages)
    if s <= F(0.0):
        return F(0.0)
    t = F(1.0) + F(2.0) * s
    return F(F(2.0) * s) * recip(t + sqrt(F(1.0) + F(4.0) * s))


HANN_VAR = 1.0 / 12.0 - 1.0 / (2.0 * math.pi ** 2)       # a raised cosine of width n: n^2 x this


# -- noise ----------------------------------------------------------------------------------
class XS:
    """The voice's xorshift32 (PERC's: 13, 17, 5; XOR written as (a|b) - (a&b) on the DSP)."""

    def __init__(self, seed: int):
        s = (0x2545F491 + ((seed & 0xFFFF) << 16) + (seed & 0xFFFF)) & 0xFFFFFFFF
        self.s = s or 1
        for _ in range(3):
            self.next()

    def next(self) -> int:
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s

    def bi(self) -> np.float32:
        """-1..1: the signed word x 2^-31 (FLOAT R BY -31)"""
        s = self.next()
        return F((s - (1 << 32) if s >> 31 else s) * 2.0 ** -31)

    def u01(self) -> np.float32:
        """0..1: the top 24 bits x 2^-24 (LSHIFT BY -8, FLOAT BY -24)"""
        return F((self.next() >> 8) * 2.0 ** -24)

    def gauss(self) -> np.float32:
        """the model's normal draws: two uniforms' sum, of unit variance ((bi + bi) sqrt 1.5):
        triangular, kurtosis 2.4 against the normal's 3, so a noise burst's energy varies hit
        to hit as 0.84 of the model's (a single uniform: 0.63; test_noise_contact_...)"""
        a = self.bi()
        return (a + self.bi()) * _SQ15


# -- controls -------------------------------------------------------------------------------
def clamp_ctl(v) -> int:
    """a control as the DSP sees it: an integer 0..127 (NaN, infinities and junk: 0)"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(x):
        return 0
    return int(min(max(x, 0.0), 127.0))


def choice(name: str, v: int) -> int:
    """the option of a 0..127 value: (v n) >> 7, capped (model.choice)"""
    n = len(M.CHOICES[name])
    return min((clamp_ctl(v) * n) >> 7, n - 1)


def ichoice(name: str, v: int) -> int:
    n = len(M.ICHOICES[name])
    return min((clamp_ctl(v) * n) >> 7, n - 1)


def _span(n: int, k: int) -> int:
    return ((2 * k + 1) * 64) // n                       # int((k + 0.5) 128 / n)


def expand(panel: dict) -> dict:
    """model.expand in integer maths (equal for every input, test_fascia_live): the panel's 24
    controls -> the engine's 32. The DSP can hold the (95 w) // 127 as a 128-byte table."""
    p = {k: clamp_ctl(panel.get(k, d)) for k, d in M.DEFAULTS.items()}
    q = dict(M.INTERNAL)
    for k in ("TYPA", "TYPB", "DUST", "BEND", "MIX", "DEC", "BODA", "BODB", "TUNE",
              "GEOM", "MATL", "POS", "DAMP", "MORPH", "SHIFT", "BUZZ", "LPG"):
        q[k] = p[k]
    h = p["HARD"]
    q["HARD"] = h
    q["ATK"] = (32 - h) * 4 if h < 32 else 0
    q["TZFM"] = p["TZFM"]
    q["SIDE"] = 16 + (3 * p["TZFM"]) // 4
    c = p["CLIK"]
    if c > 0:
        z = min(((c - 1) * 4) // 127, 3)
        w4 = 4 * (c - 1) - 127 * z                       # 4 x within, 0..127
        q["CTYP"] = _span(len(M.CLICKS), z)
        q["CLIK"] = 32 + (95 * min(max(w4, 0), 127)) // 127
    x = M.XMODS_PANEL[choice("XMOD", p["XMOD"])]
    if x == "RING":
        q["XMOD"], q["COUP"], q["RING"] = _span(len(M.XMODS), 0), 0, p["COUP"]
    else:
        q["XMOD"], q["COUP"] = _span(len(M.XMODS), M.XMODS.index(x)), p["COUP"]
    sk = p["SKIN"]
    q["FORM"] = min((64 - sk) * 2, 127) if sk < 64 else 0
    q["WATR"] = min((sk - 64) * 2, 127) if sk > 64 else 0
    d = p["DRIVE"]
    q["CHAR"] = min(d * 2, 127)
    q["FOLD"] = (d - 64) * 2 if d > 64 else 0
    return q


def engine(controls) -> dict:
    """a block's engine controls: the panel's through expand(), or (`_internal`) the 32 directly"""
    controls = controls or {}
    if controls.get("_internal"):
        return {k: clamp_ctl(controls.get(k, d)) for k, d in M.INTERNAL.items()}
    return expand(controls)


def note_ok(note) -> float:
    try:
        x = float(note)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def vel_ok(vel) -> np.float32:
    try:
        x = float(vel)
    except (TypeError, ValueError):
        return F(1.0)
    return F(1.0) if not math.isfinite(x) else F(min(max(x, 0.0), 1.0))


# -- constant tables (DDR) ------------------------------------------------------------------
# log2 of each body's 16 mode ratios (float64 -> float32), 9 x 16 words
LOG2R = {k: np.array([math.log2(r) for r in M.RATIOS[k]], F) for k in M.RATIOS}
# the ratios themselves (for the twins' beat, model.Body): 2^LOG2R in float32, as the DSP computes
# them from the one table it holds (until 2026-11-08 F(ratio) directly: within 2 ulps of it)
RATIO = {k: exp2(LOG2R[k]) for k in M.RATIOS}
LOG2_440 = math.log2(440.0)
C_DECAY = F(-3.0 * math.log(10.0) / RATE)        # 10^(-3/(T R)) = e^(C/T)
F_HI, F_LO = F(0.45 * RATE), F(15.0)
H_SCALE = F(math.pi / RATE)                       # f -> the half-angle w/2


def f0_of(note: float, tune: int) -> tuple[np.float32, np.float32]:
    """(f0, log2 f0) for a note and TUNE: 440 x 2^((note + (TUNE-64) 0.375 - 69) / 12)"""
    nn = F(note) + (F(tune) - F(64.0)) * F(0.375)
    l2 = (nn - F(69.0)) * F(1.0 / 12.0)
    return F(440.0) * exp2(l2), l2 + F(LOG2_440)


# -- the bodies -----------------------------------------------------------------------------
def twin_select(kind: str, L, pair, f0, strike, T: int) -> list[int]:
    """the T modes whose twins are kept: the ones that matter most at the strike, by their
    amplitude x sqrt(T60) (the RMS of a decaying mode: how loud, how long), from the strike's
    controls (GEOM, DAMP, MATL, POS, the tilt). The rest beat no more. On the DSP: 16 scores
    at the strike (as Body.coeffs, without the drift and the LPG), then T passes of a
    selection over 16; ties go to the lower mode."""
    geom_e, inv_t60, matl, pos, tilt = strike
    lr = F(geom_e) * L
    ratio = exp2(lr)
    f = np.minimum(np.maximum(ratio * F(f0), F_LO), F_HI)
    mt = min(max(F(matl) + F(M.RING_BIAS[kind]), F(0.0)), F(1.0))
    om = F(1.0) - mt
    a1 = F(4.0) * (om * om) + F(0.015)
    a2 = F(2.0) * ((om * om) * om) + F(0.002)
    fk = f * F(0.001)
    inv = np.minimum(F(inv_t60) * ((fk * a2 + a1) * fk + F(1.0)), F(1000.0))
    sp = ratio if M.SPATIAL[kind] == 1.0 else exp2(lr * F(M.SPATIAL[kind]))
    sh = np.abs(sin_t(frac(sp * (F(pos) * F(0.5)))))
    score = ((sh * exp2(lr * (F(-0.7) * F(tilt)))) * pair) * rsqrt(inv)
    alive = (ratio * F(f0) < F_HI) & (ratio * F(f0) > F_LO)
    score = np.where(alive, score, F(-1.0))
    left, sel = list(range(len(L))), []
    for _ in range(T):
        best = max(left, key=lambda i: (score[i], -i))
        sel.append(best)
        left.remove(best)
    return sorted(sel)


class Body:
    """One modal body: 16 primaries, plus twins on TWINS of them where the body is round (the
    ones that matter most at the strike: twin_select; the lowest TWINS without STRIKE).
    State per mode: y (output) and d (y - y[n-1]); coefficients m, k, b once a block."""

    def __init__(self, kind: str, f0, rng: XS, vary, twins: int = TWINS, draws=None, strike=None):
        self.kind = kind
        n = MODES
        L0 = LOG2R[kind]
        split = M.SPLIT[kind]
        if draws is None:
            ks = np.arange(n)
            js = np.array([math.sqrt(3.0) * 0.0012 * (1.0 + 0.15 * k) for k in ks], F) * F(vary)
            eps = np.array([rng.bi() for _ in ks], F) * js
            eps[0] = eps[0] * F(0.2)
            g2 = np.array([rng.gauss() for _ in ks], F)
            aj = exp2(g2 * (F(0.10) * F(vary) * LOG2E))
            for i, wgt in enumerate(M.MODE_WEIGHT.get(kind, ())):
                aj[i] = aj[i] * F(wgt)
            if split:
                r1 = np.array([rng.u01() for _ in ks], F)
                beat = np.minimum((F(f0) * RATIO[kind]) * F(split) * (F(0.6) + F(0.8) * r1),
                                  F(M.BEAT_MAX[kind]))
                offs = np.maximum(beat, F(0.15))
                r2 = np.array([rng.u01() for _ in ks], F)
                ajt = aj * (F(0.5) + F(0.5) * r2)
        else:
            eps, aj = np.array(draws["eps"], F), np.array(draws["aj"], F)
            offs, ajt = draws.get("offs"), draws.get("ajt")
            if split:
                offs, ajt = np.array(offs, F), np.array(ajt, F)
        # log2(1 + e) ~ e (1 - e/2) log2e: e is a few 1e-3, the error e^3/3
        Lj = L0 + (eps * (F(1.0) - F(0.5) * eps)) * LOG2E
        sel = []
        if split:
            T = max(0, min(twins, n))
            if T >= n or strike is None:
                sel = list(range(T))
            else:
                sel = twin_select(kind, Lj, aj + ajt, f0, strike, T)
            folded = np.array([k not in sel for k in range(n)])
            self.L = np.concatenate([Lj, Lj[sel]])
            fold = np.where(folded, aj + ajt, aj).astype(F)   # folded twins: same onset, same sums
            self.aj = np.concatenate([fold, ajt[sel]])
            self.offs = np.concatenate([np.zeros(n, F), offs[sel]])
            self.mult = np.concatenate([np.where(folded, F(2.0), F(1.0)), np.ones(len(sel), F)])
            self.nfull = F(2 * n)
        else:
            self.L, self.aj, self.offs = Lj.astype(F), aj.astype(F), np.zeros(n, F)
            self.mult, self.nfull = np.ones(n, F), F(n)
        self.sel = sel
        self.ddraw = None
        if draws is not None and draws.get("drift") is not None:
            dd = np.asarray(draws["drift"])                  # blocks x the model's modes
            cols = list(range(n)) + [n + i for i in sel]
            self.ddraw = dd[:, cols].astype(F)
        self.n = len(self.L)
        self.spatial = M.SPATIAL[kind]
        self.bias = F(M.RING_BIAS[kind])
        self.y = np.zeros(self.n, F)
        self.d = np.zeros(self.n, F)
        self.drift = np.zeros(self.n, F)
        self.dsig = F(math.sqrt(3.0) * 1.5e-5) * F(vary)
        self.nblk = 0
        self.peak = F(1e-9)
        self.level = F(1.0)
        self.og = self.og_prev = None
        self.ramp_og = False
        self.amp = np.zeros(self.n, F)
        self.s2 = self.sw = None

    def coeffs(self, rng: XS, f0b, geom_e, inv_t60, matl, loss, pos, tilt, mexp) -> None:
        """the block's coefficients (model.Body.coeffs). f0b = f0 x bend; inv_t60 = 1 / T60;
        mexp = MORPH's exponent this block (0: off)."""
        if self.ddraw is not None and self.nblk < len(self.ddraw):
            inc = self.ddraw[self.nblk]                       # the model's (a test's draws)
        else:
            inc = np.array([rng.bi() for _ in range(self.n)], F) * self.dsig
        self.nblk += 1
        self.drift = self.drift * F(0.995) + inc
        lr = F(geom_e) * self.L
        rg = exp2(lr)
        ratio = rg * (F(1.0) + self.drift)
        f = ratio * F(f0b) + self.offs
        alive = (f < F_HI) & (f > F_LO)
        f = np.minimum(np.maximum(f, F_LO), F_HI)
        h = f * H_SCALE
        s = sinp(h)
        sw = (F(2.0) * s) * cosp(h)                       # sin w
        mt = min(max(F(matl) + self.bias, F(0.0)), F(1.0))
        om = F(1.0) - mt
        a1 = F(4.0) * (om * om) + F(0.015)
        a2 = F(2.0) * ((om * om) * om) + F(0.002)
        fk = f * F(0.001)
        den = (fk * a2 + a1) * fk + F(1.0)
        lf = F(loss) * np.maximum(ratio - F(1.0), F(0.0)) + F(1.0)
        inv = np.minimum((F(inv_t60) * den) * lf, F(1000.0))      # 1 / max(t60k, 1 ms)
        # a mode moved out of range (TUNE, GEOM or BEND after the strike) dies in a ms instead
        # of ringing on at the clamp; static, such a mode was never excited (the model's)
        inv = np.where(alive, inv, F(1000.0)).astype(F)
        q = -expm1(inv * C_DECAY)                                 # 1 - r
        r = F(1.0) - q
        self.m = q * (F(2.0) - q)                                 # 1 - r^2
        s2 = s * s
        self.k = q * q + F(4.0) * (r * s2)
        self.prev = (self.s2, self.sw)
        self.s2, self.sw = s2, sw
        sp = ratio if self.spatial == 1.0 else exp2(lr * F(self.spatial))
        sh = np.abs(sin_t(frac(sp * (F(pos) * F(0.5)))))         # |sin(pi sp pos)|
        tw = exp2(lr * (F(-0.7) * F(tilt)))
        shape = (sh * tw) * self.aj
        S = seqsum(shape)
        gn = OUT * recip(max(S, F(1e-6)))
        self.amp = np.where(alive, shape * gn, F(0.0)).astype(F)
        self.b = self.amp * sw
        self.phi = self.amp * F(4.0 / M.OUT)
        self.og_prev = self.og
        if mexp > F(0.0):
            we = exp2(lr * F(mexp))
            W = seqsum(we * self.mult)
            self.og = we * (self.nfull * recip(W))
        else:
            self.og = None

    def _out(self, Y: np.ndarray) -> np.ndarray:
        """Y: modes x 32 -> the block: the sum over modes, in mode order (og-weighted; when
        MORPH itself moved, the weights ramp from the last block's across this one)"""
        if self.og is not None:
            if self.ramp_og and self.og_prev is not None:
                r = np.arange(1, BLOCK + 1, dtype=F) * F(1.0 / BLOCK)
                Y = Y * (self.og_prev[:, None] + (self.og - self.og_prev)[:, None] * r[None, :])
            else:
                Y = Y * self.og[:, None]
        return np.add.accumulate(Y, axis=0, dtype=F)[-1]

    def run(self, x: np.ndarray | None) -> np.ndarray:
        """a block driven by a known input (None: no input this block)"""
        y, d, m, k = self.y, self.d, self.m, self.k
        Y = np.empty((self.n, BLOCK), F)
        if x is None:
            for j in range(BLOCK):
                d = d - m * d
                d = d - k * y
                y = y + d
                Y[:, j] = y
        else:
            b = self.b
            for j in range(BLOCK):
                d = d - m * d
                d = d - k * y
                d = d + b * x[j]
                y = y + d
                Y[:, j] = y
        self.y, self.d = y, d
        return self._done(self._out(Y))

    def run_driven(self, force, x: np.ndarray | None) -> np.ndarray:
        """a block whose input depends on the body's motion, sample by sample: v = 40 sum
        phi d (the contact velocity), f = force(j, v) + x[j]"""
        y, d, m, k, b, phi = self.y, self.d, self.m, self.k, self.b, self.phi
        Y = np.empty((self.n, BLOCK), F)
        for j in range(BLOCK):
            v = seqsum(phi * d) * F(40.0)
            fj = force(j, v)
            if x is not None:
                fj = fj + x[j]
            d = d - m * d
            d = d - k * y
            d = d + b * fj
            y = y + d
            Y[:, j] = y
        self.y, self.d = y, d
        return self._done(self._out(Y))

    def _done(self, out: np.ndarray) -> np.ndarray:
        pk = F(np.max(np.abs(out)))
        self.peak = max(self.peak, pk)
        self.level = pk * recip(self.peak)
        return out

    def flush(self) -> None:
        z = (np.abs(self.y) < F(FLOOR)) & (np.abs(self.d) < F(FLOOR))
        self.y[z] = F(0.0)
        self.d[z] = F(0.0)

    def energy(self) -> np.float32:
        return F(np.max(np.abs(self.y))) + F(np.max(np.abs(self.y - self.d)))

    def active(self, has_input: bool) -> int:
        """modes the DSP must run this block (state nonzero, or input and gain)"""
        live = (self.y != 0) | (self.d != 0)
        if has_input:
            live = live | (self.amp != 0)
        return int(np.count_nonzero(live))

    def retune(self) -> None:
        """the state re-expressed for this block's frequencies (TUNE or GEOM moved): with
        y = A sin p, d = y (1 - cos w) + A cos p sin w, the same A and p at the new w are
        d' = 2 s'^2 y + (d - 2 s^2 y) sin w' / sin w  (s = sin w/2; exact undamped)"""
        s2o, swo = self.prev
        if s2o is None:
            return
        t = self.d - (F(2.0) * s2o) * self.y
        self.d = (F(2.0) * self.s2) * self.y + t * (self.sw * recip(np.maximum(swo, F(1e-6))))

    def scale_y(self, s) -> None:
        """y[n-1] x= s, y[n-2] kept (TRADE): t = (1 - s) y; y -= t; d -= t"""
        t = (F(1.0) - F(s)) * self.y
        self.y = self.y - t
        self.d = self.d - t

    def ok(self) -> bool:
        return bool(np.all(np.isfinite(self.y)) and np.all(np.isfinite(self.d))
                    and np.max(np.abs(self.y)) < GUARD and np.max(np.abs(self.d)) < GUARD)


# -- the exciters ---------------------------------------------------------------------------
TG = {k: F(v) for k, v in M.TYPE_GAIN.items()}
K_RAMP = F(1.0 / 96.0)                            # a driven exciter's 2 ms rise without ATK


class Smear:
    """N unit-gain one-poles in a row: y_i += (1 - a)(y_{i-1} - y_i)"""

    def __init__(self, a, stages: int):
        self.ca = F(1.0) - F(a)
        self.s = [F(0.0)] * stages

    def __call__(self, x):
        s, ca = self.s, self.ca
        for i in range(len(s)):
            s[i] = _fl(s[i] + (x - s[i]) * ca)
            x = s[i]
        return x


class TZ:
    """Through-zero FM (model.Exciter.tzfm), per sample: the modulator's phase is the time's
    (read, then advanced); the carrier's is advanced by a signed increment, then read."""

    def __init__(self):
        self.mph = F(0.0)
        self.cph = F(0.0)
        self.ei = F(1.0)
        self.eo = F(1.0)

    def setup(self, f0, ratio, depth, tau) -> None:
        self.ci = F(f0) * INVR
        self.fm = (F(f0) * F(ratio)) * INVR
        self.d6 = F(depth) * F(6.0)
        it = recip(F(tau))
        self.ki = onepole_inv(it)
        self.ko = onepole_inv(recip(F(3.0) * F(tau) + F(0.005)))

    def __call__(self):
        mv = sin_t(self.mph)
        self.mph = frac(self.mph + self.fm)
        inc = self.ci + ((self.ei * self.d6) * mv) * self.fm
        self.cph = frac(self.cph + inc)
        y = sin_t(self.cph) * self.eo
        self.ei = _fl(self.ei * self.ki)
        self.eo = _fl(self.eo * self.ko)
        return y


class Gen:
    """An impulsive exciter's excitation, one sample a call (x vel x TYPE_GAIN, the TZFM burst
    in): STRIKE's pulse and contact noise, DUST's grains, PULSE, TZFM. It owns its xorshift
    and its sample count, and reads its controls at each 32 samples of its own count from
    `self.c` (the voice's block controls, or the strike's when latched), so a copy started
    later replays it exactly (ATK's window needs that)."""

    def __init__(self, kind: str, q: dict, f0, vel, seed: int):
        self.kind, self.vel, self.rng = kind, F(vel), XS(seed)
        self.k = 0
        hard = u(q["HARD"]) * (F(0.5) + F(0.5) * self.vel)
        self.width = F(4.0e-3) * exp2(hard * F(math.log2(0.0125)))     # 4 ms .. 0.05 ms
        self.pn = max(int(np.trunc(self.width * F(RATE))), 2)          # STRIKE's pulse, samples
        self.pinv = recip(F(self.pn))
        self.en = F(1.0)                                 # contact noise / DUST envelope
        self.burst = TZ() if q["TZFM"] > 0 and kind != "TZFM" else None
        self.tz = TZ() if kind == "TZFM" else None
        if kind == "DUST":
            dn = max(int(np.trunc(max(self.width, F(1e-4)) * F(RATE))), 2)
            # the grain's variance in float32, as the DSP computes it (F(HANN_VAR) (dn dn), dn a
            # small int; until 2026-11-08 the float64 HANN_VAR dn^2, rounded once: 1 ulp apart)
            self.grain = Smear(smear_pole(F(HANN_VAR) * (F(dn) * F(dn)), 4), 4)
        self.ph = F(0.0)                                 # PULSE
        self.pe = F(1.0)
        self.ep = F(1.0)
        self.c = None
        self.f0 = F(f0)

    def _setup(self) -> None:
        """the controls of this 32 samples (model.Exciter._make's, as rates and gains)"""
        c, f0, kind = self.c, self.f0, self.kind
        dec = c["dec"]
        if self.burst is not None:
            self.burst.setup(f0, c["side"], c["utz"], min(dec, F(0.03)))
        if kind == "STRIKE":
            self.kn = onepole_inv(recip(dec * F(0.25)))
            self.cn = F(0.15) * c["udust"]
        elif kind == "DUST":
            dens = expmap(c["DUST"], 5.0, 3000.0) * (F(0.5) + self.vel)
            self.pd = dens * INVR
            self.kd = onepole_inv(recip(dec))
            self.ga = F(2.0) * rsqrt(max(dens * dec, F(1.0)))        # 1 / sqrt(max(dens dec, 1) / 4)
        elif kind == "PULSE":
            ub3 = c["ubend"] * F(3.0)
            c2 = (f0 * F(2.0)) * INVR
            inc0 = c2 * exp2(ub3 * self.pe)
            self.pe = self.pe * K_PE
            inc1 = c2 * exp2(ub3 * self.pe)
            self.inc0, self.dinc = inc0, (inc1 - inc0) * F(1.0 / BLOCK)
            self.kep = onepole_inv(recip(dec * F(0.3)))
        elif kind == "TZFM":
            self.tz.setup(f0, c["side"], max(c["utz"], F(0.15)), dec)

    def __call__(self) -> np.float32:
        k = self.k
        if k % BLOCK == 0:
            self._setup()
        kind, rng = self.kind, self.rng
        pulse = F(0.0)
        rest = F(0.0)
        if kind == "STRIKE":
            if k < self.pn:
                pulse = (F(1.0) - cos_t(F(k) * self.pinv)) * self.pinv
            if self.cn != F(0.0):
                rest = (rng.gauss() * self.en) * self.cn
                self.en = _fl(self.en * self.kn)
        elif kind == "DUST":
            ev = F(0.0)
            if rng.u01() < self.pd * self.en:
                ev = rng.bi() * self.ga
            self.en = _fl(self.en * self.kd)
            rest = self.grain(ev)
        elif kind == "PULSE":
            self.ph = frac(self.ph + (self.inc0 + F(k % BLOCK) * self.dinc))
            rest = sin_t(self.ph) * self.ep
            self.ep = _fl(self.ep * self.kep)
        else:
            rest = self.tz()
        tg = TG[kind]
        x = (pulse + rest) * tg
        if self.burst is not None:
            x = x + self.burst() * TG["TZFM"]
        self.k = k + 1
        return x * self.vel

K_PE = F(math.exp(-BLOCK / (0.01 * RATE)))       # PULSE's pitch envelope (10 ms), a block


class Exciter:
    """One exciter. Impulsive kinds return their block of excitation (`Gen`, and under ATK
    the model's window, exactly); BOW and BLOW return zeros and leave this block's pressure
    and speed (or breath) for the body loop's force (`force_fn`).

    ATK (impulsive): the model convolves the excitation with w[k] = (k/(m-1))^2, k < m, over
    its sum. Causally, by the window's moments in age a = n - j (0 <= a < m):
    B0 = sum x, B1 = sum x a, B2 = sum x a^2 and y[n] = cS B2, cS = 6 / ((m-1) m (2m-1)).
    A sample ages all of them (B2 += 2 B1 + B0, B1 += B0), takes in x_n at age 0 and lets go
    of x_{n-m} at age m (B0 -= x, B1 -= m x, B2 -= m^2 x), which a second Gen, started m
    samples late with the same seed and the strike's latched controls, replays exactly
    (under ATK the exciter's controls are latched at the strike). Those integrator sums keep
    every rounding they ever made, and it grows with the square of their age; so there are
    two, staggered: each restarts from zero every 2m samples (taking in only what came after
    its restart, letting go only of that), is whole again m samples later, and the output is
    read from the one that is whole. No sum lives longer than 2m samples, so the rounding is
    bounded whatever the excitation's length. The output stops at the exciter's end, as the
    model's [:n]. Against an exact float64 convolution of the same stream:
    test_fascia_live.test_atk_window_precision."""

    DRIVEN = ("BOW", "BLOW")

    def __init__(self, kind: str, q: dict, f0, vel, rng: XS, seed: int, phase=None):
        self.kind, self.vel, self.rng = kind, F(vel), rng
        self.t = 0
        self.atk = expmap(q["ATK"], 0.0002, 0.5) if q["ATK"] > 0 else F(0.0)
        self.driven = kind in self.DRIVEN
        self.done = False
        self.n_end = 1
        self.latched = None
        if not self.driven:
            self.gen = Gen(kind, q, f0, vel, seed)
            self.lag = None
            if self.atk > F(0.0):
                m = max(int(np.trunc(self.atk * F(RATE))), 2)
                self.am = m
                self.cS = F(6.0) * recip((F(m - 1) * F(m)) * F(2 * m - 1))
                self.fm, self.fm2 = F(m), F(m) * F(m)
                # two staggered windows: [restart sample, B0, B1, B2]; the second starts at m
                self.acc = [[0, F(0.0), F(0.0), F(0.0)], [m, F(0.0), F(0.0), F(0.0)]]
                self.lag = Gen(kind, q, f0, vel, seed)
        # driven
        self.oq = F(1.0)                                 # the onset's exp(-t / (atk/3))
        self.hold = F(1.0)
        if kind == "BOW":
            r = rng.u01() if phase is None else F(phase)
            self.sph = F(r * F(6.0) * F(1.0 / (2.0 * math.pi)))
            self.grit = F(0.0)
        if kind == "BLOW":
            self.breath = F(0.0)
        self.press = None

    def gen_block(self, c: dict, f0):
        """this block's 32 samples (impulsive: the excitation; driven: zeros, with
        self.press and self.drive set). C: the block's controls."""
        k0 = self.t
        if self.atk > F(0.0) and not self.driven:
            if self.latched is None:
                self.latched = (c, F(f0))
            c, f0 = self.latched
        self.n_end = int(np.trunc((c["dec"] * F(4.0) + F(0.01) + self.atk) * F(RATE)))
        out = np.zeros(BLOCK, F)
        if self.done or k0 >= self.n_end:
            self.done = True
            self.press = None
            self.t = k0 + BLOCK
            return out
        if self.driven:
            return self._driven(c, k0, out)
        g = self.gen
        g.c, g.f0 = c, F(f0)
        lag = self.lag
        if lag is not None:
            lag.c, lag.f0 = c, F(f0)
        for j in range(BLOCK):
            k = k0 + j
            if k >= self.n_end:
                self.done = True
                break
            x = g()
            if lag is None:
                out[j] = x
                continue
            m = self.am
            xo = lag() if k >= m else F(0.0)                  # x_{k-m}, now of age m: out
            y = F(0.0)
            for a in self.acc:
                if k == a[0] + 2 * m:                         # its time to start afresh
                    a[0], a[1], a[2], a[3] = k, F(0.0), F(0.0), F(0.0)
                if k < a[0]:
                    continue
                a[3] = (a[3] + F(2.0) * a[2]) + a[1]          # every sample a year older
                a[2] = a[2] + a[1]
                a[1] = a[1] + x
                if k - m >= a[0]:                             # x_{k-m} was this window's
                    a[1] = a[1] - xo
                    a[2] = a[2] - xo * self.fm
                    a[3] = a[3] - xo * self.fm2
                if a[0] == 0 or k >= a[0] + m:                # whole: everything since k - m
                    y = a[3]
            out[j] = y * self.cS
        self.t = k0 + BLOCK
        if self.t >= self.n_end:
            self.done = True
        return out

    def _driven(self, c: dict, k0: int, out: np.ndarray) -> np.ndarray:
        """BOW: press = onset x hold(80 ms) x (0.2 + 0.8 vel), speed (0.7 Hz) x (1 + grit/2);
        BLOW: press = onset x hold(60 ms) x (0.4 + 0.6 vel) x (1 + breath)."""
        rng, vel = self.rng, self.vel
        decR = c["dec"] * F(RATE)
        bow = self.kind == "BOW"
        kh = F(math.exp(-1.0 / ((0.08 if bow else 0.06) * RATE)))
        pv = (F(0.2) + F(0.8) * vel) if bow else (F(0.4) + F(0.6) * vel)
        ko = onepole_inv(recip(self.atk * F(1.0 / 3.0))) if self.atk > F(0.0) else None
        press = np.zeros(BLOCK, F)
        drive = np.zeros(BLOCK, F)
        if bow:
            pg = expmap(c["DUST"], 20.0, 4000.0) * INVR
            ud = c["udust"]
            sinc = F(0.7) * INVR
        else:
            cut = F(400.0) * exp2(c["uhard"] * F(math.log2(30.0)))
            a = exp2(cut * F(-2.0 * math.pi / math.log(2.0) / RATE))
            ca = F(1.0) - a
            bg = F(0.3) + F(0.7) * c["udust"]
        n = 0
        for j in range(BLOCK):
            k = k0 + j
            if k >= self.n_end:
                break
            if ko is None:
                on = min(F(k) * K_RAMP, F(1.0))
            else:
                on = F(1.0) - self.oq
                self.oq = self.oq * ko
            if F(k) > decR:
                self.hold = self.hold * kh
            pr = (on * self.hold) * pv
            if bow:
                sp = F(0.25) + F(0.15) * sin_t(self.sph)
                self.sph = frac(self.sph + sinc)
                if ud != F(0.0):
                    ev = F(0.0)
                    if rng.u01() < pg:
                        ev = rng.bi()
                    self.grit = self.grit * F(0.6) + ev
                    sp = sp * (F(1.0) + (self.grit * ud) * F(0.5))
                else:
                    self.grit = F(0.0)
                press[j], drive[j] = pr, sp
            else:
                self.breath = ca * rng.gauss() + a * self.breath
                press[j] = pr * (F(1.0) + self.breath * bg)
            n = j + 1
        self.press = press[:n] if n else None
        self.drive = drive
        self.t = k0 + BLOCK
        if self.t >= self.n_end:
            self.done = True
        return out

    def force_fn(self, c: dict, g):
        """the force on body A at sample j given its contact velocity v (None: no force)"""
        if not self.driven or self.press is None or g < F(1e-4):
            return None
        press, n = self.press, len(self.press)
        if self.kind == "BOW":
            slope = F(1.5) + F(6.0) * (F(1.0) - c["hard"])
            gb = (F(4.0) * F(g)) * (F(0.5) + F(1.5) * c["hard"])
            drive = self.drive

            def f(j, v):
                if j >= n:
                    return F(0.0)
                return bow_table(drive[j] - v, slope) * press[j] * gb
        else:
            gf = F(0.03) * F(g)

            def f(j, v):
                if j >= n:
                    return F(0.0)
                dp = press[j] - v * F(0.6)
                return (dp * max(F(0.0), F(1.0) - abs(dp) * F(0.9))) * gf
        return f

    def flush(self):
        """(the generators flush their own envelopes, a sample at a time, so that ATK's lagged
        copy replays them exactly)"""
        if self.driven:
            self.oq = _fl(self.oq)
            self.hold = _fl(self.hold)
            if self.kind == "BOW":
                self.grit = _fl(self.grit)
            else:
                self.breath = _fl(self.breath)


BOW_LO, BOW_HI = F(0.25 / 0.245), F(100.0)       # y^4 where k/4 reaches 0.245 and 0.0025


def bow_table(dv, slope):
    """model.bow_table: dv x clamp(0.25 / (|dv slope| + 0.75)^4, 0.0025, 0.245); the y^4 is
    clamped to where those limits bite before its reciprocal."""
    y = abs(F(dv) * F(slope)) + F(0.75)
    y2 = y * y
    y4 = min(max(y2 * y2, BOW_LO), BOW_HI)
    kq = min(max(F(0.25) * recip(y4), F(0.0025)), F(0.245))
    return F(dv) * kq


# -- clicks ---------------------------------------------------------------------------------
class Click:
    """CLIK's transient (model.click), per sample, straight to the output."""

    def __init__(self, kind: str, hard, level, rng: XS):
        self.kind, self.rng, self.k = kind, rng, 0
        self.level = F(level)
        h1 = F(1.0) - F(hard)
        if kind == "SNAP":
            self.n = max(int(np.trunc((F(0.00015) + F(0.0006) * h1) * F(RATE))), 3)
            self.ninv = recip(F(self.n))
            self.len = self.n + 1
            self.gain = F(self.n) * F(0.35)
        elif kind == "TICK":
            self.len = int(0.004 * RATE)
            self.inc = (F(2500.0) + F(3000.0) * F(hard)) * INVR
            self.ke = onepole_inv(recip(F(0.0004) + F(0.0008) * h1))
        elif kind == "NOISE":
            self.len = int(0.012 * RATE)
            self.prev = F(0.0)
            self.ke = onepole_inv(recip(F(0.0008) + F(0.003) * h1))
        else:
            self.len = int(0.06 * RATE)
            self.ke = onepole_inv(recip(F(0.012) + F(0.01) * h1))
            self.kp = F(math.exp(-1.0 / (0.008 * RATE)))
            self.pe = F(1.0)
        self.ph = F(0.0)
        self.e = F(1.0)

    @property
    def done(self) -> bool:
        return self.k >= self.len

    def _hann(self, j: int):
        if j < 0 or j >= self.n:
            return F(0.0)
        return F(0.5) - F(0.5) * cos_t(F(j) * self.ninv)

    def block(self) -> np.ndarray:
        out = np.zeros(BLOCK, F)
        for j in range(BLOCK):
            k = self.k
            if k >= self.len:
                break
            if self.kind == "SNAP":
                x = (self._hann(k) - self._hann(k - 1)) * self.gain
            elif self.kind == "TICK":
                x = sin_t(self.ph) * self.e
                self.ph = frac(self.ph + self.inc)
                self.e = self.e * self.ke
            elif self.kind == "NOISE":
                g = self.rng.gauss()
                x = ((g - self.prev) * self.e) * F(0.5)
                self.prev = g
                self.e = self.e * self.ke
            else:
                self.ph = frac(self.ph + (F(40.0) + F(50.0) * self.pe) * INVR)
                self.pe = self.pe * self.kp
                x = sin_t(self.ph) * self.e
                self.e = self.e * self.ke
            out[j] = x * self.level
            self.k = k + 1
        return out


# -- after the bodies -----------------------------------------------------------------------
class SVF:
    """Simper's trapezoidal SVF, vectorised over bands: low = v2, band = v1 (RBJ's band-pass
    of constant peak gain is k v1, its low-pass v2: the model's biquads, exactly in exact
    arithmetic, and well-conditioned at low frequencies in float32)."""

    def __init__(self, n: int = 1):
        self.ic1 = np.zeros(n, F)
        self.ic2 = np.zeros(n, F)
        self.key = None

    def set(self, fc, q) -> None:
        fc = np.minimum(np.asarray(fc, F), F_HI)
        h = fc * H_SCALE
        g = sinp(h) * recip(cosp(h))                     # tan(w/2)
        self.kk = F(1.0) * recip(F(q)) if np.ndim(q) == 0 else recip(np.asarray(q, F))
        self.a1 = recip(F(1.0) + g * (g + self.kk))
        self.a2 = g * self.a1
        self.a3 = g * self.a2

    def tick(self, x):
        v3 = x - self.ic2
        v1 = self.a1 * self.ic1 + self.a2 * v3
        v2 = (self.ic2 + self.a2 * self.ic1) + self.a3 * v3
        self.ic1 = F(2.0) * v1 - self.ic1
        self.ic2 = F(2.0) * v2 - self.ic2
        return v1, v2

    def flush(self) -> None:
        for a in (self.ic1, self.ic2):
            a[np.abs(a) < F(FLOOR)] = F(0.0)


def _shift_coeffs():
    from ..shft import live as SL
    return np.array(SL.A2, F), np.array(SL.B2, F)


class Shifter:
    """SHIFT: SHFT's Hilbert pair (two chains of four all-passes in z^-2, chain A one sample
    late is I, chain B is Q, Q lagging I by 90 degrees) and a quadrature oscillator:
    y = I cos + Q sin, so that a positive shift moves the spectrum up as the model's
    Re(analytic x e^(i 2 pi hz t)) does. The unwanted sideband is 45..57 dB down (the model's
    FFT Hilbert: ideal); the pair's phase dispersion is inaudible on its own
    (test_fascia_live.test_shift_moves_up_and_rejects_the_image)."""

    def __init__(self):
        self.A2, self.B2 = _shift_coeffs()
        self.in1 = F(0.0)
        self.in2 = F(0.0)
        self.ay1, self.ay2 = np.zeros(4, F), np.zeros(4, F)
        self.by1, self.by2 = np.zeros(4, F), np.zeros(4, F)
        self.iprev = F(0.0)
        self.ph = F(0.0)

    @staticmethod
    def _chain(x, in2, c2, y1, y2):
        old2 = in2
        for i in range(4):
            y = c2[i] * (x + y2[i]) - old2
            old2 = y2[i]
            y2[i] = y1[i]
            y1[i] = y
            x = y
        return x

    def tick(self, x, inc):
        ya = self._chain(x, self.in2, self.A2, self.ay1, self.ay2)
        yb = self._chain(x, self.in2, self.B2, self.by1, self.by2)
        self.in2, self.in1 = self.in1, x
        i, self.iprev = self.iprev, ya
        y = i * cos_t(self.ph) + yb * sin_t(self.ph)
        self.ph = frac(self.ph + inc)
        return y

    def flush(self) -> None:
        for a in (self.ay1, self.ay2, self.by1, self.by2):
            a[np.abs(a) < F(FLOOR)] = F(0.0)


WATER_USE = tuple(M.WATER_USE)


class Water:
    """WATR (model.water), causal: per band a modulator band-pass (Q 3) and a carrier (Q 14,
    4..8 % high), a fast and a slow follower, wet += car min((e/es)^2, 6); the body under
    1.8 x the note is two cascaded low-passes; the wet skin's level matches the dry skin's by
    the running sums since the strike."""

    KA1, KR1 = F(math.exp(-1 / (0.0008 * RATE))), F(math.exp(-1 / (0.012 * RATE)))
    KA2, KR2 = F(math.exp(-1 / (0.02 * RATE))), F(math.exp(-1 / (0.15 * RATE)))
    GMAX = F(16.0)

    def __init__(self):
        self.lp1, self.lp2 = SVF(1), SVF(1)
        self.an, self.car = SVF(6), SVF(6)
        self.e = np.zeros(6, F)
        self.es = np.zeros(6, F)
        self.ss = F(0.0)
        self.sw = F(0.0)
        self.g = None
        self.amt = None
        self.key = None

    def set(self, f0, l2f0, amt) -> None:
        key = (float(f0), float(amt))
        if key == self.key:
            return
        self.key = key
        self.lp1.set(f0 * F(1.8), F(math.sqrt(0.5)))
        self.lp2.set(f0 * F(1.8), F(math.sqrt(0.5)))
        # bands f0 2.2 (top / (f0 2.2))^(k/7): log2 of the span = min(5, log2(9000/2.2) - log2 f0)
        span = min(F(5.0), F(math.log2(9000.0 / 2.2)) - F(l2f0))
        b0 = F(f0) * F(2.2)
        fc = np.array([b0 * exp2(span * F(k / 7.0)) for k in WATER_USE], F)
        self.use = fc <= F(0.4 * RATE)
        fc = np.where(self.use, fc, F(1000.0)).astype(F)
        self.an.set(fc, F(3.0))
        self.car.set(fc * (F(1.04) + F(0.04) * F(amt)), F(14.0))

    def block(self, z: np.ndarray, amt) -> np.ndarray:
        n = len(z)
        body = np.empty(n, F)
        skin = np.empty(n, F)
        wet = np.empty(n, F)
        use = self.use
        for j in range(n):
            _, l1 = self.lp1.tick(np.array([z[j]], F))
            _, l2 = self.lp2.tick(l1)
            b = l2[0]
            s = z[j] - b
            body[j], skin[j] = b, s
            sv = np.full(6, s, F)
            v1a, _ = self.an.tick(sv)
            an = self.an.kk * v1a
            v1c, _ = self.car.tick(sv)
            car = self.car.kk * v1c
            av = np.abs(an)
            k1 = np.where(av > self.e, self.KA1, self.KR1)
            self.e = av + (self.e - av) * k1
            k2 = np.where(av > self.es, self.KA2, self.KR2)
            self.es = av + (self.es - av) * k2
            ratio = self.e * recip(self.es + F(1e-6))
            gate = np.minimum(ratio * ratio, F(6.0))
            w = np.where(use, car * gate, F(0.0)).astype(F)
            wet[j] = seqsum(w)
        for j in range(n):
            self.ss = self.ss + skin[j] * skin[j]
            self.sw = self.sw + wet[j] * wet[j]
        g = sqrt(self.ss * recip(self.sw)) if self.sw > F(1e-20) else F(1.0)
        g = min(g, self.GMAX)
        g0 = g if self.g is None else self.g
        self.g = g
        steps = np.arange(1, n + 1, dtype=F) * F(1.0 / BLOCK)
        ramp = g0 + (g - g0) * steps
        a1 = F(amt)
        a0 = a1 if self.amt is None else self.amt
        self.amt = a1
        a = a1 if a0 == a1 else a0 + (a1 - a0) * steps    # the amount ramps across the block
        return (body + skin * (F(1.0) - a)) + (wet * ramp) * a

    def flush(self) -> None:
        for s in (self.lp1, self.lp2, self.an, self.car):
            s.flush()
        self.e[np.abs(self.e) < F(FLOOR)] = F(0.0)
        self.es[np.abs(self.es) < F(FLOOR)] = F(0.0)


VOWELS = np.array(M.VOWELS, F)
LIM_TH = F(M.LIMIT[0])
LIM_KR = F(math.exp(-BLOCK / (M.LIMIT[2] * RATE)))
DC_A = F(math.exp(-2 * math.pi * 20.0 / RATE))
K_CHIRP = F(math.exp(-BLOCK / (0.004 * RATE)))
SQ2 = F(1.414)


def block_controls(q: dict, vel) -> dict:
    """everything constant across a block, from the engine's controls"""
    hv = F(0.5) + F(0.5) * F(vel)
    hard = u(q["HARD"]) * hv
    inv_t60 = F(1.0 / 0.03) * exp2(-u(127 - q["DAMP"]) * F(math.log2(400.0)))
    mix = u(q["MIX"]) * F(math.pi / 2)
    side = u(q["SIDE"])
    return {
        "hard": hard, "uhard": u(q["HARD"]), "tilt": F(1.2) * (F(1.0) - hard),
        "geom_e": F(0.6) + F(0.8) * u(q["GEOM"]),
        "inv_t60": inv_t60, "matl": u(q["MATL"]), "pos": F(0.02) + F(0.48) * u(q["POS"]),
        "bend": (u(q["BEND"]) * F(7.0)) * (F(0.4) + F(0.6) * F(vel)),
        "ubend": u(q["BEND"]),
        "chirp": (u(q["HARD"]) * F(vel)) * F(0.6),
        "lpg": u(q["LPG"]) * F(6.0), "ulpg": u(q["LPG"]),
        "coup": u(q["COUP"]), "xmod": M.XMODS[ichoice("XMOD", q["XMOD"])],
        "fdbk": u(q["FDBK"]), "buzz": u(q["BUZZ"]),
        "morph": u(q["MORPH"]) * F(1.4),
        "ga": max(cosp(mix), F(0.0)), "gb": sinp(mix),
        "dec": expmap(q["DEC"], 0.004, 2.0),
        "DUST": q["DUST"], "udust": u(q["DUST"]), "utz": u(q["TZFM"]),
        "side": F(0.5) + F(6.5) * (side * sqrt(side)),
        "ring": q["RING"], "shift": q["SHIFT"], "form": q["FORM"], "watr": q["WATR"],
        "fold": q["FOLD"], "char": q["CHAR"], "LPG": q["LPG"], "TUNE": q["TUNE"],
    }


# -- the voice ------------------------------------------------------------------------------
class Voice:
    def __init__(self, seed: int = 1, twins: int = TWINS):
        self.seed, self.twins = seed, twins
        self.on = False
        self.pending = None
        self.fading = False
        self.faults = 0
        self.cost = 0
        self.blocks = 0
        self.end = None

    # -- life ----------------------------------------------------------------------------
    @property
    def idle(self) -> bool:
        return not self.on and self.pending is None

    def rest(self) -> None:
        self.on = False
        self.pending = None
        self.fading = False

    def note_on(self, note, vel=1.0, draws=None) -> None:
        """arm a strike for the next block (a steal if the voice is sounding: that block fades
        the old sound out, the strike is the block after)"""
        self.pending = (note_ok(note), vel_ok(vel), draws)
        self.fading = self.on

    def _strike(self, controls) -> None:
        note, vel, draws = self.pending
        self.pending = None
        self.note, self.vel = note, vel
        q = engine(controls)
        self.rng = XS(self.seed)
        vary = u(q["VARY"]) * F(3.2)
        self.vary = vary
        f0, _ = f0_of(note, q["TUNE"])
        ka = M.BODIES[choice("BODA", q["BODA"])]
        kb = M.BODIES[choice("BODB", q["BODB"])]
        da = db = None
        if draws is not None:
            da, db = draws.get("a"), draws.get("b")
        c0 = block_controls(q, vel)
        st = (c0["geom_e"], c0["inv_t60"], c0["matl"], c0["pos"], c0["tilt"])
        self.a = Body(ka, f0, self.rng, vary, self.twins, da, st)
        self.bratio = F(M.B_RATIO.get(kb, 1.0))
        stb = st[:3] + (c0["pos"] * F(0.73),) + st[4:]
        self.b = None if kb == "OFF" else Body(kb, f0 * self.bratio, self.rng, vary, self.twins, db, stb)
        ta = M.TYPES[choice("TYPA", q["TYPA"])]
        tb = M.TYPES[choice("TYPB", q["TYPB"])]
        ph = draws.get("phase", (None, None)) if draws is not None else (None, None)
        self.ea = Exciter(ta, q, f0, vel, self.rng, self.seed * 4 + 1, ph[0])
        self.eb = Exciter(tb, q, f0, vel, self.rng, self.seed * 4 + 2, ph[1])
        hard = u(q["HARD"]) * (F(0.5) + F(0.5) * vel)
        self.clk = None
        if q["CLIK"] > 0:
            ck = M.CLICKS[ichoice("CTYP", q["CTYP"])]
            self.clk = Click(ck, hard, (u(q["CLIK"]) * vel) * F(0.5), self.rng)
        self.t = 0
        self.cenv = F(1.0)                               # the chirp's exp(-t / 4 ms), a block
        self.lenv = F(1.0)                               # the LPG contour's (body loss)
        self.menv = F(1.0)                               # MORPH's exp(-t / tau)
        self.venv = F(1.0)                               # the LPG's VCA, a sample
        self.ob_prev = np.zeros(BLOCK, F)
        self.rattle = F(0.0)
        self.dc_x = F(0.0)
        self.dc_y = F(0.0)
        self.lim = F(0.0)
        self.ring_ph = F(0.0)
        self.lv, self.par = {}, {}
        self.pitch_prev = None
        self.shift = None
        self.form = None
        self.form_v = None
        self.water = None
        self.on = True
        self.fading = False
        self.end = None
        self.blocks = 0

    # -- a block -------------------------------------------------------------------------
    def block(self, controls=None) -> np.ndarray:
        if self.fading and self.on:
            out = self._run(controls)
            self.fading = False
            self.on = False
            return (out * (F(1.0) - np.arange(1, BLOCK + 1, dtype=F) * F(1.0 / BLOCK))).astype(F)
        if self.pending is not None:
            self._strike(controls)
        if not self.on:
            self.cost = 0
            return np.zeros(BLOCK, F)
        return self._run(controls)

    def _run(self, controls) -> np.ndarray:
        q = engine(controls)
        c = block_controls(q, self.vel)
        cost = COST["block"]
        f0, l2f0 = f0_of(self.note, q["TUNE"])
        a, b = self.a, self.b
        # the exciters
        x = np.zeros(BLOCK, F)
        has_x = False
        for e, g in ((self.ea, c["ga"]), (self.eb, c["gb"])):
            if e.done:
                e.press = None                           # its last block was the last
                continue
            s = e.gen_block(c, f0)
            cost += COST["exc_" + e.kind.lower()] * BLOCK
            if not e.driven:
                x = x + s * g
                has_x = True
        exc_done = self.ea.done and self.eb.done
        ch = c["chirp"] * self.cenv
        self.cenv = _fl(self.cenv * K_CHIRP)
        bend = exp2((c["bend"] * a.level + ch) * F(1.0 / 12.0))
        gl = self.lenv
        self.lenv = _fl(self.lenv * onepole_inv(min(c["inv_t60"] * F(4.0), F(100.0)), BLOCK))
        loss = c["lpg"] * (F(1.0) - gl)
        xmod = c["xmod"]
        back = c["fdbk"] + (c["coup"] if xmod == "TRADE" else F(0.0))
        if b is not None and back > F(0.0):
            x = x + (tanh_r(self.ob_prev * F(2.0)) * back) * F(0.08)
            has_x = has_x or bool(np.any(self.ob_prev != 0))
            cost += COST["fdbk"] * BLOCK
        # TUNE or GEOM moved since the last block: each mode's d is rescaled by its frequency
        # ratio, so a resonator keeps its amplitude while its pitch moves (d ~ A w). BEND's
        # glide and the drift are not (the model's own resonators, as approved).
        pitch = (l2f0, c["geom_e"])
        retune = self.pitch_prev is not None and pitch != self.pitch_prev
        self.pitch_prev = pitch
        mexp = F(0.0)
        # MORPH's depth slews a quarter of the way a block (2.7 ms): from the strike's value,
        # so a held MORPH is the model's; a moving one does not step the modes' weights
        m0 = None if self.blocks == 0 else self.morph
        self.morph = c["morph"] if self.blocks == 0 else self.morph + (c["morph"] - self.morph) * F(0.25)
        if self.morph < F(1e-6):
            self.morph = F(0.0)
        for body in (a, b):
            if body is not None:
                body.ramp_og = m0 is not None and m0 != self.morph
        if self.morph > F(0.0):
            prog = F(1.0) - self.menv
            mexp = (self.morph * prog) * F(0.5)
        self.menv = _fl(self.menv * onepole_inv(min(c["inv_t60"] * F(1.0 / 0.35), F(20.0)), BLOCK))
        a.coeffs(self.rng, f0 * bend, c["geom_e"], c["inv_t60"], c["matl"], loss, c["pos"],
                 c["tilt"], mexp)
        if retune:
            a.retune()
            cost += COST["retune"] * a.n
        forces = [ff for ff in (self.ea.force_fn(c, c["ga"]), self.eb.force_fn(c, c["gb"]))
                  if ff is not None]
        xa = x if has_x else None
        if forces:
            if len(forces) == 1:
                force = forces[0]
            else:
                fa, fb = forces

                def force(j, v):
                    return fa(j, v) + fb(j, v)
            na = a.n
            oa = a.run_driven(force, xa)
            cost += COST["mode_block"] * na + COST["mode_driven"] * na * BLOCK \
                + COST["force"] * BLOCK * len(forces)
        else:
            na = a.active(has_x)
            oa = a.run(xa)
            cost += COST["mode_block"] * na + (COST["mode_in"] if has_x else COST["mode"]) * na * BLOCK
        if a.og is not None:
            cost += COST["og"] * na * BLOCK
        # BUZZ
        bz = None
        if c["buzz"] > F(0.0):
            gap = F(0.25) * (F(1.0) - c["buzz"]) + F(0.004)
            ex = np.maximum(np.abs(oa) - gap, F(0.0))
            nz = np.array([self.rng.gauss() for _ in range(BLOCK)], F)
            prev = np.concatenate([[self.rattle], nz[:-1]]).astype(F)
            self.rattle = nz[-1]
            hp = nz - prev
            bz = ((hp * ex) * F(0.8) + (np.sign(oa).astype(F) * ex) * F(0.5)) * c["buzz"]
            cost += COST["buzz"] * BLOCK
        # body B
        ob = np.zeros(BLOCK, F)
        if b is not None:
            inv_tb = c["inv_t60"]
            bb = exp2((c["bend"] * b.level + ch) * F(1.0 / 12.0))
            xb = x if bz is None else x + bz * F(0.5)
            has_xb = has_x or bz is not None
            coup = c["coup"]
            if xmod in ("EXCITE", "TRADE"):
                xb = (F(1.0) - coup) * xb + (coup * np.minimum(np.maximum(oa, F(-1.0)), F(1.0))) * F(0.5)
                has_xb = has_xb or (coup > F(0.0) and bool(np.any(oa != 0)))
            elif xmod == "BEND":
                bb = bb * exp2(coup * a.level)
            elif xmod == "CHOKE":
                inv_tb = inv_tb * (F(1.0) + (coup * F(30.0)) * a.level)
            b.coeffs(self.rng, (f0 * self.bratio) * bb, c["geom_e"], inv_tb, c["matl"], loss,
                     c["pos"] * F(0.73), c["tilt"], mexp)
            if retune:
                b.retune()
                cost += COST["retune"] * b.n
            nb = b.active(has_xb)
            ob = b.run(xb if has_xb else None)
            cost += COST["mode_block"] * nb + (COST["mode_in"] if has_xb else COST["mode"]) * nb * BLOCK
            if b.og is not None:
                cost += COST["og"] * nb * BLOCK
            if xmod == "TRADE":
                a.scale_y(F(1.0) - coup * F(0.002))
            self.ob_prev = ob
        y = oa + ob
        if bz is not None:
            y = y + bz
        ra, rb = oa, ob
        a.flush()
        if b is not None:
            b.flush()
        self.ea.flush()
        self.eb.flush()
        # the IDLE rule (model.Voice.render): exciters done, the block and the bodies quiet
        ended = False
        if exc_done and (self.clk is None or self.clk.done) and F(np.max(np.abs(y))) < IDLE \
                and a.energy() < IDLE and (b is None or b.energy() < IDLE):
            ended = True
        if self.clk is not None and not self.clk.done:
            y = y + self.clk.block()
            cost += COST["click"] * BLOCK
        # the DC block, the level guard
        z = np.empty(BLOCK, F)
        x1, y1 = self.dc_x, self.dc_y
        for j in range(BLOCK):
            y1 = (y[j] - x1) + DC_A * y1
            x1 = y[j]
            z[j] = y1
        self.dc_x, self.dc_y = x1, F(0.0) if abs(y1) < FLOOR else y1
        pk = F(np.max(np.abs(z)))
        self.lim = pk if pk > self.lim else self.lim * LIM_KR
        if self.lim > LIM_TH:
            z = z * (LIM_TH * recip(self.lim))
        z, pc = self._post(z, ra, rb, c, q, f0, l2f0)
        cost += pc + COST["post"] * BLOCK
        self.t += BLOCK
        self.blocks += 1
        self.cost = cost
        if not (a.ok() and (b is None or b.ok()) and np.all(np.isfinite(z))):
            self.faults += 1
            self.on = False
            self.end = self.t / RATE
            return np.zeros(BLOCK, F)
        if ended:
            self.on = False
            self.end = self.t / RATE
        return z

    def _post(self, z, ra, rb, c, q, f0, l2f0):
        """RING, SHIFT, FORM, WATR, FOLD, CHAR, the LPG's VCA, the knee (model.Voice.post).
        A stage on at the strike is simply on (the model's path, exactly); one that a p-lock,
        slide or LFO turns on or off mid-note crossfades over FADE blocks (2.7 ms) and keeps
        running, on its last settings, until it has faded out: no step, no cold-start click."""
        cost = 0
        first = self.blocks == 0
        ons = {"ring": c["ring"] > 0, "shift": c["shift"] != 64, "form": c["form"] > 0,
               "watr": c["watr"] > 0, "fold": c["fold"] > 0, "char": c["char"] > 0,
               "vca": c["LPG"] > 0}
        kv = onepole_inv(min(c["inv_t60"], F(100.0)))
        for st in POST_STAGES:
            on = ons[st]
            lv0 = self.lv.get(st, F(0.0))
            if first:
                lv0 = lv1 = F(1.0) if on else F(0.0)
            else:
                lv1 = min(lv0 + FADE_STEP, F(1.0)) if on else max(lv0 - FADE_STEP, F(0.0))
            self.lv[st] = lv1
            p0 = self.par.get(st)
            if on:
                self.par[st] = self._par(st, c)
            if first or st not in RAMPED:
                p0 = None
            if st == "vca":
                # the envelope runs whether or not the VCA is heard (model: exp(-t / T60))
                g = np.empty(BLOCK, F)
                e = self.venv
                for j in range(BLOCK):
                    g[j] = e
                    e = e * kv
                self.venv = _fl(e)
            if lv0 == F(0.0) and lv1 == F(0.0):
                self._drop(st)
                continue
            w, k = self._stage(st, z, ra, rb, f0, l2f0, self.par[st], g if st == "vca" else None,
                               p0 if p0 is not None and p0 != self.par[st] else None)
            cost += k
            if lv0 == F(1.0) and lv1 == F(1.0):
                z = w
            else:
                r = lv0 + (lv1 - lv0) * (np.arange(1, BLOCK + 1, dtype=F) * F(1.0 / BLOCK))
                z = z + r * (w - z)
        out = tanh_r(z * F(1.5)) * F(1.0 / 1.5)
        return np.asarray(out, F), cost

    def _par(self, st, c):
        if st == "ring":
            return u(c["ring"])
        if st == "shift":
            s = (F(c["shift"]) - F(64.0)) * F(1.0 / 63.0)
            hz = F(5.0) * exp2(abs(s) * F(math.log2(400.0)))
            return (hz if s > F(0.0) else -hz) * INVR
        if st == "form":
            return c["form"]
        if st == "watr":
            return u(c["watr"])
        if st == "fold":
            return u(c["fold"])
        if st == "char":
            return u(c["char"])
        return c["ulpg"]

    def _drop(self, st) -> None:
        """a stage faded out: its state goes (it starts from rest when it comes back)"""
        if st == "shift":
            self.shift = None
        elif st == "form":
            self.form, self.form_v = None, None
            self.__dict__.pop("form_wet", None)
        elif st == "watr":
            self.water = None

    def _stage(self, st, z, ra, rb, f0, l2f0, par, g, p0=None):
        """one stage's output; P0: the last block's setting when it moved (RAMPED stages: the
        setting ramps across the block, or the two settings' outputs crossfade)"""
        r = None if p0 is None else np.arange(1, BLOCK + 1, dtype=F) * F(1.0 / BLOCK)
        if st == "ring":
            d = par if r is None else F(p0) + (F(par) - F(p0)) * r
            if self.b is not None:
                car = rb * F(8.0)
                cost = COST["ring"] * BLOCK
            else:
                inc = (f0 * SQ2) * INVR
                car = np.empty(BLOCK, F)
                for j in range(BLOCK):
                    car[j] = sin_t(self.ring_ph)
                    self.ring_ph = frac(self.ring_ph + inc)
                cost = (COST["ring"] + COST["osc"]) * BLOCK
            return z * (F(1.0) - d) + (tanh_r(ra * F(8.0)) * tanh_r(car)) * (F(0.25) * d), cost
        if st == "shift":
            if self.shift is None:
                self.shift = Shifter()
            zz = np.empty(BLOCK, F)
            for j in range(BLOCK):
                zz[j] = self.shift.tick(z[j], par)
            self.shift.flush()
            return zz, COST["shift"] * BLOCK
        if st == "form":
            cost = COST["form"] * BLOCK
            if self.form is None:
                self.form = SVF(2)
            if self.form_v != par:
                self.form_v = par
                v = u(par) * F(len(M.VOWELS) - 1)
                j = min(int(np.trunc(v)), len(M.VOWELS) - 2)
                fr = v - F(j)
                fc = VOWELS[j] * (F(1.0) - fr) + VOWELS[j + 1] * fr
                self.form.set(fc, F(8.0))
                w1 = min(F(par) * F(1.0 / 16.0), F(1.0)) * F(0.8)
                self.form_w0 = getattr(self, "form_wet", w1)
                self.form_wet = w1
                cost += COST["svf_set"] * 2
            else:
                self.form_w0 = self.form_wet
            w0, w1 = self.form_w0, self.form_wet
            dw = (w1 - w0) * F(1.0 / BLOCK)              # the wet mix ramps across the block
            zz = np.empty(BLOCK, F)
            for j in range(BLOCK):
                v1, _ = self.form.tick(np.array([z[j], z[j]], F))
                bp = self.form.kk * v1
                fsum = bp[0] + bp[1]
                wet = w1 if dw == F(0.0) else w0 + F(j + 1) * dw
                zz[j] = (F(1.0) - wet) * z[j] + (wet * fsum) * F(2.0)
            self.form.flush()
            return zz, cost
        if st == "watr":
            cost = COST["watr"] * BLOCK
            if self.water is None:
                self.water = Water()
            if self.water.key != (float(f0), float(par)):
                cost += COST["svf_set"] * 14
            self.water.set(f0, l2f0, par)
            w = self.water.block(z, par)
            self.water.flush()
            return w, cost
        if st in ("fold", "char"):
            w = self._shape(st, z, par)
            if r is None:
                return w, COST[st] * BLOCK
            w0 = self._shape(st, z, p0)
            return w0 + r * (w - w0), 2 * COST[st] * BLOCK
        ul = par if r is None else F(p0) + (F(par) - F(p0)) * r
        return z * ((F(1.0) - ul * F(0.5)) + (ul * F(0.5)) * g), COST["vca"] * BLOCK

    @staticmethod
    def _shape(st, z, par):
        if st == "fold":
            dr = F(1.0) + F(8.0) * par
            k = (dr * F(4.0)) * F(1.0 / (2 * math.pi))
            return sin_t(frac(z * k)) * (F(0.25) * (F(1.0) - par * F(0.3)))
        dr = F(1.0) + F(20.0) * (par * par)
        b0 = F(0.1) * par
        return tanh_r(z * dr + b0) * recip(tanh_r(dr)) - tanh_r(b0)


POST_STAGES = ("ring", "shift", "form", "watr", "fold", "char", "vca")
RAMPED = ("ring", "fold", "char", "vca")          # memoryless: a moved setting ramps in a block
FADE = 4                                          # blocks a stage takes to fade in or out
FADE_STEP = F(1.0 / FADE)


# -- cost -----------------------------------------------------------------------------------
# Rough DSL scalar-instruction counts (one instruction per F/R op, load, store, compare or
# branch; no multifunction forms). Per sample unless named _block. The mode loop is the
# DSL's unrolled 32-sample body with two modes a pass (their out[j] load/add/store shared).
COST = {
    "block": 400,           # expand, block_controls (a dozen exp2), envelopes, level, idle test
    "mode_block": 135,      # a mode's coefficients: 2..4 exp2, sin/cos, expm1, drift's noise, loads
    "mode": 8,              # a mode a sample, no input: 4 flops, out accumulate (shared), moves
    "mode_in": 11,          # with input: + load x, b x, add
    "mode_driven": 21,      # driven: state and coefficients from memory, v's phi d accumulate
    "og": 1,                # MORPH's output weight
    "force": 30,            # BOW's table (a reciprocal) or BLOW's reed, a sample
    "exc_strike": 34, "exc_dust": 40, "exc_pulse": 22, "exc_tzfm": 40,
    "exc_bow": 40, "exc_blow": 40,          # (the noises: two xorshift draws a sample)
    "fdbk": 26, "buzz": 36, "click": 28,
    "post": 40,             # DC block, the guard's peak, knee (a tanh), store
    "ring": 52, "osc": 10, "shift": 60, "form": 34, "watr": 340, "fold": 16, "char": 28,
    "vca": 4, "svf_set": 45,
    "retune": 18,           # a mode re-expressed for a new pitch (TUNE/GEOM moved): a recip, 5 ops
}


def cost_estimate(controls: dict | None = None, note: float = 60.0) -> dict:
    """A rough per-block instruction count for a voice on CONTROLS (panel), from the stages
    they turn on: 'attack' while the exciters run (a driven exciter makes body A's loop per
    sample), 'ring' after, with every mode alive (the start of the ring: the worst of it).
    -> {'attack', 'ring', 'parts': {...}}."""
    q = engine(controls or {})
    c = block_controls(q, F(1.0))
    ka = M.BODIES[choice("BODA", q["BODA"])]
    kb = M.BODIES[choice("BODB", q["BODB"])]

    def nmodes(kind):
        return MODES + (TWINS if M.SPLIT[kind] else 0)
    na = nmodes(ka)
    nb = 0 if kb == "OFF" else nmodes(kb)
    ta = M.TYPES[choice("TYPA", q["TYPA"])]
    tb = M.TYPES[choice("TYPB", q["TYPB"])]
    exc = [t for t, g in ((ta, c["ga"]), (tb, c["gb"])) if g >= F(1e-4) or t not in Exciter.DRIVEN]
    driven = [t for t in exc if t in Exciter.DRIVEN]
    B = BLOCK
    parts = {"block": COST["block"]}
    parts["exciters"] = sum(COST["exc_" + t.lower()] for t in (ta, tb)) * B
    parts["coeffs"] = COST["mode_block"] * (na + nb)
    morph = COST["og"] * (na + nb) * B if c["morph"] > 0 else 0
    if driven:
        parts["body_a_attack"] = COST["mode_driven"] * na * B + COST["force"] * B * len(driven)
    else:
        parts["body_a_attack"] = COST["mode_in"] * na * B
    parts["body_a_ring"] = COST["mode"] * na * B
    parts["body_b_attack"] = COST["mode_in"] * nb * B
    parts["body_b_ring"] = (COST["mode_in"] if c["buzz"] > 0 else COST["mode"]) * nb * B
    stages = {"fdbk": nb and (c["fdbk"] > 0 or (c["xmod"] == "TRADE" and c["coup"] > 0)),
              "buzz": c["buzz"] > 0, "click": q["CLIK"] > 0, "ring": q["RING"] > 0,
              "osc": q["RING"] > 0 and nb == 0, "shift": q["SHIFT"] != 64, "form": q["FORM"] > 0,
              "watr": q["WATR"] > 0, "fold": q["FOLD"] > 0, "char": q["CHAR"] > 0,
              "vca": q["LPG"] > 0}
    post = COST["post"] * B
    for k, on in stages.items():
        if on and k != "click":
            parts[k] = COST[k] * B
            post += parts[k]
    attack = parts["block"] + parts["exciters"] + parts["coeffs"] + morph + post \
        + parts["body_a_attack"] + parts["body_b_attack"] + (COST["click"] * B if stages["click"] else 0)
    ring = parts["block"] + parts["coeffs"] + morph + post + parts["body_a_ring"] + parts["body_b_ring"]
    return {"attack": int(attack), "ring": int(ring), "parts": parts, "modes": (na, nb)}


# -- rendering ------------------------------------------------------------------------------
def render_voice(controls, note, vel=1.0, seconds=1.0, seed=1, twins=TWINS, draws=None,
                 voice: Voice | None = None) -> np.ndarray:
    """one note from its strike for SECONDS (or until it ends). CONTROLS: a dict, or a
    function of the block index -> a dict (LFOs, p-locks)."""
    v = voice or Voice(seed=seed, twins=twins)
    v.note_on(note, vel, draws)
    n = int(seconds * RATE)
    nb = (n + BLOCK - 1) // BLOCK
    out = np.zeros(nb * BLOCK, F)
    ctl = controls if callable(controls) else (lambda b, c=controls: c)
    for i in range(nb):
        out[i * BLOCK:(i + 1) * BLOCK] = v.block(ctl(i))
        if v.idle:
            break
    return out[:n]


def model_draws(p: dict, note, vel, seed: int, drift_blocks: int = 3000) -> dict:
    """the model's per-hit draws for a voice, and its drift for DRIFT_BLOCKS blocks (for a
    test that wants the same hits)"""
    mv = M.Voice(p, note, vel, seed=seed)
    out = {}
    for name, body in (("a", mv.a), ("b", mv.b)):
        if body is None:
            continue
        base = np.array(M.RATIOS[body.kind])
        d = {"eps": body.base[:MODES] / base - 1.0, "aj": body.aj[:MODES]}
        if M.SPLIT[body.kind]:
            d["ajt"], d["offs"] = body.aj[MODES:], body.offs[MODES:]
        # the drift: the body's generator goes on to draw it a block at a time (Body.coeffs)
        d["drift"] = body.rng.normal(0.0, 1.5e-5 * body.vary, (drift_blocks, body.n))
        out[name] = d
    # the bow's speed phase: the first draw of each exciter's generator (model.Exciter._make)
    out["phase"] = tuple(float(np.random.default_rng(s).random()) for s in (seed, seed + 7919))
    return out


def render_notes(p, events, seconds: float, twins: int = TWINS, model_hits: bool = False,
                 quantize: bool = False) -> np.ndarray:
    """events: (start s, note, vel[, param overrides]) -> one mono mix, every note its own
    voice (seed k + 1, as model.render_notes). MODEL_HITS: each voice takes the model's
    per-hit draws. QUANTIZE: notes start on a block, as on the DSP (else on their sample, as
    the model's). P may be a function of the block index since the start (an LFO)."""
    out = np.zeros(int(seconds * RATE), F)
    for k, ev in enumerate(events):
        t0, note, vel = ev[:3]
        over = ev[3] if len(ev) > 3 else {}
        if callable(p):
            pp = (lambda b, base=p, o=over, s=int(t0 * RATE) // BLOCK: {**base(b + s), **o})
            pm = {**p(int(t0 * RATE) // BLOCK), **over}
        else:
            pp = pm = {**p, **over}
        i0 = int(t0 * RATE)
        if quantize:
            i0 = (i0 // BLOCK) * BLOCK
        draws = model_draws(pm, note, vel, k + 1) if model_hits else None
        x = render_voice(pp, note, vel, seconds - t0, seed=k + 1, twins=twins, draws=draws)
        m = min(len(x), len(out) - i0)
        out[i0:i0 + m] += x[:m]
    return out

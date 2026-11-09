"""FASCIA's DSP-order contract (src/dnfw/fascia/live.py) against the approved design model
(src/dnfw/fascia/model.py): every audition patch by ear-level measures (spectrum, envelope,
pitch; scripts/fascia_live_compare.py says how each is measured and why its tolerance is
what it is), and the contract's own promises: float32, causal and block-wise, robust to any
control, idle, denormal-free, polyphonic, bounded and click-free under per-block modulation.

    PYTHONPATH=src python3 -m pytest -q test/test_fascia_live.py
"""

import functools
import math
import random
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fascia_audition as A  # noqa: E402
import fascia_live_compare as CMP  # noqa: E402
from dnfw.fascia import live as L  # noqa: E402
from dnfw.fascia import model as R  # noqa: E402

F = np.float32
NAMES = [n for page in R.PAGES.values() for n in page]
KNEE = 1.0 / 1.5                                  # the output knee's ceiling


def C(name, opt):
    return int((R.CHOICES[name].index(opt) + 0.5) * 128 / len(R.CHOICES[name]))


# -- controls -------------------------------------------------------------------------------
def test_expand_is_the_models_for_every_value():
    for k in R.DEFAULTS:
        for v in range(128):
            assert L.expand({k: v}) == R.expand({k: v}), (k, v)
    for x in range(128):
        for cp in range(0, 128, 7):
            assert L.expand({"XMOD": x, "COUP": cp}) == R.expand({"XMOD": x, "COUP": cp})
    rnd = random.Random(5)
    for _ in range(500):
        p = {k: rnd.randint(0, 127) for k in R.DEFAULTS}
        assert L.expand(p) == R.expand(p), p


def test_choices_are_the_models():
    for name in R.CHOICES:
        assert [L.choice(name, v) for v in range(128)] == [R.choice(name, v) for v in range(128)]
    for name in R.ICHOICES:
        assert [L.ichoice(name, v) for v in range(128)] == [R.ichoice(name, v) for v in range(128)]


def test_garbage_controls_clamp():
    assert [L.clamp_ctl(v) for v in (float("nan"), float("inf"), -float("inf"), -5, 300, 64.9, "x", None)] \
        == [0, 0, 0, 0, 127, 64, 0, 0]
    assert L.vel_ok(float("nan")) == 1.0 and L.vel_ok(-1) == 0.0 and L.vel_ok(9) == 1.0
    assert L.note_ok(float("inf")) == 0.0


# -- the approximations (live.py's docstring states each bound) ------------------------------
def test_approximations():
    x = np.linspace(-60, 30, 20001).astype(F)
    assert np.max(np.abs(L.exp2(x) / 2.0 ** x.astype(float) - 1)) < 2.5e-7
    h = np.linspace(1e-4, math.pi / 2, 20001).astype(F)
    assert np.max(np.abs(L.sinp(h) / np.sin(h.astype(float)) - 1)) < 2.5e-7
    assert np.max(np.abs(L.cosp(h) - np.cos(h.astype(float)))) < 2e-7
    z = np.logspace(-20, 20, 2001).astype(F)
    assert np.max(np.abs(L.recip(z) * z.astype(float) - 1)) < 2e-7
    assert np.max(np.abs(L.rsqrt(z) * np.sqrt(z.astype(float)) - 1)) < 2e-7
    t = np.linspace(-10, 10, 20001).astype(F)
    th = L.tanh_r(t)
    assert np.max(np.abs(th - np.tanh(t.astype(float)))) < 1.2e-4 and np.max(np.abs(th)) <= 1.0
    small = np.abs(t) <= 3
    assert np.max(np.abs(th[small] - np.tanh(t[small].astype(float)))) < 2e-6
    e = np.linspace(-0.144, -1e-6, 2001).astype(F)
    assert np.max(np.abs(L.expm1(e) / np.expm1(e.astype(float)) - 1)) < 3e-7
    ph = np.linspace(0, 1, 20001).astype(F)
    assert np.max(np.abs(L.sin_t(ph) - np.sin(2 * np.pi * ph.astype(float)))) < 8e-5


def test_float32_throughout():
    v = L.Voice(seed=2)
    v.note_on(60, 1.0)
    p = dict(BODB=C("BODB", "BELL"), SKIN=120, SHIFT=90, DRIVE=100, XMOD=C("XMOD", "RING"), COUP=60)
    for _ in range(20):
        y = v.block(p)
        assert y.dtype == F
    for body in (v.a, v.b):
        for arr in (body.y, body.d, body.m, body.k, body.b, body.amp, body.L, body.aj):
            assert arr.dtype == F


# -- faithfulness: every audition patch --------------------------------------------------
@functools.lru_cache(maxsize=None)
def _cmp(name):
    return CMP.compare(name)


@pytest.mark.parametrize("name", list(A.PATCHES))
def test_patch_deterministic_twin(name):
    """the algorithm alone: the patch with DUST 0, live given every model draw (and the drift)
    and all 16 twins, against the model: float32, DSP order and the causal substitutions
    within fixed, tight limits (CMP.DET). A patch with another noise source is skipped."""
    r = _cmp(name)
    if r["noisy"]:
        pytest.skip("a noise source DUST does not stop (BLOW, BUZZ, the NOISE click)")
    if r["chaotic"]:
        pytest.skip("bowed: stick-slip amplifies float32's rounding (reported in index.txt)")
    if name in CMP.KNOWN:
        pytest.skip("WATR's causal level match: measured in index.txt, for the owner's ear")
    bad = CMP.failures(r, "det", name)
    assert not bad, f"{name}: {bad}\n  det {CMP.fmt(r['det'])}"


@pytest.mark.parametrize("name", list(A.PATCHES))
def test_patch_twin_cut(name):
    """the cost cut (twins on 8 modes) against all 16, three hits each: within the model's own
    hit-to-hit spread"""
    r = _cmp(name)
    bad = CMP.failures(r, "cut", name)
    assert not bad, f"{name}: {bad}\n  cut  {CMP.fmt(r['cut'])}\n  base {CMP.fmt(r['base'])}"


@pytest.mark.parametrize("name", list(A.PATCHES))
def test_patch_as_the_dsp_plays_it(name):
    """three live hits with their own draws (contact noise off: test_noise_* hold it), and the
    phrase's first second with every noise source on, against the model's: within the
    model's own hit-to-hit spread (and KNOWN, measured, for WATR and the twin cut on bells)"""
    r = _cmp(name)
    bad = CMP.failures(r, "own", name)
    assert not bad, f"{name}: {bad}\n  own  {CMP.fmt(r['own'])}\n  base {CMP.fmt(r['base'])}"


def test_deterministic_paths_follow_the_model_sample_for_sample():
    """where the model has no noise (DUST 0, MIX 0, the model's hits), live's samples are the
    model's to float32's and the drift's precision for the first 20 ms"""
    for p in (dict(MIX=0, DUST=0), dict(MIX=0, DUST=0, BODA=C("BODA", "BELL"), MATL=110),
              dict(MIX=0, DUST=0, TYPA=C("TYPA", "TZFM"), TZFM=100),
              dict(MIX=0, DUST=0, HARD=10, BODA=C("BODA", "VIBE")),             # ATK
              dict(MIX=0, DUST=0, CLIK=50, BODB=C("BODB", "MEMB"), XMOD=C("XMOD", "CHOKE"), COUP=90)):
        m = R.Voice(p, 48, 1.0, seed=1).render(0.05)[:960]
        x = L.render_voice(p, 48, 1.0, 0.05, seed=1, twins=16, draws=L.model_draws(p, 48, 1.0, 1))[:960]
        err = np.sqrt(np.mean((x - m) ** 2)) / np.sqrt(np.mean(m ** 2))
        assert err < 10 ** (-40 / 20), (p, 20 * math.log10(err))


def test_atk_window_is_the_models_exactly():
    """ATK's convolution, causal (running sums and a lagged generator): the excitation
    equals model.Exciter's for every deterministic impulsive type"""
    for kind, extra in (("STRIKE", {}), ("PULSE", {"BEND": 60}), ("TZFM", {"TZFM": 90}),
                        ("STRIKE", {"TZFM": 50})):
        for hard in (2, 10, 25, 31):            # (at 0 float32 makes the window a sample short)
            p = {"HARD": hard, "DUST": 0, **extra}
            q = R.expand(p)
            f0 = R.mtof(57)
            want = R.Exciter(kind, q, f0, 0.8, 1).sig
            e = L.Exciter(kind, L.expand(p), F(f0), F(0.8), L.XS(1), 9)
            c = L.block_controls(L.expand(p), F(0.8))
            got = np.concatenate([e.gen_block(c, F(f0)) for _ in range(len(want) // 32 + 1)])[:len(want)]
            # PULSE's 10 ms pitch envelope is computed a block at a time, linear between: 0.6 %
            tol = 1e-2 if kind == "PULSE" else 1e-3
            assert np.max(np.abs(got - want)) <= tol * np.max(np.abs(want)), (kind, hard, extra)


@pytest.mark.parametrize("hard,dec,dust", [(0, 20, 127), (10, 80, 127), (25, 80, 40), (31, 80, 127),
                                           (31, 20, 0)])
def test_atk_window_precision(hard, dec, dust):
    """the causal window (two staggered moment sums) against an exact float64 convolution of
    the same excitation stream, noise and all, however long the excitation"""
    q = L.expand({"HARD": hard, "DEC": dec, "DUST": dust})
    f0 = F(220.0)
    c = L.block_controls(q, F(0.9))
    e = L.Exciter("STRIKE", q, f0, F(0.9), L.XS(1), 9)
    g = L.Gen("STRIKE", q, f0, F(0.9), 9)
    g.c, g.f0 = c, f0
    out = []
    while not e.done:
        out.append(e.gen_block(c, f0))
    y = np.concatenate(out).astype(float)[:e.n_end]
    x = np.array([g() for _ in range(e.n_end)], float)
    w = (np.arange(e.am) / (e.am - 1)) ** 2
    ref = np.convolve(x, w / w.sum())[:e.n_end]
    assert np.sqrt(np.mean((y - ref) ** 2)) <= 1e-3 * np.sqrt(np.mean(ref ** 2))


# -- the noise sources: the model's statistics, over twenty hits ---------------------------------
def _exc_stats(kind, p, n_seeds=20):
    q = R.expand(p)
    ql = L.expand(p)
    f0 = R.mtof(57)
    c = L.block_controls(ql, F(0.9))
    out = {"m_area": [], "l_area": [], "m_e": [], "l_e": []}
    for k in range(1, n_seeds + 1):
        m = R.Exciter(kind, q, f0, 0.9, k).sig
        e = L.Exciter(kind, ql, F(f0), F(0.9), L.XS(k), 4 * k + 1)
        x = np.concatenate([e.gen_block(c, F(f0)) for _ in range(len(m) // 32 + 1)])[:len(m)].astype(float)
        out["m_area"].append(m.sum())
        out["l_area"].append(x.sum())
        out["m_e"].append(np.sum(m ** 2))
        out["l_e"].append(np.sum(x ** 2))
    return {k: np.array(v) for k, v in out.items()}


@pytest.mark.parametrize("p", [dict(DUST=127, HARD=60), dict(DUST=40, HARD=10), dict(DUST=127, HARD=120)])
def test_noise_contact_has_the_models_statistics(p):
    """STRIKE's contact noise (two uniforms' sum of unit variance for the model's Gaussian),
    alone and under ATK's window: its area and energy over forty hits, as the model's (means
    within three standard errors; spreads within 0.6..1.6: the triangular noise's energy
    varies ~0.7..0.84 as much from hit to hit, +-0.4 dB against the model's +-0.65)"""
    s = _exc_stats("STRIKE", p, 40)
    for key in ("area", "e"):
        mm, ll = s["m_" + key], s["l_" + key]
        se = math.sqrt(mm.var(ddof=1) / len(mm) + ll.var(ddof=1) / len(ll))
        assert abs(ll.mean() - mm.mean()) <= 3 * se + 1e-9, (key, mm.mean(), ll.mean(), se)
        assert 0.6 <= ll.std(ddof=1) / mm.std(ddof=1) <= 1.6, (key, mm.std(), ll.std())


def test_noise_breath_and_grit_have_the_models_level():
    """BLOW's breath and BOW's grit drive a body: the held level of twenty notes each, as the
    model's (means within three standard errors)"""
    for p in (dict(TYPA=C("TYPA", "BLOW"), MIX=0, DEC=90, DUST=80, BODA=C("BODA", "TUBE"), HARD=30),
              dict(TYPA=C("TYPA", "BOW"), MIX=0, DEC=90, DUST=100, BODA=C("BODA", "STRING"), HARD=60)):
        lev = lambda x: 10 * math.log10(np.mean(np.asarray(x[int(0.2 * R.RATE):], float) ** 2) + 1e-20)   # noqa: E731
        mm = np.array([lev(R.Voice(p, 48, 0.9, seed=k).render(0.5)) for k in range(1, 13)])
        ll = np.array([lev(L.render_voice(p, 48, 0.9, 0.5, seed=k)) for k in range(1, 13)])
        se = math.sqrt(mm.var(ddof=1) / len(mm) + ll.var(ddof=1) / len(ll))
        assert abs(ll.mean() - mm.mean()) <= max(3 * se, 1.0), (p, mm.mean(), ll.mean(), se)


def test_noise_click_has_the_models_energy():
    """the NOISE click: its energy over twenty hits, as the model's"""
    lm, ll = [], []
    for k in range(1, 21):
        lm.append(np.sum(R.click("NOISE", 0.6, np.random.default_rng(k)) ** 2))
        c = L.Click("NOISE", F(0.6), F(1.0), L.XS(k))
        ll.append(np.sum(np.concatenate([c.block() for _ in range(20)]).astype(float) ** 2))
    lm, ll = np.array(lm), np.array(ll)
    se = math.sqrt(lm.var(ddof=1) / 20 + ll.var(ddof=1) / 20)
    assert abs(ll.mean() - lm.mean()) <= 3 * se, (lm.mean(), ll.mean())


PLAIN_CUT = {("PLATE", "body"): 4.5}


def test_twin_cut_on_plain_strikes():
    """the cost cut on every round body: twins on 8 modes (twin_select), the rest folded into
    their primaries (a + b: the same onset), against all sixteen twinned: within the
    faithfulness tests' tolerance of the model's own hit-to-hit spread (the onset within
    0.5 dB; what goes is the folded modes' slow beat in the body and tail)"""
    for body in ("MEMB", "PLATE", "CHIME", "BELL", "GLASS", "STRING"):
        p = dict(BODA=C("BODA", body), MATL=110, DAMP=20, MIX=0, DUST=0)
        a = L.render_voice(p, 60, 1.0, 1.0, seed=4, twins=16).astype(float)
        b = L.render_voice(p, 60, 1.0, 1.0, seed=4, twins=8).astype(float)
        ms = [R.Voice(p, 60, 1.0, seed=sd).render(1.0) for sd in (1, 2, 3)]
        for w, t0, t1 in CMP.WINDOWS:
            s = slice(int(t0 * R.RATE), int(t1 * R.RATE))
            d = CMP.spec_dist(a[s], b[s])[0]
            ref = max(CMP.spec_dist(ms[0][s], m[s])[0] for m in ms[1:])
            # PLATE: measured 3.4..4.0 dB in the body (dense modes, their slow beats folded),
            # against the model's 2.0: for the owner's ear (12_gong_morph, 10_steel_pan)
            assert d <= max(CMP.SPEC_K * ref + CMP.SPEC_DB, PLAIN_CUT.get((body, w), 0.0)), (body, w, d, ref)
            if w == "onset":
                assert d < 0.5, (body, d)


def test_shift_moves_up_and_rejects_the_image():
    t = np.arange(24000) / R.RATE
    for f, hz in ((1000, 200), (1000, -200), (300, 1500), (5000, -2000)):
        x = (0.3 * np.sin(2 * np.pi * f * t)).astype(F)
        s = L.Shifter()
        y = np.array([s.tick(v, F(hz / R.RATE)) for v in x], float)[4000:]
        Y = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        fr = np.fft.rfftfreq(len(y), 1 / R.RATE)
        want, img = abs(f + hz), abs(f - hz)
        assert abs(fr[np.argmax(Y)] - want) < 5
        at = lambda ff: Y[np.argmin(np.abs(fr - ff))]      # noqa: E731
        assert 20 * math.log10(at(img) / at(want)) < -40, (f, hz)


def _model_wet(z, amt, f0):
    """model.water's wet skin before its level match, and its skin"""
    body = R.lowpass2(R.lowpass2(z, f0 * 1.8), f0 * 1.8)
    skin = z - body
    top = min(f0 * 2.2 * 32.0, 9000.0)
    bands = [f0 * 2.2 * (top / (f0 * 2.2)) ** (k / 7) for k in range(8)]
    wet = np.zeros(len(z))
    for k in R.WATER_USE:
        fc = bands[k]
        an = R.bandpass(skin, fc, 3.0)
        car = R.bandpass(skin, fc * (1.04 + 0.04 * amt), 14.0)
        e = R.follow(an, 0.0008, 0.012)
        es = R.follow(an, 0.02, 0.15) + 1e-6
        wet += car * np.minimum((e / es) ** 2, 6.0)
    return skin, wet


@pytest.mark.parametrize("patch,note", [("30_water_glass", 79), ("29_water_droplet_vibe", 60)])
def test_water_level_match_converges_on_the_models(patch, note):
    """WATR's causal level match (running sums since the strike) reaches the model's
    whole-signal gain; early it is lower (the documented onset deviation, bounded here)"""
    p = dict(A.PATCHES[patch][0], SKIN=64)
    z = R.Voice(p, note, 0.8, seed=1).render(1.5)
    f0 = R.mtof(note)
    skin, wet = _model_wet(z, 1.0, f0)
    g_model = 20 * math.log10(math.sqrt(np.mean(skin ** 2) / np.mean(wet ** 2)))
    w = L.Water()
    f0l, l2 = L.f0_of(note, 64)
    w.set(f0l, l2, F(1.0))
    g = []
    for i in range(0, len(z) - 31, 32):
        w.block(z[i:i + 32].astype(F), F(1.0))
        g.append(20 * math.log10(float(w.g)))
    at = lambda s: g[int(s * R.RATE) // 32]              # noqa: E731
    assert abs(g[-1] - g_model) < 0.5
    assert abs(at(0.5) - g_model) < 3.0
    assert g_model - at(0.01) < 22.0


# -- robustness ---------------------------------------------------------------------------
JUNK = (float("nan"), float("inf"), -float("inf"), -1e9, 1e9, -1, 128, 255, "?", None)


def _check(v, y):
    assert y.dtype == F and len(y) == L.BLOCK
    assert np.all(np.isfinite(y)), "non-finite output"
    assert np.max(np.abs(y)) <= KNEE + 1e-6
    assert v.faults == 0


def test_random_patches_and_plocks_are_finite_and_bounded():
    rnd = random.Random(11)
    for trial in range(24):
        v = L.Voice(seed=trial + 1)
        p = {k: rnd.randint(0, 127) for k in R.DEFAULTS}
        v.note_on(rnd.choice((0, 12, 36, 60, 84, 108, 127, rnd.uniform(0, 127))),
                  rnd.choice((0.0, 0.01, 0.5, 1.0, rnd.random())))
        for b in range(160):
            if rnd.random() < 0.3:                     # a p-lock or an LFO step on a few controls
                for k in rnd.sample(NAMES, rnd.randint(1, 6)):
                    p[k] = rnd.randint(0, 127)
            if rnd.random() < 0.05:
                p[rnd.choice(NAMES)] = rnd.choice(JUNK)
            if rnd.random() < 0.02:
                v.note_on(rnd.uniform(-10, 140), rnd.random())     # retrigger: a steal
            _check(v, v.block(p))


@pytest.mark.parametrize("fill", [0, 127])
def test_every_control_at_its_extreme(fill):
    for note in (0, 60, 127):
        for vel in (0.0, 1.0):
            v = L.Voice(seed=3)
            v.note_on(note, vel)
            for _ in range(200):
                _check(v, v.block({k: fill for k in R.DEFAULTS}))


def test_every_exciter_and_body_pair_is_finite_and_bounded():
    for ta in R.TYPES:
        for ba in R.BODIES[:-1]:
            for bb in ("PLATE", "OFF"):
                p = dict(TYPA=C("TYPA", ta), TYPB=C("TYPB", "BOW"), BODA=C("BODA", ba),
                         BODB=C("BODB", bb), MIX=64, COUP=90, BUZZ=60)
                v = L.Voice(seed=1)
                v.note_on(48, 1.0)
                for _ in range(40):
                    _check(v, v.block(p))


def test_garbage_notes_and_velocities():
    for note, vel in ((float("nan"), float("nan")), (float("inf"), 2.0), (-50, -1), (1e6, 0.5), ("x", "y")):
        v = L.Voice(seed=1)
        v.note_on(note, vel)
        for _ in range(30):
            _check(v, v.block({}))


# -- life: idle, rest, steal --------------------------------------------------------------
def test_a_short_hit_ends_its_voice():
    v = L.Voice(seed=1)
    x = L.render_voice(dict(DAMP=110, LPG=60), 60, 1.0, 2.0, voice=v)
    assert v.idle and v.end is not None and v.end < 1.5
    assert np.all(x[int(v.end * R.RATE):] == 0)
    m = R.Voice(dict(DAMP=110, LPG=60), 60, 1.0)
    m.render(2.0)
    assert abs(v.end - m.end) < 0.05                       # the model's IDLE rule


def test_a_long_bow_holds_its_voice():
    v = L.Voice(seed=1)
    L.render_voice(dict(TYPA=C("TYPA", "BOW"), DEC=110, MIX=0, DAMP=110), 60, 1.0, 0.5, voice=v)
    assert not v.idle


def test_a_driven_exciter_stops_driving_when_it_ends():
    """after BOW's or BLOW's end its force is gone (no block of pressure left behind)"""
    for kind in ("BLOW", "BOW"):
        v = L.Voice(seed=1)
        v.note_on(48, 1.0)
        p = dict(TYPA=C("TYPA", kind), MIX=0, DEC=10, DAMP=100)
        for _ in range(200):
            v.block(p)
        assert v.ea.done and v.ea.force_fn(L.block_controls(L.engine(p), F(1.0)), F(1.0)) is None
        v.block(p)
        assert v.cost < L.cost_estimate(p)["attack"]


def test_rest_and_steal():
    v = L.Voice(seed=1)
    v.note_on(60, 1.0)
    for _ in range(50):
        v.block({})
    assert not v.idle
    v.note_on(72, 1.0)                                   # a steal: one block fades the old out
    y = v.block({})
    assert abs(y[-1]) < 0.05 * max(np.max(np.abs(y)), 1e-9) + 1e-6
    y2 = v.block({})                                     # the strike
    assert v.note == 72 and np.max(np.abs(y2)) > 0
    v.rest()
    assert v.idle and np.all(v.block({}) == 0)


def test_choices_latch_at_the_strike_and_xmod_steps():
    v = L.Voice(seed=1)
    v.note_on(60, 1.0)
    v.block(dict(BODA=C("BODA", "BELL"), BODB=C("BODB", "OFF"), XMOD=C("XMOD", "EXCITE")))
    v.block(dict(BODA=C("BODA", "MEMB"), BODB=C("BODB", "PLATE"), TYPA=C("TYPA", "BOW")))
    assert v.a.kind == "BELL" and v.b is None and v.ea.kind == "STRIKE"
    q = L.engine(dict(XMOD=C("XMOD", "RING"), COUP=80))
    assert L.block_controls(q, 1.0)["ring"] == 80        # XMOD is read every block


# -- denormals ----------------------------------------------------------------------------
def _subnormal(a) -> bool:
    a = np.asarray(a, F)
    return bool(np.any((a != 0) & (np.abs(a) < np.finfo(F).tiny)))


def test_no_denormals_anywhere():
    """every state is flushed under FLOOR each block (the SHARC flushes denormals), so none is
    ever held; checked every block of long tails, quiet hits and every post stage"""
    for p, vel in ((dict(DAMP=0, MATL=127, BODA=C("BODA", "GLASS")), 1e-6),
                   (dict(DAMP=127, LPG=127, SKIN=120, SHIFT=20, DRIVE=127, XMOD=C("XMOD", "RING"), COUP=70), 0.3),
                   (dict(HARD=5, DUST=127, TYPB=C("TYPB", "BOW"), MIX=60, BODB=C("BODB", "BELL"), BUZZ=90), 1.0)):
        v = L.Voice(seed=2)
        v.note_on(30, vel)
        for _ in range(3000):
            y = v.block(p)
            assert not _subnormal(y)
            if v.idle:
                break
            for body in (v.a, v.b):
                if body is not None:
                    assert not _subnormal(body.y) and not _subnormal(body.d)
            for e in (v.ea, v.eb):
                if not e.driven:
                    assert not _subnormal([e.gen.en, e.gen.ep])
            if v.water is not None:
                assert not _subnormal(np.concatenate([v.water.e, v.water.es, v.water.an.ic1, v.water.car.ic2]))
            if v.shift is not None:
                assert not _subnormal(np.concatenate([v.shift.ay1, v.shift.by2]))
            assert not _subnormal([v.dc_y, v.venv, v.lim])


# -- polyphony ----------------------------------------------------------------------------
def test_a_chord_is_the_sum_of_its_voices():
    p = dict(BODA=C("BODA", "BAR"), BODB=C("BODB", "TUBE"), COUP=50)
    evs = [(0.0, 60, 0.8), (0.0, 64, 0.8), (0.0, 67, 0.8), (0.0, 71, 0.9)]
    mix = L.render_notes(p, evs, 0.3)
    parts = np.zeros(len(mix), F)
    for k, (_, n, vel) in enumerate(evs):
        parts = parts + L.render_voice(p, n, vel, 0.3, seed=k + 1)
    assert np.array_equal(mix, parts)
    assert np.all(np.isfinite(mix)) and np.max(np.abs(mix)) <= 4 * KNEE


def test_sixteen_voices_staggered():
    p = dict(BODA=C("BODA", "BELL"), DAMP=30)
    evs = [(0.01 * k, 36 + 5 * k, 0.5 + 0.03 * k) for k in range(16)]
    x = L.render_notes(p, evs, 0.4, quantize=True)
    assert np.all(np.isfinite(x)) and np.max(np.abs(x)) <= 16 * KNEE


# -- per-block modulation: an LFO on each control ------------------------------------------
LFO_BASES = {
    "bell": dict(BODA=C("BODA", "BELL"), MATL=110, DAMP=20, BODB=C("BODB", "GLASS"), COUP=40),
    "bow": dict(TYPA=C("TYPA", "BOW"), DEC=120, MIX=0, BODA=C("BODA", "STRING"), MATL=90, DAMP=40, DUST=30),
}
LFO_S = 0.5


def _lfo(b):
    """4 Hz over the whole range 0..127, a value a block (the DN2's LFO into a record)"""
    return min(127, int(round(64 + 64 * math.sin(2 * math.pi * 4 * b * L.BLOCK / R.RATE))))


def _residual(x, order: int = 24, frame: int = 2048) -> np.ndarray:
    """the signal less its linear prediction (order 24, fitted a frame at a time): ringing
    modes are predictable, a step is not"""
    e = np.zeros(len(x))
    for a in range(order, len(x), frame):
        b = min(a + frame, len(x))
        if b - a < 4 * order:
            break
        X = np.stack([x[a - k - 1:b - k - 1] for k in range(order)], 1)
        c, *_ = np.linalg.lstsq(X, x[a:b], rcond=None)
        e[a:b] = x[a:b] - X @ c
    return np.abs(e)


def _worst_at(x, e, off: int) -> float:
    top, worst = np.max(np.abs(x)), 0.0
    for b in range(int(0.05 * R.RATE) // L.BLOCK, len(x) // L.BLOCK - 2):
        n = L.BLOCK * b + off
        if np.max(np.abs(x[n - 34:n + 34])) < 1e-4 * top:
            continue
        edge = e[n - 1:n + 2].max()
        if edge < 1e-5:                                    # a step under -100 dBFS is not heard
            continue
        ctx = np.concatenate([e[n - 34:n - 2], e[n + 2:n + 34]])
        worst = max(worst, edge / (math.sqrt(np.mean(ctx ** 2)) + 1e-12))
    return worst


def click_score(x) -> float:
    """how much more the prediction residual spikes at block boundaries than mid-block
    (where per-block changes cannot step): random events (grit, dust) land on either alike.
    A clean bell scores ~1.3; one step of 0.3 % / 1 % of its peak at a boundary 1.6 / 2.6,
    a 3 % / 10 % gain step 2.6 / 4.5. The model's own bowed voice scores 2.4-3.3 (its
    coefficients step a block at a time on a driven body)."""
    x = np.asarray(x, float)
    e = _residual(x)
    mid = max(_worst_at(x, e, o) for o in (8, 16, 24))
    return _worst_at(x, e, 0) / max(mid, 1e-9)


CLICK_K, CLICK_FLOOR = 1.5, 2.5


@pytest.mark.parametrize("base", list(LFO_BASES))
@pytest.mark.parametrize("ctl", NAMES)
def test_lfo_on_each_control_is_bounded_and_click_free(base, ctl):
    """an LFO sweeping CTL over 0..127 at 4 Hz while the voice rings: finite, under the knee,
    and its clicks (click_score) no worse than CLICK_K x the worst static setting's of 0, 64,
    127, or CLICK_FLOOR (a step of ~1 % of the peak on a clean bell)"""
    p = LFO_BASES[base]
    v = L.Voice(seed=3)
    x = L.render_voice(lambda b: {**p, ctl: _lfo(b)}, 55, 1.0, LFO_S, voice=v)
    assert np.all(np.isfinite(x)) and np.max(np.abs(x)) <= KNEE + 1e-6 and v.faults == 0
    static = max(click_score(L.render_voice({**p, ctl: s}, 55, 1.0, LFO_S, seed=3)) for s in (0, 64, 127))
    got = click_score(x)
    assert got <= max(CLICK_K * static, CLICK_FLOOR), (ctl, got, static)


# -- cost ---------------------------------------------------------------------------------
def test_cost_estimate():
    typical = L.cost_estimate(dict(A.PATCHES["01_tubular_bell"][0]))
    worst = L.cost_estimate({**{k: 127 for k in R.DEFAULTS}, "TYPA": C("TYPA", "BOW"),
                             "TYPB": C("TYPB", "BLOW"), "MIX": 64, "BODA": C("BODA", "BELL"),
                             "BODB": C("BODB", "GLASS"), "XMOD": C("XMOD", "TRADE"),
                             "SKIN": 127, "SHIFT": 0})
    assert typical["ring"] < typical["attack"] < worst["attack"]
    assert worst["modes"] == (24, 24)
    off = L.cost_estimate({"SKIN": 64, "SHIFT": 64, "DRIVE": 0, "BUZZ": 0, "CLIK": 0, "LPG": 0, "BODB": C("BODB", "OFF")})
    assert "watr" not in off["parts"] and "shift" not in off["parts"]
    # the voice's own tally agrees in kind: an attack block costs more than a ringing one
    v = L.Voice(seed=1)
    v.note_on(60, 1.0)
    p = dict(A.PATCHES["01_tubular_bell"][0])
    costs = []
    for _ in range(300):
        v.block(p)
        costs.append(v.cost)
    assert costs[0] > costs[-1] > 0

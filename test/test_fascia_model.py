"""FASCIA's design model (src/dnfw/fascia/model.py): bounded, finite, deterministic, and doing
what each control says, before any DSP code is written against it."""

import itertools
import math
import random

import numpy as np
import pytest

from dnfw.fascia import model as R


def C(name, opt):
    return int((R.CHOICES[name].index(opt) + 0.5) * 128 / len(R.CHOICES[name]))


def render(p, note=48, vel=1.0, secs=0.3, seed=1):
    return R.Voice(p, note, vel, seed=seed).render(secs)


def test_pages_are_three_by_eight_and_defaults_cover_them():
    names = [n for page in R.PAGES.values() for n in page]
    assert [len(p) for p in R.PAGES.values()] == [8, 8, 8, 8]
    assert len(set(names)) == 32 and set(names) | set(R.EXTRA) == set(R.DEFAULTS)


@pytest.mark.parametrize("name", list(R.CHOICES))
def test_choice_spans_are_equal_and_reach_every_option(name):
    n = len(R.CHOICES[name])
    picks = [R.choice(name, v) for v in range(128)]
    assert sorted(set(picks)) == list(range(n))
    spans = [picks.count(k) for k in range(n)]
    assert max(spans) - min(spans) <= 1
    assert picks == sorted(picks)                       # monotonic: no option skipped back


def test_every_exciter_and_body_combination_is_finite_and_bounded():
    for ta, tb, ba, bb in itertools.product(R.TYPES, R.TYPES, R.BODIES[:-1], ("MEMB", "OFF")):
        p = dict(TYPA=C("TYPA", ta), TYPB=C("TYPB", tb), BODA=C("BODA", ba), BODB=C("BODB", bb), MIX=64)
        x = render(p, secs=0.08)
        assert np.all(np.isfinite(x)), (ta, tb, ba, bb)
        assert np.max(np.abs(x)) <= 1.0, (ta, tb, ba, bb)


@pytest.mark.parametrize("fill", [0, 127])
def test_every_control_at_its_extreme(fill):
    p = {k: fill for k in R.DEFAULTS}
    for note in (0, 60, 127):
        x = render(p, note=note, secs=0.2)
        assert np.all(np.isfinite(x)) and np.max(np.abs(x)) <= 1.0


def test_random_patches_are_finite_and_bounded():
    rnd = random.Random(7)
    for _ in range(40):
        p = {k: rnd.randint(0, 127) for k in R.DEFAULTS}
        x = render(p, note=rnd.randint(24, 108), vel=rnd.random(), secs=0.15)
        assert np.all(np.isfinite(x)) and np.max(np.abs(x)) <= 1.0, p


def test_deterministic():
    p = dict(TYPA=C("TYPA", "DUST"), DUST=100)
    assert np.array_equal(render(p, seed=3), render(p, seed=3))


def test_a_short_hit_releases_its_voice():
    v = R.Voice(dict(DAMP=110, LPG=60), 60, 1.0)
    v.render(2.0)
    assert v.end is not None and v.end < 1.5


def test_a_long_excitation_holds_its_voice():
    v = R.Voice(dict(TYPA=C("TYPA", "BOW"), DEC=110, MIX=0, DAMP=110), 60, 1.0)
    v.render(0.5)
    assert v.end is None


def test_velocity_brightens_a_strike():
    def centroid(x):
        s = np.abs(np.fft.rfft(x))
        f = np.fft.rfftfreq(len(x), 1 / R.RATE)
        return float((s * f).sum() / s.sum())
    p = dict(BODA=C("BODA", "PLATE"), MATL=100, HARD=90, DAMP=60)
    assert centroid(render(p, vel=1.0)) > centroid(render(p, vel=0.25)) * 1.1


def test_tzfm_goes_through_zero():
    e = R.Exciter("TZFM", {**R.DEFAULTS, "TZFM": 127, "SIDE": 40}, 110.0, 1.0, 1)
    t = np.arange(2000) / R.RATE
    ratio = 0.5 + 6.5 * R.u(40) ** 1.5
    m = np.sin(2 * math.pi * 110.0 * ratio * t)
    inc = 110.0 + 127 / 127 * 6.0 * np.exp(-t / e.dec) * 110.0 * ratio * m
    assert np.min(inc) < 0 < np.max(inc)


def test_chord_is_the_sum_of_its_voices():
    p = dict(BODA=C("BODA", "BAR"))
    evs = [(0.0, 60, 0.8), (0.0, 64, 0.8), (0.0, 67, 0.8)]
    mix = R.render_notes(p, evs, 0.2)
    parts = sum(R.Voice(p, n, v, seed=k + 1).render(0.2) for k, (_, n, v) in enumerate(evs))
    assert np.allclose(mix, parts)


def test_body_b_off_and_coupling():
    p = dict(BODB=C("BODB", "PLATE"), COUP=0)
    q = dict(BODB=C("BODB", "PLATE"), COUP=127)
    assert not np.allclose(render(p), render(q))
    assert R.Voice(dict(BODB=C("BODB", "OFF")), 48).b is None

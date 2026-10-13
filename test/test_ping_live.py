"""PING's DSP contract (dnfw.ping.live): bounded, exact where it must be, in tune."""

import math
import random

import pytest

from dnfw.ping import live as L

T = L.tables()


def rec(kind, over=None):
    r = {L.R_TYPE: (L.TYPES.index(kind) + 0.5) / 4, L.R_FREQ: 72 / 128, L.R_RES: 0.7,
         L.R_DRIVE: 0.5, L.R_ATK: 0.1, L.R_DEC: 0.6, L.R_CURVE: 0.8, L.R_STRIKE: 1.0,
         L.R_DEPTH: 0.5, L.R_KEYT: 0.0}
    r.update(over or {})
    return r


def run(kind, src, blocks, over=None):
    v, out = L.Voice(), []
    for b in range(blocks):
        out += L.block(v, src[b * 32:(b + 1) * 32] or [0.0] * 32, rec(kind, over), 60.0, b == 0, T)
    return out


def test_reciprocal_is_float32_accurate():
    rng = random.Random(3)
    for _ in range(2000):
        x = 1.0 + rng.random() * 200.0
        assert abs(L.recip(x) * x - 1.0) < 2e-7


def test_knees_are_exactly_linear_below_them():
    for x in (-0.6, -0.3, 0.0, 0.25, 0.6):
        assert L.ceiling(x) == x
    for x in (-1.0, -0.5, 0.7, 1.0):
        assert L.soft_loop(x) == x
    assert L.ceiling(100.0) == pytest.approx(0.9) and L.ceiling(-100.0) == pytest.approx(-0.9)
    assert abs(L.cubic(9.0)) == pytest.approx(1.0)


@pytest.mark.parametrize("kind", L.TYPES)
def test_every_core_is_bounded_at_its_extremes(kind):
    rng = random.Random(1)
    loud = [rng.uniform(-4, 4) for _ in range(32 * 200)]
    for res in (0.0, 0.97, 1.0):
        y = run(kind, loud, 200, {L.R_RES: res, L.R_DRIVE: 1.0, L.R_DEPTH: 1.0, L.R_FREQ: 1.0})
        assert all(abs(s) <= 0.9 + 1e-6 and not math.isnan(s) for s in y)


@pytest.mark.parametrize("kind", ["SVF", "VCFQ"])
def test_struck_it_rings_at_its_frequency(kind):
    y = run(kind, [], 400, {L.R_FREQ: 72 / 128, L.R_RES: 0.75})
    seg = y[2000:2000 + 9600]
    crossings = sum(1 for a, b in zip(seg, seg[1:]) if a < 0 <= b)
    assert abs(crossings / (len(seg) / 48000) - L.note_hz(72)) < 3


def test_tables_have_their_documented_ends():
    assert T["g"][69] == pytest.approx(math.tan(math.pi * 440 / 48000), rel=1e-6)
    assert 1 / (T["atk"][0] * 48) == pytest.approx(0.1, rel=1e-3)
    assert 1 / (T["dec"][127] * 48) == pytest.approx(10000, rel=1e-3)
    assert T["exp"][0] == 0 and T["exp"][-1] == pytest.approx(1.0)
    blob, at = L.tables_bytes()
    assert len(blob) == 4 * sum(len(t) for t in T.values()) and at["g"] == 0

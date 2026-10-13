"""PING's reference model: bounded at any setting, in tune, RES is ring time."""

import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ping"))
import model as M   # noqa: E402

N = 48000


def ring(kind, res, note=72, **kw):
    p = {"strike": 1.0, "dec": 3000, "env": 0.0, "atk": 0.1, **kw}
    return np.asarray(M.voice(np.zeros(N), note, kind, res=res, **p))


def pitch(y, start=2000, n=8192):
    seg = y[start:start + n] * np.hanning(n)
    sp = np.abs(np.fft.rfft(seg, 1 << 17))
    return (np.argmax(sp[50:]) + 50) * M.RATE / (1 << 17)


@pytest.mark.parametrize("kind", M.TYPES)
def test_every_type_is_bounded_at_its_most_extreme(kind):
    """Full RES, full DRIVE, full strike, a loud saw: never above the ceiling, never
    NaN. The thing the stock filters do that the owner hears as 'blown out' cannot
    run away here."""
    t = M.Table(__import__("dnfw.waverider.factory", fromlist=["x"]).tables()[0])
    src = t.osc(M.note_hz(48), N) * 4.0
    y = np.asarray(M.voice(src, 48, kind, res=1.0, drive=1.0, strike=1.0, env=1.0, freq=24))
    assert not np.isnan(y).any()
    assert np.max(np.abs(y)) <= M.CEILING + 1e-12


@pytest.mark.parametrize("kind", ["SVF", "VCFQ"])
def test_a_ping_rings_at_the_note(kind):
    for note in (60, 72, 84):
        f = pitch(ring(kind, 0.8, note))
        assert abs(1200 * math.log2(f / M.note_hz(note))) < 10


@pytest.mark.parametrize("kind", ["SVF", "VCFQ"])
def test_res_is_ring_time_and_the_same_at_every_pitch(kind):
    def t40(y):
        pk = np.max(np.abs(y))
        return np.where(np.abs(y) > pk * 0.01)[0][-1] / M.RATE
    times = [t40(ring(kind, r)) for r in (0.3, 0.5, 0.7)]
    assert times[0] < times[1] < times[2]
    low, high = t40(ring(kind, 0.5, 60)), t40(ring(kind, 0.5, 84))
    assert abs(low - high) / high < 0.25


def test_the_ring_is_round():
    """A struck VCFQ is nearly a pure tone: its harmonics are far below the ring."""
    y = ring("VCFQ", 0.8)
    seg = y[2000:2000 + 8192] * np.hanning(8192)
    sp = np.abs(np.fft.rfft(seg, 1 << 17))
    f0 = np.argmax(sp[50:]) + 50
    for h in (2, 3):
        band = sp[int(h * f0 * 0.98):int(h * f0 * 1.02)]
        assert 20 * math.log10(band.max() / sp[f0]) < -30


def test_curve_shapes():
    assert M.shape(0.0, 0.7) == 0.0 and abs(M.shape(1.0, 0.7) - 1.0) < 1e-12
    assert M.shape(0.5, 1.0) < 0.5 < M.shape(0.5, -1.0)
    assert M.shape(0.3, 0.0) == 0.3


def test_the_loop_limiter_is_transparent_below_its_knee():
    for x in (-0.99, -0.3, 0.0, 0.5, 1.0):
        assert M.soft(x) == x
    assert M.soft(10.0) < M.LIMIT and M.soft(-10.0) > -M.LIMIT

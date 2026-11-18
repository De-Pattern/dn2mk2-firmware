"""dnfw.dt2.reader, the DT2 sample reader's reference model, on its own (2026-11-15)."""

from __future__ import annotations

import cmath

import pytest

from dnfw.dt2 import reader as DR
from dnfw.dt2 import rom

pytestmark = pytest.mark.skipif(not rom.available(), reason="the owner's DT2 image (DT2_SECTION7) is not here")


def test_the_decimators_filter_is_an_all_pass():
    c = rom.decimator()
    for w in (0.05, 0.5, 1.0, 2.0, 3.1):
        z = cmath.exp(-1j * w)
        num = c[3] + c[2] * z + c[1] * z ** 2 + c[0] * z ** 3 + z ** 4
        den = 1 + c[0] * z + c[1] * z ** 2 + c[2] * z ** 3 + c[3] * z ** 4
        assert abs(abs(num / den) - 1.0) < 1e-6


def test_a_constant_comes_out_at_the_interpolators_gain():
    rows = DR.coefficients()
    gain = sum(sum(r) for r in rows) / len(rows) / 2.0 ** 31          # about 0.4045
    out = DR.read(DR.Voice([16384] * 600, 0, DR.ONE // 4), 200)
    assert abs(out[-1] - 0.5 * gain) < 2.0 ** -14


def test_the_mac_keeps_whole_16_bit_steps_toward_minus_infinity():
    v = DR.Voice([-1, 1, -1, 1, -1, 1, 0, 0], 0, DR.ONE // 3)
    for _ in range(6):
        y = DR.interpolate(v, DR.coefficients())
        assert y * 32768.0 == int(y * 32768.0)
        DR.advance(v)


def test_backward_reads_the_same_six_frames_against_the_row_in_order():
    rows = DR.coefficients()
    pcm = [(-1) ** k * 1000 * k for k in range(32)]
    fwd = DR.Voice(pcm, (10 << 32) + (DR.ONE * 3 // 8), 0)
    rev = DR.Voice(pcm, (15 << 32) + (DR.ONE * 3 // 8), 0, reverse=True)
    assert DR.interpolate(fwd, rows) == DR.interpolate(rev, rows)       # both s[10..15]


def test_taps_wrap_inside_the_window_and_reads_stay_in_it():
    rows = DR.coefficients()
    pcm = list(range(0, 1600, 100))
    v = DR.Voice(pcm, 7 << 32, 0, lo=4, hi=10)                          # taps 7, 8, 9, 4, 5, 6
    w = DR.Voice([pcm[k] for k in (7, 8, 9, 4, 5, 6)], 0, 0)
    assert DR.interpolate(v, rows) == DR.interpolate(w, rows)
    with pytest.raises(ValueError):
        DR.interpolate(DR.Voice(pcm, 10 << 32, 0, lo=4, hi=10), rows)

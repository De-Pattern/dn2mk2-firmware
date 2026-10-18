"""SHFT's DSP contract (dnfw.shft.live): it shifts, it is bounded, rest is silence."""

import math

from dnfw.shft import live as L

T = L.tables()


def _rec(mode, knob, fdbk=0.0, mix=1.0, depth=0.5, keyt=0.0):
    return {L.R_TYPE: (mode + 0.5) / 3, L.R_FREQ: knob / 128, L.R_RES: fdbk, L.R_DRIVE: 0.375,
            L.R_ATK: 0.0, L.R_DEC: 0.0, L.R_MIX: mix, L.R_DEPTH: depth, L.R_KEYT: keyt}


def _run(rec, x, note=60.0):
    v, out = L.Voice(), []
    for b in range(0, len(x), 32):
        out += L.block(v, x[b:b + 32], rec, note, b == 0, T)
    return out


def _tone(f, n):
    return [L._f32(0.5 * math.sin(2 * math.pi * f * k / L.RATE)) for k in range(n)]


def _amp(y, f):
    re = sum(v * math.cos(2 * math.pi * f * k / L.RATE) for k, v in enumerate(y))
    im = sum(v * math.sin(2 * math.pi * f * k / L.RATE) for k, v in enumerate(y))
    return math.hypot(re, im) / len(y)


def test_up_and_down_move_a_tone_by_the_shift():
    knob = 64 + 63 * (100 / 2500) ** (1 / 3)
    x = _tone(1000, 9600)
    for mode, want, image in ((0, 1100, 900), (1, 900, 1100)):
        y = _run(_rec(mode, knob), x)[4800:]
        assert _amp(y, want) > 100 * _amp(y, image)            # >= 40 dB


def test_centre_shifts_nothing_and_dry_mix_is_the_input():
    x = _tone(440, 3200)
    assert _run(_rec(0, 64, mix=0.0), x) == x


def test_feedback_at_the_top_stays_bounded():
    y = _run(_rec(0, 70, fdbk=1.0), _tone(60, 24000))
    assert max(abs(v) for v in y) <= 0.9 + 1e-6


def test_zero_state_is_rest():
    v = L.Voice()
    assert v.stage == 0 and v.phase == 0.0 and v.fb == 0.0
    assert L.block(v, [0.0] * 32, _rec(0, 100), 60.0, False, T) == [0.0] * 32

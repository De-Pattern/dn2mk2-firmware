"""RESONATOR's DSP contract (dnfw.rings.live)."""

import math

from dnfw.rings import live as L

T = L.tables()


def _run(words, note=60.0, blocks=60, trig_at=(0,)):
    v, out = L.Voice(), []
    for b in range(blocks):
        o, _ = L.block(v, 0, words, note, b in trig_at, T)
        out += o
    return v, out


def test_rest_is_silent_and_costs_nothing():
    v = L.Voice()
    o, did = L.block(v, 0, dict(L.DEFAULTS), 60.0, False, T)
    assert o == [0.0] * 32 and not did


def test_a_hit_rings_at_the_note_and_is_bounded():
    _, out = _run(dict(L.DEFAULTS), note=57.0, blocks=150)      # A3, 220 Hz, harmonic
    y = out[2000:]
    def amp(f):
        re = sum(v * math.cos(2 * math.pi * f * k / L.RATE) for k, v in enumerate(y))
        im = sum(v * math.sin(2 * math.pi * f * k / L.RATE) for k, v in enumerate(y))
        return math.hypot(re, im) / len(y)
    assert amp(220.0) > 5 * amp(330.0)
    assert max(abs(x) for x in out) <= 0.9 + 1e-6


def test_damping_sets_the_decay():
    short = {**L.DEFAULTS, L.P_DAMP: 0x0800}
    long_ = {**L.DEFAULTS, L.P_DAMP: 0x7F00}
    tail = lambda o: max(abs(x) for x in o[-3200:])
    assert tail(_run(short, blocks=200)[1]) < 0.05 * tail(_run(long_, blocks=200)[1])


def test_voice_goes_idle_after_a_short_decay():
    v, _ = _run({**L.DEFAULTS, L.P_DAMP: 0}, blocks=400)
    assert v.active == 0 and v.y1 == [0.0] * L.MODES


def test_voices_past_the_cap_are_silent():
    v = L.Voice()
    o, did = L.block(v, L.MAX_VOICES, dict(L.DEFAULTS), 60.0, True, T)
    assert o == [0.0] * 32 and not did and v.active == 0


def test_tables_fit_the_dsp_region():
    from dnfw.waverider import dsp
    assert dsp.RINGS_TABLES_DM + len(L.tables_bytes()[0]) <= dsp.REGION[1]

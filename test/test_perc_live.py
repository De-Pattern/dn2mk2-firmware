"""PERC (docs/perc.md): the model -- dnfw.perc.program run in Python, the same program the
SHARC runs (the runner holds the DSP to it bit for bit) -- against the owner's own C.

test/data/perc_c_reference.json is the owner's Ravel PERC C (rv_perc.c, perc_machine)
at 48 kHz, each machine at its defaults: its peak, 10 ms RMS envelope and zero-crossing
rate. The model is not the C bit for bit (tables instead of libm, float32 throughout), so
these are the measures a listener hears: level, decay, pitch.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest

from dnfw.perc import live as PL
from dnfw.perc import machines as PM
from dnfw.perc import program as PP

REF = json.loads((pathlib.Path(__file__).parent / "data" / "perc_c_reference.json").read_text())["machines"]
SECONDS = 0.1


def env(x, w=480):
    return [math.sqrt(sum(a * a for a in x[i:i + w]) / w) for i in range(0, len(x) - w + 1, w)]


def zcr(x):
    x = x[:1440]
    return sum(1 for a, b in zip(x, x[1:]) if (a < 0) != (b < 0)) / len(x) * 48000 / 2


@pytest.fixture(scope="module")
def renders():
    out = {}
    for k, name in enumerate(PM.NAMES):
        out[name] = PL.Harness().render(k, PL.defaults(name), SECONDS)
    return out


def test_every_machine_is_in_the_reference():
    assert set(REF) == set(PM.NAMES) and PM.N == 24


@pytest.mark.parametrize("name", PM.NAMES)
def test_level_decay_and_pitch_follow_the_owners_c(renders, name):
    m, c = renders[name], REF[name]
    peak = max(map(abs, m))
    assert abs(peak / c["peak"] - 1) < 0.08, (peak, c["peak"])
    em = env(m)
    for a, b in zip(em, c["env10ms"]):
        if b > 0.02 * c["peak"]:
            assert 0.8 < a / b < 1.25, (name, em, c["env10ms"])
    if c["zcr30ms"] > 50:
        assert abs(zcr(m) / c["zcr30ms"] - 1) < 0.25, (zcr(m), c["zcr30ms"])


def test_the_model_is_finite_and_silent_without_a_note():
    h = PL.Harness()
    h.set_controls(0, PL.defaults("TRX-BD"))
    assert all(x == 0.0 for _ in range(4) for x in h.block(60.0, False))


def test_two_slots_keep_their_own_state():
    a, b = PL.Harness(0), PL.Harness(5)
    a.set_controls(PM.NAMES.index("TRX-SD"), PL.defaults("TRX-SD"))
    b.set_controls(PM.NAMES.index("TRX-SD"), PL.defaults("TRX-SD"))
    xa = [a.block(60.0, k == 0) for k in range(3)]
    xb = [b.block(60.0, k == 0) for k in range(3)]
    # the same machine and note on two slots: the noise is seeded by slot, the tone is not
    assert xa != xb and all(math.isfinite(v) for blk in xa + xb for v in blk)


def test_the_program_assembles_from_the_model():
    from dnfw.waverider import dsp
    text = PP.program(PL.layout(), dsp.RINGS_SW)
    lines = [ln for ln in text.splitlines() if ln.startswith("      ") and not ln.strip().startswith("//")]
    assert 3000 < len(lines) < 6000
    assert f"JUMP {dsp.RINGS_SW:#x};" in text

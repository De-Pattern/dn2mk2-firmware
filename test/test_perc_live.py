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


def _ravel_fx(x, q, fs=48000.0):
    """rv_perc.c perc_render's track effects in float64 with libm's tan and sin"""
    e = [v * 127 for v in q]
    amd, amf, eqf = q[0], 0.1 * 2 ** (e[1] * 14.5 / 127), 40 * 2 ** (e[2] * 8.9 / 127)
    eqg = (q[3] - 0.5) * 36
    flo = 0 if e[4] < 0.5 else 20 * 2 ** (e[4] * 10 / 127)
    fhi = 0 if e[5] > 126.5 else 20 * 2 ** (min(max(e[4] + e[5], 0), 127) * 10 / 127)
    fq = 0.5 + e[6] ** 2 * 12 / 16129

    def mk(hz, qq):
        hz = min(max(hz, 10), fs / 2 * 0.9)
        g, k = math.tan(math.pi * hz / fs), 1 / max(qq, 0.05)
        a1 = 1 / (1 + g * (g + k))
        return {"k": k, "a1": a1, "a2": g * a1, "a3": g * g * a1, "ic1": 0.0, "ic2": 0.0}

    def tick(f, v):
        v3 = v - f["ic2"]
        v1 = f["a1"] * f["ic1"] + f["a2"] * v3
        v2 = f["ic2"] + f["a2"] * f["ic1"] + f["a3"] * v3
        f["ic1"], f["ic2"] = 2 * v1 - f["ic1"], 2 * v2 - f["ic2"]
        return v2, v1, v - f["k"] * v1 - v2
    eq, hp, lp = mk(eqf, 1.2), mk(flo, fq) if flo else None, mk(fhi, fq) if fhi else None
    ph, out = 0.0, []
    for y in x:
        if amd > 0:
            ph += amf / fs
            ph -= math.floor(ph)
            y *= 1 - amd * (0.5 - 0.5 * math.sin(2 * math.pi * ph))
        if abs(eqg) > 0.2:
            y += tick(eq, y)[1] * eq["k"] * (2 ** (eqg * 0.1661) - 1)
        if hp:
            y = tick(hp, y)[2]
        if lp:
            y = tick(lp, y)[0]
        out.append(y)
    return out


@pytest.mark.parametrize("name,fx", [("TRX-SD", (0.8, 0.6, 0.5, 0.9, 0.3, 0.4, 0.7)),
                                     ("EFM-HH", (0.0, 0.5, 0.7, 0.1, 0.0, 0.5, 0.2)),
                                     ("TRX-BD", (0.5, 0.9, 0.5, 0.5, 0.0, 1.0, 0.0)),
                                     ("GND-NS", (0.0, 0.5, 0.5, 0.5, 0.6, 1.0, 0.9))])
def test_the_track_effects_follow_ravels(name, fx):
    """v0.12: AMD AMF EQF EQG FLTF FLTW FLTQ, as rv_perc.c applies them to a voice"""
    k = PM.NAMES.index(name)
    off = PL.Harness().render(k, PL.defaults(name), 0.05)
    on = PL.Harness().render(k, PL.defaults(name), 0.05, fx=fx)
    ref = _ravel_fx(off, fx)
    peak = max(map(abs, ref))
    assert on != off
    assert max(abs(a - b) for a, b in zip(on, ref)) < 0.08 * peak


def test_the_effects_are_off_at_the_records_defaults():
    assert PL.Harness().render(2, PL.defaults("TRX-SD"), 0.01, fx=PL.FX_OFF) == \
        PL.Harness().render(2, PL.defaults("TRX-SD"), 0.01)

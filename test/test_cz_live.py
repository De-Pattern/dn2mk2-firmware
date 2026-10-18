"""CZ's DSP contract (dnfw.cz.live), against the reference model (cz/model.py)."""

import math

from dnfw.cz import live as L

T = L.tables()


def _run(words, note=60.0, blocks=40, trig_at=(0,)):
    v, out = L.Voice(), []
    for b in range(blocks):
        o, _ = L.block(v, 0, words, note, b in trig_at, T)
        out += o
    return v, out


def _amp(y, f):
    re = sum(v * math.cos(2 * math.pi * f * k / L.RATE) for k, v in enumerate(y))
    im = sum(v * math.sin(2 * math.pi * f * k / L.RATE) for k, v in enumerate(y))
    return math.hypot(re, im) / len(y)


def _wave_word(i):
    return int((i + 0.5) * 0x7800 / 33)


def test_rest_is_silent():
    v = L.Voice()
    o, did = L.block(v, 0, dict(L.DEFAULTS), 60.0, False, T)
    assert o == [0.0] * 32 and not did


def test_the_waves_match_the_reference_model():
    import numpy as np
    import sys
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from cz import model as M
    ph = np.linspace(0.0, 0.999, 300)
    for w, name in enumerate(L.WAVES):
        for d in (0.0, 0.4, 1.0):
            ours = np.array([L.wave(w, float(np.float32(x)), d, T) for x in ph])
            assert np.max(np.abs(ours - M.wave_out(name, ph, np.full_like(ph, d)))) < 1e-3, (name, d)


def test_dcw_zero_is_a_sine_at_the_note():
    words = {**L.DEFAULTS, L.P_DCW: 0}
    _, out = _run(words, note=57.0, blocks=60)                  # 220 Hz
    y = out[320:]
    assert _amp(y, 220.0) > 20 * _amp(y, 440.0)


def test_dcw_adds_harmonics():
    full = {**L.DEFAULTS, L.P_DCW: 0x7F00, L.P_LEVELS[0]: 0x7F00, L.P_RATES[0]: 0x6400}
    _, out = _run(full, note=57.0, blocks=60)
    y = out[640:]
    assert _amp(y, 440.0) > 0.1 * _amp(y, 220.0)


def test_every_combination_is_bounded():
    for i in range(33):
        for sel in range(4):
            for mod in range(3):
                words = {**L.DEFAULTS, L.P_WAVE: _wave_word(i), L.P_SEL: sel << 8,
                         L.P_MOD: mod << 8, L.P_DCW: 0x7F00, L.P_OCT: 0x200}
                _, out = _run(words, blocks=3)
                assert all(abs(x) <= 1.0 for x in out), (i, sel, mod)


def test_envelope_runs_to_sustain_and_holds():
    words = {**L.DEFAULTS, **{p: 0x7F00 if p >= 42 else 0x6400 for p in L.P_RATES},
             L.P_SUS: int(2.5 * 0x7800 / 9)}                    # sustain on step 3
    v, _ = _run(words, blocks=60)
    assert v.step == 2 and v.v == L.controls(words, 60.0, T)["levels"][2]


def test_no_sustain_runs_all_eight_steps():
    words = {**L.DEFAULTS, **{p: 0x7F00 if p >= 42 else 0x6400 for p in L.P_RATES},
             L.P_SUS: 0x7800}
    v, _ = _run(words, blocks=60)
    assert v.step == 7


def test_a_trigger_restarts_the_envelope():
    words = {**L.DEFAULTS, L.P_SUS: 0x7800}
    v, _ = _run(words, blocks=30)
    L.block(v, 0, words, 60.0, True, T)
    assert v.step == 0


def test_pairs_alternate_cycle_by_cycle():
    v = L.Voice()
    words = {**L.DEFAULTS, L.P_WAVE: _wave_word(8)}             # SAW then SQUARE
    for b in range(40):
        L.block(v, 0, words, 60.0, b == 0, T)
    assert v.par1 in (0, 1)
    c = L.controls(words, 60.0, T)
    assert (c["a"], c["b"]) == (0, 1)


def test_voices_past_the_cap_are_silent():
    v = L.Voice()
    o, did = L.block(v, L.MAX_VOICES, dict(L.DEFAULTS), 60.0, True, T)
    assert o == [0.0] * 32 and not did and v.active == 0


def test_layout():
    from dnfw.waverider import dsp
    assert dsp.CZ_TABLES_DDR + len(L.tables_bytes()[0]) <= dsp.CZ_TABLES_DDR + 0x1000
    assert dsp.CZ_CODE_DM < dsp.REGION[1] and dsp.CZ_SW == dsp.CZ_CODE_DM // 2
    assert len(L.COMBOS) == 33 and len(set(L.COMBOS)) == 33


def test_the_pages_carry_every_control_once():
    from dnfw.waverider import pages
    ids = [r for page in pages.CZ_PAGES for r in page]
    assert len(ids) == len(set(ids)) == 24 and pages.CZ_UNUSED == (251,)
    assert [pages.CZ_LABELS[r] for r in pages.CZ_RATE_IDS] == [f"R{k}" for k in range(1, 9)]
    assert [pages.CZ_LABELS[r] for r in pages.CZ_LEVEL_IDS] == [f"L{k}" for k in range(1, 9)]
    # record id -> frame slot, as the stock record table has it (checked against the image
    # when this was written): the pages and the contract agree
    slot = {238: 25, 239: 26, 240: 29, 241: 30, 242: 31, 243: 32, 244: 35, 245: 36, 246: 28,
            247: 27, 248: 37, 249: 39, 250: 34, 252: 38, 253: 40, 254: 41, 255: 42, 256: 43,
            257: 44, 258: 45, 259: 46, 260: 47, 261: 48, 262: 49}
    assert [slot[r] for r in pages.CZ_RATE_IDS] == list(L.P_RATES)
    assert [slot[r] for r in pages.CZ_LEVEL_IDS] == list(L.P_LEVELS)
    assert [slot[r] for r in pages.CZ_PAGES[0]] == [L.P_WAVE, L.P_SEL, L.P_DET, L.P_OCT,
                                                    L.P_MOD, L.P_DCW, L.P_KF, L.P_SUS]

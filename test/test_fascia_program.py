"""FASCIA's DSP program (dnfw.fascia.program, machine type 18) against live.py, bit for bit.

The run mode of the DSL program is the model the SHARC runner holds the assembled code to
(scripts/sharc_waverider_m5.py, parts fascia, fchords, fgarbage, fstress, fsilence); here the
run mode is held to `dnfw.fascia.live` word for word: the audition patches (strike and ring),
random panels with p-locks moving mid-note and retriggers (steals), the idle rule, and garbage
state. Plus the layout and the tables.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.fascia import bench as B          # noqa: E402
from dnfw.fascia import live as LV           # noqa: E402
from dnfw.fascia import machines as FM       # noqa: E402
from dnfw.fascia import model as MD          # noqa: E402
from dnfw.fascia import program as P         # noqa: E402
from dnfw.waverider import dsp               # noqa: E402

import fascia_audition as A                  # noqa: E402


def same(a, b) -> bool:
    return np.array_equal(np.asarray(a, np.float32).view(np.uint32), np.asarray(b, np.float32).view(np.uint32))


def test_the_names_are_the_models():
    assert P.TYPES == MD.TYPES and P.BODIES == MD.BODIES and P.CLICKS == MD.CLICKS and P.XMODS == MD.XMODS
    assert P.MODES == MD.MODES == LV.MODES and P.TWINS == LV.TWINS and P.BLOCK == LV.BLOCK
    assert MD.INTERNAL["VARY"] == P.VARY_INTERNAL and MD.INTERNAL["FDBK"] == 0
    assert P.POST == LV.POST_STAGES


def test_the_tables_are_current():
    """tables.json (what the build ships, read without numpy) is what live.py computes now"""
    spec = json.loads(P.TABLES_JSON.read_text(encoding="utf-8"))
    vals = P.table_values()
    for name, n in P.TABLE_SPEC:
        want = [f"{v & 0xFFFFFFFF:08x}" if isinstance(v, int) else f"{P.bits(P.f32(v)):08x}" for v in vals[name]]
        assert spec[name] == want, name
    assert len(P.tables_bytes()) == 4 * P.TABLE_WORDS
    assert ("FASCIA's tables (dnfw.fascia.program.tables_bytes; v0.45)", dsp.FSC_TABLES_DDR,
            P.tables_bytes()) in dsp.ddr_spans()


def test_the_layout_fits():
    L = P.layout()
    assert 4 * P.VOICE_WORDS <= P.STRIDE and dsp.FSC_STATE_SPAN == 8 * P.STRIDE
    assert L.state == dsp.FSC_STATE_L2 and L.state2 == dsp.FSC_STATE2_L2
    assert dsp.FSC_STATE_L2 + dsp.FSC_STATE_SPAN <= dsp.MD_STATE_L2           # voices 0..7: below the MD's state
    assert dsp.MAIN_TAP_L2 + dsp.MAIN_TAP_BYTES <= dsp.FSC_STATE2_L2          # 8..15: after the main mix's tap
    assert dsp.FSC_L2_LOAD == dsp.FSC_STATE2_L2 + dsp.FSC_STATE_SPAN
    assert dsp.FSC_L2_LOAD + dsp.FSC_L2_SPAN == dsp.PERC_L2_LOAD
    assert dsp.L2_IMAGE_END + 0x10000 <= dsp.FSC_STATE_L2                     # _check_l2's rule
    assert L.scratch == dsp.FSC_SCRATCH_DM and L.scratch_end <= dsp.REGION[1]  # L1, in the region's padding
    # the bookkeeping, in the Monomachine scratch after PERC's (keys .. strikes end at 0x3180)
    from dnfw.perc import program as PP
    assert PP.STRIKES_OFF + 0x40 <= P.MISC_OFF and P.MISC_OFF + 0x180 <= dsp.MNM_SCRATCH_BYTES
    assert L.order == PP.ORDER
    for t in range(16):
        base = (L.state if t < 8 else L.state2) + P.STRIDE * (t & 7)
        assert base + 4 * P.VOICE_WORDS <= (dsp.MD_STATE_L2 if t < 8 else dsp.FSC_L2_LOAD)


def test_the_program_emits():
    text = P.program(P.layout(), dsp.PING_SW)
    n = sum(1 for ln in text.splitlines() if ln.startswith("      ") and not ln.strip().startswith("//"))
    assert 1000 < n < 20000
    assert f"JUMP {dsp.PING_SW:#x};" in text
    import re
    for ln in text.splitlines():
        t = ln.split("//", 1)[0].strip()
        m = re.match(r"(I|M|L|B)(\d+) =", t)
        if m:
            assert f"{m.group(1)}{m.group(2)}" in ("I0", "I1", "I2", "I3", "I4", "I5", "I12"), t
        assert not re.search(r"DM\(I[035], M", t), t         # I0, I3, I5 never post-modified
        assert not re.search(r"\b(R1[6-9]|F1[6-9]|USTAT|MODE1|MODE2|LCNTR|CALL|DO )\b", t), t


QUICK = ("01_tubular_bell", "06_plasticine", "08_glass_harmonica", "12_gong_morph", "20_snare_wires",
         "22_col_legno_strings", "25_blown_tube", "27_trade_bar_bell", "29_water_droplet_vibe",
         "15_tzfm_clank", "28_swell_attack_vibe")


@pytest.mark.parametrize("name", QUICK)
def test_audition_patch_bit_exact(name):
    p, evs, _secs, _trem = A.PATCHES[name]
    got, want, first = B.compare_voice(p, [(0.0, evs[0][1], evs[0][2])], 40, slot=0)
    assert first is None, (name, first)
    assert np.max(np.abs(want)) > 0.001


@pytest.mark.parametrize("seed", [11, 101, 202, 303])
def test_random_panels_plocks_and_steals_bit_exact(seed):
    """every control random, a few moving every 8..40 blocks (p-locks, slides, LFOs), notes
    retriggering the same voice (steals): every block the same words"""
    rng = random.Random(seed)
    blocks = 140
    base = {c: rng.randrange(128) for c in FM.CONTROLS}
    moves, k = {}, 0
    while k < blocks:
        k += rng.randrange(8, 40)
        moves[k] = {c: rng.randrange(128) for c in rng.sample(FM.CONTROLS, rng.randrange(1, 4))}

    def ctl(b):
        q = dict(base)
        for kk in sorted(moves):
            if kk <= b:
                q.update(moves[kk])
        return q
    evs, t = [(0.0, rng.uniform(30, 90), rng.uniform(0.05, 1.0))], 0.0
    while True:
        t += rng.uniform(0.02, 0.3)
        if t * LV.RATE / LV.BLOCK >= blocks:
            break
        evs.append((t, rng.uniform(30, 90), rng.uniform(0.05, 1.0)))
    _g, _w, first = B.compare_voice(base, evs, blocks, slot=rng.randrange(16), controls=ctl)
    assert first is None, (seed, first)


def test_dust_pulse_and_atk_exciters_bit_exact():
    """the exciters no audition patch uses: DUST and PULSE, under ATK (HARD under 32), a TZFM burst"""
    C = lambda o: int((MD.TYPES.index(o) + 0.5) * 128 / 6)
    for typa, typb, hard in (("DUST", "PULSE", 10), ("PULSE", "DUST", 0), ("STRIKE", "TZFM", 20), ("DUST", "BOW", 31)):
        p = dict(TYPA=C(typa), TYPB=C(typb), HARD=hard, MIX=64, TZFM=60, DUST=90, BEND=80, DEC=60)
        _g, want, first = B.compare_voice(p, [(0.0, 57, 0.8), (0.04, 64, 0.5)], 50, slot=3)
        assert first is None, (typa, typb, hard, first)


def test_the_idle_rule_rests_the_voice():
    p = dict(BODA=0, DAMP=127, MATL=0, HARD=127, MIX=0, DEC=0, LPG=0)
    got, want, first = B.compare_voice(p, [(0.0, 60, 1.0)], 140, slot=0)
    assert first is None
    last = max(k for k in range(len(got)) if got[k] != 0)
    assert last < len(got) - 32 * 10                     # it rested, and stays silent


def test_silent_without_a_note():
    got, want, first = B.compare_voice({}, [], 20, slot=5)
    assert first is None and not np.any(got)


@pytest.mark.parametrize("fill", ["nan", "random"])
def test_garbage_state_stays_finite(fill):
    """power-on memory: the voices' state and the scratch full of NaN or random words; the voice
    struck: every block finite and within the knee (the model's run mode, the DSP's program)"""
    g = random.Random(7)
    L = P.layout()
    spans = [(L.state, 8 * P.STRIDE), (L.state2, 8 * P.STRIDE), (L.scratch, L.scratch_end - L.scratch)]

    def garbage(a):
        if any(lo <= a < lo + n for lo, n in spans):
            return 0xFFFFFFFF if fill == "nan" else g.getrandbits(32)
        return 0
    dsp_ = B.Dsp(fill=garbage)
    pan = A.PATCHES["29_water_droplet_vibe"][0]
    for k in range(10):
        f = B.Frame()
        for t in (0, 9):
            f.slot(t, B.panel_words(pan), 0.9, 60.0, k in (1, 4))
        out = dsp_.block(f, [0, 9])
        for t in (0, 9):
            assert np.all(np.isfinite(out[t])) and np.max(np.abs(out[t])) <= 0.7, (fill, k, t)


@pytest.mark.parametrize("ctl,a,b,at", [("SHIFT", 64, 90, 8), ("DRIVE", 0, 100, 8), ("DRIVE", 100, 0, 8),
                                        ("LPG", 0, 60, 8), ("LPG", 60, 0, 1), ("SKIN", 20, 80, 8),
                                        ("SKIN", 100, 20, 1), ("XMOD", 0, 120, 8), ("COUP", 0, 90, 2)])
def test_a_post_stage_switched_mid_note_bit_exact(ctl, a, b, at):
    """a stage turned on or off by a p-lock mid-note (on block 1 too): the crossfade, the drop"""
    sel = lambda k: {ctl: a if k < at else b, "BODA": 40, "XMOD": 120 if ctl == "COUP" else 0}
    _g, _w, first = B.compare_voice(sel(0), [(0.0, 60, 0.9)], 20, slot=0, controls=sel)
    assert first is None, (ctl, a, b, at, first)


def test_the_note_is_the_frames_not_the_late_note_cell():
    """the stock unpack writes the note cell (engine +0x1387c + 4t) after FASCIA runs, so on a
    trig with a new note it still holds the note before (the SHARC runner: a steal 60 -> 67, the
    cell 60 on the trig's block). The program takes the frame's header word: the cell, left
    stale or garbage here, changes nothing"""
    pan = A.PATCHES["03_vibraphone"][0]
    for cell in (60.0, float("nan")):
        dsp_ = B.Dsp()
        v = LV.Voice(seed=1)
        for b in range(8):
            f = B.Frame()
            note = 60.0 if b < 4 else 67.0
            f.slot(0, B.panel_words(pan), 0.8, note, b in (1, 4))
            f.w[P.NOTE_CELLS] = P.bits(P.f32(cell))
            got = dsp_.block(f, [0])[0]
            if b in (1, 4):
                v.note_on(B.note_seen(note), B.vel_seen(0.8))
            assert same(got, v.block(B.panel_seen(pan))), (cell, b)

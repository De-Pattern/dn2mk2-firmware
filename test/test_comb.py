"""COMB- and COMB+ (v0.20, docs/comb.md): the model (dnfw.comb.program run in Python, the
same calls that write comb.asm) against the DT2's comb as reverse-engineered
(research/tools/models_comb.py, when present), and its behaviour on its own. The SHARC
gate (step 7c) holds comb.asm to this model bit for bit."""

from __future__ import annotations

import json
import pathlib
import random
import re
import struct

import pytest

from dnfw.comb import program as CP
from dnfw.dt2 import rom
from dnfw.perc import live as PL
from dnfw.perc import program as PP
from dnfw.perc.dsl import Mem, bits, flt
from dnfw.ping import live as PGL
from dnfw.waverider import dsp

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARC = ROOT / "csrc" / "waverider" / "sharc"
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
DT2_MODELS = ROOT.parent / "dt2s117" / "research" / "tools"
L = CP.Layout(0x81220000, 0x81221000, 0x81222000, 0x81300000, PL.layout().T["exp2"], 0x81230000)
BUF, BLOCK = 0x300000, 32

needs_rom = pytest.mark.skipif(not rom.available(), reason="the owner's DT2 section 7 is not here")


def machine(freq, fb, damp, note=60.0, depth=0.5, atk=0.0, dec=0.5):
    words = {}
    tb = CP.tables_bytes()
    for k in range(CP.GAIN_N):
        words[L.tables + 4 * k] = struct.unpack_from("<I", tb, 4 * k)[0]
    pt = PGL.tables_bytes()[0]
    for k in range(len(pt) // 4):
        words[L.T["ping"] + 4 * k] = struct.unpack_from("<I", pt, 4 * k)[0]
    mem = Mem(lambda a: words.get(a, 0))
    rec = CP.RECORDS
    mem.put(rec + CP.R_FREQ, bits(freq))
    mem.put(rec + CP.R_RES, bits(fb))
    mem.put(rec + CP.R_DAMP, bits(damp))
    mem.put(rec + CP.R_KEYT, bits(0.0))
    mem.put(rec + CP.R_DEPTH, bits(depth))
    mem.put(rec + CP.R_ATK, bits(atk))
    mem.put(rec + CP.R_DEC, bits(dec))
    mem.put(PP.NOTE_CELLS, bits(note))
    mem.put(PP.BUFFERS, BUF)
    return mem


def block(mem, x, ftype=10, trig=False):
    for k in range(BLOCK):
        mem.put(BUF + 4 * k, bits(x[k]))
    mem.put(PP.TRIG_WORD, (1 << 16) if trig else 0)
    p, _ = CP.run_track(L, None, 0, ftype, mem=mem)
    return [flt(mem.get(BUF + 4 * k)) for k in range(BLOCK)], p.steps


def impulse_response(ftype, freq, fb, damp, blocks=40):
    mem = machine(freq, fb, damp)
    out, steps = [], 0
    for b in range(blocks):
        x = [0.0] * BLOCK
        if b == 0:
            x[0] = 0.5
        y, steps = block(mem, x, ftype, trig=(b == 0))
        out += y
    return out, steps, mem


@needs_rom
@pytest.mark.skipif(not (DT2_MODELS / "models_comb.py").is_file(), reason="research models not here")
def test_matches_the_dt2_comb():
    import sys
    sys.path.insert(0, str(DT2_MODELS))
    import numpy as np
    import models_comb as MC
    for f, fb, lpf in ((0.55, 0.8, 0.8), (0.1, 0.5, 1.0), (0.9, 1.0, 0.3), (0.3, 0.0, 0.0)):
        mem = machine(f, fb, 1 - lpf)
        S = MC.CombState()
        rng = random.Random(1)
        outs, refs = [], []
        for b in range(40):
            x = [rng.uniform(-0.5, 0.5) if b < 3 else 0.0 for _ in range(BLOCK)]
            y, _ = block(mem, x, 10, trig=(b == 0))
            outs += y
            MC.setup(S, np.float32(f), np.float32(fb), np.float32(lpf), np.float32(1))
            if b == 0:
                MC.reset(S)
            refs += list(MC.render(S, np.array(x, dtype=np.float32)))
        assert max(abs(o - r) for o, r in zip(outs, refs)) <= 5e-5, (f, fb, lpf)


@needs_rom
def test_feedback_curve_is_the_dt2s():
    g = rom.comb_gain()
    assert len(g) == 128 and g[0] == pytest.approx(0.0, abs=1e-6)
    assert all(b >= a for a, b in zip(g, g[1:])) and 0.9 < g[-1] <= 1.0


@needs_rom
def test_rings_at_the_frequency_bounded_and_affordable():
    out, steps, mem = impulse_response(10, 0.6, 0.9, 0.0)
    assert max(abs(v) for v in out) <= 1.0
    D = flt(mem.get(L.state + 4 * CP.S["D"]))
    hz = 220 * 2 ** ((127 * 0.6 - 69) / 12)
    assert D == pytest.approx(48000 / hz, rel=0.02)
    peaks = [k for k in range(1, len(out)) if abs(out[k]) > 0.05]
    assert len(peaks) > 10                       # it rings on after the impulse
    assert steps < 6000                          # SHARC instructions a block (the gate times the whole)


@needs_rom
def test_comb_minus_inverts_the_feedback():
    plus, _, _ = impulse_response(10, 0.6, 0.9, 0.0)
    minus, _, _ = impulse_response(9, 0.6, 0.9, 0.0)
    assert plus[0] == minus[0]                   # the dry impulse
    assert plus != minus
    # the first echo has opposite signs
    k = next(i for i in range(1, len(plus)) if abs(plus[i]) > 0.01)
    assert plus[k] * minus[k] < 0


@needs_rom
def test_a_trigger_or_a_new_type_resets_the_line():
    mem = machine(0.6, 1.0, 0.0)
    x = [0.5] + [0.0] * (BLOCK - 1)
    block(mem, x, 10, trig=True)
    for _ in range(5):
        block(mem, [0.0] * BLOCK, 10)
    assert flt(mem.get(L.state + 4 * CP.S["A"])) != 0.0
    y, _ = block(mem, [0.0] * BLOCK, 10, trig=True)
    assert y == [0.0] * BLOCK                    # retriggered: no old ring, no stale line
    block(mem, x, 10)
    for _ in range(5):
        block(mem, [0.0] * BLOCK, 10)
    y, _ = block(mem, [0.0] * BLOCK, 9)          # COMB+ -> COMB-
    assert y == [0.0] * BLOCK


@needs_rom
def test_zero_feedback_is_the_dry_signal():
    mem = machine(0.5, 0.0, 0.0)
    rng = random.Random(3)
    block(mem, [0.0] * BLOCK, 10, trig=True)
    for _ in range(4):                           # past the gain ramp
        x = [rng.uniform(-0.5, 0.5) for _ in range(BLOCK)]
        y, _ = block(mem, x, 10)
    assert y == [flt(bits(v)) for v in x]


def test_layout_in_ddr_and_l2():
    assert dsp.COMB_SW == 0xBED000
    L2 = CP.layout()
    assert L2.state == dsp.COMB_STATE_DDR and L2.buf == dsp.COMB_BUF_DDR
    assert CP.STATE_WORDS * 4 * 16 <= 0x800
    assert CP.FILTER_TYPES == (9, 10)


def test_the_jumps_between_ping_and_comb_land_on_their_labels():
    import sharc_resolve_jumps as R
    ping = (SHARC / "ping.asm").read_text(encoding="utf-8")
    spec = json.loads((SHARC / "ping.json").read_text(encoding="utf-8"))
    nxt = dsp.PING_SW + spec["instruction_offsets"][R.labels(ping)["wr_p_next"]] // 2
    c = (SHARC / "comb.asm").read_text(encoding="utf-8")
    assert f"IF EQ JUMP {dsp.COMB_SW:#x};" in ping
    back = re.compile(r"JUMP (0x[0-9a-f]+);\s*// ping.asm's wr_p_next")
    assert [int(x, 16) for x in back.findall(c)] == [nxt]
    cs = json.loads((SHARC / "comb.json").read_text(encoding="utf-8"))
    assert int(cs["load_sw"], 16) == dsp.COMB_SW


def test_comb_asm_is_what_its_generator_writes_now():
    import gen_comb_asm
    lit = re.compile(r"(JUMP\s+)0x[0-9a-f]+;|(=\s*)0x[0-9a-f]+(;\s*// return address)")

    def norm(text):
        return lit.sub(lambda m: (m.group(1) or m.group(2)) + "0x0;" + (m.group(3) or "")[1:], text)
    assert norm(gen_comb_asm.build()) == norm((SHARC / "comb.asm").read_text(encoding="utf-8"))


def test_no_committed_source_has_an_unresolved_jump():
    """v0.20 in progress: ping.asm and gran.asm were regenerated (types 9, 10) and committed
    with their branch targets still 0x0; the SHARC gate's first PING block jumped to 0.
    Every committed source has its targets filled (scripts/sharc_resolve_jumps.py)."""
    for f in sorted(SHARC.glob("*.asm")):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"JUMP\s+0x0;", text), f.name
        assert not re.search(r"=\s*0x0;\s*// return address", text), f.name


def _env_expected(atk_v, dec_v, blocks):
    """SHFT's envelope a block at a time: the value at each block's start."""
    from dnfw.perc.dsl import f32
    T = PGL.tables()
    atk, dec = PGL.at127(T["atk"], atk_v), PGL.at127(T["dec"], dec_v)
    stage, x, out = 1, 0.0, []
    for _ in range(blocks):
        a = 0.0
        if stage == 2:
            d = f32(1.0 - x)
            a = f32(f32(d * d) * d)
            x = f32(x + f32(dec * 32.0))
            if x >= 1.0:
                stage, x = 0, 0.0
        elif stage == 1:
            a = x
            x = f32(x + f32(atk * 32.0))
            if x >= 1.0:
                stage, x = 2, 0.0
        out.append(a)
    return out


@needs_rom
@pytest.mark.parametrize("atk,dec", [(0.3, 0.4), (0.0, 0.2), (0.6, 0.0)])
def test_the_envelope_moves_freq_by_env_depth(atk, dec):
    base = 0.4
    want = _env_expected(atk, dec, 60)
    for depth, sign in ((1.0, 1.0), (0.0, -1.0), (0.75, 0.5)):
        mem = machine(base, 0.5, 0.0, depth=depth, atk=atk, dec=dec)
        got = []
        for b in range(60):
            block(mem, [0.0] * BLOCK, 10, trig=(b == 0))
            got.append(flt(mem.get(L.state + 4 * CP.S["f"])))
        exp = [min(max(base + sign * a, 0.0), 1.0) for a in want]
        assert got == pytest.approx(exp, abs=1e-6), (depth, atk, dec)
    assert max(want) > 0.2                                # it moves


@needs_rom
def test_env_depth_at_the_centre_changes_nothing():
    a, _, _ = impulse_response(10, 0.6, 0.9, 0.0)
    mem = machine(0.6, 0.9, 0.0, depth=0.5, atk=0.1, dec=0.1)
    out = []
    for b in range(40):
        x = [0.0] * BLOCK
        if b == 0:
            x[0] = 0.5
        y, _ = block(mem, x, 10, trig=(b == 0))
        out += y
    assert out == a

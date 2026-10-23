"""GRAN, the granular effect (filter type 8, docs/gran.md): the model's properties, the
layout, and the jumps between gran.asm and ping.asm. The SHARC gate (step 7b) holds
gran.asm to dnfw.grain.live bit for bit."""

from __future__ import annotations

import json
import math
import pathlib
import re
import sys

from dnfw.grain import live as G
from dnfw.ping import coldfire as PCF
from dnfw.ping import live as P
from dnfw.ping import pages as PP
from dnfw.waverider import dsp

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARC = ROOT / "csrc" / "waverider" / "sharc"
sys.path.insert(0, str(ROOT / "scripts"))
T = G.tables()


def rec(size=0.3, dens=1.0, mode=0, sprd=0.5, fdbk=0.0, mix=1.0, drive=0.375):
    return {P.R_TYPE: (mode + 0.5) / 4, P.R_FREQ: size, P.R_RES: dens, P.R_DEPTH: sprd,
            P.R_ATK: fdbk, P.R_CURVE: mix, P.R_DRIVE: drive}


def sine(hz, n, amp=0.5):
    return [G._f32(amp * math.sin(2 * math.pi * hz * k / G.RATE)) for k in range(n)]


def run(r, x):
    v, out = G.Voice(), []
    for b in range(0, len(x), 32):
        out += G.block(v, x[b:b + 32], r, 60.0, False, T)
    return out, v


def crossings(s):
    return sum(1 for a, b in zip(s, s[1:]) if (a < 0) != (b < 0))


def test_mix_0_is_the_dry_signal_bit_for_bit():
    x = sine(220.0, 32 * 40)
    out, _ = run(rec(mix=0.0), x)
    assert out == x


def test_grains_start_at_the_density_and_stay_bounded_with_full_feedback():
    x = sine(330.0, 32 * 300, amp=0.9)
    out, v = run(rec(size=0.0, dens=1.0, fdbk=1.0, sprd=1.0), x)
    assert all(abs(y) <= 1.0 for y in out) and not any(y != y for y in out)
    # 10 ms grains, 4 overlapping: one every 120 samples
    assert v.idx == len(x) // 120 + 1


def test_up_is_an_octave_above_norm_and_down_an_octave_below():
    x = sine(300.0, 32 * 600)
    tail = slice(32 * 300, None)
    norm = crossings(run(rec(mode=0, sprd=0.5), x)[0][tail])
    up = crossings(run(rec(mode=1, sprd=0.5), x)[0][tail])
    down = crossings(run(rec(mode=2, sprd=0.5), x)[0][tail])
    assert 1.8 < up / norm < 2.3 and 0.4 < down / norm < 0.6


def test_grains_never_read_ahead_of_the_write_head():
    """The largest delay any grain needs fits the buffer: UP's L + the scatter + the
    guard ahead, REV's L behind."""
    big = int(max(T["size"]))
    assert G.GUARD + big + G.SCATTER + big < G.BUF_N


def test_the_filter_list_names_and_type_text():
    assert G.FILTER_TYPE in PCF.NEW_FILTERS and PCF.NAMES[8] == ("Grains", "GRAN")
    assert PP.TYPE_TEXT[8] == G.MODES
    assert {PP.SETS[8][r][1] for r in (36, 37, 38, 49, 45, 47)} == {"SIZE", "DENS", "MODE", "SPRD",
                                                                     "FDBK", "MIX"}


def test_layout_code_state_and_ddr():
    obj = dsp.objects()
    assert dsp.GRAN_CODE_DM + len(obj["gran"]) + 64 <= dsp.GRAN_SCRATCH_DM
    assert dsp.GRAN_SCRATCH_DM + 0x100 <= dsp.SHFT_STATE_DM
    assert dsp.GRAN_STATE_DM + 16 * dsp.GRAN_STATE_STRIDE <= dsp.RINGS_CODE_DM
    assert dsp.GRAN_BUF_STRIDE == 4 * G.BUF_N
    spans = {w: (at, len(p)) for w, at, p in dsp.ddr_spans()}
    ordered = sorted((at, at + n) for at, n in spans.values())
    assert all(a1 <= b0 for (_, a1), (b0, _) in zip(ordered, ordered[1:]))
    assert dsp.GRAN_BUF_DDR + 16 * dsp.GRAN_BUF_STRIDE <= 0x85000000     # below the runner's strays


def test_the_jumps_between_ping_and_gran_land_on_their_labels():
    import sharc_resolve_jumps as R
    ping = (SHARC / "ping.asm").read_text(encoding="utf-8")
    spec = json.loads((SHARC / "ping.json").read_text(encoding="utf-8"))
    nxt = dsp.PING_SW + spec["instruction_offsets"][R.labels(ping)["wr_p_next"]] // 2
    g = (SHARC / "gran.asm").read_text(encoding="utf-8")
    assert f"IF EQ JUMP {dsp.GRAN_SW:#x};" in ping
    back = re.compile(r"JUMP (0x[0-9a-f]+);\s*// ping.asm's wr_p_next")
    assert [int(x, 16) for x in back.findall(g)] == [nxt]
    gs = json.loads((SHARC / "gran.json").read_text(encoding="utf-8"))
    assert int(gs["load_sw"], 16) == dsp.GRAN_SW


def test_every_generated_asm_is_what_its_generator_writes_now():
    """v0.10's gate caught RESONATOR and CZ still reading SHFT's tables from L1 after the
    tables moved to DDR: their asm had not been regenerated. Each generated source must
    equal its generator's output today, branch targets aside (the resolver fills those)."""
    import importlib
    lit = re.compile(r"(JUMP\s+)0x[0-9a-f]+;|(=\s*)0x[0-9a-f]+(;\s*// return address)")

    def norm(text):
        return lit.sub(lambda m: (m.group(1) or m.group(2)) + "0x0;" + (m.group(3) or "")[1:], text)
    for gen, name in (("gen_ping_asm", "ping"), ("gen_rings_asm", "rings"), ("gen_cz_asm", "cz"),
                      ("gen_gran_asm", "gran")):
        mod = importlib.import_module(gen)
        import gen_ping_asm
        gen_ping_asm.n_label[0] = 0                     # labels count from a fresh run's
        built = mod.build()
        built = built[0] if isinstance(built, tuple) else built
        assert norm(built) == norm((SHARC / f"{name}.asm").read_text(encoding="utf-8")), name
    import gen_perc_asm                                 # v0.11: PERC (osc 2 went with Waverider)
    assert norm(gen_perc_asm.build()) == norm((SHARC / "perc.asm").read_text(encoding="utf-8"))

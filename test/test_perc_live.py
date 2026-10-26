"""PERC (docs/perc.md, docs/md.md): the model -- dnfw.perc.program run in Python, the same
program the SHARC runs (the runner holds the DSP to it bit for bit). Since v0.17 its
machines are the Machinedrum's (dnfw.md): test/test_md.py holds each machine to the
Machinedrum's own output; here the whole PERC voice is held to it, at 48 kHz, through the
frame's controls."""

from __future__ import annotations

import math

import pytest

from dnfw.md import bench as MDB
from dnfw.md import core as MDK
from dnfw.md import machines as MM
from dnfw.perc import live as PL
from dnfw.perc import machines as PM
from dnfw.perc import program as PP


def _catmull(a, b, c, d, f):
    return b + 0.5 * f * (c - a + f * (2 * a - 5 * b + 4 * c - d + f * (3 * (b - c) + d - a)))


def _resampled(md: list[float], n: int) -> list[float]:
    """The Machinedrum's 44.1 kHz output as the voice reads it: its position is a float32
    (dnfw.md.voice), 35 down to 3 as each block of the stream moves on, so this keeps it
    the same way rather than as an exact count."""
    from dnfw.perc.dsl import f32
    stream = [0.0] * 35 + md + [0.0] * 64
    out, pos, base, step = [], f32(35.0), 0, f32(MDK.STEP)
    while len(out) < n:
        if pos >= 35.0:
            pos, base = f32(pos - 32.0), base + 32
        for _ in range(32):
            i = int(pos)
            j = base + i - 32                  # the stream as B holds it after the move
            out.append(PP.MD_LEVEL * _catmull(*stream[j - 1:j + 3], pos - i))
            pos = f32(pos + step)
    return out[:n]


def _record_value(knob: int, top: int) -> float | None:
    """the 0..1 control on a record of TOP steps that lands on the Machinedrum KNOB, if any"""
    for k in range(top + 1):
        if int(k / top * 127.0 + 0.5) == knob:
            return k / top
    return None


def test_every_machine_is_the_machinedrums():
    assert PM.NAMES == MM.NAMES and PM.N == 34          # v0.24: and the nine P-I machines
    assert set(PM.NAMES) == set(MM.DEFAULTS)


@pytest.mark.parametrize("name", PM.NAMES)
def test_the_voice_plays_the_machinedrums_default_hit_at_48k(name):
    """Each machine's 'default' golden case (the MD's own output at its default knobs), read
    through the voice's Catmull-Rom at 0.91875 samples a sample, x the level: the PERC
    voice, from the frame's records, gives the same."""
    if not MDB.golden_available():
        pytest.fail("no reference (docs/md.md)")
    case = MDB.golden(name)["cases"][0]
    assert case["name"] == "default"
    inputs, start = case["events"][0][1], 0
    if getattr(MM.MACHINES[MM.NAMES.index(name)], "INIT_FIRST", False):
        # v0.24: its first note after the machine is chosen is silent on the MD; the voice
        # runs its init first, so that note is the MD's second (golden 'second_hit')
        case = next(c for c in MDB.golden(name)["cases"] if c["name"] == "second_hit")
        start, inputs = case["events"][1][0], case["events"][1][1]
    params = []
    for (_rid, _slot, _lo, top), x in zip(PM.PARAMS, inputs):
        v = _record_value(x >> 7, top)
        if v is None:
            pytest.skip(f"knob {x >> 7} is not on a {top}-step record")
        params.append(v)
    h = PL.Harness()
    h.set_controls(PM.NAMES.index(name), params)
    ours = []
    for b in range(case["nblocks"] - start - 4):
        ours += h.block(60.0, b == 0)
    want = _resampled(MDB.unpack(case["out"])[32 * start:], len(ours))
    r = MDB.compare(ours, want)
    assert r["snr_db"] > 60 or r["rms_err"] < 2 ** -20, r


def test_the_model_is_finite_and_silent_without_a_note():
    h = PL.Harness()
    h.set_controls(0, PL.defaults(PM.NAMES[0]))
    assert all(x == 0.0 for _ in range(4) for x in h.block(60.0, False))


def test_two_slots_keep_their_own_state():
    a, b = PL.Harness(0), PL.Harness(5)
    a.set_controls(PM.NAMES.index("TRX-SD"), PL.defaults("TRX-SD"))
    b.set_controls(PM.NAMES.index("TRX-BD"), PL.defaults("TRX-BD"))
    b.mem = a.mem                              # one memory, two slots
    xa, xb = [], []
    for k in range(4):
        xa += a.block(60.0, k == 0)
        xb += b.block(60.0, k == 0)
    ref = PL.Harness(0)
    ref.set_controls(PM.NAMES.index("TRX-SD"), PL.defaults("TRX-SD"))
    alone = []
    for k in range(4):
        alone += ref.block(60.0, k == 0)
    assert xa == alone and xa != xb and all(math.isfinite(v) for v in xa + xb)


def test_the_program_assembles_from_the_model():
    from dnfw.waverider import dsp
    text = PP.program(PL.layout(), dsp.SMP_SW)
    lines = [ln for ln in text.splitlines() if ln.startswith("      ") and not ln.strip().startswith("//")]
    assert 5000 < len(lines) < 30000
    assert f"JUMP {dsp.SMP_SW:#x};" in text


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
# (v0.17: the voices are the Machinedrum's; the effects are still Ravel's, after the voice)
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
    k = PM.NAMES.index("TRX-SD")
    assert PL.Harness().render(k, PL.defaults("TRX-SD"), 0.01, fx=PL.FX_OFF) == \
        PL.Harness().render(k, PL.defaults("TRX-SD"), 0.01)


def test_v026_the_monomachine_costs_cover_what_each_voice_takes():
    """each Monomachine machine's MNM_COST is at least the instructions its voice takes in a
    DN2 block (the model's steps), at its defaults, every knob up, every knob down and a few
    random settings, over notes an octave apart"""
    import random
    from dnfw.md import core as MDK
    from dnfw.mnm import dpro, machines as MM
    from dnfw.mnm import rom as MROM
    if not MROM.available():
        pytest.skip("needs the owner's Monomachine OS")
    rnd = random.Random(1)
    for typ, k in PP.MNM_TYPES.items():
        name = MM.NAMES[k]
        worst = 0
        for knobs in [list(MM.DEFAULTS[name]), [127] * 8, [0] * 8] + [[rnd.randrange(128) for _ in range(8)]
                                                                     for _ in range(3)]:
            h = PL.Harness()
            h.words.update(dpro.bench_words(h.L.md.mnm))
            h.words[h.L.md.C["fill"]] = MDK.Z_N
            h.set_mnm(typ, knobs)
            for b in range(6):
                h.steps = 0
                h.block(note=60 + 12 * (b % 3), trig=b == 0)
                worst = max(worst, h.steps)
        assert worst <= PP.MNM_COST[name], (name, worst)
    assert PP.MNM_BUDGET >= max(PP.MNM_COST[n] for n in MM.NAMES)    # any one of them alone plays

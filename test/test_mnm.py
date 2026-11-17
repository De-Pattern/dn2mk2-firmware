"""The Monomachine machines (docs/mnm.md) against the Monomachine's own output.

The golden runs are the Monomachine's DSP code run in an emulator, outside the repository
(`MNM_GOLDEN`; the firmware is Elektron's): every case of every machine, in run mode, with
the increments exactly the Monomachine's, within 60 dB signal-to-error. And each machine's
`pitch` (the increments from the DN2's pitch, in float) against the exact ones."""

from __future__ import annotations

import pytest

from dnfw.mnm import bench, ddrw, dens, fm, rom, sid, vo6, wave
from dnfw.mnm import core as C

MACHINES = {"WAVE": wave, "SID": sid, "DENS": dens, "DDRW": ddrw, "VO6": vo6,
            "FMSTAT": fm.Stat, "FMPAR": fm.Par, "FMDYN": fm.Dyn}       # v0.59: FM+
pytestmark = pytest.mark.skipif(not (rom.available() and bench.GOLDEN.is_dir()),
                                reason="needs the owner's Monomachine OS and the golden runs")


def _cases():
    out = []
    for name in MACHINES:
        if (bench.GOLDEN / f"{name}.json").exists():
            out += [(name, c["name"]) for c in bench.golden(name)["cases"]]
    return out


_G = {}


def _golden(name):
    if name not in _G:
        _G[name] = {c["name"]: c for c in bench.golden(name)["cases"]}
    return _G[name]


def _trimmed(M) -> bool:
    """v0.51: a machine re-made lighter, not bit for bit: SID below 12x (sid.OS), DDRW and DENS
    below 2x (dpro.OS), VO-6's series formants in float (vo6.SER_EXACT)"""
    from dnfw.mnm import dpro
    if M is sid:
        return sid.OS != 12
    if M in (ddrw, dens):
        return dpro.OS != 2
    if M is vo6:
        return not vo6.SER_EXACT
    return False


@pytest.mark.parametrize("name,case", _cases())
def test_against_the_monomachine(name, case):
    M = MACHINES[name]
    g = _golden(name)[case]
    ours, theirs = bench.run_case(M, g)
    if _trimmed(M):
        # v0.51: held by its level and spectrum (bench.likeness); NOIS by its level
        noise = name == "SID" and any(e[1] and e[1][3] >= 103 for e in g["events"])
        r = bench.likeness(ours, theirs, noise)
        assert r["ok"], {k: v for k, v in r.items() if k != "ok"}
        return
    r = bench.compare(ours, theirs)
    if _chaotic(M, g):
        # v0.59: FM+'s self feedback at 32 and above (dnfw.mnm.fm): within 60 dB, or held by its
        # level and spectrum as the trimmed machines are
        assert r["snr_db"] >= 60.0 or bench.likeness(ours, theirs)["ok"], r
        return
    assert r["snr_db"] >= 60.0 or r["rms_err"] < 2.0 ** -20, r


def _chaotic(M, g) -> bool:
    k = getattr(M, "FB_KNOB", None)
    return k is not None and any(e[1] and e[1][k] >= 32 for e in g["events"])


def test_fm_chaotic_cases_are_only_the_self_feedback_ones():
    """the negative control for the FM+ rule: the likeness test refuses a chaotic case 6 dB
    down, and a case without self feedback (FM+ PAR's all; STAT's, DYN's at FB 0) is held to
    60 dB"""
    for name in ("FMSTAT", "FMDYN"):
        M = MACHINES[name]
        cases = bench.golden(name)["cases"]
        hot = [c for c in cases if _chaotic(M, c)]
        cold = [c for c in cases if not _chaotic(M, c)]
        assert hot and cold
        ours, theirs = bench.run_case(M, hot[-1])
        assert not bench.likeness([v * 0.5 for v in ours], theirs)["ok"]
    assert not any(_chaotic(fm.Par, c) for c in bench.golden("FMPAR")["cases"])


@pytest.mark.parametrize("name", [n for n, M in MACHINES.items() if _trimmed(M)])
def test_trimmed_likeness_fails_a_wrong_level(name):
    """the negative control: the likeness test refuses the same output 6 dB down (a trimmed
    machine's decimator shift one bit off: v0.51's first measurement of SID at 4x)"""
    g = bench.golden(name)["cases"][0]
    ours, theirs = bench.run_case(MACHINES[name], g)
    assert bench.likeness(ours, theirs)["ok"]
    assert not bench.likeness([v * 0.5 for v in ours], theirs)["ok"]


@pytest.mark.parametrize("name", list(MACHINES))
def test_pitch(name):
    """the float increments within 1e-4 of the integer ones (a fraction of a cent)"""
    from dnfw.mnm import exact as X
    from dnfw.perc.dsl import Prog
    M = MACHINES[name]
    knobs = [0, 0, 0, 0, 0, 0, 64, 64]
    for F in range(0x800, 0x5000, 0x377):
        A = X.increment(F)
        b = bench.Bench(M)
        p = b._prog()
        for k, x in enumerate(knobs):
            p.fconst(0, x / 128.0)
            p.sti(C.P0 + k, 3, 0)
        p.fconst(0, A / 2.0 ** 24)
        C.vws(p, "A", 0)
        M.pitch(p, b.L)
        want = M.exact(A, F, knobs)
        got = b.mem.get(b.L.md.state + 4 * C.VW["i1"])
        assert abs(got - want["i1"]) <= max(2, 1e-4 * want["i1"]), (F, got, want)


def test_vo6_tables_where_the_layout_says():
    """VO-6's tables (rom.vo6_words) sit in rom.table_words where core.Layout addresses them"""
    L = bench.layout()
    words = rom.table_words()
    at = (L.VO["c1"] - L.tables) // 4
    assert words[at:at + len(rom.vo6_words())] == rom.vo6_words()
    assert sum(n for _, n in C.VO_TABLES) == len(rom.vo6_words())


def test_digibank_room():
    """DPRO's stand-in (built by the DSP, 256 KB at the Monomachine tables + DIGI_OFF) lies past
    the Machinedrum/Monomachine tables' end and below the Machinedrum voices (1 MB on)."""
    from dnfw.md import core as K
    mnm = K.TABLE_LAYOUT["mnm"][0]
    lo, hi = mnm + C.DIGI_OFF, mnm + C.DIGI_OFF + 4 * C.DIGI_WORDS
    assert lo >= K.TABLE_LAYOUT["_end"][0] and hi <= 0x100000, (hex(lo), hex(hi))


# v0.56 (owner: "time in ddrw is not working ... BR1 and BR2 controls are 99% inaudible";
# docs/ddrw-fix.md): the DN2's host maps DDRW's BR and TIME; the Monomachine's model and its
# references (above) are untouched (gl 0 there: g = 1.0)
def _ddrw_host(inputs):
    import struct
    from dnfw.md import core as K
    from dnfw.mnm import machines as MM
    b = bench.Bench(ddrw)                                   # its memory and tables
    L = b.L.md                                              # the layout the DSP's host is given
    p = b._prog()
    for k, x in enumerate(inputs):
        p.iconst(0, x)
        p.sti(K.INP0 + k, 3, 0)
    MM._host_ddrw(p, L)
    f = lambda a: struct.unpack("<f", struct.pack("<I", b.mem.get(a) & 0xFFFFFFFF))[0]   # noqa: E731
    knobs = [round(f(L.state + 4 * (K.W0 + C.P0 + k)) * 128) for k in range(8)]
    return knobs, f(L.mnm.W["gl"])


@pytest.mark.parametrize("br,want", [(0, 0), (1, 64), (64, 95), (127, 127)])
def test_ddrw_br_mapped(br, want):
    knobs, _ = _ddrw_host([5 << 7, 64 << 7, 9 << 7, 0, br << 7, 3 << 7, br << 7, 64 << 7])
    assert knobs == [5, 64, 9, 0, want, 3, want, 64]       # BR1, BR2 mapped; the rest as sent


@pytest.mark.parametrize("t", [0, 16, 64, 127])
def test_ddrw_time_glide(t):
    from dnfw.mnm import machines as MM
    _, g = _ddrw_host([0, 0, 0, t << 7, 0, 0, 0, 64 << 7])
    want = 0.0 if t == 0 else (t + 1) / (MM.DDRW_RATE * (1 + MM.DDRW_FADE * t * t))
    assert g == pytest.approx(want, rel=1e-4)


def test_ddrw_time_fades_for_its_time():
    """a WAV1 change mid-note at TIME 16 (g as the host gives it) differs from the instant change
    for about 30 ms (1 + c 16^2 half-renders); the model's own (no host: gl 0) is instant"""
    import math
    import struct
    from dnfw.mnm import machines as MM
    c = bench.golden("DDRW")["cases"][0]

    def render(t, glide, n=160):
        b = bench.Bench(ddrw)
        out = []
        for blk in range(n):
            if glide:
                g = (t + 1) / (MM.DDRW_RATE * (1 + MM.DDRW_FADE * t * t))
                b.mem.put(b.L.W["gl"], struct.unpack("<I", struct.pack("<f", g))[0])
            A, F = c["A"][min(blk, 31)], c["F"][min(blk, 31)]
            knobs = [40 if blk >= 10 else 0, 0, 0, t, 0, 0, 0, 64]
            out += b.block(A, F, knobs, blk == 0) if blk in (0, 10) else b.block(A, F)
        return out
    inst, slow, model = render(0, False), render(16, True), render(16, False)
    d = [math.sqrt(sum((x - y) ** 2 for x, y in zip(slow[16 * k:16 * k + 16], inst[16 * k:16 * k + 16])) / 16)
         for k in range(160)]
    last = max(k for k in range(160) if d[k] > 1e-3)
    assert 60 <= last - 10 <= 120                           # 1 + 0.372 x 256 = 96 half-renders
    assert model == inst                                    # the Monomachine's own: TIME inaudible

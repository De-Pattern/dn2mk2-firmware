"""The Monomachine machines (docs/mnm.md) against the Monomachine's own output.

The golden runs are the Monomachine's DSP code run in an emulator, outside the repository
(`MNM_GOLDEN`; the firmware is Elektron's): every case of every machine, in run mode, with
the increments exactly the Monomachine's, within 60 dB signal-to-error. And each machine's
`pitch` (the increments from the DN2's pitch, in float) against the exact ones."""

from __future__ import annotations

import pytest

from dnfw.mnm import bench, ddrw, dens, rom, sid, vo6, wave
from dnfw.mnm import core as C

MACHINES = {"WAVE": wave, "SID": sid, "DENS": dens, "DDRW": ddrw, "VO6": vo6}
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


@pytest.mark.parametrize("name,case", _cases())
def test_against_the_monomachine(name, case):
    ours, theirs = bench.run_case(MACHINES[name], _golden(name)[case])
    r = bench.compare(ours, theirs)
    assert r["snr_db"] >= 60.0 or r["rms_err"] < 2.0 ** -20, r


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

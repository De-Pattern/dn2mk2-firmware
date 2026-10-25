"""The Monomachine machines (docs/mnm.md) against the Monomachine's own output.

The golden runs are the Monomachine's DSP code run in an emulator, outside the repository
(`MNM_GOLDEN`; the firmware is Elektron's): every case of every machine, in run mode, with
the increments exactly the Monomachine's, within 60 dB signal-to-error. And each machine's
`pitch` (the increments from the DN2's pitch, in float) against the exact ones."""

from __future__ import annotations

import pytest

from dnfw.mnm import bench, rom, sid, wave
from dnfw.mnm import core as C

MACHINES = {"WAVE": wave, "SID": sid}
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

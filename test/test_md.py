"""The Machinedrum machines (docs/md.md): each held to the Machinedrum's own output.

The reference (golden vectors from DSP2's own code in a DSP56300 emulator, and the
firmware's tables) is Elektron's, read from the owner's files beside the repository
(dnfw.md.rom, dnfw.md.bench); without them these tests cannot run, and the ship gate
counts that as a failure (CLAUDE.md: an unchecked gate is a failed gate)."""

import pytest

from dnfw.md import bench as B
from dnfw.md import machines as MM

# how close a case must be: the signal-to-error ratio over the case, or an error so
# small it is below the 24-bit floor anyway
MIN_SNR_DB = 60.0
QUIET_RMS = 2.0 ** -20
LOWER = {}                                    # name -> a looser bound, with its reason


def test_the_reference_is_there():
    assert B.golden_available(), ("the Machinedrum's firmware and golden vectors are needed: "
                                  "MD_OS_BIN, MD_GOLDEN (docs/md.md)")


@pytest.mark.parametrize("name", MM.NAMES)
def test_machine_matches_the_machinedrum(name):
    if not B.golden_available():
        pytest.fail("no reference: see test_the_reference_is_there")
    M = MM.BY_NAME[name]
    bad = []
    for case in B.golden(name)["cases"]:
        ours, theirs = B.run_case(M, case)
        r = B.compare(ours, theirs)
        if r["snr_db"] < LOWER.get(name, MIN_SNR_DB) and r["rms_err"] > QUIET_RMS:
            bad.append((case["name"], round(r["snr_db"], 1), r["rms_err"]))
    assert not bad, f"{name}: {bad}"


def _catmull(a, b, c, d, f):
    return b + 0.5 * f * (c - a + f * (2 * a - 5 * b + 4 * c - d + f * (3 * (b - c) + d - a)))


def test_the_voice_resamples_the_machine_to_48k():
    """A slot through dnfw.md.voice: GND-SN's default case, at 48 kHz, is the Machinedrum's
    own 44.1 kHz output read by the same Catmull-Rom at 0.91875 samples a sample, within
    the machine's own error."""
    if not B.golden_available():
        pytest.fail("no reference")
    import struct
    from dnfw.md import core as K, voice as V
    from dnfw.perc.dsl import Mem, Prog
    case = B.golden("GND-SN")["cases"][0]
    inputs, _trig = case["events"][0][1], case["events"][0][2]
    L = B.layout()
    tm = B.table_mem(L)
    mem = Mem(lambda a: tm.get(a, 0))
    knobs = [0x2DF800 + 4 * k for k in range(8)]
    out_at = 0x2DF900
    mem.put(L.C["mdb"], L.state)
    ours = []
    want_i = MM.NAMES.index("GND-SN")
    for blk in range(40):
        p = Prog("run", mem=mem)
        p.i[3] = L.state
        if blk == 0:
            V.reset(p, L)
        for k, x in enumerate(inputs):
            p.fconst(0, x / V.KNOB_SCALE)
            p.st(knobs[k], 0)
        p.iconst(2, 1 if blk == 0 else 0)
        p.iconst(3, want_i)
        p.iconst(0, out_at)
        p.seti(4, 0)
        V.block(p, L, knobs, 2, 3)
        ours += [struct.unpack("<f", struct.pack("<I", mem.get(out_at + 4 * k)))[0] for k in range(32)]
    md = B.unpack(case["out"])
    stream = [0.0] * 35 + md                 # the first block arrives after one of silence
    want, pos = [], 3.0
    for _ in range(len(ours)):
        i = int(pos)
        want.append(_catmull(*stream[i - 1:i + 3], pos - i))
        pos += K.STEP
    r = B.compare(ours, want)
    assert r["snr_db"] > 60, r

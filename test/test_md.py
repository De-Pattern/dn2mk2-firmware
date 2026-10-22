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

"""FASCIA's approved sound (owner, 2026-11-07, the pass-3 tour): the design model still
renders every audition patch's first second within 2 LSB of the goldens
(scripts/fascia_golden.py; the private bench's goldens/fascia, installed by its setup.sh
at ../fascia-golden or FASCIA_GOLDEN). A missing golden is a failure, not a skip."""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fascia_golden as G  # noqa: E402

GOLDEN = Path(os.environ.get("FASCIA_GOLDEN", ROOT.parent / "fascia-golden"))
INDEX = json.loads((GOLDEN / "index.json").read_text()) if (GOLDEN / "index.json").exists() else None


def test_goldens_present():
    assert INDEX is not None, f"FASCIA goldens missing at {GOLDEN} (bench setup.sh installs them)"
    assert set(INDEX["patches"]) == set(G.A.PATCHES)


@pytest.mark.parametrize("name", list(G.A.PATCHES))
def test_patch_matches_golden(name):
    assert INDEX is not None
    want = np.load(GOLDEN / f"{name}.npy").astype(np.int32)
    got = G.render(name).astype(np.int32)
    assert got.shape == want.shape
    assert int(np.max(np.abs(got - want))) <= 2, name

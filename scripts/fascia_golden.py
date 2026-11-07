"""FASCIA's sound, locked: the owner approved the pass-3 tour on 2026-11-07 ("they're all
perfect ... that will be the new engine, exactly as you made it"). This writes each
audition patch's first second, as the design model renders it, to int16 .npy files and an
index; test/test_fascia_golden.py holds the model to them (2 LSB), so no later change
moves the approved sound by accident. The goldens live in the private bench repo
(dn2mk2-bench, goldens/fascia; setup.sh installs them at ../fascia-golden).

    PYTHONPATH=src python3 scripts/fascia_golden.py OUTDIR
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fascia_audition as A  # noqa: E402
from dnfw.fascia import model as R  # noqa: E402

SECONDS = 1.0


def render(name: str) -> np.ndarray:
    p, evs, _secs, trem = A.PATCHES[name]
    x = R.render_notes(p, [e for e in evs if e[0] < SECONDS], SECONDS)
    if trem:
        x = x * (1.0 - 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * trem * np.arange(len(x)) / R.RATE)))
    return np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")


def main(out: str) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for name in A.PATCHES:
        x = render(name)
        np.save(out / f"{name}.npy", x)
        index[name] = hashlib.sha256(x.tobytes()).hexdigest()
        print(name, index[name][:12])
    (out / "index.json").write_text(json.dumps({"seconds": SECONDS, "patches": index}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])

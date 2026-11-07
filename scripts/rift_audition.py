"""Render RIFT's design model to WAVs for listening (docs/rift.md).

    PYTHONPATH=src python3 scripts/rift_audition.py OUTDIR

Writes one WAV a patch (a few hits at different velocities) and `rift_tour.wav`
(every patch in a row), 48 kHz mono 16-bit.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np

from dnfw.rift import model as R

C = lambda name, opt: int((R.CHOICES[name].index(opt) + 0.5) * 128 / len(R.CHOICES[name]))

PATCHES = {
    "01_tuned_kick": dict(BODA=C("BODA", "MEMB"), TUNE=40, DAMP=70, HARD=70, BEND=60, MATL=10,
                          LPG=80, CHAR=30, POS=20),
    "02_snare_membrane_blow": dict(BODA=C("BODA", "MEMB"), BODB=C("BODB", "PLATE"), TYPB=C("TYPB", "BLOW"),
                                   MIX=70, HARD=110, DEC=25, DAMP=85, COUP=50, TUNE=70, MATL=60),
    "03_woodblock": dict(BODA=C("BODA", "BAR"), MATL=0, DAMP=95, HARD=120, TUNE=90, POS=30),
    "04_marimba": dict(BODA=C("BODA", "BAR"), MATL=25, DAMP=55, HARD=60, TUNE=64, POS=35, GEOM=58),
    "05_bell_plate": dict(BODA=C("BODA", "PLATE"), MATL=127, DAMP=20, HARD=100, GEOM=75, TUNE=76),
    "06_tzfm_clank": dict(TYPA=C("TYPA", "TZFM"), TZFM=110, SIDE=70, BODA=C("BODA", "PLATE"), MATL=110,
                          DAMP=55, DEC=15, CHAR=20),
    "07_dust_rattle": dict(TYPA=C("TYPA", "DUST"), DUST=90, DEC=60, BODA=C("BODA", "MEMB"),
                           BODB=C("BODB", "PLATE"), MIX=0, DAMP=80, MATL=90, COUP=40),
    "08_bowed_plate": dict(TYPA=C("TYPA", "BOW"), DEC=110, BODA=C("BODA", "PLATE"), MATL=115, DAMP=25,
                           HARD=50, MIX=0),
    "09_wood_to_metal_morph": dict(BODA=C("BODA", "BAR"), MATL=40, DAMP=30, MORPH=127, GEOM=50,
                                   HARD=100, TZFM=50, SIDE=55, FORM=90),
    "10_ring_coupled_toms": dict(BODA=C("BODA", "MEMB"), BODB=C("BODB", "TUBE"), COUP=90, RING=70,
                                 DAMP=60, TUNE=55, BEND=40),
    "11_shifted_hat": dict(TYPA=C("TYPA", "BLOW"), BODA=C("BODA", "PLATE"), MATL=127, DAMP=105, HARD=127,
                           SHIFT=100, MIX=0, DEC=8, TUNE=110),
    "12_pulse_zap_folded": dict(TYPA=C("TYPA", "PULSE"), BEND=127, DEC=10, BODA=C("BODA", "STRING"),
                                DAMP=80, FOLD=60, CHAR=40),
}

HITS = [(0.0, 48, 1.0), (0.6, 48, 0.6), (1.2, 48, 0.3), (1.8, 55, 1.0)]
CHORD = [(0.0, 60, 0.9), (0.0, 64, 0.9), (0.0, 67, 0.9), (0.0, 71, 0.9)]


def write(path: Path, x: np.ndarray) -> None:
    pk = float(np.max(np.abs(x))) or 1.0
    x = x / max(pk, 1.0) * 0.98
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(R.RATE))
        w.writeframes((x * 32767).astype("<i2").tobytes())


def main(out: str) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tour = []
    for name, p in PATCHES.items():
        t = time.time()
        evs = CHORD if name in ("04_marimba", "05_bell_plate") else HITS
        secs = 3.5 if name.startswith(("05", "08", "09")) else 2.6
        x = R.render_notes(p, evs, secs)
        assert np.all(np.isfinite(x)), name
        write(out / f"{name}.wav", x)
        tour.append(x / max(float(np.max(np.abs(x))), 1e-9) * 0.8)
        tour.append(np.zeros(int(0.3 * R.RATE)))
        print(f"{name}: peak {np.max(np.abs(x)):.3f}  {time.time() - t:.1f}s")
    write(out / "rift_tour.wav", np.concatenate(tour))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/rift")

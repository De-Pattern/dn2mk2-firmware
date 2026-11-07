"""Render FASCIA's design model to WAVs for listening (docs/fascia.md).

    PYTHONPATH=src python3 scripts/fascia_audition.py OUTDIR

Writes one WAV a patch (a few hits at different velocities) and `fascia_tour.wav`
(every patch in a row), 48 kHz mono 16-bit.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np

from dnfw.fascia import model as R

C = lambda name, opt: int((R.CHOICES[name].index(opt) + 0.5) * 128 / len(R.CHOICES[name]))

PHRASE = [(0.0, 60, 0.9), (0.45, 67, 0.7), (0.9, 64, 0.8), (1.35, 72, 1.0), (1.8, 62, 0.5),
          (2.25, 69, 0.8)]
HITS = [(0.0, 48, 1.0), (0.6, 48, 0.6), (1.2, 48, 0.3), (1.8, 55, 1.0)]
CHORD = [(0.0, 60, 0.9), (0.0, 64, 0.9), (0.0, 67, 0.9), (0.0, 71, 0.9)]
CHIMES = [(t, n, v) for t, n, v in zip((0.0, 0.17, 0.41, 0.52, 0.86, 1.1, 1.33, 1.7, 1.95),
                                       (79, 84, 86, 91, 79, 88, 84, 91, 86),
                                       (0.7, 0.4, 0.9, 0.3, 0.6, 0.5, 0.8, 0.35, 0.6))]

# (params, events, seconds, tremolo Hz or 0: the DN2's own LFO on AMP, imitated here)
PATCHES = {
    "01_tubular_bell": (dict(BODA=C("BODA", "CHIME"), MATL=110, DAMP=22, HARD=112, POS=6, TUNE=52),
                        PHRASE, 4.5, 0),
    "02_wind_chimes": (dict(BODA=C("BODA", "CHIME"), MATL=118, DAMP=30, HARD=95, POS=10), CHIMES, 4.0, 0),
    "03_vibraphone": (dict(BODA=C("BODA", "VIBE"), BODB=C("BODB", "TUBE"), COUP=70, MATL=96, DAMP=34,
                           HARD=42, POS=28, LPG=20, MIX=0), PHRASE, 4.0, 5.5),
    "04_marimba": (dict(BODA=C("BODA", "VIBE"), BODB=C("BODB", "TUBE"), COUP=80, MATL=18, DAMP=78,
                        HARD=58, POS=30, MIX=0), PHRASE, 3.2, 0),
    "05_plonk_membrane": (dict(BODA=C("BODA", "MEMB"), BEND=62, MATL=30, DAMP=82, HARD=78, POS=18,
                               LPG=70), HITS, 2.6, 0),
    "06_plasticine": (dict(BODA=C("BODA", "STRING"), BODB=C("BODB", "MEMB"), COUP=50, MATL=0, DAMP=92,
                           HARD=28, BEND=38, LPG=100, CHAR=14, POS=35, GEOM=58), PHRASE, 3.0, 0),
    "07_glass_bowl": (dict(BODA=C("BODA", "GLASS"), MATL=100, DAMP=14, HARD=100, POS=50), CHORD, 4.5, 0),
    "08_glass_harmonica": (dict(TYPA=C("TYPA", "BOW"), DEC=112, BODA=C("BODA", "GLASS"), MATL=105,
                                DAMP=30, HARD=50, MIX=0), [(0.0, 72, 0.8), (1.6, 76, 0.8)], 4.0, 0),
    "09_kalimba": (dict(BODA=C("BODA", "BAR"), MATL=82, DAMP=62, HARD=88, POS=8, GEOM=70, BEND=12),
                   PHRASE, 3.2, 0),
    "10_steel_pan": (dict(BODA=C("BODA", "STRING"), BODB=C("BODB", "PLATE"), COUP=35, MATL=108, DAMP=58,
                          HARD=82, POS=20, GEOM=66), PHRASE, 3.2, 0),
    "11_bell_tower": (dict(BODA=C("BODA", "BELL"), MATL=115, DAMP=12, HARD=120, POS=45, TUNE=40),
                      [(0.0, 60, 1.0), (1.5, 55, 0.8)], 5.0, 0),
    "12_gong_morph": (dict(BODA=C("BODA", "PLATE"), MATL=120, DAMP=10, HARD=40, MORPH=70, TUNE=30,
                           POS=40), [(0.0, 48, 1.0)], 5.0, 0),
    "13_tabla": (dict(BODA=C("BODA", "MEMB"), BEND=40, DAMP=72, POS=12, MATL=45, HARD=92, TUNE=72),
                 HITS, 2.6, 0),
    "14_tuned_kick": (dict(BODA=C("BODA", "MEMB"), TUNE=40, DAMP=70, HARD=70, BEND=60, MATL=10,
                           LPG=80, CHAR=30, POS=20), HITS, 2.6, 0),
    "15_tzfm_clank": (dict(TYPA=C("TYPA", "TZFM"), TZFM=110, SIDE=70, BODA=C("BODA", "PLATE"), MATL=110,
                           DAMP=55, DEC=15, CHAR=20), HITS, 2.6, 0),
    "16_wood_to_glass_morph": (dict(BODA=C("BODA", "BAR"), MATL=40, DAMP=30, MORPH=127, GEOM=50,
                                    HARD=100, TZFM=40, SIDE=55), PHRASE, 4.0, 0),
}


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
    for name, (p, evs, secs, trem) in PATCHES.items():
        t = time.time()
        x = R.render_notes(p, evs, secs)
        if trem:
            x = x * (1.0 - 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * trem * np.arange(len(x)) / R.RATE)))
        assert np.all(np.isfinite(x)), name
        write(out / f"{name}.wav", x)
        tour.append(x / max(float(np.max(np.abs(x))), 1e-9) * 0.8)
        tour.append(np.zeros(int(0.3 * R.RATE)))
        print(f"{name}: peak {np.max(np.abs(x)):.3f}  {time.time() - t:.1f}s")
    write(out / "fascia_tour.wav", np.concatenate(tour))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/fascia")

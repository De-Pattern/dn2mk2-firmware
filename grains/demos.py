"""Render the GRAINS demo WAVs from Waverider's two baked tables.

    python grains/demos.py      # writes grains/demos/*.wav
"""

import os
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
from dnfw.waverider import testtable, harmonics          # noqa: E402
from model import Table, render, write_wav, RATE         # noqa: E402

PRIM = Table(testtable.table())     # sine -> saw over 16 frames
HARM = Table(harmonics.table())     # fundamental -> 16th partial

OUT = str(HERE / "demos") + "/"
os.makedirs(OUT, exist_ok=True)

lin = lambda a, b, T: (lambda t: a + (b - a) * min(t / T, 1.0))   # noqa: E731

demos = {
    # 1. the formant: one held C2, FMNT -12 -> +24 semitones; pitch never moves
    "01_sync_formant_sweep": lambda: render(PRIM, 6, 36, pos=15, fmnt=lin(-12, 24, 6), size=2),
    # 2. SIZE: 1 period (buzzy, vocal) -> 4 periods (smooth, close to the plain wave)
    "02_sync_size_sweep": lambda: render(PRIM, 6, 36, pos=15, fmnt=12, size=lin(1, 4, 6)),
    # 3. SPRD: alternate grains' formants pulled apart -> chorus / double-vowel
    "03_sync_spread": lambda: render(PRIM, 6, 43, pos=12, fmnt=7, size=3, sprd=lin(0, 7, 6)),
    # 4. POS + FMNT together on the harmonic table: a talking bass
    "04_sync_talking_bass": lambda: render(HARM, 6, 31, pos=lambda t: 7.5 + 7 * np.sin(t * 2.1),
                                           fmnt=lambda t: 10 * np.sin(t * 1.3), size=1.5),
    # 5. a melody in SYNC mode, to hear it as an instrument
    "05_sync_melody": None,
    # 6. CLOUD: sparse -> dense grains, jittered position, scanning table
    "06_cloud_density": lambda: render(HARM, 8, 60, mode="CLOUD", pos=4, dens=lin(6, 120, 8),
                                       size=8, jitr=0.4, scan=0.6, seed=3),
    # 7. CLOUD with pitch jitter: shimmer / smear
    "07_cloud_pitch_jitter": lambda: render(PRIM, 8, 55, mode="CLOUD", pos=10, dens=60, size=12,
                                            jitr=0.2, pjit=lin(0, 7, 8), seed=5),
}


def melody():
    notes = [36, 43, 48, 46, 41, 43, 39, 41]
    parts = []
    for i, nt in enumerate(notes):
        parts.append(render(PRIM, 0.5, nt, pos=15, fmnt=6 + 3 * (i % 4), size=1.5 + (i % 3) * 0.5,
                            sprd=2) * np.minimum(1, np.linspace(6, 0, int(0.5 * RATE))))
    return np.concatenate(parts)


demos["05_sync_melody"] = melody

for name, fn in demos.items():
    x = fn()
    write_wav(OUT + name + ".wav", x)
    print(name, f"{len(x) / RATE:.1f}s")

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


def CK(kind: str, level: float) -> int:
    """v2: CLIK's value for a click type (its zone) at LEVEL 0..1 within the zone"""
    z = R.CLICKS.index(kind)
    return int(1 + z * 127 / 4 + min(max(level, 0.0), 0.999) * 127 / 4)

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
                           HARD=28, BEND=38, LPG=100, DRIVE=7, POS=35, GEOM=58), PHRASE, 3.0, 0),
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
                           LPG=80, DRIVE=15, POS=20), HITS, 2.6, 0),
    "15_tzfm_clank": (dict(TYPA=C("TYPA", "TZFM"), TZFM=110, BODA=C("BODA", "PLATE"), MATL=110,
                           DAMP=55, DEC=15, DRIVE=10), HITS, 2.6, 0),
    "16_wood_to_glass_morph": (dict(BODA=C("BODA", "BAR"), MATL=40, DAMP=30, MORPH=127, GEOM=50,
                                    HARD=100, TZFM=40), PHRASE, 4.0, 0),
    # SYN4: onsets, clicks and interactions
    "17_snap_click_perc": (dict(BODA=C("BODA", "MEMB"), CLIK=CK("SNAP", 1.0), HARD=127,
                                DAMP=100, MATL=40, TUNE=60), HITS, 2.6, 0),
    "18_tick_on_glass": (dict(BODA=C("BODA", "GLASS"), CLIK=CK("TICK", 0.75), MATL=100,
                              DAMP=40, HARD=110), PHRASE, 3.2, 0),
    "19_thump_tom_choke": (dict(BODA=C("BODA", "MEMB"), BODB=C("BODB", "BELL"), XMOD=C("XMOD", "CHOKE"),
                                COUP=110, CLIK=CK("THUMP", 0.65), DAMP=60, TUNE=50), HITS, 3.0, 0),
    "20_snare_wires": (dict(BODA=C("BODA", "MEMB"), BODB=C("BODB", "PLATE"), BUZZ=80, TYPB=C("TYPB", "BLOW"),
                            MIX=25, HARD=115, DAMP=80, TUNE=72, CLIK=CK("NOISE", 0.4)), HITS, 2.6, 0),
    "21_sitar_jawari_string": (dict(BODA=C("BODA", "STRING"), BUZZ=55, MATL=95, DAMP=35, HARD=100, POS=8),
                               PHRASE, 3.5, 0),
    "22_col_legno_strings": (dict(BODA=C("BODA", "STRING"), BODB=C("BODB", "STRING"), COUP=60,
                                  HARD=127, CLIK=CK("SNAP", 0.85), BUZZ=35, DAMP=70, MATL=70,
                                  POS=4),
                             [(t, n, v) for t, n, v in zip((0, .12, .2, .55, .61, .9, 1.3, 1.36, 1.42),
                                                           (55, 61, 58, 66, 52, 63, 57, 60, 70),
                                                           (1, .6, .8, 1, .5, .7, 1, .6, .9))], 3.0, 0),
    "23_bowed_string_resin": (dict(TYPA=C("TYPA", "BOW"), MIX=0, DEC=105, BODA=C("BODA", "STRING"), MATL=90,
                                   DAMP=40, DUST=45, HARD=17), [(0.0, 48, 0.8), (1.8, 55, 0.9)], 3.8, 0),
    "24_bow_scrape_plate": (dict(TYPA=C("TYPA", "BOW"), MIX=0, DEC=110, BODA=C("BODA", "PLATE"), MATL=110,
                                 DAMP=30, DUST=100, HARD=120), [(0.0, 43, 1.0)], 3.5, 0),
    "25_blown_tube": (dict(TYPA=C("TYPA", "BLOW"), MIX=0, DEC=110, BODA=C("BODA", "TUBE"), MATL=80,
                           DAMP=40, HARD=19, DUST=40), [(0.0, 48, 0.9), (1.6, 51, 0.9)], 3.5, 0),
    "26_bend_coupled_drums": (dict(BODA=C("BODA", "MEMB"), BODB=C("BODB", "MEMB"), XMOD=C("XMOD", "BEND"),
                                   COUP=100, DAMP=65, HARD=95), HITS, 2.6, 0),
    "27_trade_bar_bell": (dict(BODA=C("BODA", "BAR"), BODB=C("BODB", "BELL"), XMOD=C("XMOD", "TRADE"),
                               COUP=90, MATL=100, DAMP=25, HARD=100), PHRASE, 4.0, 0),
    "28_swell_attack_vibe": (dict(BODA=C("BODA", "VIBE"), BODB=C("BODB", "TUBE"), COUP=70, HARD=10, MATL=96,
                                  DAMP=34, MIX=0), PHRASE, 4.0, 5.5),
    "29_water_droplet_vibe": (dict(BODA=C("BODA", "VIBE"), BODB=C("BODB", "TUBE"), COUP=70, MATL=96,
                                   DAMP=34, HARD=70, MIX=0, SKIN=119), PHRASE, 4.0, 0),
    "30_water_glass": (dict(BODA=C("BODA", "GLASS"), MATL=100, DAMP=25, HARD=100, SKIN=127), CHIMES, 4.0, 0),
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

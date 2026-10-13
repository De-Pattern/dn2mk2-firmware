"""Render the PING audition WAVs (docs/ping.md) from Waverider's factory tables.

    python ping/demos.py      # writes ping/demos/*.wav
"""

import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
from dnfw.waverider import factory                      # noqa: E402
from model import RATE, Table, sequence, write_wav       # noqa: E402

TABLES = dict(zip(factory.names(), (Table(t) for t in factory.tables())))
SAW, SINE = 0, 15                                         # PRIM's first and last frames
OUT = HERE / "demos"
OUT.mkdir(exist_ok=True)


def steps(bpm, notes, every=0.25, start=0.1, **over):
    """Notes on a grid: EVERY beats apart; None is a rest."""
    beat = 60.0 / bpm
    return [(start + k * every * beat, n, dict(over)) for k, n in enumerate(notes) if n is not None]


MELODY = [72, None, 79, 76, None, 84, 79, None, 72, 74, None, 79, 76, 72, None, 67]
MARBLE = [84, 84, 91, 84, 88, 84, 91, 96, 84, 84, 91, 84, 88, 93, 91, 88] * 2
BONGO = [60, None, 60, 67, None, 63, 60, None, 60, None, 65, 67, None, 60, 58, None] * 2
BASS = [36, None, 36, 48, None, 36, 43, None, 36, None, 39, 41, None, 36, 34, None]


def demo(name, table, events, seconds, pos=0.0, **kw):
    x = sequence(TABLES[table], events, seconds, pos=pos, **kw)
    write_wav(str(OUT / f"{name}.wav"), x)
    print(f"  {name}.wav  {seconds:.1f} s")


def main():
    # 1. SVF: glassy plucks, keytracked so every ping is in tune
    demo("01_svf_glass", "PRIM", steps(110, MELODY * 2), 5.0, pos=SINE, kind="SVF",
         res=0.78, freq=12, env=0.25, atk=0.2, dec=380, curve=0.7, strike=0.9, drive=0.3, level=0.5)
    # 2. LADR: thick, round 4-pole on the saw, envelope opening it
    demo("02_ladr_thick", "PRIM", steps(100, BASS * 2), 5.0, pos=SAW, kind="LADR",
         res=0.9, freq=0, env=0.55, atk=0.3, dec=260, curve=0.8, strike=0.4, drive=0.7)
    # 3. VCFQ: the marble on the bowl -- strike-led, very high Q, short exp decay, fast
    demo("03_vcfq_marble", "PRIM", steps(140, MARBLE, every=0.25), 3.6, pos=SINE, kind="VCFQ",
         res=0.86, freq=0, env=0.0, atk=0.1, dec=220, curve=0.9, strike=1.0, drive=0.2, level=0.15)
    # 4. LPG: the bongo -- vactrol tail, a little resonance
    demo("04_lpg_bongo", "PRIM", steps(105, BONGO), 4.8, pos=SINE, kind="LPG",
         res=0.6, freq=12, env=0.6, atk=0.1, dec=420, strike=0.8, drive=0.6)
    # 5. CURVE: the same VCFQ ping, log -> linear -> exp, twice each
    ev = []
    for k, c in enumerate((-1.0, -1.0, 0.0, 0.0, 1.0, 1.0)):
        ev.append((0.1 + 0.55 * k, 79, {"curve": c}))
    demo("05_curve_log_lin_exp", "PRIM", ev, 3.8, pos=SINE, kind="VCFQ",
         res=0.8, freq=0, env=0.0, atk=3.0, dec=450, strike=1.0, drive=0.4, level=0.4)
    # 6. RES: each type struck while the ring time rises to its top -- round, never blown
    ev = []
    t = 0.1
    for kind in ("SVF", "LADR", "VCFQ", "LPG"):
        for k in range(6):
            ev.append((t, 67, {"kind": kind, "res": 0.35 + 0.13 * k}))
            t += 0.42
        t += 0.3
    demo("06_resonance_rise_all_types", "PRIM", ev, t + 1.0, pos=SAW, kind="SVF",
         freq=7, env=0.3, atk=0.2, dec=360, curve=0.7, strike=0.9, drive=0.6, level=0.6)
    # 7. the same phrase through SVF, LADR, VCFQ, LPG in turn, on the VOX table
    ev = []
    t = 0.1
    for kind in ("SVF", "LADR", "VCFQ", "LPG"):
        for e in steps(120, MELODY[:8], start=t, kind=kind):
            ev.append(e)
        t += 2.1
    demo("07_types_side_by_side", "VOX", ev, t + 0.6, pos=6, kind="SVF",
         res=0.75, freq=7, env=0.35, atk=0.3, dec=300, curve=0.6, strike=0.7, drive=0.5)
    # 8. hard, fast hits: VCFQ near self-oscillation at 16ths, 150 BPM -- the liquid machine
    hits = [96, 91, 96, 103, 91, 96, 98, 91] * 4
    demo("08_vcfq_liquid_fast", "PRIM", steps(150, hits, every=0.25), 3.6, pos=SINE, kind="VCFQ",
         res=0.93, freq=0, env=0.0, atk=0.1, dec=160, curve=1.0, strike=1.0, drive=0.1, level=0.05)


if __name__ == "__main__":
    main()

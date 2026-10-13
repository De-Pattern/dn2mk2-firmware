"""The owner's three favourites (02, 04, 08), rendered through the DSP contract
(dnfw.ping.live) instead of the model: what the firmware will play.

    python ping/demos_live.py      # writes ping/demos/live_*.wav
"""

import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
import demos as D                                   # noqa: E402
from compare import live_note                       # noqa: E402
from model import note_hz, write_wav                # noqa: E402

RATE = 48000


def sequence(table, events, seconds, pos, **kw):
    n = int(seconds * RATE)
    mix = np.zeros(n)
    for t, note, over in events:
        p = {**kw, **over}
        kind = p.pop("kind")
        length = int(min(seconds - t, (p.get("atk", 0.5) + p.get("dec", 300.0) * 3 + 60) / 1000.0) * RATE)
        length -= length % 32
        if length <= 0:
            continue
        src = D.TABLES[table].osc(note_hz(note), length, pos) * p.pop("level", 1.0)
        freq = p.pop("freq", 0.0)
        y = live_note(kind, note, src, freq=freq, **p)
        start = int(t * RATE)
        mix[start:start + length] += y[:n - start]
    return mix


def main():
    jobs = {
        "live_02_ladr_thick": ("PRIM", D.steps(100, D.BASS * 2), 5.0, D.SAW,
                               dict(kind="LADR", res=0.9, freq=0, env=0.55, atk=0.3, dec=260, curve=0.8,
                                    strike=0.4, drive=0.7)),
        "live_04_lpg_bongo": ("PRIM", D.steps(105, D.BONGO), 4.8, D.SINE,
                              dict(kind="LPG", res=0.6, freq=12, env=0.6, atk=0.1, dec=420, strike=0.8,
                                   drive=0.6)),
        "live_08_vcfq_liquid_fast": ("PRIM", D.steps(150, [96, 91, 96, 103, 91, 96, 98, 91] * 4, every=0.25),
                                     3.6, D.SINE, dict(kind="VCFQ", res=0.93, freq=0, env=0.0, atk=0.1,
                                                       dec=160, curve=1.0, strike=1.0, drive=0.1, level=0.05)),
    }
    for name, (table, ev, sec, pos, kw) in jobs.items():
        write_wav(str(D.OUT / f"{name}.wav"), sequence(table, ev, sec, pos, **kw))
        print(f"  {name}.wav")


if __name__ == "__main__":
    main()

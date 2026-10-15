"""Render the SHFT audition WAVs (docs/shft.md): python shft/demos.py -> shft/demos/*.wav
Each demo plays its phrase dry first, then through SHFT."""

import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from dnfw.waverider import factory                       # noqa: E402
import importlib.util                                     # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load("ping_model", HERE.parent / "ping" / "model.py")
S = _load("shft_model", HERE / "model.py")
Table = P.Table

TABLES = dict(zip(factory.names(), (Table(t) for t in factory.tables())))
OUT = HERE / "demos"
OUT.mkdir(exist_ok=True)
R = S.RATE


def track(table, events, seconds, pos=0.0, dec=0.35, level=0.5):
    """The machine: wavetable notes with a simple amp decay. -> (signal, triggers, notes)."""
    n = int(seconds * R)
    x = np.zeros(n)
    trig, notes = [], []
    for t, note in events:
        i = int(t * R)
        length = min(n - i, int((dec * 4 + 0.05) * R))
        src = TABLES[table].osc(P.note_hz(note), length, pos)
        envl = np.exp(-np.arange(length) / (dec * R)) * np.minimum(1, np.arange(length) / 48)
        x[i:i + length] += src * envl * level
        trig.append(i)
        notes.append(note)
    return x, trig, notes


def steps(bpm, notes, every=0.25, start=0.05):
    beat = 60.0 / bpm
    return [(start + k * every * beat, m) for k, m in enumerate(notes) if m is not None]


def demo(name, table, events, seconds, shft, pos=0.0, dec=0.35, chord=None):
    x, trig, notes = track(table, events, seconds, pos, dec)
    if chord:                                       # extra notes at the same times
        for off in chord:
            y, _, _ = track(table, [(t, m + off) for t, m in events], seconds, pos, dec)
            x = x + y
    wet = S.shifter(x, trig, notes, **shft)
    gap = np.zeros(int(0.4 * R))
    S.write_wav(str(OUT / f"{name}.wav"), np.concatenate([x / (np.max(np.abs(x)) or 1) * 0.7, gap,
                                                        wet / (np.max(np.abs(wet)) or 1) * 0.89]))
    print(f"  {name}.wav")


MEL = [72, None, 79, 76, None, 84, 79, None, 72, 74, None, 79, 76, 72, None, 67]
HITS = [60, None, 60, 60, None, 60, None, 60] * 2


def main():
    # 1. a few Hz up on a chord: slow beating, a phaser-like shimmer
    demo("01_shimmer_3hz_chord", "PRIM", [(0.05, 60), (1.6, 58)], 3.2,
         dict(mode="UP", freq=64 + 63 * (3 / 2500) ** (1 / 3), mix=0.5), pos=6, dec=1.2, chord=(4, 7))
    # 2. a melody shifted down ~180 Hz: harmonic becomes metallic, bell-like
    demo("02_metal_down_melody", "PRIM", steps(110, MEL), 2.4,
         dict(mode="DOWN", freq=64 - 63 * (180 / 2500) ** (1 / 3), mix=1.0), pos=10, dec=0.4)
    # 3. barber-pole: a small shift with heavy feedback climbs for ever
    demo("03_barberpole_feedback", "HARM", [(0.05, 48), (1.5, 55)], 4.0,
         dict(mode="UP", freq=64 + 63 * (6 / 2500) ** (1 / 3), fdbk=0.88, mix=0.8), pos=4, dec=1.5)
    # 4. percussive zaps: the envelope throws the shift on each hit
    demo("04_env_zaps", "PRIM", steps(120, HITS), 2.2,
         dict(mode="DOWN", freq=64, env=0.35, atk=0.2, dec=90, mix=1.0, drive=0.6), pos=15, dec=0.25)
    # 5. BOTH (ring mod) at a fixed 333 Hz: clangorous bells from a sine
    demo("05_both_bells", "PRIM", steps(100, MEL), 2.6,
         dict(mode="BOTH", freq=64 + 63 * (333 / 2500) ** (1 / 3), mix=1.0), pos=15, dec=0.6)
    # 6. a sweep of the shift across the whole range on a held saw
    demo("06_sweep_full_range", "PRIM", [(0.05, 48)], 4.0,
         dict(mode="UP", freq_at=lambda t: 64 + 63 * np.sin(2 * np.pi * t / 4.0), mix=1.0), pos=0, dec=3.0)
    # 7. key tracking: the same shift ratio on every note keeps the colour in tune-ish
    demo("07_keytracked", "VOX", steps(110, MEL), 2.4,
         dict(mode="UP", freq=64 + 63 * (130 / 2500) ** (1 / 3), keyt=1.0, mix=1.0), pos=6, dec=0.4)


if __name__ == "__main__":
    main()

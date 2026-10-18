"""RESONATOR as the DSP renders it (dnfw.rings.live, bit-exact to rings.asm): a few
phrases, so the machine can be heard before it is flashed. python rings/demos_dsp.py"""

import pathlib
import sys
import wave

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from dnfw.rings import live as L          # noqa: E402

T = L.tables()
OUT = HERE / "demos_dsp"
OUT.mkdir(exist_ok=True)
B = L.BLOCK


def render(events, seconds, words, voices=4):
    """EVENTS: (time s, note); each note takes the next of VOICES slots in turn."""
    n_blocks = int(seconds * L.RATE / B)
    slots = [L.Voice() for _ in range(voices)]
    notes = [60.0] * voices
    trig_at = {}
    for k, (t, note) in enumerate(events):
        trig_at.setdefault(int(t * L.RATE / B), []).append((k % voices, note))
    out = np.zeros(n_blocks * B)
    for b in range(n_blocks):
        hits = dict(trig_at.get(b, []))
        rendered = 0
        for s, v in enumerate(slots):
            if s in hits:
                notes[s] = float(hits[s])
            o, did = L.block(v, rendered, words, notes[s], s in hits, T)
            rendered += did
            out[b * B:(b + 1) * B] += o
    return out


def write(name, x):
    y = np.clip(x, -1, 1)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    print(f"  {name}.wav  peak {float(np.max(np.abs(x))):.2f}")


def steps(bpm, notes, every=0.25):
    beat = 60.0 / bpm
    return [(0.05 + k * every * beat, m) for k, m in enumerate(notes) if m is not None]


def main():
    d = dict(L.DEFAULTS)
    mel = [72, None, 79, 76, None, 84, 79, None, 72, 74, None, 79, 76, 72, None, 67]
    write("01_bar_melody", render(steps(110, mel * 2), 5.0,
                                  {**d, L.P_STRC: 0x3C00, L.P_BRIT: 0x4800, L.P_DAMP: 0x4800}))
    ch = [(0.05, n) for n in (60, 67, 76)] + [(1.6, n) for n in (57, 64, 72)] + \
         [(3.2, n) for n in (62, 69, 77, 81)]
    write("02_bell_chords", render(ch, 6.5, {**d, L.P_STRC: 0x6E00, L.P_BRIT: 0x5800,
                                              L.P_DAMP: 0x6000, L.P_POS: 0x1400}))
    write("03_string_default", render(steps(100, [48, 55, 60, 63, 67, 63, 60, 55] * 2, 0.5), 5.2, d))
    write("04_noise_plates", render(steps(120, [40, None, 40, 47, None, 40, 43, None] * 2), 4.5,
                                    {**d, L.P_STRC: 0x6400, L.P_EXCT: 0x5000, L.P_DAMP: 0x4400,
                                     L.P_BRIT: 0x3000, L.P_TUN: 0x4000}))


if __name__ == "__main__":
    main()

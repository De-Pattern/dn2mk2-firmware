"""CZ as the DSP renders it (dnfw.cz.live, bit-exact to cz.asm), through a stand-in for
the DN2's AMP envelope (the DCA): a few phrases, so the machine can be heard before it is
flashed. python cz/demos_dsp.py"""

import pathlib
import sys
import wave

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from dnfw.cz import live as L          # noqa: E402

T = L.tables()
OUT = HERE / "demos_dsp"
OUT.mkdir(exist_ok=True)
B = L.BLOCK


def knob(slot, v99, ranges):
    lo, span = ranges[slot]
    return lo + min(span, int((v99 + 0.5) * span / 99))


def env(steps, sus=None):
    """STEPS: eight (rate, level) 0..99; SUS: the sustain step 1..8, or None"""
    out = {}
    for k, (r, lv) in enumerate(steps):
        out[L.P_RATES[k]] = knob(L.P_RATES[k], r, L.RATE_RANGE)
        out[L.P_LEVELS[k]] = knob(L.P_LEVELS[k], lv, L.LEVEL_RANGE)
    out[L.P_SUS] = int(((sus - 1 if sus else 8) + 0.5) * 0x7800 / 9)
    return out


def wave_word(index):
    return int((index + 0.5) * 0x7800 / 33)


def amp(n, gate, a=0.003, d=0.4, s=0.7, r=0.25):
    """the stand-in DCA: attack, decay to sustain while the gate is up, release"""
    t = np.arange(n) / L.RATE
    e = np.where(t < a, t / a, s + (1 - s) * np.exp(-(t - a) / max(d, 1e-3) * 3))
    g = int(gate * L.RATE)
    if g < n:
        e[g:] = e[g - 1] * np.exp(-(t[g:] - t[g - 1]) / max(r, 1e-3) * 3)
    return e


def render(events, seconds, words, voices=6, dca=None):
    """EVENTS: (time s, note, gate s); each note takes the next of VOICES slots in turn."""
    n_blocks = int(seconds * L.RATE / B)
    n = n_blocks * B
    slots = [L.Voice() for _ in range(voices)]
    notes, starts, gates = [60.0] * voices, [None] * voices, [0.0] * voices
    trig_at = {}
    for k, (t, note, gate) in enumerate(events):
        trig_at.setdefault(int(t * L.RATE / B), []).append((k % voices, note, gate))
    lines = np.zeros((voices, n))
    for b in range(n_blocks):
        hits = {s: (note, gate) for s, note, gate in trig_at.get(b, [])}
        from dnfw import voices as VOICES
        keep = VOICES.plan({k: (k in hits, bool(x.active), x.age) for k, x in enumerate(slots)},
                           L.MAX_VOICES)
        for s, v in enumerate(slots):
            if s in hits:
                notes[s], gates[s] = float(hits[s][0]), hits[s][1]
                starts[s] = b * B
            o, did = L.block(v, keep[s], words, notes[s], s in hits, T)
            lines[s, b * B:(b + 1) * B] = o
    out = np.zeros(n)
    for s in range(voices):
        # each trigger restarts the slot's DCA from its own start
        marks = sorted(b for b, hs in trig_at.items() for x in hs if x[0] == s)
        for k, b in enumerate(marks):
            a0 = b * B
            a1 = marks[k + 1] * B if k + 1 < len(marks) else n
            gate = next(x[2] for x in trig_at[b] if x[0] == s)
            out[a0:a1] += lines[s, a0:a1] * amp(a1 - a0, gate, **(dca or {}))
    return out


def write(name, x):
    pk = float(np.max(np.abs(x))) or 1.0
    y = np.clip(x / pk * 0.89, -1, 1)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    print(f"  {name}.wav  peak {float(np.max(np.abs(x))):.2f}")


def seq(bpm, notes, every=0.25, gate=0.8):
    beat = 60.0 / bpm
    return [(0.05 + k * every * beat, m, gate * every * beat)
            for k, m in enumerate(notes) if m is not None]


def main():
    d = dict(L.DEFAULTS)
    bass = [36, None, 36, 48, None, 36, 39, None, 36, None, 43, 36, None, 41, 43, None]
    write("01_saw_bass", render(seq(118, bass * 2), 4.4, {
        **d, L.P_WAVE: wave_word(0), L.P_DCW: 0x7F00,
        **env([(99, 99), (62, 18), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0)], sus=2)},
        dca={"d": 0.25, "s": 0.5, "r": 0.08}))
    chords = [(0.05 + 1.6 * k, n, 1.3) for k, ch in enumerate(((60, 64, 67), (58, 62, 67),
                                                               (57, 60, 64), (55, 59, 62)))
              for n in ch]
    write("02_brass_1+1", render(chords, 7.0, {
        **d, L.P_WAVE: wave_word(0), L.P_SEL: 0x200, L.P_DET: 0x4C00, L.P_DCW: 0x7000,
        **env([(70, 92), (55, 60), (40, 55), (60, 0), (50, 0), (50, 0), (50, 0), (50, 0)], sus=3)},
        dca={"a": 0.04, "d": 0.6, "s": 0.8, "r": 0.4}))
    write("03_reso_sweep", render([(0.05, 45, 3.6), (0.05, 57, 3.6)], 4.4, {
        **d, L.P_WAVE: wave_word(6), L.P_DCW: 0x7F00,
        **env([(45, 99), (40, 10), (45, 80), (40, 0), (50, 0), (50, 0), (50, 0), (50, 0)])},
        dca={"a": 0.01, "d": 3.0, "s": 0.9, "r": 0.5}))
    bell = [72, None, 79, None, 76, None, 84, None, 81, 79, None, 76, 72, None, None, None]
    write("04_ring_bell", render(seq(96, bell), 4.0, {
        **d, L.P_WAVE: wave_word(1), L.P_SEL: 0x300, L.P_MOD: 0, L.P_OCT: 0x100,
        L.P_DET: 0x4600, L.P_KF: 0x100, L.P_DCW: 0x6000,
        **env([(99, 99), (55, 30), (40, 0), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0)])},
        dca={"d": 0.5, "s": 0.0, "r": 0.6}))
    write("05_noise_line", render(seq(100, [48, None, 51, None, 55, None, 58] * 2, 0.5), 5.0, {
        **d, L.P_WAVE: wave_word(4), L.P_SEL: 0x300, L.P_MOD: 0x200, L.P_DCW: 0x5000,
        **env([(80, 70), (50, 30), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0)], sus=2)},
        dca={"d": 0.3, "s": 0.6, "r": 0.2}))
    pads = [(0.05 + 2.0 * k, n, 1.8) for k, ch in enumerate(((48, 55, 64, 71), (53, 60, 69, 72)))
            for n in ch]
    write("06_saw_pulse_pair_pad", render(pads, 4.6, {
        **d, L.P_WAVE: wave_word(9), L.P_SEL: 0x200, L.P_DET: 0x4400, L.P_DCW: 0x6000,
        **env([(45, 70), (35, 40), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0)], sus=2)},
        dca={"a": 0.3, "d": 1.0, "s": 0.8, "r": 0.8}))
    write("07_every_wave", render_each_wave())


def render_each_wave():
    """the eight waves in turn, one note each, the DCW swept up then down"""
    d = dict(L.DEFAULTS)
    out = []
    for w in range(8):
        words = {**d, L.P_WAVE: wave_word(w), L.P_DCW: 0x7F00,
                 **env([(60, 99), (55, 0), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0), (50, 0)])}
        out.append(render([(0.0, 48, 0.55)], 0.6, words, voices=1,
                          dca={"a": 0.005, "d": 2.0, "s": 0.9, "r": 0.03}))
    return np.concatenate(out)


if __name__ == "__main__":
    main()

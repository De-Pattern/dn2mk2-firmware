"""RESONATOR: the reference model of a Rings-style resonator machine (docs/rings.md).

A struck, plucked or bowed object is a few resonant modes, each ringing at its own
frequency with its own decay. This machine makes that object and hits it: an internal
exciter (a mallet or a noise burst) at every note, into a bank of resonant modes
(MODAL) or a plucked string (STRING). Original code from the textbook forms (modal
synthesis: a two-pole resonator per mode; the string: Karplus-Strong with a loss
filter), not from any module's source.

    MODEL      MODAL (a bank of up to 24 modes) / STRING (a delay-line string)
    STRUCTURE  where the modes sit: 0 harmonic (a string), 0.5 a free bar (marimba),
               1 a plate / bell (inharmonic clusters)
    BRIGHTNESS how much of the top survives: the exciter's tone, and how much faster
               the high modes decay than the low
    DAMPING    the decay, 0.05 s .. 10 s
    POSITION   where the object is hit, 0..0.5 of its length: the middle cancels
               every other mode, the edge keeps them all
    EXCITER    MALLET (a soft half-cosine, its width from BRIGHTNESS) / NOISE (a
               short burst)
"""

from __future__ import annotations

import math
import wave

import numpy as np
from scipy.signal import lfilter

RATE = 48000
MODES = 24
# mode ratios of the anchors STRUCTURE moves between
HARMONIC = np.arange(1, MODES + 1, dtype=float)
BAR = np.array([((2 * n + 1) / 3.0) ** 2 for n in range(1, MODES + 1)])      # free-free beam
BAR = BAR / BAR[0]
PLATE = np.array([1.0, 1.594, 2.136, 2.296, 2.653, 2.918, 3.156, 3.501, 3.600, 4.060, 4.154,
                  4.601, 4.832, 5.131, 5.412, 5.651, 5.937, 6.164, 6.415, 6.749, 6.976, 7.244,
                  7.470, 7.735])                                               # a circular plate


def note_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def ratios(structure: float) -> np.ndarray:
    """Geometric interpolation: harmonic -> bar over 0..0.5, bar -> plate over 0.5..1."""
    s = min(max(structure, 0.0), 1.0)
    if s <= 0.5:
        a, b, t = HARMONIC, BAR, s / 0.5
    else:
        a, b, t = BAR, PLATE, (s - 0.5) / 0.5
    return a ** (1 - t) * b ** t


def t60(damping: float) -> float:
    return 0.05 * 200.0 ** min(max(damping, 0.0), 1.0)          # 0.05 s .. 10 s


def exciter(kind: str, brightness: float, n: int, rng) -> np.ndarray:
    x = np.zeros(n)
    if kind == "MALLET":
        width = int(RATE * (0.0004 + 0.008 * (1 - brightness) ** 2))
        k = np.arange(width)
        x[:width] = np.sin(np.pi * k / width) / max(1.0, width / 24.0)
    else:
        L = int(RATE * 0.012)
        burst = rng.standard_normal(L) * np.exp(-np.arange(L) / (L / 4))
        a = math.exp(-2 * math.pi * (300 + 12000 * brightness ** 2) / RATE)
        x[:L] = lfilter([1 - a], [1, -a], burst) * 0.5
    return x


def modal(x: np.ndarray, f0: float, structure: float, brightness: float, damping: float,
          position: float) -> np.ndarray:
    r = ratios(structure)
    y = np.zeros_like(x)
    pos = 0.02 + 0.48 * min(max(position, 0.0), 1.0)
    for n, ratio in enumerate(r):
        f = f0 * ratio
        if f > 0.45 * RATE:
            break
        decay = t60(damping) * ratio ** (-(1.0 - brightness) * 1.3 - 0.2)
        R = math.exp(-6.91 / (decay * RATE))
        w = 2 * math.pi * f / RATE
        amp = math.sin(math.pi * (n + 1) * pos) * (1 - R) * 4.0 * (brightness + 0.25) ** (n * 0.08)
        y += lfilter([amp * math.sin(w)], [1, -2 * R * math.cos(w), R * R], x)
    return y


def string(x: np.ndarray, f0: float, structure: float, brightness: float, damping: float,
           position: float) -> np.ndarray:
    """Karplus-Strong: a delay of one period with a loss filter in the loop; POSITION
    combs the excitation; STRUCTURE adds stiffness (an all-pass in the loop)."""
    g = 10 ** (-3 * (1.0 / f0) / t60(damping))            # loss a period for the T60
    lp = 0.15 + 0.84 * brightness                          # the loop's low-pass
    ap = -0.6 * structure                                  # stiffness: dispersion
    # the loop filters' own delay at the fundamental comes off the delay line, so the
    # string plays in tune (one-pole: (1 - lp) / lp; the all-pass: (1 - ap) / (1 + ap))
    period = RATE / f0 - (1 - lp) / lp - (1 - ap) / (1 + ap)
    N = int(period)
    frac = period - N
    pos = int(max(1, (0.02 + 0.48 * position) * N))
    xin = x.copy()
    xin[pos:] -= x[:-pos]
    y = np.zeros_like(x)
    buf = np.zeros(N + 2)
    i = 0
    s_lp = 0.0
    a_x1 = a_y1 = 0.0
    for n in range(len(x)):
        d = buf[(i - N) % len(buf)] * (1 - frac) + buf[(i - N - 1) % len(buf)] * frac
        s_lp = s_lp + lp * (d - s_lp)
        v = ap * s_lp + a_x1 - ap * a_y1
        a_x1, a_y1 = s_lp, v
        out = xin[n] + g * v
        buf[i % len(buf)] = out
        i += 1
        y[n] = out
    return y


def note(n_note: float, n: int, *, model="MODAL", structure=0.5, brightness=0.5,
         damping=0.5, position=0.3, exc="MALLET", level=1.0, seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = exciter(exc, brightness, n, rng)
    f0 = note_hz(n_note)
    y = (modal if model == "MODAL" else string)(x, f0, structure, brightness, damping, position)
    return y * level


def sequence(events, seconds, **kw) -> np.ndarray:
    n = int(seconds * RATE)
    mix = np.zeros(n)
    for ev in events:
        t, m = ev[0], ev[1]
        p = {**kw, **(ev[2] if len(ev) > 2 else {})}
        start = int(t * RATE)
        length = min(n - start, int(min(seconds - t, t60(p.get("damping", 0.5)) + 0.2) * RATE))
        if length > 0:
            mix[start:start + length] += note(m, length, **p)
    return mix


def write_wav(path: str, x: np.ndarray, peak: float = 0.89) -> None:
    m = float(np.max(np.abs(x))) or 1.0
    y = np.clip(x / m * peak, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((y * 32767).astype("<i2").tobytes())

"""SHFT: the reference model of a frequency shifter as a filter type (docs/shft.md).

A frequency shifter moves every partial of the sound by the same number of Hz (a pitch
shifter multiplies them), so harmonic sounds turn metallic and bell-like, small shifts
beat and phase, and feedback through the shift climbs or falls for ever (the
"barber-pole"). It sits in the track's filter slot, like PING, on any machine.

    MODE   UP / DOWN / BOTH (thirds of TYPE): the upper sideband, the lower, or both
           (both is a clean ring modulation)
    SHFT   the shift, -2.5 kHz .. +2.5 kHz, cubic so the middle is fine (FREQ; 64 is 0)
    FDBK   0..0.95 of the output fed back into the shifter (RESO)
    ENV    the envelope's depth on the shift, +-2.5 kHz (ENV)
    ATK    ms, DEC ms: the envelope, restarted by every note (ATK, DEC)
    MIX    dry -> wet (SUS)
    DRIV   0.4 .. 2.0 into the shifter, soft-clipped in the feedback loop (Env. Delay)
    KEY.T  0..1: the shift scales with the note's pitch (relative to C4), so a shift
           keeps the same interval-like colour across the keyboard

The quadrature pair is two chains of four first-order-in-z^2 all-passes, 90 degrees
apart across ~20 Hz..20 kHz (Olli Niemitalo's published coefficients for an IIR
Hilbert pair). Plain Python per sample, as the DSP will run it.
"""

from __future__ import annotations

import math
import wave

import numpy as np

RATE = 48000
MODES = ("UP", "DOWN", "BOTH")
MAX_HZ = 2500.0
A = (0.6923878, 0.9360654322959, 0.9882295226860, 0.9987488452737)
B = (0.4021921162426, 0.8561710882420, 0.9722909545651, 0.9952884791278)


class AllpassChain:
    """y[n] = c^2 (x[n] + y[n-2]) - x[n-2], four in a row."""

    def __init__(self, coefs):
        self.c2 = [c * c for c in coefs]
        self.x1 = [0.0] * 4
        self.x2 = [0.0] * 4
        self.y1 = [0.0] * 4
        self.y2 = [0.0] * 4

    def run(self, x: float) -> float:
        for i, c2 in enumerate(self.c2):
            y = c2 * (x + self.y2[i]) - self.x2[i]
            self.x2[i], self.x1[i] = self.x1[i], x
            self.y2[i], self.y1[i] = self.y1[i], y
            x = y
        return x


class Hilbert:
    """-> (i, q): q lags i by 90 degrees over the audio band."""

    def __init__(self):
        self.a = AllpassChain(A)
        self.b = AllpassChain(B)
        self.i_prev = 0.0

    def run(self, x: float) -> tuple[float, float]:
        i, self.i_prev = self.i_prev, self.a.run(x)      # path A one sample late
        q = self.b.run(x)
        return i, q


def shift_hz(knob: float) -> float:
    """FREQ 0..127, 64 = no shift -> Hz."""
    u = max(-1.0, min(1.0, (knob - 64.0) / 63.0))
    return math.copysign(MAX_HZ * abs(u) ** 3, u)


def soft(x: float) -> float:
    return math.tanh(x)


def note_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


class Envelope:
    """Attack then exponential decay, restarted by a trigger."""

    def __init__(self, atk_ms: float, dec_ms: float):
        self.a = 1.0 / max(1.0, atk_ms * RATE / 1000.0)
        self.d = math.exp(-1.0 / max(1.0, dec_ms * RATE / 1000.0 / 4.6))
        self.v, self.rising = 0.0, False

    def trigger(self):
        self.rising = True

    def next(self) -> float:
        if self.rising:
            self.v += self.a
            if self.v >= 1.0:
                self.v, self.rising = 1.0, False
        else:
            self.v *= self.d
        return self.v


def shifter(x: np.ndarray, triggers, notes, *, mode="UP", freq=70.0, fdbk=0.0, env=0.0,
            atk=1.0, dec=200.0, mix=1.0, drive=0.3, keyt=0.0, freq_at=None) -> np.ndarray:
    """X: the track's signal. TRIGGERS: sample indices of notes, NOTES their pitches.
    FREQ is the knob (0..127); FREQ_AT(t) overrides it over time."""
    h = Hilbert()
    e = Envelope(atk, dec)
    trig = dict(zip(triggers, notes))
    gain = 0.4 + 1.6 * drive
    phase, fb, note = 0.0, 0.0, 60.0
    out = np.empty(len(x))
    for n, s in enumerate(x.tolist()):
        if n in trig:
            e.trigger()
            note = trig[n]
        a = e.next()
        k = freq_at(n / RATE) if freq_at else freq
        hz = shift_hz(k) * (note_hz(note) / note_hz(60)) ** keyt + env * MAX_HZ * a
        i, q = h.run(s * gain + fdbk * soft(fb))
        c, sn = math.cos(phase), math.sin(phase)
        if mode == "UP":            # q lags i: i cos + q sin is the upper sideband
            y = i * c + q * sn
        elif mode == "DOWN":
            y = i * c - q * sn
        else:
            y = i * c
        fb = y
        phase = (phase + 2 * math.pi * hz / RATE) % (2 * math.pi)
        out[n] = (1 - mix) * s + mix * 0.9 * soft(y / 0.9)
    return out


def write_wav(path: str, x: np.ndarray, peak: float = 0.89) -> None:
    m = float(np.max(np.abs(x))) or 1.0
    y = np.clip(x / m * peak, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((y * 32767).astype("<i2").tobytes())

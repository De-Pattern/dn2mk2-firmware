"""PING: the reference model of Waverider's planned filter section (`docs/ROADMAP.md`).

One filter slot per voice, four cores on one zero-delay-feedback (TPT) engine, its own
envelope, and a built-in strike. This file is the sound, chosen by ear before any
firmware; the DSP code will be held to it the way `dnfw.waverider.live` holds W2.

    TYPE   SVF   Mutable-style 2-pole state-variable, low-pass: clean, glassy
           LADR  Roland-style 4-pole OTA cascade, soft feedback: thick, round
           VCFQ  Serge-style resonant band-pass, into soft self-oscillation: the ping
           LPG   vactrol low-pass gate, one envelope opens level and cutoff: the bongo
    FREQ   cutoff, semitones from the note (keytracked, so a ping plays in tune)
    RES    0..1: the RING TIME, 1 ms to 2 s, the same at every pitch (SVF and VCFQ
           set their damping from it and the cutoff; VCFQ's top tips into a soft,
           bounded self-oscillation). Every core saturates softly in its loop, so high
           RES rounds off instead of blowing out, and the output passes a hard ceiling
    DRIVE  0..1: input level into the loop (more = denser, warmer)
    ATK    ms, from 0.1
    DEC    ms
    CURVE  -1 (log) .. 0 (linear) .. +1 (exp), for attack and decay together
    ENV    -1..1: the envelope's depth on the cutoff, in octaves x 6
    STRIKE 0..1: a 0.3 ms click into the filter at each note (the "marble")

All original code, written from the textbook forms (Zavalishin, *The Art of VA Filter
Design*; Simper's SVF), not copied from any module's source. numpy only for the
oscillator and the WAV writer; the filters run per sample in plain Python, so they
read the way the DSP will.
"""

from __future__ import annotations

import math
import wave

import numpy as np

RATE = 48000
TYPES = ("SVF", "LADR", "VCFQ", "LPG")
CEILING = 0.9


# -- the envelope --------------------------------------------------------------------------

def shape(x: float, curve: float) -> float:
    """0..1 -> 0..1. curve > 0 bends it exponential (slow start, steep end), < 0
    logarithmic (steep start), 0 is a straight line."""
    if abs(curve) < 1e-4:
        return x
    k = 5.0 * curve
    return (math.exp(k * x) - 1.0) / (math.exp(k) - 1.0)


class Envelope:
    """Attack-decay, retriggered by each note. EXP (curve > 0) gives a slow-start attack
    and the natural fast-then-long decay; LOG the reverse."""

    def __init__(self, atk_ms: float, dec_ms: float, curve: float):
        self.na = max(1, int(max(atk_ms, 0.1) * RATE / 1000))
        self.nd = max(1, int(max(dec_ms, 1.0) * RATE / 1000))
        self.curve = curve
        self.t = 10 ** 9

    def trigger(self):
        self.t = 0

    def next(self) -> float:
        t = self.t
        self.t += 1
        if t < self.na:
            return shape(t / self.na, self.curve)
        t -= self.na
        if t < self.nd:
            return shape(1.0 - t / self.nd, self.curve)
        return 0.0


# -- the strike ----------------------------------------------------------------------------

STRIKE_N = int(0.0003 * RATE) + 1          # 0.3 ms


def strike_wave() -> list[float]:
    """A raised-cosine click, one-signed: it excites every frequency at once and the
    filter's ring is what is heard."""
    return [0.5 - 0.5 * math.cos(2 * math.pi * k / (STRIKE_N - 1)) for k in range(STRIKE_N)]


# -- saturation ----------------------------------------------------------------------------

KNEE, LIMIT = 1.0, 1.6


def soft(x: float) -> float:
    """A rounded limiter for loop states: exactly linear up to KNEE (a ring at a
    normal level loses nothing to it), then bending smoothly toward LIMIT. Only a
    hard hit at high RES reaches it, and there it rounds the peak instead of
    clipping."""
    a = abs(x)
    if a <= KNEE:
        return x
    over = a - KNEE
    y = KNEE + over / (1.0 + over / (LIMIT - KNEE))
    return y if x > 0 else -y


def tanh(x: float) -> float:
    return math.tanh(x)


# -- the cores (TPT, one sample at a time) ---------------------------------------------------

def g_of(fc: float) -> float:
    return math.tan(math.pi * clamp_fc(fc) / RATE)


def clamp_fc(fc: float) -> float:
    return min(max(fc, 10.0), RATE * 0.45)


def ring_tau(res: float) -> float:
    """RES 0..1 -> the ring's time constant, seconds: 1 ms .. 2 s, exponential."""
    return 0.001 * 2000.0 ** min(max(res, 0.0), 1.0)


def damping(res: float, fc: float, floor: float) -> float:
    """The SVF damping k that makes a ring at FC decay with RES's time constant:
    the envelope of a struck SVF falls as exp(-w k t / 2), so k = 2 / (w tau)."""
    w = 2.0 * math.pi * clamp_fc(fc)
    return min(2.0, max(floor, 2.0 / (w * ring_tau(res))))


class SVF:
    """Simper's trapezoidal SVF, damping K (from `damping`: never below 0.0004, so
    it rings long but never self-oscillates, and stays clean); the band state is
    softly limited, so a hard hit rounds rather than clips. Output: low-pass."""

    def __init__(self):
        self.ic1 = self.ic2 = 0.0

    def run(self, x: float, g: float, k: float) -> float:
        a1 = 1.0 / (1.0 + g * (g + k))
        a2, a3 = g * a1, g * g * a1
        v3 = x - self.ic2
        v1 = a1 * self.ic1 + a2 * v3
        v2 = self.ic2 + a2 * self.ic1 + a3 * v3
        self.ic1 = soft(2.0 * v1 - self.ic1)
        self.ic2 = 2.0 * v2 - self.ic2
        return v2


class Ladder:
    """Four TPT one-pole stages in a loop (the Roland/Moog topology), the linear
    zero-delay solution for the loop's input, then tanh on it: the feedback compresses
    as it grows, which is what makes it thick and round at high RES. k = 4.1 RES just
    reaches a soft self-oscillation. The pass band's loss at high k is made up."""

    def __init__(self):
        self.s = [0.0, 0.0, 0.0, 0.0]

    def run(self, x: float, g: float, res: float) -> float:
        G = g / (1.0 + g)
        k = 4.1 * res
        s1, s2, s3, s4 = self.s
        d = 1.0 + g
        sigma = G * G * G * s1 / d + G * G * s2 / d + G * s3 / d + s4 / d
        y4 = (G ** 4 * x + sigma) / (1.0 + k * G ** 4)
        u = tanh(x - k * y4)
        out = []
        for i in range(4):
            v = (u - self.s[i]) * G
            y = v + self.s[i]
            self.s[i] = y + v
            u = y
        return u * (1.0 + 0.6 * k)


class VCFQ:
    """The Serge VCFQ idea: a resonant band-pass that can be pushed past its edge. At
    the top of RES the damping goes slightly negative, so it rings on by itself, and
    the soft limit on the band state turns that into a stable, rounded sine instead of
    a runaway -- the watery ping. Output: band-pass."""

    def __init__(self):
        self.ic1 = self.ic2 = 0.0

    def run(self, x: float, g: float, k: float) -> float:
        a1 = 1.0 / (1.0 + g * (g + k))
        a2, a3 = g * a1, g * g * a1
        v3 = x - self.ic2
        v1 = a1 * self.ic1 + a2 * v3
        v2 = self.ic2 + a2 * self.ic1 + a3 * v3
        self.ic1 = soft(2.0 * v1 - self.ic1)
        self.ic2 = 2.0 * v2 - self.ic2
        return v1


class Vactrol:
    """A vactrol's response to its LED: a fast rise and a slow fall that slows further
    as it darkens -- the 292's round, liquid tail."""

    def __init__(self, dec_ms: float):
        self.v = 0.0
        self.rise = 1.0 - math.exp(-1.0 / (0.0008 * RATE))
        self.fall = dec_ms

    def run(self, led: float) -> float:
        if led > self.v:
            self.v += (led - self.v) * self.rise
        else:
            tau = self.fall / 1000.0 * (0.35 + 1.3 * (1.0 - self.v))
            self.v += (led - self.v) * (1.0 - math.exp(-1.0 / (tau * RATE)))
        return self.v


# -- the voice -----------------------------------------------------------------------------

def note_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


class Table:
    def __init__(self, table):
        self.t = np.asarray(table, dtype=np.float64) / 32768.0

    def osc(self, hz: float, n: int, pos: float = 0.0, phase: float = 0.0) -> np.ndarray:
        frames, points = self.t.shape
        ph = (phase + hz / RATE * np.arange(n)) % 1.0
        idx = ph * points
        i0 = idx.astype(int) % points
        i1 = (i0 + 1) % points
        fr = idx - np.floor(idx)
        f0 = int(min(max(pos, 0), frames - 1))
        f1 = min(f0 + 1, frames - 1)
        ff = pos - f0
        a = self.t[f0][i0] * (1 - fr) + self.t[f0][i1] * fr
        b = self.t[f1][i0] * (1 - fr) + self.t[f1][i1] * fr
        return a * (1 - ff) + b * ff


def voice(source: np.ndarray, note: float, kind: str, *, freq: float = 0.0, res: float = 0.5,
          drive: float = 0.5, atk: float = 0.5, dec: float = 300.0, curve: float = 0.5,
          env: float = 0.5, strike: float = 0.5, res_at=None) -> list[float]:
    """One note through the PING section: SOURCE (the oscillator, already rendered)
    plus the strike, filtered by KIND, shaped by the envelope. RES_AT(t), if given,
    overrides RES over time (for sweeps)."""
    if kind not in TYPES:
        raise ValueError(kind)
    core = {"SVF": SVF, "LADR": Ladder, "VCFQ": VCFQ, "LPG": SVF}[kind]()
    # the LPG's envelope is the trigger into its vactrol: the attack, then 4 ms open
    e = Envelope(atk, dec if kind != "LPG" else 4.0, curve if kind != "LPG" else -1.0)
    vac = Vactrol(dec) if kind == "LPG" else None
    e.trigger()
    hit = strike_wave()
    late = int(0.0025 * RATE) if kind == "LPG" else 0      # the LPG's click lands as it opens
    base = note_hz(note) * 2.0 ** (freq / 12.0)
    # A struck SVF rings at an amplitude in proportion to g (measured: band state ~ 35 g
    # per unit of click). So SVF and VCFQ scale the click by 1/g: the same ring level at
    # every pitch, held just under the loop limiter's knee, so a ping stays a pure tone.
    hit_gain = min(12.0, 0.043 / g_of(base)) if kind in ("SVF", "VCFQ") else 2.5
    gain_in = 0.4 + 1.6 * drive
    out = []
    src = source.tolist()
    for n, s in enumerate(src):
        h = n - late
        x = s * gain_in + (strike * hit_gain * hit[h] if 0 <= h < len(hit) else 0.0)
        a = e.next()
        r = res_at(n / RATE) if res_at else res
        if kind == "LPG":
            v = vac.run(a)
            fc = 30.0 * (base / 30.0 * 2.0 ** (6.0 * env)) ** v if v > 0 else 30.0
            y = core.run(x, g_of(fc), damping(0.6 * r, fc, 0.05)) * (v ** 1.4)
        else:
            fc = base * 2.0 ** (6.0 * env * a)
            if kind == "LADR":
                y = core.run(x, g_of(fc), r) * a
            elif kind == "VCFQ":
                k = damping(r, fc, 0.0004) if r < 0.97 else -0.004 * (r - 0.97) / 0.03
                y = core.run(x, g_of(fc), k) * a
            else:
                y = core.run(x, g_of(fc), damping(r, fc, 0.0004)) * a
        out.append(CEILING * tanh(y / CEILING))
    return out


# -- rendering -----------------------------------------------------------------------------

def sequence(table: Table, events, seconds: float, pos: float = 0.0, **kw) -> np.ndarray:
    """EVENTS: (time s, note[, overrides dict]). Each note is a voice; voices overlap
    (polyphony), summed."""
    n = int(seconds * RATE)
    mix = np.zeros(n)
    for ev in events:
        t, note = ev[0], ev[1]
        p = {**kw, **(ev[2] if len(ev) > 2 else {})}
        kind = p.pop("kind")
        length = int(min(seconds - t, (p.get("atk", 0.5) + p.get("dec", 300.0) * 3 + 60) / 1000.0) * RATE)
        if length <= 0:
            continue
        src = table.osc(note_hz(note), length, p.pop("pos", pos)) * p.pop("level", 1.0)
        start = int(t * RATE)
        mix[start:start + length] += np.asarray(voice(src, note, kind, **p))[:n - start]
    return mix


def write_wav(path: str, x: np.ndarray, peak: float = 0.89) -> float:
    """16-bit mono 48 kHz, scaled so the loudest sample is PEAK. -> the scale used."""
    m = float(np.max(np.abs(x))) or 1.0
    y = np.clip(x / m * peak, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return peak / m

"""GRAINS -- a grain oscillator in the spirit of the Virus TI grain tables grain oscillator for the Digitone II, as a reference model.

Our own design, sketched in Python so it can be heard before any DSP code exists.
It reads the same baked wavetables Waverider plays (16 frames x 512 int16 points)
and is meant to become the reference the SHARC code is held to, sample for sample,
the way `dnfw.waverider.live` is for Waverider.

Two modes:

SYNC (the Virus "grain table" idea)
    A new grain starts once per period of the played note, so the note's pitch
    comes from the grain *rate*. Inside each grain, the wave plays at the note's
    frequency times 2^(FMNT/12), so FMNT moves the timbre (a formant) without
    moving the pitch. SIZE (1..4) sets how long each grain rings, FOF-style:
    short is buzzy and wide, long is narrow and vocal. SPRD reads each grain twice, formant pulled up and down
    by the same amount (two reads per grain while SPRD is not 0).

CLOUD (classic granular)
    Grains start at DENS per second with random timing, each one playing the wave
    at the note's pitch for SIZE x 10 ms with a smooth bell. POS can drift
    with SCAN, JITR scatters each grain's table position, PJIT its pitch.

Per voice at most MAX_GRAINS run at once, which bounds the DSP cost.
"""

from __future__ import annotations

import math
import random
import struct
import wave

import numpy as np

RATE = 48000
FRAMES, POINTS = 16, 512
MAX_GRAINS = 4


def note_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def window(t_periods: np.ndarray, size: float, shape: float) -> np.ndarray:
    """A grain's envelope, FOF-style, against time in periods of the note.

    A raised-cosine rise, then an exponential decay whose time constant grows
    with SIZE; the grain is cut at MAX_GRAINS periods with a short taper. The
    decay is what keeps the note's pitch: overlapping exponentials sum to a
    ramp that repeats every period, so each period has its own attack at any
    FMNT. (Symmetric windows that overlap-add to a constant lose the pitch
    whenever FMNT is a whole number of octaves: the grains join into one
    continuous wave an octave or two up. That was this model's first draft.)

    SIZE 1..4: longer ringing, narrower and more vocal formant.
    shape 0 = soft rise, 1 = hard (near-instant) rise.
    """
    att = 0.30 - 0.27 * shape                         # rise, in periods
    tau = 0.25 + 0.25 * (size - 1)                    # decay constant, in periods
    rise = 0.5 - 0.5 * np.cos(np.pi * np.clip(t_periods / att, 0, 1))
    decay = np.exp(-np.maximum(t_periods - att, 0) / tau)
    end = MAX_GRAINS
    taper = np.clip((end - t_periods) / 0.25, 0, 1)
    return rise * decay * taper


class Table:
    def __init__(self, frames: list[list[int]]):
        self.t = np.asarray(frames, dtype=np.float64) / 32768.0   # [16, 512]

    def read(self, pos: np.ndarray, ph: np.ndarray) -> np.ndarray:
        """pos in frames (0..15, fractional), ph in cycles (wraps). Linear in both."""
        pos = np.clip(pos, 0, FRAMES - 1)
        f0 = np.floor(pos).astype(int)
        f1 = np.minimum(f0 + 1, FRAMES - 1)
        ff = pos - f0
        x = (ph % 1.0) * POINTS
        i0 = np.floor(x).astype(int) % POINTS
        i1 = (i0 + 1) % POINTS
        xf = x - np.floor(x)
        a = self.t[f0, i0] + xf * (self.t[f0, i1] - self.t[f0, i0])
        b = self.t[f1, i0] + xf * (self.t[f1, i1] - self.t[f1, i0])
        return a + ff * (b - a)


def render(table: Table, seconds: float, note, *, mode="SYNC", pos=0.0, fmnt=0.0,
           size=2.0, sprd=0.0, dens=40.0, jitr=0.0, pjit=0.0, scan=0.0, win=0.0,
           seed=1) -> np.ndarray:
    """Every parameter may be a constant or a function of time t (seconds), so
    sweeps can be heard. Rendered in 32-sample blocks, the DN2's block size:
    parameters are read once per block, as the DSP would."""
    rng = random.Random(seed)
    v = lambda p, t: p(t) if callable(p) else p                    # noqa: E731
    n = int(seconds * RATE)
    out = np.zeros(n)
    grains = []                     # dicts: start, length, rate, pos, ph
    next_start = 0.0                # in samples
    scan_off = 0.0
    k = 0
    BLOCK = 32
    for b0 in range(0, n, BLOCK):
        t = b0 / RATE
        f = note_hz(v(note, t))
        period = RATE / f
        P = v(pos, t)
        scan_off += v(scan, t) * BLOCK / RATE
        base_pos = (P + scan_off) % (FRAMES - 1) if v(scan, t) else P
        # start grains due inside this block
        while next_start < b0 + BLOCK:
            if mode == "SYNC":
                L = MAX_GRAINS * period
                rate = f * 2.0 ** (v(fmnt, t) / 12.0)
                gpos = base_pos
                step = period
            else:
                L = v(size, t) * RATE / 1000.0 * 10       # SIZE x 10 ms
                rate = f * 2.0 ** (rng.uniform(-1, 1) * v(pjit, t) / 12.0)
                gpos = base_pos + rng.uniform(-1, 1) * v(jitr, t) * (FRAMES - 1)
                d = v(dens, t)
                step = RATE / d * (1 + rng.uniform(-0.5, 0.5))
            if len(grains) >= MAX_GRAINS:            # steal the oldest
                grains.sort(key=lambda g: g["start"])
                grains.pop(0)
            sp = v(sprd, t) if mode == "SYNC" else 0.0
            grains.append({"start": next_start, "len": max(L, 8.0), "rate": rate, "sp": sp,
                           "pos": gpos, "ph0": rng.random() if mode == "CLOUD" else 0.0})
            next_start += step
            k += 1
        idx = np.arange(b0, min(b0 + BLOCK, n), dtype=np.float64)
        acc = np.zeros(len(idx))
        keep = []
        for g in grains:
            local = idx - g["start"]
            live = (local >= 0) & (local < g["len"])
            if live.any():
                ph = g["ph0"] + local * g["rate"] / RATE
                if mode == "SYNC":
                    w = window(local / period, v(size, t), v(win, t))
                else:                         # CLOUD: a symmetric bell; pitch comes from the grain itself
                    x = np.clip(local / g["len"], 0, 1)
                    w = 0.5 - 0.5 * np.cos(2 * np.pi * x)
                gp = np.full(len(idx), g["pos"])
                if g["sp"]:     # SPRD: the same grain read at +/- spread, so every period is alike
                    r = 2.0 ** (g["sp"] / 12.0)
                    s = 0.5 * (table.read(gp, g["ph0"] + local * g["rate"] * r / RATE)
                               + table.read(gp, g["ph0"] + local * g["rate"] / r / RATE))
                else:
                    s = table.read(gp, ph)
                acc += np.where(live, s * w, 0.0)
            if g["start"] + g["len"] > idx[-1]:
                keep.append(g)
        grains = keep
        # normalise for overlap so SIZE does not change the level much
        norm = 1.0 / ((0.55 + 0.3 * (v(size, t) - 1)) if mode == "SYNC" else 1.6)
        out[b0:b0 + len(idx)] = acc * norm
    return out


def write_wav(path: str, x: np.ndarray, gain_db: float = -3.0) -> None:
    peak = np.max(np.abs(x)) or 1.0
    y = x / peak * 10 ** (gain_db / 20)
    fade = int(0.01 * RATE)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)

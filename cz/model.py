"""CZ: the reference model of a Casio CZ-style phase-distortion voice (docs/cz.md).

Phase distortion: a cosine read through a bent phase. DCW (0..1) sets how far it is bent:
at 0 every non-resonant wave is a sine, at 1 the full shape; on the resonant waves it
moves the resonance. Our own code from the published descriptions (to be checked by ear
against the instrument), not from Casio's.

    WAVES  SAW SQUARE PULSE DOUBLE SAWPULSE RES1 (saw window) RES2 (triangle) RES3 (trapezoid)
    LINE   one line is DCO (wave pair) -> DCW (8-stage env) -> DCA (8-stage env), with an
           8-stage pitch env; SELECT 1 / 2 / 1+1' / 1+2'; line 2 detune; RING; NOISE
    ENV    8 steps of (rate 0..99, level 0..99), a sustain step and an end step
"""

from __future__ import annotations

import math
import wave

import numpy as np

RATE = 48000
WAVES = ("SAW", "SQUARE", "PULSE", "DOUBLE", "SAWPULSE", "RES1", "RES2", "RES3")


# -- the eight waves: phase 0..1 and dcw 0..1 -> -1..1 ----------------------------------------

def _knee(ph, d):
    """phase bent at d: 0..d -> 0..0.5, d..1 -> 0.5..1 (d = 0.5 is straight)"""
    return np.where(ph < d, 0.5 * ph / d, 0.5 + 0.5 * (ph - d) / (1.0 - d))


def wave_out(name: str, ph: np.ndarray, dcw: np.ndarray) -> np.ndarray:
    dcw = np.clip(dcw, 0.0, 1.0)
    if name == "SAW":
        f = _knee(ph, 0.5 - 0.49 * dcw)
    elif name == "SQUARE":
        w = 0.5 - 0.49 * dcw
        h = ph % 0.5
        f = np.where(ph < 0.5, 0.0, 0.5) + 0.5 * np.minimum(1.0, h / w)
    elif name == "PULSE":
        w = 1.0 - 0.95 * dcw
        f = np.minimum(1.0, ph / w)
    elif name == "DOUBLE":                          # one cycle in the first half, then a hold
        f = np.where(ph < 0.5, ph * (1.0 + dcw), 0.5 * (1.0 + dcw) + (ph - 0.5) * (1.0 - dcw))
    elif name == "SAWPULSE":                        # a saw's cycle in the first half, then a hold
        g = np.where(ph < 0.5, _knee(np.minimum(ph * 2.0, 1.0), 0.1), 1.0)
        f = (1.0 - dcw) * ph + dcw * g
    else:
        k = 1.0 + 15.0 * dcw                          # the resonance, harmonic 1 .. 16
        r = 0.5 * (1.0 - np.cos(2.0 * math.pi * k * ph))
        win = {"RES1": 1.0 - ph,
               "RES2": 1.0 - np.abs(2.0 * ph - 1.0),
               "RES3": np.minimum(1.0, 2.0 * (1.0 - ph))}[name]
        return 2.0 * r * win - 1.0
    return -np.cos(2.0 * math.pi * f)


# -- the envelope -------------------------------------------------------------------------------

def rate_time(rate: float, span: float) -> float:
    """seconds to move SPAN (0..1) of the level range at CZ rate 0..99 (99 fastest)"""
    full = 0.0015 * 1.105 ** (99 - rate)             # 99: 1.5 ms, 0: ~30 s across the range
    return max(1.0 / RATE, full * max(span, 0.02))


def envelope(steps, sustain: int, end: int, gate_s: float, n: int) -> np.ndarray:
    """STEPS: 8 (rate, level 0..99). Runs step by step to SUSTAIN, holds while the gate
    is up, then on to END and stops there (the level of END, normally 0)."""
    out = np.empty(n)
    v, i, k = 0.0, 0, 0
    gate_n = int(gate_s * RATE)
    while k < n:
        rate, level = steps[i]
        target = level / 99.0
        dur = int(rate_time(rate, abs(target - v)) * RATE)
        seg = np.linspace(v, target, dur + 1)[1:] if dur > 0 else np.array([target])
        if i == sustain and k < gate_n:
            m = min(len(seg), n - k)
            out[k:k + m] = seg[:m]
            k += m
            hold = max(0, min(gate_n, n) - k)
            out[k:k + hold] = target
            k += hold
            v = target
            i += 1 if k >= gate_n else 0
            continue
        m = min(len(seg), n - k)
        out[k:k + m] = seg[:m]
        k += m
        v = target
        if i >= end:
            out[k:] = v
            break
        i += 1
        if i == sustain + 1 and k < gate_n:          # past sustain only once the gate is down
            pass
    return out


# -- a line and a voice --------------------------------------------------------------------------

def line(note: float, n: int, p: dict, gate_s: float, detune_c: float = 0.0, seed=0) -> np.ndarray:
    hz = 440.0 * 2 ** ((note - 69 + detune_c / 100.0) / 12.0)
    pitch = envelope(p.get("dco", [(99, 0)] * 8), p.get("dco_sus", 0), p.get("dco_end", 0), gate_s, n)
    depth = p.get("dco_depth", 0.0)                  # semitones at level 99
    f = hz * 2 ** (pitch * depth / 12.0)
    if p.get("noise"):
        rng = np.random.default_rng(seed)
        f = f * (1 + 0.8 * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)))
    ph_cont = np.cumsum(f) / RATE
    dcw = envelope(p["dcw"], p["dcw_sus"], p["dcw_end"], gate_s, n) * p.get("dcw_amt", 1.0)
    dcw = dcw * (1.0 - p.get("dcw_kf", 0.0) * (note - 36) / 60.0)
    w1, w2 = p["waves"] if isinstance(p["waves"], tuple) else (p["waves"], None)
    ph = ph_cont % 1.0
    if w2 is None:
        y = wave_out(w1, ph, dcw)
    else:                                            # two waves alternate cycle by cycle
        odd = (np.floor(ph_cont).astype(int) % 2) == 1
        y = np.where(odd, wave_out(w2, ph, dcw), wave_out(w1, ph, dcw))
    dca = envelope(p["dca"], p["dca_sus"], p["dca_end"], gate_s, n)
    return y * dca


def voice(note: float, seconds: float, gate_s: float, patch: dict) -> np.ndarray:
    n = int(seconds * RATE)
    l1 = line(note, n, patch["line1"], gate_s)
    sel = patch.get("select", "1")
    if sel == "1":
        return l1
    l2p = patch.get("line2", patch["line1"])
    det = patch.get("detune_c", 0.0) + 1200 * patch.get("octave2", 0)
    l2 = line(note, n, l2p, gate_s, det, seed=1)
    if patch.get("ring"):
        l2 = l2 * np.sign(l1) * np.abs(l1) ** 0.5
    return 0.5 * (l1 + l2)


def sequence(events, seconds, patch) -> np.ndarray:
    n = int(seconds * RATE)
    mix = np.zeros(n)
    for t, note, gate in events:
        i = int(t * RATE)
        tail = min(seconds - t, gate + 3.0)
        v = voice(note, tail, gate, patch)
        mix[i:i + len(v)] += v[:n - i]
    return mix


def write_wav(path: str, x: np.ndarray, peak: float = 0.89) -> None:
    m = float(np.max(np.abs(x))) or 1.0
    y = np.clip(x / m * peak, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((y * 32767).astype("<i2").tobytes())

"""The slicer: any short sample -> a wavetable, as Tonverk makes one."""

import math
import random

import pytest

from dnfw.wavetable import WavetableError
from dnfw.waverider import factory, reduce, slicer

RATE = 48000


def tone(hz, seconds, amps_at):
    """A tone whose harmonic amplitudes move with time: amps_at(t 0..1) -> [a1, a2, ...]."""
    n = int(RATE * seconds)
    out, ph = [], 0.0
    for k in range(n):
        amps = amps_at(k / n)
        out.append(sum(a * math.sin((h + 1) * ph) for h, a in enumerate(amps)))
        ph += 2 * math.pi * hz / RATE
    return out


def harmonic(frame, h):
    amps, _ = factory.analyse(frame, h)
    return amps[h - 1]


def test_a_pitched_sample_becomes_its_own_cycles():
    # a saw (1/h) fading into a sine over half a second, at 220 Hz
    s = tone(220.0, 0.5, lambda t: [1.0] + [(1 - t) / h for h in range(2, 9)])
    frames, rep = slicer.slice_samples(s, RATE)
    assert len(frames) == 16 and all(len(f) == slicer.CYCLE for f in frames)
    assert all(kind == "pitch" and abs(hz - 220.0) < 1.0 for kind, hz, _ in rep["frames"])
    first, last = frames[0], frames[-1]
    assert harmonic(first, 2) / harmonic(first, 1) == pytest.approx(0.5 * 0.97, rel=0.1)
    assert harmonic(last, 2) / harmonic(last, 1) < 0.1          # nearly a sine by the end
    assert max(abs(v) for f in frames for v in f) == pytest.approx(1.0)


def test_a_strong_second_harmonic_does_not_halve_the_pitch_read():
    s = tone(110.0, 0.4, lambda t: [0.4, 1.0, 0.2])
    _, rep = slicer.slice_samples(s, RATE, mode="pitch")
    assert all(abs(hz - 110.0) < 1.0 for _, hz, _ in rep["frames"])


def test_noise_falls_back_to_windows_and_pitch_mode_refuses():
    rng = random.Random(1)
    s = [rng.uniform(-1, 1) for _ in range(RATE // 2)]
    frames, rep = slicer.slice_samples(s, RATE)
    assert all(kind == "window" for kind, _, _ in rep["frames"])
    assert len(frames) == 16
    with pytest.raises(WavetableError):
        slicer.slice_samples(s, RATE, mode="pitch")


def test_frames_are_band_limited():
    s = tone(220.0, 0.3, lambda t: [1.0 / h for h in range(1, 60)])
    frames, _ = slicer.slice_samples(s, RATE, harmonics=48)
    amps, _ = factory.analyse(frames[5], 60)
    assert max(amps[48:]) < 1e-6 and amps[0] > 0.1


def test_tonverk_naming_and_the_wav_round_trip():
    assert slicer.name_window("pad_wt1024.wav") == 1024
    assert slicer.name_window("pad.wav") is None
    s = tone(330.0, 0.3, lambda t: [1.0, 0.5 * t])
    frames, _ = slicer.slice_samples(s, RATE)
    data = slicer.wav_bytes(frames)
    assert slicer.wav_rate(data) == 48000
    table = reduce.from_wav(data)
    assert len(table) == reduce.FRAMES and len(table[0]) == reduce.POINTS
    assert max(abs(v) for f in table for v in f) == reduce.PEAK

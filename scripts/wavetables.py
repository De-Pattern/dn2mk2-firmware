"""Three LFO wavetables, generated from maths: basic shapes, a harmonic sweep, vowels.

The owner, 2026-09-17: *"a wavetable option should be richer in the transition
between waves ... some mythical and loved wavetable to sweep across"*, and chose
three tables over one. Each is **our own maths** -- no ROM data from any other
instrument -- inspired by the classic ideas:

- **WTB1, basic shapes:** sine -> triangle -> saw -> square -> ever narrower pulse,
  the morph soft synths ship as their default table.
- **WTB2, harmonic sweep:** a sine that gains harmonics frame by frame, the PPG
  Wave's signature brightening sweep, rebuilt additively.
- **WTB3, vowels:** A E I O U and back, two formant bumps per vowel placed on
  harmonics of the fundamental.

## Why 7 frames of 32 signed bytes

The clean caves hold 896 bytes each (`docs/memory-map.md`). Three tables of
7 x 32 bytes are 672, which leaves room for the glyph sets and labels in the same
cave. The generator **interpolates bilinearly** -- across the 32 samples along the
phase, and between two frames along SPH -- so an LFO never hears a step between
samples or a jump between frames. 32 points a cycle is plenty for an LFO; the
only visible cost is that a square's edges become 1/32-cycle ramps.
"""

from __future__ import annotations

import math

FRAMES = 7
SAMPLES = 32
PEAK = 127


def _normalise(values: list[float]) -> list[int]:
    peak = max(abs(v) for v in values) or 1.0
    return [max(-PEAK, min(PEAK, int(round(v / peak * PEAK)))) for v in values]


def _frame(f) -> list[int]:
    return _normalise([f(i / SAMPLES) for i in range(SAMPLES)])


def basic_shapes() -> list[list[int]]:
    def pulse(duty):
        return lambda x: 1.0 if x < duty else -1.0
    return [
        _frame(lambda x: math.sin(2 * math.pi * x)),
        _frame(lambda x: 1 - 4 * abs(x - 0.25) if x < 0.75 else 4 * x - 4),   # triangle
        _frame(lambda x: 2 * x - 1),                                          # rising saw
        _frame(pulse(0.5)),
        _frame(pulse(0.25)),
        _frame(pulse(0.125)),
        _frame(pulse(0.0625)),
    ]


def harmonic_sweep() -> list[list[int]]:
    counts = [1, 2, 3, 5, 8, 11, 15]           # 15: the most 32 samples can hold
    return [_frame(lambda x, n=n: sum(math.sin(2 * math.pi * k * x) / k for k in range(1, n + 1)))
            for n in counts]


# (F1, F2) in harmonics of the fundamental, approximating a ~110 Hz voice and
# capped at the 15th harmonic.
VOWELS = {"A": (7, 11), "E": (4, 15), "I": (3, 15), "O": (4, 8), "U": (3, 6)}


def vowel_sweep() -> list[list[int]]:
    def vowel(f1, f2):
        def amp(k):
            return (0.7 * (k == 1)
                    + math.exp(-((k - f1) / 1.2) ** 2)
                    + 0.6 * math.exp(-((k - f2) / 1.5) ** 2))
        return lambda x: sum(amp(k) * math.cos(2 * math.pi * k * x) for k in range(1, 16))
    return [_frame(vowel(*VOWELS[v])) for v in "AEIOUIE"]


TABLES = [("WTB1", "WT1", basic_shapes), ("WTB2", "WT2", harmonic_sweep), ("WTB3", "WT3", vowel_sweep)]


def table_bytes(frames: list[list[int]]) -> bytes:
    assert len(frames) == FRAMES and all(len(f) == SAMPLES for f in frames)
    return bytes((v & 0xFF) for frame in frames for v in frame)


def reference(frames: list[list[int]], phase: int, sph: int) -> int:
    """The generator's arithmetic in Python, for checking the assembly bit for bit."""
    pos = min((sph & 0x7F) * 49, (FRAMES - 1) * 1024)
    f, ff = pos >> 10, pos & 1023
    if f == FRAMES - 1:
        f, ff = FRAMES - 2, 1024
    s, sf = phase >> 27, (phase >> 17) & 1023
    s1 = (s + 1) & 31

    def row(fr):
        a, b = frames[fr][s], frames[fr][s1]
        return a * 1024 + (b - a) * sf
    ab, cd = row(f), row(f + 1)
    out = (ab * 1024 + (cd - ab) * ff) << 4
    out &= 0xFFFFFFFF
    return out - (1 << 32) if out & 0x80000000 else out

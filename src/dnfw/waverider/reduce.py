"""Any wavetable's frames -> the geometry Waverider bakes: 16 frames x 512 int16.

The same three steps as `dnfw.wavetable` (the LFO tables), at a larger size:

1. frames are brought to **16** by linear interpolation along the table (fewer
   than 16 are interpolated up; one frame is repeated);
2. each frame is brought to **512** points by averaging each 512th of the cycle
   -- a box filter, so a 2048-sample frame's top harmonics fold smoothly instead
   of aliasing (for 2048 -> 512 it is exactly the mean of four samples);
3. the whole table is scaled so its largest point is **32767**, keeping the
   relative levels between frames, and rounded half away from zero.

**Why 16 x 512.** It is Milestone 0's geometry (16 KB), not a decision about
sound: how few points per frame stay clean depends on the oscillator's
interpolation, which is a DSP question not yet answerable
(`docs/waverider-feasibility.md`, "The geometry is not decidable yet"). Both
numbers are parameters here so the geometry can move without a rewrite.

Reading a WAV is `dnfw.wavetable.parse_wav` / `split_frames`, reused, not copied:
the factory format (float32, 2048-sample frames) is exactly what they read. The
frame length alone comes from `source.info`, which reads a short `clm ` frame
length correctly where `parse_wav` does not (see `source.clm_frame`).
"""

from __future__ import annotations

import math

from ..wavetable import WavetableError, parse_wav, split_frames
from . import source

FRAMES = 16
POINTS = 512
PEAK = 32767


def _round(v: float) -> int:
    return int(math.floor(abs(v) + 0.5)) * (1 if v >= 0 else -1)


def box(frame: list[float], points: int = POINTS) -> list[float]:
    """Average each `points`-th of the cycle. Works for frames shorter than `points`."""
    n = len(frame)
    out = []
    for j in range(points):
        lo, hi = j * n / points, (j + 1) * n / points
        total = weight = 0.0
        k = int(math.floor(lo))
        while k < hi and k < n:
            w = min(hi, k + 1) - max(lo, k)
            if w > 0:
                total += frame[k] * w
                weight += w
            k += 1
        out.append(total / weight if weight else 0.0)
    return out


def to_int16(frames: list[list[float]], count: int = FRAMES,
             points: int = POINTS) -> list[list[int]]:
    """Any frames of floats -> `count` x `points` int16 (see the module docstring)."""
    if not frames or any(len(f) == 0 for f in frames):
        raise WavetableError("a wavetable needs at least one non-empty frame")
    small = [box(f, points) for f in frames]
    picked = []
    for k in range(count):
        pos = k * (len(small) - 1) / (count - 1) if len(small) > 1 and count > 1 else 0.0
        a = int(math.floor(pos))
        b = min(a + 1, len(small) - 1)
        t = pos - a
        picked.append([small[a][j] * (1 - t) + small[b][j] * t for j in range(points)])
    peak = max(abs(v) for f in picked for v in f)
    if peak == 0:
        raise WavetableError("the wavetable is silent")
    return [[max(-PEAK, min(PEAK, _round(v / peak * PEAK))) for v in f] for f in picked]


def from_wav(data: bytes) -> list[list[int]]:
    """A WAV wavetable -> the baked geometry."""
    described = source.info(data)
    if not described["ok"]:
        raise WavetableError(described["error"])
    samples, _ = parse_wav(data)
    return to_int16(split_frames(samples, described["frame"]))

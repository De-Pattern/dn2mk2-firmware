"""The second table Milestone 5 bakes: the overtone series, one partial a frame.

Original, generated here, no Elektron data. Frame `k = 0..15` is the pure sine of
partial `k + 1`:

    frame_k(p) = sin((k + 1) * p),   p = 2*pi*n / 2048

so sweeping the frame position climbs the harmonic series -- the fundamental, then
its octave, fifth above, second octave, ... up to the 16th partial, four octaves
above the note. Nothing a stock Digitone machine offers sounds like that, which is
why it is the demo table: a knob that walks up the overtones is unmistakable within
a bar.

Every frame has the same peak, so `reduce.to_int16` scales them all to 32767. The
16th partial at 512 points is 32 points a cycle, well inside what the reader's
linear interpolation holds.
"""

from __future__ import annotations

import math

from . import reduce

SOURCE_POINTS = 2048


def source_frames(frames: int = reduce.FRAMES, points: int = SOURCE_POINTS) -> list[list[float]]:
    """The float frames before reduction."""
    return [[math.sin((k + 1) * 2.0 * math.pi * n / points) for n in range(points)]
            for k in range(frames)]


def table() -> list[list[int]]:
    """-> the baked 16 x 512 int16 table."""
    return reduce.to_int16(source_frames())

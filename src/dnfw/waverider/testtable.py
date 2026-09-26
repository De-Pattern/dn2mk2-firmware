"""The table Milestone 0 bakes: original, generated here, no Elektron data.

**No Elektron IP goes into a mod** -- not the factory `Wavetables.zip`, not
anything derived from one. This table is a formula.

**The formula.** 16 frames of 2048 points (the factory frame size, so the
reduction in `reduce` runs on the shape it will meet in practice), frame
`k = 0..15`, morph `t = k / 15`, phase `p = 2*pi*n / 2048`:

    saw(p)   = sum over h = 1..32 of  (-1)^(h+1) * sin(h*p) / h
    frame_k  = (1 - t) * sin(p)  +  t * saw(p)

So frame 0 is a pure sine, frame 15 a saw band-limited to 32 harmonics (far
below the 256 a 512-point frame can hold), and the frames between are a linear
blend. The factor `2/pi` that normalises a saw is left out because `reduce`
rescales the whole table to a peak of 32767 anyway.

Every value is then fixed by `reduce.to_int16`, and the expected telemetry is
computed from those integers -- so the host and the firmware disagree only if a
byte changed on the way.
"""

from __future__ import annotations

import math

from . import reduce

SOURCE_POINTS = 2048
HARMONICS = 32


def source_frames(frames: int = reduce.FRAMES, points: int = SOURCE_POINTS,
                  harmonics: int = HARMONICS) -> list[list[float]]:
    """The float frames before reduction (see the module docstring)."""
    out = []
    for k in range(frames):
        t = k / (frames - 1) if frames > 1 else 0.0
        frame = []
        for n in range(points):
            p = 2.0 * math.pi * n / points
            saw = sum((1 if h % 2 else -1) * math.sin(h * p) / h
                      for h in range(1, harmonics + 1))
            frame.append((1.0 - t) * math.sin(p) + t * saw)
        out.append(frame)
    return out


def table() -> list[list[int]]:
    """-> the baked 16 x 512 int16 table."""
    return reduce.to_int16(source_frames())

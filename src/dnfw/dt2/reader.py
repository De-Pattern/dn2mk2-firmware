"""The Digitakt II's sample reader as a reference model, in plain Python (2026-11-15).

The gate's sample machine step (sharc_waverider_m5, "v0.18: ONESHOT plays KICK from the pool
as the DT2's reader does") and test_sampler compare the DSP's ONESHOT against this. Until now
they imported a model that lives outside the repository (`../dt2s117/research/tools/
models_reader.py`), which only upstream's host has, so the check failed everywhere else.

What the DT2's reader does (docs/sampler.md, "v0.18: the DT2's own reader"):

- **The interpolator**, one sample at 96 kHz: six frames from the read position (forward
  s[p..p+5], backward s[p-5..p]) against row floor(256 frac) of its 256 x 6 table. The
  taps wrap inside the window [lo, hi), as the DT2's circular buffer does.
- **The MAC** multiplies the 16-bit frames by the Q31 coefficients and keeps the sum's whole
  16-bit steps, toward -inf. Here that is exact integer arithmetic: floor(sum(s c) / 2^31).
  (The DSP sums in float32 and then floors, so it may differ by one step now and then.)
- **The 2:1 decimator**, float32 like the DT2's: half the sum of a fourth-order all-pass of
  the even 96 kHz samples and the odd ones four outputs late, in the DT2's order of operations.
  It starts cleared at each note.

The tables come from the owner's own DT2 image through `dnfw.dt2.rom` (its sha256 checked);
nothing of Elektron's is in this file. Positions are exact: frames in units of 2^-32.

This model covers a voice reading inside its window, which is what the gate checks; a read
that would pass the window's end raises, rather than guess what the DT2 does there.
"""

from __future__ import annotations

import dataclasses
import struct

from . import rom

ONE = 1 << 32                                   # one frame, in the position's units
TAPS, ROWS = rom.POLY_TAPS, rom.POLY_ROWS


def f32(x: float) -> float:
    """x rounded to float32, as the DT2's floating-point unit holds it"""
    return struct.unpack("<f", struct.pack("<f", x))[0]


@dataclasses.dataclass
class Voice:
    """One voice: its 16-bit frames, the window [lo, hi) in frames, the position and the
    step a 96 kHz sample (both in 2^-32 frames), and the decimator's twelve words."""
    pcm: list[int]
    pos: int
    rate: int
    lo: int = 0
    hi: int | None = None
    reverse: bool = False
    even: list[float] = dataclasses.field(default_factory=lambda: [0.0] * 4)     # e1..e4
    past: list[float] = dataclasses.field(default_factory=lambda: [0.0] * 4)     # h1..h4
    odd: list[float] = dataclasses.field(default_factory=lambda: [0.0] * 4)      # r0..r3

    def __post_init__(self) -> None:
        self.hi = len(self.pcm) if self.hi is None else self.hi
        if not 0 <= self.lo < self.hi <= len(self.pcm):
            raise ValueError(f"window [{self.lo}, {self.hi}) is not inside the {len(self.pcm)} frames")
        if any(not -32768 <= s <= 32767 for s in self.pcm):
            raise ValueError("frames are 16-bit")


def coefficients() -> list[list[int]]:
    """the interpolator's 256 rows of six Q31 coefficients, from the DT2 image"""
    return [[round(c * 2.0 ** 31) for c in row] for row in rom.polyphase()]


def interpolate(v: Voice, rows: list[list[int]]) -> float:
    """the 96 kHz sample at v.pos: the MAC's 16-bit result, as a float in [-1, 1)"""
    frame, row = v.pos >> 32, (v.pos >> 24) & (ROWS - 1)
    if not v.lo <= frame < v.hi:
        raise ValueError(f"position {frame} is outside the window [{v.lo}, {v.hi})")
    width = v.hi - v.lo
    step = -1 if v.reverse else 1
    taps = [v.lo + (frame - v.lo + step * k) % width for k in range(TAPS)]
    if v.reverse:
        taps.reverse()                          # s[p-5..p] against the row in order
    acc = sum(v.pcm[t] * c for t, c in zip(taps, rows[row]))
    return (acc >> 31) / 32768.0                # floor: the whole 16-bit steps, toward -inf


def advance(v: Voice) -> None:
    v.pos += -v.rate if v.reverse else v.rate


def decimate(v: Voice, xe: float, xo: float, c: tuple[float, ...]) -> float:
    """the decimator's next 48 kHz output from the 96 kHz pair (xe, xo)"""
    e1, e2, e3, e4 = v.even
    h1, h2, h3, h4 = v.past
    h = f32(xe * c[3])
    h = f32(h + f32(e1 * c[2]))
    h = f32(f32(e2 * c[1]) + h)
    h = f32(f32(e3 * c[0]) + h)
    h = f32(e4 + h)
    for hk, ck in ((h1, c[0]), (h2, c[1]), (h3, c[2]), (h4, c[3])):
        h = f32(h - f32(hk * ck))
    out = f32(f32(h + v.odd[3]) * 0.5)
    v.even = [xe, e1, e2, e3]
    v.past = [h, h1, h2, h3]
    v.odd = [xo] + v.odd[:3]
    return out


def read(v: Voice, n: int, rows: list[list[int]] | None = None,
         decim: tuple[float, ...] | None = None) -> list[float]:
    """the voice's next n samples at 48 kHz: two 96 kHz samples each, through the decimator"""
    rows = rows if rows is not None else coefficients()
    c = decim if decim is not None else rom.decimator()
    out = []
    for _ in range(n):
        pair = []
        for _ in range(2):
            pair.append(interpolate(v, rows))
            advance(v)
        out.append(decimate(v, pair[0], pair[1], c))
    return out

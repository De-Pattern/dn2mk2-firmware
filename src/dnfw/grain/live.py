"""GRAN, a granular effect in the filter slot (filter type 8): the contract the SHARC
code is held to, bit for bit (docs/gran.md).

The same rules as `dnfw.ping.live` and `dnfw.shft.live`: float32 after every operation,
in the DSP's order; add, subtract, multiply, min/max, compare, FLOAT/TRUNC, table reads,
integer adds, ANDs and shifts; no division.

**What it does.** Each track on GRAN writes what its machine plays into a ring buffer
of its own (`BUF_N` samples, 0.68 s), and plays it back as a stream of short grains:
up to `GRAINS` at once, each a window over a stretch of the recent past, read at its
own speed. SIZE sets a grain's length, DENS how many overlap, MODE how they read
(as played, an octave up, an octave down, reversed), SPRD how far back at random they
start, FDBK how much of the result goes back into the buffer (clouds that smear and
build). MIX is dry to wet.

**Controls**, from the stock filter fields in the track record (Multi-Mode's page,
relabelled), each a float 0..1:

| record | stock | GRAN |
|---|---|---|
| `+0x1cc` | FREQ | SIZE: 10 .. 160 ms, exponential |
| `+0x1d0` | RESO | DENS: 1 .. 4 grains overlapping |
| `+0x1c8` | TYPE | MODE: NORM, UP, DOWN, REV (quarters) |
| `+0x204` | env depth | SPRD: how far back grains scatter, by its distance from the centre |
| `+0x1f0` | env attack | FDBK, 0 .. 0.9 |
| `+0x1f8` | env sustain | MIX, dry .. wet |
| `+0x1ec` | env delay | DRIV, 0.4 .. 2.0 into the buffer (as SHFT's) |

**A grain.** Its read position starts `D` samples behind the write head:
`64 + (UP ? L : 0) + trunc(r x SPRD x SCATTER)`, `r` from a per-track LCG; it moves by
its rate a sample (1, 2, 0.5 or -1), read with linear interpolation; its window is the
parabola `4 x (1 - x)` over its `L` samples. A new grain starts every `L / DENS`
samples, in the next of the four slots (the oldest is stolen). The wet sum is scaled
by `1 / sqrt(DENS)`.

**The buffer** is float32, `BUF_N` a power of two (index & `MASK`), in DDR. The input
written is `x drive + FDBK knee(wet)`; the output is PING's ceiling on the wet signal,
mixed with the dry as SHFT does.
"""

from __future__ import annotations

import math
import struct

from ..ping import live as P

_f32, at127, knee, trunc = P._f32, P.at127, P.knee, P.trunc

RATE = P.RATE
FILTER_TYPE = 8
MODES = ("NORM", "UP", "DOWN", "REV")
RATES = (1.0, 2.0, 0.5, -1.0)
BUF_N = 32768
MASK = BUF_N - 1
GRAINS = 4
GUARD = 64                                # the nearest a grain starts to the write head
SCATTER = 16384.0                         # SPRD's reach, samples
SIZE_MIN, SIZE_MAX = 480.0, 7680.0        # 10 ms, 160 ms
FDBK_MAX = 0.9
LCG_A, LCG_C = 1664525, 1013904223
SEED = 0x9E3779B9

R_TYPE, R_FREQ, R_RES = P.R_TYPE, P.R_FREQ, P.R_RES
R_DRIVE, R_FDBK, R_MIX, R_SPRD = P.R_DRIVE, P.R_ATK, P.R_CURVE, P.R_DEPTH

CTRL_N = 128


def table_size() -> list[float]:
    """SIZE (index trunc(v x 127)) -> a grain's length in samples, a whole number."""
    return [_f32(float(round(SIZE_MIN * (SIZE_MAX / SIZE_MIN) ** (i / 127.0))))
            for i in range(CTRL_N)]


def table_wstep() -> list[float]:
    """1 / the length: the window's step a sample."""
    return [_f32(1.0 / x) for x in table_size()]


def _overlap(i: int) -> float:
    return 1.0 + 3.0 * i / 127.0


def table_spacing() -> list[float]:
    """DENS -> 1 / overlap: a grain starts every L x this samples."""
    return [_f32(1.0 / _overlap(i)) for i in range(CTRL_N)]


def table_norm() -> list[float]:
    """DENS -> 1 / sqrt(overlap): the wet sum's scale."""
    return [_f32(1.0 / math.sqrt(_overlap(i))) for i in range(CTRL_N)]


TABLES = (("size", table_size), ("wstep", table_wstep), ("spacing", table_spacing),
          ("norm", table_norm))


def tables() -> dict[str, list[float]]:
    return {name: build() for name, build in TABLES}


def tables_bytes() -> tuple[bytes, dict[str, int]]:
    out, at = b"", {}
    for name, build in TABLES:
        at[name] = len(out)
        out += struct.pack("<%df" % len(build()), *build())
    return out, at


def _clamp01(v: float) -> float:
    return min(max(v, 0.0), 1.0)


class Grain:
    def __init__(self):
        self.pos = self.rate = self.wph = self.wstep = 0.0
        self.left = 0


class Voice:
    """One track's GRAN state; zero is rest. The buffer is its own (DDR)."""

    def __init__(self):
        self.w = 0                        # the write head
        self.seed = 0                     # 0: not yet seeded (SEED on first use)
        self.count = 0                    # samples to the next grain
        self.k = 0                        # the slot the next grain takes
        self.wet = 0.0                    # the last sample's wet, for the feedback
        self.g = [Grain() for _ in range(GRAINS)]
        self.buf = [0.0] * BUF_N


def controls(rec: dict[int, float], T: dict) -> dict:
    mode = min(3, trunc(_f32(_clamp01(rec[R_TYPE]) * 4.0)))
    size = at127(T["size"], rec[R_FREQ])
    sprd = _f32(abs(_f32(rec[R_SPRD] - 0.5)) * 2.0)
    sprd = min(sprd, 1.0)
    return {
        "mode": mode,
        "rate": RATES[mode],
        "len": trunc(size),
        "wstep": at127(T["wstep"], rec[R_FREQ]),
        "spacing": max(1, trunc(_f32(size * at127(T["spacing"], rec[R_RES])))),
        "norm": at127(T["norm"], rec[R_RES]),
        "scatter": _f32(sprd * SCATTER),
        "base": GUARD + (trunc(size) if mode == 1 else 0),
        "fdbk": _f32(_clamp01(rec[R_FDBK]) * _f32(FDBK_MAX)),
        "mix": _clamp01(rec[R_MIX]),
        "drive": _f32(_f32(0.4) + _f32(_f32(1.6) * _clamp01(rec[R_DRIVE]))),
    }


def _start(v: Voice, c: dict) -> None:
    if v.seed == 0:
        v.seed = SEED
    v.seed = (v.seed * LCG_A + LCG_C) & 0xFFFFFFFF
    r = _f32(float(v.seed >> 8) * 2.0 ** -24)
    d = c["base"] + trunc(_f32(r * c["scatter"]))
    g = v.g[v.k]
    g.pos = _f32(float((v.w - d) & MASK))
    g.rate = c["rate"]
    g.wph = 0.0
    g.wstep = c["wstep"]
    g.left = c["len"]
    v.k = (v.k + 1) & (GRAINS - 1)


def _read(buf: list[float], pos: float) -> float:
    i = trunc(pos)
    f = _f32(pos - _f32(float(i)))
    a = buf[i]
    b = buf[(i + 1) & MASK]
    return _f32(a + _f32(f * _f32(b - a)))


def block(v: Voice, buf: list[float], rec: dict[int, float], note: float, trig: bool,
          T: dict | None = None) -> list[float]:
    """One 32-sample block of a GRAN track: BUF (the machine's output) -> grains."""
    T = T or tables()
    c = controls(rec, T)
    out = []
    for s in buf:
        v.count -= 1
        if v.count <= 0:
            v.count += c["spacing"]
            _start(v, c)
        acc = 0.0
        for g in v.g:
            if g.left <= 0:
                continue
            x = _read(v.buf, g.pos)
            w = _f32(_f32(4.0 * g.wph) * _f32(1.0 - g.wph))
            acc = _f32(acc + _f32(x * w))
            p = _f32(g.pos + g.rate)
            if p >= float(BUF_N):
                p = _f32(p - float(BUF_N))
            if p < 0.0:
                p = _f32(p + float(BUF_N))
            g.pos = p
            g.wph = _f32(g.wph + g.wstep)
            g.left -= 1
        wet = _f32(acc * c["norm"])
        fb = knee(wet, 0.5, 0.5)
        v.buf[v.w] = _f32(_f32(s * c["drive"]) + _f32(c["fdbk"] * fb))
        v.w = (v.w + 1) & MASK
        y = knee(wet, 0.6, 0.6)
        out.append(_f32(s + _f32(c["mix"] * _f32(y - s))))
    return out

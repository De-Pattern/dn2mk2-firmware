"""SHFT as the DSP computes it: the contract `ping.asm`'s SHFT path is held to, bit for bit.

`shft/model.py` is the sound (`docs/shft.md`). This is the same design in float32, in
the operations and the order the SHARC code performs them (`dnfw.ping.live`'s rules:
add, subtract, multiply, min/max, compare, FLOAT/TRUNC, table reads; no division, no
sin, no tanh). It reuses PING's float32 helpers and its ATK and DEC tables.

**Where it runs.** In PING's track loop (`ping.asm`), for every track whose frame filter
type is 7 (`FILTER_TYPE`), whatever its machine. The stock unpack maps 7 to DSP filter
0, "no filter", as it does 6 (`docs/ping.md`, measured for 6..9).

**Controls**, from the stock filter fields in the track record (Multi-Mode's page,
relabelled), each a float 0..1:

| record | stock | SHFT |
|---|---|---|
| `+0x1c8` | TYPE | MODE: UP, DOWN, BOTH (thirds) |
| `+0x1cc` | FREQ | SHFT: knob = FREQ x 128, 64 = 0; +-2.5 kHz, cubic |
| `+0x1d0` | RESO | FDBK, 0 .. 0.95 |
| `+0x1ec` | env delay | DRIV, 0.4 .. 2.0 into the shifter |
| `+0x1f0` | env attack | ATK (PING's table) |
| `+0x1f4` | env decay | DEC (PING's table); the decay is (1 - x)^3 |
| `+0x1f8` | env sustain | MIX, dry .. wet |
| `+0x204` | env depth | ENV, +-2.5 kHz on the shift (0.5 = 0) |
| `+0x208` | key tracking | the shift x 2^(keyt (note - 60) / 12) |

**The shifter.** Two chains of four all-passes in z^-2, `y = c^2 (x + y[n-2]) - x[n-2]`,
make a 90-degree pair over the audio band (Olli Niemitalo's published coefficients);
chain A one sample late is I, chain B is Q. A stage's input two samples ago is the
previous stage's output two samples ago, so a chain keeps two outputs per stage and the
pair shares the input's history. The oscillator reads one sine table (a quarter turn on
for the cosine). UP = I cos + Q sin, DOWN = I cos - Q sin, BOTH = I cos (a ring
modulation). The feedback passes PING's knee (to 0.75 at most); the wet signal passes
PING's output ceiling (0.9 at most). Measured on the model: the unwanted sideband is
47..58 dB down from 40 Hz to 12 kHz.
"""

from __future__ import annotations

import math
import struct

from ..ping import live as P

_f32, interp, at127, knee, trunc = P._f32, P.interp, P.at127, P.knee, P.trunc

RATE = P.RATE
FILTER_TYPE = 7
MODES = ("UP", "DOWN", "BOTH")
MAX_HZ = 2500.0
A = (0.6923878, 0.9360654322959, 0.9882295226860, 0.9987488452737)
B = (0.4021921162426, 0.8561710882420, 0.9722909545651, 0.9952884791278)
A2 = tuple(_f32(c * c) for c in A)
B2 = tuple(_f32(c * c) for c in B)

R_TYPE, R_FREQ, R_RES = P.R_TYPE, P.R_FREQ, P.R_RES
R_DRIVE, R_ATK, R_DEC, R_MIX = P.R_DRIVE, P.R_ATK, P.R_DEC, P.R_CURVE
R_DEPTH, R_KEYT = P.R_DEPTH, P.R_KEYT

SIN_N = 256                              # sine table: 256 points a turn, + a quarter + 2
POW2_MID = 64                            # 2^((i - 64) / 12), i = 0..128


def table_sin() -> list[float]:
    return [_f32(math.sin(2.0 * math.pi * j / SIN_N)) for j in range(SIN_N + SIN_N // 4 + 2)]


def table_pow2() -> list[float]:
    return [_f32(2.0 ** ((i - POW2_MID) / 12.0)) for i in range(2 * POW2_MID + 1)]


TABLES = (("sin", table_sin), ("pow2", table_pow2))


def tables() -> dict[str, list[float]]:
    out = {name: build() for name, build in TABLES}
    pt = P.tables()
    out["atk"], out["dec"] = pt["atk"], pt["dec"]
    return out


def tables_bytes() -> tuple[bytes, dict[str, int]]:
    """SHFT's own tables (not PING's), float32 little-endian; -> (bytes, {name: offset})."""
    out, at = b"", {}
    for name, build in TABLES:
        at[name] = len(out)
        out += struct.pack("<%df" % len(build()), *build())
    return out, at


def _clamp01(v: float) -> float:
    return min(max(v, 0.0), 1.0)


class Voice:
    """One track's SHFT state; zero is rest (stage 0 idle, 1 attack, 2 decay)."""

    def __init__(self):
        self.in1 = self.in2 = 0.0
        self.ay1, self.ay2 = [0.0] * 4, [0.0] * 4
        self.by1, self.by2 = [0.0] * 4, [0.0] * 4
        self.iprev = self.phase = self.fb = 0.0
        self.stage = 0
        self.x = 0.0


def note_ok(note: float) -> float:
    """machine5_live's validation: NaN, an infinity or a negative value is +0.0."""
    if math.isnan(note) or math.isinf(note) or P._bits(note) >> 31:
        return 0.0
    return note


def controls(rec: dict[int, float], note: float, T: dict) -> dict:
    mode = min(2, trunc(_f32(_clamp01(rec[R_TYPE]) * 3.0)))
    knob = _f32(_clamp01(rec[R_FREQ]) * 128.0)
    u = _f32(_f32(knob - 64.0) * _f32(1.0 / 63.0))
    u = min(max(u, -1.0), 1.0)
    hz = _f32(_f32(_f32(u * u) * u) * MAX_HZ)
    keyt = _clamp01(rec[R_KEYT])
    s = _f32(keyt * _f32(note_ok(note) - 60.0))
    ratio = interp(T["pow2"], _f32(s + float(POW2_MID)))
    inc = _f32(_f32(hz * ratio) * _f32(1.0 / RATE))
    envd = _f32(_f32(rec[R_DEPTH] - 0.5) * 2.0)
    return {
        "mode": mode,
        "inc": inc,
        "inc_env": _f32(envd * _f32(MAX_HZ / RATE)),
        "fdbk": _f32(_clamp01(rec[R_RES]) * _f32(0.95)),
        "mix": _clamp01(rec[R_MIX]),
        "drive": _f32(_f32(0.4) + _f32(_f32(1.6) * _clamp01(rec[R_DRIVE]))),
        "atk": at127(T["atk"], rec[R_ATK]),
        "dec": at127(T["dec"], rec[R_DEC]),
    }


def envelope(v: Voice, c: dict) -> float:
    if v.stage == 1:
        a = v.x
        v.x = _f32(v.x + c["atk"])
        if v.x >= 1.0:
            v.stage, v.x = 2, 0.0
        return a
    if v.stage == 2:
        d = _f32(1.0 - v.x)
        a = _f32(_f32(d * d) * d)
        v.x = _f32(v.x + c["dec"])
        if v.x >= 1.0:
            v.stage, v.x = 0, 0.0
        return a
    return 0.0


def chain(x: float, in2: float, c2: tuple, y1: list, y2: list) -> float:
    old2 = in2
    for i in range(4):
        y = _f32(_f32(c2[i] * _f32(x + y2[i])) - old2)
        old2 = y2[i]
        y2[i] = y1[i]
        y1[i] = y
        x = y
    return x


def block(v: Voice, buf: list[float], rec: dict[int, float], note: float, trig: bool,
          T: dict | None = None) -> list[float]:
    """One 32-sample block of a SHFT track: BUF (the machine's output) -> shifted."""
    T = T or tables()
    c = controls(rec, note, T)
    if trig:
        v.stage, v.x = 1, 0.0
    out = []
    for s in buf:
        a = envelope(v, c)
        fbs = knee(v.fb, 0.5, 0.5)
        x = _f32(_f32(s * c["drive"]) + _f32(c["fdbk"] * fbs))
        ya = chain(x, v.in2, A2, v.ay1, v.ay2)
        yb = chain(x, v.in2, B2, v.by1, v.by2)
        v.in2, v.in1 = v.in1, x
        i, v.iprev = v.iprev, ya
        p = _f32(v.phase * float(SIN_N))
        sn = interp(T["sin"], p)
        cs = interp(T["sin"], _f32(p + float(SIN_N // 4)))
        ic = _f32(i * cs)
        if c["mode"] == 0:
            y = _f32(ic + _f32(yb * sn))
        elif c["mode"] == 1:
            y = _f32(ic - _f32(yb * sn))
        else:
            y = ic
        v.fb = y
        ph = _f32(v.phase + _f32(c["inc"] + _f32(c["inc_env"] * a)))
        if ph >= 1.0:
            ph = _f32(ph - 1.0)
        if ph < 0.0:
            ph = _f32(ph + 1.0)
        v.phase = ph
        wet = knee(y, 0.6, 0.6)
        out.append(_f32(s + _f32(c["mix"] * _f32(wet - s))))
    return out

"""PING as the DSP will compute it: the contract `machine5_live.asm` is held to, bit for bit.

`ping/model.py` is the sound, chosen by ear (`docs/ping.md`). This is the same
design written in float32, using only operations the SHARC code can do in the
instruction forms Waverider's loop already uses: add, subtract, multiply, min/max,
compare, FLOAT/TRUNC, shifts, table reads. No division, no tan, no exp, no tanh:

- **reciprocal**: an integer seed from the float's bits (`0x7ef311c7 - bits`), then three
  Newton steps `r = r (2 - x r)`;
- **tan, the ring's damping per cutoff, the strike's gain, the envelope's rates**: tables,
  read with linear interpolation where the input is continuous;
- **saturation**: polynomial knees, exactly linear below their knee.

Every function rounds to float32 after each operation, in the order the DSP code
performs them (`_f32`). The tables are built here in float64 and stored as float32,
and the DSP reads the same bytes (`tables_bytes`).

**Where it runs.** Inside Waverider's per-block loop, for every track whose frame
filter type is 6 (`FILTER_TYPE`), whatever its machine. The stock unpack maps type 6
to DSP filter 0, "no filter" (`docs/ping.md`, measured), so the per-track chain skips
its filter stage, and PING runs on the track buffer after the machine render and before
that chain's fixed gain and base/width filter.

**Controls**, from the stock filter fields the unpack writes into the track record
(Multimode's page, relabelled), each a float:

| record | stock | PING |
|---|---|---|
| `+0x1c8` | TYPE (0..1) | the core: SVF, LADR, VCFQ, LPG (quarters) |
| `+0x1cc` | FREQ (0..1) | cutoff, x 128 = a note number |
| `+0x1d0` | RESO (0..1) | ring time, 1 ms .. 2 s |
| `+0x1ec` | env delay (0..1) | DRIVE |
| `+0x1f0` | env attack (0..1) | ATK, 0.1 ms .. 400 ms |
| `+0x1f4` | env decay (0..1) | DEC, 2 ms .. 10 s |
| `+0x1f8` | env sustain (0..1) | CURVE, log .. lin .. exp |
| `+0x1fc` | env release (0..1) | STRIKE |
| `+0x204` | env depth (0..1, 0.5 = 0) | ENV, +-6 octaves on the cutoff |
| `+0x208` | key tracking (0..1) | how far the cutoff follows the note from C4 |
"""

from __future__ import annotations

import math
import struct

RATE = 48000.0
BLOCK = 32
FILTER_TYPE = 6
TYPES = ("SVF", "LADR", "VCFQ", "LPG")

# record offsets of the stock filter fields (dnfw.waverider.frame.RECORD_FIELDS)
R_TYPE, R_FREQ, R_RES = 0x1C8, 0x1CC, 0x1D0
R_DRIVE, R_ATK, R_DEC, R_CURVE, R_STRIKE = 0x1EC, 0x1F0, 0x1F4, 0x1F8, 0x1FC
R_DEPTH, R_KEYT = 0x204, 0x208

# -- float32 ------------------------------------------------------------------------------


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _bits(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


def _float(b: int) -> float:
    return struct.unpack("<f", struct.pack("<I", b & 0xFFFFFFFF))[0]


def recip(x: float) -> float:
    """1/x for x >= 1 (every denominator here is), to float32 precision: the integer
    seed, then three Newton steps in the DSP's order."""
    r = _float(0x7EF311C7 - _bits(x))
    for _ in range(3):
        r = _f32(r * _f32(2.0 - _f32(x * r)))
    return r


def trunc(x: float) -> int:
    return int(math.trunc(x))


# -- tables -------------------------------------------------------------------------------

PITCH_TOP = 135                      # note numbers 0..135 (8.2 Hz .. 19.9 kHz)
SHAPE_N = 256                        # envelope shape tables: 257 points over 0..1
CTRL_N = 128                         # control tables, indexed by trunc(value * 127)


def note_hz(p: float) -> float:
    return 440.0 * 2.0 ** ((p - 69.0) / 12.0)


def _fc(p: float) -> float:
    return min(max(note_hz(p), 10.0), RATE * 0.45)


def table_g() -> list[float]:
    """g = tan(pi fc / fs) per note number 0..PITCH_TOP+1."""
    return [_f32(math.tan(math.pi * _fc(p) / RATE)) for p in range(PITCH_TOP + 2)]


def table_w() -> list[float]:
    """2 / (2 pi fc): the damping k for a ring time constant tau is W / tau."""
    return [_f32(2.0 / (2.0 * math.pi * _fc(p))) for p in range(PITCH_TOP + 2)]


def table_hit() -> list[float]:
    """The strike's gain for SVF and VCFQ, per note number: a struck SVF rings in
    proportion to g, so the click is scaled by 1/g (capped), as in ping/model.py."""
    return [_f32(min(12.0, 0.043 / math.tan(math.pi * _fc(p) / RATE))) for p in range(PITCH_TOP + 2)]


def table_inv_tau() -> list[float]:
    """RES (0..1, x 127) -> 1 / tau, tau = 1 ms .. 2 s exponential."""
    return [_f32(1.0 / (0.001 * 2000.0 ** (k / 127.0))) for k in range(CTRL_N)]


def _ms_inc(ms: float) -> float:
    return _f32(1.0 / (ms * RATE / 1000.0))


def table_atk() -> list[float]:
    """ATK -> the envelope phase's step per sample: 0.1 ms .. 400 ms."""
    return [_ms_inc(0.1 * 4000.0 ** (k / 127.0)) for k in range(CTRL_N)]


def table_dec() -> list[float]:
    """DEC -> the step per sample: 2 ms .. 10 s."""
    return [_ms_inc(2.0 * 5000.0 ** (k / 127.0)) for k in range(CTRL_N)]


def table_vac() -> list[float]:
    """The vactrol's fall, as a step per sample for each 1/64 of its level, before the
    DEC scale: 1 / (0.35 + 1.3 (1 - v)) -- slower as it darkens."""
    return [_f32(1.0 / (0.35 + 1.3 * (1.0 - v / 64.0))) for v in range(65)]


def _shape(x: float, c: float) -> float:
    k = 5.0 * c
    return (math.exp(k * x) - 1.0) / (math.exp(k) - 1.0)


def table_exp() -> list[float]:
    """The envelope's exponential shape over 0..1 (slow start, steep end)."""
    return [_f32(_shape(k / SHAPE_N, 1.0)) for k in range(SHAPE_N + 1)]


def table_log() -> list[float]:
    """Its mirror (steep start)."""
    return [_f32(1.0 - _shape(1.0 - k / SHAPE_N, 1.0)) for k in range(SHAPE_N + 1)]


STRIKE_N = 15


def table_strike() -> list[float]:
    """The 0.3 ms raised-cosine click."""
    return [_f32(0.5 - 0.5 * math.cos(2 * math.pi * k / (STRIKE_N - 1))) for k in range(STRIKE_N)]


TABLES = (("g", table_g), ("w", table_w), ("hit", table_hit), ("inv_tau", table_inv_tau),
          ("atk", table_atk), ("dec", table_dec), ("vac", table_vac), ("exp", table_exp),
          ("log", table_log), ("strike", table_strike))


def tables() -> dict[str, list[float]]:
    return {name: build() for name, build in TABLES}


def tables_bytes() -> tuple[bytes, dict[str, int]]:
    """Every table, float32 little-endian, back to back; -> (bytes, {name: byte offset})."""
    out, at = b"", {}
    for name, build in TABLES:
        at[name] = len(out)
        out += struct.pack("<%df" % len(build()), *build())
    return out, at


# -- reading ------------------------------------------------------------------------------


def interp(t: list[float], x: float) -> float:
    """t at fractional index x (clamped to the table): t[i] + f (t[i+1] - t[i])."""
    top = len(t) - 2
    x = min(max(x, 0.0), float(top))
    i = trunc(x)
    f = _f32(x - _f32(float(i)))
    return _f32(t[i] + _f32(f * _f32(t[i + 1] - t[i])))


def at127(t: list[float], v: float) -> float:
    """t[trunc(v * 127)], v clamped to 0..1."""
    v = min(max(v, 0.0), 1.0)
    return t[trunc(_f32(v * 127.0))]


# -- saturation ---------------------------------------------------------------------------

def knee(x: float, k: float, room: float) -> float:
    """Exactly x while |x| <= k; above it, o = min(|x| - k, room) bends as
    o - o^2 / (2 room), reaching k + room / 2 with slope 0."""
    a = abs(x)
    if a <= k:
        return x
    o = min(_f32(a - k), room)
    y = _f32(k + _f32(o - _f32(_f32(o * o) * _f32(0.5 / room))))
    return y if x > 0 else -y


def soft_loop(x: float) -> float:
    """The SVF band state's limiter: linear to 1.0, then to 1.6."""
    return knee(x, 1.0, 1.2)


def ceiling(x: float) -> float:
    """The output's: linear to 0.6, then to 0.9 at most."""
    return knee(x, 0.6, 0.6)


def cubic(x: float) -> float:
    """The ladder's loop saturation: x - 4x^3/27 on |x| <= 1.5 (slope 0 at 1.5), +-1
    beyond. Its gentle compression everywhere is the 4-pole's thickness."""
    x = min(max(x, -1.5), 1.5)
    return _f32(x - _f32(_f32(_f32(x * x) * x) * _f32(4.0 / 27.0)))


# -- the voice ----------------------------------------------------------------------------

class Voice:
    """One track's PING state, as the DSP holds it (zeroed at boot)."""

    def __init__(self):
        self.ic1 = self.ic2 = 0.0
        self.s = [0.0, 0.0, 0.0, 0.0]
        self.stage = 2                      # 0 attack, 1 decay, 2 idle
        self.x = 0.0                        # the envelope phase in its stage
        self.vac = 0.0
        self.hit = STRIKE_N                 # samples into the strike (STRIKE_N = none)


def controls(rec: dict[int, float], note: float, T: dict) -> dict:
    """The block's settings from the record's floats and the note: everything that is
    constant across a block."""
    kind = min(3, trunc(_f32(min(max(rec[R_TYPE], 0.0), 1.0) * 4.0)))
    keyt = min(max(rec[R_KEYT], 0.0), 1.0)
    base = _f32(_f32(rec[R_FREQ] * 128.0) + _f32(keyt * _f32(note - 60.0)))
    curve = _f32(_f32(min(max(rec[R_CURVE], 0.0), 1.0) * 2.0) - 1.0)
    return {
        "kind": kind, "base": base,
        "env": _f32(_f32(rec[R_DEPTH] - 0.5) * 144.0),       # +-72 semitones
        "inv_tau": at127(T["inv_tau"], rec[R_RES]),
        "res": min(max(rec[R_RES], 0.0), 1.0),
        "drive": _f32(0.4 + _f32(1.6 * min(max(rec[R_DRIVE], 0.0), 1.0))),
        "atk": at127(T["atk"], rec[R_ATK]),
        "dec": at127(T["dec"], rec[R_DEC]),
        "curve": curve,
        "strike": min(max(rec[R_STRIKE], 0.0), 1.0),
        "hit": interp(T["hit"], base) if kind in (0, 2) else 2.5,     # ping/model.py's hit_gain
    }


def shape(x: float, c: float, T: dict) -> float:
    """The envelope's shape at x (0..1): x + c (exp(x) - x) for c >= 0, else
    x + |c| (log(x) - x), the tables read at x * 256."""
    p = _f32(x * float(SHAPE_N))
    if c >= 0.0:
        return _f32(x + _f32(c * _f32(interp(T["exp"], p) - x)))
    return _f32(x - _f32(c * _f32(interp(T["log"], p) - x)))


LPG_PULSE_INC = 1.0 / (4.0 * 48.0)  # the LPG's trigger: 4 ms, then the vactrol's own fall


def envelope(v: Voice, c: dict, T: dict) -> float:
    if v.stage == 0:
        a = shape(v.x, -1.0 if c["kind"] == 3 else c["curve"], T)
        v.x = _f32(v.x + c["atk"])
        if v.x >= 1.0:
            v.stage, v.x = 1, 0.0
        return a
    if v.stage == 1:
        lpg = c["kind"] == 3
        a = shape(_f32(1.0 - v.x), -1.0 if lpg else c["curve"], T)
        v.x = _f32(v.x + (_f32(LPG_PULSE_INC) if lpg else c["dec"]))
        if v.x >= 1.0:
            v.stage, v.x = 2, 0.0
        return a
    return 0.0


def svf(v: Voice, x: float, g: float, k: float) -> tuple[float, float]:
    """One trapezoidal SVF step: -> (band, low)."""
    a1 = recip(_f32(1.0 + _f32(g * _f32(g + k))))
    a2 = _f32(g * a1)
    a3 = _f32(g * a2)
    v3 = _f32(x - v.ic2)
    v1 = _f32(_f32(a1 * v.ic1) + _f32(a2 * v3))
    v2 = _f32(_f32(v.ic2 + _f32(a2 * v.ic1)) + _f32(a3 * v3))
    v.ic1 = soft_loop(_f32(_f32(2.0 * v1) - v.ic1))
    v.ic2 = _f32(_f32(2.0 * v2) - v.ic2)
    return v1, v2


def ladder(v: Voice, x: float, g: float, res: float) -> float:
    G = _f32(g * recip(_f32(1.0 + g)))
    d = recip(_f32(1.0 + g))
    k = _f32(4.1 * res)
    G2 = _f32(G * G)
    G3 = _f32(G2 * G)
    G4 = _f32(G3 * G)
    s1, s2, s3, s4 = (_f32(s * d) for s in v.s)
    sigma = _f32(_f32(_f32(_f32(G3 * s1) + _f32(G2 * s2)) + _f32(G * s3)) + s4)
    y4 = _f32(_f32(_f32(G4 * x) + sigma) * recip(_f32(1.0 + _f32(k * G4))))
    u = cubic(_f32(x - _f32(k * y4)))
    for i in range(4):
        w = _f32(_f32(u - v.s[i]) * G)
        y = _f32(w + v.s[i])
        v.s[i] = _f32(y + w)
        u = y
    return _f32(u * _f32(1.0 + _f32(0.6 * k)))


def block(v: Voice, buf: list[float], rec: dict[int, float], note: float, trig: bool,
          T: dict | None = None) -> list[float]:
    """One 32-sample block of a PING track, in place of the stock filter: BUF (the
    machine's output) -> the filtered block."""
    T = T or tables()
    c = controls(rec, note, T)
    if trig:
        v.stage, v.x, v.hit = 0, 0.0, 0
    late = 120 if c["kind"] == 3 else 0          # the LPG's click lands as it opens (2.5 ms)
    out = []
    for s in buf:
        x = _f32(s * c["drive"])
        h = v.hit - late
        if 0 <= h < STRIKE_N:
            x = _f32(x + _f32(_f32(c["strike"] * c["hit"]) * T["strike"][h]))
        if v.hit < STRIKE_N + late:
            v.hit += 1
        a = envelope(v, c, T)
        if c["kind"] == 3:                                   # LPG
            led = a
            if led > v.vac:
                v.vac = _f32(v.vac + _f32(_f32(led - v.vac) * 0.026)) # ~0.8 ms rise
            else:
                step = _f32(c["dec"] * interp(T["vac"], _f32(v.vac * 64.0)))
                v.vac = _f32(v.vac + _f32(_f32(led - v.vac) * min(step, 1.0)))
            # the cutoff rises from 30 Hz (note 22.5) to its target as the vactrol opens:
            # the note number moves linearly, so the frequency moves exponentially
            p = _f32(22.5 + _f32(_f32(_f32(c["base"] + c["env"]) - 22.5) * v.vac))
            g = interp(T["g"], p)
            k = max(_f32(interp(T["w"], p) * at127(T["inv_tau"], _f32(0.6 * c["res"]))), 0.05)
            _, low = svf(v, x, g, min(k, 2.0))
            # the level, about vactrol ** 1.4: v (0.6 + 0.4 v) agrees at 0, 0.5 and 1
            y = _f32(low * _f32(v.vac * _f32(0.6 + _f32(0.4 * v.vac))))
        else:
            p = _f32(c["base"] + _f32(c["env"] * a))
            g = interp(T["g"], p)
            if c["kind"] == 1:                               # LADR
                y = _f32(ladder(v, x, g, c["res"]) * a)
            else:
                k = _f32(interp(T["w"], p) * c["inv_tau"])
                if c["kind"] == 2 and c["res"] >= 0.97:      # VCFQ past its edge
                    k = _f32(-0.004 * _f32(_f32(c["res"] - 0.97) * _f32(1.0 / 0.03)))
                else:
                    k = min(max(k, 0.0004), 2.0)
                band, low = svf(v, x, g, k)
                y = _f32((band if c["kind"] == 2 else low) * a)
        out.append(ceiling(y))
    return out

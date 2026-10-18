"""RESONATOR as the DSP computes it: the contract `rings.asm` is held to, bit for bit.

`rings/model.py` is the sound (`docs/rings.md`), chosen by ear. This is its MODAL model
in float32, in the operations and the order the SHARC code performs them (the rules of
`dnfw.ping.live`: add, subtract, multiply, min/max, compare, FLOAT/TRUNC, shifts, AND,
XOR, table reads; no division, no exp, no sin). Machine type 6, every voice slot whose
record says so, after Waverider's loop and before PING / SHFT (so a RESONATOR track can
go through either).

**Controls**, each from the frame copy (`0x25c48c + 218 + 2 (p - 25) + 146 t`), on
WaveTone records whose range and default fit (the page is our own, `docs/rings.md`):

| control | record | slot p | range, default | here |
|---|---|---|---|---|
| TUNE | TUN1 | 25 | 0x400..0x7c00, 0x4000 | word / 256 - 64 semitones |
| LEV  | LEV1 | 30 | 0..0x7f00, 0x6400 | word / 0x6400: 1.0 at 100 |
| STRC | WAV1 | 26 | 0..0x7800, 0 | 0 harmonic, 0.5 a bar, 1 a plate |
| BRIT | WDTH | 45 | 0..0x7f00, 0x7f00 | 0.15 .. 0.95 |
| DAMP | HOLD | 41 | 0..0x7f00, 0x7f00 | T60 0.1 s .. 12 s |
| POS  | OFS1 | 28 | 0..0x6400, 0x3200 | where it is hit: 0.02 .. 0.5 |
| EXCT | PD1  | 29 | 0..0x6400, 0x3200 | MALLET <- blend -> NOISE |
| HIT  | LEV2 | 36 | 0..0x7f00, 0x6400 | the exciter's level, 1.0 at 100 |

**The voice.** A trigger restarts the exciter (a half-cosine mallet, its width from BRIT,
blended with a 12 ms noise burst through a one-pole low-pass; the noise is the
difference of two walks through W2's random table, no XOR, which the stock code never
uses) into 24 two-pole
resonators: mode n at the note x ratio_n(STRC), ringing `y = a1 y1 - a2 y2 + b0 x`
with a1 = 2R cos w, a2 = R^2, b0 = amp_n sin w (an impulse rings at about amp_n,
whatever the decay). R from the mode's T60 (high modes shorter, by BRIT), amp_n from
POS (sin(pi n POS)) and a tilt by BRIT. Modes at or above 19.9 kHz (note 135) stop.
The sum, x LEV, passes PING's output knee (0.9 at most).

**Cost.** At most MAX_VOICES voices render a block (slot order); a further type-6 voice
is silent and idle. A voice whose exciter is done and whose block peaked under IDLE
goes idle (its modes zeroed) and costs nothing until its next note.
"""

from __future__ import annotations

import math
import struct

from ..ping import live as P
from ..shft import live as S
from ..waverider import live as W

_f32, interp, knee, trunc = P._f32, P.interp, P.knee, P.trunc

RATE = 48000.0
BLOCK = 32
MACHINE_TYPE = 6
MODES = 24
MAX_VOICES = 4
TOP_NOTE = 135.0                        # 19.9 kHz
IDLE = 1.0e-5
OUT_GAIN = 0.035                        # the mode sum to the track: the default sound peaks near 0.6
NOISE_LEN = 576                         # 12 ms
NOISE_DECAY = math.exp(-1.0 / (NOISE_LEN / 4))
NOISE_J = 251
EXC_END = 1024                          # the exciter is silent from here (mallet <= 403)

# frame slots of the eight controls
P_TUN, P_LEV, P_STRC, P_BRIT, P_DAMP, P_POS, P_EXCT, P_HIT = 25, 30, 26, 45, 41, 28, 29, 36
CONTROL_SLOTS = (P_TUN, P_LEV, P_STRC, P_BRIT, P_DAMP, P_POS, P_EXCT, P_HIT)
DEFAULTS = {P_TUN: 0x4000, P_LEV: 0x6400, P_STRC: 0x0000, P_BRIT: 0x7F00, P_DAMP: 0x7F00,
            P_POS: 0x3200, P_EXCT: 0x3200, P_HIT: 0x6400}


def frame_offset(slot: int, t: int) -> int:
    return 218 + 2 * (slot - 25) + 146 * t


# -- tables -------------------------------------------------------------------------------

NOTE_N = 142                             # cos / sin of w at note 0..141
L_LO, L_STEPS = -20.0, 8.0               # R table: L = log2(-ln R) from -20 to 0, 8 a unit
L_N = 162


def _anchor_semitones():
    n = range(1, MODES + 1)
    harmonic = [float(k) for k in n]
    bar = [((2 * k + 1) / 3.0) ** 2 for k in n]
    bar = [b / bar[0] for b in bar]
    plate = [1.0, 1.594, 2.136, 2.296, 2.653, 2.918, 3.156, 3.501, 3.600, 4.060, 4.154,
             4.601, 4.832, 5.131, 5.412, 5.651, 5.937, 6.164, 6.415, 6.749, 6.976, 7.244,
             7.470, 7.735]
    return [[_f32(12.0 * math.log2(r)) for r in a] for a in (harmonic, bar, plate)]


def table_cos() -> list[float]:
    return [_f32(math.cos(2 * math.pi * P.note_hz(p) / RATE)) for p in range(NOTE_N)]


def table_sin() -> list[float]:
    return [_f32(math.sin(2 * math.pi * P.note_hz(p) / RATE)) for p in range(NOTE_N)]


def table_r() -> list[float]:
    return [_f32(math.exp(-(2.0 ** (L_LO + i / L_STEPS)))) for i in range(L_N)]


def table_anchors() -> list[float]:
    h, b, p = _anchor_semitones()
    return h + b + p                     # 3 x 24


TABLES = (("cosw", table_cos), ("sinw", table_sin), ("r", table_r), ("anchors", table_anchors))


def tables() -> dict[str, list[float]]:
    out = {name: build() for name, build in TABLES}
    out["sin"] = S.table_sin()           # SHFT's: 256 points a turn
    out["rnd"] = [_f32(x) for x in W.rnd_table()]    # W2's: 256 in [0, 1)
    return out


def tables_bytes() -> tuple[bytes, dict[str, int]]:
    out, at = b"", {}
    for name, build in TABLES:
        at[name] = len(out)
        out += struct.pack("<%df" % len(build()), *build())
    return out, at


# -- the voice -----------------------------------------------------------------------------

class Voice:
    """One slot's state; zero is rest (idle 0: nothing to render until a note)."""

    def __init__(self):
        self.y1 = [0.0] * MODES
        self.y2 = [0.0] * MODES
        self.active = 0
        self.exc = 0                     # samples since the hit (stops at EXC_END)
        self.nenv = 0.0                  # the noise burst's envelope
        self.nlp = 0.0                   # its low-pass
        self.ni = 0                      # the noise: two walks through W2's random table,
        self.nj = 0                      # 256 and 251 long, the second read from the top
                                         # (rnd[ni] - rnd[255 - nj]: a period of 64,256)


def _knob(word: int, inv: float) -> float:
    """FLOAT(word) * inv, clamped to 0..1 (the word is the frame's unsigned 16 bits)."""
    v = _f32(float(word & 0xFFFF) * _f32(inv))
    return min(max(v, 0.0), 1.0)


def controls(words: dict[int, int], note: float, T: dict) -> dict:
    note = S.note_ok(note)
    tun = _f32(_f32(float(words[P_TUN] & 0xFFFF) * _f32(1.0 / 256.0)) - 64.0)
    pitch = min(max(_f32(note + tun), 0.0), 127.0)
    st = _knob(words[P_STRC], 1.0 / 0x7800)
    b = _f32(_f32(0.15) + _f32(_f32(0.8) * _knob(words[P_BRIT], 1.0 / 0x7F00)))
    kd = _knob(words[P_DAMP], 1.0 / 0x7F00)
    l0 = _f32(_f32(math.log2(6.91 / 4800.0)) - _f32(kd * _f32(math.log2(120.0))))
    kexp = _f32(_f32(_f32(1.0 - b) * _f32(1.3)) + _f32(0.2))
    pos = _f32(_f32(0.02) + _f32(_f32(0.48) * _knob(words[P_POS], 1.0 / 0x6400)))
    mix = _knob(words[P_EXCT], 1.0 / 0x6400)
    hit = _f32(float(words[P_HIT] & 0xFFFF) * _f32(1.0 / 0x6400))
    lev = _f32(float(words[P_LEV] & 0xFFFF) * _f32(1.0 / 0x6400))
    if st <= 0.5:
        frac, a0 = _f32(st * 2.0), 0
    else:
        frac, a0 = _f32(_f32(st * 2.0) - 1.0), MODES
    tilt_g = _f32(_f32(0.6) + _f32(_f32(0.4) * b))
    d = _f32(1.0 - b)
    width = _f32(_f32(0.0004 * RATE) + _f32(_f32(0.008 * RATE) * _f32(d * d)))
    rw = P.recip(width)
    return {"pitch": pitch, "frac": frac, "a0": a0, "l0": l0, "kexp": kexp, "pos": pos,
            "mix": mix, "hit": hit, "lev": lev, "tilt_g": tilt_g,
            "minc": _f32(128.0 * rw), "mnorm": min(_f32(24.0 * rw), 1.0),
            "nlp_a": min(_f32(_f32(_f32(_f32(b * b) * 12000.0) + 300.0) * _f32(2 * math.pi / RATE)), 1.0)}


def coefs(c: dict, T: dict) -> list[tuple[float, float, float]]:
    """(a1, a2, b0) of each mode that sounds, low to high."""
    out = []
    an = T["anchors"]
    tilt = 1.0
    for n in range(MODES):
        lo, hi = an[c["a0"] + n], an[c["a0"] + MODES + n]
        semi = _f32(lo + _f32(c["frac"] * _f32(hi - lo)))
        q = _f32(c["pitch"] + semi)
        if q >= TOP_NOTE:
            break
        cw, sw = interp(T["cosw"], q), interp(T["sinw"], q)
        lr = _f32(semi * _f32(1.0 / 12.0))
        L = _f32(c["l0"] + _f32(c["kexp"] * lr))
        R = interp(T["r"], _f32(_f32(L - L_LO) * L_STEPS))
        x = _f32(_f32(float(n + 1) * c["pos"]) * 128.0)
        xi = trunc(x)
        idx = _f32(float(xi & 255) + _f32(x - float(xi)))
        amp = _f32(interp(T["sin"], idx) * tilt)
        out.append((_f32(2.0 * _f32(R * cw)), _f32(R * R), _f32(amp * sw)))
        tilt = _f32(tilt * c["tilt_g"])
    return out


def exciter(v: Voice, c: dict, T: dict) -> list[float]:
    """The block's 32 exciter samples (zeros once the hit is done)."""
    out = []
    for _ in range(BLOCK):
        if v.exc >= EXC_END:
            out.append(0.0)
            continue
        ph = _f32(float(v.exc) * c["minc"])
        mal = _f32(interp(T["sin"], ph) * c["mnorm"]) if ph < 128.0 else 0.0
        nz = _f32(T["rnd"][v.ni] - T["rnd"][255 - v.nj])  # -1..1, triangular
        v.ni = (v.ni + 1) & 255
        v.nj = v.nj + 1 if v.nj + 1 < NOISE_J else 0
        if v.exc < NOISE_LEN:
            nz = _f32(nz * v.nenv)
            v.nenv = _f32(v.nenv * _f32(NOISE_DECAY))
        else:
            nz = 0.0
        v.nlp = _f32(v.nlp + _f32(c["nlp_a"] * _f32(nz - v.nlp)))
        x = _f32(_f32(_f32(1.0 - c["mix"]) * mal) + _f32(c["mix"] * _f32(0.5 * v.nlp)))
        out.append(_f32(x * c["hit"]))
        v.exc += 1
    return out


def block(v: Voice, rendered: int, words: dict[int, int], note: float, trig: bool,
          T: dict | None = None) -> tuple[list[float], bool]:
    """One block of a type-6 slot. RENDERED: how many type-6 voices this block has
    rendered before this one. -> (the 32 samples, whether this voice rendered)."""
    T = T or tables()
    if rendered >= MAX_VOICES:
        v.__init__()
        return [0.0] * BLOCK, False
    if trig:
        v.active, v.exc, v.nenv, v.nlp = 1, 0, 1.0, 0.0
    if not v.active:
        return [0.0] * BLOCK, False
    c = controls(words, note, T)
    x = exciter(v, c, T)
    acc = [0.0] * BLOCK
    for n, (a1, a2, b0) in enumerate(coefs(c, T)):
        y1, y2 = v.y1[n], v.y2[n]
        for k in range(BLOCK):
            y = _f32(_f32(_f32(a1 * y1) - _f32(a2 * y2)) + _f32(b0 * x[k]))
            y2, y1 = y1, y
            acc[k] = _f32(acc[k] + y)
        v.y1[n], v.y2[n] = y1, y2
    g = _f32(c["lev"] * _f32(OUT_GAIN))
    out = [knee(_f32(a * g), 0.6, 0.6) for a in acc]
    peak = max(abs(a) for a in acc)
    if v.exc >= EXC_END and peak < IDLE:
        v.__init__()
    return out, True

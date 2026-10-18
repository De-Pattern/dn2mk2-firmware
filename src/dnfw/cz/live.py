"""CZ as the DSP computes it: the contract `cz.asm` is held to, bit for bit.

`cz/model.py` is the sound (`docs/cz.md`). This is a CZ voice in float32, in the
operations and the order the SHARC code performs them (the rules of `dnfw.ping.live`).
Machine type 7; every voice slot whose record says so.

**The voice.** Two lines read one phase-distortion wave pair (the 33 CZ wave choices:
eight waves and their pairs, the pair alternating cycle by cycle), through one 8-step
DCW envelope (rate and level 0..99 a step, a sustain step). SEL: line 1, line 2,
1+1' (line 2 detuned) or 1+2' (line 2 detuned, octave-shifted and ring- or
noise-modulated). The DCA is the DN2's own AMP envelope; the machine's output is
0.5 a line.

**The envelope and the gate.** A trigger restarts DCW at 0 from step 1. It runs step
by step to the sustain step and holds there until the next trigger; with no sustain
step it runs all eight and stays at step 8's level. (The CZ goes on past sustain at
note-off; the frame's note-off is not yet located, `docs/cz.md`.)

**Controls**, frame words (`0x25c48c + 218 + 2 (p - 25) + 146 t`) on WaveTone's records:

| control | record | slot | range | here |
|---|---|---|---|---|
| WAVE | WAV1 | 26 | 0..0x7800 | 33 choices |
| SEL  | MOD  | 37 | 0..0x300 | 1, 2, 1+1', 1+2' |
| DET  | TUN2 | 31 | 0x400..0x7c00, 0x4000 = 0 | line 2 detune, +-1 semitone |
| OCT  | TYPE | 46 | 0..0x200 | line 2 octave: 0, +1, -1 |
| MOD  | RSET | 39 | 0..0x200 | line 2: ring, off, noise |
| DCW  | LEV1 | 30 | 0..0x7f00 | the envelope's depth |
| KF   | TBL1 | 27 | 0..0x100 | key follow on DCW: off, on |
| SUS  | WAV2 | 32 | 0..0x7800 | sustain step 1..8, or none |
| R1-R4| PD1, OFS1, PD2, OFS2 | 29, 28, 35, 34 | 0..0x6400 | rates 0..99 |
| L1-L4| LEV2, DRIF, ATK, HOLD | 36, 38, 40, 41 | 0..0x7f00 | levels 0..99 |
| R5-R8| DEC, NLEV, BASE, WDTH | 42, 43, 44, 45 | 0..0x7f00 | rates 0..99 |
| L5-L8| CHAR, MAST, FINE, TUN1 | 47, 48, 49, 25 | 0..0x7f00 (TUN1 0x400..0x7c00) | levels 0..99 |
"""

from __future__ import annotations

import math
import struct

from ..ping import live as P
from ..shft import live as S
from ..waverider import live as W

_f32, interp, trunc, recip = P._f32, P.interp, P.trunc, P.recip

RATE = 48000.0
BLOCK = 32
MACHINE_TYPE = 7
WAVES = ("SAW", "SQUARE", "PULSE", "DOUBLE", "SAWPULSE", "RES1", "RES2", "RES3")
NONRES = 5
# the 33 choices: the eight waves, every ordered pair of two different non-resonant
# waves (20), and five non-resonant + resonant pairs
COMBOS = ([(w, w) for w in range(8)]
          + [(a, b) for a in range(NONRES) for b in range(NONRES) if a != b]
          + [(0, 5), (1, 6), (2, 7), (3, 5), (4, 6)])
SELECTS = ("1", "2", "1+1'", "1+2'")
OCTAVES = (0, 1, -1)
MODS = ("RING", "OFF", "NOISE")

P_WAVE, P_SEL, P_DET, P_OCT, P_MOD, P_DCW, P_KF, P_SUS = 26, 37, 31, 46, 39, 30, 27, 32
P_RATES = (29, 28, 35, 34, 42, 43, 44, 45)
P_LEVELS = (36, 38, 40, 41, 47, 48, 49, 25)
CONTROL_SLOTS = (P_WAVE, P_SEL, P_DET, P_OCT, P_MOD, P_DCW, P_KF, P_SUS) + P_RATES + P_LEVELS
# each rate's and level's record range (lo, span): the knob's 0..99
RATE_RANGE = {29: (0, 0x6400), 28: (0, 0x6400), 35: (0, 0x6400), 34: (0, 0x6400),
              42: (0, 0x7F00), 43: (0, 0x7F00), 44: (0, 0x7F00), 45: (0, 0x7F00)}
LEVEL_RANGE = {36: (0, 0x7F00), 38: (0, 0x7F00), 40: (0, 0x7F00), 41: (0, 0x7F00),
               47: (0, 0x7F00), 48: (0, 0x7F00), 49: (0, 0x7F00), 25: (0x400, 0x7800)}
DEFAULTS = {26: 0, 37: 0, 31: 0x4000, 46: 0, 39: 0x100, 30: 0x6400, 27: 0, 32: 0,
            29: 0x3200, 28: 0x3200, 35: 0x3200, 34: 0x3200, 36: 0x6400, 38: 0, 40: 0,
            41: 0x7F00, 42: 0x7F00, 43: 0, 44: 0, 45: 0x7F00, 47: 0, 48: 0x4000, 49: 0x4000,
            25: 0x4000}
OUT_GAIN = 0.5
MAX_VOICES = 6                           # slots rendered a block; the rest are silent
NOISE_DEPTH = _f32(0.8)                  # line 2's pitch wander on NOISE
NOISE_J = 251


def frame_offset(slot: int, t: int) -> int:
    return 218 + 2 * (slot - 25) + 146 * t


# -- tables ---------------------------------------------------------------------------------

INC_N = 137                              # note 0..136 -> cycles a sample


def table_inc() -> list[float]:
    return [_f32(P.note_hz(p) / RATE) for p in range(INC_N)]


def rate_time(rate: float) -> float:
    """seconds to cross the whole level range at CZ rate 0..99 (99 fastest)"""
    return 0.0015 * 1.105 ** (99 - rate)


def table_rinc() -> list[float]:
    """rate 0..99 -> the level's step a sample (levels run 0..1)"""
    return [_f32(1.0 / (rate_time(r) * RATE)) for r in range(100)]


def table_combos() -> list[int]:
    return [x for a, b in COMBOS for x in (a, b)]


TABLES = (("inc", table_inc), ("rinc", table_rinc))


def tables() -> dict:
    out = {name: build() for name, build in TABLES}
    out["combos"] = table_combos()
    out["sin"] = S.table_sin()
    out["rnd"] = [_f32(x) for x in W.rnd_table()]
    return out


def table_params() -> list[tuple[int, float, float]]:
    """the eight rates' and eight levels' (frame offset, lo, 1 / span), the asm's loop"""
    out = []
    for slots, ranges in ((P_RATES, RATE_RANGE), (P_LEVELS, LEVEL_RANGE)):
        for p in slots:
            lo, span = ranges[p]
            out.append((218 + 2 * (p - 25), float(lo), _f32(1.0 / span)))
    return out


def tables_bytes() -> tuple[bytes, dict[str, int]]:
    """the float tables, the combos as 32-bit ints, then the params (int, float, float)"""
    out, at = b"", {}
    for name, build in TABLES:
        at[name] = len(out)
        out += struct.pack("<%df" % len(build()), *build())
    at["combos"] = len(out)
    out += struct.pack("<%di" % len(table_combos()), *table_combos())
    at["params"] = len(out)
    for off, lo, inv in table_params():
        out += struct.pack("<iff", off, lo, inv)
    return out, at


# -- the voice -------------------------------------------------------------------------------

class Voice:
    """One slot's state; zero is rest. ph: the lines' phases 0..1; par: which wave of the
    pair each line is on; step 0..7 and v: the DCW envelope; ni / nj: the noise walks;
    active: triggered since rest."""

    def __init__(self):
        self.ph1 = self.ph2 = 0.0
        self.par1 = self.par2 = 0
        self.step = 0
        self.v = 0.0
        self.ni = self.nj = 0
        self.active = 0


def _word_knob(word: int, lo: int, span: int) -> float:
    """the record's value as 0..1"""
    x = _f32(_f32(float(word & 0xFFFF) - float(lo)) * _f32(1.0 / span))
    return min(max(x, 0.0), 1.0)


def _enum(word: int, count: int) -> int:
    """a 0..(count-1) record (value << 8), clamped"""
    return min((word & 0xFFFF) >> 8, count - 1)


def controls(words: dict, note: float, T: dict) -> dict:
    note = S.note_ok(note)
    wave = min(trunc(_f32(_f32(float(words[P_WAVE] & 0xFFFF) * _f32(1.0 / 0x7800)) * 33.0)), 32)
    det = _f32(_f32(float(words[P_DET] & 0xFFFF) - 16384.0) * _f32(1.0 / 0x3C00))
    det = min(max(det, -1.0), 1.0)
    sel, octi, mod = _enum(words[P_SEL], 4), _enum(words[P_OCT], 3), _enum(words[P_MOD], 3)
    sus = min(trunc(_f32(_f32(float(words[P_SUS] & 0xFFFF) * _f32(1.0 / 0x7800)) * 9.0)), 8)
    depth = _f32(float(words[P_DCW] & 0xFFFF) * _f32(1.0 / 0x7F00))
    kfm = 1.0
    if _enum(words[P_KF], 2):
        x = min(max(_f32(_f32(note - 36.0) * _f32(1.0 / 96.0)), 0.0), 1.0)
        kfm = _f32(1.0 - _f32(_f32(0.6) * x))
    rates, levels = [], []
    for k in range(8):
        lo, span = RATE_RANGE[P_RATES[k]]
        r = trunc(_f32(_word_knob(words[P_RATES[k]], lo, span) * 99.0))
        rates.append(T["rinc"][r])
        lo, span = LEVEL_RANGE[P_LEVELS[k]]
        levels.append(_f32(_f32(trunc(_f32(_word_knob(words[P_LEVELS[k]], lo, span) * 99.0)))
                           * _f32(1.0 / 99.0)))
    p1 = min(max(note, 0.0), 135.0)
    p2 = min(max(_f32(_f32(note + float(12 * OCTAVES[octi])) + det), 0.0), 135.0)
    return {"a": T["combos"][2 * wave], "b": T["combos"][2 * wave + 1], "sel": sel, "mod": mod,
            "sus": sus, "dcw": _f32(depth * kfm), "rates": rates, "levels": levels,
            "inc1": interp(T["inc"], p1), "inc2": interp(T["inc"], p2)}


def rcp(x: float) -> float:
    """1/x for 1/256 <= x <= 1: recip (x >= 1 only) on x scaled by 256, exactly"""
    return _f32(recip(_f32(x * 256.0)) * 256.0)


def _knee(x: float, d: float) -> float:
    """0..d -> 0..0.5, d..1 -> 0.5..1 (d >= 0.01)"""
    if x < d:
        return _f32(_f32(x * 0.5) * rcp(d))
    return _f32(0.5 + _f32(_f32(_f32(x - d) * 0.5) * rcp(_f32(1.0 - d))))


def _cos_turns(f: float, T: dict) -> float:
    """cos(2 pi f), f in 0..1.25, from the sine table: sin at f + 1/4"""
    return interp(T["sin"], _f32(_f32(f * 256.0) + 64.0))


def wave(w: int, ph: float, d: float, T: dict) -> float:
    """one sample of wave W at phase PH (0..1) and DCW D (0..1), -1..1"""
    if w == 0:                                                   # SAW
        f = _knee(ph, _f32(0.5 - _f32(_f32(0.49) * d)))
    elif w == 1:                                                 # SQUARE
        wd = _f32(0.5 - _f32(_f32(0.49) * d))
        h, base = (ph, 0.0) if ph < 0.5 else (_f32(ph - 0.5), 0.5)
        f = _f32(base + _f32(0.5 * min(_f32(h * rcp(wd)), 1.0)))
    elif w == 2:                                                 # PULSE
        wd = _f32(1.0 - _f32(_f32(0.95) * d))
        f = min(_f32(ph * rcp(wd)), 1.0)
    elif w == 3:                                                 # DOUBLE
        if ph < 0.5:
            f = _f32(ph * _f32(1.0 + d))
        else:
            f = _f32(_f32(_f32(0.5) * _f32(1.0 + d)) + _f32(_f32(ph - 0.5) * _f32(1.0 - d)))
    elif w == 4:                                                 # SAWPULSE
        g = _knee(min(_f32(ph * 2.0), 1.0), _f32(0.1)) if ph < 0.5 else 1.0
        f = _f32(_f32(_f32(1.0 - d) * ph) + _f32(d * g))
    else:                                                        # RES1..3
        k = _f32(1.0 + _f32(15.0 * d))
        x = _f32(k * ph)
        x = _f32(x - float(trunc(x)))
        r = _f32(0.5 * _f32(1.0 - _cos_turns(x, T)))
        if w == 5:
            win = _f32(1.0 - ph)
        elif w == 6:
            u = _f32(_f32(2.0 * ph) - 1.0)
            win = _f32(1.0 - (u if u >= 0.0 else _f32(0.0 - u)))
        else:
            win = min(_f32(2.0 * _f32(1.0 - ph)), 1.0)
        return _f32(_f32(_f32(2.0 * r) * win) - 1.0)
    return _f32(0.0 - _cos_turns(f, T))


def envelope(v: Voice, c: dict) -> float:
    """the DCW envelope's value this sample, 0..1"""
    target = c["levels"][v.step]
    rinc = c["rates"][v.step]
    if v.v < target:
        v.v = min(_f32(v.v + rinc), target)
    elif v.v > target:
        v.v = max(_f32(v.v - rinc), target)
    if v.v == target and v.step != c["sus"] and v.step < 7:
        v.step += 1
    return v.v


def _line(ph: float, par: int, c: dict, d: float, T: dict) -> float:
    return wave(c["b"] if par else c["a"], ph, d, T)


def _advance(ph: float, par: int, inc: float) -> tuple[float, int]:
    ph = _f32(ph + inc)
    if ph >= 1.0:
        ph = _f32(ph - 1.0)
        par ^= 1
    return ph, par


def block(v: Voice, rendered: int, words: dict, note: float, trig: bool,
          T: dict | None = None) -> tuple[list[float], bool]:
    """One 32-sample block of a type-7 slot. RENDERED: how many type-7 voices this block
    has rendered before this one (over MAX_VOICES: rest and silence). Silent until the
    slot's first trigger. -> (the 32 samples, whether this voice rendered)."""
    T = T or tables()
    if rendered >= MAX_VOICES:
        v.__init__()
        return [0.0] * BLOCK, False
    if trig:
        v.ph1 = v.ph2 = 0.0
        v.par1 = v.par2 = 0
        v.step, v.v = 0, 0.0
        v.active = 1
    if not v.active:
        return [0.0] * BLOCK, False
    c = controls(words, note, T)
    out = []
    for _ in range(BLOCK):
        e = envelope(v, c)
        d = min(_f32(e * c["dcw"]), 1.0)
        y1 = 0.0
        if c["sel"] != 1:                                        # line 1 sounds
            y1 = _line(v.ph1, v.par1, c, d, T)
        y = y1
        if c["sel"] != 0:                                        # line 2 sounds
            inc2 = c["inc2"]
            if c["sel"] == 3 and c["mod"] == 2:                  # noise: line 2's pitch
                nz = _f32(T["rnd"][v.ni] - T["rnd"][255 - v.nj])
                inc2 = _f32(inc2 + _f32(_f32(inc2 * NOISE_DEPTH) * nz))
                v.ni = (v.ni + 1) & 255
                v.nj = v.nj + 1 if v.nj + 1 < NOISE_J else 0
            y2 = _line(v.ph2, v.par2, c, d, T)
            if c["sel"] == 3 and c["mod"] == 0:                  # ring: line 2 x line 1
                y2 = _f32(y2 * y1)
            y = _f32(y1 + y2)
            v.ph2, v.par2 = _advance(v.ph2, v.par2, inc2)
        v.ph1, v.par1 = _advance(v.ph1, v.par1, c["inc1"])
        out.append(_f32(y * OUT_GAIN))
    return out, True

"""What Milestone 5's type-5 loop computes from a track's own state: the contract
`csrc/waverider/sharc/machine5_live.asm` is held to, bit for bit.

The loop reads three things the frame unpack `sw 0x1c2712` has already put in DSP
memory, measured by running that unpack (`scripts/sharc_waverider_m5.py`):

| what | where | form |
|---|---|---|
| SLOT, WaveTone's `TBL1` (param 27) | the frame copy `0x25c48c`, offset `222 + 146t` | 16-bit, the sound's value: 0x0000 or 0x0100 |
| POS, WaveTone's `WAV1` (param 26) | the frame copy, offset `220 + 146t` | 16-bit, the sound's value: 0..0x7800 |
| pitch | engine `+0x1387c + 4t` (`0x254b14 + 4t`) | float semitones, note + fine/256 |
| TUNE, WaveTone's `TUN1` (param 25, Milestone 6) | the frame copy, offset `218 + 146t` | 16-bit, the sound's value: word / 256 - 64 semitones |

The unpack writes a type-5 track's machine parameters nowhere else: its record's
machine window is left as it is (measured, the same for any parameter value), so
the loop reads the copy of the frame the unpack itself made.

and turns them into `reader_m5.asm`'s parameter block:

- **table**: the directory's entry for `TBL1 >> 8`; at or above the count plays 0;
- **pos**: `min(WAV1, 0x7800) << 5`, Q16 frames (0x7800 << 5 is frame 15);
- **inc**: from the note plus TUN1, through a 129-entry float32 table `T` of phase steps
  (`increment_table`): `k = trunc(n)`, `fr = n - k`, `inc = trunc(T[k] + fr *
  (T[k+1] - T[k]))`, every operation rounded to float32 in the loop's order;
- **phase**: carried in the block from one block to the next, from 0.

**The frame carries the sound's own values** (read on the instrument through the
USB probe, 2026-09-30, `tools/dn2probe_frame.py`): TUN1 `0x4000` at 0, `0x4100` at
+1, `0x4c00` at +12, `0x3400` at -12; WAV1 `0x7800` at the top; TBL1 `0x0100` at 1.
Until then this module, the loop and the gates read **half** the sound's value, as
frames from the ColdFire emulator had shown (FREQ 0x6117 -> 0x308c, WAV1 0x7800 ->
0x3c00, TBL1 0x0100 -> 0x0080). Those frames were taken while the values were still
gliding to their targets after the snapshot loaded (the same run shows slot 0 and
the level headers gliding with nothing touched), so "half" was a moment, not a
scale. On the instrument that put POS's last frame halfway up WAV1, kept TBL1 1 on
table 0, and read TUN1 0 as +64 semitones.

This module is pure: numbers in, numbers out.
"""

from __future__ import annotations

import math
import struct

from . import render

RATE = 48000.0
A4_NOTE, A4_HZ = 69, 440.0
NOTES = 129                      # T[0..128]; T[128] is only read with fr = 0
POS_MAX = 0x7800                 # WAV1's range in the frame: the sound's own
POS_SHIFT = 5                    # 0x7800 << 5 == 15 << 16
SLOT_SHIFT = 8                   # TBL1 1: 0x0100, in the sound and in the frame
TUN1_ZERO = 0x4000               # TUN1's frame word for 0 semitones: the sound's own


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def note_hz(note: float) -> float:
    return A4_HZ * 2.0 ** ((note - A4_NOTE) / 12.0)


def increment_table() -> list[float]:
    """T[k], k = 0..128: the u32 phase step for note k at 48 kHz, as float32."""
    return [_f32(note_hz(k) / RATE * 2.0 ** 32) for k in range(NOTES)]


def table_bytes() -> bytes:
    """The increment table as the DSP reads it: little-endian float32."""
    return struct.pack("<%df" % NOTES, *increment_table())


def trunc(x: float) -> int:
    """SHARC `Rn = TRUNC Fx` for the values the loop meets (0 <= x < 2^31)."""
    return int(math.trunc(x))


def increment(note: float, table: list[float] | None = None) -> int:
    """The loop's inc for a note cell value, float32 in the loop's order."""
    t = table or increment_table()
    n = _f32(note)
    n = min(n, 127.0)
    n = max(n, 0.0)
    k = trunc(n)
    fr = _f32(n - _f32(float(k)))
    d = _f32(t[k + 1] - t[k])
    e = _f32(fr * d)
    return trunc(_f32(t[k] + e)) & 0xFFFFFFFF


def tuned(note: float, tun1: int = TUN1_ZERO) -> float:
    """The note cell plus TUN1, as the loop forms it: a NaN, an infinity or a negative
    note is +0.0 first; then + (word / 128 - 64) semitones, float32; below 0 is 0.

    The scale was read on the instrument through the USB probe (0x4000 at 0, 0x4100
    at +1, 0x4c00 at +12, 0x3400 at -12): one semitone per coarse step and fine / 256
    of one, which the display shows as -5..+5 octaves."""
    n = _f32(note)
    if math.isnan(n) or math.isinf(n) or n < 0 or (n == 0 and math.copysign(1.0, n) < 0):
        n = 0.0
    t = _f32(_f32(float(tun1 & 0xFFFF) / 256.0) - 64.0)
    n = _f32(n + t)
    return 0.0 if n < 0 else n


def position(wav1: int) -> int:
    """The loop's Q16 frame position for the frame's 16-bit WAV1 word."""
    return min(wav1 & 0xFFFF, POS_MAX) << POS_SHIFT


def slot(drif: int, count: int) -> int:
    """W5: the directory slot the loop plays for the frame's 16-bit DRIF word (TBL on
    Waverider's page): lut[min(DRIF >> 8, 127)], the knob shared evenly between the
    tables (`dsp.slot_lut`); a slot at or above the count plays 0."""
    v = min((drif & 0xFFFF) >> SLOT_SHIFT, 127)
    s = min(count - 1, (v * count) >> 7)
    return s if s < count else 0


GLIDE_SHIFT = 5                   # s += (target - s) >> 5 per 32-sample block


def glide(target: int, s: int, trig: bool) -> int:
    """W5: one block of the loop's POS one-pole. A block whose frame triggers the voice
    (TRIG_NOTE bit t) sets s to the target; otherwise s moves 1/32 of the way, the
    shift arithmetic (toward -inf), as the DSP holds it."""
    if trig:
        return target
    return s + ((target - s) >> GLIDE_SHIFT)


# -- W2: the scanner, LEV, MPOS, MLEV ------------------------------------------------------
#
# Page 1's four lower controls drive a per-voice modulator of Waverider's own, the
# "scanner" (owner, 2026-10-11): RATE its speed, MOVE its shape, MPOS how far it sweeps
# POS (+-), MLEV how much it moves the level (+-). LEV is the oscillator's level.
# They sit on WaveTone records whose range fits (docs/w2-scanner.md):
#
# | control | record | slot | frame offset | range, default |
# |---|---|---|---|---|
# | LEV  | LEV1 241 | 30 | 228 + 146t | 0..0x7f00, 0x6400 (100 = unity) |
# | RATE | ATK  253 | 40 | 248 + 146t | 0..0x7f00, 0 |
# | MPOS | OFS1 246 | 28 | 224 + 146t | 0..0x6400, 0x3200 (centre = 0) |
# | MLEV | PD1  240 | 29 | 226 + 146t | 0..0x6400, 0x3200 (centre = 0) |
# | MOVE | NLEV 256 | 43 | 254 + 146t | 0..0x7f00, 0 (TRI) |
#
# With MPOS and MLEV at their centre and LEV at 100 the loop adds exactly 0 to POS and
# multiplies by exactly 1.0: a sound that never touches them plays bit for bit as W5.
#
# Everything here is float32 in the loop's order (`_f32` after each operation), the
# scanner's phase a u32 per voice advanced once a block, restarted by the voice's note.

SHAPES = ("TRI", "SAW", "RAMP", "SQR", "RND", "S&H", "ONE", "ENV")
UNIPOLAR = {2, 6, 7}             # RAMP, ONE, ENV: 0..1; the rest swing -1..+1
CENTRE = 0x3200                  # MPOS / MLEV: no modulation
DEPTH_SCALE = 1.0 / 0x3200       # (word - centre) -> -1..+1, as a float32 constant
POS_SPAN = float(15 << 16)       # Q16 frames: MPOS +-1 sweeps the whole table
RATE_MIN_HZ, RATE_MAX_HZ = 0.05, 30.0
BLOCK_HZ = 48000.0 / 32
LEV_UNITY = 100                  # LEV1's default, 0x6400
RND_COUNT = 256
DEFAULTS = {"lev1": 0x6400, "atk": 0, "ofs1": CENTRE, "pd1": CENTRE, "nlev": 0,
            "tun2": TUN1_ZERO, "wav2": 0, "base": 0, "char": 0, "ofs2": CENTRE, "pd2": CENTRE}


def rate_hz(v: int) -> float:
    """RATE 0..127 -> Hz, exponential from RATE_MIN_HZ to RATE_MAX_HZ."""
    return RATE_MIN_HZ * (RATE_MAX_HZ / RATE_MIN_HZ) ** (v / 127.0)


def rate_table() -> list[int]:
    """RATE (0..127) -> the scanner's u32 phase step per 32-sample block."""
    return [int(round(rate_hz(v) / BLOCK_HZ * 2.0 ** 32)) for v in range(128)]


def level_table() -> list[float]:
    """LEV (0..127) -> gain, float32: v / 100, so the default 100 is exactly 1.0."""
    return [_f32(v / LEV_UNITY) for v in range(128)]


def rnd_table() -> list[float]:
    """256 float32 values in [0, 1) the RND and S&H shapes step through: seeded, so the
    table is the same on every build."""
    import random
    rng = random.Random(0x5CA77E)
    return [_f32(rng.randrange(1 << 24) / float(1 << 24)) for _ in range(RND_COUNT)]


def shape_of(nlev: int) -> int:
    return ((min((nlev & 0xFFFF) >> 8, 127)) * 8) >> 7


class Scanner:
    """One voice's scanner state, as the DSP holds it (W2 state block, zeroed at boot):
    phase (u32), a and b (the random walk's two values), idx (its place in the table),
    done (a one-shot has finished), gp (the gain the last block ended on)."""

    def __init__(self, t: int = 0):
        self.phase, self.a, self.b, self.idx, self.done, self.gp = 0, 0.0, 0.0, 0, 0, 0.0

    def _next(self, rnd):
        self.a = self.b
        self.b = rnd[self.idx & (RND_COUNT - 1)]
        self.idx = (self.idx + 1) & 0xFFFFFFFF

    def block(self, p: dict, trig: bool, rates, rnd) -> tuple[float, float]:
        """-> (s, u) for this block: s the POS modulator (-1..1 bipolar, 0..1 unipolar),
        u its unipolar form, used for the level. Advances the phase afterwards."""
        k = shape_of(p["nlev"])
        if trig:                                   # a fresh start: both values new
            self.phase, self.done = 0, 0
            self._next(rnd)
            self._next(rnd)
        ph = _f32(float(self.phase >> 8) * 2.0 ** -24)       # FLOAT (phase >> 8) BY -24
        if k == 0:
            q = _f32(ph + 0.25)
            if q >= 1.0:
                q = _f32(q - 1.0)
            u = _f32(q + q) if q < 0.5 else _f32(2.0 - _f32(q + q))
        elif k == 1:
            u = ph
        elif k == 2:
            u = _f32(1.0 - ph)
        elif k == 3:
            u = 1.0 if ph < 0.5 else 0.0
        elif k == 4:
            u = _f32(self.a + _f32(_f32(self.b - self.a) * ph))
        elif k == 5:
            u = self.a
        elif k == 6:
            u = 1.0 if self.done else ph
        else:
            u = 0.0 if self.done else _f32(1.0 - ph)
        s = u if k in UNIPOLAR else _f32(_f32(u + u) - 1.0)
        nxt = (self.phase + rates[min((p["atk"] & 0xFFFF) >> 8, 127)]) & 0xFFFFFFFF
        if nxt < self.phase:                                  # a cycle ended
            if k in (6, 7):
                self.done = 1
            self._next(rnd)
        self.phase = nxt
        return s, u


def depth(word: int) -> float:
    """MPOS / MLEV word -> -1..+1 (float32): (word - 0x3200) * (1 / 0x3200)."""
    return _f32(float((word & 0xFFFF) - CENTRE) * _f32(DEPTH_SCALE))


def scanned(pos_q16: int, s: float, ofs1: int) -> int:
    """POS after the scanner: the glided Q16 position plus s x MPOS x the table's
    span, clamped to the table, truncated."""
    y = _f32(_f32(s * depth(ofs1)) * POS_SPAN)
    f = _f32(float(pos_q16) + y)
    f = min(max(f, 0.0), POS_SPAN)
    return trunc(f)


def gain(u: float, p: dict, levels) -> float:
    """LEV x the scanner's level: MLEV > 0 dips toward 0 as u falls, MLEV < 0 as it
    rises; MLEV 0 is exactly 1."""
    d = depth(p["pd1"])
    if d >= 0:
        a = _f32(1.0 - _f32(d * _f32(1.0 - u)))
    else:
        a = _f32(1.0 + _f32(d * u))
    return _f32(levels[min((p["lev1"] & 0xFFFF) >> 8, 127)] * a)


# -- W3: osc 2 (page 2) ---------------------------------------------------------------------
#
# A second reader on the same voice, mixed into osc 1's output. Its controls sit on
# WaveTone records whose default leaves it silent, so every sound saved before W3 plays
# bit for bit as it did (docs/w3-osc2.md):
#
# | control | record | slot | frame offset | range, default |
# |---|---|---|---|---|
# | DETN | TUN2 242 | 31 | 230 + 146t | 0x0400..0x7c00, 0x4000 (0 semitones from osc 1) |
# | LEV  | CHAR 260 | 47 | 262 + 146t | 0..0x7f00, 0: osc 2 off |
# | POS  | WAV2 243 | 32 | 232 + 146t | 0..0x7800, 0 |
# | TBL  | BASE 257 | 44 | 256 + 146t | 0..0x7f00, 0 |
# | MPOS | OFS2 250 | 34 | 236 + 146t | 0..0x6400, 0x3200 (centre = 0) |
# | MLEV | PD2  244 | 35 | 238 + 146t | 0..0x6400, 0x3200 (centre = 0) |
#
# Osc 2 shares osc 1's scanner (RATE, MOVE) with depths of its own. LEV 0 skips it
# outright -- no reader, no state change but its gain, which rests at 0 so turning it on
# ramps in from silence.


class Osc2:
    """One voice's osc 2 state: phase (u32), s (its POS glide, Q16), gp (the gain the
    last block ended on)."""

    def __init__(self):
        self.phase, self.s, self.gp = 0, 0, 0.0


def detuned(n1: float, tun2: int) -> float:
    """Osc 2's note: osc 1's (tuned, then at most 127) plus DETN, word / 256 - 64
    semitones, float32; the reader's increment() clamps it to 0..127."""
    d = _f32(_f32(float(tun2 & 0xFFFF) / 256.0) - 64.0)
    return _f32(min(n1, 127.0) + d)


def osc2_gain(u: float, p: dict, levels) -> float:
    """as gain(), on osc 2's own level (CHAR) and depth (PD2)."""
    return gain(u, {"pd1": p["pd2"], "lev1": p["char"]}, levels)


def osc2_on(p: dict) -> bool:
    return min((p["char"] & 0xFFFF) >> 8, 127) != 0


def ramp(samples: list[float], gp: float, g: float) -> list[float]:
    """The block's samples times a gain ramped from gp to g: step = (g - gp) / 32,
    accumulated before each sample, so the last sample is at gp + 32 steps."""
    step = _f32(_f32(g - gp) * 0.03125)
    out, x = [], gp
    for v in samples:
        x = _f32(x + step)
        out.append(_f32(v * x))
    return out


def render_blocks(tables, blocks, block: int = 32, phase: int = 0,
                  precision: str = "float32") -> tuple[list[float], int]:
    """The loop's output for a sequence of blocks, each (note, WAV1, DRIF[, TUN1
    [, trig[, w2]]]) -- the frame's 16-bit words and whether the frame triggers the
    voice; TUN1 defaults to 0 semitones, trig to False, w2 (a dict of LEV1, ATK, OFS1,
    PD1, NLEV words) to WaveTone's defaults. The phase carries across blocks and
    across slot changes, as the reader block holds it; POS goes through the W5 glide
    from the DSP's zeroed state (s = 0), then the W2 scanner; the samples are scaled
    by the W2 gain, ramped across the block from the gain the last one ended on (0.0
    at boot, as the DSP's zeroed state holds it; a note starts at its own gain)."""
    out: list[float] = []
    table_t = increment_table()
    rates, levels, rnd = rate_table(), level_table(), rnd_table()
    sc = Scanner()
    o2 = Osc2()
    s = 0
    for note, wav1, drif, *rest in blocks:
        tun1 = rest[0] if rest else TUN1_ZERO
        trig = bool(rest[1]) if len(rest) > 1 else False
        p = {**DEFAULTS, **(rest[2] if len(rest) > 2 and rest[2] else {})}
        s = glide(position(wav1), s, trig)
        sv, u = sc.block(p, trig, rates, rnd)
        pos = scanned(s, sv, p["ofs1"])
        tab = tables[slot(drif, len(tables))]
        samples, phase = render.render(tab, phase, increment(tuned(note, tun1), table_t),
                                       pos, block, precision)
        g = gain(u, p, levels)
        if trig:
            sc.gp = g
        mixed = ramp(samples, sc.gp, g)
        sc.gp = g
        if osc2_on(p):
            o2.s = glide(position(p["wav2"]), o2.s, trig)
            pos2 = scanned(o2.s, sv, p["ofs2"])
            tab2 = tables[slot(p["base"], len(tables))]
            n1 = tuned(note, tun1)
            two, o2.phase = render.render(tab2, o2.phase,
                                          increment(detuned(n1, p["tun2"]), table_t),
                                          pos2, block, precision)
            g2 = osc2_gain(u, p, levels)
            if trig:
                o2.gp = g2
            mixed = [_f32(a + b) for a, b in zip(mixed, ramp(two, o2.gp, g2))]
            o2.gp = g2
        else:
            o2.gp = 0.0
        out += mixed
    return out, phase

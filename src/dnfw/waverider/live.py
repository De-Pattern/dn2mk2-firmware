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


def slot(tbl1: int, count: int) -> int:
    """The directory slot the loop plays for the frame's 16-bit TBL1 word."""
    s = (tbl1 & 0xFFFF) >> SLOT_SHIFT
    return s if s < count else 0


def render_blocks(tables, blocks, block: int = 32, phase: int = 0,
                  precision: str = "float32") -> tuple[list[float], int]:
    """The loop's output for a sequence of blocks, each (note, WAV1, TBL1[, TUN1] -- the
    frame's 16-bit words; TUN1 defaults to 0 semitones): the phase
    carries across blocks and across slot changes, as the reader block holds it."""
    out: list[float] = []
    table_t = increment_table()
    for note, wav1, tbl1, *rest in blocks:
        tun1 = rest[0] if rest else TUN1_ZERO
        tab = tables[slot(tbl1, len(tables))]
        samples, phase = render.render(tab, phase, increment(tuned(note, tun1), table_t),
                                       position(wav1),
                                       block, precision)
        out += samples
    return out, phase

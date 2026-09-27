"""What Milestone 5's type-5 loop computes from a track's own state: the contract
`csrc/waverider/sharc/machine5_live.asm` is held to, bit for bit.

The loop reads three things the frame unpack `sw 0x1c2712` has already put in DSP
memory, measured by running that unpack (`scripts/sharc_waverider_m5.py`):

| what | where | form |
|---|---|---|
| SLOT, WaveTone's `TBL1` (param 27) | the frame copy `0x25c48c`, offset `222 + 146t` | 16-bit, half the sound's value: 0x0000 or 0x0080 |
| POS, WaveTone's `WAV1` (param 26) | the frame copy, offset `220 + 146t` | 16-bit, half the sound's value: 0..0x3c00 |
| pitch | engine `+0x1387c + 4t` (`0x254b14 + 4t`) | float semitones, note + fine/256 |

The unpack writes a type-5 track's machine parameters nowhere else: its record's
machine window is left as it is (measured, the same for any parameter value), so
the loop reads the copy of the frame the unpack itself made.

and turns them into `reader_m5.asm`'s parameter block:

- **table**: the directory's entry for `TBL1 >> 7`; at or above the count plays 0;
- **pos**: `min(WAV1, 0x3c00) << 6`, Q16 frames (0x3c00 << 6 is frame 15);
- **inc**: from the note, through a 129-entry float32 table `T` of phase steps
  (`increment_table`): `k = trunc(n)`, `fr = n - k`, `inc = trunc(T[k] + fr *
  (T[k+1] - T[k]))`, every operation rounded to float32 in the loop's order;
- **phase**: carried in the block from one block to the next, from 0.

The ColdFire's frame carries every slot parameter at **half** the sound's value
(`scripts/waverider_frame_compare.py` on frames its own builder made: FREQ
0x6117 -> 0x308c, WAV1 0x7800 -> 0x3c00, TBL1 0x0100 -> 0x0080). The first M5
reading assumed the sound's scale (0x7800, >> 8): POS would have stopped at
frame 7.5 and table 1 would never have played.

This module is pure: numbers in, numbers out.
"""

from __future__ import annotations

import math
import struct

from . import render

RATE = 48000.0
A4_NOTE, A4_HZ = 69, 440.0
NOTES = 129                      # T[0..128]; T[128] is only read with fr = 0
POS_MAX = 0x3C00                 # WAV1's range in the frame (the sound's 0x7800, halved)
POS_SHIFT = 6                    # 0x3c00 << 6 == 15 << 16
SLOT_SHIFT = 7                   # TBL1 1: 0x0100 in the sound, 0x0080 in the frame


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


def position(wav1: int) -> int:
    """The loop's Q16 frame position for the frame's 16-bit WAV1 word."""
    return min(wav1 & 0xFFFF, POS_MAX) << POS_SHIFT


def slot(tbl1: int, count: int) -> int:
    """The directory slot the loop plays for the frame's 16-bit TBL1 word."""
    s = (tbl1 & 0xFFFF) >> SLOT_SHIFT
    return s if s < count else 0


def render_blocks(tables, blocks, block: int = 32, phase: int = 0,
                  precision: str = "float32") -> tuple[list[float], int]:
    """The loop's output for a sequence of blocks, each (note, WAV1, TBL1 -- the frame's
    16-bit words): the phase
    carries across blocks and across slot changes, as the reader block holds it."""
    out: list[float] = []
    table_t = increment_table()
    for note, wav1, tbl1 in blocks:
        tab = tables[slot(tbl1, len(tables))]
        samples, phase = render.render(tab, phase, increment(note, table_t), position(wav1),
                                       block, precision)
        out += samples
    return out, phase

"""The Digitakt II voice record the ONESHOT render reads, in our own words.

The layout is digikit's "voice record contract" (their findings 06, checked on
the DT2 1.16 bytes by two agents there), re-read against the render's own
instructions here (`docs/dt2-machine-port.md`, "What the routine is"). Offsets
are bytes from the record base, which the render receives in R4. Positions
and the step are Q31 fixed point in a signed 64-bit pair, low word first:
sample `n` is `n << 31`.

| offset | field | the render |
|---|---|---|
| `+0x000` | sample pointer (int16 PCM, 2 bytes a sample) | reads; 0 = silence |
| `+0x004` | 64 floats: the 96 kHz points of this block | writes |
| `+0x104` | the decimator's state | reads and writes |
| `+0x17c` / `+0x17d` / `+0x17e` | declick one-shots: fade in, zero-cross mute, reseed | reads, clears |
| `+0x180` | the previous output sample (float) | reads and writes |
| `+0x188` | sample length in samples (u32; `+0x18c` its high word) | reads |
| `+0x190` | loop start | reads |
| `+0x198` | start (the trigger seeds the phase here; the render never reads it) | -- |
| `+0x1a0` | end | reads |
| `+0x1a8` | step, signed (negative plays backwards) | reads |
| `+0x1b0` | phase | reads and writes |
| `+0x1b8` | ACTIVE (byte) | reads; clears at the end of a one-shot |
| `+0x1b9` | a fade-out request (byte) [D] | reads |
| `+0x1bb` / `+0x1bc` | REVERSE / LOOP (bytes) | reads |

What a trigger writes before the first render is the net effect of the
DT2's arm (`sw 0x1c4eaf`: ACTIVE = 1, seed pending) and one of its step
setters (step, loop start, end, phase = start, or end - 1 sample in reverse):
`trigger` below builds exactly those fields and zeroes the rest.
"""

from __future__ import annotations

import struct

RECORD_BYTES = 0x1D8
SAMPLE_PTR = 0x000
WORK = 0x004
DECIMATOR_STATE = 0x104
FADE_IN, ZC_MUTE, RESEED = 0x17C, 0x17D, 0x17E
PREVIOUS = 0x180
RATE = 0x184
LENGTH, LENGTH_HI = 0x188, 0x18C
LOOP_START, START, END, STEP, PHASE = 0x190, 0x198, 0x1A0, 0x1A8, 0x1B0
ACTIVE, STOP, SEED, REVERSE, LOOP = 0x1B8, 0x1B9, 0x1BA, 0x1BB, 0x1BC

Q31 = 1 << 31
BLOCK = 32                  # outputs a call (48 kHz); the reader makes 64 points at 96 kHz
MIN_SPAN = 141              # samples: the render lengthens a shorter end or loop to this


def q31(samples: float) -> int:
    """A position or step in samples -> the signed 64-bit Q31 the record holds."""
    return round(samples * Q31)


def put_q31(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<Q", buf, offset, value & 0xFFFFFFFFFFFFFFFF)


def get_q31(buf: bytes, offset: int) -> int:
    v = struct.unpack_from("<Q", buf, offset)[0]
    return v - (1 << 64) if v & (1 << 63) else v


def trigger(*, sample_ptr: int, length: int, start: int, end: int, loop_start: int,
            step: int, reverse: bool, loop: bool) -> bytes:
    """A record as a trigger leaves it. `step` is Q31 and positive; reverse negates it,
    as the DT2's setters do. Positions are whole samples."""
    if not 0 <= start < end <= length or not 0 <= loop_start < end:
        raise ValueError(f"positions out of order: start {start}, end {end}, loop {loop_start}, "
                         f"length {length}")
    if step <= 0:
        raise ValueError("step is a positive Q31 speed; reverse sets the sign")
    rec = bytearray(RECORD_BYTES)
    struct.pack_into("<I", rec, SAMPLE_PTR, sample_ptr)
    struct.pack_into("<II", rec, LENGTH, length, 0)
    put_q31(rec, LOOP_START, loop_start << 31)
    put_q31(rec, START, start << 31)
    put_q31(rec, END, end << 31)
    put_q31(rec, STEP, -step if reverse else step)
    put_q31(rec, PHASE, ((end - 1) if reverse else start) << 31)
    rec[ACTIVE] = 1
    rec[REVERSE] = 1 if reverse else 0
    rec[LOOP] = 1 if loop else 0
    return bytes(rec)


def words(rec: bytes) -> list[int]:
    return list(struct.unpack(f"<{RECORD_BYTES // 4}I", rec))

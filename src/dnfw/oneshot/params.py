"""From six frame parameters to a DT2-shaped voice record: the adapter's arithmetic.

`csrc/oneshot/sharc/oneshot5.asm` does exactly this on the DSP; the gate compares
the record it writes with `record_fields` word for word. The parameters are the
coarse bytes (value >> 8) of machine-page indices 25..30 in the frame, which
the DN2 unpack leaves in its frame copy for a type-5 track (it does not unpack
them into the track record: measured, `docs/dt2-machine-port.md`).
"""

from __future__ import annotations

import struct

from . import record as R

INDICES = {"TUNE": 25, "PLAY": 26, "SAMP": 27, "STRT": 28, "LEN": 29, "LOOP": 30}
PLAY_MODES = {"FORWARD": 0, "REVERSE": 1, "FORWARD LOOP": 2, "REVERSE LOOP": 3}
TUNE_CENTRE = 64


def step(tune: int, reverse: bool) -> int:
    """Q31 speed for coarse TUNE (64 = the sample's own pitch). A 48 kHz sample plays
    in the render's 96 kHz domain at half a sample a point; reverse is negative."""
    s = round(0.5 * 2 ** ((tune - TUNE_CENTRE) / 12) * R.Q31)
    return -s if reverse else s


def step_table() -> bytes:
    """256 entries of (lo, hi): [tune] forward, [128 + tune] reverse. Our own numbers."""
    out = b""
    for rev in (False, True):
        for c in range(128):
            out += struct.pack("<q", step(c, rev))
    return out


def positions(length: int, strt: int, len_: int, loop: int) -> tuple[int, int, int]:
    """(start, end, loop start) in samples, from the coarse STRT, LEN, LOOP."""
    s = min((strt * length) >> 7, length - 1)
    span = length if len_ >= 127 else (len_ * length) >> 7
    e = max(min(s + span, length), s + 1)
    p = (loop * length) >> 7
    if p >= e:
        p = s
    return s, e, p


def record_fields(*, pointer: int, length: int, tune: int, play: int, strt: int, len_: int,
                  loop: int) -> bytes:
    """The record the adapter writes on a trigger (all other words zero)."""
    s, e, p = positions(length, strt, len_, loop)
    reverse, looped = bool(play & 1), bool(play & 2)
    rec = bytearray(R.RECORD_BYTES)
    struct.pack_into("<I", rec, R.SAMPLE_PTR, pointer)
    struct.pack_into("<II", rec, R.LENGTH, length, 0)
    R.put_q31(rec, R.LOOP_START, p << 31)
    R.put_q31(rec, R.START, s << 31)
    R.put_q31(rec, R.END, e << 31)
    R.put_q31(rec, R.STEP, step(tune, reverse))
    R.put_q31(rec, R.PHASE, ((e - 1) if reverse else s) << 31)
    rec[R.ACTIVE] = 1
    rec[R.REVERSE] = int(reverse)
    rec[R.LOOP] = int(looped)
    return bytes(rec)

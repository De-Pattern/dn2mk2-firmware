"""From the DT2's own parameter values to a DT2-shaped voice record: the adapter's arithmetic.

`csrc/oneshot/sharc/oneshot5.asm` does exactly this on the DSP; the gate compares
the record it writes with `record_fields` word for word.

**The values are the Digitakt II's records' own** (`dnfw.transplant.oneshot_cf`):
the ColdFire carries the DT2 records transplanted, so a ONESHOT track's machine
slots hold what the DT2's page writes, and the DN2 frame carries machine slots
25..65 verbatim at byte offset `2 * (slot - 25)` of the track's frame slot:

| | slot | frame offset | the value | read as |
|---|---|---|---|---|
| TUNE | 25 | +0 | 4..124 coarse, 64 = the sample's pitch (`0x7c00` max) | `value >> 8` |
| PLAY | 26 | +2 | 0 REV, 1 REV.L, 2 FWD.L, 3 FWD (the DT2 formatter's order) | `value >> 8` |
| SAMP | 28 | +6 | 0..1023, **not** 8.8 (range `0x3ff`, formatter `%d` of the raw value) | whole |
| STRT | 31 | +12 | 8.8, `0x7800` = 120.00 = the end | whole |
| LEN  | 32 | +14 | 8.8, `0x7800` = the whole sample | whole |
| LOOP | 33 | +16 | 0 = OFF; else `value - 1` in 8.8, as STRT | whole |

(#133's first adapter read slots 25..30 coarse and PLAY as `bit 0 reverse, bit
1 loop`: right for its hand-made frames, wrong for the DT2's records, which put
SAMP at 28 and number PLAY the other way.)

**The frame carries half of each value.** The ColdFire's builder copies the
modulated per-track mirror, which holds every slot at half the sound's value,
rounded up (Waverider M5's frame comparison, `0x6117 -> 0x308c`; this port's
emulator run shows `0xffff -> 0x8000`, `0x2d00 -> 0x1680`). So the adapter reads
TUNE and PLAY as `frame >> 7`, STRT / LEN / LOOP as `2 * frame`, and SAMP as the
frame word itself -- which makes a bank slot `SAMP / 2`, rounded: SAMP's lowest
bit does not reach the DSP [E]. A first build bakes one sample, where it does
not matter; a bank of many needs SAMP sent whole (`docs/dt2-machine-port.md`).

LOOP = OFF is read as "loop from the start" in the looping modes. How the DT2's
own DSP maps OFF is not known -- its frame unpack was not transplanted -- so that
reading is ours [D].
"""

from __future__ import annotations

import struct

from . import record as R

INDICES = {"TUNE": 25, "PLAY": 26, "SAMP": 28, "STRT": 31, "LEN": 32, "LOOP": 33}
COARSE = {"TUNE", "PLAY"}
PLAY_MODES = {"REVERSE": 0, "REVERSE LOOP": 1, "FORWARD LOOP": 2, "FORWARD": 3}
TUNE_CENTRE = 64
FULL = 0x7800                    # 120.00: STRT / LEN / LOOP at the sample's end
RECIPROCAL = 2185                # 65536 / 30: (x >> 10) * 2185 >> 16 is x / 30720


def half(value: int) -> int:
    """The frame word the ColdFire sends for a slot holding VALUE: half, rounded up."""
    return (value + 1) >> 1


def frame_offset(name: str) -> int:
    """Byte offset of NAME inside a track's frame slot."""
    return 2 * (INDICES[name] - 25)


def play_mode(play: int) -> tuple[bool, bool]:
    """-> (reverse, loop) for the DT2's PLAY value."""
    return play < 2, play in (1, 2)


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


def scale(value: int, length: int) -> int:
    """VALUE (8.8, 0x7800 = the end) of LENGTH samples, as the adapter computes it."""
    return (((value * length) >> 10) * RECIPROCAL) >> 16


def scale_frame(word: int, length: int) -> int:
    """A frame word (half an 8.8 value) of LENGTH samples: `2 word * length / 30720`."""
    return (((word * length) >> 9) * RECIPROCAL) >> 16


def positions(length: int, strt: int, len_: int, loop: int) -> tuple[int, int, int]:
    """(start, end, loop start) in samples, from the sound's whole 16-bit STRT, LEN and
    LOOP, through the frame's halves, exactly as the adapter computes them."""
    fs, fl, fp = half(strt), half(len_), half(loop)
    s = min(scale_frame(fs, length), length - 1)
    e = max(min(s + scale_frame(fl, length), length), s + 1)
    p = scale(max(2 * fp - 1, 0), length)
    if fp == 0 or p >= e:
        p = s
    return s, e, p


def record_fields(*, pointer: int, length: int, tune: int, play: int, strt: int, len_: int,
                  loop: int) -> bytes:
    """The record the adapter writes on a trigger (all other words zero). TUNE and PLAY
    are coarse; STRT, LEN and LOOP whole 16-bit values."""
    s, e, p = positions(length, strt, len_, loop)
    tune, play = half(tune << 8) >> 7, half(play << 8) >> 7
    reverse, looped = play_mode(play)
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


def sound_words(*, tune: int, play: int, samp: int, strt: int, len_: int, loop: int) -> dict[int, int]:
    """The 16-bit slot values a ONESHOT sound holds for these settings: slot -> value."""
    return {25: tune << 8, 26: play << 8, 28: samp, 31: strt, 32: len_, 33: loop}


def frame_words(**settings) -> dict[int, int]:
    """What the ColdFire sends for those settings: slot -> frame word (each halved)."""
    return {slot: half(v) for slot, v in sound_words(**settings).items()}


def bank_slot(samp: int, count: int) -> int:
    """The bank entry the adapter plays for SAMP: the frame word, or 0 past the count."""
    k = half(samp)
    return k if k < count else 0

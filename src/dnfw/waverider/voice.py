"""The DN2 1.11 SHARC voice path, as Milestone 2 measured it, and the signal
arithmetic its gates use (`docs/waverider-feasibility.md`, "Milestone 2").

This module is pure: addresses, layouts and numbers. Running the firmware is
`scripts/sharc_waverider_voice.py`'s job, through digikit's SHARC runner.

Every address below is a DM byte address in the form the firmware itself uses
(the runner's loader alias adds 0x28000000). Each one was read back out of a
run, not only out of the listing; the doc says which run.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

# -- the engine, as `sw 0x1c8e1c` (engine init) lays it out -------------------

ENGINE = 0x241298            # R4 into sw 0x1c8e1c and sw 0x1c8ef1: the engine state
TRACKS = 0x2554B8            # R8: 16 per-track records ...
TRACK_STRIDE = 0x234         # ... of 0x234 bytes (M3 = 0x8d words in sw 0x1c8ef1)
TRACK_MACHINE = 0x1B4        # record + 0x1b4: the machine type sw 0x1c8ef1 dispatches on
CONFIG = 0x257E6C            # R12: word 0 is the block size
TRACK_BUFFERS = ENGINE + 0x137C8   # 16 pointers, one float block per track
N_TRACKS = 16

# per-machine voice state, per track: (offset from ENGINE, stride), from the
# per-track loop of sw 0x1c8e1c
MACHINE_STATE = {
    0: (0x0008, 0x240),      # FM Tone   (init sw 0x1c4e78)
    1: (0x2408, 0x30C),      # WaveTone  (init sw 0x1c6909)
    2: (0x54C8, 0x2E8),      # FM Drum   (init sw 0x1c7069)
    3: (0x8348, 0x55C),      # Swarmer   (init sw 0x1c8246)
}
MACHINES = ("FM Tone", "WaveTone", "FM Drum", "Swarmer", "MIDI")   # docs/machine-list.md

# the render call each machine type gets from sw 0x1c8ef1's per-type loops
MACHINE_RENDER = {0: 0x1C54C7, 1: 0x1C6D4A, 2: 0x1C778B, 3: 0x1C85AD}

# WaveTone (sw 0x1c6d4a): two oscillators, then a fixed-point mix into scratch
# buffers, a 2:1 decimator, and a clipped sum written to the track buffer.
WAVETONE_OSC = (0x10, 0xD0)          # state + 0x10 -> sw 0x1c44ae, + 0xd0 -> sw 0x1c43ca
WAVETONE_OUT_SUM = 0x266790          # decimated oscillator mix, one block

# field offsets (words) inside one WaveTone oscillator's state, as sw 0x1c44ae reads them
OSC_PHASE = 3         # u32 accumulator, 26 bits used
OSC_INC = 4           # added to the phase every (2x oversampled) sample
OSC_LEVEL_A = 21      # float, fixed to Q31: gain of table A
OSC_LEVEL_B = 28      # float, fixed to Q31: gain of table B
OSC_TABLE_A = 42      # pointer to int16 pairs
OSC_TABLE_B = 43

# the candidate hooks the milestone ranks
SELECTOR_CLAMP = 0x1C294C     # sw 0x1c2712: min(R2, 4)
STAGE5 = 0xB80F2E             # a per-track filter stage with a 1024-point shaper table
STAGE5_TABLE = 0x26B3A8


def track_record(track: int) -> int:
    _check_track(track)
    return TRACKS + track * TRACK_STRIDE


def machine_state(machine: int, track: int) -> int:
    _check_track(track)
    base, stride = MACHINE_STATE[machine]
    return ENGINE + base + track * stride


def _check_track(track: int) -> None:
    if not 0 <= track < N_TRACKS:
        raise ValueError(f"track {track} is outside 0..{N_TRACKS - 1}")


# -- signal arithmetic -----------------------------------------------------------

def f32_bits(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bits_f32(w: int) -> float:
    return struct.unpack("<f", struct.pack("<I", w & 0xFFFFFFFF))[0]


def peak(samples: list[float]) -> float:
    return max((abs(s) for s in samples), default=0.0)


def rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@dataclass(frozen=True)
class Fit:
    """`got ~= gain * want`, least squares, and what is left over."""

    gain: float
    residual_rms: float
    residual_peak: float
    correlation: float
    snr_db: float | None


def fit_gain(got: list[float], want: list[float]) -> Fit:
    if len(got) != len(want):
        raise ValueError("fit_gain needs equal lengths")
    ww = sum(w * w for w in want)
    gw = sum(g * w for g, w in zip(got, want))
    gg = sum(g * g for g in got)
    gain = gw / ww if ww else 0.0
    res = [g - gain * w for g, w in zip(got, want)]
    corr = gw / math.sqrt(gg * ww) if gg and ww else 0.0
    r = rms(res)
    signal = rms([gain * w for w in want])
    snr = 20 * math.log10(signal / r) if r and signal else None
    return Fit(gain, r, peak(res), corr, snr)


def loop_to(samples: list[float], count: int) -> list[float]:
    """SAMPLES repeated end to end, cut to COUNT (a short render made listenable)."""
    if not samples:
        return [0.0] * count
    reps = -(-count // len(samples))
    return (samples * reps)[:count]


def unpack_int16_pairs(words: list[int]) -> list[int]:
    """The low-then-high int16 pairs sw 0x1c44ae reads from a table word."""
    out = []
    for w in words:
        for half in (w & 0xFFFF, (w >> 16) & 0xFFFF):
            out.append(half - 0x10000 if half & 0x8000 else half)
    return out

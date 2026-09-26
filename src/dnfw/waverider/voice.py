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

# -- Milestone 3: the note trigger, the amp, and where a sixth machine type hooks --
#
# Every address below was read out of a run in digikit's SHARC runner
# (`scripts/sharc_waverider_m3.py`), not only out of the listing.

# The note trigger. The per-track frame image (copied to 0x25c48c) carries a
# trigger bit; the unpack raises the engine flag ENGINE + TRIG_CELL and calls
# NOTE_ON_FN, and the dispatch's compare at 0x1c90fb (record note counter) gates
# the amp. With the flag set the amp opens; clear, the amp is closed.
TRIG_CELL = 0x138FC           # engine + this: the per-track note-trigger flag (byte)
NOTE_ON_FN = 0xB82440         # arms a voice's note counter (0x1c91c5 / 0x1c96a3)
AMP_STAGE = 0xB80345          # the per-track amp; its write at 0xb80515
AMP_SETUP = 0xB8028C          # reads the envelope (record +0x20c..+0x228), called at 0x1c92b0
AMP_ENV_OFFSETS = (0x20C, 0x210, 0x214, 0x218, 0x21C, 0x220, 0x224)   # record words: ADSR

# The machine-type dispatch. The frame's type nibble indexes MACHINE_LOOKUP;
# entry [5] is 0 in stock (so a type-5 frame is squashed to FM Tone). A separate
# per-track selector is clamped by TYPE_CLAMP (min(R2, 4) at SELECTOR_CLAMP; the
# `R0 = 0x4` that feeds it is at TYPE_CLAMP_IMM). Raising both admits type 5.
MACHINE_LOOKUP = 0x25D748     # 8-word table: frame nibble -> machine type, [0..4]=0..4, [5..]=0
TYPE_CLAMP_IMM = 0x1C294A     # `R0 = 0x4`; raised to `R0 = 0x5` for a sixth type
PER_TYPE_SETUP = 0x8052DB90   # jump table sw 0x1c8ef1 uses to set up each machine type

# The four stock per-type render loops in sw 0x1c8ef1, and where a fifth is added.
# A JUMP over TYPE5_ENTRY (after the Swarmer loop, before the per-track chain)
# reaches our own loop; it returns to TYPE5_RESUME.
PER_TYPE_RENDER_LOOPS = (0x1C93E5, 0x1C9401, 0x1C941C, 0x1C943B)   # FM Tone/WaveTone/FM Drum/Swarmer
TYPE5_ENTRY = 0x1C9448        # the two instructions here are replaced by JUMP wr_type5
TYPE5_RESUME = 0x1C944C       # where wr_type5 rejoins the per-track chain

# Where our own SHARC code is spliced (PM sw / DM byte; unloaded spans).
READER_SW = 0x180000          # csrc/waverider/sharc/reader.asm  (wr_render)
MACHINE5_SW = 0x180100        # csrc/waverider/sharc/machine5.asm (wr_type5)


def machine_from_nibble(nibble: int, lookup: list[int] | None = None) -> int:
    """The stock frame-nibble -> machine-type mapping (MACHINE_LOOKUP): 0..4 pass
    through, 5+ squash to 0. A real type-5 frame needs entry [5] set to 5 too."""
    table = lookup if lookup is not None else [0, 1, 2, 3, 4, 0, 0, 0]
    return table[nibble] if 0 <= nibble < len(table) else 0


def type_clamp(value: int, ceiling: int = 4) -> int:
    """The per-track selector clamp at SELECTOR_CLAMP: max(value, 0) then min(., ceiling).
    Stock ceiling is 4; Milestone 3 raises it to 5 for the sixth machine type."""
    return min(max(value, 0), ceiling)


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

"""The ColdFire -> DSP parameter frame, as the DN2 1.11 DSP unpacks it
(`docs/waverider-feasibility.md`, "Milestone 4").

`sw 0x1c2712` copies a 2,688-byte frame image to `0x25c48c` and unpacks it into
the 16 track records (`voice.TRACKS`, stride 0x234) and the engine. Every offset
below was measured by running that unpack in digikit's SHARC runner with one
16-bit field changed at a time (`scripts/sharc_waverider_m4.py`), not read off a
listing. Offsets are **DSP-memory byte offsets** into the image: each field is a
little-endian 16-bit word at an even offset, as the unpack reads it. How the
ColdFire's big-endian SPI words land in that order is not measured here.

The frame has two regions (`docs/engine-state.md`, "What the frame is"):

- a header of field-major arrays, one 16-bit word per track;
- sixteen 146-byte track slots from `SLOT_BASE`, carrying the sound's parameter
  indices 25..99 as the ColdFire's four block copies lay them out (indices 93
  and 94 are not sent).

A value is the ColdFire's 16-bit parameter word, `coarse << 8 | fine`: the
parameter table's default for FREQ is `0x7f00`, coarse 127.

This module is pure: bytes in, bytes out.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

FRAME_BYTES = 2688
TRACKS = 16
SLOT_BASE = 218
SLOT_STRIDE = 146

# header arrays: base offset + 2 * track
NOTE = 2            # the trig note (param 19); DSP: engine +0x1387c + 4t, as note + fine/256
LEVEL = 116         # DSP: record +0x22c, value / 32512
MACHINE = 148       # DSP: record +0x1b4, the machine type sw 0x1c8ef1 dispatches on
FILTER = 180        # DSP: record +0x1dc, through FILTER_TO_DSP

# trigger masks: one 16-bit word each, bit t = track t. The first is the note
# trigger (the byte cell engine +0x138fc + t that Milestone 3 poked by hand); the
# other three raise byte cells at engine +0x1391c, +0x1393c and +0x1394c.
TRIG_NOTE = 34
TRIG_MASKS = (34, 36, 38, 40)

# the four block copies of the frame builder 0x400274ba: (first index, last index,
# offset of the first index inside a track slot)
SLOT_BLOCKS = ((25, 65, 0), (66, 79, 82), (80, 92, 110), (95, 99, 136))

# The ColdFire filter type (the filter page, 0 = page 5) and the DSP's own filter
# number (record +0x1dc; the render arm is 0x8052dbc0[n]). Measured through the
# unpack: 0->1, 1->3, 2->2, 3->4, 4->5, 5->6; anything else -> 0, no filter.
FILTER_NAMES = ("Multimode", "Lowpass 4", "Equalizer", "Comb-", "Legacy LP/HP", "Comb+")
FILTER_TO_DSP = (1, 3, 2, 4, 5, 6)

# Where the unpack puts each filter / amp / FX parameter in the track record
# (record offset), and how it scales the 16-bit value. `u` is value / 32768,
# `t` is value / 32512 (so 0x7f00 is exactly 1.0), `f` is a flag.
RECORD_FIELDS = {
    66: (0x1C8, "t", "filter-type parameter 3 (TYPE / Q / LPF)"),
    67: (0x1CC, "u", "FREQ"),
    68: (0x1D0, "u", "RESO / GAIN / FDBK"),
    69: (0x204, "u", "filter env depth (bipolar, 0x4000 = 0)"),
    70: (0x1EC, "t", "filter env delay"),
    71: (0x1F0, "t", "filter env attack"),
    72: (0x1F4, "t", "filter env decay"),
    73: (0x1F8, "t", "filter env sustain"),
    74: (0x1FC, "t", "filter env release"),
    75: (0x200, "f", "filter env reset"),
    76: (0x1E0, "t", "BASE (base-width filter)"),
    77: (0x1E4, "t", "WIDTH (base-width filter)"),
    78: (0x1E8, "f", "base-width routing"),
    79: (0x208, "k", "key tracking, value / 25600"),
    81: (0x210, "t", "amp attack"),
    82: (0x214, "t", "amp hold"),
    83: (0x218, "t", "amp decay"),
    84: (0x21C, "t", "amp sustain"),
    85: (0x220, "t", "amp release"),
    89: (0x230, "u", "pan"),
    90: (0x228, "v", "volume, (value / 32768) squared"),
    91: (0x20C, "p", "amp mode: a pointer the unpack picks"),
    92: (0x224, "f", "amp env reset"),
    95: (0x1B8, "t", "bit reduction"),
    96: (0x1BC, "t", "sample-rate reduction"),
    98: (0x1C0, "u", "overdrive"),
}


def slot_offset(track: int, index: int) -> int:
    """The image offset of parameter INDEX (25..99, not 93/94) for TRACK."""
    _check_track(track)
    for first, last, at in SLOT_BLOCKS:
        if first <= index <= last:
            return SLOT_BASE + SLOT_STRIDE * track + at + 2 * (index - first)
    raise ValueError(f"parameter index {index} is not carried by the frame")


def header_offset(array: int, track: int) -> int:
    _check_track(track)
    return array + 2 * track


def dsp_filter(cf_type: int) -> int:
    """The DSP filter number the unpack stores for a ColdFire filter type."""
    return FILTER_TO_DSP[cf_type] if 0 <= cf_type < len(FILTER_TO_DSP) else 0


@dataclass
class Frame:
    """A frame image under construction."""

    data: bytearray = field(default_factory=lambda: bytearray(FRAME_BYTES))

    def put(self, offset: int, value: int) -> None:
        if offset % 2 or not 0 <= offset <= FRAME_BYTES - 2:
            raise ValueError(f"offset {offset} is not an even offset in the frame")
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"value {value:#x} is not 16-bit")
        struct.pack_into("<H", self.data, offset, value)

    def get(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def param(self, track: int, index: int, value: int) -> None:
        self.put(slot_offset(track, index), value)

    def header(self, array: int, track: int, value: int) -> None:
        self.put(header_offset(array, track), value)

    def trigger(self, track: int, masks=TRIG_MASKS, on: bool = True) -> None:
        _check_track(track)
        for at in masks:
            word = self.get(at)
            self.put(at, (word | (1 << track)) if on else (word & ~(1 << track)))

    def sound(self, track: int, values: dict[int, int]) -> None:
        for index, value in values.items():
            self.param(track, index, value)

    def to_bytes(self) -> bytes:
        return bytes(self.data)


def init_frame(sound: dict[int, int], machine: int, *, cf_filter: int = 0, trigger: bool = False,
               track0: dict[int, int] | None = None) -> Frame:
    """A frame with every track on the init sound SOUND (index -> value): track 0 on
    MACHINE and CF_FILTER with TRACK0's overrides, tracks 1-15 MIDI (type 4, no render),
    the Trig Note default 60 and Track Level default 100 everywhere. TRIGGER sets track
    0's four trigger bits."""
    f = Frame()
    for t in range(TRACKS):
        f.header(MACHINE, t, machine if t == 0 else 4)
        f.header(FILTER, t, cf_filter if t == 0 else 0)
        f.header(NOTE, t, 0x3C00)
        f.header(LEVEL, t, 0x6400)
        f.sound(t, sound)
    f.sound(0, dict(track0 or {}))
    if trigger:
        f.trigger(0)
    return f


def sound_defaults(records) -> dict[int, int]:
    """Parameter index -> default, for the frame's indices 66..99, from parameter
    records (anything with `.group`, `.parameter_id`, `.default`). The filter-type
    parameters 66..68 come from page group 5, the first filter type (Multimode):
    the init sound's filter. Machine indices 25..65 are machine-specific and are
    left to the caller."""
    wanted = {5, 11, 13, 14, 15}
    out: dict[int, int] = {}
    for rec in records:
        idx, grp = rec.parameter_id, rec.group
        if idx is None or grp not in wanted or not 66 <= idx <= 99 or idx in (93, 94):
            continue
        if 66 <= idx <= 68 and grp != 5:
            continue
        out.setdefault(idx, rec.default & 0xFFFF)
    return out


def _check_track(track: int) -> None:
    if not 0 <= track < TRACKS:
        raise ValueError(f"track {track} is outside 0..{TRACKS - 1}")

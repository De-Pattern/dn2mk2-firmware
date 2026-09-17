"""Turn a user's wavetable file into an LFO table: 7 frames of 32 signed bytes.

The owner, 2026-09-17: *"Allow the person to be able to change the wavetables.
Think about what file format will work for you as an input."* Two inputs:

**A WAV wavetable** -- the de facto interchange format (Serum, Vital, Bitwig,
Ableton Wavetable, most wavetable editors export it). A single-cycle waveform is
the one-frame case. Accepted: RIFF/WAVE, PCM 8/16/24/32-bit or IEEE float
32/64-bit, any channel count (the first channel is used), any sample rate (it is
irrelevant: a wavetable is a list of cycles, not audio). The frame size comes from
a Serum-style `clm ` chunk (`<!>2048 ...`) when present, otherwise **2048** when
the length divides by it, otherwise the whole file is one cycle.

**A JSON table** -- for code and for the shape bench:
`{"name": "...", "frames": [[...], ...]}`, any number of frames of any equal
length, values in -1..1 (floats) or -127..127 (integers).

**What happens to either**, the same way here and in `site/js/wavetable.js`:

1. frames are reduced to **7** by linear interpolation along the table (a table
   with fewer than 7 frames is interpolated up, one frame is repeated);
2. each frame is reduced to **32** points by averaging each 32nd of the cycle
   (a box filter, so a 2048-sample frame's high harmonics fold smoothly instead of
   aliasing);
3. the whole table is scaled so its largest point is 127 -- relative levels
   between frames are kept -- and rounded half away from zero.

The generator then interpolates between those 32 points and 7 frames at run
time, so a smooth source stays smooth.
"""

from __future__ import annotations

import json
import math
import struct

FRAMES = 7
SAMPLES = 32
PEAK = 127
DEFAULT_FRAME = 2048


class WavetableError(ValueError):
    pass


def _round(v: float) -> int:
    return int(math.floor(abs(v) + 0.5)) * (1 if v >= 0 else -1)


def parse_wav(data: bytes) -> tuple[list[float], int | None]:
    """-> (first-channel samples in -1..1, frame size from a `clm ` chunk or None)."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavetableError("not a WAV file (no RIFF/WAVE header)")
    fmt = None
    frame = None
    samples = None
    at = 12
    while at + 8 <= len(data):
        cid, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        body = data[at + 8:at + 8 + size]
        if cid == b"fmt ":
            if len(body) < 16:
                raise WavetableError("WAV fmt chunk is too short")
            tag, channels, _, _, _, bits = struct.unpack_from("<HHIIHH", body)
            if tag == 0xFFFE and len(body) >= 26:          # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack_from("<H", body, 24)[0]
            fmt = (tag, channels, bits)
        elif cid == b"clm ":
            text = body.decode("latin1")
            if text.startswith("<!>"):
                digits = "".join(ch for ch in text[3:8] if ch.isdigit())
                if digits:
                    frame = int(digits)
        elif cid == b"data":
            samples = body
        at += 8 + size + (size & 1)
    if fmt is None or samples is None:
        raise WavetableError("WAV file has no fmt or data chunk")
    tag, channels, bits = fmt
    width = bits // 8
    if channels < 1 or width < 1:
        raise WavetableError("WAV file has no channels")
    step = width * channels
    n = len(samples) // step
    out = []
    for i in range(n):
        o = i * step
        if tag == 1 and bits == 8:
            v = (samples[o] - 128) / 128.0
        elif tag == 1 and bits == 16:
            v = struct.unpack_from("<h", samples, o)[0] / 32768.0
        elif tag == 1 and bits == 24:
            x = samples[o] | (samples[o + 1] << 8) | (samples[o + 2] << 16)
            v = (x - (1 << 24) if x & 0x800000 else x) / 8388608.0
        elif tag == 1 and bits == 32:
            v = struct.unpack_from("<i", samples, o)[0] / 2147483648.0
        elif tag == 3 and bits == 32:
            v = struct.unpack_from("<f", samples, o)[0]
        elif tag == 3 and bits == 64:
            v = struct.unpack_from("<d", samples, o)[0]
        else:
            raise WavetableError(f"unsupported WAV encoding: format {tag}, {bits}-bit")
        out.append(v)
    if not out:
        raise WavetableError("WAV file has no samples")
    return out, frame


def split_frames(samples: list[float], frame: int | None) -> list[list[float]]:
    if frame is None:
        frame = DEFAULT_FRAME if len(samples) % DEFAULT_FRAME == 0 else len(samples)
    if frame <= 0 or len(samples) < frame:
        raise WavetableError(f"frame size {frame} does not fit {len(samples)} samples")
    count = len(samples) // frame
    return [samples[k * frame:(k + 1) * frame] for k in range(count)]


def _box(frame: list[float]) -> list[float]:
    """Average each 32nd of the cycle. Works for frames shorter than 32 too."""
    n = len(frame)
    out = []
    for j in range(SAMPLES):
        lo, hi = j * n / SAMPLES, (j + 1) * n / SAMPLES
        total = weight = 0.0
        k = int(math.floor(lo))
        while k < hi and k < n:
            w = min(hi, k + 1) - max(lo, k)
            if w > 0:
                total += frame[k] * w
                weight += w
            k += 1
        out.append(total / weight if weight else 0.0)
    return out


def to_table(frames: list[list[float]]) -> list[list[int]]:
    """Any frames -> 7 x 32 signed bytes (see the module docstring)."""
    if not frames or any(len(f) == 0 for f in frames):
        raise WavetableError("a wavetable needs at least one non-empty frame")
    small = [_box(f) for f in frames]
    picked = []
    for k in range(FRAMES):
        pos = k * (len(small) - 1) / (FRAMES - 1) if len(small) > 1 else 0.0
        a = int(math.floor(pos))
        b = min(a + 1, len(small) - 1)
        t = pos - a
        picked.append([small[a][j] * (1 - t) + small[b][j] * t for j in range(SAMPLES)])
    peak = max(abs(v) for f in picked for v in f)
    if peak == 0:
        raise WavetableError("the wavetable is silent")
    return [[max(-PEAK, min(PEAK, _round(v / peak * PEAK))) for v in f] for f in picked]


def from_wav(data: bytes) -> list[list[int]]:
    samples, frame = parse_wav(data)
    return to_table(split_frames(samples, frame))


def from_json(data: bytes) -> list[list[int]]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WavetableError(f"not valid JSON: {exc}") from None
    frames = doc.get("frames") if isinstance(doc, dict) else None
    if not isinstance(frames, list) or not frames:
        raise WavetableError('JSON needs a "frames" list')
    length = len(frames[0]) if isinstance(frames[0], list) else 0
    if length == 0 or any(not isinstance(f, list) or len(f) != length for f in frames):
        raise WavetableError("all frames must be lists of the same length")
    flat = [v for f in frames for v in f]
    if not all(isinstance(v, (int, float)) for v in flat):
        raise WavetableError("frame values must be numbers")
    scale = 127.0 if all(isinstance(v, int) for v in flat) and max(map(abs, flat)) > 1 else 1.0
    return to_table([[v / scale for v in f] for f in frames])


def load(data: bytes, name: str = "") -> list[list[int]]:
    """Pick the reader by content (RIFF) or by extension."""
    if data[:4] == b"RIFF":
        return from_wav(data)
    if name.lower().endswith(".json") or data.lstrip()[:1] in (b"{", b"["):
        return from_json(data)
    raise WavetableError("expected a .wav wavetable or a .json table")


def to_bytes(table: list[list[int]]) -> bytes:
    if len(table) != FRAMES or any(len(f) != SAMPLES for f in table):
        raise WavetableError(f"a table is {FRAMES} x {SAMPLES}")
    return bytes(v & 0xFF for f in table for v in f)

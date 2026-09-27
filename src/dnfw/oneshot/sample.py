"""The user's sample, made into what the bank holds: 48 kHz, mono, int16, short enough.

One subject: a WAV file in, a list of int16 samples out. Any PCM or float WAV the
`dnfw.wavetable` parser reads; channels are averaged, other rates are resampled
linearly (the ONESHOT render interpolates at play time; this only has to be
fair), and a sample longer than the bank's room is cut with a 5 ms fade so the
cut does not click. The sample is the user's; it is never written anywhere but
into the firmware they are building.
"""

from __future__ import annotations

import struct

RATE = 48000
FADE = 240                       # 5 ms at 48 kHz


class SampleError(ValueError):
    pass


def channels_average(data: bytes) -> tuple[list[float], int]:
    """-> (mono samples in -1..1, the file's rate), every channel averaged."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise SampleError("not a WAV file (no RIFF/WAVE header)")
    fmt, body, at = None, None, 12
    while at + 8 <= len(data):
        cid, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        chunk = data[at + 8:at + 8 + size]
        if cid == b"fmt ":
            tag, ch, rate, _, _, bits = struct.unpack_from("<HHIIHH", chunk)
            if tag == 0xFFFE and len(chunk) >= 26:
                tag = struct.unpack_from("<H", chunk, 24)[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            body = chunk
        at += 8 + size + (size & 1)
    if fmt is None or body is None:
        raise SampleError("the WAV has no fmt or data chunk")
    tag, ch, rate, bits = fmt
    width = bits // 8
    if ch < 1 or width < 1:
        raise SampleError("the WAV has no channels")
    step = width * ch
    out = []
    for i in range(len(body) // step):
        acc = 0.0
        for c in range(ch):
            o = i * step + c * width
            if tag == 1 and bits == 8:
                v = (body[o] - 128) / 128.0
            elif tag == 1 and bits == 16:
                v = struct.unpack_from("<h", body, o)[0] / 32768.0
            elif tag == 1 and bits == 24:
                x = body[o] | (body[o + 1] << 8) | (body[o + 2] << 16)
                v = (x - (1 << 24) if x & 0x800000 else x) / 8388608.0
            elif tag == 1 and bits == 32:
                v = struct.unpack_from("<i", body, o)[0] / 2147483648.0
            elif tag == 3 and bits == 32:
                v = struct.unpack_from("<f", body, o)[0]
            elif tag == 3 and bits == 64:
                v = struct.unpack_from("<d", body, o)[0]
            else:
                raise SampleError(f"unsupported WAV encoding: format {tag}, {bits}-bit")
            acc += v
        out.append(acc / ch)
    if not out:
        raise SampleError("the WAV has no samples")
    return out, rate


def resample(xs: list[float], rate: int) -> list[float]:
    if rate == RATE:
        return list(xs)
    step, out = rate / RATE, []
    for i in range(int(len(xs) / step)):
        x = i * step
        k = int(x)
        a = xs[k] if k < len(xs) else 0.0
        b = xs[k + 1] if k + 1 < len(xs) else a
        out.append(a + (b - a) * (x - k))
    return out


def from_wav(data: bytes, limit: int) -> tuple[list[int], dict]:
    """-> (int16 samples, what was done). LIMIT is the most samples the bank holds."""
    xs, rate = channels_average(data)
    xs = resample(xs, rate)
    note = {"rate_in": rate, "samples_in": len(xs), "trimmed": len(xs) > limit}
    if len(xs) > limit:
        xs = xs[:limit]
        for i in range(min(FADE, len(xs))):
            xs[len(xs) - 1 - i] *= i / FADE
    pcm = [max(-32768, min(32767, round(v * 32767))) for v in xs]
    note.update(samples=len(pcm), seconds=round(len(pcm) / RATE, 3),
                peak=max((abs(v) for v in pcm), default=0))
    return pcm, note

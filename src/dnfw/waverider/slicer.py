"""Any short sample -> a Waverider wavetable, the way Tonverk makes one from a WAV.

    dnfw waverider slice voice.wav -o voice_wt.wav [--mode auto|pitch|window]
                         [--frame N] [--frames 16] [--harmonics 48]

Tonverk turns any WAV into a wavetable by reading it as consecutive single-cycle
frames (2,048 samples unless the name says otherwise, `name_wt1024.wav`). That is
what `window` does here, with one change: the frames are spread evenly across the
whole sample rather than taken from its start, so a short vowel or a chord's attack
and decay both end up in the table.

For a pitched sample that gives frames whose length has nothing to do with the
pitch, so each one is a slice through several cycles and the result buzzes at the
frame rate instead of sounding like the source. `pitch` finds the sample's period
at each of the frames' positions (autocorrelation, on a 4x decimated copy, refined
at full rate), and cuts exactly one cycle there, from a rising zero crossing. A
voice or a synth note becomes a table of its own waveforms, playable at any pitch.
`auto` (the default) uses `pitch` where the sample is clearly periodic and `window`
where it is not -- a drum, noise, a texture.

Every frame is then resampled to one cycle of 2,048 points and band-limited to
`harmonics` partials (`factory.analyse` / `additive`, as the factory set), because
Waverider's reader has no mip-maps: what a high note would fold back as noise is
removed here. The table is normalised as a whole, so the frames keep their
relative levels.

Outputs:
- `slice()` -> 16 frames of floats (2,048 points), and a report;
- `wav_bytes()` -> a standard wavetable WAV (float32, 2,048-sample frames, with a
  `clm ` chunk), which Serum, Vital and Tonverk read, and which `dnfw waverider
  bake` / `reduce.from_wav` reduce to Waverider's 16 x 512 int16.

Pure Python, no dependencies.
"""

from __future__ import annotations

import math
import pathlib
import re
import struct

from ..wavetable import WavetableError, parse_wav
from . import factory

CYCLE = 2048                     # points in an output frame (Serum / Vital / Tonverk)
FRAMES = 16
DEFAULT_WINDOW = 2048            # Tonverk's default frame length
MIN_HZ, MAX_HZ = 30.0, 2000.0    # the periods `pitch` looks for
PERIODIC = 0.6                   # normalised autocorrelation needed to call it pitched
DECIMATE = 4


def wav_rate(data: bytes) -> int:
    """The sample rate in a WAV's fmt chunk (44,100 if there is none)."""
    at = 12
    while at + 8 <= len(data):
        cid, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        if cid == b"fmt " and size >= 8:
            return struct.unpack_from("<I", data, at + 12)[0]
        at += 8 + size + (size & 1)
    return 44100


def name_window(path: str) -> int | None:
    """Tonverk's naming rule: `..._wt1024.wav` means 1,024-sample frames."""
    m = re.search(r"_wt(\d+)$", pathlib.Path(path).stem, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _decimated(samples: list[float], at: int, length: int) -> list[float]:
    """LENGTH samples from AT, averaged in fours (a box low-pass, then every 4th)."""
    out = []
    for k in range(at, min(at + length, len(samples) - DECIMATE + 1), DECIMATE):
        out.append(sum(samples[k:k + DECIMATE]) / DECIMATE)
    return out


def period_at(samples: list[float], rate: int, centre: int) -> tuple[float | None, float]:
    """-> (period in samples, clarity 0..1) of the sound around CENTRE, or (None, c).

    Normalised autocorrelation on a decimated window of about four of the longest
    periods; the first lag whose correlation is within 90 % of the best is taken
    (so a strong second-period peak does not halve the pitch), then refined at
    full rate by a parabola through the three lags around it."""
    longest = int(rate / MIN_HZ)
    window = 4 * longest
    start = max(0, min(len(samples) - window, centre - window // 2))
    x = _decimated(samples, start, window)
    if len(x) < 64:
        return None, 0.0
    m = _mean(x)
    x = [v - m for v in x]
    energy = sum(v * v for v in x)
    if energy < 1e-9:
        return None, 0.0
    lo = max(2, int(rate / MAX_HZ / DECIMATE))
    hi = min(len(x) // 2, int(rate / MIN_HZ / DECIMATE))
    if hi <= lo + 2:
        return None, 0.0
    corr = []
    for lag in range(lo, hi):
        a, b = x[:-lag], x[lag:]
        num = sum(p * q for p, q in zip(a, b))
        den = math.sqrt(sum(p * p for p in a) * sum(q * q for q in b)) or 1.0
        corr.append(num / den)
    best = max(corr)
    if best < PERIODIC:
        return None, max(best, 0.0)
    # the first local peak near the best
    for k in range(1, len(corr) - 1):
        if corr[k] >= 0.9 * best and corr[k] >= corr[k - 1] and corr[k] >= corr[k + 1]:
            pick = k
            break
    else:
        pick = corr.index(best)
    coarse = (lo + pick) * DECIMATE
    # refine at full rate: the full-rate correlation at coarse-4 .. coarse+4
    seg = samples[start:start + window]
    m = _mean(seg)
    seg = [v - m for v in seg]

    def r(lag):
        if lag <= 0 or lag >= len(seg):
            return -1.0
        a, b = seg[:-lag], seg[lag:]
        num = sum(p * q for p, q in zip(a, b))
        den = math.sqrt(sum(p * p for p in a) * sum(q * q for q in b)) or 1.0
        return num / den
    lags = range(max(1, coarse - DECIMATE), coarse + DECIMATE + 1)
    rs = {lag: r(lag) for lag in lags}
    peak = max(rs, key=rs.get)
    y0, y1, y2 = rs.get(peak - 1, rs[peak]), rs[peak], rs.get(peak + 1, rs[peak])
    d = y0 - 2 * y1 + y2
    frac = 0.5 * (y0 - y2) / d if d < 0 else 0.0
    return peak + max(-0.5, min(0.5, frac)), best


def _read(samples: list[float], t: float) -> float:
    """Linear interpolation at fractional index T (clamped to the sample)."""
    if t <= 0:
        return samples[0]
    i = int(t)
    if i >= len(samples) - 1:
        return samples[-1]
    f = t - i
    return samples[i] + (samples[i + 1] - samples[i]) * f


def _rising_zero(samples: list[float], at: int, span: int) -> int:
    """The rising zero crossing nearest AT within +-SPAN, or AT."""
    best, dist = at, span + 1
    for k in range(max(1, at - span), min(len(samples) - 1, at + span)):
        if samples[k - 1] < 0.0 <= samples[k] and abs(k - at) < dist:
            best, dist = k, abs(k - at)
    return best


def cycle(samples: list[float], start: float, length: float, points: int = CYCLE) -> list[float]:
    """LENGTH samples from START, resampled to POINTS (one cycle), DC removed."""
    out = [_read(samples, start + length * j / points) for j in range(points)]
    m = _mean(out)
    return [v - m for v in out]


def bandlimit(frame: list[float], harmonics: int) -> list[float]:
    amps, phases = factory.analyse(frame, harmonics)
    return factory.additive(amps, phases, len(frame))


def slice_samples(samples: list[float], rate: int, mode: str = "auto", window: int | None = None,
                  frames: int = FRAMES, harmonics: int = factory.HARMONICS) -> tuple[list[list[float]], dict]:
    """-> (FRAMES frames of CYCLE floats, normalised to a peak of 1, a report)."""
    if mode not in ("auto", "pitch", "window"):
        raise WavetableError(f"unknown mode {mode!r}")
    n = len(samples)
    window = window or DEFAULT_WINDOW
    if n < 64:
        raise WavetableError("the sample is too short to slice")
    # trim leading and trailing near-silence, so the frames are spread over the sound
    peak = max(abs(v) for v in samples) or 1.0
    loud = [k for k, v in enumerate(samples) if abs(v) > 0.01 * peak]
    a, b = (loud[0], loud[-1] + 1) if loud else (0, n)
    body = samples[a:b] if b - a >= 64 else samples
    n = len(body)
    out, used = [], []
    for k in range(frames):
        centre = int((k + 0.5) * n / frames)
        period, clarity = (None, 0.0)
        if mode in ("auto", "pitch"):
            period, clarity = period_at(body, rate, centre)
        if period is None and mode == "pitch":
            raise WavetableError(f"no clear pitch near {centre / rate:.2f} s (clarity "
                                 f"{clarity:.2f}); try --mode window")
        if period is not None:
            start = _rising_zero(body, int(centre - period / 2), int(period / 2))
            if start + period >= n:
                start = max(0, int(n - period - 1))
            out.append(cycle(body, start, period))
            used.append(("pitch", round(rate / period, 1), round(clarity, 2)))
        else:
            w = min(window, n)
            start = max(0, min(n - w, centre - w // 2))
            out.append(cycle(body, start, w))
            used.append(("window", w, round(clarity, 2)))
    out = [bandlimit(f, harmonics) for f in out]
    top = max(abs(v) for f in out for v in f)
    if top <= 0:
        raise WavetableError("the sample is silent")
    out = [[v / top for v in f] for f in out]
    report = {"rate": rate, "samples": len(samples), "trimmed": (a, b), "frames": used,
              "mode": mode, "window": window, "harmonics": harmonics}
    return out, report


def slice_wav(data: bytes, mode: str = "auto", window: int | None = None, frames: int = FRAMES,
              harmonics: int = factory.HARMONICS) -> tuple[list[list[float]], dict]:
    samples, _ = parse_wav(data)
    return slice_samples(samples, wav_rate(data), mode, window, frames, harmonics)


def wav_bytes(frames: list[list[float]], rate: int = 48000) -> bytes:
    """A float32 mono wavetable WAV, frames back to back, with a `clm ` chunk naming
    the frame length (the convention Serum and Vital write)."""
    data = b"".join(struct.pack("<%df" % len(f), *f) for f in frames)
    clm = f"<!>{len(frames[0])} 00000000 wavetable (dnfw)".encode()
    clm += b"\0" * (len(clm) & 1)
    fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"clm " + struct.pack("<I", len(clm)) + clm
            + b"data" + struct.pack("<I", len(data)) + data)
    return b"RIFF" + struct.pack("<I", len(body)) + body

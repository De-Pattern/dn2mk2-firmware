"""Original test samples for the ONESHOT port, synthesised here. No Elektron data.

Two shapes, chosen so that each play mode is measurable, not just audible:

- `chirp`: an exponential sweep 220 -> 1760 Hz under a decay from full scale to
  -20 dB. Played forward the pitch rises and the level falls; played in
  reverse both run the other way, so a reversed render is told from a forward
  one by its envelope slope and its zero-crossing rate, block by block.
- `saw`: a 12-harmonic band-limited sawtooth at exactly 120 Hz (400 samples a
  period) over 12 whole periods, so a loop over any whole number of periods is
  seamless and a loop that is not shows up as a step.

Both are 48 kHz, int16 (Q15), mono.
"""

from __future__ import annotations

import math

RATE = 48000


def chirp(n: int = 7200, f0: float = 220.0, f1: float = 1760.0, amp: float = 0.9) -> list[int]:
    out, phase = [], 0.0
    k = math.log(f1 / f0) / n
    for i in range(n):
        f = f0 * math.exp(k * i)
        phase += 2 * math.pi * f / RATE
        env = amp * 10 ** (-1.0 * i / n)                     # 0 dB -> -20 dB over the sample
        out.append(_q15(env * math.sin(phase)))
    return out


def saw(periods: int = 12, f: float = 120.0, harmonics: int = 12, amp: float = 0.5) -> list[int]:
    n = round(periods * RATE / f)
    norm = sum(1 / h for h in range(1, harmonics + 1))
    return [_q15(amp / norm * sum(math.sin(2 * math.pi * f * h * i / RATE) / h
                                  for h in range(1, harmonics + 1)))
            for i in range(n)]


def to_float(pcm: list[int]) -> list[float]:
    return [v / 32768.0 for v in pcm]


def _q15(x: float) -> int:
    return max(-32768, min(32767, round(x * 32768)))

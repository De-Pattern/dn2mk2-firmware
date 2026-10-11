"""Waverider's factory tables: an original set, generated here, no Elektron data.

W5 (`docs/w5-tables.md`). Slots 0 and 1 stay the two tables Milestone 5 shipped
(`testtable`, `harmonics`), so a sound saved on an earlier build keeps its sound;
the rest are new. Every table is 16 frames, each frame a single cycle, and every
frame is **band-limited**: built from at most `HARMONICS` partials, so a high note
does not fold its top partials back down as noise. Waverider's reader has no
mip-mapping, so this is where aliasing is controlled.

A table built from a "naive" waveform (a hard-synced saw, a folded sine, a
staircase) is the naive cycle sampled finely, analysed into partials, and the
first `HARMONICS` resynthesised -- the band-limited version of that shape.

`TABLES` is the order of the TBL control. Names are four characters, for the page.
The user's own WAVs go in the same way (`dnfw waverider bake`), and are added at
apply time on the user's machine; this module is only the default set.

Pure Python, no dependencies, deterministic (the random table is seeded).
"""

from __future__ import annotations

import math
import random

from . import harmonics, reduce, testtable

FRAMES = reduce.FRAMES            # 16
POINTS = reduce.POINTS            # 512
HARMONICS = 48                    # partials kept; 48 x a C5 (523 Hz) is 25 kHz
ANALYSIS = 2048                   # points a naive cycle is sampled at for analysis

TWO_PI = 2.0 * math.pi


# -- building blocks --------------------------------------------------------------------

def additive(amps: list[float], phases: list[float] | None = None,
             points: int = POINTS) -> list[float]:
    """One cycle from partials: amps[h-1] is partial h's amplitude (sine phase, plus
    phases[h-1] radians if given)."""
    out = [0.0] * points
    for h, a in enumerate(amps, start=1):
        if a == 0.0:
            continue
        ph = phases[h - 1] if phases else 0.0
        w = TWO_PI * h / points
        for n in range(points):
            out[n] += a * math.sin(w * n + ph)
    return out


def analyse(cycle: list[float], harmonics_kept: int = HARMONICS) -> tuple[list[float], list[float]]:
    """-> (amps, phases) of partials 1..H of a sampled cycle (a DFT, DC dropped)."""
    n = len(cycle)
    amps, phases = [], []
    for h in range(1, harmonics_kept + 1):
        w = TWO_PI * h / n
        re = sum(cycle[k] * math.cos(w * k) for k in range(n))
        im = sum(cycle[k] * math.sin(w * k) for k in range(n))
        # cycle ~ sum a sin(wk + ph) = a cos(ph) sin + a sin(ph) cos
        s, c = 2.0 * im / n, 2.0 * re / n
        amps.append(math.hypot(s, c))
        phases.append(math.atan2(c, s))
    return amps, phases


def bandlimited(naive) -> list[float]:
    """naive(x), x in [0, 1) one cycle -> the band-limited 512-point frame."""
    cycle = [naive(k / ANALYSIS) for k in range(ANALYSIS)]
    amps, phases = analyse(cycle)
    return additive(amps, phases)


def frames_of(make) -> list[list[float]]:
    """make(t), t = 0..1 across the table -> 16 float frames."""
    return [make(k / (FRAMES - 1)) for k in range(FRAMES)]


def saw_amps(h_max: int = HARMONICS) -> list[float]:
    return [((-1) ** (h + 1)) * 2.0 / (math.pi * h) for h in range(1, h_max + 1)]


# -- the tables -------------------------------------------------------------------------

def pwm(t: float) -> list[float]:
    """Pulse, width 50 % -> 95 %."""
    d = 0.5 + 0.45 * t
    return bandlimited(lambda x: 1.0 if x < d else -1.0)


def sync(t: float) -> list[float]:
    """A saw hard-synced to the cycle, the slave 1x -> 5x the master."""
    r = 1.0 + 4.0 * t
    return bandlimited(lambda x: 2.0 * ((x * r) % 1.0) - 1.0)


VOWELS = {             # (F1, F2, F3) Hz, rounded textbook averages
    "A": (800, 1150, 2900), "E": (400, 2000, 2550), "I": (300, 2300, 3000),
    "O": (450, 800, 2830), "U": (325, 700, 2530),
}


def vox(t: float) -> list[float]:
    """Vowels A -> E -> I -> O -> U, as formant envelopes over a 110 Hz harmonic
    series (the timbre is the vowel's at A2; transposed, it shifts, like a real voice
    played back faster)."""
    order = "AEIOU"
    x = t * (len(order) - 1)
    i = min(int(x), len(order) - 2)
    f = x - i
    fa, fb = VOWELS[order[i]], VOWELS[order[i + 1]]
    formants = [a + (b - a) * f for a, b in zip(fa, fb)]
    widths, gains = (90.0, 110.0, 160.0), (1.0, 0.5, 0.25)
    amps = []
    for h in range(1, HARMONICS + 1):
        fh = 110.0 * h
        e = sum(g / (1.0 + ((fh - fc) / bw) ** 2) for fc, bw, g in zip(formants, widths, gains))
        amps.append(e / h ** 0.3)
    return additive(amps)


def fm(t: float) -> list[float]:
    """Two-operator FM, ratio 1:1, index 0 -> 6."""
    i = 6.0 * t
    return bandlimited(lambda x: math.sin(TWO_PI * x + i * math.sin(TWO_PI * x)))


def fold(t: float) -> list[float]:
    """A sine through a wavefolder, gain 1 -> 6."""
    g = 1.0 + 5.0 * t
    return bandlimited(lambda x: math.sin(g * math.sin(TWO_PI * x)))


DRAWBARS = (           # 16', 8', 5 1/3', 4', 2 2/3', 2' as partials 1, 2, 3, 4, 6, 8
    (8, 8, 0, 0, 0, 0), (8, 8, 8, 0, 0, 0), (8, 6, 8, 4, 0, 3),
    (8, 8, 8, 8, 6, 6), (6, 8, 4, 8, 8, 8), (4, 6, 8, 8, 8, 8),
)


def organ(t: float) -> list[float]:
    """Drawbar registrations, mellow -> full, crossfaded."""
    partials = (1, 2, 3, 4, 6, 8)
    x = t * (len(DRAWBARS) - 1)
    i = min(int(x), len(DRAWBARS) - 2)
    f = x - i
    amps = [0.0] * HARMONICS
    for p, a, b in zip(partials, DRAWBARS[i], DRAWBARS[i + 1]):
        amps[p - 1] = (a + (b - a) * f) / 8.0
    return additive(amps)


def reso(t: float) -> list[float]:
    """A saw with a resonant peak sweeping from partial 2 to partial 32."""
    peak = 2.0 + 30.0 * t
    amps = [a * (0.35 + 3.0 / (1.0 + ((h - peak) / 1.5) ** 2))
            for h, a in enumerate(saw_amps(), start=1)]
    return additive([abs(a) for a in amps])


def bits(t: float) -> list[float]:
    """A sine quantised to 32 -> 2 levels: the staircase, band-limited."""
    levels = max(2, round(32 * (1.0 - t) ** 2 + 2 * t))
    q = lambda v: round((v + 1.0) / 2.0 * (levels - 1)) / (levels - 1) * 2.0 - 1.0   # noqa: E731
    return bandlimited(lambda x: q(math.sin(TWO_PI * x)))


def phase(t: float) -> list[float]:
    """Phase distortion: a cosine read through a bent phase (knee 0.5 -> 0.03),
    sine-like -> a resonant, saw-like sweep."""
    k = 0.5 - 0.47 * t

    def pd(x: float) -> float:
        p = x / (2 * k) if x < k else 0.5 + (x - k) / (2 * (1 - k))
        return -math.cos(TWO_PI * p)
    return bandlimited(pd)


def spectra(t: float, seed: int = 0x57A7) -> list[float]:
    """Four random spectra, each 1/h-weighted, crossfaded in turn (seeded)."""
    rng = random.Random(seed)
    sets = [[rng.random() / h ** 0.8 for h in range(1, HARMONICS + 1)] for _ in range(4)]
    x = t * 3
    i = min(int(x), 2)
    f = x - i
    return additive([a + (b - a) * f for a, b in zip(sets[i], sets[i + 1])])


# order of the TBL control; (name, builder) -- builders return 16 float frames,
# except the first two, which are the M5 tables as they were
TABLES = (
    ("PRIM", None), ("HARM", None),
    ("PWM ", lambda: frames_of(pwm)), ("SYNC", lambda: frames_of(sync)),
    ("VOX ", lambda: frames_of(vox)), ("FM  ", lambda: frames_of(fm)),
    ("FOLD", lambda: frames_of(fold)), ("ORGN", lambda: frames_of(organ)),
    ("RESO", lambda: frames_of(reso)), ("BITS", lambda: frames_of(bits)),
    ("PHAS", lambda: frames_of(phase)),
)
# Built but not in the default set: it does not fit the DSP upload budget beside the
# others (docs/w5-tables.md, "Budget"). A user set can include it.
EXTRA = (("SPEC", lambda: frames_of(spectra)),)


def names(count: int | None = None) -> list[str]:
    return [n.strip() for n, _ in TABLES[:count]]


def tables(count: int | None = None) -> list[list[list[int]]]:
    """-> the first `count` tables (all by default), each 16 x 512 int16."""
    out = []
    for name, build in TABLES[:count]:
        if name == "PRIM":
            out.append(list(reversed(testtable.table())))   # saw -> sine, as M5 shipped it
        elif name == "HARM":
            out.append(harmonics.table())
        else:
            out.append(reduce.to_int16(build()))
    return out

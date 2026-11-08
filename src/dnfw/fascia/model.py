"""FASCIA, the sound: the design model, chosen by ear (docs/fascia.md).

Two exciters feed two modal bodies, which interact (XMOD, COUP, FDBK, BUZZ). BOW and
BLOW are driven: their force depends on the body's own motion at every sample (friction,
a reed), so they bow and blow rather than replay noise. After the bodies: an unresonated
click (CLIK, CTYP), through-zero FM sidebands, ring modulation, frequency shift, a moving
formant, a folder, the LPG and CHAR. This is the reference the DSP code will be held to: float64, offline,
block-wise like the DSP (32 samples, coefficients once a block). `fascia/live.py` will be
the DSP-order float32 contract, like `rings/live.py` and `perc/live.py` before it.

Controls are 0..127, as on the panel (`PAGES`). Choice controls take an index
(`TYPES`, `BODIES`). A voice is one note: `Voice(params, note, vel).render(seconds)`.
`render_notes` mixes several voices, for chords and patterns.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import hilbert, lfilter

RATE = 48000.0
BLOCK = 32
MODES = 16
IDLE = 1.0e-5                    # a block that peaks under this, exciters done: the voice ends
OUT = 0.5                        # a full-velocity impulse's body peak, about
# Each exciter's level into the bodies, so every type lands near OUT (sustained ones drive
# the modes at their own pitch and build up; measured, scripts/fascia_audition.py).
TYPE_GAIN = {"STRIKE": 1.0, "BLOW": 0.04, "BOW": 0.06, "DUST": 3.5, "PULSE": 0.03, "TZFM": 0.015}
LIMIT = (0.7, 0.001, 0.12)       # the voice's level guard: threshold, attack s, release s

TYPES = ("STRIKE", "BLOW", "BOW", "DUST", "PULSE", "TZFM")
CLICKS = ("SNAP", "TICK", "NOISE", "THUMP")
XMODS = ("EXCITE", "BEND", "CHOKE", "TRADE")
BODIES = ("MEMB", "PLATE", "BAR", "VIBE", "CHIME", "BELL", "GLASS", "TUBE", "STRING", "OFF")  # OFF: B only

PAGES = {
    "SYN1 EXCITERS": ("TYPA", "TYPB", "HARD", "DUST", "TZFM", "BEND", "MIX", "DEC"),
    "SYN2 RESONATORS": ("BODA", "BODB", "TUNE", "GEOM", "MATL", "POS", "COUP", "DAMP"),
    "SYN3 SPECTRAL": ("MORPH", "FORM", "SHIFT", "RING", "SIDE", "FOLD", "LPG", "CHAR"),
    "SYN4 ONSET/INTERACT": ("ATK", "CLIK", "CTYP", "XMOD", "FDBK", "BUZZ", "WATR", "VARY"),
}
CHOICES = {"TYPA": TYPES, "TYPB": TYPES, "BODA": BODIES[:-1], "BODB": BODIES,
           "CTYP": CLICKS, "XMOD": XMODS}

DEFAULTS = {
    "TYPA": 0, "TYPB": 1, "HARD": 90, "DUST": 20, "TZFM": 0, "BEND": 10, "MIX": 30, "DEC": 20,
    "BODA": 0, "BODB": 121, "TUNE": 64, "GEOM": 64, "MATL": 50, "POS": 40, "COUP": 0, "DAMP": 60,
    "MORPH": 0, "FORM": 0, "SHIFT": 64, "RING": 0, "SIDE": 40, "FOLD": 0, "LPG": 40, "CHAR": 0,
    "ATK": 0, "CLIK": 0, "CTYP": 0, "XMOD": 0, "FDBK": 0, "BUZZ": 0, "WATR": 0, "VARY": 40,
}
EXTRA = ()                       # controls not on a page (none)

def _plate(aspect: float = 1.31, n: int = 16):
    fs = sorted((m / 1.0) ** 2 + (k / aspect) ** 2 for m in range(1, 8) for k in range(1, 8))
    return tuple(f / fs[0] for f in fs[:n])


def _bar(n: int = 16):
    """Free-free bar: beta_k L = 4.730, 7.853, then about (k + 1/2) pi."""
    b = [4.7300, 7.8532, 10.9956, 14.1372] + [(k + 0.5) * math.pi for k in range(5, n + 1)]
    return tuple((x / b[0]) ** 2 for x in b[:n])


def _glass(n: int = 16):
    """A glass bowl (or a thin bell's ring modes): f_n ~ n (n^2 - 1) / sqrt(n^2 + 1)."""
    f = [m * (m * m - 1) / math.sqrt(m * m + 1) for m in range(2, n + 2)]
    return tuple(x / f[0] for x in f)


# Mode-frequency ratios, sixteen a body, scaled so the note is the pitch you hear:
#   MEMB   an ideal circular membrane's Bessel zeros (drums, tablas, toms, plonk)
#   PLATE  a rectangular plate (aspect 1.31): dense, gongs, sheets, cymbals
#   BAR    a free-free bar: glockenspiel, kalimba-like tines, wood or metal bars
#   VIBE   a tuned bar, partials 1 : 4 : 10 (vibraphone, marimba), torsional modes beside
#   CHIME  a tube struck at its end (tubular bell, wind chime): a free-free bar heard at
#          its strike note, the missing fundamental of modes 4..6 (about 4.47 x mode 1)
#   BELL   a tuned church bell: hum, prime, tierce, quint, nominal ... (measured ratios)
#   GLASS  a glass bowl or wine glass: sparse, high, pure
#   TUBE   an air column closed at one end: odd harmonics, hollow
#   STRING harmonics (GEOM adds stiffness)
_B = _bar()
RATIOS = {
    "MEMB": (1.000, 1.594, 2.136, 2.296, 2.653, 2.918, 3.156, 3.501, 3.600, 3.652, 4.060,
             4.154, 4.230, 4.601, 4.832, 4.903),
    "PLATE": _plate(),
    "BAR": _B,
    "VIBE": (1.0, 2.86, 4.0, 6.6, 10.0, 11.9, 17.6, 18.9, 27.4, 31.0, 39.2, 45.0, 53.0,
             60.0, 69.0, 79.0),
    "CHIME": tuple(r / 4.47 for r in _B),
    "BELL": (0.5, 1.0, 1.183, 1.506, 2.0, 2.514, 2.662, 3.011, 4.166, 5.433, 6.796, 8.215,
             9.75, 11.3, 12.9, 14.5),
    "GLASS": _glass(),
    "TUBE": tuple(float(2 * k + 1) for k in range(16)),
    "STRING": tuple(float(k + 1) for k in range(16)),
}
# How each mode's spatial frequency follows its pitch (for POS): sqrt for 2-D bodies and
# bars (f ~ k^2), linear for strings and air columns.
SPATIAL = {"MEMB": 0.5, "PLATE": 0.5, "BAR": 0.5, "VIBE": 0.5, "CHIME": 0.5, "BELL": 0.5,
           "GLASS": 0.5, "TUBE": 1.0, "STRING": 1.0}
# Round and symmetric bodies split each mode into a near-degenerate pair: the slow beating
# that makes bells, glasses, chimes and plates shimmer instead of sounding like filters.
SPLIT = {"MEMB": 0.0008, "PLATE": 0.0015, "BAR": 0.0, "VIBE": 0.0, "CHIME": 0.0003,
         "BELL": 0.0020, "GLASS": 0.0025, "TUBE": 0.0, "STRING": 0.0004}
# The fastest a twin pair may beat, Hz: real bells and glasses beat slowly (a second or so);
# fast beating on the high modes reads as a quiver, not shimmer (owner, 2026-11-07: the
# first tubular bell's "quivering weird thing").
BEAT_MAX = {"MEMB": 4.0, "PLATE": 3.0, "BAR": 0.0, "VIBE": 0.0, "CHIME": 0.8, "BELL": 1.5,
            "GLASS": 1.2, "TUBE": 0.0, "STRING": 1.0}
# Per-mode level weights where an object's lowest modes are weak: a tubular bell's modes
# 1..3 are faint and short beside its strike-note modes 4..6.
MODE_WEIGHT = {"CHIME": (0.08, 0.18, 0.45)}
# Each body's own material lean (added to MATL): bells, glass and chimes ring.
RING_BIAS = {"MEMB": -0.15, "PLATE": 0.05, "BAR": 0.0, "VIBE": 0.15, "CHIME": 0.2,
             "BELL": 0.25, "GLASS": 0.3, "TUBE": 0.0, "STRING": 0.1}
# Body B's pitch against A's: fixed by B's type (owner, 2026-11-07: we fine-tune the
# interval so a pairing sounds musical at once; the patching stays free). Each is the
# interval that type is usually paired at:
#   TUBE 1:1    a marimba or vibraphone's resonator tube is tuned to its bar
#   STRING 1:1  sympathetic strings ring at the note
#   MEMB 3:2    a second drumhead a fifth up (tom stacks, talking-drum pairs)
#   GLASS 4:3   glasses a fourth apart
#   CHIME 3:2   wind chimes are tuned in fifths
#   PLATE, VIBE, BELL 2:1   an octave up: a smaller plate, bar or bell
#   BAR 2.756   the free bar's own second mode: B reinforces A's overtone
B_RATIO = {"MEMB": 1.4983, "PLATE": 2.0, "BAR": 2.756, "VIBE": 2.0, "CHIME": 1.4983, "BELL": 2.0,
           "GLASS": 1.3348, "TUBE": 1.0, "STRING": 1.0}

VOWELS = ((730, 1090), (530, 1840), (270, 2290), (570, 840), (300, 870))  # a e i o u


def u(v: int) -> float:
    """A 0..127 control as 0..1."""
    return min(max(v, 0), 127) / 127.0


def expmap(v: int, lo: float, hi: float) -> float:
    return lo * (hi / lo) ** u(v)


def choice(name: str, v: int) -> int:
    """The option a 0..127 value picks: equal spans (the panel's 4-detent stepping maps
    each option to its own span, docs/fascia.md)."""
    n = len(CHOICES[name])
    return min(int(min(max(v, 0), 127) * n / 128), n - 1)


def mtof(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


class Body:
    """A modal body: up to MODES modes (each a damped two-pole resonator,
    y = 2 r cos w y1 - r^2 y2 + g x), a near-degenerate twin per mode where the body is
    round, a per-hit variation of a few cents and a decibel or so, and a slow drift of the
    modes while it rings (both scaled by VARY), so repeated hits sound like one object
    struck again, not a sample replayed."""

    def __init__(self, kind: str, f0: float, modes: int = MODES, seed: int = 1, vary: float = 1.0):
        self.kind, self.f0, self.vary = kind, f0, vary
        self.rng = np.random.default_rng(seed)
        rng = self.rng
        base = np.array(RATIOS[kind][:modes])
        k = np.arange(len(base))
        jit = 1.0 + rng.normal(0.0, 0.0012, len(base)) * (1 + 0.15 * k) * vary
        jit[0] = 1.0 + (jit[0] - 1.0) * 0.2                     # the pitch stays the pitch
        aj = np.exp(rng.normal(0.0, 0.10, len(base)) * vary)
        for i, wgt in enumerate(MODE_WEIGHT.get(kind, ())):
            if i < len(aj):
                aj[i] *= wgt
        split = SPLIT[kind]
        offs = np.zeros(len(base))
        if split:
            beat = np.minimum(f0 * base * split * (0.6 + 0.8 * rng.random(len(base))), BEAT_MAX[kind])
            offs = np.concatenate([offs, np.maximum(beat, 0.15)])
            base = np.concatenate([base * jit, base * jit])
            aj = np.concatenate([aj, aj * (0.5 + 0.5 * rng.random(len(aj)))])
        else:
            base = base * jit
        self.base, self.aj, self.offs = base, aj, offs
        self.n = len(base)
        self.y1 = np.zeros(self.n)
        self.y2 = np.zeros(self.n)
        self.drift = np.zeros(self.n)
        self.peak = 1e-9                                         # for the tension glide
        self.level = 1.0
        self.ratio = base

    def coeffs(self, geom_e: float, bend: float, t60: float, matl: float,
               lpg_loss: float, pos: float, tilt: float):
        # the slow drift: a leaky random walk, a few cents at most (VARY)
        self.drift = self.drift * 0.995 + self.rng.normal(0.0, 1.5e-5 * self.vary, self.n)
        ratio = self.base ** geom_e * (1.0 + self.drift)
        self.ratio = ratio
        f = self.f0 * ratio * bend + self.offs              # twins: a few tenths of a Hz to a few Hz up
        alive = (f < 0.45 * RATE) & (f > 15.0)
        f = np.clip(f, 15.0, 0.45 * RATE)
        w = 2 * math.pi * f / RATE
        # MATL's damping curve: losses rising with frequency (air, internal friction);
        # wood and plasticine lose their highs fast, metal and glass keep them
        m = min(max(matl + RING_BIAS[self.kind], 0.0), 1.0)
        a1, a2 = 4.0 * (1 - m) ** 2 + 0.015, 2.0 * (1 - m) ** 3 + 0.002
        fk = f / 1000.0
        t60k = t60 / (1.0 + a1 * fk + a2 * fk * fk) / (1.0 + lpg_loss * (ratio - 1.0).clip(0))
        r = 10.0 ** (-3.0 / (np.maximum(t60k, 1e-3) * RATE))
        sp = ratio ** SPATIAL[self.kind]
        shape = np.abs(np.sin(math.pi * sp * pos)) * ratio ** (-0.7 * tilt) * self.aj
        amp = shape * alive
        amp = amp * (OUT / max(float(np.sum(shape)), 1e-6))
        return w, r, amp

    def _done(self, out: np.ndarray) -> np.ndarray:
        pk = float(np.max(np.abs(out))) if len(out) else 0.0
        self.peak = max(self.peak, pk)
        self.level = pk / self.peak
        return out

    def block(self, x: np.ndarray, w, r, amp, og=None) -> np.ndarray:
        """A block driven by a known input. OG: each mode's output weight (MORPH)."""
        out = np.zeros_like(x)
        for m in range(self.n):
            if amp[m] == 0.0 and self.y1[m] == 0.0 and self.y2[m] == 0.0:
                continue
            a1, a2 = -2.0 * r[m] * math.cos(w[m]), r[m] * r[m]
            b0 = amp[m] * math.sin(w[m])
            zi = np.array([-a1 * self.y1[m] - a2 * self.y2[m], -a2 * self.y1[m]])
            y, _ = lfilter([b0], [1.0, a1, a2], x, zi=zi)
            self.y2[m], self.y1[m] = (y[-2], y[-1]) if len(y) > 1 else (self.y1[m], y[-1])
            out += y * (1.0 if og is None else og[m])
        return self._done(out)

    def block_driven(self, force, x: np.ndarray, w, r, amp, og=None) -> np.ndarray:
        """A block whose input depends on the body's own motion, sample by sample:
        FORCE(j, v) is the drive at sample j given the body's velocity v at the contact
        point (the modes' velocities weighted by how much each moves there)."""
        a1 = 2.0 * r * np.cos(w)
        a2 = r * r
        b0 = amp * np.sin(w)
        phi = amp / (OUT / 4.0)                                  # each mode's share at the contact
        y1, y2 = self.y1.copy(), self.y2.copy()
        gw = np.ones(self.n) if og is None else og
        out = np.zeros(len(x))
        for j in range(len(x)):
            v = float(np.dot(phi, y1 - y2)) * 40.0
            f = force(j, v) + x[j]
            y = a1 * y1 - a2 * y2 + b0 * f
            y2, y1 = y1, y
            out[j] = float(np.dot(gw, y))
        self.y1, self.y2 = y1, y2
        return self._done(out)

    def energy(self) -> float:
        return float(np.max(np.abs(self.y1)) + np.max(np.abs(self.y2)))


def bow_table(dv: float, slope: float) -> float:
    """Friction against relative velocity: high near sticking, falling as it slips (the
    usual hyperbolic bow curve). Returns force for a relative velocity dv."""
    x = dv * slope
    k = (abs(x) + 0.75) ** -4
    return dv * min(max(k * 0.25, 0.0025), 0.245)


class Exciter:
    """One exciter. STRIKE, DUST, PULSE and TZFM render their whole excitation at the
    note. BOW and BLOW render envelopes only (pressure, bow speed, breath, rosin grit):
    the voice drives the body with them sample by sample (`Voice.force`)."""

    DRIVEN = ("BOW", "BLOW")

    def __init__(self, kind: str, p: dict, f0: float, vel: float, seed: int):
        self.kind, self.p, self.f0, self.vel = kind, p, f0, vel
        self.rng = np.random.default_rng(seed)
        hard = u(p["HARD"]) * (0.5 + 0.5 * vel)          # velocity -> hardness
        self.width = 4.0e-3 * (0.0125 ** hard)            # 4 ms soft .. 0.05 ms hard
        self.dec = expmap(p["DEC"], 0.004, 2.0)           # the excitation's length, s
        self.atk = expmap(p["ATK"], 0.0002, 0.5) if p["ATK"] > 0 else 0.0   # the onset, s
        self.press = None
        self.sig = self._make()

    def _pulse(self, width: float) -> np.ndarray:
        """A raised-cosine pulse: band-limited, so a very hard strike snaps, not aliases."""
        n = max(int(width * RATE), 2)
        pl = 0.5 - 0.5 * np.cos(2 * math.pi * np.arange(n) / n)
        return pl / pl.sum()                    # unit area: a low mode rings as from an impulse

    def _env(self, n: int, tau: float) -> np.ndarray:
        return np.exp(-np.arange(n) / (tau * RATE))

    def _onset(self, n: int) -> np.ndarray:
        """ATK for a driven exciter: the pressure's rise, instant .. half a second."""
        if not self.atk:
            return np.minimum(np.arange(n) / (0.002 * RATE), 1.0)
        t = np.arange(n) / RATE
        return 1.0 - np.exp(-t / (self.atk / 3.0))

    def _make(self) -> np.ndarray:
        p, k, f0 = self.p, self.kind, self.f0
        n = int((self.dec * 4 + 0.01 + self.atk) * RATE)
        t = np.arange(n) / RATE
        x = np.zeros(n)
        if k == "STRIKE":
            pl = self._pulse(self.width)
            x[: len(pl)] += pl
            # contact noise: DUST adds texture to the impact, over DEC
            nz = self.rng.standard_normal(n) * self._env(n, self.dec * 0.25)
            x += nz * 0.15 * u(p["DUST"])
        elif k == "BLOW":
            # breath: mouth pressure (DEC holds it), turbulence (brighter with HARD); the
            # reed in Voice.force turns pressure against the body's motion into flow
            hold = np.exp(-np.maximum(t - self.dec, 0) / 0.06)
            self.press = self._onset(n) * hold * (0.4 + 0.6 * self.vel)
            nz = self.rng.standard_normal(n)
            cut = 400.0 * 30.0 ** u(p["HARD"])
            a = math.exp(-2 * math.pi * cut / RATE)
            self.breath = lfilter([1 - a], [1, -a], nz) * (0.3 + 0.7 * u(p["DUST"]))
            return np.zeros(n)
        elif k == "BOW":
            # the bow: speed and pressure under DEC's hold; DUST is rosin grit (the bow
            # sticking on rosin in micro-catches), HARD the pressure: light = airy, flautando;
            # heavy = a scrape, over-pressure crunch
            hold = np.exp(-np.maximum(t - self.dec, 0) / 0.08)
            self.press = self._onset(n) * hold * (0.2 + 0.8 * self.vel)
            self.speed = 0.25 + 0.15 * np.sin(2 * math.pi * 0.7 * t + self.rng.random() * 6)
            grit = self.rng.random(n) < expmap(p["DUST"], 20.0, 4000.0) / RATE
            self.grit = lfilter([1.0], [1.0, -0.6], grit * self.rng.uniform(-1, 1, n)) * u(p["DUST"])
            return np.zeros(n)
        elif k == "DUST":
            dens = expmap(p["DUST"], 5.0, 3000.0) * (0.5 + self.vel)
            ev = self.rng.random(n) < dens / RATE * self._env(n, self.dec)
            pl = self._pulse(max(self.width, 1e-4))
            amps = self.rng.uniform(-1, 1, n) * ev / math.sqrt(max(dens * self.dec, 1.0) / 4.0)
            x = np.convolve(amps, pl)[:n]
        elif k == "PULSE":
            pitch = f0 * 2.0 * 2.0 ** (u(p["BEND"]) * 3 * np.exp(-t / 0.01))
            ph = np.cumsum(pitch) / RATE
            x = np.sin(2 * math.pi * ph) * self._env(n, self.dec * 0.3)
        elif k == "TZFM":
            x = self.tzfm(n, max(u(p["TZFM"]), 0.15), self.dec)
        # any exciter: TZFM adds a through-zero sideband burst at the attack
        if p["TZFM"] > 0 and k != "TZFM":
            x = x + self.tzfm(n, u(p["TZFM"]), min(self.dec, 0.03)) * TYPE_GAIN["TZFM"] / TYPE_GAIN[k]
        if self.atk:
            # ATK on an impulsive exciter: the hit smeared over a rising window of ATK (a
            # soft swell instead of a strike), its area kept
            m = max(int(self.atk * RATE), 2)
            win = np.linspace(0.0, 1.0, m) ** 2
            x = np.convolve(x, win / win.sum())[:n]
        return x * self.vel * TYPE_GAIN[k]

    def tzfm(self, n: int, depth: float, tau: float) -> np.ndarray:
        """Through-zero linear FM: the carrier's increment is signed, so a deep index
        runs the phase backwards (f_inst = fc + I fc m(t), m the modulator)."""
        t = np.arange(n) / RATE
        ratio = 0.5 + 6.5 * u(self.p["SIDE"]) ** 1.5       # SIDE: where the sidebands fall
        m = np.sin(2 * math.pi * self.f0 * ratio * t)
        index = depth * 6.0 * np.exp(-t / tau)
        inc = (self.f0 + index * self.f0 * ratio * m) / RATE   # may go negative
        ph = np.cumsum(inc)
        return np.sin(2 * math.pi * ph) * np.exp(-t / (tau * 3 + 0.005))


def click(kind: str, hard: float, rng) -> np.ndarray:
    """CLIK's transient, straight to the output (not through the bodies): the snap of the
    contact itself. SNAP a band-limited crack, TICK a 1 ms high blip, NOISE a short
    bright burst, THUMP a low knock. HARD shortens and brightens it."""
    if kind == "SNAP":
        n = max(int((0.00015 + 0.0006 * (1 - hard)) * RATE), 3)
        pl = 0.5 - 0.5 * np.cos(2 * math.pi * np.arange(n) / n)
        x = np.diff(np.concatenate([[0.0], pl, [0.0]])) * n * 0.35
    elif kind == "TICK":
        n = int(0.004 * RATE)
        t = np.arange(n) / RATE
        x = np.sin(2 * math.pi * (2500 + 3000 * hard) * t) * np.exp(-t / (0.0004 + 0.0008 * (1 - hard)))
    elif kind == "NOISE":
        n = int(0.012 * RATE)
        t = np.arange(n) / RATE
        nz = np.diff(np.concatenate([[0.0], rng.standard_normal(n)]))
        x = nz * np.exp(-t / (0.0008 + 0.003 * (1 - hard))) * 0.5
    else:                                            # THUMP
        n = int(0.06 * RATE)
        t = np.arange(n) / RATE
        ph = np.cumsum(40.0 + 50.0 * np.exp(-t / 0.008)) / RATE
        x = np.sin(2 * math.pi * ph) * np.exp(-t / (0.012 + 0.01 * (1 - hard)))
    return x


class Voice:
    def __init__(self, p: dict, note: float, vel: float = 1.0, seed: int = 1, modes: int = MODES):
        self.p = {**DEFAULTS, **p}
        p = self.p
        self.f0 = mtof(note + (p["TUNE"] - 64) * 24 / 64)
        self.vel = vel
        vary = u(p["VARY"]) * 3.2                                          # 40: 1.0
        ka = BODIES[choice("BODA", p["BODA"])]
        kb = BODIES[choice("BODB", p["BODB"])]
        self.a = Body(ka, self.f0, modes, seed=seed * 31 + 3, vary=vary)
        # body B: the interval its type is paired at (B_RATIO; fixed, owner 2026-11-07)
        fb = self.f0 * B_RATIO.get(kb, 1.0)
        self.b = None if kb == "OFF" else Body(kb, fb, modes, seed=seed * 31 + 5, vary=vary)
        ta, tb = TYPES[choice("TYPA", p["TYPA"])], TYPES[choice("TYPB", p["TYPB"])]
        self.ea = Exciter(ta, p, self.f0, vel, seed)
        self.eb = Exciter(tb, p, self.f0, vel, seed + 7919)
        mix = u(p["MIX"])
        self.ga, self.gb = math.cos(mix * math.pi / 2), math.sin(mix * math.pi / 2)
        self.t60 = expmap(127 - p["DAMP"], 0.03, 12.0)                 # DAMP up: shorter
        self.matl = u(p["MATL"])                                         # wood .. metal
        self.pos = 0.02 + 0.48 * u(p["POS"])
        self.hard = u(p["HARD"]) * (0.5 + 0.5 * vel)
        self.tilt = 1.2 * (1.0 - self.hard)                              # soft hits: fewer highs
        self.geom_e = 0.6 + 0.8 * u(p["GEOM"])
        # MORPH: the spectrum's weight moves up the modes while it rings (wood -> glass):
        # each mode's output level, never its frequency, so no pitch ramp (owner, 2026-11-07)
        self.morph = (u(p["MORPH"]) * 1.4, max(self.t60 * 0.35, 0.05))
        # BEND: tension glide. A struck membrane or a soft plonk sounds sharp while it is
        # loud and settles as it rings (pitch follows the body's own level), plus a short
        # contact chirp that harder hits raise
        self.bend = u(p["BEND"]) * 7.0 * (0.4 + 0.6 * vel)              # semitones at full level
        self.chirp = u(p["HARD"]) * vel * 0.6                          # semitones, 4 ms
        self.lpg = u(p["LPG"]) * 6.0
        self.coup = u(p["COUP"])
        self.xmod = XMODS[choice("XMOD", p["XMOD"])]
        self.fdbk = u(p["FDBK"])
        self.buzz = u(p["BUZZ"])
        self.rng = np.random.default_rng(seed * 977 + 11)
        self.clk = None
        if p["CLIK"] > 0:
            ck = CLICKS[choice("CTYP", p["CTYP"])]
            self.clk = click(ck, self.hard, self.rng) * u(p["CLIK"]) * vel * 0.5
        self.end = None                                                 # s, when it went idle

    def _exc(self, i: int, n: int) -> np.ndarray:
        out = np.zeros(n)
        for e, g in ((self.ea, self.ga), (self.eb, self.gb)):
            s = e.sig[i:i + n]
            out[: len(s)] += s * g
        return out

    def _force(self, i: int):
        """The driven exciters' force on body A at sample i + j, given A's velocity v."""
        parts = []
        for e, g in ((self.ea, self.ga), (self.eb, self.gb)):
            if e.press is None or g < 1e-4:
                continue
            if e.kind == "BOW":
                slope = 1.5 + 6.0 * (1.0 - self.hard)                   # light bow: wider slip
                def f(j, v, e=e, g=g):
                    k = i + j
                    if k >= len(e.press):
                        return 0.0
                    pr = e.press[k]
                    dv = e.speed[k] * (1.0 + e.grit[k] * 0.5) - v
                    return bow_table(dv, slope) * pr * 4.0 * g * (0.5 + 1.5 * self.hard)
            else:                                                        # BLOW: a reed
                def f(j, v, e=e, g=g):
                    k = i + j
                    if k >= len(e.press):
                        return 0.0
                    pr = e.press[k] * (1.0 + e.breath[k])
                    dp = pr - v * 0.6
                    flow = dp * max(0.0, 1.0 - abs(dp) * 0.9)           # the reed closes as dp rises
                    return flow * 0.03 * g
            parts.append(f)
        if not parts:
            return None
        return lambda j, v: sum(f(j, v) for f in parts)

    def render(self, seconds: float) -> np.ndarray:
        n = int(seconds * RATE)
        y = np.zeros(n)
        ra = np.zeros(n)
        rb = np.zeros(n)
        driven = any(e.press is not None for e in (self.ea, self.eb))
        exc_len = max(len(self.ea.sig), len(self.eb.sig))
        ob_prev = np.zeros(BLOCK)
        rattle_hp = 0.0
        for i in range(0, n, BLOCK):
            m = min(BLOCK, n - i)
            t = i / RATE
            x = self._exc(i, m)
            ge = self.geom_e
            ch = self.chirp * math.exp(-t / 0.004)
            bend = 2.0 ** ((self.bend * self.a.level + ch) / 12.0)
            g = math.exp(-t / max(self.t60 * 0.25, 0.01))                # the LPG contour
            loss = self.lpg * (1.0 - g)
            # B into A (FDBK, any XMOD; TRADE adds COUP to it): a block late, as on the DSP,
            # bounded by tanh
            back = self.fdbk + (self.coup if self.xmod == "TRADE" else 0.0)
            if self.b is not None and back > 0:
                x = x + np.tanh(ob_prev[:m] * 2.0) * back * 0.08
            wa = self.a.coeffs(ge, bend, self.t60, self.matl, loss, self.pos, self.tilt)
            oga = self._og(self.a, t)
            force = self._force(i) if driven else None
            oa = self.a.block_driven(force, x, *wa, oga) if force else self.a.block(x, *wa, oga)
            # BUZZ: a loose contact on A (snare wires, a sitar's bridge, a rattle): where A
            # swings past the gap it buzzes: bright noise and a clipped edge, by how far
            bz = np.zeros(m)
            if self.buzz > 0:
                gap = 0.25 * (1.0 - self.buzz) + 0.004
                exc = np.maximum(np.abs(oa) - gap, 0.0)
                nz = self.rng.standard_normal(m)
                hp = nz - np.concatenate([[rattle_hp], nz[:-1]])
                rattle_hp = nz[-1]
                bz = (hp * exc * 0.8 + np.sign(oa) * exc * 0.5) * self.buzz
            ob = np.zeros(m)
            if self.b is not None:
                tb, bb = self.t60, 2.0 ** ((self.bend * self.b.level + ch) / 12.0)
                xb = x + bz * 0.5                                         # the rattle shakes B too
                if self.xmod in ("EXCITE", "TRADE"):
                    # A's output excites B: B hears (1 - c) of the exciter and c of A
                    xb = (1.0 - self.coup) * xb + self.coup * np.clip(oa, -1.0, 1.0) * 0.5
                elif self.xmod == "BEND":
                    bb *= 2.0 ** (self.coup * 12.0 * self.a.level / 12.0)  # A's swing bends B, to an octave
                elif self.xmod == "CHOKE":
                    tb = self.t60 / (1.0 + self.coup * 30.0 * self.a.level)  # A ringing chokes B
                wb = self.b.coeffs(ge, bb, tb, self.matl, loss, self.pos * 0.73, self.tilt)
                ob = self.b.block(xb, *wb, self._og(self.b, t))
                if self.xmod == "TRADE":
                    # what A gives B it loses: a damping on A by what it sent
                    self.a.y1 *= 1.0 - self.coup * 0.002
            ob_prev = ob if len(ob) == BLOCK else np.pad(ob, (0, BLOCK - len(ob)))
            ra[i:i + m], rb[i:i + m] = oa, ob
            y[i:i + m] = oa + ob + bz
            if i >= exc_len and np.max(np.abs(y[i:i + m])) < IDLE and \
                    self.a.energy() < IDLE and (self.b is None or self.b.energy() < IDLE):
                self.end = (i + m) / RATE
                y[i + m:] = 0.0
                ra, rb = ra[: i + m], rb[: i + m]
                break
        if self.clk is not None:
            k = min(len(self.clk), len(y))
            y[:k] += self.clk[:k]
            if len(ra) < k:
                ra = np.pad(ra, (0, k - len(ra)))
                rb = np.pad(rb, (0, k - len(rb)))
        return self.post(limit(dcblock(y)), ra, rb)

    def _og(self, body: Body, t: float):
        """MORPH's output weights for a body at time t: a tilt up the modes that grows as
        it rings, its sum held (the level stays; only the colour moves)."""
        if self.morph[0] <= 0:
            return None
        prog = 1.0 - math.exp(-t / self.morph[1])
        w = body.ratio ** (self.morph[0] * prog * 0.5)
        return w * (body.n / float(np.sum(w)))

    def post(self, y, ra, rb) -> np.ndarray:
        p = self.p
        n = len(ra)
        z = y[:n].copy()
        t = np.arange(n) / RATE
        if p["RING"] > 0:
            d = u(p["RING"])
            car = rb * 8.0 if self.b is not None else np.sin(2 * math.pi * self.f0 * 1.414 * t)
            z = (1 - d) * z + d * np.tanh(ra * 8.0) * np.tanh(car) * 0.25
        if p["SHIFT"] != 64:
            s = (p["SHIFT"] - 64) / 63.0
            hz = math.copysign(5.0 * (400.0 ** abs(s)), s)              # ±5 .. ±2000 Hz
            a = hilbert(z)
            z = np.real(a * np.exp(2j * math.pi * hz * t))
        if p["FORM"] > 0:
            v = u(p["FORM"]) * (len(VOWELS) - 1)
            j = min(int(v), len(VOWELS) - 2)
            fr = v - j
            wet = min(p["FORM"] / 16.0, 1.0) * 0.8
            f = 0.0
            for q in range(2):
                fc = VOWELS[j][q] * (1 - fr) + VOWELS[j + 1][q] * fr
                f = f + bandpass(z, fc, 8.0)
            z = (1 - wet) * z + wet * f * 2.0
        if p["WATR"] > 0:
            z = water(z, u(p["WATR"]), self.f0)
        if p["FOLD"] > 0:
            dr = 1.0 + 8.0 * u(p["FOLD"])
            z = np.sin(z * dr * 4.0) / 4.0 * (1 - u(p["FOLD"]) * 0.3)
        if p["CHAR"] > 0:
            dr = 1.0 + 20.0 * u(p["CHAR"]) ** 2
            z = np.tanh(z * dr + 0.1 * u(p["CHAR"])) / math.tanh(dr) - math.tanh(0.1 * u(p["CHAR"]))
        g = np.exp(-t / max(self.t60, 0.01)) if p["LPG"] > 0 else 1.0     # LPG's VCA half
        z = z * (1 - u(p["LPG"]) * 0.5 + u(p["LPG"]) * 0.5 * g)
        out = np.zeros(len(y))
        out[:n] = np.tanh(z * 1.5) / 1.5                                  # the output knee
        return out


WATER_USE = range(1, 7)                       # bands 2..7 of the 8 (owner, 2026-11-07)


def follow(x: np.ndarray, att: float, rel: float) -> np.ndarray:
    ka, kr = math.exp(-1 / (att * RATE)), math.exp(-1 / (rel * RATE))
    e, out = 0.0, np.empty(len(x))
    ax = np.abs(x)
    for i, v in enumerate(ax):
        k = ka if v > e else kr
        e = v + (e - v) * k
        out[i] = e
    return out


def lowpass2(x: np.ndarray, fc: float) -> np.ndarray:
    w = 2 * math.pi * fc / RATE
    al = math.sin(w) / (2 * 0.7071)
    c = math.cos(w)
    return lfilter([(1 - c) / 2, 1 - c, (1 - c) / 2], [1 + al, -2 * c, 1 - al], x)


def water(z: np.ndarray, amt: float, f0: float) -> np.ndarray:
    """WATR: the sound vocodes itself. Its skin (everything above about 1.8 x the note) is
    split into eight bands from 2.2 x the note up; each of bands 2..7 is heard through a
    narrow band tuned slightly higher (the carrier) and gated by its own fast envelope
    (the modulator), squared so the band's peaks swell and its tails drop out: round,
    drippy droplets. The body under 1.8 x the note passes untouched, so its fundamental
    and its pitch stay; the wet skin is matched to the dry skin's level."""
    body = lowpass2(lowpass2(z, f0 * 1.8), f0 * 1.8)
    skin = z - body
    top = min(f0 * 2.2 * 32.0, 9000.0)
    bands = [f0 * 2.2 * (top / (f0 * 2.2)) ** (k / 7) for k in range(8)]
    wet = np.zeros(len(z))
    for k in WATER_USE:
        fc = bands[k]
        if fc > 0.4 * RATE:
            continue
        an = bandpass(skin, fc, 3.0)                           # the modulator: the band itself
        car = bandpass(skin, fc * (1.04 + 0.04 * amt), 14.0)   # the carrier: narrow, a little high
        e = follow(an, 0.0008, 0.012)
        es = follow(an, 0.02, 0.15) + 1e-6
        wet += car * np.minimum((e / es) ** 2, 6.0)            # expansion: swells, drops
    rs, rw = float(np.sqrt(np.mean(skin ** 2))), float(np.sqrt(np.mean(wet ** 2)))
    if rw > 1e-9:
        wet *= rs / rw
    return body + skin * (1.0 - amt) + wet * amt


def dcblock(x: np.ndarray) -> np.ndarray:
    """A 20 Hz one-pole high-pass: a steady force (a bow's pull, a breath's pressure)
    bends a body without sounding; only its motion is heard."""
    a = math.exp(-2 * math.pi * 20.0 / RATE)
    return lfilter([1.0, -1.0], [1.0, -a], x)


def limit(x: np.ndarray) -> np.ndarray:
    """The voice's level guard: a peak follower (fast attack, slow release) above LIMIT's
    threshold. One follower a voice on the DSP; below the threshold it does nothing."""
    th, att, rel = LIMIT
    ka, kr = math.exp(-1 / (att * RATE)), math.exp(-1 / (rel * RATE))
    env, g = 0.0, np.ones(len(x))
    ax = np.abs(x)
    for i in range(0, len(x), BLOCK):        # a block's gain, as the DSP would
        pk = float(ax[i:i + BLOCK].max()) if len(ax[i:i + BLOCK]) else 0.0
        env = pk if pk > env else env * kr ** BLOCK
        g[i:i + BLOCK] = th / env if env > th else 1.0
    return x * g


def bandpass(x: np.ndarray, fc: float, q: float) -> np.ndarray:
    w = 2 * math.pi * fc / RATE
    al = math.sin(w) / (2 * q)
    b = [al, 0.0, -al]
    a = [1 + al, -2 * math.cos(w), 1 - al]
    return lfilter(b, a, x)


def render_notes(p: dict, events, seconds: float, modes: int = MODES) -> np.ndarray:
    """events: (start s, note, vel[, param overrides]) -> one mono mix (polyphonic)."""
    out = np.zeros(int(seconds * RATE))
    for k, ev in enumerate(events):
        t0, note, vel = ev[:3]
        pp = {**p, **(ev[3] if len(ev) > 3 else {})}
        i0 = int(t0 * RATE)
        v = Voice(pp, note, vel, seed=k + 1, modes=modes).render(seconds - t0)
        out[i0:i0 + len(v)] += v[: len(out) - i0]
    return out

"""FASCIA, the sound: the design model, chosen by ear (docs/fascia.md).

Two exciters feed two modal bodies. The bodies can be coupled one way. After them come
through-zero FM sidebands, ring modulation, frequency shift, a moving formant, a folder,
the LPG and CHAR. This is the reference the DSP code will be held to: float64, offline,
block-wise like the DSP (32 samples, coefficients once a block). `fascia/live.py` will be
the DSP-order float32 contract, like `rings/live.py` and `perc/live.py` before it.

Controls are 0..127, as on the panel (`PAGES`). Choice controls take an index
(`TYPES`, `BODIES`). A voice is one note: `Voice(params, note, vel).render(seconds)`.
`render_notes` mixes several voices, for chords and patterns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

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
BODIES = ("MEMB", "PLATE", "BAR", "VIBE", "CHIME", "BELL", "GLASS", "TUBE", "STRING", "OFF")  # OFF: B only

PAGES = {
    "SYN1 EXCITERS": ("TYPA", "TYPB", "HARD", "DUST", "TZFM", "BEND", "MIX", "DEC"),
    "SYN2 RESONATORS": ("BODA", "BODB", "TUNE", "GEOM", "MATL", "POS", "COUP", "DAMP"),
    "SYN3 SPECTRAL": ("MORPH", "FORM", "SHIFT", "RING", "SIDE", "FOLD", "LPG", "CHAR"),
}
CHOICES = {"TYPA": TYPES, "TYPB": TYPES, "BODA": BODIES[:-1], "BODB": BODIES}

DEFAULTS = {
    "TYPA": 0, "TYPB": 1, "HARD": 90, "DUST": 20, "TZFM": 0, "BEND": 10, "MIX": 30, "DEC": 20,
    "BODA": 0, "BODB": 5, "TUNE": 64, "GEOM": 64, "MATL": 50, "POS": 40, "COUP": 0, "DAMP": 60,
    "MORPH": 0, "FORM": 0, "SHIFT": 64, "RING": 0, "SIDE": 40, "FOLD": 0, "LPG": 40, "CHAR": 0,
}

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
SPLIT = {"MEMB": 0.0008, "PLATE": 0.0015, "BAR": 0.0, "VIBE": 0.0, "CHIME": 0.0010,
         "BELL": 0.0020, "GLASS": 0.0025, "TUBE": 0.0, "STRING": 0.0004}
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
    round, and a per-hit variation of a few cents and a decibel or so (seeded), so that
    repeated hits sound like one object struck again, not a sample replayed."""

    def __init__(self, kind: str, f0: float, modes: int = MODES, seed: int = 1, vary: float = 1.0):
        self.kind, self.f0 = kind, f0
        rng = np.random.default_rng(seed)
        base = np.array(RATIOS[kind][:modes])
        k = np.arange(len(base))
        jit = 1.0 + rng.normal(0.0, 0.0012, len(base)) * (1 + 0.15 * k) * vary
        jit[0] = 1.0 + (jit[0] - 1.0) * 0.2                     # the pitch stays the pitch
        aj = np.exp(rng.normal(0.0, 0.10, len(base)) * vary)
        split = SPLIT[kind]
        if split:
            tw = 1.0 + split * (0.6 + 0.8 * rng.random(len(base))) * (1 + 0.3 * k)
            base = np.concatenate([base * jit, base * jit * tw])
            aj = np.concatenate([aj, aj * (0.5 + 0.5 * rng.random(len(aj)))])
        else:
            base = base * jit
        self.base, self.aj = base, aj
        self.n = len(base)
        self.y1 = np.zeros(self.n)
        self.y2 = np.zeros(self.n)
        self.peak = 1e-9                                         # for the tension glide
        self.level = 1.0

    def coeffs(self, geom_e: float, bend: float, t60: float, matl: float,
               lpg_loss: float, pos: float, tilt: float):
        ratio = self.base ** geom_e
        f = self.f0 * ratio * bend
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

    def block(self, x: np.ndarray, w, r, amp) -> np.ndarray:
        out = np.zeros_like(x)
        for m in range(self.n):
            if amp[m] == 0.0 and self.y1[m] == 0.0 and self.y2[m] == 0.0:
                continue
            a1, a2 = -2.0 * r[m] * math.cos(w[m]), r[m] * r[m]
            b0 = amp[m] * math.sin(w[m])
            zi = np.array([-a1 * self.y1[m] - a2 * self.y2[m], -a2 * self.y1[m]])
            y, _ = lfilter([b0], [1.0, a1, a2], x, zi=zi)
            self.y2[m], self.y1[m] = (y[-2], y[-1]) if len(y) > 1 else (self.y1[m], y[-1])
            out += y
        pk = float(np.max(np.abs(out))) if len(out) else 0.0
        self.peak = max(self.peak, pk)
        self.level = pk / self.peak
        return out

    def energy(self) -> float:
        return float(np.max(np.abs(self.y1)) + np.max(np.abs(self.y2)))


class Exciter:
    """One exciter: a whole excitation rendered at the note (deterministic, seeded)."""

    def __init__(self, kind: str, p: dict, f0: float, vel: float, seed: int):
        self.kind, self.p, self.f0, self.vel = kind, p, f0, vel
        self.rng = np.random.default_rng(seed)
        hard = u(p["HARD"]) * (0.5 + 0.5 * vel)          # velocity -> hardness
        self.width = 4.0e-3 * (0.0125 ** hard)            # 4 ms soft .. 0.05 ms hard
        self.dec = expmap(p["DEC"], 0.004, 2.0)           # the excitation's length, s
        self.sig = self._make()

    def _pulse(self, width: float) -> np.ndarray:
        """A raised-cosine pulse: band-limited, so a very hard strike snaps, not aliases."""
        n = max(int(width * RATE), 2)
        pl = 0.5 - 0.5 * np.cos(2 * math.pi * np.arange(n) / n)
        return pl / pl.sum()                    # unit area: a low mode rings as from an impulse

    def _env(self, n: int, tau: float) -> np.ndarray:
        return np.exp(-np.arange(n) / (tau * RATE))

    def _make(self) -> np.ndarray:
        p, k, f0 = self.p, self.kind, self.f0
        n = int((self.dec * 4 + 0.01) * RATE)
        x = np.zeros(n)
        if k == "STRIKE":
            pl = self._pulse(self.width)
            x[: len(pl)] += pl
            # contact noise: DUST adds texture to the impact, over DEC
            nz = self.rng.standard_normal(n) * self._env(n, self.dec * 0.25)
            x += nz * 0.15 * u(p["DUST"])
        elif k == "BLOW":
            nz = self.rng.standard_normal(n)
            cut = 400.0 * 30.0 ** u(p["HARD"])
            a = math.exp(-2 * math.pi * cut / RATE)
            nz = lfilter([1 - a], [1, -a], nz)
            att = np.minimum(np.arange(n) / (0.002 * RATE), 1.0)
            x = nz * att * self._env(n, self.dec) * 2.0
        elif k == "BOW":
            # stick-slip, simplified: a jittered sawtooth at the body's pitch under a
            # pressure envelope, plus friction noise (a bow is sustained: DEC holds it)
            t = np.arange(n) / RATE
            jit = np.cumsum(self.rng.standard_normal(n)) * 2e-4
            ph = (f0 * t + jit) % 1.0
            press = np.minimum(t / 0.03, 1.0) * np.exp(-np.maximum(t - self.dec, 0) / 0.05)
            x = ((ph - 0.5) * 0.6 * press + self.rng.standard_normal(n) * 0.05 * press) \
                / math.sqrt(max(self.dec / 0.1, 1.0))
        elif k == "DUST":
            dens = expmap(p["DUST"], 5.0, 3000.0) * (0.5 + self.vel)
            ev = self.rng.random(n) < dens / RATE * self._env(n, self.dec)
            pl = self._pulse(max(self.width, 1e-4))
            amps = self.rng.uniform(-1, 1, n) * ev / math.sqrt(max(dens * self.dec, 1.0) / 4.0)
            x = np.convolve(amps, pl)[:n]
        elif k == "PULSE":
            t = np.arange(n) / RATE
            pitch = f0 * 2.0 * 2.0 ** (u(p["BEND"]) * 3 * np.exp(-t / 0.01))
            ph = np.cumsum(pitch) / RATE
            x = np.sin(2 * math.pi * ph) * self._env(n, self.dec * 0.3)
        elif k == "TZFM":
            x = self.tzfm(n, max(u(p["TZFM"]), 0.15), self.dec)
        # any exciter: TZFM adds a through-zero sideband burst at the attack
        if k != "TZFM" and p["TZFM"] > 0:
            x = x + self.tzfm(n, u(p["TZFM"]), min(self.dec, 0.03)) * TYPE_GAIN["TZFM"] / TYPE_GAIN[k]
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


class Voice:
    def __init__(self, p: dict, note: float, vel: float = 1.0, seed: int = 1, modes: int = MODES):
        self.p = {**DEFAULTS, **p}
        p = self.p
        self.f0 = mtof(note + (p["TUNE"] - 64) * 24 / 64)
        self.vel = vel
        ka = BODIES[choice("BODA", p["BODA"])]
        kb = BODIES[choice("BODB", p["BODB"])]
        self.a = Body(ka, self.f0, modes, seed=seed * 31 + 3)
        self.b = None if kb == "OFF" else Body(kb, self.f0 * B_RATIO[kb], modes, seed=seed * 31 + 5)
        ta, tb = TYPES[choice("TYPA", p["TYPA"])], TYPES[choice("TYPB", p["TYPB"])]
        self.ea = Exciter(ta, p, self.f0, vel, seed)
        self.eb = Exciter(tb, p, self.f0, vel, seed + 7919)
        mix = u(p["MIX"])
        self.ga, self.gb = math.cos(mix * math.pi / 2), math.sin(mix * math.pi / 2)
        self.t60 = expmap(127 - p["DAMP"], 0.03, 12.0)                 # DAMP up: shorter
        self.matl = u(p["MATL"])                                         # wood .. metal
        self.pos = 0.02 + 0.48 * u(p["POS"])
        self.tilt = 1.2 * (1.0 - u(p["HARD"]) * (0.5 + 0.5 * vel))      # soft hits: fewer highs
        self.geom_e = 0.6 + 0.8 * u(p["GEOM"])
        self.morph = (u(p["MORPH"]) * 0.6, self.t60 * 0.3)
        # BEND: tension glide. A struck membrane or a soft plonk sounds sharp while it is
        # loud and settles as it rings (pitch follows the body's own level), plus a short
        # contact chirp that harder hits raise
        self.bend = u(p["BEND"]) * 7.0 * (0.4 + 0.6 * vel)              # semitones at full level
        self.chirp = u(p["HARD"]) * vel * 0.6                          # semitones, 4 ms
        self.lpg = u(p["LPG"]) * 6.0
        self.coup = u(p["COUP"])
        self.end = None                                                 # s, when it went idle

    def _exc(self, i: int, n: int) -> np.ndarray:
        out = np.zeros(n)
        for e, g in ((self.ea, self.ga), (self.eb, self.gb)):
            s = e.sig[i:i + n]
            out[: len(s)] += s * g
        return out

    def render(self, seconds: float) -> np.ndarray:
        n = int(seconds * RATE)
        y = np.zeros(n)
        ra = np.zeros(n)
        rb = np.zeros(n)
        exc_len = max(len(self.ea.sig), len(self.eb.sig))
        for i in range(0, n, BLOCK):
            m = min(BLOCK, n - i)
            t = i / RATE
            x = self._exc(i, m)
            ge = self.geom_e + self.morph[0] * (1 - math.exp(-t / self.morph[1]))
            ch = self.chirp * math.exp(-t / 0.004)
            bend = 2.0 ** ((self.bend * self.a.level + ch) / 12.0)
            g = math.exp(-t / max(self.t60 * 0.25, 0.01))                # the LPG contour
            loss = self.lpg * (1.0 - g)
            wa = self.a.coeffs(ge, bend, self.t60, self.matl, loss, self.pos, self.tilt)
            oa = self.a.block(x, *wa)
            ob = np.zeros(m)
            if self.b is not None:
                bb = 2.0 ** ((self.bend * self.b.level + ch) / 12.0)
                wb = self.b.coeffs(ge, bb, self.t60, self.matl, loss, self.pos * 0.73, self.tilt)
                # one-way, bounded: B hears (1 - c) of the exciter and c of A, A's level held
                xb = (1.0 - self.coup) * x + self.coup * np.clip(oa, -1.0, 1.0) * 0.5
                ob = self.b.block(xb, *wb)
            ra[i:i + m], rb[i:i + m] = oa, ob
            y[i:i + m] = oa + ob if self.b is not None else oa
            if i >= exc_len and np.max(np.abs(y[i:i + m])) < IDLE and \
                    self.a.energy() < IDLE and (self.b is None or self.b.energy() < IDLE):
                self.end = (i + m) / RATE
                y[i + m:] = 0.0
                ra, rb = ra[: i + m], rb[: i + m]
                break
        return self.post(limit(y), ra, rb)

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

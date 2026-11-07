"""RIFT, the sound: the design model, chosen by ear (docs/rift.md).

Two exciters feed two modal bodies. The bodies can be coupled one way. After them come
through-zero FM sidebands, ring modulation, frequency shift, a moving formant, a folder,
the LPG and CHAR. This is the reference the DSP code will be held to: float64, offline,
block-wise like the DSP (32 samples, coefficients once a block). `rift/live.py` will be
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
MODES = 8
IDLE = 1.0e-5                    # a block that peaks under this, exciters done: the voice ends
OUT = 0.5                        # a full-velocity impulse's body peak, about
# Each exciter's level into the bodies, so every type lands near OUT (sustained ones drive
# the modes at their own pitch and build up; measured, scripts/rift_audition.py).
TYPE_GAIN = {"STRIKE": 1.0, "BLOW": 0.04, "BOW": 0.06, "DUST": 3.5, "PULSE": 0.03, "TZFM": 0.015}
LIMIT = (0.7, 0.001, 0.12)       # the voice's level guard: threshold, attack s, release s

TYPES = ("STRIKE", "BLOW", "BOW", "DUST", "PULSE", "TZFM")
BODIES = ("MEMB", "PLATE", "BAR", "TUBE", "STRING", "OFF")      # OFF: body B only

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

# Mode-frequency ratios, the first eight of each body (the classic tables: an ideal
# circular membrane's Bessel zeros, a free square plate, a free-free bar, a closed tube's
# odd harmonics, a string's harmonics).
RATIOS = {
    "MEMB": (1.000, 1.594, 2.136, 2.296, 2.653, 2.918, 3.156, 3.501),
    "PLATE": (1.000, 2.500, 4.000, 5.000, 6.500, 8.500, 9.000, 10.000),
    "BAR": (1.000, 2.756, 5.404, 8.933, 13.344, 18.638, 24.814, 31.871),
    "TUBE": (1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0),
    "STRING": (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0),
}
# Body B's pitch against A's (fixed for now; design doc: "a selectable ratio, later
# independent tuning"). Chosen so the two bodies beat against each other musically.
B_RATIO = {"MEMB": 1.498, "PLATE": 2.0, "BAR": 2.756, "TUBE": 1.5, "STRING": 1.0}

VOWELS = ((730, 1090), (530, 1840), (270, 2290), (570, 840), (300, 870))  # a e i o u


def u(v: int) -> float:
    """A 0..127 control as 0..1."""
    return min(max(v, 0), 127) / 127.0


def expmap(v: int, lo: float, hi: float) -> float:
    return lo * (hi / lo) ** u(v)


def choice(name: str, v: int) -> int:
    """The option a 0..127 value picks: equal spans (the panel's 4-detent stepping maps
    each option to its own span, docs/rift.md)."""
    n = len(CHOICES[name])
    return min(int(min(max(v, 0), 127) * n / 128), n - 1)


def mtof(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


@dataclass
class Body:
    kind: str
    f0: float
    modes: int = MODES
    y1: np.ndarray = field(default=None)
    y2: np.ndarray = field(default=None)

    def __post_init__(self):
        self.y1 = np.zeros(self.modes)
        self.y2 = np.zeros(self.modes)

    def coeffs(self, geom_e: float, bend: float, t60: float, matl_exp: float,
               lpg_loss: float, pos: float, tilt: float):
        base = np.array(RATIOS[self.kind][: self.modes])
        ratio = base ** geom_e
        f = self.f0 * ratio * bend
        alive = f < 0.45 * RATE
        f = np.minimum(f, 0.45 * RATE)
        w = 2 * math.pi * f / RATE
        t60k = t60 * (1.0 / ratio) ** matl_exp / (1.0 + lpg_loss * (ratio - 1.0))
        r = 10.0 ** (-3.0 / (np.maximum(t60k, 1e-3) * RATE))
        k = np.arange(1, self.modes + 1)
        amp = np.abs(np.sin(math.pi * k * pos)) * k ** (-tilt)
        amp = amp * alive
        amp = amp * (OUT / max(float(np.sum(np.abs(np.sin(math.pi * k * pos)) * k ** (-tilt))), 1e-6))
        return w, r, amp

    def block(self, x: np.ndarray, w, r, amp) -> np.ndarray:
        out = np.zeros_like(x)
        for m in range(self.modes):
            if amp[m] == 0.0 and self.y1[m] == 0.0 and self.y2[m] == 0.0:
                continue
            a1, a2 = -2.0 * r[m] * math.cos(w[m]), r[m] * r[m]
            b0 = amp[m] * math.sin(w[m])
            zi = np.array([-a1 * self.y1[m] - a2 * self.y2[m], -a2 * self.y1[m]])
            y, _ = lfilter([b0], [1.0, a1, a2], x, zi=zi)
            self.y2[m], self.y1[m] = (y[-2], y[-1]) if len(y) > 1 else (self.y1[m], y[-1])
            out += y
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
        self.a = Body(ka, self.f0, modes)
        self.b = None if kb == "OFF" else Body(kb, self.f0 * B_RATIO[kb], modes)
        ta, tb = TYPES[choice("TYPA", p["TYPA"])], TYPES[choice("TYPB", p["TYPB"])]
        self.ea = Exciter(ta, p, self.f0, vel, seed)
        self.eb = Exciter(tb, p, self.f0, vel, seed + 7919)
        mix = u(p["MIX"])
        self.ga, self.gb = math.cos(mix * math.pi / 2), math.sin(mix * math.pi / 2)
        self.t60 = expmap(127 - p["DAMP"], 0.03, 12.0)                 # DAMP up: shorter
        self.matl_exp = 1.6 * (1.0 - u(p["MATL"])) + 0.05               # wood .. metal
        self.pos = 0.02 + 0.48 * u(p["POS"])
        self.tilt = 1.2 * (1.0 - u(p["HARD"]) * (0.5 + 0.5 * vel))      # soft hits: fewer highs
        self.geom_e = 0.6 + 0.8 * u(p["GEOM"])
        self.morph = (u(p["MORPH"]) * 0.6, self.t60 * 0.3)
        self.bend = (u(p["BEND"]) * 12.0 * (0.5 + 0.5 * vel), 0.03)    # semitones, s
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
            bend = 2.0 ** (self.bend[0] * math.exp(-t / self.bend[1]) / 12.0)
            g = math.exp(-t / max(self.t60 * 0.25, 0.01))                # the LPG contour
            loss = self.lpg * (1.0 - g)
            wa = self.a.coeffs(ge, bend, self.t60, self.matl_exp, loss, self.pos, self.tilt)
            oa = self.a.block(x, *wa)
            ob = np.zeros(m)
            if self.b is not None:
                wb = self.b.coeffs(ge, bend, self.t60, self.matl_exp, loss, self.pos * 0.73, self.tilt)
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

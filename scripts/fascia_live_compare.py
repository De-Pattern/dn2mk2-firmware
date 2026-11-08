"""FASCIA: the DSP-order contract (src/dnfw/fascia/live.py) against the approved design model
(src/dnfw/fascia/model.py), by ear-level measures, for every audition patch; and the WAVs
for the owner to listen to them side by side.

    PYTHONPATH=src python3 scripts/fascia_live_compare.py [OUTDIR]     (default out/fascia-live)

For each patch, its first note alone (1 s) and its first second as the audition plays it:

- **spectral distance** (dB): the log-magnitude spectrum in sixth-octave bands, 50 Hz to
  16 kHz, 60 dB of range below the model's loudest band, the level difference taken out
  (it is reported apart): the RMS of the band differences, over three windows of the note
  (onset 0-50 ms, body 50-300 ms, tail 300-1000 ms) and over the phrase's second;
- **level** (dB): the note's RMS, live less model;
- **decay**: the note's T60 from a fit of its 10 ms RMS envelope (from the peak down 40 dB),
  live / model; a sustained note (bowed, blown) compares its held level instead;
- **pitch** (cents): the strongest partial and the lowest partial within 20 dB of it, live
  less model.

Three comparisons (`compare`): `det`, the patch's deterministic twin (DUST 0, live given every
model draw: VARY's jitter and levels, the drift, the bow's phase; all 16 twins): the
algorithm alone, held to fixed, tight limits (`DET`); `cut`, live with twins on 8 modes
against all 16; and `own`, three live hits as the DSP plays them against three of the
model's (mean spectra, levels, T60s, pitches), plus the phrase. `base`, three of the model's
hits against three others, is the variation the owner approved as one instrument; `cut` and
`own` take their limits from it (`limits`). A noisy patch (BLOW, BUZZ, the NOISE click) has no
deterministic twin.

Writes, per patch, NAME.wav: the model's phrase, half a second of silence, live's (own
draws); NAME.lr.wav: model left, live right; and index.txt with every measure.
"""

from __future__ import annotations

import math
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fascia_audition as A  # noqa: E402
from dnfw.fascia import live as L  # noqa: E402
from dnfw.fascia import model as R  # noqa: E402

RATE = R.RATE
NOTE_S = 1.0
PHRASE_S = 1.0
WINDOWS = (("onset", 0.0, 0.05), ("body", 0.05, 0.30), ("tail", 0.30, 1.0))
RANGE_DB = 60.0


# -- measures -------------------------------------------------------------------------------
def bands_db(x: np.ndarray, lo: float = 50.0, hi: float = 16000.0, per_oct: int = 6) -> np.ndarray:
    x = np.asarray(x, float)
    n = max(len(x), 64)
    nfft = 1 << int(math.ceil(math.log2(max(n, 4096))))
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)), nfft)) ** 2
    f = np.fft.rfftfreq(nfft, 1 / RATE)
    edges = lo * 2.0 ** (np.arange(0, int(math.log2(hi / lo) * per_oct) + 1) / per_oct)
    idx = np.searchsorted(f, edges)
    e = np.array([X[a:max(b, a + 1)].sum() for a, b in zip(idx[:-1], idx[1:])])
    return 10 * np.log10(e + 1e-30)


def spec_dist(m: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """(shape distance dB, level difference dB) of X against M"""
    bm, bx = bands_db(m), bands_db(x)
    lev = 10 * math.log10((np.sum(np.asarray(x, float) ** 2) + 1e-30) / (np.sum(np.asarray(m, float) ** 2) + 1e-30))
    bx = bx - lev
    fl = bm.max() - RANGE_DB
    bm, bx = np.maximum(bm, fl), np.maximum(bx, fl)
    mask = (bm > fl) | (bx > fl)
    return float(np.sqrt(np.mean((bm - bx)[mask] ** 2))) if mask.any() else 0.0, lev


def envelope_db(x: np.ndarray, frame: float = 0.01) -> np.ndarray:
    n = int(frame * RATE)
    k = len(x) // n
    e = np.sqrt(np.mean(np.asarray(x[:k * n], float).reshape(k, n) ** 2, axis=1))
    return 20 * np.log10(e + 1e-12)


def decay(x: np.ndarray) -> tuple[str, float]:
    """('t60', seconds) from the envelope's fit, or ('held', dB) for a sustained note"""
    e = envelope_db(x)
    p = int(np.argmax(e))
    end = len(e)
    below = np.nonzero(e[p:] < e[p] - 40.0)[0]
    if len(below):
        end = p + int(below[0])
    seg = e[p + 2:end]
    if len(seg) < 5:
        return "t60", 0.0
    sl = np.polyfit(np.arange(len(seg)) * 0.01, seg, 1)[0]
    if sl > -6.0:                                     # under 6 dB/s: held, not decaying
        return "held", float(np.mean(e[int(0.3 / 0.01):]))
    return "t60", float(60.0 / -sl)


def _peak(X: np.ndarray, f: np.ndarray, i: int) -> float:
    if 0 < i < len(X) - 1:
        a, b, c = np.log(X[i - 1] + 1e-30), np.log(X[i] + 1e-30), np.log(X[i + 1] + 1e-30)
        den = a - 2 * b + c
        off = 0.5 * (a - c) / den if den < 0 else 0.0     # a maximum: the parabola opens down
        return float(f[i] + min(max(off, -0.5), 0.5) * (f[1] - f[0]))
    return float(f[i])


def _spectrum(x: np.ndarray, end: int | None = None):
    """the spectrum of 50..600 ms, or of 10 ms to the note's end if it ends sooner"""
    x = np.asarray(x, float)
    a, b = int(0.05 * RATE), int(0.6 * RATE)
    if end is not None and end < b:
        a, b = int(0.01 * RATE), max(end, int(0.01 * RATE) + 512)
    seg = x[a:b]
    nfft = 1 << 20
    X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nfft))
    return X, np.fft.rfftfreq(nfft, 1 / RATE)


def note_end(m: np.ndarray) -> int:
    """the last sample within 60 dB of the note's peak"""
    a = np.abs(np.asarray(m, float))
    i = np.nonzero(a > np.max(a) * 1e-3)[0]
    return int(i[-1]) + 1 if len(i) else len(a)


def partials(m: np.ndarray) -> list[float]:
    """the model's strongest partial over 40 Hz, and its lowest within 20 dB of it"""
    X, f = _spectrum(m, note_end(m))
    ok = f > 40.0
    i = int(np.argmax(np.where(ok, X, 0)))
    top = X[i]
    w = max(int(8.0 / (f[1] - f[0])), 2)               # a peak: the maximum within 8 Hz
    lows = []
    for j in np.nonzero(ok & (X > top * 0.1))[0]:
        lo, hi = max(j - w, 0), min(j + w + 1, len(X))
        if X[j] == X[lo:hi].max():
            lows.append(j)
            break
    j = lows[0] if lows else i
    return [_peak(X, f, i), _peak(X, f, j)]


def cents_at(x: np.ndarray, want: float, end: int | None = None) -> float:
    """live's partial near WANT (within 40 cents), in cents from it"""
    X, f = _spectrum(x, end)
    lo, hi = np.searchsorted(f, want * 2 ** (-40 / 1200)), np.searchsorted(f, want * 2 ** (40 / 1200))
    if hi <= lo:
        return float("nan")
    i = lo + int(np.argmax(X[lo:hi]))
    if X[i] <= 0:
        return float("nan")
    return 1200 * math.log2(_peak(X, f, i) / want)


def measure(m: np.ndarray, x: np.ndarray, mp: np.ndarray | None = None, xp: np.ndarray | None = None) -> dict:
    """every measure of a note X against the model's M (and phrases XP against MP)"""
    out = {}
    e0 = np.sum(np.asarray(m[:int(0.05 * RATE)], float) ** 2) + 1e-30
    for name, a, b in WINDOWS:
        sm, sx = m[int(a * RATE):int(b * RATE)], x[int(a * RATE):int(b * RATE)]
        em = np.mean(np.asarray(sm, float) ** 2) if len(sm) else 0.0
        if len(sm) < 256 or em * (0.05 * RATE) < e0 * 1e-6:   # 60 dB under the onset: not heard
            out[name] = None
            continue
        out[name] = spec_dist(sm, sx)[0]
    out["level"] = spec_dist(m, x)[1]
    km, vm = decay(m)
    kx, vx = decay(x)
    out["decay"] = (km, vm, kx, vx)
    end = note_end(m)
    out["pitch"] = [cents_at(x, fm, end) for fm in partials(m)]
    if mp is not None:
        out["phrase"] = spec_dist(mp, xp)[0]
        out["phrase_level"] = spec_dist(mp, xp)[1]
    return out


def decay_ratio(d) -> float:
    km, vm, kx, vx = d
    if km != kx:
        return float("nan")
    if km == "held":
        return vx - vm                                  # dB
    return vx / vm if vm > 0 else 1.0


# -- rendering ------------------------------------------------------------------------------
def model_note(p, note, vel, seed=1, seconds=NOTE_S):
    return R.Voice(p, note, vel, seed=seed).render(seconds)


def model_phrase(p, events, seconds, seed_offset=0):
    if not seed_offset:
        return R.render_notes(p, events, seconds)
    out = np.zeros(int(seconds * RATE))
    for k, ev in enumerate(events):
        t0, note, vel = ev[:3]
        i0 = int(t0 * RATE)
        v = R.Voice({**p, **(ev[3] if len(ev) > 3 else {})}, note, vel, seed=k + 1 + seed_offset).render(seconds - t0)
        out[i0:i0 + len(v)] += v[:len(out) - i0]
    return out


def live_note(p, note, vel, seed=1, matched=False, seconds=NOTE_S, twins=L.TWINS):
    draws = L.model_draws(p, note, vel, seed) if matched else None
    return L.render_voice(p, note, vel, seconds, seed=seed, twins=twins, draws=draws).astype(float)


# -- the three comparisons -------------------------------------------------------------------
GROUP_A = (1, 2, 3)                               # the hits a group measure averages
GROUP_B = (4, 5, 6)                               # the model's other hits: its own spread
# a noisy patch (a rattle's threshold, a reed's breath) varies more from hit to hit: six
NOISY_A, NOISY_B = (1, 2, 3, 4, 5, 6), (7, 8, 9, 10, 11, 12)


def chaotic(p: dict) -> bool:
    """a bowed patch: the friction's stick-slip amplifies any rounding (float32 against the
    model's float64), so no deterministic twin stays sample-close for long"""
    q = R.expand(p)
    kinds = (R.TYPES[R.choice("TYPA", q["TYPA"])], R.TYPES[R.choice("TYPB", q["TYPB"])])
    mix = R.u(q["MIX"])
    return (kinds[0] == "BOW" and mix < 0.9999) or (kinds[1] == "BOW" and mix > 1e-4)


def noisy(p: dict) -> bool:
    """a patch with a noise source DUST 0 does not stop (BLOW's breath, BUZZ, the NOISE
    click): its deterministic twin is not deterministic"""
    q = R.expand(p)
    kinds = (R.TYPES[R.choice("TYPA", q["TYPA"])], R.TYPES[R.choice("TYPB", q["TYPB"])])
    mix = R.u(q["MIX"])
    blow = (kinds[0] == "BLOW" and mix < 0.9999) or (kinds[1] == "BLOW" and mix > 1e-4)
    click = q["CLIK"] > 0 and R.CLICKS[R.ichoice("CTYP", q["CTYP"])] == "NOISE"
    return blow or q["BUZZ"] > 0 or click


def _bands_power(x):
    return 10.0 ** (bands_db(x) / 10.0)


def group_measure(ms: list, xs: list) -> dict:
    """the measures of a group of hits XS against a group MS: the mean band-power spectra per
    window, the mean level, the geometric-mean T60 (or the mean held level), the mean pitch
    of each hit's partials against MS[0]'s"""
    out = {}
    e0 = np.mean([np.sum(np.asarray(m[:int(0.05 * RATE)], float) ** 2) for m in ms]) + 1e-30
    for name, a, b in WINDOWS:
        sl = slice(int(a * RATE), int(b * RATE))
        em = np.mean([np.mean(np.asarray(m[sl], float) ** 2) for m in ms])
        if em * (0.05 * RATE) < e0 * 1e-5:                # 50 dB under the onset: not heard
            out[name] = None
            continue
        pm = np.mean([_bands_power(m[sl]) for m in ms], axis=0)
        px = np.mean([_bands_power(x[sl]) for x in xs], axis=0)
        bm, bx = 10 * np.log10(pm + 1e-30), 10 * np.log10(px + 1e-30)
        bx = bx - 10 * math.log10(px.sum() / pm.sum())
        fl = bm.max() - RANGE_DB
        bm, bx = np.maximum(bm, fl), np.maximum(bx, fl)
        mask = (bm > fl) | (bx > fl)
        out[name] = float(np.sqrt(np.mean((bm - bx)[mask] ** 2)))
    lev = lambda z: 10 * math.log10(np.sum(np.asarray(z, float) ** 2) + 1e-30)   # noqa: E731
    out["level"] = float(np.mean([lev(x) for x in xs]) - np.mean([lev(m) for m in ms]))
    dm, dx = [decay(m) for m in ms], [decay(x) for x in xs]
    if all(d[0] == "t60" and d[1] > 0 for d in dm + dx):
        gm = lambda ds: math.exp(np.mean([math.log(d[1]) for d in ds]))     # noqa: E731
        out["decay"] = ("t60", gm(dm), "t60", gm(dx))
    elif all(d[0] == "held" for d in dm + dx):
        out["decay"] = ("held", float(np.mean([d[1] for d in dm])), "held", float(np.mean([d[1] for d in dx])))
    else:
        out["decay"] = ("mixed", 0.0, "mixed", 0.0)
    ref, end = partials(ms[0]), note_end(ms[0])
    cm = [[cents_at(m, f, end) for f in ref] for m in ms]
    cx = [[cents_at(x, f, end) for f in ref] for x in xs]
    out["pitch"] = [float(np.nanmean([c[i] for c in cx]) - np.nanmean([c[i] for c in cm])) for i in range(2)]
    out["_hits"] = {"level": [lev(m) for m in ms], "t60": [d[1] for d in dm if d[0] == "t60"],
                    "cents": cm}
    return out


def compare(name: str, phrase: bool = True) -> dict:
    """one audition patch, three ways:
    'det': its deterministic twin (DUST 0, every model draw, the drift too, all 16 twins) against
       the model's: the algorithm, float32 and DSP order, alone (skipped for a noisy patch);
    'cut': live with the cost cut (twins on 8) against live with all 16: what the cut costs;
    'own': three live hits, as the DSP plays them, against three of the model's, and the
       phrase's first second; 'base': three of the model's hits against three others (the
       model's own spread, from which 'own' and 'cut' take their limits)."""
    p, evs, _secs, _trem = A.PATCHES[name]
    note, vel = evs[0][1], evs[0][2]
    res = {"noisy": noisy(p), "chaotic": chaotic(p)}
    q = {**p, "DUST": 0}
    md = model_note(q, note, vel)
    d = L.model_draws(q, note, vel, 1)
    res["det"] = measure(md, L.render_voice(q, note, vel, NOTE_S, seed=1, twins=16, draws=d).astype(float))
    # own and cut: the per-hit draws (VARY, the twins), the contact noise off: its realisation
    # can swing a hit by 10 dB (an ATK swell's end, BEND's glide); the noise sources are held
    # to the model's statistics on their own (test_fascia_live: test_noise_*), and the phrase
    # below plays with all of them
    ga, gb = (NOISY_A, NOISY_B) if res["noisy"] else (GROUP_A, GROUP_B)
    ma = [model_note(q, note, vel, seed=k) for k in ga]
    mb = [model_note(q, note, vel, seed=k) for k in gb]
    xa = [live_note(q, note, vel, seed=k) for k in ga]
    xb = [live_note(q, note, vel, seed=k) for k in gb]
    xf = [L.render_voice(q, note, vel, NOTE_S, seed=k, twins=16).astype(float) for k in ga]
    res["own"] = group_measure(ma, xa)
    res["base"] = group_measure(ma, mb)
    res["lbase"] = group_measure(xa, xb)          # live's own spread (a rattle varies a lot)
    res["cut"] = group_measure(xf, xa)
    if phrase:
        pe = [e for e in evs if e[0] < PHRASE_S]
        mp = model_phrase(p, pe, PHRASE_S)
        xp = L.render_notes(p, pe, PHRASE_S).astype(float)
        res["own"]["phrase"] = spec_dist(mp, xp)[0]
        res["base"]["phrase"] = max(spec_dist(mp, model_phrase(p, pe, PHRASE_S, seed_offset=o))[0]
                                    for o in (100, 200))
    return res


# -- tolerances -----------------------------------------------------------------------------
# det (the algorithm, the same hit): fixed and tight; what float32 in DSP order and the causal
# substitutions may cost where nothing is random. Under 0.5 dB in a sixth-octave band is
# under the ~1 dB JND of a band's level; 0.25 dB of level; T60 within 3 %; 0.5 cent.
DET = {"onset": 0.5, "body": 0.5, "tail": 0.5, "level": 0.25, "t60": math.log(1.03), "pitch": 0.5}
# own, cut (groups of n hits against the model's: three, six for a noisy patch): the model's
# own spread, with a margin. Spectra: 1.25 x the distance between two groups of the model's
# hits (or of live's, if more: a rattle's threshold makes a few hits a small sample) + 1 dB
# (about a band's level JND). Level, T60, pitch: three standard errors of a difference of two
# means of n (3 x sd x sqrt(2/n), sd over the model's group), and at least 1 dB, 10 % (decay-time
# differences under ~20 % are not heard as another instrument) and 3 cents (half the ~5-6 cent
# JND for complex tones). Patches with a measured causal deviation for the owner's ear: KNOWN.
SPEC_K, SPEC_DB = 1.25, 1.0
LEVEL_DB, T60_TOL, PITCH_C = 1.0, 0.10, 3.0
# WATR's level match is causal (running sums since the strike): its onset is drier than the
# model's whole-signal match (live.py, Water). Measured 2026-11-08; the owner to hear.
KNOWN = {"29_water_droplet_vibe": {"onset": 14.0, "phrase": 14.0, "level": 3.0, "body": 6.5,
                                   "pitch0": 10.0, "pitch1": 10.0},
         "30_water_glass": {"onset": 8.0, "phrase": 8.0, "level": 4.5, "t60": math.log(6.0)}}
# The twin cut on bells: the folded pairs no longer beat, and a T60 fitted to a beating
# envelope moves with it (the decay itself is the same: det is exact with all 16). Measured
# 2026-11-08 (three hits); the owner to hear 02 and 11 with and without the cut.
KNOWN_CUT = {"02_wind_chimes": {"t60": math.log(1.18), "tail": 5.0},
             "10_steel_pan": {"tail": 2.5},
             "11_bell_tower": {"t60": math.log(1.30)},
             "12_gong_morph": {"tail": 4.0},
             "30_water_glass": {"t60": math.log(2.0), "tail": 5.0}}


def limits(res: dict, name: str = "") -> dict:
    """the limits of 'own' and 'cut' for one patch"""
    base, lim = res["base"], {}
    lb = res.get("lbase", {})
    for w in ("onset", "body", "tail", "phrase"):
        if base.get(w) is not None:
            lim[w] = SPEC_K * max(base[w], lb.get(w) or 0.0) + SPEC_DB
    h = base["_hits"]
    k = 3.0 * math.sqrt(2.0 / len(h["level"]))
    lev = h["level"]
    lim["level"] = max(LEVEL_DB, k * float(np.std(lev, ddof=1)))
    if len(h["t60"]) >= 2:
        lim["t60"] = max(math.log(1 + T60_TOL), k * float(np.std(np.log(h["t60"]), ddof=1)))
    else:
        lim["t60"] = math.log(1 + T60_TOL)
    lim["held"] = max(LEVEL_DB, k * float(np.std(lev, ddof=1)))
    for i in range(2):
        c = [cc[i] for cc in h["cents"] if not math.isnan(cc[i])]
        lim[f"pitch{i}"] = max(PITCH_C, k * float(np.std(c, ddof=1))) if len(c) >= 2 else PITCH_C
    for kk, v in KNOWN.get(name, {}).items():
        lim[kk] = max(lim.get(kk, 0.0), v)
    return lim


def _check(r: dict, lim: dict, bad: list) -> list:
    for w in ("onset", "body", "tail", "phrase"):
        if r.get(w) is not None and lim.get(w) is not None and r[w] > lim[w]:
            bad.append(f"{w} {r[w]:.2f} > {lim[w]:.2f} dB")
    if abs(r["level"]) > lim["level"]:
        bad.append(f"level {r['level']:+.2f} > {lim['level']:.2f} dB")
    d = r["decay"]
    if d[0] == d[2] == "t60" and d[1] > 0 and abs(math.log(decay_ratio(d))) > lim["t60"]:
        bad.append(f"T60 x{decay_ratio(d):.3f} > x{math.exp(lim['t60']):.3f}")
    if d[0] == d[2] == "held" and abs(decay_ratio(d)) > lim["held"]:
        bad.append(f"held {decay_ratio(d):+.2f} > {lim['held']:.2f} dB")
    if d[0] != d[2]:
        bad.append(f"decay kind {d[0]} / {d[2]}")
    for i in range(2):
        c = r["pitch"][i]
        if math.isnan(c) or abs(c) > lim[f"pitch{i}"]:
            bad.append(f"pitch{i} {c:+.2f} > {lim[f'pitch{i}']:.2f} c")
    return bad


def failures(res: dict, which: str, name: str = "") -> list[str]:
    """what of RES[WHICH] ('det', 'cut' or 'own') is outside its limits"""
    if which == "det":
        if res["noisy"] or res["chaotic"] or name in KNOWN:
            return []
        lim = {w: DET[w] for w in ("onset", "body", "tail")}
        lim.update(level=DET["level"], t60=DET["t60"], held=DET["level"], pitch0=DET["pitch"],
                   pitch1=DET["pitch"])
        return _check(res["det"], lim, [])
    lim = limits(res, name)
    r = res[which]
    if which == "cut":
        r = {k: v for k, v in r.items() if k != "phrase"}
    for kk, v in KNOWN_CUT.get(name, {}).items():          # own includes the cut
        lim[kk] = max(lim.get(kk, 0.0), v)
    return _check(r, lim, [])


def fmt(r: dict) -> str:
    def f(v, spec="{:5.2f}"):
        return "  -  " if v is None or (isinstance(v, float) and math.isnan(v)) else spec.format(v)
    d = r["decay"]
    dr = decay_ratio(d)
    dtxt = (f"T60 {d[1]:.2f}/{d[3]:.2f} s (x{dr:.3f})" if d[0] == "t60" == d[2]
            else f"held {d[1]:.1f}/{d[3]:.1f} dB ({dr:+.2f})" if d[0] == "held" == d[2] else f"{d[0]}/{d[2]}")
    s = (f"spec onset {f(r['onset'])} body {f(r['body'])} tail {f(r['tail'])}"
         + (f" phrase {f(r['phrase'])}" if "phrase" in r else "")
         + f" | level {r['level']:+5.2f} dB | {dtxt} | pitch {f(r['pitch'][0], '{:+5.2f}')}"
         f" / {f(r['pitch'][1], '{:+5.2f}')} c")
    return s


# -- WAVs -----------------------------------------------------------------------------------
def _norm(x: np.ndarray, pk: float) -> np.ndarray:
    return np.asarray(x, float) / max(pk, 1.0) * 0.98


def write_mono(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(RATE))
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def write_lr(path: Path, a: np.ndarray, b: np.ndarray) -> None:
    n = max(len(a), len(b))
    s = np.zeros((n, 2))
    s[:len(a), 0], s[:len(b), 1] = a, b
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(int(RATE))
        w.writeframes((np.clip(s, -1, 1) * 32767).astype("<i2").tobytes())


def full_pair(name: str):
    p, evs, secs, trem = A.PATCHES[name]
    m = R.render_notes(p, evs, secs)
    x = L.render_notes(p, evs, secs).astype(float)
    if trem:
        t = np.arange(len(m)) / RATE
        tr = 1.0 - 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * trem * t))
        m, x = m * tr, x * tr
    return m, x


def main(out: str = "out/fascia-live") -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lines = ["FASCIA live.py against the design model, per audition patch (scripts/fascia_live_compare.py)",
             "spec: sixth-octave log-spectrum distance, dB RMS, level removed; windows of the first note",
             "(onset 0-50 ms, body 50-300 ms, tail 300-1000 ms) and the phrase's first second.",
             "det:  the deterministic twin (DUST 0, the model's draws and drift, 16 twins): the algorithm",
             "cut:  live with twins on 8 modes against all 16 (three hits each): the cost cut",
             "own:  three live hits (their own draws, contact noise off) against three of the model's;",
             "      phrase: the first second as the DSP plays it, every noise source on",
             "base: three of the model's hits against three others: the model's own spread (the limits);",
             "lbase: three live hits against three others: live's own (a limit uses the larger)",
             "WAVs: NAME.wav = model, 0.5 s, live; NAME.lr.wav = model left, live right (full phrase).", ""]
    for name in A.PATCHES:
        t = time.time()
        r = compare(name)
        m, x = full_pair(name)
        pk = max(float(np.max(np.abs(m))), float(np.max(np.abs(x))), 1e-9)
        gap = np.zeros(int(0.5 * RATE))
        write_mono(out / f"{name}.wav", np.concatenate([_norm(m, pk), gap, _norm(x, pk)]))
        write_lr(out / f"{name}.lr.wav", _norm(m, pk), _norm(x, pk))
        lim = limits(r, name)
        lines.append(name + ("   (KNOWN: a measured causal deviation, for the owner's ear)" if name in KNOWN else "")
                     + ("   (noisy: no deterministic twin)" if r["noisy"] else "")
                     + ("   (bowed: chaotic, its twin is reported, not held)" if r["chaotic"] else ""))
        for k in ("det", "cut", "own"):
            bad = failures(r, k, name)
            skip = k == "det" and (r["noisy"] or r["chaotic"] or name in KNOWN)
            ok = "not held" if skip else ("ok" if not bad else "OUT: " + "; ".join(bad))
            lines.append(f"  {k:5s} {fmt(r[k])}  {ok}")
        lines.append(f"  base  {fmt(r['base'])}")
        lines.append(f"  lbase {fmt(r['lbase'])}")
        lines.append("  limits " + " ".join(f"{k} {v:.2f}" for k, v in lim.items()))
        lines.append(f"  full render: model peak {np.max(np.abs(m)):.3f}, live peak {np.max(np.abs(x)):.3f}")
        print("\n".join(lines[-8:]), f"  ({time.time() - t:.0f} s)", flush=True)
    (out / "index.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/fascia-live")

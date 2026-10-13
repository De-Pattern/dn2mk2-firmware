"""The DSP contract (dnfw.ping.live) against the sound chosen by ear (ping/model.py).

    python ping/compare.py      # numbers; writes ping/demos/live_*.wav

Both are struck with the same click, one note at a time, with the same settings, and
compared on what matters for a ping: the pitch it rings at, how long it rings (the
time to -40 dB), and the peak. The live voice runs as the DSP will -- 32-sample
blocks of a track buffer, the settings read from record floats.
"""

import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
import model as M                                     # noqa: E402
from dnfw.ping import live as L                       # noqa: E402

T = L.tables()
N = 48000


def record(kind, res, freq_note, env=0.0, atk=0.5, dec=400.0, curve=0.7, strike=1.0, drive=0.5,
           keyt=1.0):
    """The record floats a FLTR page set this way would give (inverting live's maps)."""
    def inv(table, value_inc):
        best = min(range(128), key=lambda k: abs(table[k] - value_inc))
        return best / 127.0 + 1e-6
    return {L.R_TYPE: (L.TYPES.index(kind) + 0.5) / 4.0,
            L.R_FREQ: freq_note / 128.0,
            L.R_RES: res, L.R_DRIVE: drive,
            L.R_ATK: inv(T["atk"], 1.0 / (atk * 48.0)), L.R_DEC: inv(T["dec"], 1.0 / (dec * 48.0)),
            L.R_CURVE: (curve + 1.0) / 2.0, L.R_STRIKE: strike,
            L.R_DEPTH: 0.5 + env / 2.0, L.R_KEYT: 0.0}


def live_note(kind, note, src, **kw):
    rec = record(kind, kw.get("res", 0.5), note + kw.get("freq", 0.0), **{k: v for k, v in kw.items()
                                                                         if k not in ("res", "freq")})
    v = L.Voice()
    out = []
    for b in range(0, len(src), L.BLOCK):
        out += L.block(v, list(src[b:b + L.BLOCK]), rec, float(note), b == 0, T)
    return np.asarray(out)


def stats(y):
    pk = float(np.max(np.abs(y)))
    if pk == 0:
        return 0.0, 0.0, 0.0
    t40 = np.where(np.abs(y) > pk * 0.01)[0][-1] / 48000
    seg = y[1500:1500 + 8192] * np.hanning(8192)
    sp = np.abs(np.fft.rfft(seg, 1 << 17))
    f = (np.argmax(sp[50:]) + 50) * 48000 / (1 << 17)
    return f, t40, pk


def main():
    print(f"{'type':5s} {'res':>4s} {'note':>4s} | {'model Hz':>9s} {'live Hz':>8s} | {'model t40':>9s} {'live t40':>8s} | {'peak m':>6s} {'peak l':>6s}")
    for kind in L.TYPES:
        for res in (0.4, 0.7, 0.9):
            for note in (48, 72):
                kw = dict(res=res, env=0.0, atk=0.5, dec=900.0, curve=0.7, strike=1.0, drive=0.5)
                ym = np.asarray(M.voice(np.zeros(N), note, kind, freq=0.0, **kw))
                yl = live_note(kind, note, np.zeros(N), freq=0.0, **kw)
                fm, tm, pm = stats(ym)
                fl, tl, pl = stats(yl)
                print(f"{kind:5s} {res:4.1f} {note:4d} | {fm:9.1f} {fl:8.1f} | {tm:9.3f} {tl:8.3f} | {pm:6.3f} {pl:6.3f}")


if __name__ == "__main__":
    main()

"""GRAINS reference model: the two properties the SYNC mode is built on.

1. FMNT moves the timbre, not the pitch.
2. SPRD does not drop the note an octave (an earlier draft alternated the spread
   between grains, which made every second period different and put a
   subharmonic at half the note's frequency).
"""

import pathlib
import sys

import pytest

np = pytest.importorskip("numpy")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "grains"))

from model import RATE, Table, note_hz, render          # noqa: E402
from dnfw.waverider import testtable                    # noqa: E402

TABLE = Table(testtable.table())


def f0(x: np.ndarray) -> float:
    """The period: the shortest lag whose normalised autocorrelation is within
    3 % of the best. Normalised by the overlap at each lag, because the raw sum
    shrinks with the lag and so favours a short one (an octave or two up)."""
    x = x - x.mean()
    n = len(x)
    c = np.correlate(x, x, "full")[n - 1:] / (n - np.arange(n))
    lo, hi = RATE // 400, RATE // 30
    seg = c[lo:hi]
    i = int(np.argmax(seg >= 0.97 * seg.max()))
    while i + 1 < len(seg) and seg[i + 1] > seg[i]:      # climb to that peak's top
        i += 1
    return RATE / (lo + i)


def centroid(x: np.ndarray) -> float:
    s = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    return float((s * f).sum() / s.sum())


@pytest.mark.parametrize("win", [0, 0.5, 1])
@pytest.mark.parametrize("size", [1, 2, 3, 4])
@pytest.mark.parametrize("fmnt", [-12, 0, 7, 12, 24])
def test_fmnt_keeps_the_pitch(fmnt, size, win):
    """Whole-octave FMNT is the hard case: with a window that overlap-adds to a
    constant, the grains join into one wave an octave up."""
    x = render(TABLE, 0.4, 36, pos=15, fmnt=fmnt, size=size, win=win)[4800:14400]
    assert f0(x) == pytest.approx(note_hz(36), rel=0.01)


def test_fmnt_moves_the_timbre():
    lo = render(TABLE, 0.4, 36, pos=15, fmnt=-12, size=2)[4800:14400]
    hi = render(TABLE, 0.4, 36, pos=15, fmnt=24, size=2)[4800:14400]
    assert centroid(hi) > 3 * centroid(lo)


@pytest.mark.parametrize("sprd", [0, 3, 7])
def test_sprd_has_no_subharmonic(sprd):
    x = render(TABLE, 0.4, 43, pos=12, fmnt=7, size=3, sprd=sprd)[4800:14400]
    assert f0(x) == pytest.approx(note_hz(43), rel=0.01)

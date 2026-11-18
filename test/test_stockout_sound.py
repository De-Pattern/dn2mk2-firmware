"""stockout's sound checks (scripts/sharc_stockout_step.py, 2026-11-14): NaN and infinity are not sound, and a main
mix holding either is not finite. Until then `w & 0x7fffffff` counted a run of NaN as the stock run sounding."""
from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import sharc_stockout_step as SO  # noqa: E402


def w(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


NAN, QNAN_NEG, INF, NINF = 0x7FC00000, 0xFFC00001, 0x7F800000, 0xFF800000


def test_a_nan_frame_is_not_sound():
    assert not SO.sounds([NAN] * 64)
    assert not SO.sounds([QNAN_NEG, NAN] * 32)


def test_infinity_is_not_sound():
    assert not SO.sounds([INF, NINF] * 32)


def test_silence_is_not_sound():
    assert not SO.sounds([0, 0x80000000] * 32)          # +0.0 and -0.0


def test_a_finite_word_is_sound():
    assert SO.sounds([0] * 63 + [w(1e-6)])
    assert SO.sounds([w(-0.25)] + [NAN] * 63)            # sound, and the finite check below fails it


def test_finite():
    assert SO.finite([0, w(0.5), w(-3.0e38), 0x00000001])   # a denormal is finite
    assert not SO.finite([0] * 63 + [NAN])
    assert not SO.finite([w(0.5), INF])

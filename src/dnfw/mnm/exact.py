"""The Monomachine's increments in integer arithmetic, as its kernel and renders compute them
(docs/mnm.md). The DSP computes them in float from the DN2's pitch (each machine's `pitch`);
the tests compute them here from the golden runs' own increment A and pitch word F, so a
machine's per-sample code is checked on exactly the Monomachine's increments, and `pitch`
is checked against these separately."""

from __future__ import annotations

import functools

from . import rom

M24 = 0xFFFFFF
M56 = (1 << 56) - 1


def s24(v: int) -> int:
    v &= M24
    return v - (1 << 24) if v & 0x800000 else v


def s56(v: int) -> int:
    v &= M56
    return v - (1 << 56) if v >> 55 else v


def lim(a: int) -> int:
    if a >= 1 << 47:
        return 0x7FFFFF
    if a < -(1 << 47):
        return 0x800000
    return (a >> 24) & M24


def a1(a: int) -> int:
    return (a >> 24) & M24


def a0(a: int) -> int:
    return a & M24


def mpy(x: int, y: int) -> int:
    return (s24(x) * s24(y)) << 1


def set1(a: int, w: int) -> int:
    return s56((a & ~(M24 << 24)) | ((w & M24) << 24))


def acc(w: int) -> int:
    return s24(w) << 24


@functools.lru_cache(maxsize=1)
def exp_table() -> tuple[int, ...]:
    return tuple(rom.words(0x140000, 2048))


def exp_word(a: int) -> int:
    """(table[F & 0x7ff] >> 10) << (F >> 11), F in a1, as an accumulator"""
    b = a >> 11
    a = set1(a, a1(a) & 0x7FF)
    r2, x0 = lim(a), lim(b)
    a = acc(exp_table()[r2]) >> 10
    return s56(a << (x0 & 0x3F))


def increment(F: int) -> int:
    """A, the kernel's increment for the pitch word F (P:0x2DD..0x2EA)"""
    a = exp_word(acc(F))
    a = mpy(0x1D22A, lim(a))
    return a >> 3


def wave_inc(A: int, frac: int) -> int:
    """DPRO-WAVE's phase increment (samples, FRAC fraction bits): A x 0x2f8e (MPYSU, DMACSS)"""
    a = (s24(0x2F8E) * (a0(A) & M24)) << 1
    a = (a >> 24) + mpy(0x2F8E, a1(A))
    return (a1(a) << frac) + (a0(a) >> (24 - frac))


def sync_period(F: int) -> int:
    """DPRO-WAVE's sync period in blocks for the pitch word F"""
    a = exp_word(acc(F))
    a = mpy(0x20B40, lim(a)) << 12
    x0 = lim(s56(a))
    return (0xAC44 << 12) // x0 if x0 else 0


def wave_sync(knobs, pre: int = 0) -> int:
    """the period for SYNC's setting, or 0 (OFF, or SFRQ 0)"""
    sync, sfrq = knobs[4] << 16, knobs[5] << 16
    if sync < 0x2AAAAA:
        return 0
    if sync >= 0x555555:
        return sync_period(pre)
    if sfrq == 0:
        return 0
    return sync_period(52 * knobs[5] + 0x1000)


def sid_x0(A: int, noise: bool) -> int:
    """SID's increment a sample: (A >> 15) MACUU 0xFD9FB3, >> 5 (a1), x 16 for NOIS, limited"""
    a = A >> 15
    a = a + ((a0(a) * 0xFD9FB3) << 1)
    a = set1(a, a1(a) >> 5)
    x0 = lim(a)
    if noise:
        x0 = lim(s56(a << 4))
    return x0


def sid_minc(F: int) -> int:
    """SID's second oscillator's increment for the pitch word F"""
    a = exp_word(acc(F))
    a = mpy(0x20B40, lim(a)) >> 18
    a = ((a0(a) & M24) * 0xFD9FB3) << 1
    a = set1(a, a1(a) >> 2)
    return lim(a)


def sid_incs(A: int, knobs, pre: int = 0) -> tuple[int, int]:
    noise = (knobs[3] << 16) >= 0x666666
    x0 = sid_x0(A, noise)
    F2 = pre if (knobs[5] << 16) >= 0x400000 else 64 * knobs[6] + 0x800
    return x0, sid_minc(F2)

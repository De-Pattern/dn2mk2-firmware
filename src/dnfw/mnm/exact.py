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


# -- DPRO-DENS / DPRO-DDRW: the increments (b, top-level samples a 2x step, 24 fraction bits) --
SUB, SUB_B = 0x17C70, 0x1AA17
M32 = 0xFFFFFFFF


def _l48(a: int) -> tuple[int, int]:
    """move a,l: (hi, lo), the 48-bit limiter"""
    if a >= 1 << 47:
        return 0x7FFFFF, 0xFFFFFF
    if a < -(1 << 47):
        return 0x800000, 0
    return (a >> 24) & M24, a & M24


def _dmac_ss(x0: int, lo: int, hi: int) -> int:
    """mpysu x0,lo ; dmacss x0,hi"""
    return (((s24(x0) * (lo & M24)) << 1) >> 24) + mpy(x0, hi)


def _dmac_su(y: int, lo: int, hi: int) -> int:
    """mpysu y,lo ; dmacsu y,hi"""
    return (((s24(y) * (lo & M24)) << 1) >> 24) + ((s24(y) * (hi & M24)) << 1)


def _b(inc: int, k: int = SUB) -> int:
    hi, lo = _l48(inc)
    return _dmac_ss(k, lo, hi)


def dens_incs(A: int, knobs) -> dict:
    """DENS (P:0x147D1D..0x147D5E): i1..i4 the four oscillators' b (mod 2^32), i5 the muted
    ones (bit k: oscillator k's increment >= 0x4E20 Hz, or the same whole Hz as oscillator 1)"""
    hi, lo = _l48(s56(A))
    pch = rom.words(*rom.PCH)
    out = {"i1": _b(s56(A)) & M32}
    mute = 0
    for k in range(3):
        inc = s56(_dmac_ss(pch[knobs[k]], lo, hi) << 2)
        h, _ = _l48(inc)
        if s24(h) >= 0x4E20 or h == hi:
            mute |= 2 << k
        out[f"i{k + 2}"] = _b(inc) & M32
    out["i5"] = mute
    return out


def ddrw_incs(A: int, knobs) -> dict:
    """DDRW (P:0x147B56..0x147B7B, 0x147BC7): i1, i2 the two waves' b (level A), i3, i4 the
    same for level B (x 0x1AA17 / 0x17C70)"""
    hi, lo = _l48(s56(A))
    wid, mix = knobs[5], knobs[1] << 16
    t1, t2 = rom.words(*rom.WID[0])[wid], rom.words(*rom.WID[1])[wid]
    a = s56(acc(mix) << 1) + acc(0x800000)
    a = s56(abs(a))
    b = acc(0x7FFFFF) - a
    x0 = lim(b)
    b = acc(t2) - acc(0x400000)
    a = acc(t1) - acc(0x400000)
    y0, y1 = lim(b), lim(a)
    b, a = mpy(y0, x0) + acc(0x400000), mpy(x0, y1) + acc(0x400000)
    y1, y0 = lim(b), lim(a)
    out = {}
    for n, r in ((1, y0), (2, y1)):
        inc = s56(_dmac_su(r, lo, hi) << 1)
        out[f"i{n}"] = _b(inc) & M32
        out[f"i{n + 2}"] = _b(inc, SUB_B) & M32
    return out


# -- VO-6 (v0.26, dnfw.mnm.vo6) -------------------------------------------------------------
def _clb(a: int) -> int:
    A = a & M56
    if A == 0:
        return 0
    sgn, k = (A >> 55) & 1, 0
    while k < 56 and ((A >> (55 - k)) & 1) == sgn:
        k += 1
    return 9 - k


def _normf(n: int, a: int) -> int:
    n = s24(n)
    return a >> min(n, 56) if n >= 0 else s56(a << min(-n, 56))


def vo6_period(w: int) -> int:
    """VO-6's pulse period for the increment word w (the render's P:0x1469BF..0x146A28: clb,
    normf, 24 DIV steps of 0x2B1100 by the normalised w, normf back): samples << 24, 48 bits,
    within 2^-24 relative of 44100 / w"""
    if w <= 0:
        return 0
    a = acc(w)
    b = _clb(a)
    a = _normf(b, a)
    x0 = lim(a)
    a, c, s = acc(0x2B1100), 0, s24(x0)
    for _ in range(24):
        a2 = s56((a << 1) | c)
        a = s56(a2 + (s << 24) if (a < 0) != (s < 0) else a2 - (s << 24))
        c = 1 if a >= 0 else 0
    a = acc(a0(a))
    return _normf(b + 0x1D, a) & ((1 << 48) - 1)


def vo6_incs(A: int) -> dict:
    """i1, i2: the period's whole samples and 24 fraction bits; i3: w = lim(A), the pitch in Hz"""
    w = lim(s56(A))
    X = vo6_period(w)
    return {"i1": X >> 24, "i2": X & M24, "i3": w}

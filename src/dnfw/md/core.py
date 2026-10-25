"""The Machinedrum machines' common ground on the DN2's DSP (docs/md.md).

Numbers. The Machinedrum's DSP2 (a DSP56300) works in 24-bit fractions (Q23) with 56-bit
accumulators. Here a Q23 word w is the float w / 2^23, so full scale is +-1, and:

- `mpy(x, y)` (the 56300's fractional product) is x * y;
- storing an accumulator through the 56300's limiter, `sat`, is a clamp to [-1, 1 - 2^-23];
- a 48-bit envelope or phase in two words is one float (a float has 24 bits of mantissa:
  the per-sample decays, 1 - 2^-19 at the slowest, still move it, and the error is far below
  hearing);
- a phase is an unsigned 32-bit integer whose top 15 bits index the 32768-word sine
  table (`SINE_SHIFT`), so it wraps as the 56300's 15-bit mask wraps it.

The arithmetic is the Machinedrum's, step for step; it is not bit-exact (that would take
48-bit products the DN2's float unit does not have), and test/test_md.py holds every
machine to the Machinedrum's own output (its DSP code run in an emulator) within a bound.

Memory. Each voice slot has a block of MD_STRIDE bytes (I3 points at it): the host's
words W (as the Machinedrum's host sends them), the machine's state S, the stream of
44.1 kHz samples the resampler reads, and the voice's own words. The tables (the sine,
the host's pitch and decay tables, DSP2's ROM tables) are in DDR (`TABLES`).
"""

from __future__ import annotations

import math

from . import rom
from ..perc.dsl import Prog

Q23 = 2.0 ** -23
TOP = 1.0 - Q23                          # the largest positive Q23 word
MD_RATE = 44100.0
DN2_RATE = 48000.0
STEP = MD_RATE / DN2_RATE                # MD samples per DN2 sample: 0.91875
SINE_N = 32768
SINE_SHIFT = 17                          # phase >> 17 = the sine index (15 bits)
PHASE_ONE = 1 << SINE_SHIFT              # one sine index in phase units

# -- a slot's words (I3) ---------------------------------------------------------------
W0, NW = 0, 64                           # the host's words, W[k] at k (k = 1..63)
S0, NS = 64, 96                          # the machine's state
B0, NB = 160, 67                         # the stream: 3 old samples, then two blocks of 32
OUT0 = B0 + 35                           # where a block is rendered (B[35..66])
VW = dict(pos=228, mach=229, live=230, inp=231, trg=232, last=233, want=234, dirty=235, quiet=244, chg=245)   # the voice's own
INP0 = 236                               # the eight 14-bit inputs (ints), 236..243
MD_WORDS = 256
MD_STRIDE = 4 * MD_WORDS                 # 1 KB a slot

# -- the tables in DDR: see the end of this module (they need md_sine_words) ------------


def _s24(v: int) -> int:
    v &= 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


PI_DELAY_STRIDE = 8192                   # v0.24: a slot's P-I delay lines, 2048 words (floats)
PI_DELAY_WORDS = PI_DELAY_STRIDE // 4


class Layout:
    """Where the MD voices live (dnfw.waverider.dsp gives the addresses). DELAY: the
    P-I machines' delay lines, PI_DELAY_STRIDE a slot (default 1 MB past the state)."""

    def __init__(self, state: int, scratch: int, tables: int, delay: int | None = None):
        self.state, self.tables = state, tables
        self.delay = state + 0x100000 if delay is None else delay
        self.T = {name: tables + off for name, (off, _n) in TABLE_LAYOUT.items()}
        self.C = {w: scratch + 4 * k for k, w in enumerate(SC_WORDS)}


SC_WORDS = ("n1", "n2", "n3", "a", "b", "c", "d", "e", "f", "g", "h", "k", "fill", "tmp", "mdb",
            "cw", "cs", "cv", "ash", "ufill")
# fill, cw, cs, cv, ufill: table_fill's (the words decoded, the bit, the last three words)
# ash: the word dsl.ash saves its count register in
# mdb: the slot's words' address (what I3 holds), for code that needs it in an R register


def delay_base(p: Prog, L: Layout, d: int) -> None:
    """Rd = this slot's P-I delay lines (L.delay + PI_DELAY_STRIDE x the slot). Clobbers R12."""
    p.ld(d, L.C["mdb"])
    p.iconst(12, -L.state)
    p.iop(d, 12, "+", d)                       # slot x 1 KB
    p.lsh(d, d, 3)                             # x 8 KB
    p.iconst(12, L.delay)
    p.iop(d, 12, "+", d)


# -- slot words --------------------------------------------------------------------------
def w(p: Prog, d: int, k: int) -> None:
    """Fd/Rd = the host's word k."""
    p.ldi(d, W0 + k, 3)


def ws(p: Prog, k: int, s: int) -> None:
    p.sti(W0 + k, 3, s)


def s(p: Prog, d: int, k: int) -> None:
    """Fd/Rd = the machine's state word k."""
    p.ldi(d, S0 + k, 3)


def ss(p: Prog, k: int, r: int) -> None:
    p.sti(S0 + k, 3, r)


def vw(p: Prog, d: int, name: str) -> None:
    p.ldi(d, VW[name], 3)


def vws(p: Prog, name: str, r: int) -> None:
    p.sti(VW[name], 3, r)


def inp(p: Prog, d: int, k: int) -> None:
    """Rd = input k (0..16383), as the Machinedrum's host passes it to a scale function."""
    p.ldi(d, INP0 + k, 3)


# -- arithmetic --------------------------------------------------------------------------
def sat(p: Prog, x: int, t: int = 12) -> None:
    """Fx = the 56300 limiter: clamp to [-1, TOP]. Clobbers Rt."""
    p.fconst(t, TOP)
    p.fop(x, x, "MIN", t)
    p.fconst(t, -1.0)
    p.fop(x, x, "MAX", t)


def mul_k(p: Prog, d: int, a: int, k: float, t: int = 12) -> None:
    """Fd = Fa * k. Clobbers Rt."""
    p.fconst(t, k)
    p.fop(d, a, "*", t)


def add_k(p: Prog, d: int, a: int, k: float, t: int = 12) -> None:
    p.fconst(t, k)
    p.fop(d, a, "+", t)


def to_float(p: Prog, d: int, a: int, scale_log2: int = 0, t: int = 12) -> None:
    """Fd = Ra (signed) * 2^scale_log2. Clobbers Rt."""
    p.iconst(t, scale_log2)
    p.float_(d, a, t)


def q23(p: Prog, d: int, a: int, t: int = 12) -> None:
    """Fd = Ra as a Q23 word (Ra a signed 24-bit integer in a 32-bit register)."""
    to_float(p, d, a, -23, t)


def to_int(p: Prog, d: int, a: int) -> None:
    """Rd = trunc Fa."""
    p.trunc(d, a)


def table_f(p: Prog, L: Layout, d: int, name: str, idx: int, t: int = 12) -> None:
    """Fd = TABLE[name][Ridx] (Ridx an integer in range). Clobbers Rt, R13, I1 (t != 13)."""
    assert t != 13
    p.lsh(t, idx, 2)
    p.iconst(13, L.T[name])
    p.iop(d, 13, "+", t)
    p.seti(1, d)
    p.ldi(d, 0, 1)


def sine(p: Prog, L: Layout, d: int, ph: int, t: int = 12) -> None:
    """Fd = SINE[Rph >> 17] (Rph an unsigned 32-bit phase). Clobbers Rt, R13, I1."""
    p.lsh(t, ph, -SINE_SHIFT)
    table_f(p, L, d, "sine", t, t)


def phase_inc(p: Prog, d: int, x: int, t: int = 12) -> None:
    """Rd = Fx sine indices as phase units, modulo a turn (the 56300 wraps the 48-bit sum
    and masks the index to 15 bits): Fx is first brought into [-16384, 16384). Fx is
    changed. Clobbers Rt, R13."""
    p.fconst(t, 1.0 / SINE_N)
    p.fop(d, x, "*", t)
    p.trunc(d, d)                            # whole turns (towards zero)
    p.iconst(t, 0)
    p.float_(d, d, t)
    p.fconst(t, float(SINE_N))
    p.fop(d, d, "*", t)
    p.fop(x, x, "-", d)                      # (-32768, 32768)
    p.fconst(t, SINE_N / 2.0)
    p.if_(x, "GE", t, lambda: (p.fconst(13, float(SINE_N)), p.fop(x, x, "-", 13)))
    p.fconst(t, -SINE_N / 2.0)
    p.if_(x, "LT", t, lambda: (p.fconst(13, float(SINE_N)), p.fop(x, x, "+", 13)))
    p.fconst(t, float(PHASE_ONE))
    p.fop(d, x, "*", t)
    p.trunc(d, d)


def fib(p: Prog, L: Layout, k1: int, k2: int, d: int) -> None:
    """The Machinedrum's additive Fibonacci noise: f1, f2 = f2, (f1 + f2) mod 2^24, its
    state in state words k1, k2 (24-bit integers); Fd = the new value as a Q23 word.
    Clobbers R12, R13."""
    s(p, 12, k1)
    s(p, 13, k2)
    ss(p, k1, 13)
    p.iop(13, 12, "+", 13)
    p.iconst(12, 0xFFFFFF)
    p.iop(13, 13, "AND", 12)
    ss(p, k2, 13)
    p.lsh(12, 13, 8)                    # the 24-bit word into the top: a signed 32-bit
    p.iconst(13, -31)
    p.float_(d, 12, 13)


# -- the sine -----------------------------------------------------------------------------
def sine_value(k: int) -> float:
    """What the table's word k approximates (DSP2's own table, within 6.5 LSB)."""
    x = k + (1.5 if k >= 3 * SINE_N // 4 else 0.0)
    return max(-1.0, min(TOP, math.sin(2.0 * math.pi * x / SINE_N)))


def md_sine_words() -> list[int]:
    """DSP2's sine table, word for word (signed 24-bit): its boot code's 48-bit recursion
    y[n+1] = 2 cos(2 pi / 32768) y[n] - y[n-1], with its partial products' shifts and its
    limiter, from y[0] = 0, y[1] = sin(2 pi / 32768) (both as 48-bit fractions). The
    limiter clamps at the trough, after which the table runs 1.5 indices ahead."""
    def s24(v):
        v &= 0xFFFFFF
        return v - (1 << 24) if v & 0x800000 else v
    x1, x0 = 0x7FFFFF, 0xD88586                # cos, hi:lo
    st = [0, (0x000648 << 24) | 0x7ED46B]
    out = [0, 0x648]
    idx = 1
    for _ in range(SINE_N - 2):
        y = st[idx]
        y1, y0 = y >> 24, y & 0xFFFFFF
        a = (x0 * y0) << 1
        a = (a >> 24) + ((s24(x1) * y0) << 1)
        a += (s24(y1) * x0) << 1
        a = (a >> 24) + ((s24(x1) * s24(y1)) << 1)
        a <<= 1
        idx ^= 1
        o = st[idx]
        a -= (s24(o >> 24) << 24) | (o & 0xFFFFFF)
        a = max(-(1 << 47), min((1 << 47) - 1, a))
        st[idx] = a & ((1 << 48) - 1)
        out.append((a >> 24) & 0xFFFFFF)
    return [s24(v) for v in out]


def mpy_floor(p: Prog, d: int, a: int, b: int) -> None:
    """Fd = the 56300's product of two Q23 words through the limiter, exactly:
    floor(A B / 2^23) / 2^23 for the words A = Fa 2^23, B = Fb 2^23 (Fa, Fb >= 0, exact Q23
    values). Where a product feeds back on itself block after block (an envelope), the
    56300's truncation is what sets how fast it falls, and a float product does not
    truncate; this does, with 12-bit halves whose partial products a float holds exactly.
    Clobbers R0-R3, R12-R15 (d, a, b not among them)."""
    def split(x, hi, lo):
        p.fconst(12, 2.0 ** 23)
        p.fop(hi, x, "*", 12)
        p.trunc(hi, hi)                       # the word, an integer
        p.iconst(12, 4095)
        p.iop(lo, hi, "AND", 12)
        p.lsh(hi, hi, -12)
    split(a, 0, 1)                            # ah, al
    split(b, 2, 3)                            # bh, bl
    for r in (0, 1, 2, 3):
        p.iconst(12, 0)
        p.float_(r, r, 12)
    p.fop(13, 0, "*", 3)                      # ah bl
    p.fop(14, 1, "*", 2)                      # al bh
    p.trunc(13, 13)
    p.trunc(14, 14)
    p.iop(13, 13, "+", 14)                    # m
    p.fop(14, 1, "*", 3)                      # al bl
    p.trunc(14, 14)
    p.lsh(14, 14, -12)
    p.iop(13, 13, "+", 14)
    p.lsh(13, 13, -11)                        # floor((m 2^12 + n) / 2^23)
    p.fop(14, 0, "*", 2)                      # ah bh
    p.trunc(14, 14)
    p.lsh(14, 14, 1)
    p.iop(13, 13, "+", 14)
    p.iconst(12, -23)
    p.float_(d, 13, 12)


def mpyf_any(p: Prog, d: int, a: int, b: int) -> None:
    """Fd = mpy_floor(Fa, Fb) through trx1.mpyf's one shared copy (F9 = floor(F10 F11)),
    or inline inside another subroutine (v0.24: the DSP's 1 MiB upload buffer). Clobbers
    R0-R3, R9-R15, I12."""
    if p.in_sub:
        mpy_floor(p, d, a, b)
        return
    assert b != 10
    p.fpass(10, a)
    p.fpass(11, b)
    p.call("trx1_mpyf", lambda: mpy_floor(p, 9, 10, 11))
    p.fpass(d, 9)


# -- the tables in DDR ------------------------------------------------------------------
#   sine: 32768 floats (Q23), DSP2's own table word for word
#   the host's D, Q, R, A, S, B and DSP2's ROM tables: floats (Q23)
#   P: 128 ints (pitch), shipped as they are
# v0.24: the sine and every Q23 table ship as one compressed stream (zpack) that the DSP
# decodes into its floats at power-on, Z_PER_BLOCK words a block (table_fill); before,
# the sine shipped as 5-bit corrections to a polynomial and the tables packed 24 bits a
# word, and the P-I machines' tables no longer fitted the DSP's 1 MiB upload buffer.
#
# zpack: a bit stream, least significant bit first through 32-bit words. Blocks of
# Z_GROUP words, each a 7-bit header (mode: 2 bits, then width: 5 bits) and Z_GROUP
# residuals of WIDTH bits, signed (none when WIDTH is 0). A word x is its residual r plus
# a prediction from the three words before it (p1, p2, p3: across blocks and tables, 0 at
# the start): mode 0, x = r; 1, p1 + r; 2, 2 p1 - p2 + r; 3, 3 p1 - 3 p2 + p3 + r.

Z_GROUP = 16
Z_PER_BLOCK = 2048                          # words decoded a DN2 block (128 groups): 29 blocks


def _table_layout() -> dict[str, tuple[int, int]]:
    at, out = 0, {}
    for name, (_a, n) in rom.HOST_TABLES.items():
        if name != "P":
            out[f"host{name}"] = (at, n)
            at += 4 * n
    for name, (_a, n) in rom.DSP_TABLES.items():
        out[name] = (at, n)
        at += 4 * n
    out["sine"] = (at, SINE_N)                 # last: the tables are whole first (13 blocks)
    at += 4 * SINE_N
    nz = at // 4
    out["zpad"] = (at, -nz % Z_PER_BLOCK)       # rounds the decoded words to whole blocks
    at += 4 * out["zpad"][1]
    out["hostP"] = (at, rom.HOST_TABLES["P"][1])
    at += 4 * out["hostP"][1]
    out["zpack"] = (at, len(_zpack_words()))
    at += 4 * out["zpack"][1]
    out["_end"] = (at, 0)
    return out


Z_N = None                                   # the decoded words (set below)


def _z_values() -> list[int]:
    """The words zpack decodes to, in order (signed 24-bit): the tables, then the sine."""
    vals = []
    for name, (_a, n) in rom.HOST_TABLES.items():
        if name != "P":
            vals += [_s24(x) for x in rom.host_table(name)]
    for name in rom.DSP_TABLES:
        vals += [_s24(x) for x in rom.dsp_table(name)]
    vals += md_sine_words()
    vals += [0] * (-len(vals) % Z_PER_BLOCK)
    return vals


def _z_width(xs: list[int]) -> int:
    m = max(max(xs), -min(xs) - 1)
    return m.bit_length() + 1 if any(xs) else 0


_ZPACK: list[int] | None = None


def _zpack_words() -> list[int]:
    """zpack as 32-bit words, and one more (the reader may look a word ahead)."""
    global _ZPACK
    if _ZPACK is None:
        vals = _z_values()
        acc, nbits = 0, 0
        p1 = p2 = p3 = 0
        for g in range(0, len(vals), Z_GROUP):
            best = None
            for mode in range(4):
                q1, q2, q3, rs = p1, p2, p3, []
                for x in vals[g:g + Z_GROUP]:
                    rs.append(x - (0, q1, 2 * q1 - q2, 3 * q1 - 3 * q2 + q3)[mode])
                    q3, q2, q1 = q2, q1, x
                w = _z_width(rs)
                if w <= 24 and (best is None or w < best[1]):
                    best = (mode, w, rs)
            mode, w, rs = best
            acc |= (mode | w << 2) << nbits
            nbits += 7
            for r in (rs if w else ()):
                acc |= (r & ((1 << w) - 1)) << nbits
                nbits += w
            p3, p2, p1 = vals[g + Z_GROUP - 3], vals[g + Z_GROUP - 2], vals[g + Z_GROUP - 1]
        n = (nbits + 31) // 32 + 1
        _ZPACK = [(acc >> (32 * k)) & 0xFFFFFFFF for k in range(n)]
    return _ZPACK


def z_decode(words: list[int], n: int) -> list[int]:
    """zpack's words -> the first N words it holds (the decoder's model, in Python)."""
    acc = sum(w << (32 * k) for k, w in enumerate(words))
    pos, out, p1, p2, p3 = 0, [], 0, 0, 0

    def read(k):
        nonlocal pos
        v = (acc >> pos) & ((1 << k) - 1)
        pos += k
        return v
    while len(out) < n:
        h = read(7)
        mode, w = h & 3, h >> 2
        for _ in range(Z_GROUP):
            r = read(w) if w else 0
            if w and r >> (w - 1):
                r -= 1 << w
            x = r + (0, p1, 2 * p1 - p2, 3 * p1 - 3 * p2 + p3)[mode]
            out.append(x)
            p3, p2, p1 = p2, p1, x
    return out


TABLE_LAYOUT = _table_layout()
Z_N = len(_z_values())
SHIPPED = "hostP"                             # the first shipped word: hostP, then zpack


def tables_bytes() -> bytes:
    """What ships, from TABLE_LAYOUT[SHIPPED] on: the host's pitch table and zpack (the
    sine and the Q23 tables, which the DSP decodes itself); read from the owner's
    Machinedrum firmware (rom.py), at build time."""
    import struct
    p = struct.pack(f"<{TABLE_LAYOUT['hostP'][1]}I", *rom.host_table("P"))
    z = struct.pack(f"<{TABLE_LAYOUT['zpack'][1]}I", *_zpack_words())
    return p + z


def _shift_r(p: Prog, d: int, a: int, s: int, arith: bool = False) -> None:
    """Rd = (A|L)SHIFT Ra BY Rs, Rs's low byte a signed count in -31..31."""
    p.e(f"R{d} = {'ASHIFT' if arith else 'LSHIFT'} R{a} BY R{s};")
    if p.run:
        from ..perc.dsl import s32
        n = p.r[s] & 0xFF
        n = n - 256 if n & 0x80 else n
        assert -31 <= n <= 31, n
        x = s32(p.r[a]) if arith else p.r[a] & 0xFFFFFFFF
        p.setR(d, (x << n) if n >= 0 else (x >> -n))


def _z_read(p: Prog, L: Layout, n: int, signed: bool) -> None:
    """R2 = the next Rn bits of zpack (1..24; n is R5 or R6), signed or not; the bit
    position (C['cw']) moves on. Clobbers R0-R4, R7, R12, R13, I1."""
    C = L.C
    p.ld(0, C["cw"])
    p.lsh(1, 0, -5)
    p.lsh(1, 1, 2)
    p.iconst(12, L.T["zpack"])
    p.iop(1, 12, "+", 1)
    p.seti(1, 1)
    p.ldi(2, 0, 1)
    p.iconst(12, 31)
    p.iop(3, 0, "AND", 12)                    # sh: the bit in the word
    p.iconst(12, 0)
    p.iop(4, 12, "-", 3)
    _shift_r(p, 2, 2, 4)                       # the word's bits from sh on
    p.ipass(12, n)
    p.iop(4, 12, "+", 3)                       # sh + n
    p.iconst(13, 32)

    def straddle():                            # sh >= 9 here: the rest from the next word
        p.ldi(7, 1, 1)
        p.iconst(12, 32)
        p.iop(4, 12, "-", 3)
        _shift_r(p, 7, 7, 4)
        p.iop(2, 2, "OR", 7)
    p.if_(4, "GT", 13, straddle, kind="i")
    p.iconst(12, 32)
    p.iop(4, 12, "-", n)                       # 32 - n
    _shift_r(p, 2, 2, 4)
    p.iconst(12, 0)
    p.iop(4, 12, "-", 4)
    _shift_r(p, 2, 2, 4, arith=signed)
    p.ld(12, C["cw"])
    p.iop(0, 12, "+", n)
    p.st(C["cw"], 0)


def table_fill(p: Prog, L: Layout) -> None:
    """Z_PER_BLOCK more words of the sine and the Q23 tables from zpack, from C['fill']
    (0 at power-on, as are the bit position C['cw'] and the last words C['cs'], C['cv'],
    C['ufill'])
    until all Z_N are (C['fill'] = Z_N). Each word x is stored as FLOAT x BY -23. Clobbers
    R0-R13, I1, I2."""
    C = L.C
    p.ld(0, C["fill"])
    p.iconst(12, Z_N)
    p.e("COMP(R0, R12);")

    def more():
        p.ld(0, C["fill"])
        p.lsh(1, 0, 2)
        p.iconst(12, L.tables)
        p.iop(1, 12, "+", 1)
        p.seti(2, 1)                           # I2: where the words go

        def group():
            p.iconst(5, 7)
            _z_read(p, L, 5, False)
            p.iconst(12, 3)
            p.iop(0, 2, "AND", 12)
            p.st(C["g"], 0)                    # mode
            p.lsh(6, 2, -2)
            p.st(C["h"], 6)                    # width

            def word():
                p.ld(6, C["h"])
                p.iconst(2, 0)
                p.ifz(6, "NE", lambda: _z_read(p, L, 6, True))
                p.ld(8, C["cs"])               # p1
                p.ld(9, C["cv"])               # p2
                p.ld(0, C["g"])
                p.iconst(12, 1)

                def d1():
                    p.iop(2, 8, "+", 2)
                p.if_(0, "EQ", 12, d1, kind="i")
                p.iconst(12, 2)

                def d2():
                    p.iop(2, 8, "+", 2)
                    p.iop(2, 8, "+", 2)
                    p.iop(2, 2, "-", 9)
                p.if_(0, "EQ", 12, d2, kind="i")
                p.iconst(12, 3)

                def d3():
                    p.ld(10, C["ufill"])       # p3
                    for _ in range(3):
                        p.iop(2, 8, "+", 2)
                        p.iop(2, 2, "-", 9)
                    p.iop(2, 10, "+", 2)
                p.if_(0, "EQ", 12, d3, kind="i")
                p.st(C["ufill"], 9)
                p.st(C["cv"], 8)
                p.st(C["cs"], 2)
                p.iconst(12, -23)
                p.float_(4, 2, 12)
                p.stpost(2, 4)
            p.loop(C["n3"], Z_GROUP, word)
        p.loop(C["tmp"], Z_PER_BLOCK // Z_GROUP, group)
        p.ld(0, C["fill"])
        p.iconst(12, Z_PER_BLOCK)
        p.iop(0, 12, "+", 0)
        p.st(C["fill"], 0)
    p._branch(lambda: p.r[0] < Z_N, "LT", more, None)

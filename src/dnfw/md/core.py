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
VW = dict(pos=228, mach=229, live=230, inp=231, trg=232, last=233, want=234, dirty=235)   # the voice's own
INP0 = 236                               # the eight 14-bit inputs (ints), 236..243
MD_WORDS = 256
MD_STRIDE = 4 * MD_WORDS                 # 1 KB a slot

# -- the tables in DDR ------------------------------------------------------------------
#   sine: 32768 floats, made by the DSP itself at start-up (sine_fill), not shipped
#   P: 128 ints (pitch), D: 512 floats (decay coefficients, Q23), Q: 512, R: 128 floats
#   the ROM tables: floats (Q23)


def _table_layout() -> dict[str, tuple[int, int]]:
    at, out = 0, {}
    out["sine"] = (at, SINE_N)
    at += 4 * SINE_N
    for name, (_a, n) in rom.HOST_TABLES.items():
        out[f"host{name}"] = (at, n)
        at += 4 * n
    for name, (_a, n) in rom.DSP_TABLES.items():
        out[name] = (at, n)
        at += 4 * n
    out["_end"] = (at, 0)
    return out


TABLE_LAYOUT = _table_layout()


def tables_bytes() -> bytes:
    """Everything in TABLES but the sine (which the DSP fills itself): read from the
    owner's Machinedrum firmware (rom.py), at build time."""
    import struct
    start = TABLE_LAYOUT["hostP"][0]
    out = bytearray(TABLE_LAYOUT["_end"][0] - start)
    for name, (off, n) in TABLE_LAYOUT.items():
        if name in ("sine", "_end"):
            continue
        if name.startswith("host"):
            t = rom.host_table(name[4:])
            if name == "hostP":
                data = struct.pack(f"<{n}I", *t)
            else:
                data = struct.pack(f"<{n}f", *(float(_s24(x)) * Q23 for x in t))
        else:
            data = struct.pack(f"<{n}f", *(x * Q23 for x in rom.dsp_table(name)))
        out[off - start:off - start + len(data)] = data
    return bytes(out)


def _s24(v: int) -> int:
    v &= 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


class Layout:
    """Where the MD voices live (dnfw.waverider.dsp gives the addresses)."""

    def __init__(self, state: int, scratch: int, tables: int):
        self.state, self.tables = state, tables
        self.T = {name: tables + off for name, (off, _n) in TABLE_LAYOUT.items()}
        self.C = {w: scratch + 4 * k for k, w in enumerate(SC_WORDS)}


SC_WORDS = ("n1", "n2", "n3", "a", "b", "c", "d", "e", "f", "g", "h", "k", "fill", "tmp", "mdb")
# mdb: the slot's words' address (what I3 holds), for code that needs it in an R register


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


# -- the sine, filled by the DSP itself ----------------------------------------------------
SINE_PER_BLOCK = 1024


def sine_value(k: int) -> float:
    """What the table's word k approximates (DSP2's own table, within 6.5 LSB)."""
    x = k + (1.5 if k >= 3 * SINE_N // 4 else 0.0)
    return max(-1.0, min(TOP, math.sin(2.0 * math.pi * x / SINE_N)))


# sin(pi x / 2) on [-1, 1]: odd polynomial (a minimax fit, |error| < 6e-8)
SIN_POLY = (1.5707963185, -0.6459637111, 0.0796915052, -0.0046769631, 0.0001514842)


def sine_fill(p: Prog, L: Layout) -> None:
    """SINE_PER_BLOCK more words of the sine table, from C['fill'] (0 at power-on) until
    the table is whole (C['fill'] = SINE_N). Clobbers R0-R7, R12, R13, I1."""
    C = L.C
    p.ld(0, C["fill"])
    p.iconst(12, SINE_N)
    p.e("COMP(R0, R12);")

    def more():
        p.ld(0, C["fill"])
        p.lsh(1, 0, 2)
        p.iconst(12, L.T["sine"])
        p.iop(1, 12, "+", 1)
        p.seti(1, 1)

        def word():
            p.ld(0, C["fill"])
            # the quarter: k in 0..32767 -> x in quarter turns, folded to [-1, 1]
            p.iconst(12, 0)
            p.float_(2, 0, 12)
            # DSP2 makes its table with a 48-bit recursion whose limiter clamps at the
            # trough (k = 24573..24577): from there on it runs 1.5 indices ahead. Its table
            # is sin(2 pi (k + 1.5 [k >= 24576]) / 32768), clamped at -1 (within 6.5 LSB)
            p.iconst(12, 3 * SINE_N // 4)
            p.if_(0, "GE", 12, lambda: (p.fconst(13, 1.5), p.fop(2, 2, "+", 13)), kind="i")
            p.fconst(12, 4.0 / SINE_N)
            p.fop(2, 2, "*", 12)            # 0..4 quarter turns
            p.fconst(12, 2.0)
            p.if_(2, "GT", 12, lambda: (p.fconst(13, 4.0), p.fop(2, 2, "-", 13)))  # -2..2
            p.fconst(12, 1.0)
            p.if_(2, "GT", 12, lambda: (p.fconst(13, 2.0), p.fop(2, 13, "-", 2)))
            p.fconst(12, -1.0)
            p.if_(2, "LT", 12, lambda: (p.fconst(13, -2.0), p.fop(2, 13, "-", 2)))
            p.fop(3, 2, "*", 2)             # x^2
            p.fconst(4, SIN_POLY[4])
            for c in reversed(SIN_POLY[:4]):
                p.fop(4, 4, "*", 3)
                p.fconst(12, c)
                p.fop(4, 4, "+", 12)
            p.fop(4, 4, "*", 2)
            sat(p, 4)
            p.stpost(1, 4)
            p.ld(0, C["fill"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(C["fill"], 0)
        p.loop(C["tmp"], SINE_PER_BLOCK, word)
    p._branch(lambda: p.r[0] < SINE_N, "LT", more, None)


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

"""COMB- and COMB+, the Digitakt II's comb filters, as filter types 9 and 10 (docs/comb.md),
in PERC's two-backend DSL (dnfw.perc.dsl): the same calls are the SHARC code and its model.

Read from DT2 OS 1.17 (`../dt2s117/research/dt2-comb.md`, outside the repository: it is
derived from Elektron's firmware): per block, its coefficient routine; per sample, its comb

    y = clip(x + A LP(buf[n - D]), +-1),   buf[n] = y

with the delay read linearly interpolated, a TPT one-pole low-pass in the loop, the gain
A ramped across the block to its new target and the read position crossfaded from the
old delay to the new. COMB- and COMB+ differ only in the gain's sign. Their controls are
Multi-Mode's records (as PING's, SHFT's and GRAN's), each a float 0..1 in the track record:

| record | stock | COMB |
|---|---|---|
| `+0x1cc` | FREQ | FREQ: the comb's pitch, x 127 a note number (69 = 220 Hz) |
| `+0x1d0` | RESO | FDBK |
| `+0x1ec` | env delay | DAMP = 1 - the DT2's LPF (0 is its LPF 127, the default) |
| `+0x208` | key tracking | KEY.T: the pitch follows the note from note 48 |

Entered from PING's track loop (`wr_p_track`) for a track on type 9 or 10, with its
`t` in PING's word; filters the track's buffer in place and jumps back to `wr_p_next`.
A note, or a change of type, resets the line as the DT2 does (its fill flag: reads from
the part not yet written this time round give 0; the line itself is not cleared).
"""

from __future__ import annotations

import math
import struct

from ..perc import machines as PM
from ..perc import program as PP
from ..perc.dsl import Mem, Prog, bits

FILTER_TYPES = (9, 10)                    # COMB-, COMB+
NAMES = {9: ("Comb Minus", "COMB-"), 10: ("Comb Plus", "COMB+")}
RATE = 48000.0
BLOCK = 32
BUF_N = 8192                              # the delay line, float32 a track (the DT2's)
MASK = BUF_N - 1
GAIN_N = 128                              # the feedback curve's points
R_FREQ, R_RES, R_DAMP, R_KEYT = 0x1CC, 0x1D0, 0x1EC, 0x208   # DAMP: Env. Delay
PING_T = 0x2E2500                         # PING's track word (ping.asm)
RECORDS = 0x2554B8                        # track t's record: + 0x234 t

# a track's state, words at I2
S = dict(lp=0, c=1, A=2, At=3, pos2=4, w=5, D=6, fill=7, ptype=8, f=9, fb=10, lpf=11)
STATE_WORDS = 16
SC_WORDS = ("cnt", "inv", "dA", "wt", "fr1", "om1", "fr2", "a", "a1", "b", "b1", "buf", "x", "y", "e")


class Layout:
    def __init__(self, state: int, scratch: int, tables: int, buf: int, exp2: int):
        self.state, self.tables, self.buf = state, tables, buf
        self.C = {w: scratch + 4 * k for k, w in enumerate(SC_WORDS)}
        self.T = {"gain": tables, "exp2": exp2}


def tables_bytes() -> bytes:
    """the feedback curve: 128 float32 read from the owner's DT2 image (dnfw.dt2.rom)"""
    from ..dt2 import rom
    return struct.pack(f"<{GAIN_N}f", *rom.comb_gain())


def s(p: Prog, d: int, w: str) -> None:
    p.ldi(d, S[w], 2, w)


def ss(p: Prog, w: str, r: int) -> None:
    p.sti(S[w], 2, r, w)


EXP2_POLY = (2.16470232652681e-05, 0.0001429488257392499, 0.0013431431372917958, 0.009613340619249866, 0.05550540009103531, 0.24022632956314593, 0.6931471907344449, 0.9999999998592122)   # 2^r on [0, 1], highest power first


def exp2(p: Prog, d: int, x: int) -> None:
    """Fd = 2^Fx (|x| < 64): 2^floor(x) (FLOAT 1 BY n) times a degree-7 polynomial in the
    fraction (relative error under 1e-7, the DT2's powf's own accuracy). Clobbers R12-R15."""
    p.trunc(14, x)
    p.iconst(12, 0)
    p.float_(15, 14, 12)
    p.if_(x, "LT", 15, lambda: (p.iconst(12, -1), p.iop(14, 12, "+", 14), p.fconst(12, 1.0),
                                p.fop(15, 15, "-", 12)))
    p.fop(15, x, "-", 15)                               # the fraction, 0..1
    p.fconst(d, EXP2_POLY[0])
    for k in EXP2_POLY[1:]:
        p.fop(d, d, "*", 15)
        p.fconst(12, k)
        p.fop(d, d, "+", 12)
    p.iconst(12, 1)
    p.float_(13, 12, 14)                                # 2^n
    p.fop(d, d, "*", 13)


def sin_cos(p: Prog, x: int, sd: int, cd: int) -> None:
    """Fsd = sin(Fx), Fcd = cos(Fx) for 0 <= x <= pi / 2, by their Taylor series to x^11 /
    x^12 (error under 1e-7 there). Clobbers R12, R13."""
    p.fop(13, x, "*", x)                                # x^2
    p.fconst(sd, -1.0 / math.factorial(11))
    for k in (9, 7, 5, 3, 1):
        p.fop(sd, sd, "*", 13)
        p.fconst(12, (-1) ** ((k - 1) // 2) / math.factorial(k))
        p.fop(sd, sd, "+", 12)
    p.fop(sd, sd, "*", x)
    p.fconst(cd, 1.0 / math.factorial(12))
    for k in (10, 8, 6, 4, 2, 0):
        p.fop(cd, cd, "*", 13)
        p.fconst(12, (-1) ** (k // 2) / math.factorial(k))
        p.fop(cd, cd, "+", 12)


def setup(p: Prog, L: Layout) -> None:
    """The block's coefficients (the DT2's 0x1cbe19) from f, fb, lpf (state words) and the
    type's sign: At, c, D. Clobbers R0-R15, I1, I12."""
    C = L.C
    # the gain: the curve at fb x 127, linearly between its points; COMB- negative
    s(p, 0, "fb")
    p.fconst(12, 127.0)
    p.fop(0, 0, "*", 12)
    p.fconst(12, 0.0)
    p.fop(0, 0, "MAX", 12)
    p.fconst(12, 127.0)
    p.fop(0, 0, "MIN", 12)
    p.trunc(1, 0)                                       # i
    p.iconst(12, 0)
    p.float_(2, 1, 12)
    p.fop(2, 0, "-", 2)                                 # fr
    p.lsh(3, 1, 2)
    p.iconst(12, L.T["gain"])
    p.iop(3, 12, "+", 3)
    p.seti(1, 3)
    p.ldi(4, 0, 1)                                      # T[i]
    p.iconst(12, GAIN_N - 1)
    p.e("COMP(R1, R12);")
    p.ipass(5, 4)
    p._branch(lambda: p.r[1] != p.r[12], "NE", lambda: p.ldi(5, 1, 1), None)   # T[min(i + 1, 127)]
    p.fconst(12, 1.0)
    p.fop(6, 12, "-", 2)
    p.fop(4, 6, "*", 4)
    p.fop(5, 2, "*", 5)
    p.fop(4, 4, "+", 5)                                 # g
    s(p, 0, "ptype")
    p.iconst(12, FILTER_TYPES[0])
    p.if_(0, "EQ", 12, lambda: (p.fconst(12, 0.0), p.fop(4, 12, "-", 4)), kind="i")
    ss(p, "At", 4)
    # the loop's low-pass: fc = 22000 clamp(lpf^2 + 0.2 f^2) + 20; c = tan(w) / (1 + tan(w))
    # = sin(w) / (sin(w) + cos(w)), w = pi fc / fs
    s(p, 0, "lpf")
    p.fop(0, 0, "*", 0)
    s(p, 1, "f")
    p.fop(1, 1, "*", 1)
    p.st(C["e"], 1)                                     # f^2
    p.fconst(12, 0.2)
    p.fop(1, 1, "*", 12)
    p.fop(0, 0, "+", 1)
    p.fconst(12, 0.0)
    p.fop(0, 0, "MAX", 12)
    p.fconst(12, 1.0)
    p.fop(0, 0, "MIN", 12)
    p.fconst(12, 22000.0)
    p.fop(0, 0, "*", 12)
    p.fconst(12, 20.0)
    p.fop(0, 0, "+", 12)
    p.fconst(12, math.pi / RATE)
    p.fop(0, 0, "*", 12)
    sin_cos(p, 0, 1, 2)
    p.fop(3, 1, "+", 2)
    PM._recip_inline(p, 4, 3, 13)
    p.fop(1, 1, "*", 4)
    ss(p, "c", 1)
    # the comb's pitch: 220 x 2^((127 f - 69) / 12) Hz; below FREQ 33 a quadratic from fs/8191
    # to 27.5 Hz; never above 8372.016 Hz
    s(p, 8, "f")
    p.fconst(12, 127.0)
    p.fop(8, 8, "*", 12)
    p.fconst(12, 69.0)
    p.fop(8, 8, "-", 12)
    p.fconst(12, 1.0 / 12.0)
    p.fop(8, 8, "*", 12)
    exp2(p, 9, 8)
    p.fconst(12, 220.0)
    p.fop(9, 9, "*", 12)
    p.fconst(12, RATE / 8191.0)
    p.fop(9, 9, "MAX", 12)                              # hz
    s(p, 0, "f")
    p.fconst(12, 33.0 / 127.0)                          # FREQ 33

    def quad():
        p.fconst(12, 127.0 / 33.0)
        p.fop(0, 0, "*", 12)
        p.fop(0, 0, "*", 0)
        p.fconst(12, 27.5 - RATE / 8191.0)
        p.fop(0, 0, "*", 12)
        p.fconst(12, RATE / 8191.0)
        p.fop(9, 0, "+", 12)
    p.if_(0, "LE", 12, quad, lambda: (p.fconst(12, 8372.016), p.fop(9, 9, "MIN", 12)))
    # D = fs / hz - 6 (1 - lpf)^2 (1 - 0.9 f^2), within 1 .. 8191
    PM._recip_inline(p, 10, 9, 13)
    p.fconst(12, RATE)
    p.fop(10, 10, "*", 12)
    s(p, 0, "lpf")
    p.fconst(12, 1.0)
    p.fop(0, 12, "-", 0)
    p.fop(0, 0, "*", 0)
    p.fconst(12, 6.0)
    p.fop(0, 0, "*", 12)
    p.ld(1, C["e"])
    p.fconst(12, 0.9)
    p.fop(1, 1, "*", 12)
    p.fconst(12, 1.0)
    p.fop(1, 12, "-", 1)
    p.fop(0, 0, "*", 1)
    p.fop(10, 10, "-", 0)
    p.fconst(12, 1.0)
    p.fop(10, 10, "MAX", 12)
    p.fconst(12, float(BUF_N - 1))
    p.fop(10, 10, "MIN", 12)
    ss(p, "D", 10)


def render(p: Prog, L: Layout) -> None:
    """The block, in place at I4 (the DT2's 0x1cbf07). Clobbers R0-R15, I1, I4, I5."""
    C = L.C
    p.fconst(0, 1.0 / BLOCK)
    p.st(C["inv"], 0)
    s(p, 1, "w")
    p.iconst(12, 0)
    p.float_(1, 1, 12)
    s(p, 2, "D")
    p.fop(1, 1, "-", 2)                                 # the new read position
    p.fconst(12, 0.0)
    p.if_(1, "LT", 12, lambda: (p.fconst(12, float(BUF_N)), p.fop(1, 1, "+", 12)))
    s(p, 3, "At")
    s(p, 4, "A")
    p.fop(3, 3, "-", 4)
    p.fop(3, 3, "*", 0)
    p.st(C["dA"], 3)
    p.trunc(5, 1)
    p.st(C["a"], 5)
    p.iconst(12, 0)
    p.float_(6, 5, 12)
    p.fop(6, 1, "-", 6)
    p.st(C["fr1"], 6)
    p.fconst(12, 1.0)
    p.fop(6, 12, "-", 6)
    p.st(C["om1"], 6)
    s(p, 7, "pos2")
    p.trunc(8, 7)
    p.st(C["b"], 8)
    p.iconst(12, 0)
    p.float_(9, 8, 12)
    p.fop(9, 7, "-", 9)
    p.st(C["fr2"], 9)
    s(p, 0, "At")
    ss(p, "A", 0)                                       # the next block starts at the target
    for w, src in (("a1", "a"), ("b1", "b")):
        p.ld(0, C[src])
        p.iconst(12, 1)
        p.iop(0, 12, "+", 0)
        p.iconst(12, MASK)
        p.iop(0, 0, "AND", 12)
        p.st(C[w], 0)
    p.fconst(0, 0.0)
    p.st(C["wt"], 0)
    p.st(C["x"], 4)                                     # A, the ramp
    p.ld(9, PING_T)
    p.lsh(12, 9, 15)                                    # 32 KB a track
    p.iconst(11, L.buf)
    p.iop(12, 11, "+", 12)
    p.st(C["buf"], 12)

    def tap(d: int, word: str) -> None:                 # Fd = buf[C[word]]
        p.ld(0, C[word])
        p.lsh(0, 0, 2)
        p.ld(12, C["buf"])
        p.iop(0, 12, "+", 0)
        p.seti(1, 0)
        p.ldi(d, 0, 1)

    def sample():
        tap(2, "a1")
        p.ld(12, C["fr1"])
        p.fop(2, 2, "*", 12)
        tap(3, "a")
        p.ld(12, C["om1"])
        p.fop(3, 3, "*", 12)
        p.fop(2, 2, "+", 3)                             # t1
        p.ld(10, C["fr2"])
        p.fconst(12, 1.0)
        p.fop(11, 12, "-", 10)                          # om2
        tap(3, "b1")
        p.fop(3, 3, "*", 10)
        tap(4, "b")
        p.fop(4, 4, "*", 11)
        p.fop(3, 3, "+", 4)                             # t2
        p.ld(5, C["wt"])
        p.fop(2, 5, "*", 2)
        p.fconst(12, 1.0)
        p.fop(6, 12, "-", 5)
        p.fop(3, 3, "*", 6)
        p.fop(2, 2, "+", 3)                             # m
        s(p, 0, "fill")

        def fresh():                                    # the line not yet written here: 0
            s(p, 6, "w")
            p.ld(7, C["a"])
            p.ld(8, C["a1"])
            p.iconst(9, 0)
            p.if_(6, "LE", 7, lambda: p.iconst(9, 1), kind="i")
            p.if_(6, "LE", 8, lambda: p.iconst(9, 1), kind="i")
            p.ifz(9, "NE", lambda: p.fconst(2, 0.0))
        p.ifz(0, "NE", fresh)
        s(p, 4, "lp")                                   # the TPT one-pole
        s(p, 5, "c")
        p.fop(6, 2, "-", 4)
        p.fop(6, 5, "*", 6)                             # v
        p.fop(7, 6, "+", 4)                             # y
        p.fop(4, 6, "+", 7)
        ss(p, "lp", 4)
        p.ld(8, C["x"])
        p.fop(7, 8, "*", 7)
        p.ldi(9, 0, 4)                                  # the track's sample
        p.fop(7, 7, "+", 9)
        p.fconst(12, 1.0)
        p.fop(7, 7, "MIN", 12)
        p.fconst(12, -1.0)
        p.fop(7, 7, "MAX", 12)
        p.stpost(4, 7)
        s(p, 0, "w")                                    # buf[w] = y; w on
        p.lsh(1, 0, 2)
        p.ld(12, C["buf"])
        p.iop(1, 12, "+", 1)
        p.seti(1, 1)
        p.sti(0, 1, 7)
        p.iconst(12, MASK)
        p.e("COMP(R0, R12);")
        p._branch(lambda: p.r[0] == p.r[12], "EQ", lambda: (p.iconst(1, 0), ss(p, "fill", 1)), None)
        p.iconst(12, 1)
        p.iop(0, 12, "+", 0)
        p.iconst(12, MASK)
        p.iop(0, 0, "AND", 12)
        ss(p, "w", 0)
        p.ld(8, C["x"])
        p.ld(12, C["dA"])
        p.fop(8, 12, "+", 8)
        p.st(C["x"], 8)
        p.ld(5, C["wt"])
        p.ld(12, C["inv"])
        p.fop(5, 12, "+", 5)
        p.st(C["wt"], 5)
        for w in ("a", "a1", "b", "b1"):
            p.ld(0, C[w])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.iconst(12, MASK)
            p.iop(0, 0, "AND", 12)
            p.st(C[w], 0)
    p.loop(C["cnt"], BLOCK, sample)
    p.ld(0, C["a"])                                     # the old read position, next block
    p.iconst(12, 0)
    p.float_(0, 0, 12)
    p.ld(12, C["fr1"])
    p.fop(0, 0, "+", 12)
    ss(p, "pos2", 0)


def track(p: Prog, L: Layout) -> None:
    """One track on COMB- or COMB+ (its type in R0 at entry). Clobbers everything."""
    C = L.C
    p.ld(9, PING_T)
    p.lsh(12, 9, 6)                                     # STATE_WORDS words a track
    p.iconst(11, L.state)
    p.iop(12, 11, "+", 12)
    p.seti(2, 12)
    # a note, or a new type: the DT2's reset (the line is not cleared; reads of the part
    # not yet written give 0 until it wraps)
    s(p, 1, "ptype")
    p.iconst(2, 0)
    p.e("COMP(R0, R1);")
    p._branch(lambda: p.r[0] != p.r[1], "NE", lambda: p.iconst(2, 1), None)
    ss(p, "ptype", 0)
    p.ld(3, PP.TRIG_WORD)
    p.lsh(3, 3, -16)
    p.iconst(4, 1)
    p.ld(9, PING_T)
    PP._shift_by(p, 4, 9)
    p.iop(3, 3, "AND", 4)
    p.iop(2, 2, "OR", 3)
    # the controls (record 0x2554b8 + 0x234 t), as the DT2's dispatcher makes its arguments
    p.ld(9, PING_T)
    p.lsh(12, 9, 9)
    p.lsh(13, 9, 5)
    p.iop(12, 12, "+", 13)
    p.lsh(13, 9, 4)
    p.iop(12, 12, "+", 13)
    p.lsh(13, 9, 2)
    p.iop(12, 12, "+", 13)
    p.iconst(11, RECORDS)
    p.iop(12, 11, "+", 12)
    p.seti(1, 12)
    p.st(C["y"], 2)                                     # reset?
    # note (as PING reads it: 0 if not a number), keyt (note - 48) / 127 + FREQ
    p.ld(9, PING_T)
    p.lsh(12, 9, 2)
    p.iconst(11, PP.NOTE_CELLS)
    p.iop(12, 11, "+", 12)
    p.seti(5, 12)
    p.ldi(8, 0, 5)
    p.lsh(12, 8, -23)
    p.iconst(13, 0xFF)
    p.iop(12, 12, "AND", 13)
    p.if_(12, "EQ", 13, lambda: p.iconst(8, 0), kind="i")
    p.fconst(12, 48.0)
    p.fop(8, 8, "-", 12)
    p.fconst(12, 1.0 / 127.0)
    p.fop(8, 8, "*", 12)
    p.ldi(9, R_KEYT // 4, 1)
    p.fop(8, 8, "*", 9)
    p.ldi(9, R_FREQ // 4, 1)
    p.fop(8, 8, "+", 9)
    p.fconst(12, 0.0)
    p.fop(8, 8, "MAX", 12)
    p.fconst(12, 1.0)
    p.fop(8, 8, "MIN", 12)
    ss(p, "f", 8)
    p.ldi(9, R_RES // 4, 1)
    p.fconst(12, 0.0)
    p.fop(9, 9, "MAX", 12)
    p.fconst(12, 1.0)
    p.fop(9, 9, "MIN", 12)
    ss(p, "fb", 9)
    p.ldi(9, R_DAMP // 4, 1)
    p.fconst(12, 1.0)
    p.fop(9, 12, "-", 9)                                # LPF = 1 - DAMP
    p.fconst(12, 0.0)
    p.fop(9, 9, "MAX", 12)
    p.fconst(12, 1.0)
    p.fop(9, 9, "MIN", 12)
    ss(p, "lpf", 9)
    setup(p, L)
    p.ld(0, C["y"])

    def reset():
        p.iconst(0, 1)
        ss(p, "fill", 0)
        p.iconst(0, 0)
        ss(p, "w", 0)
        p.fconst(0, 0.0)
        ss(p, "lp", 0)
        s(p, 0, "At")
        ss(p, "A", 0)
    p.ifz(0, "NE", reset)
    # the track's buffer, in place
    p.ld(9, PING_T)
    p.lsh(12, 9, 2)
    p.iconst(11, PP.BUFFERS)
    p.iop(12, 11, "+", 12)
    p.seti(1, 12)
    p.ldi(0, 0, 1)
    p.seti(4, 0)
    render(p, L)


def program(L: Layout, back_sw: int, prefix: str = "cb") -> str:
    """comb.asm: entered from PING's track loop with the frame filter type in R0; back to
    BACK_SW (PING's wr_p_next)."""
    p = Prog("emit", prefix=prefix)
    p.raw("// comb.asm -- COMB- and COMB+, the Digitakt II's comb filters (docs/comb.md).")
    p.raw("// GENERATED by scripts/gen_comb_asm.py from dnfw.comb.program (one program for")
    p.raw("// this text and its model); do not edit by hand.")
    p.raw("")
    p.raw(".SECTION/PM seg_pmco;")
    p.raw("")
    p.raw(".GLOBAL wr_comb.;")
    p.raw("wr_comb.:")
    track(p, L)
    p.e(f"JUMP {back_sw:#x};", "ping.asm's wr_p_next")
    p.emit_subs()
    p.raw(".wr_comb..end:")
    p.raw("      .type wr_comb.,STT_FUNC;")
    return p.text()


def run_track(L: Layout, read, t: int, ftype: int, mem=None):
    """The model: one track's block on MEM (reads fall back to READ)."""
    mem = mem or Mem(read)
    mem.put(PING_T, t)
    p = Prog("run", mem=mem)
    p.r[0] = ftype
    track(p, L)
    return p, mem


def layout() -> Layout:
    """Where the build puts COMB (dnfw.waverider.dsp)."""
    from ..perc import live as PL
    from ..waverider import dsp
    return Layout(dsp.COMB_STATE_DDR, dsp.COMB_SCRATCH_DDR, dsp.COMB_TABLES_DDR, dsp.COMB_BUF_DDR,
                  PL.layout().T["exp2"])

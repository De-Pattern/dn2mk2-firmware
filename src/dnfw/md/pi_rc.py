"""P-IRC, P-ICC, P-IHH: the Machinedrum's physical-model cymbals and hihat (docs/md.md),
from DSP2's P-IRC, P-ICC and P-IHH and their host scale functions. The three are one
program with a few constants and stages changed; the shared code is here, and pi_cc.py,
pi_hh.py take their machine from it.

A block (the firmware's order, each stage over the block's 32 words):
  1. the strike's envelopes: GRAB's decay a block (word 9) and, CC/HH, the strike gain's
     rise (HARD, 1 - HARD); HH closes when GRAB's envelope falls through $54 (a second,
     softer excitation);
  2. 32 words of the additive Fibonacci noise (34, HH);
  3. RC: the stick, a 0.9 sine at word 5's step for the strike's first samples; it only
     ever reaches the one scratch word sample 0's noise comes from (Y:$20, below);
  4. the excitation: an envelope kicked by Y16 whenever the noise is above a threshold
     (RC HARD, CC/HH Y18), decaying 0.95 a sample, times the noise one sample late;
  5. two delta-form biquads (BR's and AU's table coefficients; CC/HH: AU scaled by the
     strike gain at the note), each reading its input two samples late;
  6. CC/HH: the stick (0.2 HARD, HH 0.2) added to the second biquad's output;
  7. the gain: RC a ramp to full scale in a block, then a decay a sample pair by DEC
     (0.8 once GRAB's envelope is under $54; HH 0.9965);
  8. four 256-word delay lines (taps -125 -107 -87 -65 x the period, CC/HH -249 -133
     -117 -73), each through a one-pole low-pass (AG), coupled in pairs by RING's gain
     ($142B49) and fed the excitation x 0.7 (CC/HH 0.8); the output is 0.9 (0.99) of two
     lines plus 0.1 (HH 0.5) of the excitation;
  9. a click (16 words of 0.8, CC 6 of 0.4, HH 8 of 0.8; the note's first block) through a
     third biquad (BR's coefficients, the last two scaled by 1 - HARD; CC HARD - 0.2; HH
     BR 127, 0.8), two samples ahead, added; the sum doubled.

Arithmetic. The firmware's words are integers here where the program's course depends on
them (the noise and its thresholds, the envelopes per block, the stick's counter and
pointer, the table indices), and floats (Q23) in the signal paths, which only add to the
sound. One integer path is exact to the bit for a reason: RC's and CC's sample 0 of each
block takes its noise from internal Y:$20, which no noise word reaches: the third biquad's
long store (l:) of its sample 30 left the low half of its 48-bit accumulator there (and
RC's stick adds to it). That word is full scale, so the third biquad runs on 48-bit
integers (two words, 12-bit partial products a float holds exactly); HH's noise covers
Y:$20, and its third biquad is a float one.

Kept from the firmware: init overwrites word 2 (DEC) with $7FDF3B, so the first note after
the machine is chosen decays as at DEC = 127; HH's close writes $020000 to the flag it
later compares with 2 (a short immediate, put in the word's top byte), so the period is
never halved and the close never clicks; the stick's pointer steps modulo the sine (the
five RC golden cases whose step leaves the table are not reproducible, test_md.py).

The DSP2 ROM words: pi_rc_tables (all three machines). The host's tblB (CC's HARD) is
rom.HOST_TABLES "B" (OS $24BB90, 128 longs).
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .trx2 import idiv, imul_k, wmul
from ..perc.dsl import Prog

Q = K.Q23
TOP = K.TOP

# -- the slot's state words (S) ------------------------------------------------------------
NF1, NF2, CNT, SIDX, F55, G57, G50, R51, G59, G60, G58, YS20, WPOS = range(13)
E16, E17, E18, ENV = 13, 14, 15, 16                    # ints, ENV (Y52) a float
A1, Y130, Y131, U1A, U1B = 17, 18, 19, 20, 21          # biquad 1: B31, y30, y31, u31, u30
A2, Y230, Y231, U2A, U2B = 22, 23, 24, 25, 26          # biquad 2: u29, u28 of biquad 1
BH, BL, Y330, Y331 = 27, 28, 29, 30                    # biquad 3 (RC/CC integers, HH floats)
OP = (31, 32, 33, 34)                                  # the one-poles (lines 0..3)
R56 = 35

# -- the slot's delay area (core.delay_base), in words -------------------------------------
LSTRIDE = 288                    # a line: 256 words and the first 32 again (read past 255)
XB = 4 * LSTRIDE                 # DSP2's internal X:$00..$FF
NZ = XB + 256                    # the noise words (Y:$00..$21), ints << 8
SB = XB + 0x40                   # the mix's 32 outputs


def _xb(p: Prog, L: K.Layout, d: int, k: int = 0) -> None:
    """Rd = the address of XB word k. Clobbers R12."""
    p.ld(d, L.C["k"])
    p.iconst(12, 4 * (XB + k))
    p.iop(d, 12, "+", d)


def _qf(p: Prog, x: int) -> None:
    """Fx floored to the Q23 grid, clamped (the 56300's store). Clobbers R12-R14."""
    p.fconst(12, 2.0 ** 23)
    p.fop(x, x, "*", 12)
    p.trunc(13, x)
    p.iconst(12, 0)
    p.float_(14, 13, 12)
    p.if_(x, "LT", 14, lambda: (p.iconst(12, -1), p.iop(13, 12, "+", 13)))
    p.iconst(12, 0x7FFFFF)
    p.iop(13, 13, "MIN", 12)
    p.iconst(12, -0x800000)
    p.iop(13, 13, "MAX", 12)
    p.iconst(12, -23)
    p.float_(x, 13, 12)


def _fw(p: Prog, d: int, r: int) -> None:
    """Fd = the integer word Rr as a Q23 float. Clobbers R12."""
    p.iconst(12, -23)
    p.float_(d, r, 12)


def _wi(p: Prog, d: int, f: int) -> None:
    """Rd = the Q23 float Ff as its integer word (exact). Clobbers R12."""
    p.fconst(12, 2.0 ** 23)
    p.fop(d, f, "*", 12)
    p.trunc(d, d)


def _sat(p: Prog, r: int) -> None:
    """Rr clamped to a 24-bit word. Clobbers R12."""
    p.iconst(12, 0x7FFFFF)
    p.iop(r, r, "MIN", 12)
    p.iconst(12, -0x800000)
    p.iop(r, r, "MAX", 12)


def _mul(p: Prog, d: int, a: int, b: int) -> None:
    """Rd = floor(Ra Rb / 2^23) for integer words, exactly (trx2.wmul). Clobbers R3-R10,
    R12-R15, I1."""
    p.ipass(14, a)
    p.ipass(15, b)
    p.ipass(5, 14)
    p.ipass(6, 15)
    wmul(p)
    p.ipass(d, 4)


def _mulk(p: Prog, d: int, a: int, k: int) -> None:
    p.ipass(5, a)
    p.iconst(6, k)
    wmul(p)
    p.ipass(d, 4)


def _tword(p: Prog, L: K.Layout, d: int, name: str, idx: int) -> None:
    """Rd = TABLE[name][Ridx] as an integer word. Clobbers R12, R13, I1."""
    K.table_f(p, L, d, name, idx)
    _wi(p, d, d)


# -- host ----------------------------------------------------------------------------------
def _divqr(p: Prog, q: int, r: int, n: int, m: int) -> None:
    """Rq = Rn / Rm, Rr = Rn - Rq Rm (Rn < 2^22, Rm < 2^17). Clobbers R5-R7, R12-R14."""
    idiv(p, q, n, m)
    p.iconst(12, 0)
    p.float_(5, q, 12)
    p.float_(6, m, 12)
    p.fop(5, 5, "*", 6)
    p.trunc(5, 5)
    p.iop(r, n, "-", 5)


def _div2k(p: Prog, d: int, m: int, k: int) -> None:
    """Rd = 2^k / Rm truncated (k 29 or 30, Rm < 2^17): three steps of 2^22, then 4 bits
    and k - 26 bits. Clobbers R1-R2, R5-R11, R12-R14 (d, m not R1, R2, R8-R11)."""
    p.iconst(8, 1 << 22)
    _divqr(p, 9, 10, 8, m)                   # q1, r1
    p.lsh(10, 10, 4)
    _divqr(p, 11, 8, 10, m)                  # q2, r2
    b = k - 26
    p.lsh(8, 8, b)
    _divqr(p, 1, 2, 8, m)                    # q3
    p.lsh(9, 9, 4 + b)
    p.lsh(11, 11, b)
    p.iop(9, 9, "+", 11)
    p.iop(d, 9, "+", 1)


def _dec_word(p: Prog, L: K.Layout, d: int, x: int, table: str, base: int) -> None:
    """Rd = table[((Rx * 18 / 10) >> 7) + base] as an integer word (Rx 0..16383).
    Clobbers R5-R8, R12-R14, I1."""
    imul_k(p, 8, x, 18)
    p.iconst(9, 10)
    idiv(p, 10, 8, 9)
    p.lsh(10, 10, -7)
    p.iconst(12, base)
    p.iop(10, 12, "+", 10)
    _tword(p, L, d, table, 10)


class _Cym:
    """Words (integers): W1 the period ((2^30 / pitch) << 4) - 1, W2 DEC (a decay a pair of
    samples), W3 HARD (RC 1 - HARD; CC tblB[HARD] << 7; HH CLSN), W4 RING, W5 the stick's
    step (2^30 / (87 (W1 >> 13)); CC/HH 2^29 / (73 ...)), W6 AG, W7 AU, W8 BR (0..127),
    W9 GRAB/CLOS (a decay a block)."""
    KIND = "RC"
    PNAMES = ("PTCH", "DEC", "HARD", "RING", "AG", "AU", "BR", "GRAB")

    # -- host --------------------------------------------------------------------------
    @classmethod
    def host(cls, p: Prog, L: K.Layout) -> None:
        k = cls.KIND
        inp(p, 0, 0)
        p.lsh(0, 0, -6)
        p.iconst(12, 127)
        p.iop(3, 0, "AND", 12)
        K.table_f(p, L, 4, "hostP", 3)          # an int
        p.lsh(0, 0, -7)
        p.iconst(12, 1)
        p.iop(0, 0, "AND", 12)
        p.e("R4 = LSHIFT R4 BY R0;")            # tblP << (p >> 7)
        if p.run:
            p.setR(4, p.r[4] << p.r[0])
        _div2k(p, 3, 4, 30)
        p.lsh(3, 3, 4)
        p.iconst(12, -1)
        p.iop(3, 12, "+", 3)
        ws(p, 1, 3)
        # W5: the stick's step
        p.lsh(4, 3, -13)
        imul_k(p, 15, 4, 87 if k == "RC" else 73)
        _div2k(p, 3, 15, 30 if k == "RC" else 29)
        ws(p, 5, 3)
        inp(p, 0, 1)
        _dec_word(p, L, 3, 0, "hostD", 120)
        ws(p, 2, 3)
        inp(p, 0, 2)
        if k == "RC":
            p.lsh(0, 0, 9)
            p.iconst(12, 0x7FFFFF)
            p.iop(3, 12, "-", 0)
        elif k == "CC":
            p.lsh(0, 0, -7)
            if "hostB" not in L.T:
                raise KeyError("P-ICC's HARD reads the host's tblB: rom.HOST_TABLES needs "
                               "'B': (0x24BB90, 128)")
            _tword(p, L, 3, "hostB", 0)
            p.lsh(3, 3, 7)
        else:
            p.lsh(3, 0, 9)
        ws(p, 3, 3)
        inp(p, 0, 3)
        p.lsh(0, 0, 6 if k != "HH" else 4)
        p.iconst(12, 0x40000)
        p.iop(0, 12, "+", 0)
        ws(p, 4, 0)
        inp(p, 0, 4)
        p.lsh(0, 0, 9)
        ws(p, 6, 0)
        inp(p, 0, 5)
        p.lsh(0, 0, -7)
        ws(p, 7, 0)
        inp(p, 0, 6)
        p.lsh(0, 0, -7)
        ws(p, 8, 0)
        inp(p, 0, 7)
        p.iconst(12, 16191)

        def grab():
            inp(p, 0, 7)
            _dec_word(p, L, 3, 0, "hostQ", 180)
            ws(p, 9, 3)

        def full():
            p.iconst(3, 0x7FFFFF)
            ws(p, 9, 3)
        p.if_(0, "LE", 12, grab, full, kind="i")

    # -- init, trig ----------------------------------------------------------------------
    @classmethod
    def init(cls, p: Prog, L: K.Layout) -> None:
        k = cls.KIND
        p.iconst(0, 0)
        for j in range(K.NS):                 # the struct words the firmware leaves are 0
            ss(p, j, 0)                       # in the golden runs (Y20 as the harness had it)
        p.iconst(0, 0x7FDF3B)
        ws(p, 2, 0)
        p.iconst(0, 10)
        ss(p, NF1, 0)
        p.iconst(0, 1)
        ss(p, NF2, 0)
        cls._env_consts(p)
        if k == "RC":
            p.iconst(0, 0x266666)
            ss(p, R56, 0)

    @staticmethod
    def _env_consts(p: Prog) -> None:
        for word, v in ((E16, 0x051EB8), (E17, 0x79999A), (E18, 0xB33333 - (1 << 24))):
            p.iconst(0, v)
            ss(p, word, 0)

    @classmethod
    def trig(cls, p: Prog, L: K.Layout) -> None:
        k = cls.KIND
        p.iconst(0, 0)
        p.iconst(1, 0x7FFFFF)
        ss(p, CNT, 0)
        ss(p, G57, 1)
        ss(p, F55, 1)
        ss(p, R51, 0)
        if k == "RC":
            s(p, 2, R56)
            ss(p, R51, 2)
            ss(p, G50, 0)
            p.fconst(2, TOP)
            ss(p, ENV, 2)
        elif k == "CC":
            w(p, 2, 3)
            ss(p, G59, 2)
            p.iop(2, 1, "-", 2)
            ss(p, G60, 2)
        else:
            cls._env_consts(p)
            p.iconst(0, 0)
            ss(p, G60, 0)
            ss(p, G59, 1)
        p.iconst(0, 0x2000)                   # $14A000: a quarter turn into the sine
        ss(p, SIDX, 0)

    # -- render ----------------------------------------------------------------------------
    @classmethod
    def render(cls, p: Prog, L: K.Layout) -> None:
        C = L.C
        K.delay_base(p, L, 0)
        p.st(C["k"], 0)
        cls._envelopes(p, L)
        cls._noise(p, L)
        if cls.KIND == "RC":
            cls._stick_rc(p, L)
        cls._excite(p, L)
        cls._biquad1(p, L)
        cls._biquad2(p, L)
        if cls.KIND != "RC":
            cls._stick_cc(p, L)
        cls._gain(p, L)
        cls._lines(p, L)
        cls._click(p, L)

    # 1 ---------------------------------------------------------------------------------
    @classmethod
    def _envelopes(cls, p: Prog, L: K.Layout) -> None:
        k = cls.KIND
        if k != "HH":
            s(p, 0, G57)
            w(p, 1, 9)
            _mul(p, 0, 0, 1)
            ss(p, G57, 0)
        else:
            # a = Y57 W9: a > $54 (in the accumulator: the floor, or $54 with bits below)
            s(p, 0, G57)
            w(p, 1, 9)
            p.ipass(5, 0)
            p.ipass(6, 1)
            from .trx2 import wmulr
            wmulr(p)                           # R4 the floor, R3 nonzero if inexact
            p.st(L.C["a"], 4)
            p.iconst(12, 0x54)
            p.iop(0, 4, "-", 12)

            def above():
                w(p, 0, 3)
                p.iconst(12, -0x4CCCCD)
                p.iop(0, 12, "+", 0)
                ss(p, E18, 0)

            def closing():
                s(p, 0, G57)
                p.iconst(12, 0x54)

                def close():
                    for word, v in ((F55, 0x020000), (E16, 0x0CCCCD), (E17, 0x75C28F),
                                    (E18, 0x0CCCCD), (G59, 0x0CCCCD), (G60, 0x733333)):
                        p.iconst(0, v)
                        ss(p, word, 0)
                p.if_(0, "GE", 12, close, kind="i")

            def at54():                         # floor = $54: above iff bits below
                p.ifz(3, "NE", above, closing)
            p.ifz(0, "GT", above, lambda: p.ifz(0, "EQ", at54, closing))
            p.ld(0, L.C["a"])
            ss(p, G57, 0)
        if k != "RC":
            s(p, 0, G59)
            p.st(L.C["b"], 0)
            s(p, 1, G60)
            _mul(p, 0, 0, 1)
            ss(p, G59, 0)
            s(p, 1, G50)
            p.ld(0, L.C["b"])
            p.ipass(13, 1)
            p.iop(1, 13, "+", 0)
            _sat(p, 1)
            ss(p, G50, 1)
            s(p, 0, F55)
            p.ifz(0, "NE", lambda: ss(p, G58, 1))

    # 2 ---------------------------------------------------------------------------------
    @classmethod
    def _noise(cls, p: Prog, L: K.Layout) -> None:
        """NZ[0..] = the additive Fibonacci words (as 24-bit signed << 8): b1 += x1; a1 =
        x1 + b1, twice a step, mod 2^24."""
        p.ld(0, L.C["k"])
        p.iconst(12, 4 * NZ)
        p.iop(0, 12, "+", 0)
        p.seti(5, 0)
        s(p, 1, NF1)                          # b1
        s(p, 2, NF2)                          # x1
        p.iconst(3, 0xFFFFFF)
        p.st(L.C["c"], 3)

        def step():
            p.ld(3, L.C["c"])
            p.lsh(4, 2, 8)
            p.stpost(5, 4)                    # x1
            p.ipass(13, 1)
            p.iop(1, 13, "+", 2)
            p.iop(1, 1, "AND", 3)             # b1 += x1
            p.ipass(4, 2)                     # a1 = x1
            p.ipass(2, 1)                     # x1 = b1
            p.ipass(13, 4)
            p.iop(4, 13, "+", 2)
            p.iop(4, 4, "AND", 3)             # a1 += x1
            p.lsh(6, 2, 8)
            p.stpost(5, 6)                    # x1
            p.ipass(2, 4)                     # x1 = a1
        p.loop(L.C["n1"], 17 if cls.KIND == "HH" else 16, step)
        ss(p, NF1, 2)
        ss(p, NF2, 1)
        if cls.KIND != "HH":
            s(p, 0, YS20)
            p.lsh(0, 0, 8)
            p.ld(1, L.C["k"])
            p.iconst(12, 4 * (NZ + 32))
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.sti(0, 1, 0)

    # 3 ---------------------------------------------------------------------------------
    @classmethod
    def _stick_count(cls, p: Prog, t: int, then) -> None:
        """The stick's counter (CNT) against the threshold Rt: then(R0 = the samples it
        writes, even, > 0) in a block it runs."""
        s(p, 0, CNT)

        def run():
            p.iconst(12, 32)
            p.iop(1, 12, "+", 0)
            ss(p, CNT, 1)
            p.iop(1, t, "-", 1)                # n = T - c - 32
            p.iconst(12, 32)
            p.iop(1, 1, "MIN", 12)
            p.iconst(12, 0)
            p.iop(2, 12, "-", 1)
            p.iop(1, 1, "MAX", 2)              # |n|
            p.lsh(1, 1, -1)
            p.lsh(0, 1, 1)                     # 2 (|n| >> 1)
            p.ifz(0, "NE", then)
        p.if_(0, "LT", t, run, kind="i")

    @classmethod
    def _stick_rc(cls, p: Prog, L: K.Layout) -> None:
        """T = floor(65 W1 / 2^25); its first sine word adds 0.9 x to Y:$20."""
        w(p, 0, 1)
        p.lsh(3, 0, 6)
        p.ipass(13, 3)
        p.iop(3, 13, "+", 0)
        p.lsh(3, 3, -25)

        def run():
            p.st(L.C["a"], 0)                  # the words written
            s(p, 1, SIDX)
            K.table_f(p, L, 2, "sine", 1)
            _wi(p, 2, 2)
            p.iconst(5, 0x733333)
            p.ipass(6, 2)
            wmul(p)
            s(p, 0, YS20)
            p.ipass(13, 0)
            p.iop(0, 13, "+", 4)
            _sat(p, 0)
            ss(p, YS20, 0)
            p.lsh(0, 0, 8)
            p.ld(1, L.C["k"])
            p.iconst(12, 4 * (NZ + 32))
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.sti(0, 1, 0)
            cls._sine_step(p, L)
        cls._stick_count(p, 3, run)

    @staticmethod
    def _sine_step(p: Prog, L: K.Layout) -> None:
        """SIDX += C[a] x W5, modulo the sine. Clobbers R0-R2, R12-R14."""
        p.ld(0, L.C["a"])
        w(p, 1, 5)
        p.iconst(12, 0)
        p.float_(0, 0, 12)
        p.float_(1, 1, 12)
        p.fop(0, 0, "*", 1)                     # < 2^22: exact
        p.trunc(0, 0)
        s(p, 1, SIDX)
        p.ipass(13, 1)
        p.iop(1, 13, "+", 0)
        p.iconst(12, 0x7FFF)
        p.iop(1, 1, "AND", 12)
        ss(p, SIDX, 1)

    # 4 ---------------------------------------------------------------------------------
    @classmethod
    def _excite(cls, p: Prog, L: K.Layout) -> None:
        """X[8 + i] = env_i x noise_(i-1): env kicked by Y16 where the noise is above the
        threshold, then x Y17."""
        k = cls.KIND
        if k == "RC":
            s(p, 0, E16)
            w(p, 1, 3)
            p.iconst(12, 0x7FFFFF)
            p.iop(1, 12, "-", 1)
            _mul(p, 0, 0, 1)
            w(p, 3, 3)                          # the threshold: HARD
        else:
            s(p, 0, E16)
            s(p, 3, E18)
        p.lsh(3, 3, 8)
        p.st(L.C["b"], 3)
        _fw(p, 1, 0)
        p.st(L.C["c"], 1)                       # F: the kick
        s(p, 0, E17)
        _fw(p, 1, 0)
        p.st(L.C["d"], 1)                       # F: the decay
        p.ld(0, L.C["k"])
        p.iconst(12, 4 * (NZ + 32))
        p.iop(1, 12, "+", 0)
        p.seti(2, 1)
        p.ldi(9, 0, 2)                          # noise_(-1) (Y:$20)
        p.iconst(12, 4 * NZ)
        p.iop(1, 12, "+", 0)
        p.seti(1, 1)
        p.iconst(12, 4 * (XB + 8))
        p.iop(1, 12, "+", 0)
        p.seti(2, 1)
        s(p, 10, ENV)

        def one():
            p.ldpost(11, 1)                     # noise_i
            p.ld(3, L.C["b"])
            p.if_(11, "GT", 3, lambda: (p.ld(4, L.C["c"]), p.fop(10, 10, "+", 4)), kind="i")
            p.fconst(12, TOP)
            p.fop(10, 10, "MIN", 12)
            p.iconst(12, -31)
            p.float_(4, 9, 12)
            p.fop(4, 4, "*", 10)
            p.stpost(2, 4)
            p.ld(4, L.C["d"])
            p.fop(10, 10, "*", 4)
            p.ipass(9, 11)
        p.loop(L.C["n1"], 32, one)
        if k == "HH":                           # the last noise word kicks the envelope
            p.iconst(12, 0x79999A << 8)
            p.if_(9, "GE", 12, lambda: (p.fconst(12, 0x333333 * Q), p.fop(10, 10, "+", 12),
                                        p.fconst(12, TOP), p.fop(10, 10, "MIN", 12)), kind="i")
        ss(p, ENV, 10)

    # 5 ---------------------------------------------------------------------------------
    @staticmethod
    def _coefs(p: Prog, L: K.Layout, name: str, idx: int) -> None:
        """F1..F4 = TABLE[name][4 Ridx ..] (C0, C1, C2 = C4, C3). Clobbers R12, R13, I1."""
        p.lsh(0, idx, 2)
        p.iconst(13, L.T[name])
        p.lsh(0, 0, 2)
        p.iop(0, 13, "+", 0)
        p.seti(1, 0)
        for j in range(4):
            p.ldi(1 + j, j, 1)

    @staticmethod
    def _bq(p: Prog, L: K.Layout, base: int, sa: int, s30: int, s31: int) -> None:
        """The delta-form biquad over XB from BASE (DSP2's at 1456e5): seeds X[base],
        X[base + 1] (y30, y31), inputs X[base + 2 + j .. base + 4 + j], output y_j at
        X[base + 2 + j]: B_j = B_(j-1) + C0 y_(j-2) + 2 C1 y_(j-1) + C2 (u_(j-2) + u_j)
        + C3 u_(j-1), y_j = B_j through the store. Coefficients in F1..F4; state words SA
        (B31), S30, S31."""
        _xb(p, L, 0, base)
        p.seti(2, 0)
        p.ldi(6, 0, 2)                          # y_(j-2)
        p.ldi(7, 1, 2)                          # y_(j-1)
        p.iconst(12, 8)
        p.iop(0, 12, "+", 0)
        p.seti(2, 0)
        s(p, 5, sa)

        def one():
            p.fop(8, 1, "*", 6)
            p.fop(5, 5, "+", 8)
            p.fop(8, 2, "*", 7)
            p.fop(5, 5, "+", 8)
            p.fop(5, 5, "+", 8)
            p.ldi(8, 0, 2)
            p.ldi(9, 2, 2)
            p.fop(8, 8, "+", 9)
            p.fop(8, 3, "*", 8)
            p.fop(5, 5, "+", 8)
            p.ldi(8, 1, 2)
            p.fop(8, 4, "*", 8)
            p.fop(5, 5, "+", 8)
            p.fpass(9, 5)
            _qf(p, 9)
            p.stpost(2, 9)
            p.fpass(6, 7)
            p.fpass(7, 9)
        p.loop(L.C["n1"], 32, one)
        ss(p, sa, 5)
        ss(p, s30, 6)
        ss(p, s31, 7)

    @classmethod
    def _biquad1(cls, p: Prog, L: K.Layout) -> None:
        _xb(p, L, 0)
        p.seti(2, 0)
        for x, word in ((4, Y130), (5, Y131), (6, U1B), (7, U1A)):
            s(p, 1, word)
            p.sti(x, 2, 1)
        p.ldi(1, 0x27, 2)
        ss(p, U1A, 1)
        p.ldi(1, 0x26, 2)
        ss(p, U1B, 1)
        w(p, 1, 8)
        cls._coefs(p, L, "PIRC_BR", 1)
        cls._bq(p, L, 4, A1, Y130, Y131)

    @classmethod
    def _biquad2(cls, p: Prog, L: K.Layout) -> None:
        _xb(p, L, 0)
        p.seti(2, 0)
        for x, word in ((0, Y230), (1, Y231), (2, U2B), (3, U2A)):
            s(p, 1, word)
            p.sti(x, 2, 1)
        p.ldi(1, 0x23, 2)
        ss(p, U2A, 1)
        p.ldi(1, 0x22, 2)
        ss(p, U2B, 1)
        if cls.KIND == "RC":
            w(p, 1, 7)
        else:                                   # AU x the strike gain at the note
            s(p, 0, G58)
            w(p, 1, 7)
            _mul(p, 1, 0, 1)
        cls._coefs(p, L, "PIRC_AU", 1)
        cls._bq(p, L, 0, A2, Y230, Y231)

    # 6 ---------------------------------------------------------------------------------
    @classmethod
    def _stick_cc(cls, p: Prog, L: K.Layout) -> None:
        """X[0 ..] += the stick's sine x (CC: 0.2 HARD if HARD >= 0.2, else 0; HH 0.2), at
        T = floor(73 W1 / 2^23) (W1 = $733333 in the note's block)."""
        w(p, 0, 1)
        s(p, 1, F55)
        p.ifz(1, "NE", lambda: p.iconst(0, 0x733333))
        p.lsh(3, 0, 6)
        p.lsh(1, 0, 3)
        p.ipass(13, 3)
        p.iop(3, 13, "+", 1)
        p.ipass(13, 3)
        p.iop(3, 13, "+", 0)
        p.lsh(3, 3, -23)

        def run():
            p.st(L.C["a"], 0)
            if cls.KIND == "CC":
                w(p, 0, 3)
                p.iconst(12, 0x19999A)
                p.iconst(4, 0)

                def amp():
                    _mulk(p, 4, 0, 0x19999A)
                p.if_(0, "GE", 12, amp, kind="i")
            else:
                p.iconst(4, 0x19999A)
            _fw(p, 10, 4)                       # F10: the stick's level
            _xb(p, L, 0)
            p.seti(2, 0)
            s(p, 9, SIDX)
            w(p, 11, 5)
            p.ld(0, L.C["a"])
            p.st(L.C["e"], 0)

            def one():
                p.iconst(12, 0x7FFF)
                p.iop(1, 9, "AND", 12)
                K.table_f(p, L, 3, "sine", 1)
                p.fop(3, 3, "*", 10)
                p.ldi(4, 0, 2)
                p.fop(4, 4, "+", 3)
                p.stpost(2, 4)
                p.ipass(13, 9)
                p.iop(9, 13, "+", 11)
                p.ld(0, L.C["e"])
                p.iconst(12, -1)
                p.iop(0, 12, "+", 0)
                p.st(L.C["e"], 0)
            cls._count_loop(p, L, one)
            cls._sine_step(p, L)
        cls._stick_count(p, 3, run)

    @staticmethod
    def _count_loop(p: Prog, L: K.Layout, body) -> None:
        """body() C[e] times (C[e] > 0)."""
        top = p.label("pic_cnt")
        p.place(top)
        if p.run:
            while True:
                body()
                if p.r[0] == 0:
                    break
            return
        body()
        p.e("R0 = PASS R0;")
        p.jump("NE", top)

    # 7 ---------------------------------------------------------------------------------
    @classmethod
    def _gain(cls, p: Prog, L: K.Layout) -> None:
        """X[k] *= the gain: RC's ramp (R51 != 0), else a decay a sample pair."""
        def ramp():
            # g_0 = Y50, g_k = Y50 + (k - 1) rate (sat); Y50 += 32 rate
            s(p, 0, G50)
            _fw(p, 9, 0)
            s(p, 1, R51)
            _fw(p, 10, 1)
            _xb(p, L, 0)
            p.seti(2, 0)
            p.fpass(11, 9)
            p.fconst(12, TOP)
            p.fop(11, 11, "MIN", 12)

            def one():
                p.ldi(4, 0, 2)
                p.fop(4, 4, "*", 11)
                p.stpost(2, 4)
                p.fop(9, 9, "+", 10)
                p.fpass(11, 9)
                p.fconst(12, TOP)
                p.fop(11, 11, "MIN", 12)
            # sample 0 at g_0, then g_0, g_0 + r, ...
            p.ldi(4, 0, 2)
            p.fop(4, 4, "*", 11)
            p.stpost(2, 4)
            p.loop(L.C["n1"], 31, one)
            s(p, 0, G50)
            p.lsh(1, 1, 5)
            p.ipass(13, 0)
            p.iop(0, 13, "+", 1)
            p.iconst(12, 0x7FFFFF)

            def done():
                p.iconst(1, 0)
                ss(p, R51, 1)
            p.if_(0, "GE", 12, done, kind="i")
            _sat(p, 0)
            ss(p, G50, 0)

        def decay():
            w(p, 0, 2)
            s(p, 1, G57)
            p.iconst(12, 0x54)
            fast = 0x7F8D50 if cls.KIND == "HH" else 0x666666
            p.if_(1, "LT", 12, lambda: p.iconst(0, fast), kind="i")
            p.st(L.C["b"], 0)
            _xb(p, L, 0)
            p.st(L.C["e"], 0)

            def pair():
                s(p, 0, G50)
                _fw(p, 9, 0)
                p.ld(0, L.C["e"])
                p.seti(2, 0)
                p.ldi(4, 0, 2)
                p.fop(4, 4, "*", 9)
                p.stpost(2, 4)
                p.ldi(4, 0, 2)
                p.fop(4, 4, "*", 9)
                p.stpost(2, 4)
                p.iconst(12, 8)
                p.iop(0, 12, "+", 0)
                p.st(L.C["e"], 0)
                s(p, 0, G50)
                p.ld(1, L.C["b"])
                _mul(p, 0, 0, 1)
                ss(p, G50, 0)
            p.loop(L.C["n1"], 16, pair)
        if cls.KIND == "RC":
            s(p, 0, R51)
            p.ifz(0, "NE", ramp, decay)
        else:
            decay()

    # 8 ---------------------------------------------------------------------------------
    @classmethod
    def _lines(cls, p: Prog, L: K.Layout) -> None:
        k = cls.KIND
        C = L.C
        # the coupling: kc = 0.7071 x GAIN[n0]
        if k == "RC":
            w(p, 0, 3)
            _mulk(p, 0, 0, 0x7FDF3B)
            w(p, 1, 4)
            p.ipass(13, 1)
            p.iop(0, 13, "+", 0)
            _sat(p, 0)
        else:
            w(p, 0, 4)
        if k != "HH":
            s(p, 1, G57)
            p.iconst(12, 0x54)
            p.if_(1, "LT", 12, lambda: p.iconst(0, 0x0CCCCD), kind="i")
        _mulk(p, 1, 0, 0x1FF if k == "RC" else 0x1F4)
        K.table_f(p, L, 2, "PI_GAIN_142B49", 1)
        p.fconst(12, 0x5A827A * Q)
        p.fop(2, 2, "*", 12)
        p.st(C["f"], 2)                         # kc
        w(p, 0, 6)                              # g = 0.9 + 0.1 AG
        _fw(p, 1, 0)
        p.fconst(12, 0x0CCCCD * Q)
        p.fop(1, 1, "*", 12)
        p.fconst(12, 0x733333 * Q)
        p.fop(1, 1, "+", 12)
        p.st(C["g"], 1)
        # the read positions: (w + floor(W1 c / 2^23)) & 255, lines 0..3
        cs = (-125, -65, -87, -107) if k == "RC" else (-249, -73, -117, -133)
        for j, c in enumerate(cs):
            w(p, 0, 1)
            _mulk(p, 1, 0, c)
            s(p, 0, WPOS)
            p.ipass(13, 0)
            p.iop(1, 13, "+", 1)
            p.iconst(12, 255)
            p.iop(1, 1, "AND", 12)
            p.iconst(12, j * LSTRIDE)
            p.iop(1, 12, "+", 1)
            p.lsh(1, 1, 2)
            p.ld(0, C["k"])
            p.ipass(13, 0)
            p.iop(1, 13, "+", 1)
            p.st(C[("a", "b", "c", "d")[j]], 1)
        p.ld(0, C["a"])
        p.seti(0, 0)
        p.ld(0, C["b"])
        p.seti(1, 0)
        p.ld(0, C["c"])
        p.seti(2, 0)
        p.ld(8, C["d"])                         # R8: line 3's read pointer
        _xb(p, L, 9)                            # R9: the excitation (and SB at + 0x40)
        s(p, 0, WPOS)                           # R10: the write pointer
        p.lsh(0, 0, 2)
        p.ld(10, C["k"])
        p.iop(10, 10, "+", 0)
        s(p, 0, WPOS)
        p.iconst(1, 0)
        p.iconst(12, 1)
        p.ifz(0, "EQ", lambda: p.ipass(1, 12))
        p.st(C["h"], 1)
        p.iconst(11, 4)
        for j in range(4):
            s(p, 1 + j, OP[j])
        mixc = 0x733333 if k == "RC" else 0x7EB852
        excm = {"RC": 0x0CCCCD, "CC": 0x0CCCCD, "HH": 0x400000}[k]
        h = 0x59999A if k == "RC" else 0x666666

        def sample():
            # F1..F4 the one-poles' states (their outputs this sample: S P Q R)
            p.seti(5, 9)
            p.ldi(0, 0, 5)                      # e
            p.fop(5, 2, "+", 3)                 # P + Q
            p.fconst(12, mixc * Q)
            p.fop(5, 5, "*", 12)
            p.fconst(12, excm * Q)
            p.fop(6, 0, "*", 12)
            p.fop(5, 5, "+", 6)
            _qf(p, 5)
            p.sti(0x40, 5, 5)                   # the mix
            p.iop(9, 11, "+", 9)
            p.fconst(12, h * Q)
            p.fop(0, 0, "*", 12)                # h e
            p.fconst(12, -0.5 * Q)              # the stores' floor, on average
            p.fop(0, 0, "+", 12)
            p.ld(5, C["f"])                     # kc
            p.seti(5, 10)
            p.fop(6, 3, "-", 4)                 # Q - R
            p.fop(6, 6, "*", 5)
            p.fop(6, 0, "+", 6)                 # line 0
            p.fop(13, 3, "+", 4)                # Q + R
            p.fop(13, 13, "*", 5)
            p.fop(13, 0, "-", 13)               # line 1
            p.fop(14, 1, "-", 2)                # S - P
            p.fop(14, 14, "*", 5)
            p.fop(14, 0, "+", 14)               # line 2
            p.fop(15, 1, "+", 2)                # S + P
            p.fop(15, 15, "*", 5)
            p.fop(15, 0, "+", 15)               # line 3
            for j, r in enumerate((6, 13, 14, 15)):
                p.sti(j * LSTRIDE, 5, r)
            p.ld(0, C["h"])                     # w = 0: words 0..31 also past the end

            def mirror():
                for j, r in enumerate((6, 13, 14, 15)):
                    p.sti(j * LSTRIDE + 256, 5, r)
            p.ifz(0, "NE", mirror)
            p.iop(10, 11, "+", 10)
            # the one-poles: st += g (line - st)
            p.ld(5, C["g"])
            p.ldpost(0, 0)
            p.fop(0, 0, "-", 1)
            p.fop(0, 0, "*", 5)
            p.fop(1, 1, "+", 0)
            p.ldpost(0, 1)
            p.fop(0, 0, "-", 2)
            p.fop(0, 0, "*", 5)
            p.fop(2, 2, "+", 0)
            p.ldpost(0, 2)
            p.fop(0, 0, "-", 3)
            p.fop(0, 0, "*", 5)
            p.fop(3, 3, "+", 0)
            p.seti(5, 8)
            p.ldi(0, 0, 5)
            p.iop(8, 11, "+", 8)
            p.fop(0, 0, "-", 4)
            p.fop(0, 0, "*", 5)
            p.fop(4, 4, "+", 0)

        def chunk():
            p.loop(C["n2"], 8, sample, one=12)
            for j in range(4):                  # the states are stored as words
                p.fpass(5, 1 + j)
                _qf(p, 5)
                p.fpass(1 + j, 5)
        p.loop(C["n1"], 4, chunk)
        for j in range(4):
            ss(p, OP[j], 1 + j)
        s(p, 0, WPOS)
        p.iconst(12, 32)
        p.iop(0, 12, "+", 0)
        p.iconst(12, 255)
        p.iop(0, 0, "AND", 12)
        ss(p, WPOS, 0)

    # 9 ---------------------------------------------------------------------------------
    @classmethod
    def _click(cls, p: Prog, L: K.Layout) -> None:
        """The click through the third biquad; out = sat(2 (mix + X[4 + k]))."""
        k = cls.KIND
        C = L.C
        cv, nc = {"RC": (0x666666, 16), "CC": (0x333333, 6), "HH": (0x666666, 8)}[k]
        s(p, 0, F55)
        p.iconst(1, 0)
        p.iconst(12, cv)
        if k == "HH":
            p.iconst(13, 0x7FFFFF)
            p.if_(0, "EQ", 13, lambda: p.ipass(1, 12), kind="i")
        else:
            p.ifz(0, "NE", lambda: p.ipass(1, 12))
        p.st(C["e"], 1)                         # the click's word (0: none)
        p.iconst(0, 0)
        ss(p, F55, 0)
        # its coefficients: C0 C1 from BR's row, C2 C3 = x0 t2, x0 t3 (exact)
        if k == "HH":
            p.iconst(1, 127)
        else:
            w(p, 1, 8)
        cls._coefs(p, L, "PIRC_BR", 1)
        for j in range(4):
            _wi(p, 1 + j, 1 + j)
            p.st(C[("a", "b", "c", "d")[j]], 1 + j)
        if k == "RC":
            w(p, 0, 3)
            p.iconst(12, 0x7FFFFF)
            p.iop(0, 12, "-", 0)
        elif k == "CC":
            w(p, 0, 3)
            p.iconst(12, -0x19999A)
            p.iop(0, 12, "+", 0)
            p.iconst(12, 0)
            p.iop(0, 0, "MAX", 12)
        else:
            p.iconst(0, 0x666666)
        p.st(C["f"], 0)
        p.ld(1, C["c"])
        _mul(p, 1, 0, 1)
        p.st(C["c"], 1)
        p.ld(0, C["f"])
        p.ld(1, C["d"])
        _mul(p, 1, 0, 1)
        p.st(C["d"], 1)
        if k == "HH":
            cls._click_float(p, L, cv, nc)
        else:
            cls._click_exact(p, L, cv, nc)
        # out = sat(2 (mix + X[4 + k])); X[34], X[35] are the click's zeros
        _xb(p, L, 0, 4)
        p.seti(2, 0)
        p.ld(0, C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(0, 12, "+", 0)
        p.seti(5, 0)

        def one():
            p.ldi(1, 0x3C, 2)                   # SB + k = X[4 + k] + 0x3C
            p.ldpost(2, 2)
            p.fop(1, 1, "+", 2)
            p.fop(1, 1, "+", 1)
            p.fconst(12, TOP)
            p.fop(1, 1, "MIN", 12)
            p.fconst(12, -1.0)
            p.fop(1, 1, "MAX", 12)
            p.stpost(5, 1)
        p.loop(C["n1"], 32, one)

    @staticmethod
    def _click_fill(p: Prog, L: K.Layout, nc: int) -> None:
        """X[4 .. 35] = the click (C[e] for nc words, then 0)."""
        _xb(p, L, 0, 4)
        p.seti(2, 0)
        p.ld(1, L.C["e"])
        p.iconst(12, 0)
        p.float_(3, 12, 12)
        p.iconst(12, -23)
        p.float_(1, 1, 12)
        p.loop(L.C["n1"], nc, lambda: p.stpost(2, 1))
        p.loop(L.C["n1"], 32 - nc, lambda: p.stpost(2, 3))

    @classmethod
    def _click_float(cls, p: Prog, L: K.Layout, cv: int, nc: int) -> None:
        cls._click_fill(p, L, nc)
        _xb(p, L, 0)
        p.seti(2, 0)
        p.iconst(1, 0)
        for x, word in ((0, Y330), (1, Y331)):
            s(p, 3, word)
            p.sti(x, 2, 3)
        p.sti(2, 2, 1)
        p.sti(3, 2, 1)
        for j in range(4):
            p.ld(1 + j, L.C[("a", "b", "c", "d")[j]])
            _fw(p, 1 + j, 1 + j)
        cls._bq(p, L, 0, BH, Y330, Y331)

    @staticmethod
    def _split(p: Prog, fh: int, fl: int, r: int) -> None:
        """Ffh, Ffl = the high (signed) and low 12 bits of the integer Rr, as floats.
        Clobbers R12 (r not 12)."""
        p.ash(fh, r, -12)
        p.iconst(12, 4095)
        p.iop(fl, r, "AND", 12)
        p.iconst(12, 0)
        p.float_(fh, fh, 12)
        p.float_(fl, fl, 12)

    @staticmethod
    def _mac(p: Prog, bh: int, bl: int, kh: int, kl: int, yh: int, yl: int) -> None:
        """(Rbh, Rbl) += 2 K y exactly (the 56300's mac in the accumulator's units: Rbh the
        bits from 24 up, Rbl the low 24, left unnormalised: < 2^27). Clobbers R12-R15."""
        p.fop(13, kh, "*", yh)
        p.trunc(13, 13)
        p.lsh(13, 13, 1)
        p.iop(bh, 13, "+", bh)
        p.fop(14, kh, "*", yl)
        p.trunc(14, 14)
        p.fop(15, kl, "*", yh)
        p.trunc(15, 15)
        p.iop(14, 14, "+", 15)                  # m
        p.ash(15, 14, -11)
        p.iop(bh, 15, "+", bh)
        p.iconst(12, 2047)
        p.iop(15, 14, "AND", 12)
        p.lsh(15, 15, 13)
        p.iop(bl, 15, "+", bl)
        p.fop(13, kl, "*", yl)
        p.trunc(13, 13)
        p.lsh(13, 13, 1)
        p.iop(bl, 13, "+", bl)

    @staticmethod
    def _norm(p: Prog, bh: int, bl: int) -> None:
        """Carry Rbl's bits from 24 up into Rbh. Clobbers R12, R13."""
        p.lsh(13, bl, -24)
        p.iop(bh, 13, "+", bh)
        p.iconst(12, 0xFFFFFF)
        p.iop(bl, bl, "AND", 12)

    @classmethod
    def _click_exact(cls, p: Prog, L: K.Layout, cv: int, nc: int) -> None:
        """The third biquad on 48-bit integers: B_j = B_(j-1) + 2 (C0 y_(j-2) + 2 C1
        y_(j-1)) + U_j, U_j = 2 cv (C2 [j-2] + C3 [j-1] + C2 [j]) over the click's words;
        y_j = the high word, into X[2 + j]; the low word of B_30 is Y:$20's next value."""
        C = L.C
        # U: (h, l) pairs at XB + 0x60 + 2 j: V1 = 2 C2 cv, V2 = V1 + 2 C3 cv, V3 = V2 + V1
        _xb(p, L, 0, 0x60)
        p.seti(2, 0)
        p.iconst(1, 0)
        p.loop(C["n1"], 64, lambda: p.stpost(2, 1))
        p.ld(0, C["e"])

        def build():
            p.ld(0, C["e"])
            cls._split(p, 9, 10, 0)             # cv
            for word, hi, lo in (("c", "g", "n2"), ("d", "h", "n3")):
                p.ld(0, C[word])
                cls._split(p, 7, 8, 0)
                p.iconst(1, 0)
                p.iconst(2, 0)
                cls._mac(p, 1, 2, 7, 8, 9, 10)
                cls._norm(p, 1, 2)
                p.st(C[hi], 1)
                p.st(C[lo], 2)
            # V1 = (g, n2); V2 = V1 + (h, n3); V3 = V2 + V1
            p.ld(1, C["g"])
            p.ld(2, C["n2"])
            p.ld(3, C["h"])
            p.ld(4, C["n3"])
            p.ipass(13, 3)
            p.iop(3, 13, "+", 1)
            p.ipass(13, 4)
            p.iop(4, 13, "+", 2)
            cls._norm(p, 3, 4)                  # V2 in R3, R4
            p.ipass(13, 3)
            p.iop(5, 13, "+", 1)
            p.ipass(13, 4)
            p.iop(6, 13, "+", 2)
            cls._norm(p, 5, 6)                  # V3 in R5, R6
            _xb(p, L, 0, 0x60)
            p.seti(2, 0)
            for (h, l) in ((1, 2), (3, 4)) + ((5, 6),) * (nc - 2) + ((3, 4), (1, 2)):
                p.stpost(2, h)
                p.stpost(2, l)
        p.ifz(0, "NE", build)
        # the coefficients' halves: K0 = C0 in F3, F4; K1 = 2 C1 in F5, F6
        p.ld(0, C["a"])
        cls._split(p, 3, 4, 0)
        p.ld(0, C["b"])
        p.lsh(0, 0, 1)
        cls._split(p, 5, 6, 0)
        p.st(C["a"], 3)
        p.st(C["b"], 4)
        p.st(C["c"], 5)
        p.st(C["d"], 6)
        s(p, 1, BH)
        s(p, 2, BL)
        s(p, 0, Y330)
        cls._split(p, 7, 8, 0)                  # y_(j-2)
        p.ipass(0, 1)
        _sat(p, 0)
        cls._split(p, 9, 10, 0)                 # y_(j-1)
        _xb(p, L, 0, 0x60)
        p.seti(2, 0)                            # U
        _xb(p, L, 0, 2)
        p.seti(1, 0)                            # y_j -> X[2 + j]
        _xb(p, L, 0, 0xA0)
        p.seti(5, 0)                            # the low words

        def one():
            p.ld(3, C["a"])
            p.ld(4, C["b"])
            cls._mac(p, 1, 2, 3, 4, 7, 8)
            p.ld(3, C["c"])
            p.ld(4, C["d"])
            cls._mac(p, 1, 2, 3, 4, 9, 10)
            p.ldpost(3, 2)
            p.ipass(13, 3)
            p.iop(1, 13, "+", 1)
            p.ldpost(3, 2)
            p.ipass(13, 3)
            p.iop(2, 13, "+", 2)
            cls._norm(p, 1, 2)
            p.stpost(5, 2)
            p.ipass(0, 1)
            _sat(p, 0)
            p.iconst(12, -23)
            p.float_(3, 0, 12)
            p.stpost(1, 3)
            p.fpass(7, 9)
            p.fpass(8, 10)
            cls._split(p, 9, 10, 0)
        p.loop(C["n1"], 32, one)
        ss(p, BH, 1)
        ss(p, BL, 2)
        _xb(p, L, 0)
        p.seti(2, 0)
        p.ldi(0, 0x20, 2)                       # y_30
        _wi(p, 0, 0)
        ss(p, Y330, 0)
        p.ldi(0, 0xA0 + 30, 2)
        p.lsh(0, 0, 8)
        p.ash(0, 0, -8)
        ss(p, YS20, 0)
        p.iconst(0, 0)
        p.sti(0x22, 2, 0)
        p.sti(0x23, 2, 0)


class PIRC(_Cym):
    NAME, ID, KIND = "PI-RC", 70, "RC"


class PICC(_Cym):
    NAME, ID, KIND = "PI-CC", 71, "CC"


class PIHH(_Cym):
    NAME, ID, KIND = "PI-HH", 72, "HH"
    PNAMES = ("PTCH", "DEC", "CLSN", "RING", "AG", "AU", "BR", "CLOS")


MACHINES = (PIRC,)

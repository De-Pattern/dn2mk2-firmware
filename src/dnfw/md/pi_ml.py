"""P-IML: the Machinedrum's mallet (a physical model; docs/md.md), from DSP2's P-IML and
its host scale function.

A block: the mallet's excitation (a ROM recording, read at a pitch-dependent rate with
linear interpolation) times HARD, through a one-pole lowpass, drives eight two-pole modes
(frequencies from PTCH and the TENS envelope, radii from DEC through the decay curve);
the modes are summed onto the excitation's first sample, under a per-block amplitude
envelope.

Exactness. Everything but the modes is the 56300's arithmetic on integer words, exactly:
`xmul` is a 24 x 24-bit product (or the sum of two) floored at bit s, from 12-bit halves
whose float products are exact; the lowpass (coefficient $7FFFAC, a 48-bit accumulator)
is integer arithmetic on its word and fraction. The coefficients that set each mode's
pole are exact words, so a mode rings at the Machinedrum's frequency. The modes' 48-bit
states are floats (Q23): their rounding is far below the 24-bit output.

Quirks kept: init sets word 3 (HARD) to 0 after the host's words, so the first note after
the machine is chosen is silent on the Machinedrum (on the DN2 the voice runs init before
the host's words, so it is not). The excitation's step 6 pass, as the firmware has it,
leaves only the block's first excited sample in the sum (its state words Y24, Y25 stay 0);
the three per-block decays at Y28..Y30 are never read and are left out.
"""

from __future__ import annotations

from . import core as K
from .core import inp, s, ss, w, ws
from .gnd import pitch_word
from ..perc.dsl import Prog

Q = K.Q23
TBASE = 0x143F38                  # PIML_T's first word: the mode tables, then the excitation
EXC0 = 0x143F50 - TBASE           # where a note starts reading
EXC_END = 0x1449C9 - TBASE        # where the stored pointer stops
Y8_LP = 0x7FFFAC                  # the lowpass coefficient (init): 1 - 84 / 2^23
Y9 = 0x7FDF3B                     # the decay index's scale (init)
MAXW, MINW = 0x7FFFFF, -0x800000


# -- exact integer helpers (shared with pi_ma) ------------------------------------------------
def _xmul_body(p: Prog, sh: int, two: bool, rne: bool) -> None:
    """R2 = floor((R4 R5 [+ R6 R7] + R3) / 2^sh) (signed 24-bit words; |R3| < 2^25), or
    with RNE the 56300's convergent rounding of it (R3 = 2^(sh-1)). Clobbers R0, R1,
    R8-R15."""
    def split(x, lo, hi):
        p.iconst(12, 4095)
        p.iop(lo, x, "AND", 12)
        p.ash(hi, x, -12)

    def floats():
        p.iconst(12, 0)
        for r in (0, 1, 8, 9):
            p.float_(r, r, 12)
    split(4, 0, 1)                            # al, ah
    split(5, 8, 9)                            # bl, bh
    floats()
    p.fop(10, 1, "*", 9)                      # ah bh (|.| <= 2^24: exact)
    p.trunc(10, 10)
    p.fop(11, 1, "*", 8)                      # ah bl
    p.trunc(11, 11)
    p.fop(13, 0, "*", 9)                      # al bh
    p.trunc(13, 13)
    p.iop(11, 11, "+", 13)                    # m
    p.fop(13, 0, "*", 8)                      # al bl
    p.trunc(13, 13)
    p.iop(13, 13, "+", 3)                     # n (+ K)
    if two:
        split(6, 0, 1)
        split(7, 8, 9)
        floats()
        for a, b, acc in ((1, 9, 10), (1, 8, 11), (0, 9, 11), (0, 8, 13)):
            p.fop(14, a, "*", b)
            p.trunc(14, 14)
            p.iop(acc, acc, "+", 14)
    if rne:
        p.iconst(12, 4095)
        p.iop(15, 13, "AND", 12)
    p.ash(14, 13, -12)
    p.iop(14, 11, "+", 14)                    # t = m + (n >> 12)
    p.ash(11, 14, -(sh - 12))
    p.lsh(10, 10, 24 - sh)
    p.iop(2, 10, "+", 11)
    if rne:                                   # a tie (the bits below are exactly a half): even
        p.iconst(12, (1 << (sh - 12)) - 1)
        p.iop(14, 14, "AND", 12)
        p.iop(14, 14, "OR", 15)
        p.ifz(14, "EQ", lambda: (p.iconst(12, -2), p.iop(2, 2, "AND", 12)))


def xmul(p: Prog, sh: int = 23, two: bool = False, rne: bool = False) -> None:
    """R2 = _xmul_body(...) through one shared copy (a leaf subroutine). Clobbers R0, R1,
    R2, R8-R15, I12; keeps R3-R7."""
    name = f"pi_x{sh}{'d' if two else ''}{'r' if rne else ''}"
    p.call(name, lambda: _xmul_body(p, sh, two, rne))


def clamp(p: Prog, r: int, lo: int = MINW, hi: int = MAXW) -> None:
    """Rr = the 56300 limiter on an integer word. Clobbers R12."""
    p.iconst(12, hi)
    p.iop(r, r, "MIN", 12)
    p.iconst(12, lo)
    p.iop(r, r, "MAX", 12)


def to_word(p: Prog, d: int, a: int) -> None:
    """Rd = the Q23 float Fa as its integer word. Clobbers R12."""
    K.mul_k(p, d, a, 2.0 ** 23)
    p.trunc(d, d)


def floor23(p: Prog, d: int, a: int, t: int, u: int) -> None:
    """Fd = Fa floored to the Q23 grid (either sign). Clobbers R12, Rt, Ru (d may be a)."""
    K.mul_k(p, u, a, 2.0 ** 23)
    p.trunc(t, u)
    p.iconst(12, 0)
    p.float_(d, t, 12)
    p.if_(d, "GT", u, lambda: (p.iconst(12, -1), p.iop(t, 12, "+", t)))
    p.iconst(12, -23)
    p.float_(d, t, 12)


# =====================================================================================
class PIML:
    """P-IML (md_models-style integer model in ../md163/research/emu56k: PI_NOTES.md).
    Words (integers, 24-bit): W1 pitch, W2 the amplitude's decay a block, W3 = W7 HARD,
    W4 DEC << 9, W5 TENS depth, W6 TENS decay a block.
    State: the excitation pointer (word, fraction), the TENS envelope, the lowpass's word,
    the amplitude envelope (ints); per-block temps; the modes' (a, x1) and (k2, k1, g);
    the block's lowpassed excitation."""
    NAME, ID = "PI-ML", 67
    PNAMES = ("PTCH", "DEC", "HARD", "TENS", "-", "-", "-", "-")
    PI, PF, TENV, LP, AMP, XI, XF, FE, LPF, H0, CS, E8, CC, AW = range(14)
    RES = 16                       # 8 x (a, x1), floats
    COEF = 32                      # 8 x (k2, k1, g), floats
    LPB = 56                       # 32 floats

    @staticmethod
    def host(p: Prog, L: K.Layout) -> None:
        inp(p, 0, 0)                                    # PTCH
        p.lsh(0, 0, -6)
        pitch_word(p, L, 4, 0, 10)
        p.trunc(4, 4)
        p.iconst(12, -1000)
        p.iop(4, 12, "+", 4)
        ws(p, 1, 4)
        inp(p, 0, 1)                                    # DEC
        p.lsh(1, 0, -7)
        p.iconst(12, 280)
        p.iop(1, 12, "+", 1)
        K.table_f(p, L, 4, "hostQ", 1)
        to_word(p, 4, 4)
        ws(p, 2, 4)
        p.lsh(4, 0, 9)
        ws(p, 4, 4)
        inp(p, 0, 2)                                    # HARD: in 400 + 1000000
        p.iconst(12, 0)
        p.float_(4, 0, 12)
        K.mul_k(p, 4, 4, 400.0)
        K.add_k(p, 4, 4, 1000000.0)
        p.trunc(4, 4)
        ws(p, 3, 4)
        ws(p, 7, 4)
        inp(p, 0, 3)                                    # TENS

        def low():
            p.lsh(4, 0, 9)
            ws(p, 5, 4)
            p.iconst(1, 300)
            K.table_f(p, L, 4, "hostQ", 1)
            to_word(p, 4, 4)
            ws(p, 6, 4)

        def high():
            p.iconst(4, 0x400200)
            ws(p, 5, 4)
            p.iconst(12, -8192)
            p.iop(1, 12, "+", 0)
            p.lsh(1, 1, -7)
            p.iconst(12, 300)
            p.iop(1, 12, "+", 1)
            K.table_f(p, L, 4, "hostQ", 1)
            to_word(p, 4, 4)
            ws(p, 6, 4)
        p.iconst(12, 8191)
        p.if_(0, "LE", 12, low, high, kind="i")

    @staticmethod
    def init(p: Prog, L: K.Layout) -> None:
        M = PIML
        p.iconst(0, 0)
        ws(p, 3, 0)                                     # HARD = 0 (the firmware's quirk)
        ss(p, M.LP, 0)
        for k in range(16):
            ss(p, M.RES + k, 0)

    @staticmethod
    def trig(p: Prog, L: K.Layout) -> None:
        M = PIML
        p.iconst(0, EXC0)
        ss(p, M.PI, 0)
        p.iconst(0, 0)
        ss(p, M.PF, 0)
        p.iconst(0, 0x7FFFAC)
        ss(p, M.TENV, 0)
        ss(p, M.AMP, 0)

    @staticmethod
    def render(p: Prog, L: K.Layout) -> None:
        M, C = PIML, L.C
        T = L.T["PIML_T"]
        # -- the block's increment and frequency scale (TENS's envelope) ------------------
        p.iconst(3, 0)
        s(p, 7, M.TENV)
        w(p, 4, 6)
        p.ipass(5, 7)
        xmul(p)                                         # env *= W6
        ss(p, M.TENV, 2)
        w(p, 4, 5)
        p.ipass(5, 7)
        xmul(p)
        p.iconst(12, 0x400000)
        p.iop(5, 12, "+", 2)
        clamp(p, 5)                                     # y0 = 0.5 + W5 env
        w(p, 4, 1)
        xmul(p, 20)                                     # X = W1 y0 >> 20 (48-bit increment)
        p.lsh(0, 2, -24)
        ss(p, M.XI, 0)
        p.iconst(12, 0xFFFFFF)
        p.iop(0, 2, "AND", 12)
        ss(p, M.XF, 0)
        p.lsh(0, 2, -2)
        clamp(p, 0)
        ss(p, M.FE, 0)                                  # Y:$FE
        # -- the excitation: read, HARD, lowpass ------------------------------------------
        p.iconst(0, 0)
        ss(p, M.LPF, 0)
        p.ld(0, C["mdb"])
        p.iconst(12, 4 * (K.S0 + M.LPB))
        p.iop(0, 12, "+", 0)
        p.seti(5, 0)

        def sample():
            s(p, 9, M.PF)
            s(p, 10, M.XF)
            p.iop(9, 9, "+", 10)
            p.lsh(10, 9, -24)                           # the carry
            p.iconst(12, 0xFFFFFF)
            p.iop(9, 9, "AND", 12)
            ss(p, M.PF, 9)
            s(p, 11, M.PI)
            s(p, 13, M.XI)
            p.iop(11, 11, "+", 13)
            p.iop(11, 11, "+", 10)
            ss(p, M.PI, 11)
            p.lsh(11, 11, 2)
            p.iconst(12, T)
            p.iop(11, 12, "+", 11)
            p.seti(1, 11)
            p.ldi(6, 0, 1)
            p.ldi(7, 1, 1)
            to_word(p, 6, 6)                            # T0
            to_word(p, 7, 7)                            # T1
            p.iop(4, 7, "-", 6)                         # T1 - T0
            p.ipass(5, 9)                               # f
            p.iconst(12, 0)
            p.iop(3, 12, "-", 6)                        # - T0
            xmul(p)
            p.lsh(6, 6, 1)
            p.ipass(8, 2)
            p.iop(4, 8, "+", 6)                         # V = 2 T0 + (D f - T0) >> 23
            clamp(p, 4)
            w(p, 5, 3)
            p.iconst(3, 0)
            xmul(p, 22)                                 # H = sat(2 mpy(V, HARD))
            clamp(p, 2)
            p.ld(0, C["n2"])
            p.iconst(12, 32)
            p.if_(0, "EQ", 12, lambda: ss(p, M.H0, 2), kind="i")
            # the lowpass, exactly: A = S 2^24 + F; A += 2 Y8 (H - S)
            s(p, 13, M.LP)
            p.iconst(12, -23)
            p.float_(4, 13, 12)
            p.stpost(5, 4)                              # the output: S before the sample
            p.iop(8, 2, "-", 13)                        # D
            p.lsh(9, 8, 4)
            p.lsh(10, 8, 2)
            p.iop(9, 9, "+", 10)
            p.iop(9, 9, "+", 8)                         # 21 D
            s(p, 10, M.LPF)
            p.iconst(12, 7)
            p.iop(14, 10, "AND", 12)                    # Fl
            p.lsh(10, 10, -3)                           # Fh
            p.iop(11, 10, "-", 9)                       # t = Fh - 21 D
            p.ash(13, 11, -21)
            p.iop(13, 13, "+", 2)
            ss(p, M.LP, 13)                             # S = H + (t >> 21)
            p.iconst(12, 0x1FFFFF)
            p.iop(11, 11, "AND", 12)
            p.lsh(11, 11, 3)
            p.iop(11, 11, "OR", 14)
            ss(p, M.LPF, 11)
        p.loop(C["n2"], 32, sample)
        s(p, 0, M.PI)                                   # the stored pointer stops at $1449C9
        p.iconst(12, EXC_END)

        def stop():
            p.iconst(0, EXC_END)
            ss(p, M.PI, 0)
            p.iconst(0, 0)
            ss(p, M.PF, 0)
        p.if_(0, "GE", 12, stop, kind="i")

        # -- the modes' coefficients ------------------------------------------------------
        def tword(d, k):
            p.ld(d, T + 4 * k)
            to_word(p, d, d)
        for i in range(8):
            p.iconst(3, 0)
            tword(4, i)
            s(p, 5, M.FE)
            xmul(p)                                     # w = T38 fe
            p.ipass(5, 2)
            p.iconst(12, 0)
            p.iop(4, 12, "-", 2)
            p.ipass(6, 4)                               # -w
            p.ipass(7, 5)                               # w
            xmul(p)                                     # y1 = floor(-w^2)
            p.ipass(4, 2)
            p.iconst(5, 0x155555)
            xmul(p)                                     # y1b = y1 / 6
            p.ipass(5, 4)
            p.ipass(4, 2)
            xmul(p, two=True)                           # y1b y1 - w^2
            p.iconst(12, MAXW)
            p.iop(2, 12, "+", 2)
            clamp(p, 2)
            ss(p, M.CS, 2)                              # cs: 1 - w^2 + w^4 / 6
            tword(4, 16 + i)
            w(p, 5, 7)
            xmul(p)
            ss(p, M.E8, 2)                              # e8 = T48 HARD
            tword(4, 8 + i)
            w(p, 5, 4)
            xmul(p)                                     # e0 = T40 DEC
            p.ipass(4, 2)
            p.iconst(5, Y9)
            xmul(p)                                     # the curve's index
            clamp(p, 2, 0, 511)
            K.table_f(p, L, 4, "PIML_C", 2)
            to_word(p, 4, 4)
            ss(p, M.CC, 4)                              # c
            s(p, 5, M.CS)
            xmul(p, 22)
            p.iconst(12, -0x800000)
            p.iop(2, 12, "+", 2)
            clamp(p, 2)
            p.iconst(12, -23)
            p.float_(0, 2, 12)
            ss(p, M.COEF + 3 * i + 1, 0)                # k1 = 2 c cs - 1
            s(p, 4, M.CC)
            p.iconst(12, 0)
            p.iop(6, 12, "-", 4)
            p.ipass(7, 4)
            p.ipass(5, 4)
            p.ipass(4, 6)
            xmul(p)
            clamp(p, 2)
            p.iconst(12, -23)
            p.float_(0, 2, 12)
            ss(p, M.COEF + 3 * i, 0)                    # k2 = -c^2
            s(p, 4, M.CC)
            s(p, 5, M.CS)
            p.lsh(5, 5, 1)
            xmul(p, two=True)                           # 2 c cs - c^2
            p.iconst(12, -0x800000)
            p.iop(2, 12, "+", 2)
            clamp(p, 2)
            p.ipass(5, 2)
            s(p, 4, M.E8)
            xmul(p, 22)
            clamp(p, 2)
            p.iconst(12, -23)
            p.float_(0, 2, 12)
            ss(p, M.COEF + 3 * i + 2, 0)                # g = 2 e8 (2 c cs - 1 - c^2)

        # -- the sum: the excitation's first sample, then each mode on top ---------------
        p.ld(0, C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(0, 12, "+", 0)
        p.seti(5, 0)
        s(p, 1, M.H0)
        p.iconst(12, -23)
        p.float_(1, 1, 12)
        p.stpost(5, 1)
        p.fconst(1, 0.0)
        p.loop(C["n2"], 31, lambda: p.stpost(5, 1))
        for i in range(8):
            s(p, 5, M.COEF + 3 * i)
            s(p, 6, M.COEF + 3 * i + 1)
            s(p, 7, M.COEF + 3 * i + 2)
            s(p, 8, M.RES + 2 * i)                      # a (48-bit, a float)
            s(p, 9, M.RES + 2 * i + 1)                  # x1: the word before
            floor23(p, 10, 8, 13, 14)                   # xw: a's word (stored limited)
            K.sat(p, 10)
            p.ld(0, C["mdb"])
            p.iconst(12, 4 * (K.S0 + M.LPB))
            p.iop(1, 12, "+", 0)
            p.seti(5, 1)
            p.iconst(12, 4 * K.OUT0)
            p.iop(1, 12, "+", 0)
            p.seti(2, 1)

            def mode():
                p.ldpost(11, 5)
                p.fop(13, 9, "*", 5)
                p.fop(8, 8, "+", 13)
                p.fop(13, 10, "*", 6)
                p.fop(8, 8, "+", 13)
                p.fop(13, 11, "*", 7)
                p.fop(8, 8, "+", 13)
                p.fpass(9, 10)
                floor23(p, 10, 8, 13, 14)                # a's word, before the limiter
                p.ldi(14, 0, 2)
                p.fop(14, 14, "+", 10)
                K.sat(p, 14)
                p.stpost(2, 14)
                K.sat(p, 10)                            # x1 takes it through the limiter
            p.loop(C["n2"], 32, mode)
            # stored as the firmware stores it: A1 through the limiter, A0 as it is
            floor23(p, 11, 8, 13, 14)
            p.fop(13, 8, "-", 11)                       # A0
            K.sat(p, 11)
            p.fop(8, 11, "+", 13)
            ss(p, M.RES + 2 * i, 8)
            ss(p, M.RES + 2 * i + 1, 9)

        # -- the amplitude: floor(env / 2), env *= W2 a block -------------------------------
        s(p, 5, M.AMP)
        w(p, 4, 2)
        p.iconst(3, 0)
        xmul(p)
        ss(p, M.AMP, 2)
        p.lsh(5, 5, -1)
        p.iconst(12, -23)
        p.float_(5, 5, 12)
        p.ld(0, C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(1, 12, "+", 0)
        p.seti(2, 1)

        def out():
            p.ldi(6, 0, 2)
            p.fop(6, 6, "*", 5)
            floor23(p, 6, 6, 13, 14)
            p.stpost(2, 6)
        p.loop(C["n2"], 32, out)


MACHINES = (PIML,)

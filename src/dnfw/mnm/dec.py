"""The Monomachine's polyphase IIR decimator (docs/mnm.md): 64 (DPRO) or 192 (SID) samples
in, 16 out, with five words of state. One copy, a leaf subroutine, for every machine.

The 56300's registers as floats: a F8, b F9, the state x:$f0..$f4 in F7, F0..F3. In: I5 the
input (walked), I4 the output (walked), I2 the state's five words, I1 the ten coefficients, F11
the input's gain (x1, kept at the coefficients' word 10, the output's shift at word 11); the
scratch words `inner` (10 minus the inner rounds: DPRO-WAVE 8, two rounds; SID 0, ten) and `shift` (2^5, 2^6 or 2^7, the output's ASL). The 56300's MACR rounding
and the limiter's E-bit test are a clamp here (sat).

v0.52 (speed): the same float operations on the same operands in the same order for
every value, so every output word and state word is the one v0.42's code gave
(scripts/mnm_identity.py), in under half the instructions:
- the constants held (0.0 F10, -1.0 F11, TOP F15): a negated product -y0 x0 is 0 - y0 x0 as
  before, without loading 0.0 each time, and a clamp is two instructions;
- y1 x1 (the input times its gain) computed once a sample (F14): the 56300 code forms it
  three times from the same y1, the same product each time;
- no register moves: x0 and the state's shifts (x:$f2 <- x:$f3, x:$f0 <- x:$f1) are which
  register holds which word; the rounds run in pairs so that a pair leaves every word where
  it found it;
- each product formed an instruction ahead and summed in a multifunction instruction (the
  multiplier's F0-F3 x F4-F7 beside the ALU's F8-F11 +- F12-F15), the coefficient and input
  loads riding on the computes (I0..I3: the input walked by I0).
"""

from __future__ import annotations

from . import core as C
from ..perc.dsl import Prog

A, B, X1 = 8, 9, 11                            # (X1: the caller's gain register; kept at COEF word 10 here)
XS = (7, 0, 1, 2, 3)
CF, YG, M1, T, T2, ZERO, TOP = 4, 14, 11, 12, 13, 10, 15   # the coefficient, y1 x1, -1.0, products, 0.0, TOP
# (the multifunction forms: products of F0-F3 by F4-F7, sums of F8-F11 and F12-F15: x:$f1..$f4 live in F0-F3
# through the inner rounds, the coefficient in F4, a and b in F8, F9, 0.0 in F10, the products in F12, F13)


def _body(p: Prog, L: C.Layout) -> None:
    W = L.W

    def coef(k):                               # the coefficient k into CF (on the compute before it)
        p.ldi(CF, k, 1)

    def sat(d, s):                             # d = lim(s)
        p.fop(d, s, "MIN", TOP)
        p.fop(d, d, "MAX", M1)

    def sample():                              # y1 x1 for the next input (x1 read from COEF word 10)
        p.ldpost(T2, 0)
        p.ldi(T, 10, 1)
        p.fop(YG, T2, "*", T)

    p.ld(12, W["inner"])                       # the inner rounds in pairs: (10 - inner) / 2 of them
    p.iconst(13, 10)
    p.iop(0, 13, "-", 12)
    p.lsh(0, 0, -1)
    p.st(W["n5"], 0)
    p.geti(12, 5)
    p.seti(0, 12)
    p.sti(10, 1, X1)                           # the gain (its register is -1.0's from here)
    p.ld(12, W["shift"])
    p.sti(11, 1, 12)                           # the output's shift, at COEF word 11
    for k in range(5):
        p.ldi(XS[k], k, 2)
    p.fconst(TOP, C.TOP)
    p.fconst(M1, -1.0)
    p.fconst(ZERO, 0.0)
    coef(0)

    def round_(m):
        """one inner round on (x0, x2, x3, x4), all in F0-F3 -> the same roles' registers after it.
        Coefficient 4 in CF on the way in and out. v0.52 (speed): x:$f1's new word (the next
        x:$f0) where x0 was, once its product is formed; the products formed one instruction ahead
        and summed in the same instruction (multifunction), the loads riding on them"""
        s0, s2, s3, s4 = m
        P = p.par
        P(("*", T, s2, CF), ("ldk", CF, 6, 1))                      # c4 x2
        P(("*", T2, s3, CF), ("-", B, ZERO, T), ("ldk", CF, 8, 1))  # b = -c4 x2; c6 x3
        P(("*", T, s4, CF), ("-", B, B, T2), ("ldk", CF, 0, 1))     # b -= c6 x3; c8 x4
        P(("op", B, B, "+", B))
        P(("*", T2, s0, CF), ("+", B, B, YG), ("ldk", CF, 2, 1))    # b += y1 x1; c0 x0
        P(("op", s0, A, "MIN", TOP))                                # x:$f1 = lim(a), the next x:$f0 too
        P(("op", s0, s0, "MAX", M1))
        P(("op", s2, B, "MIN", TOP))                                # x:$f3 (x:$f2 is the old x:$f3, in s3)
        P(("op", s2, s2, "MAX", M1))
        P(("*", T, s0, CF), ("-", B, ZERO, T), ("ldk", CF, 4, 1))   # b = -c8 x4; c2 x1
        P(("op", B, B, "+", B))
        P(("op", B, B, "+", YG))
        P(("op", A, ZERO, "-", T2), ("ld", T2, 0))                  # a = -c0 x0; y1
        P(("op", A, A, "-", T), ("ldk", T, 10, 1))                  # a -= c2 x1; x1 (the gain)
        P(("op", YG, T2, "*", T))
        P(("op", A, A, "+", A))
        P(("op", s4, B, "MIN", TOP))                                # x:$f4
        P(("op", s4, s4, "MAX", M1))
        P(("op", A, A, "+", YG))
        return (s0, s3, s2, s4)

    def one():
        x0, x1, x2, x3, x4 = XS
        # I1..I5 (coefficient 0 in CF)
        P = p.par
        P(("op", T, CF, "*", x0), ("ldk", CF, 2, 1))                # c0 x0
        P(("*", T2, x1, CF), ("-", A, ZERO, T), ("ldk", CF, 4, 1))  # a = -c0 x0; c2 x1
        P(("op", A, A, "-", T2), ("ld", T2, 0))                     # a -= c2 x1; y1
        P(("op", A, A, "+", A), ("ldk", T, 10, 1))                  # x1 (the gain)
        P(("op", YG, T2, "*", T))
        P(("op", A, A, "+", YG))
        m0 = (x1, x2, x3, x4)                  # x:$f0 <- x:$f1: x1's register; x0's spare (F7)

        def pair():
            assert round_(round_(m0)) == m0

        p.ld(6, W["n5"])
        p.loop_r(6, None, pair, one=6)
        # K1..K29 (v0.52: the products one instruction ahead, multifunction where both are in their
        # banks; x:$f1's new word, the next x:$f0, in x0's register F7)
        P = p.par
        P(("*", T, x2, CF), ("ldk", CF, 6, 1))                      # c4 x2
        P(("*", T2, x3, CF), ("-", B, ZERO, T), ("ldk", CF, 8, 1))  # b = -c4 x2; c6 x3
        P(("*", T, x4, CF), ("-", B, B, T2), ("ldk", CF, 0, 1))     # b -= c6 x3; c8 x4
        P(("op", B, B, "+", B))
        sat(x0, A)                                                  # x:$f1, then x:$f0
        P(("*", T2, x1, CF), ("+", B, B, YG), ("ldk", CF, 1, 1))    # b += y1 x1; c0 x0
        sat(x2, B)                                                  # x:$f3, then x:$f2
        P(("op", B, ZERO, "-", T))                                  # b = -c8 x4
        P(("op", B, B, "+", B))
        P(("op", B, B, "+", YG))
        P(("op", A, ZERO, "-", T2))                                 # a = -c0 x0
        sat(x4, B)                                                  # x:$f4
        P(("*", B, x1, CF), ("ldk", CF, 2, 1))                      # b = c1 x0
        P(("op", T, CF, "*", x0), ("ldk", CF, 3, 1))                # c2 x1
        P(("op", A, A, "-", T), ("ld", T2, 0))                      # a -= c2 x1; y1
        P(("op", A, A, "+", A), ("ldk", T, 10, 1))                  # x1 (the gain)
        P(("op", YG, T2, "*", T))
        P(("op", A, A, "+", YG))
        P(("op", T, CF, "*", x0), ("ldk", CF, 4, 1))                # c3 x1
        P(("*", T2, x3, CF), ("+", B, B, T), ("ldk", CF, 5, 1))     # b += c3 x1; c4 x2
        sat(x1, A)                                                  # x:$f1
        P(("*", T, x3, CF), ("-", A, ZERO, T2), ("ldk", CF, 6, 1))  # a = -c4 x2; c5 x2
        P(("*", T2, x2, CF), ("+", B, B, T), ("ldk", CF, 7, 1))     # b += c5 x2; c6 x3
        P(("*", T, x2, CF), ("-", A, A, T2), ("ldk", CF, 8, 1))     # a -= c6 x3; c7 x3
        P(("op", A, A, "+", A))
        P(("op", A, A, "+", YG))
        P(("*", T2, x4, CF), ("+", B, B, T), ("ldk", CF, 9, 1))     # b += c7 x3; c8 x4
        sat(x3, A)                                                  # x:$f3
        P(("*", T, x4, CF), ("-", A, ZERO, T2), ("ldk", T2, 11, 1)) # a = -c8 x4; c9 x4; the shift
        P(("op", A, A, "+", A))
        P(("op", A, A, "+", YG))
        P(("op", B, B, "+", T))                                     # b += c9 x4
        P(("op", B, B, "*", T2))
        sat(x4, A)                                                  # x:$f4
        sat(B, B)
        coef(0)                                                     # (the next output's first)
        p.stpost(4, B)
    p.loop_r(5, 16, one, one=5)
    p.st(W["n4"], 5)
    p.geti(12, 0)
    p.seti(5, 12)
    p.iconst(12, 0)
    p.st(W["n5"], 12)                          # (v0.41's inner count, 0 at the end)
    for k in range(5):
        p.sti(k, 2, XS[k])


def decimate(p: Prog, L: C.Layout) -> None:
    """Run the decimator (I1, I2, I4, I5, `inner`, `shift`, F11 set). Clobbers R0-R15, I0, I1, I4, I5."""
    p.call("mnm_dec", lambda: _body(p, L))

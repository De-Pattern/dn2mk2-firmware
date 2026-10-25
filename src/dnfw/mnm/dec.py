"""The Monomachine's polyphase IIR decimator (docs/mnm.md): 64 (DPRO) or 192 (SID) samples
in, 16 out, with five words of state. One copy, a leaf subroutine, for every machine.

Registers (the 56300's, as floats): a F1, b F2, x0 F3, y0 F4, y1 F5, x1 F11 (the input's
gain); the state x:$f0..$f4 in F6..F10. In: I5 the input (walked), I4 the output (walked),
I2 the state's five words, I1 the ten coefficients; the scratch words `inner` (10 minus the
inner loop's count: 8 for DPRO, 0 for SID) and `shift` (2^5, 2^6 or 2^7, the output's
ASL). The 56300's MACR rounding and the limiter's E-bit test are a clamp here (sat).
"""

from __future__ import annotations

from . import core as C
from ..perc.dsl import Prog

A, B, X0, Y0, Y1, X1 = 1, 2, 3, 4, 5, 11
XS = (6, 7, 8, 9, 10)


def _body(p: Prog, L: C.Layout) -> None:
    W = L.W

    class St:
        p5 = 0

    def coef(step):
        p.ldi(Y0, St.p5, 1)
        St.p5 = (St.p5 + step) % 10

    def mpy(d, neg=False):                     # d = -/+ y0 x0
        p.fop(d, Y0, "*", X0)
        if neg:
            p.fconst(13, 0.0)
            p.fop(d, 13, "-", d)

    def mac(d, neg=False):
        p.fop(13, Y0, "*", X0)
        p.fop(d, d, "-" if neg else "+", 13)

    def asl(d):
        p.fop(d, d, "+", d)

    def macr_in(d):                            # d += y1 x1
        p.fop(13, Y1, "*", X1)
        p.fop(d, d, "+", 13)

    def lim_to(xk, s):                         # X[k] = lim(s)
        p.fpass(XS[xk], s)
        C.sat(p, XS[xk])

    for k in range(5):
        p.ldi(XS[k], k, 2)

    def one():
        St.p5 = 0
        ptr = {"p1": 0, "p2": 2, "p3": 4}
        # I1..I5
        p.fpass(X0, XS[0]); ptr["p1"] = 1; coef(2)
        mpy(A, True); p.fpass(X0, XS[1]); ptr["p1"] = 0; coef(2)
        mac(A, True); p.fpass(XS[0], X0); ptr["p1"] = 1; p.ldpost(Y1, 5)
        asl(A)
        macr_in(A); p.fpass(X0, XS[2]); ptr["p2"] = 3; coef(2)
        p5_at_inner = St.p5

        def inner():
            St.p5 = p5_at_inner
            # J1..J12 (pointers: p1 = 1, p2 = 3 on entry, as on exit)
            mpy(B, True); p.fpass(X0, XS[3]); coef(2)                # x:(r2)- : X[3], p2 -> 2
            mac(B, True); p.fpass(XS[2], X0)                          # x0 -> X[2], p2 -> 3
            asl(B); lim_to(1, A)                                      # a -> X[1], p1 -> 0
            macr_in(B); p.fpass(X0, XS[4]); coef(2)                   # x:(r3)
            p.fpass(14, B); mpy(B, True); lim_to(3, 14)               # old b -> X[3], p2 -> 2
            asl(B)
            macr_in(B); p.fpass(X0, XS[0]); coef(2)                   # x:(r1)+ : X[0], p1 -> 1
            mpy(A, True); p.fpass(X0, XS[1]); coef(2)                 # x:(r1)- : X[1], p1 -> 0
            mac(A, True); p.fpass(XS[0], X0); p.ldpost(Y1, 5)         # x0 -> X[0], p1 -> 1
            asl(A); lim_to(4, B)                                      # b -> X[4]
            macr_in(A); p.fpass(X0, XS[2]); coef(2)                   # x:(r2)+ : X[2], p2 -> 3
            assert St.p5 == (p5_at_inner + 10) % 10

        def gated():
            p.ld(13, L.W["n5"])
            p.ld(14, L.W["inner"])
            p.if_(13, "GT", 14, inner, kind="i")
        p.loop(W["n5"], 10, gated, one=12)
        St.p5 = p5_at_inner
        # K1..K29 (p1 = 1, p2 = 3)
        mpy(B, True); p.fpass(X0, XS[3]); coef(2)                     # p2 -> 2
        mac(B, True); p.fpass(XS[2], X0)                              # p2 -> 3
        asl(B); lim_to(1, A)                                          # p1 -> 0
        macr_in(B); p.fpass(X0, XS[4]); coef(2)
        p.fpass(14, B); mpy(B, True); lim_to(3, 14)                   # p2 -> 2
        asl(B)
        macr_in(B); p.fpass(X0, XS[0]); coef(1)                       # p1 -> 1
        mpy(A, True); lim_to(4, B); coef(1)
        mpy(B); p.fpass(X0, XS[1]); coef(1)                           # p1 -> 0
        mac(A, True); p.fpass(XS[0], X0); coef(1)                     # p1 -> 1
        asl(A); p.ldpost(Y1, 5)
        macr_in(A)
        mac(B); p.fpass(X0, XS[2]); coef(1)                           # p2 -> 3
        p.fpass(14, A); mpy(A, True); lim_to(1, 14); coef(1)          # p1 -> 0
        mac(B); p.fpass(X0, XS[3]); coef(1)                           # p2 -> 2
        mac(A, True); p.fpass(XS[2], X0); coef(1)                     # p2 -> 3
        asl(A)
        macr_in(A)
        mac(B); p.fpass(X0, XS[4]); coef(1)
        p.fpass(14, A); mpy(A, True); lim_to(3, 14); coef(1)          # p2 -> 2
        asl(A)
        macr_in(A)
        mac(B)
        p.ld(13, L.W["shift"])
        p.fop(B, B, "*", 13)
        lim_to(4, A)
        C.sat(p, B)
        p.stpost(4, B)
        assert St.p5 == 0, St.p5
    p.loop(W["n4"], 16, one, one=12)
    for k in range(5):
        p.sti(k, 2, XS[k])


def decimate(p: Prog, L: C.Layout) -> None:
    """Run the decimator (I1, I2, I4, I5, `inner`, `shift` set). Clobbers R0-R14, I1, I4, I5."""
    p.call("mnm_dec", lambda: _body(p, L))

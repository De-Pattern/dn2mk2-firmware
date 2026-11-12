"""DPRO-DDRW (docs/mnm.md; the Monomachine's P:0x147B38/55/56): two Digibank waves (WAV1,
WAV2: knob >> 1, here n & 31 of the stand-in), each at its own pitch -- WID detunes them apart
(x:0x101BFB / 0x101CFB, up to -/+ 53 cents), scaled by how mixed they are (1 - |2 MIX - 1|) --
each crossfading from the previous wave when it changes (TIME: 0x7FFFFF/(TIME + 1), computed; the
glide word is 1.0 here), bit-reduced (BR1, BR2: x49 down, truncated, x48 up: 15 bits at 0
to 3 at 127), read at 2x at two mip levels (A for b, B for b x 1.12) crossfaded over each
octave's top 1/16, then MIX (ramped over the block) and the 2:1 decimator (`dpro`).

State: per wave (S0..S3, S4..S7): the phase, the wave, the previous wave, the fade (float);
S8 the mix; S9..S26 the decimator. VW i1, i2: the waves' increments b (level A), i3, i4: the
same x 0x1AA17 / 0x17C70 (level B) (`exact.ddrw_incs`).
"""

from __future__ import annotations

from . import core as C
from . import dpro as D
from ..md import core as K
from ..perc.dsl import Prog

NAME, ID = "DPRO-DDRW", 32
PNAMES = ("WAV1", "MIX", "WAV2", "TIME", "BR1", "WID", "BR2", "TUNE")
DEFAULTS = (0, 64, 0, 0, 0, 0, 0, 64)
S_U, S_NEW, S_OLD, S_FD, S_MIX, S_DEC = 0, 1, 2, 3, 8, 9
SUB, SUB_B = 0x17C70, 0x1AA17


def init(p: Prog, L: C.Layout) -> None:
    D.zero(p, L, 0, S_DEC + D.DEC_WORDS)
    for n in range(2):
        C.knob(p, 1, 2 * n)
        p.lsh(1, 1, -1)
        C.sts(p, 4 * n + S_NEW, 1)
        C.sts(p, 4 * n + S_OLD, 1)
        p.fconst(1, C.TOP)
        C.sts(p, 4 * n + S_FD, 1)
    C.par(p, 1, 1)
    p.fconst(12, 2.0 * 0x408102 * C.Q23)
    p.fop(1, 1, "*", 12)
    C.sts(p, S_MIX, 1)


def trig(p: Prog, L: C.Layout) -> None:
    pass


def exact(A: int, F: int, knobs, pre: int = 0) -> dict:
    from . import exact as X
    return X.ddrw_incs(A, knobs)


def pitch(p: Prog, L: C.Layout) -> None:
    """r_n = 0.5 + (WID's t_n - 0.5)(1 - |2 MIX - 1|); VW i1, i2 = A x 2 r_n x 2 x 0x17C70,
    i3, i4 the same x 0x1AA17. Clobbers R0-R9, R12, R13, I1."""
    C.par(p, 1, 1)
    p.fop(1, 1, "+", 1)
    p.fconst(12, -1.0)
    p.fop(1, 1, "+", 12)
    p.fconst(12, 0.0)
    p.fop(2, 12, "-", 1)
    p.fop(1, 1, "MAX", 2)
    p.fconst(2, C.TOP)
    p.fop(1, 2, "-", 1)                         # tri
    C.knob(p, 2, 5)                             # WID
    p.lsh(2, 2, 2)
    p.iconst(12, L.DT["wid"])
    p.iop(2, 12, "+", 2)
    p.seti(1, 2)
    C.vw(p, 3, "A")
    p.iconst(0, 0)
    p.st(L.W["x1"], 0)

    def one():
        p.ldi(4, 0, 1)                          # t - 0.5
        p.fop(4, 4, "*", 1)
        p.fconst(12, 0.5)
        p.fop(4, 4, "+", 12)                    # r
        p.fop(4, 4, "*", 3)
        p.fconst(12, 4.0 * SUB)
        p.fop(5, 4, "*", 12)
        p.fconst(12, 4.0 * SUB_B)
        p.fop(6, 4, "*", 12)
        D.unsigned(p, 7, 5)
        D.unsigned(p, 8, 6)
        p.ld(5, L.md.C["mdb"])
        p.ld(6, L.W["x1"])
        D.addr(p, 5, 5, 6)
        p.iconst(12, 4)
        p.iop(6, 12, "+", 6)
        p.st(L.W["x1"], 6)
        p.iconst(9, 128 * 4)
        p.iop(2, 9, "+", 2)                     # the next WID table
        p.seti(1, 5)
        p.sti(C.VW["i1"], 1, 7)
        p.sti(C.VW["i3"], 1, 8)
        p.seti(1, 2)
    p.loop(L.W["osc"], 2, one)


def _wordaddr(p: Prog, L: C.Layout, d: int, k: int) -> None:
    """Rd = the Digibank address of the stack in state word k (& 31), at the level (W boff).
    Clobbers R12."""
    C.st(p, d, k)
    p.iconst(12, 31)
    p.iop(d, d, "AND", 12)
    p.lsh(d, d, 11)
    p.ld(12, L.W["boff"])
    p.iop(d, 12, "+", d)
    p.lsh(d, d, 2)
    p.iconst(12, L.DIGI)
    p.iop(d, 12, "+", d)


def half(p: Prog, L: C.Layout) -> None:
    D.ready(p, L, lambda: _half(p, L))


def _half(p: Prog, L: C.Layout) -> None:
    from ..perc import machines as PM
    W = L.W
    # the fade's rate a block: 0x21D10 x g x 0x7FFFFF/(TIME + 1) << 11, at most 1
    C.knob(p, 1, 3)
    p.iconst(12, 1)
    p.iop(3, 12, "+", 1)
    p.iconst(12, 0)
    p.float_(3, 3, 12)
    PM.recip(p, 3, 3)                           # 1 / (TIME + 1)
    p.fconst(2, C.TOP)
    C.knob(p, 1, 3)
    p.iconst(12, 0)
    p.if_(1, "EQ", 12, lambda: p.fconst(2, 0x7EB852 * C.Q23), kind="i")
    p.fop(2, 2, "*", 3)
    p.fconst(12, 0x21D10 * C.Q23 * 2048.0)
    p.fop(2, 2, "*", 12)
    C.sat(p, 2)
    p.st(W["rate"], 2)
    p.iconst(0, 0)
    p.st(W["bit"], 0)

    def wave():
        p.ld(1, L.md.C["mdb"])
        p.ld(2, W["bit"])                       # n
        p.lsh(4, 2, 3)
        D.addr(p, 4, 1, 4)
        p.seti(1, 4)                            # the slot + 8 n: WAVn, BRn
        p.ldi(5, C.P0, 1)
        p.ldi(6, C.P0 + 4, 1)
        p.lsh(4, 2, 2)
        D.addr(p, 4, 1, 4)
        p.seti(1, 4)                            # the slot + 4 n: its increments
        p.ldi(7, C.VW["i1"], 1)
        p.st(W["b2"], 7)                        # v0.51: the 2x increment picks the level (dpro.OS)
        D.b_scaled(p, 7)                        # .. this rate's reads it
        p.st(W["b"], 7)
        p.ldi(7, C.VW["i3"], 1)
        p.st(W["y2"], 7)
        D.b_scaled(p, 7)
        p.st(W["y1"], 7)                        # level B's b
        p.fconst(12, 128.0)
        p.fop(6, 6, "*", 12)
        p.trunc(6, 6)
        p.lsh(6, 6, 3)
        p.iconst(12, L.DT["br"])
        p.iop(6, 12, "+", 6)
        p.seti(1, 6)
        p.ldi(7, 0, 1)
        p.st(W["x48"], 7)                       # X48 / 2^23
        p.ldi(7, 1, 1)
        p.fconst(12, 2.0 ** 23)
        p.fop(7, 7, "*", 12)
        p.trunc(7, 7)
        p.st(W["x49"], 7)                       # X49, the integer word (v0.42: for the SSF)
        p.fconst(12, 64.0)
        p.fop(5, 5, "*", 12)
        p.trunc(5, 5)                           # the wave chosen (knob >> 1)
        p.lsh(3, 2, 4)
        D.addr(p, 3, 1, 3)
        p.seti(3, 3)                            # I3: the slot + 4 n words: the wave's S0..S3
        C.st(p, 7, S_NEW)
        C.st(p, 8, S_FD)

        def change():
            p.fconst(12, 0x7FFF00 * C.Q23)

            def go():
                C.sts(p, S_OLD, 7)
                C.sts(p, S_NEW, 5)
                p.fconst(8, 0.0)
                C.sts(p, S_FD, 8)
            p.if_(8, "GE", 12, go)
        p.if_(5, "NE", 7, change, kind="i")
        C.st(p, 1, S_U)
        p.st(W["u"], 1)
        p.iconst(0, 0)
        p.st(W["m"], 0)

        def level():                            # A (m = 0), then B (m = 1)
            p.ld(1, W["b2"])                    # v0.51: the level from the 2x increment
            p.fconst(3, 0.5)
            p.ld(2, W["m"])
            p.ifz(2, "NE", lambda: (p.ld(1, W["y2"]), p.fconst(3, 0.53125)))
            p.st(W["bs"], 1)
            p.st(W["hf"], 3)
            D.start(p, L)
            # v0.37: level B is weighted by its wx, which is exactly 0 over 15/16 of every
            # octave (only the top 1/16 crossfades to it): it then adds exactly 0 to level A's
            # output, so it is not rendered (the same output, bit for bit)

            def body():
                _wordaddr(p, L, 1, S_NEW)
                p.st(W["cb"], 1)
                _wordaddr(p, L, 1, S_OLD)
                p.st(W["fb"], 1)
                # the fade a sample: rate / (32 min(il, 1)), at most 1
                p.ld(1, W["il"])
                p.fconst(12, C.TOP)
                p.fop(1, 1, "MIN", 12)
                p.fconst(12, float(D.N2))
                p.fop(1, 1, "*", 12)
                PM.recip(p, 1, 1)
                p.ld(2, W["rate"])
                p.fop(1, 1, "*", 2)
                C.sat(p, 1)
                p.st(W["x1"], 1)
                C.st(p, 1, S_FD)
                p.st(W["w"], 1)
                p.iconst(12, L.BUF)
                p.seti(5, 12)
                # v0.42: the loop's words held in registers (v0.41 loaded i0, msk, cb, fb, w,
                # x1, X49, X48 and the count from L2 every sample, and stored i0, w and the
                # count): the same operations in the same order, so the same words, bit for bit
                # (scripts/mnm_identity.py). R0 the count, R1 TOP, R5 -31 (q23's shift), R7 w,
                # R8 i0, R9 msk, R10 cb, R11 fb, R13 x1, R14 X49, R15 X48; R12 the scratch.
                p.ld(8, W["i0"])
                p.ld(9, W["msk"])
                p.ld(10, W["cb"])
                p.ld(11, W["fb"])
                p.ld(7, W["w"])
                p.ld(13, W["x1"])
                p.ld(14, W["x49"])
                p.ld(15, W["x48"])
                p.fconst(1, C.TOP)
                p.iconst(5, -31)

                def sat(x):                         # C.sat, TOP held in F1
                    p.fop(x, x, "MIN", 1)
                    p.fconst(12, -1.0)
                    p.fop(x, x, "MAX", 12)

                def one():
                    p.iop(2, 8, "AND", 9)
                    p.iconst(12, 1)
                    p.iop(8, 8, "+", 12)
                    p.lsh(2, 2, 2)
                    p.iop(3, 10, "+", 2)
                    p.seti(1, 3)
                    p.ldi(4, 0, 1)
                    p.lsh(4, 4, 8)
                    p.float_(4, 4, 5)               # the new wave (D.q23)
                    p.iop(3, 11, "+", 2)
                    p.seti(1, 3)
                    p.ldi(6, 0, 1)
                    p.lsh(6, 6, 8)
                    p.float_(6, 6, 5)               # the previous one
                    p.fpass(2, 7)
                    sat(2)
                    p.fop(7, 7, "+", 13)
                    p.fop(4, 4, "-", 6)
                    p.fop(4, 4, "*", 2)
                    p.fop(4, 4, "+", 6)             # old + fade (new - old)
                    sat(4)
                    # v0.42, exact as the DSP (P:0x3FA..0x405): its sample is a 24-bit word (the
                    # crossfade's a1), times X49 in the 48-bit product, of which a1 is kept: the
                    # floor of t24 x X49 / 2^23. As one fixed-point multiply: t24 << 8 (the low
                    # byte cleared, a floor) x X49 (SSF) = floor(t24 x X49 / 2^23). (v0.41 and
                    # older floored a float32 product: a step off at heavy BR, GOLDENS-MNM.md.)
                    p.fconst(12, 2.0 ** 31)
                    p.fop(4, 4, "*", 12)
                    p.trunc(4, 4)                   # t x 2^31 (saturates at the top)
                    p.iconst(12, -256)
                    p.iop(4, 4, "AND", 12)          # t24 << 8
                    p.mul_ssf(4, 4, 14)             # the truncation that reduces the bits
                    p.iconst(12, -1)
                    p.float_(4, 4, 12)              # / 2: X48 x t x 2^-24
                    p.fop(4, 4, "*", 15)
                    sat(4)
                    p.stpost(5, 4)
                p.loop_r(0, D.NBUF, one)
                p.st(W["i0"], 8)
                p.st(W["w"], 7)
                p.st(W["j"], 0)
                p.ld(1, W["bit"])
                p.lsh(1, 1, 7)
                p.iconst(12, L.W1)
                p.iop(1, 12, "+", 1)
                p.st(W["out"], 1)
                p.ld(1, W["wx"])
                p.ld(2, W["m"])

                def ga():
                    p.fconst(2, C.TOP)
                    p.fop(1, 2, "-", 1)
                p.ifz(2, "EQ", ga)
                p.st(W["g"], 1)
                D.interp(p, L)
            p.ld(1, W["wx"])
            p.ld(2, W["m"])
            p.ifz(2, "EQ", lambda: p.fconst(1, C.TOP))
            p.ifz(1, "NE", body, kind="f")
            p.ld(1, W["m"])
            p.iconst(12, 1)
            p.iop(1, 12, "+", 1)
            p.st(W["m"], 1)
        p.loop(W["st"], 2, level)
        # the fade and the phase move on
        C.st(p, 1, S_FD)
        p.ld(2, W["rate"])
        p.fop(1, 1, "+", 2)
        C.sat(p, 1)
        C.sts(p, S_FD, 1)
        p.ld(2, W["b"])
        p.lsh(2, 2, D.PHASE_SH)
        p.ld(3, W["u"])
        D.addr(p, 3, 3, 2)
        C.sts(p, S_U, 3)
        p.ld(1, L.md.C["mdb"])
        p.seti(3, 1)                            # I3: the slot again
        p.ld(2, W["bit"])
        p.iconst(12, 1)
        p.iop(2, 12, "+", 2)
        p.st(W["bit"], 2)
    p.loop(W["osc"], 2, wave)
    # MIX, ramped over the block: 4 (m (W2 - W1) + 0.66 W1)
    C.par(p, 1, 1)
    p.fconst(12, 2.0 * 0x2A9296 * C.Q23)
    p.fop(1, 1, "*", 12)
    C.st(p, 2, S_MIX)
    C.sts(p, S_MIX, 1)
    p.fop(1, 1, "-", 2)
    p.fconst(12, 1.0 / D.N2)
    p.fop(1, 1, "*", 12)
    p.st(W["x1"], 1)
    p.st(W["w"], 2)
    p.iconst(12, L.W1)
    p.seti(1, 12)
    p.iconst(12, L.W2)
    p.seti(2, 12)
    p.iconst(12, L.MIX)
    p.seti(5, 12)

    def mix():
        p.ldpost(1, 1)
        p.ldpost(2, 2)
        p.fop(2, 2, "-", 1)
        p.ld(3, W["w"])
        p.fop(2, 2, "*", 3)
        p.ld(4, W["x1"])
        p.fop(3, 3, "+", 4)
        p.st(W["w"], 3)
        p.fconst(12, 0x547AE1 * C.Q23)
        p.fop(1, 1, "*", 12)
        p.fop(1, 1, "+", 2)
        p.fconst(12, 4.0)
        p.fop(1, 1, "*", 12)
        C.sat(p, 1)
        p.stpost(5, 1)
    p.loop(W["j"], D.N2, mix)
    D.state_ptr(p, L, 2, S_DEC)
    D.dec2(p, L)

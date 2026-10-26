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
        p.st(W["b"], 7)
        p.ldi(7, C.VW["i3"], 1)
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
        p.st(W["x49"], 7)
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
            p.ld(1, W["b"])
            p.fconst(3, 0.5)
            p.ld(2, W["m"])
            p.ifz(2, "NE", lambda: (p.ld(1, W["y1"]), p.fconst(3, 0.53125)))
            p.st(W["bs"], 1)
            p.st(W["hf"], 3)
            D.start(p, L)
            _wordaddr(p, L, 1, S_NEW)
            p.st(W["cb"], 1)
            _wordaddr(p, L, 1, S_OLD)
            p.st(W["fb"], 1)
            # the fade a sample: rate / (32 min(il, 1)), at most 1
            p.ld(1, W["il"])
            p.fconst(12, C.TOP)
            p.fop(1, 1, "MIN", 12)
            p.fconst(12, 32.0)
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

            def one():
                p.ld(1, W["i0"])
                p.ld(2, W["msk"])
                p.iop(2, 1, "AND", 2)
                p.iconst(12, 1)
                p.iop(1, 12, "+", 1)
                p.st(W["i0"], 1)
                p.lsh(2, 2, 2)
                p.ld(3, W["cb"])
                D.addr(p, 3, 3, 2)
                p.seti(1, 3)
                p.ldi(4, 0, 1)
                D.q23(p, 4, 4)                  # the new wave
                p.ld(3, W["fb"])
                D.addr(p, 3, 3, 2)
                p.seti(1, 3)
                p.ldi(6, 0, 1)
                D.q23(p, 6, 6)                  # the previous one
                p.ld(1, W["w"])
                p.fpass(2, 1)
                C.sat(p, 2)
                p.ld(3, W["x1"])
                p.fop(1, 1, "+", 3)
                p.st(W["w"], 1)
                p.fop(4, 4, "-", 6)
                p.fop(4, 4, "*", 2)
                p.fop(4, 4, "+", 6)             # old + fade (new - old)
                C.sat(p, 4)
                p.ld(3, W["x49"])
                p.fop(4, 4, "*", 3)
                p.fconst(12, 2.0 ** 23)
                p.fop(4, 4, "*", 12)
                p.fconst(12, 65536.0)
                p.fop(4, 4, "+", 12)
                p.trunc(4, 4)
                p.iconst(12, -65536)
                p.iop(4, 12, "+", 4)            # floor: the truncation that reduces the bits
                p.iconst(12, -1)
                p.float_(4, 4, 12)              # / 2: X48 x t x 2^-24
                p.ld(3, W["x48"])
                p.fop(4, 4, "*", 3)
                C.sat(p, 4)
                p.stpost(5, 4)
            p.loop(W["j"], D.NBUF, one)
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
        p.lsh(2, 2, 3)
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
    p.fconst(12, 1.0 / 32)
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
    p.loop(W["j"], 32, mix)
    D.state_ptr(p, L, 2, S_DEC)
    D.dec2(p, L)

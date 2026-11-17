"""FM+ STAT, FM+ PAR and FM+ DYN (v0.59, docs/mnm.md): the Monomachine's three FM machines, a
carrier phase-modulated by two or three sine operators, all at twice the output rate (32
samples a block), then a 2:1 decimator of two allpass pairs.

The operators (the Monomachine's P:0x145D12.. / 0x145EC9.. / 0x14619D..):
- a *ramped* operator: an interpolated sine at its listed ratio (the ROM's table, by knob) of
  the carrier's increment, the increment ramped over the block from the last one; then
  differentiated, the one-pole lowpass (TONE's coefficient, DYN 0.5), and an amplitude
  feedback above 64 (out + 16 (x - 0.5) prev, prev the operator's last input);
- a *feedback* operator: the sine without interpolation, its phase offset by its own last
  output x FB (self feedback); differentiated, the lowpass;
- the carrier: the interpolated sine / 4 at the note's increment (ramped), its phase moved on by
  the operators' mix (each at its level), lowpassed, x 2^-12 of a turn.

Numbers. Phases are 32-bit (the sine's 13-bit index << 19, the 56300's 24 fraction bits less
five); signals float32 as Q23 words. The Monomachine's sine is its own (dnfw.mnm.rom.fm_sine,
word for word), and three of its truncations are kept, as they integrate: the lowpasses' state
is floored to a Q23 word at the end of each block (stored as a word: otherwise -0.5 LSB a block
reaches the carrier's phase), and the envelopes decay by floored products. test/test_mnm.py holds
each machine to the Monomachine within 60 dB, but its self feedback at 32 and above (STAT's
1FB, DYN's 2FB), which is chaotic: an LSB anywhere sends it elsewhere (even 37-bit phases with
the increments five bits short do), so those are held by their level and spectrum
(bench.likeness), as the trimmed machines are.

State words (per machine): the operators' (phase, ramp, last input, lowpass, feedback's last),
the carrier's (phase, ramp), the mix's lowpass, the envelopes, the decimator's six.
"""

from __future__ import annotations

from . import core as C
from ..md import core as K
from ..perc.dsl import Prog

SH = 19                                     # a phase's index shift (13-bit index)
FRAC = (1 << SH) - 1
CARRIER_X = 2 * 0xBE37C / 32.0              # the carrier's increment from A (VW A = A / 2^24)
DEC = (0x2BC9CA, 0x0CFCE3, 0x6F0F12, 0x4E63DF)   # the decimator's allpass coefficients (Q23)
TOP = K.TOP


def exact_inc(A: int) -> int:
    """the carrier's increment exactly as the Monomachine's (2 x 0xBE37C x A >> 24), in our
    phase units (>> 5)"""
    a = A & ((1 << 48) - 1)
    if a >> 47:
        a -= 1 << 48
    return (2 * 0xBE37C * a) >> 29


def pitch(p: Prog, L: C.Layout) -> None:
    """VW i1 = the carrier's increment from VW A"""
    C.vw(p, 1, "A")
    p.fconst(12, CARRIER_X)
    p.fop(1, 1, "*", 12)
    p.trunc(1, 1)
    C.vws(p, "i1", 1)


def exact(A: int, F: int, knobs, pre: int = 0) -> dict:
    return {"i1": exact_inc(A)}


def zero(p: Prog, n: int) -> None:
    p.iconst(0, 0)
    for k in range(n):
        C.sts(p, k, 0)


def sine_at(p: Prog, L: C.Layout, d: int, ph: int, interp: bool = True) -> None:
    """Fd = the sine at phase Rph: linear interpolation (the Monomachine's: x0 + (x1 - x0) f) or
    its word. Clobbers R12-R15, I1 (d not among them)."""
    p.lsh(13, ph, -SH)
    p.lsh(13, 13, 2)
    p.iconst(12, L.FM["sine"])
    p.iop(13, 12, "+", 13)
    p.seti(1, 13)
    p.ldi(d, 0, 1)
    if not interp:
        return
    p.ldi(14, 1, 1)
    p.iconst(12, FRAC)
    p.iop(15, ph, "AND", 12)
    p.iconst(12, -SH)
    p.float_(15, 15, 12)
    p.fop(14, 14, "-", d)
    p.fop(14, 14, "*", 15)
    p.fop(d, d, "+", 14)


def floor23(p: Prog, x: int, t: int = 13, u: int = 14) -> None:
    """Fx = floor(Fx 2^23) 2^-23: the 56300's word of an accumulator (|Fx| < 1). Clobbers
    R12, Rt, Ru."""
    p.fconst(12, 2.0 ** 23)
    p.fop(x, x, "*", 12)
    p.trunc(t, x)
    p.iconst(12, 0)
    p.float_(u, t, 12)

    def down():
        p.iconst(12, -1)
        p.iop(t, 12, "+", t)
    p.if_(u, "GT", x, down)
    p.iconst(12, -23)
    p.float_(x, t, 12)


def knobf(p: Prog, d: int, k: int) -> None:
    """Fd = knob k as the Monomachine's Q23 word (k / 128)"""
    C.par(p, d, k)


def ratio(p: Prog, L: C.Layout, d: int, k: int) -> None:
    """Fd = the listed ratio for knob k: the ROM's table at (6 knob + 3) >> 5 (the
    Monomachine's (2 x 24 x (knob << 16 + 0x8000)) >> 24). Clobbers R1-R3, R12, R13, I1."""
    C.knob(p, 1, k)
    p.lsh(2, 1, 1)
    p.lsh(3, 1, 2)
    p.iconst(12, 3)
    p.iop(2, 12, "+", 2)
    p.ipass(12, 2)
    p.iop(2, 12, "+", 3)
    p.lsh(2, 2, -5)
    p.lsh(2, 2, 2)
    p.iconst(12, L.FM["flist"])
    p.iop(2, 12, "+", 2)
    p.seti(1, 2)
    p.ldi(d, 0, 1)


def tone(p: Prog, L: C.Layout, d: int, k: int) -> None:
    """Fd = TONE's lowpass coefficient (the ROM's table, by knob k). Clobbers R1, R2, R12, I1."""
    C.knob(p, 1, k)
    p.lsh(2, 1, 2)
    p.iconst(12, L.FM["tone"])
    p.iop(2, 12, "+", 2)
    p.seti(1, 2)
    p.ldi(d, 0, 1)


def ampfb(p: Prog, L: C.Layout, k: int, word: str) -> None:
    """W[word] = 16 max(0, knob k - 0.5): the amplitude feedback's gain (0 below 64)"""
    knobf(p, 1, k)
    p.fconst(12, 0.5)
    p.fop(1, 1, "-", 12)
    p.fconst(12, 0.0)
    p.fop(1, 1, "MAX", 12)
    p.fconst(12, 16.0)
    p.fop(1, 1, "*", 12)
    p.st(L.W[word], 1)


def level(p: Prog, L: C.Layout, k: int, s_env: int, d: int) -> None:
    """Fd = an operator's level, sat(4 ENV^2) x its envelope (state word s_env), the envelope
    first decayed when ENV (knob k) >= 64: env = floor(env x d), d = 0x7FFFFF - ceil(e^4 / 32),
    e = knob - 64 (the Monomachine's word(1 - (ENV - 0.5)^4), exactly). A leaf subroutine (one
    copy). Clobbers R0-R5, R9-R15, I2, I12."""
    state_ptr(p, L, s_env)
    C.knob(p, 1, k)
    p.call("fm_level", lambda: _level(p, L))
    if d != 4:
        p.fpass(d, 4)


def _level(p: Prog, L: C.Layout) -> None:
    p.ldi(4, 0, 2)
    p.ipass(5, 1)
    p.iconst(12, 64)

    def decay():
        p.iconst(12, -64)
        p.iop(1, 12, "+", 1)
        p.iconst(12, 0)
        p.float_(2, 1, 12)
        p.fop(2, 2, "*", 2)
        p.fop(2, 2, "*", 2)                      # e^4 (< 2^24: exact)
        p.fconst(12, 31.0)
        p.fop(2, 2, "+", 12)
        p.fconst(12, 1.0 / 32)
        p.fop(2, 2, "*", 12)
        p.trunc(2, 2)                            # ceil(e^4 / 32)
        p.iconst(12, 0x7FFFFF)
        p.iop(2, 12, "-", 2)
        p.iconst(12, -23)
        p.float_(11, 2, 12)
        p.fpass(9, 4)
        K.mpyf_any(p, 4, 11, 9)                 # floor(d env) (inline: we are a subroutine)
        p.sti(0, 2, 4)
    p.if_(1, "GE", 12, decay, kind="i")
    p.iconst(12, -7)
    p.float_(1, 5, 12)                          # knob / 128
    p.fop(1, 1, "*", 1)
    p.fconst(12, 4.0)
    p.fop(1, 1, "*", 12)
    K.sat(p, 1)
    p.fop(4, 4, "*", 1)


def state_ptr(p: Prog, L: C.Layout, s: int) -> None:
    """I2 = state word s's address (the slot's words + S0 + s). Clobbers R12, R13."""
    p.ld(12, L.md.C["mdb"])
    p.iconst(13, 4 * (K.S0 + s))
    p.iop(13, 12, "+", 13)
    p.seti(2, 13)


def _ld(p: Prog, d: int, k: int) -> None:
    p.ldi(d, k, 2)


def _st(p: Prog, k: int, r: int) -> None:
    p.sti(k, 2, r)


# The operators, the carrier and the decimator are leaf subroutines, one copy each for the
# three machines (PERC's L2 span): their state at I2 (state_ptr), their output at I5.
def ramped(p: Prog, L: C.Layout, s: int, out: int) -> None:
    """A ramped operator into OUT (32 floats): its increment's target in R1 (int); state
    words s.. (phase, ramp, last input, lowpass, feedback's last); the lowpass's coefficient
    W["c"], the feedback's gain W["fb"]. Clobbers R0-R15, I1, I2, I5, I12."""
    state_ptr(p, L, s)
    p.iconst(12, out)
    p.seti(5, 12)
    p.call("fm_ramped", lambda: _ramped(p, L))


def _ramped(p: Prog, L: C.Layout) -> None:
    PH, RMP, DP, LP, FBP = range(5)
    _ld(p, 11, RMP)                              # a, from the last increment
    _st(p, RMP, 1)
    p.iop(2, 1, "-", 11)
    p.ash(10, 2, -5)                             # its step a sample
    _ld(p, 3, PH)
    _ld(p, 4, DP)
    _ld(p, 5, LP)
    _ld(p, 6, FBP)
    p.ld(7, L.W["c"])
    p.ld(8, L.W["fb"])

    def one():
        p.iop(11, 10, "+", 11)
        sine_at(p, L, 9, 3)
        p.iop(3, 11, "+", 3)
        p.fop(1, 9, "-", 4)                      # differentiated
        p.fpass(4, 9)
        K.sat(p, 1)
        p.fpass(2, 5)                            # the lowpass: its last state out
        p.fop(1, 1, "-", 5)
        p.fop(1, 1, "*", 7)
        p.fop(5, 5, "+", 1)
        p.fop(1, 6, "*", 8)                      # + 16 fb x the last input
        p.fop(1, 1, "+", 2)
        p.fpass(6, 2)
        K.sat(p, 1)
        p.stpost(5, 1)
    p.loop_r(0, 32, one)
    _st(p, PH, 3)
    _st(p, DP, 4)
    floor23(p, 5)
    _st(p, LP, 5)
    _st(p, FBP, 6)


def feedback(p: Prog, L: C.Layout, s: int, out: int, fbk: int) -> None:
    """A feedback operator into OUT (32 floats): its increment in R1 (int), its FB the knob
    FBK; state words s.. (phase, offset, last input, lowpass); the lowpass's coefficient
    W["c"]. The offset is the last output x FB x 2^31 (the Monomachine's 2 x (FB >> 11) x out,
    in our phase units). Clobbers R0-R15, I1, I2, I5, I12."""
    knobf(p, 7, fbk)
    p.fconst(12, 2.0 ** 31)
    p.fop(7, 7, "*", 12)
    state_ptr(p, L, s)
    p.iconst(12, out)
    p.seti(5, 12)
    p.call("fm_feedback", lambda: _feedback(p, L))


def _feedback(p: Prog, L: C.Layout) -> None:
    PH, OFF, DP, LP = range(4)
    p.ipass(10, 1)
    _ld(p, 3, PH)
    _ld(p, 11, OFF)
    _ld(p, 4, DP)
    _ld(p, 5, LP)
    p.ld(6, L.W["c"])

    def one():
        p.iop(3, 10, "+", 3)
        p.iop(13, 11, "+", 3)
        sine_at(p, L, 9, 13, interp=False)
        p.fop(1, 9, "*", 7)
        p.trunc(11, 1)
        p.fop(1, 9, "-", 4)
        p.fpass(4, 9)
        K.sat(p, 1)
        p.fpass(2, 5)
        p.fop(1, 1, "-", 5)
        p.fop(1, 1, "*", 6)
        p.fop(5, 5, "+", 1)
        p.stpost(5, 2)
    p.loop_r(0, 32, one)
    _st(p, PH, 3)
    _st(p, OFF, 11)
    _st(p, DP, 4)
    floor23(p, 5)
    _st(p, LP, 5)


def carrier(p: Prog, L: C.Layout, s: int, n_ops: int) -> None:
    """The mix and the carrier into IN + 96 (32 floats): the operators' outputs at IN, IN + 32
    (and IN + 64), their levels in F5, F6 (and F8): sat(F5 a + F6 b) (+ F8 c, saturated
    again), lowpassed (W["c"]), moving the carrier's phase on by 2^30 of it; state words s..
    (the carrier's phase, ramp, the mix's lowpass). Clobbers R0-R4, R7, R9-R15, I0-I2, I5, I12."""
    state_ptr(p, L, s)
    p.call(f"fm_carrier{n_ops}", lambda: _carrier(p, L, n_ops))


def _carrier(p: Prog, L: C.Layout, n_ops: int) -> None:
    PH, RMP, LP = range(3)
    C.vw(p, 1, "i1")
    _ld(p, 11, RMP)
    _st(p, RMP, 1)
    p.iop(2, 1, "-", 11)
    p.ash(10, 2, -5)
    _ld(p, 3, PH)
    _ld(p, 4, LP)
    p.ld(7, L.W["c"])
    p.iconst(12, L.IN)
    p.seti(0, 12)
    p.iconst(12, L.IN + 4 * 96)
    p.seti(5, 12)

    def one():
        p.ldpost(1, 0)
        p.ldi(2, 31, 0)
        p.fop(1, 1, "*", 5)
        p.fop(2, 2, "*", 6)
        p.fop(1, 1, "+", 2)
        K.sat(p, 1)
        if n_ops == 3:
            p.ldi(2, 63, 0)
            p.fop(2, 2, "*", 8)
            p.fop(1, 1, "+", 2)
            K.sat(p, 1)
        p.fpass(2, 4)                            # the mix's lowpass: its last state out
        p.fop(1, 1, "-", 4)
        p.fop(1, 1, "*", 7)
        p.fop(4, 4, "+", 1)
        p.iop(11, 10, "+", 11)
        sine_at(p, L, 9, 3)
        p.fconst(12, 0.25)
        p.fop(9, 9, "*", 12)
        p.stpost(5, 9)
        p.fconst(12, 2.0 ** 30)
        p.fop(2, 2, "*", 12)
        p.trunc(13, 2)
        p.iop(3, 11, "+", 3)
        p.iop(3, 13, "+", 3)
    p.loop_r(0, 32, one)
    _st(p, PH, 3)
    floor23(p, 4)
    _st(p, LP, 4)


def decimate(p: Prog, L: C.Layout, s: int) -> None:
    """IN + 96's 32 samples -> 16 at I4: the even and the odd samples each through two
    first-order allpasses (y = x[-1] + c (x - y[-1]), saturated), the output (C + D) / 4; state
    words s.. (the last even and odd inputs, A, B, C, D). Clobbers R0-R15, I2, I5, I12."""
    state_ptr(p, L, s)
    p.call("fm_decimate", lambda: _decimate(p, L))


def _decimate(p: Prog, L: C.Layout) -> None:
    for k in range(6):
        _ld(p, 1 + k, k)                         # F1 e, F2 o, F3 A, F4 B, F5 C, F6 D
    for k, cc in enumerate(DEC):
        p.fconst(7 + k, cc * C.Q23)              # F7..F10
    p.iconst(12, L.IN + 4 * 96)
    p.seti(5, 12)

    def one():
        p.ldpost(11, 5)
        p.fop(13, 11, "-", 3)
        p.fop(13, 13, "*", 7)
        p.fop(13, 13, "+", 1)
        K.sat(p, 13)
        p.fpass(1, 11)
        p.ldpost(11, 5)
        p.fop(14, 11, "-", 4)
        p.fop(14, 14, "*", 8)
        p.fop(14, 14, "+", 2)
        K.sat(p, 14)
        p.fpass(2, 11)
        p.fop(15, 13, "-", 5)
        p.fop(15, 15, "*", 9)
        p.fop(5, 15, "+", 3)
        K.sat(p, 5)
        p.fpass(3, 13)
        p.fop(15, 14, "-", 6)
        p.fop(15, 15, "*", 10)
        p.fop(6, 15, "+", 4)
        K.sat(p, 6)
        p.fpass(4, 14)
        p.fop(11, 5, "+", 6)
        p.fconst(12, 0.25)
        p.fop(11, 11, "*", 12)
        p.stpost(4, 11)
    p.loop_r(0, 16, one)
    for k in range(6):
        _st(p, k, 1 + k)


# -- the three machines --------------------------------------------------------------------
class _Machine:
    pitch = staticmethod(pitch)
    exact = staticmethod(exact)


class Stat(_Machine):
    """FM+ STAT: operator 2 (ramped, 2FRQ's ratio, its 2VOL feedback, level sat(4 2VOL^2)) and
    operator 1 (feedback, 2FRQ's ... 1FRQ's ratio x the fine tune 1FIN, its 1FB, level
    sat(4 1ENV^2) x its envelope), TONE's lowpass on each and on the mix."""
    NAME, ID = "FM+STAT", 8
    PNAMES = ("1FRQ", "1FIN", "1ENV", "1FB", "2FRQ", "2VOL", "TONE", "TUNE")
    DEFAULTS = (60, 64, 80, 30, 80, 64, 98, 64)
    FB_KNOB = 3
    N = 19
    S_OP2, S_OP1, S_CAR, S_LPM, S_ENV, S_DEC = 0, 5, 9, 11, 12, 13

    @staticmethod
    def init(p: Prog, L: C.Layout) -> None:
        zero(p, Stat.N)

    @staticmethod
    def trig(p: Prog, L: C.Layout) -> None:
        p.fconst(0, TOP)
        C.sts(p, Stat.S_ENV, 0)

    @staticmethod
    def half(p: Prog, L: C.Layout) -> None:
        W = L.W
        tone(p, L, 1, 6)
        p.st(W["c"], 1)
        ampfb(p, L, 5, "fb")
        # operator 2: 2FRQ's ratio x the increment x 8
        ratio(p, L, 1, 4)
        C.vw(p, 2, "i1")
        p.iconst(12, 0)
        p.float_(2, 2, 12)
        p.fop(1, 1, "*", 2)
        p.fconst(12, 8.0)
        p.fop(1, 1, "*", 12)
        p.trunc(1, 1)
        ramped(p, L, Stat.S_OP2, L.IN)
        # operator 1: sat(2 fine ratio) x the increment x 8, fine = (1FIN - 0.5) / 4 + 0.5
        ratio(p, L, 4, 0)
        knobf(p, 1, 1)
        p.fconst(12, 0.5)
        p.fop(1, 1, "-", 12)
        p.fconst(12, 0.25)
        p.fop(1, 1, "*", 12)
        p.fconst(12, 0.5)
        p.fop(1, 1, "+", 12)
        p.fop(1, 1, "*", 4)
        p.fop(1, 1, "+", 1)
        K.sat(p, 1)
        C.vw(p, 2, "i1")
        p.iconst(12, 0)
        p.float_(2, 2, 12)
        p.fop(1, 1, "*", 2)
        p.fconst(12, 8.0)
        p.fop(1, 1, "*", 12)
        p.trunc(1, 1)
        feedback(p, L, Stat.S_OP1, L.IN + 4 * 32, 3)
        # the levels: F5 operator 2's (sat(4 2VOL^2)), F6 operator 1's
        level(p, L, 2, Stat.S_ENV, 6)
        p.st(W["g"], 6)
        knobf(p, 5, 5)
        p.fop(5, 5, "*", 5)
        p.fconst(12, 4.0)
        p.fop(5, 5, "*", 12)
        K.sat(p, 5)
        p.ld(6, W["g"])
        carrier(p, L, Stat.S_CAR, 2)
        decimate(p, L, Stat.S_DEC)


class Par(_Machine):
    """FM+ PAR: three ramped operators (xFRQ's ratio, xENV's feedback above 64), each at
    sat(4 xENV^2) x its own envelope, TONE's lowpass on each and on the mix."""
    NAME, ID = "FM+PAR", 9
    PNAMES = ("1FRQ", "1ENV", "2FRQ", "2ENV", "3FRQ", "3ENV", "TONE", "TUNE")
    DEFAULTS = (60, 64, 80, 64, 102, 80, 98, 64)
    FB_KNOB = None
    N = 27
    S_OPS, S_CAR, S_LPM, S_ENV, S_DEC = 0, 15, 17, 18, 21

    @staticmethod
    def init(p: Prog, L: C.Layout) -> None:
        zero(p, Par.N)

    @staticmethod
    def trig(p: Prog, L: C.Layout) -> None:
        p.fconst(0, TOP)
        for j in range(3):
            C.sts(p, Par.S_ENV + j, 0)

    @staticmethod
    def half(p: Prog, L: C.Layout) -> None:
        W = L.W
        tone(p, L, 1, 6)
        p.st(W["c"], 1)
        for j in range(3):
            ampfb(p, L, 2 * j + 1, "fb")
            ratio(p, L, 1, 2 * j)
            C.vw(p, 2, "i1")
            p.iconst(12, 0)
            p.float_(2, 2, 12)
            p.fop(1, 1, "*", 2)
            p.fconst(12, 8.0)
            p.fop(1, 1, "*", 12)
            p.trunc(1, 1)
            ramped(p, L, Par.S_OPS + 5 * j, L.IN + 4 * 32 * j)
        level(p, L, 1, Par.S_ENV, 5)
        p.st(W["g"], 5)
        level(p, L, 3, Par.S_ENV + 1, 6)
        p.st(W["m"], 6)
        level(p, L, 5, Par.S_ENV + 2, 8)
        p.ld(5, W["g"])
        p.ld(6, W["m"])
        carrier(p, L, Par.S_CAR, 3)
        decimate(p, L, Par.S_DEC)


class Dyn(_Machine):
    """FM+ DYN: operator 1 (ramped, the carrier's increment + its frequency envelope 1FEN,
    x 1FRQ x 2; level 1VOL plus its volume envelope 1VEN, which also sets its feedback) and
    operator 2 (feedback, 2FRQ^2 x 4, its 2FB; level sat(4 2ENV^2) x its envelope); a fixed
    0.5 lowpass where STAT has TONE."""
    NAME, ID = "FM+DYN", 10
    PNAMES = ("1FRQ", "1FEN", "1VOL", "1VEN", "2FRQ", "2ENV", "2FB", "TUNE")
    DEFAULTS = (64, 64, 64, 64, 74, 80, 30, 64)
    FB_KNOB = 6
    N = 21
    S_OP1, S_OP2, S_CAR, S_LPM, S_ENV, S_VENV, S_FENV, S_DEC = 0, 5, 9, 11, 12, 13, 14, 15

    @staticmethod
    def init(p: Prog, L: C.Layout) -> None:
        zero(p, Dyn.N)

    @staticmethod
    def trig(p: Prog, L: C.Layout) -> None:
        p.fconst(0, TOP)
        C.sts(p, Dyn.S_ENV, 0)
        # the volume envelope: sat(4 (1VEN - 0.5) (x 1VOL below 64))
        knobf(p, 1, 3)
        p.fconst(12, 0.5)
        p.fop(1, 1, "-", 12)
        knobf(p, 2, 2)
        p.fop(2, 1, "*", 2)
        p.ifz(1, "LT", lambda: p.fpass(1, 2), kind="f")
        p.fconst(12, 4.0)
        p.fop(1, 1, "*", 12)
        K.sat(p, 1)
        C.sts(p, Dyn.S_VENV, 1)
        # the frequency envelope: b |b|, b = 1FEN - 0.5 (halved below 64)
        knobf(p, 1, 1)
        p.fconst(12, 0.5)
        p.fop(1, 1, "-", 12)

        def half_():
            p.fconst(12, 0.5)
            p.fop(1, 1, "*", 12)
        p.ifz(1, "LT", half_, kind="f")
        p.fpass(2, 1)
        p.fconst(12, 0.0)
        p.ifz(2, "LT", lambda: p.fop(2, 12, "-", 2), kind="f")
        p.fop(1, 1, "*", 2)
        C.sts(p, Dyn.S_FENV, 1)

    @staticmethod
    def envt(p: Prog, L: C.Layout, d: int, k: int) -> None:
        """Fd = -the ROM's envelope multiplier at 128 - 2 |knob k - 64|. Clobbers R1, R2, R12, I1."""
        C.knob(p, 1, k)
        p.iconst(12, -64)
        p.iop(1, 12, "+", 1)

        def neg():
            p.iconst(12, 0)
            p.iop(1, 12, "-", 1)
        p.ifz(1, "LT", neg)
        p.lsh(1, 1, 1)
        p.iconst(12, 128)
        p.iop(1, 12, "-", 1)
        p.lsh(1, 1, 2)
        p.iconst(12, L.FM["envt"])
        p.iop(1, 12, "+", 1)
        p.seti(1, 1)
        p.ldi(d, 0, 1)
        p.fconst(12, 0.0)
        p.fop(d, 12, "-", d)

    @staticmethod
    def half(p: Prog, L: C.Layout) -> None:
        W = L.W
        p.fconst(1, 0.5)
        p.st(W["c"], 1)
        # the frequency envelope: fenv x -envt(1FEN); operator 1's increment is the carrier's
        # + 2^30 of it, x 1FRQ (1.0 at 127) x 2
        Dyn.envt(p, L, 3, 1)
        C.st(p, 4, Dyn.S_FENV)
        p.fop(3, 3, "*", 4)
        p.fpass(5, 3)
        floor23(p, 5)
        C.sts(p, Dyn.S_FENV, 5)
        p.fconst(12, 2.0 ** 30)
        p.fop(3, 3, "*", 12)
        p.trunc(3, 3)
        C.vw(p, 2, "i1")
        p.ipass(12, 2)
        p.iop(3, 12, "+", 3)                      # a
        p.iconst(12, 0)
        p.float_(3, 3, 12)
        Dyn.frq(p, 1, 0)
        p.fop(1, 1, "*", 3)
        p.fconst(12, 2.0)
        p.fop(1, 1, "*", 12)
        p.trunc(1, 1)
        p.st(W["minc"], 1)
        # the volume envelope: venv x -envt(1VEN); the feedback 16 max(0, sat(1VOL + v - 0.5))
        Dyn.envt(p, L, 3, 3)
        C.st(p, 4, Dyn.S_VENV)
        p.fop(3, 3, "*", 4)
        p.fpass(5, 3)
        floor23(p, 5)
        C.sts(p, Dyn.S_VENV, 5)
        knobf(p, 1, 2)
        p.fop(1, 1, "+", 3)
        p.fconst(12, 0.5)
        p.fop(1, 1, "-", 12)
        K.sat(p, 1)
        p.fconst(12, 0.0)
        p.fop(1, 1, "MAX", 12)
        p.fconst(12, 16.0)
        p.fop(1, 1, "*", 12)
        p.st(W["fb"], 1)
        p.ld(1, W["minc"])
        ramped(p, L, Dyn.S_OP1, L.IN)
        # operator 2: 2FRQ^2 (1.0 at 127) x the increment x 4, its 2FB
        Dyn.frq(p, 1, 4)
        p.fop(1, 1, "*", 1)
        C.vw(p, 2, "i1")
        p.iconst(12, 0)
        p.float_(2, 2, 12)
        p.fop(1, 1, "*", 2)
        p.fconst(12, 4.0)
        p.fop(1, 1, "*", 12)
        p.trunc(1, 1)
        feedback(p, L, Dyn.S_OP2, L.IN + 4 * 32, 6)
        # the levels: F5 operator 1's, sat(4 (1VOL^2 + venv)); F6 operator 2's
        level(p, L, 5, Dyn.S_ENV, 6)
        p.st(W["g"], 6)
        knobf(p, 5, 2)
        p.fop(5, 5, "*", 5)
        C.st(p, 1, Dyn.S_VENV)
        p.fop(5, 5, "+", 1)
        p.fconst(12, 4.0)
        p.fop(5, 5, "*", 12)
        K.sat(p, 5)
        p.ld(6, W["g"])
        carrier(p, L, Dyn.S_CAR, 2)
        decimate(p, L, Dyn.S_DEC)

    @staticmethod
    def frq(p: Prog, d: int, k: int) -> None:
        """Fd = knob k / 128, or 1.0 at 127 (the Monomachine's 0x7FFFFF over 0x7EFFFF)"""
        knobf(p, d, k)
        p.fconst(12, 127.0 / 128)
        p.fconst(13, TOP)
        p.if_(d, "GE", 12, lambda: p.fpass(d, 13))

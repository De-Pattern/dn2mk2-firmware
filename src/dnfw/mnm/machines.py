"""The Monomachine machines as PERC's voice runs them (dnfw.md.voice): the four steps every
machine there has (host, init, trig, render), around each machine module's own
(docs/mnm.md).

- host: the eight 14-bit inputs (knob << 7) -> W[1..8], each knob / 128 (the Monomachine's
  parameter word, knob << 16, as a Q23 fraction);
- render: the pitch word F from the note (VW pitch, float semitones) and TUNE, the
  increment A the Monomachine's kernel would hand the render, the previous slot's F (PRCH,
  MSRC), the machine's own increments (`pitch`), then two of its 16-frame blocks into the
  stream at OUT0.

F = note x 2048 / 12 + TUNE x 683 / 128 (TUNE 64: in tune), 0..0x5800; A = 2^(F / 2048) x
0x1D22A / 2^14 (the kernel's exp table and scaling, in float).
"""

from __future__ import annotations

from . import core as C
from . import ddrw, dens, sid, vo6, wave
from ..md import core as K
from ..perc.dsl import Prog

MODULES = (sid, wave, ddrw, dens, vo6)      # their types: TYPES below (6, 7, 14, 15, 16)
F_TOP = 0x5800


def _host(p: Prog, L: K.Layout) -> None:
    for k in range(8):
        K.inp(p, 0, k)
        p.lsh(0, 0, -7)
        p.iconst(12, -7)
        p.float_(0, 0, 12)
        K.ws(p, C.P0 + k, 0)


# v0.26: semitones added to the DN2's note: VO-6's kernel pitch sounds two octaves over the
# others' (note 60 at 1046 Hz), so on the DN2 it plays where they do
TRANSPOSE = {"VO-6": -24}


def _pitch(p: Prog, L: K.Layout, transpose: int = 0) -> None:
    """VW F, A and pre from VW pitch and TUNE. Clobbers R0-R3, R12-R15, I1, I12."""
    from ..perc import machines as PM
    C.vw(p, 1, "pitch")
    if transpose:
        p.fconst(12, float(transpose))
        p.fop(1, 1, "+", 12)
    p.fconst(12, 2048.0 / 12.0)
    p.fop(1, 1, "*", 12)
    C.knob(p, 2, 7)
    p.iconst(12, 0)
    p.float_(2, 2, 12)
    p.fconst(12, 683.0 / 128.0)
    p.fop(2, 2, "*", 12)
    p.trunc(2, 2)
    p.iconst(12, 0)
    p.float_(2, 2, 12)
    p.fop(1, 1, "+", 2)
    p.fconst(12, 0.0)
    p.fop(1, 1, "MAX", 12)
    p.fconst(12, float(F_TOP))
    p.fop(1, 1, "MIN", 12)
    p.trunc(1, 1)
    C.vws(p, "F", 1)
    p.iconst(12, 0)
    p.float_(1, 1, 12)
    p.fconst(12, 1.0 / 2048.0)
    p.fop(1, 1, "*", 12)
    PM.exp2(p, L.mnm.perc, 1, 1)
    p.fconst(12, 0x1D22A / 2.0 ** 14)
    p.fop(1, 1, "*", 12)
    C.vws(p, "A", 1)
    # the previous slot's F (slot 15's for slot 0): PRCH, MSRC
    p.ld(1, L.C["mdb"])
    p.iconst(12, -K.MD_STRIDE)
    p.iop(1, 12, "+", 1)
    p.iconst(12, L.state)
    p.if_(1, "LT", 12, lambda: (p.iconst(12, 16 * K.MD_STRIDE), p.iop(1, 12, "+", 1)), kind="i")
    p.seti(1, 1)
    p.ldi(2, C.VW["F"], 1)
    C.vws(p, "pre", 2)


def _render(M):
    def render(p: Prog, L: K.Layout) -> None:
        mL = L.mnm
        # I4 is the caller's (the slot's output: dnfw.md.voice.advance keeps I3, I4); the
        # halves below walk their own (v0.26 WIP wrote the voice's output over its words)
        p.e("R0 = I4;")
        if p.run:
            p.r[0] = p.i[4]
        p.st(mL.W["i4s"], 0)
        _pitch(p, L, TRANSPOSE.get(M.NAME, 0))
        M.pitch(p, mL)
        p.iconst(0, 0)
        p.st(mL.W["half"], 0)

        def one():
            p.ld(1, L.C["mdb"])
            p.iconst(12, 4 * K.OUT0)
            p.iop(1, 12, "+", 1)
            p.ld(2, mL.W["half"])
            p.lsh(2, 2, 6)                      # 16 floats a half
            p.ipass(12, 1)
            p.iop(1, 12, "+", 2)
            p.seti(4, 1)
            M.half(p, mL)
            p.ld(2, mL.W["half"])
            p.ipass(12, 2)
            p.iconst(13, 1)
            p.iop(2, 12, "+", 13)
            p.st(mL.W["half"], 2)
        p.loop(mL.W["tmp"], 2, one)
        p.ld(0, mL.W["i4s"])
        p.seti(4, 0)
    return render


def _adapter(M):
    return type(M.NAME.replace(" ", "").replace("-", ""), (), {
        "NAME": M.NAME, "ID": M.ID, "PNAMES": M.PNAMES, "MNM": M,
        "host": staticmethod(_host),
        "init": staticmethod(lambda p, L, M=M: M.init(p, L.mnm)),
        "trig": staticmethod(lambda p, L, M=M: M.trig(p, L.mnm)),
        "render": staticmethod(_render(M)),
    })


MACHINES = tuple(_adapter(M) for M in MODULES)
NAMES = tuple(M.NAME for M in MACHINES)
DEFAULTS = {M.NAME: M.DEFAULTS for M in MODULES}

# each machine its own machine type (MACHINE SEL entry), in MODULES order: CZ's and
# RESONATOR's former types, then the ones after the sample machines (8..13). One table for
# the ColdFire (dnfw.waverider.coldfire, pages), the DSP's lookup (dnfw.waverider.dsp) and
# PERC's voice (dnfw.perc.program).
TYPE_SLOTS = (6, 7, 14, 15, 16)
TYPES = TYPE_SLOTS[:len(MACHINES)]
# MACHINE SEL's names (long, short), as the DN2 lists its own
LIST_NAMES = {"SID 6581": ("SID 6581", "SID"), "DPRO-WAVE": ("DPRO Wave", "DPW"),
              "DPRO-DDRW": ("DPRO Ddrw", "DDW"), "DPRO-DENS": ("DPRO Dens", "DNS"),
              "VO-6": ("VO-6", "VO6")}

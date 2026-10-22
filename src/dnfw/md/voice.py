"""A PERC voice playing a Machinedrum machine (docs/md.md): the machine at 44.1 kHz, block
by block, and the DN2's 48 kHz block read from that stream.

`block(p, L, knobs, note, want)` is one DN2 block for the slot whose words I3 points at
(and C['mdb'] holds), writing 32 samples at I4:
  1. the eight knobs (floats 0..1 in the scratch words KNOBS) become the Machinedrum's
     eight 14-bit inputs (knob x 16256: the MD's knob << 7); a change marks the words
     dirty;
  2. a note (Rnote != 0) asks for machine WANT (the TYPE now) and marks a trig waiting;
  3. if the read position has passed the stream's first block, the stream moves on a
     block and the machine renders the next (`advance`): a waiting note runs init (if the
     machine changes), the host's scale function (as a note) and trig; dirty words run
     the scale function alone (as a parameter change, which some machines answer with
     fewer words, or none, as the Machinedrum does);
  4. 32 samples are read at 0.91875 stream samples a sample with 4-point Catmull-Rom
     interpolation into the DN2's buffer.

Until its first note a slot plays nothing (VW['mach'] is -1).
"""

from __future__ import annotations

from . import core as K
from . import machines as MM
from ..perc.dsl import Prog

N = len(MM.MACHINES)
KNOB_SCALE = 16256.0                          # knob 0..1 -> 0..127 << 7
START = 35.0                                  # the read position that asks for a new block


def _each(p: Prog, L: K.Layout, step: str) -> None:
    """STEP of the machine whose index is in VW['mach'] (>= 0): a compare chain in emit
    mode; run mode calls the one machine."""
    if p.run:
        K.vw(p, 0, "mach")
        getattr(MM.MACHINES[min(p.r[0], N - 1)], step)(p, L)
        return
    end = p.label(f"md_{step}_end")
    for k, M in enumerate(MM.MACHINES):
        nxt = p.label("md_next")
        if k < N - 1:
            K.vw(p, 0, "mach")
            p.iconst(12, k)
            p.e("COMP(R0, R12);")
            p.jump("NE", nxt)
        p.comment(f"---- {M.NAME} {step} ----")
        getattr(M, step)(p, L)
        p.jump("", end)
        p.place(nxt)
    p.place(end)


def reset(p: Prog, L: K.Layout) -> None:
    """The slot's words cleared, no machine, the stream asking for a block. Clobbers R0,
    R12, I5."""
    p.ld(0, L.C["mdb"])
    p.seti(5, 0)
    p.iconst(6, 0)
    p.loop(L.C["n1"], K.MD_WORDS, lambda: p.stpost(5, 6))
    p.iconst(0, -1)
    K.vws(p, "mach", 0)
    p.fconst(0, START)
    K.vws(p, "pos", 0)


def advance(p: Prog, L: K.Layout) -> None:
    """The stream moves on a block (B[32..66] -> B[0..34]) and the next is rendered at
    OUT0. Clobbers everything but I3, I4."""
    p.ld(1, L.C["mdb"])
    p.iconst(12, 4 * K.B0)
    p.iop(1, 12, "+", 1)
    p.seti(5, 1)                               # I5: B[0]
    p.iconst(12, 4 * 32)
    p.iop(1, 12, "+", 1)
    p.seti(1, 1)                               # I1: B[32]

    def move():
        p.ldpost(6, 1)
        p.stpost(5, 6)
    p.loop(L.C["n1"], 35, move)
    K.vw(p, 0, "trg")

    def note():
        K.vw(p, 0, "want")
        K.vw(p, 1, "mach")
        p.e("COMP(R0, R1);")

        def change():
            K.vw(p, 0, "want")
            K.vws(p, "mach", 0)
            _each(p, L, "init")
        p._branch(lambda: p.r[0] != p.r[1], "NE", change, None)
        _each(p, L, "host")
        _each(p, L, "trig")
        p.iconst(0, 0)
        K.vws(p, "trg", 0)
        K.vws(p, "dirty", 0)

    def no_note():
        K.vw(p, 0, "mach")

        def playing():
            K.vw(p, 0, "dirty")

            def again():
                _each(p, L, "host")
                p.iconst(0, 0)
                K.vws(p, "dirty", 0)
            p.ifz(0, "NE", again)
        p.ifz(0, "GE", playing)
    p.ifz(0, "NE", note, no_note)
    K.vw(p, 0, "mach")

    def silent():
        p.ld(1, L.C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(1, 12, "+", 1)
        p.seti(5, 1)
        p.fconst(6, 0.0)
        p.loop(L.C["n1"], 32, lambda: p.stpost(5, 6))
    p.ifz(0, "GE", lambda: _each(p, L, "render"), silent)


def inputs(p: Prog, L: K.Layout, knobs: list[int]) -> None:
    """Step 1: the knob words (scratch addresses KNOBS, floats 0..1) -> the eight 14-bit
    inputs; any change marks the words dirty. Clobbers R0-R2, R12."""
    for k, a in enumerate(knobs):
        p.ld(0, a)
        p.fconst(12, KNOB_SCALE)
        p.fop(0, 0, "*", 12)
        p.fconst(12, 0.5)
        p.fop(0, 0, "+", 12)
        p.trunc(0, 0)
        p.iconst(12, 0)
        p.iop(0, 0, "MAX", 12)
        p.iconst(12, 16383)
        p.iop(0, 0, "MIN", 12)
        K.inp(p, 1, k)
        p.e("COMP(R0, R1);")

        def changed(k=k):
            p.sti(K.INP0 + k, 3, 0)
            p.iconst(2, 1)
            K.vws(p, "dirty", 2)
        p._branch(lambda: p.r[0] != p.r[1], "NE", changed, None)


def block(p: Prog, L: K.Layout, knobs: list[int], note: int, want: int, level: float = 1.0) -> None:
    """One DN2 block (steps 1-4): KNOBS the scratch words of the eight knobs, Rnote nonzero
    for a note, Rwant the machine TYPE asks for (0..N-1). Output at I4 (advanced past the
    block). Clobbers everything but I3."""
    p.ifz(note, "NE", lambda: (K.vws(p, "want", want), p.iconst(0, 1), K.vws(p, "trg", 0)))
    inputs(p, L, knobs)
    K.vw(p, 0, "pos")
    p.fconst(12, START)
    p.if_(0, "GE", 12, lambda: (advance(p, L), K.vw(p, 0, "pos"), p.fconst(12, 32.0),
                                  p.fop(0, 0, "-", 12), K.vws(p, "pos", 0)))
    # step 4: Catmull-Rom over B[i-1..i+2], i = trunc(pos), f = pos - i
    p.ld(0, L.C["mdb"])
    p.iconst(12, 4 * (K.B0 - 1))
    p.iop(0, 12, "+", 0)
    p.st(L.C["k"], 0)                          # the address of B[-1]

    def one():
        K.vw(p, 6, "pos")
        p.trunc(7, 6)
        p.iconst(12, 0)
        p.float_(8, 7, 12)
        p.fop(8, 6, "-", 8)                    # f
        p.lsh(7, 7, 2)
        p.ld(9, L.C["k"])
        p.iop(7, 9, "+", 7)
        p.seti(1, 7)
        p.ldpost(0, 1)                         # a = B[i-1]
        p.ldpost(1, 1)                         # b
        p.ldpost(2, 1)                         # c
        p.ldpost(3, 1)                         # d
        # y = b + f/2 (c - a + f (2a - 5b + 4c - d + f (3(b - c) + d - a)))
        p.fop(9, 1, "-", 2)
        p.fconst(12, 3.0)
        p.fop(9, 9, "*", 12)
        p.fop(9, 9, "+", 3)
        p.fop(9, 9, "-", 0)                    # 3(b - c) + d - a
        p.fop(9, 9, "*", 8)
        p.fop(10, 0, "+", 0)                   # 2a
        p.fconst(12, 5.0)
        p.fop(11, 1, "*", 12)
        p.fop(10, 10, "-", 11)                 # - 5b
        p.fconst(12, 4.0)
        p.fop(11, 2, "*", 12)
        p.fop(10, 10, "+", 11)                 # + 4c
        p.fop(10, 10, "-", 3)                  # - d
        p.fop(9, 9, "+", 10)
        p.fop(9, 9, "*", 8)
        p.fop(10, 2, "-", 0)
        p.fop(9, 9, "+", 10)
        p.fop(9, 9, "*", 8)
        p.fconst(12, 0.5 * level)
        p.fop(9, 9, "*", 12)
        p.fconst(12, level)
        p.fop(10, 1, "*", 12)
        p.fop(9, 9, "+", 10)
        p.stpost(4, 9)
        p.fconst(12, K.STEP)
        p.fop(6, 6, "+", 12)
        K.vws(p, "pos", 6)
    p.loop(L.C["n1"], 32, one)

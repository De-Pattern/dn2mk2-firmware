"""A PERC voice playing a Machinedrum machine (docs/md.md): the machine at 44.1 kHz, block
by block, and the DN2's 48 kHz block read from that stream.

`block(p, L, knobs, note, want)` is one DN2 block for the slot whose words I3 points at
(and C['mdb'] holds), writing 32 samples at I4:
  1. the eight knobs (floats 0..1 in the scratch words KNOBS) become the Machinedrum's
     eight 14-bit inputs (the nearest of its 128 knob positions, << 7); a change marks
     the words dirty;
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

N = len(MM.MACHINES)                          # PERC's TYPE spans these
try:                                          # v0.26: the Monomachine's synth machines, chosen by
    from ..mnm import machines as _MNM        # their machine type, after the Machinedrum's
    ALL = MM.MACHINES + _MNM.MACHINES
except ImportError:                           # pragma: no cover
    ALL = MM.MACHINES
N_ALL = len(ALL)
INIT_FIRST = [k for k, M in enumerate(MM.MACHINES) if getattr(M, "INIT_FIRST", False)]
# v0.42: the machines whose voices use the slot's delay area (core.delay_base): P-I, VO-6
_DLY = [k for k, M in enumerate(ALL) if M.NAME.startswith("PI-") or M.NAME == "VO-6"]
DELAY_LO, DELAY_HI = min(k for k in _DLY if ALL[k].NAME.startswith("PI-")), max(k for k in _DLY if ALL[k].NAME.startswith("PI-"))
assert [k for k in _DLY if ALL[k].NAME.startswith("PI-")] == list(range(DELAY_LO, DELAY_HI + 1))
DELAY_ALSO = [k for k in _DLY if not ALL[k].NAME.startswith("PI-")]
KNOB_SCALE = 16256.0                          # knob 0..1 -> 0..127 << 7
START = 35.0                                  # the read position that asks for a new block
QUIET_LEVEL = 2.0 ** -21                      # a block whose peak is under this is silence
QUIET_BLOCKS = 32                             # this many in a row (23 ms) and the machine rests


def _same_code(step: str) -> dict[int, int]:
    """machine index -> the index of the first machine whose STEP is the same code (a
    machine that is another's DSP code with its own scale function, TRX-OH on TRX-CH's,
    shares that machine's render, init and trig): the same function, emitting the same text."""
    def text(M):
        q = Prog("emit", prefix="md_probe")
        q.spill = _PROBE_L.C["ash"]
        getattr(M, step)(q, _PROBE_L)
        return q.text()
    out, seen = {}, {}
    for k, M in enumerate(ALL):
        if hasattr(M, "MNM"):                 # their own code each, but one host (the same)
            out[k] = seen.setdefault("mnm_host", k) if step == "host" else k
            continue
        f = getattr(M, step)
        key = getattr(f, "__func__", f)
        if key in seen and text(ALL[seen[key]]) == text(M):
            out[k] = seen[key]
        else:
            seen.setdefault(key, k)
            out[k] = k
    return out


_PROBE_L = K.Layout(0x100000, 0x80000, 0x200000)


def _each(p: Prog, L: K.Layout, step: str) -> None:
    """STEP of the machine whose index is in VW['mach'] (>= 0): a compare chain in emit
    mode, each distinct code once; run mode calls the one machine."""
    if p.run:
        K.vw(p, 0, "mach")
        getattr(ALL[min(p.r[0], N_ALL - 1)], step)(p, L)
        return
    same = _same_code(step)
    end = p.label(f"md_{step}_end")
    body = {k: p.label(f"md_{step}_{k}") for k in set(same.values())}
    K.vw(p, 0, "mach")                         # once: each body leaves by JUMP, so R0 stays
    for k, M in enumerate(ALL):
        nxt = p.label("md_next")
        if k < N_ALL - 1:
            p.iconst(12, k)
            p.e("COMP(R0, R12);")
            p.jump("NE", nxt)
        if same[k] == k:
            p.comment(f"---- {M.NAME} {step} ----")
            p.place(body[k])
            getattr(M, step)(p, L)
            p.jump("", end)
        else:
            p.comment(f"---- {M.NAME} {step}: {ALL[same[k]].NAME}'s ----")
            p.jump("", body[same[k]])
        p.place(nxt)
    p.place(end)


def reset(p: Prog, L: K.Layout) -> None:
    """The slot's words cleared, no machine, the stream asking for a block. Clobbers R0,
    R12, I5."""
    p.ld(0, L.C["mdb"])
    p.seti(5, 0)
    p.iconst(6, 0)
    p.loop(L.C["n1"], K.MD_WORDS, lambda: p.stpost(5, 6))
    # v0.24: and its P-I delay lines (the Machinedrum's start as its emulator's: zeros)
    K.delay_base(p, L, 0)
    p.seti(5, 0)
    p.iconst(6, 0)
    p.loop(L.C["n1"], K.PI_DELAY_WORDS, lambda: p.stpost(5, 6))
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
    # v0.24: the host's scale function is emitted once (it was twice: after a note and
    # for dirty words), run when a note waits or, with a machine, when words are dirty
    K.vw(p, 0, "trg")

    def change_if_new():
        K.vw(p, 0, "want")
        K.vw(p, 1, "mach")
        p.e("COMP(R0, R1);")

        def change():                          # init runs after the host (below)
            # v0.42 (the owner: PI-HH played a rimshot-like note, then loud spikes, with PI-BD
            # and TRX-CP on other tracks, gone with the tracks locked to one voice): the DSP's
            # voices go round the tracks, and a voice that played another machine kept its
            # host words, state, stream and P-I delay lines, under the new machine (a ringing
            # PI-RS's voice handed a TRX-CP note peaked at 1.40, fresh 0.41). A voice changing
            # machine now starts as a fresh one (reset's words, but the voice's own: the read
            # position, the note waiting, the inputs), its delay lines too if the machine it
            # leaves used them (the P-I machines, VO-6)
            K.vw(p, 1, "mach")

            def clear():
                p.ld(0, L.C["mdb"])
                p.seti(5, 0)
                p.iconst(6, 0)
                p.loop(L.C["n1"], K.B0 + K.NB, lambda: p.stpost(5, 6))   # W, S, the stream

                def lines():
                    K.delay_base(p, L, 0)
                    p.seti(5, 0)
                    p.iconst(6, 0)
                    p.loop(L.C["n1"], K.PI_DELAY_WORDS, lambda: p.stpost(5, 6))
                K.vw(p, 1, "mach")
                p.iconst(12, DELAY_LO)
                p.iconst(2, 0)
                p.if_(1, "GE", 12, lambda: (p.iconst(12, DELAY_HI),
                                            p.if_(1, "LE", 12, lambda: p.iconst(2, 1), kind="i")), kind="i")
                for k in DELAY_ALSO:
                    p.iconst(12, k)
                    p.if_(1, "EQ", 12, lambda: p.iconst(2, 1), kind="i")
                p.ifz(2, "NE", lines)
            p.ifz(1, "GE", clear)
            K.vw(p, 0, "want")
            K.vws(p, "mach", 0)
            p.iconst(0, 1)
            K.vws(p, "chg", 0)
            for k in INIT_FIRST:               # ... but these machines' before it
                K.vw(p, 0, "mach")
                p.iconst(12, k)

                def first(M=MM.MACHINES[k]):
                    M.init(p, L)               # (its own init only: the chain is emitted once, below)
                    p.iconst(0, 0)
                    K.vws(p, "chg", 0)
                p.if_(0, "EQ", 12, first, kind="i")
        p._branch(lambda: p.r[0] != p.r[1], "NE", change, None)
    p.ifz(0, "NE", change_if_new)
    K.vw(p, 0, "trg")

    def no_trg():                              # R0 = dirty, or 0 with no machine
        K.vw(p, 1, "mach")
        K.vw(p, 0, "dirty")
        p.ifz(1, "LT", lambda: p.iconst(0, 0))
    p.ifz(0, "EQ", no_trg)

    def host():
        _each(p, L, "host")
        p.iconst(0, 0)
        K.vws(p, "dirty", 0)
    # v0.24: a new machine's init after its host scale function, as the Machinedrum (and
    # its golden runs) order them: some inits overwrite a host word (P-IRC's DEC), so
    # init first made the first hit after choosing a machine sound like the second.
    # v0.42: then the host again, so the note plays its knobs: on the DN2 a voice changes
    # machine whenever the voices go round the tracks, so the Machinedrum's "first hit after
    # choosing a machine" (P-I's at DEC 127, the owner's ringing hi-hat) fell on a note in
    # every few; now every note is the machine's own hit at its knobs (the Machinedrum's
    # second hit after a silence). Two passes of the one emitted host (it is 4,666
    # instructions): the second only after an init
    p.st(L.C["hq"], 0)

    def hpass():
        p.ld(0, L.C["hq"])
        p.ifz(0, "NE", host)
        p.iconst(0, 0)
        p.st(L.C["hq"], 0)
        K.vw(p, 0, "chg")

        def init():
            _each(p, L, "init")
            p.iconst(0, 0)
            K.vws(p, "chg", 0)
            p.iconst(0, 1)
            p.st(L.C["hq"], 0)
        p.ifz(0, "NE", init)
    p.loop(L.C["hpass"], 2, hpass)
    K.vw(p, 0, "trg")

    def trig():
        _each(p, L, "trig")
        p.iconst(0, 0)
        K.vws(p, "trg", 0)
        K.vws(p, "quiet", 0)
    p.ifz(0, "NE", trig)

    def silent():
        p.ld(1, L.C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(1, 12, "+", 1)
        p.seti(5, 1)
        p.fconst(6, 0.0)
        p.loop(L.C["n1"], 32, lambda: p.stpost(5, 6))

    def sound():
        _each(p, L, "render")
        # silent long enough (QUIET_BLOCKS blocks under QUIET_LEVEL): the machine rests
        # until the next note, as its sound has died away (it costs the DSP nothing then)
        p.ld(1, L.C["mdb"])
        p.iconst(12, 4 * K.OUT0)
        p.iop(1, 12, "+", 1)
        p.seti(5, 1)
        p.fconst(7, 0.0)

        def peak():
            p.ldpost(6, 5)
            p.fop(7, 7, "MAX", 6)
            p.fconst(13, 0.0)
            p.fop(6, 13, "-", 6)
            p.fop(7, 7, "MAX", 6)
        p.loop(L.C["n1"], 32, peak)
        K.vw(p, 0, "quiet")
        p.fconst(12, QUIET_LEVEL)
        p.if_(7, "LT", 12, lambda: (p.iconst(12, 1), p.iop(0, 12, "+", 0)),
              lambda: p.iconst(0, 0))
        K.vws(p, "quiet", 0)
    K.vw(p, 0, "mach")

    def playing():
        K.vw(p, 0, "quiet")
        p.iconst(12, QUIET_BLOCKS)
        p.if_(0, "GE", 12, silent, sound, kind="i")
    p.ifz(0, "GE", playing, silent)


def inputs(p: Prog, L: K.Layout, knobs: list[int]) -> None:
    """Step 1: the knob words (scratch addresses KNOBS, floats 0..1) -> the eight 14-bit
    inputs; any change marks the words dirty. Clobbers R0-R2, R12."""
    for k, a in enumerate(knobs):
        p.ld(0, a)
        p.fconst(12, 127.0)
        p.fop(0, 0, "*", 12)
        p.fconst(12, 0.5)
        p.fop(0, 0, "+", 12)
        p.trunc(0, 0)
        p.lsh(0, 0, 7)                         # the Machinedrum's knob, 0..127, << 7
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


def block(p: Prog, L: K.Layout, knobs: list[int], note: int, want: int, level: float = 1.0,
          level_word: int | None = None) -> None:
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
        if level_word is None:
            p.fconst(12, 0.5 * level)
            p.fop(9, 9, "*", 12)
            p.fconst(12, level)
        else:                                  # v0.26: the level from a word (x 0.5, then x level:
            p.fconst(12, 0.5)                  # the same product, bit for bit)
            p.fop(9, 9, "*", 12)
            p.ld(12, level_word)
            p.fop(9, 9, "*", 12)
        p.fop(10, 1, "*", 12)
        p.fop(9, 9, "+", 10)
        p.stpost(4, 9)
        p.fconst(12, K.STEP)
        p.fop(6, 6, "+", 12)
        K.vws(p, "pos", 6)
    p.loop(L.C["n1"], 32, one)

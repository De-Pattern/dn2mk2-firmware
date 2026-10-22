"""The sample machines' DSP program (docs/sampler.md), in PERC's two-backend DSL
(dnfw.perc.dsl): the same calls are the SHARC assembly and its exact model.

Entered from PERC's tail; loops the 16 slots and renders every track whose machine type
is a sample machine with an engine, then jumps on to RESONATOR (and so to CZ and PING,
whose tail restores the registers PERC saved).

A voice plays one pool slot (dnfw.sampler.machines.POOL_*): float32 mono frames in DDR,
read with linear interpolation at an integer position plus a fraction, forward or
backward, once or looping. A note latches the machine, the slot and the region; the
pitch (the note, TUNE, the slot's own rate) and the level follow the knobs every block.
"""

from __future__ import annotations

from ..perc import machines as PM
from ..perc import program as PP
from ..perc.dsl import Prog, s32
from . import machines as SM

V = dict(on=0, mach=1, pos=2, frac=3, lo=4, hi=5, loop=6, mode=7, base=8, frames=9, rate=10,
         last=11, low=12)
STATE_WORDS = 16
STATE_STRIDE = 64
SC_WORDS = ("t", "count", "tr", "trig", "sbase", "type", "rate", "gain",
            "tune", "play", "samp", "a", "b", "c", "lev", "x", "y", "n", "tmp")


class Layout:
    def __init__(self, state: int, scratch: int, pool: int, exp2: int):
        self.state, self.pool, self.exp2 = state, pool, exp2
        self.C = {w: scratch + 4 * k for k, w in enumerate(SC_WORDS)}
        # PM.exp2 reads the table through L.T
        self.T = {"exp2": exp2}


def v(p: Prog, d: int, w: str) -> None:
    p.ldi(d, V[w], 2, w)


def vs(p: Prog, w: str, s: int) -> None:
    p.sti(V[w], 2, s, w)


def ctl(p: Prog, d: int, rec: int, k146: int) -> None:
    """Rd = the control on record REC as an integer 0..top. Clobbers R0, R1, R12, I1."""
    slot, lo, top = SM.RECORDS[rec]
    PP.half(p, d, PM.frame_offset(slot), k146)
    p.lsh(d, d, -8)
    p.iconst(12, -lo)
    p.iop(d, 12, "+", d)
    p.iconst(12, 0)
    p.iop(d, d, "MAX", 12)
    p.iconst(12, top)
    p.iop(d, d, "MIN", 12)


def tofloat(p: Prog, d: int, a: int, scale: float = 1.0) -> None:
    """Fd = float(Ra) * scale. Clobbers R12."""
    p.iconst(12, 0)
    p.float_(d, a, 12)
    if scale != 1.0:
        p.fconst(12, scale)
        p.fop(d, d, "*", 12)


def voice(p: Prog, L: Layout, t: int | None = None) -> None:
    C = L.C
    if p.run:
        p.iconst(9, t)
        p.st(C["t"], 9)
    p.ld(9, C["t"])
    p.lsh(12, 9, 6)
    p.iconst(11, L.state)
    p.iop(12, 11, "+", 12)
    p.seti(2, 12, "this slot's state")
    # the trigger bit
    p.ld(0, PP.TRIG_WORD)
    p.lsh(0, 0, -16)
    p.iconst(1, 1)
    p.ld(9, C["t"])
    PP._shift_by(p, 1, 9)
    p.iop(0, 0, "AND", 1)
    p.st(C["trig"], 0)
    # the controls this block
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 4, SM.TUNE_REC, 10)
    p.iconst(12, -60)
    p.iop(4, 12, "+", 4)                     # semitones, -60..+60
    tofloat(p, 5, 4, 1.0 / 12.0)
    p.st(C["tune"], 5)
    ctl(p, 4, SM.LEV_REC, 10)
    tofloat(p, 5, 4, 1.0 / SM.LEV_UNITY)
    p.st(C["lev"], 5)
    # the note, as PERC reads it: tr = 2^((note - 60) / 12 + tune / 12)
    p.ld(9, C["t"])
    p.lsh(12, 9, 2)
    p.iconst(11, PP.NOTE_CELLS)
    p.iop(12, 11, "+", 12)
    p.seti(1, 12)
    p.ldi(8, 0, 1)
    p.lsh(12, 8, -23)
    p.iconst(13, 0xFF)
    p.iop(12, 12, "AND", 13)
    p.if_(12, "EQ", 13, lambda: p.iconst(8, 0), kind="i")
    p.ifz(8, "LT", lambda: p.iconst(8, 0))
    p.fconst(12, 60.0)
    p.fop(8, 8, "-", 12)
    p.fconst(12, 1.0 / 12.0)
    p.fop(8, 8, "*", 12)
    p.ld(5, C["tune"])
    p.fop(8, 8, "+", 5)
    PM.exp2(p, L, 9, 8)
    p.st(C["tr"], 9)
    # a note: latch the machine, the slot and the region
    p.ld(0, C["trig"])
    p.ifz(0, "NE", lambda: start(p, L))
    # the voice's rate and level this block
    v(p, 0, "on")

    def sounding():
        p.ld(4, C["tr"])
        v(p, 5, "rate")
        p.fop(4, 4, "*", 5)
        p.st(C["rate"], 4)
        render(p, L)
    p.ifz(0, "NE", sounding, lambda: silence(p, L))


def silence(p: Prog, L: Layout) -> None:
    buffer(p, L)
    p.iconst(6, 0)
    p.loop(L.C["count"], 32, lambda: p.stpost(4, 6))


def buffer(p: Prog, L: Layout) -> None:
    p.ld(9, L.C["t"])
    p.lsh(12, 9, 2)
    p.iconst(11, PP.BUFFERS)
    p.iop(12, 11, "+", 12)
    p.seti(1, 12)
    p.ldi(0, 0, 1)
    p.seti(4, 0, "the slot's buffer")


def start(p: Prog, L: Layout) -> None:
    """A note: the machine from the record, the pool slot from SAMP, the region and the
    play mode from the machine's controls. A slot the pool does not hold leaves the
    voice off."""
    C = L.C
    p.iconst(0, 0)
    vs(p, "on", 0)
    p.ld(0, C["type"])
    vs(p, "mach", 0)
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 4, SM.SAMP_REC, 10)               # 0..127
    p.st(C["samp"], 4)
    ctl(p, 4, SM.PLAY_REC, 10)               # 0..127 -> 0..3
    p.lsh(4, 4, -5)
    vs(p, "mode", 4)
    # the pool: its magic, its count, the slot's entry
    p.ld(0, L.pool)
    p.iconst(12, SM.POOL_MAGIC)

    def found():
        p.ld(0, L.pool + 4)                  # count
        p.ld(4, C["samp"])
        p.iconst(12, -1)
        p.iop(4, 12, "+", 4)                 # SAMP 0 is OFF: slot = SAMP - 1
        p.st(C["samp"], 4)
        p.e("COMP(R4, R0);")

        def have():
            p.ld(4, C["samp"])
            p.lsh(4, 4, 4)                   # 16 bytes an entry
            p.iconst(12, L.pool + 8)
            p.iop(4, 12, "+", 4)
            p.seti(1, 4)
            p.ldi(5, 0, 1)
            vs(p, "base", 5)
            p.ldi(6, 1, 1)
            vs(p, "frames", 6)
            p.ldi(7, 2, 1)
            vs(p, "rate", 7)
            region(p, L)
        def inrange():
            p.ld(4, C["samp"])
            p.ifz(4, "GE", have)             # and not OFF (-1)
        p._branch(lambda: s32(p.r[4]) < s32(p.r[0]), "LT", inrange, None)
    p.e("COMP(R0, R12);")
    p._branch(lambda: p.r[0] == p.r[12], "EQ", found, None)


def region(p: Prog, L: Layout) -> None:
    """lo, hi (exclusive), loop and the start position for the latched machine, then on."""
    C = L.C
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    v(p, 6, "frames")
    tofloat(p, 13, 6)                        # F13 = frames
    p.ld(0, C["type"])
    p.iconst(12, SM.TYPE_OF["GRID"])
    p.e("COMP(R0, R12);")

    def grid():
        ctl(p, 4, SM.GRID_REC, 10)           # 0..120 -> 0..4
        # g = min(v // 24, 4) by repeated compare: (v >= 24) + (v >= 48) + ...
        p.iconst(5, 0)
        for k in (24, 48, 72, 96):
            p.iconst(12, k)
            p.if_(4, "GE", 12, lambda: (p.iconst(12, 1), p.iop(5, 12, "+", 5)), kind="i")
        p.iconst(6, 4)
        PP._shift_by(p, 6, 5)                # n = 4 << g
        p.iconst(12, -2)
        p.iop(7, 12, "-", 5)                 # -(2 + g)
        p.iconst(8, 1)
        p.float_(8, 8, 7)                    # F8 = 1/n, exactly
        p.ld(9, C["t"])
        PP.t146(p, 10, 9)
        ctl(p, 4, SM.SLICE_REC, 10)          # 0..127 -> 0..63
        p.lsh(4, 4, -1)
        p.iconst(12, -1)
        p.iop(12, 12, "+", 6)                # n - 1 (n is a power of two)
        p.iop(4, 4, "AND", 12)               # s mod n
        p.st(C["a"], 4)
        ctl(p, 5, SM.SLEN_REC, 10)           # 0..127 -> slices 1..64
        p.lsh(5, 5, -1)
        p.iconst(12, 1)
        p.iop(5, 12, "+", 5)
        p.st(C["b"], 5)
        v(p, 6, "frames")
        tofloat(p, 13, 6)
        p.fop(13, 13, "*", 8)                # size = frames / n
        p.ld(4, C["a"])
        tofloat(p, 14, 4)
        p.fop(14, 14, "*", 13)               # lo = s size
        p.ld(5, C["b"])
        tofloat(p, 15, 5)
        p.fop(15, 15, "*", 13)
        p.fop(15, 15, "+", 14)               # hi = lo + len size
        p.trunc(4, 14)
        p.trunc(5, 15)
        vs(p, "lo", 4)
        vs(p, "loop", 4)
        v(p, 6, "frames")
        p.iop(5, 5, "MIN", 6)
        vs(p, "hi", 5)

    def oneshot():
        ctl(p, 4, SM.STRT_REC, 10)           # 0..120
        tofloat(p, 14, 4, 1.0 / 120.0)
        p.fop(14, 14, "*", 13)               # lo = STRT frames
        ctl(p, 4, SM.LEN_REC, 10)            # 0..127
        tofloat(p, 15, 4, 1.0 / 127.0)
        p.fop(15, 15, "*", 13)
        p.fop(15, 15, "+", 14)               # hi = lo + LEN frames
        p.trunc(4, 14)
        p.trunc(5, 15)
        v(p, 6, "frames")
        p.iop(5, 5, "MIN", 6)
        vs(p, "lo", 4)
        vs(p, "hi", 5)
        ctl(p, 7, SM.LOOP_REC, 10)           # 0..127: the loop point, in the whole sample
        tofloat(p, 7, 7, 1.0 / 127.0)
        p.fop(7, 7, "*", 13)
        p.trunc(6, 7)
        v(p, 4, "lo")
        v(p, 5, "hi")
        p.iop(6, 6, "MAX", 4)                # kept inside lo .. hi - 1
        p.iconst(12, -1)
        p.iop(12, 12, "+", 5)
        p.iop(6, 6, "MIN", 12)
        vs(p, "loop", 6)
    p._branch(lambda: p.r[0] == p.r[12], "EQ", grid, oneshot)
    # an empty region plays nothing
    v(p, 4, "lo")
    v(p, 5, "hi")
    p.e("COMP(R4, R5);")

    def go():
        v(p, 0, "mode")
        p.iconst(12, 2)
        p.e("COMP(R0, R12);")

        def fwd():
            v(p, 4, "lo")
            vs(p, "pos", 4)

        def rev():
            v(p, 5, "hi")
            p.iconst(12, -1)
            p.iop(5, 12, "+", 5)
            vs(p, "pos", 5)
        p._branch(lambda: s32(p.r[0]) - s32(p.r[12]) >= 0, "GE", fwd, rev)
        # the backward floor: LOOP in REVERSE LOOP (it loops between LEN's end and LOOP),
        # the region's start otherwise
        v(p, 4, "lo")
        vs(p, "low", 4)
        v(p, 0, "mode")
        p.iconst(12, 1)
        p.e("COMP(R0, R12);")
        p._branch(lambda: p.r[0] == p.r[12], "EQ", lambda: (v(p, 4, "loop"), vs(p, "low", 4)), None)
        p.fconst(0, 0.0)
        vs(p, "frac", 0)
        p.iconst(0, 1)
        vs(p, "on", 0)
    p._branch(lambda: s32(p.r[4]) - s32(p.r[5]) < 0, "LT", go, None)


def render(p: Prog, L: Layout) -> None:
    """32 samples of the latched region at the block's rate, linear interpolation."""
    C = L.C
    buffer(p, L)

    def sample():
        v(p, 0, "on")

        def play():
            v(p, 9, "pos")
            v(p, 10, "base")
            p.lsh(12, 9, 2)
            p.ipass(13, 10)
            p.iop(12, 13, "+", 12)
            p.seti(1, 12)
            p.ldi(0, 0, 1)                   # s0 = pool[pos]
            # s1: the next frame in the play direction, held at the sample's ends
            v(p, 6, "frames")
            v(p, 7, "mode")
            p.iconst(12, 2)
            p.e("COMP(R7, R12);")

            def nxt_f():
                p.iconst(12, 1)
                p.iop(11, 12, "+", 9)
                p.iconst(12, -1)
                p.iop(12, 12, "+", 6)        # frames - 1
                p.iop(11, 11, "MIN", 12)

            def nxt_r():
                p.iconst(12, -1)
                p.iop(11, 12, "+", 9)
                p.iconst(12, 0)
                p.iop(11, 11, "MAX", 12)
            p._branch(lambda: s32(p.r[7]) - s32(p.r[12]) >= 0, "GE", nxt_f, nxt_r)
            p.lsh(12, 11, 2)
            p.ipass(13, 10)
            p.iop(12, 13, "+", 12)
            p.seti(1, 12)
            p.ldi(1, 0, 1)                   # s1
            v(p, 2, "frac")
            p.fop(1, 1, "-", 0)
            p.fop(1, 1, "*", 2)
            p.fop(0, 0, "+", 1)              # s0 + (s1 - s0) frac
            p.ld(3, C["lev"])
            p.fop(0, 0, "*", 3)
            p.stpost(4, 0)
            advance(p, L)

        def rest():
            p.iconst(6, 0)
            p.stpost(4, 6)
        p.ifz(0, "NE", play, rest)
    p.loop(C["count"], 32, sample)


def advance(p: Prog, L: Layout) -> None:
    """frac += rate; pos moves by its whole part in the play direction; at the region's
    end the voice loops (from loop forward, or from hi - 1 back to loop backward) or stops."""
    C = L.C
    v(p, 2, "frac")
    p.ld(3, C["rate"])
    p.fop(2, 2, "+", 3)
    p.trunc(5, 2)                            # whole frames
    p.iconst(12, 0)
    p.float_(6, 5, 12)
    p.fop(2, 2, "-", 6)
    vs(p, "frac", 2)
    v(p, 9, "pos")
    v(p, 7, "mode")
    p.iconst(12, 2)
    p.e("COMP(R7, R12);")

    def fwd():
        p.ipass(12, 9)
        p.iop(9, 12, "+", 5)
        v(p, 10, "hi")
        p.e("COMP(R9, R10);")

        def end():
            v(p, 7, "mode")
            p.iconst(12, 2)
            p.e("COMP(R7, R12);")

            def loop():                       # pos = loop + (pos - hi), kept inside
                p.ipass(12, 9)
                p.iop(9, 12, "-", 10)
                v(p, 11, "loop")
                p.ipass(12, 11)
                p.iop(9, 12, "+", 9)
                p.iconst(12, -1)
                p.iop(12, 12, "+", 10)
                p.iop(9, 9, "MIN", 12)
                vs(p, "pos", 9)

            def stop():
                p.iconst(0, 0)
                vs(p, "on", 0)
            p._branch(lambda: p.r[7] == p.r[12], "EQ", loop, stop)
        p._branch(lambda: s32(p.r[9]) - s32(p.r[10]) >= 0, "GE", end,
                  lambda: vs(p, "pos", 9))

    def rev():
        p.ipass(12, 9)
        p.iop(9, 12, "-", 5)
        v(p, 10, "low")
        p.e("COMP(R9, R10);")

        def end():
            v(p, 7, "mode")
            p.iconst(12, 1)
            p.e("COMP(R7, R12);")

            def loop():                       # back to hi - 1 less what overshot
                p.ipass(12, 10)
                p.iop(9, 12, "-", 9)          # overshoot = low - pos
                v(p, 11, "hi")
                p.iconst(12, -1)
                p.iop(12, 12, "+", 11)
                p.iop(9, 12, "-", 9)
                p.iop(9, 9, "MAX", 10)        # never below the floor
                vs(p, "pos", 9)

            def stop():
                p.iconst(0, 0)
                vs(p, "on", 0)
            p._branch(lambda: p.r[7] == p.r[12], "EQ", loop, stop)
        p._branch(lambda: s32(p.r[9]) - s32(p.r[10]) < 0, "LT", end,
                  lambda: vs(p, "pos", 9))
    p._branch(lambda: s32(p.r[7]) - s32(p.r[12]) >= 0, "GE", fwd, rev)


def program(L: Layout, next_sw: int, prefix: str = "sm") -> str:
    """smp.asm: entered by PERC's tail; on to NEXT_SW (RESONATOR) when done."""
    p = Prog("emit", prefix=prefix)
    p.raw("// smp.asm -- the Digitakt II's sample machines on the DN2 (docs/sampler.md).")
    p.raw("// GENERATED by scripts/gen_smp_asm.py from dnfw.sampler (one program for this")
    p.raw("// text and its model); do not edit by hand.")
    p.raw("")
    p.raw(".SECTION/PM seg_pmco;")
    p.raw("")
    p.raw(".GLOBAL wr_smp.;")
    p.raw("wr_smp.:")
    p.iconst(0, 0)
    p.st(L.C["t"], 0)
    top = p.label("slot")
    nxt = p.label("next")
    p.place(top)
    p.ld(9, L.C["t"])
    p.lsh(12, 9, 9)
    p.lsh(13, 9, 5)
    p.iop(12, 12, "+", 13)
    p.lsh(13, 9, 4)
    p.iop(12, 12, "+", 13)
    p.lsh(13, 9, 2)
    p.iop(12, 12, "+", 13)
    p.iconst(11, PP.RECORDS)
    p.iop(12, 11, "+", 12)
    p.seti(4, 12, "record: 0x2554b8 + 0x234 t")
    PP.raw_type(p, 2)                        # the frame's type: the record's is 5 for us all
    p.ipass(0, 2)
    p.st(L.C["type"], 0)
    other = p.label("other")
    ours = [SM.TYPE_OF[n] for n in SM.ENGINED]
    body = p.label("body")
    for ty in ours:
        p.iconst(12, ty)
        p.e("COMP(R0, R12);")
        p.jump("EQ", body)
    # a sample machine with no renderer yet: its engine slot (PERC's) writes nothing, so
    # the buffer is cleared here rather than left holding an old block
    p.iconst(12, SM.FIRST_TYPE)
    p.e("COMP(R0, R12);")
    p.jump("LT", other)
    p.iconst(12, SM.FIRST_TYPE + len(SM.NAMES) - 1)
    p.e("COMP(R0, R12);")
    mute = p.label("mute")
    p.jump("LE", mute)
    p.jump("", other)
    p.place(body)
    voice(p, L)
    p.jump("", nxt)
    p.place(mute)
    silence(p, L)
    p.place(other)                           # not a sample machine: its voice off
    p.ld(9, L.C["t"])
    p.lsh(12, 9, 6)
    p.iconst(11, L.state)
    p.iop(12, 11, "+", 12)
    p.seti(2, 12)
    p.iconst(0, 0)
    vs(p, "on", 0)
    p.place(nxt)
    p.ld(0, L.C["t"])
    p.iconst(12, 1)
    p.iop(0, 12, "+", 0)
    p.st(L.C["t"], 0)
    p.iconst(12, 16)
    p.e("COMP(R0, R12);")
    p.jump("LT", top)
    p.e(f"JUMP {next_sw:#x};", "rings.asm's wr_rings, then CZ, then PING (which restores)")
    p.emit_subs()
    p.raw(".wr_smp..end:")
    p.raw("      .type wr_smp.,STT_FUNC;")
    return p.text()


def run_voice(L: Layout, read, t: int, mtype: int, mem=None):
    from ..perc.dsl import Mem
    mem = mem or Mem(read)
    p = Prog("run", mem=mem)
    p.iconst(0, mtype)
    p.st(L.C["type"], 0)
    voice(p, L, t)
    return p, mem

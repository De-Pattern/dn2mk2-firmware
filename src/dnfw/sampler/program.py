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
         last=11, low=12, fmt=13,
         # v0.15, the time machines: STRETCH's source position and two grains (phase,
         # position); WERP's segment, its sample count, and the position in it
         spos=14, ph0=15, gp0=16, ph1=17, gp1=18, seg=19, cnt=20, rel=21)
STATE_WORDS = 16
STATE_STRIDE = 128                       # v0.15: 32 words (the time machines)
SC_WORDS = ("t", "count", "tr", "trig", "sbase", "type", "rate", "gain",
            "tune", "play", "samp", "a", "b", "c", "lev", "x", "y", "n", "tmp",
            *(f"mb{k}" for k in range(16)), "mbn",     # v0.14: the mailbox's sixteen halves
            "sr", "dir", "sdir", "smode", "nseg", "nin", "nout", "acc", "gpos", "j",   # v0.15
            "xfn", "xfa", "xfi", "xfs",                # CFAD: its length, where it starts, 1/length, the shift
            # the recorder: its state (0 idle, 1 armed, 2 recording, 3 full), slot entry,
            # frames so far, their limit, source, threshold, its frames' base, the track
            "rst", "rent", "rpos", "rmax", "rsrc", "rthr", "rbase", "rchan", "rpk",
            "rseq", "rmode")                           # v0.15: the last command's sequence; armed on 0 THRES, 1 PLAY
GRAIN = 2048                              # STRETCH's grain, output samples (43 ms); two, half apart
TEMPO_OFFSET = 216                        # the frame's tempo word: BPM x 120 (docs/modulation-display.md)


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
    p.lsh(12, 9, 7)
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
        live(p, L)
        v(p, 0, "on")
        p.ifz(0, "NE", sounding_on, lambda: silence(p, L))

    def sounding_on():
        p.ld(4, C["tr"])
        v(p, 5, "rate")
        p.fop(4, 4, "*", 5)
        p.st(C["rate"], 4)
        v(p, 0, "mach")
        p.iconst(12, SM.TYPE_OF["WERP"])
        p.e("COMP(R0, R12);")

        def timed():
            p.iconst(12, SM.TYPE_OF["REPITCH"])
            p.e("COMP(R0, R12);")

            def dispatch():
                tempo(p, L)
                v(p, 0, "mach")
                p.iconst(12, SM.TYPE_OF["WERP"])
                p.e("COMP(R0, R12);")

                def not_werp():
                    p.iconst(12, SM.TYPE_OF["STRETCH"])
                    p.e("COMP(R0, R12);")

                    def repitch():                # the region in BARS, at the note's transposition
                        p.ld(4, C["sr"])
                        p.ld(5, C["tr"])
                        p.fop(4, 4, "*", 5)
                        p.st(C["rate"], 4)
                        render(p, L)
                    p._branch(lambda: p.r[0] == p.r[12], "EQ", lambda: render_stretch(p, L), repitch)
                p._branch(lambda: p.r[0] == p.r[12], "EQ", lambda: render_werp(p, L), not_werp)
            p._branch(lambda: s32(p.r[0]) <= s32(p.r[12]), "LE", dispatch, lambda: render(p, L))
        p._branch(lambda: s32(p.r[0]) >= s32(p.r[12]), "GE", timed, lambda: render(p, L))
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
        # the recorder's slots are the DSP's own, whatever count the pool has
        p.iconst(12, SM.REC_FIRST)
        p.if_(4, "GE", 12, lambda: p.iconst(0, SM.POOL_SLOTS), kind="i")
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
            p.ldi(8, 3, 1)                   # the format: 0 float32, 1 int16 (v0.14)
            vs(p, "fmt", 8)
            region(p, L)
        def inrange():
            p.ld(4, C["samp"])
            p.ifz(4, "GE", have)             # and not OFF (-1)
        p._branch(lambda: s32(p.r[4]) < s32(p.r[0]), "LT", inrange, None)
    p.e("COMP(R0, R12);")
    p._branch(lambda: p.r[0] == p.r[12], "EQ", found, None)


def oneshot_bounds(p: Prog, L: Layout) -> None:
    """lo, hi and loop from STRT, LEN and LOOP (R10: the track's frame slot base, F13: the
    sample's frames). Clobbers R4..R7, R12, R14, R15, I1."""
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


def live(p: Prog, L: Layout) -> None:
    """v0.15: ONESHOT, STRETCH and REPITCH follow STRT, LEN, LOOP and PLAY while the note
    sounds, as the DT2's do (GRID's slice and WERP's segments are taken at the note). The
    position stays where it is unless the region moved past it: then it is put at the
    region's start (forward) or end (backward); a region with nothing in it ends the note."""
    C = L.C
    v(p, 0, "mach")
    p.iconst(12, SM.TYPE_OF["GRID"])
    p.e("COMP(R0, R12);")

    def follow():
        p.ld(9, C["t"])
        PP.t146(p, 10, 9)
        v(p, 6, "frames")
        tofloat(p, 13, 6)
        oneshot_bounds(p, L)
        p.ld(9, C["t"])
        PP.t146(p, 10, 9)
        ctl(p, 4, SM.PLAY_REC, 10)
        p.lsh(4, 4, -5)
        vs(p, "mode", 4)
        v(p, 4, "lo")
        vs(p, "low", 4)
        v(p, 0, "mode")
        p.iconst(12, 1)
        p.if_(0, "EQ", 12, lambda: (v(p, 4, "loop"), vs(p, "low", 4)), kind="i")
        v(p, 4, "lo")
        v(p, 5, "hi")
        p.e("COMP(R4, R5);")

        def inside():
            v(p, 9, "pos")
            v(p, 0, "mode")
            p.iconst(12, 2)

            def fwd():
                v(p, 4, "lo")
                p.iop(9, 9, "MAX", 4)
                vs(p, "pos", 9)

            def rev():
                v(p, 5, "hi")
                p.iconst(12, -1)
                p.iop(12, 12, "+", 5)
                p.iop(9, 9, "MIN", 12)
                vs(p, "pos", 9)
            p.if_(0, "GE", 12, fwd, rev, kind="i")

        def empty():
            p.iconst(0, 0)
            vs(p, "on", 0)
        p._branch(lambda: s32(p.r[4]) - s32(p.r[5]) < 0, "LT", inside, empty)

    def not_grid():
        p.iconst(12, SM.TYPE_OF["WERP"])
        p.e("COMP(R0, R12);")
        p._branch(lambda: p.r[0] != p.r[12], "NE", follow, None)
    p._branch(lambda: p.r[0] != p.r[12], "NE", not_grid, None)


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
        oneshot_bounds(p, L)

    def whole():                              # WERP: the whole sample, segment by segment
        p.iconst(4, 0)
        vs(p, "lo", 4)
        vs(p, "loop", 4)
        v(p, 5, "frames")
        vs(p, "hi", 5)

    def not_grid():
        p.ld(0, C["type"])
        p.iconst(12, SM.TYPE_OF["WERP"])
        p.e("COMP(R0, R12);")
        p._branch(lambda: p.r[0] == p.r[12], "EQ", whole, oneshot)
    p._branch(lambda: p.r[0] == p.r[12], "EQ", grid, not_grid)
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
        # the time machines start here: STRETCH's grains at the start, half a grain apart;
        # WERP before its first segment
        v(p, 4, "pos")
        tofloat(p, 0, 4)
        vs(p, "spos", 0)
        vs(p, "gp0", 0)
        vs(p, "gp1", 0)
        p.iconst(0, 0)
        vs(p, "ph0", 0)
        vs(p, "cnt", 0)
        p.iconst(0, GRAIN // 2)
        vs(p, "ph1", 0)
        p.iconst(0, -1)
        vs(p, "seg", 0)
        p.iconst(0, 1)
        vs(p, "on", 0)
    p._branch(lambda: s32(p.r[4]) - s32(p.r[5]) < 0, "LT", go, None)


def fetch(p: Prog, d: int, k: int) -> None:
    """Fd = the latched sample's frame Rk (R10 = its base): a float32, or (fmt 1) an
    int16 / 32768, read as the half of its 32-bit word. Clobbers R8, R12, R13, I1."""
    v(p, 8, "fmt")

    def f32():
        p.lsh(12, k, 2)
        p.ipass(13, 10)
        p.iop(12, 13, "+", 12)
        p.seti(1, 12)
        p.ldi(d, 0, 1)

    def i16():
        p.lsh(12, k, 1)
        p.ipass(13, 10)
        p.iop(13, 13, "+", 12)           # the frame's byte address
        p.iconst(12, -4)
        p.iop(12, 13, "AND", 12)
        p.seti(1, 12)
        p.ldi(d, 0, 1)                   # its 32-bit word
        p.iconst(12, 2)
        p.iop(13, 13, "AND", 12)
        p.ifz(13, "EQ", lambda: p.lsh(d, d, 16))    # the low half to the top
        p.iconst(12, 0xFFFF0000 - (1 << 32))
        p.iop(d, d, "AND", 12)           # the half alone, on top: a signed 32-bit value
        p.iconst(12, -31)
        p.float_(d, d, 12)               # / 2^31 = the int16 / 32768 (no ASHIFT: the runner lacks it)
    p.ifz(8, "NE", i16, f32)


CFAD_ON = False                               # v0.14's CFAD; off with its control off the page


def crossfade_setup(p: Prog, L: Layout) -> None:
    """ONESHOT's CFAD in FWD LOOP: over the last X frames before the end (X = CFAD/127 of
    the shorter of the loop and what lies before it), the sound fades into the audio
    just before LOOP, so the wrap from the end back to LOOP is seamless. C['xfn'] = X
    (0: none), C['xfa'] = where it starts, C['xfs'] = end - LOOP, C['xfi'] = 1 / X."""
    C = L.C
    p.fconst(0, 0.0)
    p.st(C["xfn"], 0)
    v(p, 0, "mach")
    p.iconst(12, SM.TYPE_OF["ONESHOT"])
    p.e("COMP(R0, R12);")

    def oneshot():
        v(p, 0, "mode")
        p.iconst(12, 2)

        def fwdl():
            p.ld(9, C["t"])
            PP.t146(p, 10, 9)
            ctl(p, 4, SM.CFAD_REC, 10)       # 0..127
            v(p, 5, "hi")
            v(p, 6, "loop")
            p.ipass(12, 5)
            p.iop(7, 12, "-", 6)             # hi - loop
            p.iop(8, 6, "MIN", 7)            # min(loop, hi - loop): room on both sides
            tofloat(p, 8, 8)
            tofloat(p, 4, 4, 1.0 / 127.0)
            p.fop(8, 8, "*", 4)              # X
            p.fconst(12, 1.0)

            def some():
                p.st(C["xfn"], 8)
                tofloat(p, 7, 7)
                p.st(C["xfs"], 7)
                v(p, 5, "hi")
                tofloat(p, 5, 5)
                p.fop(5, 5, "-", 8)
                p.st(C["xfa"], 5)
                p.fpass(9, 8)
                PM.recip(p, 10, 9)
                p.st(C["xfi"], 10)
            p.if_(8, "GE", 12, some)         # at least a frame
        p.if_(0, "EQ", 12, fwdl, kind="i")
    p._branch(lambda: p.r[0] == p.r[12], "EQ", oneshot, None)


def render(p: Prog, L: Layout) -> None:
    """32 samples of the latched region at the block's rate, linear interpolation."""
    C = L.C
    if CFAD_ON:
        crossfade_setup(p, L)
    else:                                     # v0.15: the DT2's ONESHOT has no CFAD control
        p.fconst(0, 0.0)
        p.st(C["xfn"], 0)
    buffer(p, L)

    def sample():
        v(p, 0, "on")

        def play():
            v(p, 9, "pos")
            v(p, 10, "base")
            fetch(p, 0, 9)                   # s0 = pool[pos]
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
            v(p, 10, "base")
            fetch(p, 1, 11)                  # s1
            v(p, 2, "frac")
            p.fop(1, 1, "-", 0)
            p.fop(1, 1, "*", 2)
            p.fop(0, 0, "+", 1)              # s0 + (s1 - s0) frac
            p.ld(3, C["xfn"])
            p.fconst(12, 0.0)

            def xfade():                     # inside the crossfade? g = (pos - start) / X
                v(p, 9, "pos")
                tofloat(p, 5, 9)
                v(p, 2, "frac")
                p.fop(5, 5, "+", 2)
                p.ld(6, C["xfa"])
                p.fop(7, 5, "-", 6)

                def inside():
                    p.st(C["acc"], 0)
                    p.ld(6, C["xfi"])
                    p.fop(7, 7, "*", 6)
                    p.st(C["gpos"], 7)       # g
                    p.ld(6, C["xfs"])
                    p.fop(5, 5, "-", 6)      # the same distance before LOOP
                    read_at(p, L, 1, 5)
                    p.ld(0, C["acc"])
                    p.ld(7, C["gpos"])
                    p.fop(1, 1, "-", 0)
                    p.fop(1, 1, "*", 7)
                    p.fop(0, 0, "+", 1)      # s + (s' - s) g
                p.fconst(12, 0.0)
                p.if_(7, "GE", 12, inside)
            p.if_(3, "GT", 12, xfade)
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


def tempo(p: Prog, L: Layout) -> None:
    """C['sr'] = the region's frames over BARS at the tempo, in output samples: the
    source frames a sample. BARS (0..100) picks 1/8 .. 16 bars; the tempo is the frame's
    word at 216, BPM x 120 (120 BPM if it reads 0). Also C['dir'] (+1 or -1, PLAY) and,
    for WERP, C['nseg'], C['nin'], C['nout'] and C['smode']. Clobbers R0-R15, I1, I12."""
    C = L.C
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 4, SM.BARS_REC, 10)               # 0..100 -> 0..7
    p.iconst(5, -3)
    for k in SM.BARS_STEPS:
        p.iconst(12, k)
        p.if_(4, "GE", 12, lambda: (p.iconst(12, 1), p.iop(5, 12, "+", 5)), kind="i")
    p.iconst(8, 1)
    p.float_(8, 8, 5)                        # bars = 2^(idx - 3)
    p.fconst(12, 4 * 60 * 48000 * 120.0)
    p.fop(8, 8, "*", 12)                     # bars x 1.3824e9
    p.iconst(10, 0)
    PP.half(p, 6, TEMPO_OFFSET, 10)
    p.ifz(6, "EQ", lambda: p.iconst(6, 120 * 120))
    tofloat(p, 7, 6)
    PM.recip(p, 9, 7)
    p.fop(8, 8, "*", 9)                      # the output samples BARS lasts
    PM.recip(p, 9, 8)
    v(p, 4, "hi")
    v(p, 5, "lo")
    p.ipass(12, 4)
    p.iop(4, 12, "-", 5)
    tofloat(p, 6, 4)
    p.fop(6, 6, "*", 9)
    p.st(C["sr"], 6)
    v(p, 0, "mode")
    p.iconst(1, 1)
    p.iconst(12, 2)
    p.if_(0, "LT", 12, lambda: p.iconst(1, -1), kind="i")
    p.st(C["dir"], 1)
    # WERP: SEG (0..120) -> 128 >> (v * 8 // 121) segments, MODE (0..127) -> 0..3
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 4, SM.SEG_REC, 10)
    p.iconst(5, 7)
    for k in SM.SEG_STEPS:
        p.iconst(12, k)
        p.if_(4, "GE", 12, lambda: (p.iconst(12, -1), p.iop(5, 12, "+", 5)), kind="i")
    p.iconst(6, 1)
    PP._shift_by(p, 6, 5)                    # nseg = 2^(7 - idx)
    p.st(C["nseg"], 6)
    p.iconst(12, 0)
    p.iop(12, 12, "-", 5)                    # -log2(nseg)
    p.iconst(13, 1)
    p.float_(9, 13, 12)                      # 1 / nseg, exactly
    v(p, 7, "frames")
    tofloat(p, 7, 7)
    p.fop(7, 7, "*", 9)
    p.trunc(7, 7)                            # nin = frames / nseg
    p.iconst(12, 1)
    p.iop(7, 7, "MAX", 12)
    p.st(C["nin"], 7)
    tofloat(p, 8, 7)
    p.ld(9, C["sr"])
    PM.recip(p, 10, 9)
    p.fop(8, 8, "*", 10)                     # nout = nin / sr
    p.trunc(8, 8)
    p.iconst(12, 1)
    p.iop(8, 8, "MAX", 12)
    p.st(C["nout"], 8)
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 4, SM.MODE_REC, 10)
    p.lsh(4, 4, -5)
    p.st(C["smode"], 4)


def read_at(p: Prog, L: Layout, d: int, x: int) -> None:
    """Fd = the latched sample at frame position Fx (float), linear, held inside
    0 .. frames - 1. Clobbers R0-R13, I1."""
    C = L.C
    p.fpass(11, x)
    p.trunc(9, 11)
    p.iconst(12, 0)
    p.iop(9, 9, "MAX", 12)
    v(p, 6, "frames")
    p.iconst(12, -2)
    p.iop(12, 12, "+", 6)
    p.iconst(13, 0)
    p.iop(12, 12, "MAX", 13)
    p.iop(9, 9, "MIN", 12)                   # i in 0 .. frames - 2
    tofloat(p, 2, 9)
    p.fop(2, 11, "-", 2)                     # frac (may leave 0..1 at the ends: held)
    p.fconst(12, 0.0)
    p.fop(2, 2, "MAX", 12)
    p.fconst(12, 1.0)
    p.fop(2, 2, "MIN", 12)
    p.st(C["x"], 2)
    v(p, 10, "base")
    fetch(p, 3, 9)
    p.iconst(12, 1)
    p.iop(11, 12, "+", 9)
    v(p, 10, "base")
    fetch(p, 4, 11)
    p.ld(2, C["x"])
    p.fop(4, 4, "-", 3)
    p.fop(4, 4, "*", 2)
    p.fop(d, 3, "+", 4)


def render_stretch(p: Prog, L: Layout) -> None:
    """STRETCH: two grains of GRAIN samples, half a grain apart, each a triangle window
    (the two sum to 1), each reading from where the source position was when it began,
    at the note's pitch; the source position moves at BARS' rate (C['sr']). PLAY as
    ONESHOT's: the source position stops, or loops, at the region's end."""
    C = L.C
    buffer(p, L)

    def sample():
        v(p, 0, "on")

        def play():
            p.fconst(0, 0.0)
            p.st(C["acc"], 0)
            for j in (0, 1):
                ph, gp = f"ph{j}", f"gp{j}"
                v(p, 0, gp)
                read_at(p, L, 5, 0)
                v(p, 6, ph)
                tofloat(p, 7, 6, 2.0 / GRAIN)
                p.fconst(12, 1.0)
                p.fop(7, 7, "-", 12)
                p.fconst(12, 0.0)
                p.fop(8, 12, "-", 7)
                p.fop(7, 7, "MAX", 8)                 # |2 ph / G - 1|
                p.fconst(12, 1.0)
                p.fop(7, 12, "-", 7)                  # 1 - |2 ph / G - 1|
                p.fop(5, 5, "*", 7)
                p.ld(8, C["acc"])
                p.fop(8, 8, "+", 5)
                p.st(C["acc"], 8)
                # on: phase + 1, position + pitch (in the play direction)
                v(p, 6, ph)
                p.iconst(12, 1)
                p.iop(6, 12, "+", 6)
                v(p, 0, gp)
                p.ld(1, C["rate"])
                p.ld(9, C["dir"])
                p.ifz(9, "LT", lambda: (p.fconst(12, 0.0), p.fop(1, 12, "-", 1)))
                p.fop(0, 0, "+", 1)
                vs(p, gp, 0)
                vs(p, ph, 6)
                p.iconst(12, GRAIN)

                def restart(ph=ph, gp=gp):
                    p.iconst(6, 0)
                    vs(p, ph, 6)
                    v(p, 0, "spos")
                    vs(p, gp, 0)
                p.if_(6, "GE", 12, restart, kind="i")
            p.ld(0, C["acc"])
            p.ld(3, C["lev"])
            p.fop(0, 0, "*", 3)
            p.stpost(4, 0)
            source_step(p, L)

        def rest():
            p.iconst(6, 0)
            p.stpost(4, 6)
        p.ifz(0, "NE", play, rest)
    p.loop(C["count"], 32, sample)


def source_step(p: Prog, L: Layout) -> None:
    """STRETCH's source position: + sr in the play direction; at the region's end it
    loops (FWD LOOP from LOOP, REV LOOP back to the top) or the voice stops."""
    C = L.C
    v(p, 0, "spos")
    p.ld(1, C["sr"])
    p.ld(9, C["dir"])

    def fwd():
        p.fop(0, 0, "+", 1)
        v(p, 5, "hi")
        tofloat(p, 2, 5)

        def over():
            v(p, 7, "mode")
            p.iconst(12, 2)

            def lp():
                v(p, 6, "loop")
                tofloat(p, 3, 6)
                p.fop(4, 2, "-", 3)               # the loop's length
                p.fop(0, 0, "-", 4)
            p.if_(7, "EQ", 12, lp, lambda: (p.iconst(6, 0), vs(p, "on", 6)), kind="i")
        p.if_(0, "GE", 2, over)

    def rev():
        p.fop(0, 0, "-", 1)
        v(p, 5, "low")
        tofloat(p, 2, 5)

        def under():
            v(p, 7, "mode")
            p.iconst(12, 1)

            def lp():
                v(p, 6, "hi")
                tofloat(p, 3, 6)
                p.fop(4, 3, "-", 2)
                p.fop(0, 0, "+", 4)
            p.if_(7, "EQ", 12, lp, lambda: (p.iconst(6, 0), vs(p, "on", 6)), kind="i")
        p.if_(0, "LT", 2, under)
    p.ifz(9, "GT", fwd, rev)
    vs(p, "spos", 0)


def render_werp(p: Prog, L: Layout) -> None:
    """WERP: the sample in NSEG equal segments; segment k starts at output sample k NOUT
    (NOUT = NIN / sr: the whole lasts BARS), in the play direction; each plays at the
    note's pitch in MODE (REV, REV LOOP, FWD LOOP, FWD) until the next one starts. FWD and
    REV stop after the last segment; the loop modes start again."""
    C = L.C
    buffer(p, L)

    def sample():
        v(p, 0, "on")

        def play():
            v(p, 5, "cnt")
            p.ld(6, C["nout"])
            v(p, 7, "seg")

            def next_seg():
                p.iconst(5, 0)
                vs(p, "cnt", 5)
                p.ld(9, C["dir"])
                v(p, 7, "seg")
                p.ld(6, C["nseg"])

                def first():                       # -1: the first segment of the direction
                    p.iconst(7, 0)
                    p.ifz(9, "LT", lambda: (p.iconst(12, -1), p.iop(7, 12, "+", 6)))

                def step():
                    p.ipass(12, 7)
                    p.iop(7, 12, "+", 9)
                p.ifz(7, "LT", first, step)
                # past either end: loop modes start again, the others stop
                p.iconst(8, 0)
                p.if_(7, "GE", 6, lambda: p.iconst(8, 1), kind="i")
                p.ifz(7, "LT", lambda: p.iconst(8, 1))

                def wrap():
                    v(p, 0, "mode")
                    p.iconst(12, 1)

                    def again():
                        p.iconst(7, 0)
                        p.ifz(9, "LT", lambda: (p.iconst(12, -1), p.iop(7, 12, "+", 6)))
                    p.ipass(10, 0)
                    p.iconst(12, 1)
                    p.e("COMP(R10, R12);")
                    p._branch(lambda: p.r[10] == p.r[12], "EQ", again,
                              lambda: (p.iconst(12, 2), p.if_(0, "EQ", 12, again,
                                                               lambda: (p.iconst(6, 0), vs(p, "on", 6), p.iconst(7, 0)),
                                                               kind="i")))
                p.ifz(8, "NE", wrap)
                vs(p, "seg", 7)
                # the segment's own start: 0 forward, its end backward (MODE)
                p.fconst(0, 0.0)
                p.ld(4, C["smode"])
                p.iconst(12, 2)

                def back():
                    p.ld(5, C["nin"])
                    p.iconst(12, -1)
                    p.iop(5, 12, "+", 5)
                    tofloat(p, 0, 5)
                p.if_(4, "LT", 12, back, kind="i")
                vs(p, "rel", 0)
            p.ifz(7, "LT", next_seg,
                  lambda: p.if_(5, "GE", 6, next_seg, kind="i"))
            v(p, 0, "on")

            def sounding_seg():
                # inside the segment? (FWD and REV play it once)
                v(p, 0, "rel")
                p.ld(5, C["nin"])
                tofloat(p, 1, 5)
                p.fconst(2, 0.0)
                p.iconst(6, 1)
                p.if_(0, "LT", 2, lambda: p.iconst(6, 0))
                p.if_(0, "GE", 1, lambda: p.iconst(6, 0))

                def inside():
                    v(p, 7, "seg")
                    p.ld(5, C["nin"])
                    # seg * nin by doubling: nin is frames / nseg, seg < nseg <= 128
                    tofloat(p, 3, 7)
                    tofloat(p, 4, 5)
                    p.fop(3, 3, "*", 4)
                    v(p, 0, "rel")
                    p.fop(0, 0, "+", 3)
                    read_at(p, L, 5, 0)
                    p.ld(3, C["lev"])
                    p.fop(5, 5, "*", 3)
                    p.st(C["acc"], 5)

                p.fconst(0, 0.0)
                p.st(C["acc"], 0)
                p.ifz(6, "NE", inside)
                # on in the segment: rel +- pitch, wrapped in the loop modes
                v(p, 0, "rel")
                p.ld(1, C["rate"])
                p.ld(4, C["smode"])
                p.iconst(12, 2)
                p.if_(4, "LT", 12, lambda: (p.fconst(12, 0.0), p.fop(1, 12, "-", 1)), kind="i")
                p.fop(0, 0, "+", 1)
                p.ld(5, C["nin"])
                tofloat(p, 2, 5)

                def fwd_loop():
                    p.if_(0, "GE", 2, lambda: p.fop(0, 0, "-", 2))

                def rev_loop():
                    p.fconst(3, 0.0)
                    p.if_(0, "LT", 3, lambda: p.fop(0, 0, "+", 2))
                p.iconst(12, 2)
                p.if_(4, "EQ", 12, fwd_loop, kind="i")
                p.iconst(12, 1)
                p.if_(4, "EQ", 12, rev_loop, kind="i")
                vs(p, "rel", 0)
                v(p, 5, "cnt")
                p.iconst(12, 1)
                p.iop(5, 12, "+", 5)
                vs(p, "cnt", 5)
                p.ld(0, C["acc"])
                p.stpost(4, 0)

            p.ifz(0, "NE", sounding_seg, lambda: (p.iconst(6, 0), p.stpost(4, 6)))

        def rest():
            p.iconst(6, 0)
            p.stpost(4, 6)
        p.ifz(0, "NE", play, rest)
    p.loop(C["count"], 32, sample)


def recorder(p: Prog, L: Layout) -> None:
    """The recorder (docs/sampler.md, v0.15). The ColdFire drives it with commands it writes,
    through the sample link, into the pool's command block (SM.CMD_OFFSET): sequence,
    command, source, channel, threshold, and dest << 24 | frames. A new sequence acts:
    ARM empties the slot and waits for the block's peak to reach the threshold; NOW
    empties it and records at once; STOP ends a recording (or cancels an arm); every
    command sets the source and channel the peak is measured on (MONITOR only that).
    Sources: IN (the codec's input as the engine converts it, 0x268538), MAIN (the last
    block's mix, 0x268438), TRK1..16 (track t's audio, panned, the last block's: the
    buffer Overbridge sends, SM.TRK_BUF + 0x100 t); channels MONO L+R, L, R. Recording
    appends 32 frames a block as int16 to the slot (SAMP 124..127, 2 MB each) and keeps
    its directory entry current, so it plays at once; it stops at the frame count. Each
    block the state, the command echoed, the frames so far and the peak go to the
    ColdFire in the SPI reply's unused tail (SM.REPLY_TAIL), in both reply pages."""
    C = L.C
    cmd = L.pool + SM.CMD_OFFSET
    p.ld(0, cmd)                              # the command's sequence
    p.ld(1, C["rseq"])

    def new_command():
        p.ld(0, cmd)
        p.st(C["rseq"], 0)
        p.ld(4, cmd + 8)                      # source: 0 IN, 1 MAIN, 2 + t a track
        p.iconst(12, 0)
        p.iop(4, 4, "MAX", 12)
        p.iconst(12, 17)
        p.iop(4, 4, "MIN", 12)
        p.st(C["rsrc"], 4)
        p.ld(4, cmd + 12)                     # channel: 0 L+R, 1 L, 2 R
        p.iconst(12, 0)
        p.iop(4, 4, "MAX", 12)
        p.iconst(12, 2)
        p.iop(4, 4, "MIN", 12)
        p.st(C["rchan"], 4)
        p.ld(4, cmd + 16)                     # the threshold, 0..32767 for a peak 0..1
        tofloat(p, 5, 4, 1.0 / 32767.0)
        p.st(C["rthr"], 5)
        p.ld(2, cmd + 4)                      # the command

        def start(state):
            def body():                       # the slot, emptied
                p.ld(4, cmd + 20)
                p.lsh(5, 4, -24)              # dest 0..3
                p.iconst(12, 3)
                p.iop(5, 5, "AND", 12)
                p.iconst(12, 0x00FFFFFF)
                p.iop(6, 4, "AND", 12)        # frames: 32 .. the slot's whole length
                p.iconst(12, 32)
                p.iop(6, 6, "MAX", 12)
                p.iconst(12, SM.REC_FRAMES)
                p.iop(6, 6, "MIN", 12)
                p.st(C["rmax"], 6)
                p.lsh(6, 5, 21)               # 2 MB a slot
                p.iconst(13, L.pool + SM.REC_OFFSET)
                p.iop(6, 13, "+", 6)
                p.st(C["rbase"], 6)
                p.iconst(13, SM.REC_FIRST)
                p.iop(5, 13, "+", 5)
                p.lsh(5, 5, 4)
                p.iconst(13, L.pool + 8)
                p.iop(5, 13, "+", 5)
                p.st(C["rent"], 5)
                p.seti(1, 5)
                p.sti(0, 1, 6)                # address
                p.iconst(7, 0)
                p.sti(1, 1, 7)                # frames: none yet
                p.fconst(7, 1.0)
                p.sti(2, 1, 7)                # rate 1
                p.iconst(7, SM.FMT_I16)
                p.sti(3, 1, 7)
                p.iconst(7, 0)
                p.st(C["rpos"], 7)
                p.iconst(7, state)
                p.st(C["rst"], 7)
            return body
        p.iconst(12, SM.CMD_ARM)
        p.if_(2, "EQ", 12, lambda: (start(1)(), p.iconst(7, 0), p.st(C["rmode"], 7)), kind="i")
        p.ld(2, cmd + 4)
        p.iconst(12, SM.CMD_ARM_PLAY)
        p.if_(2, "EQ", 12, lambda: (start(1)(), p.iconst(7, 1), p.st(C["rmode"], 7)), kind="i")
        p.ld(2, cmd + 4)
        p.iconst(12, SM.CMD_NOW)
        p.if_(2, "EQ", 12, start(2), kind="i")
        p.ld(2, cmd + 4)
        p.iconst(12, SM.CMD_STOP)

        def stop():
            p.ld(3, C["rst"])
            p.iconst(12, 1)
            p.if_(3, "EQ", 12, lambda: (p.iconst(7, 0), p.st(C["rst"], 7)), kind="i")
            p.ld(3, C["rst"])
            p.iconst(12, 2)
            p.if_(3, "EQ", 12, lambda: (p.iconst(7, 3), p.st(C["rst"], 7)), kind="i")
        p.if_(2, "EQ", 12, stop, kind="i")
    p.e("COMP(R0, R1);")
    p._branch(lambda: p.r[0] != p.r[1], "NE", new_command, None)

    # the source's block, mono, staged as floats; and its peak (for the meter)
    p.fconst(0, 0.0)
    p.st(C["rpk"], 0)
    p.ld(8, C["rsrc"])                        # its L (R at + 0x80)
    p.iconst(9, SM.IN_BUF)
    p.iconst(12, 1)
    p.if_(8, "EQ", 12, lambda: p.iconst(9, SM.MIX_BUF), kind="i")
    p.iconst(12, 2)

    def track():
        # track t is in the slot its routing half says (s16 at TRK_ROUTE + 2t, 0..15;
        # the ColdFire's slot map, normally t): the panned block 0x1c244d left there
        p.ld(8, C["rsrc"])
        p.iconst(12, -2)
        p.iop(8, 12, "+", 8)                  # t
        p.lsh(9, 8, -1)
        p.lsh(9, 9, 2)
        p.iconst(12, SM.TRK_ROUTE)
        p.iop(9, 12, "+", 9)
        p.seti(1, 9)
        p.ldi(10, 0, 1)                       # the word holding t's half
        p.iconst(12, 1)
        p.iop(8, 8, "AND", 12)
        p.ifz(8, "NE", lambda: p.lsh(10, 10, -16))
        p.iconst(12, 0xFFFF)
        p.iop(10, 10, "AND", 12)
        p.iconst(12, 15)
        p.if_(10, "GT", 12, lambda: p.iconst(10, 0), kind="i")   # negative or past 15: slot 0
        p.lsh(10, 10, 8)                      # 0x100 a slot
        p.iconst(12, SM.TRK_BUF)
        p.iop(9, 12, "+", 10)
    p.if_(8, "GE", 12, track, kind="i")
    p.st(C["a"], 9)
    p.iconst(6, 0)
    p.st(C["x"], 6)

    def frame():
        p.ld(6, C["x"])
        p.lsh(7, 6, 2)
        p.ld(9, C["a"])
        p.ipass(12, 9)
        p.iop(9, 12, "+", 7)
        p.seti(1, 9)
        p.ldi(3, 0, 1)                        # L
        p.ldi(4, 32, 1)                       # R
        p.ld(8, C["rchan"])
        p.iconst(12, 1)
        p.if_(8, "EQ", 12, lambda: p.fpass(4, 3), kind="i")
        p.iconst(12, 2)
        p.if_(8, "EQ", 12, lambda: p.fpass(3, 4), kind="i")
        p.fop(3, 3, "+", 4)
        p.fconst(12, 0.5)
        p.fop(3, 3, "*", 12)                  # mono
        p.ld(8, C["rsrc"])
        p.iconst(12, 2)
        p.if_(8, "GE", 12, lambda: (p.fconst(12, 1.0 / SM.TRK_GAIN), p.fop(3, 3, "*", 12)),
              kind="i")                       # a track's slot carries it x TRK_GAIN
        p.fconst(12, 0.999969)
        p.fop(3, 3, "MIN", 12)
        p.fconst(12, -1.0)
        p.fop(3, 3, "MAX", 12)
        p.ld(5, C["rpk"])                     # the block's peak
        p.fconst(12, 0.0)
        p.fop(6, 12, "-", 3)
        p.fop(6, 6, "MAX", 3)
        p.fop(5, 5, "MAX", 6)
        p.st(C["rpk"], 5)
        p.ld(6, C["x"])
        p.lsh(7, 6, 2)
        p.iconst(12, SM.REC_STAGE)
        p.iop(7, 12, "+", 7)
        p.seti(1, 7)
        p.sti(0, 1, 3)                        # staged as floats
        p.iconst(12, 1)
        p.iop(6, 12, "+", 6)
        p.st(C["x"], 6)
    p.loop(C["n"], 32, frame)

    p.ld(1, C["rst"])
    p.iconst(12, 1)

    def armed():
        p.ld(7, C["rmode"])

        def on_thres():                       # the peak reached the threshold: record
            p.ld(5, C["rpk"])
            p.ld(6, C["rthr"])
            p.if_(5, "GE", 6, lambda: (p.iconst(0, 2), p.st(C["rst"], 0)))

        def on_play():                        # R.STRT PLAY: the first note any track plays
            p.ld(5, PP.TRIG_WORD)
            p.lsh(5, 5, -16)
            p.ifz(5, "NE", lambda: (p.iconst(0, 2), p.st(C["rst"], 0)))
        p.ifz(7, "EQ", on_thres, on_play)
    p.if_(1, "EQ", 12, armed, kind="i")
    p.ld(1, C["rst"])
    p.iconst(12, 2)

    def record():                             # 32 frames as int16, two a word
        p.ld(5, C["rpos"])
        p.lsh(5, 5, 1)
        p.ld(6, C["rbase"])
        p.ipass(12, 6)
        p.iop(5, 12, "+", 5)
        p.seti(4, 5)
        p.iconst(6, 0)
        p.st(C["x"], 6)

        def pair():
            p.ld(6, C["x"])
            p.lsh(7, 6, 3)
            p.iconst(12, SM.REC_STAGE)
            p.iop(7, 12, "+", 7)
            p.seti(1, 7)
            p.ldi(3, 0, 1)
            p.ldi(4, 1, 1)
            p.fconst(12, 32768.0)
            p.fop(3, 3, "*", 12)
            p.fop(4, 4, "*", 12)
            p.trunc(8, 3)
            p.trunc(9, 4)
            p.iconst(12, 0xFFFF)
            p.iop(8, 8, "AND", 12)
            p.lsh(9, 9, 16)
            p.ipass(12, 9)
            p.iop(8, 12, "+", 8)
            p.stpost(4, 8)
            p.iconst(12, 1)
            p.iop(6, 12, "+", 6)
            p.st(C["x"], 6)
        p.loop(C["n"], 16, pair)
        p.ld(5, C["rpos"])
        p.iconst(12, 32)
        p.iop(5, 12, "+", 5)
        p.st(C["rpos"], 5)
        p.ld(6, C["rent"])
        p.seti(1, 6)
        p.sti(1, 1, 5)                        # the slot plays what is there
        p.ld(6, C["rmax"])
        p.if_(5, "GE", 6, lambda: (p.iconst(0, 3), p.st(C["rst"], 0)), kind="i")
    p.if_(1, "EQ", 12, record, kind="i")
    status(p, L)


def status(p: Prog, L: Layout) -> None:
    """The recorder's state to the ColdFire: 16 halves in the SPI reply's tail, a 32-bit
    store putting its low half first (docs/sampler.md): STATUS_MAGIC | state, the last
    command's sequence, frames / 32, the peak x 32767, the link's packet count, ten
    zeros, and a check (0x1D0F + the fifteen, 16 bits). Into both reply pages."""
    C = L.C
    p.ld(0, C["rst"])
    p.iconst(12, SM.STATUS_MAGIC)
    p.iop(0, 12, "+", 0)                      # h0
    p.ld(1, C["rseq"])
    p.iconst(12, 0xFFFF)
    p.iop(1, 1, "AND", 12)                    # h1
    p.ld(2, C["rpos"])
    p.lsh(2, 2, -5)
    p.iop(2, 2, "AND", 12)                    # h2
    p.ld(5, C["rpk"])
    p.fconst(12, 32767.0)
    p.fop(5, 5, "*", 12)
    p.trunc(3, 5)
    p.iconst(12, 0xFFFF)
    p.iop(3, 3, "AND", 12)                    # h3
    p.ld(4, C["mbn"])
    p.iop(4, 4, "AND", 12)                    # h4
    p.iconst(5, SM.LINK_SEED)                 # the check
    for k in range(5):
        p.ipass(12, 5)
        p.iop(5, 12, "+", k)
    p.iconst(12, 0xFFFF)
    p.iop(5, 5, "AND", 12)                    # h15
    p.lsh(6, 1, 16)
    p.ipass(12, 6)
    p.iop(6, 12, "+", 0)                      # h0 | h1 << 16
    p.lsh(7, 3, 16)
    p.ipass(12, 7)
    p.iop(7, 12, "+", 2)                      # h2 | h3 << 16
    p.lsh(8, 5, 16)                           # h14 (0) | h15 << 16
    p.iconst(9, 0)
    for page in SM.REPLY_PAGES:
        a = page + SM.REPLY_TAIL
        p.st(a, 6)
        p.st(a + 4, 7)
        p.st(a + 8, 4)                        # h4 | 0
        for k in range(3, 7):
            p.st(a + 4 * k, 9)
        p.st(a + 28, 8)


def mailbox(p: Prog, L: Layout) -> None:
    """The sample link (v0.14, docs/sampler.md): sixteen 16-bit words the ColdFire puts in
    the frame at 2650 + 2k (where stock carries a per-track array the DSP never reads):
    MAGIC, a word offset into the pool (low, high), six 32-bit words (low half first),
    and a check (0x1D0F + the sum of the fifteen before it, 16 bits). A packet that
    checks out writes its six words at pool + 4 offset, offset < POOL_WORDS - 6; anything
    else -- stock's zeros included -- writes nothing. Counts the packets written."""
    C = L.C
    p.iconst(10, 0)
    for k in range(16):
        PP.half(p, 2, SM.LINK_OFFSET + 2 * k, 10)
        p.st(C[f"mb{k}"], 2)
    p.ld(2, C["mb0"])
    p.iconst(12, SM.LINK_MAGIC)
    p.e("COMP(R2, R12);")

    def magic():
        p.iconst(4, SM.LINK_SEED)
        for k in range(15):
            p.ld(2, C[f"mb{k}"])
            p.ipass(12, 4)
            p.iop(4, 12, "+", 2)
        p.iconst(12, 0xFFFF)
        p.iop(4, 4, "AND", 12)
        p.ld(2, C["mb15"])
        p.e("COMP(R4, R2);")

        def checked():
            p.ld(5, C["mb2"])                # the offset's high half: < POOL_WORDS >> 16
            p.iconst(12, SM.POOL_WORDS >> 16)
            p.e("COMP(R5, R12);")

            def small():
                p.lsh(5, 5, 16)
                p.ld(6, C["mb1"])
                p.ipass(12, 5)
                p.iop(5, 12, "+", 6)         # offset, words
                p.iconst(12, SM.POOL_WORDS - 6)
                p.e("COMP(R5, R12);")

                def write():
                    p.lsh(5, 5, 2)
                    p.iconst(12, L.pool)
                    p.iop(5, 12, "+", 5)
                    p.seti(4, 5)
                    for j in range(6):
                        p.ld(6, C[f"mb{4 + 2 * j}"])
                        p.lsh(6, 6, 16)
                        p.ld(7, C[f"mb{3 + 2 * j}"])
                        p.ipass(12, 6)
                        p.iop(6, 12, "+", 7)
                        p.stpost(4, 6)
                    p.ld(6, C["mbn"])
                    p.iconst(12, 1)
                    p.iop(6, 12, "+", 6)
                    p.st(C["mbn"], 6)

                def inside():
                    # not over the recorder's four directory entries (slots 123..126), which
                    # are the DSP's own: a packet with any word in them writes nothing
                    lo = (8 + 16 * SM.REC_FIRST) // 4
                    hi = (8 + 16 * (SM.REC_FIRST + SM.REC_SLOTS)) // 4
                    p.iconst(12, lo - 6)
                    p.e("COMP(R5, R12);")

                    def above():
                        p.iconst(12, hi)
                        p.e("COMP(R5, R12);")
                        p._branch(lambda: s32(p.r[5]) >= s32(p.r[12]), "GE", write, None)
                    p._branch(lambda: s32(p.r[5]) <= s32(p.r[12]), "LE", write, above)
                p._branch(lambda: s32(p.r[5]) <= s32(p.r[12]), "LE", inside, None)
            p._branch(lambda: s32(p.r[5]) < s32(p.r[12]), "LT", small, None)
        p._branch(lambda: p.r[4] == p.r[2], "EQ", checked, None)
    p._branch(lambda: p.r[2] == p.r[12], "EQ", magic, None)


def link_packet(offset: int, words) -> list[int]:
    """the sixteen 16-bit words of one packet (what the ColdFire's feeder writes)"""
    words = list(words) + [0] * (6 - len(words))
    h = [SM.LINK_MAGIC, offset & 0xFFFF, (offset >> 16) & 0xFFFF]
    for w in words:
        h += [w & 0xFFFF, (w >> 16) & 0xFFFF]
    h.append((SM.LINK_SEED + sum(h)) & 0xFFFF)
    return h


def run_recorder(L: Layout, mem):
    p = Prog("run", mem=mem)
    recorder(p, L)
    return p


def run_mailbox(L: Layout, mem):
    p = Prog("run", mem=mem)
    mailbox(p, L)
    return p


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
    mailbox(p, L)
    recorder(p, L)
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
    p.lsh(12, 9, 7)
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

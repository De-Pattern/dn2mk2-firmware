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
         spos=14, ph0=15, gp0=16, ph1=17, gp1=18, seg=19, wacc=20, rel=21,
         # v0.18: the block's end fade (the DT2's: a voice that ends inside a block fades
         # over it), and STRETCH's jump (source frames, signed by the play direction)
         fade=22, fg=23, dg=24, jj=25,
         fixed=26,                       # GRID's NOTE mode: the note picks the slice, not the pitch
         walive=27,                      # WERP: its run of segments goes on (V['on'] is its segment)
         fin=28, fig=29,                 # the note's first block fades in (the DT2's 0x17c), its gain
         nsl=30,                         # v0.19: the sample's slices (its entry's format word, bits 8..15)
         sla=31)                         # v0.23: its slice table's address when edited on the instrument (0: after its frames)
STATE_WORDS = 16
STATE_STRIDE = 128                       # v0.15: 32 words (the time machines)
SC_WORDS = ("t", "count", "tr", "trig", "sbase", "type", "rate", "kill",
            "tune", "play", "samp", "a", "b", "c", "lev", "x", "y", "n", "tmp",
            "pph", "pix", "pbad", "pres", "pcnt",   # v0.22: the RAM check (probe); before, v0.14..v0.19's mailbox
            # v0.25: the recorder's preview (pvmix): its next word's address, the words left,
            # the loop's count and its save area (R0..R3, R12, R13, I1, ASTAT)
            "pva", "pvn", "pvk", "pvs0", "pvs1", "pvs2", "pvs3", "pvs12", "pvs13", "pvsi", "pvsa",
            "spare11",
            "sr", "dir", "add", "smode", "nseg", "nin", "nout", "acc", "pass", "lp",   # v0.15; v0.18 kill, add, pass, lp
            "xfn", "xfa", "xfi", "xfs",                # CFAD: its length, where it starts, 1/length, the shift
            # the recorder: its state (0 idle, 1 armed, 2 recording, 3 full), slot entry,
            # frames so far, their limit, source, threshold, its frames' base, the track
            "rst", "rent", "rpos", "rmax", "rsrc", "rthr", "rbase", "rchan", "rpk",
            "rseq", "rmode",
            "tr0", "note", "segnext")                  # v0.18: TUNE's transposition alone; the note; WERP's boundary                           # v0.15: the last command's sequence; armed on 0 THRES, 1 PLAY
GRAIN = 2048                              # STRETCH's grain, output samples (43 ms); two, half apart
TEMPO_OFFSET = 216                        # the frame's tempo word: BPM x 120 (docs/modulation-display.md)


class Layout:
    def __init__(self, state: int, scratch: int, pool: int, exp2: int, tables: int = 0, dec: int = 0):
        self.state, self.pool, self.exp2, self.dec = state, pool, exp2, dec
        self.C = {w: scratch + 4 * k for k, w in enumerate(SC_WORDS)}
        # PM.exp2 reads the table through L.T; v0.18: the DT2 reader's tables (tables_bytes)
        self.T = {"exp2": exp2, "poly": tables, "decim": tables + 4 * POLY_ROWS * POLY_TAPS,
                  "gain": tables + 4 * POLY_ROWS * POLY_TAPS + 16}


# -- v0.18: the DT2's sample reader (docs/sampler.md) -------------------------------------
# its 6-tap, 256-phase interpolator at 96 kHz and its 2:1 all-pass decimator, with the
# coefficients read from the owner's DT2 image at build time (dnfw.dt2.rom)
POLY_ROWS, POLY_TAPS = 256, 6
DEC_WORDS = 12                            # a voice's decimator: 4 even inputs, 4 outputs, 4 odd
DEC_STRIDE = 4 * DEC_WORDS


def tables_bytes() -> bytes:
    """the interpolator's 256 x 6 coefficients, then the decimator's four, as float32;
    then the gain that makes LEV 100 play a sample at its own level (the interpolator's
    rows sum to about 0.4045, -7.9 dB, which the DT2 makes up after it)"""
    import struct
    from ..dt2 import rom
    rows = rom.polyphase()
    g = sum(sum(r) for r in rows) / len(rows)
    return struct.pack(f"<{POLY_ROWS * POLY_TAPS}f", *(c for r in rows for c in r)) + \
        struct.pack("<4f", *rom.decimator()) + struct.pack("<f", 1.0 / g)


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
    p.st(C["note"], 8)
    p.fconst(12, 60.0)
    p.fop(8, 8, "-", 12)
    p.fconst(12, 1.0 / 12.0)
    p.fop(8, 8, "*", 12)
    p.ld(5, C["tune"])
    p.fop(8, 8, "+", 5)
    PM.exp2(p, L, 9, 8)
    p.st(C["tr"], 9)
    p.ld(8, C["tune"])                       # v0.18: TUNE alone (GRID's NOTE mode)
    PM.exp2(p, L, 9, 8)
    p.st(C["tr0"], 9)
    # v0.18: a note while the voice sounds: the old note is rendered first, fading out over
    # the block, and the new one is added to it (the DT2 gives a retrigger a second voice,
    # and fades the first): two passes, the first only for that
    p.iconst(0, 0)
    p.st(C["kill"], 0)
    p.st(C["add"], 0)
    p.st(C["pass"], 0)
    p.st(C["segnext"], 0)
    p.ld(0, C["trig"])
    p.ifz(0, "NE", lambda: (v(p, 0, "on"), p.ifz(0, "NE", lambda: (p.iconst(0, 1), p.st(C["kill"], 0)))),
          lambda: werp_clock(p, L))

    def a_pass():
        p.ld(0, C["pass"])
        p.ld(1, C["kill"])
        p.iop(0, 0, "OR", 1)
        p.ifz(0, "NE", lambda: (v(p, 0, "on"), p.ifz(0, "NE", sounding, lambda: silence(p, L))))
        p.ld(0, C["pass"])

        def first():                          # a note: latch the machine, the slot and the region
            p.ld(0, C["trig"])

            p.ifz(0, "NE", lambda: start(p, L))
            p.ld(0, C["segnext"])                 # WERP: the next segment starts (a note of its own)
            p.ifz(0, "NE", lambda: werp_next(p, L))
            p.ld(0, C["kill"])
            p.st(C["add"], 0)
            p.iconst(0, 0)
            p.st(C["kill"], 0)
        p.ifz(0, "EQ", first)
        p.iconst(0, 1)
        p.st(C["pass"], 0)

    def sounding():
        live(p, L)
        v(p, 0, "on")
        p.ifz(0, "NE", sounding_on, lambda: silence(p, L))

    def sounding_on():
        p.ld(4, C["tr"])
        v(p, 0, "fixed")
        p.ifz(0, "NE", lambda: p.ld(4, C["tr0"]))
        v(p, 5, "rate")
        p.fop(4, 4, "*", 5)
        p.st(C["rate"], 4)
        # the time machines (WERP 9, STRETCH 10, REPITCH 11) take the tempo
        v(p, 0, "mach")
        p.iconst(12, SM.TYPE_OF["WERP"])

        def maybe_timed():
            p.iconst(12, SM.TYPE_OF["REPITCH"])
            p.if_(0, "LE", 12, lambda: tempo(p, L), kind="i")
        p.if_(0, "GE", 12, maybe_timed, kind="i")
        v(p, 0, "mach")
        p.iconst(12, SM.TYPE_OF["REPITCH"])
        # REPITCH: the region in BARS, no TUNE, no note (as the DT2's)
        p.if_(0, "EQ", 12, lambda: (p.ld(4, C["sr"]), p.st(C["rate"], 4)), kind="i")
        v(p, 0, "mach")
        p.iconst(12, SM.TYPE_OF["WERP"])
        p.e("COMP(R0, R12);")

        def not_werp():
            p.iconst(12, SM.TYPE_OF["STRETCH"])
            p.e("COMP(R0, R12);")
            p._branch(lambda: p.r[0] == p.r[12], "EQ", lambda: render_stretch(p, L), lambda: render(p, L))
        p._branch(lambda: p.r[0] == p.r[12], "EQ", lambda: render(p, L), not_werp)
    p.loop(C["lp"], 2, a_pass)


def out(p: Prog, L: Layout, x: int) -> None:
    """the next sample of the slot's buffer (I4) = Fx, or + Fx when C['add'] (a retrigger's
    second pass, v0.18). Clobbers R13."""
    p.ld(13, L.C["add"])
    p.ifz(13, "NE", lambda: (p.ldi(13, 0, 4), p.fop(x, x, "+", 13)))
    p.stpost(4, x)


def silence(p: Prog, L: Layout) -> None:
    """32 zeros (nothing, on a retrigger's second pass: the old note's fade is there)"""
    p.ld(0, L.C["add"])

    def zeros():
        buffer(p, L)
        p.iconst(6, 0)
        p.loop(L.C["count"], 32, lambda: p.stpost(4, 6))
    p.ifz(0, "EQ", zeros)


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
    dec_reset(p, L)
    p.iconst(0, 0)
    vs(p, "on", 0)
    vs(p, "fixed", 0)
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
            p.lsh(9, 8, -8)                  # v0.19: bits 8..15 the slices it has
            p.iconst(12, 0xFF)
            p.iop(9, 9, "AND", 12)
            vs(p, "nsl", 9)
            # v0.23: bit 16, the slices were made on the instrument: their table is the
            # slot's in the slice area (SM.SLICE_AREA + SM.SLICE_TABLE_BYTES slot)
            p.lsh(9, 8, -16)
            p.iconst(12, 1)
            p.iop(9, 9, "AND", 12)

            def area():
                p.ld(4, C["samp"])
                p.lsh(5, 4, 9)
                p.lsh(4, 4, 8)
                p.ipass(12, 5)
                p.iop(4, 12, "+", 4)          # slot x 768
                p.iconst(12, L.pool + SM.SLICE_AREA)
                p.iop(9, 12, "+", 4)
            p.ifz(9, "NE", area)
            vs(p, "sla", 9)
            p.iconst(12, 0xFF)
            p.iop(8, 8, "AND", 12)
            vs(p, "fmt", 8)
            region(p, L)
        def inrange():
            p.ld(4, C["samp"])
            p.ifz(4, "GE", have)             # and not OFF (-1)
        p._branch(lambda: s32(p.r[4]) < s32(p.r[0]), "LT", inrange, None)
    p.e("COMP(R0, R12);")
    p._branch(lambda: p.r[0] == p.r[12], "EQ", found, None)


MIN_REGION = 32                                # v0.22: the shortest ONESHOT region, frames


def oneshot_bounds(p: Prog, L: Layout) -> None:
    """lo, hi and loop from STRT, LEN and LOOP (R10: the track's frame slot base, F13: the
    sample's frames). Clobbers R4..R7, R12, R14, R15, I1."""
    ctl(p, 4, SM.STRT_REC, 10)           # 0..120
    tofloat(p, 14, 4, 1.0 / 120.0)
    p.fop(14, 14, "*", 13)               # lo = STRT frames
    ctl(p, 4, SM.LEN_REC, 10)            # 0..127
    tofloat(p, 15, 4, 1.0 / 127.0)
    p.fop(15, 15, "*", 13)
    # v0.22: never an empty region (an empty one ended the note, and a held note stayed
    # silent when the knob came back): at least MIN_REGION frames, or a 508th of the
    # sample (LEN 0: a quarter of LEN 1's), so LEN at its lowest loops a short stretch as
    # fast as it goes (the owner's "markers touching"); STRT at its end keeps that much
    p.fconst(12, 1.0 / 508.0)
    p.fop(12, 12, "*", 13)
    p.fconst(7, float(MIN_REGION))
    p.fop(12, 12, "MAX", 7)
    p.fop(12, 12, "MIN", 13)              # a sample shorter than that: all of it
    p.fop(15, 15, "MAX", 12)
    p.fop(7, 13, "-", 12)
    p.fop(14, 14, "MIN", 7)              # lo <= frames - that
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
    v(p, 0, "mach")                       # v0.18: STRETCH has no LOOP: it loops at STRT (the DT2's)
    p.iconst(12, SM.TYPE_OF["STRETCH"])
    p.if_(0, "EQ", 12, lambda: (v(p, 4, "lo"), vs(p, "loop", 4)), kind="i")


SLICE_WORDS = 3                                # a slice: start, end, loop (frames), after the frames


def slice_bounds(p: Prog, L: Layout) -> None:
    """v0.19, SLICE (the DT2's, its type 5 handler): lo, hi, loop from the sample's own slice
    table (V['nsl'] slices of start, end, loop in frames, after its frames, on a word:
    dn2samples.py writes it). SLCE (0..127 -> 0..63): 0 NOTE, the note picks the slice
    from C1 up, wrapping after the last, and the sample keeps its pitch; else slice SLCE,
    past the last held at it. LEN (0..127 -> 1..64) slices play on from it. No slices: the
    region is the whole sample (v0.23; v0.19..v0.22: empty, nothing played). Clobbers
    R0-R15, I1."""
    C = L.C
    p.iconst(4, 0)
    vs(p, "lo", 4)
    vs(p, "loop", 4)
    v(p, 5, "frames")
    vs(p, "hi", 5)
    v(p, 6, "nsl")

    def some():
        ctl(p, 4, SM.SLICE_REC, 10)           # 0..127 -> 0..63
        p.lsh(4, 4, -1)
        v(p, 6, "nsl")

        def by_note():                         # (note - 12) mod nsl
            p.iconst(0, 1)
            vs(p, "fixed", 0)
            p.ld(5, C["note"])
            p.trunc(4, 5)
            p.iconst(12, -12)
            p.iop(4, 12, "+", 4)
            tofloat(p, 2, 4)
            tofloat(p, 3, 6)
            PM._recip_inline(p, 5, 3, 13)
            p.fop(2, 2, "*", 5)
            p.trunc(7, 2)                      # toward 0; then one step either way
            tofloat(p, 2, 7)
            p.fop(2, 2, "*", 3)
            p.trunc(7, 2)                      # q nsl
            p.ipass(12, 4)
            p.iop(4, 12, "-", 7)
            v(p, 6, "nsl")
            p.iconst(12, 0)
            p.if_(4, "LT", 12, lambda: (p.ipass(12, 4), p.iop(4, 12, "+", 6)), kind="i")
            p.if_(4, "GE", 6, lambda: (p.ipass(12, 4), p.iop(4, 12, "-", 6)), kind="i")
            p.if_(4, "LT", 12, lambda: (p.ipass(12, 4), p.iop(4, 12, "+", 6)), kind="i")

        def by_knob():                         # min(s, nsl) - 1
            p.iop(4, 4, "MIN", 6)
            p.iconst(12, -1)
            p.iop(4, 12, "+", 4)
        p.ifz(4, "EQ", by_note, by_knob)
        p.st(C["a"], 4)                        # k
        p.ld(9, C["t"])
        PP.t146(p, 10, 9)
        ctl(p, 5, SM.SLEN_REC, 10)             # 0..127 -> 1..64 slices
        p.lsh(5, 5, -1)
        p.ld(4, C["a"])
        p.ipass(12, 4)
        p.iop(5, 12, "+", 5)                   # k + len - 1
        v(p, 6, "nsl")
        p.iconst(12, -1)
        p.iop(12, 12, "+", 6)
        p.iop(5, 5, "MIN", 12)
        p.st(C["b"], 5)                        # the last slice
        # the table: after the frames (2 or 4 bytes each), on a word
        v(p, 6, "frames")
        v(p, 8, "fmt")
        p.lsh(7, 6, 2)
        p.ifz(8, "NE", lambda: p.lsh(7, 6, 1))
        p.iconst(12, 3)
        p.iop(7, 12, "+", 7)
        p.iconst(12, -4)
        p.iop(7, 7, "AND", 12)
        v(p, 9, "base")
        p.iop(7, 9, "+", 7)
        v(p, 9, "sla")                         # v0.23: or the slice area's
        p.ifz(9, "NE", lambda: p.ipass(7, 9))
        p.st(C["c"], 7)                        # the table's address
        # slice k's start and loop, the last's end: k 12 bytes in = (k << 3) + (k << 2)
        def entry(word, kname):
            p.ld(4, C[kname])
            p.lsh(5, 4, 3)
            p.lsh(4, 4, 2)
            p.ipass(12, 5)
            p.iop(4, 12, "+", 4)
            p.ld(5, C["c"])
            p.ipass(12, 5)
            p.iop(4, 12, "+", 4)
            p.seti(1, 4)
            p.ldi(0, word, 1)
        entry(0, "a")
        p.iconst(12, 0)
        p.iop(0, 0, "MAX", 12)
        v(p, 6, "frames")
        p.iop(0, 0, "MIN", 6)
        vs(p, "lo", 0)
        entry(1, "b")
        v(p, 6, "frames")
        p.iop(0, 0, "MIN", 6)
        vs(p, "hi", 0)
        entry(2, "a")
        v(p, 4, "lo")
        v(p, 5, "hi")
        p.iop(0, 0, "MAX", 4)
        p.iconst(12, -1)
        p.iop(12, 12, "+", 5)
        p.iop(0, 0, "MIN", 12)
        vs(p, "loop", 0)
    p.ifz(6, "GT", some)


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

        def not_werp():                      # v0.19: SLICE takes its slices at the note too
            p.iconst(12, SM.TYPE_OF["SLICE"])
            p.e("COMP(R0, R12);")
            p._branch(lambda: p.r[0] != p.r[12], "NE", follow, None)
        p._branch(lambda: p.r[0] != p.r[12], "NE", not_werp, None)
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
        ctl(p, 4, SM.SLICE_REC, 10)          # 0..127 -> 0 NOTE, 1..63 the slice (v0.18, the DT2's SLCE)
        p.lsh(4, 4, -1)
        p.iconst(0, 0)
        vs(p, "fixed", 0)

        def by_note():                       # NOTE: (note - 12) mod n picks it, the pitch stays
            p.iconst(0, 1)
            vs(p, "fixed", 0)
            p.ld(5, C["note"])
            p.trunc(4, 5)
            p.iconst(12, -12)
            p.iop(4, 12, "+", 4)
            p.iconst(12, -1)
            p.iop(12, 12, "+", 6)            # n - 1 (n is a power of two)
            p.iop(4, 4, "AND", 12)

        def by_knob():                       # min(n, s) - 1
            p.iop(4, 4, "MIN", 6)
            p.iconst(12, -1)
            p.iop(4, 12, "+", 4)
        p.ifz(4, "EQ", by_note, by_knob)
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

    def slice_():                             # v0.19: the sample's own slices
        slice_bounds(p, L)

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
        def not_werp():
            p.ld(0, C["type"])
            p.iconst(12, SM.TYPE_OF["SLICE"])
            p.e("COMP(R0, R12);")
            p._branch(lambda: p.r[0] == p.r[12], "EQ", slice_, oneshot)
        p._branch(lambda: p.r[0] == p.r[12], "EQ", whole, not_werp)
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
        # the time machines start here (v0.18): STRETCH's grain counter at 0, its new head
        # silent and its second head whole (the DT2 fades a note in from the second head);
        # WERP before its first segment, which the note's block starts (`werp_next`)
        p.fconst(0, 0.0)
        vs(p, "gp0", 0)
        p.fconst(0, 1.0)
        vs(p, "gp1", 0)
        p.iconst(0, 0)
        vs(p, "ph0", 0)
        vs(p, "wacc", 0)
        p.iconst(0, -1)
        vs(p, "seg", 0)
        p.iconst(0, 1)
        vs(p, "on", 0)
        p.ld(0, C["type"])
        p.iconst(12, SM.TYPE_OF["WERP"])
        p.if_(0, "EQ", 12, lambda: (p.iconst(0, 1), vs(p, "walive", 0), p.st(C["segnext"], 0),
                                    p.iconst(0, 0), vs(p, "on", 0)), kind="i")
        # the first block fades in -- but for ONESHOT from STRT 0, whose attack stays (the
        # DT2's ColdFire sends the declick flag, frame +0x73c, 0 only then)
        p.fconst(0, 0.0)
        vs(p, "fig", 0)
        p.iconst(0, 1)
        vs(p, "fin", 0)
        p.ld(0, C["type"])
        p.iconst(12, SM.TYPE_OF["ONESHOT"])

        def oneshot():
            p.ld(9, C["t"])
            PP.t146(p, 10, 9)
            ctl(p, 4, SM.STRT_REC, 10)
            p.ifz(4, "EQ", lambda: (p.iconst(0, 0), vs(p, "fin", 0)))
        p.if_(0, "EQ", 12, oneshot, kind="i")
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


def window(p: Prog, L: Layout) -> None:
    """C['b'], C['c']: the interpolator's tap window, [loop, hi) in the loop modes and
    [lo, hi) otherwise (the DT2's circular buffer over [w64, w68)). Clobbers R0, R4, R12."""
    C = L.C
    v(p, 4, "lo")
    v(p, 0, "mode")
    p.iconst(12, 1)
    p.if_(0, "EQ", 12, lambda: v(p, 4, "loop"), kind="i")
    p.iconst(12, 2)
    p.if_(0, "EQ", 12, lambda: v(p, 4, "loop"), kind="i")
    p.st(C["b"], 4)
    v(p, 4, "hi")
    p.st(C["c"], 4)


def tick(p: Prog, L: Layout, word: str) -> None:
    """One 96 kHz sample of the DT2's reader into C[word]: the six taps from pos (forward:
    s[pos..pos+5]; backward: s[pos-5..pos]) wrapping inside the window, against the
    coefficient row floor(frac 256). One copy of the code (a leaf subroutine).
    Clobbers R0-R3, R5-R15, I1, I3, I12."""
    p.call("tick", lambda: _tick(p, L))
    p.st(L.C[word], 7)


def _tick(p: Prog, L: Layout) -> None:
    C = L.C
    v(p, 2, "frac")
    p.fconst(12, 256.0)
    p.fop(2, 2, "*", 12)
    p.trunc(3, 2)
    p.iconst(12, POLY_ROWS - 1)
    p.iop(3, 3, "MIN", 12)
    p.iconst(12, 0)
    p.iop(3, 3, "MAX", 12)
    p.lsh(5, 3, 4)
    p.lsh(3, 3, 3)
    p.ipass(12, 5)
    p.iop(3, 12, "+", 3)                     # row * 24 bytes
    p.iconst(12, L.T["poly"])
    p.iop(3, 12, "+", 3)
    p.seti(3, 3)
    p.fconst(7, 0.0)
    v(p, 9, "pos")
    v(p, 10, "base")
    p.ld(14, C["b"])
    p.ld(15, C["c"])
    p.ipass(12, 15)
    p.iop(6, 12, "-", 14)                    # the window's length
    v(p, 0, "mode")
    p.iconst(12, 2)

    def fwd():
        for k in range(POLY_TAPS):
            fetch(p, 0, 9)
            p.ldi(1, k, 3)
            p.fop(0, 0, "*", 1)
            p.fop(7, 7, "+", 0)
            if k < POLY_TAPS - 1:
                p.iconst(12, 1)
                p.iop(9, 12, "+", 9)
                p.if_(9, "GE", 15, lambda: p.iop(9, 9, "-", 6), kind="i")

    def rev():
        for k in range(POLY_TAPS):
            fetch(p, 0, 9)
            p.ldi(1, POLY_TAPS - 1 - k, 3)
            p.fop(0, 0, "*", 1)
            p.fop(7, 7, "+", 0)
            if k < POLY_TAPS - 1:
                p.iconst(12, -1)
                p.iop(9, 12, "+", 9)
                p.if_(9, "LT", 14, lambda: (p.ipass(12, 9), p.iop(9, 12, "+", 6)), kind="i")
    def slow():                              # the taps wrap at the window's edge
        v(p, 0, "mode")
        p.iconst(12, 2)
        p.if_(0, "GE", 12, fwd, rev, kind="i")

    # v0.18: where the six taps lie inside the window, s[st .. st + 5] (st = pos forward,
    # pos - 5 backward: both are the row against six frames in order) are read in a row
    p.iconst(11, 0)
    p.if_(0, "LT", 12, lambda: p.iconst(11, -(POLY_TAPS - 1)), kind="i")
    p.iop(11, 11, "+", 9)                    # st
    p.iconst(13, 0)                          # inside: st >= lo and st + 5 < hi
    p.if_(11, "LT", 14, lambda: p.iconst(13, 1), kind="i")
    p.iconst(12, POLY_TAPS - 1)
    p.iop(12, 12, "+", 11)
    p.if_(12, "GE", 15, lambda: p.iconst(13, 1), kind="i")

    def fast():
        v(p, 8, "fmt")

        def f32():
            p.lsh(12, 11, 2)
            p.iop(12, 10, "+", 12)
            p.seti(1, 12)
            for k in range(POLY_TAPS):
                p.ldpost(5, 1)
                p.ldi(6, k, 3)
                p.fop(5, 5, "*", 6)
                p.fop(7, 7, "+", 5)

        def i16():
            p.lsh(12, 11, 1)
            p.iop(12, 10, "+", 12)           # s[st]'s byte address
            p.iconst(13, 2)
            p.iop(13, 12, "AND", 13)         # 2: it is a word's upper half
            p.iconst(14, -4)
            p.iop(12, 12, "AND", 14)
            p.seti(1, 12)
            for r in range(4):
                p.ldpost(r, 1)               # four words: eight frames from the aligned one
            p.iconst(8, -31)
            p.iconst(14, 0xFFFF0000 - (1 << 32))

            def taps(halves):
                for k, (w, upper) in enumerate(halves):
                    if upper:
                        p.iop(5, w, "AND", 14)
                    else:
                        p.lsh(5, w, 16)
                    p.float_(5, 5, 8)        # the frame / 32768
                    p.ldi(6, k, 3)
                    p.fop(5, 5, "*", 6)
                    p.fop(7, 7, "+", 5)
            even = [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
            odd = [(0, 1), (1, 0), (1, 1), (2, 0), (2, 1), (3, 0)]
            p.ifz(13, "EQ", lambda: taps(even), lambda: taps(odd))
        p.ifz(8, "NE", i16, f32)
    p.ifz(13, "EQ", fast, slow)
    # the DT2's MAC keeps the sum's whole 16-bit steps, toward -inf: floor(32768 y) / 32768
    p.fconst(12, 32768.0)
    p.fop(7, 7, "*", 12)
    p.trunc(0, 7)
    p.iconst(12, 0)
    p.float_(1, 0, 12)
    p.if_(7, "LT", 1, lambda: (p.iconst(12, -1), p.iop(0, 12, "+", 0)))
    p.iconst(12, -15)
    p.float_(7, 0, 12)


def decimate(p: Prog, L: Layout, ye: str, yo: str, d: int) -> None:
    """(one copy: a leaf subroutine, F0 its output) -- see _decimate"""
    p.call(f"decim_{ye}_{yo}", lambda: _decimate(p, L, ye, yo, 0))
    if d != 0:
        p.fpass(d, 0)


def _decimate(p: Prog, L: Layout, ye: str, yo: str, d: int) -> None:
    """Fd = the DT2's 2:1 decimator's next output from the 96 kHz pair C[ye], C[yo]: half
    the sum of a fourth-order all-pass of the even samples and the odd ones four outputs
    late (its 0xb80000), in its order of operations. The voice's twelve words at I5: the
    even inputs e1..e4, the all-pass's outputs h1..h4, the odd ring r0..r3.
    Clobbers R0-R3, R5-R7, R12, I0."""
    C = L.C
    p.iconst(12, L.T["decim"])
    p.seti(0, 12)                            # c0..c3 at DM(k, I0)
    p.ld(0, C[ye])
    p.ldi(1, 3, 0)
    p.fop(2, 0, "*", 1)                      # xe c3
    for e, k, first in ((0, 2, True), (1, 1, False), (2, 0, False)):
        p.ldi(5, e, 5)                       # e1, e2, e3
        p.ldi(1, k, 0)
        p.fop(5, 5, "*", 1)
        if first:
            p.fop(2, 2, "+", 5)
        else:
            p.fop(2, 5, "+", 2)
    p.ldi(5, 3, 5)                           # + e4
    p.fop(2, 5, "+", 2)
    for h, k in ((4, 0), (5, 1), (6, 2), (7, 3)):
        p.ldi(5, h, 5)                       # - h1 c0 .. - h4 c3
        p.ldi(1, k, 0)
        p.fop(5, 5, "*", 1)
        p.fop(2, 2, "-", 5)
    p.ldi(6, 11, 5)                          # the odd sample four outputs back
    for a, b in ((3, 2), (2, 1), (1, 0), (7, 6), (6, 5), (5, 4), (11, 10), (10, 9), (9, 8)):
        p.ldi(5, b, 5)
        p.sti(a, 5, 5)
    p.sti(0, 5, 0)                           # e1 = xe
    p.sti(4, 5, 2)                           # h1 = the all-pass's output
    p.ld(7, C[yo])
    p.sti(8, 5, 7)                           # r0 = xo
    p.fop(2, 2, "+", 6)
    p.fconst(12, 0.5)
    p.fop(d, 2, "*", 12)


def dec_reset(p: Prog, L: Layout) -> None:
    """the voice's decimator cleared (the DT2 resets it at each note). Clobbers R0, R5,
    R6, R12, I5."""
    dec_at(p, L)
    p.iconst(0, 0)
    for k in range(DEC_WORDS):
        p.sti(k, 5, 0)


def dec_at(p: Prog, L: Layout) -> None:
    """I5 = this voice's decimator words: dec + t (32 + 16). Clobbers R5, R6, R9, R12."""
    p.ld(9, L.C["t"])
    p.lsh(5, 9, 5)
    p.lsh(6, 9, 4)
    p.ipass(12, 5)
    p.iop(5, 12, "+", 6)
    p.iconst(12, L.dec)
    p.iop(5, 12, "+", 5)
    p.seti(5, 5)


def render(p: Prog, L: Layout) -> None:
    """ONESHOT, REPITCH and GRID (v0.18): the DT2's reader. Each output sample is two
    96 kHz samples of the six-tap interpolator (`tick`), stepping half the block's rate,
    through the 2:1 decimator; a voice that ends inside the next two blocks fades out
    over this one and ends (`end_fade`)."""
    C = L.C
    buffer(p, L)
    v(p, 0, "on")

    def setup():
        end_fade(p, L, 64)
        window(p, L)
        p.ld(0, C["rate"])
        p.fconst(12, 0.5)
        p.fop(0, 0, "*", 12)
        p.st(C["rate"], 0)                    # frames a 96 kHz sample
    p.ifz(0, "NE", setup)
    p.iconst(12, L.T["gain"])
    p.seti(0, 12)
    p.ldi(1, 0, 0)
    p.ld(0, C["lev"])
    p.fop(0, 0, "*", 1)
    p.st(C["tmp"], 0)                         # LEV with the make-up (C['lev'] stays: a retrigger renders twice)
    dec_at(p, L)

    def sample():
        for word in ("x", "y"):
            v(p, 0, "on")

            def play(word=word):
                tick(p, L, word)
                advance(p, L)

            p.ifz(0, "NE", play, lambda word=word: (p.fconst(0, 0.0), p.st(C[word], 0)))
        decimate(p, L, "x", "y", 0)
        p.ld(3, C["tmp"])
        p.fop(0, 0, "*", 3)
        faded(p, L, 0)
        v(p, 5, "fin")

        def fade_in():                       # 0, 1/31, .. 1 over the note's first block
            v(p, 6, "fig")
            p.fop(0, 0, "*", 6)
            p.fconst(12, 1.0 / 31.0)
            p.fop(6, 6, "+", 12)
            p.fconst(12, 1.0)
            p.fop(6, 6, "MIN", 12)
            vs(p, "fig", 6)
        p.ifz(5, "NE", fade_in)
        out(p, L, 0)
    p.loop(C["count"], 32, sample)
    p.iconst(0, 0)
    vs(p, "fin", 0)
    v(p, 0, "fade")
    p.ifz(0, "NE", lambda: (p.iconst(0, 0), vs(p, "on", 0)))


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
    source frames a sample. BARS (0..100) picks 1, 2, 4 or 8 bars; the tempo is the frame's
    word at 216, BPM x 120 (120 BPM if it reads 0). Also C['dir'] (+1 or -1, PLAY), C['play']
    and, for WERP, C['nseg'], C['smode'], and the DT2's segment clock: C['nin'] its step a
    block ((BPM x 120 x 16) >> BARS) and C['nout'] a segment's length (691,200,000 >>
    log2(nseg)). One copy (a leaf subroutine). Clobbers R0-R15, I1, I12."""
    p.call("tempo", lambda: _tempo(p, L))


def _tempo(p: Prog, L: Layout) -> None:
    C = L.C
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 4, SM.BARS_REC, 10)               # 0..100 -> 0..3: 1, 2, 4, 8 bars (v0.18, the DT2's)
    p.iconst(5, 0)
    for k in SM.BARS_STEPS[:len(SM.BARS) - 1]:
        p.iconst(12, k)
        p.if_(4, "GE", 12, lambda: (p.iconst(12, 1), p.iop(5, 12, "+", 5)), kind="i")
    p.st(C["b"], 5)                          # BARS' index (WERP's segments, below)
    p.iconst(8, 1)
    p.float_(8, 8, 5)                        # bars = 2^idx
    p.fconst(12, 4 * 60 * 48000 * 120.0)
    p.fop(8, 8, "*", 12)                     # bars x 1.3824e9
    p.iconst(10, 0)
    PP.half(p, 6, TEMPO_OFFSET, 10)
    p.ifz(6, "EQ", lambda: p.iconst(6, 120 * 120))
    tofloat(p, 7, 6)
    p.st(C["nin"], 6)                        # BPM x 120, for WERP's clock below
    PM._recip_inline(p, 9, 7, 13)
    p.fop(8, 8, "*", 9)                      # the output samples BARS lasts
    PM._recip_inline(p, 9, 8, 13)
    v(p, 4, "hi")
    v(p, 5, "lo")
    v(p, 0, "mach")                          # v0.18: WERP's lo..hi is its segment: the whole sample
    p.iconst(12, SM.TYPE_OF["WERP"])
    p.if_(0, "EQ", 12, lambda: (v(p, 4, "frames"), p.iconst(5, 0)), kind="i")
    p.ipass(12, 4)
    p.iop(4, 12, "-", 5)
    tofloat(p, 6, 4)
    p.fop(6, 6, "*", 9)
    p.st(C["sr"], 6)
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 0, SM.PLAY_REC, 10)               # PLAY (v0.18: from the record; WERP's V['mode'] is its segment's)
    p.lsh(0, 0, -5)
    p.st(C["play"], 0)
    p.iconst(1, 1)
    p.iconst(12, 2)
    p.if_(0, "LT", 12, lambda: p.iconst(1, -1), kind="i")
    p.st(C["dir"], 1)
    # WERP (v0.18, the DT2's): SEG (0..120) -> a segment of 1/32, 1/16 or 1/8 bar, so
    # (32 >> SEG) << BARS segments: 2^(5 - SEG + BARS); MODE (0..127) -> 0..3
    p.ld(9, C["t"])
    PP.t146(p, 10, 9)
    ctl(p, 4, SM.SEG_REC, 10)
    p.ld(5, C["b"])
    p.iconst(12, 5)
    p.iop(5, 12, "+", 5)
    for k in SM.SEG_STEPS[:len(SM.SEGS) - 1]:
        p.iconst(12, k)
        p.if_(4, "GE", 12, lambda: (p.iconst(12, -1), p.iop(5, 12, "+", 5)), kind="i")
    p.iconst(6, 1)
    PP._shift_by(p, 6, 5)                    # nseg = 2^(5 - SEG + BARS)
    p.st(C["nseg"], 6)
    # the DT2's segment clock (its ColdFire, each frame): the step (BPM x 120 x 16) >> BARS,
    # a segment 691,200,000 >> log2(nseg); a boundary when the sum reaches it
    p.iconst(6, 691200000 >> 3)                # log2(nseg) is 3 (1/8, 1 bar) .. 8 (1/32, 8 bars)
    for k in (4, 5, 6, 7, 8):
        p.iconst(12, k)
        p.if_(5, "GE", 12, lambda: p.lsh(6, 6, -1), kind="i")
    p.st(C["nout"], 6)
    p.ld(6, C["nin"])
    p.lsh(6, 6, 4)
    p.ld(4, C["b"])
    for k in (1, 2, 3):
        p.iconst(12, k)
        p.if_(4, "GE", 12, lambda: p.lsh(6, 6, -1), kind="i")
    p.st(C["nin"], 6)
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


GRAIN_XF = 128                            # STRETCH's crossfade after a jump, output samples
T_MIN, T_MAX = 0.125, 4.0                 # STRETCH's time rate, clamped (the DT2's 0x3e000000 .. 0x40800000)


def read2(p: Prog, L: Layout, d: int, i: int, f: int) -> None:
    """Fd = s[Ri] (1 - Ff) + s[Ri + 1] Ff, the next frame held at the sample's end: the
    DT2 STRETCH's two-tap read (one copy: a leaf subroutine on R9, F3 -> F4). Ri inside
    0 .. frames - 1. Clobbers R0-R3, R6, R8-R13, I1, I12; keeps Ri in C['x'], Ff in C['y']."""
    assert (d, i, f) == (4, 9, 3)
    p.call("read2", lambda: _read2(p, L, d, i, f))


def _read2(p: Prog, L: Layout, d: int, i: int, f: int) -> None:
    C = L.C
    p.st(C["x"], i)
    p.st(C["y"], f)
    v(p, 10, "base")
    fetch(p, 0, i)
    p.ld(9, C["x"])
    p.iconst(12, 1)
    p.iop(11, 12, "+", 9)
    v(p, 6, "frames")
    p.iconst(12, -1)
    p.iop(12, 12, "+", 6)
    p.iop(11, 11, "MIN", 12)
    v(p, 10, "base")
    fetch(p, 1, 11)
    p.ld(2, C["y"])
    p.fop(1, 1, "-", 0)
    p.fop(1, 1, "*", 2)
    p.fop(d, 0, "+", 1)


def end_fade(p: Prog, L: Layout, ahead: int = 64) -> None:
    """V['fade'] = 1 when the voice, not looping, passes its region's end within AHEAD
    output samples (the DT2's look-ahead, two blocks: such a block is faded 1 -> 0 and the
    voice ends after it); V['fg'] = 1, the block's first gain. Rate in C['rate'] (frames
    an output sample, > 0). Clobbers R0-R7, R12."""
    C = L.C
    p.iconst(0, 0)
    vs(p, "fade", 0)
    p.fconst(0, 1.0)
    vs(p, "fg", 0)
    v(p, 7, "mode")
    p.iconst(12, 3)

    def once():                                # FWD: pos + 32 rate >= hi
        v(p, 4, "pos")
        tofloat(p, 4, 4)
        v(p, 5, "frac")
        p.fop(4, 4, "+", 5)
        p.ld(5, C["rate"])
        p.fconst(12, float(ahead))
        p.fop(5, 5, "*", 12)
        p.fop(4, 4, "+", 5)
        v(p, 6, "hi")
        tofloat(p, 6, 6)
        p.if_(4, "GE", 6, lambda: (p.iconst(0, 1), vs(p, "fade", 0)))

    def rev_once():                            # REV: pos - 32 rate < low
        v(p, 4, "pos")
        tofloat(p, 4, 4)
        v(p, 5, "frac")
        p.fop(4, 4, "+", 5)
        p.ld(5, C["rate"])
        p.fconst(12, float(ahead))
        p.fop(5, 5, "*", 12)
        p.fop(4, 4, "-", 5)
        v(p, 6, "low")
        tofloat(p, 6, 6)
        p.if_(4, "LT", 6, lambda: (p.iconst(0, 1), vs(p, "fade", 0)))
    p.if_(7, "EQ", 12, once, kind="i")
    p.ifz(7, "EQ", rev_once)
    p.ld(0, C["kill"])                        # a retrigger's first pass: the old note fades out
    p.ifz(0, "NE", lambda: (p.iconst(0, 1), vs(p, "fade", 0)))


def faded(p: Prog, L: Layout, x: int) -> None:
    """Fx *= V['fg'], which steps 1 -> 0 over the block when V['fade'] is set (1/31 a
    sample, as the DT2's). Clobbers R5, R6, R12."""
    v(p, 5, "fade")

    def ramp():
        v(p, 6, "fg")
        p.fop(x, x, "*", 6)
        p.fconst(12, 1.0 / 31.0)
        p.fop(6, 6, "-", 12)
        p.fconst(12, 0.0)
        p.fop(6, 6, "MAX", 12)
        vs(p, "fg", 6)
    p.ifz(5, "NE", ramp)


def render_stretch(p: Prog, L: Layout) -> None:
    """STRETCH as the DT2's (its reader at 0x1c5576, docs/sampler.md): one read head moves
    at the note's pitch (C['rate'] frames a sample); every 2048 samples it jumps by
    (T - rate) 2048 frames, T the time rate that makes the region last BARS (C['sr'],
    clamped to 1/8 .. 4), so that on average it moves at T; for 128 samples after a jump
    the old head (where the head would have been) crossfades linearly into the new one.
    Two-tap linear reads, the old head with the new one's fraction. The region loops at
    its own start (the DT2's STRETCH has no LOOP)."""
    C = L.C
    buffer(p, L)
    # the jump this block: (T - rate) 2048, by the play direction
    p.ld(0, C["sr"])
    p.fconst(12, T_MIN)
    p.fop(0, 0, "MAX", 12)
    p.fconst(12, T_MAX)
    p.fop(0, 0, "MIN", 12)
    p.ld(1, C["rate"])
    p.fop(0, 0, "-", 1)
    p.fconst(12, float(GRAIN))
    p.fop(0, 0, "*", 12)
    p.ld(9, C["dir"])
    p.ifz(9, "LT", lambda: (p.fconst(12, 0.0), p.fop(0, 12, "-", 0)))
    vs(p, "jj", 0)
    v(p, 0, "on")

    def grain():
        v(p, 4, "ph0")                          # the grain counter
        p.iconst(12, GRAIN)

        def jump():
            p.iconst(12, -GRAIN)
            p.iop(4, 12, "+", 4)
            vs(p, "ph0", 4)
            v(p, 2, "jj")                       # pos + frac += jj, then into [low, hi)
            v(p, 1, "frac")
            p.fop(2, 2, "+", 1)
            p.fpass(3, 2)
            PM.frac(p, 2)                       # F2: the new fraction (R0, R1, R12)
            vs(p, "frac", 2)
            p.fop(2, 3, "-", 2)                 # whole frames moved
            p.fconst(12, 0.5)
            p.ifz(2, "LT", lambda: p.fconst(12, -0.5), kind="f")
            p.fop(2, 2, "+", 12)
            p.trunc(2, 2)
            v(p, 9, "pos")
            p.iop(9, 9, "+", 2)
            v(p, 10, "hi")
            v(p, 11, "low")
            p.ipass(12, 10)
            p.iop(12, 12, "-", 11)              # the span
            v(p, 7, "mode")                     # PLAY 1, 2 are the loops: (mode + 1) & 2
            p.iconst(13, 1)
            p.iop(13, 13, "+", 7)
            p.iconst(14, 2)
            p.iop(13, 13, "AND", 14)
            p.st(C["a"], 13)

            def over():
                p.iop(9, 9, "-", 12)
                p.ld(13, C["a"])
                p.ifz(13, "EQ", lambda: (p.iconst(0, 0), vs(p, "on", 0)))

            def under():
                p.iop(9, 9, "+", 12)
                p.ld(13, C["a"])
                p.ifz(13, "EQ", lambda: (p.iconst(0, 0), vs(p, "on", 0)))
            p.if_(9, "GE", 10, over, kind="i")
            p.if_(9, "LT", 11, under, kind="i")
            p.iop(9, 9, "MAX", 11)
            p.iconst(12, -1)
            p.iop(12, 12, "+", 10)
            p.iop(9, 9, "MIN", 12)
            vs(p, "pos", 9)
            p.fconst(0, 0.0)
            vs(p, "gp0", 0)                     # the new head's gain
            p.fconst(0, 1.0)
            vs(p, "gp1", 0)                     # the old head's
        p.if_(4, "GE", 12, jump, kind="i")
        v(p, 4, "ph0")
        p.iconst(12, GRAIN_XF)

        def ramping():
            p.fconst(0, 1.0 / (GRAIN_XF - 1))
            vs(p, "dg", 0)

        def steady():
            p.fconst(0, 0.0)
            vs(p, "dg", 0)
            vs(p, "gp1", 0)
            p.fconst(0, 1.0)
            vs(p, "gp0", 0)
        p.if_(4, "LT", 12, ramping, steady, kind="i")
        v(p, 4, "ph0")
        p.iconst(12, 32)
        p.iop(4, 12, "+", 4)
        vs(p, "ph0", 4)
        end_fade(p, L)
    p.ifz(0, "NE", grain)

    def sample():
        v(p, 0, "on")

        def play():
            v(p, 9, "pos")
            v(p, 3, "frac")
            read2(p, L, 4, 9, 3)                # the head
            v(p, 0, "gp0")
            p.fop(4, 4, "*", 0)
            p.st(C["acc"], 4)
            # the old head: floor(pos + frac - jj), the head's fraction; into 0 .. frames - 1
            v(p, 0, "frac")
            v(p, 1, "jj")
            p.fop(0, 0, "-", 1)
            p.fpass(2, 0)
            PM.frac(p, 2)                       # F2 = x - floor(x) (R0, R1, R12)
            v(p, 0, "frac")
            v(p, 1, "jj")
            p.fop(0, 0, "-", 1)
            p.fop(0, 0, "-", 2)                 # floor(x), whole
            p.fconst(12, 0.5)
            p.ifz(0, "LT", lambda: p.fconst(12, -0.5), kind="f")
            p.fop(0, 0, "+", 12)
            p.trunc(0, 0)
            v(p, 9, "pos")
            p.iop(9, 9, "+", 0)
            v(p, 6, "frames")
            p.iconst(12, 0)
            p.if_(9, "LT", 12, lambda: p.iop(9, 9, "+", 6), kind="i")
            p.if_(9, "GE", 6, lambda: p.iop(9, 9, "-", 6), kind="i")
            p.iconst(12, 0)
            p.iop(9, 9, "MAX", 12)
            p.iconst(12, -1)
            p.iop(12, 12, "+", 6)
            p.iop(9, 9, "MIN", 12)
            v(p, 3, "frac")
            read2(p, L, 4, 9, 3)
            v(p, 0, "gp1")
            p.fop(4, 4, "*", 0)
            p.ld(5, C["acc"])
            p.fop(4, 4, "+", 5)
            # the gains move on every sample (held inside 0 .. 1)
            v(p, 0, "gp0")
            v(p, 1, "dg")
            p.fop(0, 0, "+", 1)
            p.fconst(12, 1.0)
            p.fop(0, 0, "MIN", 12)
            vs(p, "gp0", 0)
            v(p, 0, "gp1")
            p.fop(0, 0, "-", 1)
            p.fconst(12, 0.0)
            p.fop(0, 0, "MAX", 12)
            vs(p, "gp1", 0)
            p.ld(3, C["lev"])
            p.fop(4, 4, "*", 3)
            faded(p, L, 4)
            out(p, L, 4)
            advance(p, L)

        def rest():
            p.iconst(6, 0)
            out(p, L, 6)
        p.ifz(0, "NE", play, rest)
    p.loop(C["count"], 32, sample)
    v(p, 0, "fade")
    p.ifz(0, "NE", lambda: (p.iconst(0, 0), vs(p, "on", 0)))


def werp_clock(p: Prog, L: Layout) -> None:
    """WERP's segment clock (v0.18, the DT2's ColdFire, a block at a time): while its run of
    segments goes on, add the block's step; when the sum reaches a segment's length, take it
    off and start the next segment this block (C['segnext']), the one sounding fading out
    under it (C['kill']), as the DT2's retrigger does. Clobbers R0-R15, I1, I12."""
    C = L.C
    v(p, 0, "mach")
    p.iconst(12, SM.TYPE_OF["WERP"])

    def werp():
        v(p, 0, "walive")

        def run():
            tempo(p, L)
            v(p, 4, "wacc")
            p.ld(5, C["nin"])
            p.ipass(12, 4)
            p.iop(4, 12, "+", 5)
            p.ld(6, C["nout"])

            def boundary():
                p.iop(4, 4, "-", 6)
                p.iconst(0, 1)
                p.st(C["segnext"], 0)
                v(p, 0, "on")
                p.st(C["kill"], 0)
            p.if_(4, "GE", 6, boundary, kind="i")
            vs(p, "wacc", 4)
        p.ifz(0, "NE", run)
    p.if_(0, "EQ", 12, werp, kind="i")


def werp_next(p: Prog, L: Layout) -> None:
    """WERP's next segment, as the DT2 plays one (dt2-coldfire-werp.md): in PLAY's
    direction (REV, REV LOOP from the last); past the end the loop modes start again and
    the others end the run. The segment k of n is the region [k/n, (k+1)/n) of the sample,
    played as a note in MODE from its start (FWD, FWD LOOP) or its end, through a fresh
    decimator. Clobbers R0-R15, I1, I5, I12."""
    C = L.C
    p.iconst(0, 0)
    p.st(C["segnext"], 0)
    tempo(p, L)
    p.ld(9, C["dir"])
    v(p, 7, "seg")
    p.ld(6, C["nseg"])

    def first():                               # -1: the first segment of the direction
        p.iconst(7, 0)
        p.ifz(9, "LT", lambda: (p.iconst(12, -1), p.iop(7, 12, "+", 6)))

    def step():
        p.ipass(12, 7)
        p.iop(7, 12, "+", 9)
    p.ifz(7, "LT", first, step)
    p.iconst(8, 0)
    p.if_(7, "GE", 6, lambda: p.iconst(8, 1), kind="i")
    p.ifz(7, "LT", lambda: p.iconst(8, 1))
    p.iconst(0, 1)
    p.st(C["a"], 0)                            # the run goes on

    def wrap():
        p.ld(0, C["play"])
        p.iconst(12, 1)

        def again():
            p.iconst(7, 0)
            p.ifz(9, "LT", lambda: (p.iconst(12, -1), p.iop(7, 12, "+", 6)))

        def end():                             # FWD, REV: the run is over
            p.iconst(0, 0)
            p.st(C["a"], 0)
            vs(p, "walive", 0)
            p.iconst(7, 0)
        p.if_(0, "EQ", 12, again,
              lambda: (p.iconst(12, 2), p.if_(0, "EQ", 12, again, end, kind="i")), kind="i")
    p.ifz(8, "NE", wrap)

    def segment():
        vs(p, "seg", 7)
        p.ld(6, C["nseg"])
        tofloat(p, 3, 6)
        PM._recip_inline(p, 2, 3, 13)          # 1 / n (exact: n is a power of two)
        v(p, 6, "frames")
        tofloat(p, 4, 6)
        p.fop(4, 4, "*", 2)                    # frames / n
        tofloat(p, 3, 7)
        p.fop(3, 3, "*", 4)                    # k frames / n
        p.fop(5, 3, "+", 4)                    # (k + 1) frames / n
        p.trunc(4, 3)                          # lo
        p.trunc(5, 5)                          # hi
        v(p, 6, "frames")
        p.iop(5, 5, "MIN", 6)
        p.iconst(12, 1)
        p.iop(12, 12, "+", 4)
        p.iop(5, 5, "MAX", 12)                 # at least a frame
        p.iop(5, 5, "MIN", 6)
        vs(p, "lo", 4)
        vs(p, "loop", 4)
        vs(p, "low", 4)
        vs(p, "hi", 5)
        p.ld(0, C["smode"])
        vs(p, "mode", 0)
        p.iconst(12, 2)
        p.if_(0, "LT", 12, lambda: (p.iconst(12, -1), p.iop(4, 12, "+", 5)), kind="i")
        vs(p, "pos", 4)
        p.fconst(0, 0.0)
        vs(p, "frac", 0)
        p.iconst(0, 1)
        vs(p, "on", 0)
        vs(p, "fin", 0)                        # a segment's first block fades in (+0x73c is 1)
        p.fconst(0, 0.0)
        vs(p, "fig", 0)
        dec_reset(p, L)
    p.ld(0, C["a"])
    p.ifz(0, "NE", segment)


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
        p.ld(4, cmd + 12)                     # channel: 0 L+R, 1 L, 2 R (bits 0..1; v0.22: the
        p.iconst(12, 3)                       # recording's place in bits 8..23)
        p.iop(4, 4, "AND", 12)
        p.iconst(12, 2)
        p.iop(4, 4, "MIN", 12)
        p.st(C["rchan"], 4)
        p.ld(4, cmd + 16)                     # the threshold, 0..32767 for a peak 0..1
        tofloat(p, 5, 4, 1.0 / 32767.0)
        p.st(C["rthr"], 5)
        p.ld(2, cmd + 4)                      # the command

        def start(state):
            def body():                       # the slot, emptied
                # v0.22: where the frames go, in the recordings' area: REC_OFFSET + 512 u,
                # u = bits 8..23 of the channel word (the ColdFire's allocation); and
                # never past the pool's end
                p.ld(6, cmd + 12)
                p.lsh(6, 6, -8)
                p.iconst(12, 0xFFFF)
                p.iop(6, 6, "AND", 12)
                p.iconst(12, (SM.REC_BYTES - SM.REC_MIN_BYTES) // SM.REC_UNIT)
                p.iop(6, 6, "MIN", 12)
                p.lsh(6, 6, 9)                # x 512 bytes
                p.st(C["tmp"], 6)             # the offset into the area
                p.iconst(12, SM.REC_BYTES)
                p.ipass(13, 6)
                p.iop(7, 12, "-", 13)         # the room left, bytes
                p.lsh(7, 7, -1)               # .. as int16 frames
                p.ld(4, cmd + 20)
                p.iconst(12, 0x00FFFFFF)
                p.iop(8, 4, "AND", 12)        # frames: 32 .. the room, the DT2's 66 s at most
                p.iconst(12, 32)
                p.iop(8, 8, "MAX", 12)
                p.iconst(12, SM.REC_FRAMES)
                p.iop(8, 8, "MIN", 12)
                p.iop(8, 8, "MIN", 7)
                p.st(C["rmax"], 8)
                p.ld(6, C["tmp"])
                p.iconst(13, L.pool + SM.REC_OFFSET)
                p.iop(6, 13, "+", 6)
                p.st(C["rbase"], 6)
                p.lsh(5, 4, -24)              # dest: the slot, 0 .. POOL_SLOTS - 2 (SAMP 1..)
                p.iconst(12, SM.POOL_SLOTS - 2)
                p.iop(5, 5, "MIN", 12)
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
        p.ld(2, cmd + 4)
        p.iconst(12, SM.CMD_SEND)

        def send():                           # v0.16: pool words back over the TDM link
            K = LK
            p.ld(4, cmd + 8)
            p.st(K["spos"], 4)
            p.ld(5, cmd + 12)
            p.ipass(12, 4)
            p.iop(5, 12, "+", 5)
            p.iconst(12, SM.POOL_WORDS)
            p.iop(5, 5, "MIN", 12)
            p.st(K["send"], 5)
            p.iconst(6, 1)
            p.st(K["sbusy"], 6)
        p.if_(2, "EQ", 12, send, kind="i")
        p.ld(2, cmd + 4)
        p.iconst(12, SM.CMD_VERIFY)

        def verify():                         # v0.16: a word range's sums, a chunk a block
            K = LK
            p.ld(4, cmd + 8)
            p.st(K["vpos"], 4)
            p.ld(5, cmd + 12)
            p.ipass(12, 4)
            p.iop(5, 12, "+", 5)
            p.iconst(12, SM.POOL_WORDS)
            p.iop(5, 5, "MIN", 12)
            p.st(K["vend"], 5)
            p.iconst(6, 0)
            p.st(K["vsum"], 6)
            p.st(K["vsum2"], 6)
            p.st(K["vdone"], 6)
            p.ld(6, cmd)                      # its own sequence, for vdone
            p.st(K["vseq"], 6)
        p.if_(2, "EQ", 12, verify, kind="i")
        p.ld(2, cmd + 4)
        p.iconst(12, SM.CMD_PROBE)

        def probe_start():                    # v0.22: the RAM check, from its first word
            p.iconst(6, 1)
            p.st(C["pph"], 6)
            p.iconst(6, 0)
            p.st(C["pix"], 6)
            p.st(C["pbad"], 6)
            p.iconst(6, 3)
            p.st(C["pres"], 6)
        p.if_(2, "EQ", 12, probe_start, kind="i")
        p.ld(2, cmd + 4)
        p.iconst(12, SM.CMD_PREVIEW)

        def preview():                        # v0.25: frames [first, end) of the slot, to pvmix
            p.ld(5, cmd + 8)
            p.iconst(12, 0)
            p.iop(5, 5, "MAX", 12)
            p.iconst(12, SM.POOL_SLOTS - 1)
            p.iop(5, 5, "MIN", 12)
            p.lsh(5, 5, 4)
            p.iconst(13, L.pool + 8)
            p.iop(5, 13, "+", 5)
            p.seti(1, 5)
            p.ldi(6, 0, 1)                    # the frames' address
            p.ldi(7, 1, 1)                    # their count
            p.ld(8, cmd + 12)                 # first, on a word
            p.iconst(12, -2)
            p.iop(8, 8, "AND", 12)
            p.ld(9, cmd + 16)                 # end, at most the count
            p.iop(9, 9, "MIN", 7)
            p.iop(9, 9, "-", 8)
            p.iconst(12, 0)
            p.iop(9, 9, "MAX", 12)            # none if end <= first
            p.lsh(9, 9, -1)                   # words, two frames each
            p.lsh(8, 8, 1)
            p.iop(6, 8, "+", 6)
            p.st(C["pva"], 6)
            p.st(C["pvn"], 9)
        p.if_(2, "EQ", 12, preview, kind="i")
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
        # v0.22: track t's audio is bucket t of the buffer 0x1c244d fills. The routing
        # halves (TRK_ROUTE + 2v) say which TRACK each DSP voice v plays: 0x1c244d sums
        # voice v into bucket route[v]. v0.15..v0.21 read bucket route[t], which is track
        # t's bucket only while voice t belongs to track t (the owner's v0.21 report: a
        # silent track's meter moved, recordings of a track were another's or silence).
        p.ld(8, C["rsrc"])
        p.iconst(12, -2)
        p.iop(8, 12, "+", 8)                  # t
        p.iconst(12, 15)
        p.iop(8, 8, "MIN", 12)
        p.lsh(10, 8, 8)                       # 0x100 a bucket
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


LK = {w: SM.LINK_DM + 4 * k for k, w in enumerate(SM.LINK_WORDS)}


def tdm_rx(p: Prog, L: Layout) -> None:
    """The fast link in (v0.16, dnfw.sampler.machines): the ColdFire's packet in slots 8..15
    of the TDM receive page the engine read this block. 256 units of 16 bits, each under
    the tag byte in either justification: MAGIC, sequence, a word offset (low, high), 248
    units of data (124 words, low half first), the count of words, two spare, a check
    (0x1D0F + the 255 before it). A packet that checks out, whose words lie in the pool,
    either clear of the command block or within it from its start (v0.20: the commands
    come this way too; the frame's words are the DSP's routing, never ours), is written;
    anything else -- stock's zeros included -- writes nothing."""
    K = LK
    p.ld(0, SM.TDM_PAGE)
    p.iconst(12, 1)
    p.iop(0, 0, "AND", 12)
    p.lsh(0, 0, 11)
    p.iconst(12, SM.TDM_RX + 32)              # slot 8 of frame 0
    p.iop(0, 12, "+", 0)
    p.st(K["pg"], 0)

    def unit(d):
        """Rd = the unit at C(a) (an address), or K['bad'] set. Clobbers R1..R3, R12, I1."""
        p.ld(1, K["a"])
        p.seti(1, 1)
        p.ldi(1, 0, 1)
        p.lsh(2, 1, -24)
        p.iconst(12, SM.TDM_TAG)

        def high():
            p.lsh(d, 1, -8)
        def low():
            p.lsh(2, 1, -16)
            p.iconst(12, 0xFF)
            p.iop(2, 2, "AND", 12)
            p.iconst(12, SM.TDM_TAG)
            p.if_(2, "EQ", 12, lambda: p.ipass(d, 1),
                  lambda: (p.iconst(3, 1), p.st(K["bad"], 3)), kind="i")
        p.if_(2, "EQ", 12, high, low, kind="i")
        p.iconst(12, 0xFFFF)
        p.iop(d, d, "AND", 12)

    p.iconst(0, 0)
    p.st(K["bad"], 0)
    p.ld(0, K["pg"])
    p.st(K["a"], 0)
    unit(4)
    p.ld(0, K["bad"])
    p.iconst(12, SM.RX_MAGIC)

    def packet():
        # every unit into the buffer, and the sum of the first 255
        p.iconst(0, SM.LINK_SEED)
        p.st(K["sum"], 0)
        p.iconst(0, 0)
        p.st(K["u"], 0)

        def each():
            p.ld(0, K["u"])                   # its address: page + 64 (u >> 3) + 4 (u & 7)
            p.lsh(1, 0, -3)
            p.lsh(1, 1, 6)
            p.iconst(12, 7)
            p.iop(2, 0, "AND", 12)
            p.lsh(2, 2, 2)
            p.ld(3, K["pg"])
            p.ipass(12, 3)
            p.iop(3, 12, "+", 1)
            p.ipass(12, 3)
            p.iop(3, 12, "+", 2)
            p.st(K["a"], 3)
            unit(4)
            p.ld(0, K["u"])
            p.lsh(1, 0, 2)
            p.iconst(12, SM.LINK_BUF)
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.sti(0, 1, 4)
            p.iconst(12, SM.RX_UNITS - 1)
            p.e("COMP(R0, R12);")

            def add():
                p.ld(5, K["sum"])
                p.ipass(12, 5)
                p.iop(5, 12, "+", 4)
                p.st(K["sum"], 5)
            p._branch(lambda: s32(p.r[0]) < s32(p.r[12]), "LT", add, None)
            p.ld(0, K["u"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(K["u"], 0)
        p.loop(K["v"], SM.RX_UNITS, each)
        p.ld(0, K["bad"])

        def tagged():
            p.ld(5, K["sum"])
            p.iconst(12, 0xFFFF)
            p.iop(5, 5, "AND", 12)
            p.ld(6, SM.LINK_BUF + 4 * 255)
            p.e("COMP(R5, R6);")

            def checked():
                p.ld(7, SM.LINK_BUF + 4 * 252)    # count
                p.iconst(12, SM.RX_WORDS)
                p.e("COMP(R7, R12);")

                def counted():
                    p.ld(8, SM.LINK_BUF + 4 * 3)  # the offset, words
                    p.lsh(8, 8, 16)
                    p.ld(9, SM.LINK_BUF + 4 * 2)
                    p.ipass(12, 8)
                    p.iop(8, 12, "+", 9)
                    p.st(K["off"], 8)
                    p.ld(7, SM.LINK_BUF + 4 * 252)
                    p.ipass(12, 8)
                    p.iop(9, 12, "+", 7)          # its end
                    # anywhere in the pool: wholly before the command block, wholly after
                    # it, or (v0.20, the recorder's commands) starting at it and ending
                    # within it; nothing that runs over it from one side
                    lo = SM.CMD_OFFSET // 4
                    hi = SM.CMD_OFFSET // 4 + 6
                    top = SM.POOL_WORDS
                    p.iconst(12, lo)
                    p.e("COMP(R9, R12);")

                    def write():
                        p.ld(8, K["off"])
                        p.lsh(8, 8, 2)
                        p.iconst(12, L.pool)
                        p.iop(8, 12, "+", 8)
                        p.seti(4, 8)
                        p.ld(0, SM.LINK_BUF + 4 * 252)
                        p.st(K["cnt"], 0)
                        p.iconst(0, SM.LINK_BUF + 16)
                        p.st(K["a"], 0)

                        def word():
                            p.ld(0, K["a"])
                            p.seti(1, 0)
                            p.ldi(5, 0, 1)
                            p.ldi(6, 1, 1)
                            p.lsh(6, 6, 16)
                            p.ipass(12, 6)
                            p.iop(5, 12, "+", 5)
                            p.ld(7, K["cnt"])
                            p.ifz(7, "GT", lambda: p.stpost(4, 5))
                            p.ld(7, K["cnt"])
                            p.iconst(12, -1)
                            p.iop(7, 12, "+", 7)
                            p.st(K["cnt"], 7)
                            p.iconst(12, 8)
                            p.iop(0, 12, "+", 0)
                            p.st(K["a"], 0)
                        p.loop(K["w"], SM.RX_WORDS, word)
                        p.ld(0, K["good"])
                        p.iconst(12, 1)
                        p.iop(0, 12, "+", 0)
                        p.st(K["good"], 0)
                        p.ld(0, SM.LINK_BUF + 4)
                        p.st(K["lseq"], 0)

                    def above():
                        p.ld(8, K["off"])
                        p.iconst(12, hi)
                        p.e("COMP(R8, R12);")

                        def below_top():
                            p.iconst(12, top)
                            p.e("COMP(R9, R12);")
                            p._branch(lambda: s32(p.r[9]) <= s32(p.r[12]), "LE", write, None)

                        def command():            # v0.20: exactly the command block's words
                            p.iconst(12, lo)
                            p.e("COMP(R8, R12);")

                            def at_lo():
                                p.iconst(12, hi)
                                p.e("COMP(R9, R12);")
                                p._branch(lambda: s32(p.r[9]) <= s32(p.r[12]), "LE", write, None)
                            p._branch(lambda: p.r[8] == p.r[12], "EQ", at_lo, None)
                        p._branch(lambda: s32(p.r[8]) >= s32(p.r[12]), "GE", below_top, command)
                    p._branch(lambda: s32(p.r[9]) <= s32(p.r[12]), "LE", write, above)
                p._branch(lambda: s32(p.r[7]) <= s32(p.r[12]), "LE", counted, None)

            def failed():
                p.ld(0, K["nbad"])
                p.iconst(12, 1)
                p.iop(0, 12, "+", 0)
                p.st(K["nbad"], 0)
            p._branch(lambda: p.r[5] == p.r[6], "EQ", checked, failed)
        p.ifz(0, "EQ", tagged)
    # the first unit decides: our MAGIC (stock's zeros are not tagged)
    p.ifz(0, "EQ", lambda: (p.iconst(12, SM.RX_MAGIC), p.if_(4, "EQ", 12, packet, kind="i")))


def probe(p: Prog, L: Layout) -> None:
    """v0.22, the RAM check (CMD_PROBE, dnfw.sampler.machines.PROBE_*): PROBE_STEP words a
    block of four phases -- fill the low area, fill the high one, check the low, check the
    high -- then pres = 1 (every word as written) or 2. A phase or index out of range (the
    words as the DSP's memory holds them before any check) stops it, writing nothing."""
    C = L.C
    n = SM.PROBE_BYTES // 4
    p.ld(0, C["pph"])

    def stop():                               # out of range: stop, writing nothing
        p.iconst(6, 0)
        p.st(C["pph"], 6)

    def work():
        for ph, base, pat, check in ((1, SM.PROBE_LO, SM.PROBE_PAT[0], False),
                                     (2, SM.PROBE_HI, SM.PROBE_PAT[1], False),
                                     (3, SM.PROBE_LO, SM.PROBE_PAT[0], True),
                                     (4, SM.PROBE_HI, SM.PROBE_PAT[1], True)):
            def phase(base=base, pat=pat, check=check):
                p.ld(8, C["pix"])
                p.lsh(6, 8, 2)
                p.iconst(12, L.pool + base)
                p.iop(6, 12, "+", 6)
                p.seti(4, 6)

                def word():
                    p.ld(8, C["pix"])
                    p.iconst(9, pat)
                    p.iop(7, 8, "+", 9)               # word i: i + the pattern
                    if check:
                        p.ldpost(5, 4)

                        def wrong():
                            p.ld(10, C["pbad"])
                            p.iconst(11, 1)
                            p.iop(10, 10, "+", 11)
                            p.st(C["pbad"], 10)
                        p.if_(5, "NE", 7, wrong, kind="i")
                    else:
                        p.stpost(4, 7)
                    p.ld(8, C["pix"])
                    p.iconst(9, 1)
                    p.iop(8, 8, "+", 9)
                    p.st(C["pix"], 8)
                p.loop(C["pcnt"], SM.PROBE_STEP, word)
            p.ld(0, C["pph"])
            p.iconst(12, ph)
            p.if_(0, "EQ", 12, phase, kind="i")
        # the phase's end: on to the next; after the fourth, the verdict
        p.ld(8, C["pix"])
        p.iconst(12, n)

        def next_phase():
            p.iconst(6, 0)
            p.st(C["pix"], 6)
            p.ld(8, C["pph"])
            p.iconst(9, 1)
            p.iop(8, 8, "+", 9)
            p.st(C["pph"], 8)
            p.iconst(12, 5)

            def verdict():
                p.iconst(6, 0)
                p.st(C["pph"], 6)
                p.ld(5, C["pbad"])
                p.iconst(6, 1)
                p.ifz(5, "NE", lambda: p.iconst(6, 2))
                p.st(C["pres"], 6)
            p.if_(8, "EQ", 12, verdict, kind="i")
        p.if_(8, "GE", 12, next_phase, kind="i")

    def running():
        p.ld(8, C["pix"])
        p.iconst(12, 0)

        def nonneg():
            p.iconst(13, n - SM.PROBE_STEP)

            def below():
                p.ld(0, C["pph"])
                p.iconst(12, 4)
                p.if_(0, "LE", 12, work, stop, kind="i")
            p.if_(8, "LE", 13, below, stop, kind="i")
        p.if_(8, "GE", 12, nonneg, stop, kind="i")
    p.ifz(0, "NE", running)


def tdm_tx(p: Prog, L: Layout) -> None:
    """The fast link out (v0.16): while a SEND is running, the next 29 pool words in slots
    14..15 of the TDM transmit page this block (64 units: MAGIC, sequence, the word
    offset, 58 units of data, the count, a check), each as TAG << 24 | v << 8. v0.25:
    idle, the voices' play positions instead (POS_MAGIC, then a unit a track: POS_NONE, or
    the position as a fraction of the sample x POS_ONE; zeros; the check), which the
    ColdFire draws as the sample pages' playhead."""
    K = LK
    p.ld(0, SM.TDM_PAGE)
    p.iconst(12, 1)
    p.iop(0, 0, "AND", 12)
    p.lsh(0, 0, 11)
    p.iconst(12, SM.TDM_TX + 56)              # slot 14 of frame 0
    p.iop(0, 12, "+", 0)
    p.st(K["pg"], 0)
    p.ld(0, K["sbusy"])

    def idle():                               # v0.25: the play positions
        p.iconst(6, SM.POS_MAGIC)
        p.st(SM.LINK_BUF, 6)
        p.iconst(0, 0)
        p.st(K["u"], 0)

        def track():
            p.ld(0, K["u"])
            p.lsh(1, 0, 7)                    # the track's state: state + 128 t
            p.iconst(12, L.state)
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.iconst(5, SM.POS_NONE)
            p.ldi(2, V["on"], 1)
            p.ldi(3, V["frames"], 1)

            def playing():
                p.ldi(4, V["pos"], 1)
                p.iconst(12, 0)
                p.float_(3, 3, 12)
                p.float_(4, 4, 12)
                PM._recip_inline(p, 6, 3, 7)  # F6 = 1 / frames
                p.fop(4, 4, "*", 6)
                p.fconst(12, float(SM.POS_ONE))
                p.fop(4, 4, "*", 12)
                p.fconst(12, 0.0)
                p.fop(4, 4, "MAX", 12)
                p.fconst(12, float(SM.POS_ONE))
                p.fop(4, 4, "MIN", 12)
                p.trunc(5, 4)
            p.ifz(2, "NE", lambda: p.ifz(3, "GT", playing))
            p.ld(0, K["u"])
            p.lsh(1, 0, 2)
            p.iconst(12, SM.LINK_BUF + 4)
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.sti(0, 1, 5)
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(K["u"], 0)
        p.loop(K["v"], 16, track)
        p.iconst(0, 17)
        p.st(K["u"], 0)

        def zero():
            p.ld(0, K["u"])
            p.lsh(1, 0, 2)
            p.iconst(12, SM.LINK_BUF)
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.iconst(6, 0)
            p.sti(0, 1, 6)
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(K["u"], 0)
        p.loop(K["v"], SM.TX_UNITS - 1 - 17, zero)
        _tx_out(p, K)

    def busy():
        # the units: build into the buffer, then write them out tagged
        p.ld(4, K["spos"])
        p.ld(5, K["send"])
        p.ipass(12, 5)
        p.iop(5, 12, "-", 4)                  # what is left
        p.iconst(12, SM.TX_WORDS)
        p.iop(5, 5, "MIN", 12)
        p.st(K["cnt"], 5)
        p.iconst(6, SM.TX_MAGIC)
        p.st(SM.LINK_BUF, 6)
        p.ld(6, K["sseq"])
        p.iconst(12, 0xFFFF)
        p.iop(6, 6, "AND", 12)
        p.st(SM.LINK_BUF + 4, 6)
        p.iop(7, 4, "AND", 12)
        p.st(SM.LINK_BUF + 8, 7)
        p.lsh(7, 4, -16)
        p.st(SM.LINK_BUF + 12, 7)
        p.st(SM.LINK_BUF + 4 * 62, 5)
        p.lsh(8, 4, 2)                        # the words, from pool + 4 spos
        p.iconst(12, L.pool)
        p.iop(8, 12, "+", 8)
        p.st(K["a"], 8)
        p.iconst(0, 0)
        p.st(K["u"], 0)

        def word():
            p.ld(0, K["u"])
            p.ld(8, K["a"])
            p.seti(1, 8)
            p.ldi(5, 0, 1)
            p.ld(7, K["cnt"])
            p.e("COMP(R0, R7);")
            p._branch(lambda: s32(p.r[0]) >= s32(p.r[7]), "GE", lambda: p.iconst(5, 0), None)
            p.lsh(1, 0, 3)
            p.iconst(12, SM.LINK_BUF + 16)
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.iconst(12, 0xFFFF)
            p.iop(6, 5, "AND", 12)
            p.sti(0, 1, 6)
            p.lsh(6, 5, -16)
            p.sti(1, 1, 6)
            p.ld(8, K["a"])
            p.iconst(12, 4)
            p.iop(8, 12, "+", 8)
            p.st(K["a"], 8)
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(K["u"], 0)
        p.loop(K["v"], SM.TX_WORDS, word)
        _tx_out(p, K)
        # on
        p.ld(4, K["spos"])
        p.ld(5, K["cnt"])
        p.ipass(12, 4)
        p.iop(4, 12, "+", 5)
        p.st(K["spos"], 4)
        p.ld(6, K["sseq"])
        p.iconst(12, 1)
        p.iop(6, 12, "+", 6)
        p.st(K["sseq"], 6)
        p.ld(5, K["send"])
        p.e("COMP(R4, R5);")
        p._branch(lambda: s32(p.r[4]) >= s32(p.r[5]), "GE",
                  lambda: (p.iconst(6, 0), p.st(K["sbusy"], 6)), None)
    p.ifz(0, "EQ", idle, busy)


def _tx_out(p: Prog, K) -> None:
    """LINK_BUF's 64 units: unit 63 the check of the first 63, then each out tagged, unit i
    at frame i >> 1, slot 14 + (i & 1), in this block's page (K['pg'])."""
    if True:
        p.iconst(5, SM.LINK_SEED)             # the check
        p.iconst(0, 0)
        p.st(K["u"], 0)

        def sumup():
            p.ld(0, K["u"])
            p.lsh(1, 0, 2)
            p.iconst(12, SM.LINK_BUF)
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.ldi(2, 0, 1)
            p.ipass(12, 5)
            p.iop(5, 12, "+", 2)
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(K["u"], 0)
        p.loop(K["v"], SM.TX_UNITS - 1, sumup)
        p.iconst(12, 0xFFFF)
        p.iop(5, 5, "AND", 12)
        p.st(SM.LINK_BUF + 4 * 63, 5)
        # out: unit i at frame i >> 1, slot 14 + (i & 1), tagged
        p.iconst(0, 0)
        p.st(K["u"], 0)

        def out():
            p.ld(0, K["u"])
            p.lsh(1, 0, 2)
            p.iconst(12, SM.LINK_BUF)
            p.iop(1, 12, "+", 1)
            p.seti(1, 1)
            p.ldi(2, 0, 1)
            p.lsh(2, 2, 8)
            p.iconst(12, SM.TDM_TAG << 24)
            p.iop(2, 12, "+", 2)
            p.lsh(3, 0, -1)
            p.lsh(3, 3, 6)
            p.iconst(12, 1)
            p.iop(4, 0, "AND", 12)
            p.lsh(4, 4, 2)
            p.ld(5, K["pg"])
            p.ipass(12, 5)
            p.iop(5, 12, "+", 3)
            p.ipass(12, 5)
            p.iop(5, 12, "+", 4)
            p.seti(1, 5)
            p.sti(0, 1, 2)
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(K["u"], 0)
        p.loop(K["v"], SM.TX_UNITS, out)


def verify_step(p: Prog, L: Layout) -> None:
    """VERIFY's work this block: up to VERIFY_CHUNK words of [vpos, vend) into two sums
    (a += w, b += a, mod 2^32); at the end, vdone = the command's sequence."""
    K, C = LK, L.C
    p.ld(4, K["vpos"])
    p.ld(5, K["vend"])
    p.e("COMP(R4, R5);")

    def work():
        p.lsh(6, 4, 2)
        p.iconst(12, L.pool)
        p.iop(6, 12, "+", 6)
        p.seti(4, 6)

        def word():
            p.ld(4, K["vpos"])
            p.ld(5, K["vend"])
            p.e("COMP(R4, R5);")

            def add():
                p.ldpost(6, 4)
                p.ld(7, K["vsum"])
                p.ipass(12, 7)
                p.iop(7, 12, "+", 6)
                p.st(K["vsum"], 7)
                p.ld(8, K["vsum2"])
                p.ipass(12, 8)
                p.iop(8, 12, "+", 7)
                p.st(K["vsum2"], 8)
                p.iconst(12, 1)
                p.iop(4, 12, "+", 4)
                p.st(K["vpos"], 4)
            p._branch(lambda: s32(p.r[4]) < s32(p.r[5]), "LT", add, None)
        p.loop(K["v"], SM.VERIFY_CHUNK, word)
        p.ld(4, K["vpos"])
        p.ld(5, K["vend"])
        p.e("COMP(R4, R5);")
        p._branch(lambda: s32(p.r[4]) >= s32(p.r[5]), "GE",
                  lambda: (p.ld(6, K["vseq"]), p.st(K["vdone"], 6)), None)
    p._branch(lambda: s32(p.r[4]) < s32(p.r[5]), "LT", work, None)


def status(p: Prog, L: Layout) -> None:
    """The recorder's and the fast link's state to the ColdFire: 16 halves in the SPI
    reply's tail, a 32-bit store putting its low half first (docs/sampler.md):
    STATUS_MAGIC | state, the last command's sequence, frames / 32, the peak x 32767,
    the link's packet count; v0.16: TDM packets in (good), the last one's sequence, TDM
    packets out, a SEND running, TDM packets refused; five zeros; a check (0x1D0F + the
    fifteen, 16 bits). Into both reply pages."""
    C, K = L.C, LK
    h = []
    for k, (addr, scale) in enumerate(((C["rst"], None), (C["rseq"], None), (C["rpos"], -6),
                                       (C["rpk"], "peak"), (C["pres"], None), (K["good"], None),
                                       (K["lseq"], None), (K["sseq"], None), (K["sbusy"], None),
                                       (K["nbad"], None), (K["vsum"], None), (K["vsum"], -16),
                                       (K["vsum2"], None), (K["vsum2"], -16), (K["vdone"], None))):
        p.ld(0, addr)
        if scale == "peak":
            p.fconst(12, 32767.0)
            p.fop(0, 0, "*", 12)
            p.trunc(0, 0)
        elif scale is not None:
            p.lsh(0, 0, scale)
        if k == 0:
            p.iconst(12, SM.STATUS_MAGIC)
            p.iop(0, 12, "+", 0)
            p.ld(1, C["pvn"])                     # v0.25: + 16 while a preview plays
            p.iconst(12, 0)
            p.iop(1, 1, "MAX", 12)
            p.iconst(12, 1)
            p.iop(1, 1, "MIN", 12)
            p.lsh(1, 1, 4)
            p.ipass(12, 0)
            p.iop(0, 12, "+", 1)
        p.iconst(12, 0xFFFF)
        p.iop(0, 0, "AND", 12)
        p.st(SM.LINK_BUF + 0x300 + 4 * k, 0)      # staged halves (the buffer's spare end)
        h.append(SM.LINK_BUF + 0x300 + 4 * k)
    p.iconst(5, SM.LINK_SEED)
    for a in h:
        p.ld(0, a)
        p.ipass(12, 5)
        p.iop(5, 12, "+", 0)
    p.iconst(12, 0xFFFF)
    p.iop(5, 5, "AND", 12)                      # h15
    words = []
    for k in range(8):
        lo = h[2 * k] if 2 * k < len(h) else None
        hi = h[2 * k + 1] if 2 * k + 1 < len(h) else None
        words.append((lo, hi))
    for page in SM.REPLY_PAGES:
        a = page + SM.REPLY_TAIL
        for k, (lo, hi) in enumerate(words):
            if k == 7:                            # h14, then h15 = the check
                p.ld(6, lo)
                p.lsh(7, 5, 16)
                p.ipass(12, 7)
                p.iop(6, 12, "+", 6)
            else:
                p.iconst(6, 0)
                if lo is not None:
                    p.ld(6, lo)
                if hi is not None:
                    p.ld(7, hi)
                    p.lsh(7, 7, 16)
                    p.ipass(12, 7)
                    p.iop(6, 12, "+", 6)
            p.st(a + 4 * k, 6)


def run_recorder(L: Layout, mem):
    """the block's front, as the DSP runs it before the voices: the fast link in, the
    recorder (and its status), the fast link out"""
    p = Prog("run", mem=mem)
    tdm_rx(p, L)
    verify_step(p, L)
    recorder(p, L)
    probe(p, L)
    tdm_tx(p, L)
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
    tdm_rx(p, L)
    verify_step(p, L)
    recorder(p, L)
    probe(p, L)
    tdm_tx(p, L)
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
    from ..perc import guard as G
    G.around(p, L.C["t"], G.COST_SMP, PP.BUFFERS, lambda: voice(p, L))   # v0.27: if it fits in the frame
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


# -- v0.25: the recorder's preview, after the engine's mix -----------------------------------
# The per-block driver calls 0x1c9d3f (the master mix at MIX_BUF into the SPORT page) at
# sw 0x1c9fd2 with `CJUMP 0x1c9d3f (DB)` and its two delay-slot instructions (the C call's
# pushes). The build puts `JUMP wr_pvmix` there (dnfw.waverider.dsp.PVMIX_SITE_SW);
# wr_pvmix adds the preview's next 32 frames to both sides of the mix, then performs the
# displaced call itself: its last three instructions are the stock's own, copied in by the
# build over PVMIX_TAIL (dsp.pvmix_object), so the call, its pushes and its return are the
# stock's. Every register it uses is saved first and restored after, ASTAT included.
PVMIX_TAIL = (0x5A5A0001, 0x5A5A0002, 0x5A5A0003)    # `R0 = TAIL[k];`: 48-bit placeholders
PVMIX_SAVE = (0, 1, 2, 3, 12, 13)


def pvmix(p: Prog, L: Layout) -> None:
    """MIX_BUF += frames [pva, pva + 2 min(pvn, 16)) of the preview (int16 pairs, the low
    half first), on L and R alike; pva and pvn move on. Uses R0..R3, R12, R13, I1."""
    C = L.C
    p.ld(0, C["pvn"])
    p.iconst(12, 0)

    def some():
        p.iconst(0, 0)
        p.st(C["pvk"], 0)

        def word():
            p.ld(1, C["pvk"])
            p.ld(2, C["pvn"])

            def one():
                p.lsh(12, 1, 2)
                p.ld(13, C["pva"])
                p.iop(13, 13, "+", 12)
                p.seti(1, 13)
                p.ldi(2, 0, 1)                # two frames
                p.lsh(3, 2, 16)               # the first (low half) on top
                p.iconst(12, 0xFFFF0000 - (1 << 32))
                p.iop(2, 2, "AND", 12)        # the second, on top
                p.iconst(12, -31)
                p.float_(3, 3, 12)            # int16 / 32768
                p.float_(2, 2, 12)
                p.lsh(12, 1, 3)
                p.iconst(13, SM.MIX_BUF)
                p.iop(13, 13, "+", 12)        # frames 2k and 2k + 1, L; R at + 32 words
                p.seti(1, 13)
                for k, x in ((0, 3), (1, 2), (32, 3), (33, 2)):
                    p.ldi(0, k, 1)
                    p.fop(0, 0, "+", x)
                    p.sti(k, 1, 0)
                p.ld(1, C["pvk"])
            p.if_(1, "LT", 2, one, kind="i")
            p.iconst(12, 1)
            p.ipass(13, 1)
            p.iop(1, 13, "+", 12)
            p.st(C["pvk"], 1)
        _loop16(p, C, word)
        p.ld(0, C["pvn"])                     # on: 16 words, or what was left
        p.iconst(12, 16)
        p.iop(1, 0, "MIN", 12)
        p.iop(0, 0, "-", 1)
        p.st(C["pvn"], 0)
        p.lsh(1, 1, 2)
        p.ld(13, C["pva"])
        p.iop(13, 13, "+", 1)
        p.st(C["pva"], 13)
    p.if_(0, "GT", 12, some, kind="i")


def _loop16(p: Prog, C, body) -> None:
    """for 16 times body(); the count in pvk (body() counts it up from 0)"""
    top = p.label("pv")
    p.place(top)
    if p.run:
        while True:
            body()
            if p.mem.get(C["pvk"]) >= 16:
                return
    body()
    p.ld(0, C["pvk"])
    p.iconst(12, 16)
    p.e("COMP(R0, R12);")
    p.jump("LT", top)


def pvmix_program(L: Layout, prefix: str = "pv") -> str:
    """pvmix.asm: the driver's JUMP at PVMIX_SITE_SW comes here; on to the stock call."""
    C = L.C
    p = Prog("emit", prefix=prefix)
    p.raw("// pvmix.asm -- the recorder's preview, added to the main mix after the engine")
    p.raw("// (docs/sampler.md, v0.25). GENERATED by scripts/gen_smp_asm.py from")
    p.raw("// dnfw.sampler.program.pvmix; do not edit by hand.")
    p.raw("")
    p.raw(".SECTION/PM seg_pmco;")
    p.raw("")
    p.raw(".GLOBAL wr_pvmix.;")
    p.raw("wr_pvmix.:")
    for r in PVMIX_SAVE:
        p.st(C[f"pvs{r}"], r)
    p.e(f"DM({C['pvsi']:#x}) = I1;")
    p.e(f"DM({C['pvsa']:#x}) = ASTAT;")
    pvmix(p, L)
    p.e(f"ASTAT = DM({C['pvsa']:#x});")
    p.e(f"I1 = DM({C['pvsi']:#x});")
    for r in PVMIX_SAVE:
        p.ld(r, C[f"pvs{r}"])
    for w in PVMIX_TAIL:                      # the stock call, copied in by the build
        p.e(f"R0 = {w:#x};", "placeholder: the stock instruction")
    # the call returns here when it returns through the PC stack (a CJUMP's return
    # address is the instruction after its delay slots): on as stock, after them
    p.e("JUMP 0x1c9fdb;", "the driver, after its call of 0x1c9d3f")
    p.emit_subs()
    p.raw(".wr_pvmix..end:")
    p.raw("      .type wr_pvmix.,STT_FUNC;")
    return p.text()


def pvmix_run(L: Layout, mem) -> Prog:
    p = Prog("run", mem=mem)
    pvmix(p, L)
    return p

"""PERC's whole DSP program: the type-5 loop (in Waverider's former place), one voice a
slot, the machines (dnfw.perc.machines), written once for both backends (dnfw.perc.dsl).

`voice(p, L, t)` is one slot's block -- what run mode executes as the model, and what the
SHARC runner holds the assembled code to. `program(L, ...)` adds the loop around it: the
register save the per-track chain expects (PING's tail restores it), the 16 slots, and the
jump on to RESONATOR's entry.
"""

from __future__ import annotations

import math

from . import kit as K
from . import machines as M
from .dsl import Prog

SAVE = 0x2DDE00                          # the save area PING's tail restores from
SAVE_REGS = [f"R{k}" for k in range(16)] + ["I0", "I1", "I2", "I3", "I4", "I5", "I12",
                                            "M0", "M1", "M2", "M3", "M4"]
NOTE_CELLS = 0x254B14
TRIG_WORD = 0x25C4AC
BUFFERS = 0x254A60
RECORDS, RECORD_STRIDE = 0x2554B8, 0x234
MACHINE_TYPE = 5
SEED = 0x2545F491
OFF_LEVEL = 0.0002


def t146(p: Prog, d: int, t: int) -> None:
    """Rd = 146 Rt. Clobbers R12, R13."""
    p.lsh(12, t, 7)
    p.lsh(13, t, 4)
    p.iop(12, 12, "+", 13)
    p.lsh(13, t, 1)
    p.iop(d, 12, "+", 13)


def half(p: Prog, d: int, off: int, k146: int) -> None:
    """Rd = the frame copy's 16-bit word at offset OFF for this slot (Rk146 = 146 t).
    Clobbers R0, R1, R12, I1."""
    p.iconst(12, M.FRAME + off)
    p.iop(0, 12, "+", k146)
    p.iconst(12, 2)
    p.iop(1, 0, "AND", 12)
    p.iconst(12, -4)
    p.iop(0, 0, "AND", 12)
    p.seti(1, 0)
    p.ldi(d, 0, 1)
    p.ifz(1, "NE", lambda: p.lsh(d, d, -16))
    p.iconst(12, 0xFFFF)
    p.iop(d, d, "AND", 12)


def voice(p: Prog, L: M.Layout, t: int | None = None) -> None:
    """One slot's block. In run mode T is the slot (also stored at C['t']); in emit mode
    the slot is read from C['t']."""
    C = L.C
    if p.run:
        p.iconst(9, t)
        p.st(C["t"], 9)
    p.ld(9, C["t"], "t")
    p.lsh(12, 9, 7)
    p.iconst(11, L.state)
    p.iop(12, 11, "+", 12)
    p.seti(2, 12, "this slot's state")
    p.st(C["sbase"], 12)
    # the trigger
    p.ld(0, TRIG_WORD)
    p.lsh(0, 0, -16)
    p.iconst(1, 1)
    p.ld(9, C["t"])
    _shift_by(p, 1, 9)
    p.iop(0, 0, "AND", 1)
    p.st(C["trig"], 0)
    # TYPE and the eight parameters from the frame
    p.ld(9, C["t"])
    t146(p, 10, 9)
    half(p, 4, M.frame_offset(M.TYPE_REC[1]), 10)
    p.lsh(4, 4, -8)
    p.iconst(12, 127)
    p.iop(4, 4, "MIN", 12)
    p.lsh(5, 4, 4)
    p.lsh(6, 4, 3)
    p.ipass(12, 5)
    p.iop(4, 12, "+", 6)
    p.lsh(4, 4, -7)
    p.st(C["type"], 4)
    for k, (_rid, slot, lo, top) in enumerate(M.PARAMS + M.FX_PARAMS):
        half(p, 4, M.frame_offset(slot), 10)
        p.lsh(4, 4, -8)
        p.iconst(12, -lo)
        p.iop(4, 12, "+", 4)
        p.iconst(12, 0)
        p.iop(4, 4, "MAX", 12)
        p.iconst(12, top)
        p.iop(4, 4, "MIN", 12)
        p.iconst(12, 0)
        p.float_(5, 4, 12)
        p.fconst(12, 1.0 / top)
        p.fop(5, 5, "*", 12)
        p.st(C[f"p{k}" if k < 8 else f"q{k - 8}"], 5)
    # the note: machine5_live's validation, then the transpose 2^((note - 60) / 12)
    p.ld(9, C["t"])
    p.lsh(12, 9, 2)
    p.iconst(11, NOTE_CELLS)
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
    M.exp2(p, L, 9, 8)
    p.st(C["tr"], 9)
    # a note: the voice starts afresh on the machine TYPE names now
    p.ld(0, C["trig"])

    def start():
        M.v(p, 5, "rng")

        def seed():
            p.ld(9, C["t"])
            p.lsh(9, 9, 20)
            p.iconst(12, SEED)
            p.iop(5, 12, "+", 9)
        p.ifz(5, "EQ", seed)
        p.iconst(0, 0)
        for k in range(M.STATE_WORDS):
            p.sti(k, 2, 0)
        M.vs(p, "rng", 5)
        p.iconst(0, 1)
        M.vs(p, "on", 0)
        p.fconst(0, 1.0)
        for w in ("aenv", "penv", "nenv", "menv", "xenv"):
            M.vs(p, w, 0)
        p.ld(0, C["type"])
        M.vs(p, "mach", 0)
    p.ifz(0, "NE", start)
    # the slot's buffer
    p.ld(9, C["t"])
    p.lsh(12, 9, 2)
    p.iconst(11, BUFFERS)
    p.iop(12, 11, "+", 12)
    p.seti(1, 12)
    p.ldi(0, 0, 1)
    p.seti(4, 0, "the slot's buffer")
    p.st(C["buf"], 0)
    M.v(p, 0, "on")

    def silent():
        p.iconst(6, 0)
        p.loop(C["count"], 32, lambda: p.stpost(4, 6))

    def sounding():
        dispatch(p, L)
        fx(p, L)
        # done when the drum has died away
        M.v(p, 4, "t")
        p.fconst(12, 0.02)

        def late():
            M.v(p, 5, "aenv")
            p.fconst(12, OFF_LEVEL)
            p.if_(5, "LT", 12, lambda: (p.iconst(0, 0), M.vs(p, "on", 0)))
        p.if_(4, "GT", 12, late)
        M.v(p, 4, "t")
        p.fconst(12, 30.0)
        p.if_(4, "GT", 12, lambda: (p.iconst(0, 0), M.vs(p, "on", 0)))
    p.ifz(0, "EQ", silent, sounding)


def fx(p: Prog, L: M.Layout) -> None:
    """The Machinedrum's track effects on the block the machine just wrote (rv_perc.c
    perc_render): amplitude modulation, a one-band peaking EQ, a high pass and a low pass
    (the band filter). Each runs only when its control turns it on; at the records'
    defaults none does and the block is left as it is. Linear, so run after the machine's
    trim rather than before it."""
    C = L.C
    one = 12

    def q(d, k):
        p.ld(d, C[f"q{k}"])

    # AM: depth, and the phase step a sample (0.1 Hz .. 2.3 kHz)
    q(4, 0)
    p.st(C["amd"], 4)
    p.iconst(5, 0)
    p.st(C["fxam"], 5)
    p.fconst(6, 0.0)
    p.if_(4, "GT", 6, lambda: (p.iconst(5, 1), p.st(C["fxam"], 5)))
    q(8, 1)
    p.fconst(one, 14.5)
    p.fop(8, 8, "*", one)
    M.exp2(p, L, 8, 8)
    p.fconst(one, 0.1 * M.DT)
    p.fop(8, 8, "*", one)
    p.st(C["amdt"], 8)
    # EQ: gain in dB, (EQG - 0.5) x 36: +-18, 0 at the record's default
    q(4, 3)
    p.fconst(one, 0.5)
    p.fop(4, 4, "-", one)
    p.fconst(one, 36.0)
    p.fop(4, 4, "*", one)
    p.st(C["tmp"], 4)
    p.iconst(5, 0)
    p.st(C["fxeq"], 5)

    def eq_on():
        p.iconst(5, 1)
        p.st(C["fxeq"], 5)
        p.ld(4, C["tmp"])
        p.fconst(one, 0.1661)
        p.fop(4, 4, "*", one)
        M.exp2(p, L, 9, 4)
        p.fconst(one, 1.0)
        p.fop(9, 9, "-", one)
        p.st(C["eqm"], 9)                   # 2^(eqg 0.1661) - 1
        q(8, 2)
        p.fconst(one, 8.9)
        p.fop(8, 8, "*", one)
        M.exp2(p, L, 8, 8)
        p.fconst(one, 40.0)
        p.fop(8, 8, "*", one)                # 40 .. 19 kHz
        M.svf_set(p, L, 3, 8, qc=1.2)
        p.ld(9, C["eqm"])
        p.ld(10, C["s3k"])
        p.fop(9, 9, "*", 10)
        p.st(C["eqm"], 9)                   # eq.k (2^(eqg 0.1661) - 1)
    p.fconst(one, 0.2)
    p.if_(4, "GT", one, eq_on, lambda: (p.fconst(one, -0.2), p.if_(4, "LT", one, eq_on)))
    # the band filter: base FLTF, width FLTW, q 0.5 + FLTQ^2 x 12 / 16129 (0..127 each)
    q(4, 4)
    p.fconst(one, 127.0)
    p.fop(4, 4, "*", one)
    p.st(C["y"], 4)                          # e13
    q(5, 5)
    p.fop(5, 5, "*", one)
    p.st(C["ns"], 5)                         # e14
    q(6, 6)
    p.fop(6, 6, "*", one)
    p.fop(6, 6, "*", 6)
    p.fconst(one, 12.0 / 16129.0)
    p.fop(6, 6, "*", one)
    p.fconst(one, 0.5)
    p.fop(6, 6, "+", one)
    p.st(C["tmp2"], 6)                       # fq
    p.iconst(7, 0)
    p.st(C["fxhp"], 7)
    p.st(C["fxlp"], 7)

    def hp_on():
        p.iconst(7, 1)
        p.st(C["fxhp"], 7)
        p.ld(8, C["y"])
        p.fconst(one, 10.0 / 127.0)
        p.fop(8, 8, "*", one)
        M.exp2(p, L, 8, 8)
        p.fconst(one, 20.0)
        p.fop(8, 8, "*", one)
        p.ld(6, C["tmp2"])
        M.svf_set(p, L, 4, 8, q=6)
    p.ld(4, C["y"])
    p.fconst(one, 0.5)
    p.if_(4, "GE", one, hp_on)

    def lp_on():
        p.iconst(7, 1)
        p.st(C["fxlp"], 7)
        p.ld(8, C["y"])
        p.ld(5, C["ns"])
        p.fop(8, 8, "+", 5)
        p.fconst(one, 127.0)
        p.fop(8, 8, "MIN", one)
        p.fconst(9, 0.0)
        p.fop(8, 8, "MAX", 9)
        p.fconst(one, 10.0 / 127.0)
        p.fop(8, 8, "*", one)
        M.exp2(p, L, 8, 8)
        p.fconst(one, 20.0)
        p.fop(8, 8, "*", one)
        p.ld(6, C["tmp2"])
        M.svf_set(p, L, 5, 8, q=6)
    p.ld(5, C["ns"])
    p.fconst(one, 126.5)
    p.if_(5, "LE", one, lp_on)
    # anything on? then once more through the block
    p.ld(0, C["fxam"])
    p.ld(1, C["fxeq"])
    p.iop(0, 0, "OR", 1)
    p.ld(1, C["fxhp"])
    p.iop(0, 0, "OR", 1)
    p.ld(1, C["fxlp"])
    p.iop(0, 0, "OR", 1)

    def run():
        p.ld(0, C["buf"])
        p.seti(4, 0, "the slot's buffer, again")

        def sample():
            p.ldi(0, 0, 4)
            p.st(C["fxy"], 0)

            def am():
                M.v(p, 13, "amph")
                p.ld(12, C["amdt"])
                p.fop(13, 13, "+", 12)
                M.frac(p, 13)
                M.vs(p, "amph", 13)
                M.sin_(p, L, 9, 13)
                p.fconst(12, 0.5)
                p.fop(9, 9, "*", 12)
                p.fop(9, 12, "-", 9)            # 0.5 - 0.5 sin
                p.ld(10, C["amd"])
                p.fop(9, 10, "*", 9)
                p.fconst(12, 1.0)
                p.fop(9, 12, "-", 9)
                p.ld(0, C["fxy"])
                p.fop(0, 0, "*", 9)
                p.st(C["fxy"], 0)
            p.ld(5, C["fxam"])
            p.ifz(5, "NE", am)

            def eq():
                p.ld(0, C["fxy"])
                M.svf_tick(p, L, 3)
                p.ld(12, C["eqm"])
                p.fop(2, 2, "*", 12)
                p.ld(0, C["fxy"])
                p.fop(0, 0, "+", 2)
                p.st(C["fxy"], 0)
            p.ld(5, C["fxeq"])
            p.ifz(5, "NE", eq)

            def hp():
                p.ld(0, C["fxy"])
                M.svf_tick(p, L, 4, hp=True)
                p.st(C["fxy"], 3)
            p.ld(5, C["fxhp"])
            p.ifz(5, "NE", hp)

            def lp():
                p.ld(0, C["fxy"])
                M.svf_tick(p, L, 5)
                p.st(C["fxy"], 1)
            p.ld(5, C["fxlp"])
            p.ifz(5, "NE", lp)
            p.ld(0, C["fxy"])
            p.stpost(4, 0)
        M.samples(p, L, sample)
    p.ifz(0, "NE", run)


def _shift_by(p: Prog, d: int, s: int) -> None:
    """Rd = LSHIFT Rd BY Rs."""
    p.e(f"R{d} = LSHIFT R{d} BY R{s};")
    if p.run:
        n = p.r[s] & 0xFF
        assert n < 32
        p.setR(d, p.r[d] << n)


def dispatch(p: Prog, L: M.Layout) -> None:
    """The machine the voice latched at its note: a chain of compares to its setup, then
    its family's loop (each loop emitted once, after the chain), then on past them."""
    if p.run:
        M.v(p, 0, "mach")
        name = M.NAMES[min(p.r[0], M.N - 1)]
        setup, loop = K.MACHINE[name]
        setup(p, L, name)
        K.LOOPS[loop](p, L)
        return
    end = p.label("vend")
    loops: dict[str, str] = {}
    for k, name in enumerate(M.NAMES):
        setup, loop = K.MACHINE[name]
        lab = loops.setdefault(loop, p.label(f"loop_{loop}"))
        nxt = p.label("mnext")
        if k < M.N - 1:
            M.v(p, 0, "mach")
            p.iconst(12, k)
            p.e("COMP(R0, R12);")
            p.jump("NE", nxt)
        p.comment(f"---- {name} ----")
        setup(p, L, name)
        p.jump("", lab)
        p.place(nxt)
    for loop, lab in loops.items():
        p.place(lab)
        K.LOOPS[loop](p, L)
        p.jump("", end)
    p.place(end)


def program(L: M.Layout, rings_sw: int, prefix: str = "pk") -> str:
    """perc.asm: entered by the block counter's JUMP (in machine5_live's former place)."""
    p = Prog("emit", prefix=prefix)
    p.raw("// perc.asm -- PERC, machine type 5 (docs/perc.md): the owner's Ravel PERC machines")
    p.raw("// (TRX, EFM, GND) on the DN2's DSP. GENERATED by scripts/gen_perc_asm.py from")
    p.raw("// dnfw.perc (one program for this text and its model); do not edit by hand.")
    p.raw("")
    p.raw(".SECTION/PM seg_pmco;")
    p.raw("")
    p.raw(".GLOBAL wr_perc.;")
    p.raw("wr_perc.:")
    for k, r in enumerate(SAVE_REGS):
        p.e(f"DM({SAVE + 4 * k:#x}) = {r};")
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
    p.iconst(11, RECORDS)
    p.iop(12, 11, "+", 12)
    p.seti(4, 12, "record: 0x2554b8 + 0x234 t")
    p.ldi(0, 109, 4, "the record's machine type (+0x1b4)")
    p.iconst(12, MACHINE_TYPE)
    p.e("COMP(R0, R12);")
    other = p.label("other")
    p.jump("NE", other)
    voice(p, L)
    p.jump("", nxt)
    # not PERC: its voice is silenced, so a track that comes back to PERC starts clean
    # (v0.12: v0.11 resumed what it had left ringing)
    p.place(other)
    p.ld(9, L.C["t"])
    p.lsh(12, 9, 7)
    p.iconst(11, L.state)
    p.iop(12, 11, "+", 12)
    p.seti(2, 12)
    p.iconst(0, 0)
    M.vs(p, "on", 0)
    p.place(nxt)
    p.ld(0, L.C["t"])
    p.iconst(12, 1)
    p.iop(0, 12, "+", 0)
    p.st(L.C["t"], 0)
    p.iconst(12, 16)
    p.e("COMP(R0, R12);")
    p.jump("LT", top)
    p.e(f"JUMP {rings_sw:#x};", "rings.asm's wr_rings, then CZ, then PING (which restores)")
    p.emit_subs()
    p.raw(".wr_perc..end:")
    p.raw("      .type wr_perc.,STT_FUNC;")
    return p.text()


def run_voice(L: M.Layout, read, t: int, mem=None):
    """The model: one slot's block, on memory READ (and MEM's earlier writes, carried
    across blocks). -> (Prog, its memory)."""
    from .dsl import Mem
    mem = mem or Mem(read)
    p = Prog("run", mem=mem)
    voice(p, L, t)
    return p, mem

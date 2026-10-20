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
    for k, (_rid, slot, lo, top) in enumerate(M.PARAMS):
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
        p.st(C[f"p{k}"], 5)
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
    M.v(p, 0, "on")

    def silent():
        p.iconst(6, 0)
        p.loop(C["count"], 32, lambda: p.stpost(4, 6))

    def sounding():
        dispatch(p, L)
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
    p.jump("NE", nxt)
    voice(p, L)
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

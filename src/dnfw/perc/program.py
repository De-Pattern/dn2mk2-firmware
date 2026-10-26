"""PERC's whole DSP program: the type-5 loop (in Waverider's former place), one voice a
slot, the machines (dnfw.perc.machines), written once for both backends (dnfw.perc.dsl).

`voice(p, L, t)` is one slot's block -- what run mode executes as the model, and what the
SHARC runner holds the assembled code to. `program(L, ...)` adds the loop around it: the
register save the per-track chain expects (PING's tail restores it), the 16 slots, and the
jump on to RESONATOR's entry.
"""

from __future__ import annotations

import math

from . import machines as M
from .dsl import Prog
from ..md import voice as MDV

MD_LEVEL = 1.4                            # the Machinedrum's full scale on a DN2 track: v0.22 +6 dB (0.7 in v0.17..v0.21),
                                          # its default hits as loud as WaveTone's and FM Tone's default notes

SAVE = 0x2DDE00                          # the save area PING's tail restores from
SAVE_REGS = [f"R{k}" for k in range(16)] + ["I0", "I1", "I2", "I3", "I4", "I5", "I12",
                                            "M0", "M1", "M2", "M3", "M4"]
NOTE_CELLS = 0x254B14
TRIG_WORD = 0x25C4AC
BUFFERS = 0x254A60
RECORDS, RECORD_STRIDE = 0x2554B8, 0x234
MACHINE_TYPE = 5
# v0.26: the Monomachine's synth machines (docs/mnm.md), each its own machine type, in PERC's
# voice: type -> index in dnfw.mnm.machines.MACHINES
MNM_TYPES = {6: 0, 7: 1}                 # SID 6581, DPRO-WAVE (CZ's and RESONATOR's types until v0.25)
MNM_LEVEL = 0.25                         # a Monomachine machine's full scale on a DN2 track
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


def raw_type(p: Prog, d: int) -> None:
    """Rd = this slot's machine type as the ColdFire sent it: the frame's header word at
    148 + 2 t (v0.13). The record's copy (+0x1b4) is the lookup's answer, which is 5 for
    PERC and for every sample machine (types 8..12 borrow PERC's engine slot, the one
    path through the stock code the runner and the instrument have proven), so the frame
    word tells them apart. Needs C['t'] in R9; clobbers R0, R1, R10, R12, I1."""
    p.iop(10, 9, "+", 9)
    half(p, d, 148, 10)


def voice(p: Prog, L: M.Layout, t: int | None = None) -> None:
    """One slot's block. In run mode T is the slot (also stored at C['t']); in emit mode
    the slot is read from C['t']."""
    C = L.C
    if p.run:
        p.iconst(9, t)
        p.st(C["t"], 9)
    # v0.26: which Monomachine machine (index + 1), 0 for PERC, from the frame's type word
    p.ld(9, C["t"], "t")
    raw_type(p, 2)
    p.iconst(0, 0)
    for typ, k in MNM_TYPES.items():
        p.iconst(12, typ)
        p.if_(2, "EQ", 12, lambda k=k: p.iconst(0, k + 1), kind="i")
    p.st(C["mnm"], 0)
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
    p.iconst(12, 0)
    p.float_(4, 4, 12)
    p.fconst(12, MDV.N / 128.0)               # 0..127 over the machines (v0.17)
    p.fop(4, 4, "*", 12)
    p.trunc(4, 4)
    p.ld(5, C["mnm"])                         # v0.26: a Monomachine machine's type picks it
    p.ifz(5, "NE", lambda: (p.iconst(12, MDV.N - 1), p.iop(4, 12, "+", 5)))
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
    # the Machinedrum machine (v0.17, docs/md.md): its slot's words at I3
    p.ld(9, C["t"])
    p.lsh(12, 9, 10)
    p.iconst(11, L.md.state)
    p.iop(12, 11, "+", 12)
    p.seti(3, 12, "this slot's Machinedrum words")
    p.st(L.md.C["mdb"], 12)
    # the slot's buffer
    p.ld(9, C["t"])
    p.lsh(12, 9, 2)
    p.iconst(11, BUFFERS)
    p.iop(12, 11, "+", 12)
    p.seti(1, 12)
    p.ldi(0, 0, 1)
    p.seti(4, 0, "the slot's buffer")
    p.st(C["buf"], 0)
    # a slot that has just become PERC starts clean, playing nothing until its first note
    M.v(p, 0, "on")

    def fresh():
        MDV.reset(p, L.md)
        p.iconst(0, 1)
        M.vs(p, "on", 0)
    p.ifz(0, "EQ", fresh)
    # the level, and for a Monomachine machine the note (float semitones, as RESONATOR reads it)
    p.fconst(0, MD_LEVEL)
    p.st(C["lev"], 0)
    p.ld(0, C["mnm"])

    def mnm_note():
        from ..mnm import core as MNC
        p.fconst(0, MNM_LEVEL)
        p.st(C["lev"], 0)
        p.ld(9, C["t"])
        p.lsh(12, 9, 2)
        p.iconst(11, NOTE_CELLS)
        p.iop(12, 11, "+", 12)
        p.seti(1, 12)
        p.ldi(8, 0, 1)
        p.lsh(12, 8, -23)
        p.iconst(13, 0xFF)
        p.iop(12, 12, "AND", 13)
        p.if_(12, "EQ", 13, lambda: p.iconst(8, 0), kind="i")    # NaN, infinite: 0
        p.ifz(8, "LT", lambda: p.iconst(8, 0))                    # negative: 0
        MNC.vws(p, "pitch", 8)
    p.ifz(0, "NE", mnm_note)
    p.ld(2, C["trig"])
    p.ld(5, C["type"])
    MDV.block(p, L.md, [C[f"p{k}"] for k in range(8)], 2, 5, level_word=C["lev"])
    p.ld(12, C["sbase"])
    p.seti(2, 12, "this slot's state, again")
    p.ld(0, C["mnm"])
    p.ifz(0, "EQ", lambda: fx(p, L))          # the Machinedrum's track effects: PERC's only


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


def program(L: M.Layout, rings_sw: int, prefix: str = "pk") -> str:
    """perc.asm: entered by the block counter's JUMP (in machine5_live's former place)."""
    p = Prog("emit", prefix=prefix)
    p.spill = L.md.C["ash"]
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
    from ..md import core as MDK
    MDK.table_fill(p, L.md)                    # the Machinedrum's sine and tables, 1024 words a block until whole (v0.24: zpack)
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
    raw_type(p, 2)
    for typ in MNM_TYPES:                     # v0.26: a Monomachine machine is PERC's voice too
        p.iconst(12, typ)
        p.if_(2, "EQ", 12, lambda: p.iconst(2, MACHINE_TYPE), kind="i")
    p.ipass(0, 2)
    p.iconst(12, MACHINE_TYPE)
    p.e("COMP(R0, R12);")
    other = p.label("other")
    p.jump("NE", other)
    p.ld(0, L.md.C["fill"])                   # v0.26: silent until the tables (sent by the
    p.iconst(12, MDK.Z_N)                     # ColdFire at power-on) are decoded
    p.e("COMP(R0, R12);")
    p.jump("LT", other)
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
    p.e(f"JUMP {rings_sw:#x};", "smp.asm's wr_smp, then PING (which restores)")
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
    p.spill = L.md.C["ash"]
    voice(p, L, t)
    return p, mem

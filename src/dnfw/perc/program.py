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
from ..md import core as MDK

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
from ..mnm import machines as _mnm_types   # noqa: E402
MNM_TYPES = {t: k for k, t in enumerate(_mnm_types.TYPES)}   # 6, 7 (CZ's and RESONATOR's until v0.25), 14..
MNM_LEVEL = 0.25                         # a Monomachine machine's full scale on a DN2 track
# v0.27: each machine's own (owner: MNM-1 was quiet). 0.25 put SID's default sound at a peak
# of 0.046 on its track's buffer, DPRO Wave's 0.022, DDRW's 0.26, DENS's 0.13, VO-6's 0.015,
# where the Machinedrum machines peak at 1.0..1.4 (the model, 2026-10-27); each now peaks
# about 1.0 at its defaults. MODULES order (SID, WAVE, DDRW, DENS, VO-6).
MNM_LEVELS = (5.4, 11.5, 0.95, 2.0, 16.5)
# v0.26: the DSP's room for the Monomachine voices. They never go quiet (as on the
# Monomachine, a voice plays until the next note), and one costs as much as two to ten of
# the Machinedrum's, so each block they are rendered in track order while their cost (the
# instructions a DN2 block takes, measured in the model at the most each can take,
# test_perc_live) fits MNM_BUDGET; a track past it plays silence that block. About half of
# what the SHARC has free beside the stock engines (docs/sharc-load.md: ~250,000 cycles).
MNM_COST = {"SID 6581": 60_000, "DPRO-WAVE": 34_000, "DPRO-DDRW": 78_000, "DPRO-DENS": 70_000,
            "VO-6": 75_000}
# v0.36: no longer the limit (the owner and misterairplane: two voices at most on a Monomachine
# track). 150,000 fitted 2 SID / VO-6 / DENS and 1 DDRW whatever the DSP's real time; it came
# before the frame guard (v0.27), which measures the frame and leaves out (v0.36: steals) the
# oldest voices that do not fit. Kept as a ceiling far above what sixteen voices can reach.
MNM_BUDGET = 1_000_000
# v0.29: which Monomachine voices get the budget: the newest first (the owner, 2026-10-28:
# with the DN2's dynamic voice allocation each note lands on a new voice; the older ones,
# which never go quiet, kept the budget in slot order, so most new notes were silent --
# CZ's v0.10 bug again, docs/cz.md). At PERC's entry every slot gets a key, its age in
# blocks (0 the block it is triggered) times 16 plus the slot, or NONE for a slot not on a
# Monomachine machine; a voice plays if the costs of the voices with smaller keys, and its
# own, fit the budget. In the Monomachine scratch's free tail (dnfw.mnm.core uses < 4 KB).
MNM_KEYS_OFF, MNM_COSTS_OFF = 0x3000, 0x3040
# v0.29: and every voice of ours (PERC, the Monomachine's, the sample machines') is rendered
# newest first: the owner's PERC test (TRX-CY, dynamic allocation) heard voices 1-8 and
# then silence -- the ringing older voices took the frame in slot order and the guard
# skipped every newer one. ORDER: the slots by key, the newest first (the ones not ours
# last); PERC's loop and the sample machines' loop walk it (their own index words).
ORDER_OFF, RANK_U, RANK_N, PERC_I, SMP_I = 0x3080, 0x30C0, 0x30C4, 0x30C8, 0x30CC
# v0.29: a Monomachine voice rests once its sound has died away after the AMP envelope (the
# owner: two Monomachine tracks sounding, a third stayed silent -- the budget held by voices
# whose notes had ended long before). At PERC's entry a type-5 track's buffer still holds
# its last block as the chain left it, after AMP (measured in the runner); QUIET_BLOCKS
# blocks under QUIET_LEVEL there, no note, and the voice rests: no cost, silent, until its
# next note. QUIET counts each slot's blocks at RESTS_OFF.
RESTS_OFF = 0x3100
# v0.36: the frame guard's strikes against each slot since its note: a voice left out a second
# time in one note is stolen (rests until its next note); once is a one-block gap (a note's
# first blocks cost the most: DDRW's chord lost three of its four voices to the attack alone)
STRIKES_OFF = 0x3140
STEAL_STRIKES = 2
# each slot's budget sum: the Monomachine costs of the slots with smaller keys and its own (mnm_ages, in a
# block with a Monomachine slot), so a voice's budget reads one word, not sixteen keys and their costs. In
# the scratch's free tail below the keys (dnfw.mnm.core uses < 4 KB)
CUM_OFF = 0x2FC0
assert CUM_OFF + 4 * 16 <= MNM_KEYS_OFF
# mnm_ages' and the slot loop's type tests, a bit a type (every type here is under 32): ours (PERC, the
# Monomachine machines, the sample machines), the Monomachine machines, and the slots PERC's voice plays
from ..sampler import machines as _smx_types   # noqa: E402
OURS_TYPES = (*MNM_TYPES, MACHINE_TYPE, *_smx_types.TYPES)
assert all(0 <= t < 32 for t in OURS_TYPES)
OURS_MASK = sum(1 << t for t in set(OURS_TYPES))
MNM_MASK = sum(1 << t for t in MNM_TYPES)
VOICE_MASK = MNM_MASK | 1 << MACHINE_TYPE
MNM_QUIET_LEVEL = 2.0 ** -16                # -96 dB: an AMP envelope's tail and a filter's are under it
MNM_QUIET_BLOCKS = 64                      # 43 ms
MNM_SCRATCH = 0x200A4000                   # dsp.MNM_SCRATCH_L2 (v0.32: L2; test_waverider_dsp holds them equal)
ORDER = MNM_SCRATCH + ORDER_OFF
MNM_AGE_TOP = (1 << 26) - 1
MNM_NONE = 0x7FFFFFF0
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


assert M.FRAME % 4 == 0


def frame_regs(p: Prog) -> None:
    """For frame_byte, with the slot in R9 and 146 t in R10: I1 = the slot's frame halves' word-aligned
    base (FRAME + 146 t, less 2 for an odd slot), I4 = that + 4 for an odd slot; R13, R14 the shifts that
    bring a record's high byte down for a record at an offset = 0, = 2 (mod 4) (a half at an address = 2
    (mod 4) is a word's upper one, as half() reads it); R11 = 0xFF, R15 = 0. Clobbers R0, R1, R12."""
    p.iconst(12, M.FRAME)
    p.iop(0, 12, "+", 10)
    p.iconst(12, -4)
    p.iop(0, 0, "AND", 12)
    p.seti(1, 0, "the slot's frame words")
    p.iconst(12, 1)
    p.iop(1, 9, "AND", 12)                    # t & 1
    p.lsh(12, 1, 2)
    p.iop(0, 12, "+", 0)
    p.seti(4, 0, "the same, a word on for an odd slot")
    p.lsh(12, 1, 4)                           # 16 (t & 1)
    p.iconst(13, -8)
    p.iop(13, 13, "-", 12)                    # offset = 0 (mod 4): even slot the lower half (-8), odd the upper (-24)
    p.iconst(14, -24)
    p.iop(14, 12, "+", 14)                    # = 2: even slot the upper half (-24), odd the lower (-8)
    p.iconst(11, 0xFF)
    p.iconst(15, 0)


def frame_byte(p: Prog, d: int, slot: int) -> None:
    """Rd = frame record SLOT's high byte for this slot (half() >> 8: the same byte), after frame_regs
    (whose registers it keeps): one load, a shift and a mask, not half()'s address arithmetic."""
    off = M.frame_offset(slot)
    if off & 2:
        p.ldi(d, (off - 2) // 4, 4)
    else:
        p.ldi(d, off // 4, 1)
    MDK._shift_r(p, d, d, 14 if off & 2 else 13)
    p.iop(d, d, "AND", 11)


def raw_type(p: Prog, d: int) -> None:
    """Rd = this slot's machine type as the ColdFire sent it: the frame's header word at
    148 + 2 t (v0.13). The record's copy (+0x1b4) is the lookup's answer, which is 5 for
    PERC and for every sample machine (types 8..12 borrow PERC's engine slot, the one
    path through the stock code the runner and the instrument have proven), so the frame
    word tells them apart. Needs C['t'] in R9; clobbers R0, R1, R10, R12, I1."""
    p.iop(10, 9, "+", 9)
    half(p, d, 148, 10)


def mnm_ages(p: Prog, L: M.Layout) -> None:
    """v0.29: every slot's key and Monomachine cost for this block (MNM_KEYS_OFF), and the
    slots in key order (ORDER_OFF), and, in a block with a Monomachine slot, the budget sums
    (CUM_OFF). RANK_U is left at 16 and RANK_N at 0, as the ordering loop left them. Clobbers
    R0-R15, I1, I4."""
    from ..mnm import machines as MNM
    keys = L.md.mnm.scratch + MNM_KEYS_OFF
    costs = L.md.mnm.scratch + MNM_COSTS_OFF
    p.ld(3, TRIG_WORD)
    p.lsh(3, 3, -16)                           # the slots' note triggers
    p.iconst(15, 0)                            # R15: a Monomachine slot this block (for the budget sums)
    for u in range(16):
        p.iconst(10, 2 * u)
        half(p, 2, 148, 10)                    # the slot's machine type, as raw_type
        p.iconst(4, 0)
        p.iconst(14, 0)                        # R14: ours (PERC, Monomachine, a sample machine): nonzero
        # which types are ours, and Monomachine machines, by one bit each of two masks (every such type is
        # under 32), the cost compares only for a Monomachine machine: the same R4, and R14 as a flag, as a
        # compare for each type gave
        p.iconst(12, 32)

        def small():                           # (1 << type: a count under 32)
            p.iconst(13, 1)
            MDK._shift_r(p, 13, 13, 2)
            p.iconst(12, OURS_MASK)
            p.iop(14, 13, "AND", 12)
            p.iconst(12, MNM_MASK)
            p.iop(12, 13, "AND", 12)

            def mnm_cost():
                p.iconst(15, 1)
                for typ, k in MNM_TYPES.items():
                    p.iconst(12, typ)
                    p.if_(2, "EQ", 12, lambda c=MNM_COST[MNM.NAMES[k]]: p.iconst(4, c), kind="i")
            p.ifz(12, "NE", mnm_cost)
        p.if_(2, "LT", 12, small, kind="i")
        p.st(costs + 4 * u, 4)

        def mnm(u=u):
            rests = L.md.mnm.scratch + RESTS_OFF
            p.iconst(12, 1 << u)
            p.iop(12, 3, "AND", 12)

            def struck():
                p.iconst(0, 0)
                p.st(rests + 4 * u, 0)
                p.st(L.md.mnm.scratch + STRIKES_OFF + 4 * u, 0)    # v0.36: a new note, no strikes

            def listen():                      # the block the chain left in its buffer
                p.ld(0, BUFFERS + 4 * u)
                p.seti(4, 0)
                p.fconst(7, 0.0)
                MDV.peak32(p, 4, counter=5)
                p.ld(0, rests + 4 * u)
                p.fconst(12, MNM_QUIET_LEVEL)
                p.if_(7, "LT", 12, lambda: (p.iconst(12, 1), p.iop(0, 12, "+", 0)), lambda: p.iconst(0, 0))
                p.st(rests + 4 * u, 0)
            p.ifz(12, "NE", struck, listen)
            p.ld(0, rests + 4 * u)
            p.iconst(12, MNM_QUIET_BLOCKS)
            p.if_(0, "GE", 12, lambda: (p.iconst(4, 0), p.st(costs + 4 * u, 4)), kind="i")   # resting: free
            p.ld(13, keys + 4 * u)
            p.lsh(13, 13, -4)                  # its age last block
            p.iconst(12, MNM_AGE_TOP)
            p.if_(13, "LT", 12, lambda: (p.iconst(12, 1), p.iop(13, 13, "+", 12)), kind="i")
            p.iconst(12, 1 << u)
            p.iop(12, 3, "AND", 12)
            p.ifz(12, "NE", lambda: p.iconst(13, 0))    # a note this block: the newest
            p.lsh(13, 13, 4)
            p.iconst(12, u)
            p.iop(13, 13, "OR", 12)
            p.st(keys + 4 * u, 13)

        def none(u=u):
            p.iconst(5, MNM_NONE | u)
            p.st(keys + 4 * u, 5)
        p.ifz(14, "NE", mnm, none)
    # the slots in key order: slot u goes to place (how many keys are smaller). Six slots' keys at a time
    # held in registers, each pass over the sixteen keys (one L2 read each) counting for all six at once (a
    # compare and a conditional add): the same places, 48 key reads a block, not 272; ORDER written place by
    # place as before (its words the same)
    order = L.md.mnm.scratch + ORDER_OFF
    p.iconst(0, 16)
    p.st(L.md.mnm.scratch + RANK_U, 0)
    p.iconst(0, 0)
    p.st(L.md.mnm.scratch + RANK_N, 0)
    held = (0, 1, 2, 3, 4, 6)                  # slot u's key
    counts = (8, 9, 10, 11, 13, 14)            # how many keys are smaller (integer adds take R8..R15 first)
    for lo in range(0, 16, len(held)):
        us = list(range(lo, min(lo + len(held), 16)))
        for j, u in enumerate(us):
            p.ld(held[j], keys + 4 * u)
        for j in range(len(us)):
            p.iconst(counts[j], 0)
        p.iconst(12, keys)
        p.seti(1, 12)
        p.iconst(12, 1)                        # (loop_r reloads its R12 = 1 at each pass's end)

        def each_v(n=len(us)):
            p.ldpost(7, 1)                     # key v
            for j in range(n):
                p.comp_iop_if(7, held[j], "LT", counts[j], counts[j], "+", 12)
        p.loop_r(5, 16, each_v)
        p.iconst(7, order)
        for j, u in enumerate(us):
            p.lsh(counts[j], counts[j], 2)
            p.iop(counts[j], counts[j], "+", 7)
            p.seti(1, counts[j])
            p.iconst(12, u)
            p.sti(0, 1, 12)                    # ORDER[place] = u

    # the budget sums (CUM_OFF), in a block with a Monomachine slot: the costs in key order, summed (the
    # same integers budget() added up, in another order)
    def sums():
        p.iconst(8, 0)
        p.iconst(11, costs)
        p.iconst(12, order)
        p.seti(1, 12)

        def one():
            p.ldpost(9, 1)                     # the next slot in key order
            p.lsh(10, 9, 2)
            p.iop(10, 11, "+", 10)
            p.seti(4, 10)
            p.ldi(10, 0, 4)
            p.iop(8, 8, "+", 10)
            p.sti((CUM_OFF - MNM_COSTS_OFF) // 4, 4, 8)
        p.loop_r(14, 16, one)
    p.ifz(15, "NE", sums)


def order_slot(p: Prog, idx: int) -> None:
    """v0.29: C['t'] (the caller's) = ORDER[the index word IDX]; R9 = it. Clobbers R0, R12, I1."""
    p.ld(0, idx)
    p.lsh(12, 0, 2)
    p.iconst(9, ORDER)
    p.iop(12, 9, "+", 12)
    p.seti(1, 12)
    p.ldi(9, 0, 1)


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
    frame_regs(p)                             # the records read through two pointers (frame_byte)
    frame_byte(p, 4, M.TYPE_REC[1])
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
        frame_byte(p, 4, slot)
        if lo:                                 # (+ 0 left out: the same word)
            p.iconst(12, -lo)
            p.iop(4, 12, "+", 4)
        p.iop(4, 4, "MAX", 15)                 # (R15 = 0: frame_regs)
        p.iconst(12, top)
        p.iop(4, 4, "MIN", 12)
        p.float_(5, 4, 15)
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
        for k, lev in enumerate(MNM_LEVELS):    # v0.27: the machine's own level
            p.iconst(12, k + 1)
            p.if_(0, "EQ", 12, lambda lev=lev: (p.fconst(1, lev), p.st(C["lev"], 1)), kind="i")
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
    # v0.26: a Monomachine voice only while the block's Monomachine cost fits MNM_BUDGET
    p.iconst(0, 0)
    p.st(C["mskip"], 0)
    p.ld(0, C["mnm"])

    def budget():
        # v0.29: the newer voices' costs first (mnm_ages), then this one's
        keys = L.md.mnm.scratch + MNM_KEYS_OFF
        p.ld(8, C["t"])
        p.lsh(12, 8, 2)
        p.iconst(11, keys)
        p.iop(12, 11, "+", 12)
        p.seti(1, 12)
        p.ldi(8, (CUM_OFF - MNM_KEYS_OFF) // 4, 1)    # their costs and its own, summed by mnm_ages
        p.ldi(5, (RESTS_OFF - MNM_KEYS_OFF) // 4, 1)    # v0.29: resting (its sound died away)
        p.iconst(12, MNM_QUIET_BLOCKS)
        p.if_(5, "GE", 12, lambda: p.iconst(8, MNM_BUDGET + 1), kind="i")
        p.iconst(12, MNM_BUDGET)
        p.if_(8, "GT", 12, lambda: (p.iconst(0, 1), p.st(C["mskip"], 0)),
              lambda: p.st(C["mcost"], 8), kind="i")
    p.ifz(0, "NE", budget)

    def md_rest():
        # v0.31: a Machinedrum voice rests too once its sound has died away after the AMP
        # (depaffect: eight PERC tracks with dynamic allocation stopped all audio; each note
        # takes another voice, and the old ones went on costing a full render each block)
        p.ld(8, C["t"])
        p.lsh(12, 8, 2)
        p.iconst(11, L.md.mnm.scratch + RESTS_OFF)
        p.iop(12, 11, "+", 12)
        p.seti(1, 12)
        p.ldi(5, 0, 1)
        p.iconst(12, MNM_QUIET_BLOCKS)
        p.if_(5, "GE", 12, lambda: (p.iconst(0, 1), p.st(C["mskip"], 0)), kind="i")
    p.ld(0, C["mnm"])
    p.ifz(0, "EQ", md_rest)

    def render():
        p.ld(2, C["trig"])
        p.ld(5, C["type"])
        MDV.block(p, L.md, [C[f"p{k}"] for k in range(8)], 2, 5, level_word=C["lev"])

    def silence():                            # past the budget: this block is silent
        p.ld(0, C["buf"])
        p.seti(4, 0)
        p.fconst(1, 0.0)
        p.loop(C["tmp"], 32, lambda: p.stpost(4, 1))
    p.ld(0, C["mskip"])
    p.ifz(0, "NE", silence, render)
    p.ld(12, C["sbase"])
    p.seti(2, 12, "this slot's state, again")
    p.ld(0, C["mnm"])
    p.ifz(0, "EQ", lambda: fx(p, L))          # the Machinedrum's track effects: PERC's only
    out_guard(p, L)


OUT_LIMIT = 8.0                                # v0.33: our voices' samples, at most (+- 18 dBFS)


def out_guard(p: Prog, L: M.Layout) -> None:
    """v0.33 (Moog, CAT: a PERC track burst into white noise, then all audio went silent until
    a restart -- the signature of a voice blowing up: a resonant filter or a feedback state
    running away to infinity, then NaN, which the stock chain carries into the delay and
    reverb, where it stays). Every sample of the block our voice wrote is held to
    +-OUT_LIMIT; and if one is not finite (infinite or NaN: its exponent all ones), the whole
    block is zeroed and the voice's state cleared (its 'on' word with it: the next block starts
    it fresh, as a new machine), so nothing non-finite ever leaves our code. The mask, the
    flag's 1 and the limits held in registers through the block and the count in R5 (a
    register loop): the same tests and stores. Uses R0, R1, R5, R12-R15, I2, I4 and fxy (a
    flag, free after the effects)."""
    C = L.C
    p.iconst(0, 0)
    p.st(C["fxy"], 0)
    p.ld(0, C["buf"])
    p.seti(4, 0, "the slot's buffer, the guard")
    p.iconst(13, 0xFF)
    p.iconst(1, 1)
    p.fconst(14, OUT_LIMIT)
    p.fconst(15, -OUT_LIMIT)

    def sample():
        p.ldi(0, 0, 4)
        p.lsh(12, 0, -23)
        p.iop(12, 12, "AND", 13)
        p.if_(12, "EQ", 13, lambda: p.st(C["fxy"], 1), kind="i")
        p.fop(0, 0, "MIN", 14)
        p.fop(0, 0, "MAX", 15)
        p.stpost(4, 0)
    p.loop_r(5, 32, sample)

    def blown():
        # v0.34: the record first (docs/timing-model.md; the owner's O13: P-I machines silent
        # on the same voices every time). Which slot and machine, and the first non-finite
        # word in the voice's P-I delay lines; none: the poison was in the voice's own state
        # (the filters', zeroed here), its input, or the effects
        from . import guard as G
        p.comment("v0.34: the guard's record: count, slot | type << 8, the mask")
        p.ld(1, G.BLOWN_COUNT)
        p.iconst(12, 1)
        p.iop(1, 12, "+", 1)
        p.st(G.BLOWN_COUNT, 1)
        p.ld(1, C["type"])
        p.lsh(1, 1, 8)
        p.ld(12, C["t"])
        p.iop(1, 1, "OR", 12)
        p.st(G.BLOWN_INFO, 1)
        p.iconst(1, 1)
        p.ld(12, C["t"])
        _shift_by(p, 1, 12)                   # 1 << t
        p.ld(12, G.BLOWN_MASK)
        p.iop(1, 1, "OR", 12)
        p.st(G.BLOWN_MASK, 1)
        p.iconst(1, G.WHERE_NONE)
        p.st(G.BLOWN_WHERE, 1)
        p.iconst(1, 0)
        p.st(C["fxy"], 1, "the scan's index")

        def scan(n: int, tag: int):
            """I5 walks N words; the first non-finite one's index | TAG and bits are kept"""
            def word():
                p.ldpost(1, 5)
                p.lsh(12, 1, -23)
                p.iconst(13, 0xFF)
                p.iop(12, 12, "AND", 13)

                def first():
                    p.ld(13, G.BLOWN_WHERE)
                    p.iconst(12, G.WHERE_NONE)

                    def keep():
                        p.st(G.BLOWN_WORD, 1)
                        p.ld(13, C["fxy"])
                        p.iconst(12, tag)
                        p.iop(13, 13, "OR", 12)
                        p.st(G.BLOWN_WHERE, 13)
                    p.if_(13, "EQ", 12, keep, kind="i")
                p.if_(12, "EQ", 13, first, kind="i")
                p.ld(13, C["fxy"])
                p.iconst(12, 1)
                p.iop(13, 12, "+", 13)
                p.st(C["fxy"], 13)
            p.loop(C["tmp"], n, word)
        # (the delay lines only: the voice's stream holds the tainted output itself, and
        # its machine words hold integers, -1 among them, whose bits are the core's NaN)
        MDK.delay_base(p, L.md, 1)
        p.seti(5, 1, "the P-I delay lines")
        scan(MDK.PI_DELAY_WORDS, G.WHERE_DELAY)
        # then the wipe: the block silent and the voice's state zeroed, so the next block
        # starts it fresh (reset: its words and delay lines cleared). v0.33 stored R0 here,
        # which loop() uses as its counter: the state got 32, 31 .. 1 instead of zeros, its
        # 'on' word with them, so the voice never reset and stayed silent until a power-on
        p.ld(0, C["buf"])
        p.seti(4, 0)
        p.fconst(1, 0.0)
        p.loop(C["tmp"], 32, lambda: p.stpost(4, 1))
        p.ld(12, C["sbase"])
        p.seti(2, 12, "this slot's state, cleared")
        p.iconst(1, 0)
        p.loop(C["tmp"], 32, lambda: p.stpost(2, 1))
    p.ld(0, C["fxy"])
    p.ifz(0, "NE", blown)


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

    def am_on():
        p.iconst(5, 1)
        p.st(C["fxam"], 5)
        q(8, 1)                               # the step only when AM is on (only the AM pass reads
        p.fconst(one, 14.5)                   # amdt): the same word then
        p.fop(8, 8, "*", one)
        M.exp2(p, L, 8, 8)
        p.fconst(one, 0.1 * M.DT)
        p.fop(8, 8, "*", one)
        p.st(C["amdt"], 8)
    p.if_(4, "GT", 6, am_on)
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
    from ..mnm import dpro as MNP
    MNP.build(p, L.md.mnm)                     # v0.26: then DENS's and DDRW's Digibank stand-in, 8 words a block
    p.iconst(0, 0)
    p.st(L.C["mcost"], 0)                      # v0.26: no Monomachine voice rendered yet this block
    mnm_ages(p, L)                             # v0.29: the newest Monomachine voices first
    from . import guard as G
    G.entry(p)                                 # v0.27: the frame's length and the time our voices have
    from ..sampler import machines as SMx2
    from ..sampler.program import V as SV
    from ..waverider import dsp as DSPx
    G.perc_limit(p, [SMx2.TYPE_OF[n] for n in SMx2.ENGINED], DSPx.SMP_STATE_DM, DSPx.SMP_STATE_STRIDE,
                 SV["on"], TRIG_WORD, lambda p, d, k: half(p, d, 148, k))   # v0.49: the samples' time first
    p.iconst(0, 0)
    p.st(L.md.mnm.scratch + PERC_I, 0)
    top = p.label("slot")
    nxt = p.label("next")
    p.place(top)
    order_slot(p, L.md.mnm.scratch + PERC_I)   # v0.29: the newest first
    p.st(L.C["t"], 9)
    # no record pointer (I4 = 0x2554b8 + 0x234 t was set here and read by nothing: the voice sets I4
    # to its buffer before any use), and PERC or a Monomachine machine (v0.26: PERC's voice too) by one
    # bit of VOICE_MASK, not a compare a type
    raw_type(p, 2)
    p.iconst(0, 0)
    p.iconst(12, 32)
    p.if_(2, "LT", 12, lambda: (p.iconst(13, 1), MDK._shift_r(p, 13, 13, 2), p.iconst(12, VOICE_MASK),
                                p.iop(0, 13, "AND", 12)), kind="i")
    p.ipass(0, 0)
    other = p.label("other")
    p.jump("EQ", other)
    p.ld(0, L.md.C["fill"])                   # v0.26: silent until the tables (sent by the
    p.iconst(12, MDK.Z_N)                     # ColdFire at power-on) are decoded
    p.e("COMP(R0, R12);")
    p.jump("LT", other)
    G.around(p, L.C["t"], G.COST_PERC, BUFFERS, lambda: voice(p, L),   # v0.27: if it fits in the frame
             rests=L.md.mnm.scratch + RESTS_OFF, rest_blocks=MNM_QUIET_BLOCKS,   # v0.36: else, the second
             strikes=L.md.mnm.scratch + STRIKES_OFF, steal_at=STEAL_STRIKES,       # time in a note, stolen
             limit=G.LIMIT_PERC)                                                    # v0.49: after the samples' share
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
    p.ld(0, L.md.mnm.scratch + PERC_I)
    p.iconst(12, 1)
    p.iop(0, 12, "+", 0)
    p.st(L.md.mnm.scratch + PERC_I, 0)
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

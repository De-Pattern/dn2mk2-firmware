"""The asm for dnfw.voices: each slot's age into a 16-word array, then a slot's rank.

Shared by gen_rings_asm.py and gen_cz_asm.py (PING's helpers, G). The machine's own
`ld` / `st` reach its scratch words; the array is at E_ADDR, in its scratch block.
"""

from __future__ import annotations

import gen_ping_asm as G
from dnfw import voices

emit, label, jump, place = G.emit, G.label, G.jump, G.place


def imm(v: int) -> str:
    return f"-{(1 << 32) - v:#x}" if v >> 31 else f"{v:#x}"


def ages(machines, ld, st, j: str) -> None:
    """e[t] for t = 0..15 (dnfw.voices.age_of), for each of MACHINES -- (type, state
    DDR, stride shift, active word, age word, e array) -- in its own array: 0 on a
    trigger, age + 1 (to AGE_TOP) while active, NONE otherwise or on another machine.
    One pass for all of them (RESONATOR's entry runs it for CZ too, which runs next in
    the same block). Clobbers R0-R2, R9, R11-R13, I1, I2, I4; scratch word J."""
    emit("      // ---- every slot's age (dnfw.voices), one array a machine ----")
    emit("      R0 = R0 - R0;")
    st(0, j)
    top, nxt = label("vtop"), label("vnext")
    place(top)
    ld(9, j)
    emit(f"      R0 = {voices.NONE:#x};")
    for _, _, _, _, _, e_addr in machines:
        emit("      R12 = LSHIFT R9 BY 2;")
        emit(f"      R11 = {e_addr:#x};")
        emit("      R12 = R11 + R12;")
        emit("      I1 = R12;")
        emit("      DM(0, I1) = R0;".ljust(40) + "// NONE")
    G.record_base()
    emit("      R1 = DM(109, I4);".ljust(40) + "// the record's machine type")
    for mtype, state_ddr, shift, active, age, e_addr in machines:
        other, notrig, store = label("vother"), label("vnotrig"), label("vstore")
        emit(f"      R12 = {mtype};")
        emit("      COMP(R1, R12);")
        jump("NE", other)
        emit("      R0 = DM(0x25c4ac);")
        emit("      R0 = LSHIFT R0 BY -16;".ljust(40) + "// TRIG_NOTE")
        emit("      R2 = 1;")
        emit("      R2 = LSHIFT R2 BY R9;")
        emit("      R0 = R0 AND R2;")
        jump("EQ", notrig)
        emit("      R0 = R0 - R0;".ljust(40) + "// triggered: 0")
        jump("", store)
        place(notrig)
        emit(f"      R12 = LSHIFT R9 BY {shift};")
        emit(f"      R11 = {imm(state_ddr)};")
        emit("      R12 = R11 + R12;")
        emit("      I2 = R12;")
        emit(f"      R0 = DM({active}, I2);".ljust(40) + "// active?")
        emit("      R0 = PASS R0;")
        jump("EQ", nxt)
        emit(f"      R0 = DM({age}, I2);")
        emit("      R12 = 1;")
        emit("      R0 = R12 + R0;")
        emit(f"      R12 = {voices.AGE_TOP:#x};")
        emit("      R0 = MIN(R0, R12);")
        place(store)
        emit("      R12 = LSHIFT R9 BY 2;")
        emit(f"      R11 = {e_addr:#x};")
        emit("      R12 = R11 + R12;")
        emit("      I1 = R12;")
        emit("      DM(0, I1) = R0;")
        jump("", nxt)
        place(other)
    place(nxt)
    ld(0, j)
    emit("      R12 = 1;")
    emit("      R0 = R12 + R0;")
    st(0, j)
    emit("      R12 = 16;")
    emit("      COMP(R0, R12);")
    jump("LT", top)


def rank(e_addr: int, cap: int, quiet: str, steal: str) -> None:
    """For slot R9: R3 = e[t]; on to QUIET if it has no age, to STEAL if its rank is at
    least CAP; falls through to render with R3 kept. Clobbers R4-R6, R11, R12, I1."""
    emit("      // ---- this slot's rank among the newest (dnfw.voices.plan) ----")
    emit("      R12 = LSHIFT R9 BY 2;")
    emit(f"      R11 = {e_addr:#x};")
    emit("      R12 = R11 + R12;")
    emit("      I1 = R12;")
    emit("      R3 = DM(0, I1);".ljust(40) + "// e[t]")
    emit(f"      R12 = {voices.NONE:#x};")
    emit("      COMP(R3, R12);")
    jump("EQ", quiet)
    emit("      R4 = R4 - R4;".ljust(40) + "// rank")
    emit("      R5 = R5 - R5;".ljust(40) + "// j")
    emit(f"      R12 = {e_addr:#x};")
    emit("      I1 = R12;")
    loop, inc, nxt = label("rk"), label("rkinc"), label("rknext")
    place(loop)
    emit("      R6 = DM(I1, M6);".ljust(40) + "// e[j]")
    emit("      COMP(R6, R3);")
    jump("LT", inc)
    jump("NE", nxt)
    emit("      COMP(R5, R9);")
    jump("GE", nxt)
    place(inc)
    emit("      R12 = 1;")
    emit("      R4 = R12 + R4;")
    place(nxt)
    emit("      R12 = 1;")
    emit("      R5 = R12 + R5;")
    emit("      R12 = 16;")
    emit("      COMP(R5, R12);")
    jump("LT", loop)
    emit(f"      R12 = {cap};")
    emit("      COMP(R4, R12);")
    jump("GE", steal)

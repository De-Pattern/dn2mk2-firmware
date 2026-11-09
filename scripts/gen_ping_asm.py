"""Write `csrc/waverider/sharc/ping.asm`. Until v0.44 it was PING on the DSP; since v0.45
(PING removed) it is only the shared tail every machine of ours returns through (`build`).
The helpers here (a table read, the reciprocal, a knee) are still imported by the other
generators, which is why they stay.

    python scripts/gen_ping_asm.py

The output is committed and is what selas assembles (`scripts/gen_waverider_sharc.py
--assemble`); this script only exists so the 400-odd instructions are produced the
same way every time. The code mirrors `dnfw.ping.live` operation by operation, in its
order, so the SHARC gate can hold it to that module bit for bit. Branch targets are
written as `0x0` with a `// -> label.` comment; `scripts/sharc_resolve_jumps.py`
fills them in.

Instruction forms: only those Waverider's loop already uses (and the gate checks
that selmap and digikit read every one as written).
"""

from __future__ import annotations

import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.ping import live as L                     # noqa: E402
from dnfw.shft import live as SL                    # noqa: E402
from dnfw.waverider import dsp                      # noqa: E402

OUT = ROOT / "csrc" / "waverider" / "sharc" / "ping.asm"


def fbits(x: float) -> str:
    return f"0x{struct.unpack('<I', struct.pack('<f', x))[0]:08x}"


_, AT = L.tables_bytes()
TAB = {name: dsp.PING_TABLES_DDR + off for name, off in AT.items()}
LENS = {name: len(t) for name, t in L.tables().items()}
STATE = dsp.PING_STATE_DM
_, SAT = SL.tables_bytes()
STAB = {name: 0 for name in SAT}                   # v0.27: SHFT removed (its code is no longer emitted)


def imm(v: int) -> str:
    """A DDR address as selmap prints it: signed."""
    return f"-{(1 << 32) - v:#x}" if v >> 31 else f"{v:#x}"
SLENS = {name: len(t) for name, t in SL.tables().items()}
# SHFT's per-track state words (dnfw.shft.live.Voice, then the block's controls)
SS = dict(in1=0, in2=1, iprev=18, phase=19, fb=20, stage=21, x=22,
          mode=24, inc=25, inc_env=26, fdbk=27, mix=28, drive=29, atk=30, dec=31, left=32)
for _i in range(4):
    SS[f"ay1_{_i}"], SS[f"ay2_{_i}"] = 2 + _i, 6 + _i
    SS[f"by1_{_i}"], SS[f"by2_{_i}"] = 10 + _i, 14 + _i
SAVE = 0x2DDE00                      # machine5_live's save area (R0-R15, I0-I5, I12, M0-M4)

# per-track state words (dnfw.ping.live.Voice, then the block's controls)
S = dict(ic1=0, ic2=1, s0=2, s1=3, s2=4, s3=5, stage=6, x=7, vac=8, hit=9,
         kind=16, base=17, env=18, inv_tau=19, res=20, drive=21, atk=22, dec_env=23,
         curve=24, strike_hit=25, late=26, hit_end=27, left=28, k_vcfq=29, lpg_q=30,
         dec_vac=31, lpg_inv_tau=10, t=11)
STATE_STRIDE = 128

lines: list[str] = []
n_label = [0]


def emit(s: str = "") -> None:
    lines.append(s)


def label(stem: str) -> str:
    n_label[0] += 1
    return f"wr_p_{stem}_{n_label[0]}"


def place(name: str) -> None:
    emit(f".GLOBAL {name}.;")
    emit(f"{name}.:")


def jump(cond: str, target: str) -> None:
    pre = f"IF {cond} " if cond else ""
    emit(f"      {pre}JUMP 0x0;".ljust(40) + f"// -> {target}.")


def fconst(reg: int, value: float, note: str = "") -> None:
    """R{reg} = the float32 bits of VALUE; a value with the top bit set is written as a
    negative number, as selmap prints it (the same 32 bits either way)."""
    b = struct.unpack('<I', struct.pack('<f', value))[0]
    lit = f"-{(1 << 32) - b:#x}" if b >> 31 else f"{b:#010x}"
    emit(f"      R{reg} = {lit};".ljust(40) + (f"// {note}" if note else f"// {value!r}"))


def interp(table: str, fx: int, out: int, shft: bool = False) -> None:
    """F{out} = live.interp(table, F{fx}). Clobbers R0-R3, R12, I1; F{fx} is clamped in
    place. live: x = min(max(x, 0), top); i = trunc(x); f = x - float(i);
    t[i] + f * (t[i+1] - t[i])."""
    top = (SLENS if shft else LENS)[table] - 2
    addr = (STAB if shft else TAB)[table]
    emit(f"      // F{out} = {table}[F{fx}], interpolated")
    emit("      R12 = R12 - R12;")
    emit(f"      F{fx} = MAX(F{fx}, F12);")
    fconst(12, float(top))
    emit(f"      F{fx} = MIN(F{fx}, F12);")
    emit(f"      R0 = TRUNC F{fx};")
    emit("      R12 = R12 - R12;")
    emit("      F1 = FLOAT R0 BY R12;")
    emit(f"      F1 = F{fx} - F1;".ljust(40) + "// f")
    emit("      R0 = LSHIFT R0 BY 2;")
    emit(f"      R12 = {imm(addr)};".ljust(40) + f"// {table} ({addr:#x}, DDR)")
    emit("      R0 = R12 + R0;")
    emit("      I1 = R0;")
    emit("      R2 = DM(0, I1);")
    emit("      R3 = DM(1, I1);")
    emit("      F3 = F3 - F2;")
    emit("      F3 = F1 * F3;")
    emit(f"      F{out} = F2 + F3;")


def at127(table: str, fv: int, out: int) -> None:
    """F{out} = table[trunc(clamp(F{fv}, 0, 1) * 127)]. Clobbers R0, R12, I1, F{fv}."""
    emit(f"      // F{out} = {table}[trunc(F{fv} * 127)]")
    emit("      R12 = R12 - R12;")
    emit(f"      F{fv} = MAX(F{fv}, F12);")
    fconst(12, 1.0)
    emit(f"      F{fv} = MIN(F{fv}, F12);")
    fconst(12, 127.0)
    emit(f"      F{fv} = F{fv} * F12;")
    emit(f"      R0 = TRUNC F{fv};")
    emit("      R0 = LSHIFT R0 BY 2;")
    emit(f"      R12 = {imm(TAB[table])};".ljust(40) + f"// {table} ({TAB[table]:#x}, DDR)")
    emit("      R0 = R12 + R0;")
    emit("      I1 = R0;")
    emit(f"      R{out} = DM(0, I1);")


def clamp01(f: int) -> None:
    emit("      R12 = R12 - R12;")
    emit(f"      F{f} = MAX(F{f}, F12);")
    fconst(12, 1.0)
    emit(f"      F{f} = MIN(F{f}, F12);")


def recip(fx: int, out: int) -> None:
    """F{out} = live.recip(F{fx}): R{out} = 0x7ef311c7 - R{fx}, then three times
    r = r * (2 - x * r). Clobbers R12, R13."""
    emit(f"      // F{out} = 1 / F{fx}")
    emit("      R12 = 0x7ef311c7;")
    emit(f"      R{out} = R12 - R{fx};")
    for _ in range(3):
        emit(f"      F13 = F{fx} * F{out};")
        fconst(12, 2.0)
        emit("      F13 = F12 - F13;")
        emit(f"      F{out} = F{out} * F13;")


def knee(f: int, k: float, room: float) -> None:
    """F{f} = live.knee(F{f}, k, room), in place. Clobbers R12, R13, R14, R15."""
    lin, neg, done = label("lin"), label("neg"), label("kdone")
    emit(f"      // F{f} = knee(F{f}, {k}, {room})")
    emit("      R12 = R12 - R12;")
    emit(f"      F14 = F12 - F{f};".ljust(40) + "// -x")
    emit(f"      COMP(F{f}, F12);")
    jump("LT", neg)
    emit(f"      F14 = PASS F{f};".ljust(40) + "// |x|")
    place(neg)
    fconst(12, k)
    emit("      COMP(F14, F12);")
    jump("LE", lin)
    emit("      F14 = F14 - F12;".ljust(40) + "// |x| - k")
    fconst(12, room)
    emit("      F14 = MIN(F14, F12);".ljust(40) + "// o")
    emit("      F15 = F14 * F14;")
    fconst(12, 0.5 / room)
    emit("      F15 = F15 * F12;")
    emit("      F15 = F14 - F15;")
    fconst(12, k)
    emit("      F15 = F12 + F15;".ljust(40) + "// y = k + (o - o^2 / 2room)")
    emit("      R12 = R12 - R12;")
    emit(f"      COMP(F{f}, F12);")
    jump("LT", neg2 := label("kneg"))                 # the sign of x (x != 0 here)
    emit(f"      F{f} = PASS F15;")
    jump("", lin)
    place(neg2)
    emit(f"      F{f} = F12 - F15;")
    place(lin)


def cubic(f: int) -> None:
    """F{f} = live.cubic(F{f}). Clobbers R12, R13."""
    fconst(12, -1.5)
    emit(f"      F{f} = MAX(F{f}, F12);")
    fconst(12, 1.5)
    emit(f"      F{f} = MIN(F{f}, F12);")
    emit(f"      F13 = F{f} * F{f};")
    emit(f"      F13 = F13 * F{f};")
    fconst(12, 4.0 / 27.0)
    emit("      F13 = F13 * F12;")
    emit(f"      F{f} = F{f} - F13;")


def ld(reg: int, word: str) -> None:
    emit(f"      R{reg} = DM({S[word]}, I2);".ljust(40) + f"// {word}")


def st(reg: int, word: str) -> None:
    emit(f"      DM({S[word]}, I2) = R{reg};".ljust(40) + f"// {word}")


def svf(fx: int, fg: int, fk: int) -> None:
    """live.svf: band -> F6, low -> F7. Inputs F{fx}, F{fg}, F{fk} (fk is clobbered).
    Uses R4..R7, R10, R11 and the state's ic1/ic2."""
    emit("      // the SVF step")
    emit(f"      F{fk} = F{fg} + F{fk};".ljust(40) + "// g + k")
    emit(f"      F{fk} = F{fg} * F{fk};")
    fconst(12, 1.0)
    emit(f"      F{fk} = F12 + F{fk};".ljust(40) + "// 1 + g (g + k)")
    recip(fk, 14)                                    # a1 -> F14
    emit(f"      F5 = F{fg} * F14;".ljust(40) + "// a2")
    emit(f"      F10 = F{fg} * F5;".ljust(40) + "// a3")
    ld(6, "ic1")
    ld(7, "ic2")
    emit(f"      F11 = F{fx} - F7;".ljust(40) + "// v3")
    emit("      F12 = F14 * F6;")
    emit("      F13 = F5 * F11;")
    emit("      F4 = F12 + F13;".ljust(40) + "// v1")
    emit("      F12 = F5 * F6;")
    emit("      F12 = F7 + F12;")
    emit("      F13 = F10 * F11;")
    emit("      F5 = F12 + F13;".ljust(40) + "// v2")
    emit("      F12 = F4 + F4;")
    emit("      F6 = F12 - F6;".ljust(40) + "// 2 v1 - ic1")
    knee(6, 1.0, 1.2)
    st(6, "ic1")
    emit("      F12 = F5 + F5;")
    emit("      F7 = F12 - F7;")
    st(7, "ic2")
    emit("      F6 = PASS F4;".ljust(40) + "// band")
    emit("      F7 = PASS F5;".ljust(40) + "// low")


def build() -> str:
    """v0.45 (owner, 2026-11-08): PING removed, to make room for FASCIA. What stays is
    ping.asm's tail, at the same address (dsp.PING_SW): every machine of ours ends by
    jumping there (smp.asm's `JUMP 0x170280`), and it restores what PERC saved and
    rejoins the per-track chain. These instructions are exactly the old tail's (v0.44's
    ping.asm after its track loop). PING's filter code, state and tables are gone; the
    helpers above stay for the generators that import them (gen_rings/cz/gran_asm,
    voice_alloc_asm)."""
    lines.clear()
    emit("// ping.asm -- the shared tail of our DSP code (v0.45: the PING filter removed).")
    emit("// GENERATED by scripts/gen_ping_asm.py; do not edit by hand.")
    emit("//")
    emit("// Entered once a block from smp.asm's tail (JUMP 0x170280), after every machine of")
    emit("// ours has rendered: it restores the registers PERC saved at 0x2dde00, re-runs the")
    emit("// two stock instructions the entry JUMP replaced, and rejoins the per-track chain")
    emit("// at 0x1c944c -- exactly what PING's tail did (v0.27..v0.44), without PING's track")
    emit("// loop. It stays at this address: every machine of ours returns through it.")
    emit("")
    emit(".SECTION/PM seg_pmco;")
    emit("")
    emit(".GLOBAL wr_ping.;")
    emit("wr_ping.:")
    # restore what PERC (dnfw.perc.program, SAVE) saved, and rejoin the chain
    regs = [f"R{k}" for k in range(16)] + ["I0", "I1", "I2", "I3", "I4", "I5", "I12",
                                          "M0", "M1", "M2", "M3", "M4"]
    for k, r in enumerate(regs):
        emit(f"      {r} = DM({SAVE + 4 * k:#x});")
    emit("      // the two instructions the entry JUMP replaced (0x1c9448, 0x1c944a)")
    emit("      I5 = DM(-24, I6);")
    emit("      R10 = DM(-34, I6);")
    emit("      JUMP 0x1c944c;")
    emit(".wr_ping..end:")
    emit("      .type wr_ping.,STT_FUNC;")
    return "\n".join(lines) + "\n"


def sld(reg: int, word: str) -> None:
    emit(f"      R{reg} = DM({SS[word]}, I2);".ljust(40) + f"// {word}")


def sst(reg: int, word: str) -> None:
    emit(f"      DM({SS[word]}, I2) = R{reg};".ljust(40) + f"// {word}")


def record_base() -> None:
    """I4 = the track record of track R9: 0x2554b8 + 0x234 t. Clobbers R11-R13."""
    emit("      R12 = LSHIFT R9 BY 9;".ljust(40) + "// record: 0x2554b8 + 0x234 t")
    emit("      R13 = LSHIFT R9 BY 5;")
    emit("      R12 = R12 + R13;")
    emit("      R13 = LSHIFT R9 BY 4;")
    emit("      R12 = R12 + R13;")
    emit("      R13 = LSHIFT R9 BY 2;")
    emit("      R12 = R12 + R13;")
    emit("      R11 = 0x2554b8;")
    emit("      R12 = R11 + R12;")
    emit("      I4 = R12;")


def note_into_f11() -> None:
    """F11 = the track's note, validated as machine5_live does. Clobbers R11-R13, I1."""
    emit("      R12 = LSHIFT R9 BY 2;")
    emit("      R11 = 0x254b14;".ljust(40) + "// the note cells")
    emit("      R12 = R11 + R12;")
    emit("      I1 = R12;")
    emit("      R11 = DM(0, I1);".ljust(40) + "// note, float semitones")
    emit("      R12 = LSHIFT R11 BY -23;")
    emit("      R13 = 0xff;")
    emit("      R12 = R12 AND R13;")
    bad, ok = label("snote0"), label("snoteok")
    emit("      COMP(R12, R13);")
    jump("EQ", bad)
    emit("      R11 = PASS R11;")
    jump("LT", bad)
    jump("", ok)
    place(bad)
    emit("      R11 = R11 - R11;")
    place(ok)


def chain(name: str, c2: tuple, out: int) -> None:
    """dnfw.shft.live.chain on F11 (the input), with in2 the shared input history:
    the four all-passes, result -> F{out}. Clobbers R3-R6, R12."""
    emit(f"      // all-pass chain {name}")
    sld(3, "in2")                                    # old2
    cur = 11
    for i in range(4):
        sld(4, f"{name}y2_{i}")
        emit(f"      F5 = F{cur} + F4;")
        fconst(12, c2[i], f"c{i}^2")
        emit("      F5 = F12 * F5;")
        emit("      F5 = F5 - F3;".ljust(40) + "// y")
        emit("      F3 = PASS F4;".ljust(40) + "// old2 = y2")
        sld(6, f"{name}y1_{i}")
        sst(6, f"{name}y2_{i}")
        sst(5, f"{name}y1_{i}")
        cur = 5
    emit(f"      F{out} = PASS F5;")


def shft_path() -> None:
    """SHFT (dnfw.shft.live.block) on track R9, then on to wr_p_next."""
    emit("")
    emit("// ---- SHFT: filter type 7 (dnfw.shft.live) ----")
    place("wr_s_track")
    emit("      R12 = LSHIFT R9 BY 8;")
    emit(f"      R11 = {dsp.SHFT_STATE_DM:#x};")
    emit("      R12 = R11 + R12;")
    emit("      I2 = R12;".ljust(40) + "// this track's SHFT state")
    record_base()
    emit("      // mode = min(2, trunc(clamp(TYPE) * 3))")
    emit(f"      R8 = DM({SL.R_TYPE // 4}, I4);")
    clamp01(8)
    fconst(12, 3.0)
    emit("      F8 = F8 * F12;")
    emit("      R8 = TRUNC F8;")
    emit("      R12 = 2;")
    emit("      R8 = MIN(R8, R12);")
    sst(8, "mode")
    emit("      // hz = 2500 u^3, u = clamp((FREQ 128 - 64) / 63, -1, 1)")
    emit(f"      R4 = DM({SL.R_FREQ // 4}, I4);")
    clamp01(4)
    fconst(12, 128.0)
    emit("      F4 = F4 * F12;")
    fconst(12, 64.0)
    emit("      F4 = F4 - F12;")
    fconst(12, L._f32(1.0 / 63.0))
    emit("      F4 = F4 * F12;")
    fconst(12, -1.0)
    emit("      F4 = MAX(F4, F12);")
    fconst(12, 1.0)
    emit("      F4 = MIN(F4, F12);")
    emit("      F5 = F4 * F4;")
    emit("      F5 = F5 * F4;")
    fconst(12, SL.MAX_HZ)
    emit("      F5 = F5 * F12;".ljust(40) + "// hz")
    emit("      // ratio = pow2[keyt (note - 60) + 64]")
    emit(f"      R10 = DM({SL.R_KEYT // 4}, I4);")
    clamp01(10)
    note_into_f11()
    fconst(12, 60.0)
    emit("      F11 = F11 - F12;")
    emit("      F11 = F10 * F11;")
    fconst(12, float(SL.POW2_MID))
    emit("      F11 = F11 + F12;")
    interp("pow2", 11, 6, shft=True)
    emit("      F5 = F5 * F6;")
    fconst(12, L._f32(1.0 / SL.RATE))
    emit("      F5 = F5 * F12;")
    sst(5, "inc")
    emit(f"      R4 = DM({SL.R_DEPTH // 4}, I4);")
    fconst(12, 0.5)
    emit("      F4 = F4 - F12;")
    fconst(12, 2.0)
    emit("      F4 = F4 * F12;")
    fconst(12, L._f32(SL.MAX_HZ / SL.RATE))
    emit("      F4 = F4 * F12;")
    sst(4, "inc_env")
    emit(f"      R4 = DM({SL.R_RES // 4}, I4);")
    clamp01(4)
    fconst(12, L._f32(0.95))
    emit("      F4 = F4 * F12;")
    sst(4, "fdbk")
    emit(f"      R4 = DM({SL.R_MIX // 4}, I4);")
    clamp01(4)
    sst(4, "mix")
    emit(f"      R4 = DM({SL.R_DRIVE // 4}, I4);")
    clamp01(4)
    fconst(12, 1.6)
    emit("      F4 = F12 * F4;")
    fconst(12, 0.4)
    emit("      F4 = F12 + F4;")
    sst(4, "drive")
    emit(f"      R4 = DM({SL.R_ATK // 4}, I4);")
    at127("atk", 4, 6)
    sst(6, "atk")
    emit(f"      R4 = DM({SL.R_DEC // 4}, I4);")
    at127("dec", 4, 6)
    sst(6, "dec")
    # trigger
    emit("      R0 = DM(0x25c4ac);")
    emit("      R0 = LSHIFT R0 BY -16;".ljust(40) + "// TRIG_NOTE")
    emit("      R2 = 1;")
    emit("      R2 = LSHIFT R2 BY R9;")
    emit("      R0 = R0 AND R2;")
    notrig = label("snotrig")
    jump("EQ", notrig)
    emit("      R0 = 1;")
    sst(0, "stage")
    emit("      R0 = R0 - R0;")
    sst(0, "x")
    place(notrig)
    emit("      R12 = LSHIFT R9 BY 2;")
    emit("      R11 = 0x254a60;".ljust(40) + "// the track buffers")
    emit("      R12 = R11 + R12;")
    emit("      I1 = R12;")
    emit("      R0 = DM(0, I1);")
    emit("      I0 = R0;".ljust(40) + "// this track's 32 floats")
    emit(f"      R0 = DM({SAVE + 0x24:#x});".ljust(40) + "// the block size")
    emit("      R0 = PASS R0;")
    jump("EQ", "wr_p_next")
    sst(0, "left")

    place("wr_s_sample")
    emit("      // the envelope -> F9")
    sld(0, "stage")
    s_dec, s_idle, e_done = label("sedec"), label("seidle"), label("sedone")
    emit("      R12 = 1;")
    emit("      COMP(R0, R12);")
    jump("NE", s_dec)
    sld(9, "x")
    sld(4, "x")
    sld(12, "atk")
    emit("      F4 = F4 + F12;")
    sst(4, "x")
    fconst(12, 1.0)
    emit("      COMP(F4, F12);")
    jump("LT", e_done)
    emit("      R0 = 2;")
    sst(0, "stage")
    emit("      R0 = R0 - R0;")
    sst(0, "x")
    jump("", e_done)
    place(s_dec)
    emit("      R12 = 2;")
    emit("      COMP(R0, R12);")
    jump("NE", s_idle)
    sld(4, "x")
    fconst(12, 1.0)
    emit("      F5 = F12 - F4;".ljust(40) + "// d = 1 - x")
    emit("      F9 = F5 * F5;")
    emit("      F9 = F9 * F5;".ljust(40) + "// d^3")
    sld(12, "dec")
    emit("      F4 = F4 + F12;")
    sst(4, "x")
    fconst(12, 1.0)
    emit("      COMP(F4, F12);")
    jump("LT", e_done)
    emit("      R0 = R0 - R0;")
    sst(0, "stage")
    sst(0, "x")
    jump("", e_done)
    place(s_idle)
    emit("      R9 = R9 - R9;".ljust(40) + "// a = 0.0")
    place(e_done)
    emit("      R8 = DM(0, I0);".ljust(40) + "// s, the machine's sample")
    sld(10, "fb")
    knee(10, 0.5, 0.5)
    sld(12, "drive")
    emit("      F11 = F8 * F12;")
    sld(12, "fdbk")
    emit("      F10 = F12 * F10;")
    emit("      F11 = F11 + F10;".ljust(40) + "// x")
    chain("a", SL.A2, 7)
    chain("b", SL.B2, 6)
    sld(0, "in1")
    sst(0, "in2")
    sst(11, "in1")
    sld(4, "iprev")
    sst(7, "iprev")
    emit("      // the oscillator: sin and cos from one table")
    sld(10, "phase")
    fconst(12, float(SL.SIN_N))
    emit("      F10 = F10 * F12;")
    emit("      F11 = PASS F10;")
    interp("sin", 10, 5, shft=True)
    fconst(12, float(SL.SIN_N // 4))
    emit("      F11 = F11 + F12;")
    interp("sin", 11, 7, shft=True)
    emit("      F7 = F4 * F7;".ljust(40) + "// i cos")
    emit("      F10 = F6 * F5;".ljust(40) + "// q sin")
    sld(0, "mode")
    m1, m2, mdone = label("sm1"), label("sm2"), label("smdone")
    emit("      R12 = 1;")
    emit("      COMP(R0, R12);")
    jump("EQ", m1)
    emit("      R12 = 2;")
    emit("      COMP(R0, R12);")
    jump("EQ", m2)
    emit("      F10 = F7 + F10;".ljust(40) + "// UP")
    jump("", mdone)
    place(m1)
    emit("      F10 = F7 - F10;".ljust(40) + "// DOWN")
    jump("", mdone)
    place(m2)
    emit("      F10 = PASS F7;".ljust(40) + "// BOTH")
    place(mdone)
    sst(10, "fb")
    sld(12, "inc_env")
    emit("      F12 = F12 * F9;")
    sld(13, "inc")
    emit("      F12 = F13 + F12;")
    sld(13, "phase")
    emit("      F13 = F13 + F12;")
    w1, w2 = label("swrap1"), label("swrap2")
    fconst(12, 1.0)
    emit("      COMP(F13, F12);")
    jump("LT", w1)
    emit("      F13 = F13 - F12;")
    place(w1)
    emit("      R12 = R12 - R12;")
    emit("      COMP(F13, F12);")
    jump("GE", w2)
    fconst(12, 1.0)
    emit("      F13 = F13 + F12;")
    place(w2)
    sst(13, "phase")
    knee(10, 0.6, 0.6)
    emit("      F10 = F10 - F8;")
    sld(12, "mix")
    emit("      F10 = F12 * F10;")
    emit("      F10 = F8 + F10;")
    emit("      DM(I0, M6) = F10;")
    sld(0, "left")
    emit("      R12 = 1;")
    emit("      R0 = R0 - R12;")
    sst(0, "left")
    jump("NE", "wr_s_sample")
    jump("", "wr_p_next")


def shape_into(fx: int, out: int) -> None:
    """F{out} = live.shape(F{fx}, curve): p = x * 256; c >= 0: x + c (exp[p] - x),
    else x - c (log[p] - x). Clobbers R0-R3, R5, R6, R12, R13, I1."""
    pos, done = label("cpos"), label("cdone")
    emit(f"      F5 = PASS F{fx};".ljust(40) + "// x")
    fconst(12, float(L.SHAPE_N))
    emit(f"      F13 = F{fx} * F12;".ljust(40) + "// p")
    ld(6, "curve")
    emit("      R12 = R12 - R12;")
    emit("      COMP(F6, F12);")
    jump("GE", pos)
    interp("log", 13, out)
    emit(f"      F{out} = F{out} - F5;")
    emit(f"      F{out} = F6 * F{out};")
    emit(f"      F{out} = F5 - F{out};")
    jump("", done)
    place(pos)
    interp("exp", 13, out)
    emit(f"      F{out} = F{out} - F5;")
    emit(f"      F{out} = F6 * F{out};")
    emit(f"      F{out} = F5 + F{out};")
    place(done)


def main() -> int:
    text = build()
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {sum(1 for l in text.splitlines() if l.startswith('      ') and not l.strip().startswith('//'))} instructions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

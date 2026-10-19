"""Write `csrc/waverider/sharc/gran.asm`: GRAN, the granular effect (filter type 8,
docs/gran.md), on the DSP.

    python scripts/gen_gran_asm.py

PING's track loop (ping.asm) jumps here for a track whose frame filter type is 8; this
runs `dnfw.grain.live.block` on the track's buffer, in place, and jumps back to PING's
`wr_p_next`. The code mirrors `dnfw.grain.live` operation by operation, in its order, so
the SHARC gate holds it to that module bit for bit. Branch targets are `0x0` with a
`// -> label.` comment (scripts/sharc_resolve_jumps.py fills them in); the jump back
into ping.asm is an address, checked against that object's layout by
test_gran_live.py and the gate's decode step. Instruction forms: only those PING and
Waverider's loop already use (no XOR, no multiply of integers, no hardware loops, no
CALL, every integer add R8-R15 first).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import gen_ping_asm as G                             # noqa: E402
from dnfw.grain import live as L                     # noqa: E402
from dnfw.waverider import dsp                       # noqa: E402
from dnfw.waverider import live as WL                # noqa: E402

OUT = ROOT / "csrc" / "waverider" / "sharc" / "gran.asm"
emit, label, jump, place, fconst, clamp01, knee, imm = (G.emit, G.label, G.jump, G.place,
                                                        G.fconst, G.clamp01, G.knee, G.imm)

_, AT = L.tables_bytes()
TAB = {name: dsp.GRAN_TABLES_DDR + off for name, off in AT.items()}

SC = dsp.GRAN_SCRATCH_DM
WORDS = ("t", "sbase", "rate", "len", "wstep", "spacing", "norm", "scatter", "base", "fdbk", "mix",
         "drive", "bufbase", "n", "gp", "j", "acc", "s", "wet", "ptr")
A = {w: SC + 4 * k for k, w in enumerate(WORDS)}
# per-track state, words: the write head, the random index, samples to the next grain,
# the next slot; then four grains of five words (pos, rate, wph, wstep, left)
S = {"w": 0, "idx": 1, "count": 2, "k": 3}
GRAIN0, GRAIN_WORDS = 8, 5


def ld(reg: int, word: str) -> None:
    emit(f"      R{reg} = DM({A[word]:#x});".ljust(40) + f"// {word}")


def st(reg: int, word: str) -> None:
    emit(f"      DM({A[word]:#x}) = R{reg};".ljust(40) + f"// {word}")


def at127(table: str, fv: int, out: int) -> None:
    """F{out} = live.at127(table, F{fv}). Clobbers R0, R12, I1, F{fv}."""
    emit(f"      // F{out} = {table}[trunc(clamp(F{fv}) * 127)]")
    clamp01(fv)
    fconst(12, 127.0)
    emit(f"      F{fv} = F{fv} * F12;")
    emit(f"      R0 = TRUNC F{fv};")
    emit("      R0 = LSHIFT R0 BY 2;")
    emit(f"      R12 = {imm(TAB[table])};".ljust(40) + f"// {table} ({TAB[table]:#x}, DDR)")
    emit("      R0 = R12 + R0;")
    emit("      I1 = R0;")
    emit(f"      R{out} = DM(0, I1);")


def ping_next() -> int:
    """ping.asm's wr_p_next, from its committed object (refused when stale)."""
    import sharc_resolve_jumps as R
    src = ROOT / "csrc" / "waverider" / "sharc" / "ping.asm"
    spec = json.loads(src.with_suffix(".json").read_text(encoding="utf-8"))
    text = src.read_text(encoding="utf-8")
    if spec["source_sha256"] != hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest():
        raise SystemExit("ping.json is stale: assemble ping.asm first")
    return int(spec["load_sw"], 16) + spec["instruction_offsets"][R.labels(text)["wr_p_next"]] // 2


def controls() -> None:
    """live.controls, into the scratch words."""
    emit("      // ---- controls (live.controls) ----")
    emit(f"      R8 = DM({L.R_TYPE // 4}, I4);".ljust(40) + "// TYPE -> MODE")
    clamp01(8)
    fconst(12, 4.0)
    emit("      F8 = F8 * F12;")
    emit("      R8 = TRUNC F8;")
    emit("      R12 = 3;")
    emit("      R8 = MIN(R8, R12);".ljust(40) + "// mode")
    # rate by mode: 1, 2, 0.5, -1
    r_done = label("rdone")
    fconst(1, 1.0)
    emit("      R12 = 1;")
    emit("      COMP(R8, R12);")
    jump("NE", m2 := label("m2"))
    fconst(1, 2.0)
    jump("", r_done)
    place(m2)
    emit("      R12 = 2;")
    emit("      COMP(R8, R12);")
    jump("NE", m3 := label("m3"))
    fconst(1, 0.5)
    jump("", r_done)
    place(m3)
    emit("      R12 = 3;")
    emit("      COMP(R8, R12);")
    jump("NE", r_done)
    fconst(1, -1.0)
    place(r_done)
    st(1, "rate")
    # size, len, wstep
    emit(f"      R9 = DM({L.R_FREQ // 4}, I4);".ljust(40) + "// FREQ -> SIZE")
    at127("size", 9, 10)
    emit("      R11 = TRUNC F10;".ljust(40) + "// len")
    st(11, "len")
    emit(f"      R9 = DM({L.R_FREQ // 4}, I4);")
    at127("wstep", 9, 1)
    st(1, "wstep")
    # base: GUARD, + len for UP
    emit(f"      R1 = {L.GUARD};")
    emit("      R12 = 1;")
    emit("      COMP(R8, R12);")
    jump("NE", b_ok := label("bok"))
    emit("      R1 = R11 + R1;".ljust(40) + "// UP: + len")
    place(b_ok)
    st(1, "base")
    # spacing = max(1, trunc(size * spacing[RES])); norm = norm[RES]
    emit(f"      R9 = DM({L.R_RES // 4}, I4);".ljust(40) + "// RESO -> DENS")
    at127("spacing", 9, 1)
    emit("      F1 = F10 * F1;".ljust(40) + "// size x 1/overlap")
    emit("      R1 = TRUNC F1;")
    emit("      R12 = 1;")
    emit("      R1 = MAX(R1, R12);")
    st(1, "spacing")
    emit(f"      R9 = DM({L.R_RES // 4}, I4);")
    at127("norm", 9, 1)
    st(1, "norm")
    # scatter = min(|depth - 0.5| * 2, 1) * SCATTER
    emit(f"      R1 = DM({L.R_SPRD // 4}, I4);".ljust(40) + "// ENV depth -> SPRD")
    fconst(12, 0.5)
    emit("      F1 = F1 - F12;")
    emit("      R12 = R12 - R12;")
    emit("      COMP(F1, F12);")
    jump("GE", pos := label("abs"))
    emit("      F1 = F12 - F1;".ljust(40) + "// |x|")
    place(pos)
    fconst(12, 2.0)
    emit("      F1 = F1 * F12;")
    fconst(12, 1.0)
    emit("      F1 = MIN(F1, F12);")
    fconst(12, L.SCATTER)
    emit("      F1 = F1 * F12;")
    st(1, "scatter")
    # fdbk, mix, drive
    emit(f"      R1 = DM({L.R_FDBK // 4}, I4);".ljust(40) + "// ATK -> FDBK")
    clamp01(1)
    fconst(12, L.FDBK_MAX)
    emit("      F1 = F1 * F12;")
    st(1, "fdbk")
    emit(f"      R1 = DM({L.R_MIX // 4}, I4);".ljust(40) + "// sustain -> MIX")
    clamp01(1)
    st(1, "mix")
    emit(f"      R1 = DM({L.R_DRIVE // 4}, I4);".ljust(40) + "// env delay -> DRIV")
    clamp01(1)
    fconst(12, 1.6)
    emit("      F1 = F12 * F1;")
    fconst(12, 0.4)
    emit("      F1 = F12 + F1;")
    st(1, "drive")


def start_grain() -> None:
    """live._start: the next random value, the delay, the slot's five words."""
    emit("      // ---- a new grain (live._start) ----")
    emit(f"      R1 = DM({S['idx']}, I2);")
    emit("      R2 = 255;")
    emit("      R2 = R1 AND R2;")
    emit("      R2 = LSHIFT R2 BY 2;")
    emit(f"      R12 = {dsp.W2_RND_DM:#x};".ljust(40) + "// Waverider's random table")
    emit("      R2 = R12 + R2;")
    emit("      I1 = R2;")
    emit("      R3 = DM(0, I1);".ljust(40) + "// r")
    emit("      R12 = 1;")
    emit("      R1 = R12 + R1;")
    emit(f"      DM({S['idx']}, I2) = R1;")
    ld(4, "scatter")
    emit("      F3 = F3 * F4;")
    emit("      R3 = TRUNC F3;")
    ld(12, "base")
    emit("      R3 = R12 + R3;".ljust(40) + "// d")
    emit(f"      R1 = DM({S['w']}, I2);")
    emit("      R1 = R1 - R3;")
    emit(f"      R12 = {L.MASK};")
    emit("      R1 = R1 AND R12;")
    emit("      R12 = R12 - R12;")
    emit("      F1 = FLOAT R1 BY R12;".ljust(40) + "// pos")
    # the slot's address: state + 4 (8 + 5k)
    emit(f"      R4 = DM({S['k']}, I2);")
    emit("      R12 = LSHIFT R4 BY 2;")
    emit("      R12 = R12 + R4;".ljust(40) + "// 5k")
    emit("      R5 = LSHIFT R12 BY 2;")
    emit(f"      R12 = {4 * GRAIN0};")
    emit("      R5 = R12 + R5;")
    ld(12, "sbase")
    emit("      R5 = R12 + R5;")
    emit("      I1 = R5;")
    emit("      DM(0, I1) = R1;".ljust(40) + "// pos")
    ld(1, "rate")
    emit("      DM(1, I1) = R1;".ljust(40) + "// rate")
    emit("      R1 = R1 - R1;")
    emit("      DM(2, I1) = R1;".ljust(40) + "// wph = 0")
    ld(1, "wstep")
    emit("      DM(3, I1) = R1;".ljust(40) + "// wstep")
    ld(1, "len")
    emit("      DM(4, I1) = R1;".ljust(40) + "// left")
    emit("      R12 = 1;")
    emit("      R4 = R12 + R4;")
    emit(f"      R12 = {L.GRAINS - 1};")
    emit("      R4 = R4 AND R12;")
    emit(f"      DM({S['k']}, I2) = R4;".ljust(40) + "// the next slot")


def grain() -> None:
    """One grain's sample, for the slot at I0 (live.block's inner loop)."""
    skip = label("gskip")
    emit("      R0 = DM(4, I0);".ljust(40) + "// left")
    emit("      R0 = PASS R0;")
    jump("LE", skip)
    emit("      R1 = DM(0, I0);".ljust(40) + "// pos")
    emit("      R2 = TRUNC F1;".ljust(40) + "// i")
    emit("      R12 = R12 - R12;")
    emit("      F3 = FLOAT R2 BY R12;")
    emit("      F3 = F1 - F3;".ljust(40) + "// f")
    ld(11, "bufbase")
    emit("      R4 = LSHIFT R2 BY 2;")
    emit("      R4 = R11 + R4;")
    emit("      I4 = R4;")
    emit("      R5 = DM(0, I4);".ljust(40) + "// a = buf[i]")
    emit("      R12 = 1;")
    emit("      R6 = R12 + R2;")
    emit(f"      R12 = {L.MASK};")
    emit("      R6 = R6 AND R12;")
    emit("      R6 = LSHIFT R6 BY 2;")
    emit("      R6 = R11 + R6;")
    emit("      I4 = R6;")
    emit("      R7 = DM(0, I4);".ljust(40) + "// b = buf[(i + 1) & MASK]")
    emit("      F7 = F7 - F5;")
    emit("      F7 = F3 * F7;")
    emit("      F5 = F5 + F7;".ljust(40) + "// x = a + f (b - a)")
    emit("      R8 = DM(2, I0);".ljust(40) + "// wph")
    fconst(12, 4.0)
    emit("      F9 = F12 * F8;")
    fconst(12, 1.0)
    emit("      F10 = F12 - F8;")
    emit("      F9 = F9 * F10;".ljust(40) + "// w = 4 wph (1 - wph)")
    emit("      F5 = F5 * F9;")
    ld(10, "acc")
    emit("      F10 = F10 + F5;")
    st(10, "acc")
    emit("      R2 = DM(1, I0);".ljust(40) + "// rate")
    emit("      F1 = F1 + F2;".ljust(40) + "// pos + rate")
    fconst(12, float(L.BUF_N))
    emit("      COMP(F1, F12);")
    jump("LT", lo := label("plo"))
    emit("      F1 = F1 - F12;")
    place(lo)
    emit("      R12 = R12 - R12;")
    emit("      COMP(F1, F12);")
    jump("GE", ok := label("pok"))
    fconst(12, float(L.BUF_N))
    emit("      F1 = F1 + F12;")
    place(ok)
    emit("      DM(0, I0) = R1;")
    emit("      R3 = DM(3, I0);".ljust(40) + "// wstep")
    emit("      F8 = F8 + F3;")
    emit("      DM(2, I0) = R8;")
    emit("      R12 = 1;")
    emit("      R0 = R0 - R12;")
    emit("      DM(4, I0) = R0;")
    place(skip)


def build() -> str:
    G.lines.clear()
    emit("// gran.asm -- GRAN, the granular effect, filter type 8 (docs/gran.md).")
    emit("// GENERATED by scripts/gen_gran_asm.py; do not edit by hand. The contract is")
    emit("// dnfw.grain.live, operation by operation: the SHARC gate holds this to it bit for bit.")
    emit("//")
    emit("// Entered by ping.asm's track loop for a track whose frame filter type is 8, with")
    emit("// the track in DM(PING_T); runs one block on the track's buffer in place and jumps")
    emit("// back to ping.asm's wr_p_next. PING restores every register at its end.")
    emit(f"// State: 16 x {dsp.GRAN_STATE_STRIDE} bytes at {dsp.GRAN_STATE_DM:#x}; scratch {SC:#x};")
    emit(f"// tables {dsp.GRAN_TABLES_DDR:#x} and buffers {dsp.GRAN_BUF_DDR:#x} + {dsp.GRAN_BUF_STRIDE:#x} t (DDR).")
    emit("")
    emit(".SECTION/PM seg_pmco;")
    emit("")
    emit(".GLOBAL wr_gran.;")
    emit("wr_gran.:")
    emit(f"      R9 = DM({dsp.PING_T_DM:#x});".ljust(40) + "// t")
    st(9, "t")
    emit(f"      R12 = LSHIFT R9 BY {dsp.GRAN_STATE_STRIDE.bit_length() - 1};")
    emit(f"      R11 = {dsp.GRAN_STATE_DM:#x};")
    emit("      R12 = R11 + R12;")
    emit("      I2 = R12;".ljust(40) + "// this track's GRAN state")
    st(12, "sbase")
    emit(f"      R12 = LSHIFT R9 BY {dsp.GRAN_BUF_STRIDE.bit_length() - 1};")
    emit(f"      R11 = {imm(dsp.GRAN_BUF_DDR)};".ljust(40) + f"// {dsp.GRAN_BUF_DDR:#x}, DDR")
    emit("      R12 = R11 + R12;")
    st(12, "bufbase")
    G.record_base()
    controls()
    # the track's buffer (controls() used R9: t again)
    ld(9, "t")
    emit("      R12 = LSHIFT R9 BY 2;")
    emit("      R11 = 0x254a60;".ljust(40) + "// the track buffers")
    emit("      R12 = R11 + R12;")
    emit("      I1 = R12;")
    emit("      R0 = DM(0, I1);")
    st(0, "ptr")
    emit("      R0 = 32;")
    st(0, "n")
    place("wr_g_sample")
    emit(f"      R0 = DM({S['count']}, I2);")
    emit("      R12 = 1;")
    emit("      R0 = R0 - R12;")
    emit(f"      DM({S['count']}, I2) = R0;")
    emit("      R0 = PASS R0;")
    jump("GT", "wr_g_nostart")
    ld(12, "spacing")
    emit("      R0 = R12 + R0;")
    emit(f"      DM({S['count']}, I2) = R0;")
    start_grain()
    place("wr_g_nostart")
    emit("      R0 = R0 - R0;")
    st(0, "acc")
    for g in range(L.GRAINS):
        ld(12, "sbase")
        emit(f"      R11 = {4 * (GRAIN0 + GRAIN_WORDS * g)};")
        emit("      R12 = R11 + R12;")
        emit("      I0 = R12;".ljust(40) + f"// grain {g}")
        grain()
    # wet, the buffer write, the output
    ld(10, "acc")
    ld(12, "norm")
    emit("      F10 = F10 * F12;".ljust(40) + "// wet")
    st(10, "wet")
    ld(0, "ptr")
    emit("      I1 = R0;")
    emit("      R1 = DM(0, I1);".ljust(40) + "// s")
    st(1, "s")
    knee(10, 0.5, 0.5)                                # fb, in F10
    ld(12, "fdbk")
    emit("      F10 = F12 * F10;")
    ld(1, "s")
    ld(12, "drive")
    emit("      F1 = F1 * F12;")
    emit("      F1 = F1 + F10;".ljust(40) + "// s drive + fdbk fb")
    emit(f"      R2 = DM({S['w']}, I2);")
    emit("      R3 = LSHIFT R2 BY 2;")
    ld(11, "bufbase")
    emit("      R3 = R11 + R3;")
    emit("      I4 = R3;")
    emit("      DM(0, I4) = R1;")
    emit("      R12 = 1;")
    emit("      R2 = R12 + R2;")
    emit(f"      R12 = {L.MASK};")
    emit("      R2 = R2 AND R12;")
    emit(f"      DM({S['w']}, I2) = R2;")
    ld(10, "wet")
    knee(10, 0.6, 0.6)                                # y
    ld(1, "s")
    emit("      F10 = F10 - F1;")
    ld(12, "mix")
    emit("      F10 = F12 * F10;")
    emit("      F1 = F1 + F10;".ljust(40) + "// s + mix (y - s)")
    ld(0, "ptr")
    emit("      I1 = R0;")
    emit("      DM(0, I1) = R1;")
    emit("      R12 = 4;")
    emit("      R0 = R12 + R0;")
    st(0, "ptr")
    ld(0, "n")
    emit("      R12 = 1;")
    emit("      R0 = R0 - R12;")
    st(0, "n")
    jump("NE", "wr_g_sample")
    emit(f"      JUMP {ping_next():#x};".ljust(40) + "// ping.asm's wr_p_next (checked by test_gran_live)")
    emit(".wr_gran..end:")
    emit("      .type wr_gran.,STT_FUNC;")
    return "\n".join(G.lines) + "\n"


def main() -> int:
    text = build()
    OUT.write_text(text, encoding="utf-8", newline="\n")
    n = sum(1 for ln in text.splitlines() if ln.startswith("      ") and not ln.strip().startswith("//"))
    print(f"wrote {OUT.relative_to(ROOT)}: {n} instructions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""One program, two backends: SHARC assembly text, and its exact execution in Python.

PERC's DSP code (docs/perc.md) is written once, as calls on a `Prog`. In **emit** mode each
call appends the instruction it stands for to the assembly; in **run** mode it performs
that instruction on a register file and a memory, with the SHARC's semantics for the
forms we use: float32 arithmetic rounded to nearest, FLOAT/TRUNC, 32-bit integer
arithmetic, logical and arithmetic shifts, word loads and stores at byte addresses.

Control flow is structured (`if_`, `loop`): emit mode writes both arms with labels and
`JUMP 0x0; // -> label.` targets (scripts/sharc_resolve_jumps.py fills them in); run mode
evaluates the condition and runs one arm. So the model *is* the program: what the SHARC
runner holds the assembled code to, bit for bit, is this module running the same calls.
That checks the assembler, the encodings and these semantics; whether the program
sounds like the design is checked separately, against the design (test_perc_live.py).

The instruction forms are the ones our other SHARC code already uses (and the gate's
decode step reads every instruction back): no XOR, no integer multiply, no hardware
loops, no CALL; every integer add has R8..R15 as its first operand.
"""

from __future__ import annotations

import math
import struct


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def bits(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


def flt(b: int) -> float:
    return struct.unpack("<f", struct.pack("<I", b & 0xFFFFFFFF))[0]


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def imm(v: int) -> str:
    """A 32-bit literal as selmap prints it: signed when its top bit is set."""
    v &= 0xFFFFFFFF
    return f"-{(1 << 32) - v:#x}" if v >> 31 else f"{v:#x}"


def fimm(x: float) -> str:
    return imm(bits(f32(x)))


COND = {"EQ": lambda c: c == 0, "NE": lambda c: c != 0, "LT": lambda c: c < 0,
        "GE": lambda c: c >= 0, "LE": lambda c: c <= 0, "GT": lambda c: c > 0}
NOT = {"EQ": "NE", "NE": "EQ", "LT": "GE", "GE": "LT", "LE": "GT", "GT": "LE"}


class Mem:
    """Run mode's memory: word reads and writes at byte addresses; READ supplies what
    this run has not written (the DSP's own memory, in the runner)."""

    def __init__(self, read=None):
        self.w: dict[int, int] = {}
        self.read = read or (lambda a: 0)

    def get(self, a: int) -> int:
        a &= 0xFFFFFFFF
        return self.w[a] if a in self.w else (self.read(a) or 0) & 0xFFFFFFFF

    def put(self, a: int, v: int) -> None:
        self.w[a & 0xFFFFFFFF] = v & 0xFFFFFFFF


class Prog:
    def __init__(self, mode: str = "emit", mem: Mem | None = None, prefix: str = "pk"):
        assert mode in ("emit", "run")
        self.mode, self.mem = mode, mem or Mem()
        self.lines: list[str] = []
        self.r = [0] * 16                 # R0..R15 (F aliases R)
        self.i = [0] * 8                  # I0..I7 (byte addresses)
        self.n_label = 0
        self.prefix = prefix
        self.steps = 0
        self.subs: dict[str, object] = {}       # name -> body, emitted once by emit_subs()
        self.in_sub = False
        self.spill: int | None = None           # a DM word `ash` may use (see ash)

    # -- emit helpers -------------------------------------------------------------------
    @property
    def run(self) -> bool:
        return self.mode == "run"

    def e(self, text: str, note: str = "") -> None:
        if not self.run:
            line = f"      {text}"
            self.lines.append(line.ljust(40) + f"// {note}" if note else line)
        else:
            self.steps += 1

    def comment(self, text: str) -> None:
        if not self.run:
            self.lines.append(f"      // {text}")

    def raw(self, text: str) -> None:
        if not self.run:
            self.lines.append(text)

    def label(self, stem: str) -> str:
        self.n_label += 1
        return f"wr_{self.prefix}_{stem}_{self.n_label}"

    def place(self, name: str) -> None:
        if not self.run:
            self.lines += [f".GLOBAL {name}.;", f"{name}.:"]

    def jump(self, cond: str, target: str) -> None:
        if not self.run:
            pre = f"IF {cond} " if cond else ""
            self.lines.append(f"      {pre}JUMP 0x0;".ljust(40) + f"// -> {target}.")

    def jump_abs(self, cond: str, addr: int, note: str) -> None:
        if not self.run:
            pre = f"IF {cond} " if cond else ""
            self.lines.append(f"      {pre}JUMP {addr:#x};".ljust(40) + f"// {note}")

    # -- registers ----------------------------------------------------------------------
    def F(self, k: int) -> float:
        return flt(self.r[k])

    def setF(self, k: int, x: float) -> None:
        self.r[k] = bits(f32(x))

    def setR(self, k: int, v: int) -> None:
        self.r[k] = v & 0xFFFFFFFF

    # -- constants ----------------------------------------------------------------------
    def fconst(self, d: int, x: float, note: str = "") -> None:
        self.e(f"R{d} = {fimm(x)};", note or repr(f32(x)))
        if self.run:
            self.setF(d, f32(x))

    def iconst(self, d: int, v: int, note: str = "") -> None:
        self.e(f"R{d} = {imm(v)};", note)
        if self.run:
            self.setR(d, v)

    # -- float -------------------------------------------------------------------------
    def fop(self, d: int, a: int, op: str, b: int, note: str = "") -> None:
        if op in ("MIN", "MAX"):
            self.e(f"F{d} = {op}(F{a}, F{b});", note)
        else:
            self.e(f"F{d} = F{a} {op} F{b};", note)
        if self.run:
            x, y = self.F(a), self.F(b)
            v = {"+": lambda: x + y, "-": lambda: x - y, "*": lambda: x * y,
                 "MIN": lambda: min(x, y), "MAX": lambda: max(x, y)}[op]()
            self.setF(d, f32(v))

    def fpass(self, d: int, a: int, note: str = "") -> None:
        self.e(f"F{d} = PASS F{a};", note)
        if self.run:
            self.r[d] = self.r[a]

    def trunc(self, d: int, a: int, note: str = "") -> None:
        self.e(f"R{d} = TRUNC F{a};", note)
        if self.run:
            x = self.F(a)
            v = int(math.trunc(x)) if math.isfinite(x) else 0
            self.setR(d, max(-(1 << 31), min((1 << 31) - 1, v)))

    def float_(self, d: int, a: int, s: int, note: str = "") -> None:
        """Fd = FLOAT Ra BY Rs: the signed integer Ra times 2^Rs."""
        self.e(f"F{d} = FLOAT R{a} BY R{s};", note)
        if self.run:
            self.setF(d, f32(float(s32(self.r[a])) * 2.0 ** s32(self.r[s])))

    # -- integer ------------------------------------------------------------------------
    def iop(self, d: int, a: int, op: str, b: int, note: str = "") -> None:
        if op == "+":
            assert 8 <= a <= 15, "integer adds take R8..R15 first (docs/waverider-m5-dsp.md, G5)"
        if op in ("MIN", "MAX"):
            self.e(f"R{d} = {op}(R{a}, R{b});", note)
        else:
            self.e(f"R{d} = R{a} {op} R{b};", note)
        if self.run:
            x, y = self.r[a], self.r[b]
            v = {"+": lambda: x + y, "-": lambda: x - y, "AND": lambda: x & y, "OR": lambda: x | y,
                 "MIN": lambda: min(s32(x), s32(y)), "MAX": lambda: max(s32(x), s32(y))}[op]()
            self.setR(d, v)

    def ipass(self, d: int, a: int, note: str = "") -> None:
        self.e(f"R{d} = PASS R{a};", note)
        if self.run:
            self.r[d] = self.r[a]

    def lsh(self, d: int, a: int, n: int, note: str = "") -> None:
        self.e(f"R{d} = LSHIFT R{a} BY {n};", note)
        if self.run:
            x = self.r[a]
            self.setR(d, (x << n) if n >= 0 else (x >> -n))

    def ash(self, d: int, a: int, n: int, note: str = "", keep12: bool = False) -> None:
        """Rd = Ra >> -n, arithmetic. selas mis-encodes the immediate form `ASHIFT Rx BY n`
        (its shifter-op field is not the one the firmware's immediate ASHIFTs carry:
        digikit reads it as "unsupported ShiftImm opcode 0x20", reader.asm), so the count
        goes in a register: R12, the DSL's scratch (the run mode sets it too, so a caller
        that needed R12 kept fails its model), unless d or a is R12 or KEEP12 -- then
        another register, saved to and restored from the word `self.spill`."""
        assert n < 0
        if 12 not in (d, a) and not keep12:
            x = s32(self.r[a]) >> -n if self.run else 0
            self.iconst(12, n)
            self.e(f"R{d} = ASHIFT R{a} BY R12;", note)
            if self.run:
                self.setR(d, x)
            return
        if not self.run:
            assert self.spill is not None, "ash needs Prog.spill"
        t = next(r for r in (13, 14, 15) if r not in (d, a))
        if self.spill is not None:
            self.st(self.spill, t)
        else:
            self.steps += 1
        x = s32(self.r[a]) >> -n if self.run else 0
        self.iconst(t, n)
        self.e(f"R{d} = ASHIFT R{a} BY R{t};", note)
        if self.spill is not None:
            self.ld(t, self.spill)
        else:
            self.steps += 1
        if self.run:
            self.setR(d, x)

    def xor(self, d: int, a: int, b: int, t: int) -> None:
        """Rd = Ra ^ Rb as (Ra | Rb) - (Ra & Rb) (no XOR form in the stock corpus).
        Clobbers Rt; d may equal a."""
        self.iop(t, a, "AND", b)
        self.iop(d, a, "OR", b)
        self.iop(d, d, "-", t)

    # -- memory -------------------------------------------------------------------------
    def ld(self, d: int, addr: int, note: str = "") -> None:
        self.e(f"R{d} = DM({imm(addr)});", note)
        if self.run:
            self.r[d] = self.mem.get(addr)

    def st(self, addr: int, s: int, note: str = "") -> None:
        self.e(f"DM({imm(addr)}) = R{s};", note)
        if self.run:
            self.mem.put(addr, self.r[s])

    def ldi(self, d: int, k: int, i: int, note: str = "") -> None:
        self.e(f"R{d} = DM({k}, I{i});", note)
        if self.run:
            self.r[d] = self.mem.get(self.i[i] + 4 * k)

    def sti(self, k: int, i: int, s: int, note: str = "") -> None:
        self.e(f"DM({k}, I{i}) = R{s};", note)
        if self.run:
            self.mem.put(self.i[i] + 4 * k, self.r[s])

    def seti(self, i: int, s: int, note: str = "") -> None:
        self.e(f"I{i} = R{s};", note)
        if self.run:
            self.i[i] = self.r[s]

    def stpost(self, i: int, s: int, note: str = "") -> None:
        """DM(Ii, M6) = Fs: store, then Ii moves one word on (M6 = 1)."""
        self.e(f"DM(I{i}, M6) = F{s};", note)
        if self.run:
            self.mem.put(self.i[i], self.r[s])
            self.i[i] += 4

    def ldpost(self, d: int, i: int, note: str = "") -> None:
        self.e(f"R{d} = DM(I{i}, M6);", note)
        if self.run:
            self.r[d] = self.mem.get(self.i[i])
            self.i[i] += 4

    # -- structured control flow ------------------------------------------------------
    def _cmp(self, a: int, b: int, kind: str) -> int:
        if kind == "f":
            x, y = self.F(a), self.F(b)
        else:
            x, y = s32(self.r[a]), s32(self.r[b])
        return (x > y) - (x < y)

    def if_(self, a: int, cond: str, b: int, then, else_=None, kind: str = "f") -> None:
        """if (a COND b) then() else else_(). kind 'f': COMP(Fa, Fb); 'i': COMP(Ra, Rb)."""
        self.e(f"COMP({'F' if kind == 'f' else 'R'}{a}, {'F' if kind == 'f' else 'R'}{b});")
        self._branch(lambda: COND[cond](self._cmp(a, b, kind)), cond, then, else_)

    def ifz(self, a: int, cond: str, then, else_=None, kind: str = "i") -> None:
        """if (a COND 0) by PASS (kind 'i': R, 'f': F)."""
        self.e(f"{'R' if kind == 'i' else 'F'}{a} = PASS {'R' if kind == 'i' else 'F'}{a};")

        def test():
            x = s32(self.r[a]) if kind == "i" else self.F(a)
            return COND[cond]((x > 0) - (x < 0))
        self._branch(test, cond, then, else_)

    def _branch(self, test, cond, then, else_) -> None:
        if self.run:
            if test():
                then()
            elif else_:
                else_()
            return
        skip = self.label("else")
        self.jump(NOT[cond], skip)
        then()
        if else_:
            end = self.label("fi")
            self.jump("", end)
            self.place(skip)
            else_()
            self.place(end)
        else:
            self.place(skip)

    def loop(self, counter: int, n_from: int, body, one: int = 12) -> None:
        """for (counter = n_from; counter; counter--) body(). COUNTER is a scratch word
        address (the body may use every register). ONE: a register body() leaves free."""
        self.iconst(0, n_from)
        self.st(counter, 0)
        top = self.label("loop")
        self.place(top)
        if self.run:
            while True:
                body()
                self.ld(0, counter)
                self.iconst(one, 1)
                self.iop(0, 0, "-", one)
                self.st(counter, 0)
                if self.r[0] == 0:
                    break
            return
        body()
        self.ld(0, counter)
        self.iconst(one, 1)
        self.iop(0, 0, "-", one)
        self.st(counter, 0)
        self.jump("NE", top)

    # -- leaf subroutines ---------------------------------------------------------------
    def call(self, name: str, body) -> None:
        """A leaf subroutine: run mode runs BODY here; emit mode jumps to its one copy with
        the return address - 1 in I12, and the copy ends `JUMP (M14, I12)` (M14 is 1, an
        ABI constant), not delayed. Clobbers R12 and I12 (saved and restored around the
        whole program); BODY must not call."""
        assert not self.in_sub, f"{name}: subroutines are leaves"
        if self.run:
            self.in_sub = True
            body()
            self.in_sub = False
            return
        self.subs.setdefault(name, body)
        ret = self.label("ret")
        self.lines.append("      R12 = 0x0;".ljust(40) + f"// return address - 1: {ret}. - 1")
        self.e("I12 = R12;")
        self.jump("", f"wr_{self.prefix}_sub_{name}")
        self.place(ret)

    def emit_subs(self) -> None:
        for name, body in list(self.subs.items()):
            self.place(f"wr_{self.prefix}_sub_{name}")
            self.in_sub = True
            body()
            self.in_sub = False
            # not delayed: the delayed form, JUMP (M14, I12) (DB), is the compiler's
            # function return, and the SHARC runner holds that form to its call stack
            self.e("JUMP (M14, I12);")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

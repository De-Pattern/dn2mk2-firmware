"""dnfw.perc.dsl: packing a memory move into the compute next to it (Prog(merge=True), off by
default), and the conditional and small operations. With packing off nothing a program emits
or counts changes; with it on, run mode counts a packed pair as one step at exactly the pairs
emit mode packs, and computes the same results."""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

from dnfw.perc.dsl import Mem, Prog, bits, f32

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARC = ROOT / "csrc" / "waverider" / "sharc"
SETUP = 8                                       # _setup's instructions


def _word(a: int) -> int:
    return bits(f32(a / 4096.0))


def _setup(p: Prog) -> None:
    p.iconst(8, 0x1000)
    p.seti(1, 8)                                # I1 -> 0x1000
    p.iconst(8, 0x2000)
    p.seti(0, 8)                                # I0 -> 0x2000
    p.fconst(2, 1.5)
    p.fconst(3, 2.25)
    p.fconst(6, 0.5)
    p.fconst(7, -3.0)


def _both(body, merge: bool) -> tuple[Prog, Prog]:
    e = Prog("emit", merge=merge)
    _setup(e)
    body(e)
    e.emit_subs()
    r = Prog("run", mem=Mem(_word), merge=merge)
    _setup(r)
    body(r)
    return e, r


def _instructions(p: Prog) -> int:
    """Emit mode's instructions that run mode counts as steps (not jumps, nor a call's
    return-address load and I12 = R12)."""
    n = 0
    for ln in p.lines:
        t = ln.split("//", 1)[0].strip()
        if not t or t.startswith(".") or t.endswith(":") or "JUMP" in t or t == "I12 = R12;" \
                or "return address" in ln:
            continue
        n += 1
    return n


def _state(p: Prog):
    return list(p.r), list(p.i), dict(p.mem.w)


def _code(p: Prog) -> list[str]:
    return [ln.split("//", 1)[0].strip() for ln in p.lines if ln.split("//", 1)[0].strip()]


# -- off: nothing changes ------------------------------------------------------------------

def test_packing_is_off_unless_asked_and_the_programs_emit_what_is_committed():
    """With packing off (the default) the DSL emits what it emitted before packing existed:
    PERC's and the sample machines' programs are still exactly their committed sources
    (branch targets aside: the resolver fills those in)."""
    assert Prog().merge is False and Prog("run").merge is False
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_perc_asm
    import gen_smp_asm
    lit = re.compile(r"(JUMP\s+)0x[0-9a-f]+;|(=\s*)0x[0-9a-f]+(;\s*// return address)")

    def norm(text):
        return lit.sub(lambda m: (m.group(1) or m.group(2)) + "0x0;" + (m.group(3) or "")[1:], text)
    for gen, name in ((gen_perc_asm, "perc"), (gen_smp_asm, "smp")):
        assert norm(gen.build()) == norm((SHARC / f"{name}.asm").read_text(encoding="utf-8")), name


def test_packing_off_keeps_every_move_on_its_own_line():
    def body(p):
        p.fop(1, 2, "+", 3)
        p.ldpost(4, 1)
        p.ldi(5, 3, 0)
        p.fop(6, 2, "*", 3)
    e, r = _both(body, False)
    assert _code(e)[-4:] == ["F1 = F2 + F3;", "R4 = DM(I1, M6);", "R5 = DM(3, I0);", "F6 = F2 * F3;"]
    assert r.steps == SETUP + 4 == _instructions(e)


# -- on: what is packed, and the counts ----------------------------------------------------

def test_a_move_after_a_compute_is_packed_into_it():
    def body(p):
        p.fop(1, 2, "+", 3)
        p.ldpost(4, 1)
    (e, r), (e0, r0) = _both(body, True), _both(body, False)
    assert _code(e)[-1] == "F1 = F2 + F3, R4 = DM(I1, M6);"
    assert _code(e0)[-2:] == ["F1 = F2 + F3;", "R4 = DM(I1, M6);"]
    assert (r.steps, r0.steps) == (SETUP + 1, SETUP + 2)
    assert r.steps == _instructions(e) and r0.steps == _instructions(e0)
    assert _state(r) == _state(r0)


def test_a_move_before_a_compute_is_packed_into_it_across_a_comment():
    # a comment is not an instruction: run mode never sees it, so emit mode packs across it
    def body(p):
        p.ldi(4, 3, 0)
        p.comment("a comment between them")
        p.fop(1, 2, "*", 3)
    (e, r), (e0, r0) = _both(body, True), _both(body, False)
    assert [ln.strip() for ln in e.lines[-2:]] == ["// a comment between them", "F1 = F2 * F3, R4 = DM(3, I0);"]
    assert (r.steps, r0.steps) == (SETUP + 1, SETUP + 2)
    assert r.steps == _instructions(e) and r0.steps == _instructions(e0)
    assert _state(r) == _state(r0)


def test_a_store_before_a_compute_stores_the_old_value():
    def body(p):
        p.fconst(1, 7.0)
        p.sti(0, 0, 1)
        p.fop(1, 2, "+", 3)
    (e, r), (_e0, r0) = _both(body, True), _both(body, False)
    assert _code(e)[-1] == "F1 = F2 + F3, DM(0, I0) = R1;"
    assert r.mem.w[0x2000] == bits(7.0) and r.F(1) == 3.75
    assert r.steps == SETUP + 2 == _instructions(e)
    assert _state(r) == _state(r0)


@pytest.mark.parametrize("case", ["load into the result", "load into an operand", "store of the result",
                                  "I4", "offset 40", "a constant between"])
def test_what_is_not_packed(case):
    def body(p):
        if case == "load into the result":
            p.fop(1, 2, "+", 3)
            p.ldpost(1, 1)
        elif case == "load into an operand":
            p.ldi(2, 0, 0)
            p.fop(1, 2, "+", 3)
        elif case == "store of the result":
            p.fop(1, 2, "+", 3)
            p.stpost(1, 1)
        elif case == "I4":
            p.iconst(8, 0x3000)
            p.seti(4, 8)
            p.fop(1, 2, "+", 3)
            p.ldpost(5, 4)
        elif case == "offset 40":
            p.fop(1, 2, "+", 3)
            p.ldi(5, 40, 0)
        else:
            p.fop(1, 2, "+", 3)
            p.iconst(9, 5)
            p.ldpost(5, 1)
    (e, r), (e0, r0) = _both(body, True), _both(body, False)
    assert e.lines == e0.lines
    assert r.steps == r0.steps == _instructions(e)
    assert _state(r) == _state(r0)


@pytest.mark.parametrize("move_first", [False, True])
def test_a_constant_load_emit_mode_leaves_out_still_parts_the_pair(move_first):
    # emit mode leaves the second R9 = 5 out (R9 holds 5 already); run mode loads it. Neither
    # packs across it, so run mode counts emit mode's instructions plus that load
    def body(p):
        p.iconst(9, 5)
        if move_first:
            p.ldpost(4, 1)
            p.iconst(9, 5)
            p.fop(1, 2, "+", 3)
        else:
            p.fop(1, 2, "+", 3)
            p.iconst(9, 5)
            p.ldpost(4, 1)
    (e, r), (_e0, r0) = _both(body, True), _both(body, False)
    assert sum(1 for t in _code(e) if t == "R9 = 0x5;") == 1
    assert not any(", R4 = DM" in t for t in _code(e))
    assert r.steps == r0.steps == _instructions(e) + 1
    assert _state(r) == _state(r0)


def test_nothing_is_packed_across_a_branch():
    def body(p):
        p.if_(2, "LT", 3, lambda: p.fop(1, 2, "+", 3))      # taken: 1.5 < 2.25
        p.ldpost(4, 1)
    (e, r), (_e0, r0) = _both(body, True), _both(body, False)
    assert not any(", R4 = DM" in t for t in _code(e))
    assert r.steps == r0.steps == SETUP + 3 == _instructions(e)
    assert _state(r) == _state(r0)


def test_nothing_is_packed_across_a_loops_top_or_its_jump_back():
    def body(p):
        def each():
            p.ldpost(4, 1)
            p.fop(5, 6, "+", 7)                 # takes the load in (one step a time round)
        p.loop_r(9, 2, each)
        p.ldpost(10, 1)
    (e, r), (_e0, r0) = _both(body, True), _both(body, False)
    assert "F5 = F6 + F7, R4 = DM(I1, M6);" in _code(e)
    assert _code(e)[-1] == "R10 = DM(I1, M6);"
    # R9 = 2; twice: the packed pair, R12 = 1, R9 = R9 - R12; then the load after
    assert (r.steps, r0.steps) == (SETUP + 1 + 2 * 3 + 1, SETUP + 1 + 2 * 4 + 1)
    assert _state(r) == _state(r0)


def test_nothing_is_packed_into_or_out_of_a_call():
    def body(p):
        def sub():
            p.ldpost(4, 1)
            p.fop(5, 6, "+", 7)
        p.fop(1, 2, "+", 3)
        p.call("sub", sub)
        p.ldpost(10, 1)
    (e, r), (_e0, r0) = _both(body, True), _both(body, False)
    code = _code(e)
    assert "F1 = F2 + F3;" in code and "R10 = DM(I1, M6);" in code
    assert "F5 = F6 + F7, R4 = DM(I1, M6);" in code
    assert r.steps == SETUP + 3 == _instructions(e)
    assert r0.steps == SETUP + 4
    assert _state(r) == _state(r0)


# -- the new operations --------------------------------------------------------------------

def test_fop_if_takes_the_flags_of_the_alu_op_before_it():
    p = Prog("run")
    p.fconst(1, 1.0)
    p.fconst(2, 3.0)
    p.fop(3, 1, "-", 2)                         # -2: LT
    p.fop_if("LT", 4, 1, "+", 2)
    assert p.F(4) == 4.0
    p.fop(3, 2, "-", 1)                         # 2: not LT
    p.fop_if("LT", 5, 1, "+", 2)
    assert p.r[5] == 0
    p.fop(3, 1, "-", 1)                         # +0: EQ, not GT
    p.fop_if("EQ", 6, 2, "PASS")
    assert p.F(6) == 3.0
    p.fop(3, 1, "-", 1)
    p.fop_if("GT", 7, 2, "PASS")
    assert p.r[7] == 0
    p.iconst(8, 0x7FC00000)                     # a NaN: the result is all ones, AN set, not zero
    p.fop(3, 8, "+", 1)
    assert p.r[3] == 0xFFFFFFFF
    p.fop_lt(9, 1, "+", 2)
    assert p.F(9) == 4.0
    p.fop(3, 1, "MIN", 2)                       # MIN is an ALU op too: 1, not LT
    p.fop_lt(10, 1, "+", 2)
    assert p.r[10] == 0


def test_the_conditional_lines():
    e = Prog("emit")
    e.fop(3, 1, "-", 2)
    e.fop_if("LT", 4, 1, "*", 2)
    e.fop(3, 1, "-", 2)
    e.fop_if("GE", 4, 1, "PASS")
    e.fop(3, 1, "MAX", 2)
    e.fop_lt(4, 1, "-", 2)
    e.fop(3, 1, "+", 2)
    e.iop_if("LE", 9, 10, "+", 11)
    e.comp_iop_if(1, 2, "LT", 9, 10, "-", 11)
    assert [t for t in _code(e) if not t.startswith("F3")] == [
        "IF LT F4 = F1 * F2;", "IF GE F4 = PASS F1;", "IF LT F4 = F1 - F2;", "IF LE R9 = R10 + R11;",
        "COMP(R1, R2);", "IF LT R9 = R10 - R11;"]


@pytest.mark.parametrize("mode", ["emit", "run"])
def test_a_conditional_compute_must_follow_an_alu_op_directly(mode):
    befores = (lambda p: p.fop(3, 1, "*", 2),                                     # the multiplier
               lambda p: (p.fop(3, 1, "-", 2), p.iconst(9, 1)),
               lambda p: (p.iconst(9, 1), p.fop(3, 1, "-", 2), p.iconst(9, 1)),   # left out in emit mode
               lambda p: (p.fop(3, 1, "-", 2), p.place(p.label("x"))),
               lambda p: (p.fop(3, 1, "-", 2), p.fop_if("LT", 4, 1, "+", 2)))
    for before in befores:
        p = Prog(mode)
        before(p)
        with pytest.raises(AssertionError):
            p.fop_if("LT", 4, 1, "+", 2)
        with pytest.raises(AssertionError):
            p.iop_if("LT", 9, 10, "+", 11)


def test_iop_if_and_comp_iop_if():
    p = Prog("run")
    p.fconst(1, 1.0)
    p.fconst(2, 3.0)
    p.iconst(10, 5)
    p.iconst(11, 7)
    p.fop(3, 1, "-", 2)
    p.iop_if("LT", 9, 10, "+", 11)
    assert p.r[9] == 12
    p.fop(3, 2, "-", 1)
    p.iop_if("LT", 9, 10, "-", 11)
    assert p.r[9] == 12
    p.fop(3, 1, "-", 2)
    p.iop_if("LE", 9, 10, "-", 11)
    assert p.r[9] == 0xFFFFFFFE
    p.iconst(1, 3)
    p.iconst(2, 5)
    s = p.steps
    p.comp_iop_if(1, 2, "LT", 8, 10, "-", 11)
    assert p.r[8] == 0xFFFFFFFE and p.steps == s + 2
    p.comp_iop_if(2, 1, "LT", 8, 10, "+", 11)
    assert p.r[8] == 0xFFFFFFFE


def test_dec_geti_fabs_float0():
    p, e = Prog("run"), Prog("emit")
    for q in (p, e):
        q.iconst(10, 0)
        q.dec(9, 10)
        q.iconst(8, 0x1234)
        q.seti(2, 8)
        q.geti(7, 2)
        q.iconst(1, -3 & 0xFFFFFFFF)
        q.float0(2, 1)
        q.iconst(5, 0)
        q.float_(3, 1, 5)
    assert p.r[9] == 0xFFFFFFFF and p.r[7] == 0x1234
    assert p.F(2) == -3.0 and p.r[2] == p.r[3]
    assert {"R9 = R10 - 1;", "R7 = I2;", "F2 = FLOAT R1;"} <= set(_code(e))
    for src, want in ((0x7FC00000, 0xFFFFFFFF), (0xFFC00001, 0xFFFFFFFF), (bits(-2.5), bits(2.5)),
                      (0x80000000, 0), (bits(1.0), bits(1.0))):
        p.iconst(4, src)
        p.fabs_(6, 4)
        assert p.r[6] == want, hex(src)


def test_ldm_stm_and_a_biased_index():
    p = Prog("run", mem=Mem(lambda a: a))
    p.iconst(8, 0x100)
    p.seti(1, 8)
    p.fconst(3, 2.0)
    p.stm(1, 3)
    assert p.mem.w[0x100] == bits(2.0) and p.i[1] == 0xFC
    p.ldm(4, 1)
    assert p.r[4] == 0xFC and p.i[1] == 0xF8
    p.iconst(8, 0x1000 + 4 * 8)
    p.seti(1, 8, bias=8)                        # I1 is 8 words into a table at 0x1000
    p.ldi(4, 10, 1)
    assert p.r[4] == 0x1000 + 40
    p.geti(5, 1)
    assert p.r[5] + p.ioff(1, 12) == 0x1000 + 12
    p.seti(1, 8)                                # a plain Ii = Rs: unbiased again
    p.ldi(4, 10, 1)
    assert p.r[4] == 0x1020 + 40
    e = Prog("emit")
    e.stm(1, 3)
    e.ldm(4, 1)
    e.seti(1, 8, bias=8)
    e.ldi(4, 10, 1)
    e.sti(-20, 1, 4)
    assert _code(e) == ["DM(I1, M7) = F3;", "R4 = DM(I1, M7);", "I1 = R8;", "R4 = DM(2, I1);",
                        "DM(-28, I1) = R4;"]

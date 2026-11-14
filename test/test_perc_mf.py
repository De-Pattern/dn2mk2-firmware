"""dnfw.perc.mf: the float multifunction compute field, and Prog.par (several operations in one instruction)."""
import pytest

from dnfw.perc import mf
from dnfw.perc.dsl import Prog, bits


def test_the_firmwares_own_word():
    # stock 1.11 (sw 0x1c7258, a type 3a): F12 = F0 * F7, F8 = F8 + F12 is the compute field 0x58c830
    assert mf.field(12, 0, 7, "+", 8, 8, 12) == 0x58C830


def test_field_round_trip():
    for fm in (0, 5, 15):
        for xm in range(4):
            for ym in range(4, 8):
                for op in ("+", "-", "MAX", "MIN"):
                    for xa in (8, 11):
                        for ya in (12, 15):
                            c = mf.field(fm, xm, ym, op, 3, xa, ya)
                            assert mf.unfield(c) == (fm, xm, ym, op, 3, xa, ya)


def test_text_parses_back_to_the_field():
    assert mf.parse(mf.text(9, 1, 5, "-", 13, 10, 14, "R5 = DM(I1, M6)")) == mf.field(9, 1, 5, "-", 13, 10, 14)
    assert mf.parse("F8 = F2 * F6, F12 = F9 + F13, F13 = F9 - F13;") == mf.field_dual(8, 2, 6, 12, 13, 9, 13)
    assert mf.parse("F8 = F2 * F6;") is None
    assert mf.parse("F12 = MAX(F9, F13);") is None


def test_operand_groups_are_checked():
    for bad in ((12, 4, 7, "+", 8, 8, 12), (12, 0, 3, "+", 8, 8, 12), (12, 0, 7, "+", 8, 4, 12), (12, 0, 7, "+", 8, 8, 9)):
        with pytest.raises(AssertionError):
            mf.field(*bad)


def test_the_alu_reads_the_old_value_of_the_multipliers_result():
    p = Prog("run")
    for r, v in ((0, 2.0), (4, 3.0), (8, 10.0), (12, 100.0)):
        p.fconst(r, v)
    p.par(("*", 12, 0, 4), ("+", 9, 8, 12))      # F12 = F0 * F4 (6), F9 = F8 + F12 (the OLD F12: 110)
    assert p.F(12) == 6.0 and p.F(9) == 110.0


def test_dual_add_subtract():
    p = Prog("run")
    for r, v in ((1, 2.0), (5, 4.0), (9, 7.0), (14, 3.0)):
        p.fconst(r, v)
    p.par(("*", 2, 1, 5), ("+-", 3, 4, 9, 14))
    assert (p.F(2), p.F(3), p.F(4)) == (8.0, 10.0, 4.0)


def test_par_lines_and_their_checks():
    e = Prog("emit")
    e.par(("*", 12, 0, 7), ("+", 8, 8, 12), ("ld", 4, 1))
    e.par(("*", 2, 1, 5), ("+-", 3, 4, 9, 14))
    e.par(("op", 1, 2, "MIN", 3), ("stk", -2, 0, 5))
    assert [ln.strip() for ln in e.lines] == ["F12 = F0 * F7, F8 = F8 + F12, F4 = DM(I1, M6);",
                                              "F2 = F1 * F5, F3 = F9 + F14, F4 = F9 - F14;",
                                              "F1 = MIN(F2, F3), DM(-2, I0) = F5;"]
    assert mf.parse(e.lines[0]) == 0x58C830
    for bad in ((("*", 12, 4, 7), ("+", 8, 8, 12)),        # multiplier operand outside F0-F3
                (("*", 12, 0, 7), ("+", 8, 4, 12)),        # ALU operand outside F8-F11
                (("op", 1, 2, "+", 3), ("ld", 4, 4)),       # a move through I4
                (("op", 1, 2, "+", 3), ("ldk", 4, 40, 0)),  # an offset beyond the 4-byte form
                (("op", 1, 2, "+", 3), ("ld", 1, 0)),       # two results in F1
                (("op", 1, 2, "+", 3), ("ld", 4, 0), ("st", 0, 5))):
        with pytest.raises(AssertionError):
            Prog("emit").par(*bad)


def test_par_reads_every_operand_before_it_writes():
    p = Prog("run")
    p.iconst(8, 0x100)
    p.seti(0, 8)
    p.fconst(1, 2.0)
    p.fconst(2, 5.0)
    p.par(("op", 1, 1, "+", 2), ("st", 0, 1))      # F1 = 7, the store takes the old F1 (2)
    assert p.F(1) == 7.0 and p.mem.w[0x100] == bits(2.0) and p.i[0] == 0x104


def test_par_sets_the_flags_of_its_alu_op():
    p = Prog("run")
    p.fconst(0, 2.0)
    p.fconst(4, 3.0)
    p.fconst(8, 1.0)
    p.fconst(12, 4.0)
    p.par(("*", 1, 0, 4), ("-", 9, 8, 12))         # F9 = -3: LT
    p.fop_if("LT", 10, 0, "+", 4)
    assert p.F(1) == 6.0 and p.F(10) == 5.0
    p.par(("*", 1, 0, 4), ("ld", 5, 0))            # the multiplier alone sets no flags
    with pytest.raises(AssertionError):
        p.fop_if("LT", 10, 0, "+", 4)

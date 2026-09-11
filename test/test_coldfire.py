"""The ColdFire encoder: fixed encodings, branch resolution, and -- where the
real assembler is reachable -- agreement with it on every method that takes no
label."""

import pytest

from dnfw.patch import assemble
from dnfw.patch.coldfire import Asm, jmp_abs, jsr_abs


def test_jmp_and_jsr_absolute_encodings():
    assert jmp_abs(0x40098000) == bytes.fromhex("4ef940098000")
    assert jsr_abs(0x400D24D0) == bytes.fromhex("4eb9400d24d0")


def test_nop_and_rts():
    assert Asm().nop().link() == b"\x4e\x71"
    assert Asm().rts().link() == b"\x4e\x75"


def test_link_resolves_a_forward_branch():
    # bra.w (4 bytes) then a nop at the label. m68k displacement is relative to
    # (branch address + 2): label is at offset 6, base is 2, so disp is 4.
    code = Asm().bra("end").nop().label("end").link()
    assert code[:2] == b"\x60\x00"
    disp = int.from_bytes(code[2:4], "big", signed=True)
    assert disp == 4


def test_link_rejects_an_unresolved_label():
    with pytest.raises(ValueError, match="unresolved label"):
        Asm().beq("nowhere").link()


def test_moveq_masks_to_a_byte():
    assert Asm().moveq(1, 0).link() == bytes.fromhex("7001")


# --- cross-check the encoder against the real assembler, when it is present ---

# (method call, GNU-syntax source) pairs whose bytes must match. Only fixed
# encodings (no labels); the assembler is the arbiter of the ISA.
CASES = [
    (lambda a: a.move_l_imm(0x18B2, 0), "move.l #0x18b2, %d0"),
    (lambda a: a.move_l_abs_d(0x401E29D0, 1), "move.l 0x401e29d0, %d1"),
    (lambda a: a.movea_abs(0x40064786, 2), "movea.l 0x40064786, %a2"),
    (lambda a: a.movea_imm(0x00095048, 0), "movea.l #0x95048, %a0"),
    (lambda a: a.adda_imm(0x0008F3E2, 0), "adda.l #0x8f3e2, %a0"),
    (lambda a: a.cmpi(0x141, 0), "cmpi.l #0x141, %d0"),
    (lambda a: a.addi(0x24, 7), "addi.l #0x24, %d7"),
    (lambda a: a.addq(1, 4), "addq.l #1, %d4"),
    (lambda a: a.jmp(0x40098000), "jmp 0x40098000"),
    (lambda a: a.jsr(0x400CF906), "jsr 0x400cf906"),
    (lambda a: a.tst_abs(0x80000000), "tst.l 0x80000000"),
    (lambda a: a.moveq(5, 3), "moveq #5, %d3"),
    (lambda a: a.rts(), "rts"),
    (lambda a: a.nop(), "nop"),
]


@pytest.mark.skipif(not assemble.available(), reason="no m68k assembler (native or WSL)")
@pytest.mark.parametrize("build, source", CASES)
def test_encoder_agrees_with_the_assembler(build, source):
    assert build(Asm()).link() == assemble.assemble(source)

"""Gate F: no reverse-engineering starts on an unvalidated disassembler.

The parts that need no toolchain — parsing objdump's output, and judging
agreement — are tested here unconditionally. The measurement of Capstone's
ColdFire blindness runs whenever Capstone is installed. The gate itself skips
until an m68k objdump is on PATH, and says so rather than passing quietly.
"""

import pytest

from dnfw.image import capstone_m68k, instruction, objdump

MAIN_OS = 3
# Somewhere dense in code, well past the reset vectors.
SPAN_ADDRESS = 0x40001000
SPAN_LENGTH = 4096

# One real objdump listing shape, including the continuation line binutils
# emits when an encoding is too long for one line.
SAMPLE = """
span.bin:     file format binary

Disassembly of section .data:

40000400 <.data>:
40000400:\t46 fc 27 00 \tmovew #9984,%sr
40000404:\t2f 48 ff fc \tmovel %a0,%fp@(-4)
40000408:\t20 79 46 48 \tmoveal 0x46487fdc,%a0
4000040c:\t7f dc
4000040e:\t4e 75       \trts
"""


def test_parse_folds_continuation_lines():
    parsed = objdump.parse(SAMPLE)
    assert [i.address for i in parsed] == [0x40000400, 0x40000404, 0x40000408, 0x4000040E]
    long_one = parsed[2]
    assert long_one.size == 6, "a wrapped encoding must be one instruction, not two"
    assert long_one.data == bytes.fromhex("207946487fdc")
    assert parsed[-1].text == "rts"


def test_agreement_is_about_boundaries_not_spelling():
    reference = [instruction.Instruction(0x100, b"\x60\x02", "bras 0x104")]
    candidate = [instruction.Instruction(0x100, b"\x60\x02", "bra.b $104")]
    assert instruction.compare(reference, candidate).ok


def test_a_wrong_length_is_a_divergence():
    reference = [
        instruction.Instruction(0x100, b"\x71\x00\x44\x80", "mvsw %d0,%d0"),
        instruction.Instruction(0x104, b"\x4e\x75", "rts"),
    ]
    candidate = [
        instruction.Instruction(0x100, b"\x71\x00", ".byte 0x71, 0x00"),
        instruction.Instruction(0x102, b"\x44\x80", "neg.l d0"),
    ]
    result = instruction.compare(reference, candidate)
    assert not result.ok
    assert result.first_divergence == 0x100
    assert result.matched == 0, "a desynchronised stream matches nothing after the divergence"


def test_capstone_has_no_coldfire_mode():
    """The root cause, asserted rather than described. If Capstone ever gains a
    ColdFire mode this fails, which is the moment to re-run Gate F."""
    capstone = pytest.importorskip("capstone")
    modes = [m for m in dir(capstone) if m.startswith("CS_MODE_M68K")]
    assert modes, "capstone should expose m68k modes"
    assert not any("CF" in m or "COLDFIRE" in m.upper() for m in modes)


def test_capstone_cannot_read_this_image(dn2):
    """Measured, not assumed: Capstone fails on a meaningful number of
    instructions in real Digitone II code, and calls every one of them two
    bytes long -- which is the mechanism by which it desynchronises."""
    pytest.importorskip("capstone")
    section = dn2.container.find(MAIN_OS)
    content = section.unpack()
    start = SPAN_ADDRESS - section.dest
    span = content[start : start + 0x20000]

    decoded = capstone_m68k.disassemble(span, SPAN_ADDRESS)
    skipped = capstone_m68k.undecodable(decoded)

    assert skipped, "expected Capstone to fail on ColdFire instructions"
    assert all(insn.size == 2 for insn in skipped)


@pytest.mark.skipif(objdump.find_tool() is None, reason="no m68k objdump on PATH")
def test_gate_f_objdump_carries_coldfire():
    tool = objdump.require_tool()
    assert objdump.supports_coldfire(tool), (
        f"{tool} lacks {objdump.ARCHITECTURE}; it cannot serve as the reference"
    )


@pytest.mark.skipif(objdump.find_tool() is None, reason="no m68k objdump on PATH")
def test_gate_f_capstone_disagrees_with_objdump(dn2):
    """The gate. Recorded as an expectation rather than a hope: Capstone is
    expected to FAIL against objdump on this CPU. If it ever agrees over a span
    this size, something has changed and the docs need revisiting."""
    section = dn2.container.find(MAIN_OS)
    content = section.unpack()
    start = SPAN_ADDRESS - section.dest
    span = content[start : start + SPAN_LENGTH]

    reference = objdump.disassemble(span, SPAN_ADDRESS)
    candidate = capstone_m68k.disassemble(span, SPAN_ADDRESS)
    result = instruction.compare(reference, candidate)

    assert reference, "objdump produced nothing"
    assert not result.ok, "Capstone unexpectedly agreed with objdump on ColdFire code"

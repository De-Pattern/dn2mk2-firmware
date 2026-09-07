"""Grouping and classifying disassembler disagreements.

The counting rule this file pins down is the one that decides a Gate F verdict,
and getting it wrong made Ghidra look like it misread ten instructions when it
had misread none: when a decoder gets one instruction wrong it usually gets the
next wrong too, and counting those separately both inflates the number and
hides the cause. A cluster is one failure, and what it *starts* on is what it
means.
"""

from dnfw.image import ghidra_listing
from dnfw.image.instruction import Instruction, compare


def insn(address, data, text):
    return Instruction(address, bytes.fromhex(data), text)


def test_consecutive_divergences_are_one_cluster():
    reference = [
        insn(0x100, "0000", ".short 0x0000"),
        insn(0x102, "2f0a", "movel %a2,%sp@-"),
        insn(0x104, "4e75", "rts"),
    ]
    # Ghidra's actual behaviour: it swallows the padding and the instruction
    # after it as one, then gets back in step.
    candidate = [
        insn(0x100, "00002f0a", "ori.b #0xa,D0b"),
        insn(0x104, "4e75", "rts"),
    ]
    result = compare(reference, candidate)
    assert len(result.divergences) == 2
    assert len(result.clusters) == 1, "one stumble, not two failures"
    assert len(result.on_data) == 1, "it began on bytes objdump would not decode"
    assert not result.on_code
    assert result.longest_run == 2


def test_a_cluster_beginning_on_a_real_instruction_counts_as_code():
    reference = [
        insn(0x100, "73f940573e80", "mvzw 0x40573e80,%d1"),
        insn(0x106, "4e75", "rts"),
    ]
    candidate = [
        insn(0x100, "73f9", ".byte 0x73, 0xf9"),
        insn(0x102, "4057", "negx.w d7"),
    ]
    result = compare(reference, candidate)
    assert len(result.on_code) == 1
    assert not result.on_data


def test_separated_divergences_are_separate_clusters():
    reference = [insn(0x100, "0000", ".short 0x0000"), insn(0x102, "4e75", "rts"),
                 insn(0x104, "0000", ".short 0x0000"), insn(0x106, "4e75", "rts")]
    candidate = [insn(0x102, "4e75", "rts"), insn(0x106, "4e75", "rts")]
    result = compare(reference, candidate)
    assert len(result.clusters) == 2
    assert result.longest_run == 1


def test_full_agreement_has_no_clusters():
    both = [insn(0x100, "4e75", "rts")]
    result = compare(both, list(both))
    assert result.ok
    assert not result.clusters
    assert result.longest_run == 0


def test_ghidra_listing_round_trip():
    text = (
        "40001000\t2f0a\tmove.l A2,-(SP)\n"
        "40001002\t0000\t; undecodable\n"
        "not a listing line\n"
    )
    parsed = ghidra_listing.parse(text)
    assert [i.address for i in parsed] == [0x40001000, 0x40001002]
    assert parsed[0].data == b"\x2f\x0a"
    assert len(ghidra_listing.undecodable(parsed)) == 1

"""The ADI boot-stream parser: what identifies a stream, and what does not.

The point of these tests is the discrimination, not the parsing. A signature
byte occurs by chance more than a thousand times in the real section, so every
test here asks whether the parser can tell a stream from bytes that merely look
like one.
"""

import struct

import pytest

from dnfw.image import bootstream


def header(code_flags: int, target: int, count: int, argument: int = 0) -> bytes:
    """One block header. `code_flags` is the flag byte, placed at bits 8..15."""
    code = (bootstream.SIGNATURE << 24) | (code_flags << 8) | 0x01
    return struct.pack("<IIII", code, target, count, argument)


def stream(*blocks: bytes) -> bytes:
    return b"".join(blocks)


class TestBlock:
    def test_flags_come_from_bits_8_to_15(self):
        block = bootstream.header_at(header(bootstream.FLAG_FINAL, 0x100, 0), 0)
        assert block.flags == bootstream.FLAG_FINAL
        assert "final" in block.flag_names

    def test_a_fill_block_carries_no_payload_however_large_its_count(self):
        """Section 7 ends with a 4.5 MB fill. A fill advances the load address
        without advancing the file, and a walk that misses this desynchronises."""
        block = bootstream.header_at(header(bootstream.FLAG_FILL, 0x80000018, 0x45A6B0), 0)
        assert block.count == 0x45A6B0
        assert not block.has_payload
        assert block.end == bootstream.HEADER

    def test_an_ordinary_block_is_followed_by_its_payload(self):
        block = bootstream.header_at(header(0, 0x28240000, 0x40), 0)
        assert block.has_payload
        assert block.end == bootstream.HEADER + 0x40


class TestWalk:
    def test_a_chain_of_contiguous_blocks_walks_to_the_end(self):
        data = stream(
            header(0, 0x1000, 4) + b"\x01\x02\x03\x04",
            header(0, 0x1004, 4) + b"\x05\x06\x07\x08",
            header(bootstream.FLAG_FINAL, 0xABCD, 0),
        )
        result = bootstream.walk(data)
        assert len(result.blocks) == 3
        assert result.stopped_at == len(data)
        assert result.contiguous == result.transitions == 1
        assert result.complete
        assert result.convincing
        assert result.entry_point == 0xABCD

    def test_a_fill_between_two_blocks_does_not_break_the_chain(self):
        """The case that truncated the real walk: skip a fill's bytes in the
        file, but still advance the load address by its count."""
        data = stream(
            header(0, 0x1000, 4) + b"\x01\x02\x03\x04",
            header(bootstream.FLAG_FILL, 0x1004, 0x100),
            header(0, 0x1104, 4) + b"\x05\x06\x07\x08",
            header(bootstream.FLAG_FINAL, 0x20, 0),
        )
        result = bootstream.walk(data)
        assert len(result.blocks) == 4
        assert result.stopped_at == len(data)
        assert result.contiguous == result.transitions == 2

    def test_random_bytes_with_a_signature_do_not_walk(self):
        data = bytes([0x00, 0x00, 0x00, bootstream.SIGNATURE]) + b"\xff" * 64
        result = bootstream.walk(data)
        assert not result.convincing

    def test_a_payload_running_past_the_end_stops_the_walk(self):
        """`blocks` holds only blocks the walk actually stepped over, so a header
        whose payload cannot exist is reported in `reason` and not counted."""
        data = header(0, 0x1000, 0x10000) + b"\x00" * 8
        result = bootstream.walk(data)
        assert result.blocks == ()
        assert "past the end" in result.reason
        assert not result.convincing

    def test_a_huge_fill_past_the_end_is_fine_because_it_carries_nothing(self):
        """The guard must test the payload, not the count. A blunter one
        rejected the real section's final fill and lost 7 of its 95 blocks."""
        data = stream(
            header(0, 0x1000, 4) + b"\x01\x02\x03\x04",
            header(bootstream.FLAG_FILL, 0x1004, 0xFFFFFF),
            header(bootstream.FLAG_FINAL, 0x20, 0),
        )
        result = bootstream.walk(data)
        assert len(result.blocks) == 3
        assert result.complete


class TestConvincing:
    def test_a_jump_between_memories_does_not_make_a_stream_unconvincing(self):
        """A real image loads several memories, so it jumps by design -- section
        7 does it 16 times. Requiring perfect contiguity called the true
        95-block walk noise while blessing fragments of it."""
        data = stream(
            header(0, 0x20000000, 4) + b"\x01\x02\x03\x04",
            header(0, 0x28240000, 4) + b"\x05\x06\x07\x08",   # different memory
            header(0, 0x28240004, 4) + b"\x09\x0a\x0b\x0c",
            header(bootstream.FLAG_FINAL, 0x40, 0),
        )
        result = bootstream.walk(data)
        assert result.contiguous < result.transitions   # the jump is real
        assert result.complete
        assert result.convincing

    def test_an_incomplete_walk_needs_every_target_to_chain(self):
        data = stream(
            header(0, 0x1000, 4) + b"\x01\x02\x03\x04",
            header(0, 0x9999, 4) + b"\x05\x06\x07\x08",
            header(0, 0x1008, 4) + b"\x09\x0a\x0b\x0c",
        ) + b"\xff" * 4
        result = bootstream.walk(data)
        assert not result.complete
        assert not result.convincing

    def test_two_blocks_are_never_enough(self):
        data = stream(
            header(0, 0x1000, 4) + b"\x01\x02\x03\x04",
            header(bootstream.FLAG_FINAL, 0x20, 0),
        )
        assert not bootstream.walk(data).convincing


class TestRegions:
    def test_adjacent_spans_merge_and_a_gap_stays_separate(self):
        data = stream(
            header(0, 0x1000, 4) + b"\x01\x02\x03\x04",
            header(0, 0x1004, 4) + b"\x05\x06\x07\x08",
            header(0, 0x9000, 4) + b"\x09\x0a\x0b\x0c",
            header(bootstream.FLAG_FINAL, 0x20, 0),
        )
        assert bootstream.walk(data).regions() == [(0x1000, 0x1008), (0x9000, 0x9004)]

    def test_a_stream_with_no_final_block_has_no_entry_point(self):
        data = stream(header(0, 0x1000, 4) + b"\x01\x02\x03\x04")
        assert bootstream.walk(data).entry_point is None


class TestFindStreams:
    def test_it_finds_a_stream_that_does_not_start_at_zero(self):
        data = b"\x00" * 32 + stream(
            header(0, 0x1000, 4) + b"\x01\x02\x03\x04",
            header(0, 0x1004, 4) + b"\x05\x06\x07\x08",
            header(0, 0x1008, 4) + b"\x09\x0a\x0b\x0c",
        )
        found = bootstream.find_streams(data)
        assert found and found[0].blocks[0].offset == 32

    def test_empty_input_is_not_a_stream(self):
        assert bootstream.find_streams(b"") == []
        assert bootstream.walk(b"").blocks == ()


@pytest.mark.parametrize("offset", [-1, 0, 4])
def test_header_at_out_of_range_is_none(offset):
    assert bootstream.header_at(b"\x00" * 8, offset) is None

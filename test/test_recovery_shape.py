"""The two ways our images differed from Elektron's that no checksum catches.

Gates D and E booted through the normal update path and stalled in the Early
Start-up Menu's recovery flash. Two differences from stock were found, and
both are pinned here: our packer reached back further than Elektron's ever do,
and our compressed sections were not padded to four bytes. Which of the two
the bootloader objects to is not yet known -- `docs/flashing.md` -- so neither
is allowed back in.
"""

import random

import pytest

from dnfw.codec import limits
from dnfw.codec.aplib import depack
from dnfw.codec.aplibpack import _Writer, pack
from dnfw.codec.profile import profile
from dnfw.container.section import HEADER, STORED_ALIGN, Section, compress
from dnfw.firmware import verify


def _far_stream(offset: int) -> bytes:
    """A tiny stream whose last match reaches `offset` bytes back.

    One literal, then runs copying it until the output is long enough, then
    the far match. Megabytes of output from a few kilobytes of stream, so a
    window violation can be tested without packing megabytes.
    """
    w = _Writer()
    w.literal(0x55)
    last = 1
    produced = 1
    while produced < offset:
        step = min(limits.MAX_MATCH, offset - produced + 1)
        step = max(step, 2)
        last = w.match(1, step, last)
        produced += step
    w.match(offset, 4, last)
    w.end()
    return bytes(w.out)


def _section_from_stream(stream: bytes, pad: bool = True) -> Section:
    header = len(stream).to_bytes(4, "big") + (sum(stream) & 0xFFFFFFFF).to_bytes(4, "big")
    padding = bytes(-(HEADER + len(stream)) % STORED_ALIGN) if pad else b""
    return Section(id=3, dest=0x40000400, stored=header + stream + padding)


# --- the packer ---------------------------------------------------------------


def test_packer_never_reaches_past_its_limit():
    """A block repeated beyond the limit must be re-emitted, not matched."""
    rng = random.Random(7)
    block = bytes(rng.randrange(256) for _ in range(512))
    filler = bytes(rng.randrange(256) for _ in range(6000))
    data = block + filler + block

    capped = pack(data, max_offset=4096)
    assert depack(capped) == data
    assert profile(capped).max_offset <= 4096

    uncapped = pack(data, max_offset=len(data))
    assert depack(uncapped) == data
    assert profile(uncapped).max_offset > 4096, "the test data should tempt a far match"


def test_the_default_limit_sits_inside_elektrons_window():
    assert limits.PACK_MAX_OFFSET < limits.WINDOW
    # Under the furthest match measured in Elektron's own 1.10E and 1.11 streams,
    # so everything we emit is a distance the device has already been shown.
    assert limits.PACK_MAX_OFFSET < 1_048_508


# --- the profile --------------------------------------------------------------


def test_profile_finds_a_match_past_the_window():
    far = limits.WINDOW + 10
    p = profile(_far_stream(far))
    assert p.max_offset == far
    assert p.beyond == 1
    assert p.first_beyond is not None and p.first_beyond >= far
    assert not p.within_limits


def test_profile_agrees_with_depack_about_length():
    data = b"abcabcabcabc" * 50 + bytes(range(256))
    stream = pack(data)
    assert profile(stream).output == len(depack(stream)) == len(data)


# --- section padding ----------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 100, 101, 102, 103])
def test_compressed_sections_are_padded_to_four(size):
    content = bytes((i * 37) & 0xFF for i in range(size))
    section = compress(3, 0x40000400, content)
    assert len(section.stored) % STORED_ALIGN == 0
    assert section.unpack() == content
    assert section.sum_ok, "the header's sum covers the stream, not the padding"
    assert len(section.stored) - HEADER - section.declared_length < STORED_ALIGN


# --- the verifier -------------------------------------------------------------


def test_verifier_fails_an_unpadded_section():
    stream = pack(b"xy" * 3)  # any stream whose length leaves a remainder
    section = _section_from_stream(stream, pad=False)
    if len(section.stored) % STORED_ALIGN == 0:
        section = _section_from_stream(stream + b"\x00", pad=False)
    assert not verify._padded(section).ok
    assert verify._padded(_section_from_stream(stream)).ok


def test_verifier_fails_a_stream_past_the_window():
    check = verify._limits(_section_from_stream(_far_stream(limits.WINDOW + 10)))
    assert not check.ok
    assert "past the window" in check.detail


# --- Elektron's own images ----------------------------------------------------


def test_every_stock_section_is_padded_and_within_limits(dn2):
    for section in dn2.container.sections:
        assert verify._padded(section).ok, section.id
        assert verify._limits(section).ok, section.id


def test_a_rebuild_of_stock_content_matches_elektrons_shape(dn2):
    """Recompress the smallest compressed section and check the result has
    both properties -- the same path `dnfw build` takes."""
    original = dn2.container.find(2)
    rebuilt = compress(original.id, original.dest, original.unpack())
    assert verify._padded(rebuilt).ok
    assert verify._limits(rebuilt).ok
    assert rebuilt.unpack() == original.unpack()

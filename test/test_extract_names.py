"""`dnfw extract` must produce a legal filename for every section.

`ele3.name` returns `?` for a section id we have not identified, which is the
right thing to show and an illegal filename on Windows. DN2 1.11 ships an
unnamed section 8, and extracting it failed outright until this was fixed --
so this is the normal case for new firmware, not an edge one.
"""

import pytest

from dnfw.cli.extract import _filename
from dnfw.container import ele3

ILLEGAL = set('<>:"/\\|?*')


@pytest.mark.parametrize(
    "label, expected",
    [
        ("?", "unnamed"),
        ("MAIN OS", "MAIN_OS"),
        ("blob", "blob"),
        ("meta", "meta"),
        ("", "unnamed"),
        ("a/b", "a_b"),
        ("*", "unnamed"),
    ],
)
def test_filename_is_legal_and_stable(label, expected):
    assert _filename(label) == expected


def test_every_known_section_name_survives():
    """A rename must not silently change the files a rebuild diffs against."""
    for section_id in list(ele3.NAMES) + [8, 99]:
        name = _filename(ele3.name(section_id))
        assert name, f"section {section_id} produced an empty filename"
        assert not (set(name) & ILLEGAL), f"section {section_id} -> {name!r}"
        assert name == name.strip(), f"section {section_id} -> {name!r}"


# --- raw sections and the 8-byte header ----------------------------------
#
# Added 2026-09-13 after `m-dwyer/digikit` extracted section 4 as 32,768 bytes
# where `dnfw extract` wrote 32,776, with `ours[8:] == theirs` exactly. digikit's
# layout is confirmed by execution -- it runs the updater's own aPLib depacker at
# 0x80000432 from that base -- so those eight bytes are a header we were writing
# as payload. See docs/emulator.md and Section.raw_payload.

from dnfw.container.section import HEADER, Section


def test_a_raw_section_with_a_zero_declared_sum_has_its_header_stripped():
    # Section 4's real header on DN2 1.10E: [0x80000492][0]. The length field is
    # not a length; the zero sum is what marks it as a header over raw bytes.
    stored = bytes.fromhex("80000492") + bytes(4) + b"PAYLOAD!"
    section = Section(id=4, dest=0x80000400, stored=stored)
    assert section.declared_sum == 0
    assert section.raw_payload == b"PAYLOAD!"


def test_a_raw_section_that_is_only_payload_keeps_every_byte():
    # Section 5 (meta) is 15 ASCII bytes of build stamp with no header at all;
    # its bytes 4..8 are ASCII, so the declared sum is never zero.
    stored = b"DN2_1.10E_BUILD"
    section = Section(id=5, dest=0, stored=stored)
    assert section.declared_sum != 0
    assert section.raw_payload == stored


def test_the_rule_is_the_declared_sum_not_the_section_id():
    # Same id, different headers -> different answers. Deciding from the id
    # would be a guess; the sum is a check.
    with_header = Section(id=4, dest=0, stored=bytes(8) + b"abcd")
    without = Section(id=4, dest=0, stored=b"\x00\x00\x00\x01\x00\x00\x00\x09abcd")
    assert with_header.raw_payload == b"abcd"
    assert without.raw_payload == without.stored


def test_a_section_too_short_to_hold_a_header_is_returned_whole():
    section = Section(id=5, dest=0, stored=bytes(HEADER))
    assert section.raw_payload == section.stored

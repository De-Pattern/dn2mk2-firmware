"""The parameter table: that it is found, and that it says what it said.

These pin the measurements `docs/lfo-parameters.md` rests on. The numbers are
written down rather than derived, so a change in the finder that quietly moves
the table's edges or renumbers a group fails here instead of in a document
nobody re-checks.
"""

import pytest

from dnfw.image.coldfire import LoadedImage
from dnfw.params import record as rec
from dnfw.params import table as tbl

MAIN_OS = 3

DN2_TABLE = 0x401E29D4
DN2_RECORDS = 320
DN1_SET_IN_DN2 = 0x401BAE00

LFO_BLOCKS = {
    "LFO1": (0x401E3B2C, 26, range(1, 9)),
    "LFO2": (0x401E3D84, 27, range(9, 17)),
    "LFO3": (0x401E3FDC, 28, range(17, 25)),
}


@pytest.fixture(scope="module")
def image(dn2) -> LoadedImage:
    section = dn2.container.find(MAIN_OS)
    content = section.unpack()
    assert content is not None, "MAIN OS should be aPLib-compressed"
    return LoadedImage(dest=section.dest, content=content)


@pytest.fixture(scope="module")
def table(image) -> tbl.Table:
    return tbl.containing(image, LFO_BLOCKS["LFO1"][0], rec.DN2_WORDS)


def test_the_table_is_found_where_it_was_measured(table):
    assert table.address == DN2_TABLE
    assert len(table.records) == DN2_RECORDS
    assert table.stride == 60


def test_finding_by_shape_returns_both_parameter_tables(image):
    found = tbl.find(image, rec.DN2_WORDS)
    addresses = [t.address for t in found]
    assert addresses[0] == DN2_TABLE, "the DN2 table should be the largest"
    assert DN1_SET_IN_DN2 in addresses, "the DN1 parameter set is also in this image"


def test_each_lfo_block_is_ten_records_carrying_eight_ids(table):
    for page, (address, group, ids) in LFO_BLOCKS.items():
        block = [r for r in table.records if r.page == page]
        assert len(block) == 10, f"{page} should be ten records"
        assert block[0].address == address
        assert {r.group for r in block} == {group}
        assert {r.parameter_id for r in block} == set(ids)


def test_slew_shares_start_phase_id_and_has_no_controller(table):
    """The measurement the record alignment was settled on, and confirmed on
    the instrument: for random waveforms the phase knob controls slew."""
    for page, (_, _, _) in LFO_BLOCKS.items():
        block = [r for r in table.records if r.page == page]
        slew = next(r for r in block if r.short_name == "SLEW")
        phase = next(r for r in block if r.short_name == "SPH")
        assert slew.parameter_id == phase.parameter_id
        assert slew.controller is None
        assert phase.controller is not None


def test_the_parameter_id_is_not_unique(table):
    """The finding that overturned the first reading of this table: ids are
    reused across groups, so Chorus's 25 does not follow LFO3's 24."""
    claims: dict[int, set] = {}
    for r in table.records:
        if r.parameter_id is not None:
            claims.setdefault(r.parameter_id, set()).add(r.group)
    shared = [pid for pid, groups in claims.items() if len(groups) > 1]
    assert len(shared) == 68
    assert len(claims) == 100
    assert 25 in shared, "id 25 is claimed by Chorus, Src and every SYN group"


def test_the_head_records_carry_no_group_or_id(table):
    """Something reaches these by array index, not by (group, id)."""
    head = table.records[:18]
    assert not any(r.addressable for r in head)
    assert head[0].long_name == "Error"
    assert all(r.addressable for r in table.records[18:])


def test_group_29_is_already_taken(table):
    """An earlier draft proposed group 29 for a fourth LFO. It is Retrig and
    Euclidean, and 4, 12 and 31 are the free numbers."""
    used = {r.group for r in table.records if r.group is not None}
    assert 29 in used
    # Its named pages are Retrig and Euclidean; it also covers unnamed records
    # near the head of the table, which carry an empty page label.
    assert {r.page for r in table.records if r.group == 29} == {"Retrig", "Euclidean", ""}
    assert {4, 12, 31}.isdisjoint(used)


def test_string_at_accepts_the_empty_page_label(image):
    """Rejecting empty strings stopped an earlier walk 74 records short."""
    empty = [r for r in tbl.containing(image, LFO_BLOCKS["LFO1"][0], rec.DN2_WORDS).records
             if r.page == ""]
    assert empty, "several records carry an empty page label"

"""Moving the parameter table: the site lists, and what the copy must preserve.

The relocation is built to degrade gracefully -- a base it failed to find keeps
reading a table that is still there and still correct -- which is exactly why
its completeness has to be asserted somewhere that fails loudly. The emulator
answers the behavioural half (`scripts/emu_table_watch.py` watches the old
range for reads); this answers the arithmetic half, against the real image.
"""

import pathlib
import struct

import pytest

from dnfw.cli.files import read_image
from dnfw.firmware.load import load
from dnfw.patch import lfo4records, paramtable

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
MAIN_OS, BASE = 3, 0x40000400


@pytest.fixture(scope="module")
def stock():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    return load(read_image(STOCK_111)).container.find(MAIN_OS).unpack()


def test_the_site_counts_are_what_was_measured(stock):
    assert len(paramtable.base_sites(stock, BASE)) == sum(paramtable.EXPECTED_BASES.values())
    assert len(paramtable.runtime_sites(stock, BASE)) == paramtable.EXPECTED_RUNTIME
    assert len(paramtable.bound_sites(stock, BASE)) == paramtable.EXPECTED_BOUNDS


def test_every_site_holds_what_it_is_asserted_to_hold(stock):
    for site in (paramtable.base_sites(stock, BASE) + paramtable.runtime_sites(stock, BASE)
                 + paramtable.bound_sites(stock, BASE)):
        assert struct.unpack_from(">I", stock, site.va - BASE)[0] == site.was


def test_relocating_changes_only_those_sites(stock):
    buf = bytearray(stock)
    sites = paramtable.relocate(buf, BASE, table_va=0x46900000,
                                runtime_va=0x46A00000, added=10)
    changed = {i for i in range(len(stock)) if stock[i] != buf[i]}
    covered = {site.va - BASE + k for site in sites for k in range(site.width)}
    assert changed <= covered


def test_the_bound_grows_by_exactly_the_records_added(stock):
    buf = bytearray(stock)
    for site in paramtable.relocate(buf, BASE, table_va=0x46900000,
                                    runtime_va=0x46A00000, added=10):
        if site.what.startswith("bound"):
            assert site.now - site.was == 10


def test_the_three_excluded_sites_are_not_this_bound(stock):
    """Each steps `d2` by 20 up to 320 -- sixteen iterations of something else.

    The counter is stepped a few instructions before the compare rather than
    immediately before it, so the window is what identifies them.
    """
    for va in paramtable.NOT_THE_BOUND:
        at = va - BASE
        assert stock[at:at + 2] == b"\x0c\x82"                        # cmpil #,%d2
        assert b"\x06\x82\x00\x00\x00\x14" in stock[at - 20:at]       # addil #20,%d2


def test_lfo4s_records_copy_lfo3s_except_where_they_must_not(stock):
    records = lfo4records.build(stock, BASE, page_name_va=0x46904D58)
    assert len(records) == lfo4records.RECORD * lfo4records.GROUP_SIZE
    written = {lfo4records.SLOT, lfo4records.NRPN, lfo4records.UNIQUE,
               lfo4records.FLAGS, lfo4records.PAGE_NAME}
    for k in range(lfo4records.GROUP_SIZE):
        at = paramtable.TABLE - BASE + paramtable.RECORD * (lfo4records.LFO3_FIRST + k)
        was = stock[at:at + paramtable.RECORD]
        now = records[paramtable.RECORD * k:paramtable.RECORD * (k + 1)]
        for off in range(0, paramtable.RECORD, 4):
            if off not in written:
                assert was[off:off + 4] == now[off:off + 4], f"record {k}, +{off}"


def test_the_ten_value_slots_are_101_to_108_with_the_two_alternates(stock):
    records = lfo4records.build(stock, BASE, page_name_va=0)
    slots = [struct.unpack_from(">I", records, paramtable.RECORD * k + lfo4records.SLOT)[0]
             for k in range(lfo4records.GROUP_SIZE)]
    assert slots == [101, 102, 103, 104, 105, 106, 106, 107, 108, 102]


def test_the_unidentified_id_stays_unique(stock):
    """Field +40 is a key: 320 distinct values, no duplicates, no -1."""
    used = {struct.unpack_from(">I", stock, paramtable.TABLE - BASE
                               + paramtable.RECORD * i + lfo4records.UNIQUE)[0]
            for i in range(paramtable.COUNT)}
    assert len(used) == paramtable.COUNT
    fresh = lfo4records.free_unique_ids(stock, BASE)
    assert len(set(fresh)) == lfo4records.GROUP_SIZE
    assert not (used & set(fresh))
    assert min(used) < min(fresh) and max(fresh) < max(used)


def test_only_lfo4s_dest_record_claims_a_capability_bit(stock):
    records = lfo4records.build(stock, BASE, page_name_va=0)
    flags = [struct.unpack_from(">I", records, paramtable.RECORD * k + lfo4records.FLAGS)[0]
             for k in range(lfo4records.GROUP_SIZE)]
    assert flags[lfo4records.DEST_POSITION] == lfo4records.DEST_FLAGS
    assert all(f == 0 for k, f in enumerate(flags) if k != lfo4records.DEST_POSITION)


def test_the_slot_filing_loop_keeps_its_bound(stock):
    """`param_set_tables_build` files by value slot into 101-entry tables.

    Raising its bound registers LFO4's slots 101-108 thirty-two bytes past the
    end of three of them, and the byte after the first is the filter table the
    same routine zeroes two calls earlier. It boots and it draws.
    """
    va = next(iter(paramtable.NOT_THIS_TIME))
    at = va - BASE
    assert stock[at:at + 6] == b"\x0c\x82\x00\x00\x01\x41"          # cmpil #321,%d2
    assert stock[at - 4:at] == b"\x45\xea\x00\x3c"                  # lea %a2@(60),%a2
    assert all(site.va - 2 != va for site in paramtable.bound_sites(stock, BASE))


def test_the_three_slot_tables_are_101_entries_and_adjacent(stock):
    """404 bytes each, and the filter table begins at the end of the first."""
    zeroed = {0x42C64B3C: 0x194, 0x42C647AC: 0x194, 0x42C649A8: 0x194,
              0x42C64CD0: 0x48}
    for base_va, size in zeroed.items():
        pea = b"\x48\x78" + struct.pack(">H", size) + b"\x48\x79" + struct.pack(">I", base_va)
        assert pea in stock, f"{base_va:#010x} is not zeroed with {size} bytes"
    assert 0x42C64B3C + 0x194 == 0x42C64CD0
    assert 0x42C649A8 + 0x194 == 0x42C64B3C

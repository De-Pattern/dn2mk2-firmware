"""The Waverider mod: it applies to stock 1.11, refuses anything else, reproduces
the compose it was generated from, and its edits say what they say.

`scripts/gen_waverider_code.py` writes the SPEC from `dnfw.waverider.coldfire`
and refuses unless replaying it gives the compose output byte for byte; what is
asserted here is that the shipped JSON still does, and what the data means.
`scripts/emu_waverider_menu.py` is the behavioural evidence (MACHINE SEL, the
SYN page, the frame), `scripts/sharc_waverider_m5.py` the DSP's.
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import waverider
from dnfw.waverider import coldfire as CF

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = waverider.BASE


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(3).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return waverider.apply(dn2_111)


def at(content: bytes, va: int, n: int) -> bytes:
    return bytes(content[va - BASE:va - BASE + n])


def long_at(content: bytes, va: int) -> int:
    return struct.unpack(">I", at(content, va, 4))[0]


def test_applies_to_both_sections(applied, dn2_111):
    assert set(applied.payloads) == {3, 7}
    assert len(applied.payloads[3]) == len(dn2_111.container.find(3).unpack())
    assert len(applied.payloads[7]) > len(dn2_111.container.find(7).unpack())


def test_the_list_offers_type_5_before_midi(applied):
    main = applied.payloads[3]
    begin = long_at(main, CF.LIST_BEGIN + 2)
    end = long_at(main, CF.LIST_END + 2)
    types = [long_at(main, a) for a in range(begin, end, 4)]
    assert types == [0, 2, 1, 3, 5, 4]
    assert at(main, CF.LIST_ALLOC, 4) == bytes.fromhex("48780018")
    assert at(main, CF.LIST_CAP, 4) == bytes.fromhex("41e80018")


def test_row_5_of_the_name_table_names_waverider(applied):
    main = applied.payloads[3]
    table = long_at(main, 0x400DC344)
    long_ptr, short_ptr = long_at(main, table + 60), long_at(main, table + 64)
    assert at(main, long_ptr, 10) == b"Waverider\0"
    assert at(main, short_ptr, 4) == b"WVR\0"
    for bound in (0x400DC332, 0x400DC358, 0x400DC37E):
        assert at(main, bound, 2) == bytes.fromhex("7205")


def test_the_sixth_attribute_row_is_wavetones(applied, stock):
    main = applied.payloads[3]
    rows = long_at(main, 0x400DC168)
    assert at(main, rows, 20) == at(stock, CF.ATTR_STOCK_VA, 20)
    assert at(main, rows + 20, 4) == at(stock, CF.ATTR_STOCK_VA + 4, 4)
    assert at(main, 0x400DC19C, 2) == bytes.fromhex("7405")


def test_the_stored_sound_load_keeps_type_5(applied):
    assert at(applied.payloads[3], CF.LOAD_BOUND, 2) == bytes.fromhex("7407")


def test_every_edit_replaces_stock_bytes(stock):
    for e in waverider.SPEC["edits"]:
        assert at(stock, e["va"], len(e["stock"]) // 2).hex() == e["stock"], e["what"]
    for g in waverider.SPEC["guards"]:
        assert at(stock, g["va"], len(g["bytes"]) // 2).hex() == g["bytes"], g["what"]


def test_nothing_is_written_outside_its_extents(applied, stock, dn2_111):
    main = applied.payloads[3]
    spans = [(e.start, e.end) for e in waverider.extents(dn2_111) if e.section == 3]
    for i in range(len(stock)):
        if stock[i] != main[i]:
            assert any(s <= i < t for s, t in spans), f"{BASE + i:#010x} is outside every extent"


def test_the_caves_were_free_in_stock(stock):
    for cave, cap in (CF.DATA_CAVE, CF.CODE_CAVE, CF.NAME_CAVE):
        assert not any(at(stock, cave - 4, cap + 8))


def test_refuses_an_image_already_modified(dn2_111):
    main = bytearray(dn2_111.container.find(3).unpack())
    main[CF.LOAD_BOUND - BASE + 1] = 9
    with pytest.raises(ModError):
        waverider._main_os(bytes(main))


def test_extents_do_not_overlap_each_other(dn2_111):
    found = waverider.extents(dn2_111)
    for i, a in enumerate(found):
        for b in found[i + 1:]:
            assert not a.overlaps(b), (a, b)
    assert check_compatible([("waverider", found)]) == []


def test_the_json_reproduces_the_compose(stock):
    from dnfw.patch.assemble import assemble, available
    if not available():
        pytest.skip("no m68k assembler")
    built = CF.compose(stock, assemble)
    content = bytearray(stock)
    for e in waverider.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    assert bytes(content) == built["content"]

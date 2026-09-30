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
from dnfw.mods import platform, waverider
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
    # MAIN OS: the stock image, plus the platform area carrying the M7 pages chunk
    main, chunks = platform.split(applied.payloads[3])
    assert len(main) == len(dn2_111.container.find(3).unpack())
    assert [kind for kind, _ in chunks] == [platform.area.CODE]
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


def test_the_group_function_gives_the_sample_machines_their_own_section(applied):
    # run the rewritten 0x40059274 on every type: synths 1, MIDI 2, 5 and 6 3, else 0
    main = applied.payloads[3]
    code = at(main, CF.GROUP_FN, len(CF.GROUP_STOCK))
    got = {t: _run_group(code, t) for t in (-1, 0, 1, 2, 3, 4, 5, 6, 7, 100)}
    assert got == {-1: 0, 0: 1, 1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 6: 3, 7: 0, 100: 0}


def _run_group(code: bytes, t: int) -> int:
    """A reading of the group function's own bytes, instruction by instruction -- the
    handful of opcodes it is made of, and nothing else (anything else fails)."""
    d0, d1, pc = 0, 0, 0
    n = z = c = False
    while True:
        op = struct.unpack_from(">H", code, pc)[0]
        if op == 0x222F:                                  # move.l %sp@(d16),%d1
            d1 = t & 0xFFFFFFFF
            n, z = t < 0, t == 0
            pc += 4
        elif op & 0xFF00 == 0x7000:                       # moveq #k,%d0: N, Z set; C cleared
            d0 = op & 0xFF
            n, z, c = bool(d0 & 0x80), d0 == 0, False
            pc += 2
        elif op == 0x4A81:                                # tst.l %d1: N, Z set; C cleared
            n, z, c = bool(d1 & 0x80000000), d1 == 0, False
            pc += 2
        elif op & 0xF1FF == 0x5181:                       # subq.l #k,%d1
            k = (op >> 9) & 7 or 8
            c, d1 = d1 < k, (d1 - k) & 0xFFFFFFFF
            z = d1 == 0
            pc += 2
        elif op == 0x4E75:                                # rts
            return d0 & 0xFF
        elif op >> 8 in (0x6D, 0x67, 0x65, 0x63):        # blt, beq, bcs, bls (.s)
            take = {0x6D: n, 0x67: z, 0x65: c, 0x63: c or z}[op >> 8]
            disp = (op & 0xFF) - 256 if op & 0x80 else op & 0xFF
            pc += 2 + (disp if take else 0)
        else:
            raise AssertionError(f"unexpected opcode {op:04x} at +{pc}")


def test_machine_sel_asks_for_the_real_type(applied, stock):
    # MACHINE SEL marks and places its cursor on 0x4003134e(model, track), which ends in
    # a tail jump to getMachineType(track). That jump must reach raw_track (the real type),
    # not the canonicalising getMachineType: otherwise YES on WAVERIDER marks WAVETONE.
    main = applied.payloads[3]
    raw = waverider.SPEC["layout"]["raw_track"]
    assert at(stock, CF.MODEL_TRACK_TYPE_JMP, 6) == bytes.fromhex("4ef94004b7f2")
    assert at(main, CF.MODEL_TRACK_TYPE_JMP, 6) == bytes.fromhex("4ef9") + struct.pack(">I", raw)
    for site in (0x4005A5C6, 0x4005A632, 0x4005A9C8, 0x4005B6C2):     # MACHINE SEL's callers
        assert at(main, site, 6) == bytes.fromhex("4eb94003134e")
    # ... and raw_track is still the stock getMachineType's body, reading sound+0xDE
    assert at(main, raw, 4) == bytes.fromhex("2f0a246f")


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

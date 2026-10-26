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
    # MAIN OS: the stock image, plus the platform area carrying the M7 pages chunk and,
    # since W5, the wave display's chunk, and since PING P2, PING's FLTR-list chunk
    main, chunks = platform.split(applied.payloads[3])
    assert len(main) == len(dn2_111.container.find(3).unpack())
    # pages, the page renderer (its own chunk since v0.13), machines, PING (the wave
    # display chunk went with Waverider, v0.11); v0.20: and, when the owner's MD OS is
    # there, the Machinedrum's screen graphics (copied to RAM, never run: no init entry);
    # v0.26: and the tables the ColdFire sends the DSP at power-on (dnfw.mods.waverider._tables)
    from dnfw.md import rom as md_rom
    want = 6 if md_rom.available() else 4
    assert [kind for kind, _ in chunks] == [platform.area.CODE] * want
    assert len(applied.payloads[7]) > len(dn2_111.container.find(7).unpack())


def test_the_sample_link_hooks_call_into_the_renderer_chunk(applied, stock):
    # v0.14: the SysEx router jsr's into the C chunk, and replays exactly the stock lea it
    # displaced; v0.20: the frame builder is stock again (its words 2650.. are the DSP's
    # per-track routing: writing them made the stock voices buzz)
    main = applied.payloads[3]
    c = waverider.SPEC["c_chunk"]
    lo, hi = c["load"], c["load"] + len(bytes.fromhex(c["code"]))
    assert at(main, CF.LINK_FEED_SITE, 6) == at(stock, CF.LINK_FEED_SITE, 6) == CF.LINK_FEED_STOCK
    for site, stock_bytes, sym in ((CF.LINK_RX_SITE, CF.LINK_RX_STOCK, "smp_rx_hook"),):
        assert at(stock, site, 6) == stock_bytes
        assert at(main, site, 2) == bytes.fromhex("4eb9")
        target = long_at(main, site + 2)
        assert lo <= target < hi, hex(target)
        # the hook replays the displaced lea and returns
        code = _chunked(target, 64)
        assert stock_bytes in code and bytes.fromhex("4e75") in code[code.index(stock_bytes):]


def test_the_fast_link_hook_replays_the_isr_instructions(applied, stock):
    # v0.16: the SSI ISR's 8 bytes at TDM_SITE become jsr smp_tdm_hook ; nop, and the
    # hook ends with the two instructions it displaced, then rts
    main = applied.payloads[3]
    assert at(stock, CF.TDM_SITE, 8) == CF.TDM_STOCK
    assert at(main, CF.TDM_SITE, 2) == bytes.fromhex("4eb9")
    assert at(main, CF.TDM_SITE + 6, 2) == bytes.fromhex("4e71")
    code = _chunked(long_at(main, CF.TDM_SITE + 2), 64)
    assert CF.TDM_STOCK + bytes.fromhex("4e75") in code


def _chunked(va: int, n: int) -> bytes:
    """N bytes at VA from the RAM chunks the mod loads (the machines chunk holds the
    name table, the attribute rows and the list since RESONATOR)."""
    for name in ("machines_chunk", "ping_chunk", "chunk", "c_chunk"):
        c = waverider.SPEC[name]
        code = bytes.fromhex(c["code"])
        if c["load"] <= va and va + n <= c["load"] + len(code):
            return code[va - c["load"]:va - c["load"] + n]
    raise AssertionError(f"{va:#x} is in no chunk")


def _clong(va: int) -> int:
    return struct.unpack(">I", _chunked(va, 4))[0]


def test_the_list_offers_our_machines_then_the_sample_machines_before_midi(applied):
    main = applied.payloads[3]
    begin = long_at(main, CF.LIST_BEGIN + 2)
    end = long_at(main, CF.LIST_END + 2)
    types = [_clong(a) for a in range(begin, end, 4)]
    # v0.15: the five sample machines in the Digitakt II's order (v0.13: ONESHOT, GRID)
    # v0.26: the Monomachine's machines after PERC (6, 7, then 14..)
    from dnfw.mnm import machines as MM
    assert types == [0, 2, 1, 3, 5, *MM.TYPES, 8, 9, 10, 11, 13, 12, 4]   # v0.19: SLICE before GRID
    n = 4 * len(types)
    assert at(main, CF.LIST_ALLOC, 4) == bytes.fromhex("4878") + n.to_bytes(2, "big")   # v0.19: 14 longs
    assert at(main, CF.LIST_CAP, 4) == bytes.fromhex("41e8") + n.to_bytes(2, "big")


def test_rows_5_to_12_of_the_name_table(applied):
    main = applied.payloads[3]
    table = long_at(main, 0x400DC344)
    # v0.26: 6, 7 (and 14..) the Monomachine's machines (RESONATOR's and CZ's until v0.25)
    assert CF.MACHINE_NAMES[5] == ("Perc", "PRC") and CF.MACHINE_NAMES[13] == ("Slice", "SLC")
    assert CF.MACHINE_NAMES[6] == ("SID 6581", "SID") and CF.MACHINE_NAMES[7] == ("DPRO Wave", "DPW")
    for row in CF.NEW_TYPES:
        lo, sh = (n.encode() + b"\0" for n in CF.MACHINE_NAMES[row])
        long_ptr, short_ptr = _clong(table + 12 * row), _clong(table + 12 * row + 4)
        assert _chunked(long_ptr, len(lo)) == lo and _chunked(short_ptr, len(sh)) == sh
    for bound in (0x400DC332, 0x400DC358, 0x400DC37E):
        assert at(main, bound, 2) == bytes([0x72, CF.TYPES_LAST])    # rows to TYPES_LAST (v0.19: 13)


def test_attribute_rows_5_to_12_are_wavetones(applied, stock):
    main = applied.payloads[3]
    rows = long_at(main, 0x400DC168)
    assert _chunked(rows, 20) == at(stock, CF.ATTR_STOCK_VA, 20)
    for row in CF.NEW_TYPES:
        assert _chunked(rows + 4 * row, 4) == at(stock, CF.ATTR_STOCK_VA + 4, 4)
    assert at(main, 0x400DC19C, 2) == bytes([0x74, CF.TYPES_LAST])   # v0.19: to 13 (v0.26: TYPES_LAST)


def test_the_stored_sound_load_keeps_types_5_to_12(applied):
    assert at(applied.payloads[3], CF.LOAD_BOUND, 2) == bytes([0x74, CF.TYPES_LAST + 2])   # v0.19: 13 SLICE kept


def test_the_group_function_gives_the_sample_machines_their_own_section(applied):
    # run the rewritten 0x40059274 on every type: synths 1, MIDI 2, 5 to 7 3, the sample
    # machines 8 to 12 4 (v0.13), else 0
    main = applied.payloads[3]
    code = at(main, CF.GROUP_FN, len(CF.GROUP_STOCK))
    got = {t: _run_group(code, t) for t in (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 16, 100)}
    assert got == {-1: 0, 0: 1, 1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 6: 3, 7: 3, 8: 4, 9: 4, 12: 4,
                   13: 4, 14: 3, 16: 3, 100: 3}             # v0.19: 13 SLICE; v0.26: 14.. ours (3)


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
    assert _chunked(raw, 4) == bytes.fromhex("2f0a246f")


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


def test_the_machines_chunk_fits_between_pings_and_the_runtime():
    c = waverider.SPEC["machines_chunk"]
    assert c["load"] == CF.MCHUNK and c["load"] + len(bytes.fromhex(c["code"])) <= CF.MCHUNK_END


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
    from dnfw.waverider import cpage
    if not (available() and cpage.available()):
        pytest.skip("no m68k assembler or GCC")
    built = CF.compose(stock, assemble, cpage.compile_page)
    content = bytearray(stock)
    for e in waverider.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    assert bytes(content) == built["content"]


def _edit(va):
    return next(e for e in waverider.SPEC["edits"] if e["va"] == va)


def test_the_setter_hook_writes_where_stock_wrote():
    # v0.15: the parameter setter's write goes through smp_quant_hook, which must end in
    # stock's own store (move.w %d3,0x14(%a0,%d2.l*2): 31 83 2a 14) and return; a store
    # at a different displacement would write the wrong slot of every sound edited
    e = _edit(CF.QUANT_SITE)
    assert bytes.fromhex(e["stock"]) == CF.QUANT_STOCK
    new = bytes.fromhex(e["new"])
    assert new[:2] == bytes.fromhex("4eb9")
    code = _chunked(struct.unpack(">I", new[2:6])[0], 64)
    tail = code.index(bytes.fromhex("2040" "31832a14"))          # movea.l %d0,%a0 ; the store
    assert code[tail + 6:tail + 8] == bytes.fromhex("4e75")


def test_the_key_handler_slot_points_into_the_renderer_and_stock_is_kept():
    e = _edit(CF.KEY_SLOT)
    assert struct.unpack(">I", bytes.fromhex(e["stock"]))[0] == CF.KEY_STOCK
    target = struct.unpack(">I", bytes.fromhex(e["new"]))[0]
    code = _chunked(target, 256)
    assert struct.pack(">I", CF.KEY_STOCK) in code          # smp_key calls stock's handler


def test_the_recorder_screen_hooks_replace_exactly_the_stock_calls():
    # v0.22: the UI loop's queue receive and screen draw become jsr's into the renderer
    # chunk (which call stock's own: 0x40001928, 0x4011d32a); FUNC + VOICE's branch of the
    # key handler becomes jsr rec_combo + bra to the handler's common exit
    c = waverider.SPEC["c_chunk"]
    lo, hi = c["load"], c["load"] + len(bytes.fromhex(c["code"]))
    for site, stock_bytes, called in ((CF.UI_POP_SITE, CF.UI_POP_STOCK, 0x40001928),
                                      (CF.SCREEN_SITE, CF.SCREEN_STOCK, 0x4011D32A)):
        e = _edit(site)
        assert bytes.fromhex(e["stock"]) == stock_bytes
        new = bytes.fromhex(e["new"])
        assert new[:2] == bytes.fromhex("4eb9") and len(new) == 6
        target = struct.unpack(">I", new[2:])[0]
        assert lo <= target < hi
        assert struct.pack(">I", called) in _chunked(target, 128)
    e = _edit(CF.REC_COMBO_SITE)
    assert bytes.fromhex(e["stock"]) == CF.REC_COMBO_STOCK
    new = bytes.fromhex(e["new"])
    assert len(new) == len(CF.REC_COMBO_STOCK) and new[:2] == bytes.fromhex("4eb9") and new[6:8] == bytes.fromhex("6000")
    assert lo <= struct.unpack(">I", new[2:6])[0] < hi
    assert CF.REC_COMBO_SITE + 8 + struct.unpack(">h", new[8:10])[0] == CF.REC_COMBO_EXIT


def test_the_lfo_list_asks_wr_lfo_mask_which_asks_stock():
    e = _edit(CF.LFO_MASK_LEA + 2)
    assert struct.unpack(">I", bytes.fromhex(e["stock"]))[0] == CF.LFO_MASK_STOCK
    target = struct.unpack(">I", bytes.fromhex(e["new"]))[0]
    assert struct.pack(">I", CF.LFO_MASK_STOCK) in _chunked(target, 128)


def test_trk_clear_reads_the_real_machine():
    # v0.22: TRK + CLEAR's getMachineType call is one of the identity sites
    assert any(va == 0x40071EB6 for va, _op, _w in CF.IDENTITY_SITES)


def test_v023_keyboard_notes_ask_slc_keynotes_which_asks_stock():
    # the KeyboardView's call for a trig key's notes goes to slc_keynotes (slice.c), which
    # gives slice k's note on a SLICE track and otherwise calls stock's 0x40034460
    c = waverider.SPEC["c_chunk"]
    lo, hi = c["load"], c["load"] + len(bytes.fromhex(c["code"]))
    e = _edit(CF.KEYNOTES_SITE)
    assert bytes.fromhex(e["stock"]) == CF.KEYNOTES_STOCK
    new = bytes.fromhex(e["new"])
    assert new[:2] == bytes.fromhex("4eb9") and len(new) == 6
    target = struct.unpack(">I", new[2:])[0]
    assert lo <= target < hi
    assert struct.pack(">I", 0x40034460) in _chunked(target, 256)

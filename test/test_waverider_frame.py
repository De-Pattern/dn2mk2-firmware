"""dnfw.waverider.frame: the parameter frame image as the DN2 1.11 DSP unpacks it."""

from dataclasses import dataclass

import pytest

from dnfw.waverider import frame as F


def test_slot_blocks_tile_146_bytes():
    covered = []
    for first, last, at in F.SLOT_BLOCKS:
        covered += list(range(at, at + 2 * (last - first + 1)))
    assert sorted(covered) == list(range(F.SLOT_STRIDE))


def test_slot_offsets_follow_the_four_block_copies():
    assert F.slot_offset(0, 25) == 218
    assert F.slot_offset(0, 66) == 218 + 82          # the filter block starts at 66
    assert F.slot_offset(0, 67) == 302               # FREQ, measured -> record +0x1cc
    assert F.slot_offset(0, 79) == 326               # KEY.T, measured -> record +0x208
    assert F.slot_offset(0, 80) == 218 + 110
    assert F.slot_offset(0, 95) == 218 + 136
    assert F.slot_offset(1, 25) - F.slot_offset(0, 25) == 146
    assert F.slot_offset(15, 99) + 2 <= F.FRAME_BYTES - 2688 + 2554
    for bad in (24, 93, 94, 100):
        with pytest.raises(ValueError):
            F.slot_offset(0, bad)


def test_header_arrays_are_one_word_per_track():
    assert F.header_offset(F.MACHINE, 0) == 148
    assert F.header_offset(F.FILTER, 15) == 180 + 30
    with pytest.raises(ValueError):
        F.header_offset(F.MACHINE, 16)


def test_filter_type_mapping_as_measured():
    assert [F.dsp_filter(t) for t in range(8)] == [1, 3, 2, 4, 5, 6, 0, 0]
    assert len(F.FILTER_NAMES) == len(F.FILTER_TO_DSP) == 6


def test_frame_puts_little_endian_words_and_trigger_bits():
    f = F.Frame()
    f.param(0, 67, 0x7F00)
    f.header(F.MACHINE, 3, 5)
    f.trigger(2)
    f.trigger(0, masks=(F.TRIG_NOTE,))
    b = f.to_bytes()
    assert len(b) == F.FRAME_BYTES
    assert b[302:304] == b"\x00\x7f"
    assert b[148 + 6:148 + 8] == b"\x05\x00"
    assert f.get(F.TRIG_NOTE) == 0b101
    assert all(f.get(m) == 0b100 for m in F.TRIG_MASKS[1:])
    f.trigger(2, on=False)
    assert f.get(F.TRIG_NOTE) == 0b001
    with pytest.raises(ValueError):
        f.put(3, 0)
    with pytest.raises(ValueError):
        f.put(0, 0x10000)


@dataclass
class Rec:
    group: int | None
    parameter_id: int | None
    default: int


def test_sound_defaults_takes_the_first_filter_page_and_the_sound_pages():
    recs = [Rec(5, 67, 0x7F00), Rec(6, 67, 0x1234),     # FREQ: Multimode's, not Lowpass 4's
            Rec(13, 77, 0x7F00), Rec(11, 90, 0x6E00),
            Rec(0, 30, 0x4000),                          # a machine parameter: left out
            Rec(15, 93, 1), Rec(None, None, 0)]
    d = F.sound_defaults(recs)
    assert d == {67: 0x7F00, 77: 0x7F00, 90: 0x6E00}


def test_record_fields_are_inside_the_track_record():
    for index, (off, kind, _) in F.RECORD_FIELDS.items():
        assert 0x1B4 < off < 0x234, index
        assert kind in "utfkvp"


def test_init_frame_puts_track0_on_the_machine_and_the_rest_on_midi():
    f = F.init_frame({67: 0x7F00, 90: 0x6E00}, 5, cf_filter=1, trigger=True, track0={67: 0})
    assert f.get(F.header_offset(F.MACHINE, 0)) == 5
    assert all(f.get(F.header_offset(F.MACHINE, t)) == 4 for t in range(1, 16))
    assert f.get(F.header_offset(F.FILTER, 0)) == 1
    assert f.get(F.slot_offset(0, 67)) == 0 and f.get(F.slot_offset(1, 67)) == 0x7F00
    assert f.get(F.header_offset(F.NOTE, 7)) == 0x3C00
    assert f.get(F.TRIG_NOTE) == 1

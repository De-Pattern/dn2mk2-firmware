"""The two gates a fourth LFO has to be let through, asserted against the image.

`build_lfo4_ui.py` refuses to patch an image whose bytes are not the ones these
sites were read from, which is the right behaviour at build time and invisible
until someone builds. This is the same assertion where it fails loudly, plus
the two facts about those sites that are not bytes: that the `SLEW` table has
a string immediately behind it and so cannot grow where it stands, and that
LFO4's entries sit exactly 226 above LFO3's.

The behavioural half belongs to the emulator -- `scripts/emu_lfo4_slew.py` and
`scripts/emu_lfo4_dest.py` open the real pages and count what executes. This is
the arithmetic half.
"""

import pathlib
import struct
import sys

import pytest

from dnfw.cli.files import read_image
from dnfw.firmware.load import load

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
MAIN_OS, BASE = 3, 0x40000400

# LFO3's ten records are 94..103, so its entries are 95..104; LFO4's are 321
# onwards. Everything below is stated in those terms rather than as raw
# numbers, so a change to either first entry cannot leave this test agreeing
# with a build that moved.
LFO3_ENTRY0, LFO4_ENTRY0 = 95, 321
SPH, SLEW, DEST = 6, 5, 3                  # positions within a group of ten


@pytest.fixture(scope="module")
def stock():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    return load(read_image(STOCK_111)).container.find(MAIN_OS).unpack()


@pytest.fixture(scope="module")
def ui():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    import build_lfo4_ui
    return build_lfo4_ui


def test_the_slew_gate_names_the_three_sph_entries(stock, ui):
    """81, 91, 101 -- LFO1's, LFO2's and LFO3's `SPH`, as literals."""
    at = ui.SLEW_GATE - BASE
    assert bytes(stock[at:at + len(ui.SLEW_GATE_STOCK)]) == ui.SLEW_GATE_STOCK
    for lfo, entry in enumerate((81, 91, 101)):
        assert entry == LFO3_ENTRY0 - 20 + 10 * lfo + SPH
    assert struct.pack(">B", 101) in ui.SLEW_GATE_STOCK


def test_the_slew_table_cannot_grow_where_it_stands(stock, ui):
    """`{80, 90, 100}`, and the next byte belongs to a mangled RTTI name."""
    at = ui.SLEW_ENTRIES - BASE
    assert struct.unpack(">3I", stock[at:at + 12]) == (80, 90, 100)
    for lfo, entry in enumerate((80, 90, 100)):
        assert entry == LFO3_ENTRY0 - 20 + 10 * lfo + SLEW
    behind = bytes(stock[at + 12:at + 32])
    assert b"LfoPag" in behind, behind


def test_the_slew_index_is_clamped_to_the_three_that_exist(stock, ui):
    for va in (ui.SLEW_CLAMP, ui.SLEW_CLAMPED):
        word = stock[va - BASE:va - BASE + 2]
        assert word[0] & 0xF1 == 0x70, word.hex()          # moveq #imm,dN
        assert word[1] == 2, word.hex()


def test_the_slew_table_is_reached_by_a_plain_lea(stock, ui):
    at = ui.SLEW_TABLE - BASE
    assert bytes(stock[at:at + 6]) == ui.SLEW_TABLE_STOCK
    assert struct.unpack_from(">I", ui.SLEW_TABLE_STOCK, 2)[0] == ui.SLEW_ENTRIES


def test_the_dest_gate_and_its_mask_cascade(stock, ui):
    at = ui.DEST_GATE - BASE
    assert bytes(stock[at:at + len(ui.DEST_GATE_STOCK)]) == ui.DEST_GATE_STOCK
    assert 98 == LFO3_ENTRY0 + DEST
    at = ui.DEST_MASK - BASE
    assert bytes(stock[at:at + len(ui.DEST_MASK_STOCK)]) == ui.DEST_MASK_STOCK
    # The three masks, and the one the staircase names next.
    assert b"\x1e\x00" in ui.DEST_MASK_STOCK
    assert b"\x0e\x00" in ui.DEST_MASK_STOCK
    assert b"\x06\x00" in ui.DEST_MASK_STOCK
    assert b"\x02\x00" not in ui.DEST_MASK_STOCK


def test_the_gate_and_the_mask_do_not_overlap(ui):
    assert ui.DEST_GATE + len(ui.DEST_GATE_STOCK) <= ui.DEST_MASK
    assert ui.SLEW_GATE + len(ui.SLEW_GATE_STOCK) <= ui.SLEW_CLAMP
    assert ui.SLEW_CLAMPED + 2 <= ui.SLEW_TABLE


def test_lfo4s_entries_are_lfo3s_plus_the_same_offset(ui):
    offset = LFO4_ENTRY0 - LFO3_ENTRY0
    assert offset == 226
    assert LFO3_ENTRY0 + SPH + offset == 327
    assert LFO3_ENTRY0 + SLEW + offset == 326
    assert LFO3_ENTRY0 + DEST + offset == 324

"""The LFO4 mod: it applies to stock 1.11, refuses what it cannot sit on, and
reproduces the image that was gated.

`scripts/gen_lfo4_code.py` packages `build_lfo4_browser.RELEASE`, the build
the release `.syx` came from, so what is asserted here is **byte equality with
`lfo4-everyvoice4`**, the release twin of the code that passed tests 10 and 11
on the instrument (`docs/lfo4-build-plan.md`).
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, lfo4, moddest
from dnfw.patch import paramtable

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
GATED = ROOT / "out/lfo4-everyvoice4/section_3_MAIN_OS.bin"
BASE = lfo4.BASE


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(lfo4.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(stock):
    return lfo4.compose(stock)


def test_is_the_image_that_was_gated(applied):
    if not GATED.exists():
        pytest.skip("out/lfo4-everyvoice4 is not built")
    assert applied == GATED.read_bytes()


def test_changes_nothing_outside_its_extents(stock, applied):
    allowed = [(e.start, e.end) for e in lfo4.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(applied) == allowed[-1][1]


def test_ships_no_stock_table():
    """The relocated table's place in the packaged blob is blank."""
    blob = bytes.fromhex(lfo4.SPEC["blob"])
    at = lfo4.SPEC["table_offset"]
    assert not any(blob[at:at + paramtable.RECORD * lfo4.SPEC["table_records"]])


def test_refuses_an_image_that_already_grew(stock):
    with pytest.raises(ModError, match="appended"):
        lfo4.compose(stock + bytes(16))


def test_refuses_a_changed_edit_site(stock):
    e = lfo4.SPEC["edits"][0]
    bad = bytearray(stock)
    bad[e["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError, match="not stock"):
        lfo4.compose(bytes(bad))


def test_carries_a_table_edit_made_before_it(dn2_111, stock):
    """moddest opens thirteen masks in the stock table; applied first, they
    are in LFO4's relocated copy -- which is why the CLI applies lfo4 last."""
    opened = moddest.apply(dn2_111).payloads[moddest.SECTION]
    out = lfo4.compose(opened)
    table = paramtable.TABLE - BASE
    moved = lfo4.SPEC["area_va"] - BASE + lfo4.SPEC["table_offset"]
    for at, label in moddest._targets(stock):
        assert struct.unpack_from(">I", out, moved + at - table)[0] == moddest.OPEN, label

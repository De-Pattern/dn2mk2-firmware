"""The song guard: it rewrites exactly the song LOAD's header copy, refuses an
image that is not stock there, and shares no byte with any other mod.

What it *does* is measured in the emulator, not here
(`scripts/emu_project_load.py --full`, 2026-09-26): SKETCHPAD's first song
carries a row count of 21,503, and stock, `fxmod+lfo4` and
`lfowaves+moddest+midiarp` all fault opening it and open it cleanly with this
mod or with that one field repaired. A 99-row song loads byte-identically with
and without it. `src/dnfw/mods/songguard.py` carries the detail.
"""

import pathlib

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import songguard

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
AT = songguard.SITE - songguard.BASE


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(songguard.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return songguard.apply(dn2_111).payloads[songguard.SECTION]


def test_stock_bytes_are_what_the_image_holds(stock):
    assert stock[AT:AT + len(songguard.STOCK)] == songguard.STOCK


def test_writes_the_rewrite_and_nothing_else(stock, applied):
    assert len(applied) == len(stock)
    assert applied[AT:AT + len(songguard.NEW)] == songguard.NEW
    assert applied[:AT] == stock[:AT]
    assert applied[AT + len(songguard.NEW):] == stock[AT + len(songguard.NEW):]


def test_extent_is_the_rewrite(applied, stock):
    (e,) = songguard.extents()
    changed = [i for i in range(len(stock)) if stock[i] != applied[i]]
    assert e.start <= min(changed) and max(changed) < e.end


def test_the_bound_is_the_record_capacity():
    # Stored rows: 29 B from +20 up to the count at +2891. Live rows: 37 B from
    # +16 up to the count at +3679. Both are exactly 99 rows.
    assert (2891 - 20) / 29 == songguard.ROWS == (3679 - 16) / 37
    assert songguard.NEW[4:6] == bytes([0x70, songguard.ROWS])     # moveq #99,%d0


def test_refuses_an_image_already_guarded(dn2_111, applied):
    from dnfw.cli.mods import _staged
    staged = _staged(dn2_111, {songguard.SECTION: applied})
    with pytest.raises(ModError):
        songguard.apply(staged)


def test_shares_no_byte_with_any_mod(dn2_111):
    from dnfw.cli.mods import REGISTRY
    named = [(mid, list(mod.extents(dn2_111))) for mid, mod in REGISTRY.items()
             if mid != "transients"]
    ours = [n for n in named if n[0] == songguard.ID]
    for other in named:
        if other[0] != songguard.ID:
            assert check_compatible(ours + [other]) == [], other[0]

"""v0.58's microtonal scales (dnfw.waverider.scales): the tunings, the names' room, and the
tables built from stock MAIN OS 1.11 when its section is at hand (DT2_SECTIONS)."""

import os
import pathlib

import pytest

from dnfw.waverider import scales as SC


def test_fine_units_are_1_256_semitone():
    assert SC.fine(0.0) == 0 and SC.fine(None) == 0
    assert SC.fine(100.0) == 256
    assert SC.fine(-50.6) == -130            # ROD12's 11th: 1049.4 cents
    assert SC.fine(17.5) == 45


def test_tunings():
    rod, mn = SC.CENTS[SC.ROD12], SC.CENTS[SC.MIN12]
    assert len(rod) == len(mn) == 12 and rod[0] == mn[0] == 0.0
    assert all(c is not None for c in rod)
    # the minor is the 12-note scale's 1 2 b3 4 5 b6 b7, its cents the same
    assert [s for s, c in enumerate(mn) if c is not None] == [0, 2, 3, 5, 7, 8, 10]
    assert all(mn[s] == rod[s] for s in range(12) if mn[s] is not None)
    # cents within a semitone either way, so a note never passes its neighbour
    assert all(abs(c) < 100 for c in rod)


def test_names_fit_stock_room():
    # stock's longest full name is "Locr. bb3 bb7" (13), its short names 4 characters
    for full, short in SC.NAMES.values():
        assert len(full) <= 13 and len(short) == 4 and full.isascii()


def _stock():
    sec = os.environ.get("DT2_SECTIONS")
    f = pathlib.Path(sec or "", "section_3_MAIN_OS.bin")
    if not sec or not f.exists():
        pytest.skip("stock MAIN OS 1.11 (DT2_SECTIONS) not present")
    return f.read_bytes()


def test_tables_from_stock():
    t = SC.tables(_stock())
    assert len(t["keys"]) == SC.LAST + 2 and len(t["deg"]) == len(t["mask"]) == SC.LAST + 1
    assert len(t["names"]) == len(t["short"]) == SC.N_STOCK + 1
    assert t["keys"][SC.ROD12 + 1] == t["keys"][0]                     # Chromatic's keys
    assert t["keys"][SC.MIN12 + 1] == t["keys"][SC.AEOLIAN + 1]
    assert t["deg"][SC.ROD12] == t["deg"][SC.IONIAN] and t["deg"][SC.MIN12] == t["deg"][SC.AEOLIAN]
    assert all(t["mask"][SC.ROD12]) and t["mask"][SC.MIN12] == t["mask"][SC.AEOLIAN]
    h = SC.c_header(_stock())
    assert '"Poole Rod12"' in h and '"PM12"' in h and "kb_keys[38][16]" in h

"""The pairwise matrix tells refused, order-only and clean pairs apart."""

import pathlib

import pytest

from dnfw.mods import bootscreen, lfo4, lfowaves, matrix, moddest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def found():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.cli.mods import _apply_default, _staged
    from dnfw.firmware.load import load
    fw = load(read_image(STOCK_111))
    registry = {m.ID: m for m in (bootscreen, lfo4, lfowaves, moddest)}
    pairs = matrix.pairs(fw, registry, lambda mod, f: _apply_default(mod, f, ROOT), _staged)
    return {(p.a, p.b): p for p in pairs}


def test_two_loader_mods_share_the_platform(found):
    """lfo4 and lfowaves both use the start-up loader and the appended area,
    which the platform owns; they combine with lfowaves first, because lfo4
    edits the compare lfowaves' getShortName hook displaced."""
    pair = found[("lfo4", "lfowaves")]
    assert pair.combines and pair.order_only and not pair.overlaps
    assert list(pair.refused) == ["lfo4+lfowaves"]
    for other in ("lfo4", "lfowaves"):
        boot = found[tuple(sorted(("bootscreen", other)))]
        assert boot.combines and not boot.order_only


def test_moddest_then_lfo4_only(found):
    pair = found[("lfo4", "moddest")]
    assert pair.combines and pair.order_only
    assert list(pair.refused) == ["lfo4+moddest"]


def test_disjoint_pair_combines(found):
    pair = found[("lfowaves", "moddest")]
    assert pair.combines and not pair.order_only


def test_a_pages_row_is_that_row_of_the_table(found):
    """A tool page shows its mod's row (`<!-- dnfw:matrix-row ID -->`): the same
    header and the same cells as that row of the full table, and no other row."""
    pairs = list(found.values())
    ids = sorted({m for p in pairs for m in (p.a, p.b)})
    names = {m: m.upper() for m in ids}
    full = matrix.table_html(ids, pairs, names)
    row = matrix.table_html(ids, pairs, names, only="lfo4")
    rows = [ln for ln in row.splitlines() if ln.strip().startswith('<tr><th scope="row">')]
    assert len(rows) == 1 and "<code>lfo4</code>" in rows[0]
    assert rows[0] in full.splitlines()
    assert row.splitlines()[:3] == full.splitlines()[:3]

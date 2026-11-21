"""v0.68: MACHINE SEL's icons (src/dnfw/msicons.py -> csrc/sampler/msicon_art.h)"""
from dnfw import msicons
from dnfw.waverider import coldfire


def test_header_is_current():
    assert msicons.HEADER.read_text() == msicons.header()


def test_every_mod_machine_has_an_icon_and_none_else():
    assert set(msicons.TYPE_ICON) == set(coldfire.NEW_TYPES)


def test_icons_fit_the_pane():
    for n in msicons.ORDER:
        rows = msicons.icon(n)
        assert 1 <= len(rows) <= msicons.ICON_H and all(len(r) == len(rows[0]) <= msicons.ICON_W for r in rows)
        x0, y0 = 25 - len(rows[0]) // 2, 27 - len(rows) // 2
        assert x0 >= 6 and x0 + len(rows[0]) <= 45 and y0 >= 12 and y0 + len(rows) <= 42, n

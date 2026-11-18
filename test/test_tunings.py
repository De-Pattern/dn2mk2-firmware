"""v0.61: the factory tunings against their definitions (docs/microtuning.md)."""
from dnfw.waverider import tunings as T


def _by(name):
    return dict((n, c) for n, _, c in T.FACTORY)[name]


def test_shape():
    assert T.check()
    assert len(T.FACTORY) == 11 and T.USER_SLOTS == 8


def test_known_values():
    jm = _by("JUST MAJOR")
    assert round(jm[4], 3) == -13.686          # 5/4: 386.314 cents
    assert round(jm[7], 3) == 1.955            # 3/2: 701.955
    py = _by("PYTHAGOREAN")
    assert round(py[4], 3) == 7.820            # 81/64: 407.820
    mt = _by("MEANTONE 1/4")
    assert round(mt[7], 3) == -3.422           # the fifth, 696.578
    assert round(mt[4], 3) == -13.686          # its pure major third
    assert round(mt[8], 3) == -27.373          # G#, 772.627 (the wolf sits G# - Eb)
    assert _by("12-TET") == [0.0] * 12


def test_fine():
    assert T.fine(1000) == 256 and T.fine(-500) == -128 and T.fine(0) == 0
    assert T.fine(137) == 35                   # 13.7 cents -> 35/256 semitone


def test_negative_control():
    # a tuning off by a semitone at pc 4 would read -1000 tenths: refused by check()'s range
    bad = list(T.FACTORY)
    bad.append(("BAD", "BAD", [0] * 4 + [-100.0] + [0] * 7))
    old = T.FACTORY
    T.FACTORY = bad
    try:
        T.check()
        assert False, "check() let a 100-cent offset through"
    except AssertionError as e:
        assert "BAD" in str(e)
    finally:
        T.FACTORY = old


def test_c_header():
    h = T.c_header()
    assert "#define TN_FACTORY 11" in h and "#define TN_USER 8" in h
    assert h.count("{0, ") >= 11 and '"JMAJ"' in h and '"POOLE ROD12"' in h
    assert all(s.isupper() or not s.isalpha() for _, s, _ in T.FACTORY)   # the screen's font: capitals

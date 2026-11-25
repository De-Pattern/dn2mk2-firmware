"""v0.61 microtuning: the factory tunings (docs/microtuning.md).

A tuning is 12 offsets in tenths of a cent, one per semitone above its ROOT (pc 0..11), against
12-TET, repeating every octave. The audio side adds them to a voice's NOTE word
(note << 8 | fine, fine in 1/256 semitone): fine = round(tenths * 256 / 1000).
"""
from fractions import Fraction
from math import log2

NAMES_MAX = 15                     # the list's full names; SHORT is the knob's 5 letters


def _ratios(rs):
    return [1200 * log2(Fraction(r)) - 100 * k for k, r in enumerate(rs)]


def _cents(cs):
    return [c - 100 * k for k, c in enumerate(cs)]


def _fifths(fifth, lo):
    """Each pitch class by its stack of FIFTH-cent fifths, from LO fifths below ROOT."""
    out = [0.0] * 12
    for k in range(lo, lo + 12):
        c = (k * fifth) % 1200
        out[(k * 7) % 12] = c
    return _cents(out)


# (1/4-comma meantone's fifth: 3/2 narrowed by a quarter of the syntonic comma, 696.578 cents)
_QC = 1200 * log2(Fraction(3, 2)) - 1200 * log2(Fraction(81, 80)) / 4

# (full name, short name, offsets in cents by pc above ROOT)
FACTORY = [
    ("12-TET", "12TET", [0.0] * 12),
    ("JUST MAJOR", "JMAJ", _ratios(["1", "16/15", "9/8", "6/5", "5/4", "4/3", "45/32", "3/2",
                                     "8/5", "5/3", "9/5", "15/8"])),
    ("JUST MINOR", "JMIN", _ratios(["1", "16/15", "10/9", "6/5", "5/4", "4/3", "64/45", "3/2",
                                     "8/5", "5/3", "16/9", "15/8"])),
    ("PYTHAGOREAN", "PYTH", _ratios(["1", "256/243", "9/8", "32/27", "81/64", "4/3", "729/512",
                                     "3/2", "128/81", "27/16", "16/9", "243/128"])),
    ("MEANTONE 1/4", "MEAN4", _fifths(_QC, -3)),          # Eb .. G#, the wolf between them
    ("WERCKMEISTER3", "WERK3", _cents([0, 90.225, 192.180, 294.135, 390.225, 498.045, 588.270,
                                       696.090, 792.180, 888.270, 996.090, 1092.180])),
    ("KIRNBERGER3", "KIRN3", _cents([0, 90.225, 193.157, 294.135, 386.314, 498.045, 590.224,
                                     696.578, 792.180, 889.735, 996.090, 1088.269])),
    ("VALLOTTI", "VALOT", _cents([0, 94.135, 196.090, 298.045, 392.180, 501.955, 592.180,
                                  698.045, 796.090, 894.135, 1000.000, 1090.225])),
    ("ARABIC RAST", "RAST", [0, 0, 0, 0, -50.0, 0, 0, 0, 0, 0, 0, -50.0]),   # E and B half flat
    ("POOLE ROD12", "PR12", [0, -46.7, 3.9, -33.1, 17.5, -2.0, -48.7, 2.0, -35.1, 5.9, -31.2,
                             -50.6]),                     # the owner's poole-rod12tone.scl
    ("POOLE12 MIN", "PM12", [0, 0, 3.9, -33.1, 0, -2.0, 0, 2.0, -35.1, 0, -31.2, 0]),
    # (the owner's poole12minor.scl: its 7 degrees; the other 5 at 12-TET)
]

USER_SLOTS = 8


def tenths(cents):
    """Offsets in whole tenths of a cent, as the EDIT page shows and the project keeps them."""
    return [int(round(c * 10)) for c in cents]


def fine(t):
    """Tenths of a cent -> the NOTE word's fine units (1/256 semitone)."""
    return int(round(t * 256 / 1000))


def table():
    """The factory tunings as the C chunk carries them: per tuning 12 signed shorts in tenths."""
    return [(n, s, tenths(c)) for n, s, c in FACTORY]


def check():
    for n, s, c in FACTORY:
        assert len(c) == 12 and len(n) <= NAMES_MAX and len(s) <= 5, n
        assert abs(c[0]) < 1e-9, n
        assert all(-999 <= t <= 999 for t in tenths(c)), n
    return True


def c_header() -> str:
    """The factory tunings for csrc/sampler/tune.c (wr_gen.h, under TUNE_C): their tenths of a cent
    and their names, the user slots' count."""
    t = table()
    rows = ",\n ".join("{" + ", ".join(str(v) for v in c) + "}" for _, _, c in t)
    longs = ", ".join(f'"{n}"' for n, _, _ in t)
    shorts = ", ".join(f'"{s}"' for _, s, _ in t)
    return (f"\n/* v0.61 microtuning (dnfw.waverider.tunings) */\n#ifdef TUNE_C\n"
            f"#define TN_FACTORY {len(t)}\n#define TN_USER {USER_SLOTS}\n"
            f"static const short tn_factory[TN_FACTORY][12] = {{\n {rows}}};\n"
            f"static const char *const tn_long[TN_FACTORY] = {{{longs}}};\n"
            f"static const char *const tn_short[TN_FACTORY] = {{{shorts}}};\n#endif\n")

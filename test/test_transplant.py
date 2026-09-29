"""dnfw.transplant: the SHARC relocation arithmetic.

The pure-arithmetic tests always run; they need no firmware file.
"""

import pathlib

import pytest

from dnfw.transplant import sharc as S

ROOT = pathlib.Path(__file__).resolve().parent.parent
FW = ROOT / "00_Resources" / "00_Firmware"
DT2 = FW / "Digitakt_II_OS1.16_dist" / "Digitakt_II_OS1.16.syx"
DN2 = FW / "Digitone_II_OS1.11_dist.zip"
DT2_15C = FW / "Digitakt_II_OS1.15C.syx"


# -- relocation arithmetic (pure) -------------------------------------------------------------

def test_code_and_data_addresses():
    assert S.code_address(0x1C4ECF) == 0x28000000 + 2 * 0x1C4ECF
    assert S.data_address(0x25D940) == 0x28000000 + 0x25D940
    assert S.code_address(0xB80000, "l2") == 0x20000000 + 2 * (0xB80000 - 0x00B80000)


def test_value_bytes_roundtrip():
    value = 0xF150025D940
    assert S.to_value(S.to_bytes(value)) == value
    assert S.get_field(value, "data32") == 0x25D940


def test_retarget_absolute_and_relative():
    # a 17a `I5 = 0x25d940` -> point it at 0x294000
    v = 0xF150025D940
    v2 = S.retarget(v, "data32", 0x1809DB, 0x294000)
    assert S.get_field(v2, "data32") == 0x294000
    # an 8a_rel CALL at sw src to donor target keeps its meaning after moving both
    src, dst = 0x1C5193, 0x1C06BA
    rel = S.retarget(0, "rel24", src, dst)  # build a rel field
    assert S.target_of(rel, "rel24", src) == dst
    moved = S.retarget(rel, "rel24", 0x180AC4, 0x180D00)
    assert S.target_of(moved, "rel24", 0x180AC4) == 0x180D00

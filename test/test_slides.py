"""Parameter slides (dnfw.slides, docs/slides.md): which slots a slide moves, the length
table, and the hooks the shipped SPEC carries. `scripts/emu_slides.py` is the behavioural
evidence (the ship gate's "parameter slides (ColdFire)" step)."""

import pathlib

import pytest

from dnfw import slides as SL
from dnfw.mods import waverider

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def stock():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111)).container.find(3).unpack()


def bits(m):
    return {s for s in range(128) if m >> s & 1}


def test_continuous_slots(stock):
    shared, machine = SL.masks(stock)
    s = bits(shared)
    assert {67, 68, 69, 90, 93} <= s                  # FREQ, RESO, filter ENV, VOL, PTIM
    assert not s & {4, 12, 20}                        # LFO DEST: never
    assert not s & {2, 5, 7, 66, 75, 91, 92, 94, 97, 99}   # MULT, WAVE, MODE, the EQ's TYPE, resets, routings
    fm = bits(machine[0])
    assert 31 in fm and 25 not in fm and 26 not in fm  # FDBK slides; ALGO and RATIO C do not
    assert all(25 <= x <= 65 for t in machine for x in bits(t))


def test_lengths():
    assert len(SL.SLEN_UNITS) == len(SL.SLEN_TEXT)
    assert SL.SLEN_UNITS[SL.SLEN_DEFAULT] == 24       # the default: one step
    assert list(SL.SLEN_UNITS) == sorted(SL.SLEN_UNITS)
    assert SL.SLEN_UNITS[-1] * 65536 < 2 ** 31       # elapsed, units << 16, fits


def test_ids_clear_of_stock_and_arp():
    assert SL.ID_SLD > 129 and SL.ID_SLEN > 129 and 0xFF not in (SL.ID_SLD, SL.ID_SLEN)
    assert SL.RAM_SLD <= 100 and SL.RAM_SLEN <= 100


def test_spec_hooks():
    edits = {e["va"]: e for e in waverider.SPEC["edits"]}
    for site, stock_hex in ((SL.PRE_SITE, SL.PRE_STOCK), (SL.APPLY_SITE, SL.APPLY_STOCK),
                            (SL.SMOOTH_SITE, SL.SMOOTH_STOCK), (SL.BUILD_SITE, SL.BUILD_STOCK),
                            (SL.CLEAR_SITE, SL.CLEAR_STOCK), (SL.LOAD_SITE, SL.LOAD_STOCK),
                            (SL.SAVE_SITE, SL.SAVE_STOCK)):
        assert edits[site]["stock"] == stock_hex
    lay = waverider.SPEC["layout"]
    c0 = waverider.SPEC["c_chunk"]["load"]
    for name in ("sl_pre_hook", "sl_apply", "sl_smooth", "sl_build", "sl_clear", "sl_load", "sl_save"):
        assert c0 <= lay[name] < lay["c_text_end"]

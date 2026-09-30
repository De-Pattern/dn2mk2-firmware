"""Every address above BSS a mod's bytes name is RAM the mod declares (`dnfw.mods.ramcheck`).

The platform compares declared RAM pairwise, so a declaration that misses a
range defeats it silently. On 2026-09-30 lfo4's LFO state arrays were missing
from its `ram()`, the boot screen's stamp was placed on them, and the first
flash of the three together raised V04 at 0x46700000.
"""

import pathlib

import pytest

from dnfw.mods import ramcheck

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def applied(tmp_path_factory):
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.cli.mods import REGISTRY, _apply_default
    from dnfw.firmware.load import load
    fw = load(read_image(STOCK_111))
    stock = fw.container.find(3).unpack()
    tmp = tmp_path_factory.mktemp("ramcheck")
    out = {}
    for mid, mod in REGISTRY.items():
        result = _apply_default(mod, fw, tmp)
        if 3 in result.payloads:
            out[mid] = (mod, result.payloads[3])
    return stock, out


def test_every_mod_declares_the_ram_it_names(applied):
    stock, mods = applied
    bad = {}
    for mid, (mod, content) in mods.items():
        found = ramcheck.undeclared(stock, content, getattr(mod, "ram", list)(),
                                    getattr(mod, "NOT_RAM", ()))
        if found:
            bad[mid] = [f"0x{at:08x} names 0x{v:08x}" for at, v in found[:8]]
    assert not bad, bad


def test_it_would_have_caught_the_stamp_on_lfo4s_state(applied):
    """lfo4 without its state arrays declared, as it was when the stamp went there."""
    from dnfw.mods import lfo4
    stock, mods = applied
    _, content = mods["lfo4"]
    missing = [x for x in lfo4.ram() if not x.what.startswith("LFO state")]
    found = {v & ~0xFFF for _, v in ramcheck.undeclared(stock, content, missing)}
    assert 0x46700000 in found

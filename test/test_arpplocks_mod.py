"""The arp p-locks mod: applies to stock 1.11, refuses a changed image, and
combines with the boot screen (its core cave sits past the boot screen's code)."""

import pathlib

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import arpplocks, bootscreen

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


def test_applies_every_edit(dn2_111):
    result = arpplocks.apply(dn2_111)
    content = result.payloads[arpplocks.SECTION]
    for e in arpplocks.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        at = e["va"] - arpplocks.BASE
        assert content[at:at + len(new)] == new


def test_refuses_a_changed_image(dn2_111):
    section = dn2_111.container.find(arpplocks.SECTION)
    content = bytearray(section.unpack())
    at = arpplocks.SPEC["edits"][0]["va"] - arpplocks.BASE
    content[at] ^= 0xFF

    class Stub:
        class container:
            @staticmethod
            def find(_):
                class S:
                    @staticmethod
                    def unpack():
                        return bytes(content)
                return S
    with pytest.raises(ModError):
        arpplocks.apply(Stub)


def test_combines_with_the_boot_screen():
    named = [(arpplocks.ID, arpplocks.extents()),
             (bootscreen.ID, bootscreen.extents(None, area_length=4096))]
    assert check_compatible(named) == []

"""The FX modulation mod: it applies to stock 1.11, refuses anything else, and
reproduces the image that was gated.

The last of those is the point of this file. `fxmod` is not a re-derivation of
`fxbrowser3` for the browser — `scripts/gen_fxmod_code.py` composes it from
`scripts/build_fxbrowser.compose`, the same function the `.syx` came out of. So
what is asserted here is **byte equality with the build that was measured**,
which is a stronger statement than "the mod does what its own data says".

`docs/fx-master-modulation.md` §12, §15, §18 and §23 carry the evidence.
"""

import pathlib

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import fxmod, lfowaves, moddest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
GATED = ROOT / "out/fxbrowser3/section_3_MAIN_OS.bin"

BASE = fxmod.BASE
CHORUS_SLOT = 0x401F7720          # the group -> short-name table, group 16
REVERB_SLOT = 0x401F7724
DELAY_SLOT = 0x401F7728
ERR, CHR = 0x40210C9E, 0x4021077C


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def applied(dn2_111):
    return fxmod.apply(dn2_111).payloads[fxmod.SECTION]


def long_at(content: bytes, va: int) -> int:
    return int.from_bytes(content[va - BASE:va - BASE + 4], "big")


def test_applies_every_edit(applied):
    for e in fxmod.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        at = e["va"] - BASE
        assert applied[at:at + len(new)] == new, e["what"]


def test_changes_nothing_else(dn2_111, applied):
    """A mod that writes its edits *and* something else would pass the test
    above. The extents are the compatibility promise, so anything outside them
    is both a wrong image and a broken promise."""
    stock = dn2_111.container.find(fxmod.SECTION).unpack()
    allowed = [(e.start, e.end) for e in fxmod.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i]
             and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == [], f"{len(stray)} bytes changed outside the declared extents"


def test_is_the_image_that_was_gated(applied):
    """Byte equality with `fxbrowser3`, whose predecessor was flashed.

    Skips rather than passing when the build output is absent: `out/` is
    scratch and is not in the repository, so a missing file here means the
    check did not run, not that it succeeded.
    """
    if not GATED.exists():
        pytest.skip(f"{GATED.relative_to(ROOT)} not present; "
                    "run scripts/build_fxbrowser3.py to regenerate it")
    assert applied == GATED.read_bytes()


def test_names_chorus_and_leaves_its_neighbours(dn2_111, applied):
    """The one edit whose meaning a byte comparison does not carry.

    Stated for all three groups, because §22 of the evidence document was a
    hypothesis that explained Chorus and predicted nothing about Delay and
    Reverb, and one question to the owner killed it.
    """
    stock = dn2_111.container.find(fxmod.SECTION).unpack()
    assert long_at(stock, CHORUS_SLOT) == ERR
    assert long_at(applied, CHORUS_SLOT) == CHR
    for slot in (REVERB_SLOT, DELAY_SLOT):
        assert long_at(stock, slot) == long_at(applied, slot)


def test_the_cave_it_writes_into_was_free(dn2_111):
    stock = dn2_111.container.find(fxmod.SECTION).unpack()
    at = fxmod.SPEC["cave_va"] - BASE
    assert stock[at:at + fxmod.SPEC["cave_used"]] == bytes(fxmod.SPEC["cave_used"])


def test_refuses_a_changed_image(dn2_111):
    section = dn2_111.container.find(fxmod.SECTION)
    content = bytearray(section.unpack())
    content[fxmod.SPEC["edits"][0]["va"] - BASE] ^= 0xFF

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
        fxmod.apply(Stub)


def test_refuses_an_image_whose_guards_moved(dn2_111):
    """A guard is a site the mod reads and never writes, so breaking one must
    still refuse — otherwise the guards are decoration."""
    section = dn2_111.container.find(fxmod.SECTION)
    content = bytearray(section.unpack())
    content[fxmod.SPEC["guards"][0]["va"] - BASE] ^= 0xFF

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
        fxmod.apply(Stub)


def test_names_twenty_four_destinations():
    assert sum(len(p) for _, p in fxmod.destinations()) == 24


def test_combines_with_the_other_section_three_mods(dn2_111):
    named = [(fxmod.ID, fxmod.extents()),
             (moddest.ID, moddest.extents(dn2_111)),
             (lfowaves.ID, lfowaves.extents(dn2_111))]
    assert check_compatible(named) == []

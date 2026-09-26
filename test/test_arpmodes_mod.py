"""The arp modes mod: it applies to stock 1.11, refuses anything else, reproduces
the build it was generated from, and leaves arpplocks' bytes alone while
reaching its MODE lock.

`scripts/gen_arpmodes_code.py` composes the SPEC from
`scripts/build_arpmodes.compose` and refuses to write it unless replaying it on
stock gives the compose output byte for byte. What is asserted here is that the
shipped JSON still does, and what each edit means.
`scripts/emu_arp_modes.py` is the behavioural evidence (SHUF, RAND, the bounds).
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import arpmodes, arpplocks, bootscreen, fxmod, lfowaves, midiarp, moddest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BUILT = ROOT / "out/arpmodes/section_3_MAIN_OS.bin"
BASE = arpmodes.BASE
BOUNDS = (0x4004BEFA, 0x4004BF00, 0x4004BFB4, 0x4004BFC6, 0x400DD530)
DISPATCH = 0x4002A13C
SET_MODE_CEILING = 0x4004BF01


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(arpmodes.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return arpmodes.apply(dn2_111).payloads[arpmodes.SECTION]


def at(content: bytes, va: int, n: int) -> bytes:
    return content[va - BASE:va - BASE + n]


def stub(content: bytes):
    class Stub:
        class container:
            @staticmethod
            def find(_):
                class S:
                    @staticmethod
                    def unpack():
                        return bytes(content)
                return S
    return Stub


def test_applies_every_edit(applied):
    for e in arpmodes.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        assert at(applied, e["va"], len(new)) == new, e["what"]


def test_changes_nothing_else(stock, applied):
    allowed = [(e.start, e.end) for e in arpmodes.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(applied) == len(stock)


def test_is_the_build(applied):
    """Byte equality with `scripts/build_arpmodes.py`'s output, which the
    emulator gates ran. Skips when it is absent: `out/` is scratch."""
    if not BUILT.exists():
        pytest.skip("out/arpmodes is not built; run scripts/build_arpmodes.py")
    assert applied == BUILT.read_bytes()


def test_every_bound_is_six(stock, applied):
    """MODE stops at RAND: SHUF 5 and RAND 6 in, CHRD 7 out."""
    for va in BOUNDS:
        assert at(stock, va, 2)[1] == 4
        assert at(applied, va, 2)[0] == at(stock, va, 2)[0]        # the same moveq
        assert at(applied, va, 2)[1] == 6


def test_the_dispatch_jumps_into_the_cave(applied):
    hook = at(applied, DISPATCH, 12)
    assert hook[:2] == bytes.fromhex("4ef9")
    assert struct.unpack(">I", hook[2:6])[0] == arpmodes.SPEC["labels"]["arpmodes"]
    assert hook[6:] == bytes.fromhex("4e71") * 3


def test_the_caves_were_free(stock):
    for e in arpmodes.SPEC["edits"]:
        if e["what"] == "arp modes code cave":
            n = len(e["new"]) // 2
            assert at(stock, e["va"] - 4, n + 8) == bytes(n + 8), hex(e["va"])


def test_refuses_a_changed_image(stock):
    content = bytearray(stock)
    content[arpmodes.SPEC["edits"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        arpmodes.apply(stub(content))


def test_refuses_an_image_whose_guards_moved(stock):
    content = bytearray(stock)
    content[arpmodes.SPEC["guards"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        arpmodes.apply(stub(content))


def test_byte_disjoint_from_every_section_three_mod(dn2_111):
    for other in (arpplocks.extents(), fxmod.extents(), midiarp.extents(),
                  moddest.extents(dn2_111), lfowaves.extents(dn2_111),
                  bootscreen.extents(None, area_length=4096)):
        assert check_compatible([(arpmodes.ID, arpmodes.extents()), ("other", other)]) == []


def test_ram_is_its_own():
    """0x467a0000.. is below arpplocks' shadows and above everyone else's."""
    mine = arpmodes.SPEC["ram"][0]
    lo, hi = mine["va"], mine["va"] + mine["bytes"]
    for r in arpplocks.SPEC["ram"]:
        assert hi <= r["va"] or r["va"] + r["bytes"] <= lo
    assert hi <= 0x467C0000 and lo >= 0x46780000 + 0x10000


def test_arpplocks_reads_the_ceiling_this_mod_widens(dn2_111, applied):
    """The arpplocks + arpmodes pair: arpplocks' MODE lock clamps to the
    immediate of setMode's `moveq`, which is 4 on stock and 6 here. So arpplocks
    needs no knowledge of this mod, and this mod writes none of its bytes."""
    read = bytes.fromhex("1039") + struct.pack(">I", SET_MODE_CEILING)     # move.b abs.l,%d0
    cave = next(e for e in arpplocks.SPEC["edits"] if e["va"] == 0x402CF560)
    assert read in bytes.fromhex(cave["new"])
    assert not any(lo <= SET_MODE_CEILING - BASE < hi for lo, hi in
                   ((e.start, e.end) for e in arpplocks.extents()))
    stock = dn2_111.container.find(3).unpack()
    assert at(stock, SET_MODE_CEILING, 1) == b"\x04"
    assert at(applied, SET_MODE_CEILING, 1) == b"\x06"


def test_applies_either_side_of_arpplocks(dn2_111):
    """Each accepts the image the other produced, and the two orders agree."""
    first = arpplocks.apply(dn2_111).payloads[3]
    a = arpmodes.apply(stub(first)).payloads[3]
    second = arpmodes.apply(dn2_111).payloads[3]
    b = arpplocks.apply(stub(second)).payloads[3]
    assert a == b

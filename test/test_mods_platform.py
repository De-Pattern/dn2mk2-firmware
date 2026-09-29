"""The platform: one loader and one appended area, shared by lfo4, lfowaves and bootscreen."""

import itertools
import json
import pathlib

import pytest

from dnfw.mods import ModError, check_compatible, platform
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = platform.BASE
STOCK_SYX = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.11 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


@pytest.fixture(scope="module")
def stock(firmware):
    return firmware.container.find(3).unpack()


def _apply(firmware, order):
    from dnfw.cli.mods import _staged
    from dnfw.mods import bootscreen, lfo4, lfowaves
    mark = [bootscreen.image_from_pixels({(x, x // 2) for x in range(128)})]
    run = {"lfo4": lfo4.apply, "lfowaves": lfowaves.apply,
           "bootscreen": lambda f: bootscreen.apply(f, mark)}
    payloads = {}
    for mid in order:
        payloads.update(run[mid](_staged(firmware, payloads)).payloads)
    return payloads[3]


def test_installs_the_loader_lfo4_passed_with(stock):
    """The platform's loader and call are lfo4's, which passed on the instrument."""
    spec = json.loads((pathlib.Path(platform.__file__).with_name("lfo4_code.json")).read_text())
    image = bytearray(stock)
    for e in spec["edits"]:
        at = e["va"] - BASE
        image[at:at + len(e["new"]) // 2] = bytes.fromhex(e["new"])
    out = platform.join(stock, [])
    for x in platform.extents():
        assert out[x.start:x.end] == image[x.start:x.end], x


def test_lfo4_alone_is_the_gated_build(stock):
    """lfo4 on the platform: its edits, then its own two CODE chunks, as before."""
    from dnfw.mods import lfo4
    spec = lfo4.SPEC
    image = bytearray(stock)
    for e in spec["edits"]:
        at = e["va"] - BASE
        image[at:at + len(e["new"]) // 2] = bytes.fromhex(e["new"])
    blob = bytearray.fromhex(spec["blob"])
    records = lfo4._table(stock)
    blob[spec["table_offset"]:spec["table_offset"] + len(records)] = records
    assert lfo4.compose(stock) == bytes(image) + bytes(blob)


def test_split_join_round_trip(stock):
    chunks = [(b"BOOT", b"abc"), (area.CODE, area.CodeChunk(0x46700000, b"\x4e\x75").pack())]
    out = platform.join(stock, chunks)
    base, back = platform.split(out)
    assert base == platform.join(stock, [])[:platform.STOCK_LENGTH]
    assert [c for c, _ in back] == [b"BOOT", area.CODE]
    assert platform.add(out, []) == out


def test_refuses_an_unknown_tail(stock):
    with pytest.raises(ModError, match="not the platform loader"):
        platform.split(stock + bytes(16))


def test_refuses_overlapping_code_chunks(stock):
    a = area.CodeChunk(0x46800000, bytes(8), bss=8).pack()
    b = area.CodeChunk(0x46800008, bytes(8)).pack()
    with pytest.raises(ModError, match="overlap at run time"):
        platform.join(stock, [(area.CODE, a), (area.CODE, b)])


def test_refuses_data_past_the_window(stock):
    with pytest.raises(ModError, match="past the data window"):
        platform.join(stock, [(b"ANIM", bytes(platform.DATA_LIMIT - platform.RUNTIME_VA))])


def test_data_chunks_go_first(stock):
    code = area.CodeChunk(0x46800000, bytes(64)).pack()
    _, back = platform.split(platform.join(stock, [(area.CODE, code), (b"BOOT", b"x")]))
    assert [c for c, _ in back] == [b"BOOT", area.CODE]


def test_an_edit_in_a_displaced_site_lands_on_the_copy(stock):
    site = 0x400372DA
    replay = bytes(stock[site - BASE:site - BASE + 10])
    code = area.CodeChunk(0x46780000, bytes(16) + replay).pack()
    chunks = [(area.CODE, code), platform.displace(site, 10, 0x46780010)]
    content = bytearray(stock)
    platform.write(content, chunks, site + 9, b"\x41", b"\x4b")
    assert content == stock
    moved = area.CodeChunk.unpack(chunks[0][1]).image
    assert moved[16 + 9] == 0x4B and moved[16:25] == replay[:9]
    with pytest.raises(ModError, match="straddles"):
        platform.write(content, chunks, site + 8, b"\x01\x41\x55", b"\x01\x4b\x55")


def test_the_three_combine_in_every_order_lfo4_last(firmware):
    results = set()
    for first in itertools.permutations(["lfowaves", "bootscreen"]):
        out = _apply(firmware, list(first) + ["lfo4"])
        base, chunks = platform.split(out)
        results.add((base, frozenset(chunks)))
    assert len(results) == 1


def test_lfo4_before_lfowaves_is_refused_with_the_order(firmware):
    with pytest.raises(ModError, match="apply lfowaves first"):
        _apply(firmware, ["lfo4", "lfowaves"])


def test_lfo4s_bound_reaches_lfowaves_replay(firmware):
    """getShortName's compare, displaced by lfowaves, carries lfo4's 331."""
    from dnfw.mods import lfowaves
    _, chunks = platform.split(_apply(firmware, ["lfowaves", "lfo4"]))
    (_, _, copy), = platform.displaced(chunks)
    code = next(area.CodeChunk.unpack(d) for c, d in chunks
                if c == area.CODE and area.CodeChunk.unpack(d).load == lfowaves.RUNTIME_VA)
    at = copy - code.load
    assert code.image[at:at + 10] == bytes.fromhex("202f00080c800000014b")


def test_no_two_of_the_three_overlap(firmware):
    from dnfw.mods import bootscreen, lfo4, lfowaves
    named = [(m.ID, list(m.extents(firmware)) + m.ram()) for m in (lfo4, lfowaves, bootscreen)]
    assert check_compatible(named) == []


@pytest.mark.parametrize("order", [["lfowaves"], ["bootscreen"], ["lfowaves", "bootscreen", "lfo4"]])
def test_changes_nothing_outside_the_declared_extents(firmware, stock, order):
    from dnfw.mods import bootscreen, lfo4, lfowaves
    mods = {"lfo4": lfo4, "lfowaves": lfowaves, "bootscreen": bootscreen}
    out = _apply(firmware, order)
    allowed = [x for m in order for x in mods[m].extents(firmware)]
    for i, (a, b) in enumerate(zip(stock, out)):
        if a != b:
            assert any(x.start <= i < x.end for x in allowed), hex(BASE + i)

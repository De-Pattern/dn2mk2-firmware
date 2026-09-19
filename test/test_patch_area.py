"""The appended area's layout, the CODE chunk, and the startup loader's fit."""

import pytest

from dnfw.mods import bootscreen
from dnfw.patch import area, cbuild, loader


def test_same_bytes_as_the_boot_screen_builds():
    chunks = [(b"BOOT", bytes(range(37))), (b"ANIM", b"\x01" * 8)]
    assert area.build(chunks) == bootscreen.area(chunks)


def test_round_trip_and_runtime_address():
    code = area.CodeChunk(0x46800000, b"\x4e\x75", bss=6, init=0x46800000)
    blob = area.build([(b"BOOT", b"xyz"), (area.CODE, code.pack())])
    (_, boot), (cid, packed) = area.parse(blob)
    assert boot == b"xyz" and cid == area.CODE
    back = area.CodeChunk.unpack(packed)
    assert (back.load, back.image, back.bss, back.init) == (0x46800000, b"\x4e\x75\x00\x00", 8, 0x46800000)
    assert area.runtime_address(blob, b"BOOT") == area.RUNTIME_VA + 36


def test_code_chunk_refuses_bad_addresses():
    with pytest.raises(area.AreaError):
        area.CodeChunk(0x46800002, b"\x4e\x75").pack()
    with pytest.raises(area.AreaError):
        area.CodeChunk(0x46800000, b"\x4e\x75", init=0x46900000).pack()


@pytest.mark.skipif(not cbuild.available(), reason="no m68k GCC")
def test_loader_fits_its_cave():
    linked = loader.build()
    assert linked["dnfw_boot"] == loader.LINK_VA
    assert len(linked.image) <= loader.CAVE_VA + loader.CAVE_CAP - loader.LINK_VA

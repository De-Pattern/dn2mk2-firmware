"""The USB probe: the host codec, the mod's data, and what it writes to stock 1.11.

derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

The behaviour on the ColdFire is `scripts/emu_usbprobe.py`'s (the router called
with real messages, the reply captured at the stock sender); this checks what
can be checked without the emulator.
"""

import pathlib
import struct
import sys

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import usbprobe

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dn2probe  # noqa: E402

RES = next((d / "00_Resources" for d in (ROOT, *ROOT.parents) if (d / "00_Resources").is_dir()),
           ROOT / "00_Resources")
STOCK_111 = RES / "00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
BASE = usbprobe.BASE


def test_codec_selftest():
    dn2probe.selftest()


def test_pack7_round_trip():
    data = bytes(range(256)) * 3
    assert dn2probe.unpack7(dn2probe.pack7(data)) == data
    assert all(b < 0x80 for b in dn2probe.pack7(data))


def test_device_byte_is_above_the_routers_table():
    # the DN2 router routes 0x00..0x17 only (0x401216c4); DNX uses 0x15 and 0x10
    assert dn2probe.HEADER == bytes([0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x00])


def test_the_host_allow_list_is_the_probes():
    assert dn2probe.PEEK_RANGES == ((0x40000000, 0x48000000), (0x80000000, 0x80010000),
                                    (0x4E6DF100, 0x4E6E1100))


def test_spec_is_two_caves_and_four_jsr_hooks():
    """The code cave, STATS layout 2's cave (ext.S), and four hooks into the first."""
    edits = usbprobe.SPEC["edits"]
    assert len(edits) == 6
    cave, cave2 = edits[0], edits[1]
    assert cave["va"] == usbprobe.SPEC["cave"]["va"] and len(cave["new"]) // 2 <= 896
    assert cave2["va"] == usbprobe.SPEC["cave2"]["va"] == 0x402D0668
    assert cave2["va"] + len(cave2["new"]) // 2 <= 0x402D08B8     # 4 B short of arpmodes' cave guard
    assert set(bytes.fromhex(cave["stock"])) == {0} == set(bytes.fromhex(cave2["stock"]))
    for e in edits[2:]:
        new = bytes.fromhex(e["new"])
        assert len(new) == 6 == len(bytes.fromhex(e["stock"])) and new[:2] == b"\x4e\xb9"
        target = struct.unpack(">I", new[2:])[0]
        assert cave["va"] <= target < cave["va"] + len(cave["new"]) // 2


def test_extents_do_not_overlap_each_other():
    assert check_compatible([(f"e{i}", [x]) for i, x in enumerate(usbprobe.extents())]) == []


def test_tag_is_bounded():
    assert usbprobe.tag_bytes("usbprobe")[:9] == b"usbprobe\0"
    for bad in ("", "x" * usbprobe.SPEC["tag"]["length"], "café"):
        with pytest.raises((ModError, UnicodeEncodeError)):
            usbprobe.tag_bytes(bad)


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


def test_applies_to_stock_and_writes_only_its_extents(dn2_111):
    stock = dn2_111.container.find(3).unpack()
    out = usbprobe.apply(dn2_111, tag="t1").payloads[3]
    assert len(out) == len(stock)
    allowed = set()
    for e in usbprobe.extents():
        allowed |= set(range(e.start, e.end))
    changed = {i for i in range(len(stock)) if stock[i] != out[i]}
    assert changed and changed <= allowed
    at = usbprobe.SPEC["tag"]["va"] - BASE
    assert out[at:at + 3] == b"t1\0"

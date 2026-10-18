"""The preflight refuses what could cost the instrument its way back.

Each refusal is shown against a build that is otherwise well formed and
correctly signed, so `verify` alone would pass it: that is the gap the
preflight closes. The control is the Waverider build, which must pass.
"""

import pathlib

import pytest

from dnfw import safety
from dnfw.cli.files import read_image
from dnfw.firmware.build import build as rebuild
from dnfw.firmware.build import replacement
from dnfw.firmware.load import load
from dnfw.firmware.verify import verify

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def stock():
    if not STOCK.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    return load(read_image(STOCK))


def _ok(checks):
    return all(c.ok for c in checks)


def _failed(checks):
    return [c.name for c in checks if not c.ok]


def _with_section(stock, sid, content):
    out = rebuild(stock, {sid: replacement(stock, sid, content)})
    assert verify(load(out)).ok, "the tampered image must still verify, or the test proves nothing"
    return out


def test_stock_passes(stock):
    assert _ok(safety.preflight(stock, read_image(STOCK)))


def test_waverider_passes(stock):
    from dnfw.cli import main
    out = ROOT / "out/safety/waverider.syx"
    out.parent.mkdir(parents=True, exist_ok=True)
    assert main.main(["mods", "apply", str(STOCK), "--mod", "waverider", "-o", str(out)]) == 0
    assert _ok(safety.preflight(stock, out.read_bytes()))


def test_a_changed_bootstrap_is_refused(stock):
    boot = bytearray(stock.container.find(2).unpack())
    boot[-1] ^= 0xFF                                   # one byte, in padding-free code
    failed = _failed(safety.build_checks(stock, _with_section(stock, 2, bytes(boot))))
    assert any("section 2" in n for n in failed)


def test_a_changed_updater_is_refused(stock):
    upd = bytearray(stock.container.find(4).raw_payload)
    upd[100] ^= 0x01
    failed = _failed(safety.build_checks(stock, _with_section(stock, 4, bytes(upd))))
    assert any("section 4" in n for n in failed)


def test_an_oversized_dsp_program_is_refused(stock):
    dsp = stock.container.find(7).unpack()
    big = dsp + bytes(safety.SHARC_MAX_UNPACKED - len(dsp) + 1)   # one byte over
    failed = _failed(safety.build_checks(stock, _with_section(stock, 7, big)))
    assert any("1 MiB" in n for n in failed)


def test_an_input_that_is_not_stock_is_refused(stock):
    main_os = bytearray(stock.container.find(3).unpack())
    main_os[0x1000] ^= 0x01
    modified = load(_with_section(stock, 3, bytes(main_os)))
    assert any("input section 3" in n for n in _failed(safety.stock_checks(modified)))


def test_usb_upgrade_buffer_bound():
    # 101 decoded bytes a 0x7E data packet; the OS's USB receiver has 0x200000 of room
    pkt = bytes([0xF0, 0, 0x20, 0x3C, 0x15, 0, 0x7E]) + bytes(120) + b"\xf7"
    start = bytes([0xF0, 0, 0x20, 0x3C, 0x15, 0, 0x7F]) + bytes(8) + b"\xf7"
    fits = 0x200000 // safety.USB_PACKET_BYTES
    assert safety.usb_upgrade_bytes(start + pkt * fits + start) == fits * 101 <= 0x200000
    assert safety.usb_upgrade_bytes(pkt * (fits + 1)) > safety.USB_UPGRADE_BUFFER

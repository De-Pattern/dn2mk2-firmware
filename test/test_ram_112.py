"""On OS 1.12 every chunk the build places in RAM lies above stock's uncached buffers, and apart.

1.12 moved stock's uncached (0x4e...) buffers +0x8000 (docs/os112-port.md): the +Drive bounce
buffer is 64 KiB from 0x4e6f9300, the alias of 0x466f9300, so it reaches 0x46709300. Stock's read
goes through it whenever its destination is unaligned, so whatever lies under it is overwritten by
the SD reads at power-on. The boot-screen stamp sat at 0x46708000 and crashed a unit there
(EXCEPTION, vector 0x0B, PC 0x46708000, 2026-11-16). The emulator's eSDHC never takes that path,
so no boot under it can show this: this file holds the layout to it instead.

The highest 0x4e alias operand in stock 1.12 MAIN OS's buffer block is 0x4e70a018 (measured,
2026-11-16); nothing of ours may start below CLEAR_FROM.
"""

import pathlib
import struct

import pytest

from dnfw.mods import RAM, bootscreen, waverider
from dnfw.waverider import coldfire as CF
from dnfw.waverider import pages

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_112 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.12_dist.zip"

BOUNCE, BOUNCE_BYTES = 0x4E6F9300, 0x10000           # stock 1.12's +Drive bounce buffer, uncached
ALIAS = 0x08000000                                   # 0x4e... is the uncached alias of 0x46...
CLEAR_FROM = 0x4670B000                              # above 0x4670a018, the block's last operand


def _ram():
    return [e for e in waverider.ram() if e.section == RAM]


def test_every_chunk_is_above_stocks_uncached_buffers():
    low = [str(e) for e in _ram() if e.start < CLEAR_FROM]
    assert not low, f"under stock 1.12's uncached buffers (below {CLEAR_FROM:#010x}): {low}"


def test_the_bounce_buffer_ends_below_clear_from():
    assert BOUNCE - ALIAS + BOUNCE_BYTES <= CLEAR_FROM


def test_no_two_chunks_overlap():
    ext = sorted(_ram(), key=lambda e: e.start)
    for a, b in zip(ext, ext[1:]):
        assert a.end <= b.start, f"{a} and {b} overlap"


def test_the_stamp_is_in_its_own_room_above_the_pages():
    stamp = bootscreen.ram()[0]
    assert stamp.start == CF.PAGES_END
    assert stamp.end <= CF.PAGES_END + 0x1000 <= CF.MCHUNK
    assert pages.LOAD < CF.PAGES_END


def test_stock_112_holds_the_bounce_buffer_where_measured():
    if not STOCK_112.exists():
        pytest.skip("Digitone II 1.12 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    main = load(read_image(STOCK_112)).container.find(3).unpack()
    assert struct.pack(">I", BOUNCE) in main
    assert struct.pack(">I", BOUNCE - 0x8000) not in main      # 1.11's place: not 1.12's

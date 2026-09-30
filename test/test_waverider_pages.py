"""Waverider's own SYN pages (M7) and its waveform display (M8): the committed code
spec, the hooks it installs, and the display's copy of the tables."""

from __future__ import annotations

import json
import pathlib
import struct

from dnfw.waverider import coldfire as CF
from dnfw.waverider import dsp, pages, wave

SPEC = json.loads((pathlib.Path(__file__).parents[1] / "src/dnfw/mods/waverider_code.json").read_text())
CHUNK = bytes.fromhex(SPEC["chunk"]["code"])


def edit(va: int) -> bytes:
    (e,) = [e for e in SPEC["edits"] if e["va"] == va]
    return bytes.fromhex(e["new"])


def jsr_target(code: bytes) -> int:
    assert code[:2] == bytes.fromhex("4eb9")
    return struct.unpack(">I", code[2:6])[0]


def in_chunk(va: int) -> bool:
    return pages.LOAD <= va < pages.LOAD + len(CHUNK)


def test_the_chunk_runs_from_its_load_address():
    assert SPEC["chunk"]["load"] == pages.LOAD
    assert len(CHUNK) < 0x4000     # clear of the platform runtime at 0x46710000


def test_every_m7_site_calls_into_the_chunk():
    for site in (CF.COUNT_SITE, CF.PAGE_SITE, CF.LABEL_SITE, CF.ICON_SITE):
        assert in_chunk(jsr_target(edit(site))), hex(site)


def test_the_icon_site_is_a_call_and_a_nop():
    # a bne.s cannot reach the stock target (0xa0 is -96 as a byte); the routine
    # moves its own return address instead, so the displaced bne is a nop
    assert len(edit(CF.ICON_SITE)) == len(CF.ICON_STOCK) == 8
    assert edit(CF.ICON_SITE)[6:] == bytes.fromhex("4e71")


def test_the_descriptors_name_the_owners_layout():
    ids = struct.pack(">8I", *pages.PAGES[0])
    assert ids in CHUNK
    assert struct.pack(">8I", *pages.PAGES[1]) in CHUNK


def test_the_strings_carry_an_unshareable_header():
    for text in (pages.SUBTITLE, *pages.TITLES):
        raw = text.encode() + b"\0"
        at = CHUNK.find(raw)
        assert at >= 12, text
        assert struct.unpack(">IIi", CHUNK[at - 12:at]) == (len(text), len(text), -1)


def test_the_spans_are_the_tables_the_sharc_plays():
    got = wave.spans()
    assert len(got) == len(dsp.tables()) == wave.TABLES
    for table in got:
        assert len(table) == wave.FRAMES
        for lo, hi in table:
            assert len(lo) == len(hi) == wave.WIDTH
            assert all(-127 <= a <= b <= 127 for a, b in zip(lo, hi))


def test_the_16th_partial_is_a_band_not_a_line():
    # point samples landed on its zero crossings and drew a flat line
    lo, hi = wave.spans()[1][15]
    assert max(lo) < -100 and min(hi) > 100


def test_the_fundamental_is_one_cycle():
    lo, hi = wave.spans()[1][0]
    mids = [(a + b) / 2 for a, b in zip(lo, hi)]
    assert max(mids[:8]) > 90 and min(mids[8:]) < -90


def test_the_display_data_is_in_the_chunk():
    data = bytes(v & 0xFF for table in wave.spans() for lo, hi in table for v in lo + hi)
    assert data in CHUNK

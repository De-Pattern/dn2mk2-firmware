"""dnfw.waverider.dsp / live / harmonics: Milestone 5's section-7 builder and its contract.

The runner gate is scripts/sharc_waverider_m5.py; these need no runner, no WSL and
no firmware beyond the DN2 1.11 image (skipped cleanly when it is absent).
"""

from __future__ import annotations

import cmath
import hashlib
import json
import math
import pathlib
import struct

import pytest

from dnfw.image import bootstream
from dnfw.waverider import dsp, harmonics, live, reduce, render, testtable

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = ROOT / "00_Resources" / "00_Firmware" / "Digitone_II_OS1.11_dist.zip"
SHARC = ROOT / "csrc" / "waverider" / "sharc"


@pytest.fixture(scope="module")
def stock7() -> bytes:
    if not IMAGE.exists():
        pytest.skip(f"{IMAGE.name} not present")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    sec = load(read_image(IMAGE)).container.find(7)
    return sec.unpack() or sec.raw_payload


@pytest.fixture(scope="module")
def built(stock7) -> bytes:
    return dsp.section7(stock7)


# -- the committed objects -----------------------------------------------------------------

def test_committed_objects_match_their_sources():
    spec = json.loads(dsp.CODE.read_text(encoding="utf-8"))
    for key, name in (("reader", "reader_m5"), ("machine5_live", "machine5_live")):
        src = (SHARC / f"{name}.asm").read_bytes().replace(b"\r\n", b"\n")
        assert spec[key]["source_sha256"] == hashlib.sha256(src).hexdigest(), name
        csrc = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
        assert csrc["object_parcels_be"] == spec[key]["object_parcels_be"], name
    assert spec["entry_jump"]["source"] == "JUMP 0x180200;"


def test_our_sources_avoid_dag1_m0_m3_in_memory_accesses():
    """No DM(..M0..M3..) access and no pre-modify read outside a DO loop (the two
    forms selas and selmap disagree on; docs/waverider-m5-dsp.md)."""
    import re
    for name in ("reader_m5", "machine5_live"):
        in_loop = False
        for line in (SHARC / f"{name}.asm").read_text().splitlines():
            code = line.split("//", 1)[0].strip().upper()
            if "DO " in code and "UNTIL" in code:
                in_loop = True
            assert not re.search(r"DM\s*\([^)]*\bM[0-3]\b", code), (name, line)
            # the one exception is the firmware's own return idiom, byte for byte
            # its `i12=dm(m7,i6)` (3b fe4d3f0e)
            if re.search(r"DM\s*\(\s*M\d+\s*,", code) and code != "I12 = DM(M7, I6);":
                assert in_loop, (name, line)
            if code.startswith(".WR5_LOOP_END"):
                in_loop = False


# -- the builder ------------------------------------------------------------------------------

def test_refuses_anything_but_stock(stock7):
    with pytest.raises(dsp.DspError):
        dsp.section7(stock7[:100] + bytes([stock7[100] ^ 1]) + stock7[101:])


def test_is_deterministic_and_walks(stock7, built):
    assert dsp.section7(stock7) == built
    w = bootstream.walk(built)
    assert w.complete and w.stopped_at == len(built)


def test_every_added_span_is_in_block_2_below_its_top_16k_and_outside_every_stock_block(stock7):
    stock_blocks = [b for b in bootstream.walk(stock7).blocks if b.count]
    for what, at, payload in dsp.spans():
        lo, hi = at - dsp.LOAD_ALIAS, at - dsp.LOAD_ALIAS + len(payload)
        assert 0x300000 <= lo and hi <= 0x31C000, what
        for b in stock_blocks:
            assert not (b.target < at + len(payload) and at < b.target + b.count), what


def test_loaded_image_holds_our_bytes(built):
    for what, at, payload in dsp.spans():
        assert bootstream.read_span(built, at, len(payload)) == payload, what


def test_the_two_patches_and_nothing_else_in_the_stock_blocks(stock7, built):
    entry = bootstream.read_span(built, dsp.sw_to_load(dsp.ENTRY_SW), 8)
    assert entry == bytes.fromhex("3e06180000020100")          # jump 0x180200 ; nop
    lookup = struct.unpack("<8I", bootstream.read_span(built, dsp.dm_to_load(dsp.LOOKUP_DM), 32))
    assert lookup == (0, 1, 2, 3, 4, 5, 0, 0)
    # the clamp min(R2, 4) stays stock: its R0 = 0x4 parcel pair at sw 0x1c294a
    clamp = dsp.sw_to_load(0x1C294A)
    assert bootstream.read_span(built, clamp, 4) == bootstream.read_span(stock7, clamp, 4) \
        == bytes.fromhex("800f0400")
    # the per-type setup table is not touched
    assert bootstream.read_span(built, 0x8052DB90, 24) == bootstream.read_span(stock7, 0x8052DB90, 24)
    # every stock block's payload differs from stock only at the two patches
    final = bootstream.walk(stock7).final
    head = built[:final.offset]
    diff = [k for k in range(final.offset) if head[k] != stock7[k]]
    entry_off = bootstream.spans(stock7, dsp.sw_to_load(dsp.ENTRY_SW), 8)[0][0]
    look_off = bootstream.spans(stock7, dsp.dm_to_load(dsp.LOOKUP_DM + 20), 4)[0][0]
    allowed = set(range(entry_off, entry_off + 8)) | set(range(look_off, look_off + 4))
    assert diff and set(diff) <= allowed


def test_directory_names_both_tables():
    d = dsp.directory()
    assert struct.unpack("<4I", d) == (0x57525431, 2, 0x302000, 0x306000)


# -- the contract -------------------------------------------------------------------------------

def test_increment_table_is_equal_tempered_at_48k():
    t = live.increment_table()
    assert len(t) == 129
    assert t[69] == pytest.approx(440 / 48000 * 2 ** 32, rel=1e-7)
    assert all(b > a for a, b in zip(t, t[1:]))
    assert t[128] < 2 ** 31                                    # TRUNC stays in range
    assert live.table_bytes() == struct.pack("<129f", *t)


def test_increment_follows_the_note():
    assert live.increment(72.0) == 2 * live.increment(60.0)
    assert live.increment(-5.0) == live.increment(0.0)         # clamped
    assert live.increment(200.0) == live.increment(127.0)
    lo, mid, hi = live.increment(60.0), live.increment(60.5), live.increment(61.0)
    assert lo < mid < hi


def test_position_and_slot_from_frame_words():
    assert live.position(0) == 0
    assert live.position(0x7800) == 15 << 16
    assert live.position(0x7F00) == 15 << 16                   # clamped
    assert live.position(0x4000) == 0x4000 << 5
    assert live.slot(0x0000, 2) == 0 and live.slot(0x0100, 2) == 1
    assert live.slot(0x0200, 2) == 0                           # out of range -> 0


def test_render_blocks_carries_phase_across_a_slot_change():
    tables = dsp.tables()
    a, ph = live.render_blocks(tables, [(60.0, 0, 0)], 32)
    b, _ = live.render_blocks(tables, [(60.0, 0, 0x100)], 32, ph)
    both, _ = live.render_blocks(tables, [(60.0, 0, 0), (60.0, 0, 0x100)], 32)
    assert both == a + b


# -- the tables -----------------------------------------------------------------------------------

def _partial(frame, h):
    n = len(frame)
    return abs(sum(v * cmath.exp(-2j * math.pi * h * k / n) for k, v in enumerate(frame))) / n


def test_slot0_is_the_saw_at_pos0_and_the_sine_at_pos15():
    t0 = dsp.tables()[0]
    assert t0 == list(reversed(testtable.table()))
    assert _partial(t0[0], 2) > 0.2 * _partial(t0[0], 1)       # bright: harmonics present
    assert _partial(t0[15], 2) < 1e-3 * _partial(t0[15], 1)    # pure sine


def test_harmonics_frame_k_is_partial_k_plus_1():
    t = harmonics.table()
    assert len(t) == reduce.FRAMES and all(len(f) == reduce.POINTS for f in t)
    for k in (0, 1, 7, 15):
        strongest = max(range(1, 20), key=lambda h: _partial(t[k], h))
        assert strongest == k + 1


def test_tables_are_original_and_distinct():
    t0, t1 = dsp.tables()
    assert t0 != t1
    assert render.dsp_bytes(t0) != render.dsp_bytes(t1)

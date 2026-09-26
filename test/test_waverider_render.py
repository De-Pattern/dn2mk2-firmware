"""Waverider Milestone 1, the host half: the reference reader the SHARC code is held to.

The SHARC half is checked by running it (`scripts/sharc_waverider_render.py`,
which needs digikit's SHARC runner); this checks the reference itself, with no
firmware and no external tool.
"""

from __future__ import annotations

import math
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import render, testtable  # noqa: E402

TABLE = testtable.table()
HALF = 1 << 22                     # half a sample of phase


def ramp_table():
    """16 frames; frame f, sample i = 64*i - 16384 + 1000*f: linear everywhere but the wrap."""
    return [[64 * i - 16384 + 1000 * f for i in range(512)] for f in range(16)]


def test_on_a_sample_the_reader_returns_that_sample():
    for k in (0, 1, 255, 510, 511):
        out, _ = render.render(TABLE, k << 23, 0, 3 << 16, 1)
        assert out[0] == TABLE[3][k] / 32768


def test_halfway_between_samples_is_their_mean():
    out, _ = render.render(TABLE, (100 << 23) + HALF, 0, 0, 1)
    assert out[0] == pytest.approx((TABLE[0][100] + TABLE[0][101]) / 2 / 32768, abs=1e-12)


def test_between_samples_wraps_511_to_0():
    out, _ = render.render(TABLE, (511 << 23) + HALF, 0, 9 << 16, 1)
    assert out[0] == pytest.approx((TABLE[9][511] + TABLE[9][0]) / 2 / 32768, abs=1e-12)


def test_between_frames_is_linear():
    t = ramp_table()
    for frac in (0, 0x4000, 0x8000, 0xC000):
        out, _ = render.render(t, 200 << 23, 0, (4 << 16) + frac, 1)
        want = (64 * 200 - 16384 + 1000 * (4 + frac / 65536)) / 32768
        assert out[0] == pytest.approx(want, abs=1e-12)


def test_frame_15_interpolates_with_itself():
    out, _ = render.render(TABLE, 17 << 23, 0, 15 << 16, 1)
    assert out[0] == TABLE[15][17] / 32768
    with pytest.raises(ValueError):
        render.render(TABLE, 0, 0, (15 << 16) + 1, 1)


def test_phase_advances_and_wraps_mod_2_32():
    out, phase = render.render(TABLE, 0xFFFFFF00, 0x200, 0, 3)
    assert phase == (0xFFFFFF00 + 3 * 0x200) & 0xFFFFFFFF
    assert len(out) == 3


def test_blocks_carry_the_phase():
    inc = render.increment(440.0)
    whole, _ = render.render(TABLE, 0, inc, 5 << 16, 96)
    blocks = render.render_blocks(TABLE, inc, [5 << 16] * 3, 32)
    assert blocks == whole


def test_float32_stays_within_a_few_ulp_of_ideal():
    inc = render.increment(1234.5)
    ideal, _ = render.render(TABLE, 0x13579BDF, inc, 0x7ABCD, 512, "ideal")
    f32, _ = render.render(TABLE, 0x13579BDF, inc, 0x7ABCD, 512, "float32")
    assert max(abs(a - b) for a, b in zip(ideal, f32)) < 2e-7
    assert all(struct.unpack("<f", struct.pack("<f", v))[0] == v for v in f32)


def test_one_cycle_at_the_right_pitch():
    """100 Hz at 48 kHz is a 480-sample cycle: the sine frame repeats with it, and
    crosses zero upwards once a cycle (at 3/4 of it, starting a quarter in)."""
    inc = render.increment(100.0)
    out, _ = render.render(TABLE, 1 << 30, inc, 0, 960)      # start a quarter cycle in
    assert max(abs(out[n] - out[n + 480]) for n in range(480)) < 2e-3
    zero_ups = sum(1 for n in range(959) if out[n] < 0 <= out[n + 1])
    assert zero_ups == 2


def test_increment_and_position_ranges():
    assert render.increment(24000.0 - 1e-6) > 0
    with pytest.raises(ValueError):
        render.increment(24000.0)
    assert render.position(7.5) == (7 << 16) + 0x8000
    with pytest.raises(ValueError):
        render.position(15.5)


def test_sweep_goes_up_and_back():
    s = render.sweep(16, 5)
    assert s == [0, 15 << 15, 15 << 16, 15 << 15, 0]


def test_dsp_bytes_are_little_endian_even_sample_low():
    b = render.dsp_bytes(TABLE)
    assert len(b) == 16384
    word, = struct.unpack_from("<I", b, 4 * 37)            # frame 0, samples 74 and 75
    assert (word & 0xFFFF) == (TABLE[0][74] & 0xFFFF)
    assert (word >> 16) == (TABLE[0][75] & 0xFFFF)


def test_pcm16_clips_and_rounds():
    b = render.pcm16([0.0, 1.0, -1.5, 0.5 / 32768, -0.5 / 32768])
    assert struct.unpack("<5h", b) == (0, 32767, -32768, 1, -1)


def test_committed_reader_matches_its_source():
    """reader.json is selas output for reader.asm; a stale one would test old code."""
    import hashlib
    import json
    committed = json.loads((ROOT / "csrc/waverider/sharc/reader.json").read_text())
    src = (ROOT / committed["source"]).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(src).hexdigest() == committed["source_sha256"]
    offsets = committed["instruction_offsets"]
    assert offsets == sorted(offsets) and offsets[0] == 0
    assert offsets[-1] < len(bytes.fromhex(committed["object_parcels_be"]))
    assert math.gcd(*offsets) % 2 == 0

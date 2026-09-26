"""Waverider Milestone 0, the host half: the table, the bake, the expectation.

The firmware half is checked by running it (`scripts/emu_waverider_m0.py`);
this checks that what it is compared against is itself right.
"""

from __future__ import annotations

import math
import re
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dnfw.telemetry import gen  # noqa: E402
from dnfw.waverider import bake, expect, reduce, testtable  # noqa: E402

TABLE = testtable.table()


def test_geometry_is_16_by_512_int16():
    assert len(TABLE) == 16 and all(len(f) == 512 for f in TABLE)
    assert len(bake.to_bytes(TABLE)) == 16384
    assert max(v for f in TABLE for v in f) == 32767
    assert min(v for f in TABLE for v in f) >= -32768


def test_frame_zero_is_a_sine():
    """The formula says frame 0 is a pure sine: odd-symmetric about the cycle's middle."""
    f = TABLE[0]
    assert all(abs(f[i] + f[(i + 256) % 512]) <= 1 for i in range(512))


def test_box_of_2048_to_512_is_the_mean_of_four():
    src = [float(i % 7) for i in range(2048)]
    out = reduce.box(src, 512)
    assert all(math.isclose(out[j], sum(src[4 * j:4 * j + 4]) / 4) for j in range(512))


def test_checksum_is_order_sensitive():
    swapped = [TABLE[1], TABLE[0], *TABLE[2:]]
    assert bake.checksum(swapped) != bake.checksum(TABLE)


def test_header_carries_the_same_numbers():
    text = bake.header(TABLE, expect.PROBES, expect.SLICE)
    assert f"checksum {bake.checksum(TABLE):#06x}" in text
    assert "#define WR_WORDS      8192" in text
    body = text[text.index("#define WR_TABLE_INIT {") + len("#define WR_TABLE_INIT {"):]
    body = re.sub(r"/\*.*?\*/", " ", body[:body.index("}")])
    values = [int(tok) for tok in re.findall(r"-?\d+", body)]
    assert values == [v for f in TABLE for v in f]


def test_signals_exist_in_the_channel_map():
    names = {s["name"] for s in gen.load()["signals"]}
    assert set(expect.SIGNALS) <= names
    assert "probe_a" in names


def _capture(table, bursts, corrupt=None):
    """Simulate the firmware's output: the same algorithm as table.c, on the host."""
    words = bake.words(table)
    pairs, probe, at, run, total, passes = [], 0, 0, 0, 0, 0
    for _ in range(bursts):
        pairs.append(("probe_a", 99))
        f, i = expect.PROBES[probe]
        v = table[f][i] & 0xFFFF
        if corrupt == (f, i):
            v ^= 1
        probe = (probe + 1) % len(expect.PROBES)
        if at == 0:
            run = 0
        for w in words[at:at + expect.SLICE]:
            run = (run * bake.MULT + w) & 0xFFFF
        at += expect.SLICE
        if at >= len(words):
            total, passes, at = run, passes + 1, 0
        lo, mid, hi = expect.split16(v)
        slo, smid, shi = expect.split16(total)
        pairs += [("wr_frame", f), ("wr_idx_lo", i & 0x7F), ("wr_idx_hi", i >> 7),
                  ("wr_val_lo", lo), ("wr_val_mid", mid), ("wr_val_hi", hi),
                  ("wr_sum_lo", slo), ("wr_sum_mid", smid), ("wr_sum_hi", shi),
                  ("wr_passes", passes & 0x7F)]
    return pairs


def test_a_faithful_capture_passes():
    ok, lines = expect.verify(_capture(TABLE, 16), TABLE)
    assert ok, lines


def test_one_wrong_bit_fails_and_is_named():
    ok, lines = expect.verify(_capture(TABLE, 16, corrupt=expect.PROBES[3]), TABLE)
    assert not ok
    assert any("frame 7 index 255" in line for line in lines)


def test_a_short_capture_says_the_checksum_never_completed():
    ok, lines = expect.verify(_capture(TABLE, 4), TABLE)
    assert not ok
    assert any("wr_passes stayed 0" in line for line in lines)


def test_parse_reads_midi_watch_lines():
    text = "   12.345  ch16 CC41  (wr_frame)             = 3\n   ch1  CC41  = 9\n"
    assert expect.parse(text) == [("wr_frame", 3)]


def _wav(frames, rate=48000, float32=True, channels=1, clm=None):
    """A WAV in memory: float32 or PCM16, frames concatenated."""
    import struct
    flat = [v for f in frames for v in f]
    if float32:
        data, tag, bits = b"".join(struct.pack("<f", v) for v in flat for _ in range(channels)), 3, 32
    else:
        data, tag, bits = b"".join(struct.pack("<h", int(v * 32767)) for v in flat
                                   for _ in range(channels)), 1, 16
    fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * channels * bits // 8,
                      channels * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if clm:
        text = f"<!>{clm} 00000000 waverider-test".encode()
        body += b"clm " + struct.pack("<I", len(text)) + text + b"\0" * (len(text) & 1)
    body += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_a_float32_wav_of_the_generator_bakes_to_the_same_table():
    """The WAV path and the generator path agree, to float32's rounding."""
    from dnfw.waverider import source
    data = _wav(testtable.source_frames())
    i = source.info(data)
    assert (i["ok"], i["encoding"], i["frames"], i["frame"], i["rate"]) == \
        (True, "float 32-bit", 16, 2048, 48000)
    assert i["warnings"] == []
    got = reduce.from_wav(data)
    assert max(abs(a - b) for fa, fb in zip(got, TABLE) for a, b in zip(fa, fb)) <= 1


def test_scan_flags_what_it_changes():
    from dnfw.waverider import source
    odd = [[math.sin(2 * math.pi * n / 256) for n in range(256)]] * 3
    i = source.info(_wav(odd, rate=44100, float32=False, channels=2))
    assert i["ok"] and i["frames"] == 1 and i["origin"] == "whole file"
    assert any("ONE frame" in w for w in i["warnings"])
    assert any("only the first" in w for w in i["warnings"])
    j = source.info(_wav(odd, clm=256))
    assert (j["frame"], j["frames"], j["origin"]) == (256, 3, "clm chunk")
    assert any("interpolated up to 16" in w for w in j["warnings"])

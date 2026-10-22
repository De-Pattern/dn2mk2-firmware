"""The sample machines' model (dnfw.sampler): the pool, the sample link's packets, the
machines' timing; and the host tool's codec (tools/dn2samples.py). The SHARC runner
(scripts/sharc_waverider_m5.py, steps 3b and 3c) holds the assembled code to this model."""

from __future__ import annotations

import math
import pathlib
import struct
import sys
import wave

import pytest

from dnfw.perc import machines as PM
from dnfw.perc.dsl import Mem
from dnfw.sampler import live as SL
from dnfw.sampler import machines as SM
from dnfw.sampler import program as P

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))


def _tempo(h, bpm):
    a = PM.FRAME + P.TEMPO_OFFSET
    w = h.mem.get(a & ~3)
    h.mem.put(a & ~3, (w & 0xFFFF0000) | int(bpm * 120))


def _play(mtype, recs, blocks, bpm=120.0, note=60.0):
    h = SL.Harness(0)
    h.defaults()
    for r, v in recs.items():
        h.set(r, v)
    _tempo(h, bpm)
    out = []
    for b in range(blocks):
        out += h.block(mtype, note, b == 1)
    return out


def _span(out):
    nz = [i for i, x in enumerate(out) if abs(x) > 1e-6]
    return (nz[-1] - nz[0] + 1) / 48000.0 if nz else 0.0


def test_the_pool_layout():
    pool = SL.pool_bytes(SL.test_samples(), 0x84000000, SL.test_rates(), SL.test_fmts(), SL.TEST_NAMES)
    magic, count = struct.unpack_from("<II", pool)
    assert (magic, count) == (SM.POOL_MAGIC, 4)
    for k, snd in enumerate(SL.test_samples()):
        addr, frames, rate, fmt = struct.unpack_from("<IIfI", pool, 8 + 16 * k)
        assert frames == len(snd) and fmt == SM.FMT_I16 and addr % 64 == 0
        assert addr - 0x84000000 >= SM.DATA_OFFSET
        assert pool[SM.NAMES_OFFSET + 8 * k:SM.NAMES_OFFSET + 8 * k + 8].rstrip(b"\0").decode() == SL.TEST_NAMES[k]
    assert SM.NAMES_OFFSET + 8 * SM.POOL_SLOTS <= SM.DATA_OFFSET


def test_oneshot_plays_the_int16_kick_exactly():
    out = _play(SM.TYPE_OF["ONESHOT"], {}, 20)
    q = [max(-32768, min(32767, round(x * 32768))) / 32768 for x in SL.test_samples()[0]]
    exp = [q[k // 2] if k % 2 == 0 else 0.5 * (q[k // 2] + q[k // 2 + 1]) for k in range(500)]
    assert max(abs(a - b) for a, b in zip(out[32:532], exp)) < 1e-6


@pytest.mark.parametrize("name", ["REPITCH", "STRETCH", "WERP"])
def test_the_time_machines_last_bars_at_the_tempo(name):
    # 1/8 bar (BARS 0) at 120 BPM: 0.25 s; at 60 BPM, 0.5 s
    samp = 4 if name == "WERP" else 1
    for bpm, want in ((120.0, 0.25), (60.0, 0.5)):
        out = _play(SM.TYPE_OF[name], {SM.BARS_REC: 0, SM.SAMP_REC: samp}, int(want * 1500) + 60, bpm)
        assert abs(_span(out) - want) < 0.03, (name, bpm, _span(out))
        assert all(math.isfinite(x) and abs(x) <= 2.0 for x in out)


def test_stretch_keeps_the_pitch_repitch_does_not():
    # the kick stretched to 1 bar: STRETCH's first 20 ms keep its zero-crossing rate,
    # REPITCH's (slowed down 8x) do not
    zc = lambda s: sum(1 for a, b in zip(s, s[1:]) if (a < 0) != (b < 0))
    one = _play(SM.TYPE_OF["ONESHOT"], {SM.SAMP_REC: 3}, 40)[32:32 + 960]
    st = _play(SM.TYPE_OF["STRETCH"], {SM.SAMP_REC: 3, SM.BARS_REC: 26}, 40)[32:32 + 960]
    rp = _play(SM.TYPE_OF["REPITCH"], {SM.SAMP_REC: 3, SM.BARS_REC: 26}, 40)[32:32 + 960]
    assert abs(zc(st) - zc(one)) <= 0.25 * zc(one)
    assert zc(rp) < 0.5 * zc(one)


def _frame_mem(halves):
    words = {}
    mem = Mem(lambda a: words.get(a, 0))
    for k, h in enumerate(halves):
        a = PM.FRAME + SM.LINK_OFFSET + 2 * k
        w = mem.get(a & ~3)
        mem.put(a & ~3, (w & 0xFFFF) | (h << 16) if a & 2 else (w & 0xFFFF0000) | h)
    return mem


def test_the_mailbox_writes_good_packets_only():
    L = SL.layout()
    mem = _frame_mem(P.link_packet(100, [1, 2, 3, 0xDEADBEEF, 5, 6]))
    P.run_mailbox(L, mem)
    assert [mem.get(L.pool + 400 + 4 * j) for j in range(6)] == [1, 2, 3, 0xDEADBEEF, 5, 6]
    bad = P.link_packet(100, [9] * 6)
    bad[15] ^= 1
    mem = _frame_mem(bad)
    P.run_mailbox(L, mem)
    assert mem.get(L.pool + 400) == 0 and mem.get(L.C["mbn"]) == 0
    mem = _frame_mem(P.link_packet(SM.POOL_WORDS - 5, [7] * 6))
    P.run_mailbox(L, mem)
    assert mem.get(L.C["mbn"]) == 0
    mem = _frame_mem([0] * 16)                    # stock's words: nothing
    P.run_mailbox(L, mem)
    assert mem.get(L.C["mbn"]) == 0


def test_the_host_tool_codec_and_pool(tmp_path):
    import dn2samples as D
    req = D.request(0x1234, D.WRITE, struct.pack(">I", 4096) + bytes(range(256)))
    assert req[:6] == D.HEADER and req[-1] == 0xF7 and all(b < 0x80 for b in req[6:-1])
    body = D.unpack7(req[6:-1])
    assert body[:3] == bytes([0x12, 0x34, D.WRITE]) and body[3:7] == struct.pack(">I", 4096)
    assert body[7:] == bytes(range(256))
    p = tmp_path / "tone.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(44100)
        w.writeframes(b"".join(int(0.5 * 8388607 * math.sin(k / 10)).to_bytes(3, "little", signed=True) * 2
                               for k in range(4410)))
    pool, names, _ = D.build_pool([p])
    addr, frames, rate, fmt = struct.unpack_from("<IIfI", pool, 8)
    assert names == ["TONE"] and frames == 4410 and abs(rate - 44100 / 48000) < 1e-6 and fmt == SM.FMT_I16
    assert len(pool) <= SM.MIRROR_BYTES


def test_the_pages_follow_the_dt2_layout():
    # v0.15: A TUNE (or nothing), B PLAY, C empty or CFAD, D SAMP on every machine
    for name, page in SM.PAGES.items():
        assert page[1][0] == SM.PLAY_REC and page[3][0] == SM.SAMP_REC, name
        assert page[7][0] == SM.LEV_REC, name
        assert page[2][0] in (0, 260), name
    from dnfw.waverider import pages
    hdr = pages.smp_widgets_header()
    assert "#define W_SAMP" in hdr and "smp_test_wave[4][SMP_WAVE_W]" in hdr
    assert all(r in SM.WIDGETS for page in SM.PAGES.values() for r, _s, _l in page if r)


def test_the_drive_region_is_above_everything_the_dn2_uses():
    src = (pathlib.Path(__file__).resolve().parents[1] / "csrc/sampler/link.c").read_text()
    assert "#define STORE_SECTOR 0x600000u" in src
    assert "#define STORE_FLOOR 0x458000u" in src and "STORE_SECTOR >= STORE_FLOOR" in src
    assert 0x600000 * 512 >= 3 << 30 and (0x600000 + 1 + SM.MIRROR_BYTES // 512) * 512 < 4 << 30

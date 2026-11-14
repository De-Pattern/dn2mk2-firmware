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
from dnfw.perc.dsl import flt
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


DT2_MODELS = pathlib.Path(__file__).resolve().parents[2] / "dt2s117" / "research" / "tools"


@pytest.mark.skipif(not (DT2_MODELS / "models_reader.py").is_file(),
                    reason="the DT2 reader's reference model (outside the repository) is not here")
def test_oneshot_is_the_dt2s_reader():
    # v0.18: ONESHOT through the DT2's own reader -- its 6-tap interpolator at 96 kHz and
    # its decimator -- against the bit-exact model of the DT2's code (dt2-reader-exact.md,
    # outside the repository: it is derived from Elektron's firmware)
    sys.path.insert(0, str(DT2_MODELS))
    import models_reader as MR
    out = _play(SM.TYPE_OF["ONESHOT"], {}, 20)
    pcm = [max(-32768, min(32767, round(x * 32768))) for x in SL.test_samples()[0]]
    v = MR.Voice(pcm, 0, 0, len(pcm) << 31, 1 << 29, 0)          # 0.25 frames a 96 kHz tick
    ref = [0.0] * 32
    for _ in range(19):
        ref += [float(x) for x in MR.read_block(v, MR.load_polyphase())]
    # LEV 100 makes up the interpolator's gain (0.4045): the DT2's output times 1 / 0.4045
    g = struct.unpack("<f", P.tables_bytes()[-4:])[0]
    err = [abs(a - g * b) for a, b in zip(out, ref)]
    assert max(err) <= 2.0 ** -13 and sum(e < 1e-6 for e in err) >= 0.99 * len(err)


@pytest.mark.parametrize("name", ["REPITCH", "STRETCH", "WERP"])
def test_the_time_machines_last_bars_at_the_tempo(name):
    # 1 bar (BARS 0, v0.18: the DT2's 1, 2, 4, 8) at 480 BPM: 0.5 s; at 240 BPM, 1 s
    samp = 4 if name == "WERP" else 1
    for bpm, want in ((480.0, 0.5), (240.0, 1.0)):
        out = _play(SM.TYPE_OF[name], {SM.BARS_REC: 0, SM.SAMP_REC: samp}, int(want * 1500) + 60, bpm)
        # STRETCH (the DT2's): the head reaches the end at the pitch's speed between jumps,
        # so the region ends up to one grain (2048 samples, 43 ms) early
        # (by up to (pitch / T - 1) grains: the kick's pitch is 4 T here)
        tol = 0.03 + (3 * 2048 / 48000 if name == "STRETCH" else 0.0)
        assert abs(_span(out) - want) < tol, (name, bpm, _span(out))
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


def test_the_dsp_program_never_reads_the_frames_routing_words():
    # v0.20: the frame's words 2650..2681 are the DSP's per-track routing (stock's own,
    # docs/link-research.md); v0.14..v0.19 read packets from them there, and the ColdFire
    # wrote them. Nothing of ours names them now.
    text = P.program(SL.layout(), 0x1000)
    assert "mb0" not in text and not hasattr(P, "mailbox") and not hasattr(SM, "LINK_OFFSET")


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
    # v0.15: A TUNE (or nothing), B PLAY, C empty, D SAMP on every machine
    for name, page in SM.PAGES.items():
        assert page[1][0] == SM.PLAY_REC, name
        # v0.44: BOUNCE's D is BUF (its track's buffer), the rest D SAMP
        assert page[3][0] == (SM.BUF_REC if name == "FLEX" else SM.SAMP_REC), name
        assert page[7][0] == SM.LEV_REC, name
        assert page[2][0] == 0, name                 # the DT2: C is an empty box on every machine
    from dnfw.waverider import pages
    hdr = pages.smp_widgets_header()
    assert "#define W_SAMP" in hdr and "smp_test_wave[4][SMP_WAVE_W]" in hdr
    assert all(r in SM.WIDGETS for page in SM.PAGES.values() for r, _s, _l in page if r)


def test_the_drive_region_is_above_everything_the_dn2_uses():
    src = (pathlib.Path(__file__).resolve().parents[1] / "csrc/sampler/link.c").read_text()
    assert "#define STORE_SECTOR 0x600000u" in src
    assert "#define STORE_FLOOR 0x458000u" in src and "STORE_SECTOR >= STORE_FLOOR" in src
    assert 0x600000 * 512 >= 3 << 30 and (0x600000 + 1 + SM.POOL_BYTES // 512) * 512 < 4 << 30


def _check(h):
    st = h.status()
    return st[15] == (SM.LINK_SEED + sum(st[:15])) & 0xFFFF and st[0] & 0xFF00 == SM.STATUS_MAGIC


def test_the_recorder_records_and_plays_back():
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    sig = [0.5 * math.sin(2 * math.pi * 440 * k / 48000) for k in range(32 * 20)]
    h.block(ONE, recorder=True)
    assert _check(h) and h.status()[0] == SM.STATUS_MAGIC          # idle
    h.command(SM.CMD_NOW, src=0, dest=SM.REC_FIRST + 1, place=0x123)   # IN, SAMP 125
    for b in range(20):
        h.block(ONE, recorder=True, inp=sig[32 * b:32 * b + 32])
    st = h.status()
    assert _check(h) and st[0] == SM.STATUS_MAGIC | 2 and st[2] == 10 and st[1] == 1
    assert abs(st[3] / 32767 - 0.5) < 0.01                          # the peak, for the meter
    ent = h.L.pool + 8 + 16 * (SM.REC_FIRST + 1)
    assert h.mem.get(ent) == h.L.pool + SM.REC_OFFSET + 0x123 * 512
    assert h.mem.get(ent + 4) == 32 * 20 and h.mem.get(ent + 12) == SM.FMT_I16
    h.command(SM.CMD_STOP)
    h.block(ONE, recorder=True)
    assert h.status()[0] == SM.STATUS_MAGIC | 3 and h.mem.get(ent + 4) == 32 * 20
    h.set(SM.SAMP_REC, SM.REC_FIRST + 2)
    out = []
    for b in range(20):
        out += h.block(ONE, 60.0, b == 0)
    # v0.18: through the DT2's reader, a 440 Hz sine plays back at its level, a few samples
    # late (the interpolator and the decimator); the last two blocks fade out (the DT2's)
    best = min(max(abs(a - b) for a, b in zip(out[64 + d:-64], sig[64:len(out) - 64 - d]))
               for d in range(8))
    assert best < 0.03                       # (the all-pass delays by a fraction of a sample too)


def test_the_recorder_waits_for_its_threshold_and_stops_at_its_length():
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    h.command(SM.CMD_ARM, thres=0.5, frames=64)
    ent = h.L.pool + 8 + 16 * SM.REC_FIRST
    for b in range(5):
        h.block(ONE, recorder=True, inp=[0.1] * 32)
    assert h.mem.get(ent + 4) == 0 and h.status()[0] == SM.STATUS_MAGIC | 1
    for b in range(4):
        h.block(ONE, recorder=True, inp=[0.7] * 32)
    assert h.mem.get(ent + 4) == 64 and h.status()[0] == SM.STATUS_MAGIC | 3


def _take_frames(h, slot):
    ent = h.L.pool + 8 + 16 * slot
    fr, a, got = h.mem.get(ent + 4), h.mem.get(h.L.pool + 8 + 16 * slot), []
    for k in range(fr // 2):
        w = h.mem.get(a + 4 * k)
        got += [(v - 65536 if v >= 32768 else v) / 32768.0 for v in (w & 0xFFFF, w >> 16)]
    return fr, got


def _q(x):
    return max(-32768, min(32767, int(min(0.999969, max(-1.0, x)) * 32768.0))) / 32768.0


def _hum_hiss(k, ch=0):
    """an input with nothing played into it: DC, hiss and 50 Hz hum, about -45 dB"""
    return (0.0015 + 0.0012 * ((((k + 977 * ch) * 2654435761) >> 7 & 0xFFFF) / 32768.0 - 1.0)
            + 0.004 * math.sin(2 * math.pi * 50 * k / 48000))


def _tail(k, ch=0):
    """MAIN idle after a pattern: a low reverb/delay tail and dither, about -50 dB"""
    return (0.002 * math.exp(-k / 20000.0) * math.sin(2 * math.pi * (90 + 7 * ch) * k / 48000)
            + 0.0004 * ((((k + 31 * ch) * 40503) >> 3 & 0xFF) / 128.0 - 1.0))


def test_v039_the_links_commands_leave_a_take_whole():
    # paQ and the owner on v0.38: "it only records one step and leaves the rest blank" (MAIN
    # or a track; the take its full length, its sound only in its first fraction). v0.38's
    # count fix sends K_HEAD and its VERIFY at every take's start; the DSP took every new
    # command's words 2..4 as the recorder's source, channel and threshold, so VERIFY's
    # (0, 2, 0) moved the take to IN, R. A 2 s take of MAIN, with the link's every other
    # command while it records, is its source's from its first frame to its last
    h = SL.Harness(0)
    h.defaults()
    n = 3000                                                    # 2 s
    h.command(SM.CMD_NOW, src=1, chan=0, dest=5, place=0x100)
    traffic = {3: (SM.CMD_VERIFY, 0, 2), 500: (SM.CMD_VERIFY, SM.DATA_OFFSET // 4, 0x4000),
               1000: (SM.CMD_PREVIEW, P.PREVIEW_AT, 0x10000, 4800), 1002: (SM.CMD_PREVIEW, P.PREVIEW_AT, 0, 0),
               1500: (SM.CMD_SCAN, h.L.pool, 64), 2000: (SM.CMD_SEND, SM.DATA_OFFSET // 4, 0x100),
               2500: (SM.CMD_VERIFY, 0x10, 0x7FFF, 0x7FFF)}
    main = lambda k, ch: 0.6 * math.sin(2 * math.pi * (220 if ch == 0 else 330) * k / 48000)   # noqa: E731
    for b in range(n):
        if b in traffic:
            h.link(*traffic[b])
        x = 32 * b
        h.recorder(inp=([_hum_hiss(x + k) for k in range(32)], [0.0] * 32),
                   main=([main(x + k, 0) for k in range(32)], [main(x + k, 1) for k in range(32)]),
                   trk={3: ([0.5] * 32, [0.5] * 32)})
    fr, got = _take_frames(h, 5)
    want = [_q((main(k, 0) + main(k, 1)) * 0.5) for k in range(32 * n)]
    assert fr == 32 * n
    bad = [k for k, (a, b) in enumerate(zip(got, want)) if abs(a - b) > 2 / 32768]
    assert not bad, f"{len(bad)} frames wrong from {bad[0] / 48000:.3f} s"
    assert h.status()[0] == SM.STATUS_MAGIC | 2
    # and a track, MONO L, armed at a set THRES: still the track's after the link's commands
    h2 = SL.Harness(0)
    h2.defaults()
    g = SM.TRK_GAIN
    h2.command(SM.CMD_ARM, src=2 + 2, chan=1, thres=0.5, dest=6)
    for b in range(200):
        if b in (2, 3, 100):
            h2.link(SM.CMD_VERIFY, 0, 2)
        on = b >= 20
        lv = [0.7 * g * math.cos(2 * math.pi * 300 * (32 * b + k - 640) / 48000) * on for k in range(32)]
        h2.recorder(inp=([_hum_hiss(32 * b + k) for k in range(32)],) * 2, trk={2: (lv, [-0.3 * g] * 32)})
    fr2, got2 = _take_frames(h2, 6)
    want2 = [_q(0.7 * math.cos(2 * math.pi * 300 * (k - 640) / 48000)) for k in range(32 * 20, 32 * 200)]
    assert fr2 == len(want2) and max(abs(a - b) for a, b in zip(got2, want2)) <= 2 / 32768


def test_v039_settings_come_only_from_the_recorders_commands():
    assert P.REC_SETTING_CMDS == (SM.CMD_ARM, SM.CMD_NOW, SM.CMD_STOP, SM.CMD_MONITOR, SM.CMD_ARM_PLAY)
    h = SL.Harness(0)
    h.defaults()
    h.command(SM.CMD_MONITOR, src=2 + 7, chan=1, thres=0.25)
    h.recorder()
    C = h.L.C
    before = (h.mem.get(C["rsrc"]), h.mem.get(C["rchan"]), h.mem.get(C["rthr"]))
    for c in (SM.CMD_SEND, SM.CMD_VERIFY, SM.CMD_PREVIEW, SM.CMD_SCAN):
        h.link(c, 0x1234, 0x5677, 0x10)
        h.recorder()
        assert (h.mem.get(C["rsrc"]), h.mem.get(C["rchan"]), h.mem.get(C["rthr"])) == before, c


@pytest.mark.parametrize("what", ["IN: DC, hiss, 50 Hz hum", "MAIN: a reverb tail, dither"])
def test_v039_thres0_waits_through_a_real_idle_input(what):
    # the owner on v0.38: "THRES 0 still triggers". v0.38's floor dropped AT ONCE to the
    # quietest 0.7 ms block: a hum's or a tail's zero crossing, a tenth of its crest; the next
    # crest started the take. Now the floor is learnt over 48 blocks, falls slowly: a second
    # of the idle input never starts it; the sound starts it on its first block
    h = SL.Harness(0)
    h.defaults()
    src = 0 if what.startswith("IN") else 1
    idle = _hum_hiss if src == 0 else _tail
    h.command(SM.CMD_ARM, src=src, chan=0, thres=33 / 32767, dest=7)
    quiet, n = 1500, 1510
    sound = lambda k: 0.3 * math.cos(2 * math.pi * 440 * (k - 32 * quiet) / 48000) if k >= 32 * quiet else 0.0  # noqa: E731
    for b in range(n):
        x = 32 * b
        lr = ([idle(x + k, 0) + sound(x + k) for k in range(32)], [idle(x + k, 1) + sound(x + k) for k in range(32)])
        if src == 0:
            h.recorder(inp=lr)
        else:
            h.recorder(main=lr, inp=([0.0] * 32, [0.0] * 32))
        if b == quiet - 1:
            assert h.status()[0] == SM.STATUS_MAGIC | 1, f"started on the idle input at block {b}"
    fr, got = _take_frames(h, 7)
    assert fr == 32 * (n - quiet)
    want = [_q((idle(k, 0) + idle(k, 1)) * 0.5 + sound(k)) for k in range(32 * quiet, 32 * n)]
    assert max(abs(a - b) for a, b in zip(got, want)) <= 2 / 32768


def _route(h, slots):
    for t in range(0, 16, 2):
        h.mem.put(SM.TRK_ROUTE + 2 * t, (slots[t] & 0xFFFF) | (slots[t + 1] & 0xFFFF) << 16)


def test_the_recorder_records_a_track_and_a_channel():
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    _route(h, list(range(16)))
    g = SM.TRK_GAIN
    left, right = [0.25 * g] * 32, [-0.5 * g] * 32
    h.command(SM.CMD_NOW, src=2 + 5, chan=2, dest=SM.REC_FIRST + 3)  # TRK6, MONO R, SAMP 127
    h.block(ONE, recorder=True, trk={5: (left, right), 4: ([0.9 * g] * 32, [0.9 * g] * 32)})
    ent = h.L.pool + 8 + 16 * (SM.REC_FIRST + 3)
    w = h.mem.get(h.mem.get(ent))
    assert h.mem.get(ent + 4) == 32 and abs((w & 0xFFFF) - ((-16384) & 0xFFFF)) <= 1
    h.command(SM.CMD_MONITOR, src=2 + 5, chan=1)                    # the meter on TRK6 L
    h.block(ONE, recorder=True, trk={5: (left, right)})
    assert abs(h.status()[3] / 32767 - 0.25) < 0.001
    # v0.22: track t is bucket t whatever the voices' routing says (the routing halves say
    # which track each DSP voice plays; v0.21 read bucket route[t], the owner's report)
    _route(h, [9] * 16)                                             # every voice playing track 9
    h.block(ONE, recorder=True, trk={5: (left, right), 9: ([0.125 * g] * 32, right)})
    assert abs(h.status()[3] / 32767 - 0.25) < 0.001


def test_a_recording_goes_where_it_is_placed_and_stops_at_the_areas_end():
    # v0.22: the ColdFire places a recording in the recordings' area (512-byte units) and
    # names its slot; the DSP never records past the pool's end, whatever it is asked
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    last = (SM.REC_BYTES - SM.REC_MIN_BYTES) // SM.REC_UNIT
    h.command(SM.CMD_NOW, dest=40, place=0xFFFF)                    # asked past the end: clamped
    ent = h.L.pool + 8 + 16 * 40
    for b in range(SM.REC_MIN_BYTES // 64 + 4):                     # 32 frames, 64 bytes a block
        h.block(ONE, recorder=True, inp=[0.3] * 32)
    assert h.mem.get(ent) == h.L.pool + SM.REC_OFFSET + last * SM.REC_UNIT
    assert h.mem.get(ent + 4) == SM.REC_MIN_BYTES // 2 and h.status()[0] == SM.STATUS_MAGIC | 3
    h.command(SM.CMD_NOW, dest=SM.POOL_SLOTS - 1)                   # a slot past the last: the last
    h.block(ONE, recorder=True, inp=[0.3] * 32)
    assert h.mem.get(h.L.pool + 8 + 16 * (SM.POOL_SLOTS - 2) + 4) == 32
    # v0.44: a dest of BUF_SLOT0.. is a BOUNCE buffer half: its entry in the buffer directory
    # (address, frames, steps), the last half for one past them
    h.command(SM.CMD_NOW, dest=200, steps=16)
    h.block(ONE, recorder=True, inp=[0.3] * 32)
    e = h.L.pool + SM.BUF_DIR + SM.BUF_ENTRY * (SM.BUF_HALVES - 1)
    assert h.mem.get(e + 4) == 32 and h.mem.get(e + 8) == 16 and h.mem.get(e) >= h.L.pool + SM.REC_OFFSET
    assert h.mem.get(h.L.pool + 8 + 16 * (SM.POOL_SLOTS - 2) + 4) == 32        # the pool's untouched


def test_r_strt_play_starts_at_the_first_note():
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    h.command(SM.CMD_ARM_PLAY, thres=0.0)
    ent = h.L.pool + 8 + 16 * SM.REC_FIRST
    for b in range(3):
        h.block(ONE, recorder=True, inp=[0.9] * 32)                 # loud, but no note: waits
    assert h.mem.get(ent + 4) == 0 and h.status()[0] == SM.STATUS_MAGIC | 1
    h.block(ONE, 60.0, True, recorder=True, inp=[0.2] * 32)        # a note: it starts
    h.block(ONE, recorder=True, inp=[0.2] * 32)
    assert h.mem.get(ent + 4) == 64 and h.status()[0] == SM.STATUS_MAGIC | 2


def test_a_saved_sound_cannot_start_the_recorder():
    # nothing the frame carries starts it: every recorder record turned up, no command
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    for r in (SM.ARM_REC, SM.RSRC_REC, SM.RDST_REC, SM.RLEN_REC, SM.RSTRT_REC, SM.RCHAN_REC):
        h.set(r, SM.RECORDS[r][2])
    for b in range(3):
        h.block(ONE, recorder=True, inp=[0.9] * 32)
    assert h.status()[0] == SM.STATUS_MAGIC
    assert all(h.mem.get(h.L.pool + 8 + 16 * (SM.REC_FIRST + k) + 4) == 0 for k in range(4))


def test_the_host_tool_leaves_the_recorders_slots():
    assert SM.USER_SLOTS < SM.REC_FIRST
    assert SM.POOL_SLOTS >= SM.REC_FIRST + SM.REC_SLOTS
    src = (pathlib.Path(__file__).resolve().parents[1] / "tools" / "dn2samples.py").read_text()
    assert "SM.USER_SLOTS" in src
    # v0.22: a send keeps every recording (an entry whose frames lie in the recordings'
    # area), in its own slot if the new image leaves it empty, else in the first empty one
    c = (pathlib.Path(__file__).resolve().parents[1] / "csrc" / "sampler" / "link.c").read_text()
    assert "is_recording(k)" in c and "rec_keep" in c and "smp_rec_place" in c


def test_a_loop_follows_len_loop_and_play_while_it_sounds():
    # a ramp, so the output says where in the sample the voice is
    n = 48000
    ramp = [k / n for k in range(n)]
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0, samples=[ramp], rates=[1.0], fmts=[0])
    h.defaults()
    h.set(SM.PLAY_REC, 80)                       # FWD LOOP
    h.set(SM.LEN_REC, 127)
    h.set(SM.LOOP_REC, 0)
    out = []
    for b in range(10):
        out += h.block(ONE, 60.0, b == 0)
    h.set(SM.LEN_REC, 2)                         # the end moves in to 800 frames, mid-note (v0.48: 2.00 of 120.00;
    h.set(SM.LOOP_REC, 1)                        # and the loop to 400               v0.15..v0.47 2 of 127: 756, 377)
    later = []
    for b in range(100):
        later += h.block(ONE, 60.0, False)
    tail = later[-2000:]
    # v0.18: through the DT2's reader (its interpolator and decimator ring a little at
    # the loop's seam, a few frames' worth of the ramp)
    eps = 100 / n                                 # (a quarter of the seam's step)
    assert max(tail) < 801 / n + eps and min(tail) >= 400 / n - eps    # looping in the new region
    h.set(SM.PLAY_REC, 40)                       # REV LOOP, mid-note: it turns round
    rev = []
    for b in range(40):
        rev += h.block(ONE, 60.0, False)
    steps = [rev[k + 16] - rev[k] for k in range(0, len(rev) - 16, 16)]   # (over 16: the filters ripple)
    assert sum(1 for d in steps if d < 0) > 0.9 * len(steps)        # mostly backward
    assert max(rev[-1000:]) < 801 / n + eps and min(rev[-1000:]) >= 400 / n - eps


def test_v049_strt_turned_mid_note_moves_the_start_not_the_playhead():
    # impbox, the owner: "the start indicator should move with the start knob, but the sample
    # playhead ... should accurately show where the playhead is on the sample as it reads it".
    # The note keeps reading where it is; the new STRT is where the next trig starts.
    n = 48000
    ramp = [k / n for k in range(n)]
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0, samples=[ramp], rates=[1.0], fmts=[0])
    h.defaults()
    h.set(SM.PLAY_REC, 127)                      # FWD
    h.set(SM.LEN_REC, 127)
    h.set(SM.STRT_REC, 0)
    out = []
    for b in range(40):
        out += h.block(ONE, 60.0, b == 0)
    at = out[-1]
    assert 0.01 < at < 0.1                       # reading near the start
    h.set(SM.STRT_REC, 60)                       # STRT to the middle, past the playhead, mid-note
    later = []
    for b in range(8):
        later += h.block(ONE, 60.0, False)
    eps = 100 / n
    assert max(later) < 0.25                     # still reading on from where it was (before: 0.5..)
    steps = [later[k + 16] - later[k] for k in range(0, len(later) - 16, 16)]
    assert all(d > -eps for d in steps) and later[-1] > at   # forward, no jump
    nxt = []
    for b in range(8):                            # the next trig: from the new STRT
        nxt += h.block(ONE, 60.0, b == 0)
    assert 0.5 - eps < nxt[-1] < 0.6


def test_one_detent_a_choice_lands_inside_each_choice():
    # every value the setter sets is read by the DSP (and the page) as that choice
    def zone(th, c):
        return sum(1 for x in th if c >= x)
    for names, rec, th, rep in SM.QUANT:
        slot, lo, top = SM.RECORDS[rec]
        assert len(rep) == len(th) + 1 and len(rep) <= 18 and len(th) <= 17
        for z, r in enumerate(rep):
            assert lo <= r <= lo + top and zone(th, r) == z, (rec, z, r)
    # and the zones are the DSP's: PLAY and MODE v >> 5, BARS and SEG their steps, GRID v // 24
    for c in range(128):
        assert zone(SM.QUANT[0][2], c) == min(3, c >> 5)
    for c in range(101):
        assert zone(SM.QUANT[2][2], c) == sum(1 for x in SM.BARS_STEPS if c >= x)
    for v in range(121):
        assert zone(SM.QUANT[3][2], v + 4) == sum(1 for x in SM.SEG_STEPS if v >= x)
        assert zone(SM.QUANT[4][2], v) == min(4, v // 24)


def _rx(h, units, high=True, pg=0):
    h.mem.put(SM.TDM_PAGE, pg)
    base = SM.TDM_RX + (pg << 11) + 32
    for off, w in SL.rx_page(units, high).items():
        h.mem.put(base + off, w)


def test_the_fast_link_writes_a_packet_in_either_justification():
    ONE = SM.TYPE_OF["ONESHOT"]
    for high, pg in ((True, 0), (False, 1)):
        h = SL.Harness(0)
        h.defaults()
        words = [(0x01020304 * k) & 0xFFFFFFFF for k in range(1, 125)]
        _rx(h, SL.rx_units(0x2000, words, seq=9), high, pg)
        h.block(ONE, recorder=True)
        assert [h.mem.get(h.L.pool + 4 * (0x2000 + k)) for k in range(124)] == words
        st = h.status()
        assert st[5] == 1 and st[6] == 9 and st[9] == 0


def test_the_fast_link_refuses_bad_packets_and_the_command_block():
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    u = SL.rx_units(0x2000, [7] * 10)
    u[100] ^= 1                                   # a bit wrong: the check fails
    _rx(h, u)
    h.block(ONE, recorder=True)
    assert h.mem.get(h.L.pool + 4 * 0x2000) == 0 and h.status()[9] == 1
    for off in (SM.CMD_OFFSET // 4 - 9, SM.CMD_OFFSET // 4 + 5, SM.POOL_WORDS - 3):
        _rx(h, SL.rx_units(off, [7] * 10))
        h.block(ONE, recorder=True)
        assert h.mem.get(h.L.pool + 4 * off) == 0, off
    # v0.20: at the command block's start, its six words or fewer, but never more
    _rx(h, SL.rx_units(SM.CMD_OFFSET // 4, [7] * 7))
    h.block(ONE, recorder=True)
    assert h.mem.get(h.L.pool + SM.CMD_OFFSET) == 0
    # the recorder's entries and frames: written (the ColdFire restores them, v0.16)
    for off in ((8 + 16 * SM.REC_FIRST) // 4 - 5, SM.REC_OFFSET // 4 - 5, SM.CMD_OFFSET // 4 - 10,
                SM.CMD_OFFSET // 4 + 6):
        _rx(h, SL.rx_units(off, [7] * 10))
        h.block(ONE, recorder=True)
        assert h.mem.get(h.L.pool + 4 * off) == 7, off
    _rx(h, [0] * 256)                             # stock's zeros: nothing, not even counted
    h.block(ONE, recorder=True)
    assert h.status()[5] == 4


def test_a_command_comes_by_the_fast_link():
    # v0.20: the ColdFire's command, six words at the command block, written and acted on
    # once (here MONITOR from MAIN, MONO L: the status echoes its sequence); sent again
    # (the ColdFire repeats each a few periods), nothing new
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    cmd = [41, SM.CMD_MONITOR, 1, 1, 100, 0]
    for _ in range(3):
        _rx(h, SL.rx_units(SM.CMD_OFFSET // 4, cmd, seq=3))
        h.block(ONE, recorder=True)
        assert [h.mem.get(h.L.pool + SM.CMD_OFFSET + 4 * j) for j in range(6)] == cmd
        st = h.status()
        assert st[1] == 41 and st[0] == SM.STATUS_MAGIC


def test_send_streams_pool_words_back_and_then_falls_silent():
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    data = [(k * 2654435761) & 0xFFFFFFFF for k in range(70)]
    for k, w in enumerate(data):
        h.mem.put(h.L.pool + 4 * (0x3000 + k), w)
    a = h.L.pool + SM.CMD_OFFSET                   # SEND 70 words from 0x3000
    for k, w in enumerate((1, SM.CMD_SEND, 0x3000, 70, 0, 0)):
        h.mem.put(a + 4 * k, w)
    got = {}
    for b in range(6):
        pg = b & 1
        h.mem.put(SM.TDM_PAGE, pg)
        h.block(ONE, recorder=True)
        base = SM.TDM_TX + (pg << 11) + 56
        pk = SL.tx_decode(lambda o: h.mem.get(base + o))
        if b < 3:
            assert pk is not None and pk[1] == b
            for k, w in enumerate(pk[2:]):
                got[pk[0] + k] = w
        elif b >= 4:
            assert pk is None                      # done: each page zeroed on its next turn
    assert [got[0x3000 + k] for k in range(70)] == data
    assert h.status()[7] == 3 and h.status()[8] == 0


def test_verify_sums_a_word_range_and_reports_it():
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    n = 3000
    data = [(k * 2246822519 + 7) & 0xFFFFFFFF for k in range(n)]
    for k, w in enumerate(data):
        h.mem.put(h.L.pool + 4 * (0x5000 + k), w)
    a = h.L.pool + SM.CMD_OFFSET
    for k, w in enumerate((4, SM.CMD_VERIFY, 0x5000, n, 0, 0)):
        h.mem.put(a + 4 * k, w)
    for b in range(4):
        h.block(ONE, recorder=True)
    st = h.status()
    sa = sb = 0
    for w in data:
        sa = (sa + w) & 0xFFFFFFFF
        sb = (sb + sa) & 0xFFFFFFFF
    assert st[14] == 4 and st[10] | st[11] << 16 == sa and st[12] | st[13] << 16 == sb
    assert st[15] == (SM.LINK_SEED + sum(st[:15])) & 0xFFFF


def test_v034_scan_counts_the_non_finite_words_of_any_range():
    """SCAN (docs/timing-model.md): a range of DSP memory by address -- a P-I voice's delay
    lines in DDR here -- walked a chunk a block; the status reports how many words are NaN
    or infinite and the first one's index, then the command's sequence when it is done."""
    from dnfw.waverider import dsp
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    base, n = dsp.MD_DELAY_DDR + 8192 * 3, 2048          # slot 3's lines
    for k in range(n):
        h.mem.put(base + 4 * k, 0)
    h.mem.put(base + 4 * 700, 0x7FC00000)                 # a NaN
    h.mem.put(base + 4 * 1900, 0xFF800000)                # -inf
    h.mem.put(base + 4 * 1901, 0xFFFFFFFF)                # the core's own NaN
    a = h.L.pool + SM.CMD_OFFSET
    for k, w in enumerate((9, SM.CMD_SCAN, base, n, 0, 0)):
        h.mem.put(a + 4 * k, w)
    h.block(ONE, recorder=True)
    st = h.status()
    assert st[14] == 0, "not done after one block (1024 words a block)"
    h.block(ONE, recorder=True)
    h.block(ONE, recorder=True)
    st = h.status()
    assert st[14] == 9, "done: the command's sequence"
    assert st[10] | st[11] << 16 == 3, "three non-finite words"
    assert st[12] | st[13] << 16 == 700, "the first one's index"
    # a clean range: none, the first index SCAN_NONE
    for k, w in enumerate((10, SM.CMD_SCAN, base, 512, 0, 0)):
        h.mem.put(a + 4 * k, w)
    h.block(ONE, recorder=True)
    h.block(ONE, recorder=True)
    st = h.status()
    assert st[14] == 10 and st[10] | st[11] << 16 == 0 and st[12] | st[13] << 16 == SM.SCAN_NONE


def test_smp_asm_is_the_program_as_it_now_is():
    # v0.16: csrc/waverider/sharc/smp.asm is written by scripts/gen_smp_asm.py from
    # dnfw.sampler.program; a change to the program without a regeneration ships the old
    # DSP code (caught by the runner once). Every line but the resolved jump targets.
    import re
    import sys
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import gen_smp_asm as G
    def norm(ln):
        ln = re.sub(r"(JUMP|CALL) 0x[0-9a-f]+;\s*", r"\1 T; ", ln)
        return re.sub(r"R12 = 0x[0-9a-f]+;\s*(// return address)", r"R12 = T; \1", ln)
    want = [norm(ln) for ln in G.build().splitlines()]
    have = [norm(ln) for ln in (root / "csrc/waverider/sharc/smp.asm").read_text().splitlines()]
    assert have == want, "run scripts/gen_smp_asm.py, then gen_waverider_sharc.py --assemble"


def test_repitch_ignores_the_note_and_tune_as_the_dt2s():
    rp = SM.TYPE_OF["REPITCH"]
    a = _play(rp, {SM.SAMP_REC: 4, SM.BARS_REC: 50}, 30, note=60.0)
    b = _play(rp, {SM.SAMP_REC: 4, SM.BARS_REC: 50, SM.TUNE_REC: 100}, 30, note=72.0)
    assert any(abs(x) > 1e-3 for x in a) and a == b


def test_grid_slce_note_lets_the_note_pick_the_slice_at_the_samples_pitch():
    g = SM.TYPE_OF["GRID"]
    for k in (0, 3, 9):
        by_note = _play(g, {SM.SAMP_REC: 4, SM.SLICE_REC: 0}, 12, note=24.0 + k)
        by_knob = _play(g, {SM.SAMP_REC: 4, SM.SLICE_REC: 2 * (k + 1)}, 12, note=60.0)
        assert any(abs(x) > 1e-3 for x in by_note) and by_note == by_knob, k


def test_stretch_crossfades_its_jumps_without_a_step():
    # a sine stretched: after each jump the output moves no more than a ramp would
    st = _play(SM.TYPE_OF["STRETCH"], {SM.SAMP_REC: 1, SM.BARS_REC: 26}, 200)
    d = max(abs(a - b) for a, b in zip(st[64:], st[65:]))
    assert d < 0.2


def test_a_retrigger_fades_the_old_note_under_the_new_one():
    # v0.18, as the DT2's second voice: the block of the new note is the new note plus the
    # old one fading out; from the next block on, the new note alone
    ONE = SM.TYPE_OF["ONESHOT"]

    def run(trigs):
        h = SL.Harness(0)
        h.defaults()
        h.set(SM.SAMP_REC, 4)                    # BEAT: long enough to be sounding at the retrigger
        out = []
        for b in range(10):
            out.append(h.block(ONE, 60.0, b in trigs))
        return out
    both, alone, first = run((1, 5)), run((5,)), run((1,))
    assert both[6:] == alone[6:]
    old = [a - b for a, b in zip(both[5], alone[5])]
    fade = [x * (1.0 - k / 31.0) for k, x in enumerate(first[5])]     # the old note, 1 -> 0
    assert max(abs(x) for x in first[5]) > 1e-2
    assert max(abs(a - b) for a, b in zip(old, fade)) < 1e-5


def test_werp_segments_are_the_dt2s_note_values_and_change_at_blocks():
    # v0.18: SEG 1/32, 1/16, 1/8 of a bar, a segment starting on a block (the DT2's ColdFire
    # clock); at 480 BPM a bar is 750 blocks: 32, 16 or 8 segments in it
    for seg, n in ((0, 32), (60, 16), (100, 8)):
        h = SL.Harness(0)
        h.defaults()
        h.set(SM.BARS_REC, 0)
        h.set(SM.SAMP_REC, 4)
        h.set(SM.SEG_REC, seg)
        _tempo(h, 480.0)
        segs = []
        for b in range(800):
            h.block(SM.TYPE_OF["WERP"], 60.0, b == 1)
            segs.append(h.mem.get(h.L.state + 4 * P.V["seg"]))
        changes = [b for b in range(1, len(segs)) if segs[b] != segs[b - 1]]
        assert len(changes) == n - 1, (seg, len(changes))
        assert abs(changes[1] - changes[0] - 750 / n) <= 1


def test_slice_plays_the_samples_own_slices():
    # v0.19: SLICE (the DT2's): a ramp with three slices of its own; SLCE picks one, LEN
    # plays on into the next, SLCE NOTE picks by the note from C1 (wrapping) at the
    # sample's pitch
    n = 3000
    ramp = [k / n for k in range(n)]
    cuts = [(0, 1000, 0), (1000, 1800, 1000), (1800, 3000, 1800)]
    SL_ = SM.TYPE_OF["SLICE"]

    def play(slce, slen=0, note=60.0, slices=cuts):
        h = SL.Harness(0, samples=[ramp], rates=[1.0], fmts=[0], slices=[slices])
        h.defaults()
        h.set(SM.SLICE_REC, slce)
        h.set(SM.SLEN_REC, slen)
        out = []
        for b in range(120):
            out += h.block(SL_, note, b == 1)
        nz = [x for x in out if abs(x) > 1e-4]
        return nz[64:-64]                      # (its first block fades in, its last two out)
    g = struct.unpack("<f", P.tables_bytes()[-4:])[0]
    for k, (a, b, _) in enumerate(cuts):
        nz = play(2 * (k + 1))
        assert abs(len(nz) + 128 - (b - a)) <= 140, (k, len(nz))  # the slice's frames
        assert abs(min(nz) - a / n) < 0.05 and abs(max(nz) - b / n) < 0.05
    nz = play(2, slen=2)                       # slices 1 and 2
    assert abs(max(nz) - 1800 / n) < 0.05
    nz = play(2 * 9)                           # past the last: the last
    assert abs(min(nz) - 1800 / n) < 0.05
    nz = play(0, note=24.0 + 4)                # NOTE: C1 + 4 -> slice 4 mod 3 = 1 (the second)
    assert abs(min(nz) - 1000 / n) < 0.05 and abs(max(nz) - 1800 / n) < 0.05
    whole = play(2, slices=())                 # v0.23: no slices: the whole sample (v0.19..v0.22: nothing)
    assert abs(min(whole) - 0.0) < 0.05 and abs(max(whole) - 1.0) < 0.05


def test_the_host_tool_writes_a_wavs_slices(tmp_path):
    # v0.19: dn2samples.py takes a WAV's cue points as its SLICE slices (or a grid, or onsets)
    import dn2samples as T
    rate, n = 24000, 2400
    frames = struct.pack(f"<{n}h", *(int(8000 * math.sin(k / 7)) for k in range(n)))
    cues = (0, 700, 1500)
    cue = struct.pack("<I", len(cues)) + b"".join(
        struct.pack("<II4sIII", k, 0, b"data", 0, 0, c) for k, c in enumerate(cues))
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"cue " + struct.pack("<I", len(cue)) + cue
            + b"data" + struct.pack("<I", len(frames)) + frames)
    p = tmp_path / "loop.wav"
    p.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    assert T.read_cues(p) == list(cues)
    pool, names, _ = T.build_pool([p])
    addr, fr, _r, fmtw = struct.unpack_from("<IIfI", pool, 8)
    assert fr == n and fmtw == SM.FMT_I16 | 3 << 8
    tbl = addr - 0x84000000 + 2 * n
    assert [struct.unpack_from("<III", pool, tbl + 12 * k) for k in range(3)] == \
        [(0, 700, 0), (700, 1500, 700), (1500, 2400, 1500)]
    pool, _, _ = T.build_pool([p], "grid:4")
    assert struct.unpack_from("<I", pool, 8 + 12)[0] >> 8 == 4
    pool, _, _ = T.build_pool([p], "none")
    assert struct.unpack_from("<I", pool, 8 + 12)[0] == SM.FMT_I16


def _probe(mem_cls):
    from dnfw.perc.dsl import Mem
    h = SL.Harness(0)
    if mem_cls is not None:
        old = h.mem
        h.mem = mem_cls(old.read)
    h.command(SM.CMD_PROBE)
    blocks = 0
    while True:
        P.run_recorder(h.L, h.mem)
        blocks += 1
        st = h.status()
        if st[4] in (1, 2) or blocks > 5000:
            return h, st[4], blocks


def test_v022_the_ram_check_passes_on_a_whole_512_mb_part():
    h, res, blocks = _probe(None)
    n = SM.PROBE_BYTES // 4
    assert res == 1 and blocks == 4 * n // SM.PROBE_STEP + 1      # the verdict shows a block later
    lo, hi = h.L.pool + SM.PROBE_LO, h.L.pool + SM.PROBE_HI
    assert hi + SM.PROBE_BYTES <= h.L.pool + SM.POOL_BYTES <= 0xA0000000
    assert h.mem.get(lo + 4 * 7) == SM.PROBE_PAT[0] + 7 and h.mem.get(hi + 4 * 7) == SM.PROBE_PAT[1] + 7
    # it writes nowhere but its two areas and its own words
    ddr = [a for a in h.mem.w if a >= 0x80000000]
    assert all(lo <= a < lo + SM.PROBE_BYTES or hi <= a < hi + SM.PROBE_BYTES or a == h.L.pool + SM.CMD_OFFSET
               or h.L.pool + SM.CMD_OFFSET <= a < h.L.pool + SM.CMD_OFFSET + 4 * SM.CMD_WORDS for a in ddr)
    # and once done, a block more does nothing
    before = dict(h.mem.w)
    P.run_recorder(h.L, h.mem)
    assert {a: v for a, v in h.mem.w.items() if a >= 0x80000000} == {a: v for a, v in before.items() if a >= 0x80000000}


def test_v022_the_ram_check_fails_on_a_256_mb_part():
    from dnfw.perc.dsl import Mem

    class Folded(Mem):                     # a 256 MB part: address bit 28 is not decoded
        def get(self, a):
            return super().get(a & ~0x10000000 if a >= 0x80000000 else a)

        def put(self, a, v):
            super().put(a & ~0x10000000 if a >= 0x80000000 else a, v)
    _h, res, _ = _probe(Folded)
    assert res == 2


def test_v022_the_ram_check_does_nothing_from_stray_words():
    h = SL.Harness(0)
    h.mem.put(h.L.C["pph"], 3)
    h.mem.put(h.L.C["pix"], 0x40000000)           # far out of range: stops, writes nothing
    P.run_recorder(h.L, h.mem)
    assert h.mem.get(h.L.C["pph"]) == 0
    assert not [a for a in h.mem.w if a >= 0x80000000]


def test_v022_send_skips_the_recordings_area_and_link4_reports_the_ram():
    import dn2samples as T
    pool = bytes(range(256)) * ((SM.REC_END + (1 << 20)) // 256)       # past the hole
    sent = []

    class FakeLink:
        proto = 4

        def call(self, cmd, payload=b"", timeout=2.0, tries=3):
            if cmd == T.WRITE:
                at = struct.unpack(">I", payload[:4])[0]
                sent.append((at, len(payload) - 4))
            if cmd == T.STATUS:
                return struct.pack(">7I", len(pool), 4, len(pool), 0, 1, 0, 1)
            return b"\0" * 8
    T.cmd_send3(FakeLink(), pool, ["X"], 1 << 16)
    assert sent and all(not (a < SM.REC_END and a + n > SM.REC_OFFSET) for a, n in sent)
    assert sum(n for _, n in sent) == len(pool) - SM.HOLE_BYTES
    assert sent[-1][0] + sent[-1][1] == len(pool)
    src = (pathlib.Path(__file__).resolve().parents[1] / "csrc/sampler/link.c").read_text()
    assert "(at < REC_END && at + k > REC_OFFSET)" in src
    import re
    assert int(re.search(r"#define PROTO (\d+)", src).group(1)) >= 4      # (v0.31: 5, the library)


def test_v022_len_at_its_lowest_still_loops_and_a_held_note_survives_the_knobs():
    # the owner: LEN at its lowest went silent instead of looping a short stretch, and a
    # held looped note sometimes stopped while the knobs moved (an empty region ended it)
    n = 48000
    ramp = [0.2 + 0.6 * k / n for k in range(n)]
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0, samples=[ramp], rates=[1.0], fmts=[0])
    h.defaults()
    h.set(SM.PLAY_REC, 80)                       # FWD LOOP
    h.set(SM.LEN_REC, 0)
    h.set(SM.LOOP_REC, 0)
    out = []
    for b in range(60):
        out += h.block(ONE, 60.0, b == 0)
    tail = out[-500:]
    assert min(tail) > 0.1                                       # sounding: a short loop
    assert max(tail) - min(tail) < 0.6 * (n // 508 + 4) / n + 0.01   # .. of about n / 508 frames
    # the knobs swept to their ends and back, the note held: it never stops
    for strt, ln in ((120, 0), (120, 127), (0, 0), (60, 1), (0, 127)):
        h.set(SM.STRT_REC, strt)
        h.set(SM.LEN_REC, ln)
        seg = []
        for b in range(8):
            seg += h.block(ONE, 60.0, False)
        assert max(abs(x) for x in seg[-64:]) > 0.1, (strt, ln)


def test_v022_stretch_and_repitch_at_len_0_are_heard():
    # the owner: STRETCH (no LOOP of its own) went silent with LEN at its lowest, as ONESHOT
    n = 48000
    snd = [0.5 * math.sin(2 * math.pi * 220 * k / 48000) for k in range(n)]
    for name, floor in (("STRETCH", 0.3), ("REPITCH", 0.03)):
        h = SL.Harness(0, samples=[snd], rates=[1.0], fmts=[0])
        h.defaults()
        h.set(SM.PLAY_REC, 80)
        h.set(SM.LEN_REC, 0)
        out = []
        for b in range(120):
            out += h.block(SM.TYPE_OF[name], 60.0, b == 0)
        assert max(abs(x) for x in out[-1600:]) > floor, name


def test_v023_slices_made_on_the_instrument_come_from_the_slice_area():
    # the entry's bit 16: the table is the slot's in the slice area (link.c's
    # smp_slices_set), not after the frames; a sample sent without slices gets them so
    n = 3000
    ramp = [k / n for k in range(n)]
    SL_ = SM.TYPE_OF["SLICE"]
    cuts = [(0, 900, 0), (900, 2100, 900), (2100, 3000, 2100)]

    def play(slce):
        h = SL.Harness(0, samples=[ramp], rates=[1.0], fmts=[0])
        h.defaults()
        ent = h.L.pool + 8                      # slot 0 (SAMP 1)
        h.mem.put(ent + 12, h.mem.get(ent + 12) | len(cuts) << 8 | 1 << 16)
        area = h.L.pool + SM.SLICE_AREA
        for j, (a, b, lp) in enumerate(cuts):
            for w, x in enumerate((a, b, lp)):
                h.mem.put(area + 12 * j + 4 * w, x)
        h.set(SM.SLICE_REC, slce)
        out = []
        for b in range(120):
            out += h.block(SL_, 60.0, b == 1)
        nz = [x for x in out if abs(x) > 1e-4]
        return nz[64:-64]
    for k, (a, b, _) in enumerate(cuts):
        nz = play(2 * (k + 1))
        assert abs(min(nz) - a / n) < 0.05 and abs(max(nz) - b / n) < 0.05, k
    assert SM.SLICE_AREA + SM.POOL_SLOTS * SM.SLICE_TABLE_BYTES <= SM.REC_END
    assert SM.REC_OFFSET + SM.REC_BYTES == SM.TABLE_AREA      # v0.26: then the tables the ColdFire sends
    assert SM.TABLE_AREA + SM.TABLE_ROOM == SM.SLICE_AREA and SM.TABLE_AREA <= SM.TABLE_READY < SM.SLICE_AREA


def test_idle_link_sends_the_play_positions():
    """v0.25: with no SEND running, the DSP's packet is each track's play position (the
    playhead on the sample pages), as the voices stood when the block began: track 0
    plays and its unit is its read position as a fraction of the sample x POS_ONE; the
    others play nothing (POS_NONE)."""
    ONE = SM.TYPE_OF["ONESHOT"]
    h = SL.Harness(0)
    h.defaults()
    seen, before = [], None
    for b in range(6):
        pg = b & 1
        h.mem.put(SM.TDM_PAGE, pg)
        h.block(ONE, trig=(b == 1), recorder=True)
        base = SM.TDM_TX + (pg << 11) + 56
        pk = SL.pos_decode(lambda o: h.mem.get(base + o))
        assert pk is not None and len(pk) == 16
        assert all(u == SM.POS_NONE for u in pk[1:])
        if before and before[0] and before[2]:
            want = int(min(max(before[1] / before[2], 0.0), 1.0) * SM.POS_ONE)
            assert abs(pk[0] - want) <= 1, (pk[0], want)
            seen.append(pk[0])
        else:
            assert pk[0] == SM.POS_NONE
        before = [h.mem.get(h.L.state + 4 * P.V[k]) for k in ("on", "pos", "frames")]
    assert len(seen) >= 3 and seen == sorted(seen) and seen[-1] > seen[0]


class _FakeLib:
    """v0.31: the +Drive library's SysEx side, as csrc/sampler/lib.c answers it (cmds 16..23,
    little-endian), to hold the host tool's packing to it."""

    def __init__(self):
        self.folders = ["INCOMING", "RECORDED"]
        self.entries = {}
        self.w = None

    def call(self, cmd, payload=b"", timeout=2.0):
        rq = b"\0\0" + bytes([cmd]) + payload          # lib.c reads after seq and cmd
        if cmd == 17:
            name = rq[3:34].split(b"\0")[0].decode()
            if name not in self.folders:
                self.folders.append(name)
            return bytes([self.folders.index(name)])
        if cmd == 18:
            frames, fmt, folder = struct.unpack_from("<IBB", rq, 3)
            rate = struct.unpack_from("<f", rq, 9)[0]
            k = next(i for i in range(2048) if i not in self.entries)
            self.w = dict(k=k, frames=frames, fmt=fmt, folder=folder, rate=rate,
                          name=rq[13:].decode(), data=bytearray())
            return struct.pack("<II", k, 0x700105)
        if cmd == 19:
            at = struct.unpack_from("<I", rq, 3)[0]
            assert at == len(self.w["data"])
            self.w["data"] += rq[7:]
            return struct.pack("<I", len(self.w["data"]))
        if cmd == 20:
            import dn2samples as D
            w = self.w
            assert len(w["data"]) == w["frames"] * (2 if w["fmt"] else 4)
            assert struct.unpack_from("<I", rq, 3)[0] == D.lib_adler(bytes(w["data"]))
            self.entries[w["k"]] = w
            return struct.pack("<I", w["k"])
        if cmd == 21:
            k0 = rq[3] | rq[4] << 8
            out = struct.pack("<I", len(self.entries))
            for k in range(k0, k0 + 4):
                e = self.entries.get(k)
                out += struct.pack("<HIB", k, e["frames"] if e else 0, e["folder"] if e else 0xFF)
                out += (e["name"].encode()[:24] if e else b"").ljust(24, b"\0")
            return out
        if cmd == 16:                                   # INFO (v0.45: the host tool reads the capacity)
            return struct.pack("<5I", 0, 16384, len(self.entries), 0, 0)
        if cmd == 23:
            f0 = rq[3]
            return b"".join((self.folders[f].encode() if f < len(self.folders) else b"").ljust(24, b"\0")
                            for f in range(f0, f0 + 4))
        raise AssertionError(cmd)


def test_the_host_tool_sends_into_the_drive_library(tmp_path):
    import dn2samples as D
    p = tmp_path / "kick.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(k / 7))) for k in range(1000)))
    lib = _FakeLib()
    D.lib_send(lib, [p], "DRUMS", 300)
    e = lib.entries[0]
    assert e["frames"] == 1000 and e["fmt"] == SM.FMT_I16 and lib.folders[e["folder"]] == "DRUMS"
    assert abs(e["rate"] - 44100 / 48000) < 1e-6 and e["name"] == "KICK"
    assert D.lib_list(lib) == [(0, "DRUMS", "KICK", 1000)]
    assert D.lib_adler(b"abc") == 0x024D0127                      # zlib's adler32
    c = (pathlib.Path(__file__).resolve().parents[1] / "csrc" / "sampler" / "lib.c").read_text()
    # v0.46: BEGIN's fields read where the host tool packs them (<IBBI: frames 3, fmt 7, folder 8,
    # rate 9, the name from 13), through the writer the recordings' copy shares
    assert "cmd == 18" in c and "w_begin(lget(rq + 3), rq[7], rq[8], lget(rq + 9), rq + 13, n - 13, 0)" in c


def _plays_on_dsp(h, slot):
    """the DSP's model plays SAMP slot + 1 on a trig: any sound in four blocks"""
    ONE = SM.TYPE_OF["ONESHOT"]
    h.set(SM.SAMP_REC, slot + 1)
    out = []
    for b in range(4):
        out += h.block(ONE, 60.0, b == 0)
    return any(abs(x) > 1e-6 for x in out)


@pytest.mark.parametrize("case", ["below", "at", "past", "rec", "magic", "fmt", "base", "frames"])
def test_v038_slot_plays_is_the_dsps_own_rule(case):
    """SL.slot_plays (the ColdFire gates' DSP rule) answers as the DSP's model plays: the
    count gates every slot below REC_FIRST (the testers' silent live adds), the recorder's
    slots need none, and an entry outside the pool is silent"""
    h = SL.Harness(0)
    h.defaults()
    pool = h.L.pool
    kick = [h.mem.get(pool + 8 + 4 * j) for j in range(4)]   # slot 0's entry: real frames
    count = h.mem.get(pool + 4)
    slot = {"below": 1, "at": count, "past": count + 5, "rec": SM.REC_FIRST + 1}.get(case, 2)
    ent = list(kick)
    if case == "fmt":
        ent[3] = (ent[3] & ~0xFF) | ((SM.FMT_I16S if SM.STEREO else SM.FMT_I16) + 1)   # past the last format (stereo: 3)
    if case == "base":
        ent[0] = pool + 0x800
    if case == "frames":
        ent[1] = 0
    for j, w in enumerate(ent):
        h.mem.put(pool + 8 + 16 * slot + 4 * j, w)
    if case == "magic":
        h.mem.put(pool, 0)
    want = case in ("below", "rec")
    assert SL.slot_plays(h.mem.get, pool, slot) is want
    assert _plays_on_dsp(h, slot) is want


def test_v038_a_slot_past_the_count_plays_once_the_count_covers_it():
    """the root cause of 'new samples are silent until a restart' on the DSP's side: a slot
    with a whole entry past the count is silent; the same slot plays once word 1 covers it
    (which the ColdFire now sends after every live entry, csrc/sampler/link.c K_HEAD)"""
    h = SL.Harness(0)
    h.defaults()
    pool = h.L.pool
    count = h.mem.get(pool + 4)
    for j in range(4):
        h.mem.put(pool + 8 + 16 * count + 4 * j, h.mem.get(pool + 8 + 4 * j))
    assert not _plays_on_dsp(h, count)
    h.mem.put(pool + 4, count + 1)
    assert SL.slot_plays(h.mem.get, pool, count) and _plays_on_dsp(h, count)


def test_v044_a_bounce_take_plays_from_the_buffer_directory_for_its_steps_at_the_tempo():
    """v0.44 BOUNCE: a take recorded into buffer half BUF_SLOT0 + 3 (steps 8) has its entry in the
    buffer directory, not the pool's; a STRETCH voice on SAMP BUF_SAMP0 + 3 plays it, fitted to
    8 steps at the frame's tempo (twice as fast at twice the tempo), with no slices; SAMP past
    the halves, or a half never recorded, is silent"""
    STR = SM.TYPE_OF["STRETCH"]
    h = SL.Harness(0)
    h.defaults()
    h.command(SM.CMD_NOW, dest=SM.BUF_SLOT0 + 3, place=64, steps=8)
    for b in range(40):
        h.block(STR, recorder=True, inp=[0.5 * (1 if (b * 32 + k) % 16 < 8 else -1) for k in range(32)])
    h.command(SM.CMD_STOP)
    h.block(STR, recorder=True, inp=[0.0] * 32)
    e = h.L.pool + SM.BUF_DIR + SM.BUF_ENTRY * 3
    assert h.mem.get(e) == h.L.pool + SM.REC_OFFSET + 64 * SM.REC_UNIT and h.mem.get(e + 4) == 40 * 32 and h.mem.get(e + 8) == 8
    assert h.mem.get(h.L.pool + 8 + 16 * (SM.POOL_SLOTS - 2) + 4) == 0 and h.mem.get(h.L.pool + 8 + 16 * SM.REC_FIRST + 4) == 0

    def play(tempo, samp):
        h.set(SM.SAMP_REC, samp)
        h.set(SM.PLAY_REC, 127)
        h.tempo(tempo)
        outs = []
        for b in range(6):
            outs += h.block(STR, note=60.0, trig=b == 0)
        return outs, flt(h.mem.get(h.L.C["sr"]))
    slow, sr120 = play(120, SM.BUF_SAMP0 + 3)
    fast, sr240 = play(240, SM.BUF_SAMP0 + 3)
    assert max(abs(x) for x in slow) > 0.1 and max(abs(x) for x in fast) > 0.1
    # fitted to the steps, not BARS: the source frames an output sample = frames over the
    # output samples 8 steps last at the tempo (1280 / 48000 at 120 BPM), twice that at 240
    assert abs(sr120 - 1280 / 48000) < 1e-6 and abs(sr240 - 2 * 1280 / 48000) < 1e-6
    # (the first block fades the note before out, as the DT2's retrigger does)
    assert all(x == 0.0 for x in play(120, SM.BUF_SAMP0 + SM.BUF_HALVES)[0][32:])      # past the halves
    assert all(x == 0.0 for x in play(120, SM.BUF_SAMP0 + 5)[0][32:])                  # never recorded


def test_stereo_format_2_plays_its_left_plus_right_halved_on_every_reader():
    """stereo stage 2a (docs/stereo-assessment.md): a stereo sample (format 2, int16 L R a frame)
    plays (L + R) / 2 -- every reader (ONESHOT's fast and edge taps, REPITCH, STRETCH, WERP, GRID),
    bit for bit the same output as a float32 sample holding (L + R) / 65536, exact in float32.
    Stereo voices past the cap play this; it is also the whole of a stereo sample before stage 2b.
    The negative: a build without STEREO trusts no format 2 entry: silence"""
    n = 6000
    pairs = [(((k * 37) % 4001 - 2000) * 7, -(((k * 11) % 3001) - 1500) * 9) for k in range(n)]
    st = [(l / 32768, r / 32768) for l, r in pairs]
    mix = [(l + r) / 65536 for l, r in pairs]

    def run(sample, fmt, mtype, note, play):
        h = SL.Harness(0, samples=[sample], rates=[1.0], fmts=[fmt])
        h.defaults()
        h.set(SM.PLAY_REC, play)
        _tempo(h, 120)
        out = []
        for b in range(40):
            out += h.block(mtype, note, b == 0)
        return out
    for name, note, play in (("ONESHOT", 67.0, 127), ("ONESHOT", 55.0, 40), ("REPITCH", 60.0, 127),
                             ("STRETCH", 60.0, 127), ("WERP", 60.0, 127), ("GRID", 60.0, 127)):
        mt = SM.TYPE_OF[name]
        a, b = run(st, SM.FMT_I16S, mt, note, play), run(mix, SM.FMT_F32, mt, note, play)
        assert max(abs(x) for x in b) > 0.01, name
        assert [struct.pack("<f", x) for x in a] == [struct.pack("<f", x) for x in b], (name, note, play)
    # the negative: STEREO 0 (a build without it) refuses the entry, the voice silent
    import importlib
    try:
        SM.STEREO = 0
        importlib.reload(P)
        importlib.reload(SL)
        silent = run(st, SM.FMT_I16S, SM.TYPE_OF["ONESHOT"], 60.0, 127)
        assert max(abs(x) for x in silent) == 0.0
    finally:
        SM.STEREO = 1
        importlib.reload(P)
        importlib.reload(SL)


def test_stereo_2b_a_stereo_voice_renders_l_and_r_each_as_its_own_mono_sample():
    """stereo stage 2b (dnfw.sampler.program.stereo_voice): a format-2 sample on a voice with a
    stereo slot renders L into the voice's block and R into the slot's R block, each bit for bit
    what an int16 mono sample of that channel alone renders (every reader: ONESHOT fast and
    edge taps, REPITCH, STRETCH, WERP, GRID), block after block, with R's own decimator. The
    slot is taken on the note's first block (rendered again as L), freed when the voice plays
    a mono sample. The negative: the same stereo sample without the wrapper is the mix."""
    from dnfw.sampler import stereo as ST
    n = 6000
    pairs = [(((k * 37) % 4001 - 2000) * 7, -(((k * 11) % 3001) - 1500) * 9) for k in range(n)]
    st = [(l / 32768, r / 32768) for l, r in pairs]
    left = [l / 32768 for l, _ in pairs]
    right = [r / 32768 for _, r in pairs]

    def run(sample, fmt, mtype, note, play, stereo, blocks=24):
        h = SL.Harness(0, samples=[sample], rates=[1.0], fmts=[fmt])
        h.stereo = stereo
        h.defaults()
        h.set(SM.PLAY_REC, play)
        _tempo(h, 120)
        out, rb, slots = [], [], []
        for b in range(blocks):
            out += h.block(mtype, note, b == 0)
            rb += [struct.unpack("<f", struct.pack("<I", h.mem.get(ST.RBLK + 4 * k)))[0] for k in range(32)]
            slots.append(h.mem.get(ST.laddr(0, 0)))
        return out, rb, slots, h
    bits = lambda xs: [struct.pack("<f", x) for x in xs]          # noqa: E731
    for name, note, play in (("ONESHOT", 67.0, 127), ("ONESHOT", 55.0, 40), ("REPITCH", 60.0, 127),
                             ("STRETCH", 60.0, 127), ("WERP", 60.0, 127), ("GRID", 60.0, 127)):
        mt = SM.TYPE_OF[name]
        lo, ro, slots, _h = run(st, SM.FMT_I16S, mt, note, play, True)
        lm, *_ = run(left, SM.FMT_I16, mt, note, play, False)
        rm, *_ = run(right, SM.FMT_I16, mt, note, play, False)
        assert max(abs(x) for x in lm) > 0.01 and max(abs(x) for x in rm) > 0.01, name
        assert bits(lo) == bits(lm), (name, "L")
        assert bits(ro) == bits(rm), (name, "R")
        assert all(slots), name                                  # the slot held every block
    # a mono sample on the wrapper: one run, as voice() alone, no slot
    mo, _, mslots, _ = run(left, SM.FMT_I16, SM.TYPE_OF["ONESHOT"], 60.0, 127, True)
    mv, *_ = run(left, SM.FMT_I16, SM.TYPE_OF["ONESHOT"], 60.0, 127, False)
    assert bits(mo) == bits(mv) and not any(mslots)
    # the negative: without the wrapper a stereo sample is the mix, not L
    mix, *_ = run(st, SM.FMT_I16S, SM.TYPE_OF["ONESHOT"], 60.0, 127, False)
    lone, *_ = run(left, SM.FMT_I16, SM.TYPE_OF["ONESHOT"], 60.0, 127, False)
    assert bits(mix) != bits(lone)

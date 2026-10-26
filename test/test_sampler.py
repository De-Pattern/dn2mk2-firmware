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
        assert page[1][0] == SM.PLAY_REC and page[3][0] == SM.SAMP_REC, name
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
    h.command(SM.CMD_NOW, dest=200)                                 # a slot past the last: the last
    h.block(ONE, recorder=True, inp=[0.3] * 32)
    assert h.mem.get(h.L.pool + 8 + 16 * (SM.POOL_SLOTS - 2) + 4) == 32


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
    h.set(SM.LEN_REC, 2)                         # the end moves in to 756 frames, mid-note
    h.set(SM.LOOP_REC, 1)                        # and the loop to 377
    later = []
    for b in range(100):
        later += h.block(ONE, 60.0, False)
    tail = later[-2000:]
    # v0.18: through the DT2's reader (its interpolator and decimator ring a little at
    # the loop's seam, a few frames' worth of the ramp)
    eps = 100 / n                                 # (a quarter of the seam's step)
    assert max(tail) < 757 / n + eps and min(tail) >= 377 / n - eps    # looping in the new region
    h.set(SM.PLAY_REC, 40)                       # REV LOOP, mid-note: it turns round
    rev = []
    for b in range(40):
        rev += h.block(ONE, 60.0, False)
    steps = [rev[k + 16] - rev[k] for k in range(0, len(rev) - 16, 16)]   # (over 16: the filters ripple)
    assert sum(1 for d in steps if d < 0) > 0.9 * len(steps)        # mostly backward
    assert max(rev[-1000:]) < 757 / n + eps and min(rev[-1000:]) >= 377 / n - eps


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
        by_note = _play(g, {SM.SAMP_REC: 4, SM.SLICE_REC: 0}, 12, note=12.0 + k)
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
    nz = play(0, note=12.0 + 4)                # NOTE: C1 + 4 -> slice 4 mod 3 = 1 (the second)
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
    assert "(at < REC_END && at + k > REC_OFFSET)" in src and "#define PROTO 4" in src


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

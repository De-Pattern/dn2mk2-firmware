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


def test_cfad_is_off_with_its_control_off_the_page():
    assert P.CFAD_ON is False
    assert all(r != SM.CFAD_REC for r, _s, _l in SM.PAGES["ONESHOT"])


def test_cfad_makes_the_loop_seamless(monkeypatch):
    monkeypatch.setattr(P, "CFAD_ON", True)
    # ONESHOT FWD LOOP on a sine whose loop does not meet itself: without CFAD the wrap
    # jumps; with it the step there is no bigger than the sine's own
    n = 4000
    snd = [0.8 * math.sin(2 * math.pi * k / 97.3) for k in range(n)]

    def run(cfad):
        h = SL.Harness(0, samples=[snd], rates=[1.0], fmts=[0])
        h.defaults()
        h.set(SM.PLAY_REC, 80)                   # FWDL
        h.set(SM.LEN_REC, 40)
        h.set(SM.LOOP_REC, 20)
        h.set(SM.CFAD_REC, cfad)
        out = []
        for b in range(120):
            out += h.block(SM.TYPE_OF["ONESHOT"], 60.0, b == 1)
        return out
    own = max(abs(snd[k + 1] - snd[k]) for k in range(n - 1))
    jump = lambda o: max(abs(o[k + 1] - o[k]) for k in range(64, len(o) - 1))
    assert jump(run(0)) > 2 * own
    assert jump(run(127)) <= own * 1.05


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
    h.command(SM.CMD_NOW, src=0, dest=1)                            # IN, SAMP 125
    for b in range(20):
        h.block(ONE, recorder=True, inp=sig[32 * b:32 * b + 32])
    st = h.status()
    assert _check(h) and st[0] == SM.STATUS_MAGIC | 2 and st[2] == 10 and st[1] == 1
    assert abs(st[3] / 32767 - 0.5) < 0.01                          # the peak, for the meter
    ent = h.L.pool + 8 + 16 * (SM.REC_FIRST + 1)
    assert h.mem.get(ent) == h.L.pool + SM.REC_OFFSET + (1 << SM.REC_SLOT_SHIFT)
    assert h.mem.get(ent + 4) == 32 * 20 and h.mem.get(ent + 12) == SM.FMT_I16
    h.command(SM.CMD_STOP)
    h.block(ONE, recorder=True)
    assert h.status()[0] == SM.STATUS_MAGIC | 3 and h.mem.get(ent + 4) == 32 * 20
    h.set(SM.SAMP_REC, SM.REC_FIRST + 2)
    out = []
    for b in range(20):
        out += h.block(ONE, 60.0, b == 0)
    assert max(abs(a - b) for a, b in zip(out, sig[:len(out)])) < 1e-4


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
    h.command(SM.CMD_NOW, src=2 + 5, chan=2, dest=3)                # TRK6, MONO R, SAMP 127
    h.block(ONE, recorder=True, trk={5: (left, right), 4: ([0.9 * g] * 32, [0.9 * g] * 32)})
    ent = h.L.pool + 8 + 16 * (SM.REC_FIRST + 3)
    w = h.mem.get(h.mem.get(ent))
    assert h.mem.get(ent + 4) == 32 and abs((w & 0xFFFF) - ((-16384) & 0xFFFF)) <= 1
    h.command(SM.CMD_MONITOR, src=2 + 5, chan=1)                    # the meter on TRK6 L
    h.block(ONE, recorder=True, trk={5: (left, right)})
    assert abs(h.status()[3] / 32767 - 0.25) < 0.001
    _route(h, [9] * 16)                                             # every track in slot 9
    h.block(ONE, recorder=True, trk={5: (left, right), 9: ([0.125 * g] * 32, right)})
    assert abs(h.status()[3] / 32767 - 0.125) < 0.001


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


def test_the_mailbox_writes_the_recorders_entries_too():
    # v0.16: the ColdFire restores the recorder's entries from the +Drive (nothing streams
    # over them any more), so a packet there is written like any other
    L = SL.layout()
    lo = (8 + 16 * SM.REC_FIRST) // 4
    for w in (lo - 5, lo, SM.CMD_OFFSET // 4):
        mem = _frame_mem(P.link_packet(w, [7] * 6))
        P.run_mailbox(L, mem)
        assert mem.get(L.C["mbn"]) == 1 and mem.get(L.pool + 4 * w) == 7, w


def test_the_host_tool_leaves_the_recorders_slots():
    assert SM.USER_SLOTS < SM.REC_FIRST
    assert SM.POOL_SLOTS >= SM.REC_FIRST + SM.REC_SLOTS
    src = (pathlib.Path(__file__).resolve().parents[1] / "tools" / "dn2samples.py").read_text()
    assert "SM.USER_SLOTS" in src
    c = (pathlib.Path(__file__).resolve().parents[1] / "csrc" / "sampler" / "link.c").read_text()
    assert f"16u * {SM.REC_FIRST}u" in c and f"16u * {SM.REC_FIRST + SM.REC_SLOTS}u" in c


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
    assert max(tail) < 757 / n and min(tail) >= 377 / n - 1e-6    # looping in the new region
    h.set(SM.PLAY_REC, 40)                       # REV LOOP, mid-note: it turns round
    rev = []
    for b in range(40):
        rev += h.block(ONE, 60.0, False)
    steps = [rev[k + 1] - rev[k] for k in range(len(rev) - 1)]
    assert sum(1 for d in steps if d < 0) > 0.9 * len(steps)        # mostly backward
    assert max(rev[-1000:]) < 757 / n and min(rev[-1000:]) >= 377 / n - 1e-6


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
    for v in range(128):
        assert zone(SM.QUANT[5][2], v) == v * len(SM.SRC_NAMES) // 128


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
    # the recorder's entries and frames: written (the ColdFire restores them, v0.16)
    for off in ((8 + 16 * SM.REC_FIRST) // 4 - 5, SM.REC_OFFSET // 4 - 5, SM.CMD_OFFSET // 4 - 10,
                SM.CMD_OFFSET // 4 + 6):
        _rx(h, SL.rx_units(off, [7] * 10))
        h.block(ONE, recorder=True)
        assert h.mem.get(h.L.pool + 4 * off) == 7, off
    _rx(h, [0] * 256)                             # stock's zeros: nothing, not even counted
    h.block(ONE, recorder=True)
    assert h.status()[5] == 4


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

"""dn2live: the STATS decoder, the readings, the poller and the SSE server, with no instrument.

derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

The replies are built the way `csrc/usbprobe/probe.S` builds them (label 20:
u16 layout, u16 0, ten u32 counters, four u32 hashes, packed by pack7 under the
0x7D header), and three were captured from the probe itself in the emulator
(`scripts/emu_usbprobe.py`'s Rig on out/usbprobe: HELLO, STATS, then five ISRs
and one changed word of the SHARC reply, then STATS again).
"""
import http.client
import json
import pathlib
import struct
import sys
import threading
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dn2log  # noqa: E402
import dn2poll  # noqa: E402
import dn2probe  # noqa: E402
import dn2stats  # noqa: E402
import dn2watch  # noqa: E402

# the probe's own bytes, from the emulator (2026-09-27, out/usbprobe, digikit-up)
EMU_HELLO = bytes.fromhex("f000203c7d001003010100000100000000007573627000726f626500f7")
EMU_STATS1 = bytes.fromhex(
    "f000203c7d001003020200000100000000000000000000000000000000001000055c0000000000000000000000"
    "00000000000000000000000000000000000c0000000f5f000000000000000000000000f7")
EMU_STATS2 = bytes.fromhex(
    "f000203c7d001003030200000100000000000000000000000500000000001000055c0000000000000000050000"
    "000000000000000000000000000000004e1c782c5a0f5f000000000000000000000000f7")


def reply(seq, cmd, payload, status=0):
    """A reply as probe.S sends it: header, pack7(seq, cmd|0x80, status, payload), F7."""
    return dn2probe.HEADER + dn2probe.pack7(struct.pack(">HBB", seq, cmd | 0x80, status) + payload) + b"\xF7"


def stats_payload(w, layout=1, extra=(), tail=b""):
    """Layout 1's 60 bytes, then (layout >= 2) ext.S's five words in its order, then `extra`."""
    words = [w[k] for k in dn2stats.LAYOUTS[max(1, min(layout, 2))]]
    return (struct.pack(">HH", layout, 0) + struct.pack(">%dI" % len(words), *(v & 0xFFFFFFFF for v in words))
            + b"".join(struct.pack(">I", v) for v in extra) + tail)


class Device:
    """A DN2 with a probe, in numbers: counters that advance with (fake) time."""

    TIMER = 99_000_000        # a guess; the page measures it, and nothing here depends on it

    def __init__(self, isr=0.51, peak=0.74, switches=575.0, fps=1500.0, per_request=0.0, layout=1):
        self.isr, self.peak, self.switches, self.fps = isr, peak, switches, fps
        self.layout = layout
        self.lfo4 = None          # (base, bytearray) of a profiling build's lfo4 block, if any
        self.regions = []         # more (base, bytearray) memory PEEK can read
        self.per_request = per_request
        self.t = 0.0
        self.c = {k: 0 for k in dn2stats.ALL_WORDS}
        self.c.update(hash0=1, hash1=2, hash2=3, hash3=4)
        self.frac = {"frames": 0.0, "switches": 0.0}
        self.extra = []

    def advance(self, dt):
        self.t += dt
        ticks = int(self.TIMER * dt)
        c = self.c
        c["dtcn0"] = (c["dtcn0"] + ticks) & 0xFFFFFFFF
        for key, rate in (("frames", self.fps), ("switches", self.switches)):
            self.frac[key] += rate * dt
            whole = int(self.frac[key])
            self.frac[key] -= whole
            c[key] += whole
        c["samples"] = c["frames"] * 32
        c["isr_ticks"] = (c["isr_ticks"] + int(ticks * self.isr)) & 0xFFFFFFFF
        c["isr_count"] = c["frames"]
        c["isr_max"] = int(self.peak * self.TIMER / self.fps)
        c["idle_ticks"] = (c["idle_ticks"] + int(ticks * 0.3)) & 0xFFFFFFFF
        for k in ("hash0", "hash1", "hash2"):
            c[k] = (c[k] * 31 + 7) & 0xFFFFFFFF      # the DSP link moving; USB audio in STILL
        if self.peak > 1.0:
            c["isr_over"] += max(1, int(self.fps * dt * 0.05))

    def answer(self, req):
        body = dn2probe.unpack7(req[len(dn2probe.HEADER):-1])
        seq, cmd = struct.unpack_from(">HB", body)
        if cmd == dn2probe.HELLO:
            return reply(seq, cmd, struct.pack(">HI", self.layout, self.c["frames"]) + b"usbprobe\0")
        if cmd == dn2probe.STATS:
            self.c["switches"] += int(self.per_request)
            return reply(seq, cmd, stats_payload(self.c, layout=self.layout, extra=self.extra))
        if cmd == dn2probe.PEEK:
            addr, n = struct.unpack_from(">IH", body, 3)
            for base, mem in ([self.lfo4] if self.lfo4 else []) + self.regions:
                if base <= addr and addr + n <= base + len(mem):
                    return reply(seq, cmd, struct.pack(">I", addr) + bytes(mem[addr - base:addr - base + n]))
        return reply(seq, cmd, b"", status=2)


# ---- the decoder ------------------------------------------------------------------

def test_the_emulators_replies_decode():
    h = dn2stats.decode_hello(dn2probe.parse(EMU_HELLO)["payload"])
    assert h["proto"] == 1 and h["tag"] == "usbprobe"
    a = dn2stats.decode(dn2probe.parse(EMU_STATS1)["payload"])
    b = dn2stats.decode(dn2probe.parse(EMU_STATS2)["payload"])
    assert a["layout"] == 1 and a["extra"] == [] and a["tail"] == b""
    assert b["words"]["isr_count"] - a["words"]["isr_count"] == 5
    assert b["words"]["frames"] - a["words"]["frames"] == 5
    assert b["words"]["hash0"] != a["words"]["hash0"]
    assert [b["words"]["hash%d" % i] for i in (1, 2, 3)] == [a["words"]["hash%d" % i] for i in (1, 2, 3)]


def test_layout_1_is_dn2probes_layout():
    assert dn2stats.V1_BYTES == dn2probe.STATS_BYTES == 60
    d = Device()
    d.advance(1.0)
    p = stats_payload(d.c)
    ours, theirs = dn2stats.decode(p), dn2probe.decode_stats(p)
    for k in dn2probe.STATS_FIELDS[2:]:
        assert ours["words"][k] == theirs[k]
    assert [ours["words"]["hash%d" % i] for i in range(4)] == theirs["hash"]


def test_unknown_trailing_fields_are_kept_raw():
    d = Device()
    p = stats_payload(d.c, layout=3, extra=(7, 0xDEADBEEF), tail=b"\x01\x02")
    s = dn2stats.decode(p)
    assert s["layout"] == 3 and s["extra"] == [7, 0xDEADBEEF] and s["tail"] == b"\x01\x02"
    assert "isr_over" in s["words"]                                # read with layout 2's table
    tr = dn2stats.Tracker()
    tr.feed(stats_payload(d.c, layout=3, extra=(7, 10)), 0.0)
    d.advance(0.1)
    r = tr.feed(stats_payload(d.c, layout=3, extra=(9, 5)), 0.1)
    assert [(x["offset"], x["value"], x["delta"]) for x in r["extra"]] == [(80, 9, 2), (84, 5, 0xFFFFFFFB)]
    assert "layout 3" in r["layout_note"] and "appends" in r["layout_note"]


def test_too_short_or_layout_0_is_refused():
    d = Device()
    with pytest.raises(dn2stats.LayoutError):
        dn2stats.decode(stats_payload(d.c)[:56])
    with pytest.raises(dn2stats.LayoutError):
        dn2stats.decode(stats_payload(d.c, layout=0))


def test_layout_2_is_ext_s_order_and_agrees_with_dn2probe():
    # ext.S's ext_stats copies isr_over, idle_in, idle_out, idle_offpc, idle_lastpc after the hashes
    assert dn2stats.LAYOUTS[2][len(dn2stats.V1_WORDS):] == (
        "isr_over", "idle_in", "idle_out", "idle_offpc", "idle_lastpc")
    assert dn2stats.HEADER_BYTES + 4 * len(dn2stats.LAYOUTS[2]) == dn2probe.STATS2_BYTES == 80
    d = Device(layout=2)
    d.c.update(isr_over=5, idle_in=6, idle_out=7, idle_offpc=8, idle_lastpc=0x400CEBE2)
    p = stats_payload(d.c, layout=2)
    ours, theirs = dn2stats.decode(p), dn2probe.decode_stats(p)
    for k in dn2probe.STATS2_FIELDS:
        assert ours["words"][k] == theirs[k]
    assert ours["extra"] == [] and ours["missing"] == []
    # a layout-2 reply cut back to layout 1's size keeps what it has and says so
    short = dn2stats.decode(p[:60])
    assert short["missing"] == list(dn2probe.STATS2_FIELDS) and "isr_over" not in short["words"]


# ---- the readings ---------------------------------------------------------------

def run(tr, d, seconds, hz=10, start=0.0):
    out, t = [], start
    for _ in range(int(seconds * hz)):
        d.advance(1 / hz)
        t += 1 / hz
        r = tr.feed(stats_payload(d.c), t)
        if r:
            out.append(r)
    return out, t


def test_readings_match_the_owners_figures():
    tr, d = dn2stats.Tracker(), Device(isr=0.51, peak=0.74, switches=575)
    tr.feed(stats_payload(d.c), 0.0)
    rs, _ = run(tr, d, 3)
    r = rs[-1]
    assert r["clock"] == "device" and r["window_full"]
    assert abs(r["frames_s"] - 1500) < 2
    assert abs(r["isr_avg"] - 51) < 0.2 and abs(r["isr_peak"] - 74) < 0.5
    assert abs(r["switches_s"] - 575) < 15
    assert abs(r["timer_mhz"] - Device.TIMER / 1e6) < 0.01
    assert r["link"] == ["moving", "moving", "moving", "STILL"]
    assert not r["late"] and r["late_intervals"] == 0
    assert r["reliable"] == {"cpu": False, "audio_out": True, "explains_cpu": False}
    assert "isr_over" not in r and "idle" not in r


def test_a_save_doubles_the_switches_and_late_frames_are_flagged():
    tr, d = dn2stats.Tracker(), Device()
    tr.feed(stats_payload(d.c), 0.0)
    _, t = run(tr, d, 2)
    d.switches, d.isr = 1200, 0.55                 # SAVE PROJECT
    rs, t = run(tr, d, 2, start=t)
    assert abs(rs[-1]["switches_s"] - 1200) < 20 and not rs[-1]["late"]
    d.peak = 1.10                                  # one frame's ISR past its frame
    rs, t = run(tr, d, 0.3, start=t)
    assert rs[-1]["late"] and "ISR peak" in rs[-1]["late_why"] and rs[-1]["late_intervals"] == 3
    d.peak, d.fps = 0.7, 1480                      # frames missed
    rs, t = run(tr, d, 1.5, start=t)
    assert rs[-1]["late"] and "frames/s" in rs[-1]["late_why"] and rs[-1]["low_episodes"] == 1
    d.fps = 1500
    rs, t = run(tr, d, 2, start=t)
    assert not rs[-1]["late"] and rs[-1]["low_episodes"] == 1


def test_layout_2_counts_isrs_over_a_frame_and_explains_cpu():
    tr, d = dn2stats.Tracker(), Device(layout=2)
    tr.feed(stats_payload(d.c, layout=2), 0.0)
    rs, t = run2(tr, d, 2)
    r = rs[-1]
    assert r["isr_over"] == 0 and r["isr_over_total"] == 0 and not r["late"]
    assert r["reliable"]["cpu"] is False and r["reliable"]["explains_cpu"]
    assert "never switched in" in r["cpu_verdict"]              # idle_in stayed 0
    d.peak = 1.10
    rs, t = run2(tr, d, 0.5, start=t)
    assert rs[-1]["isr_over"] > 0 and rs[-1]["late"] and "over a frame" in rs[-1]["late_why"]
    assert rs[-1]["isr_over_total"] > 0 and rs[-1]["isr_over_s"] > 0
    d.peak = 0.7
    for _ in range(20):                                        # the idle task runs, off its spin
        d.c["idle_in"] += 1
        d.c["idle_out"] += 1
        d.c["idle_offpc"] += 1
        d.c["idle_lastpc"] = 0x40001234
        rs, t = run2(tr, d, 0.1, start=t)
    assert "misses it" in rs[-1]["cpu_verdict"] and rs[-1]["idle"]["lastpc"] == "0x40001234"


def run2(tr, d, seconds, hz=10, start=0.0):
    out, t = [], start
    for _ in range(max(1, int(seconds * hz))):
        d.advance(1 / hz)
        t += 1 / hz
        r = tr.feed(stats_payload(d.c, layout=2), t)
        if r:
            out.append(r)
    return out, t


def test_cpu_is_trusted_from_protocol_3():
    """Protocol 3 times the prio-1 task's spin, the real idle loop (read on the instrument 2026-09-30)."""
    assert dn2stats.reliability(2, 2)["cpu"] is False
    assert dn2stats.reliability(3, 2)["cpu"] is True
    assert dn2stats.reliability(None, 2)["cpu"] is False


def test_no_timer_falls_back_to_the_host_clock():
    tr, d = dn2stats.Tracker(), Device()
    d.TIMER = 0
    tr.feed(stats_payload(d.c), 0.0)
    rs, _ = run(tr, d, 2)
    r = rs[-1]
    assert r["clock"] == "host" and r["isr_avg"] is None and r["timer_mhz"] is None
    assert abs(r["frames_s"] - 1500) < 20


def test_a_reboot_restarts_the_readings():
    tr, d = dn2stats.Tracker(), Device()
    tr.feed(stats_payload(d.c), 0.0)
    run(tr, d, 1)
    d2 = Device()                                  # counters from zero: frames went backwards
    d2.advance(0.1)
    assert tr.feed(stats_payload(d2.c), 1.2) is None


# ---- the poller -----------------------------------------------------------------

class Wire:
    """send() -> the device answers after `rtt` of fake time, unless it is stock."""

    def __init__(self, device=None, rtt=0.004):
        self.device, self.rtt = device, rtt
        self.pending, self.sent = [], []

    def send(self, data):
        self.sent.append(data)
        if self.device:
            self.pending.append((self.now + self.rtt, self.device.answer(data)))

    def deliver(self, poller, now):
        due = [p for p in self.pending if p[0] <= now]
        self.pending = [p for p in self.pending if p[0] > now]
        for t, raw in due:
            assert poller.on_sysex(raw, t)


def drive(poller, wire, device, seconds, t=0.0, dt=0.001):
    end = t + seconds
    while t < end:
        t += dt
        if device:
            device.advance(dt)
        wire.now = t
        poller.step(t)
        wire.deliver(poller, t)
    return t


def test_stock_firmware_is_absent_and_keeps_being_asked():
    events, wire = [], Wire(None)
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, t0=0.0)
    p.restart(0.0)
    drive(p, wire, None, 10)
    states = [e["state"] for e in events if e["type"] == "probe-status"]
    assert states[-1] == "absent"
    hellos = len(wire.sent)
    assert 5 <= hellos <= 7                        # 1/s for 3 s, then 1 per 3 s
    assert all(dn2probe.unpack7(s[6:-1])[2] == dn2probe.HELLO for s in wire.sent)
    assert not p.on_sysex(bytes.fromhex("F0 7E 7F 06 02 F7"), 1.0)   # not the probe's: the MIDI view's


def test_poller_finds_the_probe_polls_one_at_a_time_and_times_the_round_trip():
    d = Device()
    events, wire = [], Wire(d, rtt=0.004)
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, rate_hz=10, t0=0.0)
    p.restart(0.0)
    t = drive(p, wire, d, 3)
    assert p.state == "present"
    probes = [e for e in events if e["type"] == "probe"]
    assert 25 <= len(probes) <= 31
    last = probes[-1]
    assert abs(last["rtt_ms"] - 4) < 1.5 and abs(last["rate_hz"] - 10) <= 1
    assert last["rate_ceiling"] > 100
    p.set_rate(50)
    drive(p, wire, d, 2, t)
    last = [e for e in events if e["type"] == "probe"][-1]
    assert abs(last["rate_hz"] - 50) <= 3


def test_a_slow_round_trip_caps_the_rate():
    d = Device()
    events, wire = [], Wire(d, rtt=0.030)          # 30 ms: at most ~33 a second
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, rate_hz=50, t0=0.0)
    p.restart(0.0)
    drive(p, wire, d, 3)
    last = [e for e in events if e["type"] == "probe"][-1]
    assert 28 <= last["rate_hz"] <= 34 and abs(last["rate_ceiling"] - 33) <= 2
    assert not wire.pending or len(wire.pending) == 1        # never more than one in flight


def test_a_probe_that_stops_answering_is_lost():
    d = Device()
    events, wire = [], Wire(d)
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, t0=0.0)
    p.restart(0.0)
    t = drive(p, wire, d, 2)
    wire.device = None
    drive(p, wire, None, 3, t)
    states = [e["state"] for e in events if e["type"] == "probe-status"]
    assert "present" in states and states[-1] == "lost"


def test_calibration_measures_switches_per_request():
    d = Device(switches=500, per_request=3)
    events, wire = [], Wire(d)
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, t0=0.0)
    p.restart(0.0)
    t = drive(p, wire, d, 2)
    p.calibrate(low=5, high=25, phase_s=4, settle_s=1.5)
    drive(p, wire, d, 9, t)
    cost = [e for e in events if e["type"] == "probe-cost"]
    assert cost and abs(cost[-1]["per_request"] - 3) < 0.4
    assert abs(cost[-1]["background"] - 500) < 20
    last = [e for e in events if e["type"] == "probe"][-1]
    assert "switches_net" in last


def test_poller_reads_lfo4_timers_by_peek_after_each_stats():
    sym = {"lfo4_prof_skip_b": 0x46802BD0, "lfo4_prof_skip_a": 0x46802BD4,
           "lfo4_prof_memset_calls": 0x46802BD8, "lfo4_prof_memcpy_calls": 0x46802BDC,
           "lfo4_prof_prev_max": 0x46802BE0, "lfo4_prof": 0x46802BF4}   # the owner's build's
    path = pathlib.Path(__file__).parent / "_lfo4_symbols.json"
    lo, n, offsets = None, None, None
    try:
        path.write_text(json.dumps({k: hex(v) for k, v in sym.items()}), encoding="utf-8")
        lo, n, offsets = dn2probe.lfo4_layout(str(path))
    finally:
        path.unlink()
    assert (lo, n) == (0x46802BD0, 136)
    d = Device(layout=2)
    mem = bytearray(n)
    d.lfo4 = (lo, mem)
    events, wire = [], Wire(d)
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, t0=0.0, lfo4=(lo, n, offsets))
    p.restart(0.0)

    def save_calls(k):                         # on_save: count k, ticks 1320 each (10 us at 132 MHz)
        struct.pack_into(">5I", mem, offsets["lfo4_prof"], k, 1320 * k, 1320, 0, 1320)
        struct.pack_into(">I", mem, offsets["lfo4_prof_skip_a"], 2400 * k)
    save_calls(0)
    t = drive(p, wire, d, 2)
    save_calls(100)
    drive(p, wire, d, 0.3, t)
    lf = [e for e in events if e["type"] == "probe-lfo4"]
    assert lf and any(e["pieces"]["on_save"]["n"] == 100 for e in lf)
    hit = next(e for e in lf if e["pieces"]["on_save"]["n"] == 100)
    # 132,000 ticks at the fake device's 99 MHz timer: 1333 us
    assert abs(hit["pieces"]["on_save"]["us"] / (132000 / Device.TIMER * 1e6) - 1) < 0.01
    assert hit["fast"]["skip_a"] == 240000
    peeks = [s for s in wire.sent if dn2probe.unpack7(s[6:-1])[2] == dn2probe.PEEK]
    stats = [s for s in wire.sent if dn2probe.unpack7(s[6:-1])[2] == dn2probe.STATS]
    assert abs(len(peeks) - len(stats)) <= 1                       # one PEEK per STATS
    assert len(wire.pending) <= 1


# ---- the watches -------------------------------------------------------------------

def frame_image(track, values):
    """A frame as the ColdFire holds it: big-endian words at dnfw.waverider.frame's offsets."""
    from dnfw.waverider import frame as wrframe
    img = bytearray(wrframe.FRAME_BYTES)
    for p, v in values.items():
        struct.pack_into(">H", img, wrframe.slot_offset(track - 1, p), v)
    return img


def test_a_frame_watch_names_the_tracks_fields_at_the_frames_offsets():
    from dnfw.waverider import frame as wrframe
    w = dn2watch.parse("frame:1")
    by = {f.name: f for f in w.fields}
    assert by["TUN1"].addr == 0x80005E60 + 218 and by["WAV1"].addr == 0x80005E60 + 220
    assert by["TBL1"].addr == 0x80005E60 + 222 and by["TUN2"].addr == 0x80005E60 + 230
    assert by["NOTE"].addr == 0x80005E60 + wrframe.NOTE
    assert w.spans == ((0x80005E62, 248),)                  # one PEEK for track 1
    w16 = dn2watch.parse("frame:16")
    assert len(w16.spans) == 2 and all(n <= dn2probe.PEEK_MAX for _, n in w16.spans)
    assert dict((f.name, f.addr) for f in w16.fields)["TUN1"] == 0x80005E60 + 218 + 146 * 15
    for bad in ("frame:0", "frame:17", "frame:x", "0x80005e60", "0x80005e60+3", "0x10000000+4",
                "0x80005e60+4:f32"):
        with pytest.raises(ValueError):
            dn2watch.parse(bad)


def test_a_frame_watch_reads_what_the_probe_read_on_the_instrument():
    """The 2026-09-30 readings: TUN1 +12 = 0x4c00, WAV1 top = 0x7800, TBL1 1 = 0x0100."""
    w = dn2watch.parse("frame:1")
    img = frame_image(1, {25: 0x4C00, 26: 0x7800, 27: 0x0100, 31: 0x3400})
    reads = {lo: bytes(img[lo - 0x80005E60:lo - 0x80005E60 + n]) for lo, n in w.spans}
    v = {x["name"]: x for x in w.decode(reads)}
    assert v["TUN1"]["semitones"] == 12 and v["TUN1"]["hex"] == "0x4c00"
    assert v["TUN2"]["semitones"] == -12
    assert v["WAV1"]["word"] == 0x7800 and v["WAV1"]["coarse_fine"] == 120
    assert v["TBL1"]["coarse_fine"] == 1 and "semitones" not in v["TBL1"]
    assert "TUN1=0x4c00(+12 st)" in dn2watch.summary(list(v.values()))


def test_a_raw_watch_reads_words_of_its_format():
    w = dn2watch.parse("0x800068e4+8:s16")
    assert [f.name for f in w.fields] == ["+0", "+2", "+4", "+6"] and w.spans == ((0x800068E4, 8),)
    vals = w.decode({0x800068E4: struct.pack(">4h", 1, -1, 300, -300)})
    assert [v["word"] for v in vals] == [1, -1, 300, -300]
    raw = dn2watch.parse("0x46700000+8:u32").decode({0x46700000: bytes.fromhex("00000005ffffffff")})
    assert [v["word"] for v in raw] == [5, 0xFFFFFFFF]


def test_poller_reads_the_watches_after_each_stats_and_says_what_changed():
    d = Device()
    img = frame_image(1, {25: 0x4000, 26: 0x0000})
    d.regions.append((0x80005E60, img))
    events, wire = [], Wire(d)
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, rate_hz=10, t0=0.0,
                       watches=[dn2watch.parse("frame:1"), dn2watch.parse("0x80005e60+4")])
    p.restart(0.0)
    t = drive(p, wire, d, 2)
    struct.pack_into(">H", img, 218, 0x4100)                # the owner turns TUN1 to +1
    drive(p, wire, d, 0.5, t)
    ws = [e for e in events if e["type"] == "probe-watch"]
    fr = [e for e in ws if e["name"] == "frame:1"]
    assert fr and {e["name"] for e in ws} == {"frame:1", "0x80005e60+4"}
    tun = [next(v for v in e["values"] if v["name"] == "TUN1") for e in fr]
    assert tun[0]["semitones"] == 0 and tun[-1]["semitones"] == 1
    assert sum(1 for e in fr if e["changed"] == ["TUN1"]) == 1
    stats = [s for s in wire.sent if dn2probe.unpack7(s[6:-1])[2] == dn2probe.STATS]
    peeks = [s for s in wire.sent if dn2probe.unpack7(s[6:-1])[2] == dn2probe.PEEK]
    assert abs(len(peeks) - 2 * len(stats)) <= 2            # one span each, after every STATS
    assert len(wire.pending) <= 1                           # still one in flight
    assert not [e for e in events if e["type"] == "probe-error"]
    p.set_watches([])
    n = len(ws)
    drive(p, wire, d, 0.5, t + 0.5)
    assert len([e for e in events if e["type"] == "probe-watch"]) <= n + 2
    with pytest.raises(ValueError):
        p.set_watches([dn2watch.parse("frame:%d" % k) for k in range(1, 10)])


def test_a_refused_watch_is_said_and_does_not_slow_the_poll():
    d = Device()
    d.regions.append((0x80005E60, frame_image(1, {25: 0x4000})))
    events, wire = [], Wire(d, rtt=0.004)
    wire.now = 0.0
    p = dn2poll.Poller(wire.send, events.append, rate_hz=10, t0=0.0,
                       watches=[dn2watch.parse("0x800068e4+32"), dn2watch.parse("frame:1")])
    p.restart(0.0)
    drive(p, wire, d, 3)
    last = [e for e in events if e["type"] == "probe"][-1]
    assert abs(last["rate_hz"] - 10) <= 1 and last["lost_replies"] == 0
    errs = [e["error"] for e in events if e["type"] == "probe-error"]
    assert errs and "0x800068e4+32, 0x800068e4 +32" in errs[-1]
    assert [e for e in events if e["type"] == "probe-watch" and e["name"] == "frame:1"]


# ---- the log ---------------------------------------------------------------------

def test_log_rows(tmp_path):
    log = dn2log.RunLog(tmp_path, stamp="t")
    tr, d = dn2stats.Tracker(), Device()
    tr.feed(stats_payload(d.c), 0.0)
    d.advance(0.1)
    r = tr.feed(stats_payload(d.c, layout=3, extra=(42,)), 0.1)
    r["type"] = "probe"
    log.write(r)
    log.write({"type": "mark", "t": 0.2, "label": "save pressed"})
    w = dn2watch.parse("frame:1")
    img = frame_image(1, {25: 0x4C00})
    vals = w.decode({lo: bytes(img[lo - 0x80005E60:lo - 0x80005E60 + n]) for lo, n in w.spans})
    log.write({"type": "probe-watch", "t": 0.25, "name": "frame:1", "values": vals, "changed": ["TUN1"]})
    log.write({"t": 0.3, "kind": "cc", "ch": 1, "d1": 7, "d2": 64, "raw": "b0 07 40"})
    log.close()
    rows = (tmp_path / "t.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split(",")[:3] == ["t", "kind", "label"] and len(rows) == 4
    assert ",probe," in rows[1] and "+80=42/" in rows[1]
    assert rows[2].startswith("0.2,mark,save pressed")
    assert rows[3].startswith("0.25,watch,frame:1,TUN1,") and "TUN1=0x4c00(+12 st)" in rows[3]
    assert len((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()) == 4


# ---- the server, with a fake port ------------------------------------------------

class FakePort:
    """dn2port.Dn2Port's surface over a Device, answering in real time."""

    def __init__(self, device):
        self.device, self.shorts, self.sysex = device, [], []
        self.t = time.time()

    def service(self):
        now = time.time()
        self.device.advance(now - self.t)
        self.t = now

    def send(self, data):
        self.service()
        self.sysex.append((time.time(), self.device.answer(data)))

    def close(self):
        pass


def sse(conn_host, port, want, timeout=8.0):
    """Read the SSE stream until `want(events)` or the timeout."""
    c = http.client.HTTPConnection(conn_host, port, timeout=timeout)
    c.request("GET", "/events")
    resp = c.getresponse()
    events, name, end = [], None, time.time() + timeout
    while time.time() < end and not want(events):
        line = resp.fp.readline().decode().rstrip("\n")
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            events.append((name or "message", json.loads(line[6:])))
            name = None
    c.close()
    return events


def get(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path)
    body = c.getresponse().read()
    c.close()
    return body


@pytest.mark.skipif(sys.platform != "win32", reason="midi_live loads winmm at import")
def test_server_streams_probe_and_midi_but_not_the_probes_sysex(tmp_path):
    import dn2live
    from http.server import ThreadingHTTPServer

    dev = Device()
    dev.regions.append((0x80005E60, frame_image(1, {25: 0x4C00})))
    port = FakePort(dev)
    live = dn2live.Live(lambda: (port, ("[0] fake in", "[0] fake out")), log_dir=tmp_path)
    live.start()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dn2live.handler(live))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    http_port = srv.server_address[1]
    try:
        page = get(http_port, "/").decode()
        assert "/panel.js" in page and "/panel.css" in page and "DN2 Live" in page
        assert b"use strict" in get(http_port, "/panel.js")

        def midi_later():
            time.sleep(1.2)
            port.shorts.append((time.time(), 0x4007B0))               # CC7 = 64 on ch 1
            port.sysex.append((time.time(), bytes.fromhex("F0 7E 7F 06 02 00 F7")))
            get(http_port, "/mark?label=save%20pressed")
        threading.Thread(target=midi_later, daemon=True).start()

        def done(evs):
            names = [n for n, _ in evs]
            kinds = [e.get("kind") for n, e in evs if n == "message"]
            return names.count("probe") >= 5 and "mark" in names and "sysex" in kinds and "cc" in kinds
        evs = sse("127.0.0.1", http_port, done)
        names = [n for n, _ in evs]
        assert names[0] == "state" and names[1] == "backlog"
        assert "probe-status" in names or evs[0][1]["status"]["state"] in ("searching", "present")
        midi = [e for n, e in evs if n == "message"]
        assert any(e.get("kind") == "cc" and e["d1"] == 7 and e["d2"] == 64 for e in midi)
        sx = [e for e in midi if e.get("kind") == "sysex"]
        assert sx and all(not e["raw"].startswith("f0 00 20 3c 7d") for e in sx)
        probes = [e for n, e in evs if n == "probe"]
        assert abs(probes[-1]["isr_avg"] - 51) < 1

        st = json.loads(get(http_port, "/watch?add=frame:1"))
        assert st["ok"] and st["watches"] == ["frame:1"]
        assert not json.loads(get(http_port, "/watch?add=frame:1"))["ok"]            # already watched
        assert "1..16" in json.loads(get(http_port, "/watch?add=frame:99"))["message"]
        evs = sse("127.0.0.1", http_port, lambda e: any(n == "probe-watch" for n, _ in e))
        wv = next(e for n, e in evs if n == "probe-watch")
        assert next(v for v in wv["values"] if v["name"] == "TUN1")["semitones"] == 12
        assert json.loads(get(http_port, "/watch?drop=frame:1"))["watches"] == []

        r = json.loads(get(http_port, "/rate?hz=50"))
        assert r["rate_hz"] == 10 and "capped" in r["message"]
        st = json.loads(get(http_port, "/midi?on=0"))
        assert st["midi_on"] is False
        assert json.loads(get(http_port, "/rate?hz=50"))["rate_hz"] == 50
        port.shorts.append((time.time(), 0x5090))                      # a note while the view is off
        time.sleep(0.3)
        json.loads(get(http_port, "/midi?on=1"))
        assert live.poller.rate_hz == 10                               # back under the cap
    finally:
        srv.shutdown()
        live.close()
    rows = live.log.csv_path.read_text(encoding="utf-8")
    assert ",mark,save pressed" in rows and ",probe," in rows
    lines = live.log.jsonl_path.read_text(encoding="utf-8").splitlines()
    assert not any('"note-on"' in ln for ln in lines)                  # dropped while the view was off

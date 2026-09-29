"""Ask the probe for STATS at a set rate, time every round trip, and say what it answered.

derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

One job: the conversation with the probe. It sends (HELLO to find it, then
STATS), takes the probe's replies from whoever holds the port (`on_sysex`,
which returns False for any SysEx that is not the probe's, so the MIDI view
keeps it), and publishes events:

    {'type': 'probe-status', 'state': 'searching' | 'present' | 'absent' | 'lost', ...}
    {'type': 'probe', ...}          one reading per STATS reply (dn2stats.Tracker's,
                                    plus the round trip and the achieved rate)
    {'type': 'probe-cost', ...}     a calibration's result: context switches per request
    {'type': 'probe-lfo4', ...}     a profiling build's lfo4 timers, per STATS (with --symbols)
    {'type': 'probe-error', ...}    a reply that could not be read, and why

**One request in flight, never more.** STATS goes out when the previous one
has been answered (or given up on after `GIVE_UP` s) *and* the period has
passed. So the achieved rate is `min(asked, 1 / round trip)` by construction,
requests never queue up in the driver or on the device, and each reply's
round trip is measured from its own request (matched by seq).

**What a request costs the instrument** (`csrc/usbprobe/probe.S`): the probe
answers from the SysEx router, **in the MIDI input task, not the audio ISR**.
Interrupts are masked only for the copy of ten counters (label 20, `move.w
#0x2700,%sr` .. `move.w %d7,%sr`); the four link hashes (about 13.6 KB read),
pack7 and the send run at task level, where the audio ISR preempts them. So
polling does not add to the ISR figures it reads; what it adds is **task
switches** (the MIDI input task waking per request, and whatever the USB send
wakes) and a little task-level CPU. `Calibration` measures the switches: it
polls at a low and a high rate, and the slope of switches/s against the
achieved rate is the cost of one request.

**lfo4's timers** (a build made with `scripts/build_lfo4_profile.py`) are not
in STATS: they sit in lfo4's BSS, and are read with one PEEK (136 bytes) right
after each STATS reply, at the addresses in the build's `symbols.json`
(`dn2probe.lfo4_layout`, `decode_lfo4`, as `dn2probe.py watch` does). That is a
second request per reading, still one in flight at a time, so it halves the
rate the round trip allows and doubles the probe's own cost.

**States.** `searching`: HELLO once a second since the port opened. `absent`:
three seconds of that with no answer -- stock firmware, or a probe build with
USB CONFIG not on USB MIDI / Overbridge; HELLO goes on every three seconds, so
flashing a probe build and pressing Reopen port finds it. `present`: HELLO
answered, STATS flowing. `lost`: a present probe stopped answering for two
seconds (a reflash, a freeze, the cable) -- back to searching.

Every command it sends only reads (the probe has no command that writes).
`step(now)` does one tick and `run()` is the loop around it, so the tests drive
it with a fake port and fake time.
"""
from __future__ import annotations

import threading
import time
from collections import deque

import dn2probe
import dn2stats

SEARCH_EVERY, SEARCH_FOR, ABSENT_EVERY, LOST_AFTER = 1.0, 3.0, 3.0, 2.0
GIVE_UP = 0.5                  # a STATS unanswered this long is counted lost, and the next goes out
RATES = (10, 25, 50)           # what the page offers; 10 is the default and the cap with MIDI on
DEFAULT_HZ = 10


class Calibration:
    """Two phases at two rates -> context switches per STATS request.

    `s = background + k * rate`: with the instrument otherwise steady (the
    same pattern playing, or stopped, and no one touching it), the slope `k`
    between a low and a high phase is what one request costs. Each phase's
    first second is discarded (the 1 s window still holds the previous rate)."""

    def __init__(self, low: float = 5.0, high: float = 25.0, phase_s: float = 5.0, settle_s: float = 1.5):
        self.phases = [low, high]
        self.phase_s, self.settle_s = phase_s, settle_s
        self.i = 0
        self.started: float | None = None
        self.samples: list[list[tuple[float, float]]] = [[], []]

    def rate(self) -> float:
        return self.phases[self.i]

    def feed(self, now: float, achieved: float | None, switches_s: float | None) -> dict | None:
        """One reading. -> the result once both phases are done, else None."""
        if self.started is None:
            self.started = now
        age = now - self.started
        if age >= self.settle_s and achieved and switches_s is not None:
            self.samples[self.i].append((achieved, switches_s))
        if age < self.phase_s:
            return None
        if self.i == 0:
            self.i, self.started = 1, now
            return None
        (r1, s1), (r2, s2) = (_mean(p) for p in self.samples)
        ok = None not in (r1, s1, r2, s2) and abs(r2 - r1) > 1
        k = (s2 - s1) / (r2 - r1) if ok else None
        return {'type': 'probe-cost', 'low_hz': round(r1, 2) if r1 else r1,
                'high_hz': round(r2, 2) if r2 else r2,
                'switches_low': _r(s1), 'switches_high': _r(s2),
                'per_request': _r(k, 2),
                'background': _r(s1 - k * r1) if k is not None else None}


def _mean(pairs):
    if not pairs:
        return None, None
    return (sum(p[0] for p in pairs) / len(pairs), sum(p[1] for p in pairs) / len(pairs))


def _r(v, nd=1):
    return None if v is None else round(v, nd)


class Poller:
    def __init__(self, send, publish, rate_hz: float = DEFAULT_HZ, t0: float | None = None,
                 lfo4: tuple | None = None):
        self.send = send
        self.lfo4 = lfo4           # (start, length, offsets) from dn2probe.lfo4_layout, or None
        if lfo4 and not dn2probe.peek_allowed(lfo4[0], lfo4[1]):
            raise ValueError('lfo4 profile block 0x%08x+%d is outside what PEEK allows' % lfo4[:2])
        self.publish = publish
        self.t0 = time.time() if t0 is None else t0
        self.tracker = dn2stats.Tracker()
        self.lock = threading.Lock()
        self.seq = 0x300
        self.status: dict = {}
        self.cost: dict | None = None
        self.calibration: Calibration | None = None
        self.rate_hz = float(rate_hz)
        self.restart()

    # ---- rate ---------------------------------------------------------------

    def set_rate(self, hz: float) -> float:
        with self.lock:
            self.rate_hz = max(0.5, min(float(hz), max(RATES)))
            self.calibration = None
            self._set(self.state, time.time())
            return self.rate_hz

    def calibrate(self, **kw) -> None:
        with self.lock:
            self.calibration = Calibration(**kw)
            self._set(self.state, time.time())

    def _period(self) -> float:
        return 1.0 / (self.calibration.rate() if self.calibration else self.rate_hz)

    # ---- state --------------------------------------------------------------

    def restart(self, now: float | None = None) -> None:
        """Forget the probe and look for it again (after a reopen, or at start)."""
        now = time.time() if now is None else now
        with self.lock:
            self._forget(now)
            self._set('searching', now)

    def _forget(self, now: float) -> None:
        self.search_from = now
        self.last_hello = None
        self.last_reply = None
        self.inflight: tuple[int, float, str] | None = None    # (seq, sent at, 'stats' | 'peek')
        self.lfo4_prev: dict | None = None
        self.last_sent = None
        self.rtts: deque = deque(maxlen=64)
        self.arrivals: deque = deque()
        self.lost_replies = 0
        self.tracker.reset()
        self.tracker.hello = None

    def _set(self, state: str, now: float, **more) -> None:
        h = self.tracker.hello
        self.state = state
        self.status = {'type': 'probe-status', 'state': state, 't': self._rel(now),
                       'proto': h and h['proto'], 'tag': h and h['tag'],
                       'boot_s': h and round(h['frames'] / dn2stats.FRAMES_PER_S, 1),
                       'rate_hz': self.rate_hz, 'rates': list(RATES),
                       'calibrating': self.calibration is not None,
                       'reliable': dn2stats.reliability(h and h['proto'], None), **more}
        self.publish(dict(self.status))

    def _rel(self, now: float) -> float:
        return round(now - self.t0, 3)

    # ---- out ----------------------------------------------------------------

    def _ask(self, builder, now: float) -> int:
        self.seq = (self.seq + 1) & 0xFFFF or 1
        try:
            self.send(builder(self.seq))
        except OSError as exc:            # a port gone deaf after a flash: say so, keep going
            self.publish({'type': 'probe-error', 't': self._rel(now), 'error': str(exc)})
        return self.seq

    def step(self, now: float) -> None:
        with self.lock:
            st = self.state
            if st == 'present':
                if self.last_reply is not None and now - self.last_reply > LOST_AFTER:
                    self._forget(now)
                    self._set('lost', now)
                    return
                if self.inflight and now - self.inflight[1] > GIVE_UP:
                    self.lost_replies += 1
                    self.inflight = None
                if self.inflight is None and (self.last_sent is None
                                              or now - self.last_sent >= self._period()):
                    self.last_sent = now
                    self.inflight = (self._ask(dn2probe.req_stats, now), now, 'stats')
                return
            if st in ('searching', 'lost') and now - self.search_from >= SEARCH_FOR:
                self._set('absent', now)
                st = 'absent'
            every = ABSENT_EVERY if st == 'absent' else SEARCH_EVERY
            if self.last_hello is None or now - self.last_hello >= every:
                self.last_hello = now
                self._ask(dn2probe.req_hello, now)

    def run(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            self.step(time.time())
            time.sleep(0.001)

    # ---- in -----------------------------------------------------------------

    def on_sysex(self, raw: bytes, now: float) -> bool:
        """A SysEx from the port. True if it was the probe's (and is handled here)."""
        raw = bytes(raw)
        if not raw.startswith(dn2probe.HEADER):
            return False
        r = dn2probe.parse(raw)
        if r is None:
            self.publish({'type': 'probe-error', 't': self._rel(now),
                          'error': 'a probe-channel message that is not a reply',
                          'raw': raw[:48].hex(' ')})
            return True
        with self.lock:
            self.last_reply = now
            if r['status']:
                self.publish({'type': 'probe-error', 't': self._rel(now),
                              'error': 'the probe answered 0x%02x with status %d (%s)'
                              % (r['cmd'], r['status'], dn2probe.STATUS.get(r['status'], '?'))})
                return True
            cmd = r['cmd'] & 0x7F
            try:
                if cmd == dn2probe.HELLO:
                    self._hello(r['payload'], now)
                elif cmd == dn2probe.STATS and self.state == 'present':
                    self._stats(r, now)
                    if self.lfo4 and self.inflight is None:
                        lo, n, _ = self.lfo4
                        self.inflight = (self._ask(lambda q: dn2probe.req_peek(q, lo, n), now), now, 'peek')
                elif cmd == dn2probe.PEEK and self.state == 'present':
                    self._peek(r, now)
            except ValueError as exc:
                self.publish({'type': 'probe-error', 't': self._rel(now), 'error': str(exc),
                              'raw': r['payload'][:96].hex(' ')})
        return True

    def _hello(self, payload: bytes, now: float) -> None:
        if self.state == 'present':
            return                      # a late answer to a search HELLO: nothing new
        h = dn2stats.decode_hello(payload)
        self._forget(now)
        self.last_reply = now
        self.tracker.hello = h
        self._set('present', now)

    def _stats(self, r: dict, now: float) -> None:
        rtt = None
        if self.inflight and self.inflight[0] == r['seq'] and self.inflight[2] == 'stats':
            rtt = now - self.inflight[1]
            self.rtts.append(rtt)
            self.inflight = None
        self.arrivals.append(now)
        while self.arrivals and self.arrivals[0] <= now - 1.0:
            self.arrivals.popleft()
        ev = self.tracker.feed(r['payload'], now)
        if not ev:
            return
        first = self.tracker.first_host
        span = now - first if first is not None else 0
        achieved = len(self.arrivals) / min(1.0, span) if span >= 0.2 else None
        rtts = sorted(self.rtts)
        ev.update({'type': 'probe', 't': self._rel(now),
                   'rtt_ms': _r(rtt * 1000, 2) if rtt is not None else None,
                   'rtt_med_ms': _r(rtts[len(rtts) // 2] * 1000, 2) if rtts else None,
                   'rtt_max_ms': _r(rtts[-1] * 1000, 2) if rtts else None,
                   'rate_asked': round(1 / self._period(), 2),
                   'rate_hz': _r(achieved, 1),
                   'rate_ceiling': _r(1 / rtts[len(rtts) // 2], 0) if rtts else None,
                   'lost_replies': self.lost_replies})
        if self.cost and self.cost.get('per_request') is not None and achieved:
            own = self.cost['per_request'] * achieved
            ev['switches_probe'] = _r(own, 0)
            if ev['switches_s'] is not None:
                ev['switches_net'] = _r(ev['switches_s'] - own, 0)
        self.publish(ev)
        if self.calibration:
            res = self.calibration.feed(now, achieved, ev['switches_s'])
            if res:
                res['t'] = self._rel(now)
                self.cost = res
                self.calibration = None
                self.publish(res)
                self._set(self.state, now)

    def _peek(self, r: dict, now: float) -> None:
        if self.inflight and self.inflight[0] == r['seq'] and self.inflight[2] == 'peek':
            self.inflight = None
        if not self.lfo4:
            return
        p = dn2probe.decode_peek(r['payload'])
        lo, n, offsets = self.lfo4
        if p['addr'] != lo or len(p['data']) != n:
            raise ValueError('lfo4 PEEK came back at 0x%08x +%d, not 0x%08x +%d'
                             % (p['addr'], len(p['data']), lo, n))
        cur = dn2probe.decode_lfo4(p['data'], offsets)
        prev, self.lfo4_prev = self.lfo4_prev, cur
        if prev is None:
            return
        hz = self.tracker.timer_hz(now)
        us = (lambda ticks: round(ticks / hz * 1e6, 1)) if hz else (lambda ticks: None)
        pieces = {}
        for name in dn2probe.LFO4_PIECES:
            a, b = prev[name], cur[name]
            pieces[name] = {'n': (b['count'] - a['count']) & 0xFFFFFFFF,
                            'us': us((b['ticks'] - a['ticks']) & 0xFFFFFFFF),
                            'peak_us': us(b['recent_max']), 'max_us': us(b['max']),
                            'count': b['count']}
        fast = {k: (cur[k] - prev[k]) & 0xFFFFFFFF
                for k in ('memcpy_calls', 'memset_calls', 'skip_a', 'skip_b')}
        self.publish({'type': 'probe-lfo4', 't': self._rel(now), 'pieces': pieces, 'fast': fast,
                      'clock': 'device' if hz else None})

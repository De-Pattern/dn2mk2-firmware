"""The probe's STATS replies -> live readings: decoded by layout, differenced, rated.

derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

One job: turn a stream of STATS payloads (and the HELLO before them) into the
figures `tools/dn2live.py` puts on the page and in the log. No port, no thread,
no clock of its own: every call is handed the host time the reply arrived, so
this imports anywhere and is tested with byte strings.

**Layouts, by table** (`LAYOUTS`, `FIELDS`). A STATS payload is `u16 layout,
u16 0`, then big-endian u32 words (`csrc/usbprobe/probe.S`, label 20). The
names come from `tools/dn2probe.py` (`STATS_FIELDS`, `STATS2_FIELDS`), so the
codec there stays the one definition:

    layout 1  offsets 4..59   ten counters, four link hashes              (probe protocol 1)
    layout 2  offsets 60..79  APPENDED: isr_over, idle_in, idle_out,       (probe protocol 2,
                              idle_offpc, idle_lastpc (csrc/usbprobe/ext.S) layout 1 unchanged)

A reply is read with its own layout's table. A layout above the newest known
is read with the newest table, and every word past it is kept **raw** with its
per-reply difference (the page flags that it is assuming the newer layout
appends, as layouts 1 -> 2 did). A reply shorter than its layout's table keeps
the fields it has and says which are missing. Only a reply shorter than layout
1, or a layout of 0, is refused, because its words cannot be placed.

**What layout 2 does not carry**, though it was expected to: lfo4's per-piece
timers are in lfo4's BSS in a profiling build and are read by PEEK
(`dn2probe.lfo4_layout`, `dn2poll`), not in STATS; and the ISR's own time
cannot be split from time lost to nested interrupts with the probe's hooks
(docs/usbprobe.md, "Why layout 2": the level-6/7 handlers are not hooked).

**CPU and the fourth link hash, by layout.** Layout 2 does not fix CPU: it
adds the idle-task counters that say *why* it reads 100 %, so CPU stays marked
unreliable and the reading carries the counters' verdict (`cpu_verdict`). The
fourth hash was never broken: that window is the ColdFire -> SHARC USB-audio
stream, which the frame ISR zeroes every frame unless USB audio is streaming
in, so STILL is the right answer for every layout; it is labelled as such.

**Why rates come from the device's timer, not the host's clock.** At 10 Hz a
USB round trip jitters by milliseconds, which is several frames a second of
noise -- larger than the 1495 threshold the page watches. DTCN0 runs on the
ColdFire's clock and is copied in the same masked instant as the frame count,
so frames per DTCN0 tick is exact. Its rate in Hz is measured once, against the
host over the whole run, and every per-second figure divides device ticks by
it. With the timer stopped (the emulator) the host clock is used and the
reading says `clock: 'host'`.
"""
from __future__ import annotations

import struct
from collections import deque

import dn2probe

FRAMES_PER_S = dn2probe.FRAMES_PER_S
LINK = dn2probe.LINK
LATE_BELOW = 1495              # frames/s under this over a second: frames were missed
HEADER_BYTES = 4               # u16 layout, u16 0
HASHES = tuple('hash%d' % i for i in range(len(LINK)))
#: each layout's words after the header, in order; a later layout appends
LAYOUTS = {
    1: tuple(dn2probe.STATS_FIELDS[2:]) + HASHES,
    2: tuple(dn2probe.STATS_FIELDS[2:]) + HASHES + tuple(dn2probe.STATS2_FIELDS),
}
NEWEST = max(LAYOUTS)
V1_WORDS = LAYOUTS[1]
V1_BYTES = HEADER_BYTES + 4 * len(V1_WORDS)
ALL_WORDS = LAYOUTS[NEWEST]
#: name -> (from layout, unit, kind, meaning). kind: counter (cumulative, differenced),
#: peak (read-and-clear per STATS), value (a snapshot), hash (a change detector)
FIELDS = {
    'dtcn0':       (1, 'ticks', 'counter', 'DMA timer 0 at the copy'),
    'frames':      (1, 'frames', 'counter', 'audio frames since boot'),
    'samples':     (1, 'samples', 'counter', '+32 per frame'),
    'push_wait':   (1, 'frames', 'value', 'countdown before the first DSPI push, then 0'),
    'isr_ticks':   (1, 'ticks', 'counter', 'time in the audio-frame ISR'),
    'isr_count':   (1, 'ISRs', 'counter', 'ISRs timed'),
    'isr_max':     (1, 'ticks', 'peak', 'longest ISR since the previous STATS'),
    'isr_in_idle': (1, 'ticks', 'counter', 'ISR time inside idle intervals'),
    'idle_ticks':  (1, 'ticks', 'counter', 'time the idle task sat at its spin'),
    'switches':    (1, 'switches', 'counter', 'context switches'),
    'hash0':       (1, '', 'hash', LINK[0]),
    'hash1':       (1, '', 'hash', LINK[1]),
    'hash2':       (1, '', 'hash', LINK[2]),
    'hash3':       (1, '', 'hash', LINK[3]),
    'isr_over':    (2, 'ISRs', 'counter', 'ISRs longer than one frame (87,708 ticks at 132 MHz)'),
    'idle_in':     (2, 'switches', 'counter', 'switches into the idle task'),
    'idle_out':    (2, 'switches', 'counter', 'switches out of it'),
    'idle_offpc':  (2, 'switches', 'counter', '... whose resume PC was not the idle spin'),
    'idle_lastpc': (2, 'address', 'value', 'the last such resume PC'),
}
assert set(FIELDS) == set(ALL_WORDS)
COUNTERS = tuple(k for k in ALL_WORDS if FIELDS[k][2] == 'counter')
WINDOW_S = 1.0                 # the span the per-second figures are taken over
RESET_FRAMES = FRAMES_PER_S * 600   # more frames than this between replies: the device rebooted


class LayoutError(ValueError):
    pass


def decode(payload: bytes) -> dict:
    """A STATS payload -> {'layout', 'words': {name: u32}, 'missing', 'extra': [u32...], 'tail'}.

    `words` holds the fields of the reply's own layout (the newest known, for a
    layout above it) that the reply carries; `missing` names the ones it is too
    short for; `extra` is every whole u32 past the table; `tail` any 1..3 bytes
    after those."""
    p = bytes(payload)
    if len(p) < V1_BYTES:
        raise LayoutError('STATS reply of %d bytes: layout 1 needs %d' % (len(p), V1_BYTES))
    layout, pad = struct.unpack_from('>HH', p)
    if layout < 1:
        raise LayoutError('STATS layout %d: layouts start at 1' % layout)
    names = LAYOUTS[min(layout, NEWEST)]
    n = (len(p) - HEADER_BYTES) // 4
    vals = struct.unpack_from('>%dI' % n, p, HEADER_BYTES)
    return {'layout': layout, 'pad': pad, 'words': dict(zip(names, vals)),
            'missing': list(names[n:]), 'extra': list(vals[len(names):]),
            'tail': p[HEADER_BYTES + 4 * n:]}


def decode_hello(payload: bytes) -> dict:
    """HELLO -> {'proto', 'frames', 'tag'}; tolerant of a missing tag."""
    p = bytes(payload)
    if len(p) < 6:
        raise LayoutError('HELLO reply of %d bytes: needs 6' % len(p))
    return dn2probe.decode_hello(p)


def reliability(proto: int | None, layout: int | None) -> dict:
    """-> which figures the page may trust, for this probe version.

    CPU: not fixed by any layout so far (layout 2 adds the counters that
    explain it, not a corrected figure). The fourth hash: correct in every
    layout -- STILL means no USB audio is streaming in."""
    return {'cpu': False, 'audio_out': True,
            'explains_cpu': (layout or 0) >= 2}


def cpu_verdict(d: dict) -> str | None:
    """Layout 2's idle counters over an interval -> why CPU reads what it does."""
    if 'idle_in' not in d:
        return None
    if not d['idle_in'] and not d['idle_out']:
        return 'the idle task was never switched in: the CPU is never idle, so 100 % is real'
    if d['idle_out'] and d['idle_offpc'] == d['idle_out']:
        return ('the idle task runs but never leaves from its spin: the idle credit misses it, '
                'so CPU reads high falsely')
    return 'the idle task runs and is credited'


class Tracker:
    """Successive STATS -> one reading per reply, from the second reply on."""

    def __init__(self, window_s: float = WINDOW_S):
        self.window_s = window_s
        self.hello: dict | None = None
        self.reset()

    def reset(self) -> None:
        self.prev: dict | None = None
        self.first_host: float | None = None
        self.ticks = 0             # DTCN0 ticks since the first reply, unwrapped
        self.frames = 0            # frames since the first reply
        self.switches = 0
        self.over = 0              # ISRs over a frame since the first reply (layout 2)
        self.idle = {'idle_in': 0, 'idle_out': 0, 'idle_offpc': 0}   # the same, for the idle task
        self.hist: deque = deque()  # (host t, ticks, frames, switches, interval peak, over)
        self.changed: list[float | None] = [None] * len(LINK)
        self.late_intervals = 0    # replies whose ISR peak reached a frame, or with an ISR over one
        self.low_episodes = 0      # times frames/s fell under LATE_BELOW
        self._low = False
        self.replies = 0

    # ---- the clock ----------------------------------------------------------

    def timer_hz(self, now: float) -> float | None:
        """DTCN0's rate, measured against the host since the first reply."""
        if self.first_host is None:
            return None
        span = now - self.first_host
        if not self.ticks or span < 0.5:
            return None
        return self.ticks / span

    def _seconds(self, ticks: int, host_dt: float, now: float) -> tuple[float, str]:
        hz = self.timer_hz(now)
        if hz and ticks:
            return ticks / hz, 'device'
        return host_dt, 'host'

    # ---- one reply ------------------------------------------------------------

    def feed(self, payload: bytes, now: float) -> dict | None:
        """One STATS payload received at host time `now` -> a reading, or None for the first."""
        s = decode(payload)
        s['t'] = now
        self.replies += 1
        prev = self.prev
        if prev is not None:
            df = (s['words']['frames'] - prev['words']['frames']) & 0xFFFFFFFF
            if df > RESET_FRAMES:
                self.reset()
                self.replies = 1
                prev = None
        if prev is None:
            self.prev = s
            self.first_host = now
            self.hist.append((now, 0, 0, 0, None, 0))
            return None
        self.prev = s
        return self._reading(prev, s, now)

    def _reading(self, a: dict, b: dict, now: float) -> dict:
        wa, wb = a['words'], b['words']
        d = {k: (wb[k] - wa[k]) & 0xFFFFFFFF for k in COUNTERS if k in wa and k in wb}
        self.ticks += d['dtcn0']
        self.frames += d['frames']
        self.switches += d['switches']
        self.over += d.get('isr_over', 0)
        for k in self.idle:
            self.idle[k] += d.get(k, 0)
        t, n = d['dtcn0'], d['frames']

        isr_avg = d['isr_ticks'] / t if t else None
        # a frame's length in ticks: the run's average once it has a second of frames,
        # because one interval's own t/n is quantised to whole frames (+-3 % at 50 Hz)
        frame = (self.ticks / self.frames if self.frames >= FRAMES_PER_S
                 else (t / n if n else 0))
        isr_peak = wb['isr_max'] / frame if t and frame else None
        cpu = 1 - max(0, d['idle_ticks'] - d['isr_in_idle']) / t if t else None
        peak_hit = isr_peak is not None and isr_peak >= 1.0
        over_hit = bool(d.get('isr_over'))
        if peak_hit or over_hit:
            self.late_intervals += 1

        self.hist.append((now, self.ticks, self.frames, self.switches, isr_peak, self.over))
        while len(self.hist) > 2 and self.hist[1][0] <= now - self.window_s:
            self.hist.popleft()
        h0 = self.hist[0]
        full = now - h0[0] >= self.window_s * 0.9
        secs, clock = self._seconds(self.ticks - h0[1], now - h0[0], now)
        frames_s = (self.frames - h0[2]) / secs if secs > 0 else None
        switches_s = (self.switches - h0[3]) / secs if secs > 0 else None
        peaks = [h[4] for h in list(self.hist)[1:] if h[4] is not None]

        for i, key in enumerate(HASHES):
            if wa[key] != wb[key]:
                self.changed[i] = now
        since = now - self.first_host
        link = []
        for c in self.changed:
            if c is not None and now - c < self.window_s:
                link.append('moving')
            elif since >= self.window_s:
                link.append('STILL')
            else:
                link.append('waiting')

        low = bool(full and frames_s is not None and frames_s < LATE_BELOW)
        if low and not self._low:
            self.low_episodes += 1
        self._low = low
        hz = self.timer_hz(now)

        known = LAYOUTS[min(b['layout'], NEWEST)]
        extra_prev = a['extra']
        extra = [{'index': len(known) + i, 'offset': HEADER_BYTES + 4 * (len(known) + i),
                  'value': v,
                  'delta': ((v - extra_prev[i]) & 0xFFFFFFFF) if i < len(extra_prev) else None}
                 for i, v in enumerate(b['extra'])]
        note = None
        if b['layout'] > NEWEST:
            note = ('layout %d: read as layout %d plus %d unknown word(s), assuming it appends'
                    % (b['layout'], NEWEST, len(extra)))
        elif b['missing']:
            note = 'layout %d reply without %s' % (b['layout'], ', '.join(b['missing']))
        proto = self.hello['proto'] if self.hello else None
        why = [w for w, on in (('frames/s under %d' % LATE_BELOW, low),
                               ('ISR peak at or over 100 %', peak_hit),
                               ('%d ISR(s) over a frame' % d.get('isr_over', 0), over_hit)) if on]
        r = {
            't': round(now, 3),
            'layout': b['layout'],
            'layout_note': note,
            'clock': clock,
            'window_full': full,
            'frames': n,
            'frames_s': _r(frames_s, 1),
            'switches_s': _r(switches_s, 0),
            'isr_avg': _pct(isr_avg),
            'isr_peak': _pct(isr_peak),
            'isr_peak_1s': _pct(max(peaks)) if peaks else None,
            'cpu': _pct(cpu),
            'timer_mhz': _r(hz / 1e6, 3) if hz else None,
            'timer': bool(t),
            'link': link,
            'late': low or peak_hit or over_hit,
            'late_why': ', '.join(why),
            'late_intervals': self.late_intervals,
            'low_episodes': self.low_episodes,
            'reliable': reliability(proto, b['layout']),
            'extra': extra,
            'tail': b['tail'].hex(' ') if b['tail'] else '',
            'raw': dict(wb),
        }
        if 'isr_over' in d:
            r['isr_over'] = d['isr_over']
            r['isr_over_s'] = _r((self.over - h0[5]) / secs, 1) if secs > 0 else None
            r['isr_over_total'] = self.over
        if 'idle_in' in d:
            r['idle'] = {'in': d['idle_in'], 'out': d['idle_out'], 'offpc': d['idle_offpc'],
                         'in_total': self.idle['idle_in'], 'out_total': self.idle['idle_out'],
                         'offpc_total': self.idle['idle_offpc'],
                         'lastpc': '0x%08x' % wb['idle_lastpc']}
            # over the run, not one interval: an idle task that runs now and then
            # can miss a 100 ms interval entirely
            r['cpu_verdict'] = cpu_verdict(self.idle) if since >= self.window_s else None
        return r


def _r(v, nd):
    return None if v is None else round(v, nd)


def _pct(v):
    return None if v is None else round(100 * v, 2)

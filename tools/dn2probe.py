"""Read live ColdFire state from a Digitone II running a usbprobe build, over USB MIDI.

    python tools/dn2probe.py ports              the MIDI ports Windows sees
    python tools/dn2probe.py hello              is a probe answering, and which build
    python tools/dn2probe.py stats [N]          N readings, one a second: CPU, ISR load, DSP link
    python tools/dn2probe.py dsp [SECONDS]      is the DSP alive, at a glance
    python tools/dn2probe.py peek ADDR [LEN]    hex dump of DDR, the SRAM or the audio windows
    python tools/dn2probe.py watch [SECONDS] [--symbols out/<build>/symbols.json]
                                                10 readings a second: frames, ISR, lfo4's pieces
    python tools/dn2probe.py selftest           the codec, with no device

    options: --port "Digitone II" (a substring of the port name), or --in N --out N

derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

The probe answers its own SysEx channel: Elektron's manufacturer header with a
device byte (0x7D) no Elektron machine uses, so stock firmware drops the
messages and talking to it does nothing. Every command only reads; the probe
has no command that writes.

    request  F0 00 20 3C 7D 00 <pack7: u16 seq, u8 cmd, payload> F7
    reply    F0 00 20 3C 7D 00 <pack7: u16 seq, u8 cmd | 0x80, u8 status, payload> F7

Integers big-endian. Status 0 ok, 1 refused argument, 2 unknown command.
Windows only for the device (winmidi.py: winmm through ctypes, no packages);
the codec imports anywhere. **Windows lets one program at a time open a MIDI
port: close Elektron Transfer and DNX first.**

Divergences from digiusb.py: STATS is cumulative counters and link hashes,
differenced here, rather than a one-second snapshot; `dsp` is new; PEEK's
ranges are DN2 1.11's (docs/memory-map.md, docs/audio-dma.md), not the mk1's.
"""
import argparse
import struct
import sys
import time

HEADER = bytes([0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x00])
HELLO, STATS, PEEK = 0x01, 0x02, 0x03
STATUS = {0: 'ok', 1: 'refused', 2: 'unknown command'}
PEEK_MAX = 1024
# DN2 1.11: DDR (ACR0 maps 0x40000000-0x47ffffff), the 64 KB on-chip SRAM, and
# the SSI0 audio windows. Never 0xfc000000 (the MCF5441x peripherals) or
# 0xec000000 (the FPGA and DSPI window): a read there can clear a status bit.
PEEK_RANGES = ((0x40000000, 0x48000000), (0x80000000, 0x80010000), (0x4E6DF100, 0x4E6E1100))
FRAMES_PER_S = 1500           # the audio-frame ISR: 48 kHz in blocks of 32
# The fourth window is the ColdFire -> SHARC stream. The frame ISR zeroes it
# every frame (0x40026090, jsr 0x40133ebc with 0x800) unless a USB audio input
# is streaming (0x80005366), so "still" while a pattern plays is correct: it is
# idle, not stuck (read 2026-09-27, after the owner's first reading).
LINK = ('SHARC reply 0x800053a4', 'control frame 0x80005e60',
        'audio in 0x4e6df100', 'USB audio to the SHARC 0x4e6e0100')
STATS_FIELDS = ('layout', 'pad', 'dtcn0', 'frames', 'samples', 'push_wait',
                'isr_ticks', 'isr_count', 'isr_max', 'isr_in_idle', 'idle_ticks', 'switches')
STATS_FMT = '>HH10I4I'
STATS_BYTES = struct.calcsize(STATS_FMT)
# Layout 2 (probe protocol 2) appends these, after the four hashes, and
# changes nothing before them (csrc/usbprobe/ext.S, docs/usbprobe.md).
STATS2_FIELDS = ('isr_over', 'idle_in', 'idle_out', 'idle_offpc', 'idle_lastpc')
STATS2_FMT = '>5I'
STATS2_BYTES = STATS_BYTES + struct.calcsize(STATS2_FMT)
ISR_OVER_TICKS = 87708        # ext.S: one frame at 132.00 MHz / 1505 frames/s
# lfo4's timers in a profiling build (csrc/lfo4/profile.h), read by PEEK: five
# pieces of five u32 (count, ticks, max, window, window_max), then the fast
# path counts, from the build's symbols.json.
LFO4_PIECES = ('on_save', 'on_load', 'memcpy', 'memset', 'refresh')


def pack7(data):
    """8-bit -> 7-bit: a header byte holding the high bits of up to 7 bytes."""
    data = bytes(data)
    out = bytearray()
    for i in range(0, len(data), 7):
        grp = data[i:i + 7]
        hdr = 0
        for k, b in enumerate(grp):
            if b & 0x80:
                hdr |= 1 << (6 - k)
        out.append(hdr)
        out.extend(b & 0x7F for b in grp)
    return bytes(out)


def unpack7(data):
    """7-bit -> 8-bit (a partial last group is allowed)."""
    data = bytes(data)
    out = bytearray()
    i = 0
    while i < len(data):
        hdr = data[i]
        i += 1
        for k in range(1, 8):
            if i >= len(data):
                break
            out.append(data[i] | ((hdr << k) & 0x80))
            i += 1
    return bytes(out)


def request(seq, cmd, payload=b''):
    return HEADER + pack7(struct.pack('>HB', seq & 0xFFFF, cmd) + payload) + b'\xF7'


def req_hello(seq):
    return request(seq, HELLO)


def req_stats(seq):
    return request(seq, STATS)


def peek_allowed(addr, length):
    return 0 < length <= PEEK_MAX and any(lo <= addr and addr + length <= hi for lo, hi in PEEK_RANGES)


def req_peek(seq, addr, length):
    if not peek_allowed(addr, length):
        raise ValueError('0x%08x+%d: outside DDR 0x40000000-0x47ffffff, SRAM 0x80000000-0x8000ffff '
                         'and the audio windows 0x4e6df100-0x4e6e10ff, or not 1..%d bytes'
                         % (addr, length, PEEK_MAX))
    return request(seq, PEEK, struct.pack('>IH', addr, length))


def parse(sx):
    """A reply -> {'seq', 'cmd', 'status', 'payload'}, or None if it is not one."""
    sx = bytes(sx)
    if not sx.startswith(HEADER) or not sx.endswith(b'\xF7'):
        return None
    msg = unpack7(sx[len(HEADER):-1])
    if len(msg) < 4:
        return None
    seq, cmd, status = struct.unpack_from('>HBB', msg)
    return {'seq': seq, 'cmd': cmd, 'status': status, 'payload': msg[4:]}


def decode_hello(p):
    proto, frames = struct.unpack_from('>HI', p)
    return {'proto': proto, 'frames': frames,
            'tag': p[6:].split(b'\0')[0].decode('ascii', 'replace')}


def decode_stats(p):
    v = struct.unpack_from(STATS_FMT, p)
    d = dict(zip(STATS_FIELDS, v[:12]))
    d['hash'] = list(v[12:16])
    if d['layout'] >= 2 and len(p) >= STATS2_BYTES:
        d.update(zip(STATS2_FIELDS, struct.unpack_from(STATS2_FMT, p, STATS_BYTES)))
    return d


def decode_peek(p):
    addr, = struct.unpack_from('>I', p)
    return {'addr': addr, 'data': p[4:]}


def delta(a, b):
    """Two STATS -> the figures for the time between them."""
    d = {k: (b[k] - a[k]) & 0xFFFFFFFF for k in ('dtcn0', 'frames', 'isr_ticks', 'isr_count',
                                                 'isr_in_idle', 'idle_ticks', 'switches')}
    d['link_moved'] = [x != y for x, y in zip(a['hash'], b['hash'])]
    d['isr_max'] = b['isr_max']
    for k in ('isr_over', 'idle_in', 'idle_out', 'idle_offpc'):
        if k in a and k in b:
            d[k] = (b[k] - a[k]) & 0xFFFFFFFF
    if 'idle_lastpc' in b:
        d['idle_lastpc'] = b['idle_lastpc']
    t, n = d['dtcn0'], d['frames']
    d['timer'] = bool(t)
    if t and n:
        d['ticks_per_s'] = t / n * FRAMES_PER_S
        d['isr_load'] = d['isr_ticks'] / t
        d['isr_peak'] = d['isr_max'] / (t / n)
        d['cpu'] = 1 - max(0, d['idle_ticks'] - d['isr_in_idle']) / t
    return d


class Probe:
    """The channel over a winmidi Port. Stock firmware never answers."""

    def __init__(self, port):
        self.port = port
        self.seq = 0x200

    def call(self, builder, *args, timeout=2.0, tries=2):
        # Every command only reads, so a lost request or reply (the first
        # message after a port opens is sometimes dropped) is asked again.
        for attempt in range(tries):
            try:
                return self._call(builder, *args, timeout=timeout)
            except TimeoutError:
                if attempt == tries - 1:
                    raise

    def _call(self, builder, *args, timeout=2.0):
        self.seq = (self.seq + 1) & 0xFFFF or 1
        seq = self.seq
        req = builder(seq, *args)
        cmd = unpack7(req[len(HEADER):-1])[2]
        self.port.send(req)
        found = []

        def answered(msgs):
            for m in msgs[len(found):]:
                r = parse(m)
                found.append(r if r and r['seq'] == seq and r['cmd'] == cmd | 0x80 else None)
            return any(found)
        self.port.receive(timeout, until=answered)
        for r in found:
            if r:
                if r['status']:
                    raise ValueError('the probe refused 0x%02x: %s'
                                     % (cmd, STATUS.get(r['status'], r['status'])))
                return r['payload']
        raise TimeoutError('no answer: is a usbprobe build running, on this port, with USB '
                           'CONFIG set to USB MIDI or Overbridge? Stock firmware stays silent.')


def cmd_hello(pr, args):
    h = decode_hello(pr.call(req_hello))
    print('%s  (probe protocol %d, %d audio frames since boot = %.1f s)'
          % (h['tag'], h['proto'], h['frames'], h['frames'] / FRAMES_PER_S))


def show(d):
    moved = ', '.join('%s %s' % (name, 'moving' if m else 'STILL') for name, m in zip(LINK, d['link_moved']))
    print('  audio frames %5d (%d expected per second)   context switches %d'
          % (d['frames'], FRAMES_PER_S, d['switches']))
    if 'cpu' in d:
        print('  CPU %5.1f %%   audio ISR %5.1f %% (peak %5.1f %% of a frame)   timer %.2f MHz'
              % (100 * d['cpu'], 100 * d['isr_load'], 100 * d['isr_peak'], d['ticks_per_s'] / 1e6))
    elif not d['timer']:
        print('  no load figures: DMA timer 0 (DTCN0) did not move')
    else:
        print('  no load figures: no audio frames in this interval')
    print('  link: ' + moved)
    if 'idle_in' in d:
        print('  ISRs over a frame %d   idle: in %d, out %d, of them not at the spin %d%s'
              % (d['isr_over'], d['idle_in'], d['idle_out'], d['idle_offpc'],
                 ' (last at 0x%08x)' % d['idle_lastpc'] if d['idle_offpc'] else ''))
        if not d['idle_in'] and 'cpu' in d:
            print('  the idle task was never switched in: the CPU really is never idle')


def cmd_stats(pr, args):
    n = int(args.rest[0]) if args.rest else 5
    last = decode_stats(pr.call(req_stats))
    for _ in range(n):
        time.sleep(1.0)
        s = decode_stats(pr.call(req_stats))
        print('reading (frames %d)' % s['frames'])
        show(delta(last, s))
        last = s


def cmd_dsp(pr, args):
    seconds = float(args.rest[0]) if args.rest else 1.0
    a = decode_stats(pr.call(req_stats))
    time.sleep(seconds)
    b = decode_stats(pr.call(req_stats))
    d = delta(a, b)
    rate = d['frames'] / seconds
    reply_moves = d['link_moved'][0]
    print('audio-frame ISR: %.0f frames/s (%s)' % (rate, 'running' if rate > FRAMES_PER_S * 0.9
                                                    else 'STALLED' if rate == 0 else 'SLOW'))
    print('SHARC reply over DSPI: %s' % ('changing' if reply_moves else 'NOT CHANGING'))
    print('audio from the SHARC (SSI0 in): %s' % ('changing' if d['link_moved'][2] else 'not changing'))
    print('control frame to the SHARC: %s' % ('changing' if d['link_moved'][1] else 'not changing'))
    if 'cpu' in d:
        print('CPU %.1f %%, audio ISR %.1f %% (peak %.1f %%)'
              % (100 * d['cpu'], 100 * d['isr_load'], 100 * d['isr_peak']))
    if rate > FRAMES_PER_S * 0.9 and reply_moves:
        print('=> the DSP link is alive')
    elif rate > FRAMES_PER_S * 0.9:
        print('=> the ColdFire runs its frames but the SHARC reply is frozen: the DSP looks halted '
              '(compare with a reading taken before the trig)')
    else:
        print('=> the ColdFire audio-frame ISR is not running at speed')


def cmd_peek(pr, args):
    addr = int(args.rest[0], 0)
    length = int(args.rest[1], 0) if len(args.rest) > 1 else 256
    out = b''
    while len(out) < length:
        n = min(PEEK_MAX, length - len(out))
        r = decode_peek(pr.call(req_peek, addr + len(out), n))
        if r['addr'] != addr + len(out) or len(r['data']) != n:
            raise ValueError('short or misplaced PEEK reply at 0x%08x' % r['addr'])
        out += r['data']
    for i in range(0, len(out), 16):
        row = out[i:i + 16]
        print('%08x  %-48s %s' % (addr + i, row.hex(' '),
                                   ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)))


# waverider-disc-stages: the stage the DSP last reached, in word 1 of the SHARC reply
# (build_waverider_disc_wtplace.py STAGES_READER / STAGES_ADAPTER, on the Waverider branch)
REPLY = 0x800053a4
STAGE_NAMES = {
    1: 'adapter entry, registers saved', 2: 'parameters filled, about to call the reader',
    3: 'reader entry', 4: 'parameter loads done (I4, six loads, I2)',
    5: 'row f0 stored: DM(6, I4)', 6: 'the c018 add: R1 = R1 + R8', 7: 'row f1 stored: DM(7, I4)',
    8: 'frame fraction: AND, FLOAT BY', 9: 'constants and the count test',
    10: 'first tap address: I0 = R3', 11: 'first table read: DM(0, I0)',
    12: 'all four table reads', 13: 'sample computed', 14: 'output store: DM(I2, M6)',
    15: 'samples-left store: DM(4, I4)', 16: 'reader done (wr5_done)',
    18: 'back in the adapter', 19: 'all done: restores made, about to return',
    # stages-loads: inside the parameter loads (they run between 3 and 4)
    20: 'I4 = R4 done', 21: 'load 1 done: R8 = DM(0, I4)', 22: 'load 2 done: R9 = DM(1, I4)',
    23: 'load 3 done: R10 = DM(2, I4)', 24: 'load 4 done: R11 = DM(3, I4)',
    25: 'load 5 done: R12 = DM(4, I4)', 26: 'load 6 done: R0 = DM(5, I4)',
}


def halves(word):
    """The DSP word as the DSP wrote it: the link delivers its 16-bit halves swapped."""
    return ((word & 0xFFFF) << 16) | (word >> 16)


def decode_stage(word):
    """-> the stage number, whichever way the link orders the halves, or None."""
    for hi, lo in ((word >> 16, word & 0xFFFF), (word & 0xFFFF, word >> 16)):
        if hi == 0x5752 and lo in STAGE_NAMES:
            return lo
    return None


def cmd_stage(pr, args):
    reads = []
    for k in range(3):
        r = decode_peek(pr.call(req_peek, REPLY, 20))
        reads.append(struct.unpack('>IIIII', r['data']))
        time.sleep(0.05)
    for w0, w1, w2, w3, w4 in reads:
        print('reply word 0 %08x   word 1 %08x   word 2 %08x   word 3 %08x   word 4 %08x' % (w0, w1, w2, w3, w4))
    moving = len({r[0] for r in reads}) > 1
    print('DSP heartbeat (word 0): %s' % ('changing: the DSP core is running' if moving else
                                           'FROZEN: the DSP core has stopped'))
    stages = [decode_stage(r[1]) for r in reads]
    if all(s is None for s in stages):
        print('no stage marker in word 1: not a stages build, or the channel does not carry it')
        return
    calls = halves(reads[-1][2])
    if calls:
        print('adapter calls counted (stages-loads builds): %d' % calls)
    w3, w4 = halves(reads[-1][3]), halves(reads[-1][4])
    if w3 or w4:
        print('stages-i2: output pointer R0 = 0x%08x; I2 after the move = %s'
              % (w3, '0x%08x' % w4 if w4 else 'NOT WRITTEN (the core stopped at or right after I2 = R0)'))
    for s in sorted({s for s in stages if s is not None}):
        print('stage %2d  %s' % (s, STAGE_NAMES[s]))
    if not moving and len(set(stages)) == 1:
        print('=> the DSP stopped after stage %d (%s), before the next marker'
              % (stages[0], STAGE_NAMES[stages[0]]))


# stages-irptl: IRPTL bits by interrupt vector slot (stock DN2 1.11's vector table)
IRPTL_BITS = {0: 'EMUI', 1: 'RSTI', 3: 'PARI', 4: 'ILOPI', 5: 'CB7I', 6: 'IICDI', 7: 'SOVFI',
              8: 'ILADI', 11: 'TMZHI', 12: 'BKPI', 13: 'FIR', 14: 'IIR', 15: 'SECI', 20: 'RINSEQI',
              21: 'CB15I', 22: 'TMZLI', 23: 'FIXI', 24: 'FLTOI', 25: 'FLTUI', 26: 'FLTII',
              27: 'EMULI', 28: 'SFT0I', 29: 'SFT1I', 30: 'SFT2I', 31: 'SFT3I'}


def irptl_names(v):
    return ', '.join(IRPTL_BITS.get(b, 'bit %d' % b) for b in range(32) if v >> b & 1) or 'none'


def cmd_irptl(pr, args):
    r = decode_peek(pr.call(req_peek, REPLY, 20))
    w = struct.unpack('>IIIII', r['data'])
    print('stage: %s' % (STAGE_NAMES.get(decode_stage(w[1]), 'no marker')))
    which = args.rest[0] if args.rest else ''
    names = {'ilop': ('after the I2 write', 'after the I2 stores', 'after marker 4'),
             'm4': ('after R13 = imm', 'after store 1', 'after store 2')}.get(
        which, ('after load 6 (26)', 'after marker 4', 'at the end (19)'))
    for name, word in zip(names, (w[2], w[3], w[4])):
        v = halves(word)
        print('IRPTL %-18s 0x%08x  %s' % (name, v, irptl_names(v)))


def selftest():
    assert irptl_names(0x100) == 'ILADI' and irptl_names(0) == 'none'
    assert decode_stage(0x57520013) == 19 and decode_stage(0x00065752) == 6 and decode_stage(0x12345678) is None
    sx = req_peek(7, 0x80005e60, 20)
    assert sx[:6] == HEADER and all(b < 0x80 for b in sx[1:-1])
    assert unpack7(sx[6:-1]) == struct.pack('>HBIH', 7, PEEK, 0x80005e60, 20)
    reply = HEADER + pack7(struct.pack('>HBBI', 7, PEEK | 0x80, 0, 0x80005e60) + bytes(range(20))) + b'\xF7'
    r = parse(reply)
    assert r['status'] == 0 and decode_peek(r['payload'])['data'] == bytes(range(20))
    for good in ((0x80000000, 16), (0x8000FFF0, 16), (0x47FFFC00, 1024), (0x4E6E10FF, 1)):
        req_peek(1, *good)
    for bad in ((0xFC045640, 4), (0xEC094018, 1), (0x47FFFFFF, 2), (0x40000000, 0),
                (0x40000000, PEEK_MAX + 1), (0x7FFFFFFE, 4), (0x8000FFFE, 4), (0x4E6DF0FF, 2)):
        try:
            req_peek(1, *bad)
        except ValueError:
            continue
        raise AssertionError('accepted %r' % (bad,))
    a = dict(zip(STATS_FIELDS, (1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)), hash=[1, 2, 3, 4])
    b = dict(zip(STATS_FIELDS, (1, 0, 66_000_000, 1500, 0, 0, 33_000_000, 1500, 30_000, 0,
                                 26_400_000, 9000)), hash=[9, 2, 3, 4])
    d = delta(a, b)
    assert round(d['ticks_per_s']) == 66_000_000 and round(d['isr_load'], 2) == 0.5
    assert round(d['cpu'], 2) == 0.6 and d['link_moved'] == [True, False, False, False]
    assert STATS_BYTES == 60 and STATS2_BYTES == 80
    two = struct.pack(STATS_FMT, 2, 0, *range(14)) + struct.pack(STATS2_FMT, 5, 6, 7, 8, 0x400cebe2)
    d2 = decode_stats(two)
    assert d2['isr_over'] == 5 and d2['idle_lastpc'] == 0x400cebe2 and d2['switches'] == 9
    one = decode_stats(struct.pack(STATS_FMT, 1, 0, *range(14)))
    assert 'isr_over' not in one
    print('selftest ok')


def lfo4_layout(path):
    """-> (start, length, {name: offset}) of lfo4's profile block, or None."""
    import json
    sym = {k: int(v, 16) for k, v in json.load(open(path)).items()}
    need = ('lfo4_prof', 'lfo4_prof_prev_max', 'lfo4_prof_memcpy_calls', 'lfo4_prof_memset_calls',
            'lfo4_prof_skip_a', 'lfo4_prof_skip_b')
    if not all(k in sym for k in need):
        return None
    at = {k: sym[k] for k in need}
    lo = min(at.values())
    hi = max(max(at.values()) + 4, sym['lfo4_prof'] + 20 * len(LFO4_PIECES),
             sym['lfo4_prof_prev_max'] + 4 * len(LFO4_PIECES))
    return lo, hi - lo, {k: v - lo for k, v in at.items()}


def decode_lfo4(raw, offsets):
    def u32(off):
        return struct.unpack_from('>I', raw, off)[0]
    out = {}
    for i, name in enumerate(LFO4_PIECES):
        base = offsets['lfo4_prof'] + 20 * i
        count, ticks, peak, _window, window_max = struct.unpack_from('>5I', raw, base)
        out[name] = {'count': count, 'ticks': ticks, 'max': peak,
                     'recent_max': max(window_max, u32(offsets['lfo4_prof_prev_max'] + 4 * i))}
    for k in ('memcpy_calls', 'memset_calls', 'skip_a', 'skip_b'):
        out[k] = u32(offsets['lfo4_prof_' + k])
    return out


def cmd_watch(pr, args):
    """Ten readings a second, one line each: press SAVE PROJECT while it runs.

    Per 100 ms: audio frames (150 expected), the ISR's load and its peak as a
    share of a frame, how many ISRs ran longer than a frame, and, when a
    profiling build's symbols are given, each lfo4 piece's calls and time in
    microseconds (DTCN0 at the rate the first reading measures).
    """
    seconds = float(args.rest[0]) if args.rest else 30.0
    lfo4 = lfo4_layout(args.symbols) if args.symbols else None

    def read():
        s = decode_stats(pr.call(req_stats))
        s['host'] = time.perf_counter()
        if lfo4:
            s['lfo4'] = decode_lfo4(decode_peek(pr.call(req_peek, lfo4[0], lfo4[1]))['data'], lfo4[2])
        return s
    last = read()
    rate = None
    print('   t(s) frames  ISR%%  peak%%  over  idle-in' + ''.join(
        '  %s n/us/peak' % n for n in LFO4_PIECES) * bool(lfo4) + ('  cpy/set/skipA/skipB' if lfo4 else ''))
    start = last['host']
    while last['host'] - start < seconds:
        time.sleep(0.1)
        s = read()
        d = delta(last, s)
        if d.get('ticks_per_s') and d['frames'] > 100:
            rate = d['ticks_per_s'] if rate is None else 0.9 * rate + 0.1 * d['ticks_per_s']
        line = '%7.2f %6d %5s %6s %5s %8s' % (
            s['host'] - start, d['frames'],
            '%.1f' % (100 * d['isr_load']) if 'isr_load' in d else '-',
            '%.0f' % (100 * d['isr_peak']) if 'isr_peak' in d else '-',
            d.get('isr_over', '-'), d.get('idle_in', '-'))
        if lfo4:
            us = (lambda t: t / rate * 1e6) if rate else (lambda t: float('nan'))
            for n in LFO4_PIECES:
                a, b = last['lfo4'][n], s['lfo4'][n]
                line += '  %5d/%6.0f/%4.0f' % ((b['count'] - a['count']) & 0xFFFFFFFF,
                                               us((b['ticks'] - a['ticks']) & 0xFFFFFFFF),
                                               us(b['recent_max']))
            line += '  ' + '/'.join(str((s['lfo4'][k] - last['lfo4'][k]) & 0xFFFFFFFF)
                                    for k in ('memcpy_calls', 'memset_calls', 'skip_a', 'skip_b'))
        print(line)
        last = s


COMMANDS = {'hello': cmd_hello, 'stats': cmd_stats, 'dsp': cmd_dsp, 'peek': cmd_peek, 'stage': cmd_stage, 'irptl': cmd_irptl,
            'watch': cmd_watch}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument('command', choices=sorted([*COMMANDS, 'ports', 'selftest']))
    p.add_argument('rest', nargs='*')
    p.add_argument('--port', default='Digitone II', help='a substring of the MIDI port name')
    p.add_argument('--in', dest='i', type=int, help='MIDI in index (see `ports`)')
    p.add_argument('--out', dest='o', type=int, help='MIDI out index')
    p.add_argument('--symbols', help='watch: a profiling build\'s symbols.json, for lfo4\'s timers')
    args = p.parse_args(argv)
    if args.command == 'selftest':
        selftest()
        return 0
    sys.path.insert(0, __import__('os').path.dirname(__file__))
    import winmidi
    if args.command == 'ports':
        ins, outs = winmidi.ports()
        print('in:  ' + '; '.join('%d %s' % kv for kv in enumerate(ins)))
        print('out: ' + '; '.join('%d %s' % kv for kv in enumerate(outs)))
        return 0
    port = winmidi.Port(args.port, args.i, args.o)
    try:
        COMMANDS[args.command](Probe(port), args)
    except (TimeoutError, ValueError) as exc:
        print(exc)
        return 1
    finally:
        port.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""A run's log: every probe reading and mark as CSV, everything as JSON lines.

derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

One job: the files a run leaves behind, so a save can be analysed after it.

    out/dn2live/<YYYYmmdd-HHMMSS>.csv     one row per probe reading, mark and status change
    out/dn2live/<YYYYmmdd-HHMMSS>.jsonl   every event the page saw, MIDI included, as sent

The CSV's columns are fixed (spreadsheet-friendly); anything a newer probe adds
that the page does not know goes, raw, in its `extra` column as
`+offset=value/delta` items, and the JSONL has every field as published.
Each row is flushed as it is written: a run stopped with the window's close
button keeps everything up to that instant.

A watch's reading (`dn2watch`) is a row of kind `watch`: its name in `label`,
its fields as `name=hex` in `extra` (semitones beside a TUN field), and the
fields that changed since its last reading in `state`.
"""
from __future__ import annotations

import csv
import json
import pathlib
import threading
import time

import dn2probe
import dn2stats
import dn2watch

COLUMNS = (['t', 'kind', 'label', 'state', 'frames_s', 'isr_avg', 'isr_peak', 'isr_peak_1s',
            'switches_s', 'switches_probe', 'cpu', 'timer_mhz', 'clock']
           + ['link_%s' % n for n in ('reply', 'control', 'audio_in', 'audio_out')]
           + ['late', 'late_why', 'late_intervals', 'low_episodes', 'rtt_ms', 'rate_hz',
              'lost_replies', 'layout', 'isr_over', 'isr_over_s', 'isr_over_total',
              'idle_in', 'idle_out', 'idle_offpc', 'idle_lastpc', 'cpu_verdict', 'extra']
           + ['lfo4_%s_%s' % (p, k) for p in dn2probe.LFO4_PIECES for k in ('n', 'us', 'peak_us')]
           + ['lfo4_%s' % k for k in ('memcpy_calls', 'memset_calls', 'skip_a', 'skip_b')]
           + ['raw_%s' % w for w in dn2stats.ALL_WORDS])


class RunLog:
    def __init__(self, folder: pathlib.Path, stamp: str | None = None):
        folder.mkdir(parents=True, exist_ok=True)
        stamp = stamp or time.strftime('%Y%m%d-%H%M%S')
        self.csv_path = folder / (stamp + '.csv')
        self.jsonl_path = folder / (stamp + '.jsonl')
        self._csv_f = open(self.csv_path, 'w', encoding='utf-8', newline='')
        self._jsonl_f = open(self.jsonl_path, 'w', encoding='utf-8', newline='\n')
        self._csv = csv.DictWriter(self._csv_f, COLUMNS, extrasaction='ignore')
        self._csv.writeheader()
        self._lock = threading.Lock()

    def write(self, ev: dict) -> None:
        with self._lock:
            if self._jsonl_f.closed:
                return
            self._jsonl_f.write(json.dumps(ev, separators=(',', ':')) + '\n')
            self._jsonl_f.flush()
            row = row_of(ev)
            if row is not None:
                self._csv.writerow(row)
                self._csv_f.flush()

    def close(self) -> None:
        with self._lock:
            self._csv_f.close()
            self._jsonl_f.close()


def row_of(ev: dict) -> dict | None:
    """An event -> its CSV row, or None for one the CSV does not carry (MIDI)."""
    kind = ev.get('type')
    if kind == 'probe':
        row = {k: ev.get(k) for k in COLUMNS if k in ev}
        row['kind'] = 'probe'
        for name, v in zip(('reply', 'control', 'audio_in', 'audio_out'), ev.get('link') or ()):
            row['link_' + name] = v
        row['late'] = int(bool(ev.get('late')))
        row['extra'] = ' '.join('+%d=%d/%s' % (x['offset'], x['value'],
                                               '' if x['delta'] is None else x['delta'])
                                for x in ev.get('extra') or ())
        if ev.get('tail'):
            row['extra'] = (row['extra'] + ' tail=' + ev['tail'].replace(' ', '')).strip()
        for w, v in (ev.get('raw') or {}).items():
            row['raw_' + w] = v
        idle = ev.get('idle')
        if idle:
            row.update(idle_in=idle['in'], idle_out=idle['out'], idle_offpc=idle['offpc'],
                       idle_lastpc=idle['lastpc'])
        return row
    if kind == 'probe-lfo4':
        row = {'t': ev['t'], 'kind': 'lfo4'}
        for p, v in ev['pieces'].items():
            for k in ('n', 'us', 'peak_us'):
                row['lfo4_%s_%s' % (p, k)] = v[k]
        for k, v in ev['fast'].items():
            row['lfo4_' + k] = v
        return row
    if kind == 'probe-watch':
        return {'t': ev['t'], 'kind': 'watch', 'label': ev['name'],
                'state': ' '.join(ev.get('changed') or ()), 'extra': dn2watch.summary(ev['values'])}
    if kind == 'mark':
        return {'t': ev['t'], 'kind': 'mark', 'label': ev.get('label', '')}
    if kind == 'probe-status':
        return {'t': ev['t'], 'kind': 'status', 'state': ev['state'],
                'label': ' '.join(str(x) for x in (ev.get('tag'), ev.get('proto') and
                                                   'proto %s' % ev['proto']) if x),
                'rate_hz': ev.get('rate_hz')}
    if kind == 'probe-cost':
        return {'t': ev['t'], 'kind': 'cost',
                'label': 'switches per request %s (at %s and %s Hz)'
                % (ev.get('per_request'), ev.get('low_hz'), ev.get('high_hz'))}
    if kind == 'probe-error':
        return {'t': ev['t'], 'kind': 'error', 'label': ev.get('error', '')}
    return None

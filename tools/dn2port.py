"""The Digitone II's USB MIDI in and out, held open for as long as the page runs.

derived from irpina/digihealth (tools/winmidi.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

One job: the port. `tools/winmidi.py` polls its input with no callback, which
loses every short message (notes, CCs, start/stop) -- fine for a request and a
reply, useless for a live view. `scripts/midi_probe.py`'s `InPort` has the
callback but never re-posts a SysEx buffer, so it goes deaf after its eighth
SysEx -- under a second at ten STATS a second. This joins the two:

- the callback (winmm's thread) only appends: a short message, or a finished
  buffer's bytes and its index. Windows deadlocks if a multimedia function is
  called from inside it (midi_probe's docstring has the history);
- `service()`, called from an ordinary thread, re-posts the buffers the
  callback finished, and joins a SysEx split across buffers;
- `send()` is SysEx out, serialised by a lock.

Ports are chosen by `winmidi.find` (one exact pair containing "Digitone II",
never the first "Digitone"), or by index.
"""
from __future__ import annotations

import ctypes
import threading
import time

import winmidi

CALLBACK_FUNCTION = 0x00030000
MIM_DATA, MIM_LONGDATA = 0x3C3, 0x3C4      # 0x3C5 is MIM_ERROR: midi_probe learned that the hard way
MHDR_DONE = 0x1


def pick(name: str, i: int | None, o: int | None) -> tuple[int, int, str, str]:
    """-> (in index, out index, in name, out name)."""
    ins, outs = winmidi.ports()
    if i is None or o is None:
        fi, fo = winmidi.find(name)
        i = fi if i is None else i
        o = fo if o is None else o
    if i >= len(ins) or o >= len(outs):
        raise OSError('no MIDI in %d / out %d: there are %d in and %d out' % (i, o, len(ins), len(outs)))
    return i, o, ins[i], outs[o]


class Dn2Port:
    def __init__(self, i: int, o: int, nbuf: int = 32, size: int = 8192):
        from ctypes import wintypes
        wt, self.MIDIHDR, _, _ = winmidi._types()
        w = winmidi.winmm()
        self.shorts: list[tuple[float, int]] = []     # (host time, packed dwParam1)
        self.sysex: list[tuple[float, bytes]] = []    # complete messages, F0..F7
        self._done: list[tuple[float, int, bytes]] = []  # (time, buffer index, bytes): the callback's
        self._part = b''
        self._send_lock = threading.Lock()
        self._closed = False
        proc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_void_p)

        def on_msg(h, msg, inst, p1, p2):
            if msg == MIM_DATA:
                self.shorts.append((time.time(), ctypes.cast(p1, ctypes.c_void_p).value or 0))
            elif msg == MIM_LONGDATA:
                mh = ctypes.cast(p1, ctypes.POINTER(self.MIDIHDR)).contents
                idx = mh.dwUser or 0
                raw = ctypes.string_at(mh.lpData, mh.dwBytesRecorded) if mh.dwBytesRecorded else b''
                self._done.append((time.time(), idx, raw))
                # NOT re-posted here: service() does it, outside the callback

        self._cb = proc(on_msg)
        self.hin, self.hout = wt.HANDLE(), wt.HANDLE()
        r = w.midiInOpen(ctypes.byref(self.hin), i, self._cb, None, CALLBACK_FUNCTION)
        if r:
            raise OSError('midiInOpen(%d) failed: %d (is Transfer, DNX or midi_live using it?)' % (i, r))
        r = w.midiOutOpen(ctypes.byref(self.hout), o, 0, 0, 0)
        if r:
            w.midiInClose(self.hin)
            raise OSError('midiOutOpen(%d) failed: %d (is Transfer or DNX using it?)' % (o, r))
        self._bufs = []
        for k in range(nbuf):
            mem = ctypes.create_string_buffer(size)
            h = self.MIDIHDR(lpData=ctypes.cast(mem, ctypes.c_void_p), dwBufferLength=size, dwUser=k)
            w.midiInPrepareHeader(self.hin, ctypes.byref(h), ctypes.sizeof(h))
            w.midiInAddBuffer(self.hin, ctypes.byref(h), ctypes.sizeof(h))
            self._bufs.append((h, mem))
        w.midiInStart(self.hin)

    def service(self) -> None:
        """Re-post finished buffers and move whole SysEx messages to `self.sysex`."""
        if self._closed:
            return
        w = winmidi.winmm()
        while self._done:
            t, idx, raw = self._done.pop(0)
            h, _mem = self._bufs[idx]
            h.dwBytesRecorded = 0
            h.dwFlags &= ~MHDR_DONE
            w.midiInAddBuffer(self.hin, ctypes.byref(h), ctypes.sizeof(h))
            if not raw:
                continue
            if raw[0] == 0xF0:
                self._part = b''
            self._part += raw
            if self._part.endswith(b'\xF7'):
                self.sysex.append((t, self._part))
                self._part = b''
            elif len(self._part) > 1 << 20:
                self._part = b''            # a runaway: drop it rather than grow

    def send(self, data: bytes) -> None:
        w = winmidi.winmm()
        with self._send_lock:
            mem = ctypes.create_string_buffer(bytes(data), len(data))
            h = self.MIDIHDR(lpData=ctypes.cast(mem, ctypes.c_void_p), dwBufferLength=len(data))
            w.midiOutPrepareHeader(self.hout, ctypes.byref(h), ctypes.sizeof(h))
            r = w.midiOutLongMsg(self.hout, ctypes.byref(h), ctypes.sizeof(h))
            if r:
                w.midiOutUnprepareHeader(self.hout, ctypes.byref(h), ctypes.sizeof(h))
                raise OSError('midiOutLongMsg failed: %d' % r)
            t = time.time()
            while not h.dwFlags & MHDR_DONE and time.time() - t < 2:
                time.sleep(0.0005)
            w.midiOutUnprepareHeader(self.hout, ctypes.byref(h), ctypes.sizeof(h))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        w = winmidi.winmm()
        w.midiInStop(self.hin)
        w.midiInReset(self.hin)
        for h, _mem in self._bufs:
            w.midiInUnprepareHeader(self.hin, ctypes.byref(h), ctypes.sizeof(h))
        w.midiInClose(self.hin)
        with self._send_lock:
            w.midiOutReset(self.hout)
            w.midiOutClose(self.hout)

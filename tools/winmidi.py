"""A tiny SysEx client over the Windows MIDI API (winmm, through ctypes: no packages).

derived from irpina/digihealth (tools/winmidi.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

Opens one MIDI in and one MIDI out port, sends a SysEx message and collects
whatever SysEx comes back. Where this diverges from digihealth's: ports are
chosen by an exact device, never the first name that contains "Digitone"
(this desk has a Digitone and a Digitone II on USB at once, and their in and
out indices do not line up), and `winmm` is loaded on first use so the codec
beside it imports on Linux too, for the emulator tests.

Windows lets one program at a time open a MIDI port: close Elektron Transfer
and DNX first.
"""
import ctypes
import time

MHDR_DONE = 0x1
CALLBACK_NULL = 0
_winmm = None


def winmm():
    global _winmm
    if _winmm is None:
        _winmm = ctypes.WinDLL('winmm')
    return _winmm


def _types():
    from ctypes import wintypes

    class MIDIHDR(ctypes.Structure):
        pass

    MIDIHDR._fields_ = [('lpData', ctypes.c_void_p), ('dwBufferLength', wintypes.DWORD),
                        ('dwBytesRecorded', wintypes.DWORD), ('dwUser', ctypes.c_void_p),
                        ('dwFlags', wintypes.DWORD), ('lpNext', ctypes.POINTER(MIDIHDR)),
                        ('reserved', ctypes.c_void_p), ('dwOffset', wintypes.DWORD),
                        ('dwReserved', ctypes.c_void_p * 8)]

    class InCaps(ctypes.Structure):
        _fields_ = [('wMid', wintypes.WORD), ('wPid', wintypes.WORD),
                    ('vDriverVersion', wintypes.UINT), ('szPname', wintypes.WCHAR * 32),
                    ('dwSupport', wintypes.DWORD)]

    class OutCaps(ctypes.Structure):
        _fields_ = [('wMid', wintypes.WORD), ('wPid', wintypes.WORD),
                    ('vDriverVersion', wintypes.UINT), ('szPname', wintypes.WCHAR * 32),
                    ('wTechnology', wintypes.WORD), ('wVoices', wintypes.WORD),
                    ('wNotes', wintypes.WORD), ('wChannelMask', wintypes.WORD),
                    ('dwSupport', wintypes.DWORD)]
    return wintypes, MIDIHDR, InCaps, OutCaps


def ports():
    """-> (input names, output names), in winmm's index order."""
    _, _, InCaps, OutCaps = _types()
    w = winmm()

    def names(count, caps_fn, struct):
        out = []
        for i in range(count()):
            c = struct()
            caps_fn(i, ctypes.byref(c), ctypes.sizeof(c))
            out.append(c.szPname)
        return out
    return (names(w.midiInGetNumDevs, w.midiInGetDevCapsW, InCaps),
            names(w.midiOutGetNumDevs, w.midiOutGetDevCapsW, OutCaps))


def find(name):
    """-> (in index, out index) of the one port pair whose name contains `name`.

    "Digitone II" matches the DN2's port and not the Digitone 1's ("Elektron
    Digitone"). More than one candidate is an error, never a guess."""
    ins, outs = ports()

    def pick(names, kind):
        hits = [k for k, n in enumerate(names) if name in n]
        if len(hits) != 1:
            raise OSError('%s MIDI %s port containing %r. Ports: %s. Name them with --in/--out.'
                          % ('no' if not hits else 'more than one', kind, name,
                             '; '.join('%d %s' % (k, n) for k, n in enumerate(names)) or 'none'))
        return hits[0]
    return pick(ins, 'in'), pick(outs, 'out')


class Port:
    def __init__(self, name='Digitone II', i=None, o=None, nbuf=16, size=65536):
        wintypes, self.MIDIHDR, _, _ = _types()
        w = winmm()
        if i is None or o is None:
            fi, fo = find(name)
            i = fi if i is None else i
            o = fo if o is None else o
        self.hin, self.hout = wintypes.HANDLE(), wintypes.HANDLE()
        r = w.midiInOpen(ctypes.byref(self.hin), i, 0, 0, CALLBACK_NULL)
        if r:
            raise OSError('midiInOpen(%d) failed: %d (is Transfer or DNX using it?)' % (i, r))
        r = w.midiOutOpen(ctypes.byref(self.hout), o, 0, 0, CALLBACK_NULL)
        if r:
            w.midiInClose(self.hin)
            raise OSError('midiOutOpen(%d) failed: %d (is Transfer or DNX using it?)' % (o, r))
        self.bufs = []
        for _ in range(nbuf):
            mem = ctypes.create_string_buffer(size)
            h = self.MIDIHDR(lpData=ctypes.cast(mem, ctypes.c_void_p), dwBufferLength=size)
            w.midiInPrepareHeader(self.hin, ctypes.byref(h), ctypes.sizeof(h))
            w.midiInAddBuffer(self.hin, ctypes.byref(h), ctypes.sizeof(h))
            self.bufs.append((h, mem))
        w.midiInStart(self.hin)

    def send(self, data):
        w = winmm()
        mem = ctypes.create_string_buffer(bytes(data), len(data))
        h = self.MIDIHDR(lpData=ctypes.cast(mem, ctypes.c_void_p), dwBufferLength=len(data))
        w.midiOutPrepareHeader(self.hout, ctypes.byref(h), ctypes.sizeof(h))
        r = w.midiOutLongMsg(self.hout, ctypes.byref(h), ctypes.sizeof(h))
        if r:
            raise OSError('midiOutLongMsg failed: %d' % r)
        t = time.time()
        while not h.dwFlags & MHDR_DONE and time.time() - t < 5:
            time.sleep(0.001)
        w.midiOutUnprepareHeader(self.hout, ctypes.byref(h), ctypes.sizeof(h))

    def receive(self, seconds=1.0, until=None):
        """-> SysEx messages received within `seconds` (early once `until(msgs)`)."""
        w = winmm()
        msgs, end = [], time.time() + seconds
        while time.time() < end:
            for h, mem in self.bufs:
                if h.dwFlags & MHDR_DONE:
                    n = h.dwBytesRecorded
                    if n:
                        msgs.append(bytes(mem.raw[:n]))
                    h.dwBytesRecorded = 0
                    h.dwFlags &= ~MHDR_DONE
                    w.midiInAddBuffer(self.hin, ctypes.byref(h), ctypes.sizeof(h))
            if until and until(msgs):
                break
            time.sleep(0.002)
        return msgs

    def close(self):
        w = winmm()
        w.midiInStop(self.hin)
        w.midiInReset(self.hin)
        for h, _mem in self.bufs:
            w.midiInUnprepareHeader(self.hin, ctypes.byref(h), ctypes.sizeof(h))
        w.midiInClose(self.hin)
        w.midiOutClose(self.hout)

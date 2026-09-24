"""Capture the instrument's own audio, with no dependency and no callback.

    python scripts/audio_probe.py --list
    python scripts/audio_probe.py --in 0 --seconds 5 --wav out/cap.wav

**Why this exists.** Every hardware result in this project has been "the owner
says it sounds right". That is one observer, and the question the LFO4 work is
stuck on -- *is the modulation actually happening?* -- is one a machine can
answer. The Digitone's USB audio interface is an input on this PC, so its sound
can be measured in the same seconds as its telemetry.

**No callback, on purpose.** `midi_probe.InPort` documents why a winmm callback
must stay trivial: calling a multimedia function from inside one deadlocks
Windows. `waveIn` can be driven without any callback at all -- open with
`CALLBACK_NULL`, hand it buffers, and poll each header's `WHDR_DONE` flag from
the caller's own thread. Nothing can deadlock because nothing runs in the
driver's context.

**Read-only.** No output device is opened. Nothing here can make a sound.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import struct
import time
import wave

winmm = ctypes.WinDLL("winmm")

CALLBACK_NULL = 0x0
WHDR_DONE = 0x1


class WAVEINCAPS(ctypes.Structure):
    _fields_ = [("wMid", w.WORD), ("wPid", w.WORD), ("vDriverVersion", ctypes.c_uint),
                ("szPname", ctypes.c_wchar * 32), ("dwFormats", ctypes.c_ulong),
                ("wChannels", w.WORD), ("wReserved1", w.WORD)]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", w.WORD), ("nChannels", w.WORD),
                ("nSamplesPerSec", ctypes.c_ulong), ("nAvgBytesPerSec", ctypes.c_ulong),
                ("nBlockAlign", w.WORD), ("wBitsPerSample", w.WORD), ("cbSize", w.WORD)]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [("lpData", ctypes.c_char_p), ("dwBufferLength", ctypes.c_ulong),
                    ("dwBytesRecorded", ctypes.c_ulong), ("dwUser", ctypes.c_void_p),
                    ("dwFlags", ctypes.c_ulong), ("dwLoops", ctypes.c_ulong),
                    ("lpNext", ctypes.POINTER(WAVEHDR)), ("reserved", ctypes.c_void_p)]


def list_inputs() -> list[str]:
    out = []
    for i in range(winmm.waveInGetNumDevs()):
        c = WAVEINCAPS()
        if winmm.waveInGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c)) == 0:
            out.append(c.szPname)
        else:
            out.append(f"<device {i} would not describe itself>")
    return out


class InStream:
    """An open capture device, drained by polling rather than by callback.

    `read()` returns whatever whole buffers have completed since last time and
    immediately requeues them, so the driver never runs out. Buffers are kept
    small enough that a poll every few milliseconds cannot fall behind at
    48 kHz stereo, and there are enough of them to absorb a scheduling hiccup.
    """

    def __init__(self, index: int = 0, rate: int = 48000, channels: int = 2,
                 nbuf: int = 16, frames_per_buf: int = 2048) -> None:
        self.rate, self.channels = rate, channels
        self.width = 2
        fmt = WAVEFORMATEX(1, channels, rate, rate * channels * 2,
                           channels * 2, 16, 0)
        self.h = w.HANDLE()
        rc = winmm.waveInOpen(ctypes.byref(self.h), index, ctypes.byref(fmt),
                              0, 0, CALLBACK_NULL)
        if rc != 0:
            raise SystemExit(f"  waveInOpen failed: {rc} "
                             f"(device busy, or it does not accept "
                             f"{rate} Hz / {channels} ch / 16-bit)")
        nbytes = frames_per_buf * channels * 2
        self.bufs = [ctypes.create_string_buffer(nbytes) for _ in range(nbuf)]
        self.hdrs = []
        for b in self.bufs:
            hdr = WAVEHDR(ctypes.cast(b, ctypes.c_char_p), nbytes, 0, None, 0, 0, None, None)
            winmm.waveInPrepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr))
            winmm.waveInAddBuffer(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr))
            self.hdrs.append(hdr)
        self.started = time.time()
        if winmm.waveInStart(self.h) != 0:
            raise SystemExit("  waveInStart failed")

    def read(self) -> bytes:
        """-> the PCM that has completed since the last call, and requeue."""
        out = bytearray()
        for i, hdr in enumerate(self.hdrs):
            if hdr.dwFlags & WHDR_DONE:
                out += self.bufs[i].raw[:hdr.dwBytesRecorded]
                winmm.waveInUnprepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr))
                hdr.dwFlags = 0
                hdr.dwBytesRecorded = 0
                winmm.waveInPrepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr))
                winmm.waveInAddBuffer(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr))
        return bytes(out)

    def close(self) -> None:
        winmm.waveInStop(self.h)
        winmm.waveInReset(self.h)
        for hdr in self.hdrs:
            winmm.waveInUnprepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.waveInClose(self.h)


def capture(index: int, seconds: float, rate: int = 48000, channels: int = 2) -> bytes:
    s = InStream(index, rate=rate, channels=channels)
    pcm = bytearray()
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            pcm += s.read()
            time.sleep(0.004)
        pcm += s.read()
    finally:
        s.close()
    return bytes(pcm)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--list", action="store_true")
    p.add_argument("--in", dest="index", type=int, default=0)
    p.add_argument("--seconds", type=float, default=5.0)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--wav", help="also write the capture here")
    args = p.parse_args()

    names = list_inputs()
    if args.list or not names:
        print("AUDIO IN:")
        for i, n in enumerate(names):
            print(f"  [{i}] {n}")
        return 0 if names else 1
    if args.index >= len(names):
        print(f"  no input {args.index}; there are {len(names)}")
        return 1

    print(f"  capturing {args.seconds}s from [{args.index}] {names[args.index]}")
    pcm = capture(args.index, args.seconds, rate=args.rate)
    frames = len(pcm) // 4
    print(f"  {len(pcm):,} bytes = {frames:,} stereo frames = "
          f"{frames / args.rate:.2f}s at {args.rate} Hz")
    if frames == 0:
        print("  nothing arrived. The device opened but delivered no audio -- check")
        print("  that the instrument is actually routed to its USB output.")
        return 1

    peak = 0
    for i in range(0, min(len(pcm), 4 * args.rate), 2):
        v = struct.unpack_from("<h", pcm, i)[0]
        peak = max(peak, abs(v))
    print(f"  peak in the first second: {peak} of 32767 "
          f"({'silent' if peak < 64 else 'signal present'})")

    if args.wav:
        with wave.open(args.wav, "wb") as f:
            f.setnchannels(2)
            f.setsampwidth(2)
            f.setframerate(args.rate)
            f.writeframes(pcm)
        print(f"  wrote {args.wav}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

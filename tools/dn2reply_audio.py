"""The per-sample audio records in the SHARC's reply, channel by channel, from a usbprobe build.

    python tools/dn2reply_audio.py LABEL [--n 20] [--dir out/reply-audio]

The reply the ColdFire receives each frame at `0x800053a4` holds, from `+0x1c`,
32 records of 84 bytes (docs/for-digikit-coldfire-sharc-link.md, section 8): one
per sample of the 32-sample block, 28 channels of 3 bytes each on the reading in
use (the per-track stream Overbridge carries; not confirmed channel by channel).

This reads the records N times (one PEEK of 2,688 bytes each, read-only), saves
them to DIR/LABEL.K.bin, and prints, for each 3-byte channel, how many of the
N x 32 samples are non-zero and their RMS as a signed 24-bit big-endian value.
The 16-bit halves as the ColdFire holds them are kept as read. A channel that
carries audio in one state and not in another stands out either way, whatever
the exact sample format.
"""
from __future__ import annotations

import argparse
import math
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import dn2probe as dp                                          # noqa: E402
from dn2probe_frame import read                                # noqa: E402

RECORDS, RECORD_BYTES, CHANNELS = 32, 84, 28
BASE = 0x800053A4 + 0x1C


def s24(b: bytes) -> int:
    v = (b[0] << 16) | (b[1] << 8) | b[2]
    return v - (1 << 24) if v & 0x800000 else v


def channels(blobs: list[bytes]) -> list[tuple[int, float]]:
    """-> per channel (non-zero samples, RMS) over every record of every reading."""
    out = []
    for c in range(CHANNELS):
        vals = [s24(blob[r * RECORD_BYTES + 3 * c: r * RECORD_BYTES + 3 * c + 3])
                for blob in blobs for r in range(RECORDS)]
        nz = sum(1 for v in vals if v)
        out.append((nz, math.sqrt(sum(v * v for v in vals) / len(vals)) if vals else 0.0))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("label")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("out/reply-audio"))
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import winmidi
    a.dir.mkdir(parents=True, exist_ok=True)
    port = winmidi.Port(a.port, None, None)
    blobs = []
    try:
        pr = dp.Probe(port)
        for k in range(a.n):
            blob = read(pr, BASE, RECORDS * RECORD_BYTES)
            (a.dir / f"{a.label}.{k:02d}.bin").write_bytes(blob)
            blobs.append(blob)
            time.sleep(0.05)
    finally:
        port.close()
    total = a.n * RECORDS
    print(f"{a.label}: {a.n} readings x {RECORDS} samples")
    for c, (nz, rms) in enumerate(channels(blobs)):
        bar = "#" * min(40, int(rms / 2 ** 23 * 400)) if rms else ""
        print(f"  ch {c:2d}  non-zero {nz:4d}/{total}  rms {rms:10.0f}  {bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Save the ColdFire's live DSP frame and parameter mirror from a usbprobe build.

    python tools/dn2probe_frame.py NAME [--dir out/probe-frames] [--repeat 3]

Reads, over the read-only USB probe (`tools/dn2probe.py`):

- the frame the audio ISR sends the SHARC, 2,688 bytes at `0x80005e60`
  (big-endian 16-bit words at `dnfw.waverider.frame`'s offsets);
- the modulated per-track mirror the frame builder copies from, 4,096 bytes at
  `0x800068e4`.

`--repeat` takes that many readings in a row, so a value that moves on its own
(a glide, a modulation) shows as a difference between them. Writes
`DIR/NAME.frame_be.K.bin` and `DIR/NAME.mirror_be.K.bin`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import dn2probe as dp                                          # noqa: E402

FRAME, FRAME_LEN = 0x80005E60, 2688
MIRROR, MIRROR_LEN = 0x800068E4, 4096


def read(pr, addr: int, length: int) -> bytes:
    out = b""
    while len(out) < length:
        n = min(dp.PEEK_MAX, length - len(out))
        r = dp.decode_peek(pr.call(dp.req_peek, addr + len(out), n))
        if r["addr"] != addr + len(out) or len(r["data"]) != n:
            raise ValueError(f"short or misplaced PEEK reply at 0x{r['addr']:08x}")
        out += r["data"]
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("name")
    p.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("out/probe-frames"))
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import winmidi
    a.dir.mkdir(parents=True, exist_ok=True)
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        for k in range(a.repeat):
            (a.dir / f"{a.name}.frame_be.{k}.bin").write_bytes(read(pr, FRAME, FRAME_LEN))
            (a.dir / f"{a.name}.mirror_be.{k}.bin").write_bytes(read(pr, MIRROR, MIRROR_LEN))
            time.sleep(0.2)
        print(f"saved {a.repeat} reading(s) of the frame and the mirror as {a.dir / a.name}.*")
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

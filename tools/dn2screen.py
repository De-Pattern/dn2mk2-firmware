"""Save the instrument's screen, live, from any usbprobe build.

    python tools/dn2screen.py NAME [--n 1] [--interval 0] [--dir out/screens-live] [--scale 4]
    python tools/dn2screen.py NAME --gif SECONDS      # an animation, in real time

Reads the two 1,024-byte panel buffers (`0x44622bc8` and `0x44622fc8`, 128 x 64 at
1 bpp; docs/display-path.md) over the read-only probe's PEEK and writes each as a
PNG: `DIR/NAME.K.a.png` and `DIR/NAME.K.b.png`. The firmware double-buffers, so one
of the two is the frame on the glass and the other the one being drawn; a read can
also land mid-draw, so take a few (`--n`) and keep the clean ones.

The bytes are column-major, 8 a column, top band last:
pixel (x, y) is bit `y % 8` of byte `8 x + 7 - y // 8` (the same layout the
emulator's captures use). Only reads; nothing is written to the instrument.

Prints how long each read took, so the frames a second the probe can give are
measured rather than assumed.

`--gif SECONDS` reads both buffers as fast as the probe answers (about 6 ms a read)
for that long and writes `DIR/NAME.glass.gif` (and each buffer's own, `.a`, `.b`),
one frame per change, each held for as long as the screen held it. The firmware
draws into the two buffers in turn, so the glass is whichever changed last. It
prints how many times each changed: the rate the screen really updates.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

BUFFERS = {"a": 0x44622BC8, "b": 0x44622FC8}
W, H, SIZE = 128, 64, 1024


def pixels(buf: bytes) -> list[list[bool]]:
    """-> rows[y][x], y down from the top of the glass."""
    return [[bool((buf[8 * x + 7 - y // 8] >> (y % 8)) & 1) for x in range(W)] for y in range(H)]


def write_png(buf: bytes, path: pathlib.Path, scale: int) -> None:
    image(buf, scale).save(path)


def image(buf: bytes, scale: int):
    from PIL import Image                                          # noqa: PLC0415
    img = Image.new("L", (W, H), 0)
    img.putdata([255 if on else 0 for row in pixels(buf) for on in row])
    return img.resize((W * scale, H * scale), Image.NEAREST)


def record(pr, dp, seconds: float) -> dict[str, list[tuple[float, bytes]]]:
    """-> per buffer, (time, bytes) at each change, from as many reads as fit."""
    seen: dict[str, list[tuple[float, bytes]]] = {n: [] for n in (*BUFFERS, "glass")}
    t0 = time.perf_counter()
    while (now := time.perf_counter() - t0) < seconds:
        for name, addr in BUFFERS.items():
            buf = dp.decode_peek(pr.call(dp.req_peek, addr, SIZE))["data"]
            if not seen[name] or seen[name][-1][1] != buf:
                seen[name].append((now, buf))
                # the two buffers take turns: the one that changed last is the newest frame
                if not seen["glass"] or seen["glass"][-1][1] != buf:
                    seen["glass"].append((now, buf))
    for name in seen:
        seen[name].append((seconds, seen[name][-1][1]))
    return seen


def write_gif(changes: list[tuple[float, bytes]], path: pathlib.Path, scale: int) -> None:
    frames = [image(buf, scale) for _, buf in changes[:-1]]
    hold = [max(20, round(1000 * (changes[k + 1][0] - changes[k][0]))) for k in range(len(frames))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=hold, loop=0)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name")
    p.add_argument("--n", type=int, default=1)
    p.add_argument("--interval", type=float, default=0.0, help="seconds between reads")
    p.add_argument("--dir", type=pathlib.Path, default=HERE.parent / "out" / "screens-live")
    p.add_argument("--scale", type=int, default=4)
    p.add_argument("--gif", type=float, default=None, metavar="SECONDS")
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import dn2probe as dp                                          # noqa: PLC0415
    import winmidi                                                 # noqa: PLC0415
    a.dir.mkdir(parents=True, exist_ok=True)
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        print(dp.decode_hello(pr.call(dp.req_hello))["tag"])
        if a.gif:
            for name, changes in record(pr, dp, a.gif).items():
                write_gif(changes, a.dir / f"{a.name}.{name}.gif", a.scale)
                print(f"  buffer {name}: {len(changes) - 2} changes in {a.gif:.1f} s"
                      f" = {(len(changes) - 2) / a.gif:.1f} a second -> {a.dir / f'{a.name}.{name}.gif'}")
            return 0
        t_start = time.perf_counter()
        for k in range(a.n):
            t0 = time.perf_counter()
            bufs = {}
            for name, addr in BUFFERS.items():
                r = dp.decode_peek(pr.call(dp.req_peek, addr, SIZE))
                if r["addr"] != addr or len(r["data"]) != SIZE:
                    raise SystemExit(f"short PEEK at {addr:#010x}")
                bufs[name] = r["data"]
            took = time.perf_counter() - t0
            for name, buf in bufs.items():
                write_png(buf, a.dir / f"{a.name}.{k}.{name}.png", a.scale)
            print(f"  {k}: both buffers in {took * 1000:.0f} ms")
            if a.interval and k + 1 < a.n:
                time.sleep(a.interval)
        total = time.perf_counter() - t_start
        if a.n > 1:
            print(f"  {a.n} reads in {total:.1f} s = {a.n / total:.1f} a second")
    finally:
        port.close()
    print("  wrote", a.dir / f"{a.name}.*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

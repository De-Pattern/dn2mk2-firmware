"""A different start-up animation: re-scale the intro's tunnel.

`docs/ideas-backlog.md` §9. The Digitone's intro is not a canned animation, it is
a **polar tunnel** computed at boot (read 2026-09-17 in Ghidra, `FUN_400d3606`):
for each panel pixel, centred and normalised to about -1..1, with a random jitter
of `rand() % 12` on the centre,

    r = sqrt(u*u + v*v)      theta = atan2(v, u)
    source = ( cos(theta) / r * 128  & 127,   sin(theta) / r * 64  & 63 )

That table maps every panel pixel to a point on the logo texture; a scroll added
afterwards flies through it, and a final pass resolves to the plain logo. So the
logo is the texture on the wall of a tunnel.

**The two scale constants decide what the tunnel looks like.** `128.0` sets how
many times the texture wraps around and along the tunnel horizontally, `64.0`
vertically. They are 32-bit floats pushed as immediates:

    0x400d374e  move.l #0x43000000,%sp@-    | 128.0
    0x400d377e  move.l #0x42800000,%sp@     | 64.0

Raising them tiles the logo more times around the wall -- a denser, busier tunnel;
lowering them stretches one logo across more of it. Nothing else changes: the
masks still keep every coordinate on the bitmap, so no value can read out of
range, and the final resolve to the plain logo is untouched.

    python scripts/build_intro_tunnel.py --x-scale 512 --y-scale 256
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load

MAIN_OS = 3
BASE = 0x40000400

X_SCALE_VA = 0x400D374E            # move.l #<float>,-(sp)
X_SCALE_OP = bytes.fromhex("2f3c")
Y_SCALE_VA = 0x400D377E            # move.l #<float>,(sp)
Y_SCALE_OP = bytes.fromhex("2ebc")
STOCK_X, STOCK_Y = 128.0, 64.0

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/intro-tunnel_DN2_1.11.syx")


def f32(v: float) -> bytes:
    return struct.pack(">f", v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--x-scale", type=float, default=512.0, help=f"stock {STOCK_X}")
    ap.add_argument("--y-scale", type=float, default=256.0, help=f"stock {STOCK_Y}")
    args = ap.parse_args()
    for name, v in (("x", args.x_scale), ("y", args.y_scale)):
        if not 1.0 <= v <= 65536.0:
            raise SystemExit(f"{name}-scale {v} is outside 1..65536")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())

    for va, op, stock, new, name in (
        (X_SCALE_VA, X_SCALE_OP, STOCK_X, args.x_scale, "x scale"),
        (Y_SCALE_VA, Y_SCALE_OP, STOCK_Y, args.y_scale, "y scale"),
    ):
        off = va - BASE
        want = op + f32(stock)
        have = bytes(content[off:off + 6])
        if have != want:
            raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({name})")
        content[off:off + 6] = op + f32(new)
        print(f"  {va:#010x}  {name}: {stock} -> {new}   {want.hex()} -> {(op + f32(new)).hex()}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

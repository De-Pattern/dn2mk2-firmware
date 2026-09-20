"""Read a firmware `Bitmap` out of an emulator snapshot and write it as a PNG.

The intro is not drawn through `setPixel`: one routine displaces a source bitmap
through an animated offset table and copies the result to the panel
(`docs/display-path.md`). To see the undisplaced image -- what a mod stamp would
be added to -- read the source `Bitmap` directly.

    DIGIKIT=/mnt/d/01_Code/Z_Personal/digikit DT2_SECTIONS=/root/dt2-sections-115c \\
    /root/dn2-emu-venv/bin/python scripts/dump_bitmap.py \\
        snapshots/dt2_115c_ext400M.snap 0x43135268 out/source.png

A `Bitmap` is `+4 width, +8 height, +12 stride, +16 data`, all big-endian longs,
and a pixel is bit `31 - (y & 31)` of the long at `data + 4*(x*stride + (y>>5))`
-- the layout digikit's own `setPixel` HLE writes, so this reads back exactly
what the firmware drew. It writes a raw 1-byte-per-pixel PGM, so it needs no
imaging library inside the emulator's environment.
"""

from __future__ import annotations

import os
import struct
import sys


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    snapshot, bmp, out = sys.argv[1], int(sys.argv[2], 0), sys.argv[3]
    digikit = os.environ.get("DIGIKIT")
    if not digikit:
        raise SystemExit("set DIGIKIT to the digikit checkout")
    sys.path.insert(0, digikit)
    out = os.path.abspath(out)
    os.chdir(digikit)

    from emu.longrun import build

    m, ev, st, pc, inq, at = build(snapshot)
    w, h, stride, data = struct.unpack(">4I", bytes(m.uc.mem_read(bmp + 4, 16)))
    print(f"Bitmap {bmp:#x}: {w} x {h}, stride {stride}, data {data:#x}")
    if not (0 < w <= 1024 and 0 < h <= 1024):
        raise SystemExit("that does not look like a Bitmap header")

    words = (w * stride + (h >> 5) + 1) * 4
    raw = bytes(m.uc.mem_read(data, words))
    pix = bytearray(w * h)
    lit = 0
    for y in range(h):
        for x in range(w):
            word = struct.unpack_from(">I", raw, 4 * (x * stride + (y >> 5)))[0]
            if word & (0x80000000 >> (y & 31)):
                pix[y * w + x] = 235
                lit += 1
    with open(out, "wb") as f:
        f.write(b"P5\n%d %d\n255\n" % (w, h))
        f.write(pix)
    print(f"{lit} lit -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

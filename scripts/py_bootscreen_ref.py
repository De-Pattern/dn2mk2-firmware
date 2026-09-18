"""Write the Python boot-screen mod's MAIN OS for the cases `js_bootscreen_check.mjs` compares.

    PYTHONPATH=src python scripts/py_bootscreen_ref.py STOCK.zip OUT_DIR [PGM]
"""

from __future__ import annotations

import pathlib
import sys

from dnfw.cli.files import read_image
from dnfw.cli.mods import _read_pgm
from dnfw.firmware.load import load
from dnfw.mods import bootscreen


def main() -> int:
    stock, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    pgm = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else "site/art/chimera.pgm")
    firmware = load(read_image(stock))
    pix = _read_pgm(pgm)
    mark = bootscreen.image_from_pixels(pix)
    cases = [
        ([mark], {}),
        ([mark, bootscreen.invert(mark)], dict(slow=4, fast=3, rush=48, stop=72, tunnel=(96.0, 48.0))),
        ([], dict(ascii=bootscreen.ascii_frames(lambda x, y: (x, y) in pix, resolve=24, idle_frames=8, seed=7))),
        ([], dict(ascii=bootscreen.spin_frames(lambda x, y: (x, y) in pix, resolve=20, idle_frames=6, seed=5))),
    ]
    out.mkdir(parents=True, exist_ok=True)
    for k, (images, opts) in enumerate(cases):
        result = bootscreen.apply(firmware, images, **opts)
        (out / f"case{k}.bin").write_bytes(result.payloads[bootscreen.SECTION])
    print(f"wrote {len(cases)} cases to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

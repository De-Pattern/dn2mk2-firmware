"""PING feasibility (docs/ping.md): what the DSP makes of each FLTR-page filter type.

    python scripts/sharc_filter_probe.py [--image STOCK.syx] [--digikit DIR]

For ColdFire filter types 0..9 in frame field 180 + 2t, one block of the stock
per-block routine (sw 0x1c2712: the frame unpack, then the dispatch) in the SHARC
runner, on the STOCK section 7, then: the DSP filter number the unpack wrote to the
track record (+0x1dc), and the engine's per-track cache of it (+0x13840 + 4t). The
stock map is expected to be 0->1, 1->3, 2->2, 3->4, 4->5, 5->6, and the question is
what 6 and above become. Nothing is patched; this only reads.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import sharc_waverider_m5 as m5                 # noqa: E402
from dnfw.waverider import frame as FR           # noqa: E402
from dnfw.waverider import voice as V            # noqa: E402

FILTER_CACHE = V.ENGINE + 0x13840


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT.parent / "Digitone_II_OS1.11.syx")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC", ROOT.parent / "digikit-wt-sharcemu")))
    a = p.parse_args()
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    sound, machines = m5.m4.init_sound(a.image)
    img = m5.Image(dk, stock)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, img)
        print(" type  record+0x1dc  engine cache")
        for cf in range(10):
            def frames(b, cf=cf):
                f = m5.base_frame(sound, machines, t0=0, trigger=True)
                f.header(FR.FILTER, 0, cf)
                return f.to_bytes()
            r = m5.run_blocks(init, frames, 1)
            if not r["ok"]:
                print(f"  {cf}: halted {r.get('halt')}")
                continue
            st = r["state"].state
            rec = m5.m2.word(st, V.track_record(0) + 0x1DC)
            cache = m5.m2.word(st, FILTER_CACHE)
            print(f"  {cf:3d}  {rec!s:>12}  {cache!s:>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

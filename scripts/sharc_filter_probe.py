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


if __name__ == "__main__" and not (len(sys.argv) > 1 and sys.argv[1] in ("entry", "chain")):
    raise SystemExit(main())


def at_entry(argv=None) -> int:
    """Track 1 on FM Tone with filter type 6, triggered: its buffer and record filter
    fields where Waverider's loop is entered (sw 0x1c9448), and its buffer at the end
    of the block. Equal buffers mean nothing after the entry touched the signal before
    the amp (`m5.AMP_STAGE` tap): the chain had no filter to run."""
    p = argparse.ArgumentParser()
    p.add_argument("--image", type=pathlib.Path, default=ROOT.parent / "Digitone_II_OS1.11.syx")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC", ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--filter", type=int, default=6)
    p.add_argument("--machine", type=int, default=1)
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    sound, machines = m5.m4.init_sound(a.image)
    img = m5.Image(dk, stock)
    import struct
    import tempfile
    from dnfw.waverider import dsp
    seen = {}

    def entry(r):
        bufs = [m5.m2.word(r.state, V.TRACK_BUFFERS + 4 * t) for t in range(16)]
        seen["buf"] = m5.m2.floats(r.state, bufs[1], m5.BLOCK)
        rec = V.track_record(1)
        seen["fields"] = {hex(o): struct.unpack("<f", struct.pack("<I", m5.m2.word(r.state, rec + o) or 0))[0]
                          for o in range(0x1C8, 0x20C, 4)}
        seen["n"] = m5.m2.word(r.state, rec + 0x1DC)
        seen["bufaddr"] = bufs[1]

    with tempfile.TemporaryDirectory() as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, img)

        def frames(b):
            f = m5.base_frame(sound, machines, t0=0, others={1: a.machine}, trigger=True, trigger_others=True)
            f.header(FR.FILTER, 1, a.filter)
            return f.to_bytes()
        r = m5.run_blocks(init, frames, 3, extra_hooks={dsp.ENTRY_SW: entry})
        if not r["ok"]:
            print("halted", r.get("halt"))
            return 1
        end = r["buffers"][-1][1]
        print("filter type", a.filter, "-> DSP number", seen["n"])
        print("track 1 buffer at entry, peak", max(abs(x) for x in seen["buf"]))
        print("track 1 buffer at block end, peak", max(abs(x) for x in end),
              "identical to entry:", end == seen["buf"])
        for k, v in seen["fields"].items():
            print(f"   record {k}: {v:.6g}")
    return 0


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "entry":
    raise SystemExit(at_entry(sys.argv[2:]))


def chain(argv=None) -> int:
    """Track 0 on WaveTone, filter type 6 (DSP 'no filter'): the buffer where Waverider's
    loop is entered against the amp stage's input. Bit-identical means nothing in the
    per-track chain runs before the (skipped) filter stage, so PING applied at the
    entry sits exactly where the filter would."""
    import tempfile
    from dnfw.waverider import dsp
    dk = m5.m1.Digikit(ROOT.parent / "digikit-wt-sharcemu")
    m5.fx.bind(str(ROOT.parent / "digikit-wt-sharcemu" / "tools"))
    image = ROOT.parent / "Digitone_II_OS1.11.syx"
    m5.m4.IMAGE = image
    stock = m5.m1.dn2_section7(image)
    sound, machines = m5.m4.init_sound(image)
    img = m5.Image(dk, stock)
    seen = []

    def entry(r):
        b0 = m5.m2.word(r.state, V.TRACK_BUFFERS)
        seen.append(m5.m2.floats(r.state, b0, m5.BLOCK))

    with tempfile.TemporaryDirectory() as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, img)
        for cf in (6, 0):
            seen.clear()

            def frames(b, cf=cf):
                f = m5.base_frame(sound, machines, t0=1, trigger=(b == 1))
                f.header(FR.FILTER, 0, cf)
                return f.to_bytes()
            r = m5.run_blocks(init, frames, 3, extra_hooks={dsp.ENTRY_SW: entry})
            amp_in = [r["amp_in"][k * m5.BLOCK:(k + 1) * m5.BLOCK] for k in range(3)]
            same = [a == b for a, b in zip(seen, amp_in)]
            peak = max(abs(x) for blk in seen for x in blk)
            print(f"filter type {cf}: entry peak {peak:.3f}; amp input == entry buffer per block: {same}")
            for k in range(3):
                e, a_ = seen[k][:6], amp_in[k][:6]
                print("   entry", [round(x, 5) for x in e])
                print("   amp  ", [round(x, 5) for x in a_])
    return 0


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "chain":
    raise SystemExit(chain(sys.argv[2:]))

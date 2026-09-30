"""Waverider against frames read off the instrument: each with its own known answer.

    python scripts/sharc_waverider_m6_probe_frames.py [--dir out/probe-frames]

Milestone 6's first build read TUN1, WAV1 and TBL1 at half the sound's value,
because the gates built their frames from `dnfw.waverider.frame`'s model and
compared the loop with `dnfw.waverider.live`, and both carried that assumption.
On the instrument the pitch clamped. So these checks use neither.

The frames are the ones the ColdFire built on the instrument
(`tools/dn2probe_frame.py`, 2026-09-30: track 1 Waverider, C5, plain sound),
and each check states the musical answer in its own terms:

| capture | the owner set | expected |
|---|---|---|
| `tun0` | TUN1 0 | the phase step of note 60 |
| `tunp12oct` | TUN1 +12 | exactly twice `tun0`'s |
| `tunm12oct` | TUN1 -12 | exactly half `tun0`'s |
| `wav1max` | TUN1 -12, WAV1 at its top | POS = frame 15 (15 << 16) |
| `tbl1` | TUN1 -12, WAV1 top, TBL1 1 | the table pointer of table 1 |

Each frame is run through the firmware's own per-block routine with the M6
image in digikit's SHARC runner; the loop's reader block for track 0 is read
back and compared.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as m5                                # noqa: E402
from dnfw.waverider import dsp, live                           # noqa: E402

NOTE60 = live.increment(60.0)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", type=pathlib.Path, default=ROOT / "out/probe-frames")
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--blocks", type=int, default=3)
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, dsp.section7(stock))
    rb = {}
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, image)
        for name in ("tun0", "tunp12oct", "tunm12oct", "wav1max", "tbl1"):
            frame = m5.swap16((a.dir / f"{name}.frame_be.0.bin").read_bytes())
            run = m5.run_blocks(init, lambda b, f=frame: f, a.blocks)
            block = run["reader_blocks"][-1].get(0) if run["ok"] and run["reader_blocks"] else None
            rb[name] = block
            print(f"  {name:10} reader block {block}")
    inc = {k: (v[2] if v else 0) for k, v in rb.items()}
    checks = {
        "TUN1 0 plays note 60's phase step": inc["tun0"] == NOTE60,
        "TUN1 +12 is exactly an octave up (twice the step, within 1e-6)":
            bool(inc["tun0"]) and abs(inc["tunp12oct"] / inc["tun0"] - 2.0) < 1e-6,
        "TUN1 -12 is exactly an octave down (half the step, within 1e-6)":
            bool(inc["tun0"]) and abs(inc["tunm12oct"] / inc["tun0"] - 0.5) < 1e-6,
        "WAV1 at its top is the last frame (POS = 15 << 16)": bool(rb["wav1max"]) and rb["wav1max"][3] == 15 << 16,
        "TBL1 1 selects table 1": bool(rb["tbl1"]) and rb["tbl1"][0] == dsp.TABLES_DM[1],
        "control: TBL1 0 selects table 0": bool(rb["wav1max"]) and rb["wav1max"][0] == dsp.TABLES_DM[0],
    }
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

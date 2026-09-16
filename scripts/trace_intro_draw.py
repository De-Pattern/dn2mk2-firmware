"""Which code draws which part of the start-up screen.

Blocks two backlog entries -- §9 (a custom start-up animation) and §13 (a mod
stamp on the intro screen) -- which both need the same fact: which routine draws
the logo, which draws the version text, and where on the 128 x 64 panel each
lands. That is a trace question, not a scan question.

Runs under digikit's emulator as a library, from a snapshot, with the draw task
unblocked and `Bitmap::setPixel` served by digikit's HLE. Every pixel is
attributed to the return address of its `setPixel` call, via
`emu.hle.LAST_PIXEL_CALLER` (digikit branch `emu/setpixel-caller`). Nothing is
kept per frame -- only per caller -- so a 400M-instruction run stays small.

    DIGIKIT=/mnt/c/ZZ_Code/ZZ_Personal/digikit \\
    DT2_SECTIONS=/root/dt2-sections-115c \\
    /root/dn2-emu-venv/bin/python scripts/trace_intro_draw.py \\
        snapshots/dt2_115c60M.snap 360000000 out/intro-dt2.json

Output, per caller: pixels set, pixels lit, the bounding box on its bitmap, the
bitmap, and the instruction count of its first and last pixel (to the nearest
slice). Plus the final contents of every bitmap that was drawn, so the picture
can be rendered and compared with the attribution.

Digitakt first, on the owner's advice: it is the image digikit supports best.
What carries across to the Digitone is the structure -- how many callers, in
what order, drawing what shape -- not the addresses.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot")
    ap.add_argument("instrs", type=int)
    ap.add_argument("out")
    ap.add_argument("--slice", type=int, default=20_000_000,
                    help="instructions per progress line (default 20M)")
    args = ap.parse_args()

    digikit = os.environ.get("DIGIKIT")
    if not digikit:
        raise SystemExit("set DIGIKIT to the digikit checkout (see docs/emulator.md)")
    sys.path.insert(0, digikit)
    os.chdir(digikit)                       # snapshot paths are relative to it

    import emu.hle as hle
    from emu.longrun import build, spin

    if not hasattr(hle, "LAST_PIXEL_CALLER"):
        raise SystemExit("this digikit has no emu.hle.LAST_PIXEL_CALLER -- "
                         "merge branch emu/setpixel-caller")

    now = {"n": 0}
    callers: dict[int, dict] = {}
    bitmaps: dict[int, dict] = collections.defaultdict(dict)

    def on_pixel(x, y, val, bmp):
        ret = hle.LAST_PIXEL_CALLER
        c = callers.get(ret)
        if c is None:
            c = callers[ret] = {"set": 0, "lit": 0, "bitmaps": set(),
                                "x0": x, "y0": y, "x1": x, "y1": y,
                                "first": now["n"], "last": now["n"]}
        c["set"] += 1
        c["lit"] += val
        c["bitmaps"].add(bmp)
        if x < c["x0"]: c["x0"] = x
        if y < c["y0"]: c["y0"] = y
        if x > c["x1"]: c["x1"] = x
        if y > c["y1"]: c["y1"] = y
        c["last"] = now["n"]
        bitmaps[bmp][(x, y)] = val

    m, ev, st, pc, inq, at = build(args.snapshot, unblock=True, softfloat=True,
                                   bitmap=True, on_pixel=on_pixel)
    print(f"built from {args.snapshot}; running {args.instrs:,} instructions")

    t0, stop = time.time(), None
    while now["n"] < args.instrs:
        step = min(args.slice, args.instrs - now["n"])
        pc, done, stop = spin(m, pc, step)
        now["n"] += done
        px = sum(c["set"] for c in callers.values())
        print(f"  {now['n']/1e6:7.0f}M  pixels {px:>10,}  callers {len(callers):>3}  "
              f"pends satisfied {ev.get('satisfied', 0):>5}  "
              f"{now['n']/max(time.time()-t0, 1e-9)/1e6:.2f}M/s  stop={stop}", flush=True)
        if done < step:
            break

    ranked = sorted(callers.items(), key=lambda kv: -kv[1]["set"])
    print("\ncaller        pixels      lit   bbox (x0,y0)-(x1,y1)   bitmap(s)")
    for ret, c in ranked[:30]:
        bm = ",".join(f"{b:#x}" for b in sorted(c["bitmaps"]))
        print(f"  {ret:#010x}  {c['set']:>9,}  {c['lit']:>7,}   "
              f"({c['x0']:>3},{c['y0']:>3})-({c['x1']:>3},{c['y1']:>3})   {bm}")

    out = {
        "snapshot": args.snapshot,
        "instructions": now["n"],
        "stop": str(stop),
        "pends_satisfied": ev.get("satisfied", 0),
        "callers": [
            {"caller": f"{ret:#010x}", "set": c["set"], "lit": c["lit"],
             "bbox": [c["x0"], c["y0"], c["x1"], c["y1"]],
             "bitmaps": [f"{b:#x}" for b in sorted(c["bitmaps"])],
             "first": c["first"], "last": c["last"]}
            for ret, c in ranked
        ],
        "bitmaps": {
            f"{b:#x}": [[x, y] for (x, y), v in sorted(px.items()) if v]
            for b, px in bitmaps.items()
        },
    }
    path = os.path.join(os.environ.get("TRACE_OUT_ROOT", ""), args.out) \
        if not os.path.isabs(args.out) else args.out
    with open(path, "w") as f:
        json.dump(out, f)
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

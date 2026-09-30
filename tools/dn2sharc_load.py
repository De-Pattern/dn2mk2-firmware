"""Benchmark the SHARC: its per-frame cycle count, read off the reply it sends the ColdFire.

    python tools/dn2sharc_load.py LABEL [--n 100] [--csv out/sharc-load.csv]
    python tools/dn2sharc_load.py LABEL --idle [--seconds 1] [--n 10]
                                  the SHARC's whole load, from its idle time (a build
                                  with idle_load.asm: dnfw.waverider.dsp, patch 4)

    e.g.  silent                  first, with nothing sounding: the baseline
          waverider-1             one held note on a Waverider track
          fmtone-1                the same note on FM Tone, and so on

Needs a usbprobe build (it reads with PEEK, read-only).

The SHARC's per-frame handler (sw `0x1c9d6b`) ends by storing its own EMUCLK
cycle count in word 0 of the reply ring, halves swapped so a big-endian reader
of 16-bit halves gets it in order (`docs/waverider-dsp-compare.md`,
`docs/for-digikit-coldfire-sharc-link.md` section 7). The ColdFire receives that
reply at `0x800053a4` every frame, so a big-endian u32 there is the cycles the
DSP's frame took. Read on the instrument 2026-09-30: about 416,000 silent.

Each reading is one PEEK, so N readings are N frames sampled at the round
trip's pace, not consecutive frames. The row printed and appended to the CSV is
the median, the 5th and 95th percentile, the extremes, and the median's
difference from the CSV's latest `silent` row: the cost of what LABEL added.
A benchmark wants the same track, the same note and no overdrive or FX, so
only the synth differs.

**Word 0 misleads** around a Waverider track (docs/sharc-load.md, the benchmark):
it is one handler's span, not the frame. **`--idle`** reads the whole load instead.
A build with `idle_load.asm` keeps the idle task's own cycles, cumulative, in reply
word 1 (0x800053a8 on the ColdFire). Two readings SECONDS apart, each with the
ColdFire's frame count from STATS, give

    load = 1 - d(idle) / (d(frames) * FRAME_CYCLES)

one row per interval, N intervals. A build without the stub leaves word 1 at 0 (or a
stale value) and the tool says so. A build with `block_count.asm` also keeps the
per-block routine's passes in reply word 2, printed as blocks per second of frames
(1,500 would be one per frame); word 2 at 0 is shown as `--`. A build whose idle stub
splits busy stretches at block_count.asm's MARK (reply words 3 and 4) also prints the
busy time before the dispatch's splice, after it, and elsewhere, as shares of the frame.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

REPLY = 0x800053A4
IDLE_WORD = REPLY + 4                 # reply word 1: idle_load.asm's cumulative idle cycles
BLOCKS_WORD = REPLY + 8               # reply word 2: block_count.asm's cumulative per-block passes
# reply words 3, 4: idle_load.asm's busy time split at the dispatch's MARK (before / after it)
FRAME_CYCLES = 1_000_000_000 / 1500   # the core's 1 GHz (docs/sharc-load.md, the clock) per frame
COLUMNS = ("when", "label", "n", "median", "p5", "p95", "min", "max", "over_silent")


def cycles(word0: bytes) -> int:
    """Reply word 0, as the ColdFire holds it -> the frame's SHARC cycles."""
    return struct.unpack(">I", word0[:4])[0]


def summary(values: list[int]) -> dict:
    v = sorted(values)
    at = lambda q: v[min(len(v) - 1, int(q * len(v)))]
    return {"n": len(v), "median": at(0.5), "p5": at(0.05), "p95": at(0.95), "min": v[0], "max": v[-1]}


def load_from_idle(a: tuple[int, int], b: tuple[int, int]) -> float | None:
    """Two (idle total, frames) readings -> the SHARC's load, 0..1; None if no frame passed."""
    d_idle = (b[0] - a[0]) & 0xFFFFFFFF
    d_frames = (b[1] - a[1]) & 0xFFFFFFFF
    if not d_frames:
        return None
    return 1.0 - d_idle / (d_frames * FRAME_CYCLES)


def baseline(path: pathlib.Path) -> int | None:
    """The latest `silent` row's median in the CSV, if there is one."""
    if not path.exists():
        return None
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8")) if r["label"] == "silent"]
    return int(rows[-1]["median"]) if rows else None


def append(path: pathlib.Path, row: dict) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("label")
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--csv", type=pathlib.Path, default=HERE.parent / "out" / "sharc-load.csv")
    p.add_argument("--port", default="Digitone II")
    p.add_argument("--idle", action="store_true", help="the whole load, from the idle stub's word 1")
    p.add_argument("--seconds", type=float, default=1.0)
    a = p.parse_args(argv)
    import dn2probe as dp
    import winmidi
    port = winmidi.Port(a.port, None, None)
    if a.idle:
        try:
            return idle_main(dp, dp.Probe(port), a)
        finally:
            port.close()
    try:
        pr = dp.Probe(port)
        values = []
        for _ in range(a.n):
            r = dp.decode_peek(pr.call(dp.req_peek, REPLY, 4))
            values.append(cycles(r["data"]))
    finally:
        port.close()
    s = summary(values)
    base = baseline(a.csv)
    s["over_silent"] = "" if base is None or a.label == "silent" else s["median"] - base
    row = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "label": a.label, **s}
    append(a.csv, row)
    extra = "" if s["over_silent"] == "" else "   %+d over silent" % s["over_silent"]
    print("%-16s median %7d cycles = %.1f %% of a frame  (p5 %d, p95 %d, %d..%d, n %d)%s"
          % (a.label, s["median"], 100 * s["median"] / FRAME_CYCLES, s["p5"], s["p95"],
             s["min"], s["max"], s["n"], extra))
    print("  appended to", a.csv)
    return 0


def idle_main(dp, pr, a) -> int:
    def reading():
        data = dp.decode_peek(pr.call(dp.req_peek, IDLE_WORD, 16))["data"]
        frames = dp.decode_stats(pr.call(dp.req_stats))["frames"]
        return cycles(data[:4]), frames, cycles(data[4:8]), cycles(data[8:12]), cycles(data[12:16])
    prev, loads = reading(), []
    for _ in range(a.n if a.n != 100 else 10):
        time.sleep(a.seconds)
        cur = reading()
        if cur[0] == prev[0]:
            print("  reply word 1 did not move: this build has no idle stub, or the SHARC never idled")
            return 1
        v = load_from_idle(prev[:2], cur[:2])
        if v is not None:
            loads.append(v)
            frames = (cur[1] - prev[1]) & 0xFFFFFFFF
            blocks = (cur[2] - prev[2]) & 0xFFFFFFFF
            per = "--" if not cur[2] else "%.2f blocks/frame" % (blocks / frames)
            split = ""
            if cur[3] or cur[4]:
                span = frames * FRAME_CYCLES
                before = ((cur[3] - prev[3]) & 0xFFFFFFFF) / span
                after = ((cur[4] - prev[4]) & 0xFFFFFFFF) / span
                split = "; before %.1f %%, after %.1f %%, other %.1f %%" % (
                    100 * before, 100 * after, 100 * (v - before - after))
            print("  %-16s SHARC load %5.1f %%   (idle %d cycles over %d frames; %s%s)"
                  % (a.label, 100 * v, (cur[0] - prev[0]) & 0xFFFFFFFF, frames, per, split))
        prev = cur
    loads.sort()
    med = loads[len(loads) // 2]
    append(a.csv.with_name("sharc-idle-load.csv"), {"when": time.strftime("%Y-%m-%d %H:%M:%S"),
           "label": a.label, "n": len(loads), "median": round(100 * med, 2), "p5": round(100 * loads[0], 2),
           "p95": round(100 * loads[-1], 2), "min": round(100 * loads[0], 2), "max": round(100 * loads[-1], 2),
           "over_silent": ""})
    print("%-16s SHARC load median %.1f %% (%.1f..%.1f, %d intervals)"
          % (a.label, 100 * med, 100 * loads[0], 100 * loads[-1], len(loads)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

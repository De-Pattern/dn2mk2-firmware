"""Benchmark the SHARC: its per-frame cycle count, read off the reply it sends the ColdFire.

    python tools/dn2sharc_load.py LABEL [--n 100] [--csv out/sharc-load.csv]

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
COLUMNS = ("when", "label", "n", "median", "p5", "p95", "min", "max", "over_silent")


def cycles(word0: bytes) -> int:
    """Reply word 0, as the ColdFire holds it -> the frame's SHARC cycles."""
    return struct.unpack(">I", word0[:4])[0]


def summary(values: list[int]) -> dict:
    v = sorted(values)
    at = lambda q: v[min(len(v) - 1, int(q * len(v)))]
    return {"n": len(v), "median": at(0.5), "p5": at(0.05), "p95": at(0.95), "min": v[0], "max": v[-1]}


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
    a = p.parse_args(argv)
    import dn2probe as dp
    import winmidi
    port = winmidi.Port(a.port, None, None)
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
    print("%-16s median %7d cycles  (p5 %d, p95 %d, %d..%d, n %d)%s"
          % (a.label, s["median"], s["p5"], s["p95"], s["min"], s["max"], s["n"], extra))
    print("  appended to", a.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

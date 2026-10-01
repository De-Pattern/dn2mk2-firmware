"""Measure what Waverider's page costs to draw, live, on a modview build.

    python tools/dn2modview.py LABEL [--n 10] [--seconds 1] [--slot 26] [--csv out/modview.csv]

    e.g.  idle        the Waverider SYN page on screen, nothing touched, stopped
          turning     turning POS (encoder C) the whole time
          playing     a pattern playing on the Waverider track
          lfo-pos     an LFO on POS (WAV1): with --slot 26, the value heard moves

Needs a modview build (scripts/build_modview_probe.py): the usbprobe plus a probe
block in the page renderer (csrc/waverider/page.c, `WR_PROBE`) counting every page
draw and the DTCN0 ticks it takes (build 2 also times its markers). The block is found
from the build's `.modview.json` (the one in 00_Resources/02_Builds whose tag the
probe answers HELLO with, or --json), or
--addr. Each interval reads STATS and the block, twice, and prints:

- draws/s: how often the page really redraws;
- us/draw, and us/draw in the markers;
- page %: the share of the ColdFire's time spent drawing the page (markers %: in them);
- CPU %: the probe's whole ColdFire load (1 - idle), for comparison.

`--slot S` also reads slot S of the active track's value array (0x800068e4 + 34 +
202 t + 2 s): the value heard, as the audio tick left it, at the record's own scale for a linear
parameter (instrument: POS 74 reads 0x4a00 = 74 << 8; docs/modulation-display.md).
Only reads; read-only PEEK.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BUILDS = HERE.parent / "00_Resources" / "02_Builds"

MAGIC = 0x57525052                     # "WRPR"
ACTIVE_TRACK = 0x42431A6C
VALUES = 0x800068E4
COLUMNS = ("when", "label", "tag", "draws_s", "us_draw", "us_markers", "page_pct", "markers_pct",
           "cpu_pct", "slot", "heard")


def find_json(path: pathlib.Path | None, tag: str) -> dict:
    """The build's .modview.json: PATH, or the one in 02_Builds whose tag is what the
    probe answers HELLO with."""
    if path is not None:
        return json.loads(path.read_text())
    for found in sorted(BUILDS.glob("*.modview.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = json.loads(found.read_text())
        if meta.get("tag") == tag:
            return meta
    raise SystemExit(f"no .modview.json for {tag!r} in 00_Resources/02_Builds; pass --json or --addr")


def read(dp, pr, addr: int, n: int) -> bytes:
    r = dp.decode_peek(pr.call(dp.req_peek, addr, n))
    if r["addr"] != addr or len(r["data"]) != n:
        raise ValueError(f"short PEEK at {addr:#010x}")
    return r["data"]


def block(dp, pr, addr: int) -> dict:
    magic, draws, ticks, marker, markers, _ = struct.unpack(">6I", read(dp, pr, addr, 24))
    if magic != MAGIC:
        raise SystemExit(f"{addr:#010x} holds {magic:#010x}, not the probe block: wrong build?")
    return {"draws": draws, "ticks": ticks, "marker": marker, "markers": markers}


def heard(dp, pr, slot: int) -> tuple[int, int]:
    t = read(dp, pr, ACTIVE_TRACK, 1)[0]
    raw = struct.unpack(">H", read(dp, pr, VALUES + 34 + 202 * t + 2 * slot, 2))[0]
    return t, raw


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
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--seconds", type=float, default=1.0)
    p.add_argument("--json", type=pathlib.Path, default=None)
    p.add_argument("--addr", type=lambda s: int(s, 0), default=None)
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--csv", type=pathlib.Path, default=HERE.parent / "out" / "modview.csv")
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import dn2probe as dp
    import winmidi
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        tag = dp.decode_hello(pr.call(dp.req_hello))["tag"]
        meta = {} if a.addr is not None else find_json(a.json, tag)
        addr = a.addr if a.addr is not None else meta["probe"]
        s0, b0 = dp.decode_stats(pr.call(dp.req_stats)), block(dp, pr, addr)
        print(f"{tag}: probe block at {addr:#010x}, markers {'on' if b0['markers'] else 'off'}")
        for _ in range(a.n):
            time.sleep(a.seconds)
            s1, b1 = dp.decode_stats(pr.call(dp.req_stats)), block(dp, pr, addr)
            d = dp.delta(s0, s1)
            if not d.get("ticks_per_s"):
                print("no timer reading in STATS: is this a protocol-3 usbprobe build?")
                return 1
            hz, span = d["ticks_per_s"], d["dtcn0"]
            draws = (b1["draws"] - b0["draws"]) & 0xFFFFFFFF
            ticks = (b1["ticks"] - b0["ticks"]) & 0xFFFFFFFF
            mark = (b1["marker"] - b0["marker"]) & 0xFFFFFFFF
            row = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "label": a.label, "tag": tag,
                   "draws_s": round(draws / (span / hz), 1),
                   "us_draw": round(ticks / draws / hz * 1e6, 1) if draws else "",
                   "us_markers": round(mark / draws / hz * 1e6, 1) if draws else "",
                   "page_pct": round(100 * ticks / span, 3),
                   "markers_pct": round(100 * mark / span, 3),
                   "cpu_pct": round(100 * d["cpu"], 1) if "cpu" in d else "",
                   "slot": "", "heard": ""}
            if a.slot is not None:
                t, raw = heard(dp, pr, a.slot)
                row["slot"], row["heard"] = f"t{t + 1}:{a.slot}", f"{raw:#06x} ({raw / 256:.1f})"
            append(a.csv, row)
            print("%-10s %6s draws/s  %7s us/draw  (markers %6s us)  page %6.3f %%  markers %6.3f %%"
                  "  CPU %5s %%  %s"
                  % (a.label, row["draws_s"], row["us_draw"], row["us_markers"], row["page_pct"],
                     row["markers_pct"], row["cpu_pct"],
                     f"heard {row['slot']} = {row['heard']}" if row["slot"] else ""))
            s0, b0 = s1, b1
    finally:
        port.close()
    print("  appended to", a.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Record the instrument's audio and its telemetry together, on one clock.

    python scripts/audio_sync.py --seconds 20
    python scripts/audio_sync.py --seconds 20 --csv out/sync.csv

**The question this exists for.** "Is the modulation happening?" has been
answered by one person listening. It is measurable: a modulated timbre *moves*,
and movement is a number. This records the Digitone's own USB audio and the
telemetry the firmware is emitting in the same seconds, so the two can be put
side by side instead of one being taken on trust.

**Alignment.** `midi_live.py` already parses the sequencer's `start`, `stop` and
`continue`, so stopping and starting the sequence puts a hard marker in the same
stream as the telemetry -- the owner's own suggestion, and better than any
timestamp negotiation.

**No numpy, so the measures are ones that do not need it.** Per window:

- **RMS** -- amplitude. Catches an LFO reaching a level destination.
- **Zero-crossing rate** -- a cheap brightness proxy. Catches an LFO reaching a
  timbral destination, which is what `Synth Ratio C` is.

Neither is a spectrum. They do not need to be: the question is whether a number
*moves periodically*, not what the timbre is. A still number under a running LFO
is the finding; which harmonic moved is not.

**Read-only on both ports.** Audio in, MIDI over the probe's HTTP stream. Nothing
is sent to the instrument.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from audio_probe import InStream, list_inputs                  # noqa: E402

WINDOW_MS = 20
CC_NAMES = {20: "track", 21: "lo", 22: "mid", 24: "dest", 26: "probe_a", 30: "marker"}


def midi_thread(url: str, events: list, stop: threading.Event, t0: float) -> None:
    """Drain the probe's SSE stream into `events`, stamped on our own clock."""
    try:
        r = urllib.request.urlopen(url, timeout=10)
    except Exception as exc:                                    # noqa: BLE001
        events.append({"t": 0.0, "error": str(exc)})
        return
    while not stop.is_set():
        line = r.readline()
        if not line:
            return
        line = line.decode("utf-8", "replace").strip()
        if not line.startswith("data: "):
            continue
        ev = json.loads(line[6:])
        ev["t_local"] = time.time() - t0
        events.append(ev)


def windows(pcm: bytes, rate: int, channels: int, window_ms: int):
    """-> (t, rms, zcr) per window. Left channel only; the DN2's USB out is a
    stereo pair of the same program, and one channel halves the work."""
    step = max(1, (rate * window_ms) // 1000)
    frame = 2 * channels
    n = len(pcm) // frame
    out = []
    for start in range(0, n - step, step):
        acc, crossings, prev = 0, 0, 0
        for i in range(start, start + step):
            v = struct.unpack_from("<h", pcm, i * frame)[0]
            acc += v * v
            if (v >= 0) != (prev >= 0):
                crossings += 1
            prev = v
        out.append((start / rate,
                    int((acc / step) ** 0.5),
                    crossings * (rate / step) / 2.0))
    return out


def spark(vals, lo=None, hi=None, width=60):
    if not vals:
        return ""
    lo = min(vals) if lo is None else lo
    hi = max(vals) if hi is None else hi
    if hi <= lo:
        return "-" * min(width, len(vals))
    bars = " .:-=+*#%@"
    stride = max(1, len(vals) // width)
    out = []
    for i in range(0, len(vals), stride):
        chunk = vals[i:i + stride]
        v = sum(chunk) / len(chunk)
        out.append(bars[min(len(bars) - 1, int((v - lo) / (hi - lo) * (len(bars) - 1)))])
    return "".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--in", dest="index", type=int, default=0)
    p.add_argument("--seconds", type=float, default=20.0)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--probe", default="http://127.0.0.1:8737/events")
    p.add_argument("--csv")
    args = p.parse_args()

    names = list_inputs()
    if args.index >= len(names):
        print(f"  no audio input {args.index}; there are {len(names)}")
        return 1
    if "Elektr" not in names[args.index]:
        print(f"  warning: input {args.index} is {names[args.index]!r}, which does not")
        print( "  look like the instrument. Pass --in for the Elektron device.")

    t0 = time.time()
    events: list = []
    stop = threading.Event()
    threading.Thread(target=midi_thread, args=(args.probe, events, stop, t0),
                     daemon=True).start()

    print(f"  recording {args.seconds}s from [{args.index}] {names[args.index]}")
    print( "  (stop and start the sequencer whenever you like: it marks the stream)")
    stream = InStream(args.index, rate=args.rate)
    pcm = bytearray()
    try:
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            pcm += stream.read()
            time.sleep(0.004)
        pcm += stream.read()
    finally:
        stream.close()
        stop.set()

    frames = len(pcm) // 4
    print(f"\n  audio: {frames:,} frames = {frames / args.rate:.2f}s")
    if not frames:
        print("  nothing arrived from the audio device.")
        return 1

    win = windows(bytes(pcm), args.rate, 2, WINDOW_MS)
    rms = [v[1] for v in win]
    zcr = [v[2] for v in win]
    print(f"  windows: {len(win)} of {WINDOW_MS} ms\n")

    print(f"  RMS  {min(rms):>6} .. {max(rms):>6}   |{spark(rms)}|")
    print(f"  ZCR  {min(zcr):>6.0f} .. {max(zcr):>6.0f}   |{spark(zcr)}|")

    # movement is the measurement: a still number under a running LFO is the finding
    def spread(v):
        m = sum(v) / len(v)
        return (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5, m
    sd_r, mean_r = spread(rms)
    sd_z, mean_z = spread(zcr)
    print(f"\n  RMS  mean {mean_r:8.1f}  sd {sd_r:8.1f}  ({100 * sd_r / max(1, mean_r):5.1f}% )")
    print(f"  ZCR  mean {mean_z:8.1f}  sd {sd_z:8.1f}  ({100 * sd_z / max(1, mean_z):5.1f}% )")

    sysev = [e for e in events if e.get("kind") in ("start", "stop", "continue")]
    ccs = [e for e in events if e.get("kind") == "cc"]
    print(f"\n  telemetry: {len(ccs)} CC, {len(sysev)} transport event(s)")
    for e in sysev:
        print(f"    {e['t_local']:7.3f}s  {e['kind']}")

    seen = {}
    for e in ccs:
        n = CC_NAMES.get(e["d1"])
        if n:
            seen.setdefault(n, set()).add(e["d2"])
    for n, vals in sorted(seen.items()):
        v = sorted(vals)
        print(f"    {n:<8} {len(v):>4} distinct  {v[:8]}{' ...' if len(v) > 8 else ''}")

    if args.csv:
        pathlib.Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="\n") as f:
            f.write("t,rms,zcr\n")
            for t, r, z in win:
                f.write(f"{t:.4f},{r},{z:.1f}\n")
        print(f"\n  wrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

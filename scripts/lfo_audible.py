"""Is the modulation audible? Measure it, instead of asking someone to listen.

    python scripts/lfo_audible.py record --label voice7 --seconds 20
    python scripts/lfo_audible.py record --label voice-other --seconds 20
    python scripts/lfo_audible.py compare

**Why a tool and not an opinion.** Everything the LFO4 work believes about the
"voice gate" rests on whether a sweep is *heard*. "Inaudible" and "present but
half the depth of the other LFO" sound identical to a listener and are entirely
different findings -- and LFO4's measured span in the mirror is half LFO1's, so
that distinction is live rather than pedantic.

**What it measures.** An LFO modulating a timbre makes the sound's brightness
rise and fall **periodically, at the LFO's rate**. So: cut the audio into 20 ms
windows, take each window's RMS (level) and zero-crossing rate (a cheap
brightness proxy), and ask how much of that envelope sits at a single low
frequency. A Goertzel filter over 0.2-12 Hz gives the peak and its strength
without needing numpy, which is not installed here.

The number that matters is the **modulation index**: the amplitude at the peak
frequency divided by the envelope's mean. A still timbre scores near zero
whatever its loudness; a swept one scores well above it, and the score does not
care how loud the instrument is set.

**Telemetry runs beside it, as the control.** The firmware reports the mirror
slot it is writing. If the slot sweeps in both runs while the audio only moves
in one, that is the finding -- the value reaches the mirror but not the sound.
If the slot does not sweep, the run is void and the tool says so rather than
reporting a confident zero.

**Read-only.** Audio in, telemetry over the probe's HTTP stream. Nothing is
sent to the instrument.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import struct
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from audio_probe import InStream, list_inputs                  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "out" / "lfo-audible"
WINDOW_MS = 20
ENV_RATE = 1000.0 / WINDOW_MS          # envelope samples per second
F_LO, F_HI, F_STEP = 0.2, 12.0, 0.05   # the band an LFO can plausibly sit in
CC = {20: "track", 21: "lo", 22: "mid", 24: "dest", 26: "probe_a"}


def envelope(pcm, rate, channels=2):
    """-> (rms[], zcr[]) per 20 ms window, left channel."""
    step = max(1, int(rate * WINDOW_MS / 1000))
    frame = 2 * channels
    n = len(pcm) // frame
    rms, zcr = [], []
    for start in range(0, n - step, step):
        acc = 0
        crossings = 0
        prev = 0
        for i in range(start, start + step):
            v = struct.unpack_from("<h", pcm, i * frame)[0]
            acc += v * v
            if (v >= 0) != (prev >= 0):
                crossings += 1
            prev = v
        rms.append(math.sqrt(acc / step))
        zcr.append(crossings * (rate / step) / 2.0)
    return rms, zcr


def goertzel(x, fs, f):
    """-> amplitude of `x` at frequency `f`. One bin, no FFT, no numpy."""
    n = len(x)
    if n < 8:
        return 0.0
    w = 2.0 * math.pi * f / fs
    coeff = 2.0 * math.cos(w)
    s1 = 0.0
    s2 = 0.0
    for v in x:
        s0 = v + coeff * s1 - s2
        s2 = s1
        s1 = s0
    real = s1 - s2 * math.cos(w)
    imag = s2 * math.sin(w)
    return 2.0 * math.hypot(real, imag) / n


def modulation(series):
    """-> (peak_hz, index). Index is peak amplitude over the mean level."""
    if len(series) < 16:
        return 0.0, 0.0
    mean = sum(series) / len(series)
    centred = [v - mean for v in series]
    best_f = 0.0
    best_a = 0.0
    f = F_LO
    while f <= F_HI:
        a = goertzel(centred, ENV_RATE, f)
        if a > best_a:
            best_f = f
            best_a = a
        f += F_STEP
    return best_f, (best_a / mean if mean > 1e-9 else 0.0)


def telemetry(url, events, stop, t0):
    try:
        r = urllib.request.urlopen(url, timeout=10)
    except Exception:                                           # noqa: BLE001
        return
    while not stop.is_set():
        line = r.readline()
        if not line:
            return
        line = line.decode("utf-8", "replace").strip()
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            ev["t"] = time.time() - t0
            events.append(ev)


def slot_span(events):
    """-> (span, bursts, probe_ok) for the track reporting a non-zero DEST."""
    per = {}
    cur = {}
    broken = 0
    for ev in events:
        if ev.get("kind") != "cc":
            continue
        name = CC.get(ev["d1"])
        if name == "probe_a":
            if ev["d2"] != 99:
                broken += 1
            elif cur.get("dest"):
                value = (cur.get("mid", 0) << 7) | cur.get("lo", 0)
                per.setdefault(cur.get("track"), []).append(value)
            cur = {}
        elif name:
            cur[name] = ev["d2"]
    if not per:
        return 0, 0, broken == 0
    track = max(per, key=lambda t: len(per[t]))
    vals = per[track]
    return max(vals) - min(vals), len(vals), broken == 0


def record(args):
    names = list_inputs()
    idx = args.index
    if idx >= len(names):
        print(f"  no audio input {idx}; there are {len(names)}")
        return 1
    if "Elektr" not in names[idx] and not args.force:
        # **A warning was not enough, and this is why.** On 2026-09-25 the
        # instrument was not enumerated, input 0 was the owner's microphone, and
        # a self-test recorded eight seconds of the room -- after this project
        # had explicitly declined to record that microphone the day before. A
        # tool that only warns will be run anyway. So it refuses.
        print(f"  input {idx} is {names[idx]!r}, which is not the instrument.")
        print( "  Refusing: this tool records a room otherwise. Connect the DN2")
        print( "  (SETTINGS > SYSTEM > USB CONFIG must expose audio), pick the")
        print( "  Elektron input with --in, or pass --force if you really mean it.")
        print("\n  inputs:")
        for i, n in enumerate(names):
            print(f"    [{i}] {n}")
        return 1

    t0 = time.time()
    events = []
    stop = threading.Event()
    threading.Thread(target=telemetry, args=(args.probe, events, stop, t0),
                     daemon=True).start()

    print(f"  recording {args.seconds}s as {args.label!r} from [{idx}] {names[idx]}")
    stream = InStream(idx, rate=args.rate)
    pcm = bytearray()
    try:
        end = time.time() + args.seconds
        while time.time() < end:
            pcm += stream.read()
            time.sleep(0.004)
        pcm += stream.read()
    finally:
        stream.close()
        stop.set()

    if len(pcm) // 4 == 0:
        print("  no audio arrived.")
        return 1
    rms, zcr = envelope(bytes(pcm), args.rate)
    f_r, i_r = modulation(rms)
    f_z, i_z = modulation(zcr)
    span, bursts, ok = slot_span(events)

    rec = {"label": args.label, "seconds": args.seconds, "windows": len(rms),
           "rms_peak_hz": round(f_r, 2), "rms_index": round(i_r, 4),
           "zcr_peak_hz": round(f_z, 2), "zcr_index": round(i_z, 4),
           "slot_span": span, "bursts": bursts, "probe_ok": ok}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (args.label + ".json")).write_text(json.dumps(rec, indent=2),
                                              encoding="utf-8")

    print(f"\n  windows {len(rms)}   telemetry bursts {bursts}   slot span {span}")
    if not ok:
        print("  ** probe_a was not 99: the telemetry in this run is void **")
    if bursts and span == 0:
        print("  ** the mirror slot did NOT sweep -- the firmware is not modulating,")
        print("     so a quiet result here proves nothing about the audio path **")
    print(f"  RMS  peak {f_r:5.2f} Hz   index {i_r:.4f}")
    print(f"  ZCR  peak {f_z:5.2f} Hz   index {i_z:.4f}")
    print(f"\n  saved {OUT / (args.label + '.json')}")
    return 0


def compare(args):
    files = sorted(OUT.glob("*.json"))
    if len(files) < 2:
        print(f"  need at least two runs in {OUT}; found {len(files)}")
        return 1
    recs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    head = "{:<16}{:>10}{:>8}{:>9}{:>10}{:>9}{:>10}".format(
        "label", "slot span", "bursts", "RMS Hz", "RMS idx", "ZCR Hz", "ZCR idx")
    print(head)
    for r in recs:
        print("{:<16}{:>10}{:>8}{:>9}{:>10.4f}{:>9}{:>10.4f}".format(
            r["label"], r["slot_span"], r["bursts"],
            r["rms_peak_hz"], r["rms_index"],
            r["zcr_peak_hz"], r["zcr_index"]))

    print("\n  How to read this:")
    print("  * slot span must be > 0 in EVERY run, or they are not comparable:")
    print("    the firmware has to be modulating for the audio to mean anything.")
    print("  * indices close together -> the modulation reaches the sound in both,")
    print("    so the 'voice gate' is a loudness difference, not a gate.")
    print("  * one index near zero while its slot span matches the other's ->")
    print("    the value reaches the mirror and not the sound. That is the finding.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--label", required=True)
    r.add_argument("--seconds", type=float, default=20.0)
    r.add_argument("--in", dest="index", type=int, default=0)
    r.add_argument("--rate", type=int, default=48000)
    r.add_argument("--probe", default="http://127.0.0.1:8737/events")
    r.add_argument("--force", action="store_true",
                   help="record from an input that is not the instrument")
    r.set_defaults(fn=record)
    c = sub.add_parser("compare")
    c.set_defaults(fn=compare)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

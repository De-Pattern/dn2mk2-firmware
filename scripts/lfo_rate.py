"""How fast is the modulation, in Hz? Record the instrument and measure it.

    python scripts/lfo_rate.py --label slow3 --bpm 120 --steps 4

**Why this exists.** On 2026-09-25 a forced-row LFO4 demo was described as
"gurgling" and three builds were made slower by guesswork. A 15-second recording
answered it in one pass: **57.0 Hz**, which is audio-rate, which is why it read
as timbre and not as movement. Guessing would have taken several more flashes.

**The band matters more than the method.** The first analysis used 20 ms windows
-- a 50 Hz envelope, so nothing above 25 Hz is visible -- and duly reported the
*sequencer* as if it were the LFO. This uses **2 ms windows**, a 500 Hz envelope,
so modulation up to 250 Hz is in range. A tool with the wrong band does not fail
loudly; it returns a confident number about the wrong thing.

**The sequencer is a decoy and is labelled as one.** Notes retrigger the
amplitude envelope, which puts a strong peak at the note rate and its harmonics
in exactly the band being searched. Give `--bpm` and `--steps` (notes per bar)
and those are marked in the output instead of being read as modulation.

**Two measures, because they answer different questions.** RMS follows level;
ZCR (zero-crossing rate) follows brightness, so a filter or timbre modulation
shows there even when the level is steady.

**Read-only.** Audio in only; nothing is sent to the instrument.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import struct
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from audio_probe import capture, list_inputs                    # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "out" / "audio"
WIN_MS = 2.0


def envelopes(pcm, rate, channels=2):
    """-> (rms[], zcr[], env_rate) at WIN_MS resolution, left channel."""
    step = max(1, int(rate * WIN_MS / 1000))
    frame = 2 * channels
    n = len(pcm) // frame
    rms, zcr = [], []
    for s in range(0, n - step, step):
        acc = 0
        cross = 0
        prev = 0
        for i in range(s, s + step):
            v = struct.unpack_from("<h", pcm, i * frame)[0]
            acc += v * v
            if (v >= 0) != (prev >= 0):
                cross += 1
            prev = v
        rms.append(math.sqrt(acc / step))
        zcr.append(cross * (rate / step) / 2.0)
    return rms, zcr, rate / step


def goertzel(x, fs, f):
    w0 = 2 * math.pi * f / fs
    c = 2 * math.cos(w0)
    s1 = s2 = 0.0
    for v in x:
        s0 = v + c * s1 - s2
        s2, s1 = s1, s0
    return 2 * math.hypot(s1 - s2 * math.cos(w0), s2 * math.sin(w0)) / len(x)


def peaks(series, env_rate, lo, hi, step, keep=6, apart=1.5):
    mean = sum(series) / len(series)
    centred = [v - mean for v in series]
    scored = []
    f = lo
    while f <= hi:
        scored.append((goertzel(centred, env_rate, f), f))
        f += step
    scored.sort(reverse=True)
    out, seen = [], []
    for a, f in scored:
        if any(abs(f - g) < apart for g in seen):
            continue
        seen.append(f)
        out.append((f, a / max(mean, 1e-9)))
        if len(out) >= keep:
            break
    return mean, out


def note_rate(bpm, steps_per_bar):
    """-> the note rate in Hz, assuming 4/4 and one bar of `steps_per_bar`."""
    return (bpm / 60.0) * (steps_per_bar / 4.0)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--label", required=True, help="names the .wav under out/audio/")
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--in", dest="index", type=int, default=0)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--bpm", type=float, default=None, help="to label the sequencer's peaks")
    p.add_argument("--steps", type=float, default=4, help="notes per bar (default 4)")
    p.add_argument("--hi", type=float, default=200.0, help="highest frequency to search")
    p.add_argument("--wav", help="analyse this file instead of recording")
    args = p.parse_args()

    if args.wav:
        w = wave.open(args.wav, "rb")
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
        print(f"  reading {args.wav}")
    else:
        names = list_inputs()
        if args.index >= len(names) or "Elektr" not in names[args.index]:
            print(f"  input {args.index} is not the instrument. Inputs:")
            for i, n in enumerate(names):
                print(f"    [{i}] {n}")
            return 1
        rate = args.rate
        print(f"  recording {args.seconds}s from [{args.index}] {names[args.index]}")
        pcm = capture(args.index, args.seconds, rate=rate)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{args.label}.wav"
        with wave.open(str(path), "wb") as f:
            f.setnchannels(2)
            f.setsampwidth(2)
            f.setframerate(rate)
            f.writeframes(pcm)
        print(f"  wrote {path}")

    if len(pcm) < 4 * rate:
        print("  too little audio to measure")
        return 1

    rms, zcr, env_rate = envelopes(pcm, rate)
    hi = min(args.hi, env_rate / 2 - 1)
    print(f"  envelope {len(zcr)} samples at {env_rate:.0f} Hz — searching 0.5..{hi:.0f} Hz\n")

    seq = note_rate(args.bpm, args.steps) if args.bpm else None
    if seq:
        print(f"  sequencer is {seq:.2f} Hz ({args.steps:g} notes/bar at {args.bpm:g} BPM); "
              f"its harmonics are marked [seq]\n")

    def is_seq(f):
        if not seq:
            return False
        k = round(f / seq)
        return k >= 1 and abs(f - k * seq) < 0.35

    for series, label in ((rms, "RMS  (level)"), (zcr, "ZCR  (brightness)")):
        mean, pk = peaks(series, env_rate, 0.5, hi, 0.25)
        print(f"  {label}   mean {mean:.1f}")
        for f, idx in pk:
            tag = "  [seq]" if is_seq(f) else ""
            print(f"      {f:7.2f} Hz   index {idx:.4f}{tag}")
        best = [(f, i) for f, i in pk if not is_seq(f)]
        if best:
            f, i = best[0]
            print(f"      -> strongest non-sequencer peak: {f:.2f} Hz  ({1/f:.3f} s per cycle)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

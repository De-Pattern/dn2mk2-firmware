"""Locate and cut the FM drum transient bank out of the SHARC image.

## How this was finally found, after three failed detectors

`docs/pcm-hunt.md` records detectors that failed for three different reasons --
a zero-crossing test that rejected the wavetables it should have found, and
plane-asymmetry and autocorrelation tests that both reward pointer tables. All
three were calibrated on *guesses* about what a transient looks like.

The Syntakt OS 1.41 download ships **`TRANSIENT 01`-`08.wav`** in its Twinshot
Sound Pack: Elektron's own transients, 16-bit mono 44.1 kHz, 5,292 frames =
exactly 120 ms. Measuring the detector against those gives the thresholds that
were previously invented:

| | real transients | pointer tables (the old false positives) |
|---|---|---|
| plane-delta | **0.99 - 3.67** | 0.45 - 0.77 |
| step-correlation | **0.978 - 0.995** | 0.36 - 0.92 |

The old thresholds were `0.35 / 0.35`. With the measured ones, **MAIN OS code
scores zero** and the hits concentrate in one contiguous span of the SHARC
image's DDR region. The owner confirmed by ear: the span is many transients
concatenated, and an 8 KB slice of it is a single transient.

*The lesson is cheap to state and was expensive to learn: a detector needs a
positive sample of the thing it detects, not a theory about it.*

## What this does

Finds the extent with the calibrated test, then cuts it into individual
transients at silence -- percussion decays to near-zero between hits, which is
the segmentation the data offers rather than one imposed on it. Equal slicing is
NOT used: `scripts/chop_bank.py` had to assume it because nothing was known, and
that assumption is exactly what this replaces.

    python scripts/find_transients.py <image> --out out/dn2_transients

No firmware bytes enter the repository; `out/` is gitignored, and the audio is
Elektron's copyrighted content -- local analysis only.
"""

import argparse
import collections
import math
import pathlib
import struct
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image          # noqa: E402
from dnfw.firmware.load import load            # noqa: E402
from dnfw.image import bootstream              # noqa: E402

# Measured on Syntakt's TRANSIENT 01-08.wav, not chosen.
DELTA_MIN = 0.60
STEP_MIN = 0.95


def entropy(b) -> float:
    c = collections.Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def metrics(pcm: bytes, endian="<"):
    if len(pcm) < 1024:
        return 0.0, 0.0
    delta = abs(entropy(pcm[0::2]) - entropy(pcm[1::2]))
    n = len(pcm) // 2
    v = struct.unpack_from(f"{endian}{n}h", pcm, 0)
    rng = max(v) - min(v)
    if rng < 1024:
        return delta, 0.0
    steps = sum(abs(v[i + 1] - v[i]) for i in range(n - 1)) / (n - 1)
    return delta, 1.0 - steps / (rng / 3.0)


def write_wav(path, samples, rate):
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", nargs="?",
                   default="00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--out", default="out/dn2_transients")
    p.add_argument("--rate", type=int, default=44100)
    p.add_argument("--window", type=int, default=1024)
    p.add_argument("--endian", choices=["<", ">"], default="<")
    p.add_argument("--silence", type=int, default=64,
                   help="peak below this counts as silence")
    p.add_argument("--min-gap", type=int, default=256,
                   help="samples of silence needed to split two transients")
    p.add_argument("--min-len", type=int, default=512)
    args = p.parse_args(argv)

    fw = load(read_image(pathlib.Path(args.image)))
    regions = bootstream.load_regions(fw.container.find(7).unpack())

    W = args.window
    spans = []
    for base, blob in regions:
        run_lo = None
        for off in range(0, len(blob) - W, W):
            d, s = metrics(blob[off:off + W], args.endian)
            hit = d > DELTA_MIN and s > STEP_MIN
            if hit and run_lo is None:
                run_lo = off
            elif not hit and run_lo is not None:
                if off - run_lo >= 4 * W:
                    spans.append((base, run_lo, off))
                run_lo = None
        if run_lo is not None:
            spans.append((base, run_lo, len(blob)))

    print(f"{len(spans)} audio-shaped span(s) across the SHARC image\n")
    for base, lo, hi in spans:
        print(f"  0x{base + lo:08x} .. 0x{base + hi:08x}   {hi - lo:>9,} bytes"
              f"   {(hi - lo) // 2:>8,} samples   {(hi-lo)/2/args.rate:6.2f}s")

    if not spans:
        return 0
    base, lo, hi = max(spans, key=lambda s: s[2] - s[1])
    blob = [b for b0, b in regions if b0 == base][0]
    seg = blob[lo:hi]
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"\ncutting the largest span, 0x{base + lo:08x}, {len(seg):,} bytes")

    n = len(seg) // 2
    v = list(struct.unpack_from(f"{args.endian}{n}h", seg, 0))

    # Segment at silence. Percussion decays to near zero between hits, so the
    # data itself says where the boundaries are -- unlike chop_bank.py, which
    # had to assume equal slices because nothing was known.
    quiet = [abs(x) < args.silence for x in v]
    cuts, i, run = [], 0, 0
    start = 0
    for i, q in enumerate(quiet):
        if q:
            run += 1
        else:
            if run >= args.min_gap and i - start >= args.min_len:
                cuts.append((start, i - run + args.min_gap // 2))
                start = i - run + args.min_gap // 2
            run = 0
    cuts.append((start, n))
    cuts = [(a, b) for a, b in cuts if b - a >= args.min_len]

    print(f"  segmented at silence into {len(cuts)} transient(s)\n")
    lens = [b - a for a, b in cuts]
    if lens:
        print(f"  length: min {min(lens):,}  max {max(lens):,}  "
              f"mean {sum(lens)//len(lens):,} samples "
              f"({1000*sum(lens)/len(lens)/args.rate:.0f} ms)")
    d = out / "segments"
    d.mkdir(exist_ok=True)
    for k, (a, b) in enumerate(cuts):
        write_wav(d / f"{k:03d}.wav", v[a:b], args.rate)
    write_wav(out / "bank_whole.wav", v, args.rate)
    print(f"  wrote {len(cuts)} files to {d} and the whole bank to "
          f"{out/'bank_whole.wav'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

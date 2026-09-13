"""Find the audio sample data in the SHARC image, and carve it out.

## Why this is askable now and was not before

`docs/ideas-backlog.md` §3 parked the PCM hunt on one sentence: *"the first job
is to map `blob`'s internal layout and find its index, not to look for a WAV-like
header."* There is no header to look for — the DN2's `blob` is an ADI boot
stream, and its contents are whatever the DSP was linked with.

That layout now exists (`docs/sharc-code-map.md`, `docs/sharc-reading.md`): nine
regions, two of them code, the rest data, each at a known address. So the
question stops being "where in 837 KB" and becomes "which of these four data
regions holds audio, and where inside them".

## How audio is told apart from coefficients

Both are arrays of numbers, so the test cannot be "does it parse". What
separates them is **behaviour over a window**:

| | a filter/curve table | an audio transient |
|---|---|---|
| sign changes | few — curves are smooth and often monotonic | many — a waveform oscillates |
| amplitude | arbitrary, often > 1 | bounded, typically within ±1 for normalised float |
| variation | smooth, low local roughness | high, and decaying over the length of a hit |

So each window is scored on **zero-crossing rate**, **range** and **roughness**,
and only runs of consecutive audio-like windows are reported. A single window
means nothing; a drum transient is hundreds of them.

## The control, which is the part that makes it a measurement

**The two code regions are scanned with exactly the same test.** They are known
not to be audio — they are instructions, established independently by the cjump
census. If the detector fires on them at a similar rate to the data regions, it
is detecting nothing and its output on the data regions is worthless.

The format is not assumed either: **float32 and int16 are both tried**, and the
one that produces the cleaner, better-bounded runs is the answer rather than the
starting assumption. §3 assumed 16-bit PCM and was later corrected to float32 on
other grounds; neither is taken on faith here.

    python scripts/find_pcm.py <image.syx|.zip>
    python scripts/find_pcm.py <image.syx|.zip> --wav out/pcm --min-samples 512

No firmware bytes are written into this repository; `out/` is gitignored, and
the carved audio is a derivative of copyrighted firmware — it stays local.
"""

import argparse
import math
import pathlib
import struct
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image          # noqa: E402
from dnfw.firmware.load import load            # noqa: E402
from dnfw.image import bootstream              # noqa: E402

BLOB = 7
WINDOW = 256            # samples per scored window


def code_region(base: int, blob: bytes) -> bool:
    """The cjump census, reused as the control's definition of 'is code'."""
    n = 0
    for off in range(0, len(blob) - 6, 2):
        w0, w1, w2 = struct.unpack_from("<HHH", blob, off)
        insn = (w0 << 32) | (w1 << 16) | w2
        if (insn >> 24) & 0xFFFFFF == 0x180400:
            n += 1
            if n >= 100:
                return True
    return False


def read_float32(blob: bytes, i: int, n: int):
    return struct.unpack_from(f"<{n}f", blob, i)


def read_int16(blob: bytes, i: int, n: int):
    return tuple(v / 32768.0 for v in struct.unpack_from(f"<{n}h", blob, i))


FORMATS = {
    "float32": (4, read_float32),
    "int16": (2, read_int16),
}


def score(samples) -> dict | None:
    """-> stats for one window, or None if it cannot be audio at all."""
    peak = 0.0
    for v in samples:
        if not math.isfinite(v):
            return None                    # NaN/Inf: not a sample buffer
        a = abs(v)
        if a > peak:
            peak = a
    if peak == 0.0:
        return {"silent": True, "peak": 0.0, "zcr": 0.0, "rough": 0.0}
    if peak > 8.0:
        return None                        # far outside any normalised range

    crossings = 0
    rough = 0.0
    energy = 0.0
    prev = samples[0]
    for v in samples[1:]:
        if (v >= 0) != (prev >= 0):
            crossings += 1
        rough += abs(v - prev)
        energy += v * v
        prev = v
    n = len(samples)
    return {
        "silent": False,
        "peak": peak,
        "zcr": crossings / (n - 1),
        "rough": rough / (n - 1) / peak,
        "rms": math.sqrt(energy / n),
    }


def audio_like(st) -> bool:
    """A window that oscillates, is bounded, and is not flat."""
    if st is None or st["silent"]:
        return False
    return (st["zcr"] >= 0.05          # it changes sign often enough to be a wave
            and st["peak"] <= 4.0      # bounded like a normalised sample
            and st["rough"] >= 0.002   # not a smooth curve or a constant
            and st["rms"] > 1e-6)


def scan(blob: bytes, fmt: str):
    """-> list of (start_sample, end_sample, peak) runs of audio-like windows."""
    width, reader = FORMATS[fmt]
    total = len(blob) // width
    runs, cur = [], None
    peak = 0.0
    for w in range(total // WINDOW):
        i = w * WINDOW * width
        st = score(reader(blob, i, WINDOW))
        if audio_like(st):
            if cur is None:
                cur, peak = w, st["peak"]
            peak = max(peak, st["peak"])
        else:
            if cur is not None:
                runs.append((cur * WINDOW, w * WINDOW, peak))
                cur = None
    if cur is not None:
        runs.append((cur * WINDOW, (total // WINDOW) * WINDOW, peak))
    return runs


def write_wav(path: pathlib.Path, samples, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        peak = max((abs(v) for v in samples), default=1.0) or 1.0
        scale = 32767.0 / peak if peak > 1.0 else 32767.0
        fh.writeframes(b"".join(
            struct.pack("<h", max(-32768, min(32767, int(v * scale))))
            for v in samples))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("--section", type=int, default=BLOB)
    p.add_argument("--min-samples", type=int, default=512,
                   help="ignore runs shorter than this")
    p.add_argument("--wav", metavar="DIR",
                   help="carve each run to a .wav here (outside the repo)")
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--format", choices=sorted(FORMATS) + ["both"], default="both")
    args = p.parse_args(argv)

    fw = load(read_image(args.image))
    section = fw.container.find(args.section)
    if section is None:
        raise SystemExit(f"image has no section id={args.section}")
    regions = bootstream.load_regions(section.unpack() or section.raw_payload)

    formats = sorted(FORMATS) if args.format == "both" else [args.format]
    for fmt in formats:
        width, reader = FORMATS[fmt]
        print(f"\n{'=' * 66}\nreading every region as {fmt}\n{'=' * 66}")
        print(f"{'region':<13}{'kind':<7}{'bytes':>10}{'runs':>6}"
              f"{'audio bytes':>13}{'%':>7}")
        for base, blob in regions:
            kind = "CODE" if code_region(base, blob) else "data"
            runs = [r for r in scan(blob, fmt)
                    if r[1] - r[0] >= args.min_samples]
            got = sum((b - a) * width for a, b, _ in runs)
            print(f"0x{base:08x}   {kind:<7}{len(blob):>10,}{len(runs):>6}"
                  f"{got:>13,}{100 * got / max(len(blob), 1):>6.1f}%")

            if args.wav and runs and kind != "CODE":
                out = pathlib.Path(args.wav)
                for a, b, _pk in runs:
                    samples = reader(blob, a * width, b - a)
                    name = f"{fmt}_0x{base + a * width:08x}_{b - a}.wav"
                    write_wav(out / name, samples, args.rate)
                print(f"{'':13}-> carved {len(runs)} file(s) to {out}")

    print("\nThe CODE rows are the control. They are instructions, established")
    print("independently by the cjump census, so whatever the detector reports")
    print("there is its false-positive rate -- read the data rows against it.")
    print("\nMeasured on DN2 1.11 (docs/pcm-hunt.md): int16 fires on 99.9% of")
    print("BOTH code regions, so every int16 row is noise -- compiled ColdFire")
    print("defeats this test entirely. float32 returned zero everywhere,")
    print("including on regions it could have flattered, which is why that")
    print("negative is worth something and the int16 positives are not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

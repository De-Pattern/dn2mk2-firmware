"""Cut a candidate sample bank into equal entries, for listening.

## Why equal slices, and what that assumes

`docs/pcm-hunt.md` establishes one number: the FM drum transient selector
`TRAN` (id 286) spans integer positions 0..124, so **125**. No index table has
been found -- a scan for monotonic runs of 120-132 entries at every plausible
width turns up only arithmetic progressions and a saturation curve.

So this cuts a region into N equal pieces. That is a **hypothesis, not a
reading**: it is right only if the bank is N entries of identical length,
starting at the region's first byte, with no header. If any of those is false
the cuts land mid-entry -- which is still useful, because a listener can hear
that the pieces are offset and by roughly how much, and the manifest gives the
exact byte range of every piece so a better guess can be re-cut immediately.

## The fade, which is not cosmetic

Every piece gets a short linear fade at both edges. Without it, hard-cutting
**any** signal into pieces puts a discontinuity at the start of each one, and a
discontinuity is a click -- so all 125 pieces would begin with a percussive
attack whether or not the data is percussion at all. That would manufacture the
exact evidence being looked for. The fade is a few hundred microseconds, far
shorter than any real transient's decay, and its length is reported.

Levels are **not** normalised per piece. Normalising would flatten the
loud-to-quiet differences between entries, which is information.

    python scripts/chop_bank.py --pieces 125 --out out/pcm/chopped

Output stays outside the repository: this is audio derived from Elektron's
copyrighted firmware, fine to carve locally for analysis and not something to
redistribute. `out/` is gitignored.
"""

import argparse
import csv
import pathlib
import struct
import sys
import wave
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image          # noqa: E402
from dnfw.firmware.load import load            # noqa: E402

# The region docs/pcm-hunt.md reports as dense and high-entropy in MAIN OS.
LO, HI = 0x40238800, 0x40287400

STEP = [7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,
80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,
544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,
2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,
11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767]
IDX = [-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8]


def ima_adpcm(data: bytes, hi_first: bool):
    pred = idx = 0
    out = []
    for byte in data:
        nibs = ((byte >> 4) & 0xF, byte & 0xF) if hi_first \
            else (byte & 0xF, (byte >> 4) & 0xF)
        for nib in nibs:
            step = STEP[idx]
            diff = step >> 3
            if nib & 1:
                diff += step >> 2
            if nib & 2:
                diff += step >> 1
            if nib & 4:
                diff += step
            pred = pred - diff if nib & 8 else pred + diff
            pred = max(-32768, min(32767, pred))
            idx = max(0, min(88, idx + IDX[nib]))
            out.append(pred)
    return out


def renderings(seg: bytes):
    """-> {name: (samples, bytes_per_sample)} -- the five sent for audition."""
    n2 = len(seg) // 2
    return {
        "be16":     (list(struct.unpack_from(f">{n2}h", seg, 0)), 2),
        "le16":     (list(struct.unpack_from(f"<{n2}h", seg, 0)), 2),
        "s8":       ([v * 256 for v in struct.unpack_from(f"{len(seg)}b", seg, 0)], 1),
        "adpcm_lo": (ima_adpcm(seg, False), 0.5),
        "adpcm_hi": (ima_adpcm(seg, True), 0.5),
    }


def write_wav(path: pathlib.Path, samples, rate: int, fade: int) -> int:
    s = list(samples)
    f = min(fade, len(s) // 4)
    for i in range(f):
        g = i / f
        s[i] = int(s[i] * g)
        s[-1 - i] = int(s[-1 - i] * g)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(struct.pack(f"<{len(s)}h",
                                   *(max(-32768, min(32767, int(v))) for v in s)))
    return max((abs(int(v)) for v in s), default=0)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", nargs="?",
                   default="00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--lo", type=lambda x: int(x, 0), default=LO)
    p.add_argument("--hi", type=lambda x: int(x, 0), default=HI)
    p.add_argument("--pieces", type=int, default=125)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--fade", type=int, default=32, help="fade samples per edge")
    p.add_argument("--out", default="out/pcm/chopped")
    p.add_argument("--zip", action="store_true", default=True)
    args = p.parse_args(argv)

    fw = load(read_image(pathlib.Path(args.image)))
    sec = fw.container.find(3)
    data = sec.unpack()
    base = sec.dest
    seg = data[args.lo - base:args.hi - base]
    print(f"region 0x{args.lo:08x}..0x{args.hi:08x}  {len(seg):,} bytes  "
          f"-> {args.pieces} pieces\n")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    made = []

    for name, (samples, bps) in renderings(seg).items():
        d = out / name
        d.mkdir(exist_ok=True)
        total = len(samples)
        per = total // args.pieces
        rows = []
        for i in range(args.pieces):
            chunk = samples[i * per:(i + 1) * per]
            # byte range in the ORIGINAL image that produced this piece --
            # the point of the manifest: a piece that sounds like a hit can be
            # turned straight back into an address.
            b0 = args.lo + int(i * per * bps)
            b1 = args.lo + int((i + 1) * per * bps)
            f = d / f"{i:03d}.wav"
            peak = write_wav(f, chunk, args.rate, args.fade)
            rows.append({"piece": i, "file": f.name,
                         "src_start": f"0x{b0:08x}", "src_end": f"0x{b1:08x}",
                         "samples": len(chunk),
                         "ms": round(1000 * len(chunk) / args.rate, 1),
                         "peak": peak})
        with (d / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        (d / "README.txt").write_text(
            f"{args.pieces} equal pieces of 0x{args.lo:08x}..0x{args.hi:08x}\n"
            f"rendering: {name}\n"
            f"{per} samples each = {1000*per/args.rate:.1f} ms at "
            f"{args.rate} Hz\n\n"
            "EQUAL SLICING IS A HYPOTHESIS, not a reading. No index table has\n"
            "been found. The cuts are right only if the bank is this many\n"
            "entries of identical length starting at the first byte with no\n"
            "header. If the pieces sound offset, manifest.csv gives the exact\n"
            "source byte range of each one so a better guess can be re-cut.\n\n"
            f"Each piece has a {args.fade}-sample "
            f"({1000*args.fade/args.rate:.1f} ms) fade at both edges. Without\n"
            "it every hard cut would click, and all pieces would seem to\n"
            "start with a percussive attack whether or not this is\n"
            "percussion. Levels are NOT normalised -- loudness differences\n"
            "between pieces are information.\n", encoding="utf-8")

        print(f"  {name:<9} {args.pieces} x {per:>6} samples "
              f"({1000*per/args.rate:6.1f} ms)  -> {d}")

        if args.zip:
            z = out / f"{name}.zip"
            with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(d.iterdir()):
                    zf.write(f, f"{name}/{f.name}")
            made.append(z)
            print(f"  {'':<9} zipped -> {z} ({z.stat().st_size:,} bytes)")

    print(f"\n{len(made)} archive(s) written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

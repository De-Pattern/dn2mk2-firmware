"""Dump a span of emulator RAM to a file, and say what shape it is.

Written for one finding: `scripts/ram_audio_scan.py` reports a contiguous run of
audio-shaped windows in the main BSS from about `0x446d0000`, at 3.9% of that
region against 0.2% and 0.0% elsewhere. Contiguity is the interesting part --
consecutive 8 KB windows all passing means one buffer, not scattered noise.

This pulls the bytes out so they can be looked at, converted, and listened to.
It also walks outward from the given address to find where the audio-shaped
property starts and stops, because the extent is what says whether this is a
sample bank or an incidental buffer.

    python scripts/ram_dump.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
        --at 0x446d0000 --out out/ram
"""

import argparse
import collections
import math
import pathlib
import struct
import sys
import wave


def entropy(b) -> float:
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def shape(chunk: bytes):
    """-> (plane_delta, step_correlation) -- the two surviving tests."""
    if len(chunk) < 2048 or chunk.count(0) > len(chunk) * 0.6:
        return 0.0, 0.0
    delta = abs(entropy(chunk[0::2]) - entropy(chunk[1::2]))
    n = len(chunk) // 2
    best = 0.0
    for fmt in ("<", ">"):
        v = struct.unpack_from(f"{fmt}{n}h", chunk, 0)
        rng = max(v) - min(v)
        if rng < 4096:
            continue
        steps = sum(abs(v[i + 1] - v[i]) for i in range(n - 1)) / (n - 1)
        best = max(best, 1.0 - steps / (rng / 3.0))
    return delta, best


def run(args) -> int:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import longrun, symbols, config  # noqa: E402
    from emu.dtim import Dtims, Timers  # noqa: E402
    from emu.pit import Pits, intro_running  # noqa: E402

    profile = symbols.resolve(open(config.main_image(), "rb").read())
    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=True,
        softfloat=True, dsp=True, sdgate=True, esdhc=True)
    intro = intro_running(m, profile.intro_pit3_isr)
    pits = Timers(Pits(m, hold=intro), Dtims(m, channels=(3,), hold=intro))
    if intro and profile.intro_done is not None:
        at(profile.intro_done, lambda uc, a, s, d: pits.release())
    for _ in range(args.warmup):
        pc, ran, _ = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)

    W = 8192

    def ok(a):
        try:
            d, s = shape(bytes(m.uc.mem_read(a, W)))
        except Exception:
            return False
        return d > 0.35 and s > 0.35

    # Walk outward to find the extent of the audio-shaped property.
    lo = args.at
    while lo - W >= args.floor and ok(lo - W):
        lo -= W
    hi = args.at
    while hi + W <= args.ceil and ok(hi):
        hi += W
    print(f"audio-shaped extent: 0x{lo:08x} .. 0x{hi:08x}  "
          f"= {hi - lo:,} bytes ({(hi - lo) / 1024:.0f} KB)")
    if hi > lo:
        print(f"  over 125 entries that is {(hi - lo) // 125:,} bytes each")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = bytes(m.uc.mem_read(lo, hi - lo))
    raw = out / f"ram_0x{lo:08x}_{hi - lo}.bin"
    raw.write_bytes(data)
    print(f"  wrote {raw}")

    d, s = shape(data[:65536])
    print(f"  plane-delta {d:.3f}  step-correlation {s:.3f}")

    for lbl, fmt in (("be16", ">"), ("le16", "<")):
        n = len(data) // 2
        v = struct.unpack_from(f"{fmt}{n}h", data, 0)
        p = out / f"ram_0x{lo:08x}_{lbl}.wav"
        with wave.open(str(p), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(args.rate)
            fh.writeframes(struct.pack(f"<{n}h", *v))
        print(f"  wrote {p}  ({n:,} samples, {n / args.rate:.1f}s @ {args.rate})")

    print(f"\n  first 32 bytes: {data[:32].hex(' ')}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--digikit", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--syx", default=None)
    p.add_argument("--at", type=lambda x: int(x, 0), default=0x446D0000)
    p.add_argument("--floor", type=lambda x: int(x, 0), default=0x44000000)
    p.add_argument("--ceil", type=lambda x: int(x, 0), default=0x45000000)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--slice-size", type=int, default=10_000_000)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--out", default="out/ram")
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

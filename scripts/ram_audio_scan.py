"""Look for decompressed audio in the emulator's RAM, not in the image.

## Why RAM and not the file

`docs/pcm-hunt.md` searched every section of the OS update and found no sample
bank. Then §11 identified the one arithmetically-perfect candidate as the
**factory project, LZ-compressed**. That reframes every earlier negative: a
compressed transient bank would look exactly like that block did -- high
entropy, no byte-plane asymmetry, no autocorrelation -- and would be invisible
to any detector run against the file.

**The firmware has to decompress what it uses.** So the emulator is the right
instrument: boot it, and whatever is compressed on disk is expanded in RAM, in
the form the detectors were built for.

## The tests, which are the two that survived

Zero-crossing rate was thrown away -- it rejected the band-limited wavetables
this project had already found (`docs/pcm-hunt.md` §4b). What replaced it:

- **Byte-plane asymmetry.** 16-bit PCM has a correlated MSB plane and a noisy
  LSB plane, so their entropies differ. MAIN OS code measures 1.183; the
  compressed project block measures **0.003**.
- **Autocorrelation.** A sampled waveform moves in small steps between adjacent
  samples. Compressed or entropy-coded bytes do not: the project block's mean
  step is 19,401 against a 65,535 range, where random gives ~21,845.

A window passes only if it shows *both*. Either alone has a known false
positive.

## The control, which is not optional

RAM is mostly zeros, structures and pointers, and a detector that fires on those
is measuring nothing. So the scan reports what it finds in **code** regions
too -- `0x40000400` onward is the loaded MAIN OS and is known not to be audio.
If the hit rate there is comparable, the run says nothing.

    python scripts/ram_audio_scan.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap
"""

import argparse
import collections
import math
import pathlib
import struct
import sys

# docs/memory-map.md, 1.11.
REGIONS = [
    ("MAIN OS image (CONTROL: not audio)", 0x40000400, 0x4030B980),
    ("main BSS, low 16 MB",                0x40400000, 0x41400000),
    ("main BSS, ParameterSet area",        0x42000000, 0x43000000),
    ("main BSS, high",                     0x44000000, 0x45000000),
    ("fast SRAM",                          0x80000000, 0x80010000),
]


def entropy(b) -> float:
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def pointer_fraction(chunk: bytes) -> float:
    """How much of this looks like ColdFire addresses.

    A POINTER TABLE passes both PCM tests, and RAM is full of them. High bytes
    are nearly constant (0x40-0x46) so one byte plane has low entropy while the
    other varies -- a large plane delta; and consecutive pointers are
    numerically close, which reads as autocorrelation. The first run of this
    scan reported 3.9% of the main BSS as audio and the top hit was 53%
    pointers. Neither surviving test excludes them, so this does.
    """
    n = len(chunk) // 4
    if not n:
        return 0.0
    v = struct.unpack_from(f">{n}I", chunk, 0)
    return sum(1 for x in v if 0x40000000 <= x < 0x47000000) / n


def looks_like_pcm(chunk: bytes):
    """-> (ok, plane_delta, step_ratio) using the two surviving tests."""
    if len(chunk) < 2048:
        return False, 0.0, 0.0
    if chunk.count(0) > len(chunk) * 0.5:
        return False, 0.0, 0.0                      # mostly zero: not a buffer
    if pointer_fraction(chunk) > 0.08:
        return False, 0.0, 0.0                      # a pointer/structure table
    even, odd = chunk[0::2], chunk[1::2]
    delta = abs(entropy(even) - entropy(odd))

    n = len(chunk) // 2
    best = 0.0
    for fmt in ("<", ">"):
        v = struct.unpack_from(f"{fmt}{n}h", chunk, 0)
        rng = max(v) - min(v)
        if rng < 4096:
            continue
        steps = sum(abs(v[i + 1] - v[i]) for i in range(n - 1)) / (n - 1)
        ratio = steps / (rng / 3.0)                 # 1.0 == random
        best = max(best, 1.0 - ratio)               # >0 means correlated
    # PCM: planes differ AND steps are small relative to range
    return (delta > 0.35 and best > 0.35), delta, best


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

    W = args.window
    print(f"\nwindow {W} bytes; a hit needs plane-delta > 0.35 AND "
          f"step-correlation > 0.35\n")
    print(f"  {'region':<38}{'windows':>9}{'hits':>7}{'%':>7}")
    all_hits = []
    for name, lo, hi in REGIONS:
        hits, total = [], 0
        # Two passes. A cheap prefilter on a 1 KB sample rejects the ~99% of
        # RAM that is zeros, pointers or structures, and only survivors get the
        # entropy and autocorrelation work. Scanning 50 MB the expensive way
        # took long enough that the owner stopped it.
        for a in range(lo, hi, W):
            try:
                probe = bytes(m.uc.mem_read(a, 1024))
            except Exception:
                continue
            total += 1
            if probe.count(0) > 512:
                continue                       # mostly zero
            if len(set(probe)) < 64:
                continue                       # too few distinct byte values
            try:
                chunk = bytes(m.uc.mem_read(a, W))
            except Exception:
                continue
            ok, d, sc = looks_like_pcm(chunk)
            if ok:
                hits.append((a, d, sc))
        pct = 100 * len(hits) / max(total, 1)
        print(f"  {name:<38}{total:>9}{len(hits):>7}{pct:>6.1f}%")
        all_hits.append((name, hits))

    print("\nThe first row is the control: it is the loaded firmware image and")
    print("is not audio. If its rate resembles the others, this scan is")
    print("measuring structure rather than sound and none of it counts.")

    for name, hits in all_hits:
        if not hits or name.startswith("MAIN OS"):
            continue
        print(f"\n{name}: first candidates")
        for a, d, s in hits[:12]:
            print(f"  0x{a:08x}  plane-delta {d:.3f}  step-correlation {s:.3f}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--digikit", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--syx", default=None)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--slice-size", type=int, default=10_000_000)
    p.add_argument("--window", type=int, default=8192)
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

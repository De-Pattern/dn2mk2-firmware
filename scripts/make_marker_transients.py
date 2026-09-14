"""Build a marker set for the first transient flash, so one flash answers two questions.

## Why markers rather than 34 new samples

Flashing is slow and carries real risk, so a test should be designed to return
the most per attempt. Two things are open (`docs/mods.md`):

1. **Are these bytes the FM drum transients?** They are PCM in the audio DSP's
   image, transient-shaped and transient-length, and they sound like a bank of
   transients — but nothing traces parameter `TRAN` (id 286) to them.
2. **How do `TRAN`'s 125 positions map onto 34 entries?** The 4-step
   interpolation model predicted 32 entries and the bank has 34, so the mapping
   is not understood.

Replacing all 34 with new material answers only the first. Replacing a handful
at **known indices** with sounds nobody could mistake answers both: sweep `TRAN`
and note the position at which each marker appears, and the mapping falls out of
where they land.

## The markers, and why these

Five entries get a marker; the other 29 stay factory. Each marker is chosen to
be unmistakable over a 100 ms percussive slot and instantly distinguishable from
the others *and* from any real transient:

| entry | marker | why it is recognisable |
|---|---|---|
| 0 | 220 Hz square, full length | a low buzz, nothing like a drum hit |
| 8 | 880 Hz square | an obvious mid beep |
| 16 | 3,520 Hz square | a piercing high beep |
| 25 | white noise, flat, no decay | a sustained hiss; real transients all decay |
| 33 | silence | the last entry: if `TRAN` reaches it, something goes quiet |

Silence at the last entry is deliberate. It is the one marker whose *absence* of
sound is the signal, so it distinguishes "TRAN reached entry 33" from "TRAN
never gets that far" — which is exactly the question about the top of the range.

Leaving 29 entries factory keeps the change small and means the instrument still
sounds like itself between markers, so a sweep is easy to follow by ear.

    python scripts/make_marker_transients.py --out out/marker_transients
"""

import argparse
import math
import pathlib
import random
import struct
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image          # noqa: E402
from dnfw.firmware.load import load            # noqa: E402
from dnfw.mods import transients as T          # noqa: E402

AMP = 22000


def square(freq, n, rate):
    return [AMP if math.sin(2 * math.pi * freq * i / rate) >= 0 else -AMP
            for i in range(n)]


def noise(n, seed=7):
    r = random.Random(seed)
    return [r.randint(-AMP, AMP) for _ in range(n)]


def silence(n):
    return [0] * n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", nargs="?",
                   default="00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--out", default="out/marker_transients")
    args = p.parse_args(argv)

    n, rate = T.ENTRY_SAMPLES, T.RATE
    markers = {
        0:  ("220 Hz square — low buzz", square(220, n, rate)),
        8:  ("880 Hz square — mid beep", square(880, n, rate)),
        16: ("3520 Hz square — high beep", square(3520, n, rate)),
        25: ("white noise, no decay", noise(n)),
        33: ("silence", silence(n)),
    }

    # Everything else stays factory, so the bank still sounds like itself and a
    # sweep is easy to follow. Extract them rather than synthesise filler.
    firmware = load(read_image(pathlib.Path(args.image)))
    factory = T.extract(firmware)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.wav"):
        f.unlink()

    for k in range(T.COUNT):
        if k in markers:
            samples = markers[k][1]
            raw = struct.pack(f"<{len(samples)}h", *samples)
        else:
            raw = factory[k]
        with wave.open(str(out / f"{k:02d}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(raw)

    print(f"wrote {T.COUNT} entries to {out}\n")
    print(f"  {'entry':>5}  content")
    for k in range(T.COUNT):
        if k in markers:
            print(f"  {k:>5}  ** {markers[k][0]} **")
    print(f"  {'others':>5}  factory, unchanged ({T.COUNT - len(markers)} entries)")
    print("\nSweep TRAN on an FM DRUM track and write down the position at which")
    print("each marker appears. Those five positions give the mapping from")
    print("TRAN's 0..124 onto the 34 entries, which is currently unknown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

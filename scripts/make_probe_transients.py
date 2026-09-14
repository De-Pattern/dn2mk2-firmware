"""Build a transient bank that maps `TRAN`'s 125 positions onto the 34 entries.

## Why the first design was wrong

`scripts/make_marker_transients.py` put five distinctive sounds at known slots
and asked which `TRAN` values played them. That assumed each entry is heard at
one `TRAN` position.

**The owner's correction: the entries blend.** If `TRAN` interpolates between
adjacent entries, a marker does not appear at a point — it fades in over a
range and fades out again, and a sweep gives smeared landmarks rather than
positions. Every reading would be an opinion about where the middle of a fade
was.

## The design that survives blending

**Alternate a tone with silence.** With a tone at every even slot and silence at
every odd one, the tone's amplitude *peaks* exactly where its entry reaches full
weight and falls to nothing between. The peak is the position, and it is a
maximum rather than an edge — which is what makes it readable through a blend
instead of in spite of one.

Each tone gets its **own frequency**, so a peak identifies *which* slot as well
as where it is. Seventeen tones across 34 slots pin the mapping outright, and
the *width* of each peak measures the interpolation — a second unknown answered
by the same sweep.

Frequencies are spaced so none is a harmonic of another (`650 + 300k`), because
a harmonic of a neighbouring tone landing in the bin being measured would read
as that neighbour's energy. Pure sines, not squares: a square's harmonics would
do the same thing to itself.

Constant amplitude across the whole 100 ms, with only a 1 ms edge fade — the
level we want to measure is the blend weight, and an envelope of our own would
be indistinguishable from one.

## Reading it

By ear: sweep `TRAN` and note where each pitch is loudest. By machine: set
`TRAN` over NRPN and capture USB audio — see `docs/tran-mapping.md`.

    python scripts/make_probe_transients.py --out out/probe_transients
"""

import argparse
import math
import pathlib
import struct
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.mods import transients as T          # noqa: E402

BASE_HZ = 650          # lowest probe tone
STEP_HZ = 300          # spacing; no tone is a harmonic of another
FADE_MS = 1.0          # just enough to avoid a click at the slot edges
LEVEL = 26000          # well below full scale, so a blend of two cannot clip


def tone(hz: float, n: int, rate: int) -> list[int]:
    """A pure sine at constant amplitude, with a 1 ms fade at each edge."""
    fade = max(1, int(FADE_MS * rate / 1000))
    out = []
    for i in range(n):
        gain = min(1.0, i / fade, (n - 1 - i) / fade)
        out.append(int(LEVEL * gain * math.sin(2 * math.pi * hz * i / rate)))
    return out


def plan(count: int, rate: int, n: int):
    """-> {slot: (label, samples)}; tones on even slots, silence on odd."""
    entries = {}
    k = 0
    for slot in range(count):
        if slot % 2:
            entries[slot] = ("silence", [0] * n)
        else:
            hz = BASE_HZ + STEP_HZ * k
            entries[slot] = (f"{hz} Hz", tone(hz, n, rate))
            k += 1
    return entries


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="out/probe_transients")
    p.add_argument("--all-slots", action="store_true",
                   help="a tone in every slot instead of alternating; more "
                        "information per sweep, harder to separate by ear")
    args = p.parse_args(argv)

    n, rate = T.ENTRY_SAMPLES, T.RATE
    if args.all_slots:
        entries = {s: (f"{BASE_HZ + STEP_HZ * s} Hz",
                       tone(BASE_HZ + STEP_HZ * s, n, rate))
                   for s in range(T.COUNT)}
    else:
        entries = plan(T.COUNT, rate, n)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.wav"):
        f.unlink()

    for slot in range(T.COUNT):
        label, samples = entries[slot]
        with wave.open(str(out / f"{slot:02d}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    tones = [(s, lab) for s, (lab, _) in sorted(entries.items()) if lab != "silence"]
    print(f"wrote {T.COUNT} probe entries to {out}")
    print(f"  {len(tones)} tones, {T.COUNT - len(tones)} silent")
    print()
    for slot, label in tones:
        print(f"  slot {slot:2d}  {label}")
    print()
    print("Apply with:")
    print(f"  dnfw mods apply <image> --mod transients --from {out} -o out/probe.syx")
    print()
    print("Then sweep TRAN on an FM DRUM track. Each tone is loudest at the")
    print("TRAN value where its slot reaches full weight; between slots you")
    print("hear it fade toward silence. Those peaks are the mapping, and the")
    print("width of each is the interpolation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

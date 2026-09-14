"""`dnfw mods` -- list firmware mods, extract their factory content, apply them.

    dnfw mods list
    dnfw mods extract <image> --mod transients -o out/factory
    dnfw mods apply   <image> --mod transients --from my_samples/ -o out/modded.syx

`apply` hands the modified section to the ordinary build path, so the output is
re-signed and **re-verified before it is written** -- nothing leaves this
command the toolchain cannot check end to end. That is `docs/PRINCIPLES.md`'s
rule about flashing, enforced here rather than remembered.
"""

import pathlib

from ..firmware.build import build as rebuild
from ..firmware.build import replacement
from ..firmware.load import load
from ..firmware.verify import verify
from ..mods import ModError, check_compatible
from ..mods import transients as transients_mod
from .files import read_image

NAME = "mods"
HELP = "list, extract and apply firmware mods"

REGISTRY = {transients_mod.ID: transients_mod}


def configure(parser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="show available mods and what they touch")

    ex = sub.add_parser("extract", help="write a mod's factory content out")
    ex.add_argument("image", type=pathlib.Path)
    ex.add_argument("--mod", required=True, choices=sorted(REGISTRY))
    ex.add_argument("-o", "--out", type=pathlib.Path, required=True)

    ap = sub.add_parser("apply", help="apply a mod and rebuild the image")
    ap.add_argument("image", type=pathlib.Path)
    ap.add_argument("--mod", required=True, choices=sorted(REGISTRY))
    ap.add_argument("--from", dest="source", type=pathlib.Path, required=True,
                    help="directory of .wav files, used in sorted order")
    ap.add_argument("-o", "--out", type=pathlib.Path, required=True)


def _list() -> int:
    print(f"{len(REGISTRY)} mod(s)\n")
    for mid, mod in sorted(REGISTRY.items()):
        print(f"  {mid}")
        print(f"    {mod.SUMMARY}")
        print(f"    device 0x{mod.DEVICE:02x}, section {mod.SECTION}")
    print("\nTwo mods can be applied together when the byte ranges they write")
    print("do not overlap. `apply` checks that; it does not and cannot check")
    print("whether two mods make musical sense together.")
    return 0


def _extract(args) -> int:
    import struct
    import wave

    mod = REGISTRY[args.mod]
    firmware = load(read_image(args.image))
    entries = mod.extract(firmware)
    args.out.mkdir(parents=True, exist_ok=True)
    for k, raw in enumerate(entries):
        n = len(raw) // 2
        with wave.open(str(args.out / f"{k:02d}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(mod.RATE)
            w.writeframes(raw)
    print(f"wrote {len(entries)} factory entries to {args.out}")
    print(f"  {mod.ENTRY_SAMPLES} samples each at {mod.RATE} Hz "
          f"= {1000 * mod.ENTRY_SAMPLES // mod.RATE} ms")
    return 0


def _apply(args) -> int:
    mod = REGISTRY[args.mod]
    firmware = load(read_image(args.image))

    found = [e for e in mod.extents(firmware)]
    print("this mod writes:")
    for e in found:
        print(f"  {e}")
    conflicts = check_compatible([(args.mod, found)])
    if conflicts:
        for c in conflicts:
            print(f"  CONFLICT: {c}")
        return 1

    sources = sorted(p for p in args.source.iterdir()
                     if p.suffix.lower() == ".wav")
    if not sources:
        raise ModError(f"no .wav files in {args.source}")
    print(f"\n{len(sources)} input sample(s), in sorted order:")

    result = mod.apply(firmware, sources)
    for note in result.notes:
        print(f"  {note}")

    reps = {sid: replacement(firmware, sid, payload)
            for sid, payload in result.payloads.items()}
    out = rebuild(firmware, reps)
    report = verify(load(out))
    bad = [c for c in report.checks if not c.ok]
    print(f"\nintegrity: {len(report.checks) - len(bad)}/{len(report.checks)} "
          f"checks pass")
    if bad:
        for c in bad:
            print(f"  FAILED: {c.name}")
        print("\nNot written. A rebuild that does not verify never leaves here.")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(out)
    print(f"wrote {args.out} ({len(out):,} bytes)")
    print("\nNothing has been sent to an instrument. Check it with "
          "`dnfw inspect` before it goes anywhere near hardware,")
    print("and make sure the recovery route in docs/flashing.md is proven on "
          "your device first.")
    return 0


def run(args) -> int:
    if args.action == "list":
        return _list()
    if args.action == "extract":
        return _extract(args)
    return _apply(args)

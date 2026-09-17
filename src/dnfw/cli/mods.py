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
from ..mods import bootscreen as bootscreen_mod
from ..mods import lfowaves as lfowaves_mod
from ..mods import moddest as moddest_mod
from ..mods import transients as transients_mod
from .files import read_image

NAME = "mods"
HELP = "list, extract and apply firmware mods"

REGISTRY = {transients_mod.ID: transients_mod,
            moddest_mod.ID: moddest_mod,
            bootscreen_mod.ID: bootscreen_mod,
            lfowaves_mod.ID: lfowaves_mod}


def configure(parser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="show available mods and what they touch")

    ex = sub.add_parser("extract", help="write a mod's factory content out")
    ex.add_argument("image", type=pathlib.Path)
    ex.add_argument("--mod", required=True, choices=sorted(REGISTRY))
    ex.add_argument("-o", "--out", type=pathlib.Path, required=True)

    ap = sub.add_parser("apply", help="apply a mod and rebuild the image")
    ap.add_argument("image", type=pathlib.Path)
    # Repeatable, because applying two mods together is the thing the extent
    # system exists for -- and until there were two mods, the compatibility
    # check was a test that could not fail.
    ap.add_argument("--mod", required=True, action="append",
                    choices=sorted(REGISTRY),
                    help="repeat to apply several mods to one image")
    ap.add_argument("--from", dest="source", type=pathlib.Path,
                    help="directory of .wav files, used in sorted order "
                         "(only mods that take samples need this)")
    ap.add_argument("-o", "--out", type=pathlib.Path, required=True)
    ap.add_argument("--lead-ms", type=float, default=3.0,
                    help="default milliseconds kept before the detected onset "
                         "(per-sample overrides go in prepare.csv)")
    boot = ap.add_argument_group("bootscreen")
    boot.add_argument("--boot-image", type=pathlib.Path, action="append", default=[],
                      help="a 128x64 binary PGM (P5); give one for a static mark or two "
                           "for flashing")
    boot.add_argument("--boot-invert", action="store_true",
                      help="use the inverse of the single --boot-image as the second image")
    boot.add_argument("--boot-slow", type=int, default=4)
    boot.add_argument("--boot-fast", type=int, default=3)
    boot.add_argument("--boot-rush", type=int, default=48)
    boot.add_argument("--boot-stop", type=int, default=72)
    boot.add_argument("--tunnel", type=float, nargs=2, metavar=("X", "Y"),
                      default=list(bootscreen_mod.STOCK_TUNNEL),
                      help="the intro tunnel's texture scale (stock 128 64)")
    lfo = ap.add_argument_group("lfowaves")
    lfo.add_argument("--wavetable", action="append", default=[], metavar="N=FILE",
                     help="replace wavetable N (1-3) with a .wav wavetable or .json table; "
                          "repeatable, the others stay ours")
    ap.add_argument("--prepare", action="store_true",
                    help="onset-align each input to the slot and fade its end; "
                         "off by default so a factory round-trip stays "
                         "byte-identical")


def _staged(firmware, payloads: dict[int, bytes]):
    """`firmware` with any already-applied payloads standing in for sections.

    Mods read the section they are about to change, so a second mod touching
    the same section must see the first one's bytes rather than the original's.
    Both current mods touch different sections, so this is not yet exercised --
    which is exactly why it is written now rather than after it bites.
    """
    if not payloads:
        return firmware
    from ..container.section import Section

    swapped = []
    for section in firmware.container.sections:
        if section.id in payloads:
            swapped.append(_Restaged(section, payloads[section.id]))
        else:
            swapped.append(section)
    return _Firmware(firmware, tuple(swapped))


class _Restaged:
    """A section whose unpacked content is overridden, not recompressed."""

    def __init__(self, original, content: bytes):
        self._o, self._c = original, content
        self.id, self.dest, self.stored = original.id, original.dest, original.stored

    def unpack(self):
        return self._c

    @property
    def raw_payload(self):
        return self._c


class _Firmware:
    """`firmware` with a different section tuple, for staging only."""

    def __init__(self, original, sections):
        self._o = original
        self.container = _Container(original.container, sections)

    def __getattr__(self, name):
        return getattr(self._o, name)


class _Container:
    def __init__(self, original, sections):
        self._o, self.sections = original, sections

    def find(self, section_id):
        return next((s for s in self.sections if s.id == section_id), None)

    def __getattr__(self, name):
        return getattr(self._o, name)


def _apply_transients(mod, firmware, args):
    if args.source is None:
        raise ModError("--from is required for the transients mod")
    sources = sorted(p for p in args.source.iterdir()
                     if p.suffix.lower() == ".wav")
    if not sources:
        raise ModError(f"no .wav files in {args.source}")
    print(f"\n{len(sources)} input sample(s), in sorted order:")
    options = mod.read_options(args.source) if args.prepare else {}
    unknown = set(options) - {p.name for p in sources}
    if unknown:
        raise ModError("prepare.csv names files that are not in "
                       f"{args.source}: {', '.join(sorted(unknown))}")
    if options:
        print(f"  prepare.csv: per-sample settings for {len(options)} file(s)")
    return mod.apply(firmware, sources, condition=args.prepare,
                     lead_ms=args.lead_ms, options=options)


def _read_pgm(path: pathlib.Path) -> set[tuple[int, int]]:
    """Lit pixels of a 128x64 binary PGM (P5), thresholded at half."""
    parts = path.read_bytes().split(maxsplit=4)
    if len(parts) < 5 or parts[0] != b"P5" or int(parts[1]) != 128 or int(parts[2]) != 64:
        raise ModError(f"{path}: expected a 128x64 binary PGM (P5)")
    pix = parts[4]
    return {(x, y) for y in range(64) for x in range(128) if pix[y * 128 + x] > 127}


def _apply_bootscreen(mod, firmware, args):
    if not args.boot_image:
        raise ModError("--boot-image is required for the bootscreen mod")
    images = [mod.image_from_pixels(_read_pgm(p)) for p in args.boot_image]
    if args.boot_invert:
        if len(images) != 1:
            raise ModError("--boot-invert takes exactly one --boot-image")
        images.append(mod.invert(images[0]))
    return mod.apply(firmware, images, slow=args.boot_slow, fast=args.boot_fast,
                     rush=args.boot_rush, stop=args.boot_stop, tunnel=tuple(args.tunnel))


def _apply_lfowaves(mod, firmware, args):
    from .. import wavetable
    tables = [None, None, None]
    for spec in args.wavetable:
        slot, _, path = spec.partition("=")
        if slot not in ("1", "2", "3") or not path:
            raise ModError(f"--wavetable {spec!r}: expected N=FILE with N 1-3")
        path = pathlib.Path(path)
        try:
            tables[int(slot) - 1] = wavetable.to_bytes(wavetable.load(path.read_bytes(), path.name))
        except wavetable.WavetableError as exc:
            raise ModError(f"{path}: {exc}") from None
    return mod.apply(firmware, tables)


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
    firmware = load(read_image(args.image))
    chosen = [REGISTRY[m] for m in dict.fromkeys(args.mod)]

    named = []
    for mod in chosen:
        found = list(mod.extents(firmware))
        print(f"{mod.ID} writes:")
        for e in found:
            print(f"  {e}")
        named.append((mod.ID, found))

    conflicts = check_compatible(named)
    if conflicts:
        for c in conflicts:
            print(f"  CONFLICT: {c}")
        return 1
    if len(named) > 1:
        print(f"\n{len(named)} mods, no overlapping bytes -- "
              f"they can be combined.\n")

    # Each mod is applied to the payload the previous one produced, so a later
    # mod sees the earlier one's bytes. Disjoint extents make the order
    # irrelevant to the result; it is not relied on.
    payloads: dict[int, bytes] = {}
    for mod in chosen:
        staged = _staged(firmware, payloads)
        if mod.ID == "transients":
            result = _apply_transients(mod, staged, args)
        elif mod.ID == "bootscreen":
            result = _apply_bootscreen(mod, staged, args)
        elif mod.ID == "lfowaves":
            result = _apply_lfowaves(mod, staged, args)
        else:
            result = mod.apply(staged)
        for note in result.notes:
            print(f"  {note}")
        payloads.update(result.payloads)

    reps = {sid: replacement(firmware, sid, payload)
            for sid, payload in payloads.items()}
    out = rebuild(firmware, reps)
    report = verify(load(out))
    bad = [c for c in report.checks if not c.ok]
    print(f"\nintegrity: {len(report.checks) - len(bad)}/"
          f"{len(report.checks)} checks pass")
    if bad:
        for c in bad:
            print(f"  FAILED: {c.name}")
        print("\nNot written. A rebuild that does not verify never "
              "leaves here.")
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

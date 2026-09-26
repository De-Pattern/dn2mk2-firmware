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
from ..mods import arpmodes as arpmodes_mod
from ..mods import arpplocks as arpplocks_mod
from ..mods import bootscreen as bootscreen_mod
from ..mods import fxmod as fxmod_mod
from ..mods import lfo4 as lfo4_mod
from ..mods import lfowaves as lfowaves_mod
from ..mods import midiarp as midiarp_mod
from ..mods import moddest as moddest_mod
from ..mods import transients as transients_mod
from .files import read_image

NAME = "mods"
HELP = "list, extract and apply firmware mods"

REGISTRY = {transients_mod.ID: transients_mod,
            moddest_mod.ID: moddest_mod,
            bootscreen_mod.ID: bootscreen_mod,
            lfowaves_mod.ID: lfowaves_mod,
            midiarp_mod.ID: midiarp_mod,
            fxmod_mod.ID: fxmod_mod,
            arpplocks_mod.ID: arpplocks_mod,
            arpmodes_mod.ID: arpmodes_mod,
            lfo4_mod.ID: lfo4_mod}


def configure(parser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="show available mods and what they touch")

    ex = sub.add_parser("extract", help="write a mod's factory content out")
    ex.add_argument("image", type=pathlib.Path)
    ex.add_argument("--mod", required=True, choices=sorted(REGISTRY))
    ex.add_argument("-o", "--out", type=pathlib.Path, required=True)

    mx = sub.add_parser("matrix", help="try every pair of mods, both orders, and report which combine")
    mx.add_argument("image", type=pathlib.Path)
    mx.add_argument("--json", type=pathlib.Path, help="also write the result as JSON")
    mx.add_argument("--page", type=pathlib.Path, action="append", default=[],
                    help="rewrite the generated regions (<!-- dnfw:matrix -->, "
                         "<!-- dnfw:matrix-row ID --> and <!-- dnfw:combines ID -->) "
                         "of this HTML or Markdown file")
    mx.add_argument("--boots", type=pathlib.Path,
                    help="a directory of <a>+<b>/boot.txt from emu_boot_check.py, "
                         "written into the <!-- dnfw:boots --> region")
    mx.add_argument("--emit", type=pathlib.Path,
                    help="write each combinable MAIN OS pair to DIR/<a>+<b>/section_3_MAIN_OS.bin "
                         "for scripts/emu_boot_check.py")

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
    boot.add_argument("--boot-animation", choices=["tunnel", "ascii", "spin"], default="tunnel",
                      help="tunnel: the mark through the stock tunnel; ascii: the mark "
                           "decomposed into glitching characters (DNX's loader); spin: the "
                           "mark spinning and zooming over a smeared star swirl (1966)")
    from .. import asciiglitch
    boot.add_argument("--ascii-chars", default=asciiglitch.RAMP,
                      help="the picture's characters, dark to bright")
    boot.add_argument("--glitch-chars", default=asciiglitch.GLITCH,
                      help="the characters the noise is made of")
    boot.add_argument("--ascii-resolve", type=int, default=96,
                      help="frames from noise to the picture (the intro runs about 175)")
    boot.add_argument("--ascii-idle-frames", type=int, default=16,
                      help="frames of residual glitch, looped once resolved")
    boot.add_argument("--ascii-glitch", type=float, default=1.0,
                      help="tearing and scramble, 0..2 (1 is DNX's)")
    boot.add_argument("--ascii-idle", type=float, default=0.3,
                      help="residual glitch once resolved, 0..1")
    boot.add_argument("--ascii-seed", type=int, default=26,
                      help="the pattern of noise (ascii) or of stars (spin)")
    boot.add_argument("--spin-resolve", type=int, default=120, help="frames until the mark settles")
    boot.add_argument("--spin-loop", type=int, default=48, help="frames per turn of the swirl once settled")
    boot.add_argument("--spin-stars", type=int, default=90)
    boot.add_argument("--spin-smear", type=float, default=1.0, help="trail length, 0..3")
    boot.add_argument("--spin-turns", type=float, default=3.0, help="turns of the mark, 0..12")
    boot.add_argument("--spin-zoom", type=float, default=1.0, help="back-and-forth size swing, 0..2")
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
    if args.boot_animation == "ascii":
        if len(args.boot_image) != 1:
            raise ModError("--boot-animation ascii takes exactly one --boot-image")
        pix = _read_pgm(args.boot_image[0])
        ascii = mod.ascii_frames(lambda x, y: (x, y) in pix, ramp=args.ascii_chars,
                                 glitch_chars=args.glitch_chars, resolve=args.ascii_resolve,
                                 idle_frames=args.ascii_idle_frames, seed=args.ascii_seed,
                                 glitch=args.ascii_glitch, idle=args.ascii_idle)
        return mod.apply(firmware, [], ascii=ascii)
    if args.boot_animation == "spin":
        if len(args.boot_image) != 1:
            raise ModError("--boot-animation spin takes exactly one --boot-image")
        pix = _read_pgm(args.boot_image[0])
        anim = mod.spin_frames(lambda x, y: (x, y) in pix, resolve=args.spin_resolve,
                               idle_frames=args.spin_loop, stars=args.spin_stars,
                               smear=args.spin_smear, spin=args.spin_turns,
                               zoom=args.spin_zoom, seed=args.ascii_seed)
        return mod.apply(firmware, [], ascii=anim)
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
    # A mod that copies stock structures (lfo4 copies the parameter table) goes
    # last, so what the others changed in them is carried into its copy.
    chosen.sort(key=lambda mod: getattr(mod, "APPLY_LAST", False))

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


def _apply_default(mod, firmware, scratch: pathlib.Path):
    """A mod with its factory or neutral inputs, for the matrix."""
    if mod.ID == "transients":
        import wave
        paths = []
        for k, raw in enumerate(mod.extract(firmware)):
            path = scratch / f"{k:02d}.wav"
            if not path.exists():
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(mod.RATE)
                    w.writeframes(raw)
            paths.append(path)
        return mod.apply(firmware, paths)
    if mod.ID == "bootscreen":
        frame = {(x, y) for x in range(128) for y in range(64)
                 if x in (0, 127) or y in (0, 63)}
        return mod.apply(firmware, [mod.image_from_pixels(frame)])
    if mod.ID == "lfowaves":
        return mod.apply(firmware, None)
    return mod.apply(firmware)


def _rewrite(page: pathlib.Path, ids, found, names, boots=None) -> None:
    import re

    from ..mods import matrix

    text = page.read_text(encoding="utf-8")
    table = (matrix.table_md if page.suffix == ".md" else matrix.table_html)(ids, found, names)
    text = re.sub(r"(<!-- dnfw:matrix -->).*?(<!-- /dnfw:matrix -->)",
                  lambda m: m.group(1) + "\n" + table + "\n" + m.group(2), text, flags=re.S)
    if boots is not None:
        rows = []
        for pair in found:
            log = boots / f"{pair.a}+{pair.b}" / "boot.txt"
            if log.exists():
                last = [ln.strip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
                        if ln.strip()]
                verdict = next((ln for ln in reversed(last) if ln.startswith(("booted", "SKIPPED", "FAULT", "NO UI",
                                                                                 "fault", "no UI"))), last[-1])
                rows.append(f"- `{pair.a}` + `{pair.b}`: {verdict}")
        text = re.sub(r"(<!-- dnfw:boots -->).*?(<!-- /dnfw:boots -->)",
                      lambda m: m.group(1) + "\n" + "\n".join(rows) + "\n" + m.group(2), text, flags=re.S)
    text = re.sub(r"(<!-- dnfw:matrix-row (\w+) -->).*?(<!-- /dnfw:matrix-row -->)",
                  lambda m: (m.group(1) + "\n" + matrix.table_html(ids, found, names, only=m.group(2))
                             + "\n" + m.group(3)),
                  text, flags=re.S)
    text = re.sub(r"(<!-- dnfw:combines (\w+) -->).*?(<!-- /dnfw:combines -->)",
                  lambda m: m.group(1) + matrix.combines_text(m.group(2), found, names) + m.group(3),
                  text, flags=re.S)
    page.write_text(text, encoding="utf-8", newline="\n")


def _matrix(args) -> int:
    import json
    import tempfile

    from ..mods import matrix

    firmware = load(read_image(args.image))
    ids = sorted(REGISTRY)
    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        found = matrix.pairs(firmware, REGISTRY,
                             lambda mod, fw: _apply_default(mod, fw, scratch), _staged)
        if args.emit:
            for pair in found:
                mods = sorted((REGISTRY[pair.a], REGISTRY[pair.b]),
                              key=lambda mod: getattr(mod, "APPLY_LAST", False))
                if f"{mods[0].ID}+{mods[1].ID}" in pair.refused:
                    mods.reverse()
                if not pair.combines or 3 not in (mods[0].SECTION, mods[1].SECTION):
                    continue
                payloads = {}
                for mod in mods:
                    payloads.update(_apply_default(mod, _staged(firmware, payloads), scratch).payloads)
                if 3 in payloads:
                    out = args.emit / f"{pair.a}+{pair.b}"
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "section_3_MAIN_OS.bin").write_bytes(payloads[3])

    cell = {}
    for pair in found:
        mark = "yes" if pair.combines and not pair.order_only else (
            "order" if pair.combines else "NO")
        cell[(pair.a, pair.b)] = cell[(pair.b, pair.a)] = mark
    width = max(map(len, ids))
    print(" " * (width + 2) + "  ".join(f"{m[:6]:>6}" for m in ids))
    for a in ids:
        print(f"  {a:<{width}}" + "  ".join(f"{('-' if a == b else cell[(a, b)]):>6}" for b in ids))
    print(f"\nyes = disjoint bytes and applies in both orders; order = only in the order "
          "`apply` uses;\nNO = refused. Not a hardware result: no combined image has been flashed.\n")
    for pair in found:
        if not pair.combines or pair.order_only or pair.note:
            print(f"  {pair.a} + {pair.b}: " + (pair.reason() or next(iter(pair.refused.values()), "")))
            if pair.note:
                print(f"    note: {pair.note}")
    names = {m: getattr(REGISTRY[m], "NAME", m) for m in ids}
    for page in args.page:
        _rewrite(page, ids, found, names, args.boots)
        print(f"  rewrote the generated regions of {page}")
    if args.json:
        args.json.write_text(json.dumps(
            {"mods": ids,
             "pairs": [{"a": p.a, "b": p.b, "combines": p.combines, "order_only": p.order_only,
                        "overlaps": p.overlaps, "refused": p.refused, "note": p.note}
                       for p in found]}, indent=1) + "\n", newline="\n")
    return 0


def run(args) -> int:
    if args.action == "list":
        return _list()
    if args.action == "matrix":
        return _matrix(args)
    if args.action == "extract":
        return _extract(args)
    return _apply(args)

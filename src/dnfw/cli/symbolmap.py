"""`dnfw symbolmap` -- the curated names for a section, merged with its RTTI.

Lists what is known, flags any curated name whose byte guard no longer matches
the image (an address that drifted between OS builds), and with `--ghidra`
writes the script that seeds a fresh Ghidra project with all of it. That script
plus `dnfw symbols` is how an anonymous section becomes a named program without
re-doing the analysis by hand each time.
"""

import pathlib

from ..firmware.load import load
from ..symbolmap import build, discover
from .files import read_image

NAME = "symbolmap"
HELP = "list curated + RTTI names for a section, or emit a Ghidra seeding script"

MAIN_OS = 3


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument(
        "--section", type=int, default=MAIN_OS, help="section id (default: 3, MAIN OS)"
    )
    parser.add_argument(
        "--symbols",
        type=pathlib.Path,
        default=discover.DEFAULT_DIRECTORY,
        help="directory of curated symbols/*.py (default: symbols/)",
    )
    parser.add_argument(
        "--ghidra",
        type=pathlib.Path,
        metavar="FILE",
        help="write the names manifest for ghidra/ApplyNames.java instead of listing",
    )


def run(args) -> int:
    firmware = load(read_image(args.image))
    curated = discover.load(args.symbols)
    names = build.merge(firmware, curated, args.section)

    if args.ghidra:
        from ..symbolmap import ghidra

        args.ghidra.write_text(ghidra.manifest(names), encoding="utf-8")
        print(f"  wrote {args.ghidra}")
        print(f"    {len(names.curated_ok)} curated names, {len(names.derived)} RTTI labels, "
              f"base 0x{names.base:08x}")
        print(f"    apply with: ghidra/ApplyNames.java <this file>  (see docs/symbol-map.md)")
        if names.drift:
            print(f"    {len(names.drift)} curated names skipped: guard no longer matches")
        return 0

    label = build.name(args.section)
    print(f"section {args.section} ({label})  build {firmware.container.build} "
          f"{firmware.container.version}  run base 0x{names.base:08x}")
    print(f"  curated {len(names.curated_ok)} ok"
          + (f", {len(names.drift)} drifted" if names.drift else "")
          + f"   RTTI {len(names.derived)}")
    print()
    for placed in names.curated_ok:
        s = placed.symbol
        print(f"  0x{s.address:08x}  {s.kind:<8} {s.name:<28} {s.note}")
    for placed in names.drift:
        s = placed.symbol
        print(f"  0x{s.address:08x}  DRIFT    {s.name:<28} "
              f"guard {s.guard[:12]}... no longer matches this image")
    return 0

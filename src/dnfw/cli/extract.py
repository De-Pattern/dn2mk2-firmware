"""`dnfw extract` -- write each section out for disassembly or diffing."""

import pathlib

from ..container import ele3
from ..firmware.load import load
from .files import read_image

NAME = "extract"
HELP = "write each section to a directory, depacked where it is compressed"


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("-o", "--out", type=pathlib.Path, required=True, help="output directory")
    parser.add_argument(
        "--section",
        type=int,
        action="append",
        dest="sections",
        metavar="ID",
        help="extract only this section id; repeatable (default: all)",
    )


def _filename(label: str) -> str:
    """Make a section's display name safe to put in a path.

    `ele3.name` returns `?` for a section id we have not identified, which is
    the right thing to *show* and an illegal filename on Windows -- extracting
    DN2 1.11, whose section 8 is still unnamed, failed outright until this.
    Unknown sections are common in new firmware, so this is the normal case,
    not an edge one.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    return safe.strip("_") or "unnamed"


def run(args) -> int:
    firmware = load(read_image(args.image))
    args.out.mkdir(parents=True, exist_ok=True)

    wanted = set(args.sections) if args.sections else None
    written = 0
    for section in firmware.container.sections:
        if wanted is not None and section.id not in wanted:
            continue
        content = section.unpack()
        # The suffix records how the section is stored, because that decides
        # how a rebuild must put it back.
        kind = "aplib" if content else "raw"
        path = args.out / f"section_{section.id}_{_filename(ele3.name(section.id))}.{kind}.bin"
        path.write_bytes(content if content else section.stored)
        print(f"  {path}  {len(content) if content else len(section.stored):,} bytes"
              f"  dest 0x{section.dest:08x}")
        written += 1

    if wanted is not None and written != len(wanted):
        raise ValueError(f"asked for {sorted(wanted)} but wrote {written} section(s)")
    return 0

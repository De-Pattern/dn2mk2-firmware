"""`dnfw diff` -- what changed between two firmware images.

Section by section on decoded content, with differing bytes clustered into
blocks, and optionally the human-readable strings that appeared or vanished.
Written to answer "what did 1.10D -> 1.10E change?" -- see
`docs/os-versions.md` -- and kept because every future OS release asks the same
question before a patch can be ported to it.
"""

import pathlib

from ..container import ele3
from ..firmware import compare
from ..firmware.load import load
from .files import read_image

NAME = "diff"
HELP = "compare two firmware images section by section"

MAIN_OS = 3


def configure(parser) -> None:
    parser.add_argument("a", type=pathlib.Path, help="the older image (.syx or .zip)")
    parser.add_argument("b", type=pathlib.Path, help="the newer image (.syx or .zip)")
    parser.add_argument(
        "--strings",
        type=int,
        nargs="?",
        const=MAIN_OS,
        metavar="SECTION",
        help="also list text strings added and removed (default section: 3, MAIN OS)",
    )
    parser.add_argument(
        "--blocks", type=int, default=8, help="how many change blocks to list per section"
    )


def run(args) -> int:
    a, b = load(read_image(args.a)), load(read_image(args.b))
    ca, cb = a.container, b.container

    print(f"a  {args.a.name}   build {ca.build}  version {ca.version}  "
          f"container {ca.declared_size:,}")
    print(f"b  {args.b.name}   build {cb.build}  version {cb.version}  "
          f"container {cb.declared_size:,}")
    if a.key and b.key:
        same = a.key.value == b.key.value
        print(f"signing key {'unchanged' if same else 'CHANGED'}")
    print()

    for d in compare.sections(a, b):
        label = f"id {d.id:<2} {ele3.name(d.id):<10}"
        if not all(d.present):
            where = "only in a" if d.present[0] else "only in b"
            print(f"{label} {where}  ({max(d.length):,} bytes)")
            continue
        kind = "raw  " if d.raw[0] else "aPLib"
        dest = (f"0x{d.dest[0]:08x}" if d.dest[0] == d.dest[1]
                else f"0x{d.dest[0]:08x} -> 0x{d.dest[1]:08x}  MOVED")
        sizes = (f"{d.length[0]:>9,}" if d.length[0] == d.length[1]
                 else f"{d.length[0]:,} -> {d.length[1]:,} ({d.length[1] - d.length[0]:+,})")
        verdict = "identical" if d.identical else "differs"
        print(f"{label} {kind} {sizes:<28} {verdict:<9}  dest {dest}")
        if d.blocks:
            total = sum(x.differing for x in d.blocks)
            shared = min(d.length)
            scope = "" if d.length[0] == d.length[1] else f" of the first {shared:,}, unshifted"
            print(f"    {total:,} bytes differ{scope}, in {len(d.blocks)} blocks; densest first:")
            for x in sorted(d.blocks, key=lambda x: -x.differing)[: args.blocks]:
                print(f"      +0x{x.start:06x}..+0x{x.end:06x}  {x.differing:>7,} bytes")

    if args.strings is not None:
        sa, sb = ca.find(args.strings), cb.find(args.strings)
        if sa is None or sb is None:
            raise ValueError(f"section {args.strings} is not in both images")
        ta = compare.text(compare.content(sa)[0])
        tb = compare.text(compare.content(sb)[0])
        added, removed = sorted(tb - ta), sorted(ta - tb)
        print(f"\ntext in section {args.strings}: +{len(added)}  -{len(removed)}")
        for s in added:
            print(f"  + {s}")
        for s in removed:
            print(f"  - {s}")
    return 0

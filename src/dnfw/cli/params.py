"""`dnfw params` -- find the parameter tables, or dump one.

Three views, because three different questions get asked of this table:
`--find` locates them, the default dumps records, and `--ids` reports which
groups claim which parameter ids. The last one is the one that matters for a
fourth LFO -- see `docs/lfo-parameters.md`.
"""

import collections
import pathlib

from ..firmware.load import load
from ..image.coldfire import LoadedImage
from ..params import record as rec
from ..params import table as tbl
from .files import read_image

NAME = "params"
HELP = "find and dump the instrument's parameter table"

MAIN_OS = 3


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument(
        "--section", type=int, default=MAIN_OS, help="section id (default: 3, MAIN OS)"
    )
    parser.add_argument(
        "--words",
        type=int,
        default=rec.DN2_WORDS,
        help=f"words per record (default {rec.DN2_WORDS}, the Digitone II record). "
        f"The Digitone 1 record is {rec.DN1_WORDS} words, but only its name pointers "
        "have been verified -- searching a DN1 image is not yet reliable.",
    )
    parser.add_argument(
        "--at", help="dump the table containing this address instead of searching"
    )
    parser.add_argument("--find", action="store_true", help="list the tables and stop")
    parser.add_argument("--ids", action="store_true", help="report the parameter id space")
    parser.add_argument("--page", help="dump only records whose page label is this")


def run(args) -> int:
    image = _section(args)

    if args.at:
        tables = [tbl.containing(image, int(args.at, 0), args.words)]
    else:
        tables = tbl.find(image, args.words)

    if not tables:
        raise ValueError(
            f"no {args.words}-word parameter table found in section {args.section}. "
            f"Try --words {rec.DN1_WORDS} for a Digitone 1 image."
        )

    if args.find:
        for table in tables:
            pages = [p for p in table.pages() if p]
            print(f"0x{table.address:08x}..0x{table.end:08x}  {len(table.records):>4} records")
            print(f"    pages: {', '.join(pages[:16])}" + (" ..." if len(pages) > 16 else ""))
        return 0

    table = tables[0]
    if args.ids:
        _report_ids(table)
        return 0

    _dump(table, args.page)
    return 0


def _section(args) -> LoadedImage:
    firmware = load(read_image(args.image))
    section = firmware.container.find(args.section)
    if section is None:
        raise ValueError(f"image has no section id={args.section}")
    content = section.unpack()
    if content is None:
        raise ValueError(f"section id={args.section} is stored raw, not code")
    return LoadedImage(dest=section.dest, content=content)


def _dump(table: tbl.Table, page: str | None) -> None:
    print(f"0x{table.address:08x}  {len(table.records):,} records of {table.stride} bytes")
    print(
        f"{'addr':>10} {'#':>4} {'grp':>4} {'id':>4}  {'page':<11} {'name':<20} "
        f"{'short':<7} {'range':>6} {'dflt':>6} {'cc':>4} {'nrpn':>5}"
    )
    for index, r in enumerate(table.records):
        if page is not None and r.page != page:
            continue
        print(
            f"0x{r.address:08x} {index:>4} {_n(r.group):>4} {_n(r.parameter_id):>4}  "
            f"{(r.page or ''):<11} {(r.long_name or ''):<20} {(r.short_name or ''):<7} "
            f"{r.value_range:>6x} {r.default:>6x} {_n(r.controller):>4} {_n(r.nrpn):>5}"
        )


def _report_ids(table: tbl.Table) -> None:
    groups: dict[int | None, dict] = collections.defaultdict(
        lambda: {"ids": set(), "pages": set(), "count": 0}
    )
    for r in table.records:
        entry = groups[r.group]
        entry["count"] += 1
        if r.parameter_id is not None:
            entry["ids"].add(r.parameter_id)
        if r.page:
            entry["pages"].add(r.page)

    print(f"{'group':>6} {'recs':>5}  {'ids':<26} pages")
    for group in sorted(groups, key=lambda g: (g is None, g)):
        entry = groups[group]
        label = "(none)" if group is None else str(group)
        print(
            f"{label:>6} {entry['count']:>5}  {_ranges(entry['ids']):<26} "
            f"{', '.join(sorted(entry['pages'])) or '-'}"
        )

    claims: dict[int, set] = collections.defaultdict(set)
    for group, entry in groups.items():
        for pid in entry["ids"]:
            claims[pid].add(group)
    shared = {pid: gs for pid, gs in claims.items() if len(gs) > 1}

    print()
    print(f"{len(shared)} of {len(claims)} parameter ids are claimed by more than one group.")
    if shared:
        print("So the id alone identifies nothing -- see docs/lfo-parameters.md.")

    used = set(g for g in groups if g is not None)
    free = [g for g in range(max(used) + 2) if g not in used] if used else []
    print(f"unused group numbers below {max(used) + 2 if used else 0}: "
          f"{', '.join(str(g) for g in free) or 'none'}")


def _n(value: int | None) -> str:
    return "--" if value is None else str(value)


def _ranges(values: set[int]) -> str:
    """Collapse a set of ids into readable runs: {1,2,3,7} -> '1-3,7'."""
    if not values:
        return "-"
    ordered = sorted(values)
    out, low, high = [], ordered[0], ordered[0]
    for value in ordered[1:]:
        if value == high + 1:
            high = value
        else:
            out.append(str(low) if low == high else f"{low}-{high}")
            low = high = value
    out.append(str(low) if low == high else f"{low}-{high}")
    return ",".join(out)

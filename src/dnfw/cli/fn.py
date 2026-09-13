"""`dnfw fn` -- who calls this address, and what function is it in?

The check this project did not make before hooking `0x4004ca80`. That address
appears in the image exactly once, as a vtable slot; nothing calls it directly;
the cave spliced into it never ran; and four flashed builds were read as four
different problems before anyone counted (`docs/lfo4-slot-plan.md`).

It is one command and it costs nothing, so it belongs in front of every hook:

  `dnfw fn callers <image> --at 0x4004ca80`   how many sites call it directly
  `dnfw fn entry <image> --at 0x4004cb08`     the nearest entry at or below

A count of zero does not prove an address is dead -- a virtual override is
reached through a vtable and no instruction names it. It proves something
narrower and more useful: **a cave there cannot be assumed to run**, so a
silent result would tell you nothing. What settles reachability on the device is
the trace harness (`patch/trace.py`).
"""

import pathlib

from ..firmware.load import load
from ..image import functions
from ..image.coldfire import LoadedImage
from .files import read_image

NAME = "fn"
HELP = "count direct callers of an address, or find the function containing it"

MAIN_OS = 3


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("--section", type=int, default=MAIN_OS, help="section id (default: 3)")
    sub = parser.add_subparsers(dest="fn_action", required=True)

    callers = sub.add_parser("callers", help="list the sites that call --at directly")
    callers.add_argument("--at", required=True, help="virtual address, e.g. 0x4006408a")
    callers.add_argument("--limit", type=int, default=20, help="how many sites to list")
    callers.set_defaults(run=_callers)

    entry = sub.add_parser("entry", help="the nearest call target at or below --at")
    entry.add_argument("--at", required=True, help="virtual address, e.g. 0x4004cb08")
    entry.set_defaults(run=_entry)


def run(args) -> int:
    return args.run(args)


def _image(args) -> LoadedImage:
    firmware = load(read_image(args.image))
    section = firmware.container.find(args.section)
    if section is None:
        raise ValueError(f"image has no section id={args.section}")
    content = section.unpack()
    if content is None:
        raise ValueError(f"section id={args.section} is stored raw, not code")
    return LoadedImage(dest=section.dest, content=content)


def _callers(args) -> int:
    image = _image(args)
    at = int(args.at, 0)
    if not image.contains(at):
        raise ValueError(f"0x{at:08x} is outside 0x{image.dest:08x}..0x{image.end:08x}")
    sites = functions.build(image).callers_of(at)

    print(f"0x{at:08x}: {len(sites)} direct caller(s)")
    for site in sites[:args.limit]:
        print(f"  called from 0x{site:08x}")
    if len(sites) > args.limit:
        print(f"  ... and {len(sites) - args.limit} more")
    if not sites:
        print("\n  Nothing calls this directly. It may still run -- a virtual override is")
        print("  reached through a vtable, which no instruction names -- but a cave here")
        print("  CANNOT BE ASSUMED TO RUN, so a silent result would prove nothing.")
        print("  Verify reachability on the device first (patch/trace.py).")
    return 0


def _entry(args) -> int:
    image = _image(args)
    at = int(args.at, 0)
    if not image.contains(at):
        raise ValueError(f"0x{at:08x} is outside 0x{image.dest:08x}..0x{image.end:08x}")
    graph = functions.build(image)
    entry = graph.containing(at)
    if entry is None:
        print(f"0x{at:08x}: no call target at or below it in this section")
        return 0
    callers = len(graph.callers_of(entry))
    print(f"0x{at:08x} is 0x{at - entry:x} bytes into 0x{entry:08x} "
          f"({callers} direct caller(s))")
    print("\n  A guess, not an identification: functions reached only through a vtable")
    print("  are not call targets, so an address inside one is attributed to whichever")
    print("  directly-called function precedes it. Disassemble from the entry to check.")
    return 0

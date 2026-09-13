"""`dnfw ldr` -- walk a section as an Analog Devices boot stream.

Section 7, which `elektron-firmware-tool` and digikit both call `blob`, is the
**SHARC program** in this format (`docs/sharc-image.md`). It was read as opaque
data for months because a test for a raw 48-bit instruction stream — SHARC's
instruction width — found no 6-byte period in it. There is none to find: a boot
stream is 16-byte headers with payloads between them, so the container has no
global period even when every payload is code.

  `dnfw ldr <image>`             walk section 7 from offset 0
  `dnfw ldr <image> --scan`      find every convincing chain in the section

**Read the `contiguous` line, not the block count.** The `0xAD` signature occurs
by chance more than a thousand times in this section; what identifies a real
stream is that each block's target address continues the previous one's.
"""

import pathlib

from ..firmware.load import load
from ..image import bootstream
from .files import read_image

NAME = "ldr"
HELP = "walk a section as an ADI boot stream (the SHARC program, section 7)"

BLOB = 7


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("--section", type=int, default=BLOB, help="section id (default: 7)")
    parser.add_argument("--start", default="0", help="offset to walk from (default: 0)")
    parser.add_argument("--scan", action="store_true",
                        help="find every convincing chain instead of walking one")
    parser.add_argument("--limit", type=int, default=20, help="blocks to print per stream")


def run(args) -> int:
    firmware = load(read_image(args.image))
    section = firmware.container.find(args.section)
    if section is None:
        raise ValueError(f"image has no section id={args.section}")
    data = section.unpack()
    if data is None:
        data = section.raw_payload

    if args.scan:
        streams = bootstream.find_streams(data)
        if not streams:
            print(f"section {args.section}: no convincing boot stream "
                  f"({len(data):,} bytes)")
            print("\n  A chain must be 3+ blocks with every target continuing the last.")
            return 0
        print(f"section {args.section}: {len(streams)} convincing stream(s) "
              f"in {len(data):,} bytes\n")
        for stream in streams:
            _print_walk(stream, args.limit)
            print()
        return 0

    _print_walk(bootstream.walk(data, int(args.start, 0)), args.limit)
    return 0


def _print_walk(result: bootstream.Walk, limit: int) -> None:
    if not result.blocks:
        print(f"no block header at 0x{result.stopped_at:06x} -- {result.reason}")
        return
    begin = result.blocks[0].offset
    print(f"stream at 0x{begin:06x}: {len(result.blocks)} block(s), "
          f"ends 0x{result.stopped_at:06x} ({result.reason})")
    print(f"  contiguous targets: {result.contiguous} of {result.transitions} transition(s)"
          f"{'  <- convincing' if result.convincing else ''}")
    if result.entry_point is not None:
        print(f"  entry point: 0x{result.entry_point:08x}")
    print(f"  {result.payload_bytes:,} payload bytes into {len(result.regions())} region(s):")
    for lo, hi in result.regions():
        print(f"    0x{lo:08x}..0x{hi:08x}  {hi - lo:>10,} bytes")

    print(f"\n  {'at':<9}{'code':<12}{'target':<12}{'count':<10}{'argument':<12}flags")
    for block in result.blocks[:limit]:
        print(f"  0x{block.offset:06x} 0x{block.code:08x}  0x{block.target:08x}  "
              f"0x{block.count:06x}  0x{block.argument:08x}  "
              f"{','.join(block.flag_names) or '-'}")
    if len(result.blocks) > limit:
        print(f"  ... and {len(result.blocks) - limit} more")

    if not result.convincing:
        print("\n  NOT convincing. 0xAD occurs by chance; a signature is not a format.")
        print("  Treat this as noise unless the targets chain.")

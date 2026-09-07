"""`dnfw validate-disasm` -- Gate F: check a disassembler against objdump.

No reverse-engineering starts on a decoder that has not passed this. The
failure this guards against is not a tool that reports an error; it is a tool
that reads a ColdFire instruction it does not know, assumes it was two bytes,
and carries on producing ordinary-looking instructions that are not there.

Agreement is judged on instruction boundaries, not on how each engine spells
the result -- see `image.instruction`.
"""

import pathlib

from ..image import capstone_m68k, instruction, objdump
from .disasm import read_span

NAME = "validate-disasm"
HELP = "Gate F: check another disassembler against objdump over a span"

MAIN_OS = 3
DEFAULT_LENGTH = 4096


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("address", help="virtual address to start at, e.g. 0x40000400")
    parser.add_argument(
        "length", nargs="?", type=int, default=DEFAULT_LENGTH, help="bytes (default: 4096)"
    )
    parser.add_argument(
        "--section", type=int, default=MAIN_OS, help="section id (default: 3, MAIN OS)"
    )
    parser.add_argument(
        "--against",
        choices=("capstone",),
        default="capstone",
        help="the engine under test (default: capstone)",
    )
    parser.add_argument(
        "--show", type=int, default=5, help="how many divergences to print (default: 5)"
    )


def run(args) -> int:
    tool = objdump.require_tool()
    if not objdump.supports_coldfire(tool):
        raise ValueError(
            f"{tool} was built without the {objdump.ARCHITECTURE} architecture, so it "
            "cannot be the reference. Install a binutils build that carries it."
        )

    span, address = read_span(args.image, args.section, int(args.address, 0), args.length)
    reference = objdump.disassemble(span, address, tool=tool)
    candidate = capstone_m68k.disassemble(span, address)

    result = instruction.compare(reference, candidate)
    skipped = capstone_m68k.undecodable(candidate)

    print(f"span            0x{address:08x} + {len(span)} bytes, section {args.section}")
    print(f"reference       {tool.describe()}  -m {objdump.ARCHITECTURE}  ({len(reference):,} instructions)")
    print(f"candidate       {args.against}  ({len(candidate):,} instructions, "
          f"{len(skipped):,} undecodable)")
    print(f"agreement       {result.matched:,}/{result.compared:,}  ({100 * result.ratio:.1f}%)")

    if result.ok:
        print("\nPASS - the candidate agrees with objdump on every instruction boundary.")
        return 0

    print(f"first divergence at 0x{result.first_divergence:08x}; "
          f"everything the candidate prints after that point is suspect.\n")
    for divergence in result.divergences[: args.show]:
        print(divergence.describe("objdump", args.against))
        print()
    remaining = len(result.divergences) - args.show
    if remaining > 0:
        print(f"... and {remaining:,} more divergences")
    print("FAIL - do not reverse-engineer with this decoder.")
    return 1

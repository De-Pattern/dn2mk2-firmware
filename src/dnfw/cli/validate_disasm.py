"""`dnfw validate-disasm` -- Gate F: check a disassembler against objdump.

No reverse-engineering starts on a decoder that has not been through this. The
failure it guards against is not a tool that reports an error; it is a tool
that meets an instruction it does not know, assumes it was two bytes, and
carries on emitting ordinary-looking code that is not there.

Agreement is judged on instruction boundaries, not on how each engine spells
the result -- see `image.instruction`. The breakdown matters as much as the
percentage: misreading real code is disqualifying, while disagreeing about
whether alignment padding is an instruction is a defect you can work around
once it is written down.
"""

import pathlib

from ..image import capstone_m68k, ghidra_listing, instruction, objdump
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
        choices=("capstone", "ghidra"),
        default="capstone",
        help="the engine under test (default: capstone)",
    )
    parser.add_argument(
        "--listing",
        type=pathlib.Path,
        help="for --against ghidra: the file ghidra/run-gate-f.sh wrote",
    )
    parser.add_argument(
        "--show", type=int, default=5, help="how many divergences to print (default: 5)"
    )


def run(args) -> int:
    tool = objdump.require_tool()
    if not objdump.supports_coldfire(tool):
        raise ValueError(
            f"{tool.describe()} was built without ColdFire support, so it cannot be the "
            "reference. Install a binutils build that carries it."
        )

    span, address = read_span(args.image, args.section, int(args.address, 0), args.length)
    reference = objdump.disassemble(span, address, tool=tool)

    if args.against == "ghidra":
        if args.listing is None:
            raise ValueError(
                "--against ghidra needs --listing FILE. Produce it with "
                "ghidra/run-gate-f.sh, which runs Ghidra headless over the same span."
            )
        candidate = ghidra_listing.load(args.listing)
        skipped = ghidra_listing.undecodable(candidate)
    else:
        candidate = capstone_m68k.disassemble(span, address)
        skipped = capstone_m68k.undecodable(candidate)

    result = instruction.compare(reference, candidate)

    print(f"span            0x{address:08x} + {len(span):,} bytes, section {args.section}")
    print(f"reference       {tool.describe()}  -m {objdump.ARCHITECTURE}  "
          f"({len(reference):,} instructions)")
    print(f"candidate       {args.against}  ({len(candidate):,} instructions, "
          f"{len(skipped):,} undecodable)")
    print(f"agreement       {result.matched:,}/{result.compared:,}  ({100 * result.ratio:.2f}%)")

    if result.ok:
        print()
        print("PASS - the candidate agrees with objdump on every instruction boundary.")
        return 0

    print(f"divergences     {len(result.divergences):,} in {len(result.clusters):,} runs  "
          f"({len(result.on_code):,} starting on code, "
          f"{len(result.on_data):,} on bytes objdump declined to decode)")
    # Reported, not judged. A decoder that has genuinely lost the stream shows
    # a run in the thousands, because it never gets back in step; a short run
    # means it stumbled and recovered.
    print(f"longest run     {result.longest_run} consecutive before resynchronising")
    print(f"first at        0x{result.first_divergence:08x}")
    print()

    for divergence in result.divergences[: args.show]:
        print(divergence.describe("objdump", args.against))
        print()
    remaining = len(result.divergences) - args.show
    if remaining > 0 and args.show > 0:
        print(f"... and {remaining:,} more divergences")
        print()

    if result.on_code:
        print("FAIL - the candidate misread real instructions.")
        print("Do not reverse-engineer with this decoder.")
    else:
        print("FAIL on strict equality, but no real instruction was misread: every")
        print("disagreement is about bytes objdump itself declined to decode.")
        print("Usable with that caveat recorded - see docs/mainos-image.md.")
    return 1

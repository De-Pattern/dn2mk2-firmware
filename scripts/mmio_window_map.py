"""Map every absolute access to a memory-mapped window, by register and caller.

The DN2's ColdFire reaches its off-chip world through four FlexBus windows --
`0xec03xxxx`, `0xec07xxxx`, `0xec09xxxx` and `0x8c00xxxx`. `docs/engine-index-
map.md` §9 counted the accesses in each, saw byte-wide registers, and concluded
none of them could be a boot channel. The count was right and the conclusion
was wrong: the SHARC's boot stream goes out over a DSPI at `0xec038000`, and
`0xec09xxxx` is the FPGA register file beside it (`docs/sharc-image.md`).

A headcount cannot tell those apart. What can is the shape: which addresses are
read, which written, how wide, and -- the part that does the work -- **which
function each access sits in**, since a register touched by one function is a
private control block and one touched by seven is a shared status port.

    python scripts/mmio_window_map.py <image.syx> 0xec090000 0xec0a0000

Reproduces the table in `docs/sharc-image.md`.
"""

import argparse
import collections
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import load_section  # noqa: E402
from dnfw.image import functions  # noqa: E402

MAIN_OS = 3

# Absolute-long operand forms. ColdFire encodes the size in the opcode, so the
# width comes free and is worth keeping: a lone word-wide register among fifty
# byte-wide ones is a data port, which is how `0xec094034` stood out.
#
# **The register field is part of the opcode and must be masked out.** A first
# version of this script matched only the `d0` spelling of each form, and so
# missed `movel %d1,0xec038034` (0x23C1) -- which is the SHARC's boot data
# port, the single most important access in the whole window. Undercounting is
# the failure mode that looks like a clean result, so the masks are written out
# explicitly below.
#
#   move.X dN,(xxx).L   size<<12 | 0x3C0 | N        -> mask 0xFFF8
#   move.X (xxx).L,dN   size<<12 | N<<9 | 0x039     -> mask 0xF1FF
#   movea.X (xxx).L,aN  size<<12 | N<<9 | 0x079     -> mask 0xF1FF
SIZES = {0x1000: "b", 0x3000: "w", 0x2000: "l"}
WRITE_REG = {v | 0x3C0: s for v, s in SIZES.items()}   # masked with 0xFFF8
READ_REG = {v | 0x039: s for v, s in SIZES.items()}    # masked with 0xF1FF
READ_AREG = {v | 0x079: s for v, s in SIZES.items()}   # masked with 0xF1FF
LEA_MASK, LEA_VALUE = 0xF1FF, 0x41F9  # lea abs.l,aN -- the address is taken
CLR_TST = {0x42B9: ("write", "l"), 0x4239: ("write", "b"),
           0x4279: ("write", "w"), 0x4A39: ("read", "b"),
           0x4A79: ("read", "w"), 0x4AB9: ("read", "l")}

# NOT counted, deliberately: andi/ori/eori/cmpi/bset/bclr/btst against an
# absolute address. Those carry their immediate BEFORE the address word, so the
# address is not at +2 and matching them here would misread operands as
# addresses. Every count this script prints is therefore a LOWER BOUND, and it
# says so rather than implying completeness.


def accesses(content: bytes, base: int, lo: int, hi: int):
    """Every absolute access into [lo, hi), as (address, site, kind)."""
    for off in range(0, len(content) - 6, 2):
        word = struct.unpack_from(">H", content, off)[0]
        target = struct.unpack_from(">I", content, off + 2)[0]
        if not lo <= target < hi:
            continue
        kind = None
        if word & LEA_MASK == LEA_VALUE:
            kind = "lea"
        elif (size := WRITE_REG.get(word & 0xFFF8)) is not None:
            kind = f"write.{size}"
        elif (size := READ_REG.get(word & 0xF1FF)) is not None:
            kind = f"read.{size}"
        elif (size := READ_AREG.get(word & 0xF1FF)) is not None:
            kind = f"read.{size}"
        elif word in CLR_TST:
            op, size = CLR_TST[word]
            kind = f"{op}.{size}"
        if kind is not None:
            yield target, base + off, kind


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=pathlib.Path)
    parser.add_argument("low", help="window start, e.g. 0xec090000")
    parser.add_argument("high", help="window end (exclusive)")
    parser.add_argument("--section", type=int, default=MAIN_OS)
    parser.add_argument("--functions", type=int, default=2,
                        help="list enclosing functions when a register has at "
                             "most this many (default: 2) -- a private block")
    args = parser.parse_args()

    lo, hi = int(args.low, 0), int(args.high, 0)
    image = load_section(args.image, args.section)
    graph = functions.build(image)

    by_address = collections.defaultdict(list)
    for target, site, kind in accesses(image.content, image.dest, lo, hi):
        by_address[target].append((site, kind))

    total = sum(len(v) for v in by_address.values())
    print(f"at least {total} accesses across {len(by_address)} distinct "
          f"addresses in {lo:#x}..{hi:#x}")
    print("(a lower bound: immediate-operand forms such as `andi #x,(yyy).l` "
          "are not counted -- see the module docstring)")
    if not by_address:
        return 0

    widths = collections.Counter(
        k.rsplit(".", 1)[-1] for v in by_address.values() for _, k in v)
    print(f"widths: {dict(widths)}\n")

    for address in sorted(by_address):
        sites = by_address[address]
        kinds = collections.Counter(k for _, k in sites)
        callers = sorted({f for f in (graph.containing(s) for s, _ in sites)
                          if f is not None})
        shape = ", ".join(f"{k}x{n}" for k, n in kinds.most_common())
        print(f"  {address:#010x}  {len(sites):>3}  {shape:<30} "
              f"{len(callers)} fn(s)")
        if len(callers) <= args.functions or len(sites) >= 8:
            for caller in callers[:8]:
                print(f"                  in {caller:#010x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

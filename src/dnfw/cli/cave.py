"""`dnfw cave` -- author a code-cave detour: find free space, size a hook.

Two things you need before writing a `CaveHook` (patch/cave.py), and both are
tedious by hand:

  `dnfw cave scan <image>`     free zero-runs in the safe region, as candidate
                               caves -- see docs/memory-map.md for which are
                               genuinely safe (this lists runs, not blessings).
  `dnfw cave probe <image> --at <addr>`
                               disassemble the hook site and print the exact
                               whole-instruction `stock` bytes a detour must
                               displace, with a PC-relative warning.

Applying a cave is not a CLI action: a detour carries a code payload, which is
authored in Python against patch/cave.py, not passed on a command line.
"""

import json
import pathlib

from ..firmware.load import load
from ..image import objdump
from ..image.coldfire import LoadedImage
from ..patch import cave as cavelib
from .files import read_image

NAME = "cave"
HELP = "find free space and size a hook for a code-cave detour"

MAIN_OS = 3
# The region docs/memory-map.md marks safe: unreferenced padding in the
# constants area. Below it is code/rodata; above 0x402e2000 is the .data/BSS
# initializer, which is zero here but copied to SDRAM at boot -- not free.
SAFE_START = 0x4026E000
SAFE_END = 0x402E2000


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("--section", type=int, default=MAIN_OS, help="section id (default: 3)")
    sub = parser.add_subparsers(dest="cave_action", required=True)

    scan = sub.add_parser("scan", help="list free zero-runs (candidate caves)")
    scan.add_argument("--min", type=int, default=32, help="smallest run to report (default: 32)")
    scan.add_argument("--start", default=hex(SAFE_START), help=f"range start (default: {SAFE_START:#x})")
    scan.add_argument("--end", default=hex(SAFE_END), help=f"range end (default: {SAFE_END:#x})")
    scan.add_argument("--json", type=pathlib.Path, default=None,
                      help="also write every run and its verdict here, for a write-map run")
    scan.set_defaults(run=_scan)

    probe = sub.add_parser("probe", help="size the stock a hook at --at must displace")
    probe.add_argument("--at", required=True, help="hook virtual address, e.g. 0x400de34e")
    probe.add_argument("--min", type=int, default=cavelib.HOOK_BRANCH_LEN,
                       help=f"minimum displaced bytes (default: {cavelib.HOOK_BRANCH_LEN}, a jmp)")
    probe.set_defaults(run=_probe)


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


def _scan(args) -> int:
    image = _image(args)
    lo, hi = int(args.start, 0), int(args.end, 0)
    runs = cavelib.find_free_runs(image, lo, hi, args.min)
    if not runs:
        print(f"no free run of {args.min}+ bytes in 0x{lo:08x}..0x{hi:08x}")
        return 0
    verdicts = cavelib.classify(image, runs, lo, hi)
    suspects = cavelib.suspect_arrays(runs)

    total = sum(v.run.size for v in verdicts)
    clean = [v for v in verdicts if v.passes]

    print(f"{len(runs)} free run(s), {total:,} bytes total "
          "(candidates -- confirm against docs/memory-map.md):")
    for v in sorted(verdicts, key=lambda v: v.run.size, reverse=True):
        marks = []
        if v.strided:
            marks.append("fixed-stride group")
        if v.references:
            marks.append(f"{len(v.references)} code reference(s), e.g. 0x{v.references[0]:08x}")
        mark = "  <- " + "; ".join(marks) if marks else ""
        print(f"  0x{v.run.address:08x}  {v.run.size:>6,} bytes{mark}")

    print(f"\n{len(clean)} run(s), {sum(v.run.size for v in clean):,} bytes pass BOTH checks:")
    for v in sorted(clean, key=lambda v: v.run.size, reverse=True)[:10]:
        print(f"  0x{v.run.address:08x}  {v.run.size:>6,} bytes")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "section": args.section,
            "range": [lo, hi],
            "min_size": args.min,
            "runs": [v.as_dict() for v in verdicts],
        }, indent=2) + "\n")
        print(f"\nwrote {len(verdicts)} verdict(s) to {args.json}")

    if suspects:
        print(f"\n{len(suspects)} group(s) repeat at a fixed stride. A compiler pads to an")
        print("alignment boundary; it does not emit many equal gaps at a constant pitch.")
        print("These are almost certainly ARRAYS shipped zeroed and written at runtime:")
        for s in suspects:
            print(f"  {s.describe()}")
        print("\n  0x40287ef6 was exactly this -- 16 records of 1,036 bytes, and its base")
        print("  0x40287f04 is loaded by a clearing loop at 0x4002a4d2 that steps 1,036")
        print("  per record. Caves put there were overwritten while the keyboard was")
        print("  played, faulting the device (docs/flashing.md, 2026-09-13).")

    print("\nThe two checks are complementary and neither is enough alone: that array's")
    print("BASE carries 9 code references while its other fifteen records carry none,")
    print("because they are reached by base + i*1036. References catch a base; stride")
    print("catches the members.")
    print("\nAnd passing both is still not a blessing. These bytes are zero in the image,")
    print("and a region reached only through a computed pointer would pass both checks.")
    print("The only proof is watching the firmware run -- docs/emulator.md, and note that")
    print("a value watch cannot see a write of zero.")
    return 0


def _probe(args) -> int:
    image = _image(args)
    at = int(args.at, 0)
    # Read a generous window and let objdump find the instruction boundaries.
    window = image.read(at, min(32, image.end - at))
    instructions = objdump.disassemble(window, at)
    stock = cavelib.displaced_stock([i.data for i in instructions], args.min)

    covered = 0
    print(f"hook 0x{at:08x}: displace {len(stock)} bytes (whole instructions):")
    for insn in instructions:
        if covered >= len(stock):
            break
        print(f"  0x{insn.address:08x}  {insn.data.hex(' '):<14}  {insn.text}")
        covered += len(insn.data)

    print(f"\n  stock = bytes.fromhex(\"{stock.hex()}\")")
    if cavelib._looks_pcrel(stock):
        print("  WARNING: a byte here is in the PC-relative branch range (0x60-0x6f).")
        print("           If any displaced instruction is a Bcc/BSR, replaying it in the")
        print("           cave retargets it. Prefer a straight-line hook site.")
    else:
        print("  looks straight-line (no PC-relative branch opcode) -- safe to replay.")
    return 0

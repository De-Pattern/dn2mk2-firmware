"""`dnfw disasm` -- disassemble a span of a section.

Defaults to objdump, the only decoder trusted for this CPU. The Capstone engine
is selectable so it can be looked at, and prints a warning when it is, because
it cannot read ColdFire instructions and does not say so itself -- see
`dnfw validate-disasm` and `docs/mainos-image.md`.
"""

import pathlib

from ..image import capstone_m68k, objdump
from ..image.coldfire import LoadedImage
from ..firmware.load import load
from .files import read_image

NAME = "disasm"
HELP = "disassemble a span of a section (ColdFire V4e)"

MAIN_OS = 3


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("address", help="virtual address to start at, e.g. 0x40000400")
    parser.add_argument("length", nargs="?", type=int, default=128, help="bytes (default: 128)")
    parser.add_argument(
        "--section", type=int, default=MAIN_OS, help="section id (default: 3, MAIN OS)"
    )
    parser.add_argument(
        "--engine",
        choices=("objdump", "capstone"),
        default="objdump",
        help="objdump is the reference; capstone cannot read ColdFire (default: objdump)",
    )


def run(args) -> int:
    span, address = read_span(args.image, args.section, int(args.address, 0), args.length)

    if args.engine == "capstone":
        print("warning: Capstone has no ColdFire mode. Instructions ColdFire added")
        print("         decode as .byte, and where they are longer than two bytes the")
        print("         listing below desynchronises. Use it for comparison only.")
        instructions = capstone_m68k.disassemble(span, address)
    else:
        instructions = objdump.disassemble(span, address)

    for insn in instructions:
        print(f"0x{insn.address:08x}  {insn.data.hex(' '):<18}  {insn.text}")
    return 0


def read_span(image_path: pathlib.Path, section_id: int, address: int, length: int):
    """The bytes of one span, and its address. Shared with `validate-disasm`."""
    firmware = load(read_image(image_path))
    section = firmware.container.find(section_id)
    if section is None:
        raise ValueError(f"image has no section id={section_id}")
    content = section.unpack()
    if content is None:
        raise ValueError(f"section id={section_id} is stored raw, not code")
    image = LoadedImage(dest=section.dest, content=content)
    return image.read(address, length), address

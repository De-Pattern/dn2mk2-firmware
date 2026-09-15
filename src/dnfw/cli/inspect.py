"""`dnfw inspect` -- report a firmware image and every integrity field it has."""

import pathlib

from ..container import ele3
from ..firmware.load import load
from ..firmware.verify import verify
from .files import read_image

NAME = "inspect"
HELP = "report an image's transport, container, sections and integrity fields"

# The product code the updater and the bootstrap both check before flashing.
# Only two are measured; anything else prints bare rather than guessing.
PRODUCTS = {52: "Digitone II", 43: "Digitakt II"}


def _product_note(code: int) -> str:
    known = PRODUCTS.get(code)
    return f"  ({known})" if known else ""


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")


def run(args) -> int:
    firmware = load(read_image(args.image))
    container = firmware.container

    print(f"{args.image}")
    print(f"  device            0x{firmware.envelope.device:02x}")
    print(f"  product code      {container.product}{_product_note(container.product)}")
    print(f"  build / version   {container.build} / {container.version}")
    print(f"  container         {container.declared_size:,} bytes")
    print(f"  data packets      {firmware.packets:,}")
    if firmware.key is None:
        print("  signing           unsigned (no HMAC trailer)")
    else:
        print(f"  signing           HMAC-SHA256, key derived from {firmware.key.derivation_string!r}")

    print("  sections")
    for section in container.sections:
        content = section.unpack()
        stored = f"{len(section.stored):,}"
        shape = f"aPLib -> {len(content):,} B" if content else "stored raw"
        print(
            f"    id={section.id:<2} {ele3.name(section.id):<8} "
            f"stored {stored:>10}  dest 0x{section.dest:08x}  {shape}"
        )

    report = verify(firmware)
    print("  integrity")
    for check in report.checks:
        print(f"    [{'ok ' if check.ok else 'BAD'}] {check.name:<32} {check.detail}")

    return 0 if report.ok else 1

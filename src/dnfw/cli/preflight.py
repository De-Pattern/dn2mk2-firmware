"""`dnfw preflight STOCK BUILD`: the safety gate on a finished build file.

`dnfw mods apply` runs this itself before it writes. Run it again on the exact
file you are about to send to the instrument (docs/SAFETY.md).
"""

import pathlib

from .. import safety
from ..firmware.load import load
from .files import read_image

NAME = "preflight"
HELP = "check a build against the stock 1.11 image it came from, before flashing"


def configure(parser) -> None:
    parser.add_argument("stock", type=pathlib.Path, help="Elektron's Digitone II OS 1.11 (.syx or .zip)")
    parser.add_argument("build", type=pathlib.Path, help="the .syx you intend to flash")


def run(args) -> int:
    stock = load(read_image(args.stock))
    ok, text = safety.report(safety.preflight(stock, read_image(args.build)))
    print(text)
    print("\nPASS: safe to flash as far as bytes can say. Follow docs/SAFETY.md for the rest."
          if ok else "\nFAIL: do not flash this file.")
    return 0 if ok else 1

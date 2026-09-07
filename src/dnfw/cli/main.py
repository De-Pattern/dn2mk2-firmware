"""The `dnfw` entry point: argument parsing and dispatch, nothing else.

Every capability in this package is reachable from here. A subcommand module
provides NAME, HELP, `configure(parser)` and `run(args) -> int`, does argument
handling and I/O, and leaves the work to the library.
"""

import argparse
import sys

from . import build, disasm, extract, inspect, patch, symbols, validate_disasm

COMMANDS = (inspect, extract, build, patch, symbols, disasm, validate_disasm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dnfw",
        description="Inspect, modify and rebuild Elektron Digitone firmware images.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in COMMANDS:
        sub = subparsers.add_parser(module.NAME, help=module.HELP, description=module.HELP)
        module.configure(sub)
        sub.set_defaults(run=module.run)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (ValueError, OSError) as error:
        print(f"dnfw {args.command}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Loading curated symbols from the `symbols/` directory.

Same shape as `patch.discover`: each `symbols/*.py` declares a module-level
`SYMBOLS` list, files load in sorted order so a listing is stable, and duplicate
ids are refused. A symbol file is Python for the same reason a patch file is --
the addresses are written with arithmetic and comments beside them, and a data
format that grows expressions is a worse language than the one it is written in.
"""

import importlib.util
import pathlib

from .record import Symbol, SymbolError, validate

DEFAULT_DIRECTORY = pathlib.Path("symbols")


def load(directory: pathlib.Path = DEFAULT_DIRECTORY) -> list[Symbol]:
    """Every curated symbol under `directory`, in file then declaration order."""
    if not directory.is_dir():
        return []

    symbols: list[Symbol] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        symbols.extend(_from_file(path))
    validate(symbols)
    return symbols


def _from_file(path: pathlib.Path) -> list[Symbol]:
    spec = importlib.util.spec_from_file_location(f"dnfw_symbols_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise SymbolError(f"{path}: cannot be loaded as a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    declared = getattr(module, "SYMBOLS", None)
    if declared is None:
        raise SymbolError(f"{path}: no module-level SYMBOLS list")
    for item in declared:
        if not isinstance(item, Symbol):
            raise SymbolError(f"{path}: SYMBOLS contains a {type(item).__name__}, not a Symbol")
    return list(declared)

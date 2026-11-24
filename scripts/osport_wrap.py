"""Put the 1.11 address literals that move in 1.12 through `A()` in the gate's harnesses
(docs/os112-port.md).

    python3 scripts/osport_wrap.py [--write] FILE...

Python's tokenizer finds the numeric literals in code (never comments or strings). A literal is
wrapped when the translator places it and its 1.12 address differs; one it cannot place is listed
for review and left alone (the run's code-hook audit catches a forgotten one). Without --write it
only reports.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dnfw.osport.os import to112  # noqa: E402

IMPORT = ("\nimport sys as _osport_sys, pathlib as _osport_pl  # noqa: E401\n"
          "_osport_sys.path.insert(0, str(_osport_pl.Path(__file__).resolve().parents[{up}] / 'src'))\n"
          "from dnfw.osport.os import A  # noqa: E402  (docs/os112-port.md)\n")


def plan(src: str):
    """-> [(row, col, end_col, text, new)] and the unplaced literals"""
    out, unplaced = [], []
    toks = tokenize.generate_tokens(io.StringIO(src).readline)
    prev = None
    for t in toks:
        if t.type == tokenize.NUMBER and re.fullmatch(r"0[xX][0-9a-fA-F_]{8}", t.string):
            v = int(t.string.replace("_", ""), 16)
            if 0x40000400 <= v < 0x46700000 or 0x80000000 <= v < 0x80020000:
                if prev is not None and prev.string == "(" and _is_A(src, t):
                    prev = t
                    continue
                try:
                    nv = to112(v)
                except ValueError as e:
                    unplaced.append((t.start[0], t.string, str(e)))
                    prev = t
                    continue
                if nv != v:
                    out.append((t.start[0], t.start[1], t.end[1], t.string, f"A({t.string})"))
        prev = t
    return out, unplaced


def _is_A(src: str, t) -> bool:
    line = src.splitlines()[t.start[0] - 1]
    return line[:t.start[1]].endswith("A(")


def apply(src: str, edits) -> str:
    lines = src.splitlines(keepends=True)
    for row, c0, c1, old, new in sorted(edits, key=lambda e: (e[0], -e[1])):
        ln = lines[row - 1]
        assert ln[c0:c1] == old, (row, ln, old)
        lines[row - 1] = ln[:c0] + new + ln[c1:]
    return "".join(lines)


def add_import(src: str, up: int) -> str:
    if "from dnfw.osport.os import A" in src:
        return src
    # after the module docstring and the __future__ import, before the first other statement
    tree_lines = src.splitlines(keepends=True)
    import ast
    mod = ast.parse(src)
    at = 0
    for node in mod.body:
        if (isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant)
                and isinstance(node.value.value, str)) or (
                isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            at = node.end_lineno
            continue
        break
    return "".join(tree_lines[:at]) + IMPORT.format(up=up) + "".join(tree_lines[at:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=pathlib.Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    total = 0
    for f in a.files:
        src = f.read_text()
        edits, unplaced = plan(src)
        total += len(edits)
        print(f"{f}: {len(edits)} to wrap, {len(unplaced)} unplaced")
        for row, lit, why in unplaced:
            print(f"    line {row}: {lit} {why}")
        if a.write and edits:
            up = len(f.resolve().relative_to(ROOT).parts) - 1
            f.write_text(add_import(apply(src, edits), up))
    print(f"{total} literal(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

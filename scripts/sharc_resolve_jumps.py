"""Re-resolve the absolute jump targets in one of our SHARC sources from selas's layout.

    python scripts/sharc_resolve_jumps.py SOURCE.asm LOAD_SW [--check]

Our sources write every branch target as an absolute short-word address, with the
target named in the comment after it, in one of two forms:

    IF NE JUMP 0x16ee14;              // -> wr_t5v_next.
    DM(I7, M7) = 0x16ee13;            // return address - 1: wr_t5v_next. - 1

This assembles SOURCE with selas (WSL), reads where each named label lands (LOAD_SW
plus its byte offset / 2), rewrites the literals, and repeats until the layout is
stable (a literal's width can move later code). `--check` only reports mismatches.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

JUMP = re.compile(r"(JUMP\s+)(0x[0-9a-fA-F]+)(;\s*//\s*->\s*)([A-Za-z_][\w]*)\.")
RET = re.compile(r"(=\s*)(0x[0-9a-fA-F]+)(;\s*//\s*return address - 1:\s*)([A-Za-z_][\w]*)\.\s*-\s*1")


def labels(text: str) -> dict[str, int]:
    """label -> index of the next instruction line (the rule m3._selas numbers by)."""
    out, k, pend = {}, 0, []
    for line in text.splitlines():
        t = line.split("//", 1)[0].strip()
        if not t or t.startswith("."):
            continue
        if t.endswith(":"):
            pend.append(t[:-1].rstrip("."))
            continue
        for p in pend:
            out[p] = k
        pend = []
        k += 1
    return out


def resolve(src: str, load_sw: int, work: pathlib.Path) -> tuple[str, bytes, list[int]]:
    import sharc_waverider_m3 as m3  # noqa: PLC0415  (WSL + selas)
    lab = labels(src)
    for _ in range(6):
        (work / "r.asm").write_text(src, encoding="utf-8", newline="\n")
        be, offs = m3._selas(work / "r.asm", work)
        addr = {name: load_sw + offs[k] // 2 for name, k in lab.items() if k < len(offs)}

        def fix(m, minus=0):
            name = m.group(4)
            if name not in addr:
                raise SystemExit(f"no label {name!r}")
            tail = m.group(0)[m.end(3) - m.start(0):]
            return f"{m.group(1)}{addr[name] - minus:#x}{m.group(3)}{tail}"

        new = JUMP.sub(lambda m: fix(m), src)
        new = RET.sub(lambda m: fix(m, 1), new)
        if new == src:
            return src, be, offs
        src = new
    raise SystemExit("jump targets did not settle")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=pathlib.Path)
    ap.add_argument("load_sw", type=lambda s: int(s, 0))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    src = a.source.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        out, be, offs = resolve(src, a.load_sw, pathlib.Path(tmp))
    if out == src:
        print(f"{a.source.name}: every target already resolved ({len(offs)} instructions, {len(be)} bytes)")
        return 0
    if a.check:
        print(f"{a.source.name}: targets are stale")
        return 1
    a.source.write_text(out, encoding="utf-8", newline="\n")
    print(f"{a.source.name}: targets rewritten ({len(offs)} instructions, {len(be)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

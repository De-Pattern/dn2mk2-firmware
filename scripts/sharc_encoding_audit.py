"""Our SHARC code against the stock DN2 corpus, instruction by instruction (sharcdb databases).

    python scripts/sharc_encoding_audit.py STOCK.sqlite MOD.sqlite LO-HI [LO-HI ...] [--branches]

STOCK.sqlite and MOD.sqlite are digikit `tools/sharcdb.py build` databases (run as a
tool; nothing of it is copied here); LO-HI are short-word spans of our code in MOD.
Each span is walked by instruction width from LO, so an instruction sharcdb left
unaligned (it does for the first few of our spans) is still read; with no mnemonic
there, its `op` count is its `shape` count.

Per instruction it counts, over every aligned stock instruction inside a function:

- `raw`: the exact encoding;
- `shape`: the form with every field except immediates, addresses and offsets
  (the opcode form plus its register combination);
- `op`: the form plus the mnemonic with the data registers R/F/S masked and the DAG
  registers kept (the opcode alone);

and flags RAW-UNSEEN / SHAPE-UNSEEN / OP-UNSEEN. For every Type 5b move it re-derives
the source and destination ureg codes from the raw bits (bits 42:38 srcureghigh,
32 srclow[1], 31 srclow[0], 29:23 dstureg; the field order of the SHARC+ PRM
Figure 13-15) and reports whether stock uses our source and destination codes in
those positions. `--branches` checks every branch and pushed return address lands on
an instruction boundary of the walked spans. docs/waverider-dsp-compare.md section 8
has the reading for the Waverider reader and adapter.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3

IMM = ("addr", "data", "imm", "disp", "offset", "value", "reladdr", "shift")
GROUP = {0: "R", 1: "I", 2: "M", 3: "L", 4: "B", 5: "S"}


def shape(form: str, fields: str | None) -> str:
    f = json.loads(fields) if fields else {}
    return form + json.dumps({k: v for k, v in f.items() if not k.startswith(IMM)}, sort_keys=True)


def op_level(mn: str | None) -> str:
    m = mn or ""
    m = re.sub(r"target=0x[0-9a-f]+", "target=T", m)
    m = re.sub(r"0x[0-9a-f]+", "#", m)
    m = re.sub(r"\b([RFS])\d+\b", r"\1n", m)
    return re.sub(r"(?<![A-Za-z_\d])-?\d+(?!\d)", "#", m)


def ureg_codes(raw: str) -> tuple[int, int]:
    """(src, dst) 7-bit ureg codes of a 32-bit Type 5b move, from the raw bits."""
    v = int(raw, 16)
    hi, lo = v >> 16, v & 0xFFFF
    return ((hi >> 6) & 0x1F) << 2 | (hi & 1) << 1 | lo >> 15, (lo >> 7) & 0x7F


def ureg_name(code: int) -> str:
    return f"{GROUP.get(code >> 4, hex(code >> 4))}{code & 15}"


def walk(rows: dict, lo: int, hi: int):
    sw = lo
    while sw < hi:
        row = rows[sw]
        yield row
        sw += row[1] // 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock", help="the stock sharcdb database")
    ap.add_argument("mod", help="the patched image's sharcdb database")
    ap.add_argument("spans", nargs="+", help="short-word spans LO-HI (hex) of our code")
    ap.add_argument("--branches", action="store_true", help="check branch targets land in the walk")
    a = ap.parse_args(argv)
    stock, mod = sqlite3.connect(a.stock), sqlite3.connect(a.mod)
    raw_c, shp_c, op_c = collections.Counter(), collections.Counter(), collections.Counter()
    ex, src_seen, dst_seen = {}, collections.Counter(), collections.Counter()
    for sw, raw, form, fields, mn in stock.execute(
            "select sw, raw, form, fields, mnemonic from insn where aligned = 1 and function_sw is not null"):
        raw_c[raw] += 1
        k = shape(form, fields)
        shp_c[k] += 1
        ex.setdefault(k, sw)
        op_c[(form, op_level(mn))] += 1
        if form == "5b_move":
            s, d = ureg_codes(raw)
            src_seen[s] += 1
            dst_seen[d] += 1
    rows = {r[0]: r for r in mod.execute("select sw, width, raw, form, fields, mnemonic, confidence from insn")}
    bounds, branches, flagged = set(), [], 0
    for span in a.spans:
        lo, hi = (int(x, 16) for x in span.split("-"))
        for sw, _w, raw, form, fields, mn, conf in walk(rows, lo, hi):
            bounds.add(sw)
            k = shape(form, fields)
            n_raw, n_shape = raw_c[raw], shp_c[k]
            # sharcdb leaves a few of our first instructions unaligned, without a mnemonic:
            # their opcode is then judged by the shape (which includes every register field)
            n_op = op_c[(form, op_level(mn))] if mn else n_shape
            flags = [f for f, n in (("RAW-UNSEEN", n_raw), ("SHAPE-UNSEEN", n_shape), ("OP-UNSEEN", n_op)) if not n]
            if conf != "confident":
                flags.append(f"DECODE-{conf}")
            if form == "5b_move":
                s, d = ureg_codes(raw)
                flags.append(f"[{ureg_name(d)} = {ureg_name(s)}: src code {s:07b} in stock {src_seen[s]}x, "
                             f"dst code {d:07b} in stock {dst_seen[d]}x]")
            flagged += bool(flags) and not n_op
            print(f"{sw:x} {raw:>13} {form:11} raw={n_raw:4} shape={n_shape:5} op={n_op:5}  {mn or '':42} {' '.join(flags)}")
            for t in re.findall(r"target=0x([0-9a-f]+)", mn or ""):
                branches.append((sw, int(t, 16)))
            for t in re.findall(r"DM\(I7, M7\) = 0x([0-9a-f]+)", mn or ""):
                branches.append((sw, int(t, 16) + 1))
    print(f"instructions whose opcode (form + mnemonic, data registers masked) stock never uses: {flagged}")
    if a.branches:
        bad = [(s, t) for s, t in branches if t not in bounds]
        for s, t in branches:
            print(f"branch {s:#x} -> {t:#x} {'ok' if t in bounds else 'NOT AN INSTRUCTION OF OUR SPANS'}")
        return 1 if bad or flagged else 0
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())

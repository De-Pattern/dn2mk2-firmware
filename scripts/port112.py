"""Port a gated DN2 mk2 build from stock OS 1.11 to stock OS 1.12 (docs/os112-port.md).

    PYTHONPATH=src python3 scripts/port112.py BUILD_OS1.11.syx -o BUILD_OS1.12.syx [--report R.json]

Deterministic: the same 1.11 build always gives the same 1.12 file (the gate's rebuild step checks
it). The 1.12 file is gated like any build: `DN2_OS=1.12 DT2_SECTIONS=../sec112 scripts/ship_gate.py
../Digitone_II_OS1.12.syx BUILD_OS1.12.syx`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dnfw.osport.port import port_syx  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path, required=True)
    ap.add_argument("--report", type=pathlib.Path)
    a = ap.parse_args()
    rep = port_syx(a.build, a.out)
    print(f"{a.out}: {len(rep.edits)} edits moved, {len(rep.operands)} operands translated, "
          f"{sum('pointer' in w[3] for w in rep.data_words)} data pointers translated, "
          f"{len(rep.data_words)} data words reviewed, 0 refused")
    if a.report:
        a.report.write_text(json.dumps({
            "edits": [[hex(x), hex(y), n] for x, y, n in rep.edits],
            "operands": [[w, t, hex(v), hex(n)] for w, t, v, n in rep.operands],
            "data_words": [[w, hex(v), hex(n), why] for w, v, n, why in rep.data_words]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

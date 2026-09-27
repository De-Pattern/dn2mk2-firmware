"""Assemble Waverider's ColdFire half ahead of time, for `dnfw mods`.

    python scripts/gen_waverider_code.py

Runs `dnfw.waverider.coldfire.compose` on stock Digitone II 1.11 MAIN OS (the GNU
m68k assembler, natively or through WSL, is needed here and nowhere else) and
records what it changed in `src/dnfw/mods/waverider_code.json`:

- `edits`: every run of section 3 the compose changes, each with the **stock
  bytes it replaces**, so applying is a check-then-write;
- `guards`: whole instructions the edits rely on, read and never written;
- `layout`: where each shim, table and name landed.

Then it replays the edits on the stock image and refuses to write unless the
result is the compose output **byte for byte** -- the data is the build, not a
description of it. The DSP half needs no generation step here: `dnfw.waverider.dsp`
applies committed SHARC objects (`scripts/gen_waverider_sharc.py`).
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                   # noqa: E402
from dnfw.firmware.load import load                     # noqa: E402
from dnfw.patch.assemble import assemble, available     # noqa: E402
from dnfw.waverider import coldfire as CF               # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
OUT_JSON = ROOT / "src/dnfw/mods/waverider_code.json"


def replay(stock: bytes, edits: list[dict]) -> bytes:
    content = bytearray(stock)
    for e in edits:
        at = e["va"] - CF.BASE
        old, new = bytes.fromhex(e["stock"]), bytes.fromhex(e["new"])
        if bytes(content[at:at + len(old)]) != old:
            raise SystemExit(f"{e['va']:#010x}: the recorded stock bytes are not stock")
        content[at:at + len(new)] = new
    return bytes(content)


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found (m68k-linux-gnu-as; WSL is fine)")
    stock = load(read_image(STOCK)).container.find(3).unpack()
    built = CF.compose(stock, assemble)
    edits = sorted((e.to_json() for e in built["edits"]), key=lambda e: e["va"])
    if replay(stock, edits) != built["content"]:
        raise SystemExit("the edits do not reproduce the compose output -- not written")
    code = {
        "os": "Digitone II 1.11",
        "stock_length": len(stock),
        "new_type": CF.NEW_TYPE,
        "clone": CF.CLONE,
        "names": [CF.LONG_NAME, CF.SHORT_NAME],
        "edits": edits,
        "guards": [{"va": va, "bytes": want, "what": why} for va, want, why in CF.GUARDS],
        "layout": {k: v for k, v in sorted(built["layout"].items())},
    }
    OUT_JSON.write_bytes((json.dumps(code, indent=1) + "\n").encode())
    size = sum(len(e["new"]) // 2 for e in edits)
    print(f"wrote {OUT_JSON.relative_to(ROOT)}: {len(edits)} edits, {size} B, "
          f"{len(code['guards'])} guards; replays to the compose output byte for byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

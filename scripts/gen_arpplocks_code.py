"""Assemble the arp p-locks mod ahead of time, for `dnfw mods` and the browser.

    python scripts/gen_arpplocks_code.py

Runs `scripts/build_arp_plocks.py`'s compose (the default build: MODE, SPEED,
RANGE and N.LEN; storage, playback, trigless locks, clear, copy and paste) on
stock Digitone II 1.11 and records what it changed:

- `edits`: every in-image run the build changes -- each code cave whole, and
  every hook and patch -- with the **stock bytes it replaces**, so applying is a
  check-then-write;
- `guards`: whole instructions the hooks replace or rely on, read not written.

Outputs `src/dnfw/mods/arpplocks_code.json`.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_arp_plocks as arp  # noqa: E402
from dnfw.cli.files import read_image  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402

OUT_JSON = ROOT / "src/dnfw/mods/arpplocks_code.json"


def main() -> int:
    if arp.FULL:
        raise SystemExit("the mod is the default build; run without --all")
    stock = load(read_image(ROOT / arp.STOCK)).container.find(arp.MAIN_OS).unpack()
    built = arp.compose(stock, log=lambda *_: None)
    content = built["content"]
    caves = {va - arp.BASE: n for va, n in built["caves"]}

    edits, i, n = [], 0, len(stock)
    while i < n:
        if i in caves:
            j = i + caves[i]
            edits.append({"va": arp.BASE + i, "stock": stock[i:j].hex(),
                          "new": content[i:j].hex(), "what": "arp p-locks code cave"})
            i = j
            continue
        if stock[i] == content[i]:
            i += 1
            continue
        j = i
        while j < n and stock[j] != content[j] and j not in caves:
            j += 1
        edits.append({"va": arp.BASE + i, "stock": stock[i:j].hex(),
                      "new": content[i:j].hex(), "what": "arp p-locks edit"})
        i = j

    code = {
        "os": "Digitone II 1.11",
        "stock_length": n,
        "edits": edits,
        "guards": ([{"va": va, "bytes": want.hex()} for va, want, _ in arp.CONTEXT]
                   + [{"va": va, "bytes": want.hex()} for va, want, _, _ in arp.HOOKS]
                   + [{"va": va, "bytes": want.hex()} for va, want, _, _ in arp.PATCHES]),
        "ram": [{"va": arp.SHADOW, "bytes": 16 * arp.SHADOW_STRIDE, "what": "shadow sounds"},
                {"va": arp.LAST_NOTE, "bytes": 4, "what": "the list the note hook last saw"}],
    }
    OUT_JSON.write_text(json.dumps(code, indent=1) + "\n", newline="\n")
    size = sum(len(e["new"]) // 2 for e in edits)
    print(f"wrote {OUT_JSON.relative_to(ROOT)}: {len(edits)} edits, {size} B, "
          f"{len(code['guards'])} guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Pre-assemble the degreetranspose mod (transpose in scale degrees) for the CLI.

    python scripts/gen_degreetranspose_code.py [--os 1.12]

Runs `build_degreetranspose.compose` on the user's own stock 1.11 image and writes
what it changed as data, the pattern of `gen_lfolength_code.py`:

- `edits`: the hooks and stock's widened masks, each with the **stock bytes it
  expects** (a guard: the mod refuses any image that differs) and its new bytes;
- `guards`: the instructions and tables the code relies on
  (`build_degreetranspose.CONTEXT`), read but not written;
- `code`: the routines, assembled to run at `build_degreetranspose.CODE_VA`, as a
  platform `CODE` chunk (`va`, `blob`), and `labels`.

It refuses to write unless replaying the data on stock gives `compose`'s output
byte for byte. Nothing is derived from Elektron's tables.

Outputs `src/dnfw/mods/degreetranspose_code.json`, or with `--os 1.12` the 1.12 build beside it,
`degreetranspose_code_1.12.json` (issue #382): every site goes through `dnfw.osport.site`.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.cli.files import read_image
from dnfw.firmware.load import load

import build_degreetranspose as bs



def main() -> int:
    os = sys.argv[sys.argv.index("--os") + 1] if "--os" in sys.argv else "1.11"
    stock = load(read_image(resources_dir(ROOT) / bs.STOCKS[os])).container.find(bs.MAIN_OS).unpack()
    built = bs.compose(stock, log=lambda *_: None, os=os)

    def at(va, want):
        return osport.site(os, va, want, stock, bs.BASE)
    content = built["content"]
    blob = built["blob"]

    edits = ([{"va": va, "stock": stock_bytes.hex(),
               "new": content[va - bs.BASE:va - bs.BASE + len(stock_bytes)].hex(),
               "what": f"degreetranspose hook ({label})"}
              for va, stock_bytes, label in [(*at(va, b), lab) for va, b, lab in bs.HOOKS]]
             + [{"va": va, "stock": stock_bytes.hex(), "new": new.hex(),
                 "what": f"degreetranspose mask ({why})"}
                for va, stock_bytes, new, why in [(*at(va, b), n, w) for va, b, n, w in bs.PATCHES]])
    replay = bytearray(stock)
    for e in edits:
        new = bytes.fromhex(e["new"])
        replay[e["va"] - bs.BASE:e["va"] - bs.BASE + len(new)] = new
    if bytes(replay) != content:
        raise SystemExit("the edits do not reproduce compose's output; nothing written")

    labels = built["labels"]
    code = {
        "os": f"Digitone II {os}",
        "stock_length": len(stock),
        "edits": edits,
        "guards": [{"va": va, "bytes": have.hex()} for va, have in
                   [at(va, want) for va, want, _ in bs.CONTEXT]
                   + [at(va, want) for va, want, _ in bs.HOOKS]],
        "labels": labels,
        "code": {"va": bs.CODE_VA, "blob": blob.hex(), "labels": labels},
    }
    out_json = ROOT / "src/dnfw/mods" / ("degreetranspose_code.json" if os == "1.11"
                                         else f"degreetranspose_code_{os}.json")
    out_json.write_text(json.dumps(code, indent=1) + "\n", newline="\n")
    print(f"{len(bs.HOOKS)} hooks, {len(bs.PATCHES)} masks, a {len(blob)} B CODE chunk at {bs.CODE_VA:#010x}; "
          + ", ".join(f"{k} {v:#010x}" for k, v in labels.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

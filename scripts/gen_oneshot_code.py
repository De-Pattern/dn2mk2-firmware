"""Assemble ONESHOT's ColdFire shims ahead of time, for `dnfw mods`.

    python scripts/gen_oneshot_code.py

Runs `dnfw.oneshot.coldfire.assemble_shims` (the GNU m68k assembler, natively or
through WSL, is needed here and nowhere else) and records the result in
`src/dnfw/mods/oneshot_code.json`: the shims' bytes and labels for their fixed place
in the CODE chunk, and the rewritten MACHINE SEL group function. Our own code only;
two assemblies must agree before anything is written. `test/test_oneshot_coldfire.py`
checks the JSON against a fresh assembly when an assembler is present.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.oneshot import coldfire as OC                  # noqa: E402
from dnfw.patch.assemble import assemble, available      # noqa: E402

OUT = ROOT / "src" / "dnfw" / "mods" / "oneshot_code.json"


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found (m68k-linux-gnu-as; WSL is fine)")
    built = OC.assemble_shims(assemble)
    again = OC.assemble_shims(assemble)
    if built != again:
        raise SystemExit("two assemblies of the shims differ")
    source = OC.shim_source() + OC.GROUP_SOURCE
    code = {
        "os": "Digitone II 1.11",
        "new_type": OC.NEW_TYPE,
        "shims_va": OC.SHIMS_VA,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "shims": built["code"].hex(),
        "labels": {k: v for k, v in sorted(built["labels"].items())},
        "group": built["group"].hex(),
    }
    OUT.write_bytes((json.dumps(code, indent=1) + "\n").encode())
    print(f"wrote {OUT.relative_to(ROOT)}: {len(built['code'])} B of shims at "
          f"{OC.SHIMS_VA:#x}, group {len(built['group'])} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

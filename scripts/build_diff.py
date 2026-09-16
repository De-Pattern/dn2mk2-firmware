"""The MAIN OS bytes a build changes, as ranges an emulator run can write.

A snapshot carries its own copy of MAIN OS, so a patched `.syx` cannot be tested
by resuming a snapshot built from stock -- the stock bytes come back with the
snapshot. What can be done is to restore the stock snapshot and then write the
build's changed bytes into guest memory before running. This produces that list.

    python scripts/build_diff.py \\
        00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \\
        00_Resources/02_Builds/intro-stamp_DN2_1.11.syx \\
        out/intro-stamp.patch.json

Only static bytes are covered. A build whose effect depends on boot-time code it
changes -- an initialiser that already ran before the snapshot -- will not show
its effect this way, and the output says how many ranges there are so that can
be judged.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.firmware.load import load

MAIN_OS = 3
BASE = 0x40000400
GAP = 16      # merge changes closer than this into one range


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    stock, built, out = (pathlib.Path(a) for a in sys.argv[1:])
    a = load(read_image(stock)).container.find(MAIN_OS).unpack()
    b = load(read_image(built)).container.find(MAIN_OS).unpack()
    if len(a) != len(b):
        raise SystemExit(f"MAIN OS size differs ({len(a)} vs {len(b)}); ranges would be meaningless")

    ranges, i, n = [], 0, len(a)
    while i < n:
        if a[i] == b[i]:
            i += 1
            continue
        j = i
        while j < n and (a[j] != b[j] or any(a[k] != b[k] for k in range(j, min(j + GAP, n)))):
            j += 1
        ranges.append({"va": f"{BASE + i:#010x}", "hex": b[i:j].hex()})
        i = j

    pathlib.Path(out).write_text(json.dumps({"stock": str(stock), "built": str(built),
                                             "ranges": ranges}, indent=1))
    total = sum(len(r["hex"]) // 2 for r in ranges)
    print(f"{len(ranges)} ranges, {total} bytes -> {out}")
    for r in ranges:
        print(f"  {r['va']}  {len(r['hex']) // 2:>5} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

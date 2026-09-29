"""Build a USB-probe image, and lay out what the emulator gates read.

    python scripts/build_usbprobe.py usbprobe
    python scripts/build_usbprobe.py waverider-m5c-usbprobe \
        --base 00_Resources/02_Builds/waverider-m5b_DN2_1.11.syx \
        --section7 00_Resources/02_Builds/waverider-m5c_DN2_1.11.syx

derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

Applies `dnfw.mods.usbprobe` to `--base` (stock 1.11 by default), optionally
swaps in another build's section 7, rebuilds and verifies (`dnfw.firmware`),
and writes:

- `out/<name>/<name>_DN2_1.11.syx`, and with `--install` (after the gates)
  `00_Resources/02_Builds/<name>_DN2_1.11.syx`, refusing to overwrite one;
- `out/<name>/section_3_MAIN_OS.bin`, `symbols.json`, `routines.json`: what
  `scripts/emu_boot_check.py`, `scripts/emu_usbprobe.py` and
  `scripts/check_coldfire.py` read under WSL, where there is no `dnfw`.

It is `dnfw mods apply` plus the section-7 swap and the gate layout, which the
CLI has no business knowing about.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                   # noqa: E402
from dnfw.firmware.load import load                     # noqa: E402
from dnfw.firmware.build import build as rebuild        # noqa: E402
from dnfw.firmware.build import replacement             # noqa: E402
from dnfw.firmware.verify import verify                 # noqa: E402
from dnfw.mods import usbprobe                          # noqa: E402

RESOURCES = next((d / "00_Resources" for d in (ROOT, *ROOT.parents) if (d / "00_Resources").is_dir()),
                 ROOT / "00_Resources")
OUT = RESOURCES.parent / "out"
STOCK = RESOURCES / "00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
BUILDS = RESOURCES / "02_Builds"


def _path(p: str) -> pathlib.Path:
    q = pathlib.Path(p)
    return q if q.is_absolute() else RESOURCES.parent / q


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("name", help="the build's subject: <name>_DN2_1.11.syx")
    p.add_argument("--base", type=_path, default=STOCK, help="the image the probe goes onto")
    p.add_argument("--section7", type=_path, help="take section 7 (the SHARC) from this build")
    p.add_argument("--tag", help="HELLO's tag (default: the name, cut to 15)")
    p.add_argument("--install", action="store_true",
                   help="also write 00_Resources/02_Builds/<name>_DN2_1.11.syx: only after the gates pass")
    args = p.parse_args()

    target = BUILDS / f"{args.name}_DN2_1.11.syx"
    if args.install and target.exists():
        raise SystemExit(f"{target} exists: builds are never overwritten")
    firmware = load(read_image(args.base))
    tag = (args.tag or args.name)[:15]
    result = usbprobe.apply(firmware, tag=tag)
    payloads = dict(result.payloads)
    if args.section7:
        payloads[7] = load(read_image(args.section7)).container.find(7).unpack()
    reps = {sid: replacement(firmware, sid, data) for sid, data in payloads.items()}
    out = rebuild(firmware, reps)
    report = verify(load(out))
    bad = [c.name for c in report.checks if not c.ok]
    print(f"integrity: {len(report.checks) - len(bad)}/{len(report.checks)} checks pass")
    if bad:
        raise SystemExit(f"not written: {', '.join(bad)}")

    folder = OUT / args.name
    folder.mkdir(parents=True, exist_ok=True)
    built = load(out)
    (folder / "section_3_MAIN_OS.bin").write_bytes(built.container.find(3).unpack())
    (folder / "section_7_blob.bin").write_bytes(built.container.find(7).unpack())
    spec = usbprobe.SPEC
    (folder / "symbols.json").write_text(json.dumps(
        {k: f"0x{v:08x}" for k, v in spec["symbols"].items() if v >= 0x40000000}, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    (folder / "routines.json").write_text(json.dumps(
        {k: f"0x{v:08x}" for k, v in spec["routines"].items()}, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    (folder / "cave.bin").write_bytes(bytes.fromhex(spec["edits"][0]["new"]))
    (folder / target.name).write_bytes(out)
    print(f"tag {tag!r}; wrote {folder / target.name} ({len(out):,} B) and the gate layout")
    if args.install:
        target.write_bytes(out)
        print(f"installed {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

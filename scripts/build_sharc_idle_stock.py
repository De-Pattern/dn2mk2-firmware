"""Stock DN2 1.11 with the USB probe and the SHARC idle-time stub, and nothing else.

    python scripts/build_sharc_idle_stock.py IMAGE -o OUT.syx [--probe-tag stock-idle]

A diagnostic build, not a mod: it measures the stock engine's SHARC load
(`tools/dn2sharc_load.py LABEL --idle`) with none of Waverider's code in either
processor. Section 3 is the usbprobe mod applied to stock; section 7 is
`dnfw.waverider.dsp.section7_idle_only` (stock plus `idle_load.asm` and its one
patch). The image goes through the same rebuild and integrity check as
`dnfw mods apply`, and is not written unless every check passes.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                   # noqa: E402
from dnfw.firmware.build import build as rebuild        # noqa: E402
from dnfw.firmware.build import replacement             # noqa: E402
from dnfw.firmware.load import load                     # noqa: E402
from dnfw.firmware.verify import verify                 # noqa: E402
from dnfw.mods import usbprobe                          # noqa: E402
from dnfw.waverider import dsp                          # noqa: E402

MAIN_OS, DSP_STREAM = 3, 7


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("-o", "--out", type=pathlib.Path, required=True)
    p.add_argument("--probe-tag", default="stock-idle")
    a = p.parse_args(argv)
    if a.out.exists():
        print(f"  {a.out} exists: builds are never overwritten")
        return 1
    firmware = load(read_image(a.image))
    probe = usbprobe.apply(firmware, tag=a.probe_tag)
    stream = firmware.container.find(DSP_STREAM).unpack()
    payloads = {MAIN_OS: probe.payloads[MAIN_OS], DSP_STREAM: dsp.section7_idle_only(stream)}
    extra = set(probe.payloads) - {MAIN_OS}
    if extra:
        print(f"  the probe also wrote sections {sorted(extra)}: not expected")
        return 1
    out = rebuild(firmware, {sid: replacement(firmware, sid, pl) for sid, pl in payloads.items()})
    report = verify(load(out))
    bad = [c for c in report.checks if not c.ok]
    print(f"integrity: {len(report.checks) - len(bad)}/{len(report.checks)} checks pass")
    if bad:
        for c in bad:
            print(f"  FAILED: {c.name}")
        return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(out)
    print(f"wrote {a.out} ({len(out):,} bytes); nothing has been sent to an instrument")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

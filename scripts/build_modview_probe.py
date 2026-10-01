"""Build the modulation-display measurement builds: Waverider M8.1 + the usbprobe.

    python scripts/build_modview_probe.py --build 1 -o 00_Resources/02_Builds/modview1-usbprobe_DN2_1.11.syx
    python scripts/build_modview_probe.py --build 2 -o 00_Resources/02_Builds/modview2-usbprobe_DN2_1.11.syx

- **Build 1** counts and times every Waverider page draw (`WR_PROBE`): how often the
  page really redraws on the instrument, and what one draw costs.
- **Build 2** adds the markers (`WR_MARKERS`) on every working control on every draw,
  modulated or not -- the worst case -- and times them apart.

The page renderer is compiled with those switches (`csrc/waverider/page.c`), so the
shipped mod (`src/dnfw/mods/waverider_code.json`) is untouched: this script composes its
own spec in memory, hands it to the Waverider mod, and applies it with the usbprobe
mod through `dnfw mods apply`. It writes `<out>.modview.json` beside the build: the
address of the probe block, for `tools/dn2modview.py`.

docs/modulation-display.md has the plan and the reading.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                   # noqa: E402
from dnfw.cli.main import main as dnfw_main             # noqa: E402
from dnfw.firmware.load import load                     # noqa: E402
from dnfw.mods import waverider as waverider_mod        # noqa: E402
from dnfw.patch.assemble import assemble                # noqa: E402
from dnfw.waverider import coldfire as CF               # noqa: E402
from dnfw.waverider import cpage                        # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
TAGS = {1: "modview1", 2: "modview2"}


def spec_for(build: int) -> tuple[dict, int]:
    """-> (the Waverider spec with the measurement switches, the probe block's address)."""
    stock = load(read_image(STOCK)).container.find(3).unpack()
    defines = f"#define WR_PROBE 1\n#define WR_MARKERS {1 if build == 2 else 0}\n"
    seen: dict[str, int] = {}

    def compile_c(header: str, *, base: int):
        image, symbols, bss = cpage.compile_page(defines + header, base=base)
        seen.update(symbols)
        return image, symbols, bss

    built = CF.compose(stock, assemble, compile_c)
    spec = dict(waverider_mod.SPEC)
    spec["edits"] = sorted((e.to_json() for e in built["edits"]), key=lambda e: e["va"])
    spec["layout"] = {k: v for k, v in sorted(built["layout"].items())}
    spec["chunk"] = {"load": built["chunk"]["load"], "code": built["chunk"]["code"].hex()}
    return spec, seen["wr_probe"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", type=int, choices=(1, 2), required=True)
    p.add_argument("-o", "--out", type=pathlib.Path, required=True)
    p.add_argument("--tag", default=None, help="the probe's HELLO tag (default modview1/2)")
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    tag = a.tag or TAGS[a.build]
    spec, probe = spec_for(a.build)
    waverider_mod.SPEC = spec
    code = dnfw_main(["mods", "apply", str(STOCK), "--mod", "waverider", "--mod", "usbprobe",
                      "--probe-tag", tag, "-o", str(a.out)])
    if code:
        return code
    side = a.out.with_name(a.out.name + ".modview.json")
    side.write_text(json.dumps({"build": a.build, "tag": tag, "probe": probe,
                                "chunk": [spec["chunk"]["load"], len(spec["chunk"]["code"]) // 2]},
                               indent=1) + "\n")
    print(f"probe block at {probe:#010x}; wrote {side}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

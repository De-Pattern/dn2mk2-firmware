"""LFO4 step 0: a trivial C routine, loaded by the startup loader, called from a hook.

    python scripts/build_c_hello.py

`docs/lfo4-build-plan.md` §8, step 0: prove the chain before any LFO4 logic
depends on it. `csrc/hello/` is compiled and linked at `0x46800000`, carried in
a `CODE` chunk of the appended area, copied there by the startup loader
(`dnfw.patch.loader`), initialised, and reached from a hook on `memcpy`'s entry
with `memcpy`'s own arguments. Its init calls the firmware's `memset`.

Writes:
- `out/c-hello/section_3_MAIN_OS.bin` -- the MAIN OS the emulator boots
  (`DT2_MAIN_IMG`), and `out/c-hello/symbols.json`, for
  `scripts/emu_c_hello.py`;
- `00_Resources/02_Builds/c-hello_DN2_1.11.syx` -- not meant for the
  instrument: step 0 is verified under the emulator.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                      # noqa: E402
from dnfw.container.section import compress               # noqa: E402
from dnfw.firmware import build as fwbuild                 # noqa: E402
from dnfw.firmware.load import load                        # noqa: E402
from dnfw.patch import area, cbuild, loader                # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
MAIN_OS, BASE = 3, 0x40000400
CODE_VA = 0x46800000              # above BSS (0x466b74d0), clear of every tenant (docs/memory-map.md)
MEMCPY_VA = 0x40134490
MEMCPY_STOCK = bytes.fromhex("226f0004206f0008")   # movea.l 4(sp),a1 ; movea.l 8(sp),a0
OUT = ROOT / "out/c-hello"
SYX = ROOT / "00_Resources/02_Builds/c-hello_DN2_1.11.syx"
SRC = ROOT / "csrc"


def compose(stock: bytes):
    code = cbuild.build([SRC / "hello/hello.c", SRC / "hello/memcpy_hook.S"], base=CODE_VA,
                        entries=["hello_init", "hello_memcpy_stub"], include=[SRC / "include"])
    chunk = area.CodeChunk(CODE_VA, code.image, code.bss, code["hello_init"]).pack()
    content = loader.install(stock, [(area.CODE, chunk)])
    at = MEMCPY_VA - BASE
    if content[at:at + 8] != MEMCPY_STOCK:
        raise SystemExit(f"memcpy at 0x{MEMCPY_VA:08x} is not stock")
    content[at:at + 8] = b"\x4e\xf9" + struct.pack(">I", code["hello_memcpy_stub"]) + b"\x4e\x71"
    return content, code


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    stock = section.unpack()
    content, code = compose(stock)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "section_3_MAIN_OS.bin").write_bytes(content)
    symbols = {k: v for k, v in code.symbols.items() if k.startswith("hello")}
    symbols["dnfw_boot"] = loader.build()["dnfw_boot"]
    (OUT / "symbols.json").write_text(json.dumps({k: f"0x{v:08x}" for k, v in symbols.items()}, indent=1) + "\n",
                                      newline="\n")
    SYX.parent.mkdir(parents=True, exist_ok=True)
    SYX.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, bytes(content))}))
    print(f"code {len(code.image)} B + {code.bss} B bss at 0x{CODE_VA:08x}; "
          f"MAIN OS {len(content):,} B (+{len(content) - len(stock)}); wrote {SYX.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

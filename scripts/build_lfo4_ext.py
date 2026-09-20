"""LFO4 step 1: the extension table, carried through `memcpy` and `memset`.

    python scripts/build_lfo4_ext.py

`docs/lfo4-build-plan.md` §8, step 1. `csrc/lfo4/` is compiled and linked at
`0x46800000`, carried in a `CODE` chunk of the appended area and copied there by
the startup loader step 0 proved (`dnfw.patch.loader`). Both `memcpy` and
`memset` get eight bytes of their entry replaced by a jump to a stub, which
calls the C and then replays what the jump displaced.

Two things are checked here rather than left to the emulator: that each site is
stock before it is patched, and that the stub replays **exactly** the bytes it
displaced -- the assembler's encoding of the two replayed instructions is
compared with the image's own.

Writes `out/lfo4-ext/section_3_MAIN_OS.bin` and `symbols.json` for
`scripts/emu_lfo4_ext.py`, and `00_Resources/02_Builds/lfo4-ext_DN2_1.11.syx`.
The build is not for the instrument: step 1 is verified here.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                      # noqa: E402
from dnfw.container.section import compress                # noqa: E402
from dnfw.firmware import build as fwbuild                 # noqa: E402
from dnfw.firmware.load import load                        # noqa: E402
from dnfw.patch import area, cbuild, loader                # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
MAIN_OS, BASE = 3, 0x40000400
CODE_VA = 0x46800000              # above BSS, clear of every tenant (docs/memory-map.md)
SRC = ROOT / "csrc"
OUT = ROOT / "out/lfo4-ext"
SYX = ROOT / "00_Resources/02_Builds/lfo4-ext_DN2_1.11.syx"

# The two sites: entry, the C stub, and the symbol at the replayed instructions.
SITES = [("memcpy", 0x40134490, "lfo4_memcpy_stub", "lfo4_memcpy_displaced"),
         ("memset", 0x401344D8, "lfo4_memset_stub", "lfo4_memset_displaced")]
DISPLACED = 8                     # bytes: jmp <abs.l> is 6, then a nop


def compile_code() -> cbuild.Linked:
    sources = [SRC / "lfo4" / name for name in ("init.c", "ext.c", "carry.c", "hooks.S")]
    # `ext_get` / `ext_set` / `ext_drop` are reached by nothing in the image yet
    # -- step 2's save and load, step 4's page, and the harness are their
    # callers -- so they are named here or `--gc-sections` drops them.
    return cbuild.build(sources, base=CODE_VA, include=[SRC / "include"],
                        entries=["lfo4_init", "ext_get", "ext_set", "ext_drop",
                                 *(s[2] for s in SITES)])


def patch(content: bytearray, code: cbuild.Linked) -> None:
    """Replace each site's first eight bytes, having checked what is there."""
    for name, va, stub, replay in SITES:
        at = va - BASE
        stock = bytes(content[at:at + DISPLACED])
        mine = code.image[code[replay] - CODE_VA:code[replay] - CODE_VA + DISPLACED]
        if mine != stock:
            raise SystemExit(f"{name}: the stub replays {mine.hex()}, the image holds {stock.hex()}")
        content[at:at + DISPLACED] = b"\x4e\xf9" + struct.pack(">I", code[stub]) + b"\x4e\x71"


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    stock = section.unpack()

    code = compile_code()
    chunk = area.CodeChunk(CODE_VA, code.image, code.bss, code["lfo4_init"]).pack()
    content = loader.install(stock, [(area.CODE, chunk)])
    patch(content, code)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "section_3_MAIN_OS.bin").write_bytes(content)
    wanted = ("lfo4_", "ext_")
    symbols = {k: v for k, v in code.symbols.items() if k.startswith(wanted)}
    symbols["dnfw_boot"] = loader.build()["dnfw_boot"]
    (OUT / "symbols.json").write_text(
        json.dumps({k: f"0x{v:08x}" for k, v in sorted(symbols.items())}, indent=1) + "\n", newline="\n")
    SYX.parent.mkdir(parents=True, exist_ok=True)
    SYX.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, bytes(content))}))

    print(f"code {len(code.image)} B at 0x{CODE_VA:08x}, {code.bss:,} B of table and state after it; "
          f"MAIN OS {len(content):,} B (+{len(content) - len(stock)}); wrote {SYX.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

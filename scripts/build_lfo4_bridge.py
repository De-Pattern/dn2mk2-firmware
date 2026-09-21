"""LFO4: the four steps become one build, and the engine pulls from the table.

    python scripts/build_lfo4_bridge.py

Steps 1-3 each proved one thing and were separate images. This is the first
build where they are the same firmware:

| from | what it brings |
|---|---|
| step 0 | the startup loader and the `CODE` chunk that carries our C |
| steps 1-2 | the extension table, its carry through `memcpy` / `memset`, and save / load through the reserved p-lock ids |
| step 3 | a fourth LFO in both evaluators, reading a **per-track** row |
| here | `csrc/lfo4/bridge.c` -- the tick pulls each track's row from the table |

**The tick pulls; nothing pushes.** `a4_top` and `b_top` already run once per
track with the index in hand, so each now calls `lfo4_refresh(track)`, which
returns that track's row address after making it current. It copies only when
the track's sound changed or `ext_generation` moved, so the common case is two
loads and two compares.

The two stubs must preserve `d0`/`d1`/`a0`/`a1` across that call: they sit
inside evaluator code that never expected one. `%a5` (A's track index) is
callee-saved by the compiler's own convention, so it survives.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import build_lfo4_tick as v6a                             # noqa: E402
import build_lfo4_tick7 as tick7                          # noqa: E402
from build_lfo4_ext import CODE_VA, SITES                 # noqa: E402
from dnfw.cli.files import read_image                      # noqa: E402
from dnfw.container.section import compress                # noqa: E402
from dnfw.firmware import build as fwbuild                 # noqa: E402
from dnfw.firmware.load import load                        # noqa: E402
from dnfw.patch import area, cbuild, loader                # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
MAIN_OS, BASE = 3, 0x40000400
KIT = 0x4210C08C                  # the live container (docs/lfo4-build-plan.md)
SRC = ROOT / "csrc"
OUT = ROOT / "out/lfo4-bridge"
SYX = ROOT / "00_Resources/02_Builds/lfo4-bridge_DN2_1.11.syx"

# `setter.c` is here because `hooks.S` is shared and its `lfo4_set_stub`
# refers to it. This build does not patch that site, so `--gc-sections`
# drops both -- but the link needs the symbol to exist.
SOURCES = ("init.c", "ext.c", "carry.c", "store.c", "bridge.c", "setter.c", "hooks.S")
ENTRIES = ["lfo4_init", "ext_get", "ext_set", "ext_drop", "lfo4_refresh", "lfo4_sound_of",
           *(s[2] for s in SITES)]

# Each stub asks the C for its row instead of computing one from a fixed table.
# `lfo4_refresh` returns the row address; the loop wants that address minus the
# displacement its body reads through.
PULL = """    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    move.l  {index},%sp@-
    jsr     {refresh:#010x}
    addq.l  #4,%sp
    movea.l %d0,%a4
    lea     %a4@(-{bias}),%a4
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp"""


def cave_source(table_va: int, refresh: int) -> str:
    """tick7's stubs, with both parameter loads replaced by a call to the C."""
    source = v6a.cave_source(table_va)
    for bias, index in ((68, "%a5"), (34, "%d0")):
        line = f"    lea     {table_va - bias:#010x},%a4"
        if source.count(line) != 1:
            raise SystemExit(f"expected one {line.strip()!r} in the stubs, found {source.count(line)}")
        source = source.replace(line, PULL.format(index=index, refresh=refresh, bias=bias))
    return source


def main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX, extra=(), chunks=None) -> int:
    """Build it. `extra` are further site patches, each `f(content, code)`.

    The arguments exist so a build that is *this one plus a site* -- step 4's
    setter divert is the first -- composes instead of copying two hundred lines
    that would then drift apart.

    `chunks`, if given, is `f(stock) -> [(id, data)]`: further area chunks to
    append beside the C. Step 4b's relocated parameter table is one, and it is
    built from the stock image rather than compiled, which is why the hook
    takes the image and runs before the loader is installed.
    """
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    stock = section.unpack()

    # The rows are a C array now, so the address comes *out* of the build
    # instead of being told to it -- and the cave goes back to holding nothing
    # but stubs, which is all a gap in someone else's code should ever hold.
    code = cbuild.build([SRC / "lfo4" / name for name in sources], base=CODE_VA,
                        include=[SRC / "include"], entries=entries + ["lfo4_rows"],
                        defines={"LFO4_KIT": f"{KIT:#x}u"})
    table_va = code["lfo4_rows"]
    chunk = area.CodeChunk(CODE_VA, code.image, code.bss, code["lfo4_init"]).pack()
    content = loader.install(stock, [(area.CODE, chunk), *(chunks(stock) if chunks else ())])
    print(f"part 1 -- C: {len(code.image)} B at {CODE_VA:#010x}, {code.bss:,} B of state; "
          f"rows at {table_va:#010x}, kit {KIT:#010x}")

    print("part 2 -- the four C hook sites")
    for name, va, stub, replay, n in SITES:
        at = va - BASE
        if bytes(content[at:at + n]) != code.image[code[replay] - CODE_VA:code[replay] - CODE_VA + n]:
            raise SystemExit(f"{name}: the stub does not replay what it displaces")
        jump = b"\x4e\xf9" + struct.pack(">I", code[stub])
        content[at:at + n] = jump + b"\x4e\x71" * ((n - len(jump)) // 2)
        print(f"  {va:#010x}  {name}")

    print("part 3 -- the engine, from step 3")
    stub_va = v6a.CAVE
    v6a.require_zero(content, v6a.CAVE, v6a.CAVE_CAP, "cave region")
    payload, offsets = v6a.assemble_stubs(cave_source(table_va, code["lfo4_refresh"]), stub_va)
    if len(payload) > v6a.CAVE_CAP:
        raise SystemExit(f"cave overflows: {len(payload)} > {v6a.CAVE_CAP}")
    content[stub_va - BASE:stub_va - BASE + len(payload)] = payload
    print(f"  rows {table_va:#010x} (in our BSS), stubs {len(payload)} B, "
          f"{v6a.CAVE_CAP - len(payload)} B of cave left")
    for va, was, new, why in v6a.edits(table_va):
        v6a.poke(content, va, was, new, why)
    for va, was, kind, label in v6a.hooks(table_va, offsets):
        op = b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9"
        new = op + v6a.be32(offsets[label])
        new += b"\x4e\x71" * ((len(was) - len(new)) // 2)
        v6a.poke(content, va, was, new, f"{kind} -> {label}")

    for patch in extra:
        patch(content, code)

    print("part 4 -- write")
    out.mkdir(parents=True, exist_ok=True)
    (out / "section_3_MAIN_OS.bin").write_bytes(bytes(content))
    wanted = ("lfo4_", "ext_")
    symbols = {k: v for k, v in code.symbols.items() if k.startswith(wanted)}
    symbols["lfo4_rows"] = table_va
    symbols["dnfw_boot"] = loader.build()["dnfw_boot"]
    (out / "symbols.json").write_text(
        json.dumps({k: f"0x{v:08x}" for k, v in sorted(symbols.items())}, indent=1) + "\n", newline="\n")
    # Which of those are code. The boot gate reports what never ran, and a
    # counter in that list is noise: `lfo4-table`'s first gate named 24
    # symbols as unexercised routines and 15 of them were variables, which
    # buries the ones that matter.
    routines = {k: v for k, v in code.routines().items() if k.startswith(wanted)}
    routines["dnfw_boot"] = symbols["dnfw_boot"]
    (out / "routines.json").write_text(
        json.dumps({k: f"0x{v:08x}" for k, v in sorted(routines.items())}, indent=1) + "\n", newline="\n")
    syx.parent.mkdir(parents=True, exist_ok=True)
    syx.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, bytes(content))}))
    print(f"  {syx.name}, MAIN OS {len(content):,} B (+{len(content) - len(stock)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

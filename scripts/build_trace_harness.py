"""Eleven reachability answers from one flash.

**Why this and not another LFO4 build.** Four LFO4 builds were flashed this week
and every one was silent. They were investigated as four problems -- a wrong
destination, a neutral value in the wrong units, a cave that does not execute, a
bad anchor -- and they had one cause: **each aimed at a function that was not on
the path being observed**. `0x4004ca80` turned out to be a lambda in a vtable
slot with no direct callers. `parameter_value_getter` turned out not to draw
parameters, which is only knowable from the device.

Static analysis had already been asked and had given its answer. The missing
instrument was a way to ask the **running firmware** which functions it reaches,
and `docs/flashing.md` 2026-09-13 supplied it: a cave executed and wrote
`CAVE RAN!!!` where a human could read it.

So instead of one more guess costing one more flash, this spends a single flash
on eleven measured answers.

**The board.** `PERSONALIZE` in SETTINGS -- eleven characters, two button
presses away, and confirmed visible on this instrument twice (Gate E, and
`DNFW ALIVE!` on 2026-09-11). It ships as `...........` and each probe stamps
its own letter in its own column when its function executes. The idle row is a
data edit in the image, so it appears whether or not any code runs: **a blank
row is a result, not an ambiguity.**

**What each probe is asked.** The eleven are the functions the LFO4 slot design
rests on (`docs/lfo4-slot-plan.md`): the generic value-array sites, the mirror
path, the reverse copy, and the two addresses this project has already been
wrong about. Reading the row after ordinary use -- load a sound, turn an
encoder, save -- says which of them the firmware actually runs, and when.

Three of the columns are worth the flash on their own:

* `M` -- `0x4004ca80`, the withdrawn `updateMirror` lambda. A mark proves it
  runs after all and the vtable reading was too strong; a blank confirms it.
* `G` -- `parameter_value_getter`. We know forcing its return changes nothing on
  screen. We do **not** know whether it runs at all, and those two cases point
  the search in opposite directions.
* `P` -- `param_index_in_page`, 34 direct callers and the shared upstream of six
  of the generic sites. If this is blank the trace itself is broken, so it
  doubles as the harness's own control.

**Safety.** Eleven 6-to-12-byte hooks and eleven caves, every one asserted
against stock bytes before writing, refused if anything branches into the bytes
being replaced, and each payload restores every register *and the condition
codes* before the displaced instructions replay (`patch/trace.py`). The only
visible effect is the SETTINGS string. Nothing is written to the +Drive.
Reflashing stock 1.11 reverts it.

No firmware bytes live in this repository. Output is a .syx under
00_Resources/02_Builds/ (gitignored).
"""

import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.image import objdump
from dnfw.image.coldfire import LoadedImage
from dnfw.image.functions import build as build_callgraph
from dnfw.patch.assemble import available
from dnfw.patch.cave import apply, displaced_stock
from dnfw.patch.trace import Board, Probe, find_board, hooks, lay_out, legend

MAIN_OS = 3
BASE = 0x40000400

BOARD_TEXT = b"PERSONALIZE\x00"

# One free run, 1,047 bytes, from `dnfw cave scan` -- inside the constants-region
# padding that docs/memory-map.md blesses and that the boot proof executed from.
CAVE_RUN = 0x40287EF6

# The eleven, in the order docs/lfo4-slot-plan.md raises them. Sites are function
# entries rather than the value-array instructions themselves: an entry is
# straight-line, is already a call target, and answers "was this function
# reached", which is the question. Entries were derived from the direct-call
# scan in image/functions.py, not read off a disassembly by eye.
PROBES = (
    Probe(id="param_index_in_page", site=0x400DBCC4, mark="P", column=0,
          note="34 callers; shared upstream of six generic sites. Also the harness control."),
    Probe(id="parameter_value_getter", site=0x4006408A, mark="G", column=1,
          note="mis-anchored: forcing its return changes nothing. Does it run at all?"),
    Probe(id="updateMirror_lambda", site=0x4004CA80, mark="M", column=2,
          note="the withdrawn hook: vtable slot, no direct callers. Blank confirms it."),
    Probe(id="mirror_enclosing", site=0x4004C5C6, mark="S", column=3,
          note="the directly-called function the two mirror sites sit inside"),
    Probe(id="reverse_copy", site=0x400DD1EA, mark="R", column=4,
          note="engine -> control copy, indexed through the inverse map"),
    Probe(id="fill_loop", site=0x40043F5E, mark="F", column=5,
          note="the 0..100 fill loop -- generic by construction"),
    Probe(id="bulk_copy_a", site=0x4004C178, mark="B", column=6,
          note="bulk value-array copy via 0x400dbc88"),
    Probe(id="bulk_copy_b", site=0x4004C23A, mark="C", column=7,
          note="the second bulk copy"),
    Probe(id="pip_consumer_a", site=0x40036274, mark="A", column=8,
          note="indexes the value array from param_index_in_page"),
    Probe(id="pip_consumer_b", site=0x40036BAC, mark="D", column=9,
          note="two generic sites inside it"),
    Probe(id="pip_consumer_c", site=0x40037942, mark="E", column=10,
          note="two generic sites inside it"),
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/trace-harness_DN2_1.11.syx")


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler -- see docs/code-caves.md")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    original = section.unpack()
    image = LoadedImage(dest=section.dest, content=original)

    board = find_board(original, BASE, BOARD_TEXT)
    print(f"board: 0x{board.address:08x}, {board.width} columns "
          f"({BOARD_TEXT[:-1].decode()!r} -> {board.idle[:-1].decode()!r})\n")

    graph = build_callgraph(image)
    stocks = _read_stock(image, graph)

    caves = lay_out(CAVE_RUN, len(PROBES))
    built = hooks(image, board, PROBES, caves, stocks)

    content = original
    for hook in built:
        content = apply(LoadedImage(dest=section.dest, content=content), hook)

    # The idle row ships in the image, so the board is visible even if no probe
    # ever executes. Written last, and only over the bytes the board occupies.
    at = board.address - BASE
    edited = bytearray(content)
    edited[at:at + len(board.idle)] = board.idle
    content = bytes(edited)

    _verify(original, content, built, board)

    syx = fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, content)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  content sha256 {hashlib.sha256(syx).hexdigest()[:16]}")

    print("\nRead SETTINGS. Every column is one function; a letter means it ran.\n")
    print(legend(PROBES, board.width))
    print("\n  ...........  no probe ran -- the harness itself is at fault, since P")
    print("               has 34 callers and cannot be missed by a working trace")
    print("  marks appear as the instrument is used: read the row, do one thing")
    print("  (load a sound, turn an encoder, save), read it again.")
    return 0


def _read_stock(image: LoadedImage, graph) -> dict[str, bytes]:
    """The whole-instruction bytes each hook displaces, with its caller count.

    The caller count is printed rather than enforced: a probe on an
    indirect-only address is exactly what column `M` is for. What would be
    wrong is not *knowing*, which is how four flashes were spent.
    """
    stocks: dict[str, bytes] = {}
    print(f"{'probe':<24} {'site':<12} {'callers':>7}  displaced")
    for probe in PROBES:
        window = image.read(probe.site, min(32, image.end - probe.site))
        instructions = objdump.disassemble(window, probe.site)
        stock = displaced_stock([i.data for i in instructions])
        stocks[probe.id] = stock
        callers = len(graph.callers_of(probe.site))
        flag = "  <- indirect only" if callers == 0 else ""
        print(f"{probe.id:<24} 0x{probe.site:08x} {callers:>7}  "
              f"{stock.hex(' '):<36}{flag}")
    return stocks


def _verify(before: bytes, after: bytes, built, board: Board) -> None:
    """Every changed byte must belong to a hook, a cave, or the board."""
    if len(before) != len(after):
        raise SystemExit("length changed -- this build must not resize the section")
    allowed: set[int] = set()
    for hook in built:
        site = hook.site - BASE
        allowed |= set(range(site, site + len(hook.stock)))
        cave = hook.cave.address - BASE
        allowed |= set(range(cave, cave + hook.cave.capacity))
    at = board.address - BASE
    allowed |= set(range(at, at + len(board.idle)))

    diffs = [i for i in range(len(before)) if before[i] != after[i]]
    stray = [i for i in diffs if i not in allowed]
    if stray:
        raise SystemExit(f"{len(stray)} bytes changed outside the hooks, caves and board")
    print(f"\n  verified: {len(diffs)} bytes changed across {len(built)} hooks, "
          f"{len(built)} caves and the board; 0 elsewhere")


if __name__ == "__main__":
    raise SystemExit(main())

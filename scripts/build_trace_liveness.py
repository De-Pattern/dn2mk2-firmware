"""Three hooks, one question: are the nine blanks "never called" or "never seen"?

**What the eleven-probe harness returned.** Flashed 2026-09-13. Two columns
marked -- `R` (`reverse_copy`) and `E` (the view function at `0x40037942`) -- and
**nine stayed blank no matter what the instrument did**: parameter pages, encoder
moves, a sound saved to slot 245. Rebooting and mangling *before* opening
SETTINGS for the first time changed nothing, which ruled out the page caching
the string.

**Why that is strange rather than simply negative.** `param_index_in_page`
(column `P`) was verified, after the fact, to have **34 direct callers at real
instruction boundaries** -- `jsr 0x400dbcc4`, decoded linearly from each
enclosing entry, not inferred from a byte-stride scan. Four of them are in
functions this same trace shows running. Its hook was disassembled out of the
built image and is a correct `jmp` into a correct cave. Every probe shares one
payload, and that payload demonstrably works, because `R` and `E` use it.

So exactly one of these is true, and they point in opposite directions:

  A. the nine functions genuinely never run -- and `param_index_in_page`, with
     34 real callers in parameter-page code, is not on the DN2's parameter path
     at all. That would be a large finding about where the UI actually lives.

  B. **writes made after boot are never displayed.** `R` and `E` would then be
     boot-time only, and the board shows a picture frozen early -- in which case
     the nine blanks mean nothing whatever, and neither does anything else this
     harness has reported.

A stamp cannot tell them apart. "Ran once at boot" and "runs constantly" leave
the same mark, and that is the flaw in the first design.

**A counter can.** This build keeps three hooks and gives the two that are known
to fire a second column each, which they *advance* -- `0`..`7`, cycling -- every
time they run:

    col 0   advanced by reverse_copy       (R, proven to fire)
    col 1   advanced by the view function  (E, proven to fire)
    col 2   stamped by param_index_in_page (P, the anomaly)

Then use the instrument and read SETTINGS again:

    the digits MOVE   -> those functions run continuously and late writes DO
                         reach the screen. World A: the nine are genuinely not
                         called, and the search moves to where the UI really is.
    the digits FREEZE -> they ran at boot and nothing since is displayed.
                         World B: the readout is broken, every blank column is
                         uninterpretable, and the harness needs a live surface.

Three hooks instead of eleven, because every removed hook is a removed variable
and the first build had ten more than this question needs.

**Safety.** Three hooks, three caves, asserted against stock bytes, refused if
anything branches into the displaced bytes, each payload restoring every
register it touches and the condition codes before the stock replays. Only the
SETTINGS string changes. Nothing is written to the +Drive. Reflashing stock 1.11
reverts it.

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
from dnfw.patch.assemble import available
from dnfw.patch.cave import apply, displaced_stock
from dnfw.patch.trace import Board, Probe, find_board, hooks, lay_out, legend

MAIN_OS = 3
BASE = 0x40000400
BOARD_TEXT = b"PERSONALIZE\x00"
CAVE_RUN = 0x40287EF6
SLOT = 128  # a counter payload is longer than a stamp; 128 leaves plenty of room

PROBES = (
    Probe(id="reverse_copy", site=0x400DD1EA, mark="R", column=4, counter=0,
          note="FIRED in the 11-probe build. Column 0 advances every time it runs."),
    Probe(id="view_fn", site=0x40037942, mark="E", column=10, counter=1,
          note="FIRED in the 11-probe build. Column 1 advances every time it runs."),
    Probe(id="param_index_in_page", site=0x400DBCC4, mark="P", column=2,
          note="34 verified direct callers, four of them in functions this trace shows running."),
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/trace-liveness_DN2_1.11.syx")


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler -- see docs/code-caves.md")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    original = section.unpack()
    image = LoadedImage(dest=section.dest, content=original)

    board = find_board(original, BASE, BOARD_TEXT)
    print(f"board: 0x{board.address:08x}, {board.width} columns\n")

    stocks = {}
    for probe in PROBES:
        window = image.read(probe.site, min(32, image.end - probe.site))
        stock = displaced_stock([i.data for i in objdump.disassemble(window, probe.site)])
        stocks[probe.id] = stock
        kind = f"stamp {probe.mark} col {probe.column}"
        if probe.counter is not None:
            kind += f" + advance col {probe.counter}"
        print(f"  {probe.id:<22} 0x{probe.site:08x}  {stock.hex(' '):<34} {kind}")

    caves = lay_out(CAVE_RUN, len(PROBES), slot=SLOT)
    built = hooks(image, board, PROBES, caves, stocks)

    content = original
    for hook in built:
        content = apply(LoadedImage(dest=section.dest, content=content), hook)

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

    print("\nSETTINGS, after booting and then USING the instrument:\n")
    print(legend(PROBES, board.width))
    print("\n  columns 0 and 1 are DIGITS that advance 0..7 each time their function runs")
    print("    digits MOVE   -> late writes reach the screen; the nine blanks are real,")
    print("                     and param_index_in_page is genuinely not on the UI path")
    print("    digits FREEZE -> only boot-time writes are displayed; every blank column")
    print("                     in the 11-probe build is uninterpretable and must be redone")
    return 0


def _verify(before: bytes, after: bytes, built, board: Board) -> None:
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

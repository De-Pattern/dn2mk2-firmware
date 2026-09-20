"""LFO4 step 3: the fourth LFO's parameters become each track's own.

    python scripts/build_lfo4_tick7.py

`docs/lfo4-build-plan.md` §8, step 3. v6a (`scripts/build_lfo4_tick.py`) proved
the engine runs a fourth LFO, with **one** 16-byte parameter block shared by all
sixteen tracks. This replaces that block with a **sixteen-row table** and makes
both evaluators index their own track's row, which is the last engine-side
question: can each track have its own LFO4?

It asks that and nothing else. The table is written into the image with
distinct values for two tracks and an inert `DEST = 0` for the rest, so the
answer is audible without any of the table, the page or storage being wired up:

| track | what it should do |
|---|---|
| 1 | a fast filter sweep |
| 2 | the same sweep, much slower |
| 3-16 | nothing -- `DEST = 0` is the LFOs' no-destination sink |

Where the index comes from, read out of the two evaluators (both checked
against the stock bytes by the `poke` guards this reuses):

- **evaluator A** `0x40137726` zeroes `%a5` at `0x40137758` and steps it once
  per track, using it as a shift count at `0x40137770`-`0x4013777e`. So at the
  `a4_top` hook `%a5` **is** the track index.
- **evaluator B** `0x401373dc` takes it as an argument -- `movel %sp@(68),%d0`
  -- and `%d0` is still live at the `b_top` hook, read but never written
  between (`0x4013740c`, `0x40137410`).

Everything else is v6a's, imported rather than copied: the state relocation, the
loop-count edits, the stride arithmetic, the flag sweep and five of the seven
stubs. Only the two that load the parameter block change, and the substitution
is guarded -- if v6a's text moves, this fails loudly instead of patching the
wrong stub.
"""

from __future__ import annotations

import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_lfo4_tick as v6a  # noqa: E402

TRACKS = 16
ROW = 16                                   # eight u16 slots, mirror order

# One row per track: SPD MULT FADE DEST WAVE SPH MODE DEP.
#
# **A demo has to be obvious in a bar.** The build that passed on hardware on
# 2026-09-20 used `MULT 0x0100` -- multiplier index 1, the slowest there is --
# with `SPD 0x7000`, and the owner had to listen through about **fourteen bars**
# to hear one bar of movement: "I almost wrote that it didn't work."
#
# That is a defect in the *instrument*, not in the firmware: a demo whose effect
# is indistinguishable from a failure cannot tell the two apart, and the tester
# pays for it. So a hard-coded modulation now runs fast enough to be heard
# within a bar, and the two rows still differ audibly from each other so the
# per-track claim is still what is being shown.
INERT = (0x7000, 0x0800, 0x4000, 0, 0x0100, 0x0000, 0x0000, 0x7FFE)
FAST = (0x7000, 0x0800, 0x4000, 76 << 8, 0x0100, 0x0000, 0x0000, 0x7FFE)
SLOW = (0x2000, 0x0800, 0x4000, 76 << 8, 0x0100, 0x0000, 0x0000, 0x7FFE)
ROWS = [FAST, SLOW] + [INERT] * (TRACKS - 2)

OUT = pathlib.Path("00_Resources/02_Builds/lfo4-tick7_DN2_1.11.syx")
# The patched section on its own, for `scripts/emu_lfo4_tick.py`: the emulator
# runs under digikit's venv, which has no dnfw to unpack a .syx with.
SECTION_OUT = pathlib.Path("out/lfo4-tick7/section_3_MAIN_OS.bin")

A_INDEX = """    move.l  %d0,-(%sp)
    move.l  %a5,%d0             | evaluator A's track index
    lsl.l   #4,%d0
    lea     {at:#010x},%a4
    adda.l  %d0,%a4
    move.l  %sp@+,%d0"""

B_INDEX = """    move.l  %d0,-(%sp)          | evaluator B's track index is already in %d0
    lsl.l   #4,%d0
    lea     {at:#010x},%a4
    adda.l  %d0,%a4
    move.l  %sp@+,%d0"""


def table_bytes() -> bytes:
    return b"".join(struct.pack(">8H", *row) for row in ROWS)


def cave_source(table_va: int) -> str:
    """v6a's stubs, with the two parameter loads made per-track.

    Each is one `lea` of a known address, so the line to replace is rendered
    rather than guessed, and a count of exactly one is required -- if v6a's
    text moves, this stops instead of patching the wrong stub.
    """
    source = v6a.cave_source(table_va)
    for bias, index in ((68, A_INDEX), (34, B_INDEX)):
        line = f"    lea     {table_va - bias:#010x},%a4"
        if source.count(line) != 1:
            raise SystemExit(f"expected exactly one {line.strip()!r} in v6a's stubs, "
                             f"found {source.count(line)}")
        source = source.replace(line, index.format(at=table_va - bias))
    return source


def main() -> int:
    if not v6a.available():
        raise SystemExit("no m68k assembler found -- patch/assemble.py needs "
                         "m68k-linux-gnu-as (WSL is fine)")

    firmware = v6a.load(v6a.read_image(v6a.STOCK))
    section = firmware.container.find(v6a.MAIN_OS)
    content = bytearray(section.unpack())

    table = table_bytes()
    table_va = v6a.CAVE
    stub_va = v6a.CAVE + len(table)
    v6a.require_zero(content, v6a.CAVE, v6a.CAVE_CAP, "cave region")

    print(f"part 1 -- the per-track table, {TRACKS} rows x {ROW} bytes")
    for track, row in enumerate(ROWS[:3], start=1):
        print(f"  track {track:<2} SPD {row[0]:#06x}  DEST {row[3] >> 8:<3} "
              f"DEP {row[7]:#06x}" + ("   (and tracks 3-16 alike)" if track == 3 else ""))
    content[table_va - v6a.BASE:table_va - v6a.BASE + len(table)] = table
    print(f"  written at {table_va:#010x}, {len(table)} bytes")

    print("part 2 -- the stubs")
    payload, offsets = v6a.assemble_stubs(cave_source(table_va), stub_va)
    if len(table) + len(payload) > v6a.CAVE_CAP:
        raise SystemExit(f"cave overflows: {len(table) + len(payload)} > {v6a.CAVE_CAP}")
    content[stub_va - v6a.BASE:stub_va - v6a.BASE + len(payload)] = payload
    print(f"  {len(payload)} bytes at {stub_va:#010x}")

    print("part 3 -- the in-place edits (v6a's, unchanged)")
    for va, stock, new, why in v6a.edits(table_va):
        v6a.poke(content, va, stock, new, why)

    print("part 4 -- the hooks (v6a's, unchanged)")
    for va, stock, kind, label in v6a.hooks(table_va, offsets):
        target = offsets[label]
        op = b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9"
        new = op + v6a.be32(target)
        new = new + b"\x4e\x71" * ((len(stock) - len(new)) // 2)
        if len(new) != len(stock):
            raise SystemExit(f"hook at {va:#010x} cannot be padded to {len(stock)}")
        v6a.poke(content, va, stock, new, f"{kind} -> {label} @ {target:#010x}")

    print("part 5 -- repack")
    SECTION_OUT.parent.mkdir(parents=True, exist_ok=True)
    SECTION_OUT.write_bytes(bytes(content))
    print(f"  wrote {SECTION_OUT} ({len(content):,} bytes)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(v6a.fwbuild.build(
        firmware, {v6a.MAIN_OS: v6a.compress(section.id, section.dest, bytes(content))}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""v6a: a fourth LFO that actually ticks, with fixed parameters.

**The question this build asks, and it is the one nothing has answered yet.**
v4 put a fourth `[MOD]` page on the instrument and v5 gave that page LFO4's own
parameter records -- but no build has ever run a fourth LFO *generator*. The
engine side has been reasoned about for a week and measured never. So this build
drops the UI entirely and asks the engine one question:

    if the LFO loop is told to run four LFOs instead of three,
    does the fourth one generate and apply modulation?

LFO4's eight parameters are **hard-coded in the image**, not editable, not saved,
not read from any preset. That is deliberate: it removes the storage problem, the
slot problem, the serialization problem and the UI problem from the experiment,
leaving only the engine. If a slow filter sweep appears on every track that no
visible LFO explains, the answer is yes and the rest of LFO4 is plumbing.

## What was read to build this (2026-09-17)

Both LFO evaluators were disassembled end to end, and they settle the runtime
layout that `docs/lfo4-slot-plan.md` spent days circling:

- The engine keeps a **per-track parameter mirror: 101 u16 slots, 202 bytes,
  sixteen of them contiguous.** `sp@(52)` in the frame walks it at stride 202.
- **An LFO's eight parameters are just slots `8*lfo + 1 .. 8*lfo + 8` of that
  mirror**, in the order `SPD MULT FADE DEST WAVE SPH MODE DEP` -- the same order
  as the sound `ParameterSet` table. LFO1 is slots 1-8, LFO2 9-16, LFO3 17-24.
- Each slot is `display << 8`. The evaluators read `MULT`, `DEST`, `WAVE` and
  `MODE` with `mvs.b` (the high byte) and `SPD`, `FADE`, `SPH`, `DEP` as words.
- **`DEST` is a slot index into that same mirror, bounded 0..100**, and the
  modulated value is written back to `mirror + 2*DEST`, clamped to 0..32512.
  `DEST = 0` is the no-destination sink, which is why slot 0 is the one hole in
  the sound table.
- **`DEP` is centred on `0x4000`**: the code computes `(DEP - 16384) * 2` before
  multiplying. Zero depth is `0x4000`, not `0`.

Both loops count **down** from the top LFO, walking `%a4` back 16 bytes and the
state pointers back 40 bytes per iteration, sixteen tracks deep.

## Why LFO4 cannot simply be slots 25-32

It is the next sixteen bytes of the mirror, and they are **machine parameters**.
`scripts/dump_param_sets.py` says the sound table's only free slots are 0 and
100. So the fourth LFO's parameters are pointed at a **16-byte block in the
image** instead, by redirecting `%a4` for the fourth iteration only and restoring
it at the end of that iteration. The apply path is untouched and still writes
into the real per-track mirror, so the modulation lands where it should.

## The state arrays have to move, and that is most of the edit count

Three 1,920-byte arrays (16 tracks x 3 LFOs x 40) sit wall to wall at
`0x4463ed18`, `0x4463f498`, `0x4463fc18`. Four LFOs need 2,560 each, so all three
relocate into the unclaimed 25.3 MB above BSS end `0x466b74d0`
(`docs/memory-map.md`). Every site that names one, sizes one, strides one or
initialises one is listed in `EDITS` below and asserted against its stock bytes.

## How to read the result

| observation | means |
|---|---|
| boots, no wobble anywhere | the fourth iteration runs but produces nothing -- read the state init |
| boots, slow filter sweep on every track | **a fourth LFO generates and applies.** The engine is not the obstacle |
| does not boot | the relocation is wrong; the state arrays are the first suspect |
| LFO1-3 misbehave | a stride edit was missed; every 120 and 1920 in both evaluators |

The sweep should be audible on any preset with a filter, on all sixteen tracks,
and should not stop when LFO1-3 are set to no destination -- that is the control.

**Not a shipping build.** LFO4 is fixed, global and invisible. See
`docs/lfo4-build-plan.md` for what v6b adds.
"""

from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400

# --- where the relocated state lives ---------------------------------------
# Unclaimed SDRAM above BSS end 0x466b74d0, below the 0x48000000 top.
# 16 tracks x 4 LFOs x 40 bytes = 2,560 each.  Page-spaced so a stray overrun
# lands in nothing rather than in a neighbour.
LIVE = 0x46700000
SECOND = 0x46701000
BACKUP = 0x46702000
STATE_LEN = 2560
STATE_STRIDE = 160          # per track: 4 LFOs x 40
STOCK_LEN = 1920
STOCK_STRIDE = 120

STOCK_LIVE = 0x4463FC18
STOCK_SECOND = 0x4463F498
STOCK_BACKUP = 0x4463ED18

# --- the cave ---------------------------------------------------------------
# 0x402dfa1c is one of the three 896-byte runs that pass both of
# `dnfw cave scan`'s checks (docs/code-caves.md).  Untouched by v4 and v5, which
# used 0x402cf52c and 0x402d0664.
CAVE = 0x402DFA1C
CAVE_CAP = 896

# --- LFO4's hard-coded parameters -------------------------------------------
# Eight u16 slots in mirror order, each `display << 8`.  Values are LFO1's own
# defaults except DEST and DEP, which are what makes the experiment observable.
LFO4_SPD = 0x7000           # LFO1's default rate
LFO4_MULT = 0x0100          # x1, LFO1's default
LFO4_FADE = 0x4000          # centred: no fade
LFO4_DEST = 76 << 8         # Filter BASE -- sound slot 76, audible on any preset
LFO4_WAVE = 0x0100          # LFO1's default waveform
LFO4_SPH = 0x0000
LFO4_MODE = 0x0000          # free-running, so it sweeps with no notes played
LFO4_DEP = 0x7FFE           # (0x7ffe - 0x4000) * 2 -- near-full positive depth

PARAMS = struct.pack(
    ">8H", LFO4_SPD, LFO4_MULT, LFO4_FADE, LFO4_DEST,
    LFO4_WAVE, LFO4_SPH, LFO4_MODE, LFO4_DEP,
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo4-tick6a_DN2_1.11.syx")


def be32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


# Every in-place edit, as (address, stock bytes, new bytes, why).  Asserted
# before it is applied: a stock mismatch means the image is not 1.11 and the
# build stops rather than writing into whatever is actually there.
def edits(params_va: int) -> list[tuple[int, bytes, bytes, str]]:
    out: list[tuple[int, bytes, bytes, str]] = []
    add = lambda *a: out.append(a)

    # -- evaluator A, 0x40137726 ------------------------------------------
    add(0x4013773C, b"\x48\x78\x07\x80", b"\x48\x78\x0a\x00",
        "A: backup copy length 1920 -> 2560")
    add(0x40137740, b"\x48\x79" + be32(STOCK_LIVE), b"\x48\x79" + be32(LIVE),
        "A: copy source, live state base")
    add(0x40137746, b"\x48\x79" + be32(STOCK_BACKUP), b"\x48\x79" + be32(BACKUP),
        "A: copy destination, backup base")
    add(0x4013775E, b"\x43\xf9" + be32(STOCK_LIVE), b"\x43\xf9" + be32(LIVE + 40),
        "A: %a1 -> live state, +40 so %a2@(80) reaches LFO index 3")
    add(0x40137784, b"\x72\x02", b"\x72\x03",
        "A: inner loop counter 2 -> 3, four LFOs")
    add(0x401377E8, b"\xe7\x8a", b"\xeb\x8a",
        "A: restore path, d2 = idx<<3 -> idx<<5")
    add(0x401377F0, b"\x90\x82", b"\xd0\x82",
        "A: restore path, 128-8=120 -> 128+32=160")
    add(0x401377F2, b"\x06\x80" + be32(STOCK_LIVE), b"\x06\x80" + be32(LIVE),
        "A: restore path, live base")
    add(0x40137800, b"\xe7\x8a", b"\xeb\x8a",
        "A: backup path, d2 = idx<<3 -> idx<<5")
    add(0x40137808, b"\x90\x82", b"\xd0\x82",
        "A: backup path, stride 120 -> 160")
    add(0x4013780C, b"\x06\x80" + be32(STOCK_BACKUP), b"\x06\x80" + be32(BACKUP),
        "A: backup path, backup base")

    # -- evaluator B, 0x401373dc ------------------------------------------
    add(0x401373FC, b"\xe7\x8a", b"\xeb\x8a",
        "B: d2 = track<<3 -> track<<5")
    add(0x40137418, b"\x92\x82", b"\xd2\x82",
        "B: track stride 120 -> 160")
    add(0x4013741C, b"\x74\x02", b"\x74\x03",
        "B: inner loop counter 2 -> 3")
    add(0x4013741E, b"\xdb\xfc" + be32(STOCK_SECOND + 80),
        b"\xdb\xfc" + be32(SECOND + 120),
        "B: %a5 -> LFO index 3's state, not index 2's")
    add(0x40137426, b"\xd5\xfc" + be32(STOCK_SECOND),
        b"\xd5\xfc" + be32(SECOND + 40),
        "B: %a2 -> state +40, so %a2@(80) reaches LFO index 3")

    # -- the initialisers, 0x401372f4 and 0x40137348 -----------------------
    add(0x401372FA, b"\x72\x03", b"\x72\x04",
        "init A: 3 LFO records per track -> 4")
    add(0x401372FC, b"\xd1\xfc" + be32(STOCK_LIVE + 37),
        b"\xd1\xfc" + be32(LIVE + 37),
        "init A: live base")
    add(0x4013732E, b"\x06\x80" + be32(STOCK_STRIDE), b"\x06\x80" + be32(STATE_STRIDE),
        "init A: track stride")
    add(0x40137334, b"\x0c\x80" + be32(STOCK_LEN), b"\x0c\x80" + be32(STATE_LEN),
        "init A: array length")
    add(0x4013734E, b"\x72\x03", b"\x72\x04",
        "init B: 3 LFO records per track -> 4")
    add(0x40137350, b"\xd1\xfc" + be32(STOCK_SECOND + 37),
        b"\xd1\xfc" + be32(SECOND + 37),
        "init B: second-state base")
    add(0x40137382, b"\x06\x80" + be32(STOCK_STRIDE), b"\x06\x80" + be32(STATE_STRIDE),
        "init B: track stride")
    add(0x40137388, b"\x0c\x80" + be32(STOCK_LEN), b"\x0c\x80" + be32(STATE_LEN),
        "init B: array length")

    # -- the two base accessors -------------------------------------------
    add(0x40137340, b"\x20\x3c" + be32(STOCK_LIVE), b"\x20\x3c" + be32(LIVE),
        "accessor: returns the live state base")
    add(0x40137394, b"\x20\x3c" + be32(STOCK_SECOND), b"\x20\x3c" + be32(SECOND),
        "accessor: returns the second-state base")

    return out


# Each hook replaces exactly `len(stock)` bytes; the payload is `jsr cave` or
# `jmp cave` padded with nops so nothing downstream shifts.
def hooks(params_va: int, cave_of: dict[str, int]) -> list[tuple[int, bytes, str, str]]:
    return [
        (0x40137798,
         b"\x49\xec\xff\xde\x47\xeb\x00\x74",
         "jsr", "a4_top",
         ),
        (0x40137AF0,
         b"\x49\xec\xff\xf0\xb0\xaf\x00\x30",
         "jsr", "a4_bottom",
         ),
        (0x40137AFC,
         b"\x22\x3c\x00\x00\x00\xca\x7e\x78\x24\x3c\x00\x00\x00\x99"
         b"\x52\x8d\xd3\xaf\x00\x34\xd5\xaf\x00\x3c\xdf\xaf\x00\x38",
         "jsr", "outer",
         ),
        (0x401373B8,
         b"\x41\xf9" + be32(STOCK_SECOND + 38),
         "jmp", "flags",
         ),
        (0x401372F4,
         b"\x2f\x02\x42\x80\x20\x40",
         "jmp", "zero_backup",
         ),
        (0x4013742C,
         b"\x47\xed\x00\x24\x58\x8d\x2f\x42\x00\x30\x2f\x48\x00\x34",
         "jsr", "b_top",
         ),
        (0x40137702,
         b"\x49\xec\xff\xf0\x70\xff",
         "jsr", "b_bottom",
         ),
    ]


def cave_source(params_va: int) -> str:
    """The seven stubs, in one assembly unit so labels resolve locally."""
    return f"""
    .text

| ---- evaluator A: %a4 for the fourth iteration -------------------------
| Stock did `lea %a4@(-34),%a4` (mirror base) then `lea %a3@(116),%a3`.
| The loop body always reads %a4@(68..83) and walks %a4 back 16 bytes at the
| end, so the FIRST iteration -- now the fourth LFO -- wants %a4 + 68 to be our
| block, whatever the counter started at.
a4_top:
    lea     {params_va - 68:#010x},%a4
    lea     %a3@(116),%a3
    rts

| ---- evaluator A: %a4 at the end of each iteration ---------------------
| After the counter is decremented, a next-counter of 2 means the fourth
| iteration has just finished, so %a4 goes back to the stock mirror base.
| Ends with the compare the stock code did, because the caller branches on it.
a4_bottom:
    move.l  %sp@(52),%d1
    cmpi.l  #2,%d1
    bne.s   1f
    movea.l %sp@(56),%a4
    lea     %a4@(-34),%a4
    bra.s   2f
1:  lea     %a4@(-16),%a4
2:  cmp.l   %sp@(52),%d0
    rts

| ---- evaluator A: the per-track advance --------------------------------
| Stock loaded 202 / 120 / 153 into d1/d7/d2 and added them to three frame
| slots.  Only the state stride changes, but 160 will not fit a moveq, so the
| whole block moves here.
outer:
    move.l  #202,%d1
    add.l   %d1,%sp@(56)
    move.l  #153,%d1
    add.l   %d1,%sp@(64)
    move.l  #{STATE_STRIDE},%d1
    add.l   %d1,%sp@(60)
    addq.l  #1,%a5
    rts

| ---- the per-LFO flag sweep --------------------------------------------
| Stock walked the second state array in 120-byte steps setting a byte in each
| of three records.  Four records need a fourth store, which does not fit in
| place, so the routine is rewritten whole.
flags:
    lea     {SECOND + 38:#010x},%a0
    moveq   #1,%d0
1:  cmpa.l  #{SECOND + 38 + STATE_LEN:#010x},%a0
    beq.s   2f
    move.b  %d0,%a0@
    move.b  %d0,%a0@(40)
    move.b  %d0,%a0@(80)
    move.b  %d0,%a0@(120)
    lea     %a0@({STATE_STRIDE}),%a0
    bra.s   1b
2:  rts

| ---- zero the backup array at boot -------------------------------------
| The relocated arrays sit above the BSS clear's bound, so nothing zeroes them.
| The two initialisers cover live and second; backup is only ever a copy target,
| and is read before it is written if the first tick's flag is clear.
zero_backup:
    lea     {BACKUP:#010x},%a0
    lea     {BACKUP + STATE_LEN:#010x},%a1
1:  clr.l   %a0@+
    cmpa.l  %a1,%a0
    bne.s   1b
    move.l  %d2,%sp@-
    clr.l   %d0
    movea.l %d0,%a0
    jmp     0x401372fa

| ---- evaluator B: %a4 for the fourth iteration -------------------------
| Here the body reads %a4@(34..49), again with the decrement at the end, so the
| first iteration wants %a4 + 34 to be our block.  The stock four instructions
| are replayed.
| Frame slots are +4 from the stock displacements, because the hook is a jsr and
| the return address is on the stack.
b_top:
    lea     %a5@(36),%a3
    addq.l  #4,%a5
    move.l  %d2,%sp@(52)
    move.l  %a0,%sp@(56)
    lea     {params_va - 34:#010x},%a4
    rts

| ---- evaluator B: %a4 at the end of each iteration ---------------------
| %sp@(56) holds the real %a4, saved by the stock prologue.  Ends by reloading
| the -1 the stock `moveq` provided for the loop compare.
b_bottom:
    move.l  %sp@(52),%d1
    cmpi.l  #2,%d1
    bne.s   1f
    movea.l %sp@(60),%a4
    bra.s   2f
1:  lea     %a4@(-16),%a4
2:  moveq   #-1,%d0
    rts
"""


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found -- patch/assemble.py needs "
                         "m68k-linux-gnu-as (WSL is fine)")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    # The parameter block goes at the top of the cave; the stubs follow it, so
    # its address is known before anything is assembled.
    params_va = CAVE
    stub_va = CAVE + len(PARAMS)

    require_zero(content, CAVE, CAVE_CAP, "cave region")

    print("part 1 -- LFO4's fixed parameters")
    for label, value in (("SPD", LFO4_SPD), ("MULT", LFO4_MULT), ("FADE", LFO4_FADE),
                         ("DEST", LFO4_DEST), ("WAVE", LFO4_WAVE), ("SPH", LFO4_SPH),
                         ("MODE", LFO4_MODE), ("DEP", LFO4_DEP)):
        print(f"  {label:<5} {value:#06x}  = {value >> 8:>3} coarse")
    content[params_va - BASE:params_va - BASE + len(PARAMS)] = PARAMS
    print(f"  written at {params_va:#010x}, {len(PARAMS)} bytes")

    print("part 2 -- the stubs")
    payload, offsets = assemble_stubs(cave_source(params_va), stub_va)
    if len(PARAMS) + len(payload) > CAVE_CAP:
        raise SystemExit(f"cave overflows: {len(PARAMS) + len(payload)} > {CAVE_CAP}")
    content[stub_va - BASE:stub_va - BASE + len(payload)] = payload
    print(f"  {len(payload)} bytes at {stub_va:#010x}")

    print("part 3 -- the in-place edits")
    for va, stock, new, why in edits(params_va):
        poke(content, va, stock, new, why)

    print("part 4 -- the hooks")
    for va, stock, kind, label in hooks(params_va, offsets):
        target = offsets[label]
        op = b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9"
        new = op + be32(target)
        if len(new) > len(stock):
            raise SystemExit(f"hook at {va:#010x} needs {len(new)} bytes, has {len(stock)}")
        new = new + b"\x4e\x71" * ((len(stock) - len(new)) // 2)
        if len(new) != len(stock):
            raise SystemExit(f"hook at {va:#010x} cannot be padded to {len(stock)}")
        poke(content, va, stock, new, f"{kind} -> {label} @ {target:#010x}")

    print("part 5 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


LABELS = ("a4_top", "a4_bottom", "outer", "flags",
          "zero_backup", "b_top", "b_bottom")


def assemble_stubs(source: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once, and get each stub's address out of the same object.

    The assembler hands back raw bytes with no symbol table, so the source is
    assembled with a trailing table of `.long <label>` and the table is read off
    the end and then cut away.  One assembly, so the addresses cannot drift from
    the bytes they describe.
    """
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(source + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(">%dI" % len(LABELS), blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def require_zero(content: bytearray, va: int, n: int, what: str) -> None:
    block = content[va - BASE:va - BASE + n]
    if any(block):
        raise SystemExit(f"{what} at {va:#010x} is not free: "
                         f"{sum(1 for b in block if b)} non-zero bytes")


def poke(content: bytearray, va: int, stock: bytes, new: bytes, why: str) -> None:
    off = va - BASE
    have = bytes(content[off:off + len(stock)])
    if have != stock:
        raise SystemExit(f"{va:#010x}: expected {stock.hex()}, found {have.hex()} -- "
                         f"not the image this patch was written against ({why})")
    content[off:off + len(new)] = new
    print(f"  {va:#010x}  {stock.hex():<16} -> {new.hex():<16}  {why}")


if __name__ == "__main__":
    raise SystemExit(main())

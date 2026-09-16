"""Three new LFO waveforms: STP, PLS and NOI.

**The idea, from the owner (2026-09-17):** *"That LFO would be great to control
the quantisation levels instead of the phase."* The first `STP` build fixed the
staircase at eight levels because the generator has no access to anything but the
phase. This build gives it one, and the parameter it borrows is `SPH`.

**Why `SPH` is the right one to take.** `Start Phase` sets where a *trigged* LFO
begins. It already exists, it is already per-LFO and per-sound, it is already
saved, and for the shapes here it has nothing useful to do -- a staircase that
starts a step early is the same staircase. So on these three waveforms and only
these three, `SPH` stops meaning start phase and becomes the shape control.
No new slot, no new record, no format change, nothing the sound file has to
carry. Its stock meaning is suppressed for them, so the knob means one thing.

| waveform | `SPH` does | range |
|---|---|---|
| `STP` | **quantisation levels** | 2, 4, 8, 16, 32, 64, 128, 256 |
| `PLS` | **pulse width** | 0.4% to 99.6% duty |
| `NOI` | **noise colour** | white, pink, brown, violet |

and `NOI`'s *rate* stays where it belongs: `SPD` and `MULT`, because it is a
sample-and-hold clocked by the phase rather than a free-running generator.

## The shapes, and where they come from

The owner's other suggestion was to read other instruments' manuals. The ASM
Hydrasynth offers ten LFO shapes -- Sine, Triangle, Saw up, Saw down, Square,
**Pulse 27%**, **Pulse 13%**, S&H, Noise, Random -- plus a 64-step user wave.
The Digitone II already has the first five in spirit and one random flavour.
What it has none of is a **variable** shape: every one of its seven is fixed. So
rather than copy `Pulse 27%` and `Pulse 13%` as two more constants, `PLS` makes
the width continuous and covers both, and `STP` is the 64-step user wave's cheap
cousin -- a stepped shape you dial rather than draw.

ASM's newer **Leviasynth** then confirms the choice from the other direction. Its
LFOs offer *"sine, triangle, multi-directional saw, square, noise, random, step,
and percentage-variable pulse"* -- **step** and **percentage-variable pulse**
named as such, on a 2026 instrument, which is two of the three built here. The
third, **noise**, is the one the Digitone II lacks outright: `RND` holds a single
value for a whole cycle, while `NOI` is a fresh value every tick. Different
sound, different use.

## How a generator gets a second argument

Generators are leaves: phase in `%sp@(4)`, level out in `%d0`. They are reached
through `movea.l %aN@(0,%d3:l:4),%aN` then `jsr %aN@`, at one site per evaluator.

`%d1` is free at both call sites -- every stock generator writes `%d1` before
reading it, and evaluator B saves its own `%d1` to the frame one instruction
earlier -- so the two hooks load `SPH`'s coarse byte into `%d1` on the way past.
Both hooks are `jmp`, not `jsr`, so the stack the generator reads is untouched.

## The three hooks

| at | replaces | does |
|---|---|---|
| `0x401379fa` | evaluator A's `lea <fn table>,%a0` | loads our table **and** `%a4@(78)` into `%d1` |
| `0x4013760c` | evaluator B's frame save + `jsr %a1@` | the same, from `%a4@(44)`, then calls and returns |
| `0x4013788e` | the `SPH` read that sets the start phase | zeroes it when `WAVE >= 7` |

`NOI` uses the same argument for its colour, which was the owner's second
suggestion: *"For the phs control in noise we could use that job to change the
noise type (white/pink...)"*. Four bands of 32, filters built from shifts alone.

The third is what makes `SPH` mean one thing instead of two. Without it, dialling
the step count would also shift where a trigged LFO starts.

## What this supersedes

The first build, `lfo-wave8`, added `STP` fixed at eight levels. This replaces
it: the same waveform at `SPH = 48`, plus seven other step counts and two more
waveforms. `docs/ideas-backlog.md` section 8 carries both.
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

# One of the three 896-byte runs that pass both of `dnfw cave scan`'s checks.
CAVE = 0x402CF52C
CAVE_CAP = 896

STOCK_NAMES = 0x401D3574            # TRI SIN SQR SAW EXP RMP RND
STOCK_TABLES = (0x4020B2EC, 0x4020B308, 0x4020B324, 0x4020B340)
STOCK_ENTRIES = 7
NEW_NAMES = (b"STP\x00", b"PLS\x00", b"NOI\x00")
ENTRIES = STOCK_ENTRIES + len(NEW_NAMES)

# What each of the four value tables gets for the three new indices.  The hold
# value and both start values are zero, as `SAW`'s are; the generator pointers
# are filled in once the stubs are assembled.
TABLE_EXTRAS = {
    0x4020B2EC: [0, 0, 0],          # per-waveform hold value
    0x4020B308: [0, 0, 0],          # start value, positive phase
    0x4020B324: [0, 0, 0],          # start value, negative phase
    0x4020B340: [None, None, None],  # the generator function pointers
}

# Plain repoints: every `lea`/`pea` that names a table and is not itself hooked.
REPOINTS = {
    0x401D3574: ((0x40007688, b"\x48\x79"),),
    0x4020B2EC: ((0x401374DE, b"\x41\xf9"), (0x401378E2, b"\x41\xf9")),
    0x4020B308: ((0x40137514, b"\x43\xf9"), (0x40137916, b"\x43\xf9")),
    0x4020B324: ((0x40137508, b"\x41\xf9"), (0x4013790C, b"\x43\xf9")),
    0x4020B340: ((0x401375EE, b"\x43\xf9"),),   # A's site is a hook, below
}

# LFO1/2/3 `Waveform`, maximum field.  6 -> 9, so indices 7, 8 and 9 are
# reachable.
WAVE_MAX_FIELDS = (0x401F9224, 0x401F947C, 0x401F96D4)
STOCK_WAVE_MAX = 6

HOOKS = (
    # (address, stock bytes, stub label)
    (0x401379FA, b"\x41\xf9\x40\x20\xb3\x40", "a_call"),
    (0x4013760C, b"\x2f\x41\x00\x30\x4e\x91", "b_call"),
    (0x4013788E, b"\x75\x6c\x00\x4e\x9e\x80", "no_phase"),
)
LABELS = ("step", "pulse", "noise", "a_call", "b_call", "no_phase")

# Any non-zero word will do -- xorshift32's only requirement.  It is re-seeded
# from the image on every power-up, so NOI is deterministic per boot.
NOISE_SEED = 0x2545F491

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo-waveshapes_DN2_1.11.syx")


def be32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def source(fn_table: int, state: int) -> str:
    """The three generators and the three hook stubs.

    `%d2` and `%d3` are saved: the stock generators never touch them, so the
    evaluators are entitled to keep values there across the call.
    """
    p0, p1, br, vi, last, out = (state + 4 * k for k in range(1, 7))
    return f"""
    .text

| ---- STP: the ramp quantised to 2^k levels, k from SPH ------------------
| SPH 0..127 -> k = 1..8 -> 2..256 levels.  Keeping the top k bits floors each
| level, which would put the mean at -1/2 step, so half a step is added back and
| the result is symmetric about zero like every stock waveform.
step:
    move.l  %sp@(4),%d0
    move.l  %d2,%sp@-
    move.l  %d3,%sp@-
    eori.l  #0x7fffffff,%d0         | the stock SAW ramp
    andi.l  #0x7f,%d1               | SPH, coarse
    lsr.l   #4,%d1                  | 0..7
    addq.l  #1,%d1                  | k = 1..8
    moveq   #32,%d2
    sub.l   %d1,%d2                 | s = 32 - k, always 24..31
    asr.l   %d2,%d0
    lsl.l   %d2,%d0                 | floor to 2^k levels
    moveq   #1,%d3
    subq.l  #1,%d2
    lsl.l   %d2,%d3                 | half a step
    add.l   %d3,%d0
    move.l  %sp@+,%d3
    move.l  %sp@+,%d2
    rts

| ---- PLS: a pulse whose width is SPH ------------------------------------
| The phase ramps over the whole 32-bit range, so the duty cycle is an unsigned
| compare against (2*SPH + 1) << 24: SPH 0 gives 0.4%, SPH 127 gives 99.6%, and
| SPH 63 or 64 is within a fraction of a percent of square.
pulse:
    move.l  %sp@(4),%d0
    move.l  %d2,%sp@-
    andi.l  #0x7f,%d1
    add.l   %d1,%d1
    addq.l  #1,%d1                  | 1..255
    moveq   #24,%d2
    lsl.l   %d2,%d1                 | the threshold
    cmp.l   %d1,%d0
    bcs.s   1f                      | unsigned: phase below threshold
    move.l  #0x80000001,%d0         | the low half
    bra.s   2f
1:  move.l  #0x7fffffff,%d0         | the high half
2:  move.l  %sp@+,%d2
    rts

| ---- NOI: noise, clocked by the phase, coloured by SPH ------------------
| Generators are called **every frame**, not every LFO tick, so a generator that
| simply returned a fresh random number would run at the frame rate and ignore
| SPD and MULT entirely.  So this one is a sample-and-hold driven by the phase:
| the top eight bits are a step index, 256 steps per cycle, and a new value is
| drawn only when that index changes.  The rate is then SPD x MULT x 256, which
| is what the owner expects those two knobs to do -- and holding between steps is
| also what keeps the pink and brown filters running at a fixed rate per step
| instead of converging whenever the LFO is slow.
|
| SPH picks the colour, four bands of 32:
|
|   SPH   0-31   white    the raw xorshift
|   SPH  32-63   pink     two one-poles plus a quarter of the white
|   SPH  64-95   brown    a leaky random walk, gained back up
|   SPH  96-127  violet   the difference of successive whites
|
| Every filter is shifts only: no multiply, no MAC, no MACSR state to disturb.
noise:
    move.l  %d2,%sp@-
    move.l  %d3,%sp@-
    move.l  %sp@(12),%d0            | the phase, two pushes deep
    lsr.l   #8,%d0
    lsr.l   #8,%d0
    lsr.l   #8,%d0                  | step index, 256 per cycle
    move.l  {last:#010x},%d2
    cmp.l   %d2,%d0
    beq     9f                      | same step: hold
    move.l  %d0,{last:#010x}

    move.l  {state:#010x},%d0       | xorshift32, the white source
    moveq   #13,%d2
    move.l  %d0,%d3
    lsl.l   %d2,%d3
    eor.l   %d3,%d0
    moveq   #17,%d2
    move.l  %d0,%d3
    lsr.l   %d2,%d3
    eor.l   %d3,%d0
    move.l  %d0,%d3
    lsl.l   #5,%d3
    eor.l   %d3,%d0
    move.l  %d0,{state:#010x}

    andi.l  #0x7f,%d1
    lsr.l   #5,%d1                  | colour: 0..3
    subq.l  #1,%d1
    bmi     8f                      | white: %d0 is already the answer
    beq     1f
    subq.l  #1,%d1
    beq     2f
    bra     3f

1:  | pink -- a fast pole, a slow pole, and some of the white on top
    move.l  {p0:#010x},%d2
    move.l  %d0,%d3
    sub.l   %d2,%d3
    asr.l   #2,%d3
    add.l   %d3,%d2
    move.l  %d2,{p0:#010x}
    move.l  {p1:#010x},%d3
    move.l  %d0,%d1
    sub.l   %d3,%d1
    asr.l   #5,%d1
    add.l   %d1,%d3
    move.l  %d3,{p1:#010x}
    asr.l   #2,%d0
    asr.l   #1,%d2
    add.l   %d2,%d0
    add.l   %d3,%d0
    bra     8f

2:  | brown -- a leaky random walk, scaled back to a useful amplitude
    move.l  {br:#010x},%d2
    move.l  %d2,%d3
    asr.l   #4,%d3
    sub.l   %d3,%d2                 | leak
    move.l  %d0,%d3
    asr.l   #4,%d3
    add.l   %d3,%d2                 | integrate
    move.l  %d2,{br:#010x}
    add.l   %d2,%d2
    add.l   %d2,%d2
    move.l  %d2,%d0                 | x4
    bra     8f

3:  | violet -- the first difference of white
    move.l  {vi:#010x},%d2
    move.l  %d0,{vi:#010x}
    sub.l   %d2,%d0
    asr.l   #1,%d0

8:  | the filtered colours can overshoot, and an LFO that wrapped would click
    cmpi.l  #0x60000000,%d0
    ble     7f
    move.l  #0x60000000,%d0
    bra     6f
7:  cmpi.l  #-0x60000000,%d0
    bge     6f
    move.l  #-0x60000000,%d0
6:  move.l  %d0,{out:#010x}
9:  move.l  {out:#010x},%d0
    move.l  %sp@+,%d3
    move.l  %sp@+,%d2
    rts

| ---- evaluator A: reach the table, and carry SPH in %d1 -----------------
a_call:
    lea     {fn_table:#010x},%a0
    mvs.b   %a4@(78),%d1            | SPH, slot 8*lfo+6
    jmp     0x40137a00

| ---- evaluator B: the same, then make the call and come back ------------
| Entered by jmp, so the stack is exactly what the generator expects.
b_call:
    move.l  %d1,%sp@(48)            | the displaced frame save
    mvs.b   %a4@(44),%d1            | SPH, this evaluator's displacement
    jsr     %a1@
    jmp     0x40137612

| ---- SPH stops being a start phase for the two new shapes ---------------
no_phase:
    mvs.b   %a4@(76),%d2            | WAVE, coarse
    subq.l  #{STOCK_WAVE_MAX + 1},%d2
    bmi.s   1f                      | a stock waveform: SPH means start phase
    clr.l   %d2                     | STP or PLS: no start phase
    bra.s   2f
1:  mvs.w   %a4@(78),%d2
2:  sub.l   %d0,%d7                 | the displaced instruction
    jmp     0x40137894
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

    require_zero(content, CAVE, CAVE_CAP, "cave region")

    # --- layout: names, then the five tables, then the code --------------
    name_vas, cursor = [], CAVE
    for text in NEW_NAMES:
        name_vas.append(cursor)
        cursor += len(text)
    cursor = (cursor + 3) & ~3
    state_va, cursor = cursor, cursor + 4 * 7  # NOI: seed, filters, S&H
    names_va, cursor = cursor, cursor + 4 * ENTRIES
    table_vas = {}
    for old in STOCK_TABLES:
        table_vas[old], cursor = cursor, cursor + 4 * ENTRIES
    stub_va = cursor

    print("part 1 -- the generators and the hook stubs")
    payload, offsets = assemble_stubs(
        source(table_vas[0x4020B340], state_va), stub_va)
    used = (stub_va - CAVE) + len(payload)
    if used > CAVE_CAP:
        raise SystemExit(f"cave overflows: {used} > {CAVE_CAP}")
    write(content, stub_va, payload)
    for label in LABELS:
        print(f"  {label:<9} {offsets[label]:#010x}")
    TABLE_EXTRAS[0x4020B340] = [offsets["step"], offsets["pulse"],
                                offsets["noise"]]

    print(f"part 2 -- the {ENTRIES}-entry copies")
    write(content, state_va, be32(NOISE_SEED) + bytes(24))
    print(f"  NOI seed {NOISE_SEED:#010x} at {state_va:#010x}, six state words after it")
    for text, va in zip(NEW_NAMES, name_vas):
        write(content, va, text)
    old_names = read_longs(content, STOCK_NAMES, STOCK_ENTRIES)
    write(content, names_va, b"".join(be32(v) for v in old_names + name_vas))
    print(f"  names {STOCK_NAMES:#010x} -> {names_va:#010x}  "
          + " ".join(cstr(content, v) or "?" for v in old_names + name_vas))
    for old in STOCK_TABLES:
        entries = read_longs(content, old, STOCK_ENTRIES) + TABLE_EXTRAS[old]
        write(content, table_vas[old], b"".join(be32(v) for v in entries))
        print(f"  {old:#010x} -> {table_vas[old]:#010x}  "
              + ", ".join(f"{v:#x}" for v in entries))

    print("part 3 -- repoint every plain site")
    resolved = {STOCK_NAMES: names_va, **table_vas}
    for old, sites in REPOINTS.items():
        for va, prefix in sites:
            poke(content, va, prefix + be32(old), prefix + be32(resolved[old]),
                 f"{old:#010x} -> {resolved[old]:#010x}")

    print("part 4 -- the three hooks")
    for va, stock, label in HOOKS:
        poke(content, va, stock, b"\x4e\xf9" + be32(offsets[label]),
             f"jmp -> {label}")

    print(f"part 5 -- WAVE's maximum, {STOCK_WAVE_MAX} -> {ENTRIES - 1}")
    for va in WAVE_MAX_FIELDS:
        poke(content, va, be32(STOCK_WAVE_MAX << 8), be32((ENTRIES - 1) << 8),
             "LFO Waveform max")

    print("part 6 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes), "
          f"{used} of {CAVE_CAP} cave bytes used")
    return 0


def assemble_stubs(text: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once, and read each label's address off a trailing table.

    The assembler returns raw bytes with no symbol table, so the source carries
    a `.long <label>` per stub that is read back and then cut away.  One
    assembly, so the addresses cannot drift from the bytes they describe.
    """
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(text + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(f">{len(LABELS)}I", blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def read_longs(content: bytearray, va: int, n: int) -> list[int]:
    return list(struct.unpack_from(f">{n}I", content, va - BASE))


def write(content: bytearray, va: int, data: bytes) -> None:
    content[va - BASE:va - BASE + len(data)] = data


def cstr(content: bytearray, va: int) -> str | None:
    off = va - BASE
    if not 0 <= off < len(content):
        return None
    text = bytes(content[off:content.find(b"\0", off)])
    return text.decode("latin1") if 0 < len(text) < 24 else None


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
    if len(new) != len(stock):
        raise SystemExit(f"{va:#010x}: {len(new)} bytes for a {len(stock)}-byte site")
    content[off:off + len(new)] = new
    print(f"  {va:#010x}  {stock.hex():<14} -> {new.hex():<14}  {why}")


if __name__ == "__main__":
    raise SystemExit(main())

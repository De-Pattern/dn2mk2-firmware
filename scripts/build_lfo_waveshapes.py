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

import lfo_wave_glyph as glyph
import lfo_wave_ui as ui

MAIN_OS = 3
BASE = 0x40000400

# One of the three 896-byte runs that pass both of `dnfw cave scan`'s checks.
CAVE = 0x402CF52C
CAVE_CAP = 896
# v5 outgrew one run: the data (names, state, tables) moves to the second verified
# 896-byte run, the one lfo-wavetable uses for its table, and the code keeps the first.
DATA_CAVE = 0x402D0664
DATA_CAVE_CAP = 896

STOCK_NAMES = 0x401D3574            # TRI SIN SQR SAW EXP RMP RND
STOCK_TABLES = (0x4020B2EC, 0x4020B308, 0x4020B324, 0x4020B340)
STOCK_ENTRIES = 7
NEW_NAMES = (b"STP\x00", b"PLS\x00", b"NOI\x00")
NEW_LONG_NAMES = (b"STEP\x00", b"PULS\x00", b"NOIS\x00")
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
    (ui.SHORT_FMT, ui.FMT_ENTRY_STOCK, "fmt_short"),
    (ui.LONG_FMT, ui.FMT_ENTRY_STOCK, "fmt_long"),
)
LABELS = ("step", "pulse", "noise", "a_call", "b_call", "no_phase",
          "fmt_v92") + ui.LABELS
SPH_LABELS = ["STPS", "WDTH", "TYPE"]   # owner-approved: STPS, WDTH, TYPE

# The sound ParameterSet's vtable slot 92 (format a record's value), v6's hook.
SOUND_SET_V92 = 0x401DB858
# MIDI tracks' LFO page formats through MidiParameterSet (vtable 0x401db994), whose
# slot 92 holds the same stock method. v6-v9 wrapped only the sound set's, so on a
# MIDI track SPH stayed a plain number (owner, 2026-09-17). v10 wraps both.
MIDI_SET_V92 = 0x401DB9F0
STOCK_V92 = 0x40036692
NEVER_FMT = b"%d.--\x00"

# Any non-zero word will do -- xorshift32's only requirement.  It is re-seeded
# from the image on every power-up, so NOI is deterministic per boot.
NOISE_SEED = 0x2545F491

# NOI v4: 1,024 x 8 bytes of per-LFO state in the unclaimed SDRAM above BSS end
# 0x466b74d0. Other tenants of that region: lfo4-tick6a at 0x46700000..0x46703000,
# the boot-screen area at 0x46710000.
NOISE_RAM = 0x46740000

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
# v2: the first build ran every new index as RND and named it ERR (`lfo_wave_ui`).
# v10: v9 with SPH colour.loop on MIDI tracks too.
OUT = pathlib.Path("00_Resources/02_Builds/lfo-waveshapes10_DN2_1.11.syx")


def be32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def source(fn_table: int, state: int, short_names: int, long_names: int,
           never_fmt: int, glyph_sets: int, label_table: int) -> str:
    noise_ram = NOISE_RAM
    noise_index = STOCK_ENTRIES + 2
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
| History, because each version failed differently on the instrument:
| v2 held its sample in ONE global word shared by all 48 LFOs -> frame-rate noise,
|    deaf to SPD and MULT.
| v3 was stateless, a hash of the step within the cycle -> SPD and MULT worked,
|    but every cycle replayed the same 64 values (owner: "it looked like the
|    noise pattern repeated").
| v4 never repeated -- but the owner found v3's per-cycle repetition *"good for
|    music creation ... easy to insert in grooves, but is better to be able to
|    control it."*
| v5: each LFO instance owns 8 bytes of RAM -- its last step and a cycle count --
|    found by a key the call hooks put in %d1's upper bits. The count wraps at the
|    loop length, and the hash input is (cycle << 6) | step, so the pattern
|    repeats every L cycles. SPD and MULT still set the rate; a held value still
|    holds for the whole step; a backwards wrap (negative SPD) counts down.
|    The RAM is uninitialised: garbage there only picks a different start.
|
| SPH is two numbers, shown on the page as `colour.loop` (see fmt_sph):
|   colour = SPH >> 5          1 white, 2 pink, 3 brown, 4 violet
|   loop   = SPH & 31          0..30 -> repeats every loop+1 cycles, 31 -> never
|
|   white    h(n)
|   pink     six octaves h(n >> k), equal weight
|   brown    the same octaves, each slower one twice as loud
|   violet   h(n) - h(n - 1)
noise:
    lea     %sp@(-20),%sp
    moveml  %d2-%d5/%a2,%sp@
    move.l  %sp@(24),%d4            | the phase, below five saved registers
    moveq   #26,%d2
    lsr.l   %d2,%d4                 | step 0..63
    move.l  %d1,%d0
    lsr.l   #8,%d0                  | the instance key, 0..1023
    lsl.l   #3,%d0
    lea     {noise_ram:#010x},%a2
    adda.l  %d0,%a2                 | this LFO's 8 bytes
    move.l  %d1,%d5
    andi.l  #31,%d5                 | loop field: 31 = never repeat
    move.l  %a2@(4),%d3             | cycle
    move.l  %d4,%d0
    sub.l   %a2@,%d0                | step - last
    cmpi.l  #-32,%d0
    bge.s   1f
    addq.l  #1,%d3                  | wrapped forwards
1:  cmpi.l  #32,%d0
    ble.s   2f
    subq.l  #1,%d3                  | wrapped backwards
2:  cmpi.l  #31,%d5
    beq.s   4f                      | never: let the count run
    cmp.l   %d5,%d3
    bls.s   4f                      | unsigned: 0..loop is in range
    clr.l   %d3                     | past the end (or below zero): wrap to 0
    tst.l   %d0
    ble.s   4f
    move.l  %d5,%d3                 | a backwards wrap lands on the last cycle
4:  move.l  %d4,%a2@
    move.l  %d3,%a2@(4)
    lsl.l   #6,%d3
    or.l    %d3,%d4                 | n = cycle << 6 | step
    andi.l  #0x7f,%d1
    lsr.l   #5,%d1
    move.l  %d1,%d5                 | colour 0..3
    beq.s   10f
    cmpi.l  #3,%d5
    beq.s   30f
    clr.l   %d1                     | pink or brown: the octave sum
    clr.l   %d2                     | k
11: move.l  %d4,%d0
    lsr.l   %d2,%d0
    bsr     90f
    moveq   #3,%d3                  | pink: equal weight
    cmpi.l  #1,%d5
    beq.s   12f
    moveq   #6,%d3                  | brown: weight 2^-(6-k)
    sub.l   %d2,%d3
12: asr.l   %d3,%d0
    add.l   %d0,%d1
    addq.l  #1,%d2
    cmpi.l  #6,%d2
    blt.s   11b
    move.l  %d1,%d0
    bra.s   99f

10: move.l  %d4,%d0                 | white
    clr.l   %d2
    bsr     90f
    bra.s   99f

30: move.l  %d4,%d0                 | violet
    clr.l   %d2
    bsr     90f
    move.l  %d0,%d1
    move.l  %d4,%d0
    subq.l  #1,%d0
    clr.l   %d2
    bsr     90f
    sub.l   %d0,%d1
    move.l  %d1,%d0
    asr.l   #1,%d0

99: moveml  %sp@,%d2-%d5/%a2
    lea     %sp@(20),%sp
    rts

| ---- SPH's value text: `colour.loop` when this LFO's WAVE is NOIS --------
| v5 put this in the `Start Phase` records' formatter, which is handed only
| (value, dest), and found WAVE through two globals read under the emulator: the
| active-track byte 0x42431a6c and the engine mirror. On the instrument SPH still
| showed a plain number -- the track byte is inside a heap-allocated struct, so its
| address is not fixed across projects. [SUPERSEDED]
|
| v6 wraps the sound ParameterSet's format method instead (vtable 0x401db7fc,
| slot 92, stock 0x40036692), which is called as (this, record, value, dest). For
| the three SPH records it asks the object itself for WAVE -- `this->vfunc40(this,
| record - 2)` -- exactly as the firmware's own sibling method 0x4003660c does when
| it checks SPH against WAVE == RND. No globals. Records: WAVE 79/89/99, SPH
| 81/91/101 (table 0x401f7f94, 60 bytes a record).
fmt_v92:
    move.l  %sp@(8),%d0             | record
    cmpi.l  #81,%d0
    beq.s   71f
    cmpi.l  #91,%d0
    beq.s   71f
    cmpi.l  #101,%d0
    bne.s   79f
71: movea.l %sp@(4),%a0             | this
    movea.l %a0@,%a1
    subq.l  #2,%d0                  | the same LFO's WAVE record
    move.l  %d0,%sp@-
    move.l  %a0,%sp@-
    movea.l %a1@(40),%a1            | get(this, record)
    jsr     %a1@
    addq.l  #8,%sp
    lsr.l   #8,%d0
    cmpi.l  #{noise_index},%d0
    bne.s   79f
    move.l  %sp@(12),%d0
    asr.l   #8,%d0                  | SPH 0..127
    move.l  %d0,%d1
    andi.l  #31,%d1                 | loop field
    lsr.l   #5,%d0
    addq.l  #1,%d0                  | colour 1..4
    cmpi.l  #31,%d1
    beq.s   78f
    addq.l  #1,%d1                  | loop length in cycles, 1..31
    move.l  %d1,%sp@-
    move.l  %d0,%sp@-
    pea     0x40210bce              | "%d.%02d", the firmware's own
    move.l  %sp@(28),%sp@-          | dest: arg 4, past three pushes
    jsr     0x40000e82
    lea     %sp@(16),%sp
    rts
78: move.l  %d0,%sp@-               | never repeats: `colour.--`
    pea     {never_fmt:#010x}
    move.l  %sp@(24),%sp@-
    jsr     0x40000e82
    lea     %sp@(12),%sp
    rts
79: jmp     0x40036692              | every other record, or another wave: stock

| hash: %d0 = value, %d2 = octave -> %d0, clobbers %d3. A murmur-style mix.
90: move.l  %d2,%d3
    lsl.l   #8,%d3
    lsl.l   #4,%d3
    add.l   %d3,%d0                 | a different stream per octave
    addq.l  #1,%d0                  | so n = 0 does not hash to 0
    move.l  #0x9e3779b1,%d3
    mulsl   %d3,%d0
    move.l  %d0,%d3
    lsr.l   #8,%d3
    lsr.l   #7,%d3
    eor.l   %d3,%d0
    move.l  #0x85ebca77,%d3
    mulsl   %d3,%d0
    move.l  %d0,%d3
    lsr.l   #8,%d3
    lsr.l   #5,%d3
    eor.l   %d3,%d0
    rts

| ---- evaluator A: reach the table, and carry SPH in %d1 -----------------
a_call:
    lea     {fn_table:#010x},%a0
    lea     %a4@(78),%a1            | &SPH: one address per track and LFO
    bsr     80f
    mvs.b   %a4@(78),%d1            | SPH, slot 8*lfo+6
    andi.l  #0x7f,%d1
    or.l    %d0,%d1                 | the instance key above SPH's seven bits
    jmp     0x40137a00

| ---- evaluator B: the same, then make the call and come back ------------
| Entered by jmp, so the stack is exactly what the generator expects.
b_call:
    move.l  %d1,%sp@(48)            | the displaced frame save
    move.l  %a1,%sp@-               | %a1 is the generator: keep it
    lea     %a4@(44),%a1            | &SPH -- the same address A computes
    bsr     80f
    move.l  %sp@+,%a1
    mvs.b   %a4@(44),%d1            | SPH, this evaluator's displacement
    andi.l  #0x7f,%d1
    or.l    %d0,%d1
    jsr     %a1@
    jmp     0x40137612

| key: %a1 = &SPH -> %d0 = ((addr >> 1) & 1023) << 8. %d0 is free at both sites.
| Slots are 202 bytes a track and 16 an LFO, so 101*dt + 8*dl never reaches
| +-1024 for 16 tracks and 3 LFOs: 48 instances, 48 distinct keys.
80: move.l  %a1,%d0
    lsr.l   #1,%d0
    andi.l  #1023,%d0
    lsl.l   #8,%d0
    rts

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
""" + ui.formatter_source(ENTRIES - 1, short_names, long_names) 


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
    require_zero(content, DATA_CAVE, DATA_CAVE_CAP, "data cave region")

    # --- layout: names, then the five tables, then the code --------------
    name_vas, cursor = [], DATA_CAVE
    for text in NEW_NAMES:
        name_vas.append(cursor)
        cursor += len(text)
    cursor = (cursor + 3) & ~3
    state_va, cursor = cursor, cursor + 4 * 7  # NOI: seed, filters, S&H
    long_name_vas = []
    for text in NEW_LONG_NAMES:
        long_name_vas.append(cursor)
        cursor += len(text)
    never_va = cursor
    cursor += len(NEVER_FMT)
    cursor = (cursor + 3) & ~3
    names_va, cursor = cursor, cursor + 4 * ENTRIES
    long_names_va, cursor = cursor, cursor + 4 * ENTRIES
    table_vas = {}
    for old in STOCK_TABLES:
        table_vas[old], cursor = cursor, cursor + 4 * ENTRIES
    glyph_va, cursor = cursor, cursor + glyph.size(SPH_LABELS)
    glyph_bytes, glyph_sets, label_table = glyph.blob(glyph_va, SPH_LABELS)
    if cursor - DATA_CAVE > DATA_CAVE_CAP:
        raise SystemExit(f"data cave overflows: {cursor - DATA_CAVE} > {DATA_CAVE_CAP}")
    stub_va = CAVE

    print("part 1 -- the generators and the hook stubs")
    payload, offsets = assemble_stubs(
        source(table_vas[0x4020B340], state_va, names_va, long_names_va, never_va, glyph_sets, label_table), stub_va)
    used = (stub_va - CAVE) + len(payload)
    if used > CAVE_CAP:
        raise SystemExit(f"cave overflows: {used} > {CAVE_CAP}")
    write(content, stub_va, payload)
    # v8's glyph and label code outgrew the code cave: it assembles on its own,
    # into the data cave after the data.
    glyph_code_va = (cursor + 3) & ~3
    glyph_code, glyph_offsets = assemble_stubs(
        glyph.source(glyph_sets, table_vas[0x4020B340], len(SPH_LABELS), label_table,
                     state_reset=NOISE_RAM + 8 * glyph.NOISE_GLYPH_KEY),
        glyph_code_va, glyph.LABELS)
    data_used = glyph_code_va + len(glyph_code) - DATA_CAVE
    if data_used > DATA_CAVE_CAP:
        raise SystemExit(f"data cave overflows: {data_used} > {DATA_CAVE_CAP}")
    write(content, glyph_code_va, glyph_code)
    offsets.update(glyph_offsets)
    print(f"  glyph code {len(glyph_code)} bytes at {glyph_code_va:#010x}; "
          f"data cave {data_used}/{DATA_CAVE_CAP}")
    for label in LABELS + glyph.LABELS:
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
    for text, va in zip(NEW_LONG_NAMES, long_name_vas):
        write(content, va, text)
    write(content, never_va, NEVER_FMT)
    write(content, glyph_va, glyph_bytes)
    print(f"  glyph sets and SPH labels {', '.join(SPH_LABELS)}: {len(glyph_bytes)} bytes at {glyph_va:#010x}")
    old_long = read_longs(content, ui.LONG_NAMES, STOCK_ENTRIES)
    write(content, long_names_va, b"".join(be32(v) for v in old_long + long_name_vas))
    print(f"  long names {ui.LONG_NAMES:#010x} -> {long_names_va:#010x}  "
          + " ".join(cstr(content, v) or "?" for v in old_long + long_name_vas))
    for old in STOCK_TABLES:
        entries = read_longs(content, old, STOCK_ENTRIES) + TABLE_EXTRAS[old]
        write(content, table_vas[old], b"".join(be32(v) for v in entries))
        print(f"  {old:#010x} -> {table_vas[old]:#010x}  "
              + ", ".join(f"{v:#x}" for v in entries))

    print("part 3 -- repoint every plain site")
    resolved = dict(table_vas)
    for old, sites in REPOINTS.items():
        for va, prefix in sites:
            poke(content, va, prefix + be32(old), prefix + be32(resolved[old]),
                 f"{old:#010x} -> {resolved[old]:#010x}")

    print("part 4 -- the hooks: three in the evaluators, two value formatters")
    for va, stock, label in HOOKS:
        poke(content, va, stock, b"\x4e\xf9" + be32(offsets[label]),
             f"jmp -> {label}")

    print(f"part 5 -- WAVE's maximum, {STOCK_WAVE_MAX} -> {ENTRIES - 1}")
    for va in WAVE_MAX_FIELDS:
        poke(content, va, be32(STOCK_WAVE_MAX << 8), be32((ENTRIES - 1) << 8),
             "LFO Waveform max")

    print("part 5c -- SPH shows colour.loop on NOIS")
    poke(content, SOUND_SET_V92, be32(STOCK_V92), be32(offsets["fmt_v92"]),
         "sound ParameterSet vtable slot 92 -> fmt_v92")
    poke(content, MIDI_SET_V92, be32(STOCK_V92), be32(offsets["fmt_v92"]),
         "MIDI ParameterSet vtable slot 92 -> fmt_v92")

    print("part 5d -- the [MOD] page glyph")
    for va, stock, new, why in glyph.clamp_edits(ENTRIES - 1) + glyph.hooks(offsets):
        poke(content, va, stock, new, why)

    print(f"part 5b -- the evaluators' WAVE clamps, 6 -> {ENTRIES - 1}")
    for va, stock, new, why in ui.clamp_edits(ENTRIES - 1):
        poke(content, va, stock, new, why)

    print("part 6 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes), "
          f"{used} of {CAVE_CAP} cave bytes used")
    return 0


def assemble_stubs(text: str, base: int, labels=None) -> tuple[bytes, dict[str, int]]:
    """Assemble once, and read each label's address off a trailing table.

    The assembler returns raw bytes with no symbol table, so the source carries
    a `.long <label>` per stub that is read back and then cut away.  One
    assembly, so the addresses cannot drift from the bytes they describe.
    """
    labels = labels or LABELS
    table = "\n".join(f"    .long {name}" for name in labels)
    blob = assemble(text + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(labels)
    addrs = struct.unpack(f">{len(labels)}I", blob[-width:])
    return blob[:-width], dict(zip(labels, addrs))


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

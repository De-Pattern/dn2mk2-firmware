"""The [MOD] page's waveform glyph and SPH label for new LFO waveforms.

Shared by `build_lfo_waveshapes.py` and `build_lfo_wavetable.py`. On the
instrument every new waveform drew RND's glyph (owner, 2026-09-17: *"the wave
glyph just show the random wave"*). Read under the emulator, not guessed:

## How the stock page draws it

`WAVE` is read once, at `0x4010e1f4`, and passed with SPH, MODE, SPD and DEP to
the composite widget `0x4010dc82(this, bmp, 0, 1, WAVE, SPH, MODE, SPD, DEP)` --
found by a stack scan on the record getter `0x4003713c` whenever its record
argument was 79 (`guirun --stack-when`). Inside it:

```
0x4010dc8e  moveq #6,%d6 ... 0x4010dcb0 moveq #6,%d5   | WAVE clamped to 6
0x4010dd2a  %d2 = SPH, or 0 for RND                    | the tile's phase shift
0x4010dd42  memcpy(fp-7, 0x4020544c, 7)                | a flag per waveform
0x4010dd58  move.b %fp@(-7,%d5:l),%d1                  | ...indexed by WAVE
0x4010deba  %d6 = 12 * WAVE + 0x44507b68               | the glyph set
            0x40115ca8(set, variant, 0)                | -> a Bitmap
            0x401157fc(bmp, glyph, x, y, 0)            | blitted 3-4 times
```

A glyph set is a `std::vector<Bitmap>` -- begin, end, capacity -- filled lazily
from seven static vectors on first draw. Each stock set holds **four** 28 x 15
tiles (normal, time-reversed, flipped, both), chosen by the signs of SPD and DEP.
A `Bitmap` is 28 bytes: vtable `0x4020650c`, width, height, stride, pixel data,
**mask** (every stock glyph points at a 15-row all-ones mask), and a spare word.
Bitmaps are stored **flipped vertically** relative to the panel.

## v7 (lfo-waveshapes7, lfo-wavetable3): a fixed picture per waveform [SUPERSEDED]

One static tile each. The owner then asked for the picture to follow SPH -- pulse
width, step count -- and for SPH to be renamed on the new waveforms.

## v8: the picture is drawn by the waveform itself

- **The glyph is rendered from the generator.** On every draw, the flag hook
  calls the waveform's own generator 28 times -- phase `x * 2^32 / 28`, SPH in
  `%d1` exactly as the evaluators pass it -- and writes the curve into a RAM tile
  the static Bitmap points at. So PULS shows its width, STEP its steps, TRP its
  repeats, and **any shape the website builds gets a correct glyph with no picture
  data at all**. NOI is called with a reserved instance key (1023, used by none of
  the 64 real LFO slots), so drawing never disturbs a playing LFO's loop state.
- **No SPH phase slide for new waveforms** -- SPH is not a phase on them, so the
  hook zeroes `%d2`, as the stock code does for RND.
- **SPH is renamed** at `getShortName(this, record)` (`0x400372da`): for the SPH
  records 81/91/101 it asks the object for WAVE (records 79/89/99) and returns the
  new waveform's label. (Stock RND gets `SLEW` differently -- a separate record,
  80, sharing SPH's slot.)
- **One tile, not four:** `0x40115b5e` clamps the variant to the set's last
  element. A new waveform's glyph does not mirror for negative SPD or DEP.
"""

from __future__ import annotations

import struct

W, H = 28, 15
BITMAP_VTABLE = 0x4020650C
FULL_MASK = 0x402B8D90          # a stock 28 x 15 all-ones mask (TRI's)
STOCK_SETS = 0x44507B68
FIRST_NEW = 7                   # the first index past the stock waveforms
NOISE_GLYPH_KEY = 1023          # an instance key no real LFO slot hashes to

# RAM for the rendered tiles: unclaimed SDRAM above BSS end 0x466b74d0. Other
# tenants: lfo4-tick6a 0x46700000.., boot screen 0x46710000, NOI state 0x46740000.
TILE_RAM = 0x46750000

CLAMPS = ((0x4010DC8E, 0x7C), (0x4010DCB0, 0x7A))    # moveq #6,%d6 / moveq #6,%d5
FLAG_SITE = 0x4010DD58
FLAG_STOCK = bytes.fromhex("123658f941ec0033")       # move.b fp@(-7,d5); lea a4@(51),a0
SET_SITE = 0x4010DED0
SET_STOCK = bytes.fromhex("068644507b68")            # addi.l #0x44507b68,%d6
# SPH's label is the record's short name, read through getShortName(this, record)
# at 0x400372da -- the page's knob labels (0x40016adc) and the value header
# (0x40064622) both call it. [WRONG — corrected] v8's first two builds wrapped
# vtable slot 88 of both ParameterSet classes instead, because RND's `Slew` lives
# there too; the emulator showed neither slot is called by the page (0 hits).
SHORT_NAME = 0x400372DA
SHORT_NAME_STOCK = bytes.fromhex("202f00080c8000000141")    # move.l sp@(8),d0; cmpi.l #321,d0
SHORT_NAME_RESUME = 0x400372E4

LABELS = ("glyph_flag", "glyph_set", "short_name")


def blob(base: int, labels: list[str]) -> tuple[bytes, int, int]:
    """Static sets, Bitmaps and label strings. -> (bytes, sets VA, label table VA).

    sets[i] = {begin, end, capacity} over one Bitmap, whose pixels are the RAM
    tile the flag hook renders.
    """
    n = len(labels)
    sets_va, objs_va, table_va = base, base + 12 * n, base + 40 * n
    strings_va = table_va + 4 * n
    sets = objs = table = strings = b""
    for i, label in enumerate(labels):
        obj = objs_va + 28 * i
        sets += struct.pack(">III", obj, obj + 28, obj + 28)
        objs += struct.pack(">IIIIIII", BITMAP_VTABLE, W, H, 1, TILE_RAM + 112 * i, FULL_MASK, 0)
        table += struct.pack(">I", strings_va + len(strings))
        strings += label.encode("ascii") + b"\x00"
    return sets + objs + table + strings, sets_va, table_va


def size(labels: list[str]) -> int:
    return 44 * len(labels) + sum(len(s) + 1 for s in labels)


def clamp_edits(max_index: int) -> list[tuple[int, bytes, bytes, str]]:
    return [(va, bytes([op, 6]), bytes([op, max_index]), f"glyph WAVE clamp 6 -> {max_index}")
            for va, op in CLAMPS]


def source(sets_va: int, fn_table: int, count: int, label_table: int) -> str:
    return f"""
| ---- [MOD] glyph: render the new waveform's tile from its own generator ----
| Reached by jsr at 0x4010dd58 with %d5 = WAVE (clamped), %d2 = SPH 0..127.
glyph_flag:
    cmpi.l  #{FIRST_NEW},%d5
    bcc.s   10f
    move.b  %fp@(-7,%d5:l),%d1      | stock waveforms: the displaced read
    lea     %a4@(51),%a0            | the displaced instruction
    rts
10: lea     %sp@(-28),%sp
    moveml  %d3-%d7/%a2-%a3,%sp@
    move.l  %d2,%d7                 | SPH
    move.l  %d5,%d0
    subq.l  #{FIRST_NEW},%d0
    move.l  %d0,%d1
    lsl.l   #7,%d0
    lsl.l   #4,%d1
    sub.l   %d1,%d0                 | 112 * new index
    movea.l #{TILE_RAM:#010x},%a2
    adda.l  %d0,%a2                 | this waveform's tile
    movea.l #{fn_table:#010x},%a3
    movea.l %a3@(0,%d5:l:4),%a3     | its generator
    moveq   #0,%d4                  | x
    moveq   #-1,%d6                 | previous y: none yet
11: move.l  %d4,%d0
    move.l  #0x09249249,%d1         | 2^32 / 28
    mulsl   %d1,%d0                 | phase
    move.l  %d0,%sp@-
    move.l  #{NOISE_GLYPH_KEY << 8},%d1
    or.l    %d7,%d1                 | key above SPH, as the call hooks pass it
    jsr     %a3@
    addq.l  #4,%sp
    eori.l  #0x80000000,%d0         | 0 at the bottom, 2^32 - 1 at the top
    moveq   #16,%d1
    lsr.l   %d1,%d0
    move.l  %d0,%d1
    lsl.l   #4,%d0
    sub.l   %d1,%d0                 | * 15
    moveq   #16,%d1
    lsr.l   %d1,%d0                 | 0..14 from the bottom
    moveq   #14,%d1
    sub.l   %d0,%d1                 | y, 0 at the top
    tst.l   %d6
    bpl.s   12f
    move.l  %d1,%d6                 | first column joins itself
12: move.l  %d1,%d2                 | lo
    move.l  %d6,%d3                 | hi
    cmp.l   %d3,%d2
    ble.s   13f
    move.l  %d2,%d3                 | ColdFire has no exg
    move.l  %d6,%d2
13: moveq   #0,%d0                  | the column
14: moveq   #17,%d5
    add.l   %d2,%d5                 | stored flipped: bit 31 - (14 - y)
    moveq   #1,%d6
    lsl.l   %d5,%d6
    or.l    %d6,%d0
    addq.l  #1,%d2
    cmp.l   %d3,%d2
    ble.s   14b
    move.l  %d0,%a2@+
    move.l  %d1,%d6                 | previous y
    addq.l  #1,%d4
    moveq   #{W},%d0
    cmp.l   %d0,%d4
    blt     11b
    moveml  %sp@,%d3-%d7/%a2-%a3
    lea     %sp@(28),%sp
    moveq   #0,%d2                  | SPH is not a phase here: no slide
    moveq   #0,%d1                  | flag 0
    lea     %a4@(51),%a0
    rts

| ---- [MOD] glyph: the set, static for new waveforms -------------------------
| %d6 = 12 * WAVE on entry, as the stock code computed it.
glyph_set:
    cmpi.l  #{FIRST_NEW},%d5
    bcc.s   1f
    addi.l  #{STOCK_SETS:#010x},%d6
    rts
1:  addi.l  #{(sets_va - 12 * FIRST_NEW) & 0xFFFFFFFF:#010x},%d6
    rts

| ---- SPH's label on the new waveforms: the record's short name ------------
| getShortName(this, record) -> const char*. Entered by jmp at 0x400372da.
short_name:
    move.l  %sp@(8),%d0
    cmpi.l  #81,%d0
    beq.s   20f
    cmpi.l  #91,%d0
    beq.s   20f
    cmpi.l  #101,%d0
    beq.s   20f
29: move.l  %sp@(8),%d0             | the displaced instructions
    cmpi.l  #321,%d0
    jmp     {SHORT_NAME_RESUME:#010x}
20: movea.l %sp@(4),%a0             | this
    subq.l  #2,%d0                  | the same LFO's WAVE record
    move.l  %d0,%sp@-
    move.l  %a0,%sp@-
    movea.l %a0@,%a1
    movea.l %a1@(40),%a1
    jsr     %a1@
    addq.l  #8,%sp
    lsr.l   #8,%d0
    subq.l  #{FIRST_NEW},%d0
    bmi.s   29b
    cmpi.l  #{count - 1},%d0
    bhi.s   29b
    lea     {label_table:#010x},%a1
    move.l  %a1@(0,%d0:l:4),%d0     | the label
    rts
"""


def hooks(offsets: dict[str, int]) -> list[tuple[int, bytes, bytes, str]]:
    be = lambda v: struct.pack(">I", v)
    return [
        (FLAG_SITE, FLAG_STOCK, b"\x4e\xb9" + be(offsets["glyph_flag"]) + b"\x4e\x71",
         "jsr -> glyph_flag"),
        (SET_SITE, SET_STOCK, b"\x4e\xb9" + be(offsets["glyph_set"]), "jsr -> glyph_set"),
        (SHORT_NAME, SHORT_NAME_STOCK,
         bytes.fromhex("4ef9") + be(offsets["short_name"]) + bytes.fromhex("4e714e71"), "jmp -> short_name"),
    ]

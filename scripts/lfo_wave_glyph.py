"""The [MOD] page's waveform glyph for new LFO waveforms.

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
The pixel data of every stock glyph lives in the firmware image.

## What this adds

- the two clamp immediates raised to the new maximum;
- a hook for the flag byte: stock waveforms read the stock table, new ones get 0
  (the flag is set only for EXP and RMP);
- a hook for the set pointer: stock waveforms keep `0x44507b68 + 12*WAVE`, new
  ones get a **static** set in the image;
- per new waveform, one static set, one Bitmap, 112 bytes of pixels. **One tile,
  not four**: `0x40115b5e` clamps the variant to the set's last element, so a
  one-element set always draws its tile. The cost is that a new waveform's glyph
  does not mirror for negative SPD or DEP. Four tiles would not fit the clean
  caves (about 570 bytes per waveform against 152).
"""

from __future__ import annotations

import struct

W, H = 28, 15
BITMAP_VTABLE = 0x4020650C
FULL_MASK = 0x402B8D90          # a stock 28 x 15 all-ones mask (TRI's)
STOCK_SETS = 0x44507B68
STOCK_FLAGS = 7                 # entries in the stock flag table

CLAMPS = ((0x4010DC8E, 0x7C), (0x4010DCB0, 0x7A))    # moveq #6,%d6 / moveq #6,%d5
FLAG_SITE = 0x4010DD58
FLAG_STOCK = bytes.fromhex("123658f941ec0033")       # move.b fp@(-7,d5); lea a4@(51),a0
SET_SITE = 0x4010DED0
SET_STOCK = bytes.fromhex("068644507b68")            # addi.l #0x44507b68,%d6

LABELS = ("glyph_flag", "glyph_set")


# ---- the pictures ---------------------------------------------------------------
# Each design is a list of 28 y values (0 top, 14 bottom), one per column. Adjacent
# columns are joined by a vertical run, the way the stock glyphs draw their edges.

def _levels(*runs: tuple[int, int]) -> list[int]:
    out: list[int] = []
    for width, y in runs:
        out += [y] * width
    assert len(out) == W, len(out)
    return out


DESIGNS = {
    # y is screen rows, 0 at the top. A four-step staircase, rising
    "STEP": _levels((7, 14), (7, 10), (7, 5), (7, 0)),
    # a narrow pulse: low for three quarters, high for one
    "PULS": _levels((21, 14), (7, 0)),
    # jagged noise: a fixed pseudo-random walk, two columns a step
    "NOIS": [v for v in (7, 3, 11, 5, 13, 1, 9, 6, 12, 2, 8, 14, 4, 10) for _ in (0, 1)],
    # a soft trapezoid: rise, hold high, fall, hold low
    "TRP": [14, 11, 7, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            3, 7, 11, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14],
}


def pixels(ys: list[int]) -> bytes:
    """28 column longwords, as the panel shows them.

    Bitmaps are stored **flipped vertically** relative to the panel -- the same
    finding as the intro's source bitmap (`docs/display-path.md`). The first v7
    film drew STEP falling instead of rising; row y on screen is stored at row
    14 - y, i.e. bit 31 - (14 - y).
    """
    cols = [0] * W
    for x, y in enumerate(ys):
        lo, hi = sorted((y, ys[x - 1] if x else y))
        for yy in range(lo, hi + 1):
            cols[x] |= 1 << (31 - (H - 1 - yy))
    return b"".join(struct.pack(">I", c) for c in cols)


def blob(base: int, names: list[str]) -> tuple[bytes, int]:
    """Sets, Bitmaps and pixels for `names`, laid out from `base`. -> (bytes, sets VA).

    sets[i] = {begin, end, capacity} over one Bitmap each.
    """
    n = len(names)
    sets_va, objs_va, data_va = base, base + 12 * n, base + 12 * n + 28 * n
    sets, objs, data = b"", b"", b""
    for i, name in enumerate(names):
        obj, px = objs_va + 28 * i, data_va + 112 * i
        sets += struct.pack(">III", obj, obj + 28, obj + 28)
        objs += struct.pack(">IIIIIII", BITMAP_VTABLE, W, H, 1, px, FULL_MASK, 0)
        data += pixels(DESIGNS[name])
    return sets + objs + data, sets_va


def size(n: int) -> int:
    return (12 + 28 + 112) * n


def clamp_edits(max_index: int) -> list[tuple[int, bytes, bytes, str]]:
    return [(va, bytes([op, 6]), bytes([op, max_index]), f"glyph WAVE clamp 6 -> {max_index}")
            for va, op in CLAMPS]


def source(sets_va: int) -> str:
    """The two hooks. Each is reached by `jsr`, so it returns with `rts`."""
    return f"""
| ---- [MOD] glyph: the per-waveform flag, zero past the stock table --------
glyph_flag:
    cmpi.l  #{STOCK_FLAGS},%d5
    bcc.s   1f
    move.b  %fp@(-7,%d5:l),%d1      | the displaced read, stock waveforms
    bra.s   2f
1:  moveq   #0,%d1
2:  lea     %a4@(51),%a0            | the displaced instruction
    rts

| ---- [MOD] glyph: the set, static for new waveforms -------------------------
| %d6 = 12 * WAVE on entry, as the stock code computed it.
glyph_set:
    cmpi.l  #{STOCK_FLAGS},%d5
    bcc.s   1f
    addi.l  #{STOCK_SETS:#010x},%d6
    rts
1:  addi.l  #{(sets_va - 12 * STOCK_FLAGS) & 0xFFFFFFFF:#010x},%d6
    rts
"""


def hooks(offsets: dict[str, int]) -> list[tuple[int, bytes, bytes, str]]:
    be = lambda v: struct.pack(">I", v)
    return [
        (FLAG_SITE, FLAG_STOCK, b"\x4e\xb9" + be(offsets["glyph_flag"]) + b"\x4e\x71",
         "jsr -> glyph_flag"),
        (SET_SITE, SET_STOCK, b"\x4e\xb9" + be(offsets["glyph_set"]), "jsr -> glyph_set"),
    ]

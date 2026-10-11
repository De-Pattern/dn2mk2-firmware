"""Waverider's waveform display: the screen's copy of the tables the SHARC plays.

The page (`csrc/waverider/page.c`, M8.1) draws the wave across the middle of the
screen, between the two strips of controls, the way Tonverk's Wavefinder page lays
it out (User Manual OS 1.4.1, p. 94). This module holds the data it draws from:
`dsp.tables()`, the tables baked into section 7, reduced to one **span** per screen
column.

A column is the frame's minimum to its maximum over the points the column stands
for, as a sample editor's overview draws. Point samples cannot show these tables:
at 16 columns the overtone table's 16th partial put every sample on a zero crossing
and drew a flat line (M8, emulator, 2026-10-01). At the strip's width the partial
is about 6 pixels a cycle, and a span still never loses it.

    per frame: WIDTH minima, then WIDTH maxima, signed bytes (-127..127)
    2 tables x 16 frames x 2 x WIDTH bytes

When the tables move to the +Drive (`docs/waverider-tables.md`), this copy is made
at load time instead.

The reader's mapping, which the page reproduces: since W5, `wr_slot[DRIF >> 8]` picks
the table (before, `TBL1 >> 8`),
`min(WAV1, 0x7800)` the position across the 16 frames, interpolated between the two
frames either side.

This module is pure: it computes the spans and writes them as C.
"""

from __future__ import annotations

from . import dsp, factory

POS_ID, TBL_ID = 239, 252         # WAV1 (POS) and, since W5, DRIF (TBL; 247 = TBL1 before)
POS_MAX = 0x7800                  # the reader's clamp on WAV1
TABLES = dsp.TABLE_COUNT
FRAMES = 16
WIDTH = 96                        # screen columns the strip spans
# W5: the spans outgrew the page's chunk (11 tables x 3 KB), so they are a chunk of
# their own at a fixed address in the free RAM above BSS (dnfw.mods.ramcheck), clear of
# every other mod's RAM; page.c reaches them through this address.
SPANS_LOAD = 0x46B00000         # (0x46a00000.. is the emulator harness's scratch stack, emulib.machine)


def span_bytes() -> bytes:
    """The spans as the RAM chunk holds them: [table][frame][min, max][column], int8."""
    out = bytearray()
    for table in spans():
        for lo, hi in table:
            out += bytes(v & 0xFF for v in lo) + bytes(v & 0xFF for v in hi)
    return bytes(out)


def _byte(v: int) -> int:
    return max(-127, min(127, round(v * 127 / 32767)))


def spans(width: int = WIDTH) -> list[list[tuple[list[int], list[int]]]]:
    """-> [table][frame] = (minima, maxima), `width` signed bytes each. Column c
    covers points floor(c*P/width) .. floor((c+1)*P/width) of a P-point frame, the
    last point shared with the next column so neighbours meet."""
    out = []
    for table in dsp.tables():
        points = len(table[0])
        rows = []
        for frame in table:
            lo, hi = [], []
            for c in range(width):
                a, b = c * points // width, (c + 1) * points // width
                col = [frame[k % points] for k in range(a, b + 1)]
                lo.append(_byte(min(col)))
                hi.append(_byte(max(col)))
            rows.append((lo, hi))
        out.append(rows)
    return out


def c_source() -> str:
    """The reader's constants, the TBL -> slot table and the table names, as C for
    `wr_gen.h`. The spans themselves are a separate RAM chunk (`span_bytes`, at
    SPANS_LOAD); C reaches them as a pointer."""
    lut = ",".join(str(v) for v in dsp.slot_lut())
    names = ",".join(f'"{n[:4]}"' for n in factory.names(TABLES))
    return (f"#define WR_POS_ID {POS_ID}\n#define WR_TBL_ID {TBL_ID}\n"
            f"#define WR_POS_MAX {POS_MAX:#x}\n#define WR_TABLES {TABLES}\n"
            f"#define WR_FRAMES {FRAMES}\n#define WR_WIDTH {WIDTH}\n"
            f"#define WR_SPANS_LOAD {SPANS_LOAD:#x}u\n"
            f"typedef signed char wr_span_t[WR_TABLES][WR_FRAMES][2][WR_WIDTH];\n"
            f"#define wr_spans (*(const wr_span_t *)WR_SPANS_LOAD)\n"
            f"static const unsigned char wr_slot[128] = {{{lut}}};\n"
            f"static const char wr_table_names[WR_TABLES][5] = {{{names}}};\n")

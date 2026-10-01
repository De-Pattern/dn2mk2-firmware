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

The reader's mapping, which the page reproduces: `TBL1 >> 8` picks the table,
`min(WAV1, 0x7800)` the position across the 16 frames, interpolated between the two
frames either side.

This module is pure: it computes the spans and writes them as C.
"""

from __future__ import annotations

from . import dsp

POS_ID, TBL_ID = 239, 247         # WAV1 (POS) and TBL1 (TBL)
POS_MAX = 0x7800                  # the reader's clamp on WAV1
TABLES = 2
FRAMES = 16
WIDTH = 96                        # screen columns the strip spans


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
    """The spans and the reader's constants, as C for `wr_gen.h`."""
    rows = []
    for table in spans():
        frames = []
        for lo, hi in table:
            frames.append("  {{" + ",".join(map(str, lo)) + "},\n   {" + ",".join(map(str, hi)) + "}}")
        rows.append(" {\n" + ",\n".join(frames) + "\n }")
    return (f"#define WR_POS_ID {POS_ID}\n#define WR_TBL_ID {TBL_ID}\n"
            f"#define WR_POS_MAX {POS_MAX:#x}\n#define WR_TABLES {TABLES}\n"
            f"#define WR_FRAMES {FRAMES}\n#define WR_WIDTH {WIDTH}\n"
            f"static const signed char wr_spans[WR_TABLES][WR_FRAMES][2][WR_WIDTH] = {{\n"
            + ",\n".join(rows) + "\n};\n")

"""v0.68 (owner, 2026-11-21): MACHINE SEL's left pane shows the machine under the cursor.

Stock draws a wave and "SYN" there for every machine in the SRC column. For the mod's
machines the pane shows that machine's icon and label instead (the owner's icon sheet,
"DN2mk2 MACHINE ICONS"); the stock machines (FM TONE, FM DRUM, WAVETONE, SWARMER, MIDI) and
the FLTR column keep stock's.

The icons are drawn here from a few primitives, 1 bit, at most ICON_W x ICON_H, and written
to csrc/sampler/msicon_art.h (`python3 -m dnfw.msicons`); test/test_msicons.py checks the
header is current. Rows are top-down; msicon.c turns them for the panel (y 0 at the bottom).
"""
from __future__ import annotations

import math
import pathlib

ICON_W, ICON_H = 34, 22

# machine type -> icon; MACHINE SEL's types (waverider/coldfire.py MACHINE_NAMES, mnm.TYPES)
TYPE_ICON = {5: "PERC", 6: "SYN+", 7: "DPRO", 14: "DDRW", 15: "DENS", 16: "VO-6",
             18: "STAT", 19: "PAR", 20: "DYN",
             8: "SAMP", 9: "SAMP", 10: "SAMP", 11: "SAMP", 12: "SAMP", 13: "SAMP",
             17: "FLEX"}
ORDER = ("PERC", "SYN+", "DPRO", "DDRW", "DENS", "VO-6", "STAT", "PAR", "DYN", "SAMP", "FLEX")

HEADER = pathlib.Path(__file__).resolve().parents[2] / "csrc" / "sampler" / "msicon_art.h"


class Canvas:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.px = [[0] * w for _ in range(h)]

    def set(self, x: int, y: int, v: int = 1) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = v

    def fill(self, x0: int, y0: int, x1: int, y1: int, v: int = 1) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, v)

    def box(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.fill(x0, y0, x1, y0)
        self.fill(x0, y1, x1, y1)
        self.fill(x0, y0, x0, y1)
        self.fill(x1, y0, x1, y1)

    def wave(self, y0: float, amp: float, period: float, phase: float, thick: int = 2,
             dash: int = 0) -> None:
        prev = None
        for x in range(self.w):
            y = round(y0 - amp * math.sin(2 * math.pi * (x + phase) / period))
            lo, hi = (y, y) if prev is None else (min(y, prev), max(y, prev))
            prev = y
            if dash and (x // dash) % 2:
                continue
            for yy in range(lo, hi + thick):
                self.set(x, yy)

    def rows(self) -> list[str]:
        ys = [y for y in range(self.h) if any(self.px[y])]
        xs = [x for x in range(self.w) if any(self.px[y][x] for y in range(self.h))]
        return ["".join("#" if self.px[y][x] else "." for x in range(xs[0], xs[-1] + 1))
                for y in range(ys[0], ys[-1] + 1)]


def _perc(c: Canvas) -> None:            # the Machinedrum: a grid of hits
    c.fill(4, 0, 10, 6); c.fill(14, 0, 20, 6)
    c.fill(28, 0, 29, 1); c.fill(28, 4, 29, 5)
    c.fill(0, 9, 7, 16)
    for x in (12, 18, 24, 30):
        c.fill(x, 10, x + 1, 11); c.fill(x, 14, x + 1, 15)
    for x in (2, 9, 16, 23, 30):
        c.fill(x, 19, x + 2, 21)


def _sid(c: Canvas) -> None:             # SID: three oscillators
    for k, y in enumerate((3, 10, 17)):
        c.wave(y, 2.4, 17, 4 * k, thick=2)


def _dpro(c: Canvas) -> None:            # DPRO WAVE: a pulse over a dotted line
    c.fill(0, 9, 6, 10); c.fill(5, 0, 6, 10); c.fill(5, 0, 14, 1); c.fill(13, 0, 14, 10)
    c.fill(13, 9, 21, 10); c.fill(20, 0, 21, 10); c.fill(20, 0, 29, 1); c.fill(28, 0, 29, 10)
    c.fill(28, 9, 33, 10)
    for x in range(1, 34, 4):
        c.fill(x, 15, x + 1, 16)


def _ddrw(c: Canvas) -> None:            # DPRO DDRW: drawbars, falling
    for k, h in enumerate((22, 19, 16, 13, 11, 9, 7, 5, 4)):
        x = 4 * k
        c.fill(x, 22 - h, x + 1, 21)


def _dens(c: Canvas) -> None:            # DENS: noise
    s = 0x2545
    for x in range(34):
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        a = 1 + (s >> 16) % 5
        if x % 7 == 3:
            a += 4
        c.fill(x, 10 - a, x, 10 + a - (x % 2))


def _vo6(c: Canvas) -> None:             # VO-6: a voice (dashed) over two waves
    c.wave(3, 2.5, 17, 0, thick=2, dash=3)
    c.wave(11, 2.5, 17, 0, thick=2)
    c.wave(18, 2.5, 17, 0, thick=2)


def _stat(c: Canvas) -> None:            # FM+ STAT: a spectrum
    for k, h in enumerate((3, 7, 4, 10, 6, 14, 9, 18, 12, 22, 16)):
        x = 3 * k + 1
        c.fill(x, 22 - h, x + 1, 21)


def _par(c: Canvas) -> None:             # FM+ PAR: scattered partials
    for x, y, s in ((15, 0, 2), (7, 4, 3), (24, 4, 2), (19, 8, 2), (12, 10, 3), (2, 11, 2),
                    (29, 11, 2), (23, 12, 4), (6, 15, 2), (12, 17, 3), (20, 17, 3),
                    (28, 17, 2), (0, 18, 3), (10, 21, 2)):
        c.fill(x, y, x + s - 1, min(21, y + s - 1))


def _dyn(c: Canvas) -> None:             # FM+ DYN: sweeps
    cx, cy = 40, 26
    for r in (13, 18, 23, 28, 33):
        for t in range(0, 900):
            a = math.radians(90 + t / 10)
            x, y = round(cx + r * math.cos(a)), round(cy - r * math.sin(a))
            if y <= 21:
                c.set(x, y)


_FONT = {"D": ["######.", "##..###", "##...##", "##...##", "##...##", "##..###", "######."],
         "T": ["#######", "#######", "..###..", "..###..", "..###..", "..###..", "..###.."],
         "2": [".#####.", "##...##", ".....##", "..####.", ".##....", "##.....", "#######"]}


def _samp(c: Canvas) -> None:            # the Digitakt II's sample machines
    for k, ch in enumerate("DT2"):
        for y, row in enumerate(_FONT[ch]):
            for x, b in enumerate(row):
                if b == "#":
                    c.set(3 + 10 * k + x, y)
    for y in (11, 15, 19):
        c.fill(0, y, 33, y + 1)


def _flex(c: Canvas) -> None:            # FLEX: stacked buffers
    for off in (8, 4, 0):
        x0, y0 = off, 8 - off
        c.fill(x0, y0, x0 + 13, y0 + 13, 0)
        c.box(x0, y0, x0 + 13, y0 + 13)
    c.fill(3, 11, 10, 18)


_DRAW = {"PERC": _perc, "SYN+": _sid, "DPRO": _dpro, "DDRW": _ddrw, "DENS": _dens,
         "VO-6": _vo6, "STAT": _stat, "PAR": _par, "DYN": _dyn, "SAMP": _samp, "FLEX": _flex}


def icon(name: str) -> list[str]:
    c = Canvas(ICON_W, ICON_H)
    _DRAW[name](c)
    rows = c.rows()
    if len(rows) > ICON_H or len(rows[0]) > ICON_W:
        raise ValueError(f"{name}: {len(rows[0])} x {len(rows)} > {ICON_W} x {ICON_H}")
    return rows


def header() -> str:
    out = ["/* generated by `python3 -m dnfw.msicons` (src/dnfw/msicons.py): do not edit */",
           f"#define MSI_N {len(ORDER)}",
           "static const unsigned char msi_w[MSI_N] = {"
           + ", ".join(str(len(icon(n)[0])) for n in ORDER) + "};",
           "static const unsigned char msi_h[MSI_N] = {"
           + ", ".join(str(len(icon(n))) for n in ORDER) + "};",
           "static const char *const msi_label[MSI_N] = {"
           + ", ".join(f'"{n}"' for n in ORDER) + "};",
           f"/* each icon: {ICON_H} rows top-down, a row two 32-bit words, bit 31 of the first the left pixel */",
           f"static const unsigned int msi_bits[MSI_N][{ICON_H}][2] = {{"]
    for n in ORDER:
        words = []
        for row in icon(n):
            v = 0
            for x, ch in enumerate(row):
                if ch == "#":
                    v |= 1 << (63 - x)
            words.append(f"{{0x{v >> 32:08x}u, 0x{v & 0xFFFFFFFF:08x}u}}")
        out.append(f"    /* {n} */ {{" + ", ".join(words) + "},")
    out.append("};")
    cases = {}
    for t, n in sorted(TYPE_ICON.items()):
        cases.setdefault(ORDER.index(n), []).append(t)
    out.append("static int msi_of(int type)")
    out.append("{")
    out.append("    switch (type) {")
    for i, ts in sorted(cases.items()):
        out.append("    " + " ".join(f"case {t}:" for t in ts) + f" return {i};")
    out.append("    default: return -1;")
    out.append("    }")
    out.append("}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    HEADER.write_text(header())
    for n in ORDER:
        print(n)
        print("\n".join(icon(n)))

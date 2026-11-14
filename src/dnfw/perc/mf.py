"""SHARC float multifunction compute (`Fm = Fx * Fy, Fa = Fb op Fc`, one cycle): a second encoder.

selas encodes the legal forms (operand groups below) itself, and the same word as the firmware's (0x58c830 for
`F12 = F0 * F7, F8 = F8 + F12`); an illegal group it silently assembles as the multiply alone, without a word of
complaint. `verify` (called from sharc_waverider_m3._selas) therefore checks every multifunction line's compute
field, the low 23 bits of the last 32-bit word of the instruction, against `field`, a second encoding.

The encoding (PGR Table 12-12, digikit's compute_table.json; both give the 6-bit multifunction category):
    bit 22 = 1, bits 21:16 = category, 15:12 Fm, 11:8 Fa, 7:6 Fxm (F0-F3), 5:4 Fym (F4-F7),
    3:2 Fxa (F8-F11), 1:0 Fya (F12-F15)
    category 011000  Fm = Fxm * Fym, Fa = Fxa + Fya        011001 ... Fxa - Fya
             011110  ... MAX(Fxa, Fya)                     011111 ... MIN(Fxa, Fya)
Both operands of the multiply read before either result is written (the ALU sees the OLD value of Fm).

The firmware uses this field layout in its dual add/subtract instructions (category 11xxxx: Fm, Fa, Fxm, Fym,
Fxa, Fya packed exactly so), and the plain `F12 = F0 * F7, F8 = F8 + F12` (category 011000, compute 0x58c830)
at sw 0x1c7258 of the stock 1.11 image. selmap (the gate's second decoder) does not know the 011xxx categories
on the 32-bit form and prints them as MRF forms; the gate checks those instructions against digikit and against
this module (sharc_waverider_m5.decode_check)."""

from __future__ import annotations

import re

CATEGORY = {"+": 0b011000, "-": 0b011001, "MAX": 0b011110, "MIN": 0b011111}
_NAME = {v: k for k, v in CATEGORY.items()}

_DUAL = re.compile(
    r"^\s*F(\d+) = F(\d+) \* F(\d+), F(\d+) = F(\d+) \+ F(\d+), F(\d+) = F(\d+) - F(\d+)(?:, (.*))?;")
_LINE = re.compile(
    r"^\s*F(\d+) = F(\d+) \* F(\d+), F(\d+) = (?:F(\d+) ([+-]) F(\d+)|(MIN|MAX)\(F(\d+), F(\d+)\))"
    r"(?:, (.*))?;")


def field(fm: int, xm: int, ym: int, op: str, fa: int, xa: int, ya: int) -> int:
    """The 23-bit compute field of `Fm = Fxm * Fym, Fa = Fxa op Fya`."""
    assert op in CATEGORY, op
    assert 0 <= fm < 16 and 0 <= fa < 16
    assert 0 <= xm < 4 and 4 <= ym < 8, f"multiplier operands are F0-F3 x F4-F7: F{xm} * F{ym}"
    assert 8 <= xa < 12 and 12 <= ya < 16, f"ALU operands are F8-F11, F12-F15: F{xa}, F{ya}"
    return ((1 << 22) | (CATEGORY[op] << 16) | (fm << 12) | (fa << 8) | (xm << 6) | ((ym - 4) << 4)
            | ((xa - 8) << 2) | (ya - 12))


def field_dual(fm: int, xm: int, ym: int, fa: int, fs: int, xa: int, ya: int) -> int:
    """`Fm = Fxm * Fym, Fa = Fxa + Fya, Fs = Fxa - Fya`: category 11 + Fs (the firmware's dual add/subtract)."""
    assert 0 <= fm < 16 and 0 <= fa < 16 and 0 <= fs < 16
    assert 0 <= xm < 4 and 4 <= ym < 8 and 8 <= xa < 12 and 12 <= ya < 16
    return ((1 << 22) | (0b110000 << 16) | (fs << 16) | (fm << 12) | (fa << 8) | (xm << 6) | ((ym - 4) << 4)
            | ((xa - 8) << 2) | (ya - 12))


def unfield(c: int) -> tuple[int, int, int, str, int, int, int]:
    """The inverse: (fm, xm, ym, op, fa, xa, ya) of a compute field of these categories."""
    assert c >> 22 & 1 and (c >> 16 & 0x3F) in _NAME, hex(c)
    return (c >> 12 & 15, c >> 6 & 3, 4 + (c >> 4 & 3), _NAME[c >> 16 & 0x3F], c >> 8 & 15,
            8 + (c >> 2 & 3), 12 + (c & 3))


def text(fm: int, xm: int, ym: int, op: str, fa: int, xa: int, ya: int, move: str = "") -> str:
    alu = f"F{fa} = MIN(F{xa}, F{ya})" if op == "MIN" else f"F{fa} = MAX(F{xa}, F{ya})" if op == "MAX" \
        else f"F{fa} = F{xa} {op} F{ya}"
    return f"F{fm} = F{xm} * F{ym}, {alu}" + (f", {move}" if move else "") + ";"


def parse(line: str) -> int | None:
    """The compute field of a source line written in full (`text`'s form), else None."""
    d = _DUAL.match(line.split("//", 1)[0])
    if d:
        g = [int(x) for x in d.groups()[:9]]
        assert g[4] == g[7] and g[5] == g[8], f"dual add / subtract of different operands: {line.strip()}"
        return field_dual(g[0], g[1], g[2], g[3], g[6], g[4], g[5])
    m = _LINE.match(line.split("//", 1)[0])
    if not m:
        return None
    g = m.groups()
    fm, xm, ym, fa = int(g[0]), int(g[1]), int(g[2]), int(g[3])
    if g[7]:
        return field(fm, xm, ym, g[7], fa, int(g[8]), int(g[9]))
    return field(fm, xm, ym, g[5], fa, int(g[4]), int(g[6]))


def verify(be: bytes, offs: list[int], lines: list[str]) -> list[int]:
    """BE: selas's code (object byte order); OFFS: the byte offset of each instruction; LINES: the source text of
    each. For every multifunction line written in full (`text`'s form) the compute field selas encoded (the low
    23 bits of the last four bytes of the instruction) must be the one `field` computes from the line: an
    independent second encoding. Returns the indices of those lines; a mismatch raises."""
    found = []
    ends = offs[1:] + [len(be)]
    for k, (o, e, line) in enumerate(zip(offs, ends, lines)):
        c = parse(line)
        if c is None:
            continue
        assert e - o in (4, 6), f"multifunction line assembled as {e - o} bytes: {line.strip()}"
        got = int.from_bytes(be[e - 4:e], "big") & 0x7FFFFF
        assert got == c, f"selas encoded {line.strip()} as compute {got:#x}, not {c:#x}"
        found.append(k)
    return found

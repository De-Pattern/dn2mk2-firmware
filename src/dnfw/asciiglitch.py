"""A mark decomposed into glitching ASCII, as frames for the Digitone II's 128 x 64 screen.

The boot-screen mod's second animation. It follows DNX's PHOSPHOR loader
(`DNX/web/src/landing/dnxloader.ts`): a grid of character cells starts as
scrambled glyphs, each cell locks into the picture at its own moment (random,
with a slight left-to-right bias), rows tear sideways while the chaos decays,
thin slices slip like broken video sync, and a residual glitch lingers once the
picture has resolved.

The panel is one bit and 128 x 64, so what DNX does with tone, alpha, bloom and
scanlines is folded into which pixels light: a glyph's alpha becomes the chance
it is drawn at all. Cells are 4 x 6 pixels -- a 3 x 5 glyph of our own font
(`font3x5.json`) and a pixel of gap -- so the grid is 32 x 10. Only glyphs in
that font can be used, which is why the character lists are smaller than DNX's.

## Parity

`site/js/asciiglitch.js` is the same algorithm, line for line, and must produce
the same pixels: `scripts/js_asciiglitch_check.mjs` fails otherwise. Both use
only integer hashing and correctly rounded arithmetic -- `u * sqrt(u)` stands in
for DNX's `u ** 1.45`, because `pow` is not correctly rounded and could differ
between Python and a browser in the last bit.
"""

from __future__ import annotations

import json
import math
import pathlib

W, H = 128, 64
CW, CH = 4, 6                 # a cell: a 3 x 5 glyph and a pixel of gap
COLS, ROWS = W // CW, H // CH  # 32 x 10
Y0 = (H - ROWS * CH) // 2      # 2: the grid centred vertically

RAMP = " .:+#"                 # the picture, dark to bright
GLITCH = "01/:=+<>[]{}#%*?_|-\\"

FONT = json.loads(pathlib.Path(__file__).with_name("font3x5.json").read_text())["glyphs"]
M32 = 0xFFFFFFFF


class GlitchError(ValueError):
    """The options cannot make an animation."""


def _imul(a: int, b: int) -> int:
    return ((a & M32) * (b & M32)) & M32


def rnd(key: int) -> float:
    """DNX's stable integer noise, 0 <= r < 1."""
    n = key & M32
    n = _imul(n ^ (n >> 16), 0x45D9F3B)
    n = _imul(n ^ (n >> 16), 0x45D9F3B)
    return ((n ^ (n >> 16)) & M32) / 4294967296


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def check_chars(chars: str, what: str) -> str:
    chars = chars.upper()
    missing = sorted({c for c in chars if c not in FONT})
    if missing:
        raise GlitchError(f"{what}: no glyph for {''.join(missing)!r}; the font has {''.join(FONT)!r}")
    if not chars:
        raise GlitchError(f"{what}: give at least one character")
    return chars


def cells(lit) -> list[str]:
    """The picture as characters: each cell's lit coverage picks from `ramp`.
    Returns the coverage counts (0..24) per cell, row by row."""
    out = []
    for r in range(ROWS):
        for c in range(COLS):
            n = 0
            for y in range(Y0 + r * CH, Y0 + r * CH + CH):
                for x in range(c * CW, c * CW + CW):
                    n += 1 if lit(x, y) else 0
            out.append(n)
    return out


def _draw(px: bytearray, ch: str, x0: int, y0: int) -> None:
    for gy, row in enumerate(FONT[ch]):
        y = y0 + gy
        if y < 0 or y >= H:
            continue
        for gx, bit in enumerate(row):
            x = x0 + gx
            if bit == "1" and 0 <= x < W:
                px[y * W + x] = 1


def frames(lit, *, ramp: str = RAMP, glitch_chars: str = GLITCH, resolve: int = 40,
           idle_frames: int = 16, seed: int = 26, glitch: float = 1.0,
           idle: float = 0.3) -> list[bytearray]:
    """-> `resolve + idle_frames` frames, each 128 x 64 bytes of 0/1, row-major.

    `lit(x, y)` is the picture. Frames `0..resolve-1` go from noise to the
    picture; the rest are the settled picture with residual glitches, meant to
    loop. `glitch` scales the chaos (0 = no tearing or scramble, 1 = DNX's),
    `idle` the residual glitch."""
    ramp = check_chars(ramp, "picture characters")
    glitch_chars = check_chars(glitch_chars, "glitch characters")
    if resolve < 1 or idle_frames < 0:
        raise GlitchError("resolve needs at least one frame, and idle frames cannot be negative")
    if not 0 <= glitch <= 2 or not 0 <= idle <= 1:
        raise GlitchError("glitch is 0..2 and idle 0..1")
    cover = cells(lit)
    steps = len(ramp) - 1
    target = [ramp[(n * steps * 2 + 24) // 48] for n in cover]
    g = len(glitch_chars)
    grid = []
    for r in range(ROWS):
        for c in range(COLS):
            key = (c + 7) * 733 + (r + 4) * 7919 + seed
            grid.append((key, 0.035 + rnd(key + 19) * 0.84 + (c / COLS) * 0.11))

    out = []
    for k in range(resolve + idle_frames):
        progress = (k / (resolve - 1) if resolve > 1 else 1.0) if k < resolve else 1.0
        reveal = _smooth((progress - 0.10) / 0.90)
        u = 1 - reveal
        chaos = u * math.sqrt(u) * glitch
        idle_amt = idle if k >= resolve else idle * _smooth((progress - 0.72) / 0.28)
        row_tick = k >> 1
        px = bytearray(W * H)
        for r in range(ROWS):
            row_key = r * 919 + row_tick * 311 + seed
            tearing = 2.4 if rnd(row_key + 41) < 0.22 else 1.0
            sx = math.floor((rnd(row_key) - 0.5) * CW * 15 * chaos * tearing + 0.5)
            sy = math.floor((rnd(row_key + 11) - 0.5) * CH * 1.8 * chaos * chaos + 0.5)
            if k >= resolve:
                j = k - resolve
                if rnd(seed * 31 + j * 977 + r * 13) < idle * 0.08:
                    step = 1 + math.floor(rnd(seed + j * 71 + r * 7) * 3)
                    sx += step if rnd(seed + j * 53 + r) < 0.5 else -step
            for c in range(COLS):
                key, lock_at = grid[r * COLS + c]
                if reveal >= lock_at:
                    ch = target[r * COLS + c]
                    if ch != " " and rnd(key + k * 1103) < idle_amt * 0.04:
                        ch = glitch_chars[math.floor(rnd(key + k * 97) * g)]
                    if ch == " ":
                        continue
                else:
                    n = rnd(key + k * 13007)
                    if n > 0.50 + chaos * 0.12:
                        continue
                    ch = glitch_chars[math.floor(rnd(key + k * 701 + 7) * g)]
                    alpha = 0.24 + rnd(key + k * 503) * 0.72
                    if rnd(key + k * 211) > alpha:
                        continue
                _draw(px, ch, c * CW + sx, Y0 + r * CH + sy)
        if chaos > 0.04:
            for i in range(4):
                yy = math.floor(rnd(row_tick * 263 + i * 73 + seed) * H)
                hh = max(1, math.floor(CH * (0.08 + chaos * 0.5) + 0.5))
                dx = math.floor((rnd(i * 31 + row_tick * 911) - 0.5) * CW * chaos * 18 + 0.5)
                for y in range(yy, min(H, yy + hh)):
                    row = px[y * W:(y + 1) * W]
                    for x in range(W):
                        s = x - dx
                        px[y * W + x] = row[s] if 0 <= s < W else 0
        out.append(px)
    return out

"""The mark as a 1966-style spinning transition, as frames for the 128 x 64 screen.

The boot-screen mod's third animation, after the owner's idea: the television
transition where a logo spins and zooms towards the camera, back and forth, over
a swirling background. Here the logo is the user's mark (cropped to its lit
pixels), and the swirl is a field of points at different radii turning about the
centre, each smeared into an arc as long as its angular speed -- a long streak
while the spin is fast, a dash once it slows.

| phase | logo | background |
|---|---|---|
| `0 .. resolve-1` | grows from nothing, spinning `spin` turns and slowing to rest, its size swinging back and forth by `zoom` | turns fast, smeared, slowing |
| after `resolve` | held, upright, full size | turns slowly, one whole turn per loop, so the loop is seamless |

A third of the points turn twice as fast, for depth; with whole turns per loop
they still meet their start.

## Parity

`site/js/batspin.js` must produce identical pixels (`scripts/js_batspin_check.mjs`).
`sin` is not correctly rounded in either language, so it is computed here from a
polynomial of plain multiplies and adds, which are.
"""

from __future__ import annotations

import math

from .asciiglitch import rnd

W, H = 128, 64
CX, CY = 63.5, 31.5
PI = 3.141592653589793
TWO_PI = 6.283185307179586


class SpinError(ValueError):
    """The options cannot make an animation."""


def sin_(x: float) -> float:
    """sin(x) to about 4e-6 from + and * only, so Python and a browser agree bit for bit."""
    x = x - TWO_PI * math.floor(x / TWO_PI)          # 0 .. 2pi
    if x > PI:
        x -= TWO_PI                                  # -pi .. pi
    if x > PI / 2:
        x = PI - x
    elif x < -PI / 2:
        x = -PI - x
    x2 = x * x
    return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42 * (1 - x2 / 72))))


def cos_(x: float) -> float:
    return sin_(x + PI / 2)


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _bbox(lit):
    xs, ys = [], []
    for y in range(H):
        for x in range(W):
            if lit(x, y):
                xs.append(x)
                ys.append(y)
    if not xs:
        raise SpinError("the mark has no lit pixels")
    return min(xs), min(ys), max(xs), max(ys)


def frames(lit, *, resolve: int = 120, idle_frames: int = 48, stars: int = 90,
           smear: float = 1.0, spin: float = 3.0, zoom: float = 1.0,
           seed: int = 26) -> list[bytearray]:
    """-> `resolve + idle_frames` frames, each 128 x 64 bytes of 0/1, row-major."""
    if resolve < 2 or idle_frames < 1:
        raise SpinError("resolve needs at least two frames and the loop at least one")
    if not (0 <= stars <= 400 and 0 <= smear <= 3 and 0 <= spin <= 12 and 0 <= zoom <= 2):
        raise SpinError("stars 0..400, smear 0..3, spin 0..12 turns, zoom 0..2")
    x0, y0, x1, y1 = _bbox(lit)
    lcx, lcy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2 + 0.5, (y1 - y0) / 2 + 0.5
    reach = math.sqrt(hw * hw + hh * hh)
    field = []
    for i in range(stars):
        r = 3 + rnd(seed + i * 97) * 72
        theta = rnd(seed + i * 131) * TWO_PI
        speed = 2 if rnd(seed + i * 57) < 0.35 else 1
        field.append((r, theta, speed))

    out = []
    angle = 0.0
    idle_step = TWO_PI / idle_frames
    for k in range(resolve + idle_frames):
        if k < resolve:
            p = k / (resolve - 1)
            e = _smooth(p)
            u = 1 - e
            scale = e * (1 + zoom * 0.45 * sin_(p * 3 * PI) * (1 - p))
            phi = spin * TWO_PI * u * u
            omega = 0.08 + 0.55 * u
        else:
            scale, phi, omega = 1.0, 0.0, idle_step
        px = bytearray(W * H)

        for r, theta, speed in field:
            a = theta + angle * speed
            trail = min(omega * speed * smear * 1.5, TWO_PI * 0.9)
            steps = 1 + math.floor(trail * r)
            for j in range(steps):
                t = a - trail * j / steps
                x = math.floor(CX + r * cos_(t) + 0.5)
                y = math.floor(CY + r * sin_(t) + 0.5)
                if 0 <= x < W and 0 <= y < H:
                    px[y * W + x] = 1

        if scale > 0.02:
            c, s = cos_(phi), sin_(phi)
            lim = math.floor(reach * scale) + 2
            for y in range(max(0, math.floor(CY - lim)), min(H, math.floor(CY + lim) + 2)):
                for x in range(max(0, math.floor(CX - lim)), min(W, math.floor(CX + lim) + 2)):
                    u_, v_ = x - CX, y - CY
                    mx = (u_ * c + v_ * s) / scale
                    my = (v_ * c - u_ * s) / scale
                    if -hw <= mx <= hw and -hh <= my <= hh:
                        sx = math.floor(lcx + mx + 0.5)
                        sy = math.floor(lcy + my + 0.5)
                        on = 0 <= sx < W and 0 <= sy < H and lit(sx, sy)
                        px[y * W + x] = 1 if on else 0
        out.append(px)
        angle += omega
        if k == resolve - 1:
            angle = angle - TWO_PI * math.floor(angle / TWO_PI)   # the loop starts from here
    return out

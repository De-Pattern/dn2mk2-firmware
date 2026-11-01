"""v0.37: the start-up animation (by s!Rwa², the DN2MK2 community, 2026-11-01): 59 frames of
128 x 64, one bit, played over the intro in place of Elektron's tunnel.

`bootanim_dn2mk2.bin` holds the frames as the artist delivered them: 1,024 bytes a frame,
page-major (8 pages of 128 bytes, each byte a column of 8 pixels, bit 0 the top one).
DURATIONS_MS is the artist's timing, frame by frame.

The firmware gets an `ANIZ` chunk (scripts/gen_bootscreen_code.py decodes it):

    +0  u32 frames
    +4  u32 T                -- the table's length, in intro frames
    +8  T bytes              -- the frame to show at each intro frame (past T, the last)
    then, on a long boundary, each frame as its changes from the one before (the first from
    a blank frame): pairs (skip, n) -- step over `skip` longwords, then XOR the next `n`
    longwords with the n longwords that follow -- ended by (0, 0). A skip over 255 is
    written as (255, 0) pairs first.

Frames are in the intro source bitmap's layout (`bootscreen.image_from_pixels`), stored
upside down as the plain blit shows them (`bootscreen._images`).

The intro runs at about 30 frames a second (175 frames; on the owner's unit, 2026-09-18,
the ANIM path ran "more fluent than the GIF"), so intro frame f shows the frame playing at
f / 30 s by the artist's timing; past the animation's end, its last frame stays.
"""

from __future__ import annotations

import pathlib
import struct

W, H = 128, 64
FRAME_BYTES = 1024
INTRO_FPS = 30
INTRO_FRAMES = 175
CHUNK = b"ANIZ"
DURATIONS_MS = (160,) + (80,) * 43 + (170, 80, 160, 80, 160, 80, 80, 160) + (80,) * 6 + (240,)
SOURCE = pathlib.Path(__file__).with_name("bootanim_dn2mk2.bin")


def frames_pixels() -> list[set[tuple[int, int]]]:
    raw = SOURCE.read_bytes()
    n = len(raw) // FRAME_BYTES
    if n * FRAME_BYTES != len(raw) or n != len(DURATIONS_MS):
        raise ValueError(f"{SOURCE.name}: {len(raw)} bytes, {len(DURATIONS_MS)} durations")
    out = []
    for f in range(n):
        fr = raw[f * FRAME_BYTES:(f + 1) * FRAME_BYTES]
        out.append({(x, page * 8 + bit) for page in range(8) for x in range(W)
                    for bit in range(8) if fr[page * W + x] >> bit & 1})
    return out


def images() -> list[bytes]:
    from .mods import bootscreen as B
    return [B.image_from_pixels({(x, H - 1 - y) for x, y in lit}) for lit in frames_pixels()]


def delta(prev: bytes, cur: bytes) -> bytes:
    pw = struct.unpack(">256I", prev)
    cw = struct.unpack(">256I", cur)
    out = bytearray()
    i = 0
    while i < 256:
        j = i
        while j < 256 and pw[j] == cw[j]:
            j += 1
        if j == 256:
            break
        skip = j - i
        while skip > 255:
            out += bytes((255, 0))
            skip -= 255
        k = j
        while k < 256 and pw[k] != cw[k] and k - j < 255:
            k += 1
        if skip == 0 and k == j:            # (0, 0) is the end marker; never written for data
            raise AssertionError("an empty change")
        out += bytes((skip, k - j))
        for w in range(j, k):
            out += struct.pack(">I", pw[w] ^ cw[w])
        i = k
    return bytes(out + b"\0\0")


def table() -> bytes:
    """intro frame -> the animation frame to show, by the artist's timing at INTRO_FPS"""
    starts, t = [], 0
    for d in DURATIONS_MS:
        starts.append(t)
        t += d
    out = []
    for f in range(INTRO_FRAMES):
        ms = f * 1000 / INTRO_FPS
        k = max(i for i, s in enumerate(starts) if s <= ms)
        out.append(k)
    return bytes(out)


def chunk() -> bytes:
    ims = images()
    tab = table()
    body = struct.pack(">2I", len(ims), len(tab)) + tab
    body += bytes(-len(body) % 4)
    prev = bytes(FRAME_BYTES)
    for im in ims:
        body += delta(prev, im)
        prev = im
    return body


def decode(body: bytes) -> list[bytes]:
    """the chunk back to its frames, as the firmware's decoder walks it (the tests' check)"""
    n, t = struct.unpack_from(">2I", body, 0)
    at = (8 + t + 3) & ~3
    cur = [0] * 256
    out = []
    for _ in range(n):
        w = 0
        while True:
            skip, k = body[at], body[at + 1]
            at += 2
            if skip == 0 and k == 0:
                break
            w += skip
            for _ in range(k):
                cur[w] ^= struct.unpack_from(">I", body, at)[0]
                at += 4
                w += 1
        out.append(struct.pack(">256I", *cur))
    return out

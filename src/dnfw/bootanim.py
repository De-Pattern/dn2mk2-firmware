"""The start-up animation by s!Rwa² (the DN2MK2 community), played over the intro in place of
Elektron's tunnel: 128 x 64, one bit.

v0.39: his own frames, the 44 PBM files he made (2026-11-02), converted bit for bit;
frames 37..43 are one picture, kept once with their time, so 38 frames. (v0.37 shipped a
redraw of his design, made with another AI from his preview: not his frames.)

`bootanim_dn2mk2.json` holds them (base64): 1,024 bytes a frame, page-major (8 pages of 128
bytes, each byte a column of 8 pixels, bit 0 the top one), and the timing, frame by frame
(DURATIONS_MS here, checked against it): the first frame 160 ms, every other 80 ms, the last
held to the intro's end.

The firmware gets an `ANIZ` chunk (scripts/gen_bootscreen_code.py decodes it):

    +0  u32 frames
    +4  u32 T                -- the table's length, in intro frames
    +8  T bytes              -- the frame to show at each intro frame (past T, the last)
    then, on a long boundary, each frame as its changes from the one before (the first from
    a blank frame): pairs (skip, n) -- step over `skip` longwords, then XOR the next `n`
    longwords with the n longwords that follow -- ended by (0, 0). A skip over 255 is
    written as (255, 0) pairs first.

v0.39 (piece 4, the owner): the mod's version, `MOD 0.39` (dnfw.modversion), drawn by our
stamp over the LAST frame only, bottom right with a 1-pixel margin, in the project's 3 x 5
font (src/dnfw/font3x5.json): an `ANZL` chunk, `+0 u32 n`, then n pairs `(u32 longword
index, u32 mask)` the stamp ORs into the shown bitmap after it copies his frame in. His
frames in ANIZ are never changed; `shown()` is what the panel shows (his frame, plus the
label on the last), and the gate checks both.

Frames are in the intro source bitmap's layout (`bootscreen.image_from_pixels`), stored
upside down as the plain blit shows them (`bootscreen._images`).

The intro runs at about 30 frames a second (175 frames; on the owner's unit, 2026-09-18,
the ANIM path ran "more fluent than the GIF"), so intro frame f shows the frame playing at
f / 30 s by his timing; past the animation's end, its last frame stays.
"""

from __future__ import annotations

import pathlib
import struct

W, H = 128, 64
FRAME_BYTES = 1024
INTRO_FPS = 30
INTRO_FRAMES = 175
CHUNK = b"ANIZ"
DURATIONS_MS = (160,) + (80,) * 36 + (560,)          # (the last: frames 37..43's 7 x 80 ms, then held)
SOURCE = pathlib.Path(__file__).with_name("bootanim_dn2mk2.json")


def frames_pixels() -> list[set[tuple[int, int]]]:
    import base64
    import json
    doc = json.loads(SOURCE.read_text())
    raw = base64.b64decode(doc["data_base64"])
    if tuple(doc["durations_ms"]) != DURATIONS_MS:
        raise ValueError(f"{SOURCE.name}: the timing is not DURATIONS_MS")
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
    """intro frame -> the animation frame to show, by his timing at INTRO_FPS"""
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


LABEL_CHUNK = b"ANZL"


def label_text() -> str:
    from .modversion import mod_version
    return f"MOD {mod_version()}"


def label_pixels(text: str | None = None) -> set[tuple[int, int]]:
    """the label's lit pixels, (x, y) with y 0 the top as in the JSON: the 3 x 5 font, one
    column between characters, its last column at x 126 and its last row at y 62"""
    import json
    font = json.loads(pathlib.Path(__file__).with_name("font3x5.json").read_text())
    text = label_text() if text is None else text
    gw, gh = font["width"], font["height"]
    width = len(text) * (gw + 1) - 1
    x0, y0 = W - 1 - width, H - 1 - gh
    out = set()
    for i, ch in enumerate(text):
        rows = font["glyphs"][ch]
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == "1":
                    out.add((x0 + i * (gw + 1) + c, y0 + r))
    return out


def label_clear(text: str | None = None) -> None:
    """refuses a label that would touch his last frame's drawing (its box and a pixel round it)"""
    lit = frames_pixels()[-1]
    lab = label_pixels(text)
    lx0, lx1 = min(x for x, _ in lab) - 1, max(x for x, _ in lab) + 1
    ly0, ly1 = min(y for _, y in lab) - 1, max(y for _, y in lab) + 1
    hit = [(x, y) for x, y in lit if lx0 <= x <= lx1 and ly0 <= y <= ly1]
    if hit or lx1 > W or ly1 > H or lx0 < -1:
        raise ValueError(f"the version label {sorted(lab)[:2]}.. would touch the last frame at {hit[:4]}")


def label_chunk() -> bytes:
    from .mods import bootscreen as B
    label_clear()
    im = B.image_from_pixels({(x, H - 1 - y) for x, y in label_pixels()})
    words = struct.unpack(">256I", im)
    pairs = [(i, w) for i, w in enumerate(words) if w]
    return struct.pack(">I", len(pairs)) + b"".join(struct.pack(">2I", i, w) for i, w in pairs)


def shown() -> list[bytes]:
    """what the panel shows for each frame: his frame, and on the last the label ORed over it"""
    ims = images()
    n, *_ = struct.unpack_from(">I", label_chunk())
    body = label_chunk()
    last = bytearray(ims[-1])
    for k in range(n):
        i, w = struct.unpack_from(">2I", body, 4 + 8 * k)
        v = struct.unpack_from(">I", last, 4 * i)[0] | w
        struct.pack_into(">I", last, 4 * i, v)
    return ims[:-1] + [bytes(last)]


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

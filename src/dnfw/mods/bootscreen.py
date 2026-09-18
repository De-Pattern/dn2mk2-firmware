"""The boot screen: your mark in the intro, static or flashing, and the tunnel's density.

Everything shown between power-on and the OS is one mod, because every change to
it goes through the same two hooks -- the startup call that copies appended data
up before the BSS clear, and the intro copy routine. Two boot-screen mods would
collide by construction, so there is one, with options.

## What the user chooses, and it is all data

| option | what it does |
|---|---|
| `images` | one or two whole 128 x 64 marks. One is held for the whole intro; two alternate |
| `slow`, `fast`, `rush`, `stop` | the flashing: alternate every `2^slow` frames, every `2^fast` from frame `rush`, hold image 0 from `stop` |
| `tunnel` | the tunnel's texture scale, stock `(128.0, 64.0)` -- larger tiles the mark more densely |

The code is fixed and assembled ahead of time (`scripts/gen_bootscreen_code.py`
-> `bootscreen_code.json`), so the browser applies exactly the same bytes this
does. Every choice above lands in a `BOOT` chunk of the appended data area.

## How it works, and how it was proven

- The intro is a polar tunnel sampling a **source bitmap** (`docs/display-path.md`).
  Each frame the stamp copies the chosen image over that bitmap, keyed on the
  intro's own frame counter, so the mark is scattered by the tunnel like the logo.
- The images are **appended past the end of MAIN OS** and copied above BSS at
  boot. Bigger than any free cave, so it has to be.
- **Seen under the emulator** frame by frame against stock, and **on the
  instrument on 2026-09-17**: the owner's Digitone II booted and played the
  animation.

## The one rule this mod relaxes

`dnfw.mods` says no section's unpacked length may change. That rule exists
because addresses after a resize move. Appending **after the last byte** of MAIN
OS moves nothing, since nothing addresses that space but this mod's own boot
hook. So MAIN OS may grow, **only** through the shared area at `area_va`, and this
mod refuses an image that already has one rather than overwriting it -- merging
chunks from several data mods is the next step, not a silent collision.

## What it cannot yet do

Knock the Elektron logo out of a mark: that needs the logo's pixels, which must
come from the user's own firmware rather than from this repository, and where the
firmware keeps them is being traced. Until then a mark is whatever image the user
supplies.
"""

from __future__ import annotations

import json
import pathlib
import struct

from . import Extent, ModError, Result

ID = "bootscreen"
NAME = "Boot screen"
SUMMARY = "Your own mark in the start-up animation, static or flashing, and the tunnel's density."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS

W, H = 128, 64
IMAGE_BYTES = 1024
STOCK_TUNNEL = (128.0, 64.0)

SPEC = json.loads((pathlib.Path(__file__).with_name("bootscreen_code.json")).read_text())
BASE = 0x40000400


def image_from_pixels(lit) -> bytes:
    """128 x 64 lit pixels -> the 1,024 bytes the source bitmap holds.

    Column-major, two longwords per column: pixel (x, y) is bit `31 - (y & 31)`
    of longword `x * 2 + (y >> 5)`. That is the layout the firmware's own
    `setPixel` writes, measured, not assumed.
    """
    words = [0] * SPEC["words"]
    for x, y in lit:
        if not (0 <= x < W and 0 <= y < H):
            raise ModError(f"pixel ({x}, {y}) is off the {W} x {H} panel")
        words[x * 2 + (y >> 5)] |= 0x80000000 >> (y & 31)
    return struct.pack(f">{SPEC['words']}I", *words)


def invert(image: bytes) -> bytes:
    return bytes((~b) & 0xFF for b in image)


def boot_chunk(images: list[bytes], slow: int, fast: int, rush: int, stop: int) -> bytes:
    if not 1 <= len(images) <= 2:
        raise ModError("a boot screen has one image (static) or two (flashing)")
    for img in images:
        if len(img) != IMAGE_BYTES:
            raise ModError(f"an image is {len(img)} bytes, not {IMAGE_BYTES}")
    for name, v in (("slow", slow), ("fast", fast)):
        if not 0 <= v <= 16:
            raise ModError(f"{name} must be a shift of 0..16 frames, got {v}")
    if not 0 <= rush <= stop:
        raise ModError(f"rush ({rush}) must not come after stop ({stop})")
    return struct.pack(">5I", len(images), slow, fast, rush, stop) + b"".join(images)


def anim_chunk(frames: list[bytes], loop_start: int) -> bytes:
    """The ANIM chunk -- any animation drawn ahead of time: u32 frames, u32 loop start, then each frame as a whole
    1,024-byte source bitmap. Past the last frame the intro loops from
    `loop_start`, so the settled picture keeps its residual glitch."""
    if not frames:
        raise ModError("an ASCII animation needs at least one frame")
    for img in frames:
        if len(img) != IMAGE_BYTES:
            raise ModError(f"a frame is {len(img)} bytes, not {IMAGE_BYTES}")
    if not 0 <= loop_start < len(frames):
        raise ModError(f"loop start {loop_start} is not a frame of {len(frames)}")
    return struct.pack(">2I", len(frames), loop_start) + b"".join(frames)


def ascii_frames(lit, **options) -> tuple[list[bytes], int]:
    """The mark as a glitching ASCII animation: (frames as images, loop start).
    `options` are `dnfw.asciiglitch.frames`'s."""
    from .. import asciiglitch
    try:
        grids = asciiglitch.frames(lit, **options)
    except asciiglitch.GlitchError as exc:
        raise ModError(str(exc)) from None
    images = _images(grids, asciiglitch.W)
    resolve = options.get("resolve", 40)
    return images, min(resolve, len(images) - 1)


def _images(grids, W: int) -> list[bytes]:
    """Frames -> images for the ANIM chunk, stored upside down: the plain blit
    that shows them (`0x401157fc`) turns the source over vertically, where the
    tunnel's sampler does not. Measured under the emulator, which runs the
    firmware's own blit, 2026-09-18."""
    return [image_from_pixels({(i % W, H - 1 - i // W) for i, v in enumerate(g) if v}) for g in grids]


def spin_frames(lit, **options) -> tuple[list[bytes], int]:
    """The mark as a 1966-style spinning transition: (frames as images, loop start).
    `options` are `dnfw.batspin.frames`'s."""
    from .. import batspin
    try:
        grids = batspin.frames(lit, **options)
    except batspin.SpinError as exc:
        raise ModError(str(exc)) from None
    return _images(grids, batspin.W), options.get("resolve", 120)


def area(chunks: list[tuple[bytes, bytes]]) -> bytes:
    """The shared appended area: 'DNFW', total length, a directory, the chunks."""
    head = 12 + 12 * len(chunks)
    directory, body, offset = b"", b"", head
    for cid, data in chunks:
        if len(cid) != 4:
            raise ModError(f"chunk id {cid!r} is not four bytes")
        pad = bytes(-len(data) % 4)
        directory += cid + struct.pack(">II", offset, len(data))
        body += data + pad
        offset += len(data) + len(pad)
    blob = SPEC["magic"].encode() + struct.pack(">II", head + len(body), len(chunks)) + directory + body
    return blob


def extents(firmware, area_length: int = 0) -> list[Extent]:
    off = lambda va: va - BASE
    out = [
        Extent(SECTION, off(SPEC["calls_va"]), 8, "startup hook: copy the appended area up"),
        Extent(SECTION, off(SPEC["intro_va"]), 8, "intro hook: the mark"),
        Extent(SECTION, off(SPEC["cave"]), len(bytes.fromhex(SPEC["code"])), "boot-screen code"),
        Extent(SECTION, off(SPEC["tunnel_x_va"]) + 2, 4, "tunnel scale x"),
        Extent(SECTION, off(SPEC["tunnel_y_va"]) + 2, 4, "tunnel scale y"),
    ]
    if area_length:
        out.append(Extent(SECTION, off(SPEC["area_va"]), area_length, "appended data area"))
    return out


def apply(firmware, images: list[bytes], slow: int = 4, fast: int = 3,
          rush: int = 48, stop: int = 72,
          tunnel: tuple[float, float] = STOCK_TUNNEL,
          ascii: tuple[list[bytes], int] | None = None) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    content = bytearray(section.unpack())

    if BASE + len(content) != SPEC["area_va"]:
        raise ModError(
            f"MAIN OS ends at 0x{BASE + len(content):08x}, not 0x{SPEC['area_va']:08x}: "
            "either not Digitone II 1.11, or another mod has already appended data")
    for va, stock, what in ((SPEC["calls_va"], SPEC["calls_stock"], "startup calls"),
                            (SPEC["intro_va"], SPEC["intro_stock"], "intro copy routine")):
        have = bytes(content[va - BASE:va - BASE + 8]).hex()
        if have != stock:
            raise ModError(f"0x{va:08x} holds {have}, not {stock} ({what}); "
                           "this mod is for Digitone II 1.11")
    code = bytes.fromhex(SPEC["code"])
    cave = SPEC["cave"] - BASE
    if any(content[cave:cave + SPEC["cave_cap"]]):
        raise ModError("the boot-screen code space is already in use by another mod")
    for va, stock_scale in ((SPEC["tunnel_x_va"], STOCK_TUNNEL[0]), (SPEC["tunnel_y_va"], STOCK_TUNNEL[1])):
        have = bytes(content[va - BASE:va - BASE + 6])
        if have[2:] != struct.pack(">f", stock_scale):
            raise ModError(f"tunnel scale at 0x{va:08x} is not stock ({have.hex()})")

    chunks = []
    if ascii is not None:
        chunks.append((SPEC["anim_chunk"].encode(), anim_chunk(*ascii)))
    if images:
        chunks.append((SPEC["boot_chunk"].encode(), boot_chunk(images, slow, fast, rush, stop)))
    if not chunks:
        raise ModError("give a mark (images) or an ASCII animation")
    blob = area(chunks)

    content[cave:cave + len(code)] = code
    jsr = b"\x4e\xb9" + struct.pack(">I", SPEC["boot"]) + b"\x4e\x71"
    jmp = b"\x4e\xf9" + struct.pack(">I", SPEC["stamp"]) + b"\x4e\x71"
    content[SPEC["calls_va"] - BASE:SPEC["calls_va"] - BASE + 8] = jsr
    content[SPEC["intro_va"] - BASE:SPEC["intro_va"] - BASE + 8] = jmp
    for va, scale in ((SPEC["tunnel_x_va"], tunnel[0]), (SPEC["tunnel_y_va"], tunnel[1])):
        if not 1.0 <= scale <= 65536.0:
            raise ModError(f"tunnel scale {scale} is outside 1..65536")
        content[va - BASE + 2:va - BASE + 6] = struct.pack(">f", scale)
    content += blob + bytes(-len(blob) % 4)

    notes = [(f"animation: {len(ascii[0])} frames, looping from {ascii[1]}" if ascii is not None else
              f"{len(images)} image(s), " + ("static" if len(images) == 1 else
              f"flashing every 2^{slow} then 2^{fast} frames from {rush}, held from {stop}")),
             f"appended data area {len(blob):,} B; MAIN OS {len(content):,} B",
             f"tunnel scale {tunnel[0]:g} x {tunnel[1]:g}" + (" (stock)" if tuple(tunnel) == STOCK_TUNNEL else "")]
    return Result({SECTION: bytes(content)}, extents(firmware, len(blob)), notes)

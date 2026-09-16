"""The bang flashes, then explodes into the tunnel.

The owner, 2026-09-17: *"maybe the bang can flash reversing black and white
backgrounds until it explodes and shows the tunnel"*. This builds on
`build_intro_burst.py` (the Elektron logo knocked out of a comic burst, written
into the intro's source bitmap) and adds time.

## What the emulator measured, which sets the timing

The intro copy routine at `0x400d3886` takes a **frame counter** as its first
argument: from a 380M snapshot it counted 1, 2, 3 ... up by exactly one per call.
Filmed with the static burst (`docs/img/intro-burst-film.png`):

- frames **~12 to ~73** show the bang whole and still;
- by frame **~87** the tunnel has started to scatter it -- the explosion;
- after that the tunnel is textured with spiralling fragments of the burst.

So "until it explodes" is a frame number, and no other clock is needed.

## The build

The payload now carries **two whole 128 x 64 images**, 1,024 bytes each: the burst
as `build_intro_burst.py` draws it (white burst, black logo on black), and its
exact inverse (a white screen, black burst, white logo -- which is the reference
image the owner sent). Every frame, before the copy runs, the stamp copies one of
them over the whole source bitmap:

| frame | image |
|---|---|
| `< RUSH` | alternates every `2^SLOW` frames |
| `RUSH .. STOP` | alternates every `2^FAST` frames -- the build-up |
| `>= STOP` | the normal burst, held, so the tunnel's scatter is the explosion |

Writing the whole bitmap rather than a masked region is what makes the inverse
possible, and it is simpler than masks: one 256-longword copy.

## Photosensitivity

Whole-screen flashing between 3 and 30 Hz is the range that matters. At the
intro's frame rate (the display tick is about 30 Hz) the defaults alternate at
roughly 1.9 Hz and then 3.75 Hz. Raise `--slow`/`--fast` to flash less.

    python scripts/build_intro_bang.py --logo out/bootdraw/dn2-source.pgm
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import build_intro_burst as burst
import build_intro_stamp as stamp
import build_payload_section as payload
from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400
W, H = 128, 64
WORDS = W * stamp.SOURCE_STRIDE             # 256 longwords of pixel data
OUT = pathlib.Path("00_Resources/02_Builds/intro-bang_DN2_1.11.syx")


def image_words(lit: set[tuple[int, int]]) -> list[int]:
    words = [0] * WORDS
    for x, y in lit:
        words[x * stamp.SOURCE_STRIDE + (y >> 5)] |= 0x80000000 >> (y & 31)
    return words


def source(payload_va: int, slow: int, fast: int, rush: int, stop: int) -> str:
    rt = payload.RUNTIME_VA
    magic = int.from_bytes(payload.MAGIC, "big")
    return payload.boot_source(payload_va).split("stamp:")[0] + f"""
stamp:
    move.l  {rt:#010x},%d0
    cmpi.l  #{magic:#010x},%d0
    bne.s   9f                               | no payload: the intro stays stock
    move.l  {stamp.SOURCE_DATA_PTR:#010x},%d0
    beq.s   9f
    movea.l %d0,%a0                          | the source bitmap's pixels
    lea     {rt + 8:#010x},%a1               | the normal burst
    move.l  %sp@(4),%d0                      | the intro's frame counter
    cmpi.l  #{stop},%d0
    bcc.s   5f                               | exploded: hold the normal image
    move.l  %d0,%d1
    cmpi.l  #{rush},%d0
    bcc.s   2f
    lsr.l   #{slow},%d1                      | slow alternation
    bra.s   3f
2:  lsr.l   #{fast},%d1                      | the build-up
3:  btst    #0,%d1
    beq.s   5f
    lea     {rt + 8 + 4 * WORDS:#010x},%a1   | the inverse
5:  move.l  #{WORDS},%d1
6:  move.l  %a1@+,%a0@+
    subq.l  #1,%d1
    bne.s   6b
9:  lea     %sp@(-60),%sp
    moveml  %d2-%d7/%a2-%fp,%sp@
    jmp     {stamp.RESUME_VA:#010x}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logo", type=pathlib.Path, required=True)
    ap.add_argument("--slow", type=int, default=4, help="alternate every 2^N frames early (default 4)")
    ap.add_argument("--fast", type=int, default=3, help="alternate every 2^N frames in the build-up (default 3)")
    ap.add_argument("--rush", type=int, default=48, help="frame the build-up starts (default 48)")
    ap.add_argument("--stop", type=int, default=72, help="frame the flashing stops (default 72)")
    ap.add_argument("--preview", type=pathlib.Path, help="write both images side by side as PNG")
    args = ap.parse_args()
    for name in ("slow", "fast"):
        if not 1 <= getattr(args, name) <= 8:
            raise SystemExit(f"--{name} must be 1..8 (a shift count)")
    if not 0 < args.rush <= args.stop:
        raise SystemExit("--rush must be after frame 0 and not after --stop")
    if not available():
        raise SystemExit("no m68k assembler found (WSL is fine)")

    logo = burst.load_logo(args.logo)
    region, lit = burst.rasterise("knockout", logo)
    if logo - region:
        raise SystemExit("logo pixels fall outside the burst")
    normal = image_words(lit)                       # black screen, white burst, black logo
    inverse = [(~w) & 0xFFFFFFFF for w in normal]   # white screen, black burst, white logo
    data = struct.pack(f">{WORDS}I", *normal) + struct.pack(f">{WORDS}I", *inverse)

    if args.preview:
        from PIL import Image
        im = Image.new("L", (W * 2 + 4, H), 60)
        for x, y in lit:
            im.putpixel((x, y), 235)
        for y in range(H):
            for x in range(W):
                im.putpixel((W + 4 + x, y), 8 if (x, y) in lit else 235)
        im.resize((im.width * 5, H * 5), Image.NEAREST).save(args.preview)

    firmware = load(read_image(stamp.STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())
    for va, want, what in ((payload.CALLS_VA, payload.CALLS_STOCK, "startup calls"),
                           (stamp.HOOK_VA, stamp.HOOK_STOCK, "intro copy routine")):
        have = bytes(content[va - BASE:va - BASE + len(want)])
        if have != want:
            raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({what})")
    if any(content[payload.CAVE - BASE:payload.CAVE - BASE + payload.CAVE_CAP]):
        raise SystemExit("cave is not free")
    payload_va = BASE + len(content)
    if payload_va != payload.INIT_TAIL_VA:
        raise SystemExit(f"MAIN OS ends at {payload_va:#010x}, not at the initialiser tail")

    blob = payload.MAGIC + struct.pack(">I", len(data)) + data
    content += blob + bytes(-len(blob) % 4)

    text = source(payload_va, args.slow, args.fast, args.rush, args.stop)
    code_blob = assemble(text + "\n    .align 2\n    .long boot\n    .long stamp\n", base=payload.CAVE)
    code, (boot_va, stamp_va) = code_blob[:-8], struct.unpack(">II", code_blob[-8:])
    if len(code) > payload.CAVE_CAP:
        raise SystemExit("cave overflows")
    content[payload.CAVE - BASE:payload.CAVE - BASE + len(code)] = code
    content[payload.CALLS_VA - BASE:payload.CALLS_VA - BASE + 8] = \
        b"\x4e\xb9" + struct.pack(">I", boot_va) + b"\x4e\x71"
    content[stamp.HOOK_VA - BASE:stamp.HOOK_VA - BASE + 8] = \
        b"\x4e\xf9" + struct.pack(">I", stamp_va) + b"\x4e\x71"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"payload {len(blob)} B; stubs {len(code)} B; flash every 2^{args.slow} then "
          f"2^{args.fast} frames from {args.rush}, hold from {args.stop}")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes), MAIN OS {len(content):,} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

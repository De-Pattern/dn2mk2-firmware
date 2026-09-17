"""The Elektron logo inside a comic "BANG" burst, animated with the intro.

Asked for by the owner, 2026-09-17: instead of `MOD` beside the logo, wrap the
logo in a bang-style burst -- the comic explosion glyph with the word replaced by
the Elektron mark -- and make it part of the intro's animation.

## Why it animates for free

The start-up screen is a polar tunnel that samples a **source bitmap** for every
panel pixel (`docs/display-path.md`). Anything drawn into that source is texture:
the tunnel scatters it through the fly-through and the final pass resolves it.
So the burst is written into the source, every frame, before the copy routine
runs -- the same hook as `build_intro_stamp.py`.

## Why it is a knockout, and why that costs a payload

The reference is a black burst with white lettering on a white page. The panel is
black, so the faithful inversion is a **solid white burst with the logo knocked
out in black**. A knockout must clear bits as well as set them, so each 32-pixel
column word gets a mask and a value, applied idempotently every frame:

    word = (word & ~mask) | value      mask = burst,  value = burst & ~logo

Idempotent is the point: the stamp runs every frame over the same persistent
bitmap, and an XOR would flicker. The price is 12 bytes per touched word -- about
2,100 bytes, against a largest free cave of 896. So the table ships **appended to
MAIN OS** and is copied above BSS at boot, the mechanism
`build_payload_section.py` proved end to end under the emulator.

## Inputs

`--logo` is the stock source bitmap as a PGM, dumped from an emulator snapshot by
`scripts/dump_bitmap.py` -- needed to compute the knockout, and read from `out/`
at build time so no firmware-derived image is kept in the repository.

    python scripts/build_intro_burst.py --logo out/bootdraw/dn2-source.pgm
    python scripts/build_intro_burst.py --logo ... --style outline   # white logo, outline burst
"""

from __future__ import annotations

import argparse
import math
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

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
OUT = pathlib.Path("00_Resources/02_Builds/intro-burst_DN2_1.11.syx")

# The burst: 14 spikes of irregular length around the logo's centre. The inner
# radius clears the logo's 32 x 24 box (it needs about 22 x 16); the tips reach
# close to the panel's edges.
CENTRE = (63.5, 31.5)
INNER = (26, 17)
OUTER = [(46, 31), (40, 26), (50, 30), (38, 24), (47, 29), (42, 27), (52, 31),
         (41, 25), (48, 30), (39, 23), (50, 29), (43, 26), (47, 31), (40, 24)]
ROTATION = 0.12


def burst_polygon() -> list[tuple[float, float]]:
    cx, cy = CENTRE
    n, pts = len(OUTER), []
    for i, (rx, ry) in enumerate(OUTER):
        a = 2 * math.pi * i / n - math.pi / 2 + ROTATION
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        b = a + math.pi / n
        pts.append((cx + INNER[0] * math.cos(b), cy + INNER[1] * math.sin(b)))
    return pts


def load_logo(path: pathlib.Path) -> set[tuple[int, int]]:
    """Lit pixels of a 128 x 64 binary PGM, thresholded -- never dithered."""
    raw = path.read_bytes()
    parts = raw.split(maxsplit=4)
    if parts[0] != b"P5" or int(parts[1]) != W or int(parts[2]) != H:
        raise SystemExit(f"{path}: expected a {W} x {H} P5 PGM")
    pix = parts[4]
    return {(x, y) for y in range(H) for x in range(W) if pix[y * W + x] > 127}


def rasterise(style: str, logo: set[tuple[int, int]]) -> tuple[set, set]:
    """-> (region the stamp owns, pixels lit inside it)."""
    from PIL import Image, ImageDraw
    fill = Image.new("1", (W, H), 0)
    ImageDraw.Draw(fill).polygon(burst_polygon(), fill=1, outline=1)
    region = {(x, y) for y in range(H) for x in range(W) if fill.getpixel((x, y))}
    if style == "knockout":
        return region, region - logo
    edge = Image.new("1", (W, H), 0)
    ImageDraw.Draw(edge).polygon(burst_polygon(), fill=0, outline=1)
    outline = {(x, y) for y in range(H) for x in range(W) if edge.getpixel((x, y))}
    return region, outline | (logo & region)


def table(region: set, lit: set) -> bytes:
    """(offset, ~mask, value) per touched longword, then a -1 sentinel."""
    words: dict[int, list[int]] = {}
    for x, y in region:
        off = 4 * (x * stamp.SOURCE_STRIDE + (y >> 5))
        bit = 0x80000000 >> (y & 31)
        entry = words.setdefault(off, [0, 0])
        entry[0] |= bit
        if (x, y) in lit:
            entry[1] |= bit
    out = b"".join(struct.pack(">III", off, (~m) & 0xFFFFFFFF, v)
                   for off, (m, v) in sorted(words.items()))
    return out + struct.pack(">I", 0xFFFFFFFF)


def source(payload_va: int) -> str:
    rt = payload.RUNTIME_VA
    magic = int.from_bytes(payload.MAGIC, "big")
    return payload.boot_source(payload_va).split("stamp:")[0] + f"""
stamp:
    move.l  {rt:#010x},%d0
    cmpi.l  #{magic:#010x},%d0
    bne.s   2f                               | no payload: the intro stays stock
    move.l  {stamp.SOURCE_DATA_PTR:#010x},%d0
    beq.s   2f
    movea.l %d0,%a0
    lea     {rt + 8:#010x},%a1
1:  move.l  %a1@+,%d0                        | offset, or -1
    bmi.s   2f
    move.l  %a1@+,%d1                        | ~mask
    and.l   %d1,%a0@(0,%d0:l)
    move.l  %a1@+,%d1                        | value
    or.l    %d1,%a0@(0,%d0:l)
    bra.s   1b
2:  lea     %sp@(-60),%sp
    moveml  %d2-%d7/%a2-%fp,%sp@
    jmp     {stamp.RESUME_VA:#010x}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logo", type=pathlib.Path, required=True)
    ap.add_argument("--style", choices=("knockout", "outline"), default="knockout")
    ap.add_argument("--preview", type=pathlib.Path, help="also write the expected source as PNG")
    args = ap.parse_args()
    if not available():
        raise SystemExit("no m68k assembler found (WSL is fine)")

    logo = load_logo(args.logo)
    region, lit = rasterise(args.style, logo)
    missing = logo - region
    if missing:
        raise SystemExit(f"{len(missing)} logo pixels fall outside the burst; widen INNER")
    blob = table(region, lit)
    print(f"part 1 -- {args.style}: region {len(region)} px, lit {len(lit)} px, "
          f"logo {len(logo)} px; table {len(blob)} B")

    if args.preview:
        from PIL import Image
        expected = (set(logo) - region) | lit
        im = Image.new("L", (W, H), 8)
        for x, y in expected:
            im.putpixel((x, y), 235)
        im.resize((W * 6, H * 6), Image.NEAREST).save(args.preview)

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
    data = payload.MAGIC + struct.pack(">I", len(blob)) + blob
    content += data + bytes(-len(data) % 4)

    labels_text = "\n    .align 2\n    .long boot\n    .long stamp\n"
    blob_code = assemble(source(payload_va) + labels_text, base=payload.CAVE)
    code, (boot_va, stamp_va) = blob_code[:-8], struct.unpack(">II", blob_code[-8:])
    if len(code) > payload.CAVE_CAP:
        raise SystemExit("cave overflows")
    content[payload.CAVE - BASE:payload.CAVE - BASE + len(code)] = code
    content[payload.CALLS_VA - BASE:payload.CALLS_VA - BASE + 8] = \
        b"\x4e\xb9" + struct.pack(">I", boot_va) + b"\x4e\x71"
    content[stamp.HOOK_VA - BASE:stamp.HOOK_VA - BASE + 8] = \
        b"\x4e\xf9" + struct.pack(">I", stamp_va) + b"\x4e\x71"
    print(f"part 2 -- payload {len(data)} B at {payload_va:#010x}; stubs {len(code)} B "
          f"(boot {boot_va:#010x}, stamp {stamp_va:#010x})")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"part 3 -- wrote {OUT} ({OUT.stat().st_size} bytes), MAIN OS {len(content):,} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

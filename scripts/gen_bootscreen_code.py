"""Assemble the boot-screen mod's fixed code once, for Python and the browser.

The site cannot run an m68k assembler, so everything a user chooses on the boot
screen -- images, timing, text -- is **data**, and the code that reads it is
assembled here, ahead of time, into one JSON file both implementations load:

    src/dnfw/mods/bootscreen_code.json     <- this script writes it
    site/js/mods/bootscreen-code.js        <- and a copy the static site can import

Run it after changing any stub. `test/test_bootscreen_code.py` re-assembles and
fails if the committed bytes are stale, so the two files cannot silently drift
from the source below. The bytes are this project's own code, not firmware.

## The shared appended area

A mod that ships data appends it past the end of MAIN OS (`0x4030b980` on 1.11,
where the `.data` initialiser stops reading). One boot hook copies the **whole**
area above BSS to `0x46710000` before the clear -- proven under the emulator and,
on 2026-09-17, on the instrument. So that several data mods can share that one
hook, the area is a directory of chunks:

    +0   'DNFW'
    +4   u32 total length, header included
    +8   u32 chunk count
    +12  per chunk: 4-byte id, u32 offset from the area's start, u32 length

## The BOOT chunk

    +0   u32 images, 1 or 2
    +4   u32 slow shift   -- alternate every 2^slow frames before `rush`
    +8   u32 fast shift   -- then every 2^fast frames
    +12  u32 rush frame
    +16  u32 stop frame   -- from here, image 0 is held
    +20  images x 1024 bytes, each a whole 128 x 64 source bitmap (256 longwords)

One image means a static mark; two means the flashing build-up. Every frame, the
stamp copies the chosen image over the intro's source bitmap, before the copy
routine displaces it through the tunnel.

## The ANIM chunk -- an animation drawn ahead of time

    +0   u32 frames
    +4   u32 loop start   -- past the last frame, play from here again
    +8   frames x 1024 bytes, each a whole 128 x 64 bitmap in the source's layout

Used by the ASCII glitch (`dnfw.asciiglitch`) and the 1966 spin (`dnfw.batspin`),
and by anything else that can be drawn at build time. When present it wins over
BOOT: the stamp runs the stock intro routine whole (so the source bitmap exists
and the frame counter advances exactly as stock), then copies frame `n` into the
source and blits it plainly over the panel -- the intro's own copy for frames
0-4, `0x40114d94` then `0x401157fc`. The tunnel's output is simply overwritten.
The routine is called through `0x4028c154` and nothing reads its result.

On 1.11 the intro routine's second argument is the intro's length: 175 frames
under the emulator from `boot400M`.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from dnfw.patch.assemble import assemble, available

# --- the 1.11 sites, each checked against stock bytes when the mod applies ---
INIT_VA, CLEAR_VA = 0x4000045C, 0x400004B2
CALLS_VA = 0x4000053E
CALLS_STOCK = "4ebaff1c4ebaff6e"             # jsr init ; jsr clear
INTRO_VA = 0x400D3886
INTRO_STOCK = "4fefffc448d77cfc"             # lea -60(sp),sp ; moveml
RESUME_VA = 0x400D388E
SOURCE_DATA_PTR = 0x42C4567C + 16            # the intro's source Bitmap data pointer
AREA_VA = 0x4030B980                         # where appended data starts
RUNTIME_VA = 0x46710000                      # where the boot hook copies it
CAVE = 0x402DFA1C
CAVE_CAP = 896
MAGIC = b"DNFW"
BOOT = b"BOOT"
ANIM = b"ANIM"
SOURCE_OBJ = 0x42C4567C                      # the intro's source Bitmap
CLEAR_BITMAP = 0x40114D94                    # (bitmap, 0, 1): what the intro calls first
BLIT = 0x401157FC                            # (dst, src, 0, 0, 0): its plain copy, frames 0-4
WORDS = 256

SOURCE = f"""
    .text
| ---- boot: run the .data initialiser, copy the appended area up, clear BSS ----
boot:
    jsr     {INIT_VA:#010x}
    lea     {AREA_VA:#010x},%a0
    move.l  %a0@,%d0
    cmpi.l  #{int.from_bytes(MAGIC, 'big'):#010x},%d0
    bne.s   2f                          | nothing appended: boot as stock
    lea     {RUNTIME_VA:#010x},%a1
    move.l  %a0@(4),%d0                 | total length, header included
1:  move.b  %a0@+,%a1@+
    subq.l  #1,%d0
    bne.s   1b
2:  jsr     {CLEAR_VA:#010x}
    rts

| ---- stamp: an ANIM chunk plays frames; else a BOOT image goes over the source ----
stamp:
    move.l  {RUNTIME_VA:#010x},%d0
    cmpi.l  #{int.from_bytes(MAGIC, 'big'):#010x},%d0
    bne     9f                          | no appended area: stock intro
    lea     %sp@(-12),%sp
    moveml  %d2-%d4,%sp@                | the intro's args now at 16, 20, 24
    lea     {RUNTIME_VA + 8:#010x},%a1
    move.l  %a1@+,%d1                   | chunk count
1:  subq.l  #1,%d1
    bmi     8f                          | neither chunk: stock intro
    move.l  %a1@,%d0
    cmpi.l  #{int.from_bytes(ANIM, 'big'):#010x},%d0
    beq     20f
    cmpi.l  #{int.from_bytes(BOOT, 'big'):#010x},%d0
    beq.s   2f
    lea     %a1@(12),%a1
    bra.s   1b
2:  move.l  %a1@(4),%d0                 | the chunk's offset
    lea     {RUNTIME_VA:#010x},%a1
    adda.l  %d0,%a1
    move.l  {SOURCE_DATA_PTR:#010x},%d0
    beq.s   8f                          | bitmap not built yet
    movea.l %d0,%a0
    move.l  %a1@,%d2                    | image count
    move.l  %sp@(16),%d0                | the intro's frame counter
    cmpi.l  #2,%d2
    bcs.s   5f                          | one image: static
    cmp.l   %a1@(16),%d0
    bcc.s   5f                          | past stop: hold image 0
    move.l  %a1@(4),%d3                 | slow shift
    cmp.l   %a1@(12),%d0
    bcs.s   3f                          | before rush
    move.l  %a1@(8),%d3                 | fast shift
3:  lsr.l   %d3,%d0
    btst    #0,%d0
    beq.s   5f
    lea     %a1@({20 + 4 * WORDS}),%a1  | image 1
    bra.s   6f
5:  lea     %a1@(20),%a1                | image 0
6:  move.l  #{WORDS},%d1
7:  move.l  %a1@+,%a0@+
    subq.l  #1,%d1
    bne.s   7b
8:  moveml  %sp@,%d2-%d4
    lea     %sp@(12),%sp
9:  lea     %sp@(-60),%sp
    moveml  %d2-%d7/%a2-%fp,%sp@
    jmp     {RESUME_VA:#010x}

| ANIM: run the stock routine whole (it builds the source bitmap and draws the
| tunnel), then put this frame in the source and blit it plainly over the panel,
| as stock does for its first five frames. Past the last frame, loop from
| `loop start`.
20: move.l  %a1@(4),%d4
    addi.l  #{RUNTIME_VA:#010x},%d4     | the chunk, kept across the call
    move.l  %sp@(24),%sp@-              | panel
    move.l  %sp@(24),%sp@-              | second argument
    move.l  %sp@(24),%sp@-              | frame counter
    bsr     9b                          | the stock intro routine
    lea     %sp@(12),%sp
    move.l  {SOURCE_DATA_PTR:#010x},%d0
    beq     30f                         | bitmap not built: leave stock's frame
    movea.l %d0,%a0
    movea.l %d4,%a1
    move.l  %sp@(16),%d0                | frame counter
    move.l  %a1@,%d1                    | frames
    cmp.l   %d1,%d0
    bcs.s   21f
    move.l  %a1@(4),%d3                 | loop start
    move.l  %d1,%d2
    sub.l   %d3,%d2                     | loop length, at least 1
    sub.l   %d3,%d0
    remul   %d2,%d1:%d0                 | d1 = d0 mod d2
    add.l   %d3,%d1
    move.l  %d1,%d0
21: moveq   #10,%d1
    lsl.l   %d1,%d0                     | x 1024
    lea     %a1@(8,%d0:l),%a1
    move.l  #{WORDS},%d1
22: move.l  %a1@+,%a0@+
    subq.l  #1,%d1
    bne.s   22b
    pea     1
    clr.l   %sp@-
    move.l  %sp@(32),%sp@-              | panel
    jsr     {CLEAR_BITMAP:#010x}
    lea     %sp@(12),%sp
    clr.l   %sp@-
    clr.l   %sp@-
    clr.l   %sp@-
    pea     {SOURCE_OBJ:#010x}
    move.l  %sp@(40),%sp@-              | panel
    jsr     {BLIT:#010x}
    lea     %sp@(20),%sp
30: moveml  %sp@,%d2-%d4
    lea     %sp@(12),%sp
    rts
"""

LABELS = ("boot", "stamp")


def generate() -> dict:
    table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in LABELS) + "\n"
    blob = assemble(SOURCE + table, base=CAVE)
    code = blob[:-4 * len(LABELS)]
    addrs = dict(zip(LABELS, struct.unpack(f">{len(LABELS)}I", blob[-4 * len(LABELS):])))
    if len(code) > CAVE_CAP:
        raise SystemExit(f"code {len(code)} B does not fit the {CAVE_CAP} B cave")
    return {
        "os": "Digitone II 1.11",
        "cave": CAVE, "cave_cap": CAVE_CAP, "code": code.hex(),
        "boot": addrs["boot"], "stamp": addrs["stamp"],
        "calls_va": CALLS_VA, "calls_stock": CALLS_STOCK,
        "intro_va": INTRO_VA, "intro_stock": INTRO_STOCK,
        "area_va": AREA_VA, "runtime_va": RUNTIME_VA,
        "magic": MAGIC.decode(), "boot_chunk": BOOT.decode(), "anim_chunk": ANIM.decode(), "words": WORDS,
        "tunnel_x_va": 0x400D374E, "tunnel_y_va": 0x400D377E,
    }


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found (WSL is fine)")
    spec = generate()
    root = HERE.parent
    (root / "src/dnfw/mods/bootscreen_code.json").write_text(json.dumps(spec, indent=1) + "\n")
    (root / "site/js/mods/bootscreen-code.js").write_text(
        "// Generated by scripts/gen_bootscreen_code.py -- do not edit by hand.\n"
        f"export const CODE = {json.dumps(spec, indent=1)};\n")
    print(f"code {len(bytes.fromhex(spec['code']))} B at {spec['cave']:#x}; "
          f"boot {spec['boot']:#x}, stamp {spec['stamp']:#x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

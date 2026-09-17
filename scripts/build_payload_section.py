"""Ship bytes past the end of MAIN OS, and prove they reach run time.

`docs/ideas-backlog.md` §1 and §6, and the cap on §3 and §14: every feature that
needs *data* -- a PCM catalogue, eight wavetable bands, a bigger logo -- is
blocked on the same fact. The largest verified-free cave run is 896 bytes, and the
25.3 MB above BSS holds nothing that ships.

## Why appending is not enough by itself

Read at the reset path (`docs/ideas-backlog.md` §1, "The BSS clear's bounds"):

    0x4000053e  jsr 0x4000045c   | copy .data: 0x402fc000..0x40304000 -> 0x80000000
                                 |             0x40304000..0x4030b980 -> 0x80008000
    0x40000542  jsr 0x400004b2   | clear BSS:  0x402fc000..0x466b74d0

MAIN OS ends at `0x4030b980`, exactly where the second initialiser stops reading,
so the tail of the image is consumed and then wiped. Bytes appended to the section
land inside that clear and are gone before the OS runs.

## What this build does

1. **Grows section 3.** A payload starting at `0x4030b980`, the first byte past
   everything the initialiser reads (stock MAIN OS ends there, so no padding): magic `DNFW`, a length, and data.
2. **Copies the payload out between the two calls.** The eight bytes of the two
   `jsr`s become `jsr boot` + `nop`. `boot` calls the initialiser exactly as stock
   does, copies the payload to `0x46710000` -- above BSS end, so the clear never
   touches it -- then calls the clear and returns.
3. **Makes the result visible.** The intro stamp (§13) reads its pixel table from
   `0x46710008` instead of from the image, after checking the magic at
   `0x46710000`. **`MOD` beside the logo means appended bytes survived to run
   time.** No `MOD` means they did not -- either the bootloader refused the larger
   section, or loaded less than it declares -- and the instrument boots stock-
   looking either way, because a missing magic just skips the stamp.

## What it does not prove

That the bootloader will accept an arbitrarily large section. It proves one size.
The container's own limits are checked by `dnfw inspect` (the aPLib window), not
by this build; a real PCM catalogue is megabytes, and that is a later question.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import build_intro_stamp as stamp                       # the font and pixel layout
from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400

INIT_VA, CLEAR_VA = 0x4000045C, 0x400004B2
CALLS_VA = 0x4000053E
CALLS_STOCK = bytes.fromhex("4ebaff1c" "4ebaff6e")    # jsr init ; jsr clear
INIT_TAIL_VA = 0x4030B980                              # the initialiser reads up to here

RUNTIME_VA = 0x46710000                                # above BSS end 0x466b74d0
MAGIC = b"DNFW"

CAVE, CAVE_CAP = 0x402DFA1C, 896
OUT = pathlib.Path("00_Resources/02_Builds/payload-section_DN2_1.11.syx")


def boot_source(payload_va: int) -> str:
    return f"""
    .text
boot:
    jsr     {INIT_VA:#010x}                  | as stock: copy .data
    lea     {payload_va:#010x},%a0           | the payload, where the loader put it
    lea     {RUNTIME_VA:#010x},%a1           | above BSS: the clear never reaches it
    move.l  %a0@(4),%d0                      | its length
    addq.l  #8,%d0                           | plus the header
1:  move.b  %a0@+,%a1@+
    subq.l  #1,%d0
    bne.s   1b
    jsr     {CLEAR_VA:#010x}                 | as stock: clear BSS
    rts

stamp:
    move.l  {RUNTIME_VA:#010x},%d0           | ColdFire cmpi takes a data register only
    cmpi.l  #{int.from_bytes(MAGIC, 'big'):#010x},%d0
    bne.s   2f                               | no payload arrived: no stamp
    move.l  {stamp.SOURCE_DATA_PTR:#010x},%d0
    beq.s   2f
    movea.l %d0,%a0
    lea     {RUNTIME_VA + 8:#010x},%a1
1:  move.l  %a1@+,%d0
    bmi.s   2f
    move.l  %a1@+,%d1
    or.l    %d1,%a0@(0,%d0:l)
    bra.s   1b
2:  lea     %sp@(-60),%sp
    moveml  %d2-%d7/%a2-%fp,%sp@
    jmp     {stamp.RESUME_VA:#010x}
"""


LABELS = ("boot", "stamp")


def assemble_stubs(text: str) -> tuple[bytes, dict[str, int]]:
    table = "\n".join(f"    .long {n}" for n in LABELS)
    blob = assemble(text + "\n    .align 2\n" + table + "\n", base=CAVE)
    width = 4 * len(LABELS)
    return blob[:-width], dict(zip(LABELS, struct.unpack(f">{len(LABELS)}I", blob[-width:])))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text", default="MOD")
    ap.add_argument("--x", type=int, default=85)
    ap.add_argument("--y", type=int, default=29)
    args = ap.parse_args()
    if not available():
        raise SystemExit("no m68k assembler found (WSL is fine)")

    firmware = load(read_image(stamp.STOCK))
    section = firmware.container.find(MAIN_OS)
    content = bytearray(section.unpack())
    stock_len = len(content)

    for va, want, what in ((CALLS_VA, CALLS_STOCK, "startup calls"),
                           (stamp.HOOK_VA, stamp.HOOK_STOCK, "intro copy routine")):
        have = bytes(content[va - BASE:va - BASE + len(want)])
        if have != want:
            raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({what})")
    if any(content[CAVE - BASE:CAVE - BASE + CAVE_CAP]):
        raise SystemExit(f"cave at {CAVE:#010x} is not free")
    if BASE + stock_len > INIT_TAIL_VA:
        raise SystemExit("MAIN OS already reaches past the initialiser tail")

    # --- the payload ------------------------------------------------------
    pixels = [(args.x + x, args.y + y) for x, y in stamp.render(args.text)]
    table = stamp.pairs(pixels)
    data = b"".join(struct.pack(">II", o, m) for o, m in table) + struct.pack(">I", 0xFFFFFFFF)
    payload = MAGIC + struct.pack(">I", len(data)) + data
    payload_va = INIT_TAIL_VA
    content += bytes(payload_va - BASE - len(content))          # zero padding
    content += payload
    content += bytes(-len(content) % 4)
    print(f"part 1 -- MAIN OS {stock_len:,} -> {len(content):,} bytes; payload "
          f"{len(payload)} B at {payload_va:#010x} ({args.text!r}, {len(pixels)} px)")

    # --- the stubs --------------------------------------------------------
    code, labels = assemble_stubs(boot_source(payload_va))
    if len(code) > CAVE_CAP:
        raise SystemExit(f"cave overflows: {len(code)} > {CAVE_CAP}")
    content[CAVE - BASE:CAVE - BASE + len(code)] = code
    print(f"part 2 -- stubs {len(code)} B: boot {labels['boot']:#010x}, stamp {labels['stamp']:#010x}")

    # --- the hooks --------------------------------------------------------
    hook1 = b"\x4e\xb9" + struct.pack(">I", labels["boot"]) + b"\x4e\x71"
    content[CALLS_VA - BASE:CALLS_VA - BASE + 8] = hook1
    hook2 = b"\x4e\xf9" + struct.pack(">I", labels["stamp"]) + b"\x4e\x71"
    content[stamp.HOOK_VA - BASE:stamp.HOOK_VA - BASE + 8] = hook2
    print(f"part 3 -- {CALLS_VA:#010x} {CALLS_STOCK.hex()} -> {hook1.hex()}")
    print(f"          {stamp.HOOK_VA:#010x} {stamp.HOOK_STOCK.hex()} -> {hook2.hex()}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"part 4 -- wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

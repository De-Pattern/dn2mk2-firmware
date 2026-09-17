"""Who puts the Elektron logo into the intro's source bitmap.

The boot-screen mod on the site offers "the logo inside the bang", which needs
the logo's pixels to knock out of the burst. The repository must not carry them
-- they are Elektron's artwork, derived from firmware -- so the site has to take
them from the user's own image at build time. That is only possible if the logo
is stored in the image in some findable form. This finds the code that draws it.

Resumes a plain (non-unblocked) snapshot before the intro, watches the source
`Bitmap` header for its data pointer being set, then watches that pixel data for
writes, and reports the writing PCs and the order they came in.

    DIGIKIT=... DT2_SECTIONS=/root/dn2-sections-111 \\
    /root/dn2-emu-venv/bin/python scripts/probe_logo_writer.py \\
        snapshots/dn2_11160M.snap 330000000 --bitmap 0x42c4567c
"""

from __future__ import annotations

import argparse
import collections
import os
import struct
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot")
    ap.add_argument("instrs", type=int)
    ap.add_argument("--bitmap", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--slice", type=int, default=10_000_000)
    ap.add_argument("--blit", type=lambda s: int(s, 0), default=0x401157FC,
                    help="the masked blit that draws the logo; its arguments are logged "
                         "while it writes into the source bitmap")
    args = ap.parse_args()

    digikit = os.environ.get("DIGIKIT")
    if not digikit:
        raise SystemExit("set DIGIKIT")
    sys.path.insert(0, digikit)
    os.chdir(digikit)

    from unicorn import UC_HOOK_MEM_WRITE
    from unicorn.m68k_const import UC_M68K_REG_PC
    from emu.longrun import build, spin

    m, ev, st, pc, inq, at = build(args.snapshot)
    uc = m.uc
    now = {"n": 0}
    header_writes: list[tuple[int, int, int, int]] = []
    pixel_writers: collections.Counter = collections.Counter()
    first_pixel: dict[int, int] = {}
    data_hook = {"h": None, "base": 0}

    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A7
    blit_calls: list[tuple[int, list[int]]] = []

    def on_blit(uc_, address, size, user):
        sp = uc_.reg_read(UC_M68K_REG_A7)
        args_ = list(struct.unpack(">8I", bytes(uc_.mem_read(sp + 4, 32))))
        if data_hook["base"] and len(blit_calls) < 40:
            blit_calls.append((now["n"], args_))

    uc.hook_add(UC_HOOK_CODE, on_blit, begin=args.blit, end=args.blit)

    def on_pixels(uc_, access, addr, size, value, user):
        pc_ = uc_.reg_read(UC_M68K_REG_PC)
        pixel_writers[pc_] += 1
        first_pixel.setdefault(pc_, now["n"])

    def arm(base: int) -> None:
        if data_hook["h"] is not None:
            uc.hook_del(data_hook["h"])
        data_hook["base"] = base
        data_hook["h"] = uc.hook_add(UC_HOOK_MEM_WRITE, on_pixels, begin=base, end=base + 1023)

    def on_header(uc_, access, addr, size, value, user):
        pc_ = uc_.reg_read(UC_M68K_REG_PC)
        header_writes.append((now["n"], addr, value, pc_))
        if addr == args.bitmap + 16 and size == 4 and value:
            arm(value)

    uc.hook_add(UC_HOOK_MEM_WRITE, on_header, begin=args.bitmap, end=args.bitmap + 19)
    existing = struct.unpack(">I", bytes(uc.mem_read(args.bitmap + 16, 4)))[0]
    print(f"data pointer at start: {existing:#x}")
    if existing:
        arm(existing)

    while now["n"] < args.instrs:
        pc, n, stop = spin(m, pc, min(args.slice, args.instrs - now["n"]))
        now["n"] += n
        print(f"  {now['n']/1e6:6.0f}M  header writes {len(header_writes)}  "
              f"pixel writes {sum(pixel_writers.values())}", flush=True)
        if n == 0:
            break

    print("\nheader writes (instr, addr, value, pc):")
    for t in header_writes[:20]:
        print(f"  {t[0]:>11,}  {t[1]:#x}  {t[2]:#x}  pc {t[3]:#010x}")
    print("\npixel writers (pc, writes, first at):")
    for pc_, k in pixel_writers.most_common(15):
        print(f"  {pc_:#010x}  x{k:>6}  first {first_pixel[pc_]:>11,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

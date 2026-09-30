"""Does the real loader lay out the platform's area the way `dnfw.mods.platform` says?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_platform_check.py out/platform/trio/section_3_MAIN_OS.bin

Boots the image from reset and stops at the one moment the question has an
answer: the loader's last instruction, `jmp bss_clear` (`0x400004b2`). By then
it has copied the area's header and every data chunk to `0x46710000` plus
their offsets, every `CODE` chunk to its own load address, zeroed each BSS and
called each init. Then every range `platform.runtime` predicts is read back
and compared, byte for byte.

A `CODE` chunk with an init is compared on its image only: the init has run and
may already have written its own BSS. The boot check (`emu_boot_check.py`) says
whether the image then boots; this says whether the loader did what the
platform model, and every test built on it, assumes.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_CODE                              # noqa: E402

from dnfw.mods import platform                                # noqa: E402
from dnfw.patch import area                                   # noqa: E402

SYX = ("/mnt/d/01_Code/Z_Personal/dn2_firmware/00_Resources/00_Firmware/"
       "Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx")
BSS_CLEAR = 0x400004B2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("image", type=pathlib.Path, help="a built section_3_MAIN_OS.bin")
    p.add_argument("--limit", type=int, default=60_000_000)
    args = p.parse_args()
    content = args.image.read_bytes()
    expected = platform.runtime(content)
    if not expected:
        print("  no platform area in this image: nothing to check")
        return 1
    inits = set()
    for cid, data in platform.split(content)[1]:
        if cid == area.CODE and area.CodeChunk.unpack(data).init:
            code = area.CodeChunk.unpack(data)
            inits.add(code.load)
            print(f"  CODE at 0x{code.load:08x} has an init at 0x{code.init:08x}")

    reached = {}

    def pre_start(m):
        def at_clear(uc, address, size, user):
            reached["n"] = True
            uc.emu_stop()
        m.uc.hook_add(UC_HOOK_CODE, at_clear, begin=BSS_CLEAR, end=BSS_CLEAR)

    holder = {}
    m, st, stop = dspboot.run(SYX, content, limit=args.limit, machine_out=holder, pre_start=pre_start)
    if not reached:
        print(f"  the loader never reached bss_clear in {st['n']:,} instructions (stop {stop!r})")
        return 1
    print(f"  stopped at bss_clear after {st['n']:,} instructions")

    bad = 0
    code_images = {}
    for cid, data in platform.split(content)[1]:
        if cid == area.CODE:
            code = area.CodeChunk.unpack(data)
            code_images[code.load] = len(code.image)
    for va, want in expected:
        if va in inits:
            want = want[:code_images[va]]
        have = bytes(m.uc.mem_read(va, len(want)))
        diff = sum(a != b for a, b in zip(have, want))
        print(f"  0x{va:08x} {len(want):>7,} B  {'ok' if not diff else f'{diff:,} B DIFFER'}")
        bad += bool(diff)
    print(f"\n  {len(expected) - bad} of {len(expected)} ranges as the platform predicts")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

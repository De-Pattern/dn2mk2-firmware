"""LFO4 step 1 from reset: does hooking `memcpy` and `memset` still boot?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_lfo4_boot.py [--limit 60000000]

`scripts/emu_lfo4_ext.py` asks whether the table is carried correctly. This asks
the other question, and only that one: the build puts a stub in front of two
routines the whole firmware uses, so it boots the stock MAIN OS and then
`out/lfo4-ext/section_3_MAIN_OS.bin` from reset and compares what each does --
the same number of calls through each routine, the same distance covered, no
detour that only our build takes.

A difference in either count would mean the stub changed the firmware's own
behaviour, which is the failure this build could have and the harness cannot
see.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot  # noqa: E402
from unicorn import UC_HOOK_CODE  # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
BUILD = f"{ROOT}/out/lfo4-ext"
MEMCPY, MEMSET, CALLS_VA = 0x40134490, 0x401344D8, 0x4000053E

failures = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def boot(main_img, watch, limit):
    firsts, counts = {}, {}
    holder = {}

    def pre_start(m):
        st = holder["st"]
        for name, addr in watch.items():
            def hit(uc, address, size, user, name=name):
                counts[name] = counts.get(name, 0) + 1
                firsts.setdefault(name, st["n"])
            m.uc.hook_add(UC_HOOK_CODE, hit, begin=addr, end=addr)

    m, st, stop = dspboot.run(SYX, open(main_img, "rb").read(), limit=limit,
                              machine_out=holder, pre_start=pre_start)
    return m, st, firsts, counts


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=60_000_000)
    args = p.parse_args()
    sym = {k: int(v, 16) for k, v in json.load(open(f"{BUILD}/symbols.json")).items()}
    stock_img = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
    watch = {"startup calls": CALLS_VA, "memcpy": MEMCPY, "memset": MEMSET,
             "loader": sym["dnfw_boot"], "memcpy stub": sym["lfo4_memcpy_stub"],
             "memset stub": sym["lfo4_memset_stub"], "init": sym["lfo4_init"]}

    print(f"control: stock MAIN OS, {args.limit:,} instructions from reset")
    m0, st0, f0, c0 = boot(stock_img, watch, args.limit)
    print(f"  counts {c0}")

    print(f"\nlfo4-ext, {args.limit:,} instructions from reset")
    m, st, f, c = boot(f"{BUILD}/section_3_MAIN_OS.bin", watch, args.limit)
    print(f"  counts {c}\n")
    u32 = lambda name: struct.unpack(">I", bytes(m.uc.mem_read(sym[name], 4)))[0]   # noqa: E731

    check("the control never reaches our code", not {"loader", "memcpy stub"} & set(f0))
    check("the loader ran, and the init with it", c.get("loader") == 1 and c.get("init") == 1)
    check("every memcpy went through the stub", c.get("memcpy stub") == c.get("memcpy"),
          f"stub {c.get('memcpy stub')}, memcpy {c.get('memcpy')}")
    check("every memset went through the stub", c.get("memset stub") == c.get("memset"),
          f"stub {c.get('memset stub')}, memset {c.get('memset')}")
    check("the boot made the same calls as the control",
          (c0.get("memcpy"), c0.get("memset")) == (c.get("memcpy"), c.get("memset")),
          f"stock {c0.get('memcpy')}/{c0.get('memset')}, ours {c.get('memcpy')}/{c.get('memset')}")
    check("no entry was refused and no batch overflowed",
          u32("ext_full") == 0 and u32("ext_overflow") == 0,
          f"full {u32('ext_full')}, overflow {u32('ext_overflow')}")
    print(f"  the boot's own copies: {u32('lfo4_copies')} of a sound or more "
          f"({u32('lfo4_sound_copies')} exactly a sound, {u32('lfo4_range_copies')} larger), "
          f"{u32('lfo4_clears')} clears; {u32('ext_live')} entries live")
    print(f"\n{len(failures)} failure(s): {failures}" if failures else "\nall checks pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

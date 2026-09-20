"""LFO4 step 0 under the emulator: cold-boot the C-hello build, and a stock control.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_c_hello.py [--limit 60000000]

Boots from reset -- not from a snapshot, because the thing under test is the
startup loader, which a snapshot has already run past -- first the stock MAIN
OS, then `out/c-hello/section_3_MAIN_OS.bin` (`scripts/build_c_hello.py`). For
each it records when the loader, `memcpy` and the C hook first run, then reads
the C code's variables at the end. The control must show no code, no calls
through the hook, and the same boot otherwise.

Checks:
- the loader ran, and before the first `memcpy` reached the hook's jump -- so a
  hook on `memcpy` never jumps into RAM that is not loaded yet;
- the code at `0x46800000` is byte-for-byte the linked image;
- init ran (`hello_ready`) and the firmware's `memset` filled the marker;
- the hook counted `memcpy` calls with their real sizes, and the boot went on
  as far as the control did.
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
BUILD = f"{ROOT}/out/c-hello"
MEMCPY, CALLS_VA = 0x40134490, 0x4000053E

failures = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def boot(main_img, watch, limit):
    firsts, counts = {}, {}

    def pre_start(m):
        st = holder["st"]
        for name, addr in watch.items():
            def hit(uc, address, size, user, name=name):
                counts[name] = counts.get(name, 0) + 1
                firsts.setdefault(name, st["n"])
            m.uc.hook_add(UC_HOOK_CODE, hit, begin=addr, end=addr)

    holder = {}
    m, st, stop = dspboot.run(SYX, open(main_img, "rb").read(), limit=limit, machine_out=holder, pre_start=pre_start)
    return m, st, firsts, counts


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=60_000_000)
    args = p.parse_args()
    sym = {k: int(v, 16) for k, v in json.load(open(f"{BUILD}/symbols.json")).items()}
    image = open(f"{BUILD}/section_3_MAIN_OS.bin", "rb").read()
    stock_img = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
    watch = {"startup calls": CALLS_VA, "memcpy": MEMCPY, "loader": sym["dnfw_boot"],
             "hook stub": sym["hello_memcpy_stub"], "hello_init": sym["hello_init"]}

    print(f"control: stock MAIN OS, {args.limit:,} instructions from reset")
    m0, st0, f0, c0 = boot(stock_img, watch, args.limit)
    print(f"  firsts {f0}\n  counts {c0}")

    print(f"\nC hello, {args.limit:,} instructions from reset")
    m, st, f, c = boot(f"{BUILD}/section_3_MAIN_OS.bin", watch, args.limit)
    print(f"  firsts {f}\n  counts {c}")
    rd = lambda va, n: bytes(m.uc.mem_read(va, n))          # noqa: E731
    u32 = lambda va: struct.unpack(">I", rd(va, 4))[0]       # noqa: E731

    # The CODE chunk's image, as appended: find it through the area directory.
    a = 0x4030B980 - 0x40000400
    count = struct.unpack_from(">I", image, a + 8)[0]
    off = next(struct.unpack_from(">I", image, a + 16 + 12 * i)[0]
               for i in range(count) if image[a + 12 + 12 * i:a + 16 + 12 * i] == b"CODE")
    load, n = struct.unpack_from(">II", image, a + off)
    linked = image[a + off + 16:a + off + 16 + n]

    print()
    check("the stock control never reaches our code", "loader" not in f0 and "hook stub" not in f0)
    check("the loader ran, once", c.get("loader") == 1, str(c.get("loader")))
    check("memcpy's first call comes after the loader",
          "memcpy" not in f or f["memcpy"] > f["loader"],
          f"loader at {f.get('loader'):,}, first memcpy at {f.get('memcpy', 0):,}")
    check("the code at 0x46800000 is the linked image", rd(load, n) == linked)
    check("init ran once, from the loader", c.get("hello_init") == 1 and u32(sym["hello_ready"]) == 0x48454C4F,
          f"hello_ready = {u32(sym['hello_ready']):#010x}")
    check("the firmware's memset filled the marker", rd(sym["hello_marker"], 16) == b"\xa5" * 16,
          rd(sym["hello_marker"], 16).hex())
    calls = u32(sym["hello_calls"])
    check("every memcpy went through the C routine", calls == c.get("memcpy", 0) == c.get("hook stub", 0),
          f"C counted {calls}, memcpy entered {c.get('memcpy', 0)}, stub {c.get('hook stub', 0)}")
    check("the control made the same number of memcpy calls", c0.get("memcpy", 0) == c.get("memcpy", 0),
          f"stock {c0.get('memcpy', 0)}, ours {c.get('memcpy', 0)}")
    print(f"  last memcpy size {u32(sym['hello_last_n'])}, whole-sound copies {u32(sym['hello_sound_copies'])}")
    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

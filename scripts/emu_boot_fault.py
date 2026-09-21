"""Boot a build from reset and catch the firmware's own exception screen.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_boot_fault.py --build out/lfo4-bridge [--limit 400000000]

`lfo4-bridge` faulted on the instrument at boot, 2026-09-20, with the
firmware's `EXCEPTION` screen. That screen is drawn by `0x4011ea6a` from
`"EXCEPTION DS%.04s"` / `"V%02x M%x P%08x"` -- **vector, mode and the faulting
PC** -- so rather than read the numbers off a photograph, this boots the same
image from reset and reads them out of the machine.

It boots the **stock** image first under the identical hook. A control matters
here more than usual: if stock also reaches the reporter within the limit, the
screen is not evidence about our build at all.

Every harness this build was verified with restored `ui1200M`, which is a
snapshot of a machine that has *already booted*. Nothing in that path ever ran
our loader, our init, or the first calls into our code from reset -- which is
exactly the window the instrument faulted in.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emu import dspboot                                   # noqa: E402
from unicorn import UC_HOOK_CODE                          # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A0, UC_M68K_REG_A1, UC_M68K_REG_A2,  # noqa: E402
                                UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_D1,
                                UC_M68K_REG_D2, UC_M68K_REG_PC)

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
REPORTER = 0x4011EA6A          # draws EXCEPTION V.. M. P........


def boot(image_path, limit, extra_watch):
    """Boot `image_path` from reset. -> (machine, state, what was hit)."""
    hits, holder = [], {}

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            a2 = uc.reg_read(UC_M68K_REG_A2)
            try:
                record = bytes(uc.mem_read(a2, 32))
            except Exception:                              # noqa: BLE001
                record = b""
            hits.append({
                "at": st["n"], "a2": a2, "record": record.hex(),
                "regs": {n: uc.reg_read(r) for n, r in
                         (("d0", UC_M68K_REG_D0), ("d1", UC_M68K_REG_D1),
                          ("d2", UC_M68K_REG_D2), ("a0", UC_M68K_REG_A0),
                          ("a1", UC_M68K_REG_A1), ("sp", UC_M68K_REG_A7),
                          ("pc", UC_M68K_REG_PC))},
            })
            uc.emu_stop()

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        for name, addr in extra_watch.items():
            def seen(uc, address, size, user, name=name):
                counts[name] = counts.get(name, 0) + 1
            m.uc.hook_add(UC_HOOK_CODE, seen, begin=addr, end=addr)

    counts = {}
    m, st, stop = dspboot.run(SYX, open(image_path, "rb").read(), limit=limit,
                              machine_out=holder, pre_start=pre_start)
    return m, st, hits, counts, stop


def report(label, st, hits, counts, stop):
    print(f"\n{label}: ran {st['n']:,} instruction(s), stop {stop!r}")
    if counts:
        print(f"  reached: {counts}")
    if not hits:
        print("  the exception reporter was never reached.")
        return False
    h = hits[0]
    rec = bytes.fromhex(h["record"])
    print(f"  ** EXCEPTION after {h['at']:,} instructions **")
    print(f"     record at {h['a2']:#010x}: {h['record']}")
    if len(rec) >= 8:
        # The formatter reads a2@(2) as a byte and a2@(4) as a long.
        print(f"     a2@(2) = {rec[2]:#04x}   a2@(4) = {struct.unpack('>I', rec[4:8])[0]:#010x}")
    print("     " + "  ".join(f"{k} {v:#010x}" for k, v in h["regs"].items()))
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-bridge")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--skip-control", action="store_true")
    args = p.parse_args()

    build = os.path.join(ROOT, args.build) if not args.build.startswith("/") else args.build
    sym = {k: int(v, 16) for k, v in json.load(open(f"{build}/symbols.json")).items()}
    watch = {n: sym[n] for n in ("dnfw_boot", "lfo4_init", "lfo4_refresh") if n in sym}

    if not args.skip_control:
        stock = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
        m0, st0, h0, c0, s0 = boot(stock, args.limit, {})
        if report("control: stock 1.11 from reset", st0, h0, c0, s0):
            print("  the control faulted too: this screen is not about our build.")
            return 1

    m, st, hits, counts, stop = boot(f"{build}/section_3_MAIN_OS.bin", args.limit, watch)
    faulted = report(f"{os.path.basename(build)} from reset", st, hits, counts, stop)
    return 1 if faulted else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The wild-read trap, in every emulator step (v0.46; docs/after-v045.md, blind spot 4).

v0.44 froze the unit: BOUNCE's label lookup walked absolute address 0x000000EE as a table.
The emulator maps low memory as zero RAM, so there the walk met a 0 and the page drew; the
unit has no RAM there and hung. With DNFW_LOWTRAP=1 (the gate sets it for every emulator
step), any read below 0x40000000 by code that is not stock's own (our chunks, or a stock site
we edited) is recorded with its PC and callers; when the process ends, one or more such reads
print `LOWTRAP FAIL ...` and the process exits 97, failing the step whatever it found.
Stock's own reads (its boot-time byte at 0) are stock's: the instruction bytes at PC are
compared with the stock image (DT2_MAIN_IMG, loaded at 0x40000400)."""

from __future__ import annotations

import atexit
import json
import os
import struct
import sys

LOW_END = 0x3FFFFFFF
BASE = 0x40000400
EXIT = 97


def install(uc) -> None:
    from unicorn import UC_HOOK_MEM_READ
    from unicorn import m68k_const as K
    stock = open(os.environ["DT2_MAIN_IMG"], "rb").read()
    seen = {"n": 0, "first": []}

    def low(uc, access, address, size, value, user):
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        off = pc - BASE
        if 0 <= off < len(stock) - 8 and bytes(uc.mem_read(pc, 8)) == stock[off:off + 8]:
            return
        seen["n"] += 1
        if len(seen["first"]) < 8:
            sp = uc.reg_read(K.UC_M68K_REG_A7)
            try:
                words = struct.unpack(">32I", bytes(uc.mem_read(sp, 128)))
            except Exception:                   # noqa: BLE001
                words = ()
            callers = [f"{v:#010x}" for v in words if 0x40000400 <= v < 0x40220000 or 0x46700000 <= v < 0x46B00000][:6]
            seen["first"].append({"address": f"{address:#010x}", "pc": f"{pc:#010x}", "callers": callers})

    uc.hook_add(UC_HOOK_MEM_READ, low, begin=0, end=LOW_END)

    def at_exit():
        if seen["n"]:
            sys.stdout.flush()
            print(f"LOWTRAP FAIL: {seen['n']} read(s) below 0x40000000 by code that is not stock's: "
                  f"{json.dumps(seen['first'])}", flush=True)
            sys.stderr.flush()
            os._exit(EXIT)

    atexit.register(at_exit)

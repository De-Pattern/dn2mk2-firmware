"""Put the LFO4 build into a restored snapshot, and call things in it.

Shared by `scripts/emu_lfo4_ext.py` (the table and its carry) and
`scripts/emu_lfo4_store.py` (save and load), which ask different questions of
the same build. One subject here: getting that build into a running machine the
way the loader and the patch would, and entering a routine with arguments.

Not a cold boot -- `scripts/emu_lfo4_boot.py` is that. A snapshot has already
run past the startup loader, so the code is written where the loader would have
put it, its init is called, and the patch sites are written exactly as
`scripts/build_lfo4_ext.py` writes them. Everything after that is the shipped
code running for real.

Needs digikit's emulator, so it imports only under WSL.
"""

from __future__ import annotations

import json
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu.longrun import build  # noqa: E402
from unicorn import UC_HOOK_CODE, UC_PROT_ALL, UcError  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A6, UC_M68K_REG_A7, UC_M68K_REG_D0  # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
BUILD = f"{ROOT}/out/lfo4-ext"
SNAP = "/root/dn2-snapshots/Digitone_II_OS1.11/ui1200M.snap"

BASE, AREA_VA = 0x40000400, 0x4030B980
SOUND, KIT = 1163, 23921          # one live sound; a kit, the block that holds sixteen
STACK, SCRATCH = 0x46A00000, 0x46A10000
PARAMS = 8

failures = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def report():
    print(f"\n{len(failures)} failure(s): {failures}" if failures else "\nall checks pass")
    return 1 if failures else 0


def load_build():
    """-> (the patched MAIN OS image, its symbols)."""
    image = open(f"{BUILD}/section_3_MAIN_OS.bin", "rb").read()
    symbols = {k: int(v, 16) for k, v in json.load(open(f"{BUILD}/symbols.json")).items()}
    return image, symbols


def code_chunk(image: bytes):
    """-> (load, image length, bss, init, the linked bytes) from the appended area."""
    a = AREA_VA - BASE
    count = struct.unpack_from(">I", image, a + 8)[0]
    off = next(struct.unpack_from(">I", image, a + 16 + 12 * i)[0]
               for i in range(count) if image[a + 12 + 12 * i:a + 16 + 12 * i] == b"CODE")
    load, length, bss, init = struct.unpack_from(">4I", image, a + off)
    return load, length, bss, init, image[a + off + 16:a + off + 16 + length]


def sites():
    """-> [(what, virtual address, patched bytes, stock bytes)], as the build
    recorded them in `sites.json`. Not a second list to keep in step: the
    harness writes exactly what the build wrote."""
    return [(s["what"], int(s["va"], 16), bytes.fromhex(s["bytes"]), bytes.fromhex(s["stock"]))
            for s in json.load(open(f"{BUILD}/sites.json"))]


class Machine:
    """A restored snapshot, with memory and a way to enter a routine.

    Everything here is true of any build: writing memory that may not be
    mapped yet, reading it back, laying out arguments the way a `jsr` does,
    and counting the instructions one call costs. What a particular build
    *installs* is its subclass's business.
    """

    def __init__(self, snapshot):
        self.m, *_ = build(snapshot, syx=SYX, unblock=True, softfloat=True, bitmap=True,
                           dsp=True, weakptr=True, slc=True, deferred_components=("timers",))
        self.uc = self.m.uc
        self.ret = STACK + 0x800
        self.at = SCRATCH
        self.count = 0

    # --- memory -----------------------------------------------------------
    def write(self, va, data):
        try:
            self.uc.mem_write(va, data)
        except UcError:
            for page in range(va & ~0xFFFFF, va + len(data) + 0x100000, 0x100000):
                try:
                    self.uc.mem_map(page, 0x100000, UC_PROT_ALL)
                except UcError:
                    pass
            self.uc.mem_write(va, data)

    def read(self, va, n):
        return bytes(self.uc.mem_read(va, n))

    def word(self, va):
        return struct.unpack(">H", self.read(va, 2))[0]

    def long(self, va):
        return struct.unpack(">I", self.read(va, 4))[0]

    def alloc(self, n):
        va = (self.at + 15) & ~15
        self.at = va + n
        self.write(va, bytes(n))
        return va

    def flush(self):
        """Unicorn keeps translated blocks; a patch written into code it has
        already run does not take effect without this (`docs/emulator.md`)."""
        try:
            self.uc.ctl_flush_tb()
        except AttributeError:
            self.uc.ctl_remove_cache(0x40000000, 0x40400000)

    # --- calling ----------------------------------------------------------
    def call(self, fn, *args):
        frame = struct.pack(">I", self.ret) + b"".join(struct.pack(">I", a & 0xFFFFFFFF) for a in args)
        self.write(STACK, frame)
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A6, 0)
        self.uc.emu_start(fn, self.ret, count=20_000_000)
        return self.uc.reg_read(UC_M68K_REG_D0)

    def cost(self, fn, *args):
        """-> (result, instructions executed). The counter is a Python callback
        per instruction, so it is installed for this one call and removed."""
        self.count = 0
        handle = self.uc.hook_add(UC_HOOK_CODE, self._tick)
        try:
            result = self.call(fn, *args)
        finally:
            self.uc.hook_del(handle)
        return result, self.count

    def _tick(self, uc, address, size, user):
        self.count += 1


class Harness(Machine):
    """`Machine`, plus the LFO4 `CODE` chunk build: its code, its init and the
    sites `scripts/build_lfo4_ext.py` patched."""

    def __init__(self, snapshot, image, symbols):
        super().__init__(snapshot)
        self.sym = symbols
        self.image = image
        self.load, length, self.bss_len, self.init, self.code = code_chunk(image)
        self.bss = self.load + length

    def u32(self, name):
        return self.long(self.sym[name])

    # --- the build, as the loader and the patch would leave it -------------
    def install(self):
        """The loader's copy and init, then every site the build patched."""
        self.write(self.load, self.code)
        self.write(self.bss, bytes(self.bss_len))
        self.call(self.init)
        for what, va, patched, stock in sites():
            if self.read(va, len(stock)) != stock:
                raise SystemExit(f"{what} at 0x{va:08x} is not stock in this snapshot")
            self.write(va, patched)
        # Unicorn caches translated blocks, and a write through the API is not
        # the self-modifying code it watches for: a routine the harness ran
        # *before* installing would keep running its stock translation, hook and
        # all. Measured 2026-09-20 -- the load hook counted zero calls while a
        # code hook on the same address counted one. Flush, or the patch is a
        # suggestion.
        self.flush()

    def reset(self):
        """Back to a just-booted table, without re-restoring the snapshot."""
        self.write(self.bss, bytes(self.bss_len))
        self.call(self.init)

    # --- the table, through its own API ------------------------------------
    def set(self, key, values):
        for p, v in enumerate(values):
            self.call(self.sym["ext_set"], key, p, v)

    def get(self, key):
        return [self.call(self.sym["ext_get"], key, p) & 0xFFFF for p in range(PARAMS)]

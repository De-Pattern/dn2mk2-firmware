"""A restored snapshot: memory, calls, instruction counts.

Everything here is true of any build. What a build *installs* is its own
business; this is the machine it installs into.

The build flags must match the ones the snapshot was saved with or digikit's
manifest guard refuses -- which is the guard working, and worth leaving alone.
`FLAGS` are `ui1200M`'s.
"""

from __future__ import annotations

import struct
import sys

DIGIKIT = "/mnt/d/01_Code/Z_Personal/digikit-up"
ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
SYX = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
SNAP = "/root/dn2-snapshots/Digitone_II_OS1.11/ui1200M.snap"

STACK, SCRATCH = 0x46A00000, 0x46A10000
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True,
             weakptr=True, slc=True, sdgate=True, esdhc=True)


class Machine:
    """A snapshot, restored and ready to be asked things."""

    def __init__(self, snapshot=SNAP, syx=SYX, digikit=DIGIKIT, defer_timers=True, **flags):
        if digikit not in sys.path:
            sys.path.insert(0, digikit)
            sys.path.insert(0, f"{digikit}/tools")
        from emu.longrun import build

        settings = dict(FLAGS)
        settings.update(flags)
        if defer_timers:
            settings["deferred_components"] = ("timers",)
        built = build(snapshot, syx=syx, **settings)
        # build() -> (machine, events, state, pc, input queue, hook registrar).
        # `hook_at` is that registrar; `at` below is this class's own scratch
        # allocator, and the two must not share a name.
        self.m, self.ev, self.st, self.pc, self.inq, self.hook_at = built
        self.uc = self.m.uc
        self.ret = STACK + 0x800
        self.at = SCRATCH
        self.count = 0

    # --- memory -----------------------------------------------------------
    def write(self, va, data):
        """Write, mapping the pages first if they are not there yet."""
        from unicorn import UC_PROT_ALL, UcError

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
        """Drop translated blocks.

        Unicorn caches them, and a write through the API is not the
        self-modifying code it watches for: a routine run *before* a patch was
        installed keeps running its old translation, hook and all. It fails
        silently and plausibly (`docs/emulator.md`).
        """
        try:
            self.uc.ctl_flush_tb()
        except AttributeError:
            self.uc.ctl_remove_cache(0x40000000, 0x40400000)

    # --- installing a build ------------------------------------------------
    def apply(self, runs):
        """Write every changed run of a build, then flush."""
        for va, blob in runs:
            self.write(va, blob)
        self.flush()
        return sum(len(b) for _, b in runs)

    def patch_sites(self, rows):
        """Write each recorded site, refusing one that is not stock here."""
        for what, va, patched, stock in rows:
            if self.read(va, len(stock)) != stock:
                raise SystemExit(f"{what} at 0x{va:08x} is not stock in this snapshot")
            self.write(va, patched)
        self.flush()

    def load_code_chunk(self, chunk):
        """Do the startup loader's job: copy, zero the BSS, call the init.

        A snapshot has already run past the loader, so a harness that wants the
        `CODE` chunk running has to do this itself.
        """
        load, length, bss, init, blob = chunk
        self.write(load, blob)
        self.write(load + length, bytes(bss))
        if init:
            self.call(init)
        return load

    # --- calling ----------------------------------------------------------
    def call(self, fn, *args):
        """Enter `fn` with `args` as a `jsr` would, and stop at the return."""
        from unicorn.m68k_const import UC_M68K_REG_A6, UC_M68K_REG_A7, UC_M68K_REG_D0

        frame = struct.pack(">I", self.ret) + b"".join(
            struct.pack(">I", a & 0xFFFFFFFF) for a in args)
        self.write(STACK, frame)
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A6, 0)
        self.uc.emu_start(fn, self.ret, count=20_000_000)
        return self.uc.reg_read(UC_M68K_REG_D0)

    def cost(self, fn, *args):
        """-> (result, instructions). The counter is a Python callback per
        instruction, so it is installed for this one call and removed."""
        from unicorn import UC_HOOK_CODE

        self.count = 0
        handle = self.uc.hook_add(UC_HOOK_CODE, self._tick)
        try:
            result = self.call(fn, *args)
        finally:
            self.uc.hook_del(handle)
        return result, self.count

    def _tick(self, uc, address, size, user):
        self.count += 1

    # --- watching -----------------------------------------------------------
    def watch_writes(self, low, high, note):
        """Call `note(pc, address, value, size)` for writes in [low, high]."""
        from unicorn import UC_HOOK_MEM_WRITE
        from unicorn.m68k_const import UC_M68K_REG_PC

        def wrote(uc, access, address, size, value, user):
            note(uc.reg_read(UC_M68K_REG_PC), address, value, size)

        return self.uc.hook_add(UC_HOOK_MEM_WRITE, wrote, begin=low, end=high)

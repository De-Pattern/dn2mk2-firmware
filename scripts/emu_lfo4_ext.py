"""LFO4 step 1 under the emulator: the extension table, driven through the real
`memcpy` and `memset`.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_lfo4_ext.py [--snapshot ...]

`docs/lfo4-build-plan.md` §8 asks step 1 for a direct-call harness: whole-sound,
kit and pattern copies, clears, overlaps, a full table, and the cost per call.
A cold boot cannot ask those questions -- the copies it makes are whatever the
UI happens to do -- so a snapshot is restored, the build's code is written where
the loader would have put it, its init is called, and the two entries are
patched exactly as `scripts/build_lfo4_ext.py` patches the image. Then the
firmware's **own** `memcpy` and `memset` are called with laid-out arguments and
the table is read back through `ext_get`.

So what runs is the shipped code: the stubs, the C, the table, and both
firmware routines. What this does not cover is the startup loader (step 0
proved it) and the boot itself (`scripts/emu_lfo4_boot.py`).
"""

from __future__ import annotations

import argparse
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
MEMCPY, MEMSET = 0x40134490, 0x401344D8
SOUND, KIT = 1163, 23921          # one live sound; a kit, the block that holds sixteen
STACK, SCRATCH = 0x46A00000, 0x46A10000
PARAMS = 8

failures = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def code_chunk(image: bytes):
    """-> (load address, linked image) out of the build's appended area."""
    a = AREA_VA - BASE
    count = struct.unpack_from(">I", image, a + 8)[0]
    off = next(struct.unpack_from(">I", image, a + 16 + 12 * i)[0]
               for i in range(count) if image[a + 12 + 12 * i:a + 16 + 12 * i] == b"CODE")
    load, length, bss, init = struct.unpack_from(">4I", image, a + off)
    return load, length, bss, init, image[a + off + 16:a + off + 16 + length]


class Harness:
    def __init__(self, snapshot, image, symbols):
        self.m, *_ = build(snapshot, syx=SYX, unblock=True, softfloat=True, bitmap=True,
                           dsp=True, weakptr=True, slc=True, deferred_components=("timers",))
        self.uc = self.m.uc
        self.sym = symbols
        self.ret = STACK + 0x800
        self.at = SCRATCH
        self.count = 0
        self.load, length, self.bss_len, self.init, self.code = code_chunk(image)
        self.bss = self.load + length

    def _tick(self, uc, address, size, user):
        self.count += 1

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

    def u32(self, name):
        return struct.unpack(">I", self.read(self.sym[name], 4))[0]

    def alloc(self, n):
        va = (self.at + 15) & ~15
        self.at = va + n
        self.write(va, bytes(n))
        return va

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

    # --- the build, as the loader and the patch would leave it -------------
    def install(self):
        self.write(self.load, self.code)
        self.write(self.bss, bytes(self.bss_len))
        self.call(self.init)
        for va, stub in ((MEMCPY, "lfo4_memcpy_stub"), (MEMSET, "lfo4_memset_stub")):
            self.write(va, b"\x4e\xf9" + struct.pack(">I", self.sym[stub]) + b"\x4e\x71")

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

    def memcpy(self, dst, src, n):
        return self.call(MEMCPY, dst, src, n)

    def memset(self, dst, fill, n):
        return self.call(MEMSET, dst, fill, n)


def marks(i):
    """Eight values no other sound has."""
    return [(0x1100 * (i + 1) + p) & 0xFFFF for p in range(PARAMS)]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", default=SNAP)
    args = p.parse_args()

    image = open(f"{BUILD}/section_3_MAIN_OS.bin", "rb").read()
    symbols = {k: int(v, 16) for k, v in json.load(open(f"{BUILD}/symbols.json")).items()}
    h = Harness(args.snapshot, image, symbols)

    print(f"stock {args.snapshot}")
    stock_small = h.cost(MEMCPY, h.alloc(64), h.alloc(64), 64)[1]
    stock_sound = h.cost(MEMCPY, h.alloc(SOUND), h.alloc(SOUND), SOUND)[1]
    h.install()
    print(f"code at 0x{h.load:08x}, {len(h.code)} B + {h.bss_len} B bss; both entries patched\n")

    # --- one sound ---------------------------------------------------------
    a, b = h.alloc(SOUND), h.alloc(SOUND)
    h.set(a, marks(0))
    h.memcpy(b, a, SOUND)
    check("a whole-sound copy carries the eight values", h.get(b) == marks(0), f"{h.get(b)}")
    check("and leaves the source's alone", h.get(a) == marks(0))

    c = h.alloc(SOUND)
    h.set(c, marks(1))
    h.memcpy(c, a, SOUND)
    check("a copy over a tracked sound replaces its values", h.get(c) == marks(0))

    d = h.alloc(SOUND)
    h.set(d, marks(2))
    h.memcpy(d, h.alloc(SOUND), SOUND)      # from a sound with no entry
    check("a copy from an untracked sound drops the destination's entry",
          h.get(d) == [0] * PARAMS, f"{h.get(d)}")

    e = h.alloc(SOUND)
    h.set(e, marks(3))
    h.memcpy(h.alloc(SOUND), e, 64)
    live = h.u32("ext_live")
    h.memcpy(h.alloc(SOUND), e, SOUND - 1)
    check("a copy shorter than a sound carries nothing", h.u32("ext_live") == live)

    # --- clears ------------------------------------------------------------
    h.memset(e, 0, SOUND)
    check("a whole-sound clear drops the entry", h.get(e) == [0] * PARAMS)
    f = h.alloc(SOUND)
    h.set(f, marks(4))
    h.memset(f, 0, SOUND - 1)
    check("a clear shorter than a sound leaves it", h.get(f) == marks(4))

    # --- a kit ---------------------------------------------------------------
    # Sixteen sounds at stride 1,163 inside a kit-sized block. Where a real kit
    # puts them is not what is under test and the carry does not read the block:
    # it moves whatever it is tracking inside the range.
    h.reset()
    src, dst = h.alloc(KIT), h.alloc(KIT)
    for i in range(16):
        h.set(src + i * SOUND, marks(i))
    h.memcpy(dst, src, KIT)
    carried = [h.get(dst + i * SOUND) for i in range(16)]
    check("a whole-kit copy carries all sixteen sounds, each to its own offset",
          carried == [marks(i) for i in range(16)],
          f"{sum(1 for i, v in enumerate(carried) if v == marks(i))}/16 landed")
    check("the kit's own sounds are untouched",
          [h.get(src + i * SOUND) for i in range(16)] == [marks(i) for i in range(16)])
    check("nothing landed between the sounds", h.get(dst + 1) == [0] * PARAMS)

    h.memset(dst, 0, KIT)
    check("a whole-kit clear drops all sixteen",
          all(h.get(dst + i * SOUND) == [0] * PARAMS for i in range(16)),
          f"{h.u32('ext_live')} entries left, the source kit's")

    # --- an overlapping move ------------------------------------------------
    h.reset()
    src = h.alloc(KIT + SOUND)
    for i in range(16):
        h.set(src + i * SOUND, marks(i))
    h.memcpy(src + SOUND, src, KIT)         # every sound one slot along, ranges overlapping
    moved = [h.get(src + SOUND + i * SOUND) for i in range(16)]
    check("an overlapping block move carries every sound",
          moved == [marks(i) for i in range(16)],
          f"{sum(1 for i, v in enumerate(moved) if v == marks(i))}/16 landed")
    check("and the one the move did not reach still reads what it was",
          h.get(src) == marks(0), f"{h.get(src)}")

    # --- a pattern-sized block the enumeration never named -------------------
    h.reset()
    big = 4 * KIT + 977                     # not a size this build knows
    src, dst = h.alloc(big), h.alloc(big)
    where = [0, 3 * SOUND + 7, big - SOUND]
    for i, off in enumerate(where):
        h.set(src + off, marks(i))
    h.memcpy(dst, src, big)
    check("a block of an unknown size carries what is inside it",
          [h.get(dst + off) for off in where] == [marks(i) for i in range(len(where))])

    # --- the range guard, and cost ------------------------------------------
    h.reset()
    tracked = h.alloc(SOUND)
    h.set(tracked, marks(0))
    far = h.alloc(0x20000)
    _, guarded = h.cost(MEMCPY, far + 0x10000, far, 0x8000)
    h.reset()
    _, empty = h.cost(MEMCPY, far + 0x10000, far, 0x8000)
    check("a large copy nowhere near a sound costs the range test only",
          guarded - empty < 100, f"{guarded - empty} instructions more than with an empty table")

    hooked_small = h.cost(MEMCPY, h.alloc(64), h.alloc(64), 64)[1]
    h.reset()
    a, b = h.alloc(SOUND), h.alloc(SOUND)
    h.set(a, marks(0))
    hooked_sound = h.cost(MEMCPY, b, a, SOUND)[1]
    src, dst = h.alloc(KIT), h.alloc(KIT)
    for i in range(16):
        h.set(src + i * SOUND, marks(i))
    _, kit_cost = h.cost(MEMCPY, dst, src, KIT)
    print("\n  cost, instructions per call")
    print(f"    64 B copy          stock {stock_small:6,}   hooked {hooked_small:6,}"
          f"   (+{hooked_small - stock_small})")
    print(f"    one sound          stock {stock_sound:6,}   hooked {hooked_sound:6,}"
          f"   (+{hooked_sound - stock_sound})")
    print(f"    a kit, 16 sounds                     hooked {kit_cost:6,}")
    print()
    check("the fast path costs under 50 instructions", hooked_small - stock_small < 50,
          f"+{hooked_small - stock_small}")

    # --- a full table --------------------------------------------------------
    h.reset()
    slots = 256
    keys = [0x40000000 + i * SOUND for i in range(slots)]
    for k in keys:
        h.call(symbols["ext_set"], k, 0, 0x55AA)
    check("the table holds its stated capacity", h.u32("ext_live") == slots, f"{h.u32('ext_live')} live")
    h.call(symbols["ext_set"], 0x50000000, 0, 1)
    check("one more is refused and counted, not written over something",
          h.u32("ext_full") == 1 and h.u32("ext_live") == slots,
          f"ext_full {h.u32('ext_full')}, live {h.u32('ext_live')}")
    check("every entry in the full table is still found",
          all(h.call(symbols["ext_get"], k, 0) & 0xFFFF == 0x55AA for k in keys))

    # --- deletion keeps the rest findable -------------------------------------
    for k in keys[::2]:
        h.call(symbols["ext_drop"], k)
    check("after dropping half, the other half is still found",
          all(h.call(symbols["ext_get"], k, 0) & 0xFFFF == 0x55AA for k in keys[1::2]),
          f"{h.u32('ext_live')} live")
    check("and the dropped half reads the default",
          all(h.call(symbols["ext_get"], k, 0) & 0xFFFF == 0 for k in keys[::2]))
    check("nothing overflowed a batch", h.u32("ext_overflow") == 0, f"{h.u32('ext_overflow')}")

    print(f"\n{len(failures)} failure(s): {failures}" if failures else "\nall checks pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

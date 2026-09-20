"""Call the arp p-lock routines under digikit's emulator, one by one.

    # in WSL, with digikit's venv:
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_arp_plocks.py out/film/<build>.ranges.json [snapshot]

The sequencer does not play under the emulator (the audio-frame chain needs the
DSP side; PLAY runs no note set, with or without `--ssi0-request-hz`), and a
pattern switch there does not reach the pattern load. So each routine that runs
on those paths is called directly: a snapshot is restored, the build's bytes
are written in, synthetic records / lists / sounds / clipboards are laid out in
spare RAM, the routine is entered with its real arguments, and what it wrote is
checked. The routines' own callees (the stock builder, applier, clear, recount,
loader, saver) run for real.

`<build>.ranges.json` is `out/mkranges.py`'s output, with `<...>.at` beside it
(the routines' addresses).
"""

from __future__ import annotations

import json
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu.longrun import build  # noqa: E402
from unicorn import UC_PROT_ALL, UcError  # noqa: E402
from unicorn import m68k_const as mc  # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A6, UC_M68K_REG_A7,  # noqa: E402
                                UC_M68K_REG_D0, UC_M68K_REG_D2)

KEPT = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "A0", "A1", "A2", "A3", "A4", "A5"]

SNAP = "/root/dn2-snapshots/Digitone_II_OS1.11/grid-rec.snap"
SYX = ("/mnt/d/01_Code/Z_Personal/dn2_firmware/00_Resources/00_Firmware/"
       "Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx")

SHADOW, SHADOW_STRIDE, LAST_NOTE = 0x467C0000, 1164, 0x467C4900
EXT_MASK, EXT_VALUES = 828, 832
ARP_STATE, TRACK_SOUNDS = 0x405984A8, 0x4058E8D8
NOTE_SET, LOADER, SAVER = 0x40029CD4, 0x400DE51E, 0x400DE718
SCRATCH = 0x467D0000                    # spare RAM past the shadows, for the tests' data
STACK = 0x467CF000                      # and the harness's stack, below it
REC, RECS, INDEX, COUNTS = 258, 80, 20640, 22256
TABLE_BYTES = COUNTS + 2048

failures = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


class Emu:
    def __init__(self, ranges_path, snapshot):
        self.m, *_ = build(snapshot, syx=SYX, unblock=True, softfloat=True, bitmap=True, dsp=True,
                           weakptr=True, slc=True, deferred_components=("timers",))
        self.uc = self.m.uc
        self.at = {k: int(v, 16) for k, v in json.load(open(ranges_path + ".at")).items()}
        for r in json.load(open(ranges_path))["ranges"]:
            self.write(int(r["va"], 16), bytes.fromhex(r["hex"]))
        self.ret = STACK + 0x800          # a return address that is never executed
        self.alloc_at = SCRATCH

    def write(self, va, data):
        try:
            self.uc.mem_write(va, data)
        except UcError:
            for page in range(va & ~0xFFFFF, va + len(data), 0x100000):
                try:
                    self.uc.mem_map(page, 0x100000, UC_PROT_ALL)
                except UcError:
                    pass                  # already mapped
            self.uc.mem_write(va, data)

    def read(self, va, n):
        return bytes(self.uc.mem_read(va, n))

    def u16(self, va):
        return struct.unpack(">H", self.read(va, 2))[0]

    def u32(self, va):
        return struct.unpack(">I", self.read(va, 4))[0]

    def put32(self, va, v):
        self.write(va, struct.pack(">I", v & 0xFFFFFFFF))

    def alloc(self, n):
        va = (self.alloc_at + 15) & ~15
        self.alloc_at = va + n
        self.write(va, bytes(n))
        return va

    def call(self, fn, args, fp=0, until=None, stack_extra=b""):
        """Enter `fn` with `args` (longs) as a jsr would, stop at the return (or `until`)."""
        sp = STACK
        frame = struct.pack(">I", self.ret) + b"".join(struct.pack(">I", a & 0xFFFFFFFF) for a in args)
        self.write(sp, frame + stack_extra)
        self.uc.reg_write(UC_M68K_REG_A7, sp)
        self.uc.reg_write(UC_M68K_REG_A6, fp)
        self.uc.emu_start(fn, until if until is not None else self.ret, count=5_000_000)
        return sp

    def table(self):
        """A pattern lock table: 80 free records, the index free, no counts."""
        t = self.alloc(TABLE_BYTES)
        self.write(t, b"\xff" * (REC * RECS))
        self.write(t + INDEX, b"\xff" * (16 * 101))
        return t

    def record(self, t, i, k, trackbyte, steps):
        hdr = bytes([k, trackbyte]) + b"\xff\xff" * 128
        self.write(t + i * REC, hdr)
        for s, v in steps.items():
            self.write(t + i * REC + 2 + 2 * s, struct.pack(">H", v))

    def model(self, table):
        """An object whose vt[40] returns `table` and vt[16] returns (notify)."""
        code = self.alloc(16)
        self.write(code, b"\x20\x3c" + struct.pack(">I", table) + b"\x4e\x75" + b"\x4e\x75")
        vt = self.alloc(64)
        self.put32(vt + 40, code)
        self.put32(vt + 16, code + 8)
        obj = self.alloc(16)
        self.put32(obj, vt)
        return obj


def main(ranges, snapshot=SNAP):
    e = Emu(ranges, snapshot)
    at = e.at

    print("builder: the step's arp locks into the list's spare half")
    t = e.table()
    e.record(t, 0, 0, 0x20, {2: 0x0003})           # MODE = DOWN on step 2
    e.record(t, 1, 6, 0x20, {2: 0x00F4})           # offset of arp step 2 = -12
    e.record(t, 2, 3, 0x21, {2: 0x0040})           # N.LEN on track 2: not this track's
    e.record(t, 3, 21, 0x20, {2: 0x00F7})          # step mask, low byte (--all's mutes)
    e.record(t, 4, 22, 0x20, {2: 0x00B6})          # step mask, high byte
    lst = e.alloc(1700)
    e.write(lst + EXT_MASK, b"\xff" * 4)           # stale: must be rewritten
    e.call(at["build_hook"], [0, lst, t, 0, 2])
    check("mask has MODE, offset 2 and the step mask", e.u32(lst + EXT_MASK) == (1 << 0) | (1 << 6) | (3 << 21),
          hex(e.u32(lst + EXT_MASK)))
    check("MODE value", e.read(lst + EXT_VALUES, 1) == b"\x03")
    check("offset value", e.read(lst + EXT_VALUES + 6, 1) == b"\xf4")
    check("no stock entries", e.u32(lst + 8) == 0, str(e.u32(lst + 8)))

    print("note hook: the note set gets the shadow, in its argument and in d2")
    sound = e.alloc(1164)
    e.write(sound, bytes(i & 0xFF for i in range(1163)))
    rec = e.alloc(128)
    e.put32(rec + 84, lst)
    fp = e.alloc(64) + 48
    e.put32(fp - 36, rec)
    args = [0, 0, 0, 0, 0, 0, 0, sound, 0, 0]       # track 0; the sound at +32
    sp = e.call(at["note_hook"], args, fp=fp, until=NOTE_SET)
    shadow = SHADOW
    check("argument is the shadow", e.u32(sp + 32) == shadow, hex(e.u32(sp + 32)))
    check("d2 is the shadow", e.uc.reg_read(UC_M68K_REG_D2) == shadow)
    check("shadow MODE (351) = 3", e.read(shadow + 351, 1) == b"\x03")
    check("shadow offset 2 (359) = -12", e.read(shadow + 359, 1) == b"\xf4")
    check("shadow step mask (356..357) = b6f7", e.read(shadow + 356, 2) == bytes.fromhex("b6f7"),
          e.read(shadow + 356, 2).hex())
    check("shadow copies the rest", e.read(shadow + 100, 1) == bytes([100]))
    check("list filed for trigless_hook", e.u32(LAST_NOTE) == lst)

    print("note hook: a list without arp locks leaves the note alone")
    plain = e.alloc(1700)
    e.put32(rec + 84, plain)
    sp = e.call(at["note_hook"], args, fp=fp, until=NOTE_SET)
    check("argument unchanged", e.u32(sp + 32) == sound)
    check("d2 is the sound", e.uc.reg_read(UC_M68K_REG_D2) == sound)

    print("trigless: a list the note hook did not handle moves the running arp")
    other = e.alloc(1164)
    e.write(other, b"\x11" * 1163)
    e.put32(ARP_STATE + 32, other)
    e.put32(TRACK_SOUNDS, other)
    e.put32(LAST_NOTE, 0)
    e.call(at["trigless_hook"], [0, lst, 0x80003AF0])
    check("arp state sound is the shadow", e.u32(ARP_STATE + 32) == shadow, hex(e.u32(ARP_STATE + 32)))
    check("per-track table is the shadow", e.u32(TRACK_SOUNDS) == shadow)
    check("shadow MODE = 3", e.read(shadow + 351, 1) == b"\x03")
    check("shadow copied from the running sound", e.read(shadow + 100, 1) == b"\x11")

    print("trigless: the note's own list does nothing more")
    e.put32(ARP_STATE + 32, other)
    e.put32(LAST_NOTE, lst)
    e.call(at["trigless_hook"], [0, lst, 0x80003AF0])
    check("arp state untouched", e.u32(ARP_STATE + 32) == other)
    check("LAST_NOTE consumed", e.u32(LAST_NOTE) == 0)

    print("paste: an arp record of the clipboard's track lands on the destination")
    clip = e.alloc(96672 + 8)
    e.put32(clip + 96668, 0)                        # the clipboard's track
    ct = e.alloc(REC)
    e.record(ct, 0, 2, 0x20, {4: 0x0011})           # SPEED on the copied page's step 4
    fp = e.alloc(64) + 48
    e.put32(fp - 16, clip)
    dest = e.table()
    e.call(at["paste_core"], [ct, ct, dest, 16, 16, 1], fp=fp)
    d0 = e.uc.reg_read(UC_M68K_REG_D0)
    check("reported as handled (-2)", d0 == 0xFFFFFFFE, hex(d0))
    check("destination header (2, track 1 | 0x20)", e.read(dest, 2) == b"\x02\x21", e.read(dest, 2).hex())
    check("value on step 20", e.u16(dest + 2 + 2 * 20) == 0x0011)
    check("step 21 still free", e.u16(dest + 2 + 2 * 21) == 0xFFFF)
    e.record(ct, 0, 2, 0x21, {4: 0x0011})           # another track's record
    e.call(at["paste_core"], [ct, ct, e.table(), 0, 16, 1], fp=fp)
    check("another track's record passes through", e.uc.reg_read(UC_M68K_REG_D0) == 0x21)
    e.record(ct, 0, 5, 0x00, {4: 0x1234})           # a stock record: registers must survive
    seeds = {r: 0x11110000 + i for i, r in enumerate(KEPT)}
    for r, v in seeds.items():
        e.uc.reg_write(getattr(mc, "UC_M68K_REG_" + r), v)
    e.call(at["paste_core"], [ct, ct, e.table(), 0, 16, 1], fp=fp)
    moved = [r for r, v in seeds.items() if e.uc.reg_read(getattr(mc, "UC_M68K_REG_" + r)) != v]
    check("a stock record leaves every register as it was", not moved, ",".join(moved))

    print("clear: placing a trig clears its step's arp locks, then frees the record")
    t = e.table()
    e.record(t, 0, 2, 0x20, {5: 0x0007, 6: 0x0008})
    e.record(t, 1, 2, 0x21, {5: 0x0009})            # track 2's: kept
    model = e.model(t)
    e.call(at["clear_hook"], [model, 0, 5])
    check("step 5 cleared", e.u16(t + 2 + 10) == 0xFFFF)
    check("step 6 kept", e.u16(t + 2 + 12) == 0x0008)
    check("header kept", e.read(t, 2) == b"\x02\x20")
    check("other track kept", e.u16(t + REC + 2 + 10) == 0x0009)
    e.call(at["clear_hook"], [model, 0, 6])
    check("record freed when empty", e.read(t, 2) == b"\xff\xff", e.read(t, 2).hex())

    print("pattern load: arp ids back to tagged records, free and stock records as stock")
    stored = e.alloc(REC * RECS)
    e.write(stored, b"\xff" * (REC * RECS))
    e.record(stored, 0, 109, 0x00, {3: 0x0005})     # SPEED (107 + 2), track 1
    e.record(stored, 2, 17, 0x00, {0: 0x1234})      # a stock lock, id 17 (slot 5)
    e.record(stored, 3, 108, 0x02, {7: 0x0001})     # RNG, track 3
    ram = e.alloc(TABLE_BYTES + 0x4000)
    e.call(LOADER, [ram, stored])
    check("arp record -> (2, 0x20)", e.read(ram, 2) == b"\x02\x20", e.read(ram, 2).hex())
    check("its step 3", e.u16(ram + 2 + 6) == 0x0005)
    check("free record stays free", e.read(ram + REC, 2) == b"\xff\xff", e.read(ram + REC, 2).hex())
    stock_hdr = e.read(ram + 2 * REC, 2)
    check("stock record loaded with its slot, track 0", stock_hdr[1] == 0 and stock_hdr[0] != 0xFF,
          stock_hdr.hex())
    check("stock record indexed", e.read(ram + INDEX + stock_hdr[0], 1) == b"\x02")
    check("RNG record -> (1, 0x22)", e.read(ram + 3 * REC, 2) == b"\x01\x22", e.read(ram + 3 * REC, 2).hex())
    free_after = all(e.read(ram + i * REC, 2) == b"\xff\xff" for i in range(4, RECS))
    check("records 4..79 stay free", free_after)
    check("no index byte for track 16+", e.read(ram + INDEX + 16 * 101, 16) == e.read(ram + INDEX + 16 * 101, 16))

    print("pattern save: tagged records back to (107 + k, track)")
    out = e.alloc(REC * RECS)
    e.call(SAVER, [out, ram])
    check("arp record -> (109, 0)", e.read(out, 2) == bytes([109, 0]), e.read(out, 2).hex())
    check("RNG record -> (108, 2)", e.read(out + 3 * REC, 2) == bytes([108, 2]), e.read(out + 3 * REC, 2).hex())
    check("stock record -> id 17", e.read(out + 2 * REC, 2) == bytes([17, 0]), e.read(out + 2 * REC, 2).hex())
    check("free record -> ff ff", e.read(out + REC, 2) == b"\xff\xff")

    print(f"\n{'all passed' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))

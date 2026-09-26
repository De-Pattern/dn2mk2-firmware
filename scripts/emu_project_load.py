"""Load a stored project through the firmware's own deserialiser, per build.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_project_load.py --build out/projload/fxmod+lfo4 \
        --project 00_Resources/07_DataCapture/projects_4_12890159B.bin

**Why.** A modded build halted with `EXCEPTION` the moment the owner opened
project 4, SKETCHPAD, which stock 1.11 wrote (2026-09-26). The emulator serves
no storage, so the `+Drive` read cannot run here -- but the read only fetches
bytes. What turns them into a project is `0x400e1782(project, image,
progress)`, the routine `0x400f6acc` calls once the file is in memory. It is
pure data: it checks the image's magic, trailer and version, then runs every
converter (128 patterns, 129 kits of 16 sounds, the 128-sound pool) and falls
back to a default for any record a converter rejects. Every mod that hooks a
converter is on this path.

**What it does.**

1. Restore `ui1200M` (a booted stock machine) and install the build the way its
   loader would have: every changed run below the `.data` image, then the
   appended area -- `DNFW` `CODE` chunks copied, their BSS zeroed and their init
   called (lfo4), or the `LFOW` blob copied to its runtime address (lfowaves).
2. Write the project's image (the file minus its 31-byte container header) to
   the working buffer `0x405cd96c`, where the MRAM path keeps it.
3. Call the deserialiser on the project the boot built at `0x41218970` (the
   static the boot's own default-project save hands `0x400e1494`, at
   `0x400bb2c4`), with the firmware's exception reporter hooked, and count which
   records each converter rejected.

The same run on stock is the control: the same bytes, the same call, one image
different.

**`--full`** runs the whole open-project routine `0x40042b92(app, slot,
progress)` instead -- the load *and* the activation after it -- with the one
step the emulator cannot serve, the `+Drive` read `0x400f6a2c`, answered by the
deserialiser on the image already in the working buffer. The deserialiser alone
cannot see a load that corrupts memory and returns success; the activation is
where that shows (2026-09-26: SKETCHPAD's song overrun, `src/dnfw/mods/songguard.py`).

**`--repair OFF=HEX`** edits the image before the load (image offsets), so a
crash can be narrowed to one field by repairing one field at a time.
"""

from __future__ import annotations

import argparse
import collections
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from emulib.image import code_chunks, differences             # noqa: E402
from emulib.machine import SCRATCH, STACK, Machine            # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
REPORTER = 0x4011EA6A            # formats "V%02x M%x P%08x"
DESERIALISE = 0x400E1782         # (project, image, progress) -> bool
PROJECT = 0x41218970             # the boot's project (0x400bb2c4)
IMAGE = 0x405CD96C               # the working-state buffer
IMAGE_BYTES = 12_890_116
FILE_HEADER = 31                 # a +Drive project file: 31-byte header, image, 12-byte trailer
DATA_IMAGE = 0x402FC000          # .data initialisers from here on: consumed at boot, now BSS
AREA_VA = 0x4030B980
BASE = 0x40000400

CONVERTERS = {
    0x400DE616: "pattern LOAD",
    0x400DDC52: "kit LOAD",
    0x400DEA6A: "song LOAD",
    0x400DD1EA: "sound LOAD",
}
DEFAULTS = {
    0x400E77D2: "settings default",
    0x400E7740: "pattern default",
    0x400E7044: "kit default",
    0x400E7A7C: "song default",
    0x400E7D4C: "sound default",
    0x400E7E66: "kit sound default",
}


def install(m, stock, built):
    """Leave the snapshot the way this build's own boot would have."""
    runs = [(va, b) for va, b in differences(stock, built[:len(stock)]) if va < DATA_IMAGE]
    m.apply(runs)
    area = built[AREA_VA - BASE:]
    what = f"{len(runs)} run(s)"
    if area[:4] == b"DNFW":
        for load, length, bss, init, blob in code_chunks(built):
            m.write(load, blob)
            m.write(load + length, bytes(bss))
            if init:
                m.call(init)
            what += f", CODE {length:,} B at {load:#010x}"
    elif area[:4] == b"LFOW":
        n = struct.unpack(">I", area[4:8])[0]
        m.write(0x46780000, area[:n])
        what += f", LFOW {n:,} B at 0x46780000"
    elif area:
        raise SystemExit(f"  unknown appended area {area[:4]!r}")
    m.flush()
    return what


def project_image(path, repairs):
    raw = bytearray(open(path, "rb").read())
    img = raw[FILE_HEADER:FILE_HEADER + IMAGE_BYTES]
    if img[:4] != b"\xbe\xef\xba\xce":
        raise SystemExit(f"  {path}: no image magic at offset {FILE_HEADER}")
    for spec in repairs:
        off, hexdata = spec.split("=")
        off = int(off, 0)
        data = bytes.fromhex(hexdata)
        img[off:off + len(data)] = data
    return bytes(img)


def call(m, fn, *args, count=3_000_000_000):
    from unicorn.m68k_const import UC_M68K_REG_A6, UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_SR

    frame = struct.pack(">I", m.ret) + b"".join(struct.pack(">I", a & 0xFFFFFFFF) for a in args)
    m.write(STACK, frame)
    m.uc.reg_write(UC_M68K_REG_A7, STACK)
    m.uc.reg_write(UC_M68K_REG_A6, 0)
    sr = m.uc.reg_read(UC_M68K_REG_SR)
    m.uc.reg_write(UC_M68K_REG_SR, (sr & ~0x0700) | 0x2700)
    try:
        m.uc.emu_start(fn, m.ret, count=count)
    finally:
        m.uc.reg_write(UC_M68K_REG_SR, sr)
    return m.uc.reg_read(UC_M68K_REG_D0)


APP = 0x4018A97A                 # the app singleton; built on first use (451,596 B)
OPEN_PROJECT = 0x40042B92        # (app, slot, progress): read, deserialise, activate
DRIVE_LOAD = 0x400F6A2C          # (handle, slot, project, progress): the +Drive read + 0x400e1782


def open_project(m, slot, n):
    """The firmware's own open-project routine, with the one step the emulator
    cannot serve -- the +Drive read -- answered from the image already written
    to the working buffer. -> its result."""
    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC

    before = n["i"]
    app = call(m, APP)
    print(f"  app singleton {app:#010x} ({n['i'] - before:,} instructions to build)")
    seen = {}

    def redirect(u, address, size, user):
        sp = u.reg_read(UC_M68K_REG_A7)
        handle, got_slot, project, progress = struct.unpack(">4I", bytes(u.mem_read(sp + 4, 16)))
        seen.update(slot=got_slot, project=project, at=n["i"])
        # 0x400e1782(project, image, progress), returning to 0x400f6a2c's caller.
        u.mem_write(sp + 4, struct.pack(">3I", project, IMAGE, progress))
        u.reg_write(UC_M68K_REG_PC, DESERIALISE)

    h = m.uc.hook_add(UC_HOOK_CODE, redirect, begin=DRIVE_LOAD, end=DRIVE_LOAD)
    progress = m.alloc(64)
    try:
        ok = call(m, OPEN_PROJECT, app, slot, progress)
    finally:
        m.uc.hook_del(h)
    print(f"  the +Drive read was asked for slot {seen.get('slot')} into project "
          f"{seen.get('project', 0):#010x} at {seen.get('at', 0):,}")
    return ok


def main() -> int:
    from unicorn import UC_HOOK_BLOCK, UC_HOOK_CODE, UcError
    from unicorn.m68k_const import UC_M68K_REG_A2, UC_M68K_REG_A7, UC_M68K_REG_PC

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", required=True, help="a folder holding section_3_MAIN_OS.bin, or 'stock'")
    p.add_argument("--project", required=True, help="a +Drive project file (31-byte header)")
    p.add_argument("--repair", action="append", default=[], metavar="OFF=HEX")
    p.add_argument("--repair-file", help="a file of OFF=HEX lines")
    p.add_argument("--dump", help="write the project object after the load to this file")
    p.add_argument("--full", action="store_true",
                   help="run the whole open-project routine 0x40042b92 (load, then activate), "
                        "with its +Drive read 0x400f6a2c answered by the deserialiser")
    p.add_argument("--probe", action="append", default=[], metavar="ADDR",
                   help="print d0-d7/a0-a7 each time ADDR runs (first 8 hits)")
    p.add_argument("--watch", action="append", default=[], metavar="ADDR[:LEN]",
                   help="print every write into ADDR..ADDR+LEN with the writing pc")
    p.add_argument("--slot", type=int, default=3, help="the project slot --full opens (0-based)")
    args = p.parse_args()

    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    if args.build == "stock":
        built = stock
    else:
        build = args.build if args.build.startswith("/") else os.path.join(ROOT, args.build)
        built = open(f"{build}/section_3_MAIN_OS.bin", "rb").read()
    proj_path = args.project if args.project.startswith("/") else os.path.join(ROOT, args.project)
    repairs = list(args.repair)
    if args.repair_file:
        repairs += [ln.strip() for ln in open(args.repair_file) if "=" in ln]

    m = Machine()
    uc = m.uc
    print(f"  {args.build}: installed {install(m, stock, built)}")
    img = project_image(proj_path, repairs)
    m.write(IMAGE, img)
    progress = m.alloc(32)
    print(f"  {os.path.basename(proj_path)}: image written to {IMAGE:#010x} "
          f"({len(repairs)} repair(s))")

    counts, fault, rejects = {}, {}, []
    last = {"conv": None, "args": None}
    n = {"i": 0}

    def at_reporter(u, address, size, user):
        if not fault:
            # The catch-all 0x40001252 saves SP and passes it: the frame.
            sp = u.reg_read(UC_M68K_REG_A7)
            a2 = struct.unpack(">I", bytes(u.mem_read(sp + 4, 4)))[0]
            try:
                rec = bytes(u.mem_read(a2, 64)).hex()
            except UcError:
                rec = ""
            fault.update(a2=a2, sp=sp, record=rec, last=dict(last), n=n["i"],
                         trail=list(trail))
        u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)

    def conv(addr, name):
        def hit(u, address, size, user):
            counts[name] = counts.get(name, 0) + 1
            sp = u.reg_read(UC_M68K_REG_A7)
            last["conv"] = name
            last["args"] = [hex(x) for x in struct.unpack(">II", bytes(u.mem_read(sp + 4, 8)))]
        uc.hook_add(UC_HOOK_CODE, hit, begin=addr, end=addr)

    for addr, name in CONVERTERS.items():
        conv(addr, name)

    def dflt(addr, name):
        def hit(u, address, size, user):
            counts[name] = counts.get(name, 0) + 1
            rejects.append((name, last["conv"], last["args"]))
        uc.hook_add(UC_HOOK_CODE, hit, begin=addr, end=addr)

    for addr, name in DEFAULTS.items():
        dflt(addr, name)

    def count(u, address, size, user):
        n["i"] += 1
    uc.hook_add(UC_HOOK_CODE, count)

    from unicorn.m68k_const import UC_M68K_REG_D0, UC_M68K_REG_A0
    for spec in args.probe:
        at = int(spec, 0)
        hits = {"n": 0}

        def probe(u, address, size, user, hits=hits):
            hits["n"] += 1
            if hits["n"] <= 8:
                d = [u.reg_read(UC_M68K_REG_D0 + i) for i in range(8)]
                a = [u.reg_read(UC_M68K_REG_A0 + i) for i in range(8)]
                print(f"  probe {address:#010x} #{hits['n']}: d " + " ".join(f"{x:08x}" for x in d)
                      + " | a " + " ".join(f"{x:08x}" for x in a))
        uc.hook_add(UC_HOOK_CODE, probe, begin=at, end=at)

    from unicorn import UC_HOOK_MEM_WRITE
    for spec in args.watch:
        at, _, ln = spec.partition(":")
        at, ln = int(at, 0), int(ln or "4", 0)

        def wrote(u, access, address, size, value, user):
            print(f"  write [{address:#010x}] <- {value & 0xFFFFFFFF:#x} ({size} B) "
                  f"from pc {u.reg_read(UC_M68K_REG_PC):#010x} at n={n['i']:,}")
        uc.hook_add(UC_HOOK_MEM_WRITE, wrote, begin=at, end=at + ln - 1)

    trail = collections.deque(maxlen=48)       # the last basic blocks entered

    def block(u, address, size, user):
        trail.append(address)
    uc.hook_add(UC_HOOK_BLOCK, block)

    started = time.time()
    err = None
    try:
        if args.full:
            ok = open_project(m, args.slot, n)
        else:
            ok = call(m, DESERIALISE, PROJECT, IMAGE, progress)
    except UcError as exc:
        ok, err = None, exc
    pc = uc.reg_read(UC_M68K_REG_PC)
    print(f"  deserialiser: {n['i']:,} instructions, {time.time() - started:.0f}s, "
          f"returned {ok!r}, pc {pc:#010x}{'' if err is None else f', error {err}'}")
    print("  calls: " + ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())))
    for name, cv, a in rejects[:60]:
        off = int(a[1], 16) - IMAGE if a else 0
        print(f"    rejected -> {name}: {cv} {a} (image+{off:#x})")
    if len(rejects) > 60:
        print(f"    ... {len(rejects) - 60} more")
    if args.dump:
        with open(args.dump, "wb") as f:
            f.write(m.read(PROJECT, 18_977_747))
    if fault:
        rec = bytes.fromhex(fault["record"]) if fault["record"] else b""
        print(f"\n  ** FAULT after {fault['n']:,}: the firmware drew EXCEPTION. sp {fault['sp']:#010x}, "
              f"frame at {fault['a2']:#010x}: {fault['record'][:96]}")
        if len(rec) >= 8:
            v = ((rec[0] & 3) << 6) | (rec[1] >> 2)
            print(f"     V{v:02X} M{rec[2] & 15:X} P{int.from_bytes(rec[4:8], 'big'):08X}; "
                  f"last converter {fault['last']}")
        print("     last blocks: " + " ".join(f"{a:08x}" for a in fault["trail"]))
        return 1
    if err is not None or ok is None:
        return 1
    print("\n  loaded clean." if ok & 0xFF else "\n  the deserialiser REFUSED the image.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

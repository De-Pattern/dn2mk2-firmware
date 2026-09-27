"""ONESHOT in the ColdFire emulator: MACHINE SEL offers it, choosing it sets type 5,
its SYN page is the DT2's (names and formatters), a push-and-turn moves a value,
and the frame the ColdFire builds carries it where the DSP adapter reads it.

    # in WSL, with digikit's venv (docs/emulator.md); the build is a directory holding
    # section_3_MAIN_OS.bin (scripts/build_oneshot.py writes one):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_oneshot_page.py --build out/oneshot --prepare \\
        --snapshot /root/dn2-snapshots/Digitone_II_OS1.11/boot400M.snap \\
        --save /root/oneshot/os-ui800M.snap
    ... scripts/emu_oneshot_page.py --build out/oneshot --snapshot /root/oneshot/os-ui800M.snap \\
        [--steps "..."] [--json OUT] [--stock]

**Why two runs.** MACHINE SEL builds its rows once, about 67 M instructions
after `boot400M` (Waverider M5 found this), so `ui1200M` -- booted from stock --
shows five machines whatever is installed over it. `--prepare` installs the
build over `boot400M` *before* that moment, exactly as the startup loader would
have left memory (MAIN OS's changed runs, and every appended `CODE` chunk at its
load address), runs to the UI and saves a snapshot. The drive run restores that.

Steps (comma-separated): `func-src` (MACHINE SEL), `up`, `down`, `left`, `right`,
`yes`, `no`, `syn` (tap the SYN key), `png:NAME`, `wait:MILLIONS`,
`turn:ENC:DELTA` (push and turn: what moves a value here), `sync` (every track's
mirror through the kit-load sync), `frame:NAME` (enter the audio ISR once and keep
the 2,688-byte frame it built, big-endian words), `mem:VA:N`.

Watched throughout: the machine setter's write of `sound+0xDE`, every call of
`param_set_slot_to_id` with type 5 (slot -> answer), and the SYN page accessors'
type arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from emulib.image import AREA_VA, BASE, code_chunks, differences   # noqa: E402
from emulib.machine import SNAP, Machine                            # noqa: E402
from emulib.panel import DOWN, LEFT, NO, RIGHT, UP, YES, Panel      # noqa: E402

FUNC, SRC = (2, 0), (0, 1)             # codes 17 and 2 (code = channel * 8 + bit + 1); SRC is SYN
KEYS = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT, "yes": YES, "no": NO}

SETTER_WRITE = 0x4004CC94              # moveb %d2,%a0@(222)
FAULT_REPORTER = 0x4011EA6A            # formats `V%02x M%x P%08x` (emu_boot_check.py)
SLOT_TO_ID = 0x400DC02A
PAGE_FNS = {0x400C248E: "overview(type)", 0x400C24D2: "count(type)", 0x400C24EE: "page(type, n)"}
ISR = 0x40025E36
FRAME_BUILT = 0x400275A2
FRAME, FRAME_BYTES = 0x80005E60, 2688
FRAME_MACHINE, SLOT_BASE, SLOT_STRIDE = 148, 218, 146
KIT_POINTER, KIT_SYNC, SOUND_STRIDE = 0x800052A0, 0x40025AF4, 1163
TRACK_SYNC = 0x4002549C                  # (sound, track) -> the builder's per-track mirror
MIRROR_TYPE, MIRROR_STRIDE = 0x80003AF0 + 3468, 153
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400


def install(machine, build: pathlib.Path, stock: bytes) -> dict:
    """What the startup loader would have left in memory: MAIN OS's changed runs up to
    the stock end, and every CODE chunk at its load address. The appended area itself
    is not written: at run time it lies inside BSS, which the loader's caller clears."""
    image = (build / "section_3_MAIN_OS.bin").read_bytes()
    runs = [(va, blob) for va, blob in differences(stock, image) if va < AREA_VA]
    n = machine.apply(runs)
    chunks = code_chunks(image) if len(image) > len(stock) else []
    for load, length, bss, init, blob in chunks:
        machine.write(load, blob)
        if bss:
            machine.write(load + length, bytes(bss))
    machine.flush()
    return {"runs": len(runs), "bytes": n, "chunks": [(f"{c[0]:#x}", c[1]) for c in chunks]}


def ranges(build: pathlib.Path, stock: bytes) -> list[dict]:
    """The same installation as `install`, as digikit guirun's --patch-ranges rows: boot400M
    has no timer state for this harness to claim, so the prepare run is guirun's
    (`--patch-ranges FILE --save-at 800M:SNAP`), as Waverider M5's was."""
    image = (build / "section_3_MAIN_OS.bin").read_bytes()
    rows = [{"va": f"{va:x}", "hex": blob.hex()} for va, blob in differences(stock, image) if va < AREA_VA]
    for load, length, bss, init, blob in (code_chunks(image) if len(image) > len(stock) else []):
        rows.append({"va": f"{load:x}", "hex": (blob + bytes(bss)).hex()})
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/oneshot")
    p.add_argument("--root", default=str(HERE.parent))
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--prepare", action="store_true", help="install over boot400M, run, save")
    p.add_argument("--save", default=None)
    p.add_argument("--run", type=int, default=400, help="millions of instructions for --prepare")
    p.add_argument("--warmup", type=int, default=20_000_000)
    p.add_argument("--steps", default="func-src,wait:20,png:menu,down,down,png:cursor,yes,wait:30,"
                   "png:syn,turn:0:3,png:tune,sync,frame:after")
    p.add_argument("--png-dir", default=None)
    p.add_argument("--json", default=None)
    p.add_argument("--stock", action="store_true", help="install nothing: the control")
    p.add_argument("--ranges", default=None,
                   help="write what --prepare would install as guirun --patch-ranges JSON, and stop")
    a = p.parse_args()
    if a.ranges:
        stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
        rows = ranges(pathlib.Path(a.root) / a.build, stock)
        pathlib.Path(a.ranges).write_text(json.dumps({"ranges": rows}))
        print(f"  wrote {len(rows)} ranges, {sum(len(r['hex']) // 2 for r in rows):,} B to {a.ranges}")
        return 0

    root = pathlib.Path(a.root)
    build = root / a.build
    png_dir = pathlib.Path(a.png_dir) if a.png_dir else build / ("screens-stock" if a.stock else "screens")
    machine = Machine(a.snapshot)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    installed = None
    if not a.stock:
        installed = install(machine, build, stock)
        print(f"  installed {installed}")
    else:
        print("  stock: nothing installed (the control)")

    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K

    uc = machine.uc
    panel = Panel(machine, png_dir=str(png_dir))

    if a.prepare:
        from emu.checkpoint import save_longrun
        ran = panel.settle(a.run * 1_000_000)
        print(f"  ran {ran:,} instructions; frames composed: {panel.frames()}")
        panel.screen("prepared")
        if a.save:
            pathlib.Path(a.save).parent.mkdir(parents=True, exist_ok=True)
            save_longrun(machine.m, machine.ev, panel.timers, a.save)
            print(f"  saved {a.save}")
        return 0

    def arg(off):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        return struct.unpack(">i", bytes(uc.mem_read(sp + off, 4)))[0]

    writes, slot_calls, page_calls, frames, shots, mems = [], {}, {}, {}, {}, {}
    built = {"n": 0}

    def setter(uc_, address, size, user):
        writes.append({"sound": f"{uc.reg_read(K.UC_M68K_REG_A0):#010x}",
                       "type": uc.reg_read(K.UC_M68K_REG_D2) & 0xFF})
    uc.hook_add(UC_HOOK_CODE, setter, begin=SETTER_WRITE, end=SETTER_WRITE)

    def slot_in(uc_, address, size, user):
        slot, typ = arg(4), arg(8)
        if typ == 5:
            key = str(slot)
            slot_calls[key] = slot_calls.get(key, 0) + 1
    uc.hook_add(UC_HOOK_CODE, slot_in, begin=SLOT_TO_ID, end=SLOT_TO_ID)

    for va, name in PAGE_FNS.items():
        def hit(uc_, address, size, user, name=name):
            t = str(arg(4))
            row = page_calls.setdefault(name, {})
            row[t] = row.get(t, 0) + 1
        uc.hook_add(UC_HOOK_CODE, hit, begin=va, end=va)

    faults = {"n": 0, "records": []}

    def reporter(uc_, address, size, user):
        # the exception frame the reporter formats: a2 -> {format/vector word, PC, ...}
        faults["n"] += 1
        if len(faults["records"]) < 4:
            a2 = arg(4) & 0xFFFFFFFF        # its argument: the exception frame
            try:
                rec = bytes(uc.mem_read(a2, 16))
            except Exception:                                  # noqa: BLE001
                rec = b""
            faults["records"].append({"a2": f"{a2:#010x}", "frame": rec.hex(),
                                      "pc": f"{struct.unpack_from('>I', rec, 4)[0]:#010x}" if rec else None})
            print(f"    FAULT {faults['records'][-1]}")
    uc.hook_add(UC_HOOK_CODE, reporter, begin=FAULT_REPORTER, end=FAULT_REPORTER)

    def builder_done(uc_, address, size, user):
        built["n"] += 1
    uc.hook_add(UC_HOOK_CODE, builder_done, begin=FRAME_BUILT, end=FRAME_BUILT)

    def guest_call(fn, *args, limit=5_000_000):
        regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]
        saved = [uc.reg_read(r) for r in regs]
        saved_pc = uc.reg_read(K.UC_M68K_REG_PC)
        sp = STACK_TOP - 0x100
        machine.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x) for x in args))
        machine.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        stepper = getattr(machine.m, "_fast_stepper_obj", None)
        if stepper is not None:
            stepper.left = 1 << 40
        # a code hook for the call's length, as Waverider M5's harness has: without one
        # the fast stepper's chained blocks ran these calls into a fault in the stock
        # control too (a harness artefact, not the firmware's)
        h = uc.hook_add(UC_HOOK_CODE, lambda *_: None)
        try:
            uc.emu_start(fn, SENTINEL, count=limit)
        finally:
            uc.hook_del(h)
            if stepper is not None:
                stepper.left = 0
            for r, v in zip(regs, saved):
                uc.reg_write(r, v)
            uc.reg_write(K.UC_M68K_REG_PC, saved_pc)

    panel.settle(a.warmup)
    for step in [s.strip() for s in a.steps.split(",") if s.strip()]:
        if step == "func-src":
            panel.hold(FUNC, 3_000_000)
            panel.tap(SRC, after=3_000_000)
            panel.let_go(FUNC)
        elif step == "syn":
            panel.tap(SRC, after=15_000_000)
        elif step in KEYS:
            panel.tap(KEYS[step])
        elif step.startswith("png:"):
            shots[step[4:]] = panel.screen(step[4:])
            print(f"    frames composed {panel.frames()}, pc {machine.pc:#010x}, "
                  f"fault reporter hits {faults['n']}")
        elif step.startswith("wait:"):
            panel.settle(int(float(step[5:]) * 1_000_000))
        elif step.startswith("turn:"):
            _, enc, delta = step.split(":")
            panel.push_and_turn(int(enc), int(delta))
        elif step.startswith("vals"):
            # track 0's sound value words for the machine slots (sound + 0x14 + 2 slot, BE)
            kit = machine.long(KIT_POINTER)
            snd = machine.read(kit + 52, SOUND_STRIDE)
            row = {s: f"{struct.unpack_from('>H', snd, 0x14 + 2 * s)[0]:#06x}" for s in range(25, 35)}
            mems[step] = row
            print(f"    {step}: type {snd[0xDE]}, slots {row}")
        elif step.startswith("mem:"):
            _, va, n = step.split(":")
            mems[va] = machine.read(int(va, 0), int(n, 0)).hex()
        elif step == "sync":
            guest_call(KIT_SYNC, machine.long(KIT_POINTER))
        elif step.startswith("sync:"):
            track = int(step[5:])
            guest_call(TRACK_SYNC, machine.long(KIT_POINTER) + 52 + SOUND_STRIDE * track, track)
        elif step.startswith("frame:"):
            name = step[6:]
            before = built["n"]
            guest_call(ISR)
            frame = machine.read(FRAME, FRAME_BYTES)
            png_dir.mkdir(parents=True, exist_ok=True)
            (png_dir / f"{name}.frame_be.bin").write_bytes(frame)
            kit = machine.long(KIT_POINTER)
            sound0 = machine.read(kit + 52, SOUND_STRIDE)
            (png_dir / f"{name}.sound0_be.bin").write_bytes(sound0)
            words = [struct.unpack_from(">H", frame, FRAME_MACHINE + 2 * t)[0] for t in range(16)]
            sound_types = [machine.read(kit + 52 + SOUND_STRIDE * t + 0xDE, 1)[0] for t in range(16)]
            mirror_types = [machine.read(MIRROR_TYPE + MIRROR_STRIDE * t, 1)[0] for t in range(16)]
            values0 = {s: f"{struct.unpack_from('>H', sound0, 0x14 + 2 * s)[0]:#06x}"
                       for s in range(25, 35)}
            print(f"    sound types {sound_types}; mirror types {mirror_types}")
            print(f"    track 0 sound values 25..34: {values0}")
            slot0 = [struct.unpack_from(">H", frame, SLOT_BASE + 2 * k)[0] for k in range(41)]
            frames[name] = {"builder_ran": built["n"] - before, "machine_words": words,
                            "sound_types": sound_types, "mirror_types": mirror_types,
                            "track0_sound_values_25_34": values0,
                            "track0_slots_25_65": {25 + k: f"{v:#06x}" for k, v in enumerate(slot0)}}
            print(f"  frame {name}: builder ran {built['n'] - before}; machine words {words}")
            print(f"    track 0 slots 25..34: {[f'{v:#06x}' for v in slot0[:10]]}")
        else:
            raise SystemExit(f"unknown step {step!r}")
        print(f"  {step}")

    result = {"build": str(build), "snapshot": a.snapshot, "stock": a.stock, "installed": installed,
              "screens": shots, "setter_writes": writes, "slot_to_id_type5": slot_calls,
              "page_accessors": page_calls, "frames": frames, "memory": mems,
              "faults": faults}
    print(json.dumps(result, indent=1))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(result, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

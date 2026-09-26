"""Waverider in the ColdFire emulator: MACHINE SEL offers it, choosing it sets type 5,
and the frame the ColdFire builds carries it.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_waverider_menu.py --build out/waverider-m5 \\
        --snapshot /root/wr-m5/wr-ui800M.snap [--steps "..."] [--json OUT]

**The snapshot matters.** The MACHINE SEL view builds its rows once, at about
67 M instructions after `boot400M` (its constructor `0x4005b6de` calls the SYN
row builder `0x4005b2c0`), so `ui1200M` -- booted from the stock image -- holds
stock rows whatever is installed over it. `wr-ui800M` is `boot400M` with this
build installed before that moment and run on to the SYN page by digikit's
`guirun --patch-ranges ... --save-at 800M` (docs, Milestone 5). The build's
changed runs are installed again here, which is a no-op on that snapshot and
keeps the harness honest about what it ran.

The panel is driven as a person would drive it (`emulib.panel`): FUNC held, SRC
tapped, DOWN, YES. Watched while it runs:

- every call of the accessors the build bounds or reroutes, with its type
  argument, so a type 5 reaching one that was *not* rerouted shows up;
- the machine setter's write of `sound+0xDE` (`0x4004cc94`): which sound, which
  type;
- the frame: the audio ISR does not run in this emulator, so `frame:NAME` enters
  it directly (`0x40025e36`, as `emu_mirror_base.py` does), checks that the
  frame builder's loop ran (`0x400275a2`), and keeps the 2,688-byte frame from
  `0x80005e60` -- big-endian 16-bit words at the offsets `dnfw.waverider.frame`
  uses.

Steps (comma-separated): `func-src` (open MACHINE SEL), `up`, `down`, `left`,
`right`, `yes`, `no`, `png:NAME`, `wait:MILLIONS`, `turn:ENC:DELTA` (push and
turn -- what moves a value here, parameters included), `spin:ENC:DELTA` (a
plain turn: shows the value, moves nothing in this emulator, stock included),
`tap:CODE`, `press:CODE` / `release:CODE` (hold a key: TRIG 1-16 are 25-40 and
play the track), `sync:T` (the track's mirror through `0x4002549c`), `sync`
(every track through the kit-load sync `0x40025af4`), `frame:NAME` (the ISR, and
the frame it built, with the mirror and the sixteen sounds beside it),
`blocks:NAME:MILLIONS[:ENC:DELTA]` (every instruction address run), `mem:VA:N`.
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

from emulib.image import differences                           # noqa: E402
from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import DOWN, LEFT, NO, RIGHT, UP, YES, Panel  # noqa: E402

FUNC, SRC = (2, 0), (0, 1)             # codes 17 and 2 (code = channel * 8 + bit + 1)
KEYS = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT, "yes": YES, "no": NO}

# the accessors the build touches, and where each keeps its type argument on entry
WATCH = {
    0x400DC02A: ("param_set_slot_to_id(slot, type, filter)", 8),
    0x400DC19A: ("permission(type, track)", 4),
    0x400DC15C: ("attribute byte(type)", 4),
    0x400DC176: ("all-tracks(type)", 4),
    0x400DC332: ("long name(type)", 4),
    0x400DC358: ("short name(type)", 4),
    0x400DC37E: ("name column 3(type)", 4),
    0x40059274: ("MACHINE SEL group(type)", 4),
    0x400394BE: ("the machine's parameter list(out, type)", 4),
    0x4004CC08: ("machine setter(sound, type, flag)", 8),
    0x40031880: ("MACHINE SEL commit(model, track, type)", 12),
    0x4004C30C: ("machine change: reset its parameters(sound, 1, old type, 0)", 12),
}
SETTER_WRITE = 0x4004CC94               # moveb %d2,%a0@(222)
# every `mvs.b %aN@(222),%dM` in the image (objdump of MAIN OS): site -> N
TYPE_READS = {0x400254B4: 2, 0x40031BD2: 0, 0x40031C1C: 0, 0x40036478: 0, 0x40036738: 0,
              0x40036C24: 0, 0x4004B816: 0, 0x4004CC82: 0, 0x4004DE0E: 3, 0x400A801C: 0,
              0x400B1668: 0}
GETTER_RTS = 0x4003647C                 # rts of the machine-type getter 0x40036462
TRACK_GETTER_EXIT = 0x4004B81E          # getMachineType(track) 0x4004b7f2: the common exit
ISR = 0x40025E36                        # the audio frame handler: modulation, frame, send
FRAME_BUILT = 0x400275A2                # the builder's sixteen passes are done
FRAME = 0x80005E60
FRAME_BYTES = 2688
FRAME_MACHINE = 148                     # + 2t
MIRROR, MIRROR_BYTES = 0x800068E4, 202  # the modulated per-track values the builder copies
KIT_POINTER, KIT_SYNC =0x800052A0, 0x40025AF4   # the live kit; its sixteen-track sync
TRACK_SYNC, SOUND_STRIDE = 0x4002549C, 1163      # (sound, track) -> the mirror; kit + 52 + 1163 t
MIRROR_TYPE, MIRROR_STRIDE =0x80003AF0 + 3468, 153   # the builder's per-track type byte
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400   # above BSS (0x466b74d0); Machine.write maps it


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/waverider-m5")
    p.add_argument("--root", default=str(HERE.parent))
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=20_000_000)
    p.add_argument("--steps", default="func-src,wait:20,png:menu,down,down,png:cursor,"
                   "yes,wait:30,png:syn,frame:after")
    p.add_argument("--png-dir", default=None)
    p.add_argument("--json", default=None)
    p.add_argument("--stock", action="store_true", help="install nothing: the control")
    p.add_argument("--regs-at", action="append", default=[], help="record registers at VA")
    a = p.parse_args()

    root = pathlib.Path(a.root)
    build = root / a.build
    png_dir = pathlib.Path(a.png_dir) if a.png_dir else build / ("screens-stock" if a.stock else "screens")
    machine = Machine(a.snapshot)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    if not a.stock:
        image = (build / "section_3_MAIN_OS.bin").read_bytes()
        runs = differences(stock, image)
        n = machine.apply(runs)
        print(f"  installed {len(runs)} run(s), {n} bytes, from {build}")
    else:
        print("  stock: nothing installed (the control)")

    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K

    uc = machine.uc
    calls: dict[str, dict] = {}
    writes, frames, shots, mems = [], {}, {}, {}
    built, counted = {"n": 0}, {"n": 0}

    def arg(off):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        return struct.unpack(">i", bytes(uc.mem_read(sp + off, 4)))[0]

    for va, (name, off) in WATCH.items():
        def hit(uc_, address, size, user, name=name, off=off):
            t = arg(off)
            ret = arg(0) & 0xFFFFFFFF
            row = calls.setdefault(name, {"n": 0, "types": {}, "type5_callers": []})
            row["n"] += 1
            row["types"][str(t)] = row["types"].get(str(t), 0) + 1
            if t == 5 and len(row["type5_callers"]) < 12 and f"{ret:#010x}" not in row["type5_callers"]:
                row["type5_callers"].append(f"{ret:#010x}")
        uc.hook_add(UC_HOOK_CODE, hit, begin=va, end=va)

    # every static read of a sound's machine type byte (`mvsb %aN@(222)`), with the
    # value it read: a site that reads 5 and was not rerouted is a candidate for
    # WaveTone-only behaviour that Waverider does not get
    type_reads: dict[str, dict] = {}
    for va, reg in TYPE_READS.items():
        def read(uc_, address, size, user, reg=reg):
            base = uc.reg_read(getattr(K, f"UC_M68K_REG_A{reg}"))
            v = struct.unpack(">b", bytes(uc.mem_read(base + 222, 1)))[0]
            row = type_reads.setdefault(f"{address:#010x}", {"n": 0, "values": {}})
            row["n"] += 1
            row["values"][str(v)] = row["values"].get(str(v), 0) + 1
        uc.hook_add(UC_HOOK_CODE, read, begin=va, end=va)

    getter5: dict[str, int] = {}

    def getter_rts(uc_, address, size, user):
        # the vtable getter 0x40036462 returns sound+0xDE: who asked, when it is 5
        if struct.unpack(">b", struct.pack(">B", uc.reg_read(K.UC_M68K_REG_D0) & 0xFF))[0] == 5:
            ret = f"{arg(0) & 0xFFFFFFFF:#010x}"
            getter5[ret] = getter5.get(ret, 0) + 1
    uc.hook_add(UC_HOOK_CODE, getter_rts, begin=GETTER_RTS, end=GETTER_RTS)

    regs_at: dict[str, list] = {}
    for va in a.regs_at:
        def at(uc_, address, size, user):
            rows = regs_at.setdefault(f"{address:#010x}", [])
            if len(rows) < 6:
                rows.append({f"{r}{i}": f"{uc.reg_read(getattr(K, f'UC_M68K_REG_{r}{i}')):#010x}"
                             for r in "DA" for i in range(8)})
        uc.hook_add(UC_HOOK_CODE, at, begin=int(va, 0), end=int(va, 0))

    track_getter5: dict[str, int] = {}

    def track_getter_exit(uc_, address, size, user):
        # getMachineType(track) 0x4004b7f2's exit: d0 the type, a2 saved at sp@0,
        # the caller's return address at sp@4
        if struct.unpack(">b", struct.pack(">B", uc.reg_read(K.UC_M68K_REG_D0) & 0xFF))[0] == 5:
            ret = f"{arg(4) & 0xFFFFFFFF:#010x}"
            track_getter5[ret] = track_getter5.get(ret, 0) + 1
    uc.hook_add(UC_HOOK_CODE, track_getter_exit, begin=TRACK_GETTER_EXIT, end=TRACK_GETTER_EXIT)

    def setter(uc_, address, size, user):
        a0 = uc.reg_read(K.UC_M68K_REG_A0)
        writes.append({"sound": f"{a0:#010x}", "type": uc.reg_read(K.UC_M68K_REG_D2) & 0xFF})
    uc.hook_add(UC_HOOK_CODE, setter, begin=SETTER_WRITE, end=SETTER_WRITE)

    mirror_writes = []

    def mirror(pc, address, value, size):
        if (address - MIRROR_TYPE) % MIRROR_STRIDE == 0 and len(mirror_writes) < 64:
            mirror_writes.append({"pc": f"{pc:#010x}", "track": (address - MIRROR_TYPE) // MIRROR_STRIDE,
                                  "value": value, "size": size})
    machine.watch_writes(MIRROR_TYPE, MIRROR_TYPE + MIRROR_STRIDE * 15, mirror)

    def builder_done(uc_, address, size, user):
        built["n"] += 1
    uc.hook_add(UC_HOOK_CODE, builder_done, begin=FRAME_BUILT, end=FRAME_BUILT)

    def count(uc_, address, size, user):
        counted["n"] += 1

    def guest_call(fn, *args, limit=5_000_000):
        """Call FN in the paused machine and put every register back, as digikit's
        machinepatch.call_dispatch does. SR is never read: the patched Unicorn
        clobbers the condition codes on that read. -> instructions run."""
        regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]
        saved = [uc.reg_read(r) for r in regs]
        saved_pc = uc.reg_read(K.UC_M68K_REG_PC)
        sp = STACK_TOP - 0x100
        machine.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x) for x in args))
        machine.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        counted["n"] = 0
        h = uc.hook_add(UC_HOOK_CODE, count)
        # `panel.settle` runs digikit's fast stepper, whose permanent block hook
        # stops the machine once its step budget is spent (longrun._FastStepper).
        # Left at zero, it stops a call at its first block with nothing run --
        # which is how three earlier calls here "returned" having done nothing.
        stepper = getattr(machine.m, "_fast_stepper_obj", None)
        if stepper is not None:
            stepper.left = 1 << 40
        try:
            uc.emu_start(fn, SENTINEL, count=limit)
        finally:
            if stepper is not None:
                stepper.left = 0
            uc.hook_del(h)
            for r, v in zip(regs, saved):
                uc.reg_write(r, v)
            uc.reg_write(K.UC_M68K_REG_PC, saved_pc)
        return counted["n"]

    panel = Panel(machine, png_dir=str(png_dir))
    panel.settle(a.warmup)
    for step in [s.strip() for s in a.steps.split(",") if s.strip()]:
        if step == "func-src":
            panel.hold(FUNC, 3_000_000)
            panel.tap(SRC, after=3_000_000)
            panel.let_go(FUNC)
        elif step in KEYS:
            panel.tap(KEYS[step])
        elif step.startswith("png:"):
            shots[step[4:]] = panel.screen(step[4:])
        elif step.startswith("wait:"):
            panel.settle(int(float(step[5:]) * 1_000_000))
        elif step.startswith("turn:"):
            _, enc, delta = step.split(":")
            panel.push_and_turn(int(enc), int(delta))
        elif step.startswith("spin:"):
            _, enc, delta = step.split(":")
            machine.pc = panel.panelin.encoder(machine.m, panel.profile, int(enc), int(delta))
            panel.settle(10_000_000)
        elif step.startswith("press:") or step.startswith("release:"):
            kind, code = step.split(":")
            key = ((int(code) - 1) // 8, (int(code) - 1) % 8)
            (panel.hold if kind == "press" else panel.let_go)(key, 2_000_000)
        elif step.startswith("tap:"):
            code = int(step[4:])
            panel.tap(((code - 1) // 8, (code - 1) % 8))
        elif step.startswith("blocks:"):
            # every instruction address executed while the machine runs MILLIONS
            # (after an optional encoder turn, so the page redraws): two of these,
            # taken with the track on WaveTone and on Waverider, diff to the code
            # that treats the two differently (emu_lfo4_modal.py's method). A code
            # hook, not a block hook: the fast stepper chains translated blocks.
            parts = step.split(":")
            name, millions = parts[1], parts[2]
            seen = set()

            def blk(uc_, address, size, user):
                seen.add(address)
            h = uc.hook_add(UC_HOOK_CODE, blk)
            if len(parts) == 5:
                machine.pc = panel.panelin.encoder(machine.m, panel.profile, int(parts[3]), int(parts[4]))
            panel.settle(int(float(millions) * 1_000_000))
            uc.hook_del(h)
            png_dir.mkdir(parents=True, exist_ok=True)
            (png_dir / f"{name}.blocks.txt").write_text("\n".join(f"{x:08x}" for x in sorted(seen)))
            print(f"  blocks {name}: {len(seen)} distinct")
        elif step.startswith("mem:"):
            _, va, n = step.split(":")
            mems[va] = machine.read(int(va, 0), int(n, 0)).hex()
        elif step.startswith("sync:"):
            # One track, through the routine the ISR's note path calls when a
            # triggered track's sound has changed (0x40026bbc / 0x40026bfe).
            track = int(step[5:])
            sound = machine.long(KIT_POINTER) + 52 + SOUND_STRIDE * track
            ran = guest_call(TRACK_SYNC, sound, track)
            print(f"  track sync {TRACK_SYNC:#010x}({sound:#010x}, {track}): {ran:,} instructions")
        elif step == "sync":
            # The mirror the frame builder reads (`0x80003af0 + 153t`, a copy of
            # sound+0xDE onwards) is refreshed by `0x4002549c(sound, track)`: from
            # the ISR when a track's note triggers with a changed sound, and for
            # all sixteen tracks by `0x40025af4(kit)` when a kit loads. No note
            # plays in this emulator, so the kit-load sync is entered -- the
            # firmware's own copy, not a poke.
            kit = machine.long(KIT_POINTER)
            ran = guest_call(KIT_SYNC, kit)
            print(f"  kit sync {KIT_SYNC:#010x}({kit:#010x}): {ran:,} instructions")
        elif step.startswith("frame:"):
            name = step[6:]
            before = built["n"]
            ran = guest_call(ISR)
            frame = machine.read(FRAME, FRAME_BYTES)
            png_dir.mkdir(parents=True, exist_ok=True)
            out = png_dir / f"{name}.frame_be.bin"
            out.write_bytes(frame)
            # what the builder read, kept beside what it wrote: the modulated
            # per-track mirror (202 B a track) and each track's sound object
            (png_dir / f"{name}.mirror_be.bin").write_bytes(machine.read(MIRROR, 16 * MIRROR_BYTES))
            kit = machine.long(KIT_POINTER)
            (png_dir / f"{name}.sounds_be.bin").write_bytes(
                b"".join(machine.read(kit + 52 + SOUND_STRIDE * t, SOUND_STRIDE) for t in range(16)))
            words = [struct.unpack_from(">H", frame, FRAME_MACHINE + 2 * t)[0] for t in range(16)]
            frames[name] = {"file": str(out), "builder_ran": built["n"] - before,
                            "isr_instructions": ran, "machine_words": words}
            print(f"  frame {name}: the builder ran {built['n'] - before} time(s) in {ran:,} "
                  f"instructions; machine words {words}")
        else:
            raise SystemExit(f"unknown step {step!r}")
        print(f"  {step}")

    result = {"build": str(build), "snapshot": a.snapshot, "stock": a.stock, "screens": shots,
              "calls": calls, "type_reads": type_reads, "getter_type5_callers": getter5,
              "track_getter_type5_callers": track_getter5, "regs_at": regs_at,
              "setter_writes": writes,
              "mirror_type_writes": mirror_writes,
              "frames": frames, "memory": mems}
    print(json.dumps(result, indent=1))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(result, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

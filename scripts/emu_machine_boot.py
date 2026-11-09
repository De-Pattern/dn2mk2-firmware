"""Boot a build with our machine types on the kit's tracks, and save the UI it reaches.

    DT2_SYX=.. DT2_SECTIONS=../sec111 DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin \\
    DNFW_EMU_FLAGS='{"weakptr": false}' ../digikit/.venv/bin/python -u scripts/emu_machine_boot.py \\
        --build BUILD_DIR --stock ../sec111/section_3_MAIN_OS.bin \\
        --snapshot ../digikit/out/snapshots/dn2-1.11/boot400M.snap --types 17,18,5,6,... \\
        --out BOOTED.snap [--save-at 800000000] [--json OUT]

v0.44's BOUNCE froze the unit at power-on whenever the working project held a BOUNCE track
(depaffect: "UNTITLED" and a small empty box, then nothing): the first page's first cell drew
its box, and its label lookup walked absolute address 0x000000EE (pages.py wr_label). This is
that power-on: `boot400M` (stock's boot, before the UI's views are built) with the build
installed as scripts/emu_install_snapshot.py does, so MACHINE SEL's rows are the build's own;
at the UI's first draw (0x4011d32a, the kit loaded) track t is given `--types[t % n]` -- the
active track (1) the first -- as a project holding those machines would load; then the boot
runs on to `--save-at`, where the machine is saved for scripts/emu_machine_sweep.py.

Fails on: any read below 0x40000000 by code that is not stock's (the unit has no RAM there:
the emulator's zero page let v0.44 draw; stock itself reads one byte at 0 at boot, at
0x400cecf2, and is allowed), the firmware's EXCEPTION reporter, the kit never set, or no
frame composed after it was.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import runpy
import struct
import sys

HERE = pathlib.Path(os.environ.get("DNFW_SCRIPTS", pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

KIT, SOUND_TYPE = 0x800052A0, 0xDE
REDRAW = 0x4011D32A
REPORTER = 0x4011EA6A


def differences(stock: bytes, image: bytes, base: int = 0x40000400):
    runs, i, n = [], 0, min(len(stock), len(image))
    while i < n:
        if stock[i] != image[i]:
            j = i
            while j < n and stock[j] != image[j]:
                j += 1
            runs.append((base + i, image[i:j]))
            i = j
        else:
            i += 1
    return runs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", required=True, type=pathlib.Path)
    p.add_argument("--stock", required=True, type=pathlib.Path)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--types", required=True, help="machine types for tracks 1.. in turn (the first on the active track)")
    p.add_argument("--save-at", type=int, default=800_000_000)
    p.add_argument("--out", required=True)
    p.add_argument("--json", default=None)
    p.add_argument("--digikit", default=os.environ.get("DIGIKIT", str(HERE.parent.parent / "digikit")))
    a = p.parse_args()
    types = [int(x) for x in a.types.split(",")]

    stock = a.stock.read_bytes()
    image = (a.build / "section_3_MAIN_OS.bin").read_bytes()
    runs = differences(stock, image)
    from dnfw.mods import platform
    copies = list(platform.runtime(image)) if len(image) > len(stock) else []

    sys.path.insert(0, a.digikit)
    sys.path.insert(0, os.path.join(a.digikit, "tools"))
    import emu.longrun as lr
    from emu import symbols
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_PROT_ALL, UcError
    from unicorn import m68k_const as K

    profile = symbols.resolve(stock)
    st = {"poked": None, "frames": 0, "frames_after": 0, "low": [], "faults": [], "stock_low": 0}

    def write(uc, va, data):
        try:
            uc.mem_write(va, data)
        except UcError:
            for page in range(va & ~0xFFFFF, va + len(data) + 0x100000, 0x100000):
                try:
                    uc.mem_map(page, 0x100000, UC_PROT_ALL)
                except UcError:
                    pass
            uc.mem_write(va, data)

    def low(uc, access, address, size, value, user):
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        off = pc - 0x40000400
        if 0 <= off < len(stock) - 8 and bytes(uc.mem_read(pc, 8)) == stock[off:off + 8]:
            st["stock_low"] += 1
            return
        if len(st["low"]) < 8:
            sp = uc.reg_read(K.UC_M68K_REG_A7)
            words = struct.unpack(">32I", bytes(uc.mem_read(sp, 128)))
            st["low"].append({"address": f"{address:#010x}", "pc": f"{pc:#010x}",
                              "callers": [f"{v:#010x}" for v in words if 0x40000400 <= v < 0x40220000][:6],
                              "after_poke": st["poked"] is not None})

    def reporter(uc, address, size, user):
        a2 = uc.reg_read(K.UC_M68K_REG_A2)
        st["faults"].append(bytes(uc.mem_read(a2, 16)).hex())

    def redraw(uc, address, size, user):
        if st["poked"] is not None:
            return
        kit = struct.unpack(">I", bytes(uc.mem_read(KIT, 4)))[0]
        if not 0x40000000 <= kit < 0x50000000:
            return
        for t in range(16):
            uc.mem_write(kit + 52 + 1163 * t + SOUND_TYPE, bytes([types[t % len(types)] & 0xFF]))
        st["poked"] = f"{kit:#010x}"

    def frame(uc, address, size, user):
        st["frames"] += 1
        if st["poked"] is not None:
            st["frames_after"] += 1

    original = lr.build

    def build(*args, **kw):
        out = original(*args, **kw)
        uc = out[0].uc
        for va, data in runs + copies:
            write(uc, va, data)
        uc.hook_add(UC_HOOK_MEM_READ, low, begin=0, end=0x3FFFFFFF)
        uc.hook_add(UC_HOOK_CODE, reporter, begin=REPORTER, end=REPORTER)
        uc.hook_add(UC_HOOK_CODE, redraw, begin=REDRAW, end=REDRAW)
        uc.hook_add(UC_HOOK_CODE, frame, begin=profile.panel_diff, end=profile.panel_diff)
        print(f"install: {len(runs)} run(s), {len(copies)} run-time copies; types {types}", flush=True)
        # guirun's terminal-loop detector is Digitakt II's address (0x4012d2fa), ordinary code on
        # DN2 1.11, where it ends a healthy boot at ~63M (docs/emulator.md, "Port 3"): registered
        # only where the instruction there is the spin itself (bra.s to itself, 60 fe)
        hook_at = out[5]

        def at(addr, cb, *rest, **kw):
            if addr == 0x4012D2FA and bytes(uc.mem_read(addr, 2)) != b"\x60\xfe":
                return None
            return hook_at(addr, cb, *rest, **kw)
        return (*out[:5], at, *out[6:])

    lr.build = build
    guirun = os.path.join(a.digikit, "tools", "guirun.py")
    sys.argv = ["guirun.py", a.snapshot, "--slc", "--save-at", f"{a.save_at}:{a.out}",
                "--limit", str(a.save_at + 20_000_000)]
    try:
        runpy.run_path(guirun, run_name="__main__")
    except SystemExit:
        pass
    pathlib.Path(a.out + ".section_3_MAIN_OS.bin").write_bytes(image)
    facts = {"the kit was set at the UI's first draw": st["poked"] is not None,
             "frames composed after it": st["frames_after"] > 0,
             "no read below 0x40000000 by our code": not st["low"],
             "no EXCEPTION": not st["faults"],
             "saved": pathlib.Path(a.out).exists()}
    ok = all(facts.values())
    print(f"\n  boot with types {types}: kit {st['poked']}, {st['frames_after']} frame(s) after "
          f"({st['frames']} in all); stock's own low reads {st['stock_low']}")
    for row in st["low"][:3]:
        print(f"  ** read of {row['address']} at pc {row['pc']} (callers {' '.join(row['callers'])}): "
              f"nothing answers there on the unit -- it freezes **")
    for f in st["faults"][:2]:
        print(f"  ** EXCEPTION {f} **")
    for k, v in facts.items():
        print(f"  {'ok  ' if v else 'FAIL'}  {k}")
    print(f"\n  machine boot: {'PASS' if ok else 'FAIL'}")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({"ok": ok, "facts": facts, **st}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Boot a build in digikit's ColdFire emulator from an early snapshot and save it at the UI.

    DT2_MAIN_IMG=... DT2_SECTIONS=... python scripts/emu_install_snapshot.py \\
        --build DIR_WITH_section_3_MAIN_OS.bin --snapshot boot400M.snap \\
        --stock STOCK_section_3_MAIN_OS.bin --save-at 1200000000 --out ui1200M-build.snap

Some views are built once, early: MACHINE SEL builds its rows about 67 M
instructions after `boot400M` (`docs/machine-list.md`). A UI snapshot booted on
stock therefore shows stock rows whatever is installed over it later. Upstream made
its Waverider snapshots with a private `guirun --patch-ranges`; this does the same
with digikit's public `tools/guirun.py`: it wraps `emu.longrun.build` so that, right
after the snapshot is restored, the build's changed runs and the platform loader's
run-time copies (`dnfw.mods.platform.runtime`) are written into memory -- what
`scripts/emu_waverider_menu.py` installs, but before the views are built -- and then
hands over to guirun with `--save-at`.

digikit (GPL-2.0+) is run as a tool; nothing of it is copied here.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import runpy
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))


def differences(stock: bytes, image: bytes, base: int = 0x40000400):
    """(va, bytes) runs where IMAGE differs from STOCK, over STOCK's length."""
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
    p.add_argument("--save-at", type=int, default=1_200_000_000)
    p.add_argument("--out", required=True)
    p.add_argument("--digikit", default=os.environ.get("DIGIKIT", "/mnt/d/01_Code/Z_Personal/digikit-up"))
    p.add_argument("--extra", action="append", default=[], help="more guirun arguments")
    a = p.parse_args()

    stock = a.stock.read_bytes()
    image = (a.build / "section_3_MAIN_OS.bin").read_bytes()
    runs = differences(stock, image)
    from dnfw.mods import platform
    copies = list(platform.runtime(image)) if len(image) > len(stock) else []
    print(f"install: {len(runs)} run(s), {sum(len(d) for _, d in runs)} bytes; "
          f"{len(copies)} run-time copies", flush=True)

    sys.path.insert(0, a.digikit)
    sys.path.insert(0, os.path.join(a.digikit, "tools"))
    import emu.longrun as lr
    from unicorn import UC_PROT_ALL, UcError

    original = lr.build

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

    def build(*args, **kw):
        out = original(*args, **kw)
        uc = out[0].uc
        for va, data in runs + copies:
            write(uc, va, data)
        print("install: written after restore", flush=True)
        return out

    lr.build = build
    sys.argv = ["guirun.py", a.snapshot, "--slc", "--save-at", f"{a.save_at}:{a.out}",
                "--limit", str(a.save_at + 20_000_000)] + a.extra
    runpy.run_path(os.path.join(a.digikit, "tools", "guirun.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Four taps on [MOD], and a picture of each page.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_screens.py

Everything else about step 4b is a number. This is the screen.

**Why this is valid now and was not this morning.** A snapshot harness installs
a build into `ui1200M`, a machine that has already booted and already built
every runtime table from the *stock* parameter table. While `lfo4-table` also
relocated the 68-byte companion, that made the two disagree -- the snapshot had
filled one address and the build read another -- and any screen it drew would
have been the harness's fault or the build's with no way to tell which. The
companion does not move any more (it has no base to move; see
`dnfw.patch.paramtable.runtime_literals`), and the 60-byte table's copy is
byte-identical for all 320 stock records, so everything the snapshot computed
still holds. Entries 321-330 are simply there now.

What a boot from reset gives that this does not is the loader, the init and the
first call into new code -- and `scripts/emu_boot_check.py` covers exactly
that, on the same build. The two halves together are the instrument; neither
alone is.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import code_chunks, differences, load_build     # noqa: E402
from emulib.machine import SNAP, Machine                          # noqa: E402
from emulib.panel import MOD, Panel                               # noqa: E402
from emulib.report import check, report                           # noqa: E402

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-value"
MODE_OBJECT = 0x447BF800
VEC_BEGIN, VEC_END, CURRENT = 124, 128, 144
LFO4_PAGE = 37


def words(blob):
    return [int.from_bytes(blob[i:i + 4], "big") for i in range(0, len(blob), 4)]


def pages(machine, obj):
    """-> (the page ids the mode offers, the index it is showing)."""
    begin, end = words(machine.read(obj + VEC_BEGIN, 8))
    if not begin or end <= begin:
        return [], -1
    return words(machine.read(begin, end - begin)), machine.long(obj + CURRENT)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--taps", type=int, default=5)
    p.add_argument("--object", type=lambda x: int(x, 0), default=MODE_OBJECT)
    args = p.parse_args()

    machine = Machine(args.snapshot)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    runs = differences(stock, image)
    machine.apply(runs)
    for load, _n, bss, init, blob in code_chunks(image):
        machine.load_code_chunk((load, len(blob), bss, init, blob))
    machine.flush()
    print(f"  installed {len(runs)} run(s), {len(code_chunks(image))} CODE chunk(s)")

    panel = Panel(machine, png_dir="out/lfo4-screens")
    panel.settle(args.warmup)
    print(f"  before any tap: pages {pages(machine, args.object)[0]}, "
          f"swapped {machine.long(sym['lfo4_pages_swapped'])}")

    seen = []
    for tap in range(args.taps):
        panel.tap(MOD)
        offered, current = pages(machine, args.object)
        shot = panel.screen(f"mod-{tap + 1}")
        seen.append((offered, current, shot))
        print(f"  [MOD] x{tap + 1}: pages {offered}, showing index {current} -> {shot}")

    swapped = machine.long(sym["lfo4_pages_swapped"])
    offered = seen[-1][0] if seen else []
    reached = sorted({c for _o, c, _s in seen if c >= 0})
    print(f"\n  lfo4_pages_swapped {swapped}, indices reached {reached}")

    check("the mode was given a fourth page", offered == [4, 5, 6, LFO4_PAGE],
          f"{offered}")
    check("it was given one exactly once", swapped == 1, f"{swapped}")
    check("[MOD] reaches the fourth page", 3 in reached, f"indices {reached}")
    check("and cycles past it rather than stopping", len(reached) == 4,
          f"indices {reached} over {args.taps} tap(s)")
    print("\n  The screens are the evidence. Look at them.")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

"""Which instruction reads a parameter's value while the MOD page is drawn?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_value_reads.py

A sound keeps its parameter values in an array at `+0x14`, two bytes per slot,
and **step 4a diverted the write**: `values[d2] = d3` at `0x40037be8`, where
the firmware's own `slot > 100` guard sat. LFO4's ids 101-108 now land in an
extension table instead.

Nothing has diverted the **read**, so the fourth page shows whatever
`sound->values[101]` happens to be -- which is `+0xDE`, the machine type, not a
value of LFO4's at all. Wiring it is the mirror of step 4a and needs the same
thing first: *which* instruction, out of the ones that could be.

Scanning the image for the addressing mode -- displacement 20, long index,
scale 2 -- finds **119 candidates**, most of them coincidence. This narrows it
by running: every candidate is hooked, the MOD page is opened, and the ones
that fire while it draws are the page's. A candidate that never fires is not
the page's reader whatever it looks like, and one that fires on every frame is.
"""

from __future__ import annotations

import argparse
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import MOD, Panel                            # noqa: E402

BASE = 0x40000400
VALUES_AT = 0x14                 # the sound's value array, two bytes per slot


def candidates(image: bytes):
    """Every `(20, An, Xn.l*2)` reference in the image, with its opcode.

    The extension word is `reg<<12 | 0x0A14`: long index, scale 2,
    displacement 20. Reads and writes both -- which is which is the opcode's
    business, and the point here is to hook them all and let the machine say.
    """
    out = []
    for i in range(0, len(image) - 2, 2):
        if image[i + 1] != VALUES_AT or image[i] & 0x0F != 0x0A:
            continue
        out.append((BASE + i - 2, struct.unpack_from(">H", image, i - 2)[0], image[i] >> 4))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--pages", type=int, default=3, help="how many [MOD] taps")
    args = p.parse_args()

    import os

    from unicorn import UC_HOOK_CODE

    machine = Machine(args.snapshot)
    image = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    sites = candidates(image)
    print(f"  {len(sites)} instruction(s) address the value array's shape")

    counts = {va: 0 for va, _op, _r in sites}

    def hit(uc, address, size, user):
        counts[address] += 1

    for va, _op, _r in sites:
        machine.uc.hook_add(UC_HOOK_CODE, hit, begin=va, end=va)

    panel = Panel(machine, png_dir="out/value-reads")
    panel.settle(args.warmup)
    before = dict(counts)
    for page in range(args.pages):
        panel.tap(MOD)
        fired = {va: counts[va] - before[va] for va in counts if counts[va] > before[va]}
        print(f"\n  after [MOD] x{page + 1} ({panel.screen(f'mod-{page + 1}')}):")
        for va in sorted(fired, key=fired.get, reverse=True):
            op = next(o for a, o, _r in sites if a == va)
            kind = "read" if op & 0xF000 in (0x7000, 0x3000) else "?"
            print(f"    {va:#010x}  x{fired[va]:,}  opcode {op:#06x}  {kind}")
        before = dict(counts)

    live = [va for va, n in counts.items() if n]
    print(f"\n  {len(live)} of {len(sites)} ever fired: "
          + ", ".join(f"{va:#010x}" for va in sorted(live)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

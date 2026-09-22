"""What does LFO3's page run when the DEST browser opens that LFO4's does not?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        DT2_BUILD=out/lfo4-ui2 /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_modal.py

Twice now this project has modelled the destination browser from reading and
been wrong -- first descriptors and mask thunks that fired zero times on both
pages, then the gate at `0x40039aba`, which turned out to build the **list**
(the order is right on the instrument now) and not to open the **window**.

So stop modelling it. `docs/lfo4-build-plan.md` says the method that has worked
every time is to **diff what two renders execute**, and this does exactly that
with no hypothesis at all: turn `DEST` with its push held on each MOD page,
record every basic block the machine enters, and report the blocks LFO3
reaches that LFO4 does not.

The answer is somewhere in that difference. Everything else on the two pages is
the same code, so the difference is small even though each set is large.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_BLOCK

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-ui2"))

DEST_ENCODER = 3                # the fourth dial on a MOD page is `DEST`
TURNS = 2
STOCK_END = 0x4030B980          # past this is our own code, not the firmware's

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

blocks = set()


def at_block(uc, address, size, user):
    blocks.add(address)


m.uc.hook_add(UC_HOOK_BLOCK, at_block)

panel = Panel(m, png_dir="out/modal")
panel.settle(60_000_000)

seen = {}
for page in ("LFO1", "LFO2", "LFO3", "LFO4"):
    panel.tap(MOD)
    blocks.clear()
    panel.push_and_turn(DEST_ENCODER, +1, times=TURNS)
    seen[page] = set(blocks)
    print(f"  {page}: {len(seen[page]):,} block(s) entered while DEST was turned"
          f"   screen {panel.screen(page.lower())}")

only3 = sorted(seen["LFO3"] - seen["LFO4"])
only4 = sorted(seen["LFO4"] - seen["LFO3"])
# A block LFO1 and LFO2 reach as well is per-LFO machinery LFO4 is missing from;
# one only LFO3 reaches could just as well be that page's own quirk.
shared = sorted(b for b in only3 if b in seen["LFO1"] and b in seen["LFO2"])

print(f"\n  LFO3 entered {len(only3)} block(s) LFO4 did not")
print(f"  LFO4 entered {len(only4)} block(s) LFO3 did not")
print(f"\n  of those, {len(shared)} are reached by LFO1 and LFO2 too -- "
      f"per-LFO machinery LFO4 is being left out of:")
for address in shared:
    where = "firmware" if address < STOCK_END else "ours"
    print(f"    {address:#010x}  ({where})")

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

trace = []


def at_block(uc, address, size, user):
    trace.append(address)


m.uc.hook_add(UC_HOOK_BLOCK, at_block)

panel = Panel(m, png_dir="out/modal")
panel.settle(60_000_000)

order, seen = {}, {}
for page in ("LFO1", "LFO2", "LFO3", "LFO4"):
    panel.tap(MOD)
    trace.clear()
    panel.push_and_turn(DEST_ENCODER, +1, times=TURNS)
    order[page] = list(trace)
    seen[page] = set(trace)
    print(f"  {page}: {len(order[page]):,} block entries, {len(seen[page]):,} distinct"
          f"   screen {panel.screen(page.lower())}")

# A block LFO1, LFO2 and LFO3 all reach and LFO4 never does is per-LFO
# machinery LFO4 is being left out of. One only LFO3 reaches could as easily be
# that page's own state.
missing = (seen["LFO1"] & seen["LFO2"] & seen["LFO3"]) - seen["LFO4"]
# **Our own code does not count.** The first block LFO3 reached and LFO4 did
# not was `lfo4_page_stub`'s stock branch -- page 6 has a record and page 37
# gets ours, so the two *must* diverge there, and it says nothing about the
# browser. A divergence inside this project's own stubs is the patch working.
missing = {b for b in missing if b < STOCK_END}
print(f"\n  {len(missing)} firmware block(s) all three reach and LFO4 never does")

# **The set says what is missing; the order says where it is lost.** Walk LFO3's
# trace to the first block LFO4 never reaches, and print what ran immediately
# before it: the decision is in those, and the block just before is the one that
# branched the other way.
BEFORE = 12
first = next((i for i, b in enumerate(order["LFO3"]) if b in missing), None)
if first is None:
    print("  LFO3 never entered one either -- the browser did not open for it")
else:
    print(f"\n  LFO3 diverges at entry {first:,} of {len(order['LFO3']):,}: "
          f"{order['LFO3'][first]:#010x}")
    print(f"  the {BEFORE} blocks it ran immediately before, newest last "
          f"(the last shared one branched):")
    for b in order["LFO3"][max(0, first - BEFORE):first + 1]:
        mark = "  <- LFO4 never gets here" if b in missing else ""
        where = "firmware" if b < STOCK_END else "ours"
        print(f"    {b:#010x}  ({where}){mark}")

    # And the same walk on LFO4, so the two can be read side by side.
    common = order["LFO3"][max(0, first - BEFORE):first]
    pivot = common[-1] if common else None
    if pivot is not None and pivot in seen["LFO4"]:
        at = len(order["LFO4"]) - 1 - order["LFO4"][::-1].index(pivot)
        print(f"\n  LFO4 reached {pivot:#010x} too, and went here instead:")
        for b in order["LFO4"][at:at + 6]:
            print(f"    {b:#010x}")

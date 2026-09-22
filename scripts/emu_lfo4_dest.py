"""Which of the destination browser's hard-coded LFO gates does LFO4 fail?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_dest.py

`scripts/scan_lfo_triples.py` finds six places that compare a parameter entry
against **78, 88 and 98** -- the `DEST` entries of LFO1, LFO2 and LFO3, written
as literals -- and five that choose a capability mask by testing bits 18, 17
and 16 of a record's `+44`. An entry that is none of the three leaves every one
of them by the door, which is why LFO4's `DEST` dials a raw number instead of
opening the browser.

Six sites and five cascades is eleven patches if all of them matter. This says
how many do: it opens the browser on LFO3's page and on LFO4's, and counts the
sites each render reaches. A site that never fires on LFO3 either is not part
of this, and a site that fires on both is not where LFO4 is being turned away.
"""
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A0, UC_M68K_REG_D0

# Which build to look at. `lfo4-value` is where the fault was measured;
# `DT2_BUILD=out/lfo4-ui` is where the fix is checked with the same probe.
BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-value"))

# `moveq #78` ... `#88` ... `#98`, the three `DEST` entries as literals.
GATES = (0x400397DA, 0x40039A9A, 0x40039CBC, 0x40039EBC, 0x400643C0, 0x40066D5C)
# `movel #0x1e00,%d0` at the head of a `btst #18 / #17 / #16` cascade.
CASCADES = (0x400397F2, 0x40039AD4, 0x40039CF6, 0x40039EF4, 0x400C2AA0)

# Where the mask lands (`movel %d0,%sp@(24)`), and where the list it built is
# counted: `0x400399e0` calls the builder at `0x40039a16` with `%fp@(-8)` as
# the output vector, then reloads it and pushes `begin` and `end`. Reading it
# there gives the number of destinations the page will offer -- which is the
# regression check that matters, because a wrong fourth mask branch would
# silently change what LFO1, LFO2 and LFO3 are offered too.
MASK_CHOSEN = 0x40039AF6
LIST_BUILT = 0x40039A22

DEST_ENCODER = 3                # the fourth dial on a MOD page is `DEST`
TURNS = 3

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

hits = {va: 0 for va in GATES + CASCADES}
masks, lengths = [], []


def count(uc, address, size, user):
    hits[address] += 1


for va in hits:
    m.uc.hook_add(UC_HOOK_CODE, count, begin=va, end=va)

m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: masks.append(uc.reg_read(UC_M68K_REG_D0)),
              begin=MASK_CHOSEN, end=MASK_CHOSEN)


def at_list(uc, address, size, user):
    vector = uc.reg_read(UC_M68K_REG_A0)
    begin = int.from_bytes(bytes(uc.mem_read(vector, 4)), "big")
    end = int.from_bytes(bytes(uc.mem_read(vector + 4, 4)), "big")
    lengths.append((end - begin) // 4)


m.uc.hook_add(UC_HOOK_CODE, at_list, begin=LIST_BUILT, end=LIST_BUILT)

panel = Panel(m, png_dir="out/dest")
panel.settle(60_000_000)


def report(label):
    before = report.last
    seen_masks, seen_lengths = masks[report.masks:], lengths[report.lengths:]
    report.last = dict(hits)
    report.masks, report.lengths = len(masks), len(lengths)
    gates = {va: hits[va] - before[va] for va in GATES}
    casc = {va: hits[va] - before[va] for va in CASCADES}
    print(f"{label}:")
    print("    gates    " + "  ".join(f"{va:#010x}x{n}" for va, n in gates.items()))
    print("    cascades " + "  ".join(f"{va:#010x}x{n}" for va, n in casc.items()))
    print(f"    mask {[hex(v) for v in seen_masks]}, "
          f"destinations offered {seen_lengths}")


report.last = dict(hits)
report.masks = report.lengths = 0

for page, taps in (("LFO1", 1), ("LFO2", 1), ("LFO3", 1), ("LFO4", 1)):
    for _ in range(taps):
        panel.tap(MOD)
    report.last = dict(hits)
    report.masks, report.lengths = len(masks), len(lengths)
    panel.push_and_turn(DEST_ENCODER, +1, times=TURNS)
    report(f"{page} DEST turned {TURNS}x")
    print(f"    screen: {panel.screen(f'{page.lower()}-dest')}")

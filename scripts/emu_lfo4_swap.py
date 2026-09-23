"""Does the live sound container ever move under us?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        DT2_BUILD=out/lfo4-browser /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_swap.py

From the instrument, 2026-09-22, the owner's own framing:

> "Is like some trigs qualify to be modulated and others doesn't"

Take that literally. LFO4's values are keyed by a live sound's **address**, and
the engine derives that address from a pointer:

    lfo4_sound_of(track) = *(0x800052a0) + 52 + track * 1163

`scripts/emu_lfo4_container.py` proves we follow that pointer when it moves.
**Nothing has ever asked whether it moves.** If the firmware double-buffers the
live kit and swaps the global, then the engine reads container A on some notes
and container B on others, while the panel wrote to whichever was current when
the knob was turned. Alternating buffers would qualify alternate trigs, which
is the shape the instrument describes.

So this watches the global itself -- every write, with the instruction that
made it -- across a warm-up, some panel work, and a long idle. A pointer that
never changes closes the idea; one that alternates between two values is the
answer.
"""
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_PC

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-browser"))

LIVE_CONTAINER = 0x800052A0
DEP_ENCODER = 7
IDLE_CHUNK = 20_000_000
CHUNKS = 15

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

writes = []


def at_write(uc, access, address, size, value, user):
    writes.append((uc.reg_read(UC_M68K_REG_PC), value, size))


m.uc.hook_add(UC_HOOK_MEM_WRITE, at_write,
              begin=LIVE_CONTAINER, end=LIVE_CONTAINER + 3)

panel = Panel(m, png_dir="out/swap")
start = m.long(LIVE_CONTAINER)
print(f"  the container global holds {start:#010x} at rest\n")

panel.settle(60_000_000)
print(f"  after warm-up:        {m.long(LIVE_CONTAINER):#010x}, {len(writes)} write(s)")

for _ in range(4):
    panel.tap(MOD)
panel.push_and_turn(DEP_ENCODER, +1, times=4)
print(f"  after the page work:  {m.long(LIVE_CONTAINER):#010x}, {len(writes)} write(s)")

for n in range(CHUNKS):
    before = len(writes)
    panel.settle(IDLE_CHUNK)
    if len(writes) != before:
        print(f"  idle {(n + 1) * IDLE_CHUNK:>11,}:   {m.long(LIVE_CONTAINER):#010x}, "
              f"{len(writes) - before} new write(s)")

print(f"\n  {len(writes)} write(s) to {LIVE_CONTAINER:#010x} in total")
values = sorted({value for _pc, value, _s in writes})
if not writes:
    print("  **it never moves.** The engine and the panel cannot be looking at")
    print("  different containers, so that is not what qualifies a trig.")
else:
    print(f"  distinct values written: {[hex(v) for v in values]}")
    sites = {}
    for pc, value, _s in writes:
        sites.setdefault(pc, set()).add(value)
    for pc, seen in sorted(sites.items()):
        print(f"    from {pc:#010x}: {[hex(v) for v in sorted(seen)]}")
    if len(values) > 1:
        print("  **it alternates.** The panel wrote under one container and the")
        print("  engine reads under another whenever this has moved between them.")

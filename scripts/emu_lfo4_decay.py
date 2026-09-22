"""Does an LFO4 entry survive being left alone, or does something eat it?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        DT2_BUILD=out/lfo4-browser /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_decay.py

From the instrument, 2026-09-22, corrected by the owner:

> "it sometimes trig when I trig, and the faster I press the trigger the more
> frequent I can hear the modulation happening. So at a fast speed of
> triggering the modulation might come every other 4 trigs but at a slower
> triggering it might come every 14 trigs."

**That is a statement about the time between trigs, not about trigs.** A hit
rate that improves when presses are closer together means something periodic is
destroying the working state and a trig re-establishes it: press fast enough
and you outrun it; leave a long gap and it has almost certainly run.

It also rules out the reading this project had a moment earlier -- a phase that
only moves when kicked would be kicked by *every* trig, not one in four.

So this needs no sequencer and no trig. Write a value, then leave the machine
alone and watch. `ext_drop` is hooked with its caller's return address, so if
the entry dies the site that killed it is named rather than guessed.
"""
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-browser"))

LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163
EXT_SLOTS = 256
DEP_ENCODER = 7
IDLE_CHUNK = 20_000_000
CHUNKS = 25                      # half a billion instructions of doing nothing

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

killers = []


def at_drop(uc, address, size, user):
    sp = uc.reg_read(UC_M68K_REG_A7)
    frame = bytes(uc.mem_read(sp, 8))
    killers.append((int.from_bytes(frame[0:4], "big"),      # return address
                    int.from_bytes(frame[4:8], "big")))     # the key dropped


m.uc.hook_add(UC_HOOK_CODE, at_drop, begin=sym["ext_drop"], end=sym["ext_drop"])

panel = Panel(m, png_dir="out/decay")
panel.settle(60_000_000)
for _ in range(4):
    panel.tap(MOD)
panel.push_and_turn(DEP_ENCODER, +1, times=4)
sound = m.long(LIVE_CONTAINER) + SOUND_AT + SOUND_STRIDE * 0


def present():
    keys = m.read(sym["ext_key"], EXT_SLOTS * 4)
    return any(int.from_bytes(keys[i * 4:i * 4 + 4], "big") == sound
               for i in range(EXT_SLOTS))


print(f"\n  track 1's sound is {sound:#010x}; in the table: {present()}")
print(f"  now doing nothing for {CHUNKS * IDLE_CHUNK:,} instruction(s)\n")

gone_at = None
for n in range(CHUNKS):
    before = len(killers)
    panel.settle(IDLE_CHUNK)
    here = present()
    dropped = killers[before:]
    if dropped or not here:
        ours = [k for _ret, k in dropped if k == sound]
        print(f"  after {(n + 1) * IDLE_CHUNK:>12,}: entry {'there' if here else 'GONE'}, "
              f"{len(dropped)} drop(s) this chunk, {len(ours)} of them ours")
    if not here and gone_at is None:
        gone_at = (n + 1) * IDLE_CHUNK

print(f"\n  {len(killers)} drop(s) in total while idle")
if gone_at:
    print(f"  **the entry died after {gone_at:,} instruction(s) of nothing happening.**")
    sites = {}
    for ret, key in killers:
        if key == sound:
            sites[ret] = sites.get(ret, 0) + 1
    for ret, count in sorted(sites.items(), key=lambda kv: -kv[1]):
        print(f"    dropped from {ret:#010x}  x{count}")
else:
    print("  the entry survived being left alone: nothing periodic removes it,")
    print("  and the instrument's rate dependence is not this.")

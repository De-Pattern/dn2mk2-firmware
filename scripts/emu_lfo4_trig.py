"""Does a trig delete the LFO4 values the panel just wrote?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        DT2_BUILD=out/lfo4-ui2 /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_trig.py

From the instrument, 2026-09-22:

> "I get the modulation to work sometimes if I press the track trigger
> repeatedly ... it plays it until I release the track trigger. Then if I play
> the track trigger again it doesn't play the modulation."

`csrc/lfo4/ext.c`, `ext_copy`:

```c
if (!from) {
    ext_drop(dst);      /* the source has no entry: neither has the copy */
    return;
}
```

So **any whole-sound copy into the live sound, from a source with no entry of
its own, deletes the live sound's entry.** The firmware's own parameters are
inside those 1,163 bytes and are carried by the copy itself; ours are in a side
table keyed by address, and a copy from an entry-less source erases them. That
reading predicts exactly the symptom above -- but it is a reading, and this
project has been wrong about the destination browser twice from reading alone.

So: write a value on the fourth MOD page, check the entry is there, press a
trig key (code 25, `(3, 0)`, read out of the firmware's own control table by
`scripts/emu_panel_map.py`), and look again. The table is read from outside
through `ext_key`, so nothing here calls into the guest to ask.
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
                     os.environ.get("DT2_BUILD", "out/lfo4-ui2"))

TRIG_1 = (3, 0)                 # code 25, from the firmware's own control table
DEP_ENCODER = 7
TURNS = 4
EXT_SLOTS = 256

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

written, dropped, copied = [], [], []


def arg1(uc):
    return int.from_bytes(bytes(uc.mem_read(uc.reg_read(UC_M68K_REG_A7) + 4, 4)), "big")


m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: written.append(arg1(uc)),
              begin=sym["ext_set"], end=sym["ext_set"])
m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: dropped.append(arg1(uc)),
              begin=sym["ext_drop"], end=sym["ext_drop"])
m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: copied.append(arg1(uc)),
              begin=sym["ext_copy"], end=sym["ext_copy"])


def keys():
    """Every live key in the table, read from outside."""
    blob = m.read(sym["ext_key"], EXT_SLOTS * 4)
    return {int.from_bytes(blob[i:i + 4], "big") for i in range(0, len(blob), 4)} - {0}


def counters(label):
    print(f"  {label}: ext_live {m.long(sym['ext_live'])}, "
          f"inserts {m.long(sym['ext_inserts'])}, drops {m.long(sym['ext_drops'])}, "
          f"sound copies {m.long(sym['lfo4_sound_copies'])}, "
          f"clears {m.long(sym['lfo4_clears'])}")


panel = Panel(m, png_dir="out/trig")
panel.settle(60_000_000)
for _ in range(4):
    panel.tap(MOD)
print("  on the fourth MOD page")
counters("before the turn")

panel.push_and_turn(DEP_ENCODER, +1, times=TURNS)
ours = set(written)
after_turn = keys()
print(f"\n  the panel wrote {sorted(hex(k) for k in ours)}")
print(f"  in the table: {sorted(hex(k) for k in (ours & after_turn)) or 'NOT PRESENT'}"
      f"   ({len(after_turn)} live key(s))")
counters("after the turn")

mark_d, mark_c = len(dropped), len(copied)
print(f"\n  pressing TRIG 1 {TRIG_1}")
panel.hold(TRIG_1)
held = keys()
panel.let_go(TRIG_1)
after_trig = keys()

print(f"  while held:     ours present = {bool(ours & held)}")
print(f"  after release:  ours present = {bool(ours & after_trig)}")
print(f"  ext_drop called {len(dropped) - mark_d} time(s) during the trig, "
      f"ext_copy {len(copied) - mark_c}")
gone = ours - after_trig
if gone:
    print(f"  **the trig deleted {sorted(hex(k) for k in gone)}** -- "
          f"dropped: {sorted(hex(k) for k in (set(dropped[mark_d:]) & ours))}")
else:
    print("  the entry survived the trig: ext_copy is not the mechanism")
counters("after the trig")
print(f"  screen: {panel.screen('after-trig')}")

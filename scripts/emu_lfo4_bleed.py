"""Does editing LFO4 change LFO3? A data-integrity check, not a feature test.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        DT2_BUILD=out/lfo4-browser /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_bleed.py

From the instrument, 2026-09-22:

> "at opening the LFO3 seem to have adopted that LFO4 config ... but I cannot
> guarantee it was not me saving something in 3. What is sure is that LFO4 was
> not empty when I switched off"

The owner is right to hedge and the question is still worth settling, because
if this build can write LFO4's values where LFO3 reads them, it can modify a
project -- which is a different class of problem from not modulating, and a
stop-ship one.

**Two candidates, and one of them is a deliberate choice of ours.**

The save path looks clean by construction: LFO4 is stored under the p-lock rank
`4 * slot + 0` (stored offsets 36, 44, 52, 60, 68, 76, 84, 92), which DNX found
unused across the corpus, while LFO3's are `4 * slot + 3`. No id is shared.

`csrc/lfo4/widget.c` is the other. It hands LFO4's entries **LFO3's companion
row object itself** rather than a copy -- changed from copying to referencing
after the owner observed that the waveform glyph is reused between the LFOs
rather than owned. If the UI keeps any per-parameter state in that row, an edit
on LFO4's page lands in LFO3's.

So: read LFO3's eight values out of the live sound, edit LFO4, read them again.
The values are read from memory at `sound + 0x14 + 2 * slot`, never by calling
into the guest -- eight identical answers from eight calls is how the
interrupted-call trap looks, and it has caught this project three times.
"""
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-browser"))

LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163
VALUES_AT = 0x14                        # a parameter's value: sound + 0x14 + 2*slot
LFO3_SLOTS = range(17, 25)              # LFO3's eight value slots
LFO4_SLOTS = range(101, 109)
NAMES = ("SPD", "MULT", "FADE", "DEST", "WAVE", "SPH", "MODE", "DEP")

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

panel = Panel(m, png_dir="out/bleed")
panel.settle(60_000_000)
sound = m.long(LIVE_CONTAINER) + SOUND_AT + SOUND_STRIDE * 0


def slots(which):
    """LFO3's or LFO4's eight values, read straight out of the live sound."""
    return [struct.unpack(">H", m.read(sound + VALUES_AT + 2 * s, 2))[0] for s in which]


def show(label, three, four):
    print(f"  {label}")
    print(f"    LFO3 {[hex(v) for v in three]}")
    print(f"    LFO4 {[hex(v) for v in four]}")


for _ in range(3):
    panel.tap(MOD)
before3, before4 = slots(LFO3_SLOTS), slots(LFO4_SLOTS)
show("on LFO3's page, before touching anything:", before3, before4)
print(f"    screen {panel.screen('lfo3-before')}")

panel.tap(MOD)                                   # to LFO4's page
print("\n  on LFO4's page: turning DEP, then MULT, then WAVE")
for encoder in (7, 1, 4):
    panel.push_and_turn(encoder, +1, times=6)
mid3, mid4 = slots(LFO3_SLOTS), slots(LFO4_SLOTS)
show("straight after the edits:", mid3, mid4)
print(f"    screen {panel.screen('lfo4-edited')}")

for _ in range(3):                               # back round to LFO3's page
    panel.tap(MOD)
after3, after4 = slots(LFO3_SLOTS), slots(LFO4_SLOTS)
show("\n  back on LFO3's page:", after3, after4)
print(f"    screen {panel.screen('lfo3-after')}")

print()
moved = [(NAMES[i], hex(a), hex(b)) for i, (a, b) in enumerate(zip(before3, after3)) if a != b]
if moved:
    print(f"  **LFO3's values changed while only LFO4 was edited: {moved}**")
    print("  That is a project being modified by a page the user did not touch,")
    print("  and it is a stop-ship fault rather than a missing feature.")
else:
    print("  LFO3's eight values are untouched by editing LFO4.")
    print("  The bleed is not in the live sound. What the owner saw was either")
    print("  their own edit, or something in the stored copy -- which this does")
    print("  not test, because no save happened here.")
if before4 == after4:
    print(f"  LFO4 kept its own edits: {[hex(v) for v in after4]}")
else:
    print(f"  LFO4's values moved on their own: {[hex(v) for v in before4]} "
          f"-> {[hex(v) for v in after4]}")

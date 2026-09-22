"""Are the values the panel writes the values the engine expects?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        DT2_BUILD=out/lfo4-browser /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_units.py

`scripts/emu_lfo4_sweep.py` shows LFO4 oscillating cleanly when the table holds
`tick7`'s row -- 399 changes over 400 frames, turning round, from a table entry
written by `ext_set`. So the lookup, the bridge and both evaluators are sound.

`tick7`'s row is in **engine units**: `DEP 0x7FFE` against a neutral `0x4000`,
`SPD 0x7000`, `MULT 0x0800`. Those were read out of the firmware's own state,
not chosen. What the *panel* writes is whatever the firmware's parameter setter
hands `lfo4_on_set`, and nothing has ever compared the two.

If they disagree -- if a knob at full travel writes 127 where the engine wants
`0x7FFE` -- then every value LFO4 holds is near the bottom of its range, the
modulation is far too small to hear, and the only thing audible is whatever
transient a trig produces. Which is the instrument's report.

So: turn each dial to one end, read back what landed in the table, and put it
beside the row that is known to sweep.
"""
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-browser"))

LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163
NAMES = ("SPD", "MULT", "FADE", "DEST", "WAVE", "SPH", "MODE", "DEP")
# The row `tick7` proved audible on the instrument, in engine units.
AUDIBLE = (0x7000, 0x0800, 0x4000, 76 << 8, 0x0100, 0, 0, 0x7FFE)
# Far enough to reach an end stop, on the two dials that answer the question.
# Turning all eight thirty steps each is 1.2 billion instructions -- about an
# hour here -- and seven of them cannot show a units mismatch the way `DEP`
# can. `SPD` comes along as the control: if one is scaled and the other is not,
# that is a different fault from both being scaled.
TURNS = 20
DIALS = ((7, "DEP"), (0, "SPD"))

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

panel = Panel(m, png_dir="out/units")
panel.settle(60_000_000)
for _ in range(4):
    panel.tap(MOD)
sound = m.long(LIVE_CONTAINER) + SOUND_AT + SOUND_STRIDE * 0
print(f"  on the fourth MOD page, track 1's sound is {sound:#010x}")
print(f"  turning every dial {TURNS} steps up, then reading the table back\n")

for encoder, name in DIALS:
    print(f"  turning {name} up {TURNS} steps")
    panel.push_and_turn(encoder, +1, times=TURNS)

# **Read the table out of memory, not by calling into it.** The first version
# asked `ext_get` eight times and got `0x7e` eight times -- including for the
# six dials it never touched. Eight identical answers from eight calls is the
# interrupted-call trap this project has been caught by twice: a call into
# firmware code on a booted machine can be diverted, and `emu_start` then stops
# on its instruction count with `d0` holding whatever a handler left. The table
# is plain BSS; walk it.
EXT_SLOTS, EXT_PARAMS = 256, 8
keys = m.read(sym["ext_key"], EXT_SLOTS * 4)
index = next((i for i in range(EXT_SLOTS)
              if int.from_bytes(keys[i * 4:i * 4 + 4], "big") == sound), None)
if index is None:
    live = sorted({int.from_bytes(keys[i * 4:i * 4 + 4], "big") for i in range(EXT_SLOTS)} - {0})
    raise SystemExit(f"no entry for {sound:#010x}; the table holds "
                     f"{[hex(k) for k in live][:8]}")

row = m.read(sym["ext_val"] + index * EXT_PARAMS * 2, EXT_PARAMS * 2)
print(f"  entry {index} of the table is track 1's sound\n")
print(f"  {'':5} {'panel wrote':>12}  {'tick7 (audible)':>16}   ratio")
for slot, name in enumerate(NAMES):
    got = int.from_bytes(row[slot * 2:slot * 2 + 2], "big")
    want = AUDIBLE[slot]
    ratio = f"{want / got:.0f}x" if got else "--"
    print(f"  {name:5} {got:#12x}  {want:#16x}   {ratio}")

print(f"\n  screen: {panel.screen('all-dials-up')}")
print("  A knob at its end stop should land near the engine's own full scale.")
print("  If it lands two orders of magnitude below, the panel and the engine")
print("  are not speaking the same units and nothing LFO4 holds can be heard.")

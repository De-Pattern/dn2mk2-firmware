"""Why does LFO4's `RND` waveform show `SPH` where LFO1-3 show `SLEW`?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_slew.py

`0x4010db00` is the substitution: given the entry a column is about to draw, it
returns either that entry or the `SLEW` that replaces it when the waveform is
`RND`. Its first act is a three-way compare against **81, 91 and 101** -- the
`SPH` entries of LFO1, LFO2 and LFO3, written as literals. Anything else takes
`0x4010dbda`, which returns the entry unchanged.

LFO4's `SPH` is entry 327, so the routine declines before it ever reaches the
page index, the clamp or the three-entry table at `0x40205454`. That is the
reading; this is the measurement. Per MOD page it reports what the gate was
asked, whether it accepted, which clamp ran and what came out of the table --
so the fix can be aimed at the gate rather than at the table it never reaches.
"""
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A2, UC_M68K_REG_D0, UC_M68K_REG_D2

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-value"

GATE = 0x4010DB18          # moveq #81,%d0 -- %d2 holds the entry being drawn
TAKEN = 0x4010DB2E         # the entry was one of the three
DECLINED = 0x4010DBDA      # movel %d2,%d0 -- hand the entry back untouched
CLAMP1 = 0x4010DB78        # the other branch: any index > 0 becomes 1
CLAMP2 = 0x4010DBCC        # moveq #2,%d0 -- the index was 3 or more
PICKED = 0x4010DBD8        # after the table load: %d0 is the SLEW entry
PAGE_INDEX = 144           # the mode object's current MOD page

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

asked, taken, declined, clamped1, clamped2, picked = [], [], [], [], [], []


def at_gate(uc, a, s, u):
    a2 = uc.reg_read(UC_M68K_REG_A2)
    index = int.from_bytes(bytes(uc.mem_read(a2 + PAGE_INDEX, 4)), "big", signed=True)
    asked.append((uc.reg_read(UC_M68K_REG_D2), index))


for site, bucket in ((TAKEN, taken), (DECLINED, declined),
                     (CLAMP1, clamped1), (CLAMP2, clamped2)):
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u, b=bucket: b.append(a),
                  begin=site, end=site)
m.uc.hook_add(UC_HOOK_CODE, at_gate, begin=GATE, end=GATE)
m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: picked.append(uc.reg_read(UC_M68K_REG_D0)),
              begin=PICKED, end=PICKED)

panel = Panel(m, png_dir="out/slew")
panel.settle(60_000_000)

WAVE_ENCODER = 4                # the fifth dial on a MOD page is `WAVE`
TO_RND = 8                      # TRI..RND is six steps; eight is past the end


def report(label):
    """What the gate was asked since the last call, and what came of it."""
    page = asked[report.marks[0]:]
    entries = sorted({e for e, _ in page})
    indices = sorted({i for _, i in page})
    print(f"{label}: page index {indices}, gate asked {len(page)}x "
          f"about entries {entries[:12]}")
    print(f"    accepted {len(taken) - report.marks[1]}, "
          f"declined {len(declined) - report.marks[2]}, "
          f"clamp->1 {len(clamped1) - report.marks[3]}, "
          f"clamp->2 {len(clamped2) - report.marks[4]}, "
          f"table gave {sorted(set(picked[report.marks[5]:]))}")
    report.marks = [len(x) for x in (asked, taken, declined, clamped1, clamped2, picked)]


report.marks = [len(x) for x in (asked, taken, declined, clamped1, clamped2, picked)]

for tap in range(4):
    panel.tap(MOD)
    report(f"[MOD] x{tap + 1}")

# Now the half a plain page walk cannot reach: the substitution only happens
# when the waveform *is* `RND`, so the clamp and the table stay untouched until
# something selects it. Three more taps returns to LFO3's page.
for phase, taps in (("LFO3", 3), ("LFO4", 1)):
    for _ in range(taps):
        panel.tap(MOD)
    report.marks = [len(x) for x in (asked, taken, declined, clamped1, clamped2, picked)]
    panel.push_and_turn(WAVE_ENCODER, +1, times=TO_RND)
    report(f"{phase} WAVE -> RND")
    print(f"    screen: {panel.screen(f'{phase.lower()}-rnd')}")

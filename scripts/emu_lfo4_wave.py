"""Which LFO index does the waveform-preview dispatch see on each MOD page?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx>         /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_wave.py

`0x4010e1f4` onward is the waveform preview: the glyph with the start-phase
braces that LFO1-3 draw across their `WAVE` and `SPH` columns. It is **three
near-identical blocks, one per LFO**, chosen by an index in `%d0`, each calling
`0x4006538e` five times with its own LFO's entry numbers **written as
literals** -- 79/81/82/75/83, then 89/91/92/85/93, then 99/101/102/95/103.

LFO4's page drew a plain dial for `SPH` because there is no fourth block. This
asks the only question that decides how to add one: what index does the
dispatch hand LFO4? If it were something other than 3, or varied, a fourth
block would need a different hook.
"""
import os, sys
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_D0

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-value"
DISPATCH = 0x4010E278          # moveq #2,%d1 ; cmpl %d0,%d1 -- d0 is the index
FALLBACK = 0x4010E2F0          # where an index the code has no block for lands

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

seen, fell = [], []
m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: seen.append(uc.reg_read(UC_M68K_REG_D0)),
              begin=DISPATCH, end=DISPATCH)
m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: fell.append(uc.reg_read(UC_M68K_REG_D0)),
              begin=FALLBACK, end=FALLBACK)
panel = Panel(m, png_dir="out/idx")
panel.settle(60_000_000)
for tap in range(4):
    a, b = len(seen), len(fell)
    panel.tap(MOD)
    print(f"  [MOD] x{tap+1}: the dispatch saw index {sorted(set(seen[a:]))}, "
          f"fell through with {sorted(set(fell[b:]))}")

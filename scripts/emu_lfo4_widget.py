"""Which entries does a MOD page ask the companion table for, and what does it get?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx>         /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_widget.py

LFO4's page drew eight identical empty circles where LFO3's has `512` in a box
for `MULT`, `SYN PD2` for `DEST` and a square glyph for `WAVE`. The labels, the
header and the cycling were all right; everything *inside* the dials was
missing.

This asks the machine why, by hooking the companion-table accessor
(`0x400c2418`, `entry -> 0x4243325c + 68 * entry`, bounded at 321) at its entry
and at its `rts`.

**Read the stack pointer with `UC_M68K_REG_A7`, not register index 15.** The
first version of this did the latter, reported every one of 676 lookups as
entry 0, and would have been believed if 676 identical answers were not
obviously an instrument fault rather than a finding.
"""
import os, sys
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-value"
COMPANION = 0x400C2418          # entry -> &companion[entry], bound 321, clamps to 0
COMPANION_RET = 0x400C243A      # the rts, with the address in d0

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

asked, answered = [], []
def at_in(uc, a, s, u):
    asked.append(int.from_bytes(bytes(uc.mem_read(uc.reg_read(UC_M68K_REG_A7) + 4, 4)), "big"))
def at_out(uc, a, s, u):
    answered.append(uc.reg_read(UC_M68K_REG_D0))
m.uc.hook_add(UC_HOOK_CODE, at_in, begin=COMPANION, end=COMPANION)
m.uc.hook_add(UC_HOOK_CODE, at_out, begin=COMPANION_RET, end=COMPANION_RET)

panel = Panel(m, png_dir="out/widget")
panel.settle(60_000_000)
for tap in range(4):
    a0, b0 = len(asked), len(answered)
    panel.tap(MOD)
    page_asks = asked[a0:]
    page_answers = answered[b0:]
    big = [e for e in page_asks if e > 320]
    print(f"[MOD] x{tap+1}: {len(page_asks)} companion lookup(s); "
          f"entries {sorted(set(page_asks))[:14]}")
    if big:
        print(f"    {len(big)} for entries past 320: {sorted(set(big))}")
        idx = [i for i, e in enumerate(page_asks) if e > 320][:6]
        print(f"    they answered {[hex(page_answers[i]) for i in idx if i < len(page_answers)]}")
        print(f"    the fallback (entry 0) is {0x4243325c:#010x}")

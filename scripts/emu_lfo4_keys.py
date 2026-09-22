"""Does the panel write LFO4's values under the key the engine reads them by?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        DT2_BUILD=out/lfo4-ui /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_keys.py

From the instrument, 2026-09-22:

> "I get the modulation to work sometimes if I press the track trigger
> repeatedly and change the destination ... Happens also changing MULT while
> pressing the track trigger."

That is a signature, not noise. The extension table is keyed by **a live
sound's address**. The panel writes under whatever pointer the firmware's own
setter had in hand; the tick reads under `*(0x800052a0) + 52 + track * 1163`.
If those are different objects the two never meet -- except that trigging a
track makes the firmware `memcpy` a sound, and `carry.c` carries the row with
it. Which is exactly "it works sometimes if I hit the trigger".

So this turns a real knob on the fourth MOD page, records every key `ext_set`
is called with, and compares them against the sixteen addresses the bridge
would derive. No evaluator needed: if the written key is not one of the
sixteen, the mismatch is proved on the spot.
"""
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine
from emulib.panel import MOD, Panel
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-ui"))

LIVE_CONTAINER = 0x800052A0     # the pointer the firmware's own routine reads
SOUND_AT, SOUND_STRIDE = 52, 1163
TRACKS = 16

DEP_ENCODER = 7                 # the eighth dial on a MOD page is `DEP`
TURNS = 4

# Entering the engine the way `emu_lfo4_tick.py` does, because a panel turn
# alone proves nothing about the tick: every `ext_find` during a turn is the
# page reading its own value back.
EVAL_A = 0x40137726
MIRROR_AT, MIRROR_BYTES, TRACKS_MIRROR = 34, 202, 16
STATE = (0x46700000, 0x46701000, 0x46702000)
STATE_LEN = 2560
REST = 0x4000
RATE = 0x402A0DEC
SET_FRAC = bytes.fromhex("a93c000000204e75")      # movel #32,%macsr ; rts
FRAMES = 4

m = Machine(SNAP)
image, sym = load_build(BUILD)
stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
m.apply(differences(stock, image))
for load, _n, bss, init, blob in code_chunks(image):
    m.load_code_chunk((load, len(blob), bss, init, blob))
m.flush()

written, looked_up = [], []


def at_set(uc, address, size, user):
    """`ext_set(key, param, value)` -- the key is the first stacked argument."""
    written.append(int.from_bytes(bytes(uc.mem_read(uc.reg_read(UC_M68K_REG_A7) + 4, 4)), "big"))


def at_find(uc, address, size, user):
    looked_up.append(int.from_bytes(bytes(uc.mem_read(uc.reg_read(UC_M68K_REG_A7) + 4, 4)), "big"))


m.uc.hook_add(UC_HOOK_CODE, at_set, begin=sym["ext_set"], end=sym["ext_set"])
m.uc.hook_add(UC_HOOK_CODE, at_find, begin=sym["ext_find"], end=sym["ext_find"])

panel = Panel(m, png_dir="out/keys")
panel.settle(60_000_000)
for _ in range(4):
    panel.tap(MOD)                                  # to the fourth page
print(f"  on the fourth MOD page; turning DEP {TURNS}x with its push held")
panel.push_and_turn(DEP_ENCODER, +1, times=TURNS)

base = m.long(LIVE_CONTAINER)
sounds = [base + SOUND_AT + SOUND_STRIDE * t for t in range(TRACKS)] if base else []
print(f"\n  the live container at {LIVE_CONTAINER:#010x} holds {base:#010x}")
print(f"  the bridge would key tracks 0..15 at "
      f"{sounds[0]:#010x} .. {sounds[-1]:#010x}" if sounds else "  no container")

print(f"\n  ext_set was called {len(written)} time(s), keys {sorted({hex(k) for k in written})}")
for key in sorted(set(written)):
    if key in sounds:
        print(f"    {key:#010x} IS track {sounds.index(key)}'s sound -- the tick will find it")
    else:
        near = min(sounds, key=lambda s: abs(s - key)) if sounds else 0
        print(f"    {key:#010x} is NOT one of the sixteen; "
              f"nearest is {near:#010x}, {key - near:+d} bytes away")

print(f"\n  ext_find was called {len(looked_up)} time(s) during the turn, "
      f"keys {sorted({hex(k) for k in looked_up})}")
print("  -- but every one of those is the PAGE reading its own value back.")
print(f"  screen: {panel.screen('lfo4-dep')}")

# --- and now the engine, in the same machine, with the turn still in the table
#
# **A panel turn on its own says nothing about the tick.** The first version of
# this probe stopped above and reported that the panel and the table agreed,
# which was never in question: the tick does not run in a snapshot unless it is
# called. This enters evaluator A the way `emu_lfo4_tick.py` does, with the
# table still holding what the knob just wrote, and asks the only question that
# matters -- does the engine look under the key the panel wrote?
mark = len(looked_up)
span = MIRROR_AT + TRACKS_MIRROR * MIRROR_BYTES + 32
buf = m.alloc(span)
m.write(buf, struct.pack(">H", REST) * (span // 2))
for state in STATE:
    m.write(state, bytes(STATE_LEN))
frac = m.alloc(len(SET_FRAC))
m.write(frac, SET_FRAC)
m.call(frac)
rate = m.long(RATE)
out1, out2 = m.alloc(256), m.alloc(256)
print(f"\n  entering evaluator A at {EVAL_A:#010x}, {FRAMES} frame(s)")
for _ in range(FRAMES):
    m.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)

engine = looked_up[mark:]
# **Zero lookups is two different findings and they must not be confused.**
# Either the tick asked under a key nothing matched, or the tick never ran --
# and a call into firmware code on a booted machine can be interrupted and
# return without reaching anything (`docs/lfo4-build-plan.md`, twice). So the
# build's own counters are read: they say which of the two happened.
print(f"  lfo4_refresh entered {m.long(sym['lfo4_refreshes']):,} time(s), "
      f"copied a row in {m.long(sym['lfo4_copies_in']):,} of them")
print(f"  the tick asked ext_find {len(engine)} time(s), "
      f"keys {sorted({hex(k) for k in engine})[:8]}")
panel_keys, engine_keys = set(written), set(engine)
shared = panel_keys & engine_keys
print(f"\n  the panel wrote {sorted(hex(k) for k in panel_keys)}")
print(f"  the tick read   {sorted(hex(k) for k in engine_keys)[:8]}")
print(f"  in common:      {sorted(hex(k) for k in shared) or 'NOTHING -- they never meet'}")

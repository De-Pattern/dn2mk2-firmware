"""Does the UI edit LFO4 under the same key the tick reads it back with?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_BUILD=out/lfo4-meterkeep \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_uikey.py

**Why this and not more disassembly.** On the instrument LFO4 modulates on
roughly one trig in fifteen. A wrong cell would never work; one in fifteen is a
key that usually misses. `lfo4_refresh` does

    values = ext_find(lfo4_sound_of(track));
    row[k] = values ? values[k] : ext_default[k];

so **a miss is not a no-op -- it loads the defaults, whose DEST is None.** A
missing row modulates nothing, which is exactly binary-per-note.

The two sides derive their key differently and that is the whole question:

  * the **UI**, in `hooks.S` and `valuehooks.S`, uses `%a2@(16)` then
    `vtable[40]()` -- the firmware's own virtual call, whatever it returns;
  * the **tick**, in `bridge.c`, computes `*0x800052a0 + 52 + 1163*track`,
    which is the firmware's own arithmetic at `0x40025bda`.

`emu_lfo4_key.py` compared the tick's formula against *the same formula* and
reported 8/8 agreement. **That was not a result and its conclusion is
withdrawn** -- it compared a thing with itself. Only the UI's own virtual call
can answer this, so this probe drives the panel to the LFO4 page and reads the
key the real getter actually used.

**The prediction, before the run.** Reaching the page makes `lfo4_on_get` run,
so `lfo4_get_sound` is filled by the firmware's virtual call for the selected
track. Then:

  * `lfo4_get_sound == lfo4_sound_of(selected)` -- the keys agree, the theory
    dies, and the fault is downstream of the lookup;
  * they **differ** -- the UI writes a row the tick never asks for, the fault is
    found offline, and the fix is a key rather than a cell.

**The control.** `lfo4_gets` must be non-zero. If the getter never ran, the page
was never reached and a zero `lfo4_get_sound` means "no input arrived", not "the
keys differ" -- the distinction `scripts/drive.py` exists to make.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build      # noqa: E402
from emulib.machine import SNAP, Machine                           # noqa: E402
from emulib.panel import DOWN, MOD, Panel                          # noqa: E402

LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163
BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-meterkeep"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--presses", type=int, default=4, help="MOD taps to reach page 4")
    p.add_argument("--track", type=int, default=0)
    args = p.parse_args()

    m = Machine(SNAP)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"],
                              "section_3_MAIN_OS.bin"), "rb").read()
    m.apply(differences(stock, image))
    for load, _n, bss, init, blob in code_chunks(image):
        m.load_code_chunk((load, len(blob), bss, init, blob))
    m.flush()

    panel = Panel(m)
    panel.settle()
    for i in range(args.presses):
        panel.tap(MOD)
    panel.tap(DOWN)
    panel.settle()

    gets = m.long(sym["lfo4_gets"]) if "lfo4_gets" in sym else None
    ui_key = m.long(sym["lfo4_get_sound"])
    called = m.call(sym["lfo4_sound_of"], args.track)
    base = m.long(LIVE_CONTAINER)
    derived = base + SOUND_AT + SOUND_STRIDE * args.track if base else 0

    print(f"  MOD tapped {args.presses}x, then DOWN")
    print(f"  lfo4_gets      {gets}")
    print(f"  lfo4_get_sound {ui_key:#010x}   <- the UI's own virtual call")
    print(f"  lfo4_sound_of  {called:#010x}   <- the tick key, by calling it")
    print(f"  base+52+1163t  {derived:#010x}   <- the same, by reading memory")

    if called != derived:
        print()
        print("  **The two derivations of the tick key disagree, so the call is")
        print("  unreliable here and nothing below it is a valid comparison.**")
        print("  This is the control that was missing when this probe first")
        print("  reported a difference: 8 is not a value lfo4_sound_of can return.")
        return 2
    tick_key = called

    if not gets:
        print("  **The getter never ran, so the page was never reached.**")
        print("  lfo4_get_sound is untouched and says nothing. This is a null")
        print("  about navigation, not about the keys -- fix the driving first.")
        return 2
    if ui_key == tick_key:
        print("  **The keys agree.** The UI writes the row the tick asks for, so")
        print("  the fault is downstream of the lookup and this probe says so.")
        return 0
    print("  **They differ.** The UI stores LFO4's row under a key the tick never")
    print("  asks for, so the tick misses, ext_default loads, and DEST is None.")
    print(f"  delta {ui_key - tick_key:+d} bytes.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

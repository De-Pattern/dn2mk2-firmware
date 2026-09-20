"""Do our panel bytes reach the firmware, and does it act on each one?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_panel_delivery.py

`emu_mod_pages.py` showed a key that works **once**: three taps of DOWN moved
the page once, two taps of UP moved it once, and a different key always moved
it. Nothing about that is the instrument -- it is this project's control of the
emulator, and there are only two places it can go wrong.

1. **The bytes never arrive.** `panelin.state` reports the receive ring's
   `produced` against the firmware's own `consumed` index, so a byte that was
   written and not drained is visible rather than inferred.
2. **They arrive and the firmware does nothing with them.** The wire carries a
   whole-channel *state mask* and the firmware XORs it against what it last saw
   for that channel, so a press whose release never registered leaves the bit
   set -- and the next identical press byte is, correctly, no edge at all. That
   is exactly the shape of "a key that works once".

So this prints the ring either side of every single press and release, with the
screen's digest beside it. A tap whose two bytes are both consumed and whose
page did not move separates 2 from 1 on the spot.
"""

from __future__ import annotations

import argparse
import hashlib
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib import panel as panelmod                           # noqa: E402
from emulib.panel import DOWN, MOD, UP, Panel                  # noqa: E402

KEYS = {"down": DOWN, "up": UP, "mod": MOD}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--keys", default="mod,down,down,down")
    p.add_argument("--dwell", type=int, default=0, help="0 uses emulib.panel's TAP")
    p.add_argument("--after", type=int, default=10_000_000)
    args = p.parse_args()

    machine = Machine(args.snapshot)
    panel = Panel(machine, png_dir="out/panel-delivery")
    from emu import panelin

    def ring():
        s = panelin.state(machine.m, panel.profile)
        return s["produced"], s["consumed"]

    def digest():
        if not panel.capture or not panel.capture.frames:
            return "--------"
        return hashlib.sha256(bytes(panel.capture.frames[-1])).hexdigest()[:8]

    panel.settle(args.warmup)
    print(f"  warmed up, {panel.frames()} frame(s); ring produced/consumed {ring()}\n")
    print("  step            produced  consumed  behind  screen")

    def show(label):
        produced, consumed = ring()
        print(f"  {label:<14} {produced:>9} {consumed:>9} {produced - consumed:>7}  {digest()}")

    dwell = args.dwell or panelmod.TAP
    for name in args.keys.split(","):
        if not name:
            continue
        channel, bit = KEYS[name]
        machine.pc = panelin.press(machine.m, panel.profile, channel, bit)
        show(f"{name} press")
        panel.settle(dwell)
        show(f"{name} held")
        machine.pc = panelin.release(machine.m, panel.profile, channel, bit)
        show(f"{name} release")
        panel.settle(args.after)
        show(f"{name} settled")

    print("\n  `behind` is bytes written into the ring the firmware has not drained.\n"
          "  It should return to the same number after every settle; a number that\n"
          "  grows is delivery, and a number that does not is the firmware's own\n"
          "  edge handling -- and then the pacing, not the mapping, is what to fix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

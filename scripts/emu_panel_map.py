"""What the firmware calls each button and encoder, read out of the image.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \\
        /root/dn2-emu-venv/bin/python -u scripts/emu_panel_map.py

Every key code this project uses came from a note written during another
session. That is exactly the kind of thing to check rather than carry, and
digikit resolves the firmware's **own** name tables, so the machine can say
which code is `[MOD]` and which is `UP` instead of us asserting it.

It also prints the `(channel, bit)` each code corresponds to under
`code_for(channel, bit) = channel * 8 + bit + 1`, since that is what
`panelin.press` actually takes -- a mapping error there sends a real press to
the wrong key and looks like a firmware that ignores input.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine        # noqa: E402

WANTED = ("MOD", "UP", "DOWN", "LEFT", "RIGHT", "FUNC", "PAGE", "TRK",
          "PLAY", "STOP", "REC", "YES", "NO", "PTN")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--all", action="store_true", help="print every code, not just the ones we use")
    args = p.parse_args()

    machine = Machine(args.snapshot)
    from emu import config, panelin, symbols

    profile = symbols.resolve(open(config.main_image(), "rb").read())
    buttons = panelin.control_names(machine.m, profile, "button")
    encoders = panelin.control_names(machine.m, profile, "encoder")

    def where(code):
        """-> the (channel, bit) that produces this code, or None."""
        for channel in range(6):
            for bit in range(8):
                if panelin.code_for(channel, bit) == code:
                    return channel, bit
        return None

    print(f"{len(buttons)} button(s), {len(encoders)} encoder(s)\n")
    rows = buttons.items() if args.all else [
        (c, n) for c, n in buttons.items()
        if any(w == n.strip().upper() or n.strip().upper().startswith(w) for w in WANTED)]
    print("  code  channel,bit  name")
    for code, name in sorted(rows):
        spot = where(code)
        print(f"  {code:>4}  {str(spot) if spot else '     --    ':>11}  {name}")

    print("\n  encoders:")
    for code, name in sorted(encoders.items()):
        print(f"  {code:>4}               {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

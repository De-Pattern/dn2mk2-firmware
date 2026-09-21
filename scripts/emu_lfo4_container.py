"""Does the bridge follow the live container, or assume where it is?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_container.py

The extension table is keyed by the live sound's address. The **setter** learns
that address from the firmware's own virtual call; the **bridge** has to work
it out for a track number it is handed by the tick.

It used to work it out from `LFO4_KIT`, a constant measured once out of
`ui1200M` -- and every check agreed with it, because the check and the constant
came from the same snapshot. On the instrument the container moves when a
project loads, and then the setter writes under one key while the tick reads
another: the page works, sounds save and reload, and **nothing modulates**.

The firmware's own routine is `0x40025bda`:

    movel %sp@(4),%d0 ; movel #1163,%d1 ; mulsl %d1,%d0
    addil #52,%d0
    addl 0x800052a0,%d0          <- the base, read from a global

So this moves the global and asks whether `lfo4_sound_of` moves with it. A
build that assumes the base answers the same address twice, which is the whole
failure in one line.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import code_chunks, differences, load_build     # noqa: E402
from emulib.machine import SNAP, Machine                          # noqa: E402
from emulib.report import check, report                           # noqa: E402

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-value"
CONTAINER = 0x800052A0
SOUND_AT, STRIDE, TRACKS = 52, 1163, 16
MOVED = 0x42200000                # somewhere else entirely, as a new project would be


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    args = p.parse_args()

    machine = Machine(args.snapshot)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    machine.apply(differences(stock, image))
    for load, _n, bss, init, blob in code_chunks(image):
        machine.load_code_chunk((load, len(blob), bss, init, blob))
    machine.flush()

    # No `Panel` here, so the timers stay deferred and a call is reliable --
    # the scope the project recorded when `call(ext_get, ...)` once lied.
    was = machine.long(CONTAINER)
    print(f"  the firmware's container pointer: {was:#010x}")
    before = [machine.call(sym["lfo4_sound_of"], t) & 0xFFFFFFFF for t in range(TRACKS)]
    print(f"  lfo4_sound_of(0..2): " + " ".join(f"{a:#010x}" for a in before[:3]))

    machine.write(CONTAINER, MOVED.to_bytes(4, "big"))
    machine.flush()
    after = [machine.call(sym["lfo4_sound_of"], t) & 0xFFFFFFFF for t in range(TRACKS)]
    print(f"  moved the pointer to {MOVED:#010x}")
    print(f"  lfo4_sound_of(0..2): " + " ".join(f"{a:#010x}" for a in after[:3]))

    machine.write(CONTAINER, (0).to_bytes(4, "big"))
    machine.flush()
    empty = machine.call(sym["lfo4_sound_of"], 0) & 0xFFFFFFFF

    check("it agrees with the firmware's arithmetic before the move",
          before == [was + SOUND_AT + t * STRIDE for t in range(TRACKS)],
          f"{before[0]:#010x} against {was + SOUND_AT:#010x}")
    check("it follows the container when it moves",
          after == [MOVED + SOUND_AT + t * STRIDE for t in range(TRACKS)],
          f"{after[0]:#010x} against {MOVED + SOUND_AT:#010x}")
    # `check` prints its detail on a pass too, so the detail is the
    # measurement rather than an account of what failure would mean.
    check("and the answers actually changed", before != after,
          f"{before[0]:#010x} -> {after[0]:#010x}; the same twice would mean the "
          "base is still assumed")
    check("no container yet answers 0, not an address", empty == 0, f"{empty:#010x}")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

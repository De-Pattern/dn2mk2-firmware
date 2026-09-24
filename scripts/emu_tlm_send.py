"""Does calling the MIDI sink actually work, or does it fault?

    DT2_SECTIONS=/root/dn2-sections-111 DT2_BUILD=out/lfo4-tlm \
        /root/dn2-emu-venv/bin/python -u scripts/emu_tlm_send.py

**Why this and not the engine gate.** The telemetry burst is rate-limited to one
in 2048 calls of `lfo4_row_for_block`, and `emu_boot_engine.py` produces 128 --
so the gate boots the build, runs the engine, and **never executes the new call
once**. A clean gate would mean nothing about the thing this build adds. That is
the same trap as `lfo4-bridge`, which booted for 400 M instructions without ever
reaching `lfo4_refresh` and then faulted on the instrument.

So call the sink directly: `0x401233f2(buffer, 3, 0, 2)`, the shape all four
stock callers use.

**What it can and cannot say.** It can say the call returns rather than faulting,
which is the risk worth retiring before a flash -- a bad argument order here
would be a crash in the audio engine. It **cannot** say a byte reached the DIN
socket: the emulator models no MIDI hardware. Only the instrument can answer
that, and `scripts/midi_live.py` is calibrated to catch it.

**The control.** A boot-only run is compared against the same call: if the
machine faults before the call is ever made, the result says nothing about the
call and the script says so rather than reporting a fault as a finding.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build   # noqa: E402
from emulib.machine import SNAP, Machine                        # noqa: E402

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-tlm"))
MIDI_TX = 0x401233F2
PORT, FLAGS = 0, 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cc", type=int, default=30)
    p.add_argument("--value", type=int, default=99)
    args = p.parse_args()

    m = Machine(SNAP)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"],
                              "section_3_MAIN_OS.bin"), "rb").read()
    m.apply(differences(stock, image))
    for load, _n, bss, init, blob in code_chunks(image):
        m.load_code_chunk((load, len(blob), bss, init, blob))
    m.flush()

    # A control first: a call we know is harmless, through the same mechanism.
    probe = m.alloc(8)
    m.write(probe, bytes.fromhex("702a4e75"))          # moveq #42,%d0 ; rts
    m.flush()
    if m.call(probe) != 42:
        print("  the control call did not return 42 -- the harness is not sound")
        print("  here, so nothing below it means anything.")
        return 2
    print("  control: a local stub returns 42, so direct calls work in this machine")

    buf = m.alloc(8)
    msg = bytes([0xB0 | 15, args.cc & 0x7F, args.value & 0x7F])   # channel 16
    m.write(buf, msg)
    m.flush()
    print(f"  sending {msg.hex(' ')} via 0x{MIDI_TX:08x}(buf, 3, {PORT}, {FLAGS})")
    try:
        rc = m.call(MIDI_TX, buf, 3, PORT, FLAGS)
    except Exception as exc:                                  # noqa: BLE001
        print(f"\n  **It faulted: {type(exc).__name__}: {exc}**")
        print("  Do not flash this. The argument order or the routine is wrong.")
        return 1

    print(f"  returned {rc} (0x{rc & 0xFFFFFFFF:08x}) without faulting")
    print()
    print("  That retires the crash risk and nothing more. Whether a byte leaves")
    print("  the socket is a question only the instrument answers -- the emulator")
    print("  models no MIDI hardware, so a silent run here is expected, not a null.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

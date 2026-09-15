"""Capture SysEx the instrument sends, without sending it anything. Ever.

## Why this exists rather than a dump request

Asking the device for a dump means sending it SysEx. That is allowed, but on
2026-09-15 a **Digitone 1 and a Digitone II were connected at the same time**,
and the Windows port indices do not line up between input and output:

    MIDI IN   [0] Elektron Digitone      [1] Elektron Digitone II
    MIDI OUT  [1] Elektron Digitone      [2] Elektron Digitone II

So "port 1" means the DN2 for input and the **DN1** for output. `midi_probe.py`
records that one malformed command froze a Digitone 1 three times, recoverable
only by a power cycle that takes the unsaved active project with it.

This file removes that whole class of mistake: **it has no output path.** It
imports `InPort` and `list_ports` and nothing else, never calls `midiOutOpen`,
and cannot be made to send by any argument. The instrument is driven by hand --
`SETTINGS -> SYSEX DUMP -> SEND ...` on the device -- and this only listens.

## What it is for

Reading back what the instrument actually stored, so a claim about the firmware
can be checked against the device's own data rather than against a disassembly.
The immediate use is the page-renumber probe: a p-lock placed on `PROB` behaves
like a change to LFO2's `DEST` (`docs/lfo4-feasibility.md`), and the question
that decides whether the **stored** format is affected is which parameter id the
lock is saved under. `DNX` decodes the pattern; this gets the bytes to it.

    python scripts/sysex_capture.py --list
    python scripts/sysex_capture.py --in 1 --out-dir out/dumps --seconds 60

Each complete `F0 ... F7` message is written as its own `.syx`, numbered in
arrival order, and a one-line summary is printed as it arrives.

**A hard limit worth knowing.** `InPort` pre-posts eight SysEx buffers and
deliberately does not recycle them -- re-adding a buffer from inside the
callback deadlocks Windows, which `midi_probe.py` records learning the hard way.
So **at most eight messages arrive per run** and the ninth onwards are lost. One
pattern is one message, so that is ample here; a whole-project dump is not.
"""

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# Only the receive half. `send_sysex` is deliberately NOT imported -- see above.
from midi_probe import InPort, list_ports

ELEKTRON = 0x00, 0x20, 0x3C


def describe(msg: bytes) -> str:
    """One line about a captured message, without pretending to decode it."""
    if len(msg) >= 4 and tuple(msg[1:4]) == ELEKTRON:
        who = f"Elektron, device 0x{msg[4]:02x}" if len(msg) > 4 else "Elektron"
        return f"{who}, {len(msg):,} bytes"
    if len(msg) >= 2 and msg[1] == 0x7E:
        return f"Universal non-realtime, {len(msg):,} bytes"
    return f"unrecognised manufacturer, {len(msg):,} bytes"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="list ports and exit")
    ap.add_argument("--in", dest="in_idx", type=int,
                    help="MIDI IN index to listen on")
    ap.add_argument("--out-dir", default="out/dumps",
                    help="directory for captured .syx files")
    ap.add_argument("--seconds", type=float, default=60.0,
                    help="how long to listen (default 60)")
    args = ap.parse_args()

    if args.list or args.in_idx is None:
        list_ports()
        print("\nNothing sent, and this tool cannot send. "
              "Pass --in <index> to listen.")
        return 0

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    port = InPort(args.in_idx)
    print(f"listening on MIDI IN [{args.in_idx}] for {args.seconds:g}s -- "
          f"nothing will be sent")
    print("on the instrument: SETTINGS -> SYSEX DUMP -> SEND, then wait\n")

    seen = 0
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(0.05)
            while len(port.msgs) > seen:
                msg = port.msgs[seen]
                seen += 1
                if not (msg and msg[0] == 0xF0):
                    continue
                path = out_dir / f"capture_{seen:03d}.syx"
                path.write_bytes(bytes(msg))
                print(f"  [{seen:3d}] {describe(bytes(msg)):<44s} -> {path}")
                deadline = max(deadline, time.time() + 5.0)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        port.close()

    if seen >= 8:
        print("  !! eight messages received -- that is InPort's buffer "
              "ceiling, so anything beyond that was lost")
    print(f"\n{seen} SysEx message(s) captured into {out_dir}/")
    if not seen:
        print("nothing arrived -- check the instrument is set to send on this "
              "port, and that --in names the right instrument")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

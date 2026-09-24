"""Watch what the instrument sends, and decode LFO4's diagnostics out of it.

    python scripts/midi_watch.py --list
    python scripts/midi_watch.py --in 0            # everything, as it arrives
    python scripts/midi_watch.py --in 0 --cc-only --seconds 60

**Why this exists.** On 2026-09-23 six firmware builds were flashed to read
single numbers off the LFO4 page, one per flash, and the page turned out to
render only the **high byte** of what a column returns -- so every diagnostic
value, all of them 0..15, displayed identically no matter what it held. A day of
readings was void, and the failure was that the readout was never calibrated.

The owner's proposal, which is better than the page: have the firmware transmit
its internal state as MIDI, and read it here. Exact values, many at once, per
note, with no display mapping in the way and no transcription step where a
number can be misread.

**This is the host half and it works today**, against MIDI the instrument
already sends -- which is also how it gets tested before any firmware depends on
it. The firmware half needs the MIDI transmit routine located first and is not
built yet.

**No dependency**: `winmm` through `ctypes`, exactly as `scripts/midi_probe.py`
does it, because `python-rtmidi` and `pygame` have no wheels for the Python
here. The input class is imported from that file rather than copied, so the
callback rule it documents -- never call a multimedia function from inside the
callback, it deadlocks -- holds in one place.

**Read-only.** This never opens an output port and never sends a byte. The
safety argument in `midi_probe.py` is about what may be *sent*; nothing here can
send anything at all.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from midi_probe import InPort, list_ports  # noqa: E402

STATUS = {0x80: "note-off", 0x90: "note-on", 0xA0: "aftertouch",
          0xB0: "cc", 0xC0: "program", 0xD0: "pressure", 0xE0: "bend"}

# The CC map, loaded from the SAME file the firmware header is generated from
# (`src/dnfw/telemetry/channels.json`). Written twice, a decoder and an emitter
# drift and nothing says so -- which is the shape of the bug that made a day of
# page readings meaningless on 2026-09-23.
def _load_map():
    here = pathlib.Path(__file__).resolve().parent
    spec = json.loads((here.parent / "src" / "dnfw" / "telemetry"
                       / "channels.json").read_text(encoding="utf-8"))
    return spec["channel"], {s["cc"]: s["name"] for s in spec["signals"]}


TLM_CHANNEL, TLM_CC = _load_map()


def decode(raw: str) -> str:
    """-> a readable line for one short message, or '' to drop it."""
    parts = [int(b, 16) for b in raw.split()]
    if not parts:
        return ""
    status, chan = parts[0] & 0xF0, (parts[0] & 0x0F) + 1
    kind = STATUS.get(status, f"status {parts[0]:#04x}")
    d1 = parts[1] if len(parts) > 1 else 0
    d2 = parts[2] if len(parts) > 2 else 0
    if status == 0xB0:
        name = TLM_CC.get(d1) if chan == TLM_CHANNEL else None
        label = f"CC{d1:<3d}" + (f" ({name})" if name else "")
        return f"ch{chan:<3d} {label:<26s} = {d2}"
    return f"ch{chan:<3d} {kind:<12s} {d1:>3d} {d2:>3d}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--list", action="store_true", help="show ports and stop")
    p.add_argument("--in", dest="in_idx", type=int, default=0)
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--cc-only", action="store_true",
                   help="drop notes and clock; keep control changes")
    args = p.parse_args()

    if args.list:
        ins, outs = list_ports()          # returns lists; it does not print
        for label, names in (("MIDI IN", ins), ("MIDI OUT", outs)):
            print(f"{label}:")
            for i, n in enumerate(names):
                print(f"  [{i}] {n}")
        return 0

    port = InPort(args.in_idx)
    print(f"  listening on input {args.in_idx} for {args.seconds:g}s -- "
          f"play the instrument\n")
    seen = 0
    start = time.time()
    try:
        while time.time() - start < args.seconds:
            time.sleep(0.05)
            while port.shorts:
                raw = port.shorts.pop(0)
                first = int(raw.split()[0], 16)
                if args.cc_only and (first & 0xF0) != 0xB0:
                    continue
                line = decode(raw)
                if line:
                    seen += 1
                    print(f"  {time.time() - start:7.3f}  {line}")
    finally:
        port.close()

    print()
    if not seen:
        print("  **Nothing arrived.** That is a null about the cable, the port or")
        print("  the instrument's MIDI settings -- not about the firmware. Check it")
        print("  against a known-good source before reading anything into it:")
        print("      python scripts/midi_watch.py --in 0        (then play a note)")
        return 1
    print(f"  {seen} message(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

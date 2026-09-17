"""Offer the ARPEGGIATOR menu on MIDI tracks, second attempt: remove the real gate.

`arp-on-midi` (v1) failed on hardware on 2026-09-17 -- *"arpegiator menu doesn't
open on the midi track with the firmware"* -- and reading the handler again says
why. v1 edited the wrong branch, and on the wrong theory.

## What v1 got wrong

The ARP key's case in the 6,516-byte menu dispatcher `0x4005ed12` runs three
tests, in this order:

```
0x4005f996  jsr  0x401160bc        | key event: pressed, and not bit 3
0x4005f9a0  beq.w 0x4005ef52       | no -> leave
0x4005f9b6  jsr  0x40031274        | (kit->midiMask@+0x5cda >> track) & 1
0x4005f9c2  bne.w 0x4005ef52       | MIDI track -> leave          <-- the gate
0x4005f9c8  jsr  0x401160ac        | key event bit 1: [FUNC] held
0x4005f9da  beq.s 0x4005fa3c       | no FUNC -> build ArpSetupMenuView
            ...                    | FUNC -> toggle, "Arpeggiator ON/OFF" popup
```

- `%d2`, the argument to `0x401160ac`, is the dispatcher's second argument: the
  **key event**, not a track. `0x40116018` on the same object returns the key
  code the switch at `0x4005ed3a` dispatches on. v1's docs called bit 1
  "track type"; it is the **FUNC modifier**. The manual, p. 86: *"[FUNC] +
  [ARP] to toggle the current track's arpeggiator on/off."* That is the arm
  that shows the ON/OFF popup.
- `0x40031274(obj, track)` returns bit `track` of a u16 at runtime `+0x5cda`.
  The kit loader at `0x400dddac` copies it from **kit offset 10,260**, which DNX
  independently verified as the per-track **synth/MIDI mask**
  (`DNX/docs/dn2-format.md`). So the MIDI test sits *before* the branch v1 edited,
  and a MIDI track never reached it.
- **So v1 changed audio tracks, not MIDI tracks:** on an audio track, [FUNC] +
  [ARP] opens the setup menu instead of toggling. The control in v1's table
  ("audio tracks unchanged") was not met, and nobody would notice without
  pressing FUNC.

## What this build does

The FUNC branch is left stock. The MIDI test's `bne.w` (`6600 f58e`) becomes two
NOPs, so a MIDI track falls through to the same FUNC split as an audio track:
[ARP] opens the setup view, [FUNC] + [ARP] toggles.

| on a MIDI track | means |
|---|---|
| menu opens, settings stick, notes arpeggiate | a UI gate only; done |
| menu opens, settings stick, no arpeggiation | the sequencer has its own mask test. Candidates already seen reading `+0x5cda` bit-wise: `0x400d9ee0`, `0x400d9062`, `0x400f7f14`, `0x40121f82` |
| menu opens with wrong or dead values | the view is bound to storage a MIDI preset uses differently |
| audio tracks change at all, including [FUNC] + [ARP] | this build is wrong. Revert |

**Storage risk, stated:** the setup view writes arp fields of the track's preset
(sound object bytes 324..353). A MIDI track's preset is not known to use those
bytes for anything else, but that is not proven. Test on a scratch project.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load

MAIN_OS = 3
BASE = 0x40000400

GATE_VA = 0x4005F9C2
GATE_STOCK = b"\x66\x00\xf5\x8e"    # bne.w 0x4005ef52: MIDI track -> leave
GATE_NEW = b"\x4e\x71\x4e\x71"      # nop; nop

CONTEXT = (
    (0x4005F9B6, b"\x4e\xb9\x40\x03\x12\x74", "jsr the per-track MIDI-mask test"),
    (0x4005F9C0, b"\x4a\x00", "tst.b %d0"),
    (0x4003129C, b"\x71\x68\x5c\xda", "the test reads the mask at +0x5cda"),
    (0x400DDDAC, b"\x37\x6a\x28\x14\x5c\xda", "kit loader: kit+10260 -> +0x5cda"),
    (0x4005F9C8, b"\x4e\xb9\x40\x11\x60\xac", "jsr the FUNC-held accessor"),
    (0x4005F9DA, b"\x67\x60", "beq.s: the FUNC split, left stock"),
    (0x4005FA52, b"\x4e\xb9\x40\x19\xf6\x00", "jsr the ArpSetupMenuView factory"),
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/arp-on-midi2_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    print("part 1 -- the chain, asserted and left alone")
    for va, want, why in CONTEXT:
        have = bytes(content[va - BASE:va - BASE + len(want)])
        if have != want:
            raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} "
                             f"-- not the image this patch was written against ({why})")
        print(f"  {va:#010x}  {have.hex():<14}  {why}")

    print("part 2 -- the gate")
    off = GATE_VA - BASE
    have = bytes(content[off:off + 4])
    if have != GATE_STOCK:
        raise SystemExit(f"{GATE_VA:#010x}: expected {GATE_STOCK.hex()}, found {have.hex()}")
    content[off:off + 4] = GATE_NEW
    print(f"  {GATE_VA:#010x}  {GATE_STOCK.hex()} -> {GATE_NEW.hex()}"
          "   bne.w -> nop nop: MIDI tracks reach the FUNC split")

    print("part 3 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

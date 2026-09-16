"""Offer the ARPEGGIATOR menu on MIDI tracks: one byte.

`docs/ideas-backlog.md` section 10 asks the only question that decides how big
this feature is:

    Is the restriction a UI gate or an engine gate?

This build answers it. It does not try to make the arpeggiator *work* on a MIDI
track -- it removes the one branch that stops the menu being offered, and then
the instrument says which kind of gate it was.

| what happens on a MIDI track | what it means |
|---|---|
| the menu opens, settings stick, **and notes arpeggiate** | a pure UI gate. The feature is done, in one byte |
| the menu opens, settings stick, no arpeggiation | a UI gate **and** an engine gate. The note generator has its own check, and that is the next thing to find |
| the menu opens and its values are wrong or dead | the view is bound to per-preset storage a MIDI track does not have. Larger, and the storage is the question |
| audio tracks change at all | the branch was not what this build claims. Revert |

The last row is the control, and it matters: audio tracks already took the
branch this build forces, so they must be **bit-for-bit unaffected**.

## What was read

The manual, section 9.7: *"The arpeggiator is not available for the MIDI
tracks."* and section 8.1: *"A track that contains any other SYN machine than the
MIDI machine is considered an audio track."* So the restriction is real,
documented, and keyed on the machine.

In the image, `ArpSetupMenuView` is reached through exactly one chain, each link
with a single caller:

```
0x401d4c70   vtable                  (typeinfo 0x401d4c08 -> "ArpSetupMenuView")
0x400191a6   constructor             installs it
0x4019f600   make_shared factory     allocates 0x24c bytes
0x4005fa3c   the only call site      inside the 6,516-byte menu dispatcher
```

and the branch that decides:

```
0x4005f9c6  move.l %d2,%sp@-
0x4005f9c8  jsr    0x401160ac       | (track->flags@0x10 >> 1) & 1
0x4005f9d8  tst.b  %d0
0x4005f9da  beq.s  0x4005fa3c       | 0 -> build the setup view
0x4005f9dc  ...                     | non-0 -> an "Arpeggiator ON/OFF" item instead
```

`0x401160ac` is a one-line accessor -- `return (obj->[0x10] >> 1) & 1` -- with
**132 callers**, so it is a fundamental track property and must not be changed
itself. The two strings the other arm chooses between are `"Arpeggiator ON"` and
`"Arpeggiator OFF"` at `0x40215d3f`, which is how we know that arm is the plain
toggle and not a second setup view.

**So the edit is the branch, not the predicate:** `beq.s` becomes `bra.s`, the
setup view is built for every track, and nothing else in the image moves.

## What Ghidra could not settle, recorded so it is not retried blind

The enclosing function `FUN_4005ed12` is 6,516 bytes of switch, and Ghidra's
decompiler reports *"Type propagation algorithm not settling"* on it: arguments
are dropped from every call, and `pea` sequences come back as writes to
imaginary stack slots (`uStack_75._1_3_ = 0x4005f5`). The raw disassembly above
is the trustworthy reading of this function; the decompiled C is not. Ghidra is
right about structure here and wrong about detail, which is the opposite of how
it behaved on the smaller routines.
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

# The branch, and the two instructions around it that prove it is the right one.
GATE_VA = 0x4005F9DA
GATE_STOCK = b"\x67\x60"            # beq.s  0x4005fa3c
GATE_NEW = b"\x60\x60"              # bra.s  0x4005fa3c

# Context asserted but not modified, so a shifted image fails loudly.
CONTEXT = (
    (0x4005F9C8, b"\x4e\xb9\x40\x11\x60\xac", "jsr the track-type accessor"),
    (0x4005F9D8, b"\x4a\x00", "tst.b %d0"),
    (0x4005FA52, b"\x4e\xb9\x40\x19\xf6\x00", "jsr the ArpSetupMenuView factory"),
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/arp-on-midi_DN2_1.11.syx")


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

    print("part 2 -- the one byte")
    off = GATE_VA - BASE
    have = bytes(content[off:off + 2])
    if have != GATE_STOCK:
        raise SystemExit(f"{GATE_VA:#010x}: expected {GATE_STOCK.hex()}, found {have.hex()}")
    content[off:off + 2] = GATE_NEW
    print(f"  {GATE_VA:#010x}  {GATE_STOCK.hex()} -> {GATE_NEW.hex()}"
          "   beq.s -> bra.s: the ARP setup view is built for every track")

    print("part 3 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

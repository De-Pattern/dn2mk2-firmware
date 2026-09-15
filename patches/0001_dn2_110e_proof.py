"""Gate E: the first patch that changes something a person can see.

This exists to prove the loop -- unpack, modify, repack, re-sign, flash,
observe -- and for no other reason. It changes one menu label and nothing else.

Why this string. `PERSONALIZE` is a top-level entry in SETTINGS, so it takes
two button presses to check on the instrument. It occurs exactly once in the
MAIN OS section, sits NUL-terminated in the settings menu string block beside
`MIDI CONFIG`, `SYSEX DUMP` and `AUDIO ROUTING` (and the
`DigisharcSettingsMenu` class name), and is eleven bytes -- long enough for a
replacement nobody could mistake for a stock label. Nothing reads it except the
menu that draws it.

Located by `find` rather than by address on purpose. The address in a stock
1.10E image is 0x40200b2e, recorded here for the disassembler's benefit, but an
offset stops being true the moment anything earlier in the section changes
size, whereas the string does not.

**Do not pick a target inside the key material.** The Digitone II derives its
HMAC key from the string "Multiplier" in the DSP section; editing that would
change the key as well as the digest, and whether the device recomputes the key
from the image it is being sent or holds its own copy is not yet known. Until
that is settled, leave it alone.
"""

from dnfw.patch.spec import Patch

PATCHES = [
    Patch(
        id="dn2-110e-proof-personalize",
        group="proof",
        description="Rename the SETTINGS > PERSONALIZE menu entry, to prove a build reached the device",
        device=0x15,  # Digitone II
        build="0050",
        version="1.10E",
        section=3,  # MAIN OS
        find=b"PERSONALIZE",
        expect=b"PERSONALIZE",
        replace=b"DNFW ALIVE!",
        notes="Stock address 0x40200b2e. Cosmetic only; revert by reflashing stock 1.10E.",
    ),
]

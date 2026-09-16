"""v4: give the [MOD] key a fourth page, and nothing else.

**The one question.** Can `LfoPageView` be made to serve a fourth page, reachable
by pressing `[MOD]` a fourth time? Everything else about LFO4 -- records, slot
space, the tick, serialization -- is deliberately absent, so a pass or a fail
means exactly one thing.

## Why the fourth page shows LFO3's parameters

The view resolves a column like this (`docs/lfo4-build-plan.md` §5f):

```
desc = descriptor_table[ id_vector[ lfo_index ] ];
parameter_id = desc[8 + column*4];
```

`id_vector` is a `std::vector<int>` handed to the view at construction -- `{4, 5,
6}` for the sound-track group -- and each id indexes a 37-entry table of page
descriptors at `0x42432C00`, stride 44.

**All 37 descriptors are live.** The initialiser around `0x400c9640` writes every
one of them, so there is no spare id to claim, and a real LFO4 page needs a
**38th** descriptor -- which means relocating the 1,672-byte table (the table
that follows it starts at `0x4243325C`, immediately after, with no slack).

That is a bigger build, and it would answer two questions at once. So this build
extends the vector to **`{4, 5, 6, 6}`**: the fourth page reuses LFO3's
descriptor. The new page is therefore a **duplicate of LFO3** -- same columns,
same parameters, editing one moves the other.

That is the point. It is unambiguous on the device, it cannot hijack a live page
because it claims no new id, and it isolates the navigation question completely.

## The edits

| VA | stock | new | bytes |
|---|---|---|---|
| `0x402cf52c` | 16 zero bytes, no code references | `4, 5, 6, 6` as longwords | 16 |
| `0x40061564` | `0x401e0048` (the packed id pool) | `0x402cf52c` | 4 |
| `0x40061558` | `moveq #3,%d1` | `moveq #4,%d1` | 1 |
| `0x4010dbc6` | `moveq #2,%d1` | `moveq #3,%d1` | 1 |

The last one is the LFO-index clamp inside `LfoPageView::getColumnParameter`'s
`Start Phase` special case. It is not needed to *reach* the page, but leaving it
at 2 would make `SPH` behave differently on page four than the others, which
would muddy the result rather than sharpen it.

**The pool at `0x401e0000` is untouched.** §5b established it is packed with no
gaps, so the vector could not simply grow in place -- hence the relocated copy.
The MIDI-track LFO group at `(0x401e0000, 2)` is not touched either: the owner's
decision, 2026-09-16, is that LFO4 is sound-tracks-only and a third MIDI LFO is a
separate feature.

## What to look for

1. **It boots.**
2. **`[MOD]` cycles four pages** instead of three.
3. **The fourth page reads `LFO3`** and shows `SPD MULT FADE DEST WAVE SLEW SPH
   MODE DEP` -- the same nine columns as page three.
4. **Editing the fourth page moves LFO3.** Turn `SPD` on page four, then look at
   page three: it should have moved. That is the positive control, and without it
   a page that merely *draws* proves nothing.
5. **LFO1, LFO2 and LFO3 still work normally.**

All five pass -> navigation is solved end to end, and v5 can spend its risk on
the 38th descriptor and the table relocation.

Fails at 2 -> the page count is not the only thing bounding `[MOD]`, and whatever
increments the view's LFO index at `+0x90` has its own limit to find.

Fails at 4 but passes at 3 -> the page draws from a descriptor but the index is
not reaching the value path, which points back at the ten `+0x90` sites
`docs/lfo4-build-plan.md` §5e lists as unread.

## Safety

Sixteen bytes into verified-free space, one 4-byte immediate and two single
bytes, each asserted against its stock encoding before it is written. No
relocation of anything that ships, no cave code, nothing executed that was not
already executed. Reversible by reflashing stock.

No firmware bytes live in this repository: the image is read from the owner's
local copy at build time. Output is a .syx under `00_Resources/02_Builds/`,
which is gitignored.
"""

import hashlib
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load

MAIN_OS = 3
BASE = 0x40000400

# 896 bytes of zeroes with no code reference, from `dnfw cave scan`, and not in
# a fixed-stride group. Sixteen of them become the relocated id vector.
VECTOR_VA = 0x402CF52C
VECTOR = (4, 5, 6, 6)  # LFO1, LFO2, LFO3, and LFO3 again

# `movel #0x401e0048,%d0` -- the operand is the 4 bytes after the opcode word.
POOL_OPERAND_VA = 0x40061564
POOL_STOCK = 0x401E0048

# The two one-byte immediates.
EDITS = [
    (0x40061558, bytes((0x72, 0x03)), bytes((0x72, 0x04)),
     "id-vector length passed to LfoPageView"),
    (0x4010DBC6, bytes((0x72, 0x02)), bytes((0x72, 0x03)),
     "LFO-index clamp in LfoPageView::getColumnParameter"),
]

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo4-nav-test4_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    _check_pool(content)
    _check_vector_space(content)

    print("edits:")
    for va, stock, new, what in EDITS:
        _poke(content, va, stock, new, what)

    at = POOL_OPERAND_VA - BASE
    got = struct.unpack_from(">I", content, at)[0]
    if got != POOL_STOCK:
        raise SystemExit(
            f"the id-vector pointer at 0x{POOL_OPERAND_VA:08x} is "
            f"0x{got:08x}, expected 0x{POOL_STOCK:08x} -- refusing to write"
        )
    struct.pack_into(">I", content, at, VECTOR_VA)
    print(f"  0x{POOL_OPERAND_VA:08x}  0x{POOL_STOCK:08x} -> 0x{VECTOR_VA:08x}"
          f"   id-vector source")

    for i, v in enumerate(VECTOR):
        struct.pack_into(">I", content, VECTOR_VA - BASE + i * 4, v)
    print(f"  0x{VECTOR_VA:08x}  16 bytes  id vector = "
          f"{{{', '.join(str(v) for v in VECTOR)}}}")

    replacement = compress(section.id, section.dest, bytes(content))
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)

    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  16 data bytes + 1 pointer + {len(EDITS)} one-byte immediates")
    print(f"  sha256 {hashlib.sha256(syx).hexdigest()}")
    print("\nVerify before flashing:  dnfw inspect", OUT)
    return 0


def _poke(content: bytearray, va: int, stock: bytes, new: bytes, what: str) -> None:
    at = va - BASE
    got = bytes(content[at:at + len(stock)])
    if got != stock:
        raise SystemExit(
            f"site 0x{va:08x} ({what}) is {got.hex()}, expected {stock.hex()} "
            f"-- not the image this build was measured against, refusing to write"
        )
    content[at:at + len(new)] = new
    print(f"  0x{va:08x}  {got.hex()} -> {new.hex()}   {what}")


def _check_vector_space(content: bytearray) -> None:
    """The 16 bytes must actually be free, checked rather than trusted.

    `dnfw cave scan` reported this run as zeroes with no code reference, but a
    scan is a scan. Re-reading the bytes here means the build refuses on an
    image whose layout differs from the one that was scanned.
    """
    at = VECTOR_VA - BASE
    span = bytes(content[at:at + len(VECTOR) * 4])
    if span != b"\x00" * len(span):
        raise SystemExit(
            f"0x{VECTOR_VA:08x} is not 16 zero bytes ({span.hex()}) -- "
            f"refusing to write the id vector over live data"
        )
    print(f"  0x{VECTOR_VA:08x}: 16 zero bytes confirmed free")


def _check_pool(content: bytearray) -> None:
    """Refuse unless the stock pool still reads {4, 5, 6} where we expect it.

    This is the geometry guard. If the pool has moved or its contents differ,
    every address in this build is suspect and it must not run.
    """
    got = [
        struct.unpack_from(">I", content, POOL_STOCK - BASE + i * 4)[0]
        for i in range(3)
    ]
    if got != [4, 5, 6]:
        raise SystemExit(
            f"the sound-track LFO id list at 0x{POOL_STOCK:08x} reads {got}, "
            f"expected [4, 5, 6] -- refusing to write"
        )
    print(f"geometry: 0x{POOL_STOCK:08x} reads {got} as expected\n")


if __name__ == "__main__":
    raise SystemExit(main())

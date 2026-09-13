"""Find the code that points at a known string -- named landmarks in a blob.

The SHARC image carries no RTTI, so the trick that turned MAIN OS into a named
C++ program does not transfer. It carries something nearly as good: FreeRTOS is
**open source**, and its `configASSERT()` macro bakes in `__FILE__`. So the image
names its own translation units -- `tasks.c`, `queue.c`, `timers.c` -- and any
code holding one of those addresses is *inside that file*.

That is the whole idea. An address is a landmark only if something references
it, and a 32-bit word equal to a string's address is a reference. No
disassembler is needed to find them, which matters: at the time of writing
nothing in this repository decodes SHARC.

What this gives and does not give:

* **gives** — "the word at 0x282d1a40 points at the `tasks.c` string, so
  0x282d1a40 is a literal in code compiled from tasks.c". That bounds a region
  of the image to a file whose source can be read upstream.
* **does not give** — a function name. A file is not a symbol, and one file
  holds many functions. This narrows; it does not identify.

Both word orders are tried, because the caller may not know the endianness of
the image it is handing over, and guessing it silently is how a scan returns
zero and gets read as "no references".
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

PRINTABLE = re.compile(rb"[ -~]{6,}")


@dataclass(frozen=True)
class Anchor:
    """A string in the image, and every word that points at it."""

    address: int
    text: str
    sites: tuple[int, ...]
    endian: str

    @property
    def referenced(self) -> bool:
        return bool(self.sites)


def strings_in(regions: list[tuple[int, bytes]], match: str | None = None) -> dict[int, str]:
    """Every printable run in the loaded regions, keyed by its load address."""
    found: dict[int, str] = {}
    for base, payload in regions:
        for hit in PRINTABLE.finditer(payload):
            text = hit.group().decode()
            if match is None or match in text:
                found[base + hit.start()] = text
    return found


def references_to(regions: list[tuple[int, bytes]], targets: set[int],
                  endian: str = "<") -> dict[int, tuple[int, ...]]:
    """Addresses of 32-bit words whose value is one of `targets`.

    Scanned on a 2-byte stride: SHARC instructions start on even offsets, and a
    literal pool entry need not be 4-byte aligned.
    """
    fmt = endian + "I"
    sites: dict[int, list[int]] = {}
    for base, payload in regions:
        for offset in range(0, max(len(payload) - 3, 0), 2):
            value = struct.unpack_from(fmt, payload, offset)[0]
            if value in targets:
                sites.setdefault(value, []).append(base + offset)
    return {value: tuple(at) for value, at in sites.items()}


def anchors(regions: list[tuple[int, bytes]], match: str | None = None) -> list[Anchor]:
    """Landmark strings and their referencing sites, best word order first.

    Whichever endianness finds more references is the one reported; if neither
    finds any, little-endian is reported with no sites rather than nothing at
    all, so the caller sees the strings and the empty result together.
    """
    found = strings_in(regions, match)
    if not found:
        return []
    targets = set(found)
    little = references_to(regions, targets, "<")
    big = references_to(regions, targets, ">")
    endian, sites = ("<", little) if len(little) >= len(big) else (">", big)
    return sorted(
        (Anchor(address=address, text=text, sites=sites.get(address, ()), endian=endian)
         for address, text in found.items()),
        key=lambda a: (-len(a.sites), a.address),
    )

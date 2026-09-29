"""Every address above BSS a mod's bytes name must be RAM the mod declares.

The RAM above BSS (`0x466b74d0`..`0x48000000`) belongs to no one: the firmware
never addresses it, so every mod that uses it picks its addresses by hand and
declares them (`ram()`), and the platform compares the declarations. A
declaration that misses a range is invisible to that comparison. On 2026-09-30
lfo4's LFO state arrays at `0x46700000` were written by its edits but not
declared, the boot screen's stamp was placed on top of them, and the instrument
raised V04 at `0x46700000`.

So this reads the bytes instead of trusting the list. It applies the mod alone
to stock, takes every changed run of MAIN OS and every `CODE` chunk image, and
finds each word-aligned 32-bit value in that window. A value is accounted for
when it falls inside the mod's own `ram()` or inside the platform's data window.
Two idioms name an address just outside a range without using it: a base
minus a field offset (lfo4's table accessors hold `0x468fffcc`, the relocated
table less 52, as stock holds its own table less 52) and an end pointer a loop
compares against. So a value within `SLACK` bytes of a declared range counts as
that range's. The scan stops at `0x47000000`: nothing is placed above it, and
the stack descends from `0x48000000`.

What is left is reported: a missing declaration, or bytes that only look like an
address (two instructions, ASCII). A mod lists the second kind in `NOT_RAM`,
each with the place it was disassembled at, so the next change to the mod is
checked afresh rather than waved through.

One subject: that comparison. Applying the mod is the caller's business.
"""

from __future__ import annotations

import struct

from . import RAM, platform
from ..patch import area

LO, HI = 0x466B74D0, 0x47000000
SLACK = 64


def _words(data: bytes, base: int) -> list[tuple[int, int]]:
    """(address of the word, its value) for every value in the window."""
    out = []
    for at in range(0, len(data) - 3, 2):
        v = struct.unpack_from(">I", data, at)[0]
        if LO <= v < HI:
            out.append((base + at, v))
    return out


def named(stock: bytes, content: bytes) -> list[tuple[int, int]]:
    """Addresses above BSS that CONTENT names and STOCK does not."""
    found = []
    n = len(stock)
    i = 0
    while i < n:
        if stock[i] == content[i]:
            i += 1
            continue
        j = i
        while j < n and stock[j] != content[j]:
            j += 1
        lo, hi = max(0, i - 3) & ~1, min(n, j + 3)        # a word straddling the run
        found += [(platform.BASE + a, v) for a, v in _words(bytes(content[lo:hi]), lo)
                  if not (LO <= struct.unpack_from(">I", stock, a)[0] < HI)]
        i = j
    if len(content) > platform.STOCK_LENGTH:
        for cid, data in platform.split(content)[1]:
            if cid == area.CODE:
                code = area.CodeChunk.unpack(data)
                found += _words(code.image, code.load)
    return sorted(set(found))


def undeclared(stock: bytes, content: bytes, ram, not_ram=()) -> list[tuple[int, int]]:
    """(where, value) for each named address no declared range holds.

    NOT_RAM: the places (`where`) a mod has shown not to hold an address."""
    ranges = [(x.start, x.end) for x in list(ram) + platform.ram() if x.section == RAM]
    skip = set(not_ram)
    return [(at, v) for at, v in named(stock, content)
            if at not in skip and not any(lo - SLACK <= v < hi + SLACK for lo, hi in ranges)]

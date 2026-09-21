"""Move the instrument's parameter table somewhere it can grow, and grow it.

The Digitone II describes every knob it has in one table of 320 records, 60
bytes each, at `0x401f7fc8` **inside the firmware image**. A fourth LFO needs
ten more records, and the table cannot grow in place: the next byte after it
already belongs to another array (`0x401fcac8`).

So the table is copied into the appended area with ten records after it, and
every instruction that reaches the old one is repointed. That is possible only
because of how the accessors are written, which is worth stating once:

    cmpil #321,%d0                 ; the entry space, entry = index + 1
    scs %d1 ; mvsb %d1,%d1 ; andl %d1,%d0
    lea 0x401f7f94,%a0             ; table - 60 + 8: the base, PRE-BIASED
    movel %d0,%d1 ; lsll #2,%d1 ; lsll #6,%d0 ; subl %d1,%d0
    movel %a0@(0,%d0:l),%d0

**Every accessor carries its own biased base and recomputes the address**;
none caches a pointer and no record boundary appears as a literal anywhere. So
rewriting the bases redirects every lookup there is. Three biases are in use --
`- 60 + 8`, `- 60 + 16`, `- 60 + 40`, one per field an accessor wants -- and
this module finds their sites by searching for the literal rather than holding
an address list, then asserts the count it expects to find.

A second table shadows the first at run time: **321 entries of 68 bytes** at
`0x4243325c`, indexed by the same entry number, which is why it shares the
`321`. It is far cheaper -- six sites -- and it moves the same way.

**What a missed site does, because that decides how much this may be trusted.**
A missed *base* keeps reading the old table, which is still there and still
correct for entries 1..320; it reads garbage only for the ten new ones. A
missed *bound* clamps a new entry to the fallback record. Both are visibly
wrong on the new page and harmless everywhere else -- this patch cannot turn a
stock parameter into a wrong one, because the copy is byte-identical for every
record that already existed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

TABLE, RECORD, COUNT = 0x401F7FC8, 60, 320
BIASES = (8, 16, 40)                       # the field each accessor wants
EXPECTED_BASES = {8: 53, 16: 1, 40: 2}     # measured on stock 1.11, 56 in all

RUNTIME, RUNTIME_STRIDE = 0x4243325C, 68   # the companion table, in RAM
EXPECTED_RUNTIME = 6                       # five field offsets, six sites

# `cmpil #320` and `cmpil #321` both spell the same bound -- `bhi` against 320
# rejects, `scs` against 321 keeps -- so both forms are rewritten. Three sites
# hold a 320 that is **not** this bound: loops that step `d2` by 20 up to 320,
# sixteen iterations of something else entirely (0x40031fd8 and its two twins).
# They are named here so that the count still checks.
NOT_THE_BOUND = (0x40031FEE, 0x40032422, 0x400325E2)

# And one site that **is** this bound and must be left alone anyway.
#
# `param_set_tables_build` (0x400dc4d0) walks every record and files its entry
# number into tables indexed by the record's **value slot**, one of them per
# parameter group: `0x42c64b3c`, `0x42c647ac` and `0x42c649a8`, each of which
# the same routine zeroes with `pea 0x194` -- 404 bytes, **101 longwords**, one
# per slot 0..100. LFO4's records carry slots 101-108, which is 32 bytes past
# the end of each, and the byte after `0x42c64b3c`'s 404th is `0x42c64cd0`, the
# filter table this routine zeroes two calls earlier.
#
# So raising this one bound registers ten records into three tables that have
# no room for them and silently overwrites the table next door. It boots, it
# draws, and it would have gone to the instrument: the class of fault a gate
# watching for crashes cannot see.
#
# Left at 321, the loop walks the relocated table's first 320 records and does
# exactly what stock does. LFO4's slots stay unregistered, which is the read
# side -- `0x400dc02a` bounds slots at 100 in its own right, so it answers 0 for
# 101 either way. Growing those three tables to 109 entries is five literals
# each plus a size immediate, and it belongs with the rest of the read side.
NOT_THIS_TIME = {0x400DC7F0: "param_set_tables_build files by value slot into "
                             "101-entry tables; see docs/lfo4-build-plan.md"}
EXPECTED_BOUNDS = 54


class TableError(ValueError):
    """The image does not hold what this module was measured against."""


@dataclass(frozen=True)
class Site:
    """One literal to rewrite: where it is, what it holds, what it means."""

    va: int
    was: int
    now: int
    what: str

    @property
    def width(self) -> int:
        return 4


def _even_occurrences(content: bytes, base: int, value: int) -> list[int]:
    """Every instruction-aligned place the four bytes of `value` appear."""
    want, out, i = struct.pack(">I", value), [], 0
    while True:
        i = content.find(want, i)
        if i < 0:
            return out
        if i % 2 == 0:
            out.append(base + i)
        i += 1


def base_sites(content: bytes, base: int) -> list[Site]:
    """The 56 pre-biased bases of the 60-byte table."""
    out = []
    for bias in BIASES:
        literal = TABLE - RECORD + bias
        found = _even_occurrences(content, base, literal)
        if len(found) != EXPECTED_BASES[bias]:
            raise TableError(f"expected {EXPECTED_BASES[bias]} site(s) holding "
                             f"0x{literal:08x} (table - {RECORD} + {bias}), found {len(found)}")
        out += [Site(va, literal, 0, f"base, field +{bias}") for va in found]
    return out


def runtime_sites(content: bytes, base: int) -> list[Site]:
    """The six bases of the 68-byte companion table, at five field offsets."""
    out = []
    for field in (0, 4, 20, 44, 60):
        for va in _even_occurrences(content, base, RUNTIME + field):
            out.append(Site(va, RUNTIME + field, 0, f"runtime base, field +{field}"))
    if len(out) != EXPECTED_RUNTIME:
        raise TableError(f"expected {EXPECTED_RUNTIME} runtime-table base sites, found {len(out)}")
    return out


def bound_sites(content: bytes, base: int) -> list[Site]:
    """Every `cmpil #320` / `#321` that bounds the entry space.

    A bound belongs to the table when the same function multiplies by 60 --
    `lsl.l #6` and `lsl.l #2` with a subtraction between them -- or walks it
    with `lea 60(aN),aN`. The six that do neither were each disassembled and
    named in `docs/lfo4-build-plan.md`; three are this bound reached through a
    call, three are loops over the table with the stride in an address
    register, and the three in `NOT_THE_BOUND` are not this bound at all.

    `NOT_THIS_TIME` is the other kind of exclusion: a site that is this bound
    and must still be left where it is. Read its entry before changing it.
    """
    out = []
    for value in (320, 321):
        for reg in range(8):
            opcode = bytes([0x0C, 0x80 | reg]) + struct.pack(">I", value)
            i = 0
            while True:
                i = content.find(opcode, i)
                if i < 0:
                    break
                va = base + i
                if i % 2 == 0 and va not in NOT_THE_BOUND and va not in NOT_THIS_TIME:
                    out.append(Site(va + 2, value, 0, f"bound, cmpil #{value},%d{reg}"))
                i += 1
    if len(out) != EXPECTED_BOUNDS:
        raise TableError(f"expected {EXPECTED_BOUNDS} bound sites, found {len(out)}")
    return out


def records(content: bytes, base: int) -> bytes:
    """The 320 stock records, byte for byte."""
    at = TABLE - base
    return bytes(content[at:at + RECORD * COUNT])


def poke(content: bytearray, base: int, site: Site) -> None:
    at = site.va - base
    here = struct.unpack_from(">I", content, at)[0]
    if here != site.was:
        raise TableError(f"0x{site.va:08x} holds 0x{here:08x}, not the stock "
                         f"0x{site.was:08x} ({site.what})")
    struct.pack_into(">I", content, at, site.now)


def relocate(content: bytearray, base: int, *, table_va: int, runtime_va: int,
             added: int) -> list[Site]:
    """Repoint both tables and widen the entry space by `added` records.

    -> every site it wrote, so the build can print and the caller can count.
    """
    delta = table_va - TABLE
    sites = [Site(s.va, s.was, s.was + delta, s.what) for s in base_sites(content, base)]
    delta_runtime = runtime_va - RUNTIME
    sites += [Site(s.va, s.was, s.was + delta_runtime, s.what)
              for s in runtime_sites(content, base)]
    sites += [Site(s.va, s.was, s.was + added, s.what) for s in bound_sites(content, base)]
    for site in sites:
        poke(content, base, site)
    return sites

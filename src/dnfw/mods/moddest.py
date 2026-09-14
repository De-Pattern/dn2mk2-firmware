"""Open thirteen more parameters to LFO and modulation control.

## What this does

The Digitone II decides whether a parameter may be a modulation destination
from a 32-bit mask at `record+0x24` in the table the destination-list builder
walks. `0x1e00` means "ordinary modulatable parameter"; `0` means the parameter
is never offered. Thirteen per-voice parameters ship with `0`, and flipping
them to `0x1e00` makes them appear as LFO destinations and actually modulate.

| page | parameters |
|---|---|
| SYN | `ATRG ARST BTRG BRST PHRT KSA KSB1 KSB2` |
| Amp | `DEL MODE RSET` |
| Portamento | `PTIM PORT` |

**Confirmed on hardware, 2026-09-12** (`docs/flashing.md`). An image opening all
32 closed parameters was flashed: all 13 of these appeared and modulated, and
the 19 Chorus and Master ones did not. The mask is necessary but not sufficient
— for global FX the gate is the enumeration, not the mask
(`docs/modulation-mask.md`, `docs/fx-parameter-space.md`). **This mod ships only
the 13 that were measured to work**, because offering a user 19 flips that
provably do nothing is worse than not offering them.

## Why it is located rather than hardcoded

The mask table is at `0x401f7f94` on 1.11, and the destination-list code sites
shift by a uniform `+0x768` between 1.10E and 1.11 — so addresses move between
builds and an address baked in here would silently write into the wrong
structure on an image it was not measured against.

Instead the table is **found**, from a signature the image itself carries: a
long run of 60-byte-strided words drawn only from the eight values the mask
histogram allows. Every target record is then matched by `(group,
parameter_id)` **and** checked to be currently closed before anything is
written, so nothing depends on where the run was judged to start.

The first attempt at that signature was wrong and is worth keeping: it looked
for the LFO `DEST` masks because `docs/modulation-mask.md` records exactly one
of each — but that histogram is over the **mask column**, and `0x00040000`
occurs 303 times in the section as a whole. A count taken down one column says
nothing about the page.

A record that does not match is an error, not a skip. An image whose layout has
moved should refuse, not half-apply.
"""

import struct

from . import Extent, ModError, Result

ID = "moddest"
NAME = "More modulation destinations"
SUMMARY = "Open 13 per-voice parameters as LFO/modulation destinations."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS, the ColdFire image

STRIDE = 60                        # one parameter record
MASK_AT = 0x24                     # the modulation mask inside a record
GROUP_AT = 0x00
ID_AT = 0x04

OPEN = 0x1E00                      # every ordinary modulatable parameter
CLOSED = 0x0                       # never offered

# Each LFO's DEST parameter carries a unique identifying bit in bits 16-18 --
# once each in the mask column, but NOT once in the section. See `find_table`.
DEST_MASKS = (0x40000, 0x20000, 0x10000)

# Every value the mask column is allowed to hold -- the histogram in
# `docs/modulation-mask.md`, identical in 1.10E and 1.11 value for value.
ALLOWED_MASKS = frozenset((0x1E00, 0x0E00, 0x0600, 0x0200, 0x0) + DEST_MASKS)

# A run shorter than this is not the table. The real one is 320 records.
MIN_RECORDS = 100

# (group, parameter_id, label). Group and id are the record's own fields, so
# they identify a parameter independently of where the table sits.
TARGETS = (
    (14, 93, "Portamento Time (PTIM)"),
    (14, 94, "Portamento Enabled (PORT)"),
    (11, 80, "Amp Delay Time (DEL)"),
    (11, 91, "Amp Mode (MODE)"),
    (11, 92, "Amp Env Reset (RSET)"),
    (0, 44, "SYN A Trig (ATRG)"),
    (0, 45, "SYN A Env Reset (ARST)"),
    (0, 47, "SYN B Trig (BTRG)"),
    (0, 48, "SYN B Env Reset (BRST)"),
    (0, 33, "SYN Phase Reset (PHRT)"),
    (0, 62, "SYN Key Tracking A (KSA)"),
    (0, 63, "SYN Key Tracking B1 (KSB1)"),
    (0, 64, "SYN Key Tracking B2 (KSB2)"),
)


def _u32(data: bytes, at: int) -> int:
    return struct.unpack_from(">I", data, at)[0]


def find_table(data: bytes) -> tuple[int, int]:
    """-> (file offset of record 0, record count), located by signature.

    **Not by a unique constant.** The first attempt looked for the LFO `DEST`
    masks on the grounds that `docs/modulation-mask.md` records exactly one of
    each — but that histogram is over the *mask column*, and `0x00040000`
    occurs 303 times in the section as a whole. A count taken down one column
    says nothing about the page.

    What is actually distinctive is the **column itself**: a long run of
    60-byte-strided words drawn only from the eight values the histogram
    allows, containing all three LFO-parameter masks. Random data does not
    produce a hundred of those in a row at a fixed stride.

    Raises ModError when no such run is unique, which is the honest outcome for
    an image this mod was not measured against.
    """
    import struct as _s
    # Seed on the rarest of the allowed values so the scan stays cheap: 0x0600
    # occurs 32 times in the section against 303 for the DEST bit.
    seeds = [i for i in range(0, len(data) - 4, 4)
             if data[i:i + 4] == _s.pack(">I", 0x0600)]

    runs = []
    for seed in seeds:
        first = seed % STRIDE
        at = seed
        while at - STRIDE >= 0 and _allowed(data, at - STRIDE):
            at -= STRIDE
        lo = at
        n = 0
        while _allowed(data, lo + n * STRIDE):
            n += 1
        if n < MIN_RECORDS:
            continue
        column = {_u32(data, lo + k * STRIDE) for k in range(n)}
        if not {0x0E00, 0x0600, 0x0200, 0x1E00} <= column:
            continue
        runs.append((lo - MASK_AT, n))

    unique = sorted(set(runs))
    if len(unique) != 1:
        raise ModError(
            f"found {len(unique)} candidate parameter tables, expected 1; "
            f"this image's layout is not the one this mod was measured "
            f"against")
    return unique[0]


def _allowed(data: bytes, at: int) -> bool:
    """Whether the word at `at` is a value the mask column is allowed to hold."""
    if at < 0 or at + 4 > len(data):
        return False
    return _u32(data, at) in ALLOWED_MASKS


def _plausible(data: bytes, at: int) -> bool:
    """Whether a record at `at` looks like one, judged by its mask."""
    return at >= 0 and at + STRIDE <= len(data) and _allowed(data, at + MASK_AT)


def _records(data: bytes):
    """-> {(group, id): file offset of the record} for named records."""
    start, count = find_table(data)
    out = {}
    for i in range(count):
        at = start + i * STRIDE
        group, pid = _u32(data, at + GROUP_AT), _u32(data, at + ID_AT)
        if group == 0xFFFFFFFF:
            continue
        out.setdefault((group, pid), at)
    return out


def _targets(data: bytes) -> list[tuple[int, str]]:
    """-> [(offset of the mask word, label)] for all thirteen, or raise."""
    found = _records(data)
    out = []
    for group, pid, label in TARGETS:
        at = found.get((group, pid))
        if at is None:
            raise ModError(f"{label}: no record with group={group} id={pid}")
        mask = _u32(data, at + MASK_AT)
        if mask == OPEN:
            raise ModError(f"{label}: already open (mask 0x{mask:x}); this "
                           f"image may already carry this mod")
        if mask != CLOSED:
            raise ModError(f"{label}: mask is 0x{mask:x}, expected 0x0; this "
                           f"is not the parameter this mod was measured on")
        out.append((at + MASK_AT, label))
    return out


def extents(firmware) -> list[Extent]:
    """One extent per parameter, and only the byte that actually changes.

    `0x00000000` -> `0x00001e00` alters a single byte of the four. Declaring
    the whole word would over-claim, and extents are the only compatibility
    guarantee the mod system offers -- over-claiming makes it refuse
    combinations that are in fact fine.
    """
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError(f"image has no section {SECTION}")
    data = section.unpack() or section.raw_payload
    return [Extent(SECTION, at + 2, 1, label) for at, label in _targets(data)]


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError(f"image has no section {SECTION}")
    data = bytearray(section.unpack() or section.raw_payload)

    notes = []
    for at, label in _targets(bytes(data)):
        struct.pack_into(">I", data, at, OPEN)
        notes.append(f"{label} opened (0x0 -> 0x{OPEN:x})")
    notes.append(f"{len(TARGETS)} parameters opened, "
                 f"{len(TARGETS)} bytes changed")

    return Result(payloads={SECTION: bytes(data)},
                  extents=extents(firmware),
                  notes=notes)

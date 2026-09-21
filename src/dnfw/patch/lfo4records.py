"""The ten parameter records a fourth LFO is made of.

They are LFO3's ten records with as little changed as possible, because every
field this project has *not* identified is a field it must not invent. Diffing
LFO1's group against LFO2's and LFO3's said exactly which words carry the LFO
number and which are the same on all three (`docs/lfo4-build-plan.md`), and
only the first kind is written here.

A group of ten is **eight primaries and two alternates**, and the alternates
are recognisable because they share a value slot with a primary: `SLEW` shares
slot 6 with `SPH` and is shown when the waveform is `RND`, and the second
`MULT` carries the shorter multiplier range. Building eight and leaving two
blank would give a fourth LFO whose random waveform has no slew control, on a
page that otherwise looked finished.

Three fields are decisions rather than copies, and each is the conservative
choice:

- **`+36`, the NRPN.** Set to `-1`, no NRPN. LFO4 is not addressable over MIDI
  in this build. `SLEW` already holds `-1` in all three stock groups, so the
  convention is the instrument's own rather than ours. Assigning ten free NRPN
  numbers is a later, separable change.
- **`+40`, the unidentified id.** It is **unique across all 320 records** --
  320 distinct values, no duplicates, no `-1` -- so it is a key and a copy
  would collide. Its meaning is unknown (`dnfw.params.record.physical_id` keeps
  the history of three wrong names), so the ten values are taken from **gaps
  inside the range the table already uses**: in range whatever it indexes, and
  claimed by no record.
- **`+8`, the group.** Copied from LFO3 rather than given a new number. A new
  group would be a new index into whatever reads this field, and nothing here
  has read it; LFO3's is known to be valid, and `(group, id)` still names each
  record uniquely because the ids are 101-108.

`+44`, the destination capability flags, is the one field where the firmware
had already left a fourth LFO room: the staircase `0x1e00 / 0x0e00 / 0x0600`
continues to `0x0200`, and the three `DEST` records' `0x40000 / 0x20000 /
0x10000` continues to `0x8000`. LFO4's eight primaries get **`0`** -- no page
may target them, which is what keeps the modulation graph acyclic -- and its
`DEST` record gets `0x8000`, the value the pattern names.
"""

from __future__ import annotations

import struct

from .paramtable import COUNT, RECORD, TABLE, TableError

LFO3_FIRST, GROUP_SIZE = 94, 10            # records 94..103, the LFO3 group
SLOT0 = 101                                # LFO4's first value slot (step 4a)

GROUP = 8                                  # the fields this module writes
SLOT = 12
NRPN = 36
UNIQUE = 40
FLAGS = 44
PAGE_NAME = 52

UNSET = 0xFFFFFFFF
DEST_POSITION = 3                          # SPD MULT FADE *DEST* WAVE SLEW SPH MODE DEP MULT'
DEST_FLAGS = 0x00008000                    # 0x40000, 0x20000, 0x10000, and then this

# Position -> value slot. Positions 5 and 6 share slot 106 (SLEW and SPH) and
# position 9 shares 102 (the second MULT), exactly as the stock groups do.
SLOTS = (0, 1, 2, 3, 4, 5, 5, 6, 7, 1)


def _u32(blob: bytes, off: int) -> int:
    return struct.unpack_from(">I", blob, off)[0]


def free_unique_ids(content: bytes, base: int, want: int = GROUP_SIZE) -> list[int]:
    """`want` values of field +40 that are inside the used range and unclaimed."""
    used = {_u32(content, TABLE - base + RECORD * i + UNIQUE) for i in range(COUNT)}
    used.discard(UNSET)
    gaps = [v for v in range(min(used), max(used)) if v not in used]
    if len(gaps) < want:
        raise TableError(f"only {len(gaps)} unused id(s) inside the table's range, {want} wanted")
    return gaps[:want]


def build(content: bytes, base: int, *, page_name_va: int) -> bytes:
    """-> the ten records, ready to append to a copy of the table."""
    ids = free_unique_ids(content, base)
    out = bytearray()
    for k in range(GROUP_SIZE):
        at = TABLE - base + RECORD * (LFO3_FIRST + k)
        record = bytearray(content[at:at + RECORD])
        struct.pack_into(">I", record, SLOT, SLOT0 + SLOTS[k])
        struct.pack_into(">I", record, NRPN, UNSET)
        struct.pack_into(">I", record, UNIQUE, ids[k])
        struct.pack_into(">I", record, FLAGS, DEST_FLAGS if k == DEST_POSITION else 0)
        struct.pack_into(">I", record, PAGE_NAME, page_name_va)
        out += record
    return bytes(out)


def describe(records: bytes) -> list[str]:
    """One line per record, for the build to print rather than be trusted."""
    rows = []
    for k in range(len(records) // RECORD):
        r = records[RECORD * k:RECORD * (k + 1)]
        rows.append(f"    slot {_u32(r, SLOT):>3}  group {_u32(r, GROUP):>3}  "
                    f"range {_u32(r, 20):#06x}  flags {_u32(r, FLAGS):#010x}  "
                    f"id {_u32(r, UNIQUE):>4}")
    return rows

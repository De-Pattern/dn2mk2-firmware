"""v3 of the page-renumber experiment: move the TRIG group AND tell the
classifier about it.

**The one thing this build tests.** `docs/lfo4-build-plan.md` §5b argues that
LFO4 should sit at page `0x1d` with the TRIG group moved up to `0x1f`, because
keeping the LFO pages contiguous turns eight sites into one-byte edits instead
of nine caves. That argument rests on the claim that **every consumer of page id
`0x1d` is now known**. This build is the falsifier.

It is the same page move v1 and v2 made. Nothing about LFO4 is added here -- no
records, no bounds, no tick, no slots. If the TRIG group works at `0x1f`, the
renumbering route is proven and `0x1d` is free for LFO4. If it does not, the
classifier list in §5b is still incomplete and LFO4 goes to `0x1f` behind caves
instead.

## Why v1 and v2 failed, and what changed

**v1** moved the 22 records' page ids and nothing else. The pages drew and every
moved parameter read zero: `param_set_tables_build` assigns records to a backing
table by page id through a cascade ending in an *exact match*, and page `0x1f`
fell out of it with no table at all.

**v2** added that one byte -- `moveq #29` -> `moveq #31` at `0x400dc71e`. The
device was still wrong, and the owner's report named the mechanism exactly:

> *"trigger and retrig parameters still doesn't work, only that weird
> modulation and if you plock in that specific way."*

DNX then read pattern A1 back off the instrument and confirmed the model eight
for eight: a moved TRIG record was writing the **sound** value array at index
`record+0x04`, and storing as a lock under `4*slot + lfo`. `VEL` read 112, which
is LFO1 `SPD`'s default; `PROB` re-aimed LFO2.

**That is a fall-through, and 2026-09-16 found the thing it falls through.**
Parameter ownership is decided by a **virtual predicate at vtable slot `+0x54`**
on each of four `*ParameterSet` classes, each reading the page id out of the
record and answering a page test. `TrigParameterSet`'s predicate names page
`0x1d` as a bare `moveq #29` and v2 never touched it, so after the move the TRIG
records were claimed by nobody, and the cascade at `0x40041a72` has **no default
guard** -- two tests and an unconditional jump into the sound-side addressing.

So v2 moved the records and the *builder*, and left the *classifier* behind.

## The three bytes

Found by scanning for comparisons against 29 anchored on the 49 sites that load
the parameter table at `0x401f7f94` -- a far better instrument than scanning for
the constant alone, which is what returned four unrelated hits in §3b and made
the earlier cost model wrong.

| VA | stock | what it is |
|---|---|---|
| `0x400dc71e` | `moveq #29,%d1` | `param_set_tables_build`'s exact-match arm (v2 had this) |
| `0x400dbfa0` | `moveq #29,%d1` | **`TrigParameterSet`'s ownership predicate** |
| `0x4003774e` | `moveq #29,%d1` | a page-`0x1d` special case guarding parameter ids 310/311 |

All three are the same instruction at the same length. Each is asserted against
its stock bytes before it is written.

## What to look for on the device

In order. The first failure makes the rest moot.

1. **It boots.**
2. **`[TRIG]` draws** -- `NOTE VEL LEN uTM` with their normal defaults, not
   zeros and not `C0` / `0.188` / `PROB 0%`.
3. **Trig parameters p-lock.** Hold a trig, turn `VEL`, the lock takes and shows.
4. **Retrig works** -- `RTRG VFAD LEN RATE`.
5. **Euclidean works** -- `PL1 PL2 EUC RO1 RO2 TRO OP LEN`.
6. **No stray modulation.** Nothing on the TRIG page should move an LFO. This is
   the specific v2 symptom and the one that matters most.

**All six pass** -> §5b's route is proven, `0x1d` is free, and the next build is
LFO4's records plus the five `moveq #2` -> `moveq #3` bounds.

**Still broken** -> a fourth consumer of `0x1d` exists. Record what differs from
v2; if the symptom has *changed*, the classifier edit did something and the
remaining consumer is narrower than before.

## Safety

Twenty-two 4-byte writes into the parameter table and **three bytes of code**,
each an immediate asserted against its stock value, same length, no relocation.
Nothing alters how the image loads. Reversible by reflashing stock over the
recovery path `docs/flashing.md` records as proven on this instrument -- and
`docs/version-gate.md` establishes the DN2 has no downgrade gate, so an older
stock image is accepted too.

**Back up the +Drive first.** Page ids are believed not to be part of the stored
format -- DNX keys p-locks on parameter id -- but v2 demonstrated that a
misclassified record *does* reach stored patterns, as stray LFO locks. A fresh
project for testing avoids the question entirely.

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
from dnfw.mods.moddest import find_table

MAIN_OS = 3
BASE = 0x40000400
RECORD = 60

F_PAGE_ID = 0x00
F_LONG = 0x28
F_PAGE_LABEL = 0x2C
F_SHORT = 0x30
F_HANDLER = 0x34

FROM_PAGE = 0x1D      # TRIG + Retrig + Euclidean, 22 records
TO_PAGE = 0x1F

EXPECTED_MOVED = 22
EXPECTED_LABELS = {None: 10, "Retrig": 4, "Euclidean": 8}

# Every site that names page 0x1d as an immediate near a parameter-table read.
# `moveq #<page>,%d1` is 0x72 <page> at all three.
NAMERS = [
    (0x400DC71E, "param_set_tables_build exact-match arm"),
    (0x400DBFA0, "TrigParameterSet ownership predicate (vtable +0x54)"),
    (0x4003774E, "page-0x1d special case for parameter ids 310/311"),
]

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/page-classifier-test3_DN2_1.11.syx")


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    start, count = find_table(bytes(content))
    print(f"parameter table: {count} records at VA 0x{start + BASE:08x}")

    def field(i: int, off: int) -> int:
        return struct.unpack_from(">I", content, start + i * RECORD + off)[0]

    def name(i: int, off: int) -> str | None:
        return _cstr(content, field(i, off) - BASE)

    _check_geometry(name, field)
    _check_target_free(field, count)

    movers = [i for i in range(count) if field(i, F_PAGE_ID) == FROM_PAGE]
    if len(movers) != EXPECTED_MOVED:
        raise SystemExit(
            f"page 0x{FROM_PAGE:02x} has {len(movers)} records, expected "
            f"{EXPECTED_MOVED} -- not the grouping this build was measured "
            f"against, refusing to write"
        )

    labels: dict[str | None, int] = {}
    for i in movers:
        label = name(i, F_PAGE_LABEL)
        labels[label] = labels.get(label, 0) + 1
    if labels != EXPECTED_LABELS:
        raise SystemExit(
            f"page 0x{FROM_PAGE:02x} spans {labels}, expected "
            f"{EXPECTED_LABELS} -- refusing to write"
        )

    print("\ncode edits:")
    for va, what in NAMERS:
        _retarget(content, va, what)

    print("\nrecords moved:")
    for i in movers:
        struct.pack_into(">I", content, start + i * RECORD + F_PAGE_ID, TO_PAGE)
        print(f"  id {i:3d}  {name(i, F_SHORT) or '?':<6s} "
              f"{name(i, F_LONG) or '?':<22s} "
              f"page 0x{FROM_PAGE:02x} -> 0x{TO_PAGE:02x}"
              f"   [{name(i, F_PAGE_LABEL) or 'TRIG'}]")

    replacement = compress(section.id, section.dest, bytes(content))
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  {len(movers)} records ({len(movers) * 4} bytes) "
          f"+ {len(NAMERS)} code bytes")
    print(f"  sha256 {hashlib.sha256(syx).hexdigest()}")
    print("\nVerify before flashing:  dnfw inspect", OUT)
    return 0


def _retarget(content: bytearray, va: int, what: str) -> None:
    """Repoint one `moveq #0x1d,%d1` at the new page id, asserting stock first.

    v2 changed the first of these and not the other two, and the device read
    the difference as a fall-through into the sound parameter set. All three
    are the same instruction; none is optional.
    """
    stock = bytes((0x72, FROM_PAGE))
    new = bytes((0x72, TO_PAGE))
    at = va - BASE
    got = bytes(content[at:at + 2])
    if got != stock:
        raise SystemExit(
            f"site 0x{va:08x} ({what}) is {got.hex()}, expected {stock.hex()} "
            f"(moveq #{FROM_PAGE},%d1) -- not the image this build was "
            f"measured against, refusing to write"
        )
    content[at:at + 2] = new
    print(f"  0x{va:08x}  moveq #{FROM_PAGE},%d1 -> moveq #{TO_PAGE},%d1"
          f"   {what}")


def _check_target_free(field, count: int) -> None:
    used = {field(i, F_PAGE_ID) for i in range(count)}
    used.discard(0xFFFFFFFF)
    if TO_PAGE in used:
        raise SystemExit(
            f"page 0x{TO_PAGE:02x} is already used by a record -- moving into "
            f"it would merge two page groups, refusing to write"
        )
    highest = max(p for p in used if p < 0x100)
    if TO_PAGE <= highest:
        raise SystemExit(
            f"page 0x{TO_PAGE:02x} is not above the highest id in use "
            f"(0x{highest:02x}) -- refusing to write"
        )
    print(f"  page ids in use: 0x00..0x{highest:02x}; "
          f"0x{TO_PAGE:02x} is free")


def _check_geometry(name, field) -> None:
    """Refuse unless the record layout resolves the way it should.

    Same guard as build_page_renumber_test.py, and for the same reason: a wrong
    anchor into a dense table still yields plausible strings.
    """
    for param_id, off, expected in [
        (6, F_LONG, "Machine Type"),
        (10, F_LONG, "Track Level"),
        (84, F_PAGE_LABEL, "LFO1"),
        (104, F_PAGE_LABEL, "LFO3"),
    ]:
        got = name(param_id, off)
        if got != expected:
            raise SystemExit(
                f"geometry check failed: id {param_id} field +0x{off:02x} is "
                f"{got!r}, expected {expected!r}"
            )
    blocks = [
        [field(i, F_HANDLER) for i in range(s, s + 10)] for s in (75, 85, 95)
    ]
    if not (blocks[0] == blocks[1] == blocks[2]):
        raise SystemExit(
            "geometry check failed: the LFO1/LFO2/LFO3 blocks disagree, so the "
            "record boundary is wrong"
        )
    for param_id, expected_page in ((75, 0x1A), (85, 0x1B), (95, 0x1C)):
        got = field(param_id, F_PAGE_ID)
        if got != expected_page:
            raise SystemExit(
                f"geometry check failed: id {param_id} is on page 0x{got:02x}, "
                f"expected 0x{expected_page:02x}"
            )

def _cstr(buf: bytes, off: int) -> str | None:
    end = buf.find(b"\x00", off, off + 40)
    if end < 0:
        return None
    s = buf[off:end]
    return s.decode() if s and all(0x20 <= c < 0x7F for c in s) else None


if __name__ == "__main__":
    raise SystemExit(main())

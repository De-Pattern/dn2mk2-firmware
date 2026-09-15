"""Build a test firmware that moves one page group's id, and nothing else.

**The experiment.** `docs/lfo4-feasibility.md` §3b revisited prices a real fourth
LFO's page-id problem: the range test `(page - 0x1a) <= 2` is replicated **six**
times, the bound is a literal `2` in all six, and the cheapest route is to
*renumber* so LFO4 sits at page `0x1d` and the group living there moves up.

That plan rests on a negative: **nothing else names that page id.** The static
evidence for it is worthless -- the scan returned four hits and all four were
unrelated arithmetic (a pointer subtraction, a loop bound, two stack locals).
`docs/PRINCIPLES.md` §19 says a negative is only as good as the instrument that
produced it, and this instrument's precision on this question measured zero.

So this build asks the device instead. It moves **page `0x1d` to page `0x1f`**
and changes nothing else -- no code, no bound, no LFO. If the parameters on that
page still work afterwards, nothing else named the id, and the renumbering route
is open. If they break, the route is closed and we learn it for the price of one
flash rather than after building a fourth LFO on top of it.

## What page 0x1d actually is -- a correction made before this was built

The plan was first written as *"move Retrig to 0x1f"*, on the strength of
§3b's "0x1d is Retrig" and a record count of 22 that seemed to confirm it.

**Page `0x1d` is not Retrig.** It is the whole sequencer/trig group, and the 22
records span three labels:

| Records | Page label | Parameters |
|---|---|---|
| 10 | *(none)* | `NOTE VEL LEN uTM COND AMP.T FLT.T LFO.T PROB FILL` |
| 4 | `Retrig` | `RTRG VFAD LEN RATE` |
| 8 | `Euclidean` | `PL1 PL2 EUC RO1 RO2 TRO OP LEN` |

The count of 22 matched, which is exactly what made the wrong label easy to
believe. This matters for the experiment: the blast radius is the **TRIG page
and the trig-related p-lock parameters**, not one small menu. Read the
observation list below accordingly.

A second correction: §3b says the first free page id is `0x1f`. That is right,
but the scan that first appeared to contradict it was reading **past the end of
the table** -- the table is 321 records, and indices beyond it are not records.
Page ids in use run `0x00`..`0x1e` with gaps at `0x04` and `0x0c`, so `0x1f` is
free and is the next id after the highest in use.

## What to look for on the device

In order, because the first failure makes the rest moot:

1. **It boots.** A data-only edit of this kind should not affect boot at all.
2. **The TRIG page draws.** Press `[TRIG]` and check `NOTE VEL LEN uTM` appear
   with their normal values and ranges.
3. **Trig parameters p-lock.** Hold a trig and turn `VEL` -- the lock should
   take and show.
4. **Retrig works.** `RTRG VFAD LEN RATE` present and functional.
5. **Euclidean works.** `PL1 PL2 EUC` present and functional.

**All five pass** -> nothing else names the page id; renumbering is the route,
and the next build is the six `moveq #2` -> `moveq #3` edits plus LFO4's records.

**Any of 2-5 fails** -> something maps page id to page, by a route the static
scans did not see. Renumbering is dead and option 2 (six caves) is the route.
That is a real answer either way, which is the point.

## Safety

Twenty-two 4-byte writes into the parameter table. **Same length, no
relocation, no code change**, nothing that alters how the image loads.
Fully reversible by reflashing stock, over the recovery path
`docs/flashing.md` records as proven on this instrument.

**Back up the +Drive first.** Page ids are believed to be a runtime grouping and
not part of the stored format -- DNX's pattern format keys p-locks on parameter
id, not page id -- but that belief has not been tested, and a wiped or corrupted
+Drive is not recoverable from anything this project holds.

No firmware bytes live in this repository: the records are read from the user's
own local image at build time and written back. Output is a .syx under
00_Resources/02_Builds/, which is gitignored.
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
from dnfw.mods.moddest import find_table          # reuse: same table, same signature

MAIN_OS = 3
BASE = 0x40000400
RECORD = 60

F_PAGE_ID = 0x00      # the page group this parameter belongs to
F_LONG = 0x28
F_PAGE_LABEL = 0x2C
F_SHORT = 0x30
F_HANDLER = 0x34

FROM_PAGE = 0x1D      # TRIG + Retrig + Euclidean -- see the module docstring
TO_PAGE = 0x1F        # the first id above the highest in use

EXPECTED_MOVED = 22

# The three labels page 0x1d spans, and how many records carry each. Asserted
# before writing, so an image whose grouping differs refuses rather than
# scattering a page group across two ids.
EXPECTED_LABELS = {None: 10, "Retrig": 4, "Euclidean": 8}

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/page-renumber-test_DN2_1.11.syx")


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
            f"{EXPECTED_MOVED} -- this is not the grouping this build was "
            f"measured against, refusing to write"
        )

    labels: dict[str | None, int] = {}
    for i in movers:
        labels[name(i, F_PAGE_LABEL)] = labels.get(name(i, F_PAGE_LABEL), 0) + 1
    if labels != EXPECTED_LABELS:
        raise SystemExit(
            f"page 0x{FROM_PAGE:02x} spans {labels}, expected {EXPECTED_LABELS} "
            f"-- refusing to write"
        )

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
    print(f"  {len(movers)} records moved, {len(movers) * 4} bytes changed, "
          f"no code edited")
    print(f"  sha256 {hashlib.sha256(syx).hexdigest()}")
    print("\nVerify before flashing:  dnfw inspect", OUT)
    return 0


def _check_target_free(field, count: int) -> None:
    """Refuse unless the destination page id is unused by any record.

    The first reconnaissance of this reported page 0x1f already in use. It was
    reading **past the end of the table** -- 400 records assumed where 321
    exist. Bounding the scan by the located count is the fix, and the check is
    kept because an id collision would merge two page groups silently.
    """
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
    """Refuse to run unless the record layout resolves the way it should.

    Same guard as scripts/build_modmask_test.py and build_lfo4_test.py, and for
    the same reason: a wrong anchor into a dense table still yields plausible
    strings. See docs/lfo4-feasibility.md, "The Stage 1 corrections".
    """
    for param_id, off, expected in [
        (6, F_LONG, "Machine Type"),
        (10, F_LONG, "Track Level"),
        (84, F_PAGE_LABEL, "LFO1"),   # last LFO1 record -- id 85 is LFO2
        (104, F_PAGE_LABEL, "LFO3"),  # last LFO3 record -- id 106 is Chorus
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
    # The three LFO pages must still be where the renumbering plan assumes.
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

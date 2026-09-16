"""v5: LFO4 as its own page, with its own parameter records.

**The question.** Does a fourth LFO page exist with **LFO4's own records** behind
it, rather than LFO3's? v4 proved the view will host and drive a fourth page by
pointing it at LFO3's descriptor; this build gives it a descriptor of its own.

**What it deliberately does not do.** LFO4's records keep LFO3's `+0x04` slot
indices, so the *values* still alias LFO3 -- turn LFO4's `SPD` and LFO3's `SPD`
moves with it. Independent values need the extension array and its hooks
(`docs/lfo4-build-plan.md` §3), which is the largest remaining piece and is v6.

So v5's result is: **the page says LFO4 and shows LFO4's own parameters**, which
is everything except where the numbers live.

## The five parts, and which are already proven on hardware

| part | status |
|---|---|
| the TRIG group moved `0x1d` -> `0x1f`, three classifier bytes | **proven, v3** |
| the id vector `{4,5,6,N}`, its length, the LFO-index clamp | **proven, v4** |
| LFO4's ten records on page `0x1d` | new |
| the LFO page-range bounds widened to include `0x1d` | new |
| a 38th page descriptor, via a cave on the accessor | new |

Three new mechanisms, and they are **not separable**: records with no descriptor
draw nothing, a descriptor with no records has nothing to name, and neither is
reachable unless the range tests claim page `0x1d`. One question, three parts.

## The descriptor, and why a cave rather than a bigger table

`FUN_400c2474` maps a view id to `0x42432C00 + id*44`, bounded `id <= 36`. All
37 descriptors are live and the table that follows begins at `0x4243325C` with
**no slack**, so growing it means relocating 1,672 bytes (§5f).

A cave on the accessor is much smaller. It special-cases id 37 and falls through
to the stock arithmetic for everything else:

    movel %sp@(4),%d0
    cmpil #37,%d0
    bne   .stock
    lea   <descriptor 6>,%a0      | LFO3's, for its two string pointers
    lea   <ours>,%a1
    movel %a0@,%a1@
    movel %a0@(4),%a1@(4)
    movel %a1,%d0
    rts
    .stock:                       | cave replays the displaced bytes, jumps back

The two string pointers are copied **at runtime** because they are heap objects
the initialiser writes at boot (`0x401ce6d6` assigns them); they are not in the
image and cannot be written statically. The nine parameter ids *are* static, and
are ours.

## The columns

Read from the initialiser at `0x400c9958`-`0x400c99a8`, descriptor 6 (LFO3) is:

| column | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| LFO3 | 95 | 96 | 97 | 98 | 99 | 101 | 102 | 103 | **10** |

Nine columns for ten records -- **100 (`SLEW`) is skipped** -- and column 8 is
`10`, `Track Level`, a shared parameter rather than an LFO one. LFO4's
descriptor mirrors that shape exactly, with its own ids and the same column 8.

## What to look for

1. **It boots.**
2. **`[MOD]` cycles four pages.**
3. **The fourth page shows `LFO4`** and its own parameter names.
4. **Editing the fourth page still moves LFO3** -- expected, and the honest
   marker that v6 is still to come.
5. **The TRIG page still works** -- `NOTE VEL LEN uTM`, `Retrig`, `Euclidean`.
6. **LFO1-3 unchanged.**

Fails at 3 with a blank or garbled page -> the descriptor cave ran but its
contents are wrong. Fails at 3 with page four showing **LFO3's** parameters ->
the cave did not run, and `docs/code-caves.md`'s reachability check applies:
`FUN_400c2474` has 17 direct callers, so it is not a vtable-only function, but
that is an argument and not a measurement.

## Safety

Same-length edits throughout plus one cave in verified-free space. Every site is
asserted against its stock encoding. Reversible by reflashing stock.

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
from dnfw.patch.assemble import assemble, available
from dnfw.patch.cave import Cave, CaveHook, apply as cave_apply

MAIN_OS = 3
BASE = 0x40000400
RECORD = 60
TABLE = 0x401F7F94

F_PAGE_ID = 0x00
F_CC = 0x18
F_NRPN = 0x1C
F_MODMASK = 0x24
F_LONG = 0x28
F_PAGE_LABEL = 0x2C
F_SHORT = 0x30
F_HANDLER = 0x34

# --- part 1: the TRIG group off page 0x1d (proven, v3) ----------------------
TRIG_FROM, TRIG_TO = 0x1D, 0x1F
TRIG_NAMERS = [
    (0x400DC71E, "param_set_tables_build exact-match arm"),
    (0x400DBFA0, "TrigParameterSet ownership predicate"),
    (0x4003774E, "page-0x1d special case for ids 310/311"),
]
EXPECTED_TRIG = 22

# --- part 2: LFO4's records -------------------------------------------------
LFO3_IDS = list(range(95, 105))
LFO4_IDS = [1, 2, 3, 4, 5, 11, 12, 13, 14, 17]   # the dead ERR records
LFO4_PAGE = 0x1D
# NOT 0x4026EFF6. `scripts/build_lfo4_test.py` uses that address and calls it
# "16 zero bytes of unreferenced padding" -- true on 1.10E, **false on 1.11**,
# where it reads 4b fc 7e 00 45. The zero-check below caught it. This address is
# inside the same verified-free run as the id vector, past its 16 bytes.
LFO4_LABEL_VA = 0x402CF540
LFO3_DEST_MASK = 0x10000
LFO4_DEST_MASK = 0x8000

# --- part 3: the LFO page-range bounds -------------------------------------
# `(page - 26) <= 2` becomes `<= 3`, and the `page <= 28` bound becomes 29.
RANGE_EDITS = [
    (0x400DBF3A, bytes((0x70, 0x02)), bytes((0x70, 0x03)), "SoundParameterSet LFO range"),
    (0x400DC6B8, bytes((0x7C, 0x02)), bytes((0x7C, 0x03)), "param_set_tables_build LFO routing"),
    (0x4012A83A, bytes((0x72, 0x02)), bytes((0x72, 0x03)), "is_lfo_page helper"),
    (0x4012AF7C, bytes((0x7C, 0x02)), bytes((0x7C, 0x03)), "inlined is_lfo_page (getter side)"),
    (0x4012AFA6, bytes((0x7C, 0x02)), bytes((0x7C, 0x03)), "inlined is_lfo_page (setter side)"),
    (0x400DBE7C, bytes((0x72, 0x1C)), bytes((0x72, 0x1D)), "sound-side page<=0x1c bound"),
]

# --- part 4: navigation (proven, v4) ---------------------------------------
VECTOR_VA = 0x402CF52C
VECTOR = (4, 5, 6, 37)
POOL_OPERAND_VA = 0x40061564
POOL_STOCK = 0x401E0048
NAV_EDITS = [
    (0x40061558, bytes((0x72, 0x03)), bytes((0x72, 0x04)), "id-vector length"),
    (0x4010DBC6, bytes((0x72, 0x02)), bytes((0x72, 0x03)), "LFO-index clamp"),
]

# --- part 5: the 38th descriptor -------------------------------------------
DESC_TABLE = 0x42432C00
DESC_STRIDE = 44
DESC_LFO3 = DESC_TABLE + 6 * DESC_STRIDE      # 0x42432d08
OUR_DESC_VA = 0x402D0800                       # inside a verified-free run
CAVE_VA, CAVE_CAP = 0x402D0664, 320
ACCESSOR_VA = 0x400C2474
ACCESSOR_STOCK = bytes((0x72, 0x24, 0x20, 0x2F, 0x00, 0x04))   # moveq #36 ; movel sp@(4),d0

# LFO3's nine columns, read from the initialiser at 0x400c9958-0x400c99a8.
LFO3_COLUMNS = [95, 96, 97, 98, 99, 101, 102, 103, 10]

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/lfo4-page-test5_DN2_1.11.syx")


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found -- patch/assemble.py needs "
                         "m68k-linux-gnu-as (WSL is fine)")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    def rec(pid: int) -> int:
        return TABLE - BASE + pid * RECORD

    def field(pid: int, off: int) -> int:
        return struct.unpack_from(">I", content, rec(pid) + off)[0]

    def name(pid: int, off: int) -> str | None:
        return _cstr(content, field(pid, off) - BASE)

    _check_geometry(name, field)

    print("part 1 -- the TRIG group off page 0x%02x" % TRIG_FROM)
    movers = [i for i in range(321) if field(i, F_PAGE_ID) == TRIG_FROM]
    if len(movers) != EXPECTED_TRIG:
        raise SystemExit(f"page 0x{TRIG_FROM:02x} has {len(movers)} records, "
                         f"expected {EXPECTED_TRIG} -- refusing")
    for va, what in TRIG_NAMERS:
        _poke(content, va, bytes((0x72, TRIG_FROM)), bytes((0x72, TRIG_TO)), what)
    for i in movers:
        struct.pack_into(">I", content, rec(i) + F_PAGE_ID, TRIG_TO)
    print(f"  {len(movers)} records 0x{TRIG_FROM:02x} -> 0x{TRIG_TO:02x}")

    print("\npart 2 -- LFO4's ten records")
    _write_label(content)
    for tid, src in zip(LFO4_IDS, LFO3_IDS):
        if (name(tid, F_LONG), name(tid, F_SHORT)) != ("Error", "ERR"):
            raise SystemExit(f"id {tid} is not a dead ERR record -- refusing")
        clone = bytearray(content[rec(src):rec(src) + RECORD])
        is_dest = struct.unpack_from(">I", clone, F_MODMASK)[0] == LFO3_DEST_MASK
        struct.pack_into(">I", clone, F_PAGE_ID, LFO4_PAGE)
        struct.pack_into(">I", clone, F_CC, 0xFFFFFFFF)
        struct.pack_into(">I", clone, F_NRPN, 0xFFFFFFFF)
        struct.pack_into(">I", clone, F_PAGE_LABEL, LFO4_LABEL_VA)
        struct.pack_into(">I", clone, F_MODMASK,
                         LFO4_DEST_MASK if is_dest else 0)
        content[rec(tid):rec(tid) + RECORD] = clone
    print(f"  ids {LFO4_IDS} cloned from {LFO3_IDS[0]}-{LFO3_IDS[-1]}, "
          f"page 0x{LFO4_PAGE:02x}, label 'LFO4'")

    print("\npart 3 -- widen the LFO page range")
    for va, stock, new, what in RANGE_EDITS:
        _poke(content, va, stock, new, what)

    print("\npart 4 -- navigation")
    for va, stock, new, what in NAV_EDITS:
        _poke(content, va, stock, new, what)
    at = POOL_OPERAND_VA - BASE
    if struct.unpack_from(">I", content, at)[0] != POOL_STOCK:
        raise SystemExit("the id-vector pointer is not stock -- refusing")
    struct.pack_into(">I", content, at, VECTOR_VA)
    _require_zero(content, VECTOR_VA, len(VECTOR) * 4, "id vector")
    for i, v in enumerate(VECTOR):
        struct.pack_into(">I", content, VECTOR_VA - BASE + i * 4, v)
    print(f"  0x{VECTOR_VA:08x}  vector = {{{', '.join(map(str, VECTOR))}}}")

    print("\npart 5 -- the 38th descriptor")
    _write_descriptor(content)
    payload = assemble(_cave_source())
    hook = CaveHook(id="lfo4-descriptor", site=ACCESSOR_VA, stock=ACCESSOR_STOCK,
                    payload=payload, cave=Cave(CAVE_VA, CAVE_CAP))
    content = bytearray(cave_apply(_as_image(section, content), hook))
    print(f"  cave at 0x{CAVE_VA:08x}, {len(payload)} bytes of payload, "
          f"hooked at 0x{ACCESSOR_VA:08x}")

    replacement = compress(section.id, section.dest, bytes(content))
    syx = fwbuild.build(firmware, {MAIN_OS: replacement})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(syx)
    print(f"\nwrote {OUT}  ({len(syx):,} bytes)")
    print(f"  sha256 {hashlib.sha256(syx).hexdigest()}")
    print("\nVerify before flashing:  dnfw inspect", OUT)
    return 0


def _cave_source() -> str:
    """The accessor detour: id 37 -> our descriptor, everything else falls through.

    `rts` on the id-37 path returns straight to the accessor's caller; the
    fall-through path leaves %d0 clobbered, which is harmless because the cave
    replays `movel %sp@(4),%d0` before jumping back.
    """
    return f"""
        move.l   4(%sp),%d0
        cmpi.l   #37,%d0
        bne.s    1f
        lea      0x{DESC_LFO3:08x},%a0
        lea      0x{OUR_DESC_VA:08x},%a1
        move.l   (%a0),(%a1)
        move.l   4(%a0),4(%a1)
        move.l   %a1,%d0
        rts
    1:
    """


def _write_descriptor(content: bytearray) -> None:
    """Our 44-byte descriptor: two strings filled at runtime, nine static ids."""
    _require_zero(content, OUR_DESC_VA, DESC_STRIDE, "descriptor 37")
    columns = [LFO4_IDS[LFO3_IDS.index(c)] if c in LFO3_IDS else c
               for c in LFO3_COLUMNS]
    at = OUR_DESC_VA - BASE
    struct.pack_into(">II", content, at, 0, 0)          # strings, filled by the cave
    for i, pid in enumerate(columns):
        struct.pack_into(">I", content, at + 8 + i * 4, pid)
    print(f"  0x{OUR_DESC_VA:08x}  columns = {columns}")
    print(f"       (LFO3's were {LFO3_COLUMNS}; column 8 is Track Level, shared)")


def _write_label(content: bytearray) -> None:
    _require_zero(content, LFO4_LABEL_VA, 5, "LFO4 page label")
    at = LFO4_LABEL_VA - BASE
    content[at:at + 5] = b"LFO4\x00"


def _require_zero(content: bytearray, va: int, n: int, what: str) -> None:
    at = va - BASE
    span = bytes(content[at:at + n])
    if span != b"\x00" * n:
        raise SystemExit(f"0x{va:08x} ({what}) is not {n} zero bytes "
                         f"({span.hex()}) -- refusing to overwrite live data")


def _poke(content: bytearray, va: int, stock: bytes, new: bytes, what: str) -> None:
    at = va - BASE
    got = bytes(content[at:at + len(stock)])
    if got != stock:
        raise SystemExit(f"site 0x{va:08x} ({what}) is {got.hex()}, expected "
                         f"{stock.hex()} -- refusing to write")
    content[at:at + len(new)] = new
    print(f"  0x{va:08x}  {got.hex()} -> {new.hex()}   {what}")


def _as_image(section, content: bytearray):
    """Wrap the edited bytes so patch/cave.py can apply a hook to them."""
    from dnfw.image.coldfire import LoadedImage
    return LoadedImage(dest=section.dest, content=bytes(content))


def _check_geometry(name, field) -> None:
    for pid, off, expected in [
        (6, F_LONG, "Machine Type"), (10, F_LONG, "Track Level"),
        (84, F_PAGE_LABEL, "LFO1"), (104, F_PAGE_LABEL, "LFO3"),
    ]:
        got = name(pid, off)
        if got != expected:
            raise SystemExit(f"geometry: id {pid} +0x{off:02x} is {got!r}, "
                             f"expected {expected!r}")
    for pid, page in ((75, 0x1A), (85, 0x1B), (95, 0x1C)):
        if field(pid, F_PAGE_ID) != page:
            raise SystemExit(f"geometry: id {pid} is not on page 0x{page:02x}")
    print("geometry: parameter table resolves as expected\n")


def _cstr(buf: bytes, off: int) -> str | None:
    end = buf.find(b"\x00", off, off + 40)
    if end < 0:
        return None
    s = buf[off:end]
    return s.decode() if s and all(0x20 <= c < 0x7F for c in s) else None


if __name__ == "__main__":
    raise SystemExit(main())

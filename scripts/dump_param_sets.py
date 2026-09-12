"""Reconstruct the runtime ParameterSet slot tables from the parameter table.

The DN2 builds its `ParameterSet` slot->id maps at boot rather than shipping
them: `param_set_tables_build` (1.11 `0x400dc4d0`) walks all 320 parameter
records and files each id into one of six BSS tables at `0x42c6xxxx`, choosing
the table by the record's **page id** (`record+0x00`) and the slot by its
**index within the page** (`record+0x04`).

That is why the tables could not be found in the image: they do not exist until
the firmware constructs them. `docs/parameter-set-tables.md` is the full
reading, including the disassembly this reimplements.

This script re-runs that construction offline, so the claim is reproducible
against any image rather than asserted from a one-time disassembly. It prints
each set's occupancy and, with `--table sound|midi|fx`, the slot-by-slot
contents with parameter names.

What it is good for: seeing which slots are free before proposing to move a
parameter between sets, and checking that a build script's edits land where
intended. `scripts/build_moddest_expand.py` established that enumeration -- not
the modulation mask -- is what keeps FX and Master parameters out of the LFO
destination list; this shows the enumeration itself.

No firmware bytes live in this repository: the records are read from the user's
own local image at run time.
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.firmware.load import load

MAIN_OS = 3
BASE = 0x40000400
RECORD = 60
N_RECORDS = 320

# record(id) = ACCESSOR_BASE + id*60, keyed by decoded MAIN OS size so the
# script refuses an image it has not been anchored against.
ACCESSOR_BASE = {
    3_085_696: 0x401E29A0,  # DN2 1.10E
    3_192_192: 0x401F7F94,  # DN2 1.11
}

F_PAGE_ID = 0x00
F_INDEX = 0x04
F_MODMASK = 0x24
F_LONG = 0x28
F_PAGE = 0x2C
F_SHORT = 0x30

SLOTS = 101  # every 101-entry table; the destination builder walks 0..0x64

STOCK = {
    "1.10E": "00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip",
    "1.11": "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip",
}


class Records:
    """The 320 parameter records, read by field."""

    def __init__(self, content: bytes, accessor_base: int) -> None:
        self._c = content
        self._origin = accessor_base - BASE

    def field(self, param_id: int, off: int) -> int:
        return struct.unpack_from(">I", self._c, self._origin + param_id * RECORD + off)[0]

    def name(self, param_id: int, off: int) -> str | None:
        ptr = self.field(param_id, off)
        if not BASE <= ptr < BASE + len(self._c):
            return None
        start = ptr - BASE
        end = self._c.find(b"\x00", start, start + 40)
        if end < 0:
            return None
        s = self._c[start:end]
        return s.decode() if s and all(0x20 <= c < 0x7F for c in s) else None


def is_sound_param(r: Records, param_id: int) -> bool:
    """1.11 `0x400dbd0c`. An exclusion list; returns True to include."""
    page = r.field(param_id, F_PAGE_ID)
    if (page - 17) & 0xFFFFFFFF <= 8 and (1 << ((page - 17) & 0xFFFFFFFF)) & 0x1F3:
        return False
    if param_id in (84, 94, 104):
        return False
    if param_id > 84:
        return True
    return not 28 <= param_id <= 31


def is_midi_param(r: Records, param_id: int) -> bool:
    """1.11 `0x400dbd7c`. Same shape, different exclusions."""
    page = r.field(param_id, F_PAGE_ID)
    if (page - 11) & 0xFFFFFFFF <= 10 and (1 << ((page - 11) & 0xFFFFFFFF)) & 0x4C7:
        return False
    return param_id not in (20, 26, 76, 86, 96)


def build_tables(r: Records) -> dict[str, dict[int, int]]:
    """Re-run `param_set_tables_build` over every record.

    Every range test below is unsigned, matching the `bcs`/`bhi` the compiler
    emitted -- reading them as signed puts pages in the wrong sets.
    """
    sound: dict[int, int] = {}
    midi: dict[int, int] = {}
    fx: dict[int, int] = {}
    machine: dict[int, int] = {}
    filt: dict[int, int] = {}

    for param_id in range(1, N_RECORDS + 1):
        page = r.field(param_id, F_PAGE_ID)
        idx = r.field(param_id, F_INDEX)
        if page <= 4:
            machine[page * 40 + idx - 25] = param_id
        elif (page - 5) & 0xFFFFFFFF <= 5:
            # the filter *type* is `page - 5`; the reader keys on type, not page
            filt[(page - 5) * 3 + idx - 66] = param_id
        elif (page - 11) & 0xFFFFFFFF <= 4:
            if is_sound_param(r, param_id):
                sound[idx] = param_id
        elif (page - 16) & 0xFFFFFFFF <= 5:
            fx[idx] = param_id
        elif (page - 22) & 0xFFFFFFFF <= 3:
            midi[idx] = param_id
        elif (page - 26) & 0xFFFFFFFF <= 2:
            if is_sound_param(r, param_id):
                sound[idx] = param_id
            if is_midi_param(r, param_id):
                midi[idx] = param_id
        # pages 29, 30 and 0xffffffff are enumerated by nothing

    return {"sound": sound, "midi": midi, "fx": fx, "machine": machine, "filter": filt}


def _runs(values: list[int]) -> str:
    """Compress a sorted slot list into ranges, so holes are readable."""
    if not values:
        return "(none)"
    out, start, prev = [], values[0], values[0]
    for v in values[1:]:
        if v != prev + 1:
            out.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = v
        prev = v
    out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", nargs="?", help="firmware .syx or _dist.zip")
    ap.add_argument("--version", choices=sorted(STOCK), default="1.11",
                    help="use the recorded stock path for this build (default 1.11)")
    ap.add_argument("--table", choices=("sound", "midi", "fx", "machine", "filter"),
                    help="also print this table slot by slot")
    args = ap.parse_args()

    path = pathlib.Path(args.image) if args.image else pathlib.Path(STOCK[args.version])
    if not path.exists():
        raise SystemExit(f"{path} not found")

    content = load(read_image(path)).container.find(MAIN_OS).unpack()
    accessor_base = ACCESSOR_BASE.get(len(content))
    if accessor_base is None:
        raise SystemExit(
            f"MAIN OS is {len(content):,} bytes -- no parameter-table anchor is "
            f"recorded for this build (docs/version-anchors.md)."
        )

    r = Records(content, accessor_base)
    _check_geometry(r)
    tables = build_tables(r)

    print(f"{path.name}  MAIN OS {len(content):,} B  table at 0x{accessor_base:08x}\n")
    widths = {"sound": SLOTS, "midi": SLOTS, "fx": SLOTS, "machine": 200, "filter": 18}
    print(f"{'set':<9} {'used':>5} {'of':>5}   free slots")
    for name, t in tables.items():
        width = widths[name]
        free = [s for s in range(width) if s not in t]
        print(f"{name:<9} {len(t):5d} {width:5d}   {_runs(free)}")

    if args.table:
        t = tables[args.table]
        print(f"\n{args.table} table, slot by slot")
        for slot in sorted(t):
            pid = t[slot]
            print(f"  {slot:3d}  id {pid:3d}  {r.name(pid, F_PAGE) or '-':<11s} "
                  f"{r.name(pid, F_SHORT) or '-':<6s} {r.name(pid, F_LONG) or '-':<24s} "
                  f"mask 0x{r.field(pid, F_MODMASK):05x}")
    return 0


def _check_geometry(r: Records) -> None:
    """Refuse to run unless the record layout resolves the way it should.

    Same guard as the build scripts, and for the same reason: a wrong anchor
    into a dense table still yields plausible strings. See
    docs/lfo4-feasibility.md, "The Stage 1 corrections".
    """
    for param_id, off, expected in [
        (6, F_LONG, "Machine Type"),
        (10, F_LONG, "Track Level"),
        (84, F_PAGE, "LFO1"),
        (104, F_PAGE, "LFO3"),
    ]:
        got = r.name(param_id, off)
        if got != expected:
            raise SystemExit(
                f"geometry check failed: id {param_id} field +0x{off:02x} is "
                f"{got!r}, expected {expected!r}"
            )


if __name__ == "__main__":
    raise SystemExit(main())

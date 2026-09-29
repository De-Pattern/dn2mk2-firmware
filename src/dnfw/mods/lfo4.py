"""A fourth LFO: a fourth page under `[MOD]` that behaves like LFO1-3.

**Passed on the instrument** (`docs/lfo4-build-plan.md`): the page opens with
the stock LFO controls, its `DEST` browser works, it modulates on every voice,
and its settings are kept by an explicit SAVE PROJECT and survive a power-cycle
without one.

## What it is

C, in `csrc/lfo4/`, compiled and linked by `scripts/build_lfo4_browser.py`
into a chunk the start-up loader copies to RAM, plus the in-image edits that
reach it: the parameter table moved to make room for ten records, the page
list, the four hook sites into the C, and the engine stubs. The C remains the
source. `scripts/gen_lfo4_code.py` runs that build and records what it changed
(`lfo4_code.json`), and checks that this mod applied to stock reproduces the
build **byte for byte**, so what applies here is exactly what was gated.

## What does not ship

The relocated parameter table is 320 stock records followed by LFO4's ten,
which are LFO3's with five fields rewritten. None of it is in the JSON: it is
rebuilt at apply time from the image being modified, through the same library
functions the build uses. A mod applied earlier that edits the stock table
(`moddest` opens thirteen masks there) is therefore carried into the
relocated copy -- **provided it is applied first**, which is why the CLI
applies this mod last.

## What it shares

The start-up loader and the appended area are the platform's
(`dnfw.mods.platform`): LFO4 contributes its two `CODE` chunks to whatever
area is already there, so it combines with `lfowaves` and `bootscreen`. The
JSON still records the loader as LFO4's build installed it;
`scripts/gen_platform_code.py` checks the platform installs those same bytes.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result, platform
from ..patch import lfo4records, paramtable

ID = "lfo4"
NAME = "A fourth LFO"
SUMMARY = ("A fourth LFO page under [MOD], like LFO1-3: modulates on every voice, "
           "kept by a save and across a power-cycle.")
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
APPLY_LAST = True                  # it copies the stock table: see the docstring

# What this mod copies out of the image, so a mod that edits it must come
# first: its edit would otherwise land on a table nothing reads any more.
COPIES = [Extent(SECTION, paramtable.TABLE - BASE, paramtable.RECORD * paramtable.COUNT,
                 "the stock parameter table, copied into the appended area")]

_CODE = pathlib.Path(__file__).with_name("lfo4_code.json")
SPEC = json.loads(_CODE.read_text()) if _CODE.exists() else None


def _spec() -> dict:
    if SPEC is None:
        raise ModError("lfo4_code.json is missing: run scripts/gen_lfo4_code.py")
    return SPEC


def _platform_owned(e: dict) -> bool:
    """An edit the platform makes: the start-up call or the loader in its cave."""
    lo, hi = e["va"] - BASE, e["va"] - BASE + len(e["new"]) // 2
    return any(x.start < hi and lo < x.end for x in platform.extents())


def _edits() -> list[dict]:
    return [e for e in _spec()["edits"] if not _platform_owned(e)]


def _chunks(blob: bytes) -> list[tuple[bytes, bytes]]:
    return platform.area.parse(blob)


def extents(firmware=None) -> list[Extent]:
    spec = _spec()
    out = [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, "LFO4 edit") for e in _edits()]
    return out + platform.extents(len(spec["blob"]) // 2)


def ram() -> list[Extent]:
    out = []
    for _, data in _chunks(bytes.fromhex(_spec()["blob"])):
        code = platform.area.CodeChunk.unpack(data)
        out.append(Extent(platform.RAM, code.load, len(code.image) + code.bss,
                          "LFO4's C and its BSS" if code.bss else "the relocated parameter table"))
    return out


def _table(content: bytes) -> bytes:
    """The relocated table, from this image: its 320 records and LFO4's ten."""
    spec = _spec()
    name_va = spec["table_va"] + paramtable.RECORD * spec["table_records"]
    return (paramtable.records(content, BASE)
            + lfo4records.build(content, BASE, page_name_va=name_va))


def compose(content: bytes) -> bytes:
    """Stock-guarded edits, then the appended area with the table filled in."""
    spec = _spec()
    content, others = platform.split(content)
    out = bytearray(content)
    others = list(others)
    for e in _edits():
        platform.write(out, others, e["va"], bytes.fromhex(e["stock"]), bytes.fromhex(e["new"]))

    blob = bytearray.fromhex(spec["blob"])
    records = _table(content)
    at = spec["table_offset"]
    if any(blob[at:at + len(records)]):
        raise ModError("lfo4_code.json is damaged: the table's place is not blank")
    blob[at:at + len(records)] = records

    return platform.join(bytes(out), others + _chunks(bytes(blob)))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    content = compose(section.unpack())
    spec = _spec()
    notes = [f"{len(_edits())} edits, {len(spec['blob']) // 2:,} B of CODE chunks in the "
             f"platform's area; the parameter table rebuilt from this image; MAIN OS {len(content):,} B"]
    return Result({SECTION: content}, extents(firmware), notes)

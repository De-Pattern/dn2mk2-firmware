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

It uses the start-up hook and the appended data area, like `lfowaves` and
`bootscreen`, and requires MAIN OS to end where stock 1.11 ends. So it
cannot be combined with either of them yet: `docs/mods-compatibility.md`.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result
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


def extents(firmware=None) -> list[Extent]:
    spec = _spec()
    out = [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, "LFO4 edit") for e in spec["edits"]]
    out.append(Extent(SECTION, spec["area_va"] - BASE, len(spec["blob"]) // 2,
                      "appended data area (loader, LFO4's C, the relocated table)"))
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
    if len(content) != spec["stock_length"]:
        raise ModError(f"MAIN OS is {len(content):,} B, not {spec['stock_length']:,}: either not "
                       "Digitone II 1.11, or another mod has already appended data "
                       "(lfowaves and bootscreen do)")
    for e in spec["edits"]:
        at = e["va"] - BASE
        have = bytes(content[at:at + len(e["stock"]) // 2]).hex()
        if have != e["stock"]:
            raise ModError(f"0x{e['va']:08x} is not stock ({have[:24]}...); another mod "
                           "has changed it, or this is not Digitone II 1.11")

    blob = bytearray.fromhex(spec["blob"])
    records = _table(content)
    at = spec["table_offset"]
    if any(blob[at:at + len(records)]):
        raise ModError("lfo4_code.json is damaged: the table's place is not blank")
    blob[at:at + len(records)] = records

    out = bytearray(content)
    for e in spec["edits"]:
        at = e["va"] - BASE
        new = bytes.fromhex(e["new"])
        out[at:at + len(new)] = new
    return bytes(out + blob)


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    content = compose(section.unpack())
    spec = _spec()
    notes = [f"{len(spec['edits'])} edits, appended {len(spec['blob']) // 2:,} B; "
             f"the parameter table rebuilt from this image; MAIN OS {len(content):,} B"]
    return Result({SECTION: content}, extents(firmware), notes)

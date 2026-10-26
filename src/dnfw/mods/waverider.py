"""Our machines and filters (the mod is still called `waverider`, its first machine).

**Since v0.11 machine type 5 is PERC** (docs/perc.md): the owner's 24 drum machines
(TRX, EFM, GND, from his Ravel firmware), one a track, chosen with TYPE; Waverider, the
wavetable machine that held type 5 until v0.10, is gone. Also: RESONATOR (type 6,
docs/rings.md), CZ (type 7, docs/cz.md), and the filters PING, SHFT and GRAN (types 6-8,
docs/ping.md, docs/shft.md, docs/gran.md).

## How it applies

Two sections, both from committed data:

- **MAIN OS (3):** `waverider_code.json`, written by `scripts/gen_waverider_code.py`
  from `dnfw.waverider.coldfire` (the MACHINE SEL list, the names, the permission rows,
  the WaveTone clone, our SYN pages). Every edit's stock bytes are checked first; the
  pages, the machines' tables and PING's lists run from RAM as platform `CODE` chunks.
- **The DSP boot stream (7):** `dnfw.waverider.dsp.section7`, from the committed SHARC
  objects. It refuses a section 7 that is not stock.

## A sound or project saved with one of our machines

Saved as its machine type by the stock SAVE. This build keeps 5-7 on LOAD; stock
firmware (and any build without this mod) loads them as **FM Tone**, the stock LOAD
bound's own fallback (`0x400dd286`), with their parameters as they were. A sound saved
with Waverider (type 5) on v0.10 or earlier loads as PERC here, its WaveTone values
read as PERC's controls.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform
from ..waverider import dsp

ID = "waverider"
NAME = "PERC, RESONATOR and CZ machines; PING, SHFT and GRAN filters"
SUMMARY = ("PERC (24 drum machines, type 5), RESONATOR and CZ in MACHINE SEL; PING, SHFT "
           "and GRAN in the filter list. Modified DSP code.")
DEVICE = 0x15                      # Digitone II
MAIN_OS, DSP_STREAM = 3, 7
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("waverider_code.json")).read_text())


def extents(firmware=None, area_length: int = 0) -> list[Extent]:
    out = [Extent(MAIN_OS, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]
    out += platform.extents(area_length)
    size = None
    if firmware is not None:
        section = firmware.container.find(DSP_STREAM)
        content = section.unpack() if section is not None else None
        size = len(content) if content is not None else None
    # The boot stream is rebuilt as a whole (blocks inserted before its final
    # block), so the whole of it is declared: nothing else may write it too.
    out.append(Extent(DSP_STREAM, 0, size or 836_956,
                      "the DSP boot stream, rebuilt: our code and state in L1 block 1, "
                      "PERC's code in L2, tables in DDR, the entry jump, the machine lookup"))
    return out


def _chunks() -> list[tuple[int, bytes, str]]:
    out = [(SPEC["chunk"]["load"], bytes.fromhex(SPEC["chunk"]["code"]),
            "our machines' SYN pages: code, descriptors, labels")]
    if "c_chunk" in SPEC:
        out.append((SPEC["c_chunk"]["load"], bytes.fromhex(SPEC["c_chunk"]["code"]),
                    "our machines' page renderer (csrc/waverider/page.c)"))
    if "machines_chunk" in SPEC:
        out.append((SPEC["machines_chunk"]["load"], bytes.fromhex(SPEC["machines_chunk"]["code"]),
                    "the machine shims, names, attributes and MACHINE SEL list (PERC, RESONATOR, CZ)"))
    if "ping_chunk" in SPEC:
        out.append((SPEC["ping_chunk"]["load"], bytes.fromhex(SPEC["ping_chunk"]["code"]),
                    "PING's FLTR-list shims, list and names (P2)"))
    md = _md_ui()
    if md is not None:
        out.append(md)
    out.append(_tables())
    return out


def _tables() -> tuple[int, bytes, str]:
    """v0.26: the tables the ColdFire sends the DSP at power-on (csrc/sampler/link.c,
    K_TABLES): the Machinedrum's (and the Monomachine's) from the owner's own firmware
    files, read now (never committed): TABLE_MAGIC, the length, then the bytes."""
    import struct
    from ..md import core as md_core
    from ..sampler import machines as SM
    data = md_core.tables_bytes()
    if len(data) > SM.TABLE_ROOM - 512:
        raise ModError(f"the tables ({len(data):,} B) do not fit the DSP's table area")
    return (SM.TABLE_LOAD, struct.pack("<II", SM.TABLE_MAGIC, len(data)) + data,
            "the Machinedrum's and Monomachine's tables, sent to the DSP at power-on (v0.26)")


def _md_ui() -> tuple[int, bytes, str] | None:
    """v0.20: the Machinedrum's screen graphics for PERC's page (csrc/waverider/md_page.c),
    read from the owner's MD OS 1.63 now (dnfw.md.ui; never committed). Without it the page
    is drawn as before."""
    from ..md import rom as md_rom, ui as md_ui
    from ..waverider import pages
    if not md_rom.available():
        return None
    return (pages.MDUI_LOAD, md_ui.blob(),
            "the Machinedrum's knob, pointers, clip and fonts (read from your MD OS, v0.20)")


def ram() -> list[Extent]:
    from ..sampler import machines as SM
    return ([Extent(RAM, load, len(code), what) for load, code, what in _chunks()]
            + [Extent(RAM, SM.MIRROR, SM.MIRROR_BYTES,
                      "the sample link's mirror of the pool (csrc/sampler/link.c, v0.14)")])


def _main_os(original: bytes) -> bytes:
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        at = g["va"] - BASE
        if original[at:at + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} ({g['what']}) is not stock; this mod is "
                           "for unmodified Digitone II 1.11")
    content = bytearray(original)
    for e in SPEC["edits"]:
        old, new = bytes.fromhex(e["stock"]), bytes.fromhex(e["new"])
        at = e["va"] - BASE
        if bytes(content[at:at + len(old)]) != old:
            raise ModError(f"0x{e['va']:08x} ({e['what']}) is not stock; this mod is for "
                           "unmodified Digitone II 1.11, or another mod already wrote there")
        content[at:at + len(new)] = new
    return bytes(content)


def apply(firmware) -> Result:
    cf = firmware.container.find(MAIN_OS)
    ds = firmware.container.find(DSP_STREAM)
    if cf is None or ds is None:
        raise ModError("image has no MAIN OS or no DSP boot stream")
    main_os, stream = cf.unpack(), ds.unpack()
    if main_os is None or stream is None:
        raise ModError("MAIN OS or the DSP boot stream did not depack")
    main_os, others = platform.split(main_os)
    try:
        section7 = dsp.section7(stream)
    except dsp.DspError as exc:
        raise ModError(f"the DSP boot stream: {exc}") from exc
    codes = [(platform.area.CODE, platform.area.CodeChunk(load, code).pack())
             for load, code, _ in _chunks()]
    content = platform.join(_main_os(main_os), others + codes)
    area_length = len(content) - platform.STOCK_LENGTH
    return Result(payloads={MAIN_OS: content, DSP_STREAM: section7},
                  extents=extents(firmware, area_length),
                  notes=[f"MACHINE SEL offers {SPEC['names'][0].upper()} after SWARMER "
                         f"(type {SPEC['new_type']}; WaveTone's pages)",
                         f"{len(SPEC['edits'])} edits in section 3, nothing appended; "
                         f"section 7 {len(stream):,} -> {len(section7):,} B"])

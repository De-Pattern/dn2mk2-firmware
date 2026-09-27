"""Waverider's DSP half: every edit Milestone 5 makes to section 7 (the SHARC boot
stream), applied from committed artefacts. `docs/waverider-m5-dsp.md` has the
evidence for each.

    section7(stock) -> the modified boot stream
    placements()    -> what goes where, for a report or a mod's extents

**What it does to DN2 1.11's section 7:**

1. **Adds boot blocks** in L1 block 2 (byte `0x300000`..), a block the stock
   stream loads nothing into, below its top 16 KB (left alone in case a cache is
   carved there; see the doc): `reader_m5.asm` (sw `0x180000`), `machine5_live.asm`
   (sw `0x180200`), a zero-filled state block (save area, counters, 16 reader
   blocks), the 129-entry increment table, the wavetable directory, and two
   original 16 x 512 int16 tables.
2. **Enters the type-5 loop**: the two instructions at sw `0x1c9448` (after the
   Swarmer render loop in `sw 0x1c8ef1`) become `JUMP 0x180200` and a 16-bit NOP;
   the loop re-executes them before it jumps back to `0x1c944c`.
3. **Lets a type-5 frame through**: the frame-nibble -> machine-type lookup
   `0x25d748[5]` becomes 5 (stock 0, FM Tone).

**What it does not do, on purpose:**

- It does **not** raise `min(R2, 4)` at `0x1c294c` (Milestones 3-4 did). Measured:
  that clamp's input is the frame's per-track field at offset `84 + 2t`, not the
  machine type, which reaches the record through the lookup alone.
- It does **not** touch the per-type setup table `0x8052db90`: the dispatch indexes
  it only after `compu(type, 5)`, so type 5 already takes the no-setup arm that
  MIDI's entry `[4]` also points to (`0x1c90d4`).

Every stock byte it replaces is checked first, and every added span is checked to
lie outside every block of the stock stream (loaded or filled). This module is pure:
bytes in, bytes out.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import struct

from ..image import bootstream, sharc_object
from . import harmonics, live, testtable
from . import render as reference

STOCK_SHA256 = "336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2"
LOAD_ALIAS = 0x28000000          # boot-stream load address = LOAD_ALIAS + DM byte address
CODE = pathlib.Path(__file__).with_name("sharc_code.json")

# L1 block 2 (DM byte addresses). Its top 16 KB (0x31c000..) is left untouched.
BLOCK2 = (0x300000, 0x31C000)
READER_SW = 0x180000
LOOP_SW = 0x180200
STATE_DM, STATE_BYTES = 0x301000, 0x400      # save area, counters, 16 reader blocks
READER_BLOCKS_DM, READER_BLOCK_BYTES = 0x301100, 32
INC_TABLE_DM = 0x301400
DIRECTORY_DM = 0x301800
DIRECTORY_MAGIC = 0x57525431                 # 'WRT1'
TABLES_DM = (0x302000, 0x306000)

# stock sites
ENTRY_SW = 0x1C9448                          # i5=dm(-0x18,i6); r10=dm(-0x22,i6)
ENTRY_STOCK = bytes.fromhex("089ce80a089c5e05")
NOP16 = bytes.fromhex("0100")                # the firmware's own 16-bit NOP (sw 0x1c9447)
LOOKUP_DM = 0x25D748                         # frame nibble -> machine type, 8 words
LOOKUP_STOCK = (0, 1, 2, 3, 4, 0, 0, 0)


class DspError(ValueError):
    pass


def tables() -> list[list[list[int]]]:
    """The two original tables, in slot order: 0 = a 32-harmonic saw darkening to a
    sine (`testtable`'s frames reversed), 1 = the overtone series (`harmonics`)."""
    return [list(reversed(testtable.table())), harmonics.table()]


def sw_to_load(sw: int) -> int:
    return LOAD_ALIAS + 2 * sw


def dm_to_load(dm: int) -> int:
    return LOAD_ALIAS + dm


def _code() -> dict:
    if not CODE.exists():
        raise DspError(f"{CODE.name} is missing: run scripts/gen_waverider_sharc.py")
    return json.loads(CODE.read_text(encoding="utf-8"))


def objects() -> dict[str, bytes]:
    """The committed SHARC objects, memory order: reader, loop, entry JUMP."""
    spec = _code()
    return {name: sharc_object.load_bytes(bytes.fromhex(spec[name]["object_parcels_be"]))
            for name in ("reader", "machine5_live", "entry_jump")}


def directory() -> bytes:
    return struct.pack("<II", DIRECTORY_MAGIC, len(TABLES_DM)) + struct.pack(
        "<%dI" % len(TABLES_DM), *TABLES_DM)


def spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of every block this adds, in stream order."""
    obj = objects()
    t = tables()
    return [
        ("reader_m5.asm (wr_render5)", sw_to_load(READER_SW), obj["reader"]),
        ("machine5_live.asm (wr_type5v)", sw_to_load(LOOP_SW), obj["machine5_live"]),
        ("state: save area, counters, 16 reader blocks (zeros)", dm_to_load(STATE_DM),
         bytes(STATE_BYTES)),
        ("increment table, 129 float32", dm_to_load(INC_TABLE_DM), live.table_bytes()),
        ("wavetable directory", dm_to_load(DIRECTORY_DM), directory()),
        ("table 0: saw -> sine (testtable reversed)", dm_to_load(TABLES_DM[0]),
         reference.dsp_bytes(t[0])),
        ("table 1: the overtone series (harmonics)", dm_to_load(TABLES_DM[1]),
         reference.dsp_bytes(t[1])),
    ]


def placements() -> list[dict]:
    out = [{"what": what, "load_address": f"{at:#010x}", "dm_byte": f"{at - LOAD_ALIAS:#08x}",
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
           for what, at, payload in spans()]
    obj = objects()
    out += [{"what": "patch: entry JUMP 0x180200 + NOP at sw 0x1c9448",
             "load_address": f"{sw_to_load(ENTRY_SW):#010x}",
             "bytes": len(obj["entry_jump"]) + len(NOP16),
             "stock": ENTRY_STOCK.hex(), "new": (obj["entry_jump"] + NOP16).hex()},
            {"what": "patch: machine lookup 0x25d748[5] 0 -> 5",
             "load_address": f"{dm_to_load(LOOKUP_DM + 20):#010x}", "bytes": 4,
             "stock": "00000000", "new": "05000000"}]
    return out


def _check_free(stock: bytes, span_list) -> None:
    blocks = [b for b in bootstream.walk(stock).blocks if b.count]
    for what, at, payload in span_list:
        lo, hi = at, at + len(payload)
        if not (dm_to_load(BLOCK2[0]) <= lo and hi <= dm_to_load(BLOCK2[1])):
            raise DspError(f"{what} at {lo:#x} leaves L1 block 2's lower 112 KB")
        for b in blocks:
            if b.target < hi and lo < b.target + b.count:
                raise DspError(f"{what} at {lo:#x}+{len(payload):#x} overlaps the stock "
                               f"block at {b.target:#x}+{b.count:#x}")
    ordered = sorted((at, at + len(p), w) for w, at, p in span_list)
    for (a0, a1, w0), (b0, b1, w1) in zip(ordered, ordered[1:]):
        if b0 < a1:
            raise DspError(f"{w0} and {w1} overlap")


def section7(stock: bytes) -> bytes:
    """DN2 1.11's section 7 -> Waverider's. Refuses anything else."""
    digest = hashlib.sha256(stock).hexdigest()
    if digest != STOCK_SHA256:
        raise DspError(f"section 7 sha256 {digest[:12]}... is not stock DN2 1.11's "
                       f"({STOCK_SHA256[:12]}...)")
    obj = objects()
    entry = obj["entry_jump"] + NOP16
    if len(entry) != len(ENTRY_STOCK):
        raise DspError(f"the entry patch is {len(entry)} bytes, not {len(ENTRY_STOCK)}")
    if bootstream.read_span(stock, sw_to_load(ENTRY_SW), len(ENTRY_STOCK)) != ENTRY_STOCK:
        raise DspError("sw 0x1c9448 is not the stock `i5=dm(-0x18,i6); r10=dm(-0x22,i6)`")
    lookup = struct.unpack("<8I", bootstream.read_span(stock, dm_to_load(LOOKUP_DM), 32))
    if lookup != LOOKUP_STOCK:
        raise DspError(f"the machine lookup is {lookup}, not stock {LOOKUP_STOCK}")
    added = spans()
    _check_free(stock, added)

    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(bootstream.block(at, payload) for _, at, payload in added)))
    bootstream.write_span(out, sw_to_load(ENTRY_SW), entry)
    bootstream.write_span(out, dm_to_load(LOOKUP_DM + 20), struct.pack("<I", 5))
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise DspError(f"the result does not walk as a boot stream ({walked.reason})")
    return result

"""Waverider's DSP half: every edit Milestone 5 makes to section 7 (the SHARC boot
stream), applied from committed artefacts. `docs/waverider-m5-dsp.md` has the
evidence for each.

    section7(stock) -> the modified boot stream
    section7_idle_only(stock) -> stock plus the idle-time stub alone (patch 4), for
                       measuring the stock engine with nothing of Waverider in it
    placements()    -> what goes where, for a report or a mod's extents

**What it does to DN2 1.11's section 7:**

1. **Adds boot blocks** in L1 block 1's free tail, byte `0x2dd600..0x2e7000`
   (Milestone 5c; M5 used L1 block 2, which silenced the instrument --
   `docs/waverider-dsp-silence.md`): `reader_m5.asm` (sw `0x16eb00`),
   `machine5_live.asm` (sw `0x16ed00`), a zeroed state block (save area, counters,
   16 reader blocks), the 129-entry increment table, the wavetable directory, and
   two original 16 x 512 int16 tables. Every payload is zero-padded to the next
   span, so the region is written end to end: each code span has >= 64 bytes of
   zeros (NOPs) after it and no byte of the region is left unwritten.
2. **Enters the type-5 loop**: the two instructions at sw `0x1c9448` (after the
   Swarmer render loop in `sw 0x1c8ef1`) become `JUMP 0x16f600` and a 16-bit NOP.
   `block_count.asm` there counts the block into reply word 2 and jumps to the loop
   at `0x16ed00`, which re-executes the two instructions before it jumps back to
   `0x1c944c`. (Until the block counter, the JUMP went straight to `0x16ed00`.)
3. **Lets a type-5 frame through**: the frame-nibble -> machine-type lookup
   `0x25d748[5]` becomes 5 (stock 0, FM Tone).
4. **Times the idle task** (`idle_load.asm`, sw `0x16f500`): the back edge of
   FreeRTOS's idle loop, `jump (pc,-0x10)` at sw `0xb88abb` in L2, becomes
   `JUMP 0x16f500`; the stub adds the idle task's own cycles to a running total in
   reply word 1 and jumps back to `0xb88aab`. The SHARC's load is then
   1 - idle / elapsed (`docs/sharc-load.md`).

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

# L1 block 1's free tail (DM byte addresses). Block 1 is 0x2c0000..0x2f0000; the
# stock stream's last byte in it is 0x2dd52c, and the startup enables the DM cache,
# which is carved from the top of block 1 (16 KB at size code 0, the size the
# startup writes; see docs/waverider-dsp-silence.md). REGION ends 36 KB below the
# block's top, so it stays clear of a 16 KB or a 32 KB DM cache.
REGION = (0x2DD600, 0x2E7000)
STOCK_BLOCK1_END = 0x2DD52C
DM_CACHE_32K = 0x2E8000                      # the lowest byte a 32 KB DM cache would own
CODE_SPAN = 0x400                            # each code object is padded to this
READER_DM = 0x2DD600
LOOP_DM = 0x2DDA00
READER_SW = READER_DM // 2                   # 0x16eb00
LOOP_SW = LOOP_DM // 2                       # 0x16ed00
STATE_DM, STATE_BYTES = 0x2DDE00, 0x400      # save area, counters, 16 reader blocks
READER_BLOCKS_DM, READER_BLOCK_BYTES = 0x2DDF00, 32
INC_TABLE_DM = 0x2DE200
DIRECTORY_DM = 0x2DE600
DIRECTORY_MAGIC = 0x57525431                 # 'WRT1'
TABLES_DM = (0x2DF000, 0x2E3000)

IDLE_DM = 0x2DEA00                           # idle_load.asm, in the gap before table 0
IDLE_SW = IDLE_DM // 2                       # 0x16f500
IDLE_STATE_DM = 0x2DE100                     # its save area and counters (state block tail)
COUNT_DM = 0x2DEC00                          # block_count.asm, after idle_load.asm
COUNT_SW = COUNT_DM // 2                     # 0x16f600: the entry JUMP's target
EMARK_DM = 0x2DED00                          # entry_mark.asm: EMUCLK as the handler calls 0x1c2712
EMARK_SW = EMARK_DM // 2                     # 0x16f680
L2_LOAD, L2_SW = 0x20000000, 0xB80000        # L2 code: load address 0x20000000 is sw 0xb80000

# stock sites
ENTRY_SW = 0x1C9448                          # i5=dm(-0x18,i6); r10=dm(-0x22,i6)
ENTRY_STOCK = bytes.fromhex("089ce80a089c5e05")
NOP16 = bytes.fromhex("0100")                # the firmware's own 16-bit NOP (sw 0x1c9447)
LOOKUP_DM = 0x25D748                         # frame nibble -> machine type, 8 words
LOOKUP_STOCK = (0, 1, 2, 3, 4, 0, 0, 0)
IDLE_SITE_SW = 0xB88ABB                      # prvIdleTask's back edge: jump (pc,-0x10)
IDLE_SITE_STOCK = bytes.fromhex("3e07ff00f0ff")
IDLE_RETURN_SW = 0xB88AAB                    # the loop's top: call prvCheckTasksWaitingTermination
CALL_SITE_SW = 0x1C9FB9                      # the handler's `r4 = 0x268438` before `cjump 0x1c2712`
CALL_SITE_STOCK = bytes.fromhex("040f26003884")


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


def l2_sw_to_load(sw: int) -> int:
    return L2_LOAD + 2 * (sw - L2_SW)


def _code() -> dict:
    if not CODE.exists():
        raise DspError(f"{CODE.name} is missing: run scripts/gen_waverider_sharc.py")
    return json.loads(CODE.read_text(encoding="utf-8"))


def objects() -> dict[str, bytes]:
    """The committed SHARC objects: reader, loop, entry JUMP, idle stub, idle JUMP."""
    spec = _code()
    return {name: sharc_object.load_bytes(bytes.fromhex(spec[name]["object_parcels_be"]))
            for name in ("reader", "machine5_live", "entry_jump", "idle_load", "idle_jump", "block_count",
                         "entry_mark", "emark_jump")}


def directory() -> bytes:
    return struct.pack("<II", DIRECTORY_MAGIC, len(TABLES_DM)) + struct.pack(
        "<%dI" % len(TABLES_DM), *TABLES_DM)


def spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of every block this adds, in stream order.

    Each payload is zero-padded up to the next span's start (the last to REGION's
    end), so the region is written end to end and every code object is followed by
    at least 64 bytes of zeros (a zero word is a NOP)."""
    obj = objects()
    t = tables()
    raw = [
        ("reader_m5.asm (wr_render5)", READER_DM, obj["reader"]),
        ("machine5_live.asm (wr_type5v)", LOOP_DM, obj["machine5_live"]),
        ("state: save area, counters, 16 reader blocks (zeros)", STATE_DM, bytes(STATE_BYTES)),
        ("increment table, 129 float32", INC_TABLE_DM, live.table_bytes()),
        ("wavetable directory", DIRECTORY_DM, directory()),
        ("idle_load.asm (wr_idle)", IDLE_DM, obj["idle_load"]),
        ("block_count.asm (wr_count)", COUNT_DM, obj["block_count"]),
        ("entry_mark.asm (wr_emark)", EMARK_DM, obj["entry_mark"]),
        ("table 0: saw -> sine (testtable reversed)", TABLES_DM[0], reference.dsp_bytes(t[0])),
        ("table 1: the overtone series (harmonics)", TABLES_DM[1], reference.dsp_bytes(t[1])),
    ]
    out = []
    for k, (what, at, payload) in enumerate(raw):
        end = raw[k + 1][1] if k + 1 < len(raw) else REGION[1]
        if len(payload) > end - at:
            raise DspError(f"{what} ({len(payload)} bytes) does not fit before {end:#x}")
        if "asm" in what and end - at - len(payload) < 64:
            raise DspError(f"{what} leaves fewer than 64 bytes of NOP padding")
        out.append((what, dm_to_load(at), payload + bytes(end - at - len(payload))))
    return out


def placements() -> list[dict]:
    out = [{"what": what, "load_address": f"{at:#010x}", "dm_byte": f"{at - LOAD_ALIAS:#08x}",
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
           for what, at, payload in spans()]
    obj = objects()
    out += [{"what": f"patch: entry JUMP {COUNT_SW:#x} (the block counter, then the loop) + NOP at sw 0x1c9448",
             "load_address": f"{sw_to_load(ENTRY_SW):#010x}",
             "bytes": len(obj["entry_jump"]) + len(NOP16),
             "stock": ENTRY_STOCK.hex(), "new": (obj["entry_jump"] + NOP16).hex()},
            {"what": "patch: machine lookup 0x25d748[5] 0 -> 5",
             "load_address": f"{dm_to_load(LOOKUP_DM + 20):#010x}", "bytes": 4,
             "stock": "00000000", "new": "05000000"},
            {"what": f"patch: the idle loop's back edge at sw {IDLE_SITE_SW:#x} -> JUMP {IDLE_SW:#x}",
             "load_address": f"{l2_sw_to_load(IDLE_SITE_SW):#010x}", "bytes": len(obj["idle_jump"]),
             "stock": IDLE_SITE_STOCK.hex(), "new": obj["idle_jump"].hex()}]
    return out


def _check_free(stock: bytes, span_list) -> None:
    blocks = [b for b in bootstream.walk(stock).blocks if b.count]
    for what, at, payload in span_list:
        lo, hi = at, at + len(payload)
        if not (dm_to_load(REGION[0]) <= lo and hi <= dm_to_load(REGION[1])):
            raise DspError(f"{what} at {lo:#x} leaves the block-1 region {REGION}")
        for b in blocks:
            if b.target < hi and lo < b.target + b.count:
                raise DspError(f"{what} at {lo:#x}+{len(payload):#x} overlaps the stock "
                               f"block at {b.target:#x}+{b.count:#x}")
    if not (STOCK_BLOCK1_END <= REGION[0] and REGION[1] <= DM_CACHE_32K):
        raise DspError(f"the region {REGION} is not between block 1's last stock byte and a 32 KB DM cache")
    ordered = sorted((at, at + len(p), w) for w, at, p in span_list)
    for (a0, a1, w0), (b0, b1, w1) in zip(ordered, ordered[1:]):
        if b0 < a1:
            raise DspError(f"{w0} and {w1} overlap")


IDLE_STATE_BYTES = 0x40                      # idle: saves, LAST, total, passes, BEFORE, AFTER; count: blocks, saves, MARK; MARK0


def idle_spans() -> list[tuple[str, int, bytes]]:
    """The idle stub's own blocks: its zeroed state, and its code padded to table 0."""
    code = objects()["idle_load"]
    end = TABLES_DM[0]
    if end - IDLE_DM - len(code) < 64:
        raise DspError("idle_load.asm leaves fewer than 64 bytes of NOP padding")
    return [("idle_load state (zeros)", dm_to_load(IDLE_STATE_DM), bytes(IDLE_STATE_BYTES)),
            ("idle_load.asm (wr_idle)", dm_to_load(IDLE_DM), code + bytes(end - IDLE_DM - len(code)))]


def _check_stock(stock: bytes) -> None:
    digest = hashlib.sha256(stock).hexdigest()
    if digest != STOCK_SHA256:
        raise DspError(f"section 7 sha256 {digest[:12]}... is not stock DN2 1.11's "
                       f"({STOCK_SHA256[:12]}...)")


def _check_idle_site(stock: bytes, obj: dict) -> None:
    if len(obj["idle_jump"]) != len(IDLE_SITE_STOCK):
        raise DspError(f"the idle JUMP is {len(obj['idle_jump'])} bytes, not {len(IDLE_SITE_STOCK)}")
    if bootstream.read_span(stock, l2_sw_to_load(IDLE_SITE_SW), len(IDLE_SITE_STOCK)) != IDLE_SITE_STOCK:
        raise DspError("sw 0xb88abb is not the stock idle loop's `jump (pc,-0x10)`")


def _finish(out: bytearray) -> bytes:
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise DspError(f"the result does not walk as a boot stream ({walked.reason})")
    return result


def section7_idle_only(stock: bytes) -> bytes:
    """Stock DN2 1.11's section 7 plus the idle-time stub and nothing else: the stock
    engine, measured. Refuses anything but stock."""
    _check_stock(stock)
    obj = objects()
    _check_idle_site(stock, obj)
    added = idle_spans()
    _check_free(stock, added)
    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(bootstream.block(at, payload) for _, at, payload in added)))
    bootstream.write_span(out, l2_sw_to_load(IDLE_SITE_SW), obj["idle_jump"])
    return _finish(out)


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
    if len(obj["idle_jump"]) != len(IDLE_SITE_STOCK):
        raise DspError(f"the idle JUMP is {len(obj['idle_jump'])} bytes, not {len(IDLE_SITE_STOCK)}")
    if bootstream.read_span(stock, l2_sw_to_load(IDLE_SITE_SW), len(IDLE_SITE_STOCK)) != IDLE_SITE_STOCK:
        raise DspError("sw 0xb88abb is not the stock idle loop's `jump (pc,-0x10)`")
    if bootstream.read_span(stock, sw_to_load(CALL_SITE_SW), len(CALL_SITE_STOCK)) != CALL_SITE_STOCK:
        raise DspError("sw 0x1c9fb9 is not the stock `r4 = 0x268438`")
    if len(obj["emark_jump"]) != len(CALL_SITE_STOCK):
        raise DspError(f"the entry-mark JUMP is {len(obj['emark_jump'])} bytes, not {len(CALL_SITE_STOCK)}")
    lookup = struct.unpack("<8I", bootstream.read_span(stock, dm_to_load(LOOKUP_DM), 32))
    if lookup != LOOKUP_STOCK:
        raise DspError(f"the machine lookup is {lookup}, not stock {LOOKUP_STOCK}")
    added = spans()
    _check_free(stock, added)

    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(bootstream.block(at, payload) for _, at, payload in added)))
    bootstream.write_span(out, sw_to_load(ENTRY_SW), entry)
    bootstream.write_span(out, dm_to_load(LOOKUP_DM + 20), struct.pack("<I", 5))
    bootstream.write_span(out, l2_sw_to_load(IDLE_SITE_SW), obj["idle_jump"])
    bootstream.write_span(out, sw_to_load(CALL_SITE_SW), obj["emark_jump"])
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise DspError(f"the result does not walk as a boot stream ({walked.reason})")
    return result

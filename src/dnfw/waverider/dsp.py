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
from . import factory, live
from . import render as reference

STOCK_SHA256 = "336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2"
LOAD_ALIAS = 0x28000000          # boot-stream load address = LOAD_ALIAS + DM byte address
CODE = pathlib.Path(__file__).with_name("sharc_code.json")

# L1 block 1's free tail (DM byte addresses). Block 1 is 0x2c0000..0x2f0000; the
# stock stream's last byte in it is 0x2dd52c, and the startup enables the DM cache,
# which is carved from the top of block 1 (16 KB at size code 0, the size the
# startup writes; see docs/waverider-dsp-silence.md). REGION ends 36 KB below the
# block's top, so it stays clear of a 16 KB or a 32 KB DM cache.
REGION = (0x2DD600, 0x2E3B00)                # W5: tables to DDR; W2: + the scanner; PING: + its code, state, tables
STOCK_BLOCK1_END = 0x2DD52C
DM_CACHE_32K = 0x2E8000                      # the lowest byte a 32 KB DM cache would own
CODE_SPAN = 0x400                            # each code object is padded to this
READER_DM = 0x2DD600
LOOP_DM = 0x2DEF00                           # W5: moved from 0x2dda00, which held 1 KB; the loop is now ~1 KB
LOOP_SPAN = 0xA00                            # W2: the scanner and the gain ramp, ~2 KB
READER_SW = READER_DM // 2                   # 0x16eb00
LOOP_SW = LOOP_DM // 2                       # 0x16f780 (0x16ed00 before W5)
STATE_DM, STATE_BYTES = 0x2DDE00, 0x400      # save area, counters, 16 reader blocks
READER_BLOCKS_DM, READER_BLOCK_BYTES = 0x2DDF00, 32
INC_TABLE_DM = 0x2DE200
DIRECTORY_DM = 0x2DE600
DIRECTORY_MAGIC = 0x57525431                 # 'WRT1'
DIRECTORY_CAP = 0x200                        # magic, count, pointers: at most 126 tables
LUT_DM = DIRECTORY_DM + DIRECTORY_CAP        # 0x2de800: TBL (0..127) -> slot, 128 words
SMOOTH_DM = 0x2DEE00                         # W5 per-voice POS glide: 16 x pos, then 16 x note counter
SMOOTH_BYTES = 0x80
# W2 (docs/w2-scanner.md): per voice 16 words of scanner state, then three tables,
# after the loop. L1 block 1 up to 0x2e7000 held M5c's tables on the instrument, so
# this stays inside memory already proven free.
W2_STATE_DM, W2_STATE_STRIDE = LOOP_DM + LOOP_SPAN, 64       # 0x2df900
W2_RATE_DM = W2_STATE_DM + 16 * W2_STATE_STRIDE              # 0x2dfd00: RATE -> u32 step a block
W2_LEVEL_DM = W2_RATE_DM + 128 * 4                           # 0x2dff00: LEV -> float32 gain
W2_RND_DM = W2_LEVEL_DM + 128 * 4                            # 0x2e0100: 256 float32 in [0, 1)
# PING (docs/ping.md): its code (entered from machine5_live's tail), 16 x 128 bytes
# of state, a few words of scratch, then its tables (dnfw.ping.live.tables_bytes)
PING_CODE_DM, PING_CODE_SPAN = 0x2E0500, 0x1800
PING_SW = PING_CODE_DM // 2                                  # 0x170280
PING_STATE_DM = PING_CODE_DM + PING_CODE_SPAN                # 0x2e1d00
PING_T_DM = PING_STATE_DM + 16 * 128                         # 0x2e2500: t, then scratch
PING_TABLES_DM = PING_T_DM + 0x40                            # 0x2e2540

# W5: the tables live in the SHARC's DDR (docs/w5-tables.md). The stock boot stream
# loads DDR to 0x8052fbe0 and the engine's init writes up to 0x80530be8
# (scripts/sharc_ddr_ceiling.py); the tables start 16 MB in, far above both.
TABLES_DDR = 0x81000000
TABLE_BYTES = 16 * 512 * 2                   # 16 frames x 512 int16
DDR_FLOOR = 0x80600000                       # nothing of ours below this in DDR
TABLE_COUNT = len(factory.TABLES)

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
    """The factory tables in slot order (`factory.TABLES`); slots 0 and 1 are the two
    M5 shipped: the saw darkening to a sine, and the overtone series."""
    return factory.tables()


def table_addresses(count: int | None = None) -> list[int]:
    n = TABLE_COUNT if count is None else count
    return [TABLES_DDR + k * TABLE_BYTES for k in range(n)]


def slot_lut(count: int | None = None) -> list[int]:
    """TBL's value >> 8 (0..127, WaveTone's DRIF record) -> table slot, the knob's
    travel shared evenly between the tables."""
    n = TABLE_COUNT if count is None else count
    return [min(n - 1, (v * n) >> 7) for v in range(128)]


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
                         "entry_mark", "emark_jump", "ping")}


def directory() -> bytes:
    """magic, count, the table pointers, zero-padded to DIRECTORY_CAP, then the
    128-word TBL -> slot table."""
    addrs = table_addresses()
    head = struct.pack("<II", DIRECTORY_MAGIC, len(addrs)) + struct.pack("<%dI" % len(addrs), *addrs)
    if len(head) > DIRECTORY_CAP:
        raise DspError(f"{len(addrs)} tables do not fit the directory")
    return head + bytes(DIRECTORY_CAP - len(head)) + struct.pack("<128I", *slot_lut())


def spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of every block this adds, in stream order.

    Each payload is zero-padded up to the next span's start (the last to REGION's
    end), so the region is written end to end and every code object is followed by
    at least 64 bytes of zeros (a zero word is a NOP)."""
    obj = objects()
    raw = [
        ("reader_m5.asm (wr_render5)", READER_DM, obj["reader"]),
        ("state: save area, counters, 16 reader blocks (zeros)", STATE_DM, bytes(STATE_BYTES)),
        ("increment table, 129 float32", INC_TABLE_DM, live.table_bytes()),
        ("wavetable directory", DIRECTORY_DM, directory()),
        ("idle_load.asm (wr_idle)", IDLE_DM, obj["idle_load"]),
        ("block_count.asm (wr_count)", COUNT_DM, obj["block_count"]),
        ("entry_mark.asm (wr_emark)", EMARK_DM, obj["entry_mark"]),
        ("W5 POS glide state: 16 positions, 16 note counters (zeros)", SMOOTH_DM, bytes(SMOOTH_BYTES)),
        ("machine5_live.asm (wr_type5v)", LOOP_DM, obj["machine5_live"]),
        ("W2 scanner state: 16 voices x 16 words (zeros)", W2_STATE_DM, bytes(16 * W2_STATE_STRIDE)),
        ("W2 RATE table, 128 u32", W2_RATE_DM, struct.pack("<128I", *live.rate_table())),
        ("W2 LEV table, 128 float32", W2_LEVEL_DM, struct.pack("<128f", *live.level_table())),
        ("W2 random table, 256 float32", W2_RND_DM, struct.pack("<256f", *live.rnd_table())),
        ("ping.asm (wr_ping)", PING_CODE_DM, obj["ping"]),
        ("PING state: 16 tracks x 128 bytes, then scratch (zeros)", PING_STATE_DM, bytes(16 * 128 + 0x40)),
        ("PING tables", PING_TABLES_DM, _ping_tables()),
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


def _ping_tables() -> bytes:
    from ..ping import live as ping_live
    return ping_live.tables_bytes()[0]


def ddr_spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of each table, in DDR (load address = address)."""
    names = factory.names()
    return [(f"table {k}: {names[k]}", at, reference.dsp_bytes(tab))
            for k, (at, tab) in enumerate(zip(table_addresses(), tables()))]


def _check_ddr(stock: bytes, span_list) -> None:
    blocks = [b for b in bootstream.walk(stock).blocks if b.count]
    for what, at, payload in span_list:
        lo, hi = at, at + len(payload)
        if lo < DDR_FLOOR or hi > 0x88000000:
            raise DspError(f"{what} at {lo:#x} is outside {DDR_FLOOR:#x}..0x88000000")
        for b in blocks:
            if b.target < hi and lo < b.target + b.count:
                raise DspError(f"{what} overlaps the stock block at {b.target:#x}")
    ordered = sorted((at, at + len(p), w) for w, at, p in span_list)
    for (a0, a1, w0), (b0, b1, w1) in zip(ordered, ordered[1:]):
        if b0 < a1:
            raise DspError(f"{w0} and {w1} overlap")


def placements() -> list[dict]:
    out = [{"what": what, "load_address": f"{at:#010x}", "dm_byte": f"{at - LOAD_ALIAS:#08x}",
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
           for what, at, payload in spans() + ddr_spans()]
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
    end = COUNT_DM                           # block_count.asm follows (W5: tables are in DDR)
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


# A run of zeros this long or longer inside a payload goes into the stream as a fill
# block (16 bytes, no payload) instead of as bytes. The stock stream does exactly this
# into the same L1 block (e.g. 36 bytes at 0x2dd328): the memory after boot is the
# same, byte for byte, and the stream is shorter -- the DSP upload budget is the
# stream's length (2026-10-14).
FILL_MIN = 64


def _blocks(at: int, payload: bytes) -> bytes:
    """`payload` at load address `at`, as payload blocks with every 4-aligned run of
    at least FILL_MIN zero bytes as a fill block."""
    out, i, n, start = [], 0, len(payload), 0
    while i < n:
        if i % 4 == 0 and payload[i] == 0:
            j = i
            while j < n and payload[j] == 0:
                j += 1
            k = i + ((j - i) // 4) * 4           # whole words only
            if k - i >= FILL_MIN:
                if start < i:
                    out.append(bootstream.block(at + start, payload[start:i]))
                out.append(bootstream.block(at + i, flags=bootstream.FLAG_FILL, count=k - i))
                start = i = k
                continue
            i = max(j, i + 1)
        else:
            i += 1
    if start < n:
        out.append(bootstream.block(at + start, payload[start:]))
    return b"".join(out)


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
    ddr = ddr_spans()
    _check_ddr(stock, ddr)

    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(_blocks(at, payload) for _, at, payload in added + ddr)))
    bootstream.write_span(out, sw_to_load(ENTRY_SW), entry)
    bootstream.write_span(out, dm_to_load(LOOKUP_DM + 20), struct.pack("<I", 5))
    bootstream.write_span(out, l2_sw_to_load(IDLE_SITE_SW), obj["idle_jump"])
    bootstream.write_span(out, sw_to_load(CALL_SITE_SW), obj["emark_jump"])
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise DspError(f"the result does not walk as a boot stream ({walked.reason})")
    return result

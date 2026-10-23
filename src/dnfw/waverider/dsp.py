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
from . import live

STOCK_SHA256 = "336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2"
LOAD_ALIAS = 0x28000000          # boot-stream load address = LOAD_ALIAS + DM byte address
CODE = pathlib.Path(__file__).with_name("sharc_code.json")

# L1 block 1's free tail (DM byte addresses). Block 1 is 0x2c0000..0x2f0000; the
# stock stream's last byte in it is 0x2dd52c, and the startup enables the DM cache,
# which is carved from the top of block 1 (16 KB at size code 0, the size the
# startup writes; see docs/waverider-dsp-silence.md). REGION ends 36 KB below the
# block's top, so it stays clear of a 16 KB or a 32 KB DM cache.
REGION = (0x2DD600, 0x2E7000)                # W5: tables to DDR; W2: + the scanner; PING: + its code, state, tables; SHFT: + state, tables; RESONATOR: + code, scratch, tables
STOCK_BLOCK1_END = 0x2DD52C
DM_CACHE_32K = 0x2E8000                      # the lowest byte a 32 KB DM cache would own
CODE_SPAN = 0x400                            # each code object is padded to this
STATE_DM, STATE_BYTES = 0x2DDE00, 0x380      # save area, PERC's scratch, idle_load's state
# PERC (v0.11, docs/perc.md): machine type 5, in Waverider's former place. Its code is
# too big for L1 (about 26 KB), so it runs from L2, above everything the stock stream
# loads (scripts/sharc_l2_ceiling.py: neither the engine's init nor any stock machine
# touches L2 above the image's end) and well below the startup's non-cacheable window
# 0x200fa000..0x200fdfff; the I-cache (enabled by the startup, docs/waverider-dsp-silence.md)
# serves it. Its voices' state and scratch stay in L1, its tables in DDR.
PERC_L2_LOAD = 0x200C0000
PERC_L2_SPAN = 0x14000                       # 80 KB (v0.17: the Machinedrum machines, about 79.5 KB)
PERC_SW = 0xB80000 + (PERC_L2_LOAD - 0x20000000) // 2       # 0xbe0000
L2_IMAGE_END = 0x2008823C                    # the stock stream's last L2 byte
L2_NOCACHE = 0x200FA000                      # the startup's non-cacheable L2 window starts here
PERC_SCRATCH_DM = 0x2DDE80                   # 55 words (dnfw.perc.machines.SC_WORDS)
PERC_STATE_DM, PERC_STATE_STRIDE = 0x2DE180, 128             # 16 voices x 32 words
PERC_TABLES_DDR = 0x81216000                 # dnfw.perc.machines.tables_bytes
# the Machinedrum machines (v0.17, docs/md.md): their tables (the sine, which the DSP fills
# itself, then the host's and DSP2's tables, read from the owner's MD firmware at build
# time), and 16 slots x 1 KB of words
MD_TABLES_DDR = 0x82000000
MD_STATE_DDR = 0x82100000
# the sample machines (v0.13, docs/sampler.md): code in L2 after PERC's span, voices and
# scratch in L1 (Waverider's former loop room), the sample pool in DDR from 64 MB in
SMP_L2_LOAD = PERC_L2_LOAD + PERC_L2_SPAN    # 0x200d4000 (0x200d0000 until v0.16)
SMP_L2_SPAN = 0x5000                         # the code is about 19 KB (v0.18: the DT2 reader; 32 KB until v0.16)
SMP_SW = 0xB80000 + (SMP_L2_LOAD - 0x20000000) // 2          # 0xbea000 (0xbe8000 until v0.16)
SMP_STATE_DM, SMP_STATE_STRIDE = 0x2DEF00, 128  # 16 voices x 128 bytes (v0.15)
SMP_SCRATCH_DM = 0x2DF700                    # after 16 x 128 bytes of state (v0.15)
SMP_STAGE_DM = SMP_SCRATCH_DM + 0x100        # the recorder's block (dnfw.sampler.machines.REC_STAGE)
SMP_LINK_DM = SMP_STAGE_DM + 0x80            # the fast link's scratch, then its packet buffer (v0.16)
SMP_POOL_DDR = 0x84000000                    # the pool's directory, then its frames
# v0.18: the DT2 reader's coefficients (dnfw.sampler.program.tables_bytes, from the owner's
# DT2 image) in DDR; each voice's decimator (12 words) in L1, where Waverider's loop was
SMP_TABLES_DDR = 0x81218000
SMP_DEC_DM = SMP_LINK_DM + 0x500                        # 16 x 48 bytes, to 0x2e0080 (W2_RND_DM is 0x2e0100)
# W2's random table (dnfw.waverider.live.rnd_table): Waverider is gone (v0.11), but
# RESONATOR, CZ and GRAN read it here
W2_RND_DM = 0x2E0100                                         # 256 float32 in [0, 1)
# PING (docs/ping.md): its code (entered from machine5_live's tail), 16 x 128 bytes
# of state, a few words of scratch, then its tables (dnfw.ping.live.tables_bytes)
PING_CODE_DM, PING_CODE_SPAN = 0x2E0500, 0x1800
PING_SW = PING_CODE_DM // 2                                  # 0x170280
PING_STATE_DM = PING_CODE_DM + PING_CODE_SPAN                # 0x2e1d00
PING_T_DM = PING_STATE_DM + 16 * 128                         # 0x2e2500: t, then scratch
# GRAN (v0.10): PING's and SHFT's tables moved to DDR, so GRAN's code takes theirs
# in L1 (0x2e2540, where PING's tables were) and its state SHFT's (0x2e4b00)
PING_TABLES_DDR = 0x81210000
GRAN_CODE_DM = PING_T_DM + 0x40                              # 0x2e2540
GRAN_SW = GRAN_CODE_DM // 2                                  # 0x1712a0
GRAN_SCRATCH_DM = 0x2E3A00                                   # 32 words, after GRAN's code
# SHFT (docs/shft.md): its code is in ping.asm; 16 x 256 bytes of state (zeros, so a
# fill block in the stream); its sine and pow2 tables (dnfw.shft.live) in DDR
SHFT_STATE_DM, SHFT_STATE_STRIDE = 0x2E3B00, 256             # after GRAN's code
SHFT_TABLES_DDR = 0x81212000
# GRAN (docs/gran.md, filter type 8): 16 x 128 bytes of state in L1, its tables and
# 16 ring buffers of 32768 float32 (128 KB a track, zeros: a fill block) in DDR
GRAN_STATE_DM, GRAN_STATE_STRIDE = SHFT_STATE_DM + 16 * SHFT_STATE_STRIDE, 128   # 0x2e4b00
GRAN_TABLES_DDR = 0x81214000
GRAN_BUF_DDR, GRAN_BUF_STRIDE = 0x81400000, 0x20000
# RESONATOR (docs/rings.md, machine type 6): its code (entered from machine5_live's
# tail, on to wr_cz), a scratch block (the exciter and the mode sum of one voice, the
# loop's counters) in the reader span's tail; its tables (dnfw.rings.live) and its 16
# voices' state in DDR (the state zeros: a fill block), read once a mode a block.
# (v0.6 had the scratch at 0x2e6400 and the tables at 0x2e6600; CZ took that room.)
RINGS_CODE_DM, RINGS_CODE_SPAN = 0x2E5300, 0xE40
RINGS_SW = RINGS_CODE_DM // 2                                # 0x172980
RINGS_SCRATCH_DM = 0x2DDB00                                  # after reader_m5's code + padding
RINGS_STATE_DDR, RINGS_STATE_STRIDE = 0x81200000, 256
RINGS_TABLES_DDR = RINGS_STATE_DDR + 16 * RINGS_STATE_STRIDE  # 0x81201000
# CZ (docs/cz.md, machine type 7): its code (entered from rings.asm's tail, on to
# wr_ping) up to 0x2e7000, the end of the memory M5c's tables proved free on the
# instrument; a scratch block in the reader span's tail; its 16 voices' state and its
# tables in DDR
CZ_SCRATCH_DM = RINGS_SCRATCH_DM + 0x200                     # 0x2ddd00
CZ_CODE_DM = RINGS_CODE_DM + RINGS_CODE_SPAN                 # 0x2e6140
CZ_SW = CZ_CODE_DM // 2                                      # 0x1730a0 (0x173000 until v0.10)
CZ_STATE_DDR, CZ_STATE_STRIDE = 0x81202000, 64
CZ_TABLES_DDR = CZ_STATE_DDR + 16 * CZ_STATE_STRIDE          # 0x81202400

DDR_FLOOR = 0x80600000                       # nothing of ours below this in DDR
IDLE_DM = 0x2DEA00                           # idle_load.asm
IDLE_SW = IDLE_DM // 2                       # 0x16f500
IDLE_STATE_DM = 0x2DE100                     # its save area and counters (state block tail)
COUNT_DM = 0x2DEC00                          # block_count.asm, after idle_load.asm
COUNT_SW = COUNT_DM // 2                     # 0x16f600: the entry JUMP's target, which goes on to PERC
EMARK_DM = 0x2DED00                          # entry_mark.asm: EMUCLK as the handler calls 0x1c2712
EMARK_SW = EMARK_DM // 2                     # 0x16f680
L2_LOAD, L2_SW = 0x20000000, 0xB80000        # L2 code: load address 0x20000000 is sw 0xb80000

# stock sites
ENTRY_SW = 0x1C9448                          # i5=dm(-0x18,i6); r10=dm(-0x22,i6)
ENTRY_STOCK = bytes.fromhex("089ce80a089c5e05")
NOP16 = bytes.fromhex("0100")                # the firmware's own 16-bit NOP (sw 0x1c9447)
LOOKUP_DM = 0x25D748                         # frame nibble -> machine type, 8 words
LOOKUP_STOCK = (0, 1, 2, 3, 4, 0, 0, 0)
MACHINE6 = 6                                 # RESONATOR: lookup[6] = 6 (stock 0, FM Tone)
MACHINE7 = 7                                 # CZ: lookup[7] = 7 (stock 0, FM Tone)
# v0.13: the lookup moves to a 16-entry copy in our region (the frame field indexes it
# unmasked, sw 0x1c295d `R2 = DM(I5, M0)` after `I5 = 0x25d748` at sw 0x1c2958), so the
# machine types can grow past 8. The word before it is 0, as stock's is (0x25d744), so a
# frame value of -1 reads FM Tone as before. Types with no engine read 0 (FM Tone).
LOOKUP_SITE_SW = 0x1C2958                    # I5 = 0x25d748
LOOKUP_SITE_STOCK = bytes.fromhex("0f150025d748")   # parcels, MSW first
LOOKUP16_DM = 0x2DEE04                       # 16 words; 0x2dee00 is the [-1] guard (0)
MACHINE_TYPES = 16
SMP_ENGINE_SLOT = 5                          # the engine slot the sample machines borrow
SMP_TYPES = range(8, 13)                     # ONESHOT WERP STRETCH REPITCH GRID
ENGINES = {5: "PERC", 6: "RESONATOR", 7: "CZ", 8: "ONESHOT", 12: "GRID"}   # types with an engine of ours

IDLE_SITE_SW = 0xB88ABB                      # prvIdleTask's back edge: jump (pc,-0x10)
IDLE_SITE_STOCK = bytes.fromhex("3e07ff00f0ff")
IDLE_RETURN_SW = 0xB88AAB                    # the loop's top: call prvCheckTasksWaitingTermination
CALL_SITE_SW = 0x1C9FB9                      # the handler's `r4 = 0x268438` before `cjump 0x1c2712`
CALL_SITE_STOCK = bytes.fromhex("040f26003884")


class DspError(ValueError):
    pass


def lookup16() -> bytes:
    """the relocated machine lookup: [-1] = 0, then type -> engine slot: the stock five
    and ours as themselves, the sample machines (8..12) to 5 -- PERC's slot, so the stock
    code takes the one path for them the runner and the instrument have proven (the
    record's +0x1b4 copy indexes 8-entry tables at sw 0x1c299f and in the render code; 8
    and above would read past them). PERC and the sample machines tell themselves apart by
    the frame's own type word; one whose machine has no renderer yet stays silent on that
    slot. Any other type reads 0 (FM Tone), as stock answers 5-7."""
    table = [t if t < 5 or t in ENGINES and t < 8 else SMP_ENGINE_SLOT if t in SMP_TYPES else 0
             for t in range(MACHINE_TYPES)]
    return struct.pack(f"<{1 + MACHINE_TYPES}I", 0, *table)


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
    """The committed SHARC objects: PERC, the entry JUMP, the stubs, the filters, the machines."""
    spec = _code()
    return {name: sharc_object.load_bytes(bytes.fromhex(spec[name]["object_parcels_be"]))
            for name in ("perc", "smp", "entry_jump", "idle_load", "idle_jump", "block_count",
                         "entry_mark", "emark_jump", "lookup_ptr", "ping", "rings", "cz", "gran")}


def spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of every block this adds, in stream order.

    Each payload is zero-padded up to the next span's start (the last to REGION's
    end), so the region is written end to end and every code object is followed by
    at least 64 bytes of zeros (a zero word is a NOP)."""
    obj = objects()
    raw = [
        ("free since v0.11 (Waverider's reader and osc 2; zeros)", REGION[0], b""),
        ("RESONATOR scratch (zeros)", RINGS_SCRATCH_DM, bytes(0x200)),
        ("CZ scratch (zeros)", CZ_SCRATCH_DM, bytes(0x100)),
        ("state: save area, PERC scratch, idle_load's counters (zeros)", STATE_DM, bytes(STATE_BYTES)),
        ("PERC state: 16 voices x 128 bytes (zeros)", PERC_STATE_DM, bytes(16 * PERC_STATE_STRIDE)),
        ("idle_load.asm (wr_idle)", IDLE_DM, obj["idle_load"]),
        ("block_count.asm (wr_count)", COUNT_DM, obj["block_count"]),
        ("entry_mark.asm (wr_emark)", EMARK_DM, obj["entry_mark"]),
        ("machine lookup, 16 types ([-1] guard, then the table; v0.13)", LOOKUP16_DM - 4, lookup16()),
        ("sample machines' state: 16 voices x 128 bytes (zeros)", SMP_STATE_DM, bytes(16 * SMP_STATE_STRIDE)),
        ("sample machines' scratch (zeros)", SMP_SCRATCH_DM, bytes(0x100)),
        ("the recorder's staging block: 32 floats (zeros)", SMP_STAGE_DM, bytes(0x80)),
        ("the fast link's scratch and packet buffer (zeros; v0.16)", SMP_LINK_DM, bytes(0x500)),
        ("sample machines' decimators: 16 voices x 48 bytes (zeros; v0.18)", SMP_DEC_DM, bytes(16 * 48)),
        ("W2 random table, 256 float32 (RESONATOR, CZ, GRAN)", W2_RND_DM, struct.pack("<256f", *live.rnd_table())),
        ("ping.asm (wr_ping)", PING_CODE_DM, obj["ping"]),
        ("PING state: 16 tracks x 128 bytes, then scratch (zeros)", PING_STATE_DM, bytes(16 * 128 + 0x40)),
        ("gran.asm (wr_gran)", GRAN_CODE_DM, obj["gran"]),
        ("GRAN scratch (zeros)", GRAN_SCRATCH_DM, bytes(0x100)),
        ("SHFT state: 16 tracks x 256 bytes (zeros)", SHFT_STATE_DM, bytes(16 * SHFT_STATE_STRIDE)),
        ("GRAN state: 16 tracks x 128 bytes (zeros)", GRAN_STATE_DM, bytes(16 * GRAN_STATE_STRIDE)),
        ("rings.asm (wr_rings)", RINGS_CODE_DM, obj["rings"]),
        ("cz.asm (wr_cz)", CZ_CODE_DM, obj["cz"]),
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


def _shft_tables() -> bytes:
    from ..shft import live as shft_live
    return shft_live.tables_bytes()[0]


def _rings_tables() -> bytes:
    from ..rings import live as rings_live
    return rings_live.tables_bytes()[0]


def _cz_tables() -> bytes:
    from ..cz import live as cz_live
    return cz_live.tables_bytes()[0]


def _md_core():
    from ..md import core
    return core


def _perc_tables() -> bytes:
    from ..perc import machines as perc_machines
    return perc_machines.tables_bytes()[0]


def ddr_spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of each DDR span (load address = address): the
    machines' and filters' state (zeros, so fill blocks) and tables."""
    return [
        ("RESONATOR state: 16 voices x 256 bytes (zeros)", RINGS_STATE_DDR,
         bytes(16 * RINGS_STATE_STRIDE)),
        ("RESONATOR tables", RINGS_TABLES_DDR, _rings_tables()),
        ("CZ state: 16 voices x 64 bytes (zeros)", CZ_STATE_DDR, bytes(16 * CZ_STATE_STRIDE)),
        ("CZ tables", CZ_TABLES_DDR, _cz_tables()),
        ("PING tables", PING_TABLES_DDR, _ping_tables()),
        ("SHFT tables", SHFT_TABLES_DDR, _shft_tables()),
        ("GRAN tables", GRAN_TABLES_DDR, _gran_tables()),
        ("PERC tables", PERC_TABLES_DDR, _perc_tables()),
        ("the DT2 sample reader's coefficients (from the owner's DT2 image; v0.18)", SMP_TABLES_DDR,
         _smp_tables()),
        ("Machinedrum sine (zeros: the DSP fills it)", MD_TABLES_DDR, bytes(4 * _md_core().SINE_N)),
        ("Machinedrum tables (from the owner's MD firmware)", MD_TABLES_DDR + _md_core().TABLE_LAYOUT["sinecorr"][0],
         _md_core().tables_bytes()),
        ("Machinedrum voices: 16 slots x 1 KB (zeros)", MD_STATE_DDR, bytes(16 * _md_core().MD_STRIDE)),
        ("GRAN buffers: 16 tracks x 32768 float32 (zeros)", GRAN_BUF_DDR, bytes(16 * GRAN_BUF_STRIDE)),
        ("sample pool: its empty directory's magic and count (v0.17: no test sounds; the +Drive's load in)",
         SMP_POOL_DDR, _smp_pool()[:8]),
        ("sample pool: the rest of its directory and names (zeros)", SMP_POOL_DDR + 8,
         bytes(len(_smp_pool()) - 8))]


def _smp_tables() -> bytes:
    from ..sampler import program as smp_program
    return smp_program.tables_bytes()


def _smp_pool() -> bytes:
    from ..sampler import live as smp_live
    # v0.17: the Machinedrum's tables needed the DSP image's room, and since v0.16 the
    # +Drive holds the owner's own samples: the build ships an empty pool (the runner puts
    # the test sounds in itself, as the ColdFire's loader would)
    return smp_live.pool_bytes([], SMP_POOL_DDR)


def l2_spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of what goes in L2: PERC's code, then the sample
    machines', each zero-padded to its span (so at least 64 bytes of NOPs after it)."""
    obj = objects()
    out = []
    for what, name, at, span in (("perc.asm (wr_perc), in L2", "perc", PERC_L2_LOAD, PERC_L2_SPAN),
                                 ("smp.asm (wr_smp), in L2", "smp", SMP_L2_LOAD, SMP_L2_SPAN)):
        code = obj[name]
        if span - len(code) < 64:
            raise DspError(f"{name}.asm ({len(code)} bytes) leaves fewer than 64 bytes of its L2 span")
        out.append((what, at, code + bytes(span - len(code))))
    return out


def _check_l2(stock: bytes, span_list) -> None:
    blocks = [b for b in bootstream.walk(stock).blocks if b.count]
    for what, at, payload in span_list:
        lo, hi = at, at + len(payload)
        if lo < L2_IMAGE_END + 0x10000 or hi > L2_NOCACHE - 0x10000:
            raise DspError(f"{what} at {lo:#x}..{hi:#x} is outside {L2_IMAGE_END + 0x10000:#x}.."
                           f"{L2_NOCACHE - 0x10000:#x} (64 KB clear of the stock image and the "
                           "non-cacheable window)")
        for b in blocks:
            if b.target < hi and lo < b.target + b.count:
                raise DspError(f"{what} overlaps the stock block at {b.target:#x}")
    for b in blocks:
        if 0x20000000 <= b.target < 0x20100000 and b.target + b.count > L2_IMAGE_END:
            raise DspError(f"the stock block at {b.target:#x} ends past L2_IMAGE_END")


def _gran_tables() -> bytes:
    from ..grain import live as gran_live
    return gran_live.tables_bytes()[0]


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
           for what, at, payload in spans() + ddr_spans() + l2_spans()]
    obj = objects()
    out += [{"what": f"patch: entry JUMP {COUNT_SW:#x} (the block counter, then PERC) + NOP at sw 0x1c9448",
             "load_address": f"{sw_to_load(ENTRY_SW):#010x}",
             "bytes": len(obj["entry_jump"]) + len(NOP16),
             "stock": ENTRY_STOCK.hex(), "new": (obj["entry_jump"] + NOP16).hex()},
            {"what": f"patch: the machine lookup's base at sw {LOOKUP_SITE_SW:#x}, I5 = 0x25d748 -> "
                     f"{LOOKUP16_DM:#x} (16 types)",
             "load_address": f"{sw_to_load(LOOKUP_SITE_SW):#010x}", "bytes": 6,
             "stock": sharc_object.load_bytes(LOOKUP_SITE_STOCK).hex(), "new": obj["lookup_ptr"].hex()},
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
    """DN2 1.11's section 7 -> the mod's. Refuses anything else."""
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
    if bootstream.read_span(stock, sw_to_load(LOOKUP_SITE_SW), 6) != sharc_object.load_bytes(LOOKUP_SITE_STOCK):
        raise DspError("sw 0x1c2958 is not the stock `I5 = 0x25d748`")
    if len(obj["lookup_ptr"]) != 6:
        raise DspError("the lookup pointer patch is not one 48-bit instruction")
    added = spans()
    _check_free(stock, added)
    ddr = ddr_spans()
    _check_ddr(stock, ddr)
    l2 = l2_spans()
    _check_l2(stock, l2)

    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(_blocks(at, payload) for _, at, payload in added + ddr + l2)))
    bootstream.write_span(out, sw_to_load(ENTRY_SW), entry)
    bootstream.write_span(out, sw_to_load(LOOKUP_SITE_SW), obj["lookup_ptr"])
    bootstream.write_span(out, l2_sw_to_load(IDLE_SITE_SW), obj["idle_jump"])
    bootstream.write_span(out, sw_to_load(CALL_SITE_SW), obj["emark_jump"])
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise DspError(f"the result does not walk as a boot stream ({walked.reason})")
    return result

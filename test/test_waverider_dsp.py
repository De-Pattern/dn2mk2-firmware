"""dnfw.waverider.dsp / live / harmonics: Milestone 5's section-7 builder and its contract.

The runner gate is scripts/sharc_waverider_m5.py; these need no runner, no WSL and
no firmware beyond the DN2 1.11 image (skipped cleanly when it is absent).
"""

from __future__ import annotations

import cmath
import hashlib
import json
import math
import pathlib
import struct

import pytest

from dnfw.image import bootstream, sharc_object
from dnfw.waverider import dsp

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = ROOT / "00_Resources" / "00_Firmware" / "Digitone_II_OS1.11_dist.zip"
SHARC = ROOT / "csrc" / "waverider" / "sharc"


@pytest.fixture(scope="module")
def stock7() -> bytes:
    if not IMAGE.exists():
        pytest.skip(f"{IMAGE.name} not present")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    sec = load(read_image(IMAGE)).container.find(7)
    return sec.unpack() or sec.raw_payload


@pytest.fixture(scope="module")
def built(stock7) -> bytes:
    return dsp.section7(stock7)


# -- the committed objects -----------------------------------------------------------------

def test_committed_objects_match_their_sources():
    spec = json.loads(dsp.CODE.read_text(encoding="utf-8"))
    for key, name in (("perc", "perc"), ("idle_load", "idle_load"), ("block_count", "block_count"),
                      ("entry_mark", "entry_mark"), ("ping", "ping"), ("rings", "rings"), ("cz", "cz"),
                      ("gran", "gran")):
        src = (SHARC / f"{name}.asm").read_bytes().replace(b"\r\n", b"\n")
        assert spec[key]["source_sha256"] == hashlib.sha256(src).hexdigest(), name
        csrc = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
        assert csrc["object_parcels_be"] == spec[key]["object_parcels_be"], name
    assert spec["entry_jump"]["source"] == "JUMP 0x16f600;"
    assert spec["idle_jump"]["source"] == "JUMP 0x16f500;" and spec["idle_jump"]["at_sw"] == "0xb88abb"


def test_our_sources_avoid_dag1_m0_m3_in_memory_accesses():
    """No DM(..M0..M3..) access and no pre-modify read outside a DO loop (the two
    forms selas and selmap disagree on; docs/waverider-m5-dsp.md)."""
    import re
    for name in ("perc", "idle_load", "block_count", "entry_mark"):
        in_loop = False
        for line in (SHARC / f"{name}.asm").read_text().splitlines():
            code = line.split("//", 1)[0].strip().upper()
            if "DO " in code and "UNTIL" in code:
                in_loop = True
            assert not re.search(r"DM\s*\([^)]*\bM[0-3]\b", code), (name, line)
            # the one exception is the firmware's own return idiom, byte for byte
            # its `i12=dm(m7,i6)` (3b fe4d3f0e)
            if re.search(r"DM\s*\(\s*M\d+\s*,", code) and code != "I12 = DM(M7, I6);":
                assert in_loop, (name, line)
            if code.startswith(".WR5_LOOP_END"):
                in_loop = False


# -- the builder ------------------------------------------------------------------------------

def test_refuses_anything_but_stock(stock7):
    with pytest.raises(dsp.DspError):
        dsp.section7(stock7[:100] + bytes([stock7[100] ^ 1]) + stock7[101:])


def test_is_deterministic_and_walks(stock7, built):
    assert dsp.section7(stock7) == built
    w = bootstream.walk(built)
    assert w.complete and w.stopped_at == len(built)


def test_every_added_span_is_in_block_1s_free_tail_and_outside_every_stock_block(stock7):
    # Milestone 5c: M5's L1 block 2 silenced the instrument (docs/waverider-dsp-silence.md)
    stock_blocks = [b for b in bootstream.walk(stock7).blocks if b.count]
    for what, at, payload in dsp.spans():
        lo, hi = at - dsp.LOAD_ALIAS, at - dsp.LOAD_ALIAS + len(payload)
        assert 0x2DD52C <= lo and hi <= 0x2E8000, what          # above stock, below a 32 KB DM cache
        assert not (0x300000 <= lo < 0x320000), what            # nothing left in block 2
        for b in stock_blocks:
            assert not (b.target < at + len(payload) and at < b.target + b.count), what


def test_loaded_image_holds_our_bytes(built):
    for what, at, payload in dsp.spans():
        assert bootstream.read_span(built, at, len(payload)) == payload, what


def test_the_four_patches_and_nothing_else_in_the_stock_blocks(stock7, built):
    entry = bootstream.read_span(built, dsp.sw_to_load(dsp.ENTRY_SW), 8)
    assert entry == bytes.fromhex("3e06160000f60100")          # jump 0x16f600 (the block counter) ; nop
    lookup = struct.unpack("<8I", bootstream.read_span(built, dsp.dm_to_load(dsp.LOOKUP_DM), 32))
    assert lookup == (0, 1, 2, 3, 4, 5, 6, 7)            # PERC 5, RESONATOR 6, CZ 7
    # the idle loop's back edge, jump (pc,-0x10) at sw 0xb88abb in L2, becomes JUMP 0x16f500
    site = dsp.l2_sw_to_load(dsp.IDLE_SITE_SW)
    assert bootstream.read_span(stock7, site, 6) == bytes.fromhex("3e07ff00f0ff")
    assert bootstream.read_span(built, site, 6) == bytes.fromhex("3e061600" "00f5")
    # the handler's call of the per-block routine: r4 = 0x268438 becomes JUMP 0x16f680
    call = dsp.sw_to_load(dsp.CALL_SITE_SW)
    assert bootstream.read_span(stock7, call, 6) == dsp.CALL_SITE_STOCK
    assert bootstream.read_span(built, call, 6) == dsp.objects()["emark_jump"]
    # the clamp min(R2, 4) stays stock: its R0 = 0x4 parcel pair at sw 0x1c294a
    clamp = dsp.sw_to_load(0x1C294A)
    assert bootstream.read_span(built, clamp, 4) == bootstream.read_span(stock7, clamp, 4) \
        == bytes.fromhex("800f0400")
    # the per-type setup table is not touched
    assert bootstream.read_span(built, 0x8052DB90, 24) == bootstream.read_span(stock7, 0x8052DB90, 24)
    # every stock block's payload differs from stock only at the two patches
    final = bootstream.walk(stock7).final
    head = built[:final.offset]
    diff = [k for k in range(final.offset) if head[k] != stock7[k]]
    entry_off = bootstream.spans(stock7, dsp.sw_to_load(dsp.ENTRY_SW), 8)[0][0]
    look_off = bootstream.spans(stock7, dsp.dm_to_load(dsp.LOOKUP_DM + 20), 12)[0][0]
    idle_off = bootstream.spans(stock7, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), 6)[0][0]
    call_off = bootstream.spans(stock7, dsp.sw_to_load(dsp.CALL_SITE_SW), 6)[0][0]
    allowed = (set(range(entry_off, entry_off + 8)) | set(range(look_off, look_off + 12))
               | set(range(idle_off, idle_off + 6)) | set(range(call_off, call_off + 6)))
    assert diff and set(diff) <= allowed


def test_ddr_spans_are_clear_of_the_stock_image_and_the_engine():
    ddr = dsp.ddr_spans()
    # RESONATOR's state (zeros) and tables, CZ's state (zeros) and tables, PING's, SHFT's,
    # GRAN's and PERC's tables, GRAN's buffers (zeros); Waverider's wavetables went in v0.11
    assert [a for _, a, _ in ddr] == [dsp.RINGS_STATE_DDR, dsp.RINGS_TABLES_DDR,
                                      dsp.CZ_STATE_DDR, dsp.CZ_TABLES_DDR,
                                      dsp.PING_TABLES_DDR, dsp.SHFT_TABLES_DDR,
                                      dsp.GRAN_TABLES_DDR, dsp.PERC_TABLES_DDR, dsp.GRAN_BUF_DDR]
    assert not any(ddr[0][2]) and not any(ddr[2][2]) and not any(ddr[-1][2])
    # the stock stream loads DDR to 0x8052fbe0 and init writes up to 0x80530be8
    # (scripts/sharc_ddr_ceiling.py); ours start 16 MB in
    assert min(a for _, a, _ in ddr) >= dsp.DDR_FLOOR > 0x80530BE8


def test_perc_code_is_in_l2_above_the_stock_image_and_below_the_uncached_window(stock7, built):
    # scripts/sharc_l2_ceiling.py (2026-10-20, a fresh engine init and every stock machine):
    # nothing reads or writes L2 above the image's end, 0x2008823c
    ((what, at, payload),) = dsp.l2_spans()
    code = dsp.objects()["perc"]
    assert at == dsp.PERC_L2_LOAD and payload[:len(code)] == code and not any(payload[len(code):])
    assert len(payload) - len(code) >= 64
    assert dsp.L2_IMAGE_END + 0x10000 <= at and at + len(payload) <= dsp.L2_NOCACHE - 0x10000
    for b in bootstream.walk(stock7).blocks:
        if b.count and 0x20000000 <= b.target < 0x20100000:
            assert b.target + b.count <= dsp.L2_IMAGE_END
    assert bootstream.read_span(built, at, len(payload)) == payload
    assert dsp.PERC_SW == 0xBE0000 and dsp.l2_sw_to_load(dsp.PERC_SW) == dsp.PERC_L2_LOAD


def test_the_region_is_written_end_to_end_and_code_is_nop_padded():
    sp = dsp.spans()
    at = [a - dsp.LOAD_ALIAS for _, a, _ in sp]
    ends = [a - dsp.LOAD_ALIAS + len(p) for _, a, p in sp]
    assert at[0] == dsp.REGION[0] and ends[-1] == dsp.REGION[1]
    assert all(e == a for e, a in zip(ends, at[1:]))           # no unwritten gap
    obj = dsp.objects()
    code_spans = [x for x in sp if "asm" in x[0]]
    assert len(code_spans) == 7
    # v0.11: Waverider's reader, loop and osc 2 are gone (their room is zeros); PERC is in L2
    for (what, _, payload), code in zip(code_spans, (obj["idle_load"], obj["block_count"], obj["entry_mark"],
                                                     obj["ping"], obj["gran"], obj["rings"], obj["cz"])):
        assert payload[:len(code)] == code
        assert len(payload) - len(code) >= 64 and not any(payload[len(code):]), what


def test_the_idle_only_stream_is_stock_but_the_stub(stock7):
    """section7_idle_only: the stock engine with the idle stub and nothing of Waverider."""
    built = dsp.section7_idle_only(stock7)
    w = bootstream.walk(built)
    assert w.complete and w.stopped_at == len(built)
    site = dsp.l2_sw_to_load(dsp.IDLE_SITE_SW)
    assert bootstream.read_span(built, site, 6) == bytes.fromhex("3e061600" "00f5")
    # idle-only: the handler's call of the per-block routine stays stock
    assert bootstream.read_span(built, dsp.sw_to_load(dsp.CALL_SITE_SW), 6) == dsp.CALL_SITE_STOCK
    code = dsp.objects()["idle_load"]
    assert bootstream.read_span(built, dsp.dm_to_load(dsp.IDLE_DM), len(code)) == code
    assert bootstream.read_span(built, dsp.dm_to_load(dsp.IDLE_STATE_DM), 0x20) == bytes(0x20)
    # none of Waverider: the entry and the lookup stay stock
    assert bootstream.read_span(built, dsp.sw_to_load(dsp.ENTRY_SW), 8) == dsp.ENTRY_STOCK
    lookup = struct.unpack("<8I", bootstream.read_span(built, dsp.dm_to_load(dsp.LOOKUP_DM), 32))
    assert lookup == dsp.LOOKUP_STOCK
    final = bootstream.walk(stock7).final
    diff = [k for k in range(final.offset) if built[k] != stock7[k]]
    idle_off = bootstream.spans(stock7, site, 6)[0][0]
    assert diff and set(diff) <= set(range(idle_off, idle_off + 6))


def test_the_idle_stub_is_placed_and_returns_where_its_source_says():
    """idle_load.asm: its skip lands on wr_idle_out, it returns to the idle loop's top,
    and its variables sit in the state block's free tail, clear of the render loop's."""
    spec = json.loads((SHARC / "idle_load.json").read_text(encoding="utf-8"))
    assert int(spec["load_sw"], 16) == dsp.IDLE_SW == 0x16F500
    be = bytes.fromhex(spec["object_parcels_be"])
    offs = spec["instruction_offsets"]
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / "idle_load.asm").read_text().splitlines()]
    src = [c for c in src if c and not c.startswith(".") and not c.endswith(":")]
    at = {c: dsp.IDLE_SW + o // 2 for c, o in zip(src, offs)}
    assert at["R8 = DM(0x2de100);"] == 0x16F57B                   # wr_idle_out.
    assert at["R8 = DM(0x2de10c);"] == 0x16F55A                   # wr_idle_after.
    assert be[offs[src.index("IF GE JUMP 0x16f53d;")]:][:6].hex() == "06220016f53d"
    assert at["R11 = DM(0x2de13c);"] == 0x16F53D                  # wr_idle_busy.
    assert be[offs[-1]:].hex() == "063e00b88aab" and dsp.IDLE_RETURN_SW == 0xB88AAB
    # its DM: 0x2de100..0x2de13f, inside the state block, after PERC's scratch, before PERC's state
    from dnfw.perc import machines as PM
    assert dsp.PERC_SCRATCH_DM + 4 * len(PM.SC_WORDS) <= dsp.IDLE_STATE_DM
    assert dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES <= dsp.STATE_DM + dsp.STATE_BYTES == dsp.PERC_STATE_DM
    stores = {c for c in src if c.startswith("DM(")}
    assert stores <= {"DM(0x2de100) = R8;", "DM(0x2de104) = R9;", "DM(0x2de108) = R10;", "DM(0x2de134) = R11;",
                      "DM(0x2de114) = R9;", "DM(0x2de10c) = R8;", "DM(0x2de110) = R9;",
                      "DM(0x2de128) = R9;", "DM(0x2de12c) = R9;",
                      "DM(0x2c49d4) = R9;", "DM(0x2c59d4) = R9;", "DM(0x2c49dc) = R9;", "DM(0x2c59dc) = R9;",
                      "DM(0x2c49e0) = R9;", "DM(0x2c59e0) = R9;"}


def test_the_block_counter_goes_on_to_perc():
    spec = json.loads((SHARC / "block_count.json").read_text(encoding="utf-8"))
    assert int(spec["load_sw"], 16) == dsp.COUNT_SW == 0x16F600
    be = bytes.fromhex(spec["object_parcels_be"])
    assert be[spec["instruction_offsets"][-1]:].hex() == "063e00be0000"   # JUMP 0xbe0000, PERC in L2 (v0.11)
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / "block_count.asm").read_text().splitlines()]
    stores = {c for c in src if c.startswith("DM(")}
    assert stores == {"DM(0x2de11c) = R8;", "DM(0x2de120) = R9;", "DM(0x2de118) = R8;",
                      "DM(0x2c49d8) = R8;", "DM(0x2c59d8) = R8;", "DM(0x2de124) = R8;"}
    assert dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES >= 0x2DE124 and dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES <= dsp.PERC_STATE_DM


def test_the_entry_mark_does_the_displaced_load_and_returns_to_the_call():
    spec = json.loads((SHARC / "entry_mark.json").read_text(encoding="utf-8"))
    assert int(spec["load_sw"], 16) == dsp.EMARK_SW == 0x16F680
    be = bytes.fromhex(spec["object_parcels_be"])
    offs = spec["instruction_offsets"]
    assert be[offs[-1]:].hex() == "063e001c9fbc"                    # JUMP 0x1c9fbc, the cjump
    assert sharc_object.load_bytes(be[offs[-2]:offs[-1]]) == dsp.CALL_SITE_STOCK  # r4 = 0x268438, as stock
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / "entry_mark.asm").read_text().splitlines()]
    assert {c for c in src if c.startswith("DM(")} == {"DM(0x2de138) = R9;", "DM(0x2de13c) = R9;"}
    assert dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES >= 0x2DE140


def test_perc_saves_what_ping_restores_and_hands_on_to_resonator():
    lines = [ln.split("//", 1)[0].strip() for ln in (SHARC / "perc.asm").read_text().splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith(".") and not ln.endswith(":")]
    regs = [f"R{k}" for k in range(16)] + ["I0", "I1", "I2", "I3", "I4", "I5", "I12", "M0", "M1", "M2", "M3", "M4"]
    assert lines[:len(regs)] == [f"DM({0x2DDE00 + 4 * k:#x}) = {r};" for k, r in enumerate(regs)]
    assert f"JUMP {dsp.RINGS_SW:#x};" in lines
    # only the registers saved there are written (and no M, L, B or DAG2 other than I12)
    import re
    for ln in lines:
        m = re.match(r"(I|M|L|B)(\d+) =", ln)
        if m:
            assert f"{m.group(1)}{m.group(2)}" in ("I1", "I2", "I4", "I12"), ln
    assert not any(re.search(r"\bCALL\b|\bDO\b|\bRTS\b", ln) for ln in lines)

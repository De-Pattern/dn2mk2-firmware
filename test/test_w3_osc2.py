"""W3: Waverider's osc 2 (docs/w3-osc2.md) -- the contract, the layout, the links.

The runner gate (scripts/sharc_waverider_m5.py, step 3) holds osc2.asm / osc2b.asm to
dnfw.waverider.live bit for bit; these need no runner.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

from dnfw.waverider import dsp, live, pages, testtable

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARC = ROOT / "csrc" / "waverider" / "sharc"
sys.path.insert(0, str(ROOT / "scripts"))

TABLES = [testtable.table(), testtable.table()]


def blocks(n, osc2=None, trig_at=(0,)):
    return [(60.0, 0x3C00, 0, live.TUN1_ZERO, b in trig_at,
             {"atk": 0x4000, "ofs1": 0x4B00, **(osc2 or {})}) for b in range(n)]


def test_osc2_off_by_default_changes_nothing():
    """LEV (CHAR) 0 -- WaveTone's default, so every sound saved before W3 -- renders
    osc 1 alone, whatever osc 2's other controls say."""
    alone, _ = live.render_blocks(TABLES, blocks(12), 32, 0, "float32")
    with_others, _ = live.render_blocks(TABLES, blocks(12, {"tun2": 0x4700, "wav2": 0x7800,
                                                            "base": 0x7F00, "ofs2": 0,
                                                            "pd2": 0x6400}), 32, 0, "float32")
    assert alone == with_others
    assert live.DEFAULTS["char"] == 0 and not live.osc2_on(live.DEFAULTS)


def test_osc2_adds_and_ramps_in_from_silence():
    on = {"char": 0x6400, "tun2": 0x4700, "wav2": 0x2000}
    alone, _ = live.render_blocks(TABLES, blocks(8), 32, 0, "float32")
    both, _ = live.render_blocks(TABLES, blocks(8, on), 32, 0, "float32")
    assert alone != both
    # turned up with no new note: the first block's osc 2 share starts at gain/32
    late = [(60.0, 0x3C00, 0, live.TUN1_ZERO, b == 0,
             {"atk": 0x4000, "ofs1": 0x4B00, "char": 0x6400 if b >= 3 else 0}) for b in range(5)]
    a, _ = live.render_blocks(TABLES, late, 32, 0, "float32")
    assert a[:96] == alone[:96] and a[96:128] != alone[96:128]


def test_detune_is_semitones_from_osc_1():
    assert live.detuned(60.0, 0x4000) == 60.0
    assert live.detuned(60.0, 0x4700) == 67.0
    assert live.detuned(127.0, 0x4100) == 128.0            # increment() clamps it to 127
    assert live.increment(live.detuned(60.0, 0x4C00)) == live.increment(72.0)


def test_page_2_names_osc_2_on_its_records():
    assert pages.PAGES[1] == (242, 260, 243, 257, 0, 250, 244, 0)
    assert [pages.label(r) for r in pages.PAGES[1]] == ["DETN", "LEV", "POS", "TBL", "-",
                                                        "MPOS", "MLEV", "-"]
    used = set(pages.PAGES[0]) | set(pages.PAGES[1])
    assert not used & set(pages.UNUSED)


def test_osc2_code_and_data_fit_their_gaps():
    obj = dsp.objects()
    assert dsp.OSC2_CODE_DM >= dsp.READER_DM + len(obj["reader"]) + 64
    assert dsp.OSC2_CODE_DM + len(obj["osc2"]) + 64 <= dsp.RINGS_SCRATCH_DM
    assert dsp.OSC2B_CODE_DM >= dsp.PING_CODE_DM + len(obj["ping"]) + 64
    assert dsp.OSC2B_CODE_DM + len(obj["osc2b"]) + 64 <= dsp.PING_STATE_DM
    assert dsp.INC_TABLE_DM + 4 * live.NOTES <= dsp.OSC2_STATE_DM
    assert dsp.OSC2_BUF_DM + 128 <= dsp.DIRECTORY_DM
    assert dsp.OSC2_STATE_DM + 16 * dsp.OSC2_STATE_STRIDE <= dsp.OSC2_BUF_DM
    # scratch and the reader block: the state block's free words, clear of the reader blocks
    assert 0x2DDE88 < dsp.OSC2_SCRATCH_DM and dsp.OSC2_SCRATCH_DM + 16 <= dsp.OSC2_BLOCK_DM
    assert dsp.OSC2_BLOCK_DM + 32 <= dsp.READER_BLOCKS_DM


def test_osc2_objects_match_their_sources():
    spec = json.loads(dsp.CODE.read_text(encoding="utf-8"))
    for name in ("osc2", "osc2b"):
        src = (SHARC / f"{name}.asm").read_bytes().replace(b"\r\n", b"\n")
        assert spec[name]["source_sha256"] == hashlib.sha256(src).hexdigest(), name
        assert int(spec[name]["load_sw"], 16) == {"osc2": dsp.OSC2_SW, "osc2b": dsp.OSC2B_SW}[name]


def test_the_jumps_between_objects_land_on_their_labels():
    import sharc_resolve_jumps as R
    loop = (SHARC / "machine5_live.asm").read_text(encoding="utf-8")
    spec = json.loads((SHARC / "machine5_live.json").read_text(encoding="utf-8"))
    nxt = dsp.LOOP_SW + spec["instruction_offsets"][R.labels(loop)["wr_t5v_next"]] // 2
    a = (SHARC / "osc2.asm").read_text(encoding="utf-8")
    b = (SHARC / "osc2b.asm").read_text(encoding="utf-8")
    back = re.compile(r"JUMP (0x[0-9a-f]+);\s*// machine5_live.asm's wr_t5v_next")
    assert f"JUMP {dsp.OSC2_SW:#x};" in loop
    assert f"JUMP {dsp.OSC2B_SW:#x};" in a
    assert [int(x, 16) for x in back.findall(a)] == [nxt]
    assert [int(x, 16) for x in back.findall(b)] == [nxt]
    assert "DM(0x2dde8c) = R8;" in loop                      # osc 1's note, for osc 2

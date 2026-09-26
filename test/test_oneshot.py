"""dnfw.oneshot: the record arithmetic, the params->record map, and the bank.

All pure: no image needed.
"""

import struct

import pytest

from dnfw.oneshot import bank, params as PR, record as REC, samples as SM


def test_record_trigger_positions_and_step():
    rec = REC.trigger(sample_ptr=0x1000, length=1000, start=10, end=900, loop_start=500,
                      step=REC.Q31 // 2, reverse=False, loop=True)
    assert len(rec) == REC.RECORD_BYTES
    assert struct.unpack_from("<I", rec, REC.SAMPLE_PTR)[0] == 0x1000
    assert REC.get_q31(rec, REC.START) == 10 << 31
    assert REC.get_q31(rec, REC.END) == 900 << 31
    assert REC.get_q31(rec, REC.STEP) == REC.Q31 // 2
    assert rec[REC.ACTIVE] == 1 and rec[REC.LOOP] == 1 and rec[REC.REVERSE] == 0
    assert REC.get_q31(rec, REC.PHASE) == 10 << 31


def test_record_reverse_negates_step_and_seeds_from_end():
    rec = REC.trigger(sample_ptr=1, length=100, start=0, end=100, loop_start=0,
                      step=REC.Q31, reverse=True, loop=False)
    assert REC.get_q31(rec, REC.STEP) == -REC.Q31
    assert rec[REC.REVERSE] == 1
    assert REC.get_q31(rec, REC.PHASE) == 99 << 31


def test_record_rejects_bad_order():
    with pytest.raises(ValueError):
        REC.trigger(sample_ptr=0, length=100, start=50, end=40, loop_start=0,
                    step=REC.Q31, reverse=False, loop=False)


def test_params_positions_and_step_match_the_adapter_math():
    # LEN >= 127 means the whole sample; STRT/LOOP scale by /128
    s, e, p = PR.positions(length=1000, strt=0, len_=127, loop=0)
    assert (s, e, p) == (0, 1000, 0)
    s, e, p = PR.positions(length=1000, strt=64, len_=64, loop=32)
    assert s == (64 * 1000) >> 7
    assert e == min(s + ((64 * 1000) >> 7), 1000)
    assert p == (32 * 1000) >> 7
    # centre tune is unity-ish; reverse negates
    assert PR.step(64, False) > 0
    assert PR.step(64, True) == -PR.step(64, False)


def test_params_record_matches_record_module():
    rec = PR.record_fields(pointer=0x2000, length=4096, tune=64, play=3, strt=0, len_=127, loop=64)
    assert struct.unpack_from("<I", rec, REC.SAMPLE_PTR)[0] == 0x2000
    assert rec[REC.REVERSE] == 1 and rec[REC.LOOP] == 1     # play 3 = reverse loop
    assert REC.get_q31(rec, REC.END) == 4096 << 31


def test_step_table_has_256_entries():
    tbl = PR.step_table()
    assert len(tbl) == 256 * 8
    lo, hi = struct.unpack_from("<q", tbl, 0), None
    # entry [64] forward is the unity-ish speed; [128+64] is its negation
    fwd = struct.unpack_from("<q", tbl, 64 * 8)[0]
    rev = struct.unpack_from("<q", tbl, (128 + 64) * 8)[0]
    assert rev == -fwd


def test_bank_layout_and_pointers_aligned():
    data, entries = bank.build(0x298800, [SM.silence(16), SM.silence(32)])
    assert struct.unpack_from("<I", data, 0)[0] == bank.MAGIC
    assert struct.unpack_from("<I", data, 4)[0] == 2
    for e in entries:
        assert e["pointer"] % 4 == 0
    assert entries[1]["pointer"] > entries[0]["pointer"]


def test_bank_refuses_overflow():
    with pytest.raises(ValueError):
        bank.build(0x298800, [SM.silence(100000)], limit=1024)


def test_samples_are_int16_and_bounded():
    for pcm in (SM.chirp(256), SM.saw(2), SM.silence(64)):
        assert all(-32768 <= v <= 32767 for v in pcm)
    assert set(SM.silence(10)) == {0}

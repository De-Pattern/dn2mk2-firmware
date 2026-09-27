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


def test_params_positions_follow_the_dt2_records():
    # STRT / LEN / LOOP are whole 8.8 values; 0x7800 (120.00) is the sample's end
    assert PR.positions(length=1000, strt=0, len_=PR.FULL, loop=0) == (0, 1000, 0)
    s, e, p = PR.positions(length=1000, strt=0x3C00, len_=0x1E00, loop=0x3C00 + 1)
    assert s == 500 and e == 750 and p == 500           # half, a quarter; LOOP - 1 = half
    s, e, p = PR.positions(length=1000, strt=0x3C00, len_=0x1E00, loop=0x1E00 + 1)
    assert p == 250                                      # a loop point before S is kept
    # LOOP 0 is OFF: the loop returns to the start
    assert PR.positions(length=1000, strt=0x1E00, len_=PR.FULL, loop=0)[2] == 250
    # a loop point at or past the end falls back to the start
    assert PR.positions(length=1000, strt=0, len_=0x1E00, loop=0x7000)[2] == 0
    # the reciprocal rounds up, so a full LEN reaches the end and the clamp holds it there
    assert 0 <= PR.scale(PR.FULL, 23540) - 23540 <= 8
    assert PR.positions(length=23540, strt=PR.FULL, len_=PR.FULL, loop=0) == (23539, 23540, 23539)


def test_play_modes_are_the_dt2_formatters_order():
    # 0 REV, 1 REV.L, 2 FWD.L, 3 FWD (the DT2 formatter 0x400e16ca)
    assert [PR.play_mode(v) for v in range(4)] == [(True, False), (True, True),
                                                    (False, True), (False, False)]
    assert PR.step(64, False) > 0
    assert PR.step(64, True) == -PR.step(64, False)


def test_frame_offsets_are_the_dt2_slots():
    assert {k: PR.frame_offset(k) for k in PR.INDICES} == {
        "TUNE": 0, "PLAY": 2, "SAMP": 6, "STRT": 12, "LEN": 14, "LOOP": 16}
    assert PR.sound_words(tune=64, play=3, samp=2, strt=0, len_=PR.FULL, loop=0) == {
        25: 0x4000, 26: 0x300, 28: 2, 31: 0, 32: 0x7800, 33: 0}
    # the ColdFire sends each at half, rounded up (0x6117 -> 0x308c, 0xffff -> 0x8000)
    assert PR.frame_words(tune=64, play=3, samp=2, strt=0, len_=PR.FULL, loop=0) == {
        25: 0x2000, 26: 0x180, 28: 1, 31: 0, 32: 0x3C00, 33: 0}
    assert PR.half(0x6117) == 0x308C and PR.half(0xFFFF) == 0x8000 and PR.half(0x2D00) == 0x1680
    # SAMP's lowest bit is lost: 1 and 2 play the same bank entry
    assert [PR.bank_slot(s, 8) for s in range(6)] == [0, 1, 1, 2, 2, 3]
    assert PR.bank_slot(40, 8) == 0


def test_params_record_matches_record_module():
    rec = PR.record_fields(pointer=0x2000, length=4096, tune=64, play=1, strt=0,
                           len_=PR.FULL, loop=0)
    assert struct.unpack_from("<I", rec, REC.SAMPLE_PTR)[0] == 0x2000
    assert rec[REC.REVERSE] == 1 and rec[REC.LOOP] == 1     # play 1 = REV.L
    assert REC.get_q31(rec, REC.END) == 4096 << 31
    fwd = PR.record_fields(pointer=1, length=100, tune=64, play=3, strt=0, len_=PR.FULL, loop=0)
    assert fwd[REC.REVERSE] == 0 and fwd[REC.LOOP] == 0      # play 3 = FWD


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

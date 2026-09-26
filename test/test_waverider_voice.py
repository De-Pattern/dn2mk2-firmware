"""dnfw.waverider.voice: the DN2 voice-path map and the M2 signal arithmetic."""

import math

import pytest

from dnfw.waverider import voice as V


def test_track_records_are_0x234_apart_from_0x2554b8():
    assert V.track_record(0) == 0x2554B8
    assert V.track_record(15) - V.track_record(14) == 0x234
    with pytest.raises(ValueError):
        V.track_record(16)


def test_machine_state_uses_each_machines_stride():
    assert V.machine_state(1, 0) == 0x241298 + 0x2408      # WaveTone, track 0
    assert V.machine_state(1, 1) - V.machine_state(1, 0) == 0x30C
    assert V.machine_state(3, 2) == 0x241298 + 0x8348 + 2 * 0x55C


def test_track_buffers_pointer_array():
    assert V.TRACK_BUFFERS == 0x254A60


def test_float_bits_round_trip():
    for x in (0.0, 1.0, -0.5, 3.1415927):
        assert V.bits_f32(V.f32_bits(x)) == pytest.approx(x, rel=1e-7)
    assert V.f32_bits(1.0) == 0x3F800000


def test_peak_and_rms():
    assert V.peak([0.1, -0.7, 0.3]) == 0.7
    assert V.rms([1.0, -1.0]) == 1.0
    assert V.rms([]) == 0.0


def test_fit_gain_recovers_a_scale():
    want = [math.sin(k / 5) for k in range(200)]
    got = [0.25 * w for w in want]
    fit = V.fit_gain(got, want)
    assert fit.gain == pytest.approx(0.25)
    assert fit.correlation == pytest.approx(1.0)
    assert fit.residual_rms == pytest.approx(0.0, abs=1e-12)


def test_fit_gain_of_unrelated_signals_is_uncorrelated():
    a = [math.sin(k / 3) for k in range(3000)]
    b = [math.cos(k / 7.1) for k in range(3000)]
    assert abs(V.fit_gain(a, b).correlation) < 0.1


def test_fit_gain_rejects_length_mismatch():
    with pytest.raises(ValueError):
        V.fit_gain([1.0], [1.0, 2.0])


def test_loop_to_repeats_and_cuts():
    assert V.loop_to([1.0, 2.0, 3.0], 7) == [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0]
    assert V.loop_to([], 3) == [0.0, 0.0, 0.0]


def test_unpack_int16_pairs_low_half_first():
    assert V.unpack_int16_pairs([0xFFFF0001, 0x80007FFF]) == [1, -1, 32767, -32768]


# -- Milestone 3 landmarks ------------------------------------------------------

def test_machine_from_nibble_passes_0_to_4_and_squashes_5():
    assert [V.machine_from_nibble(n) for n in range(6)] == [0, 1, 2, 3, 4, 0]
    # a lookup whose entry 5 is set admits type 5
    assert V.machine_from_nibble(5, [0, 1, 2, 3, 4, 5, 0, 0]) == 5


def test_type_clamp_stock_ceiling_is_4_raised_is_5():
    assert V.type_clamp(5) == 4                 # stock: type 5 squashed
    assert V.type_clamp(5, ceiling=5) == 5      # raised: type 5 admitted
    assert V.type_clamp(-3) == 0                # the max(.,0) floor


def test_m3_landmarks_are_the_measured_addresses():
    assert V.TRIG_CELL == 0x138FC
    assert V.NOTE_ON_FN == 0xB82440
    assert V.AMP_STAGE == 0xB80345
    assert V.MACHINE_LOOKUP == 0x25D748
    assert V.TYPE_CLAMP_IMM == 0x1C294A
    assert V.TYPE5_ENTRY == 0x1C9448 and V.TYPE5_RESUME == 0x1C944C
    assert V.READER_SW == 0x180000 and V.MACHINE5_SW == 0x180100
    # the four stock per-type render loops are all inside sw 0x1c8ef1
    assert all(0x1C8EF1 <= pc < 0x1C9B73 for pc in V.PER_TYPE_RENDER_LOOPS)

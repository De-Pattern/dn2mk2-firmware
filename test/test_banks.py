"""v0.65 PROJECT RAM banks (docs/banks.md): the DSP's side, on its exact model.

SAMP's whole word carries the bank in its low byte (SM.BANK_TAGS); bank A is the pool's own
directory page, banks B..D their pages at SM.BANK_AREA. SL.slot_plays (the ColdFire gates' DSP
rule) must answer as the model plays."""

from __future__ import annotations

import pytest

from dnfw.sampler import live as SL
from dnfw.sampler import machines as SM

ONE = SM.TYPE_OF["ONESHOT"]


def _render(h, word, blocks=4, mtype=ONE):
    h.set_word(SM.SAMP_REC, word)
    out = []
    for b in range(blocks):
        out += h.block(mtype, 60.0, b == 0)
    return out


def _page(h, bank):
    return h.L.pool + SM.BANK_AREA + (bank - 1) * SM.BANK_PAGE


def _install(h, bank, slot, from_slot, count=None):
    """bank BANK's page with slot SLOT holding bank A's FROM_SLOT entry"""
    pg = _page(h, bank)
    h.mem.put(pg, SM.BANK_MAGIC)
    h.mem.put(pg + 4, slot + 1 if count is None else count)
    for j in range(4):
        h.mem.put(pg + 8 + 16 * slot + 4 * j, h.mem.get(h.L.pool + 8 + 16 * from_slot + 4 * j))


def _fresh():
    h = SL.Harness(0)
    h.defaults()
    return h


def test_the_layout():
    assert SM.TABLE_AREA - SM.BANK_AREA == (SM.BANK_N - 1) * SM.BANK_PAGE
    assert SM.REC_OFFSET + SM.REC_BYTES == SM.BANK_AREA
    assert SM.BANK_SLICES + SM.POOL_SLOTS * SM.SLICE_TABLE_BYTES <= SM.BANK_PAGE
    assert [SM.bank_of(t) for t in SM.BANK_TAGS] == [0, 1, 2, 3]
    assert SM.bank_of(0x1F) == 0 and SM.bank_of(0x20) == 1 and SM.bank_of(0xFF) == 3


@pytest.mark.parametrize("bank", [1, 2, 3])
def test_a_bank_slot_plays_its_own_entry_and_bank_a_is_unchanged(bank):
    h = _fresh()
    a1 = _render(h, 2 << 8)                         # bank A, SAMP 2 (slot 1)
    h = _fresh()
    a0 = _render(h, 1 << 8)                         # bank A, SAMP 1 (slot 0)
    assert any(abs(x) > 1e-6 for x in a1) and a0 != a1
    h = _fresh()
    _install(h, bank, 0, 1)                         # bank B..D slot 0 = A's slot 1
    assert _render(h, 1 << 8 | SM.BANK_TAGS[bank]) == a1
    h = _fresh()
    _install(h, bank, 0, 1)
    assert _render(h, 1 << 8) == a0                 # the same number in bank A: A's own
    assert SL.slot_plays(h.mem.get, h.L.pool, 0, bank)


@pytest.mark.parametrize("case", ["magic", "count", "empty"])
def test_a_bank_page_without_its_magic_or_past_its_count_is_silent(case):
    h = _fresh()
    _install(h, 1, 3, 1, count=2 if case == "count" else None)
    if case == "magic":
        h.mem.put(_page(h, 1), SM.POOL_MAGIC)       # bank A's magic is not a bank page's
    slot = 3
    if case == "empty":
        slot = 0                                    # an entry never written: no frames
    out = _render(h, (slot + 1) << 8 | SM.BANK_TAGS[1])
    assert not any(abs(x) > 1e-6 for x in out)
    assert not SL.slot_plays(h.mem.get, h.L.pool, slot, 1)


def test_a_small_offset_on_the_low_byte_keeps_the_bank():
    """an LFO's raw offset on SAMP's word moves its low byte a little: the bank holds"""
    h = _fresh()
    _install(h, 2, 0, 1)
    ref = _render(h, 1 << 8 | 0x80)
    for lo in (0x61, 0x9F):
        h = _fresh()
        _install(h, 2, 0, 1)
        assert _render(h, 1 << 8 | lo) == ref


def test_bank_a_recorder_slots_still_play_without_the_count():
    h = _fresh()
    k = SM.REC_FIRST + 1
    for j in range(4):
        h.mem.put(h.L.pool + 8 + 16 * k + 4 * j, h.mem.get(h.L.pool + 8 + 4 * j))
    assert any(abs(x) > 1e-6 for x in _render(h, (k + 1) << 8))
    # the same slot number in bank B is an ordinary slot of B's, gated by its count
    h2 = _fresh()
    _install(h2, 1, 0, 0)
    assert not any(abs(x) > 1e-6 for x in _render(h2, (k + 1) << 8 | 0x40))


def test_slices_made_on_the_instrument_come_from_the_banks_own_slice_area():
    n = 3000
    ramp = [k / n for k in range(n)]
    sl_ = SM.TYPE_OF["SLICE"]
    cuts = [(0, 900, 0), (900, 2100, 900), (2100, 3000, 2100)]

    def play(slce, in_bank):
        h = SL.Harness(0, samples=[ramp], rates=[1.0], fmts=[0])
        h.defaults()
        ent = h.L.pool + 8
        h.mem.put(ent + 12, h.mem.get(ent + 12) | len(cuts) << 8 | 1 << 16)
        word = 1 << 8
        if in_bank:
            _install(h, 1, 0, 0)
            area = _page(h, 1) + SM.BANK_SLICES
            word |= 0x40
        else:
            area = h.L.pool + SM.SLICE_AREA
        for j, (a, b, lp) in enumerate(cuts):
            for w, x in enumerate((a, b, lp)):
                h.mem.put(area + 12 * j + 4 * w, x)
        h.set(SM.SLICE_REC, slce)
        out = _render(h, word, 120, sl_)
        nz = [x for x in out if abs(x) > 1e-4]
        return nz[64:-64]
    for k, (a, b, _) in enumerate(cuts):
        nz = play(2 * (k + 1), True)
        assert abs(min(nz) - a / n) < 0.05 and abs(max(nz) - b / n) < 0.05, k
        assert nz == play(2 * (k + 1), False)

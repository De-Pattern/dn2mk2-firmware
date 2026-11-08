"""FASCIA on the ColdFire (v0.45, type 18; dnfw.fascia.machines, docs/fascia.md): the panel
mirrors the model, each control sits on a stock record of the right shape, the choices' spans
and detent values are the model's, and every table that is indexed by machine type knows 18.
The ship gate's "fascia", "functurn" and "slides" steps are the behavioural evidence."""

import pathlib
import re
import struct

import pytest

from dnfw.fascia import machines as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE, RECORDS, RECORD = 0x40000400, 0x401F7F94, 60


@pytest.fixture(scope="module")
def stock():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111)).container.find(3).unpack()


def record(stock, rid):
    """(page, slot, min, max, default, cc, modulation mask) of stock record RID"""
    at = RECORDS - BASE + RECORD * rid
    w = struct.unpack(">15I", stock[at:at + RECORD])
    cc = w[6] >> 16
    return w[0], w[1], w[2], w[3], w[4], None if cc == 0xFFFF else cc, w[9]


def test_the_panel_is_the_models():
    from dnfw.fascia import model as M
    assert F.PAGES == M.PAGES and F.CHOICES == M.CHOICES and F.DEFAULTS == M.DEFAULTS
    assert len(F.CONTROLS) == 24 and set(F.CONTROLS) == set(M.DEFAULTS) == set(F.SLOTS)
    assert set(F.LONG_NAMES) == set(F.CONTROLS)


def test_each_control_on_its_own_stock_record(stock):
    rids = [F.SLOTS[c][0] for c in F.CONTROLS]
    slots = [F.SLOTS[c][1] for c in F.CONTROLS]
    assert len(set(rids)) == 24 and len(set(slots)) == 24
    for c in F.CONTROLS:
        rid, slot, lo, top = F.SLOTS[c]
        page, rslot, rmin, rmax, _df, cc, mask = record(stock, rid)
        assert rslot == slot, c                            # the record's own slot
        assert (rmin >> 8, (rmax >> 8) - (rmin >> 8)) == (lo, top), c
        assert mask != 0, f"{c}: its record is no LFO destination"
        assert cc == F.CC.get(c), c                         # a CC exactly where the record has one
        if F.is_choice(c):
            assert page == 1 and top in (100, 120)          # WaveTone's partial-range records
        else:
            assert (rmin, rmax) == (0, 0x7F00), c           # the DSP reads word >> 8 as the panel's 0..127
            assert page in (0, 1)
        if page == 0:
            assert F.FM_SLOT_FIRST <= slot <= F.FM_SLOT_LAST and cc is None
            assert any(a <= rid <= b for a, b in F.FM_OWNED)
        else:
            assert 238 <= rid <= 262 and 25 <= slot <= 49


def test_fm_owned_is_exactly_fm_tones_records_on_slots_50_to_64(stock):
    on = sorted(r for r in range(321) if record(stock, r)[0] == 0
                and F.FM_SLOT_FIRST <= record(stock, r)[1] <= F.FM_SLOT_LAST)
    assert on == sorted(r for a, b in F.FM_OWNED for r in range(a, b + 1))


def test_choices_are_the_models_and_four_detents_reach_every_option():
    from dnfw.fascia import model as M
    for c in F.CHOICES:
        n = len(F.CHOICES[c])
        for k in range(128):
            assert F.option(c, k) == M.choice(c, k) == (k * n) >> 7
        for o in range(n):                                  # each option's detent value lands on it
            assert F.option(c, F.knob(c, F.rep_word(c, o))) == o
        top = F.SLOTS[c][3]
        seen = {F.option(c, F.knob(c, v << 8)) for v in range(top + 1)}
        assert seen == set(range(n))                        # every option reachable on the record


def test_defaults_are_the_models():
    from dnfw.fascia import model as M
    dw = F.default_words()
    for c in F.CONTROLS:
        k = F.knob(c, dw[c])
        if F.is_choice(c):
            assert F.option(c, k) == M.choice(c, M.DEFAULTS[c])
        else:
            assert k == M.DEFAULTS[c] and dw[c] == M.DEFAULTS[c] << 8


def test_coldfire_type_18():
    from dnfw.waverider import coldfire as CF
    from dnfw.waverider import pages as P
    from dnfw.mnm import machines as MM
    assert F.TYPE == 18 and F.TYPE in CF.NEW_TYPES and CF.TYPES_LAST == P.TYPES_LAST == 18
    assert CF.MACHINE_NAMES[F.TYPE] == ("Fascia", "FSC")
    lst = list(CF.LIST_NEW)
    if not F.LISTED:
        assert F.TYPE not in lst
        return
    assert lst.index(F.TYPE) == lst.index(MM.TYPES[-1]) + 1 == lst.index(8) - 1   # after the MnM's, before the samples
    assert not CF.SAMPLER_FIRST <= F.TYPE <= CF.SAMPLER_LAST                   # the synth group: no divider
    assert f"cmpi.l  #{F.TYPE},%d0" in CF.SHIMS and f"cmpi.l  #{F.TYPE},%d3" in CF.SHIMS2


def test_header_kinds_names_and_tables():
    from dnfw.waverider import pages as P
    hdr = P.c_header()
    assert "#define WR_KINDS 14" in hdr and f"#define FSC_KIND {F.KIND}" in hdr
    assert "#define WR_NAMED_LO 208" in hdr and "#define WR_NAMED_HI 262" in hdr
    named = P.fsc_named()
    for c in F.CONTROLS:
        assert named[F.SLOTS[c][0]] == (F.LONG_NAMES[c], c)
    for r in F.UNUSED_RECORDS:
        assert named[r] == ("Unused", "-")
    assert "static const unsigned short fsc_rid[FSC_N] = {239, 243, 241," in hdr
    # mnm_index and SMP_IDX give FASCIA's kind no row of theirs
    assert f"if (kind == {F.KIND})" not in hdr.split("mnm_index", 1)[1].split("}", 1)[0]
    src = P.source(0x46AC0000, 0x46AC0100)
    assert "fsc_descriptors:" in src and src.count("fsc_title_") >= 6


def test_dsp_silent_hook_and_lookup():
    from dnfw.waverider import dsp
    from dnfw.sampler import program as SP
    from dnfw.sampler import live as SL
    t = struct.unpack(f"<{dsp.MACHINE_TYPES + 1}I", dsp.lookup16())
    assert dsp.MACHINE_TYPES >= F.TYPE + 1 and t[1 + F.TYPE] == dsp.SMP_ENGINE_SLOT
    text = SP.program(SL.layout(), dsp.PING_SW)
    assert SP.FASCIA_MUTE and "fmute" in text and f"R12 = {F.TYPE:#x};" in text


def test_slides_rows():
    from dnfw import slides as SL
    assert set(SL.FASCIA_SLIDE) == {F.SLOTS[c][1] for c in F.CONTROLS if not F.is_choice(c)}
    assert not set(SL.FASCIA_SLIDE) & set(SL.FASCIA_STEP) and len(SL.FASCIA_STEP) == 5


def test_csrc_uses_four_detents_for_every_choice():
    fmt = (ROOT / "csrc/sampler/fmt.c").read_text()
    assert "#define FSC_DETENTS 4" in fmt and "fq_click ? 1 : FSC_DETENTS" in fmt
    assert max(len(v) for v in F.CHOICES.values()) == 10    # BODB: more than eight, still four


def test_docs_table_is_the_slot_table():
    doc = (ROOT / "docs/fascia.md").read_text()
    rows = re.findall(r"^\| (\w+) \| (\d+) \| (\d+) \| (\d+)\.\.(\d+) \|", doc, re.M)
    got = {c: (int(r), int(s), int(lo), int(hi) - int(lo)) for c, s, r, lo, hi in rows}
    assert got == {c: (F.SLOTS[c][0], F.SLOTS[c][1], F.SLOTS[c][2], F.SLOTS[c][3]) for c in F.CONTROLS}

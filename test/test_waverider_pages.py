"""Our machines' own SYN pages (Waverider's M7/M8 mechanism; PERC's since v0.11): the
committed code spec, the hooks it installs, and PERC's names."""

from __future__ import annotations

import json
import pathlib
import struct

from dnfw.waverider import coldfire as CF
from dnfw.perc import machines as PM
from dnfw.waverider import pages

SPEC = json.loads((pathlib.Path(__file__).parents[1] / "src/dnfw/mods/waverider_code.json").read_text())
CHUNK = bytes.fromhex(SPEC["chunk"]["code"])


def edit(va: int) -> bytes:
    (e,) = [e for e in SPEC["edits"] if e["va"] == va]
    return bytes.fromhex(e["new"])


def jsr_target(code: bytes) -> int:
    assert code[:2] == bytes.fromhex("4eb9")
    return struct.unpack(">I", code[2:6])[0]


def in_chunk(va: int) -> bool:
    return pages.LOAD <= va < pages.LOAD + len(CHUNK)


def test_the_chunk_runs_from_its_load_address():
    assert SPEC["chunk"]["load"] == pages.LOAD
    assert len(CHUNK) < 0x4000     # clear of the platform runtime at 0x46710000


def test_every_m7_site_calls_into_the_chunk():
    for site in (CF.COUNT_SITE, CF.PAGE_SITE, CF.LABEL_SITE, CF.ICON_SITE):
        assert in_chunk(jsr_target(edit(site))), hex(site)


def test_the_icon_site_is_a_call_and_a_nop():
    # a bne.s cannot reach the stock target (0xa0 is -96 as a byte); the routine
    # moves its own return address instead, so the displaced bne is a nop
    assert len(edit(CF.ICON_SITE)) == len(CF.ICON_STOCK) == 8
    assert edit(CF.ICON_SITE)[6:] == bytes.fromhex("4e71")


def test_the_descriptors_name_the_owners_layout():
    ids = struct.pack(">8I", *pages.PAGES[0])
    assert ids in CHUNK
    assert struct.pack(">8I", *pages.PAGES[1]) in CHUNK


def test_the_strings_carry_an_unshareable_header():
    for text in (pages.SUBTITLE, *pages.TITLES):
        raw = text.encode() + b"\0"
        at = CHUNK.find(raw)
        assert at >= 12, text
        assert struct.unpack(">IIi", CHUNK[at - 12:at]) == (len(text), len(text), -1)


def test_perc_pages_are_the_eight_parameters_then_type_and_the_effects():
    # v0.12: page 1 is the machine's eight (the Machinedrum's page); page 2 TYPE, then
    # AMD AMF EQF / EQG FLTF FLTW FLTQ
    assert pages.PAGES[0] == tuple(r for r, *_ in PM.PARAMS)
    # v0.20: the Machinedrum's FX page, AMD AMF EQF EQG / FLTF FLTW FLTQ, TYPE in SRR's place
    assert pages.PAGES[1] == (*(r for r, *_ in PM.FX_PARAMS), PM.TYPE_REC[0])
    used = set(pages.PAGES[0]) | set(pages.PAGES[1])
    assert len(used) == 16 and not used & set(pages.UNUSED)
    assert pages.LABELS == {}                       # every label comes from the record's name
    named = {r: sh for r, _lo, sh in pages.named()}
    assert [named[r] for r in pages.PAGES[1]] == ["AMD", "AMF", "EQF", "EQG", "FLTF", "FLTW", "FLTQ", "TYPE"]


def test_every_machine_names_its_eight_parameters():
    names = pages.perc_names()
    assert len(names) == PM.N
    for k, row in enumerate(names):
        assert [sh for _, sh in row] == list(PM.PNAMES[PM.NAMES[k]])
        assert all(lo and len(sh) <= 4 for lo, sh in row)
        assert all((sh == "-") == (lo == "Unused") for lo, sh in row)


def test_the_page_type_matches_the_dsp():
    # page.c's perc_of and dnfw.perc.program both: (min(v >> 8, 127) * N) >> 7
    from dnfw.perc import live as PL
    h = PL.Harness(0)
    for k in range(PM.N):
        h.set_controls(k, [0.5] * 8)
        word = h.mem.get((PM.FRAME + PM.frame_offset(PM.TYPE_REC[1])) & ~3)
        off = PM.FRAME + PM.frame_offset(PM.TYPE_REC[1])
        word = (word >> 16) & 0xFFFF if off & 2 else word & 0xFFFF
        assert pages.type_of(word) == k


def test_the_c_header_carries_perc_tables():
    h = pages.c_header()
    assert f"#define PERC_N {PM.N}" in h
    for name in PM.NAMES:
        assert f'"{name}"' in h


def test_the_grid_site_calls_wr_grid_then_two_nops():
    new = edit(CF.GRID_SITE)
    assert len(new) == len(CF.GRID_STOCK) == 10
    assert in_chunk(jsr_target(new)) and new[6:] == bytes.fromhex("4e714e71")


def test_the_renderer_sits_between_the_assembly_and_the_runtime():
    assert pages.C_LOAD - pages.LOAD >= 0x100
    assert pages.LOAD + len(CHUNK) <= pages.C_END


def test_no_wave_display_chunk_since_perc():
    from dnfw.mods.waverider import SPEC
    assert "spans_chunk" not in SPEC


# -- the sample machines (v0.13, docs/sampler.md) -----------------------------------------

def test_each_sample_machine_has_its_descriptor_and_names():
    from dnfw.sampler import machines as SM
    assert len(pages.SMP_PAGES) == len(SM.NAMES) == 6               # v0.19: SLICE
    for k, ids in enumerate(pages.SMP_PAGES):
        at = CHUNK.find(struct.pack(">8I", *ids))
        assert at >= 8, SM.NAMES[k]
        assert struct.unpack(">I", CHUNK[at + 32:at + 36])[0] == pages.TAG
    for name in SM.NAMES:
        named = pages.smp_named(name)
        assert set(named) == set(range(238, 263))
        for rid, short, long_ in SM.PAGES.get(name, SM.PAGES["ONESHOT"]):
            if rid:
                assert named[rid] == (long_, short)
    hdr = pages.c_header()
    # a kind (is_wr: the type - 4) for every type of ours, 5..TYPES_LAST (v0.26: 14.. too)
    assert f"#define WR_KINDS {pages.TYPES_LAST - 4}" in hdr and "#define SMP_KIND0 4" in hdr
    assert '"KICK", "SNARE", "HAT", "BEAT"' in hdr


def test_the_samples_play_modes_and_grids_agree_with_the_dsp():
    # page.c draws PLAY as smp_play[v * 4 / 128] and GRID as smp_grids[v / 24]: the
    # DSP's own readings (dnfw.sampler.program: mode = v * 4 >> 7, g = v // 24)
    from dnfw.sampler import machines as SM
    assert SM.PLAY_MODES[127 * 4 // 128] == "FWD" and SM.PLAY_MODES[0] == "REV"
    assert [SM.GRIDS[min(v // 24, 4)] for v in (0, 24, 48, 72, 96, 120)] == [4, 8, 16, 32, 64, 64]


def test_every_new_type_has_our_pages():
    """v0.19 shipped with pages.TYPES_LAST at 12 while the machine list went to 13: a SLICE
    track got WaveTone's pages and stock tables read past their end. Every type the list
    offers is one the page shims claim, and every sample machine has its page."""
    from dnfw.waverider import coldfire as CF
    from dnfw.waverider import pages as P
    from dnfw.sampler import machines as SM
    assert P.TYPES_LAST == CF.TYPES_LAST == max(CF.NEW_TYPES)
    assert P.NEW_TYPE == CF.NEW_TYPES[0]
    assert len(P.SMP_PAGES) == CF.SAMPLER_LAST - CF.SAMPLER_FIRST + 1 == len(SM.NAMES)
    assert all(SM.TYPE_OF[n] == CF.SAMPLER_FIRST + k for k, n in enumerate(SM.NAMES))

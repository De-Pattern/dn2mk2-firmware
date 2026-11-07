"""v0.40: the +Drive library's folders inside folders (dnfw.sampler.libtree, csrc/sampler/lib.c).

takton's report: a pack's nested folders ("TRANCE STARTER PACK/KICKS/...") showed as many
top-level folders reading "TRANCE STARTER PAC". The model here is what the emulator checks
(scripts/emu_lib_nest.py) hold the firmware's tree to, at every power cut."""
from __future__ import annotations

import pathlib
import re

from dnfw.sampler import libtree as LT

ROOT = pathlib.Path(__file__).resolve().parents[1]


def table(recs):
    t = bytearray(64 * 32)
    for f, r in recs.items():
        t[32 * f:32 * f + 32] = r
    return bytes(t)


def test_an_old_library_is_all_top_level_folders_as_it_was():
    # v0.39's import: the whole path as one flat name, 31 characters at most, byte 31 zero
    old = table({0: LT.record("INCOMING"), 1: LT.record("RECORDED"),
                 2: LT.record("TRANCE STARTER PACK/KICKS"), 3: LT.record("TRANCE STARTER PACK/LEADS/SYNTH")})
    assert LT.tree(old) == [-1] * LT.FOLDERS
    assert LT.names(old)[2:4] == ["TRANCE STARTER PACK/KICKS", "TRANCE STARTER PACK/LEADS/SYNTH"]
    assert old[32 * 3 + 31] == 0


def test_a_folder_inside_a_folder_and_its_path():
    t = table({2: LT.record("TRANCE STARTER PACK"), 3: LT.record("KICKS", 2), 5: LT.record("808", 3),
               6: LT.record("TRANCE STARTER PACK", 3)})
    par = LT.tree(t)
    assert par[2] == -1 and par[3] == 2 and par[5] == 3 and par[6] == 3
    assert LT.path(t, 5) == "TRANCE STARTER PACK/KICKS/808" and LT.depth(par, 5) == 3
    # what an older build reads: the folder's own name (the tag after its end)
    assert LT.names(t)[6] == "TRANCE STARTER PACK" and t[32 * 6 + 31] == 0x83


def test_a_record_inside_a_folder_keeps_thirty_letters_and_its_tag():
    r = LT.record("X" * 40, 7)
    assert r[:30] == b"X" * 30 and r[30] == 0 and r[31] == 0x87
    assert LT.record("Y" * 40)[:31] == b"Y" * 31 and LT.record("Y" * 40)[31] == 0


def test_whatever_the_records_hold_the_tree_is_sound_and_every_folder_in_it():
    dangling = table({4: LT.record("ORPHAN", 9)})                  # its parent dropped by an older build
    assert LT.tree(dangling)[4] == -1
    selfp = table({4: LT.record("SELF", 4)})
    assert LT.tree(selfp)[4] == -1
    loop = table({4: LT.record("A", 5), 5: LT.record("B", 4)})       # (by index order: A cut, B under A)
    assert LT.tree(loop)[4] == -1 and LT.tree(loop)[5] == 4
    torn = bytearray(table({2: LT.record("TOP"), 4: LT.record("T" * 31)}))
    torn[32 * 4 + 31] = 0x82                                        # a tag after 31 letters: no tag
    assert LT.tree(bytes(torn))[4] == -1 and LT.names(bytes(torn))[4] == "T" * 31
    badtag = table({2: LT.record("TOP")})
    badtag = bytearray(badtag)
    badtag[32 * 3:32 * 3 + 4] = b"ODD\0"
    badtag[32 * 3 + 31] = 0x42                                      # not 0x80 | parent
    assert LT.tree(bytes(badtag))[3] == -1


def test_six_levels_deep_at_most_a_deeper_chain_from_the_top():
    recs = {10: LT.record("L1")}
    for d in range(2, 9):                                           # L1 .. L8, each inside the last
        recs[9 + d] = LT.record(f"L{d}", 8 + d)
    par = LT.tree(table(recs))
    assert all(LT.depth(par, f) <= LT.DEPTH for f in range(64))
    assert [LT.depth(par, 9 + d) for d in range(1, 7)] == [1, 2, 3, 4, 5, 6]
    assert par[16] == -1                                            # L7: from it, the top again


def test_a_path_as_its_levels():
    assert LT.levels("TRANCE STARTER PACK/KICKS/808") == ["TRANCE STARTER PACK", "KICKS", "808"]
    assert LT.levels("PACK / KICKS //808/") == ["PACK", "KICKS", "808"]
    assert LT.levels(" LEAD SPACE ") == [" LEAD SPACE "]              # no '/': as it came (link 17 before v0.40)
    assert LT.levels("A/B/C/D/E/F/G/H") == list("ABCDEF")
    assert LT.levels("P/" + "Z" * 40) == ["P", "Z" * 30]
    assert LT.levels("Q" * 40 + "/R") == ["Q" * 31, "R"]


def test_lib_c_is_the_model():
    c = (ROOT / "csrc/sampler/lib.c").read_text()
    assert re.search(r"#define LIB_DEPTH (\d+)", c).group(1) == str(LT.DEPTH)
    assert "#define FTAG(f) (FOLD[LIB_FOLDER_BYTES * (u32)(f) + LIB_FOLDER_BYTES - 1u])" in c
    assert "p = (t & 0x3Fu) + ((t & 0xC0u) == 0xC0u ? 64u : 0u)" in c and "(t & 0x80u) && FNAMED(f)" in c
    assert "0x80u | (u32)parent : 0xC0u | ((u32)parent - LIB_FOLDERS_LO)" in c
    # v0.43: 128 folders, the browser's loops the same
    assert re.search(r"#define LIB_FOLDERS (\d+)", c).group(1) == str(LT.FOLDERS) == "128"
    page = (ROOT / "csrc/sampler/smp_page.c").read_text()
    assert re.search(r"#define SMP_LIB_FOLDERS (\d+)", page).group(1) == str(LT.FOLDERS)
    assert "g < 64" not in page and "f < 64" not in page
    assert "cmd == 30" in c and "cmd == 31" in c and "folder_path(rq + 3" in c
    link = (ROOT / "csrc/sampler/link.c").read_text()
    assert re.search(r"#define PROTO (\d+)", link).group(1) == "7"
    assert "cmd == 30 || cmd == 31" in link
    # (LIST's reply, 132 bytes, fits the reply buffer: it ran on into rq before v0.40)
    assert "static u8 rp[132]" in link


def test_v043_folders_past_63_and_their_parents():
    """v0.43 (Wolljamin: the 64 folders full): 128 folders; a folder inside one past 63 keeps
    its parent (0xC0 | parent - 64), and one past 63 inside one under 64 too"""
    tab = bytearray(LT.RECORD * LT.FOLDERS)
    for f, (name, parent) in {0: ("INCOMING", None), 1: ("RECORDED", None), 70: ("PACK", None),
                              100: ("KICKS", 70), 10: ("LOOPS", 100), 101: ("SNARES", 10)}.items():
        tab[LT.RECORD * f:LT.RECORD * (f + 1)] = LT.record(name, parent)
    par = LT.tree(bytes(tab))
    assert par[70] == -1 and par[100] == 70 and par[10] == 100 and par[101] == 10
    assert LT.record("KICKS", 70)[-1] == 0xC0 | 6 and LT.record("LOOPS", 3)[-1] == 0x80 | 3

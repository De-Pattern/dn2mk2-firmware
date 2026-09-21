"""LFO4 steps 1 and 2: what can be checked without an emulator.

The table's behaviour is the emulator harnesses' subject
(`scripts/emu_lfo4_ext.py`, `scripts/emu_lfo4_store.py`), because it is only
true in the presence of the firmware's own routines. What belongs here is the build: that the code still compiles for the
target, that every symbol something outside it reaches survives
`--gc-sections`, and that each stub replays **exactly** the bytes its jump
displaces -- an assembler that re-encoded one of those two instructions would
otherwise corrupt a routine the whole firmware uses.
"""

import pathlib

import pytest

from dnfw.patch import cbuild

SRC = pathlib.Path(__file__).resolve().parent.parent / "csrc"
CODE_VA = 0x46800000
ENTRIES = ["lfo4_init", "ext_get", "ext_set", "ext_drop",
           "lfo4_memcpy_stub", "lfo4_memset_stub", "lfo4_load_stub", "lfo4_save_stub"]

# Stock 1.11, read out of the image: the two instructions each jump displaces.
STOCK = {"lfo4_memcpy_displaced": bytes.fromhex("226f0004206f0008"),   # moveal 4(sp),a1 ; moveal 8(sp),a0
         "lfo4_memset_displaced": bytes.fromhex("206f000871af000b"),   # moveal 8(sp),a0 ; mvzb 11(sp),d0
         "lfo4_load_displaced": bytes.fromhex("712a001c7406"),         # mvsb 28(a2),d0 ; moveq #6,d2
         "lfo4_save_displaced": bytes.fromhex("712a003620300c00")}     # mvsb 54(a2),d0 ; movel (a0,d0*4),d0
SLOTS, PARAMS = 256, 8


@pytest.fixture(scope="module")
def linked():
    if not cbuild.available():
        pytest.skip("no m68k GCC")
    # **Everything in `csrc/lfo4`, derived rather than listed.** `hooks.S` is
    # one assembly source and `--gc-sections` works on sections, so every stub
    # in it is kept whenever any other stub there is an entry -- which means
    # the whole file's references have to resolve, whatever this test happens
    # to be about. A hand-kept list broke twice for exactly that reason: step
    # 4a added `lfo4_set_stub` and its `lfo4_on_set`, and step 4c added
    # `lfo4_get_stub` and its `lfo4_on_get`, and neither time was the list
    # updated. A list that has to be maintained in step with a file it does
    # not sit next to is a list that will drift.
    sources = sorted(p for p in (SRC / "lfo4").iterdir() if p.suffix in (".c", ".S"))
    assert sources, "csrc/lfo4 has no sources"
    return cbuild.build(sources, base=CODE_VA, include=[SRC / "include"], entries=ENTRIES)


def test_every_reached_symbol_survives(linked):
    assert all(name in linked.symbols for name in ENTRIES)


def test_each_stub_replays_the_bytes_it_displaces(linked):
    for name, stock in STOCK.items():
        at = linked[name] - CODE_VA
        assert linked.image[at:at + len(stock)] == stock, name


def test_the_table_is_in_bss_and_the_loader_will_zero_it(linked):
    assert linked.bss >= SLOTS * (4 + 2 * PARAMS)
    assert linked["ext_key"] >= CODE_VA + len(linked.image)

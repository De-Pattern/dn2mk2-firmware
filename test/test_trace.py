"""The trace harness: board, probes, and the guards that make a splice safe.

These are offline tests over a synthetic image. They cannot tell you whether a
probe runs on the device -- that is the whole point of the harness -- but they
can hold the properties a silent build would otherwise hide: that a payload
restores what it touched, that two probes cannot share a column, and that a site
with a branch landing inside it is refused.
"""

import pytest

from dnfw.image.coldfire import LoadedImage
from dnfw.image.functions import branch_targets_within, build as build_callgraph
from dnfw.patch import trace
from dnfw.patch.assemble import available
from dnfw.patch.cave import apply
from dnfw.patch.trace import Board, Probe, TraceError

BASE = 0x40000000
needs_assembler = pytest.mark.skipif(not available(), reason="no m68k binutils")


def make_image(size: int = 0x2000) -> LoadedImage:
    """A section of NOPs with a zero run at the end to use as a cave."""
    content = bytearray(b"\x4e\x71" * (size // 2))
    content[0x1000:] = bytes(size - 0x1000)
    return LoadedImage(dest=BASE, content=bytes(content))


def place(image: LoadedImage, offset: int, data: bytes) -> LoadedImage:
    content = bytearray(image.content)
    content[offset:offset + len(data)] = data
    return LoadedImage(dest=image.dest, content=bytes(content))


# --- the board -----------------------------------------------------------

def test_board_ships_an_idle_row_of_its_own_width():
    board = Board(address=0x40001000, width=11)
    assert board.idle == b"." * 11 + b"\x00"


def test_find_board_requires_the_text_to_be_unique():
    content = b"\x00" * 16 + b"MENU\x00" + b"\x00" * 16 + b"MENU\x00"
    with pytest.raises(TraceError, match="occurs 2 times"):
        trace.find_board(content, BASE, b"MENU\x00")


def test_find_board_reports_width_without_the_terminator():
    content = b"\x00" * 16 + b"MENU\x00" + b"\x00" * 16
    board = trace.find_board(content, BASE, b"MENU\x00")
    assert board.width == 4
    assert board.address == BASE + 16


def test_find_board_insists_on_being_given_the_nul():
    with pytest.raises(TraceError, match="with its NUL"):
        trace.find_board(b"MENU\x00", BASE, b"MENU")


# --- probes --------------------------------------------------------------

def test_a_mark_must_be_distinguishable_from_the_idle_character():
    with pytest.raises(TraceError, match="idle character"):
        Probe(id="p", site=BASE, mark=".", column=0)


def test_a_mark_must_be_a_single_printable_character():
    with pytest.raises(TraceError, match="one printable character"):
        Probe(id="p", site=BASE, mark="XY", column=0)


def test_two_probes_cannot_write_the_same_column():
    image = make_image()
    board = Board(address=BASE + 0x800, width=4)
    probes = (Probe(id="a", site=BASE + 0x10, mark="A", column=1),
              Probe(id="b", site=BASE + 0x20, mark="B", column=1))
    caves = trace.lay_out(BASE + 0x1000, 2)
    stock = b"\x4e\x71" * 3
    with pytest.raises(TraceError, match="both write column 1"):
        trace.hooks(image, board, probes, caves, {"a": stock, "b": stock})


def test_a_column_outside_the_board_is_refused():
    board = Board(address=BASE + 0x800, width=4)
    with pytest.raises(TraceError, match="outside the board"):
        trace.payload(board, Probe(id="p", site=BASE, mark="P", column=9))


def test_every_probe_needs_stock_bytes():
    image = make_image()
    board = Board(address=BASE + 0x800, width=4)
    probes = (Probe(id="a", site=BASE + 0x10, mark="A", column=0),)
    with pytest.raises(TraceError, match="no stock bytes"):
        trace.hooks(image, board, probes, trace.lay_out(BASE + 0x1000, 1), {})


# --- the guard that patch/cave.py cannot make ----------------------------

def test_a_branch_into_the_displaced_bytes_is_detected():
    # bra.w from 0x100 to 0x204, which is two bytes inside a hook at 0x200.
    image = place(make_image(), 0x100, b"\x60\x00\x01\x02")
    hits = branch_targets_within(image, BASE + 0x200, 8)
    assert hits == (BASE + 0x100,)


def test_a_branch_to_the_hook_site_itself_is_not_a_hazard():
    # Landing on the first byte is fine -- that is what a call to an entry does.
    # bra.w at 0x100 with displacement 0xfe targets 0x100 + 2 + 0xfe = 0x200.
    image = place(make_image(), 0x100, b"\x60\x00\x00\xfe")
    assert branch_targets_within(image, BASE + 0x200, 8) == ()


def test_check_site_refuses_a_site_something_branches_into():
    image = place(make_image(), 0x100, b"\x60\x00\x01\x02")
    probe = Probe(id="p", site=BASE + 0x200, mark="P", column=0)
    with pytest.raises(TraceError, match="branches into the middle"):
        trace.check_site(image, probe, b"\x4e\x71" * 4)


# --- the payload ---------------------------------------------------------

@needs_assembler
def test_payload_saves_and_restores_both_registers_and_the_flags():
    board = Board(address=0x402193F4, width=11)
    code = trace.payload(board, Probe(id="p", site=BASE, mark="P", column=3))
    # lea -8 / movem save / move from ccr ... move to ccr / movem restore / lea +8
    assert code.startswith(bytes.fromhex("4fefff f8".replace(" ", "")))
    assert code.endswith(bytes.fromhex("4fef0008"))
    assert bytes.fromhex("42c0") in code, "CCR is never saved"
    assert bytes.fromhex("44c0") in code, "CCR is never restored"
    assert code.index(bytes.fromhex("42c0")) < code.index(bytes.fromhex("44c0"))


@needs_assembler
def test_payload_writes_the_mark_at_its_own_column():
    board = Board(address=0x402193F4, width=11)
    third = trace.payload(board, Probe(id="p", site=BASE, mark="P", column=3))
    zero = trace.payload(board, Probe(id="p", site=BASE, mark="P", column=0))
    assert third != zero, "the column is not reaching the encoding"
    assert bytes([ord("P")]) in third


@needs_assembler
def test_a_probe_splices_without_touching_anything_else():
    image = make_image()
    board = Board(address=BASE + 0x800, width=4)
    probe = Probe(id="a", site=BASE + 0x10, mark="A", column=0)
    cave = trace.lay_out(BASE + 0x1000, 1)[0]
    stock = image.read(probe.site, 6)
    hook = trace.hooks(image, board, (probe,), (cave,), {"a": stock})[0]

    edited = apply(image, hook)
    changed = {i for i in range(len(edited)) if edited[i] != image.content[i]}
    site = probe.site - BASE
    allowed = set(range(site, site + len(stock)))
    allowed |= set(range(cave.address - BASE, cave.address - BASE + cave.capacity))
    assert changed <= allowed
    # The displaced stock is replayed verbatim, exactly once.
    body = edited[cave.address - BASE:cave.address - BASE + cave.capacity]
    assert body.count(stock) == 1


@needs_assembler
def test_caves_do_not_overlap():
    caves = trace.lay_out(0x40287EF6, 11)
    ends = [c.address + c.capacity for c in caves]
    starts = [c.address for c in caves]
    assert all(e <= s for e, s in zip(ends, starts[1:]))
    assert all(c.address % 2 == 0 for c in caves)


def test_lay_out_refuses_an_odd_run():
    with pytest.raises(TraceError, match="2-byte aligned"):
        trace.lay_out(0x40287EF7, 2)


# --- the call graph ------------------------------------------------------

def test_a_jsr_makes_its_target_an_entry():
    image = place(make_image(), 0x100, b"\x4e\xb9\x40\x00\x02\x00")
    graph = build_callgraph(image)
    assert graph.is_entry(BASE + 0x200)
    assert graph.callers_of(BASE + 0x200) == (BASE + 0x100,)


def test_an_address_nothing_calls_has_no_callers():
    graph = build_callgraph(make_image())
    assert graph.callers_of(BASE + 0x200) == ()


def test_containing_reports_the_nearest_entry_at_or_below():
    image = place(make_image(), 0x100, b"\x4e\xb9\x40\x00\x02\x00")
    graph = build_callgraph(image)
    assert graph.containing(BASE + 0x210) == BASE + 0x200
    assert graph.containing(BASE + 0x1FF) is None


def test_a_target_outside_the_section_is_not_a_call():
    image = place(make_image(), 0x100, b"\x4e\xb9\x90\x00\x00\x00")
    assert build_callgraph(image).entries == ()


def test_an_odd_target_is_a_misread_operand_not_a_call():
    image = place(make_image(), 0x100, b"\x4e\xb9\x40\x00\x02\x01")
    assert build_callgraph(image).entries == ()


# --- the legend ----------------------------------------------------------

def test_the_legend_row_matches_what_the_screen_should_show():
    probes = (Probe(id="a", site=BASE, mark="A", column=0),
              Probe(id="c", site=BASE, mark="C", column=2))
    assert trace.legend(probes, 4).splitlines()[0] == "A.C."

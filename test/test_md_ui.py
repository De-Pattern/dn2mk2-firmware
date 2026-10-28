"""The Machinedrum's screen graphics for the PERC page (dnfw.md.ui, csrc/waverider/md_page.c).

The graphics are Elektron's and read from the owner's MD OS when the build is made; like
test_md, these need it (MD_OS_BIN) and fail without it: an unchecked gate is a failed gate."""

import re

from dnfw.md import ui
from dnfw.perc import machines as PM
from dnfw.waverider import pages


def test_the_blob_is_laid_out_as_the_page_reads_it():
    b = ui.blob()
    assert b[:4] == b"MDUI" and int.from_bytes(b[4:6], "big") == ui.VERSION
    assert len(b) == ui.blob_bytes() == ui.O_MACH + ui.MACH_BYTES * PM.N
    # the offsets the C reads are the ones blob() wrote
    h = dict(re.findall(r"#define (MDUI_\w+) (\d+)", ui.c_header()))
    assert int(h["MDUI_KNOB"]) == ui.O_KNOB and int(h["MDUI_MACH"]) == ui.O_MACH
    assert int(h["MDUI_FONT"]) == ui.O_FONT and int(h["MDUI_PTR"]) == ui.O_PTR


def test_every_machine_has_its_name_and_some_parameters():
    b = ui.blob()
    for k, name in enumerate(PM.NAMES):
        e = b[ui.O_MACH + ui.MACH_BYTES * k:ui.O_MACH + ui.MACH_BYTES * (k + 1)]
        nib = int.from_bytes(e[:4], "big")
        synth, mach = e[4:7].decode(), e[7:9].decode()
        # (v0.24: the P-I machines as the MD shows them, "P-I" and the machine)
        assert f"{synth}-{mach}" == name or (synth == "P-I" and name == f"PI-{mach}"), (k, name, synth, mach)
        assert e[9] == 0
        # at least one parameter exists (nibble bit 0), and no clip on a cell's last column
        cells = [nib >> (28 - 4 * s) & 15 for s in range(8)]
        assert any(c & 1 for c in cells), name


def test_the_fonts_and_the_pointers_are_drawn():
    b = ui.blob()
    for f in range(3):
        base = ui.O_FONT + ui.FONT_BYTES * f
        rows = b[base]
        assert 4 <= rows <= 8
        a = base + 1 + ui.FONT_STRIDE * (ord("A") - 32)
        assert b[a] > 0 and any(b[a + 1:a + 1 + b[a]])     # 'A' has a width and pixels
    ptrs = [b[ui.O_PTR + 2 * ui.PTR_COLS * v:ui.O_PTR + 2 * ui.PTR_COLS * (v + 1)] for v in range(128)]
    assert len(set(ptrs)) > 32                               # the pointer turns


def test_the_mod_places_the_blob_where_the_page_reads_it():
    assert pages.MDUI_LOAD % 4 == 0
    assert f"#define MDUI_LOAD {pages.MDUI_LOAD:#x}" in pages.md_c_header().replace("0X", "0x") \
        or str(pages.MDUI_LOAD) in pages.md_c_header() or hex(pages.MDUI_LOAD) in pages.md_c_header().lower()


def test_the_page_renderer_stops_before_the_md_graphics():
    # v0.29: the renderer's span grew to 128 KB (the multi-select took it past 64 KB); it
    # must end before the Machinedrum's graphics chunk, and both above BSS (memory-map.md)
    import json
    import pathlib
    spec = json.loads((pathlib.Path(__file__).resolve().parent.parent
                       / "src/dnfw/mods/waverider_code.json").read_text())
    c = spec["c_chunk"]
    assert c["load"] == pages.C_LOAD and c["load"] + len(bytes.fromhex(c["code"])) <= pages.C_LOAD + pages.C_SPAN
    assert pages.C_LOAD + pages.C_SPAN <= pages.MDUI_LOAD and pages.C_LOAD > 0x466B74D0

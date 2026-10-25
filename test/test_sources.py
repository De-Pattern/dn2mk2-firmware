"""Every committed SHARC source has its branch targets filled.

Generated sources (gen_ping_asm.py, gen_gran_asm.py, ...) write each target as `0x0`
with a `// -> label.` comment and `scripts/sharc_resolve_jumps.py` fills them from
selas's layout. A source committed between the two assembles and decodes cleanly and
then jumps to 0: in the SHARC runner, PING's first block did (2026-10-23, a branch that
was dropped). The runner's decode step refuses such a source too."""

from __future__ import annotations

import pathlib
import re

SHARC = pathlib.Path(__file__).resolve().parents[1] / "csrc" / "waverider" / "sharc"


def test_no_committed_source_has_an_unresolved_jump():
    sources = sorted(SHARC.glob("*.asm"))
    assert sources
    for f in sources:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"JUMP\s+0x0;", text), f.name
        assert not re.search(r"=\s*0x0;\s*// return address", text), f.name


# v0.20: the ColdFire half of the waverider and sampler mods never writes the frame it
# sends the DSP each tick (0x80005e60, 2,748 bytes). v0.14..v0.19 put the sample link's
# packets in its words 2650..2681, which the DSP reads as the per-track routing
# (docs/link-research.md, "Who sets the two tables"): the stock voices buzzed after a
# sample track was used. The frame may be read (the tempo); nothing may be stored there.
CSRC = SHARC.parents[1]
FRAME_SOURCES = sorted([*(CSRC / "waverider").glob("*.c"), *(CSRC / "sampler").glob("*.[cS]")])


def test_no_coldfire_source_writes_the_frame():
    assert FRAME_SOURCES
    for f in FRAME_SOURCES:
        text = f.read_text(encoding="utf-8")
        assert "LINK_OFFSET" not in text, f.name
        assert "smp_feed" not in text, f.name
        # the frame only through CTL_FRAME, and only read: CTL_FRAME[..] never assigned,
        # never taken as a pointer to write through
        for m in re.finditer(r"CTL_FRAME\b(.*)", text):
            rest = m.group(1)
            assert not re.match(r"\s*\[[^\]]*\]\s*(=[^=]|[-+*/|&^]=|\+\+|--)", rest), (f.name, m.group(0))
            assert not re.match(r"\s*\+", rest), (f.name, m.group(0))
        for addr in ("0x80005E6", "0x80005e6", "0x80006", "0x80005F", "0x80005f"):
            for line in text.splitlines():
                if addr in line:
                    # v0.25: the per-voice parameter mirror (smp_mod_apply writes SAMP's cell,
                    # which a static assert in link.c puts past the frame's end)
                    assert ("#define CTL_FRAME ((volatile u16 *)0x80005E60u)" in line
                            or "#define MIRROR_CELL(b, s) ((volatile u16 *)(0x800068E4u" in line
                            or "_Static_assert(0x800068E4u + 34u + 2u * SAMP_SLOT >= 0x80005E60u + 2748u" in line), (f.name, line)

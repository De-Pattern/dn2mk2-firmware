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

"""Compile Waverider's C page renderer (`csrc/waverider/page.c`) for `coldfire.compose`.

One subject: the generated header and the source in, the linked bytes out. The
header (`wr_gen.h`: the control table and the wave spans) is written beside a
temporary copy of nothing else; `page.c` is compiled from the repository.

Only `scripts/gen_waverider_code.py` (and the test that replays it) need this and the
m68k GCC it drives; applying the mod reads the committed bytes.
"""

from __future__ import annotations

import pathlib
import tempfile

from ..patch import cbuild

SOURCE = pathlib.Path(__file__).resolve().parents[3] / "csrc" / "waverider" / "page.c"
ENTRY = "wr_page_draw"
POLL = "wr_poll"                        # the UI loop's redraw test (coldfire.POLL_SITE)
OVERLAY = "wr_cell"                     # after each stock cell widget: PING's and SHFT's TYPE
# v0.14: the sample link (csrc/sampler), linked into the same chunk
LINK_SOURCES = [SOURCE.parents[1] / "sampler" / "link.c", SOURCE.parents[1] / "sampler" / "hooks.S",
                SOURCE.parents[1] / "sampler" / "smp_page.c", SOURCE.parents[1] / "sampler" / "rec.c",
                SOURCE.parents[1] / "sampler" / "fmt.c"]
LINK_ENTRIES = ["smp_rx_hook", "smp_feed_hook", "smp_hi", "smp_walk", "smp_booted", "smp_key", "smp_cmds", "smp_quant_hook"]


def available() -> bool:
    return cbuild.available()


def compile_page(header: str, *, base: int) -> tuple[bytes, dict[str, int], int]:
    """-> (image, symbols, bss) of page.c linked at BASE, with HEADER as wr_gen.h."""
    with tempfile.TemporaryDirectory(prefix="wr_gen_", dir=SOURCE.parent) as tmp:
        (pathlib.Path(tmp) / "wr_gen.h").write_bytes(header.encode())
        from ..sampler import machines as SM
        from . import dsp
        defines = {"SMP_MIRROR": hex(SM.MIRROR), "SMP_MIRROR_BYTES": hex(SM.MIRROR_BYTES),
                   "SMP_POOL_DDR": hex(dsp.SMP_POOL_DDR), "LINK_OFFSET": SM.LINK_OFFSET,
                   "LINK_MAGIC": hex(SM.LINK_MAGIC), "LINK_SEED": hex(SM.LINK_SEED),
                   "POOL_MAGIC": hex(SM.POOL_MAGIC) + "u", "NAMES_OFFSET": SM.NAMES_OFFSET,
                   "NAME_BYTES": SM.NAME_BYTES, "DATA_OFFSET": hex(SM.DATA_OFFSET),
                   "POOL_SLOTS": SM.POOL_SLOTS}
        import os
        if os.environ.get("DNFW_SMP_STORE_TEST"):
            # an emulator-only build: the +Drive region inside the emulator's 15 MB device
            # (never shipped: scripts/gen_waverider_code.py refuses to write it)
            sector, floor = os.environ["DNFW_SMP_STORE_TEST"].split(",")
            defines.update({"STORE_SECTOR": sector + "u", "STORE_FLOOR": floor + "u"})
        linked = cbuild.build([SOURCE, *LINK_SOURCES], base=base,
                              entries=[ENTRY, POLL, OVERLAY, *LINK_ENTRIES],
                              include=[pathlib.Path(tmp)], defines=defines)
    return linked.image, linked.symbols, linked.bss

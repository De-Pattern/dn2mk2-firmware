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
                SOURCE.parents[1] / "sampler" / "fmt.c", SOURCE.parent / "md_page.c",
                SOURCE.parents[1] / "sampler" / "slice.c",
                SOURCE.parents[1] / "sampler" / "lib.c"]
LINK_ENTRIES = ["smp_rx_hook", "smp_hi", "smp_walk", "smp_booted", "smp_key", "smp_cmds", "smp_quant_hook", "smp_tdm_hook", "smp_tdm_sent", "smp_tdm_heard", "smp_retries", "smp_saved", "smp_boot", "smp_save_recording", "smp_load", "smp_lstate", "smp_ui_pop", "wr_screen", "rec_combo", "wr_lfo_mask", "rec_overlay", "rec_src", "rec_dest", "smp_ram", "rec_phase", "trim_slot", "trim_n", "trim_s", "trim_e", "nm_cur", "nm_text", "slc_state", "slc_page_seen", "smp_analyse", "smp_analysis", "smp_onsets", "smp_slices_set", "smp_slices_get", "slc_keynotes", "slc_nfr", "slc_sl", "slc_ns", "slc_cur", "slc_grid_n", "smp_pos", "smp_pos_at", "smp_periods", "smp_mod_apply", "smp_dir_ok", "smp_meta_ok", "smp_lst_open", "smp_fb_open", "smp_fb_folder", "smp_fb_cur", "rec_pv_on", "smp_func_held", "smp_question_up", "smp_machine_commit", "smp_fb_store", "smp_lib_refresh", "smp_lib_pending", "smp_lp_queued", "smp_lib_load", "smp_lp_done", "smp_lp_full", "smp_lib_state", "smp_lib_writes", "smp_held_lo", "smp_held_hi", "smp_knob_d", "smp_knob_at", "smp_dsp_load", "smp_load_peak", "smp_load_seen", "smp_load_at", "rec_state", "rec_heard", "slc_kb_c", "slc_alloc_n", "smp_tables", "smp_pv_state", "trim_zoom"]


def available() -> bool:
    return cbuild.available()


def compile_page(header: str, *, base: int) -> tuple[bytes, dict[str, int], int]:
    """-> (image, symbols, bss) of page.c linked at BASE, with HEADER as wr_gen.h."""
    with tempfile.TemporaryDirectory(prefix="wr_gen_", dir=SOURCE.parent) as tmp:
        (pathlib.Path(tmp) / "wr_gen.h").write_bytes(header.encode())
        from ..sampler import machines as SM
        from . import dsp
        defines = {"SMP_MIRROR": hex(SM.MIRROR), "SMP_MIRROR_BYTES": hex(SM.MIRROR_BYTES),
                   "SMP_POOL_DDR": hex(dsp.SMP_POOL_DDR), "LINK_SEED": hex(SM.LINK_SEED),
                   "POOL_MAGIC": hex(SM.POOL_MAGIC) + "u", "NAMES_OFFSET": SM.NAMES_OFFSET,
                   "NAME_BYTES": SM.NAME_BYTES, "DATA_OFFSET": hex(SM.DATA_OFFSET),
                   "POOL_SLOTS": SM.POOL_SLOTS}
        for name in ("POOL_BYTES", "REC_OFFSET", "REC_END", "RAM_PROVEN", "SLICE_AREA", "TABLE_AREA", "TABLE_ROOM", "TABLE_READY", "TABLE_MAGIC", "TABLE_LOAD", "CMD_OFFSET", "STATUS_MAGIC", "TDM_TAG",
                     "RX_MAGIC", "TX_MAGIC", "POS_MAGIC", "POS_NONE", "POS_ONE", "META_PTR", "META_PTR_MAGIC", "META_MAGIC", "META_FOLDERS",
                     "META_FOLDER_BYTES", "META_SLOT_BYTES", "META_NAME_BYTES", "META_BYTES"):      # v0.16; v0.25 POS
            defines[name] = hex(getattr(SM, name)) + "u"
        for name in ("REC_FIRST", "REC_SLOTS", "REC_SLOT_SHIFT", "CMD_SEND", "CMD_VERIFY", "CMD_PROBE", "CMD_PREVIEW",
                     "RX_WORDS", "TX_WORDS", "CMD_WORDS"):
            defines[name] = int(getattr(SM, name))
        import os
        if os.environ.get("DNFW_SMP_STORE_TEST"):
            # an emulator-only build: the +Drive region inside the emulator's 15 MB device
            # (never shipped: scripts/gen_waverider_code.py refuses to write it)
            sector, floor = os.environ["DNFW_SMP_STORE_TEST"].split(",")
            defines.update({"STORE_SECTOR": sector + "u", "STORE_FLOOR": floor + "u"})
        linked = cbuild.build([SOURCE, *LINK_SOURCES], base=base,
                              entries=[ENTRY, POLL, OVERLAY, *LINK_ENTRIES],
                              include=[pathlib.Path(tmp)], defines=defines)
    # libgcc's 64-bit helpers use instructions the ColdFire lacks (an illegal-instruction
    # exception on the instrument, found in the emulator in v0.16): none may be linked
    wide = sorted(n for n in linked.symbols if n.endswith("di3") or n.endswith("di4"))
    if wide:
        raise RuntimeError(f"the page renderer links libgcc's 64-bit helpers {wide}: use 32-bit arithmetic")
    return linked.image, linked.symbols, linked.bss

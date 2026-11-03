"""Parameter slides (A4 mk2 / Overtone style): the ColdFire half's constants, the
continuous-slot tables and the stock sites it hooks. Design: docs/slides.md.

The C is `csrc/slides/slide.c` and `csrc/slides/hooks.S`, linked into the page renderer's
chunk (`dnfw.waverider.cpage`); `dnfw.waverider.coldfire.compose` writes the hooks.

Storage (docs/lock-id-table.md): a trig's SLIDE and SLEN are lock records of their own in
the pattern's stock lock pool (80 x 258 bytes). In RAM their header is (0x50 SLD / 0x51
SLEN, track | 0x20); stored, (200 / 201, track). Stock firmware skips ids above 106 on
load, so a pattern opened on stock loses its slides and nothing else.
"""

from __future__ import annotations

import struct

BASE = 0x40000400
PARAM_TABLE, PARAM_RECORDS, PARAM_BYTES = 0x401F7F94, 321, 60

ID_SLD, ID_SLEN = 200, 201              # stored lock ids (stock: 0..106; arp p-locks 107..129)
RAM_SLD, RAM_SLEN = 0x50, 0x51          # RAM header byte 0 (kept inside 0..100, like a slot)
RAM_TAG = 0x20                          # RAM header byte 1: track | RAM_TAG (stock's track loops skip it)
EXT_OFFSET = 1600                       # in a lock list (20 + 202 x 8 = 1636 bytes): our 12 bytes

# SLEN: the slide's length, in 1/24 of a track step (the track's own scale followed).
SLEN_UNITS = (3, 6, 12, 18, 24, 36, 48, 72, 96, 144, 192, 288, 384, 768, 1536)
SLEN_TEXT = ("1/8", "1/4", "1/2", "3/4", "1", "1.5", "2", "3", "4", "6", "8", "12", "16", "32", "64")
SLEN_DEFAULT = 4                        # 1 step: a slide trig with no SLEN lock

# Hooked stock sites (Digitone II 1.11), each with the bytes it replaces.
PRE_SITE, PRE_STOCK = 0x40026BAC, "284220280040"            # a note's voice: movea.l %d2,%a4 ; move.l 64(%a0),%d0
APPLY_SITE, APPLY_STOCK = 0x400DB092, "4fefffd4202f0030"    # lock applier (voice, list, mirror)
SMOOTH_SITE, SMOOTH_STOCK = 0x4002717E, "4eb9400db12a"      # frame ISR: jsr 0x400db12a (the smoother)
BUILD_SITE, BUILD_STOCK = 0x400D85E8, "4fefffe87065"        # lock-list builder (track, list, table, ., step)
CLEAR_SITE, CLEAR_STOCK = 0x4003D14E, "4fefffd848d73cfc"    # clear a step's locks (model, track, step)
LOAD_SITE, LOAD_STOCK = 0x400DE51E, "4fefffe048d73c3c"      # pattern lock table: stored -> RAM
SAVE_SITE, SAVE_STOCK = 0x400DE718, "4fefffe448d73c1c"      # pattern lock table: RAM -> stored

# v0.40: copy and paste carry SLD/SLEN (the arp p-locks' sites, scripts/build_arp_plocks.py):
# (site, the stock bytes, the hook's label). Each is a jsr, nops to the stock length.
PASTE_SITES = (
    (0x40050CCE, "71331801b0aa003c", "sl_copy_cmp1"),        # page autocopy: the track compare
    (0x40051158, "71358801b0aa003c", "sl_copy_cmp2"),        # shift (FUNC + LEFT/RIGHT)
    (0x40052634, "7f310801223c0001799c", "sl_paste_a"),      # page paste's UNDO: a record's track
    (0x40053246, "7b310801223c0001799c", "sl_paste_b"),      # page paste
    (0x4005389C, "7b338801223c0001799c", "sl_paste_c"),      # track paste
    (0x40052948, "79338801223c0001799c", "sl_paste_d"),      # track paste's UNDO
    (0x40053F48, "2f122f2b003c", "sl_copy_hook"),            # trig copy: an entry appended
    (0x40055440, "71ab000449faf24a", "sl_paste_hook"),       # trig paste: an entry written
)

DEST_SLOTS = (4, 12, 20)                # LFO DEST: copied unsmoothed by 0x400db12a; never slid
SHARED_PAGES = (0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F, 0x1A, 0x1B, 0x1C)
MACHINE_PAGES = (0x00, 0x01, 0x02, 0x03)    # FM TONE, WAVETONE, FM DRUM, SWARMER (types 0..3)
SPAN_MIN = 0x2000                       # at least 32 of the panel's steps: continuous


def records(stock: bytes):
    """-> [(page, slot, lo, hi)] of the 321 parameter records."""
    out = []
    for i in range(PARAM_RECORDS):
        at = PARAM_TABLE - BASE + PARAM_BYTES * i
        page, slot, lo, hi = struct.unpack(">4i", stock[at:at + 16])
        out.append((page, slot, lo, hi))
    return out


def masks(stock: bytes) -> tuple[int, list[int]]:
    """-> (shared, [machine type 0..3]): 128-bit slot masks of the parameters a slide moves.
    A slot is in a mask when every record naming it on those pages spans SPAN_MIN or more
    (so a choice -- ALGO, WAVE, MULT, MODE, a routing, the EQ filter's TYPE -- never slides),
    and it is not an LFO's DEST."""
    def mask(pages):
        ok: dict[int, bool] = {}
        for page, slot, lo, hi in records(stock):
            if page in pages and 0 <= slot <= 100:
                ok[slot] = ok.get(slot, True) and (hi - lo) >= SPAN_MIN and slot not in DEST_SLOTS
        return sum(1 << s for s, good in ok.items() if good)
    return mask(SHARED_PAGES), [mask((p,)) for p in MACHINE_PAGES]


def c_header(stock: bytes) -> str:
    shared, machine = masks(stock)

    def words(m):
        return "{" + ", ".join(f"0x{(m >> (32 * k)) & 0xFFFFFFFF:08x}u" for k in range(4)) + "}"
    rows = ",\n ".join(words(m) for m in machine)
    units = ", ".join(str(u) for u in SLEN_UNITS)
    texts = ", ".join(f'"{t}"' for t in SLEN_TEXT)
    return (f"\n/* parameter slides (dnfw.slides) */\n#ifdef SLIDE_C\n"
            f"#define SL_ID_SLD {ID_SLD}\n#define SL_ID_SLEN {ID_SLEN}\n"
            f"#define SL_RAM_SLD {RAM_SLD}\n#define SL_RAM_SLEN {RAM_SLEN}\n#define SL_TAG {RAM_TAG}\n"
            f"#define SL_EXT {EXT_OFFSET}\n#define SL_NLEN {len(SLEN_UNITS)}\n"
            f"#define SL_LEN_DEFAULT {SLEN_DEFAULT}\n"
            f"static const unsigned int sl_shared[4] = {words(shared)};\n"
            f"static const unsigned int sl_machine[4][4] = {{\n {rows}}};\n"
            f"static const unsigned short sl_units[{len(SLEN_UNITS)}] = {{{units}}};\n"
            f"static const char *const sl_len_text[{len(SLEN_TEXT)}] = {{{texts}}};\n#endif\n")

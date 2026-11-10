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
# v0.41: a REC trig's lock (docs/rectrig.md): the buffer a step records into, 1 or 2; the
# same kind of record as SLD/SLEN, kept, copied and cleared with them
ID_REC, RAM_REC = 202, 0x52
RAM_TAG = 0x20                          # RAM header byte 1: track | RAM_TAG (stock's track loops skip it)
EXT_OFFSET = 1600                       # in a lock list (20 + 202 x 8 = 1636 bytes): our 16 bytes (v0.41: 12 before)

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
    (0x400E752C, "73280001b481", "sl_clr_cmp"),              # track clear: a record's track
)

# v0.41 (ROADMAP 3, the owner 2026-11-03): slides on our machines' own controls. Only a control
# the sound engine reads while the note sounds slides (one read at the note would slide
# silently), and never a choice (TYPE, SAMP, PLAY, BARS, SEG, MODE, GRID, a *TYP).
# The sample machines (types 8..13: dnfw.sampler.program): TUNE (25) and LEV (30) every block
# (voice); ONESHOT, STRETCH and REPITCH also follow STRT (26), LEN (45) and LOOP (44) while the
# note sounds (live: follow); GRID's and SLICE's slice and WERP's segments are taken at the note.
SAMPLE_SLIDE = {8: (25, 30, 26, 45, 44),          # ONESHOT
                9: (25, 30),                      # WERP
                10: (25, 30, 26, 45),             # STRETCH
                11: (30, 26, 45),                 # REPITCH (no TUNE on its page)
                12: (25, 30),                     # GRID
                13: (25, 30),                     # SLICE
                17: (25, 30, 26, 45)}             # v0.44 BOUNCE: STRETCH's (it is STRETCH to the DSP)
# PERC (type 5): the Machinedrum's machines (dnfw.md). Their eight controls (dnfw.perc.machines
# PARAMS: frame slots 25, 31, 41, 30, 43, 44, 47, 29) reach the MD's own DSP code through its
# host words, recomputed on a block with a change; whether a change is heard while the note
# sounds is the machine's code's: measured on the bit-exact model (test_slides
# test_md_midnote_table: a note, one control changed four blocks in, against the same host
# block with nothing changed; any difference in the rest of the note is a 1), every *TYP and
# every unused control left out. Their track effects (FX_PARAMS) are applied every block.
PERC_TYPE, PERC_TYPE_SLOT = 5, 38
PERC_SLOTS = (25, 31, 41, 30, 43, 44, 47, 29)
PERC_FX_SLOTS = (26, 28, 34, 35, 32, 45, 40)
MD_MIDNOTE = {
    "TRX-BD": "111111.1", "TRX-B2": "1..1..11", "TRX-SD": "11111111", "TRX-XT": "1111.1..",
    "TRX-CP": "........", "TRX-RS": "111.....", "TRX-CB": "111111..", "TRX-CH": "..111...",
    "TRX-OH": "..111...", "TRX-CY": "111111..", "TRX-MA": "........", "TRX-CL": "........",
    "TRX-XC": "1111.1..", "TRX-S2": "1111111.", "EFM-BD": "11.11111", "EFM-SD": "11111111",
    "EFM-XT": "11.1111.", "EFM-CP": "1..11111", "EFM-RS": "11111111", "EFM-CB": "1111111.",
    "EFM-HH": "11111111", "EFM-CY": "1111111.", "GND-SN": "1111....", "GND-NS": "1.......",
    "GND-IM": "........", "PI-BD": "11.111..", "PI-SD": "1111111.", "PI-MT": "11111111",
    "PI-ML": "1111....", "PI-MA": "111.1...", "PI-RS": "111111..", "PI-RC": "11111111",
    "PI-CC": "11.11111", "PI-HH": "11111111"}


def md_midnote_measure(names=None, blocks: int = 40, at: int = 4) -> dict[str, str]:
    """the measurement MD_MIDNOTE holds (slow: a few minutes for all 34)"""
    from .md import machines as MD
    from .md.bench import Bench
    base = [8192] * 8
    out = {}
    for M in MD.MACHINES:
        if names and M.NAME not in names:
            continue

        def run(change):
            b = Bench(M)
            s = list(b.block(base, True))
            for k in range(1, blocks):
                if k == at:
                    inp = list(base)
                    if change is not None:
                        inp[change[0]] = change[1]
                    s += b.block(inp, False)
                else:
                    s += b.block()
            return s
        ref = run(None)
        bits = ""
        for k, name in enumerate(M.PNAMES):
            hit = any(any(abs(x - y) > 1e-9 for x, y in zip(run((k, v))[32 * at:], ref[32 * at:]))
                      for v in (14000, 2000))
            bits += "1" if hit and name != "-" and "TYP" not in name else "."
        out[M.NAME] = bits
    return out


# v0.45: FASCIA (type 18, dnfw.fascia.machines): every continuous control slides (its DSP reads
# them once a block, coefficients included); its five choices step, never slide
from .fascia import machines as _fsc        # noqa: E402
FASCIA_TYPE = _fsc.TYPE
FASCIA_SLIDE = tuple(_fsc.SLOTS[c][1] for c in _fsc.CONTROLS if not _fsc.is_choice(c))
FASCIA_STEP = tuple(_fsc.SLOTS[c][1] for c in _fsc.CONTROLS if _fsc.is_choice(c))

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
    from .md import machines as MD
    samp = ",\n ".join(words(sum(1 << x for x in SAMPLE_SLIDE[t])) for t in (*range(8, 14), 17))
    md_bits = ", ".join(str(sum(1 << k for k, c in enumerate(MD_MIDNOTE[M.NAME]) if c == "1"))
                        for M in MD.MACHINES)
    fx = words(sum(1 << x for x in PERC_FX_SLOTS))
    units = ", ".join(str(u) for u in SLEN_UNITS)
    texts = ", ".join(f'"{t}"' for t in SLEN_TEXT)
    return (f"\n/* parameter slides (dnfw.slides) */\n#ifdef SLIDE_C\n"
            f"#define SL_ID_SLD {ID_SLD}\n#define SL_ID_SLEN {ID_SLEN}\n"
            f"#define SL_RAM_SLD {RAM_SLD}\n#define SL_RAM_SLEN {RAM_SLEN}\n#define SL_TAG {RAM_TAG}\n"
            f"#define SL_ID_REC {ID_REC}\n#define SL_RAM_REC {RAM_REC}\n"
            f"#define SL_EXT {EXT_OFFSET}\n#define SL_NLEN {len(SLEN_UNITS)}\n"
            f"#define SL_LEN_DEFAULT {SLEN_DEFAULT}\n"
            f"static const unsigned int sl_shared[4] = {words(shared)};\n"
            f"static const unsigned int sl_machine[4][4] = {{\n {rows}}};\n"
            f"static const unsigned short sl_units[{len(SLEN_UNITS)}] = {{{units}}};\n"
            f"static const char *const sl_len_text[{len(SLEN_TEXT)}] = {{{texts}}};\n"
            f"#define SL_PERC_TYPE {PERC_TYPE}\n#define SL_PERC_TYPE_SLOT {PERC_TYPE_SLOT}\n"
            f"#define SL_PERC_N {len(MD.MACHINES)}\n"
            f"static const unsigned char sl_perc_slot[8] = {{{', '.join(map(str, PERC_SLOTS))}}};\n"
            f"static const unsigned char sl_perc_bits[{len(MD.MACHINES)}] = {{{md_bits}}};\n"
            f"static const unsigned int sl_perc_fx[4] = {fx};\n"
            f"static const unsigned int sl_samp[7][4] = {{\n {samp}}};\n"
            f"#define SL_FSC_TYPE {FASCIA_TYPE}\n"
            f"static const unsigned int sl_fsc[4] = {words(sum(1 << x for x in FASCIA_SLIDE))};\n#endif\n")

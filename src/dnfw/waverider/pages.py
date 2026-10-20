"""Waverider's own SYN pages (Milestone 7): the page count, the page descriptors and the
knob labels a Waverider track shows. `docs/waverider-m7-pages.md` has the evidence.

A Waverider track is WaveTone to most of the UI (`coldfire`, M5): the SYN page readers
are asked about type 1, whatever the track. So these routines do not trust the type
they are handed. They ask whether the **active track** (the byte `0x42431a6c`, whose
sound is `[0x800052a0] + 52 + 1163 * t`) is a Waverider (`sound+0xDE` = 5), and only
then answer with Waverider's pages and labels:

- `wr_count`, entered by `jsr` from the page-count reader `0x400c24d2` (in place of M5's
  `canon_arg` there): 2 pages; otherwise exactly what `canon_arg` does.
- `wr_page`, entered by `jsr` from the page reader `0x400c24ee` at `0x400c24f2` (in
  place of M5's `canon_page`): our descriptor for pages 0-1, the stock empty page past
  them; otherwise exactly what `canon_page` does.
- `wr_icons`, entered by `jsr` from the SYN page draw at `0x4001821e`: on a Waverider
  track, WaveTone's oscillator icons (drawn at B and F from `WAV1`/`TBL1` and
  `WAV2`/`TBL2` after the grid of page id 7) are skipped; otherwise the stock page-id test.
- `wr_grid`, entered by `jsr` from the SYN page draw at `0x40018214` (in place of its
  call to the grid `0x40017428`): a Waverider track gets its own page, drawn by
  `wr_page_draw` (`csrc/waverider/page.c`, M8.1); every other track the stock grid.
- `wr_label`, entered by `jsr` from the SYN page's label fetch at `0x40064622` (in place
  of `jsr getShortName`): the record ids Waverider relabels get our labels; every
  other id, and every other track, goes to the stock `getShortName` `0x400372da`
  unchanged (a tail jump, so the stack is the caller's own).

The labels and the page layout are the owner's (2026-10-01), from the Waverider mockup,
with our own names:

    page 1, OSC 1   A TUNE  B LEV   C POS   D TBL   E RATE  F MPOS  G MLEV  H MOVE
    page 2, OSC 2   A DETN  B LEV   C POS   D TBL   E RATE  F MPOS  G MLEV  H MOVE

Only TUNE, POS and TBL work in M7 (the loop reads TUN1, WAV1 and TBL1); every other
place is an empty entry (0), drawn as an empty box, until its milestone.

The code, the descriptors and the strings run from RAM as one platform `CODE` chunk at
`LOAD` (`dnfw.mods.platform`): the caves Waverider already uses are full.

The page is drawn in C (`csrc/waverider/page.c`), the way Tonverk's Wavefinder page
is laid out: the wave across the middle, A..D in a slim strip above it, E..H below.
That code is compiled and linked into the same chunk at `C_LOAD`, and reads this
module's control table and `wave`'s spans from a generated header (`c_header`).

This module is pure: it builds the source; `coldfire.compose` assembles and places it.
"""

from __future__ import annotations

LOAD = 0x4670C000                 # RAM above BSS, clear of every declared range (docs/mods-compatibility.md)
C_LOAD = LOAD + 0x600             # the C page renderer, after this assembly (0x400 until CZ)
C_END = 0x46710000                # the platform runtime starts here
ACTIVE_TRACK = 0x42431A6C         # byte: the UI's active track, 0..15
KIT_POINTER = 0x800052A0          # the live kit; sound t at + 52 + 1163 t
SOUND_BASE, SOUND_STRIDE, SOUND_TYPE = 52, 1163, 0xDE
NEW_TYPE, CLONE = 5, 1
GET_SHORT_NAME = 0x400372DA
EMPTY_PAGE = 0x42432BD4           # the readers' own empty-page fallback
TAG = 10                          # the tag every stock SYN descriptor ends with

# PERC (machine 5, docs/perc.md; Waverider's place until v0.11): two pages on WaveTone
# records -- TYPE (DRIF) and the eight parameters of dnfw.perc.machines.PARAMS. What each
# parameter is depends on TYPE, so its names are swapped per machine at run time
# (wr_names in page.c, from perc_c_header's tables); the page reads them back from the
# records, so it, the header line and the LFO lists always agree.
from ..perc import machines as _perc

TITLES = ("PRC 1", "PRC 2")
SUBTITLE = "Perc"
TYPE_ID = _perc.TYPE_REC[0]                                  # 252, DRIF
PARAM_IDS = tuple(r for r, _slot, _lo, _top in _perc.PARAMS)  # 238 242 254 253 256 257 260 240
PAGES = (
    (TYPE_ID, *PARAM_IDS[:7]),                  # TYPE, parameters 1-7
    (PARAM_IDS[7], 0, 0, 0, 0, 0, 0, 0),        # parameter 8
)
# no static labels: wr_label hands every PERC record to the stock getShortName, which
# reads the names wr_names swapped in
LABELS: dict[int, str] = {}
TYPE_NAMES = ("Perc Type", "TYPE")
UNUSED = tuple(r for r in range(238, 263) if r != TYPE_ID and r not in PARAM_IDS)
UNUSED_LONG, UNUSED_SHORT = "Unused", "-"
# a parameter's long name (LFO and modulation lists, the header line) from its short one
LONG = {"PTCH": "Pitch", "DEC": "Decay", "RAMP": "Ramp", "RDEC": "Ramp Decay", "STRT": "Start",
        "NOIS": "Noise", "HARM": "Harmonics", "CLIP": "Clip", "HOLD": "Hold", "TICK": "Tick",
        "DIRT": "Dirt", "DIST": "Distortion", "BUMP": "Bump", "BENV": "Bump Env", "SNAP": "Snap",
        "TONE": "Tone", "TUNE": "Tune", "DAMP": "Damping", "DTYP": "Dist Type", "CLPY": "Claps",
        "HARD": "Hardness", "RICH": "Richness", "RATE": "Rate", "ROOM": "Room", "RSIZ": "Room Size",
        "RTUN": "Room Tune", "ENH": "Enhance", "GAP": "Gap", "HPF": "High-Pass", "LPF": "Low-Pass",
        "MTAL": "Metal", "TOP": "Top", "TTUN": "Top Tune", "SIZE": "Size", "PEAK": "Peak",
        "ATT": "Attack", "SUS": "Sustain", "REV": "Reverse", "RATL": "Rattle", "RTYP": "Rattle Type",
        "DUAL": "Dual", "CLIC": "Click", "MOD": "Mod Amount", "MFRQ": "Mod Freq", "MDEC": "Mod Decay",
        "MFB": "Mod Feedback", "NDEC": "Noise Decay", "CLPS": "Claps", "CDEC": "Clap Decay",
        "SNAR": "Snare", "SPTC": "Snare Pitch", "SDEC": "Snare Decay", "SMOD": "Snare Mod",
        "FB": "Feedback", "TREM": "Tremolo", "TFRQ": "Trem Freq", "UP": "Up", "UVAL": "Up Value",
        "DOWN": "Down", "DVAL": "Down Value", "-": "Unused"}
# what each machine is, under its name in the middle of the page
DESCRIPTIONS = {"BD": "Bass Drum", "B2": "Bass Drum 2", "SD": "Snare", "XT": "Tom", "CP": "Clap",
                "RS": "Rimshot", "CB": "Cowbell", "CH": "Closed Hat", "OH": "Open Hat",
                "CY": "Cymbal", "MA": "Maracas", "CL": "Claves", "XC": "Conga", "HH": "Hi-Hat",
                "SN": "Sine", "NS": "Noise", "IM": "Impulse"}


def type_of(word: int) -> int:
    """TYPE's record value (0..0x7f00) -> the machine, as the DSP reads it (dnfw.perc.program)"""
    return (min(127, max(0, word >> 8)) * _perc.N) >> 7


# RESONATOR (machine 6, docs/rings.md): one page, on WaveTone records whose range and
# default fit (dnfw.rings.live's table), named while a RESONATOR track is active
RES_TITLE, RES_SUBTITLE = "RES", "Resonator"
RES_PAGES = ((238, 241, 239, 258, 254, 246, 240, 245),)   # TUNE LEV STRC BRIT / DAMP POS EXCT HIT
RES_LABELS = {238: "TUNE", 241: "LEV", 239: "STRC", 258: "BRIT",
              254: "DAMP", 246: "POS", 240: "EXCT", 245: "HIT"}
RES_LONG_NAMES = {238: "Tune", 241: "Level", 239: "Structure", 258: "Brightness",
                  254: "Damping", 246: "Position", 240: "Exciter", 245: "Hit Level"}
RES_UNUSED = tuple(r for r in range(238, 263) if r not in RES_LABELS)

# CZ (machine 7, docs/cz.md): three pages -- the voice, then the DCW envelope's eight
# rates and levels -- on WaveTone records (dnfw.cz.live's table); page 1's WAVE, SEL,
# OCT, MOD, KF and SUS draw their value as text where the label would be
CZ_TITLE, CZ_SUBTITLE = "CZ", "CZ Phase"
CZ_PAGES = (
    (239, 248, 242, 259, 249, 241, 247, 243),   # WAVE SEL DET OCT / MOD DCW KF SUS
    (240, 246, 244, 250, 245, 252, 253, 254),   # R1 R2 R3 R4 / L1 L2 L3 L4
    (255, 256, 257, 258, 260, 261, 262, 238),   # R5 R6 R7 R8 / L5 L6 L7 L8
)
CZ_LABELS = {239: "WAVE", 248: "SEL", 242: "DET", 259: "OCT", 249: "MOD", 241: "DCW",
             247: "KF", 243: "SUS",
             240: "R1", 246: "R2", 244: "R3", 250: "R4", 245: "L1", 252: "L2", 253: "L3", 254: "L4",
             255: "R5", 256: "R6", 257: "R7", 258: "R8", 260: "L5", 261: "L6", 262: "L7", 238: "L8"}
CZ_LONG_NAMES = {239: "Wave", 248: "Line Select", 242: "Line 2 Detune", 259: "Line 2 Octave",
                 249: "Line 2 Mod", 241: "DCW Depth", 247: "DCW Key Follow", 243: "DCW Sustain",
                 **{r: f"DCW Rate {k + 1}" for k, r in enumerate((240, 246, 244, 250, 255, 256, 257, 258))},
                 **{r: f"DCW Level {k + 1}" for k, r in enumerate((245, 252, 253, 254, 260, 261, 262, 238))}}
CZ_UNUSED = tuple(r for r in range(238, 263) if r not in CZ_LABELS)
# the records the page draws as text, and the envelope's (rate, level) pairs in step order
CZ_RATE_IDS = (240, 246, 244, 250, 255, 256, 257, 258)
CZ_LEVEL_IDS = (245, 252, 253, 254, 260, 261, 262, 238)

LABELS_OUT = ("is_wr", "wr_count", "wr_page", "wr_label", "wr_icons", "wr_grid", "wr_id9",
              "wr_cell_tail", "labels", "descriptors")
# PING / SHFT: every stock page cell's widget is drawn by 0x4006448a; its one exit
CELL_EXIT = 0x400646CA            # movem.l %sp@,%d2-%d7/%a2-%fp ; lea %sp@(80),%sp ; rts
CELL_EXIT_STOCK = "4cd77cfc4fef00504e75"
# W2: `labels` is where the assembly's code ends and its data (the label table, the
# descriptors, the strings) begins: the ship gate checks only [is_wr, labels) as code
GRID = 0x40017428                 # the stock grid: (view, canvas)
ICON_PAGE = 7                     # the SYN page draw's id for WaveTone's OSC page
ICON_SKIP = 0x400182C6            # its branch target past the oscillator icons
# CZ: the draw sends a type-1 page of id 9 (WaveTone's third page, which a CZ track's
# third page is to it) to the grid variant 0x400175e4; wr_id9 sends ours to the grid
# call wr_grid hooks instead
ID9_SITE = 0x40018202             # moveq #9,%d1 ; cmp.l %d3,%d1 ; bne.s 0x40018214
ID9_STOCK = "7209b283660c"
ID9_GRID = 0x40018214             # the standard grid's call (wr_grid's site)


def _rep(label: str, text: str) -> str:
    """A std::string's characters with the header the firmware's copy-on-write strings
    keep in front of them (libstdc++'s old ABI: length, capacity, reference count; the
    string object is a pointer to the characters). The descriptors' title and subtitle
    are such strings (the initializer builds them with a string constructor, `jsr %a2@`
    after `pea` of the text). Reference count -1 marks the string unshareable: a copy
    clones it, and nothing ever frees this one."""
    return (f"    .align 2\n    .long {len(text)}, {len(text)}, -1\n"
            f'{label}: .asciz "{text}"')


def label(rid: int) -> str:
    """-> what place `rid` is called on the page with no machine applied ("-" if none)."""
    return LABELS.get(rid, "-") if rid else "-"


def named() -> list[tuple[int, str, str]]:
    """(record id, long name, short name) of the names wr_names swaps in for every PERC
    machine alike: TYPE, and the WaveTone records PERC leaves unused. The parameters'
    are per machine (perc_names)."""
    return [(TYPE_ID, *TYPE_NAMES)] + [(r, UNUSED_LONG, UNUSED_SHORT) for r in UNUSED]


def perc_names() -> list[list[tuple[str, str]]]:
    """[machine][parameter] = (long, short), PARAM_IDS order"""
    return [[(LONG[sh], sh) for sh in _perc.PNAMES[name]] for name in _perc.NAMES]


def res_named() -> dict[int, tuple[str, str]]:
    """The same for a RESONATOR track."""
    out = {r: (RES_LONG_NAMES[r], RES_LABELS[r]) for r in RES_LABELS}
    out.update({r: (UNUSED_LONG, UNUSED_SHORT) for r in RES_UNUSED})
    return out


def cz_named() -> dict[int, tuple[str, str]]:
    """The same for a CZ track."""
    out = {r: (CZ_LONG_NAMES[r], CZ_LABELS[r]) for r in CZ_LABELS}
    out.update({r: (UNUSED_LONG, UNUSED_SHORT) for r in CZ_UNUSED})
    return out


def c_header() -> str:
    """The control tables, as C for `wr_gen.h`: per page, eight record ids and labels
    (Waverider's, then RESONATOR's); the names `wr_names` swaps in for each machine (a
    0 keeps the stock name); the scanner's shape names."""
    q = chr(34)
    ids = ",\n".join(" {" + ", ".join(str(r) for r in page) + "}" for page in PAGES)
    names = ",\n".join(" {" + ", ".join(f'"{label(r)}"' for r in page) + "}" for page in PAGES)
    rids = ",\n".join(" {" + ", ".join(str(r) for r in page) + "}" for page in RES_PAGES)
    rnames = ",\n".join(" {" + ", ".join(q + RES_LABELS.get(r, "-") + q for r in page) + "}"
                         for page in RES_PAGES)
    from ..rings import live as rings_live
    res_anchor = ", ".join("{" + ", ".join(str(round(10 * v)) for v in a) + "}"
                           for a in rings_live._anchor_semitones())
    wr = {r: (lo, sh) for r, lo, sh in named()}
    res = res_named()
    cz = cz_named()
    order = sorted(set(wr) | set(res) | set(cz) | set(PARAM_IDS))
    zids = ",\n".join(" {" + ", ".join(str(r) for r in page) + "}" for page in CZ_PAGES)
    znames = ",\n".join(" {" + ", ".join(q + CZ_LABELS.get(r, "-") + q for r in page) + "}"
                         for page in CZ_PAGES)
    from ..cz import live as cz_live
    combos = ", ".join(f"{{{a}, {b}}}" for a, b in cz_live.COMBOS)

    def row(m, col):
        return "{" + ", ".join(q + m[r][col] + q if r in m else "0" for r in order) + "}"
    return (f"#define WR_PAGES {len(PAGES)}\n"
            f"static const unsigned short wr_ids[WR_PAGES][8] = {{\n{ids}\n}};\n"
            f"static const char wr_labels[WR_PAGES][8][6] = {{\n{names}\n}};\n"
            f"#define RES_PAGES {len(RES_PAGES)}\n"
            f"static const unsigned short res_ids[RES_PAGES][8] = {{\n{rids}\n}};\n"
            f"static const char res_labels[RES_PAGES][8][6] = {{\n{rnames}\n}};\n"
            f"#define WR_NAMED {len(order)}\n"
            f"static const unsigned short wr_named_ids[WR_NAMED] = {{{', '.join(map(str, order))}}};\n"
            f"static const char *const wr_named_long[3][WR_NAMED] = {{{row(wr, 0)}, {row(res, 0)}, {row(cz, 0)}}};\n"
            f"static const char *const wr_named_short[3][WR_NAMED] = {{{row(wr, 1)}, {row(res, 1)}, {row(cz, 1)}}};\n"
            f"#define CZ_PAGES {len(CZ_PAGES)}\n"
            f"static const unsigned short cz_ids[CZ_PAGES][8] = {{\n{zids}\n}};\n"
            f"static const char cz_labels[CZ_PAGES][8][6] = {{\n{znames}\n}};\n"
            f"static const unsigned short cz_rate_ids[8] = {{{', '.join(map(str, CZ_RATE_IDS))}}};\n"
            f"static const unsigned short cz_level_ids[8] = {{{', '.join(map(str, CZ_LEVEL_IDS))}}};\n"
            f"static const unsigned char cz_combos[{len(cz_live.COMBOS)}][2] = {{{combos}}};\n"
            f"static const short res_anchor[3][24] = {{{res_anchor}}};\n"
            + perc_c_header())


def perc_c_header() -> str:
    """PERC's tables for page.c: the machines' names and what they are, the records its
    parameters sit on, and each machine's names for them (short, as chars; long, as an
    index into one list of distinct long names)."""
    q = chr(34)
    longs = sorted({lo for row in perc_names() for lo, _ in row})
    names = ", ".join(q + n + q for n in _perc.NAMES)
    desc = ", ".join(q + DESCRIPTIONS[n.split("-")[1]] + q for n in _perc.NAMES)
    shorts = ",\n".join(" {" + ", ".join(q + sh + q for _, sh in row) + "}" for row in perc_names())
    lidx = ",\n".join(" {" + ", ".join(str(longs.index(lo)) for lo, _ in row) + "}" for row in perc_names())
    return (f"#define PERC_N {_perc.N}\n#define PERC_TYPE_ID {TYPE_ID}\n"
            f"static const char perc_machine[PERC_N][7] = {{{names}}};\n"
            f"static const char perc_what[PERC_N][12] = {{{desc}}};\n"
            f"static const unsigned short perc_param_ids[8] = {{{', '.join(map(str, PARAM_IDS))}}};\n"
            f"static const char perc_short[PERC_N][8][5] = {{\n{shorts}\n}};\n"
            f"static const char *const perc_longs[{len(longs)}] = {{{', '.join(q + x + q for x in longs)}}};\n"
            f"static const unsigned char perc_long[PERC_N][8] = {{\n{lidx}\n}};\n")


def source(page_draw: int, cell: int) -> str:
    """The chunk's assembly (GNU as, ColdFire), linked at LOAD. PAGE_DRAW is the C
    renderer's entry, `wr_page_draw(view, canvas)`; CELL its `wr_cell(view, canvas, x,
    y, id)`, run as each cell widget of a stock page finishes (PING's and SHFT's TYPE)."""
    table = "\n".join(f"    .long {rid}, lab_{rid}" for rid in LABELS)
    strings = "\n".join(f'lab_{rid}: .asciz "{name}"' for rid, name in LABELS.items())
    pages = []
    for k, entries in enumerate(PAGES):
        pages.append(f"    .long title_{k}, subtitle\n"
                     f"    .long {', '.join(str(e) for e in entries)}\n"
                     f"    .long {TAG}")
    page_data = "\n".join(pages)
    rtable = "\n".join(f"    .long {rid}, rlab_{rid}" for rid in RES_LABELS)
    rstrings = "\n".join(f'rlab_{rid}: .asciz "{name}"' for rid, name in RES_LABELS.items())
    res_page_data = "\n".join(f"    .long res_title, res_subtitle\n"
                              f"    .long {', '.join(str(e) for e in entries)}\n"
                              f"    .long {TAG}" for entries in RES_PAGES)
    ztable = "\n".join(f"    .long {rid}, zlab_{rid}" for rid in CZ_LABELS)
    zstrings = "\n".join(f'zlab_{rid}: .asciz "{name}"' for rid, name in CZ_LABELS.items())
    cz_page_data = "\n".join(f"    .long cz_title, cz_subtitle\n"
                             f"    .long {', '.join(str(e) for e in entries)}\n"
                             f"    .long {TAG}" for entries in CZ_PAGES)
    return f"""
| -- the active track's machine, as ours: d0 = 1 Waverider (5), 2 RESONATOR (6), 3 CZ (7),
| else 0; every other register kept
is_wr:
    move.l  %a0,%sp@-
    move.l  %d1,%sp@-
    moveq   #0,%d1
    move.b  {ACTIVE_TRACK:#010x},%d1
    mulu.w  #{SOUND_STRIDE},%d1
    movea.l {KIT_POINTER:#010x},%a0
    adda.l  %d1,%a0
    mvs.b   %a0@({SOUND_BASE + SOUND_TYPE}),%d1
    moveq   #0,%d0
    subq.l  #{NEW_TYPE},%d1
    bne.s   2f
    moveq   #1,%d0
    bra.s   1f
2:  subq.l  #1,%d1
    bne.s   3f
    moveq   #2,%d0
    bra.s   1f
3:  subq.l  #1,%d1
    bne.s   1f
    moveq   #3,%d0
1:  move.l  %sp@+,%d1
    movea.l %sp@+,%a0
    rts

| -- 0x400c24d2 pages(type), from its first instruction by jsr. The stack: our return
| into the reader, the caller's return, the type. A Waverider track: 2, straight back
| to the caller. Otherwise M5's canon_arg: the displaced loads, 5 read as 1.
wr_count:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   1f
    addq.l  #4,%sp
    subq.l  #1,%d0
    bne.s   3f
    moveq   #{len(PAGES)},%d0
    rts
3:  subq.l  #1,%d0
    bne.s   4f
    moveq   #{len(RES_PAGES)},%d0
    rts
4:  moveq   #{len(CZ_PAGES)},%d0
    rts
1:  move.l  %sp@(8),%d0
    moveq   #5,%d1
    cmp.l   %d0,%d1
    beq.s   0f
    moveq   #6,%d1
    cmp.l   %d0,%d1
    beq.s   0f
    moveq   #7,%d1
    cmp.l   %d0,%d1
    bne.s   2f
0:  moveq   #{CLONE},%d0
2:  moveq   #4,%d1
    rts

| -- 0x400c24ee page(type, n), from 0x400c24f2 by jsr (after its own push of d2). The
| stack: our return, the saved d2, the caller's return, the type, the page. A Waverider
| track: our descriptor n (0..1) or the stock empty page, and back to the caller with d2
| restored. Otherwise M5's canon_page.
wr_page:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   3f
    subq.l  #1,%d0
    bne.s   5f
    move.l  %sp@(16),%d0
    moveq   #{len(PAGES)},%d1
    cmp.l   %d1,%d0
    bcs.s   1f
6:  move.l  #{EMPTY_PAGE:#010x},%d0
    bra.s   2f
1:  moveq   #44,%d1
    mulu.w  %d1,%d0
    addi.l  #descriptors,%d0
    bra.s   2f
5:  subq.l  #1,%d0
    bne.s   7f
    move.l  %sp@(16),%d0
    moveq   #{len(RES_PAGES)},%d1
    cmp.l   %d1,%d0
    bcc.s   6b
    moveq   #44,%d1
    mulu.w  %d1,%d0
    addi.l  #res_descriptors,%d0
    bra.s   2f
7:  move.l  %sp@(16),%d0
    moveq   #{len(CZ_PAGES)},%d1
    cmp.l   %d1,%d0
    bcc.s   6b
    moveq   #44,%d1
    mulu.w  %d1,%d0
    addi.l  #cz_descriptors,%d0
2:  addq.l  #4,%sp
    move.l  %sp@+,%d2
    rts
3:  move.l  %sp@(12),%d1
    move.l  %sp@(16),%d0
    subq.l  #5,%d1
    beq.s   0f
    subq.l  #1,%d1
    beq.s   0f
    subq.l  #1,%d1
    beq.s   0f
    addq.l  #7,%d1
    rts
0:  moveq   #{CLONE},%d1
    rts

| -- the SYN page's label fetch at 0x40064622 (jsr getShortName(this, id)), now jsr
| here. A Waverider track and a relabelled id: our label. Anything else: the stock
| getShortName, by a tail jump, so it returns to the page itself.
wr_label:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    lea     labels,%a0
    subq.l  #1,%d0
    beq.s   0f
    lea     res_label_table,%a0
    subq.l  #1,%d0
    beq.s   0f
    lea     cz_label_table,%a0
0:  move.l  %sp@(8),%d0
1:  move.l  %a0@+,%d1
    beq.s   9f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a0
    bra.s   1b
2:  move.l  %a0@,%d0
    rts
9:  jmp     {GET_SHORT_NAME:#010x}

| -- the SYN page draw at 0x4001821e (`moveq #7 ; cmp.l %d3,%d0 ; bne.w` past the icons),
| now `jsr` here and a nop. Back to the icons (0x40018226) when the stock test would draw
| them: page id 7 in d3, and not a Waverider track. Otherwise the return address becomes
| the stock branch target, past them. d0 is scratch there (the stock code loads it).
wr_icons:
    bsr.w   is_wr
    tst.l   %d0
    bne.s   3f
    moveq   #{ICON_PAGE},%d0
    cmp.l   %d3,%d0
    beq.s   2f
1:  move.l  #{ICON_SKIP:#010x},%sp@
2:  rts
| a Waverider track: never WaveTone's icons (its page, wave included, is wr_grid's)
3:  bra.s   1b

| -- the SYN page draw at 0x40018214 (`move.l %d2,-(%sp) ; move.l %a2,-(%sp) ; jsr grid ;
| addq.l #8,%sp`, 10 bytes), now jsr here and two nops. a2 = the view, d2 = the canvas.
wr_grid:
    move.l  %d2,%sp@-
    move.l  %a2,%sp@-
    bsr.w   is_wr
    tst.l   %d0
    beq.s   1f
    jsr     {page_draw:#010x}
    addq.l  #8,%sp
    rts
1:  jsr     {GRID:#010x}
    addq.l  #8,%sp
    rts

| -- the exit of 0x4006448a, a page's cell widget (view, canvas, x, y, id, ...), at
| 0x400646ca, now `jmp` here: its own epilogue, then wr_cell(view, canvas, x, y, id)
| with its d0 and d1 kept, and back to its caller.
wr_cell_tail:
    movem.l %sp@,%d2-%d7/%a2-%a6
    lea     %sp@(80),%sp
    movea.l %sp,%a1
    move.l  %d0,%sp@-
    move.l  %d1,%sp@-
    move.l  %a1@(20),%sp@-
    move.l  %a1@(16),%sp@-
    move.l  %a1@(12),%sp@-
    move.l  %a1@(8),%sp@-
    move.l  %a1@(4),%sp@-
    jsr     {cell:#010x}
    lea     %sp@(20),%sp
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    rts

| -- the SYN page draw at 0x40018202 (`moveq #9,%d1 ; cmp.l %d3,%d1 ; bne.s` to the grid
| call), now jsr here: back to the id-9 grid variant (0x40018208) only when the stock
| test would go there -- page id 9 in d3 and not one of our tracks; otherwise to the
| standard grid's call ({ID9_GRID:#010x}), which wr_grid answers. d1 = 9 either way,
| as stock leaves it; d0 is scratch (the grid call follows).
wr_id9:
    bsr.w   is_wr
    moveq   #9,%d1
    tst.l   %d0
    bne.s   1f
    cmp.l   %d3,%d1
    beq.s   2f
1:  move.l  #{ID9_GRID:#010x},%sp@
2:  rts

    .align 2
labels:
{table}
    .long 0
res_label_table:
{rtable}
    .long 0
cz_label_table:
{ztable}
    .long 0
descriptors:
{page_data}
res_descriptors:
{res_page_data}
cz_descriptors:
{cz_page_data}
{_rep("subtitle", SUBTITLE)}
{_rep("res_subtitle", RES_SUBTITLE)}
{_rep("res_title", RES_TITLE)}
{_rep("cz_subtitle", CZ_SUBTITLE)}
{_rep("cz_title", CZ_TITLE)}
{chr(10).join(_rep(f"title_{k}", t) for k, t in enumerate(TITLES))}
{strings}
{rstrings}
{zstrings}
    .align 2
"""

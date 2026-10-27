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
# v0.13: the C page renderer is a CODE chunk of its own, well above the others (it outgrew
# the room after this assembly, LOAD + 0x600 .. PING's chunk)
C_LOAD = 0x46AC0000                # clear of the emulator harnesses' stack and scratch (0x46a00000..)
C_SPAN = 0x10000
C_END = 0x46710000                # the platform runtime starts here
ACTIVE_TRACK = 0x42431A6C         # byte: the UI's active track, 0..15
KIT_POINTER = 0x800052A0          # the live kit; sound t at + 52 + 1163 t
SOUND_BASE, SOUND_STRIDE, SOUND_TYPE = 52, 1163, 0xDE
NEW_TYPE, CLONE = 5, 1
from ..mnm import machines as _mnm_types
TYPES_LAST = max(13, *_mnm_types.TYPES)   # dnfw.waverider.coldfire.TYPES_LAST: 5.. are ours (v0.20: 13,
                                  # SLICE, had been left out here: its track got WaveTone's pages;
                                  # v0.26: the Monomachine's from 14 on)
GET_SHORT_NAME = 0x400372DA
EMPTY_PAGE = 0x42432BD4           # the readers' own empty-page fallback
TAG = 10                          # the tag every stock SYN descriptor ends with

# PERC (machine 5, docs/perc.md; Waverider's place until v0.11): two pages on WaveTone
# records -- the eight parameters of dnfw.perc.machines.PARAMS; then TYPE (DRIF) and the
# track effects (FX_PARAMS). What each
# parameter is depends on TYPE, so its names are swapped per machine at run time
# (wr_names in page.c, from perc_c_header's tables); the page reads them back from the
# records, so it, the header line and the LFO lists always agree.
from ..perc import machines as _perc

TITLES = ("PRC 1", "PRC 2")
SUBTITLE = "Perc"
TYPE_ID = _perc.TYPE_REC[0]                                  # 252, DRIF
PARAM_IDS = tuple(r for r, _slot, _lo, _top in _perc.PARAMS)  # 238 242 254 253 256 257 260 240
FX_IDS = tuple(r for r, _slot, _lo, _top in _perc.FX_PARAMS)   # 239 246 250 244 243 258 253
PAGES = (
    PARAM_IDS,                                  # the machine's eight, as the Machinedrum's page
    (*FX_IDS, TYPE_ID),                         # AMD AMF EQF EQG / FLTF FLTW FLTQ, TYPE: the
)                                               # Machinedrum's FX page, TYPE in SRR's place (v0.20)
# no static labels: wr_label hands every PERC record to the stock getShortName, which
# reads the names wr_names swapped in
LABELS: dict[int, str] = {}
TYPE_NAMES = ("Perc Type", "TYPE")
UNUSED = tuple(r for r in range(238, 263) if r != TYPE_ID and r not in PARAM_IDS and r not in FX_IDS)
UNUSED_LONG, UNUSED_SHORT = "Unused", "-"
# a parameter's long name (LFO and modulation lists, the header line) from its short one
LONG = {"HAMR": "Hammer", "TENS": "Tension", "RING": "Ring", "RVOL": "Rattle Vol", "POS": "Position",   # v0.24 P-I
        "GRNS": "Grains", "GLEN": "Grain Length", "AG": "Highs Up", "AU": "Highs Down", "BR": "Lows",
        "GRAB": "Grab", "CLSN": "Closeness", "CLOS": "Close Time",
        "PTCH": "Pitch", "DEC": "Decay", "RAMP": "Ramp", "RDEC": "Ramp Decay", "STRT": "Start",
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
        "DOWN": "Down", "DVAL": "Down Value", "POWR": "Power", "NTUN": "Noise Tune",
        "NTYP": "Noise Type", "-": "Unused"}
# what each machine is, under its name in the middle of the page
DESCRIPTIONS = {"BD": "Bass Drum", "B2": "Bass Drum 2", "SD": "Snare", "XT": "Tom", "CP": "Clap",
                "RS": "Rimshot", "CB": "Cowbell", "CH": "Closed Hat", "OH": "Open Hat",
                "CY": "Cymbal", "MA": "Maracas", "CL": "Claves", "XC": "Conga", "HH": "Hi-Hat",
                "S2": "Snare 2",
                "SN": "Sine", "NS": "Noise", "IM": "Impulse",
                "MT": "Tom", "ML": "Metallica", "RC": "Ride", "CC": "Crash"}       # v0.24: P-I's


def type_of(word: int) -> int:
    """TYPE's record value (0..0x7f00) -> the machine, as the DSP reads it (dnfw.perc.program)"""
    return (min(127, max(0, word >> 8)) * _perc.N) >> 7


# v0.26: the Monomachine's machines (types 6, 7: docs/mnm.md), one page each, on PERC's
# eight records (PARAM_IDS), named per machine while such a track is active
from ..mnm import machines as _mnm
MNM_LONG = {"PW": "Pulse Width", "PWAD": "PW Sweep", "PWRS": "PW Restart", "WAVE": "Waveform",
            "MOD": "Modulation", "MSRC": "Mod Source", "MFRQ": "Mod Freq", "TUNE": "Tune",
            "WP": "Wave Position", "WPM": "WP Mod", "WPRS": "WP Restart", "SYNC": "Sync",
            "SFRQ": "Sync Freq", "---": "Unused",
            # DPRO-DDRW, DPRO-DENS (v0.26)
            "WAV1": "Wave 1", "MIX": "Wave Mix", "WAV2": "Wave 2", "TIME": "Fade Time",
            "BR1": "Bit Reduce 1", "WID": "Detune Width", "BR2": "Bit Reduce 2",
            "PCH2": "Pitch 2", "PCH3": "Pitch 3", "PCH4": "Pitch 4",
            # VO-6 (v0.26)
            "VOC1": "Vocal Freq 1", "VOC2": "Vocal Freq 2", "V-SW": "Vowel Switch",
            "VOIC": "Voice Type", "CONS": "Consonant", "CLEN": "Cons Length", "CVOL": "Cons Volume"}
# parameters the port does not run (DENS's chorus is the Monomachine's effect after the
# machine): drawn as "-", as an unused one
MNM_UNPORTED = {"CHRL", "CHRW"}


def _pch_names() -> tuple[tuple[int, ...], tuple[str, ...]]:
    """DENS's PCH2..4: the knob -> its choice (the ROM's ratio table runs, 33 of them),
    and their names as the Monomachine's: semitones -12..+12, OFF for 1.0, else the ratio"""
    import fractions
    import itertools
    import math
    from ..mnm import rom as mrom
    if not mrom.available():
        return tuple(range(128)), tuple(str(k) for k in range(128))
    t = mrom.words(*mrom.PCH)
    idx, names = [], []
    for v, g in itertools.groupby(t):
        r = v / 0x200000
        st = 12 * math.log2(r)
        if abs(st - round(st)) < 1e-3:
            n = "OFF" if round(st) == 0 else f"{round(st):+d}"
        else:
            f = fractions.Fraction(r).limit_denominator(6)
            n = f"{f.numerator}/{f.denominator}"
        idx += [len(names)] * len(list(g))
        names.append(n)
    return tuple(idx), tuple(names)
# the enumerated parameters: their choices by name, as the Monomachine shows them (0: a knob)
MNM_CHOICES = {
    "SID 6581": {"PWRS": ("OFF", "ON"), "WAVE": ("TRI", "SAW", "PULS", "MIX", "NOIS"),
                 "MOD": ("OFF", "RING", "SYNC", "R+S"), "MSRC": ("MFRQ", "PRCH")},
    "DPRO-WAVE": {"WAVE": 32, "WPRS": ("OFF", "ON"), "SYNC": ("OFF", "SFRQ", "PRCH")},
    # the Digibank's 64 (here the ROM's 32, twice: S01..S32) and DENS's pitches (by table)
    "DPRO-DDRW": {"WAV1": 64, "WAV2": 64},
    "DPRO-DENS": {"WAVE": 64, "PCH2": "pch", "PCH3": "pch", "PCH4": "pch"},
    # VO-6: its manual's names (Appendix A); V-SW below 64 ends the vowel
    "VO-6": {"V-SW": ("OFF", "ON"), "CONS": ("-", "B", "D", "F", "G", "H", "J", "K", "L", "M", "N",
                                            "P", "R", "RR", "S", "SJ", "T", "TJ", "TH", "V", "Z")},
}
MNM_WAVES = 32
MNM_PCH = 255                       # mnm_choices' mark: the choice by mnm_pch_idx[knob]


# the Monomachine's machines (v0.26; kinds 2 and 3 were RESONATOR's and CZ's until v0.25):
# is_wr's kind is the type - 4, so 2, 3 (types 6, 7) and 10.. (types 14..); one page of
# PERC's eight records each, labelled per machine
MNM_KINDS = tuple(t - 4 for t in _mnm_types.TYPES)
MNM_PAGE = PARAM_IDS
MNM_LABELS = [{r: (sh if sh != "---" and sh not in MNM_UNPORTED else "-") for r, sh in zip(PARAM_IDS, M.PNAMES)}
              for M in _mnm.MACHINES]
MNM_TITLES = tuple(_mnm.LIST_NAMES[n][1] for n in _mnm.NAMES)
MNM_SUBTITLES = tuple(_mnm.LIST_NAMES[n][0] for n in _mnm.NAMES)


def mnm_named(k: int) -> dict[int, tuple[str, str]]:
    """record -> (long, short) on a Monomachine machine's track"""
    M = _mnm.MACHINES[k]
    out = {r: ((MNM_LONG.get(sh, sh), sh) if sh != "---" and sh not in MNM_UNPORTED else (UNUSED_LONG, "-"))
           for r, sh in zip(PARAM_IDS, M.PNAMES)}
    out.update({r: (UNUSED_LONG, UNUSED_SHORT) for r in range(238, 263) if r not in out})
    return out


def mnm_c_header() -> str:
    q = chr(34)
    names, rows_n, rows_at = [], [], []
    for M in _mnm.MACHINES:
        ch = MNM_CHOICES.get(M.NAME, {})
        n_row, at_row = [], []
        for sh in M.PNAMES:
            c = ch.get(sh, 0)
            if c == "pch":
                n_row.append(MNM_PCH)
                at_row.append(len(names))
                names += list(_pch_names()[1])
            elif isinstance(c, int):
                n_row.append(c)
                at_row.append(0)
            else:
                n_row.append(len(c))
                at_row.append(len(names))
                names += list(c)
        rows_n.append(n_row)
        rows_at.append(at_row)

    def arr(rows):
        return ", ".join("{" + ", ".join(map(str, r)) + "}" for r in rows)
    labels = ", ".join("{" + ", ".join(q + (sh if sh != "---" and sh not in MNM_UNPORTED else "-") + q
                                       for sh in M.PNAMES) + "}" for M in _mnm.MACHINES)
    pidx = _pch_names()[0]
    lines = [
        f"#define MNM_N {len(_mnm.MACHINES)}",
        "/* is_wr's kind -> the Monomachine machine's index, -1 for any other kind */",
        "static inline int mnm_index(int kind)",
        "{",
        *[f"    if (kind == {kd}) return {k};" for k, kd in enumerate(MNM_KINDS)],
        "    return -1;",
        "}",
        f"#define MNM_WAVES {MNM_WAVES}",
        f"#define MNM_PCH {MNM_PCH}",
        f"static const unsigned char mnm_pch_idx[128] = {{{', '.join(map(str, pidx))}}};",
        f"static const char mnm_labels[MNM_N][8][6] = {{{labels}}};",
        f"static const unsigned char mnm_lo[8] = {{{', '.join(str(lo) for _r, _s, lo, _t in _perc.PARAMS)}}};",
        f"static const unsigned char mnm_top[8] = {{{', '.join(str(t) for _r, _s, _lo, t in _perc.PARAMS)}}};",
        f"static const unsigned char mnm_choices[MNM_N][8] = {{{arr(rows_n)}}};",
        f"static const unsigned char mnm_choice_at[MNM_N][8] = {{{arr(rows_at)}}};",
        f"static const char mnm_choice_names[{max(1, len(names))}][5] = {{{', '.join(q + n + q for n in names)}}};",
    ]
    return "\n".join(lines) + "\n"


# the Digitakt II's sample machines (types 8..12, docs/sampler.md): one page each, on
# WaveTone records (dnfw.sampler.machines.PAGES); named per machine by wr_names, as PERC's
from ..sampler import machines as _smp
SMP_FIRST = _smp.FIRST_TYPE
SMP_PAGES = tuple(tuple(r for r, _sh, _lo in _smp.PAGES.get(n, _smp.PAGES["ONESHOT"])) for n in _smp.NAMES)
SMP_TITLES = _smp.SHORT
SMP_SUBTITLES = tuple(n.capitalize() for n in _smp.NAMES)
SMP_REC_IDS = tuple(r for r, _sh, _lo in _smp.REC_PAGE)            # every sample machine's page 2


def smp_named(name: str) -> dict[int, tuple[str, str]]:
    """record -> (long, short) on a sample machine's track"""
    out = {r: (lo, sh) for r, sh, lo in _smp.PAGES.get(name, _smp.PAGES["ONESHOT"]) if r}
    out.update({r: (UNUSED_LONG, UNUSED_SHORT) for r in range(238, 263) if r not in out})
    return out


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
    machine alike: TYPE, the track effects, and the WaveTone records PERC leaves unused.
    The machine's eight are per machine (perc_names)."""
    return ([(TYPE_ID, *TYPE_NAMES)] + [(r, lo, sh) for r, (sh, lo) in zip(FX_IDS, _perc.FX_NAMES)]
            + [(r, UNUSED_LONG, UNUSED_SHORT) for r in UNUSED])


def perc_names() -> list[list[tuple[str, str]]]:
    """[machine][parameter] = (long, short), PARAM_IDS order"""
    return [[(LONG[sh], sh) for sh in _perc.PNAMES[name]] for name in _perc.NAMES]


def c_header() -> str:
    """The control tables, as C for `wr_gen.h`: per page, eight record ids and labels
    (Waverider's, then RESONATOR's); the names `wr_names` swaps in for each machine (a
    0 keeps the stock name); the scanner's shape names."""
    q = chr(34)
    ids = ",\n".join(" {" + ", ".join(str(r) for r in page) + "}" for page in PAGES)
    names = ",\n".join(" {" + ", ".join(f'"{label(r)}"' for r in page) + "}" for page in PAGES)
    wr = {r: (lo, sh) for r, lo, sh in named()}
    mnm = [mnm_named(k) for k in range(len(_mnm.MACHINES))]
    smp = [smp_named(n) for n in _smp.NAMES]
    order = sorted(set(wr) | set(PARAM_IDS) | {r for m in mnm + smp for r in m})
    # by kind (is_wr: the type - 4), from 1: PERC, the sample machines at SMP_FIRST_KIND..,
    # the Monomachine's at MNM_KINDS
    by_kind = {1: wr, **{SMP_FIRST_KIND + k: m for k, m in enumerate(smp)},
               **{kd: m for kd, m in zip(MNM_KINDS, mnm)}}
    if sorted(by_kind) != list(range(1, len(by_kind) + 1)):
        raise ValueError(f"the kinds are not 1..n: {sorted(by_kind)}")
    kinds = [by_kind[k] for k in sorted(by_kind)]

    def row(m, col):
        return "{" + ", ".join(q + m[r][col] + q if r in m else "0" for r in order) + "}"
    return (f"#define WR_PAGES {len(PAGES)}\n"
            f"static const unsigned short wr_ids[WR_PAGES][8] = {{\n{ids}\n}};\n"
            f"static const char wr_labels[WR_PAGES][8][6] = {{\n{names}\n}};\n"
            f"#define WR_NAMED {len(order)}\n"
            f"static const unsigned short wr_named_ids[WR_NAMED] = {{{', '.join(map(str, order))}}};\n"
            f"#define WR_KINDS {len(kinds)}\n"
            f"static const char *const wr_named_long[WR_KINDS][WR_NAMED] = {{{', '.join(row(m, 0) for m in kinds)}}};\n"
            f"static const char *const wr_named_short[WR_KINDS][WR_NAMED] = {{{', '.join(row(m, 1) for m in kinds)}}};\n"
            + perc_c_header() + smp_c_header() + mnm_c_header())


def smp_c_header() -> str:
    """The sample machines' tables for page.c: each machine's page (record ids), the
    records drawn as text, and the pool's sound names (the test sounds until loading)."""
    q = chr(34)
    from ..sampler import live as smp_live
    ids = ",\n".join(" {" + ", ".join(str(r) for r in page) + "}" for page in SMP_PAGES)
    names = ", ".join(q + n + q for n in _smp.NAMES)
    snd = ", ".join(q + n + q for n in smp_live.TEST_NAMES)
    return (f"#define SMP_KIND0 4\n#define SMP_N {len(_smp.NAMES)}\n#define WR_TYPES_LAST {TYPES_LAST}\n"
            f"static const unsigned short smp_ids[SMP_N][8] = {{\n{ids}\n}};\n"
            f"static const char smp_machine[SMP_N][8] = {{{names}}};\n"
            f"#define SMP_PLAY_ID {_smp.PLAY_REC}\n#define SMP_SAMP_ID {_smp.SAMP_REC}\n"
            f"#define SMP_STRT_ID {_smp.STRT_REC}\n#define SMP_LEN_ID {_smp.LEN_REC}\n"
            f"#define SMP_LOOP_ID {_smp.LOOP_REC}\n#define SMP_GRID_ID {_smp.GRID_REC}\n"
            f"#define SMP_SLICE_ID {_smp.SLICE_REC}\n#define SMP_SLEN_ID {_smp.SLEN_REC}\n"
            f"#define SMP_GRID_KIND {SMP_FIRST_KIND + _smp.NAMES.index('GRID')}\n"
            f"#define SMP_WERP_KIND {SMP_FIRST_KIND + _smp.NAMES.index('WERP')}\n"
            f"#define SMP_SLICE_KIND {SMP_FIRST_KIND + _smp.NAMES.index('SLICE')}\n"
            f"#define SMP_STRETCH_KIND {SMP_FIRST_KIND + _smp.NAMES.index('STRETCH')}\n"
            f"#define SMP_REPITCH_KIND {SMP_FIRST_KIND + _smp.NAMES.index('REPITCH')}\n"
            f"#define SMP_BARS_ID {_smp.BARS_REC}\n#define SMP_SEG_ID {_smp.SEG_REC}\n"
            f"#define SMP_MODE_ID {_smp.MODE_REC}\n"
            f"static const unsigned short smp_rec_ids[8] = {{{', '.join(str(r) for r in SMP_REC_IDS)}}};\n"
            f"#define SMP_RSRC_ID {_smp.RSRC_REC}\n#define SMP_RCHAN_ID {_smp.RCHAN_REC}\n"
            f"#define SMP_RTHR_ID {_smp.RTHR_REC}\n#define SMP_RDST_ID {_smp.RDST_REC}\n"
            f"#define SMP_RLEN_ID {_smp.RLEN_REC}\n#define SMP_RSTRT_ID {_smp.RSTRT_REC}\n"
            f"#define SMP_ARM_ID {_smp.ARM_REC}\n#define SMP_REC_FIRST {_smp.REC_FIRST}\n"
            f"#define SMP_REC_SECONDS10 {_smp.REC_FRAMES * 10 // 48000}\n"
            f"#define SMP_REC_SOURCES {len(_smp.SRC_NAMES)}\n"
            f"static const char smp_rec_chan[3][4] = {{{', '.join(q + m + q for m in ('L+R', 'L', 'R'))}}};\n"
            f"static const char smp_rec_src[{len(_smp.SRC_NAMES)}][8] = {{{', '.join(q + m + q for m in _smp.SRC_NAMES)}}};\n"
            f"static const char smp_bars[8][4] = {{{', '.join(q + b + q for b in ('1', '2', '4', '8', '8', '8', '8', '8'))}}};\n"
            f"static const unsigned char smp_bars_steps[7] = {{{', '.join(map(str, _smp.BARS_STEPS))}}};\n"
            f"static const unsigned char smp_seg_steps[7] = {{{', '.join(map(str, _smp.SEG_STEPS))}}};\n"
            f"static const char smp_play[4][5] = {{{', '.join(q + m + q for m in _smp.PLAY_MODES)}}};\n"
            f"static const unsigned char smp_grids[{len(_smp.GRIDS)}] = {{{', '.join(map(str, _smp.GRIDS))}}};\n"
            + smp_widgets_header() + smp_quant_header() +
            f"#define SMP_SOUNDS {len(smp_live.TEST_NAMES)}\n"
            f"static const char smp_sound[SMP_SOUNDS][6] = {{{snd}}};\n")


SMP_FIRST_KIND = 4                 # is_wr's answer for type 8; 5..8 for 9..12


def smp_quant_header() -> str:
    """v0.15: the one-detent-a-choice tables for csrc/sampler/fmt.c (dnfw.sampler.machines.QUANT)"""
    def mask(names):
        return sum(1 << _smp.NAMES.index(n) for n in names)
    rows, steps = [], []
    for names, rec, th, rep in _smp.QUANT:
        slot = _smp.RECORDS[rec][0]
        thr = list(th) + [255] * (17 - len(th))
        rp = list(rep) + [0] * (18 - len(rep))
        rows.append(f" {{{mask(names)}, {slot}, {len(rep)}, {{{', '.join(map(str, thr))}}}, "
                    f"{{{', '.join(map(str, rp))}}}}}")
    for names, rec, step in _smp.QUANT_STEP:
        slot, lo, top = _smp.RECORDS[rec]
        steps.append(f" {{{mask(names)}, {slot}, {step}, {lo}, {lo + top}}}")
    return ("struct smp_q { unsigned char types, slot, n, th[17], rep[18]; };\n"
            "struct smp_qs { unsigned char types, slot, step, lo, hi; };\n"
            f"#define SMP_NQ {len(rows)}\nstatic const struct smp_q smp_q[SMP_NQ] = {{\n" + ",\n".join(rows) + "\n};\n"
            f"#define SMP_NQS {len(steps)}\nstatic const struct smp_qs smp_qs[SMP_NQS] = {{\n" + ",\n".join(steps) + "\n};\n"
            f"#define SMP_PLAY_REC {_smp.PLAY_REC}\n#define SMP_MODE_REC {_smp.MODE_REC}\n"
            f"#define SMP_BARS_REC {_smp.BARS_REC}\n#define SMP_SEG_REC {_smp.SEG_REC}\n"
            f"#define SMP_GRID_REC {_smp.GRID_REC}\n#define SMP_SAMP_REC {_smp.SAMP_REC}\n"
            f"#define SMP_SEG_LO {_smp.RECORDS[_smp.SEG_REC][1]}\n"
            f"#define SMP_SEG_SLOT {_smp.RECORDS[_smp.SEG_REC][0]}\n"
            f"#define SMP_SAMP_SLOT {_smp.RECORDS[_smp.SAMP_REC][0]}\n")
SMP_WAVE_W, SMP_WAVE_AMP = 100, 11         # the waveform strip: columns, half-height in pixels
SMP_GLYPHS = "0123456789AB/-YES"


def smp_widgets_header() -> str:
    """v0.15, the DT2-style page: each record's widget kind, a 3x5 font for the SAMP box's
    inverted bank letter and digits, and the test sounds' waveform overviews (peak per
    column, 0..SMP_WAVE_AMP) -- the uploaded sounds' are read from the mirror."""
    import json
    import pathlib
    from ..sampler import live as smp_live
    kinds = ("none", "bipolar", "play", "empty", "samp", "knob", "fader", "seg", "bars")
    w = _smp.WIDGETS
    font = json.loads((pathlib.Path(__file__).resolve().parents[1] / "font3x5.json").read_text())["glyphs"]
    glyphs = ", ".join("{" + ", ".join(str(int(r, 2)) for r in font[ch]) + "}" for ch in SMP_GLYPHS)
    waves = []
    for snd in smp_live.test_samples():
        n = len(snd)
        col = []
        for c in range(SMP_WAVE_W):
            seg = snd[c * n // SMP_WAVE_W:max(c * n // SMP_WAVE_W + 1, (c + 1) * n // SMP_WAVE_W)]
            col.append(min(SMP_WAVE_AMP, round(max(abs(x) for x in seg) * SMP_WAVE_AMP)))
        waves.append("{" + ", ".join(map(str, col)) + "}")
    ids = sorted(w)
    q = chr(34)
    return (f"#define SMP_WAVE_W {SMP_WAVE_W}\n#define SMP_WAVE_AMP {SMP_WAVE_AMP}\n"
            + "".join(f"#define W_{k.upper()} {i}\n" for i, k in enumerate(kinds))
            + f"#define SMP_WIDGETS {len(ids)}\n"
            f"static const unsigned short smp_widget_ids[SMP_WIDGETS] = {{{', '.join(map(str, ids))}}};\n"
            f"static const unsigned char smp_widget_kind[SMP_WIDGETS] = {{{', '.join(str(kinds.index(w[r])) for r in ids)}}};\n"
            f"static const char smp_glyph_chars[] = {q}{SMP_GLYPHS}{q};\n"
            f"static const unsigned char smp_glyph[{len(SMP_GLYPHS)}][5] = {{{glyphs}}};\n"
            f"static const unsigned char smp_test_wave[{len(waves)}][SMP_WAVE_W] = {{{', '.join(waves)}}};\n")


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
            f"static const unsigned char perc_long[PERC_N][8] = {{\n{lidx}\n}};\n"
            + md_c_header())


MDUI_LOAD = 0x46AE0000                          # the Machinedrum's screen graphics (dnfw.md.ui)
MD_FX_NIBBLES = 0x31313311                      # AMD-AMF, EQF-EQG, FLTF-FLTW-FLTQ clipped, as the MD's
TRACK_LEVEL_ID = 10                             # record 10, "Track Level" / LEV, 0..0x7f00 (read from the 1.11 record table)


def md_c_header() -> str:
    """md_page.c's: where the MD's graphics are and how they are laid out (dnfw.md.ui: no
    Elektron data here), the FX page's clips, the machines' descriptions in capitals."""
    from ..md import ui
    q = chr(34)
    upper = ", ".join(q + DESCRIPTIONS[n.split("-")[1]].upper() + q for n in _perc.NAMES)
    return (ui.c_header() + f"#define MDUI_LOAD {MDUI_LOAD:#x}u\n#define MD_FX_NIBBLES {MD_FX_NIBBLES:#x}u\n"
            f"#define TRACK_LEVEL_ID {TRACK_LEVEL_ID}\n"
            f"static const char perc_what_upper[PERC_N][12] = {{{upper}}};\n")


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
    mtables = "\n".join(f"    .long mnm_labels_{k}" for k in range(len(MNM_LABELS)))
    mtables += "\n" + "\n".join(f"mnm_labels_{k}:\n" + "\n".join(f"    .long {rid}, mlab_{k}_{rid}" for rid in lab)
                                + "\n    .long 0" for k, lab in enumerate(MNM_LABELS))
    mstrings = "\n".join(f'mlab_{k}_{rid}: .asciz "{name}"' for k, lab in enumerate(MNM_LABELS)
                          for rid, name in lab.items())
    mnm_page_data = "\n".join(f"    .long mnm_title_{k}, mnm_subtitle_{k}\n"
                              f"    .long {', '.join(str(e) for e in MNM_PAGE)}\n"
                              f"    .long {TAG}" for k in range(len(MNM_LABELS)))
    smp_page_data = "\n".join(f"    .long smp_title_{k}, smp_subtitle_{k}\n"
                              f"    .long {', '.join(str(e) for e in entries)}\n"
                              f"    .long {TAG}" for k, entries in enumerate(SMP_PAGES))
    smp_page_data += ("\nsmp_rec_descriptor:\n    .long smp_rec_title, smp_rec_subtitle\n"
                      f"    .long {', '.join(str(e) for e in SMP_REC_IDS)}\n    .long {TAG}")
    return f"""
| -- the active track's machine, as ours: d0 = its type - 4 for types 5..{TYPES_LAST}: 1 PERC,
| 4..9 the sample machines (8..13), 2, 3 and 10.. the Monomachine's (6, 7, 14..), else 0;
| every other register kept
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
    subq.l  #{NEW_TYPE - 1},%d1
    ble.s   1f
    cmpi.l  #{TYPES_LAST - NEW_TYPE + 1},%d1
    bgt.s   1f
    move.l  %d1,%d0
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
3:  moveq   #2,%d1                         | d0 = kind - 1: 1, 2 and 9.. the Monomachine's
    cmp.l   %d1,%d0
    bls.s   4f
    moveq   #8,%d1
    cmp.l   %d1,%d0
    bls.s   5f
4:  moveq   #1,%d0                         | a Monomachine machine: its one page
    rts
5:  moveq   #2,%d0                         | a sample machine: its two pages (v0.22: the recorder is FUNC + VOICE)
    rts
1:  move.l  %sp@(8),%d0
    cmpi.l  #{NEW_TYPE},%d0
    blt.s   2f
    cmpi.l  #{TYPES_LAST},%d0
    bgt.s   2f
    moveq   #{CLONE},%d0
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
| d0 = kind - 1: 1, 2 -> the Monomachine's 0, 1; 3..8 a sample machine; 9.. -> 2..
5:  moveq   #9,%d1
    cmp.l   %d1,%d0
    bcc.s   7f
    moveq   #3,%d1
    cmp.l   %d1,%d0
    bcc.s   4f
    addq.l  #6,%d0
7:  subq.l  #7,%d0                         | the Monomachine machine's index
    move.l  %sp@(16),%d1                   | its one page
    bne.s   6b
    moveq   #44,%d1
    mulu.w  %d1,%d0
    addi.l  #mnm_descriptors,%d0
    bra.s   2f
4:  subq.l  #2,%d0
| a sample machine (d0 = its kind - 3): pages 0 and 1 its own (the DT2's SRC page 1 and
| page 2, the same parameters), page 2 the recorder
8:  move.l  %sp@(16),%d1
    subq.l  #2,%d1
    bcs.s   9f
    bne.s   6b
    move.l  #smp_rec_descriptor,%d0
    bra.s   2f
9:  subq.l  #1,%d0
    moveq   #44,%d1
    mulu.w  %d1,%d0
    addi.l  #smp_descriptors,%d0
2:  addq.l  #4,%sp
    move.l  %sp@+,%d2
    rts
3:  move.l  %sp@(12),%d1
    move.l  %sp@(16),%d0
    cmpi.l  #{NEW_TYPE},%d1
    blt.s   0f
    cmpi.l  #{TYPES_LAST},%d1
    bgt.s   0f
    moveq   #{CLONE},%d1
0:  rts

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
    moveq   #3,%d1                         | d0 = kind - 1: 1, 2 and 9.. the Monomachine's,
    cmp.l   %d1,%d0                        | 3..8 a sample machine (the stock names)
    bcs.s   3f
    moveq   #9,%d1
    cmp.l   %d1,%d0
    bcs.s   9f
    subq.l  #6,%d0
3:  subq.l  #1,%d0                         | the Monomachine machine's index
    lsl.l   #2,%d0
    lea     mnm_label_tables,%a0
    adda.l  %d0,%a0
    movea.l %a0@,%a0
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
mnm_label_tables:
{mtables}
descriptors:
{page_data}
mnm_descriptors:
{mnm_page_data}
smp_descriptors:
{smp_page_data}
{_rep("subtitle", SUBTITLE)}
{chr(10).join(_rep(f"mnm_title_{k}", t) for k, t in enumerate(MNM_TITLES))}
{chr(10).join(_rep(f"mnm_subtitle_{k}", t) for k, t in enumerate(MNM_SUBTITLES))}
{chr(10).join(_rep(f"smp_title_{k}", t) for k, t in enumerate(SMP_TITLES))}
{chr(10).join(_rep(f"smp_subtitle_{k}", t) for k, t in enumerate(SMP_SUBTITLES))}
{_rep("smp_rec_title", "REC")}
{_rep("smp_rec_subtitle", "Recorder")}
{chr(10).join(_rep(f"title_{k}", t) for k, t in enumerate(TITLES))}
{strings}
{mstrings}
    .align 2
"""

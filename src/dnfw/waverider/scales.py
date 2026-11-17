"""v0.58: two microtonal scales in KB SETUP's SCALE list (owner, 2026-11-16).

Stock OS 1.11 keeps 35 scales (index 0 Ionian .. 34 Locrian bb3 bb7; -1 Chromatic) in five
tables, each read through one accessor (docs/microtonal.md):

- full names, index + 1 (0x402a0e28, 36 pointers; scale_name 0x401500a6);
- short names, index + 1 (0x402a0eb8, 36 pointers; 0x40150096);
- the keys, index + 1 (0x4020e320, 16 words a row: key k -> semitone; 0x401500c6);
- the degrees, index (0x4020dea0, 8 words a row, -1 ends: chord MODEs; 0x401500dc);
- the membership masks, index (0x4020ec20, 13 bytes a row: semitone 0..12 in the scale;
  0x4014fe60);
- (v0.59) the chord MODEs' degree lists, index: 35 std::vectors of 12 bytes (begin, end, cap) at
  0x405c6b98 in RAM, built on the keyboard's first chord from constant int arrays in flash
  (0x40034770..0x40034af0: one constructor call a scale, 5 to 8 degrees), read by the chord code at
  0x40034b44 (base + 12 x scale), which divides by the list's length. v0.58 left this one out: on
  POOLE ROD12 / POOLE12 MIN a chord read past the 35th list, found an empty one and divided by zero
  (zuzsw, 2026-11-17: EXCEPTION at P 40034BA6). The build now gives the chord code a const table
  of 37 lists, each pointing straight at stock's own constant array (the same ints stock copies),
  ROD12's Ionian's and MIN12's Aeolian's.

and four getters/setters clamp the stored byte to -1..34. The build copies the five tables
(stock rows, as stock has them) into the C chunk with two rows more, points the five accessors
at the copies and raises the clamps to 36:

- 35 POOLE ROD12: a 12-note scale, so it lays out and plays as Chromatic (keys and mask);
  in a chord MODE (Chromatic has none) it builds Ionian's chords.
- 36 POOLE12 MIN: Aeolian's degrees (1 2 b3 4 5 b6 b7), every row Aeolian's.

What makes them microtonal is the tuning: tune.c adds each note's cents (by its pitch class
above the track's ROOT) to the voice's frame NOTE word (note + fine/256)."""

from __future__ import annotations

import struct

BASE = 0x40000400
N_STOCK = 35                       # indices 0..34 (-1 Chromatic)
ROD12, MIN12 = 35, 36
LAST = MIN12

NAMES_VA, SHORT_VA = 0x402A0E28, 0x402A0EB8
CHORDVEC_RAM = 0x405C6B98                  # stock's 35 runtime lists (12 bytes each)
CHORD_INIT = (0x40034770, 0x40034AF0)      # the code that builds them
KEYS_VA, DEG_VA, MASK_VA = 0x4020E320, 0x4020DEA0, 0x4020EC20
KEYS_ROW, DEG_ROW, MASK_ROW = 16, 8, 13
AEOLIAN, IONIAN = 5, 0

NAMES = {ROD12: ("Poole Rod12", "PR12"), MIN12: ("Poole12 Min", "PM12")}

# cents against 12-TET, by semitone above the root (owner's .scl files, 2026-11-16);
# None: not a degree of the scale (a note there is played as 12-TET)
CENTS = {
    ROD12: (0.0, -46.7, 3.9, -33.1, 17.5, -2.0, -48.7, 2.0, -35.1, 5.9, -31.2, -50.6),
    MIN12: (0.0, None, 3.9, -33.1, None, -2.0, None, 2.0, -35.1, None, -31.2, None),
}

# the accessors' table operands (the absolute after the opcode) and the clamps (moveq #34)
SITES = (  # va of the 32-bit operand, opcode bytes before it, stock table, label
    (0x4015009C, "41f9", SHORT_VA, "kb_short"),
    (0x401500AC, "41f9", NAMES_VA, "kb_names"),
    (0x401500CC, "41f9", KEYS_VA, "kb_keys"),
    (0x401500E2, "41f9", DEG_VA, "kb_deg"),
    (0x4014FEBA, "d1fc", MASK_VA, "kb_mask"),
    (0x40034B46, "d9fc", CHORDVEC_RAM, "kb_chordvec"),  # v0.59: addal #lists,a4
)
CLAMPS = (  # va, register byte, what
    (0x4003AA34, 0x72, "KB SCALE getter: bound"), (0x4003AA3A, 0x70, "KB SCALE getter: clamp"),
    (0x4003AA6E, 0x74, "KB SCALE setter: bound"), (0x4003AA74, 0x72, "KB SCALE setter: clamp"),
    (0x4005076E, 0x72, "track SCALE getter: bound"), (0x40050774, 0x70, "track SCALE getter: clamp"),
    (0x400507B0, 0x74, "track SCALE setter: bound"), (0x400507B6, 0x72, "track SCALE setter: clamp"),
)


def _rd(stock: bytes, va: int, n: int) -> bytes:
    return bytes(stock[va - BASE:va - BASE + n])


def _words(stock: bytes, va: int, n: int) -> list[int]:
    return list(struct.unpack(f">{n}i", _rd(stock, va, 4 * n)))


def tables(stock: bytes) -> dict:
    """-> the five tables' new rows: stock's rows, then ROD12's and MIN12's."""
    keys = [_words(stock, KEYS_VA + 4 * KEYS_ROW * r, KEYS_ROW) for r in range(N_STOCK + 1)]
    deg = [_words(stock, DEG_VA + 4 * DEG_ROW * r, DEG_ROW) for r in range(N_STOCK)]
    mask = [list(_rd(stock, MASK_VA + MASK_ROW * r, MASK_ROW)) for r in range(N_STOCK)]
    chromatic = keys[0]
    if chromatic != [8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7]:
        raise ValueError("the stock key table's Chromatic row is not where it was")
    if deg[AEOLIAN] != [0, 2, 3, 5, 7, 8, 10, -1] or deg[IONIAN] != [0, 2, 4, 5, 7, 9, 11, -1]:
        raise ValueError("the stock degree table's Ionian/Aeolian rows are not where they were")
    keys += [list(chromatic), list(keys[AEOLIAN + 1])]
    deg += [list(deg[IONIAN]), list(deg[AEOLIAN])]
    mask += [list(range(1, 14)), list(mask[AEOLIAN])]
    # the minor's degrees are Aeolian's: its tuning names exactly those semitones
    if [s for s, c in enumerate(CENTS[MIN12]) if c is not None] != deg[AEOLIAN][:7]:
        raise ValueError("POOLE12 MIN's degrees are not Aeolian's")
    names = [struct.unpack(">I", _rd(stock, NAMES_VA + 4 * i, 4))[0] for i in range(N_STOCK + 1)]
    short = [struct.unpack(">I", _rd(stock, SHORT_VA + 4 * i, 4))[0] for i in range(N_STOCK + 1)]
    return {"keys": keys, "deg": deg, "mask": mask, "names": names, "short": short}


def chord_lists(stock: bytes) -> list[tuple[int, int]]:
    """-> stock's 35 chord degree lists as (flash address, count), read from the code that
    builds them: each constructor call is `moveq #n,d1`, `movel #array,d0`, `pea list`,
    `jsr (a4)`, list i at CHORDVEC_RAM + 12 i."""
    lo, hi = CHORD_INIT
    code = _rd(stock, lo, hi - lo)
    out, n, arr, vec = [], None, None, None
    i = 0
    while i < len(code) - 1:
        w = code[i:i + 2]
        if w[0] == 0x72:                                   # moveq #n,d1
            n = w[1]
        elif w == b"\x20\x3c":                             # movel #imm,d0
            arr = struct.unpack(">I", code[i + 2:i + 6])[0]
        elif w == b"\x48\x79":                             # pea abs.l
            vec = struct.unpack(">I", code[i + 2:i + 6])[0]
        elif w == b"\x4e\x94":                             # jsr (a4)
            out.append((vec, arr, n))
        i += 2
    lists = []
    for k, (vec, arr, cnt) in enumerate(out):
        if vec != CHORDVEC_RAM + 12 * k or not cnt or not 0 < cnt <= 12 or not arr:
            raise ValueError(f"stock's chord list {k} is not where it was ({vec:#x}, {arr}, {cnt})")
        lists.append((arr, cnt))
    if len(lists) != N_STOCK:
        raise ValueError(f"{len(lists)} chord lists in stock's builder, not {N_STOCK}")
    for arr, cnt in lists:                                  # degrees 0..11, ascending
        d = _words(stock, arr, cnt)
        if not all(0 <= x < 12 for x in d) or d != sorted(d):
            raise ValueError(f"stock's chord list at {arr:#x} is not a scale: {d}")
    return lists


def fine(c: float | None) -> int:
    """cents -> the NOTE word's fine units (1/256 semitone)."""
    return 0 if c is None else int(round(c * 256 / 100))


def c_header(stock: bytes) -> str:
    t = tables(stock)

    def rows(rs, fmt="{}"):
        return ",\n ".join("{" + ", ".join(fmt.format(v) for v in r) + "}" for r in rs)
    names = ", ".join(f"(const char *){p:#010x}u" for p in t["names"]) + ", tn_long_35, tn_long_36"
    short = ", ".join(f"(const char *){p:#010x}u" for p in t["short"]) + ", tn_short_35, tn_short_36"
    strings = "".join(f'const char tn_long_{i}[] = "{NAMES[i][0]}";\nconst char tn_short_{i}[] = "{NAMES[i][1]}";\n'
                      for i in (ROD12, MIN12))
    lists = chord_lists(stock)
    lists += [lists[IONIAN], lists[AEOLIAN]]
    chord = ",\n ".join(f"{{{a:#010x}u, {a + 4 * c:#010x}u, {a + 4 * c:#010x}u}}" for a, c in lists)
    tune = ",\n ".join("{" + ", ".join(str(fine(c)) for c in CENTS[i]) + "}" for i in (ROD12, MIN12))
    n = LAST + 2
    return (f"\n/* v0.58 microtonal scales (dnfw.waverider.scales) */\n#ifdef TUNE_C\n"
            f"#define TN_FIRST {ROD12}\n#define TN_LAST {LAST}\n" + strings +
            f"const char *const kb_names[{n}] = {{{names}}};\n"
            f"const char *const kb_short[{n}] = {{{short}}};\n"
            f"const int kb_keys[{n}][{KEYS_ROW}] = {{\n {rows(t['keys'])}}};\n"
            f"const int kb_deg[{n - 1}][{DEG_ROW}] = {{\n {rows(t['deg'])}}};\n"
            f"const unsigned char kb_mask[{n - 1}][{MASK_ROW}] = {{\n {rows(t['mask'])}}};\n"
            f"const unsigned int kb_chordvec[{LAST + 1}][3] = {{\n {chord}}};\n"
            f"static const short tn_fine[{LAST - ROD12 + 1}][12] = {{\n {tune}}};\n#endif\n")

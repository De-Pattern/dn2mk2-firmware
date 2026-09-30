# Waverider M7 and M8: its own SYN pages, and its wave

**Goal (owner, 2026-10-01).** A Waverider track gets its own two SYN pages, laid out from the "Wavefinder on Digitone II" mockup but with our own names, and structured around a picture of the wave:

| | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| page 1, OSC 1 | TUNE | LEV | POS | TBL | RATE | MPOS | MLEV | MOVE |
| page 2, OSC 2 | DETN | LEV | POS | TBL | RATE | MPOS | MLEV | MOVE |

- **Header:** the machine name reads `Waverider`.
- **Controls not yet working show `-`** (an empty box). In M7 only TUNE, POS and TBL work, as in M6.
- **Tables:** TBL picks from a pool loaded from the +Drive (`docs/waverider-tables.md`), so no part of M7 assumes two baked tables. M8's display copy of the tables is the one piece that does, and it moves with them.
- **M8** adds the waveform display. **M9** adds LEV and osc 2. **M10** adds the MOVE modulator.

Grades: **[D]** read statically, **[E]** measured in an emulator, **[H]** on the instrument, **[O]** open.

## What is built

| | where | what |
|---|---|---|
| page count | `0x400c24d2` → `wr_count` | 2 for a Waverider track; otherwise M5's `canon_arg` |
| page descriptor | `0x400c24f2` → `wr_page` | our descriptor 0..1, or the stock empty page past them; otherwise M5's `canon_page` |
| labels | `0x40064622` → `wr_label` | TUNE / POS / TBL for ids 238 / 239 / 247 on a Waverider track; everything else is the stock `getShortName` by a tail jump |
| WaveTone's icons, and the wave | `0x4001821e` → `wr_icons` | skip WaveTone's oscillator icons on a Waverider track; on its first page, draw `wr_wave` instead (M8) |

All of it is one platform `CODE` chunk at `0x4670c000` (`dnfw.waverider.pages`, `dnfw.waverider.wave`), about 1.7 KB. "Is this a Waverider track?" is `is_wr`: the **active track**'s sound (`[0x800052a0] + 52 + 1163 t`, `t` = the byte `0x42431a6c`) has 5 at `+0xDE`. The readers themselves are always handed type 1, because M5 reports 5 as 1 to the UI.

**Emulator [E] (2026-10-01, `scripts/emu_waverider_menu.py`, snapshot `wr-ui800M`):**
- a Waverider track shows `Waverider (1/2)` and `(2/2)`; page 1 is TUNE, an empty box, POS (the wave), TBL, then four empty boxes; page 2 is eight empty boxes;
- POS moves the wave: table 0 (PRIM) goes from the saw at 0 to the sine at 120; table 1 (HARM) goes from the fundamental to the 16th partial; the marker under the wave follows POS;
- control: a WaveTone track on the same build keeps its three pages, its labels and its icons;
- M7e and M8b boot from reset and draw their UI (`scripts/emu_boot_check.py`).

## How the SYN pages are found (DN2 1.11) [D]

- **The per-machine table** is at `0x42432ad4`: one 16-byte entry per machine type, types 0-4:
  - `+0`: the page count;
  - `+4..+0xf`: a `std::vector` of 44-byte page descriptors (begin, end, capacity).

  The entries sit 16 bytes apart, so a sixth would land on `0x42432b24`, which is the start of the next table. **The table cannot grow in place.** That is why the readers are hooked rather than the table extended.
- **The readers:**
  - `0x400c24d2(type)` returns the count; it answers 1 above type 4;
  - `0x400c24ee(type, page)` returns `begin + 44 * page`, or the empty page `0x42432bd4` above type 4 or past the count;
  - `0x400c248e(type)` returns an overview descriptor, `0x42432b24 + 44 * type`: every entry 0, titles only. It keeps M5's `canon_arg`.

  Their callers are at `0x40016856`, `0x400168e6`, `0x4001696a`, `0x40017422`, `0x400177e8`, `0x4003e6fa`, `0x40045cdc`, `0x40046120`, `0x4005c4ee` and `0x40064ece`.
- **A descriptor** is `{std::string title, std::string subtitle, 8 record ids, tag 10}`. The page view reads id `n` at `+8 + 4n` (`0x4001683a`, the view's `vtable+188`). An id of 0 draws the dotted empty box (`0x446452a8`, blitted from `0x4001747e`) [E].
- **The strings** are GCC's old-ABI copy-on-write `std::string`: the object is a pointer to the characters, with `{length, capacity, reference count}` in the 12 bytes before them. A live WaveTone title reads `{7, 7, 0}` + `DN VA 1` [E]. Ours carry a reference count of -1 (unshareable): a copy clones it and never shares it. With a count of 0, the last copy's release would free our static chunk.
- **The initializer** (around `0x400ca800..0x400cad60`) builds each machine's descriptors on the stack and assigns the vector. **WaveTone (type 1) has 3 pages** (`moveq #3; move.l d0,0x42432ae4` at `0x400caa4a`):

  | page | title | subtitle | entries (record ids) | tag |
  |---|---|---|---|---|
  | 1 | `DN VA 1` (`0x4021a667`) | `WaveTone` (`0x4021a66f`) | 238-245 | 10 |
  | 2 | `DN VA 2` (`0x4021a678`) | `WaveTone` | 246-252 and one empty entry | 10 |
  | 3 | `DN VA 3` (`0x4021a680`) | `WaveTone` | 253+ | 10 |

- **The header** shows the subtitle and the page number (`Waverider (1/2)`), not the title [E].

## The SYN page draw, and WaveTone's icons [D][E]

`0x40018118` draws a SYN page. It reads the type (`0x4004b7f2`) and a page id `d3` (the view's `vtable+136`), then branches:
- **type 1, page id 9** (WaveTone page 3): `0x400175e4`, the grid variant for ids 253+;
- **type 1, otherwise:** the standard grid `0x40017428`. Then, **if the page id is 7** (WaveTone's OSC page), it draws **WaveTone's two oscillator icons**:
  - `0x40016cee(this, canvas, col 1, row 0, value(WAV1 239), value(TBL1 247), selected)` at B;
  - the same with WAV2 243 and TBL2 251 at F.

  Each icon is a frame of a sprite sheet in RAM (`0x4464752c` for table 0, `0x44647150` otherwise), picked by the WAV value over `0x7800`.

A Waverider track is type 1 to this draw, and its first page is page id 7 as well. So until `wr_icons`, **WaveTone's icons were drawn on a Waverider page at B and F, whatever our descriptor said** [E]. The WAV1 record itself draws no widget in its cell, because WaveTone always left that to the overlay. That is why POS at C first showed a label over nothing, and it is where M8 draws.

**Found by:** logging the page view's id reads (`--regs-at 0x4001746a --regs-last 16`). The last draws touched only cells A and D, so the B/F pixels had to come from something else. Then a panel-buffer write watch on cell B after the page had settled (`--panel-writers 50,16,67,27` with the `reset-trace` step) showed a second blit into the cell after the empty box, returning to `0x40016d52`. Its only caller is `0x40018246`.

## The records WaveTone's pages name [D]

The parameter table is at `0x401f7f94`: 321 records of 60 bytes (`+0x00` page, `+0x04` slot, `+0x28` long name, `+0x30` short name, `+0x34` formatter).

| id | short | slot | long name | Waverider use |
|---|---|---|---|---|
| 238 | TUN1 | 25 | Osc1 Tune | **TUNE** (osc 1), M7 |
| 239 | WAV1 | 26 | Osc1 Waveform | **POS** (osc 1), M7 |
| 247 | TBL1 | 27 | Osc1 Wave Table | **TBL** (osc 1), M7 |
| 241 | LEV1 | 30 | Osc1 Level | LEV (osc 1) |
| 240 | PD1 | 29 | Osc1 Phase Dist | RATE (osc 1) |
| 246 | OFS1 | 28 | Osc1 Lin Offset | MPOS (osc 1) |
| 248 | MOD | 37 | Osc Mod | MLEV (osc 1) |
| 249 | RSET | 39 | Osc Phase Reset | MOVE (osc 1) |
| 242 | TUN2 | 31 | Osc2 Tune | DETN (osc 2) |
| 243 | WAV2 | 32 | Osc2 Waveform | POS (osc 2) |
| 251 | TBL2 | 33 | Osc2 Wave Table | TBL (osc 2) |
| 245 | LEV2 | 36 | Osc2 Level | LEV (osc 2) |
| 244 | PD2 | 35 | Osc2 Phase Dist | RATE (osc 2) |
| 250 | OFS2 | 34 | Osc2 Lin Offset | MPOS (osc 2) |
| 252 | DRIF | 38 | Osc Drift | MLEV (osc 2) |
| 253 | ATK | 40 | Noise Attack | MOVE (osc 2) |

The storage slots are the sound's parameters 25..40, which the frame already carries to the SHARC (`dnfw.waverider.frame`). So every control keeps a real home, and M9/M10 read them from the frame, as TUN1/WAV1/TBL1 are read today.

## Where the labels come from: the options weighed

The table cannot grow in place: new ids 321+ need the table relocated and its 56 base references repointed (`docs/lfo4-feasibility.md`). Its only dead records, the 10 `ERR` ones plus id 0, are what the LFO4 mod repurposes.

| | how | cost | effect on the rest |
|---|---|---|---|
| A. dead ERR records | copy 238/239/247 into ERR ids | small | **collides with LFO4**, and only 10 exist (Waverider needs about 16) |
| B. relocate the table | move it to the platform's appended area with spare records, repoint 56 references | large | clean; could be a shared platform service LFO4 uses too |
| **C. hook the SYN page's label fetch (chosen)** | keep WaveTone's records; return our label on a Waverider track | small | p-locks, LFO destinations, CC, SAVE/LOAD unchanged (the records are WaveTone's own) |

**C, as built [E]:** `getShortName` `0x400372da(this, id)` returns `record + 0x30`, and it is the only reader of `+0x30` measured in the emulator (`--label-log`). The SYN page calls it from `0x40064622`, and its `this` is not a sound. So the hook finds the track itself (`is_wr`, the active track) and is placed at the SYN page's call, not in `getShortName`. That also leaves lfowaves' DISP record at `0x400372da` alone.

**Not yet relabelled:** the header's parameter line (`Osc1 Waveform=20` while POS turns) is the record's long name, `+0x28`. A later milestone hooks that, or relabels the long names with the same test.

## M8: the wave [E]

`dnfw.waverider.wave`. `wr_icons` calls `wr_wave(this, canvas)` on Waverider's first page (page id 7), in the cell WaveTone's WAV1 overlay used to own (C, x 77..94):
- **the wave:** the frame the SHARC reader plays for the current TBL (`TBL1 >> 8`) and POS (`min(WAV1, 0x7800)`), interpolated between the two frames either side as the reader does, in 16 columns (x 78..93, y 39..51);
- **the bar:** a dotted line at y 35 and a 3-pixel marker at POS.

Coordinates are the canvas's own: y counts up from the bottom, as the page's blits do (cell row 0 spans y 34..51). Values come from the page's value getter `0x4006538e(this, id, &flag)`, the call WaveTone's icons use; pixels come from `setPixel` `0x40113b90(canvas, x, y, on)`.

**A column is a span, not a point.** The first cut sampled one point per column. The overtone table's 16th partial has 32 points a cycle, so every sample landed on a zero crossing and POS 120 drew a flat line [E]. Each column now draws the minimum to the maximum the frame covers there, joined to its neighbour, as a sample editor's overview does. The 16th partial is a solid band, which is what 16 cycles in 16 pixels look like. The data is 2 tables × 16 frames × (16 minima + 16 maxima) signed bytes = 1 KB.

**Closed paths (kept as signals):**
- *The page titles drive the icons:* disproven. Our own titles gave the same icons; the icons come from the page id.
- *The overview table `0x42432b24` drives the icons:* disproven; its entries are all 0.
- *A byte branch to skip the icons:* `bne.s` with displacement `0xa0` is **-96**, not +160. It jumped back into the dispatcher and the UI hung behind the MACHINE SEL menu (M7d, emulator). `wr_icons` now rewrites its own return address to the stock target `0x400182c6`, and the site is `jsr wr_icons ; nop`.

## Open [O]

- The header's long name (`Osc1 Waveform`) still reads WaveTone's.
- On the instrument: pages, labels, the wave following POS and TBL, and WaveTone untouched (the test plan entry).

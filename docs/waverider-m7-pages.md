# Waverider M7: its own SYN pages (design in progress)

**Goal (owner, 2026-10-01).** A Waverider track gets its own two SYN pages, laid out from the "Wavefinder on Digitone II" mockup but with our own names:

| | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| page 1, OSC 1 | TUNE | LEV | POS | TBL | RATE | MPOS | MLEV | MOVE |
| page 2, OSC 2 | DETN | LEV | POS | TBL | RATE | MPOS | MLEV | MOVE |

- **Header:** the machine name reads `Waverider`.
- **Controls not yet working show `-`.** In M7 only TUNE, POS and TBL work, as in M6.
- **Tables:** TBL picks from a pool loaded from the +Drive (`docs/waverider-tables.md`), so no part of M7 assumes two baked tables.
- **M8** adds the waveform display. **M9** adds LEV and osc 2. **M10** adds the MOVE modulator.

Grades: **[D]** read statically, **[E]** measured in an emulator, **[O]** open.

## How the SYN pages are found (DN2 1.11) [D]

- **The per-machine table** is at `0x42432ad4`: one 16-byte entry per machine type, types 0-4:
  - `+0`: the page count;
  - `+4..+0xf`: a `std::vector` of 44-byte page descriptors (begin, end, capacity).

  The entries sit 16 bytes apart, so a sixth would land on `0x42432b24`, which is the start of the next table. **The table cannot grow in place.**
- **The readers:**
  - `0x400c24d2(type)` returns the count; it answers 1 above type 4;
  - `0x400c24ee(type, page)` returns `begin + 44 * page`, or the empty page `0x42432bd4` above type 4 or past the count;
  - `0x400c248e(type)` returns a second per-machine descriptor, `0x42432b24 + 44 * type` (not yet identified).

  Their callers are at `0x40016856`, `0x400168e6`, `0x4001696a`, `0x40017422`, `0x400177e8`, `0x4003e6fa`, `0x40045cdc`, `0x40046120`, `0x4005c4ee` and `0x40064ece`.
- **The initializer** (around `0x400ca800..0x400cad60`) builds each machine's descriptors on the stack and assigns the vector (`jsr %a4@` with `pea` of the entry's `+4`). **WaveTone (type 1) has 3 pages** (`moveq #3; move.l d0,0x42432ae4` at `0x400caa4a`):

  | page | title | subtitle | entries (record ids) | tag |
  |---|---|---|---|---|
  | 1 | `DN VA 1` (`0x4021a667`) | `WaveTone` (`0x4021a66f`) | 238-245 | 10 |
  | 2 | `DN VA 2` (`0x4021a678`) | `WaveTone` | 246-252 and one empty entry | 10 |
  | 3 | `DN VA 3` (`0x4021a680`) | `WaveTone` | 253-257, 2, 3, 4 (to be re-read) | 10 |

  Page 3's list and each entry's position are to be re-read from a live descriptor. The `-16..-11` byte moves are 240..245 once combined with the upper bytes of the register already loaded.
- **Today a type-5 track gets type 1's pages,** because `getMachineType` `0x4004b7f2` reports 5 as 1 (`docs/machine-list.md`, Milestone 5, rows 7-8).

## The records WaveTone's pages name [D]

The parameter table is at `0x401f7f94`: 321 records of 60 bytes (`+0x00` page, `+0x04` slot, `+0x28` long name, `+0x30` short name, `+0x34` formatter).

| id | short | slot | long name | proposed Waverider use |
|---|---|---|---|---|
| 238 | TUN1 | 25 | Osc1 Tune | **TUNE** (osc 1) |
| 239 | WAV1 | 26 | Osc1 Waveform | **POS** (osc 1) |
| 247 | TBL1 | 27 | Osc1 Wave Table | **TBL** (osc 1) |
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

## Where the new labels come from: three options

The table cannot grow in place: new ids 321+ need the table relocated and its 56 base references repointed (`docs/lfo4-feasibility.md`). Its only dead records, the 10 `ERR` ones plus id 0, are what the LFO4 mod repurposes.

| | how | cost | effect on the rest |
|---|---|---|---|
| **A. dead ERR records** | copy 238/239/247 into ERR ids | small | **collides with LFO4**, and only 10 exist (Waverider needs about 16) |
| **B. relocate the table** | move it to the platform's appended area with spare records, repoint 56 references | large | clean; could be a shared platform service LFO4 uses too |
| **C. hook the short-name lookup** | keep WaveTone's records; return our label when the record belongs to a Waverider track | small | p-locks, LFO destinations, CC, SAVE/LOAD unchanged (the records are WaveTone's own) |

**Option C is the likely choice, pending two checks [O]:**
1. **Does the SYN page draw its labels through `getShortName`** (`0x400372da(this, id)`: returns `record + 0x30`, the id bounded to 321, `this` unused)? It has two direct callers:
   - `0x40016adc` passes the object returned by a `vtable+196` call;
   - `0x40064622` passes `%a4`.

   The page view may instead read `+0x30` directly. The lfowaves mod already hooks `0x400372da` (a DISP record).
2. **Does the hook have the track's raw machine type in reach?** Either `this` is the track's sound (then `sound+0xDE` is 5), or it can find the current track.

Both need the ColdFire emulator on the SYN page of a type-5 track (`scripts/emu_waverider_menu.py`, the `boot400M` snapshot with the build patched in). A hook shared with lfowaves at `0x400372da` needs the platform's hook chaining (mod platform Stage 3) or a different site.

## The page structure, whichever option labels it

- **Our own entry for type 5:** a count of 2, and a descriptor array in the platform's data area (static; nothing frees it):
  - page 1: `{title, "Waverider", 238, 0, 239, 247, 0, 0, 0, 0, 10}`, i.e. TUNE, LEV (`-` until M9), POS, TBL, then four `-`;
  - page 2: all entries 0, until M9.
- **The readers:** `0x400c24d2` and `0x400c24ee` (and `0x400c248e`, once identified) answer type 5 from our entry. Their callers must pass the raw type 5, the way M5 sent five callers to the raw getter.

**Still to settle [O]:**
- that an entry of 0 draws as an empty box on the DN2 (it does on the DT2's ONESHOT page);
- that a page whose eight entries are all empty is allowed;
- where the subtitle is drawn from.

## Next

Run a type-5 track to its SYN page in the ColdFire emulator. Trace which routine fetches each label and what `this` is; read the live WaveTone descriptors; check an entry-0 box. Then pick A, B or C, and write the edits.

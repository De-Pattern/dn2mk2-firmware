# The arp's hidden modes: SHUF, RAND and CHRD are names only

**Question (2026-09-26).** The Digitone II 1.11 image names eight arpeggiator
modes, `OFF TRUE UP DOWN CYCL SHUF RAND CHRD`. The instrument and its manual
(OS 1.10D, §9.7.1) offer the first five. If the step implements the last
three, unlocking them could be a bound change, the way `moddest` was
(`docs/ideas-backlog.md` §24).

**Answer: no.** The step has four distinct cases (TRUE, UP, DOWN and one shared
default). MODE 4, 5, 6, 7 and every negative value all take the default, which
is CYCL. With MODE forced to 5, 6 or 7, the stock arp plays CYCL note for note.
There is no shuffle, no random choice and no chord anywhere in the arp. So
widening the bounds would give three menu entries that all sound like CYCL.
**No `arpmodes` mod was built.**

Measured with `scripts/emu_arp_modes.py` (stock 1.11, snapshot `grid-rec`,
28 checks, 0 failures).

## 1. The names

MAIN OS holds three pointer runs of eight names, in the same order:

| table | contents | used by |
|---|---|---|
| `0x401d4b0c` | OFF TRUE UP DOWN CYCL SHUF RAND CHRD | the arp menu's value text: `ArpSetupMenuView`'s constructor copies all eight (`0x20` bytes) to view `+400` (`0x4001923e`) |
| `0x401d4b2c` | OFF TRUE UP DOWN CYCLE SHUFFLE RANDOM CHORD | copied to view `+432`, beside the short names |
| `0x401d4af8` | five other pointers, then OFF TRUE UP | the tail of a neighbouring table |

The menu draws MODE as `view[100 + MODE]`, one long each (`0x400188de`
`jsr getMode`, `addil #100`, `movel %a2@(0,%d0:l:4)`). The view carries all
eight names, so a MODE of 5..7 would draw as SHUF, RAND or CHRD without
reading past the table.

## 2. The step's dispatch, read

`0x4002a0bc (track, arp id)` returns one note, `-1` for a rest, or `-2` for a
stale id. It keeps per-track state at `0x405984a8 + 40*track`:

| offset | meaning |
|---|---|
| `+0` | step counter, wraps past LEN (sound `+355`) |
| `+4` | which of the four bitmap words the scan is in (notes 0-31, 32-63, ...) |
| `+8` | CYCL's direction, 1 up, 0 down |
| `+12` | the last note index, so CYCL does not repeat its turning note |
| `+16` | the bits of the current word still to visit |
| `+20` | TRUE's position in the press-order list |
| `+24` | the id the caller must match |
| `+28` | the octave, wraps past RNG (sound `+353`) |
| `+32` | the sound |

Before any mode: step counter + 1, and if the step's bit in the mask
(sound `+356`, u16) is clear it returns a rest. **The note position does not
advance on a muted step.** Then the dispatch at `0x4002a114`:

```
4002a114  move.b  351(a1),d0      | MODE
          moveq   #1,d5
          mvs.b   d0,d4
          cmp.l   d4,d5
          beq     0x4002a148      | 1 TRUE: the press-order list
          blt     0x4002a12c      | MODE > 1
          tst.b   d0
          beq     0x4002a39a      | 0 OFF: rest
          bra     0x4002a28a      | MODE < 0: the default
4002a12c  moveq #2,d7; cmp d4,d7; beq 0x4002a190   | 2 UP
          moveq #3,d0; cmp d4,d0; beq 0x4002a208   | 3 DOWN
4002a144  bra     0x4002a28a      | anything else: the default
```

The default at `0x4002a28a` is CYCL, the up-and-down scan driven by `+8`. It
never reads MODE again. None of the four cases calls anything, so the step has
no random source at all. The result is
`index + 12*octave + offset[step]` (sound `+358 + step`, signed).

Nothing else tells the values apart either. Every instruction that reads sound
`+351` (`@(351)` in `out/main111.dis`; nothing indexes it through a register):

| site | what it does with MODE |
|---|---|
| `0x40029cf4` note set | zero or not |
| `0x4002a114` step | the dispatch above |
| `0x4004be98` getMode | returns it: the menu text, the FUNC+ARP LEDs (`0x4005f9fa`, `0x40060dfa`) test zero |
| `0x4004bea4` setMode | clamps to 0..4 |
| `0x4004bf32` FUNC+ARP | parks MODE at `+374` and writes 0, or restores it clamped to 1..4 |
| `0x4004cf74`, `0x4004d1b6`, `0x4004d2f2`, `0x4004d472`, `0x4004d536` | arp-settings copy and paste, raw bytes |
| `0x400dd530..0x400dd54c` LOAD | stored `+331` to live `+351`, 0 when above 4 or negative |
| `0x400dd8aa` SAVE | live `+351` to stored `+331`, raw |

The MODE has no parameter-table record (`dnfw params`: only Amp, LFO1-3 and
Euclidean MODE records), so no table range bounds it.

## 3. The emulator run

The sequencer does not play under the emulator (§18), so the harness calls the
stock step directly. It lays out the held-note set the way the note set's reset
leaves it (`0x40029f3a`): bitmap `0x40598728`, press-order list `0x40598828`
(head `0x4059c868`, tail `0x4059c828`), state as above. Held, in press order,
E4 C4 G4 B4. RNG 1 (two octaves), LEN 16, all steps on, no offsets.

```
0 OFF    rest rest rest ...
1 TRUE   E4 C4 G4 B4 E5 C5 G5 B5 E4 C4 G4 B4 ...
2 UP     C4 E4 G4 B4 C5 E5 G5 B5 C4 E4 G4 B4 ...
3 DOWN   B4 G4 E4 C4 B5 G5 E5 C5 B4 G4 E4 C4 ...
4 CYCL   C4 E4 G4 B4 G4 E4 C4 E5 G5 B5 G5 E5 C5 E4 G4 B4 G4 E4 C4 E5 ...
5 SHUF   (identical to CYCL)
6 RAND   (identical to CYCL)
7 CHRD   (identical to CYCL)
```

- UP (2) and CYCL (4) are the controls: each plays what the manual describes.
- 5, 6, 7 and -1 match CYCL for all 24 steps.
- SHUF and RAND, rerun from a fresh state, repeat themselves exactly.
- CYCL moves up an octave once per up-and-down pass, and skips a note that
  would repeat the one before (C4 then E5, not C4 C5).
- With offsets `+0 +7 -5 +12`, steps 3 and 7 muted, LEN 8 and RNG 0, CHRD and
  CYCL are again identical: `C4 B4 rest G5 B4 D5 rest E5`. The rest does not
  use up G4: step 4 plays it, with that step's offset.

## 4. The bounds, and what stock does with 5..7

All measured on stock code in the same run:

| path | 5, 6, 7 become | site |
|---|---|---|
| arp menu edit, `setMode(model, v)` | 4 (CYCL); -1 becomes 0 | `0x4004befa moveq #4` / `0x4004bf00 moveq #4` |
| FUNC+ARP restoring a parked 6 | 4; a parked 0 becomes 1 | `0x4004bfb4 moveq #4` / `0x4004bfc6 moveq #4` |
| SAVE | saved raw, 5 stays 5 | `0x400dd8aa` |
| LOAD | **0, arp OFF** | `0x400dd530 moveq #4` |
| `arpplocks` MODE lock | 0..4 | `scripts/build_arp_plocks.py` `PARAMS` |

So a sound carrying MODE 5..7, saved by a modified firmware, loads on stock
with its arp **OFF**. It does not crash. The menu text, the LEDs, the MIDI arp
(`midiarp` tests MODE against zero only) and the clipboard all tolerate 5..7.

## 5. Decision

**No, they cannot be activated.** The bounds are five `moveq #4`s and would be
easy to widen. But nothing implements the modes behind them, and each of the
three would play CYCL. `docs/ideas-backlog.md` §24 therefore stands as a
proposal for new code, not an unlock.

## 6. What it would take instead

1. **Bounds (the easy part).** The five `moveq #4` above become `moveq #7`, and
   `arpplocks`' MODE range becomes 0..7. The names and the menu text already
   exist. A stock firmware will still load such a sound with its arp OFF.
2. **SHUF and RAND.** A cave behind the default branch (`0x4002a144 bra` and
   `0x4002a128 bra`), which sends 5 and 6 to new code and everything else on to
   `0x4002a28a`:
   - RAND: count the held bits, draw one, and optionally a random octave within
     RNG.
   - SHUF: a permutation of the held notes, redrawn at the end of each cycle.
     It needs per-track state beyond the 40-byte record, which is fully used,
     for example 16 × 32 B in a BSS cave.
   - **The random source.** The firmware has an ANSI `rand()` at `0x40150670`
     (LCG `*1103515245 + 12345`, state `0x405cd95c`, 15-bit result). It has
     six callers, and its `srand` (`0x401506ba`) has no direct caller, so its
     seed is fixed at boot. It is also called outside the ISR, non-atomically.
     A private xorshift in the cave, seeded per track, is cleaner. It is also
     repeatable, which the §24 "seeded random" candidate wants.
3. **CHRD (the large part).** The step returns one note, and its two callers
   (`0x400266e0`, `0x4002686e`) write that note into the one voice record the
   trig handler is building (`+38`). Playing all held notes together on each
   step means creating one voice record per held note in the frame ISR's trig
   handler, subject to voice allocation. That is new ISR code on the voice
   path, not a dispatch case. It is the costliest of the three.

## What CHRD means, in plain words

**In 1.11, CHRD is a word in the firmware with no behaviour behind it.** The
menu cannot select it. If MODE is forced to 7, the arp does exactly what CYCL
does:

- one note per step, at the SPD rate, never two at once;
- up through the held notes from the lowest, then back down, without
  repeating the top or bottom note;
- one octave higher after each full up-and-down pass, until RNG is reached,
  then back to the first octave;
- **LEN** sets how many steps the arp pattern has before it starts over;
- a **muted step** (the step mask) is silent, and the arp does not move on:
  the next step plays the note the muted one would have;
- each step's **note offset** is added to whatever note lands on it;
- **N.LEN** is how long each note sounds, and is the same in every mode.

A real "chord" mode, all held notes struck together on each arp step, is not
in the firmware and would have to be written (§6.3).

## Unverified

- The hidden names suggest Elektron wrote or planned these modes, perhaps on
  another product. That was not checked in the Digitone 1 or Digitakt images.
- Only the 1.11 MAIN OS was read.
- The harness calls the step directly. The frame ISR's own clock, driven by
  type-9 records, was not run, because the sequencer does not play under the
  emulator. The ISR's reads of MODE are listed in §2 and do not tell 4..7 apart.
- The encoder descriptor passed to `0x4011336e` for MODE (`0x44507dec`) was
  not read. setMode clamps after it in every case measured.

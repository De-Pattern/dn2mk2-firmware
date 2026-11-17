# v0.58: microtonal scales in KB SETUP (owner, 2026-11-16)

> "how hard would it be to add these two microtonal scales to the list of scales in the KB setup
> menu under SCALE"

## What it does

KB SETUP's SCALE (knob G) goes on past stock's last scale (Locr. bb3 bb7) to two more:

| # | full name | short | keys and chords | tuning (cents against 12-TET, by semitone above ROOT) |
|---|---|---|---|---|
| 35 | Poole Rod12 | PR12 | as Chromatic (all 12); a chord MODE builds Ionian's chords | 0, -46.7, +3.9, -33.1, +17.5, -2.0, -48.7, +2.0, -35.1, +5.9, -31.2, -50.6 |
| 36 | Poole12 Min | PM12 | as Aeolian (1 2 b3 4 5 b6 b7) | 1 0, 2 +3.9, b3 -33.1, 4 -2.0, 5 +2.0, b6 -35.1, b7 -31.2 |

(The owner's `poole-rod12tone.scl` and `poole12minor.scl`.) Every track whose SCALE is one of
them plays its notes in that tuning, from the keyboard or the sequencer, with ROOT as the scale's
1. A note off POOLE12 MIN's degrees (a sequenced one) plays at 12-TET. Every other scale, track
and voice is stock's.

## How

**Stock's scales.** OS 1.11 keeps 35 scales (0 Ionian .. 34 Locrian bb3 bb7; -1 Chromatic) in five
tables, each read through one accessor:

| table | stock | row | accessor |
|---|---|---|---|
| full names | 0x402a0e28 | index + 1 | 0x401500a6 |
| short names | 0x402a0eb8 | index + 1 | 0x40150096 |
| keys (key -> semitone) | 0x4020e320, 16 words | index + 1 | 0x401500c6 |
| chord degrees, -1 ends | 0x4020dea0, 8 words | index | 0x401500dc |
| membership (semitone 0..12) | 0x4020ec20, 13 bytes | index | 0x4014fe60 |

The value is a signed byte in the keyboard's settings (+29) or a track's (+1170), read and
written only through two getters and two setters, each clamping to -1..34 (0x4003aa0a/aa44,
0x40050744/0778e).

**The build** (`dnfw.waverider.scales`) copies the five tables from stock, row for row, into the C
chunk with two rows more, points the five accessors' operands at the copies and raises the four
clamps to 36. Stock then lists, names, draws, lays out and plays them as it does its own.

**The tuning** (`csrc/sampler/tune.c`):
- `tn_poll` (the UI loop, from `smp_ui_pop`): each track's SCALE and ROOT through stock's own
  getters, the way KB SETUP's dispatchers read them (0x4003bdb2, 0x4003bce2): the track's own
  value when that setting is per track, the keyboard's when not. It checks an object's vtable
  before calling through it.
- `tn_retune` (the audio interrupt, `ms_frame`, after the frame is built): a voice on such a track
  gets its note's cents added to its frame NOTE word (`note << 8 | fine`, fine in 1/256 semitone).

**A project saved with 35 or 36** and opened on stock OS reads Locr. bb3 bb7 (stock's getter clamps).

## Gate

`tune` (ColdFire): stock's setter and getter at 35, 36, 40 (36), -1, 34; the names (ours, and 34
stock's); the keys, chord degrees and masks against Chromatic, Ionian and Aeolian; `tn_retune` at
ROOT D on 16 voices (one of no track): ROD12 each pitch class's cents, MIN12 its degrees' only, a
stock scale (34) nothing (the negative control); KB SETUP drawn at 34, 35 and 36.

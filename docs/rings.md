# RESONATOR: a Rings-style resonator machine (planned)

Owner, 2026-10-14 / 10-18: a Rings-style resonator machine, polyphonic, *"3-4 notes max
would be fine, even less"*; no samples. Built the PING way: a reference model and
audition WAVs first (`rings/model.py`, `rings/demos.py` -> `rings/demos/*.wav`), chosen
by ear, then the DSP contract, the SHARC code and the machine's pages.

Mutable Instruments' STM32 module code (Rings among it) is MIT-licensed, and its
design is the reference; this model is our own code from the textbook forms (a
two-pole resonator per mode; Karplus-Strong with a loss filter), and the machine does
not use the Mutable Instruments name (their trademark).

## The machine

Machine type 6, the slot W5 reserved beside Waverider (`SAMPLE_GROUP`), offered by
MACHINE SEL after WAVERIDER. Each note is a voice: an internal exciter hits the
resonator.

    page 1   TUNE  LEV   MODEL EXCT  /  STRC  BRIT  DAMP  POS

| control | what it does |
|---|---|
| MODEL | MODAL (a bank of up to 24 modes) / STRING (a delay-line string) |
| EXCT | the exciter: MALLET (soft, its width from BRIT) / NOISE (a short burst) |
| STRC | structure: 0 harmonic (a string), middle a free bar (marimba), top a plate / bell |
| BRIT | brightness: the exciter's tone, and how much faster the high modes decay |
| DAMP | the decay, 0.05 s .. 10 s |
| POS | where it is hit: the middle cancels every other mode, the edge keeps them all |

## Audition WAVs

1. `01_marimba_bar` -- a bar (STRC middle), mallet, a melody.
2. `02_bells_chords` -- STRC near the top, long DAMP, 3- and 4-note chords.
3. `03_string_pluck` -- MODEL STRING, a plucked line (in tune to 0.3 cents).
4. `04_glass_noise` -- the NOISE exciter, bright, high notes.
5. `05_structure_harmonic_to_bell` -- one note, STRC from 0 to the top in 8 hits.
6. `06_damping_short_to_long` -- DAMP from short to long in 7 hits.
7. `07_four_voice_chords` -- 4 voices, harmonic-leaning.
8. `08_plate_drums` -- low plates, short DAMP: tom / drum-like.

## What it needs (to measure before building)

- **CPU.** 24 modes a voice is 24 two-pole resonators, about 5 operations each a
  sample: ~120 a sample a voice, ~23 M a second for 4 voices at 48 kHz. The SHARC's
  idle time with the stock engine busy (`idle_load.asm`, `docs/sharc-load.md`) says
  whether that fits; if not, fewer modes (16) or a voice cap. The STRING model is far
  cheaper (a delay line and two one-poles).
- **Memory.** Code ~2-3 KB, mode tables ~1 KB, state 16 voices x (24 modes x 2 + a
  string's delay line, up to 1,024 samples at 47 Hz) -- the delay lines are zeros
  (fill blocks) in L1 or DDR. The DSP budget has 12 KB left after SHFT; reclaiming the
  wavetables (`docs/shft.md`, "Memory") is the reserve if it runs short.
- **ColdFire.** A second new machine type: Waverider's shims compare with type 5 only,
  so they generalise to 5 and 6 (MACHINE SEL list, names, attributes, slot_to_id as a
  WaveTone clone, the pages, getMachineType, LOAD keeping 6).

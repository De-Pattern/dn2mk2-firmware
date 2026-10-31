# User reports (YouTube thread, GitHub issues)

Source: comments on "DIGITONE 2 mk2 FIRMWARE MOD: MD|DT2|MNM" (De-Patterning), read
2026-10-28. Reporters were on v0.26 or MNM-1 unless noted.

## Bugs

| # | report (who) | status |
|---|---|---|
| U1 | MD machines: sometimes no sound on any pattern until a power cycle (zugada_); v0.26 "very unstable, no sound for more than a few minutes" (mistahairplane) | the frame overrun: v0.27's guard. Confirm on v0.27 |
| U2 | Sample (DT2) machines: choosing a sample while the pattern plays freezes the unit; a power cycle clears it. "Most of the crashes are on the Digitakt machines" (zugada_) | **open**: not reproduced yet. v0.27 changed when the list opens; check the load path while playing |
| U3 | A trig can't be pre-muted (trig mute), especially on the custom machines (zugada_) | **researched (docs/mute-research.md)**: stock mute only drops a muted track's new trigs on the ColdFire, so our voices get no note either; a sounding note ends by note-off through the stock AMP. Not reproduced: need the machine, LEN, and the exact keys |
| U4 | SYN + YES (randomize) on a Machinedrum machine crashes sometimes (zugada_) | **likely the DSP overrun (fixed v0.27's guard)**: every MD machine with random settings, all 8 controls and 7 effects, twice each, runs bit-exact, finite, no halt in the DSP model; SYN + YES on PERC in the emulator randomizes (TYPE too) and draws without fault. Retest on v0.27+ |
| U5 | After switching a track from an MD machine to a stock DN2 machine, the MD machine is still heard in the background (zugada_) | **open**: the model silences a track that leaves PERC; check the hardware path |
| U6 | Delete all samples / folders sent by the import tool (zugada_) | v0.29 multi-select delete |

## The owner's reports (v0.27, 2026-10-28)

| # | report | status |
|---|---|---|
| O1 | Monomachine tracks with dynamic voice allocation: most notes don't sound (about 2 of 16 voices); LOCK 1 voice works every time (DDRW, DENS, SID, all of them) | **open, first**: our voices read their sound by voice number as if it were the track |
| O2 | With a Monomachine track in the project, a Digitakt track with dynamic allocation plays a buzzy two-note Monomachine sound whenever it lands on voice 15; gone when the MnM machine is removed, or with REUSE on | **open, first**: the same cause as O1 |
| O3 | Monomachine voices quieter again in v0.27 (v0.28 sets each machine's level: check) | check on v0.28 |
| O4 | The CPU guard: two all-p-locked PERC tracks, a 64-step DENS, a one-shot track with p-locks, then a Slice track with 48 slices and heavy FX: no dropout | **works** (v0.27) |
| O5 | Froze on the sample pool's list after clearing a Slice track and loading a new sample; reboot | **open** (as U2) |
| O6 | The playing-slice marker on Slice/Grid lags behind the sound | v0.30: the page drew voice t's position for track t; with voice allocation the track plays on other voices. Now the track's own voices (the ColdFire's slot -> track table). Check |
| O7 | GRID: the last slice plays on the next trig when switching slices (v0.27) | v0.28's re-latch: check |
| O8 | Slice creation window: the playhead drifts and doesn't follow the preview; encoder D is the preview's loop mode: draw the forward / reverse / off icons as the DT2 pages do, not "LOOP" | v0.30 |
| O9 | A CLEAR SLICE GRID item in the slice menu | v0.29 |
| O10 | P-lock indicators on the Monomachine pages (as on the other machines) | in since v0.28 (locked controls drawn inverted): check |
| O11 | Keep the selected sample when switching between Digitakt machines | v0.30 (MACHINE SEL between two sample machines keeps SAMP; gate 6k) |
| O12 | The sample pool is slow to load at power-on: +Drive storage soon, researched first (menus, navigation, structure, behaviour) | planned |

## For v0.30 (owner, 2026-10-28)

- Sample browser (folders, INCOMING, RECORDED, the sample list): UP/DOWN held scroll on by
  themselves, as FILE NAME's arrows do since v0.27 (rec.c's rpt_start / rpt_poll: 0.4 s, then
  12 a second). Today a held arrow moves one item.

## misterairplane (Discord, v0.28, 2026-10-28)

- The recorder started recording with THRES at 0 and nothing playing, on touching a knob:
  THRES 0 now waits for sound (-60 dB floor) (v0.30)
- ARM's knob "acceleration is wonky": each detent toggled arm/stop; now right arms, left
  stops, one action a turn (v0.30)

## ema:blskk (Discord, v0.28, PERC, 2026-10-28)

- On a PERC or sample track, YES on the OS's "do you want to update? Y/N" (firmware sent over
  USB) opens our "no samples loaded" pop-up instead: the update can't be accepted. Workaround:
  NO, select a stock track, send again. Same kind as the save question on a SLICE page
  (fixed in v0.29 for FUNC + key questions only): our pages must hand YES/NO to any stock
  question or pop-up that is up: done in v0.30 (a stock question's keys are stock's, found by
  the screen's view list; gate 6j)
- TRIG + YES (the stock sound preview) opens our lock menu on PERC instead: v0.30, a YES with
  another key held is stock's (gate 6j)

## Discord, v0.29 / v0.30 (2026-10-28 evening)

- **AMD (amp mod depth) on a PERC (Machinedrum) track silences everything until a reboot**
  (depaffect, P-I BD, v0.29 and v0.30). **Found**: AMD reads a sine table that lived with
  SHFT; v0.28 removed SHFT and the table with it, so AMD read uninitialised DSP memory.
  Fixed (the table loaded again for AMD) with a unit test that every table PERC reads is
  loaded: v0.30.1 / v0.31.
- "Some machines' controls do not work", "sound cutting out" (kazeko, v0.29); "easy to get
  the sound to cut out with a few Machinedrum engines" (depaffect): DSP time (v0.30 shows
  CPU when it happens), or the AMD fault above. Ask which controls.
  **depaffect's follow-up (v0.30, also v0.27), 2026-10-29:** eight PERC tracks soon mute all
  audio, *but not when each track's voice allocation is locked to 1 voice*; with the lock,
  CPU shows and the sound keeps playing. So the cut-out comes with dynamic voice allocation:
  each new note lands on another voice while the old ones still render, so eight tracks hold
  many more PERC voices than eight. The guard (v0.27) leaves voices out but the whole DSP
  still stops. **v0.31**: a Machinedrum voice now rests once its sound has died away after
  the AMP (64 blocks under -96 dB, as the Monomachine's since v0.29), so finished voices cost
  nothing and the newest-first order (v0.29) has the time for new notes (runner: bit-exact,
  rests, wakes on its next note). To confirm on the instrument: eight PERC tracks, dynamic
  allocation.

- **FUNC + turn does nothing on our machines' controls** (Discord tester, v0.30, 2026-10-29).
  On stock pages FUNC while turning makes a value jump to set positions (DT2 manual §6.2.1:
  NOTE by octaves, delay time by tempo steps). On ours the value stays put: DDRW (BR1 SU,
  WID, WAV2, TIME, TUNE), DENS (PCH4, WAVE, TUNE), VO-6 (CONS, CLEN, TUNE, V-SW, voice type),
  SID (PWRS, WAVE, MOD, MSRC, TUNE), PERC (RAMP, RDEC, START, NOISE, CLIP, AMF, EQF, EQG, FLTW,
  FILTER Q), ONESHOT (LENGTH, PLAY MODE), WERP (SEG, BARS), STRETCH/REPITCH's matching
  controls. **Open**: find what the stock knob handler does with FUNC held (a jump table per
  parameter, from the parameter's descriptor) and give ours a plain turn, or jumps where they
  mean something (TUNE by semitone/octave, choices by one).

- **MACHINE SEL to a sample machine keeps the track's filter, amp and FX** (blskk, v0.32):
  "instead of starting fresh". **Not a bug**: the owner checked, stock keeps those pages
  switching between its own machines (FM TONE to WAVETONE); ours matches it.
- **After installing a new version, MD and Monomachine tracks silent until the track is
  cleared** (owner, v0.31/v0.32; often, not always): clearing the track (no reboot needed)
  brings them back, and they stay fine. With dynamic allocation on SID, "shared voices" for a
  minute; back to one voice and a clear fixed it. **Open**: likely what the project kept from
  the earlier version (a sound saved with an older version's controls), or a voice slot's state
  carried from another track's voice. To find: does it happen with a project saved on the same
  version (power-cycle without installing)? Does a fresh project after an install play at once?
- **SLICE/GRID at NOTE: more slices shift the layout** (blskk, v0.32): a C5 trig played slice
  1 of 4 but slice 5 of 8. Ours counted from C0 ((note - 12) mod n); the DT2 counts from C1
  ("slices play from C1 and upwards, wrapping"): (72 - 24) mod 8 = 0. **v0.33**: from C1, the
  DSP and KEYBOARD's slice keys alike.
- **Perform mode, CONTROL ALL, RTRG with LEN at 1/80** (zuzsw, v0.32): four PERC tracks each
  locked to one voice, the meter at 76 %; patterns 1-3 sound right, pattern 4 "garbled".
  **Open**: waiting for details (what pattern 4 should sound like; whether stock machines do
  the same at that retrig rate).

- **SID silent at first** (owner, v0.32): MACHINE SEL gave the Monomachine machines the shared
  records' defaults (SID's WAVE on MIX). **v0.33**: each starts as its own (dnfw.mnm DEFAULTS),
  SID on TRI (its first wave; PW at the middle for PULS); gate 6o.
- **DDRW's BR1 / BR2 (bitcrush) not heard** (owner, v0.32). **Open**: check the port against
  the Monomachine's (the runner's DDRW model at BR 0 vs 127).
- **Owner's checks at the next install** (asked to be reminded): (1) a fresh project plays at
  once, and an old project after a power-cycle alone (the silent-until-cleared report); (2) SID
  starts audible; (3) DDRW BR1/BR2.

## Requests

- Stereo sampling from the inputs (bearsshuffle)
- Samples streamed from the +Drive, using its free ~19 GB (paQ75, DrLaemmerbein)
- Polyphonic samples per track (paQ75): not planned for now
- A build with only the Machinedrum and Monomachine machines (douleursolitude)
- "Ensemble machines need work" (ModernDevotion): which machine is unclear; asked for plain-English detail
- A Discord (taktonmusic)

## Pablo Se7en and the owner (Discord, v0.32, 2026-10-30)

- **LFO DEPTH and SPEED don't snap with FUNC on our tracks** (the owner and Pablo): stock
  snaps DEPTH to -128 / 0 / 127.98 and SPEED to 0, +-8, 12, 16, 24, 32, 48, 63.99 (-64).
  v0.32's FUNC + turn held every control it did not know on our machines, the LFO pages'
  too. **v0.33**: only our machines' own records (238..260) change; gate 6m checks LFO
  controls on PERC, Monomachine and ONESHOT.
- **Freeze on the sample list** (Pablo, video: ONESHOT, the SAMP list up, keys do nothing,
  no audio). The third report of it (U2, O5). **v0.33**: the paths found closed
  (`docs/freeze-hunt.md`: stray DSP reads from a bad sample entry, keys whose release went
  elsewhere, the list left open on another track); not reproduced exactly, open until a tester
  confirms.
- **Slowdowns with a large +Drive library** (Pablo). **v0.33**: the +DRIVE browser no longer
  walks the whole library for every row it draws.
- **A track stuck on its machine** (Pablo, PERC): it would not change until the track was
  cleared. **Asked**: MACHINE SEL, or PERC's TYPE knob? TYPE is p-lockable, and trigs with a
  TYPE lock keep their machine whatever the knob says (clearing the track removes the locks).
  v0.33's lost-release fixes cover the MACHINE SEL case if it was that.
- **The owner's crackle** (v0.32, one Monomachine track): not the Digitone (headphones
  clean); something in the studio chain. The runner now checks that every Monomachine machine
  leaves the stock tracks bit-identical.

## misterairplane (Discord, v0.33, 2026-10-31)

| # | report | first look | status |
|---|---|---|---|
| M1 | VO-6: no audio at some CONS settings, around J-RR; not every time. At some CLEN settings the notes go too | new in v0.33: the output guard zeroes a voice that goes non-finite (it used to poison the effects instead). A consonant at J-RR or a CLEN value may drive VO-6's state to inf/NaN, and the guard now silences that voice | **open**: runner sweep of VO-6 over every CONS and CLEN, looking for non-finite output; then fix the cause in the machine, not the guard |
| M2 | Can't have more than two voices of any Monomachine engine | sounds like O1 (only a few voices sounding under dynamic allocation), which v0.29 fixed; may have come back | **not reproduced** (owner, v0.32, a new project: five MnM tracks, many voices on every engine). Ask: two tracks, or two notes on one track? LOCK or dynamic? an old project? |
| M3 | FUNC + YES preview in +DRIVE retriggers rapidly instead of playing through | likely v0.33's own: a key whose press was taken earlier is now handled as a new press, so the held YES's repeats each restart `fb_preview` | **open, v0.34**: a held YES on the same sample keeps playing; only a new press restarts |
| M4 | Do samples record in stereo? Is there USB recording? | the pool and every sample machine are mono by design (the import tool mixes to mono too); stereo means twice the memory and new voice code. USB audio as a recorder source: check whether the stock OS routes it to the DSP | answered; requests |
| M5 | One sample in PROJECT RAM won't play, but previews fine in the browser | v0.33's entry check plays an untrusted slot as empty; a valid sample it wrongly rejects would do exactly this. The check's rules match the link's (base past DATA_OFFSET, end inside 400 MB, format 0/1) | **open, first**: ask which slot, how it got there (Replace all, LOAD TO PROJ, a recording), its length; read that slot's entry over the link |

, `docs/feedback/2026-10-30-discord.csv`)

Twenty bugs and twenty-eight requests, sorted by the owner's export. Mapped to what we have:
B01 all-audio-cut (14 reports: v0.33's output guard and entry check), B06/B19 the sample-list
freeze (v0.33's paths), B08 FUNC + turn on LFO (v0.33), B16-B18 (v0.33). **Open, first after v0.33**: B10 PERC: switching LFO pages between two PERC tracks shows the
other track's parameter menu (the owner: important). B13 the recorder's normalising too loud
(a design question). The rest are old and, per the owner, fixed since: B03 (v0.29), B11/B12
(v0.30), B14 (VO-6, v0.29's voice fixes); B15 (PERC notes late, v0.27) only if it comes back. Requests to weigh: pattern direct jump, Markov
song mode, LFO matrix, trigless trigs, parameter slides (planned), screen streaming, MD/MnM
preset import, per-track flanger/phaser.

# User reports (YouTube thread, GitHub issues)

Source: comments on "DIGITONE 2 mk2 FIRMWARE MOD: MD|DT2|MNM" (De-Patterning), read
2026-10-28. Reporters were on v0.26 or MNM-1 unless noted.

## Bugs

| # | report (who) | status |
|---|---|---|
| U1 | MD machines: sometimes no sound on any pattern until a power cycle (zugada_); v0.26 "very unstable, no sound for more than a few minutes" (mistahairplane) | the frame overrun: v0.27's guard. Confirm on v0.27 |
| U2 | Sample (DT2) machines: choosing a sample while the pattern plays freezes the unit; a power cycle clears it. "Most of the crashes are on the Digitakt machines" (zugada_) | **open**: not reproduced yet. v0.27 changed when the list opens; check the load path while playing |
| U3 | A trig can't be pre-muted (trig mute), especially on the custom machines (zugada_) | **open**: our PERC/sample voices may not honour the trig-mute flag |
| U4 | SYN + YES (randomize) on a Machinedrum machine crashes sometimes (zugada_) | **open**: randomized values out of our ranges (TYPE?) |
| U5 | After switching a track from an MD machine to a stock DN2 machine, the MD machine is still heard in the background (zugada_) | **open**: the model silences a track that leaves PERC; check the hardware path |
| U6 | Delete all samples / folders sent by the import tool (zugada_) | multi-select delete, planned |

## The owner's reports (v0.27, 2026-10-28)

| # | report | status |
|---|---|---|
| O1 | Monomachine tracks with dynamic voice allocation: most notes don't sound (about 2 of 16 voices); LOCK 1 voice works every time (DDRW, DENS, SID, all of them) | **open, first**: our voices read their sound by voice number as if it were the track |
| O2 | With a Monomachine track in the project, a Digitakt track with dynamic allocation plays a buzzy two-note Monomachine sound whenever it lands on voice 15; gone when the MnM machine is removed, or with REUSE on | **open, first**: the same cause as O1 |
| O3 | Monomachine voices quieter again in v0.27 (v0.28 sets each machine's level: check) | check on v0.28 |
| O4 | The CPU guard: two all-p-locked PERC tracks, a 64-step DENS, a one-shot track with p-locks, then a Slice track with 48 slices and heavy FX: no dropout | **works** (v0.27) |
| O5 | Froze on the sample pool's list after clearing a Slice track and loading a new sample; reboot | **open** (as U2) |
| O6 | The playing-slice marker on Slice/Grid lags behind the sound | open |
| O7 | GRID: the last slice plays on the next trig when switching slices (v0.27) | v0.28's re-latch: check |
| O8 | Slice creation window: the playhead drifts and doesn't follow the preview; encoder D is the preview's loop mode: draw the forward / reverse / off icons as the DT2 pages do, not "LOOP" | open |
| O9 | A CLEAR SLICE GRID item in the slice menu | open |
| O10 | P-lock indicators on the Monomachine pages (as on the other machines) | open |
| O11 | Keep the selected sample when switching between Digitakt machines | later (quality of life) |
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

## Requests

- Stereo sampling from the inputs (bearsshuffle)
- Samples streamed from the +Drive, using its free ~19 GB (paQ75, DrLaemmerbein)
- Polyphonic samples per track (paQ75): not planned for now
- A build with only the Machinedrum and Monomachine machines (douleursolitude)
- "Ensemble machines need work" (ModernDevotion): which machine is unclear; asked for plain-English detail
- A Discord (taktonmusic)

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
- Polyphonic samples per track (paQ75): already there (sample tracks follow the DN2 voice allocation; the owner heard chords on v0.35); checked on the DSP for v0.37, in the gate's chord check from v0.38
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

## Pablo Se7en (Discord, v0.33, 2026-10-31)

| # | report | status |
|---|---|---|
| P1 | LOAD TO PROJ from the +Drive: some samples don't update in that slot and have to be loaded again | **v0.35**: the queue skipped a sample "already in the pool" when a slot held one of the same length whose name matched for seven letters (a pack's "808 KICK A" / "808 KICK B"): now the whole name, rate and format too (link.c smp_lib_slot_of) |

## The owner (v0.33, 2026-10-31)

| # | report | status |
|---|---|---|
| O14 | Holding SYN on a stock machine shows every on-screen parameter's value on the SYN pages; on the mod's machines it does not | **v0.35**: stock's key task sends a bit-3 item once a key is held; ours take it as SYN held and every page of ours (PERC, the Monomachine's, the sample machines' two pages) draws its values in the labels' place until SYN is let go (gate 6r) |

## blskk (Discord, 2026-10-31; the owner: not at face value, asked for specifics)

- "the sample import program doesn't take a folder of files that well", "skipping wav files": the page reads a folder progressively now with a count and a skip summary (2026-10-31); a folder with nested .WAV files loads in the harness. Open until he says which files.
- "arpeggiator, note edit and sampler make the digitone crash": no steps; the owner's arpeggiator works on every track. **v0.38: a crash path found** (below, "blskk, v0.37").

## The scraper's list (DELTA-01..15, `docs/feedback/2026-10-31-discord.csv`, 2026-11-01)

| # | report | status |
|---|---|---|
| DELTA-12 | flupperich6l (v0.33): choose one of the new machines, RIGHT to the filter machines: the FLTR column empty | **v0.35, found in the emulator**: MACHINE SEL's LEFT / RIGHT (0x4005ba9c) keeps the list's top row; stock's lists never scroll, ours (17 rows) does, so from a machine low in the list the FLTR column started past its own end. `colsw` (waverider/coldfire.py) puts the cursor on the column's current machine and follows. Gate 6r drives it and checks the drawn column |
| DELTA-11 | Kokozi (v0.33): folders deleted on the instrument stay in the Sample Manager list, unselectable | a folder emptied by ticking it (FUNC + YES) and DELETE kept its name (only DELETE on the folder itself dropped it); the page offered no way to remove an empty folder. **v0.35**: both; the page's Delete selected takes empty folders (DROP, link 6) |
| DELTA-05 / M5 | a recording in slot 2 previews but will not play | **v0.35**: `python tools/dn2diag.py entries` reads every slot's entry (ENTRY, 27) and says what the DSP's entry check makes of it; send its output |
| DELTA-02 / M2 | two Monomachine voices system-wide | not reproduced (owner). To ask: USB CONFIG (Overbridge streams sixteen track buffers every block: DSP time the voices then lack), the DSP load with FUNC held on the page, which build |
| DELTA-01 / M1 | VO-6 silent at some CONS (J-RR) and CLEN | the model swept over every consonant x every eighth CLEN, a note and a retrigger mid-consonant, 160 blocks each (378 runs, `out/vo6/sweep.py`): every output finite and under 64, nothing blows in the arithmetic. What stays silent on v0.33 is any voice the guard once wiped (O13's wipe wrote its counter, not zeros: v0.34), so one non-finite block made VO-6 dead for good; and VO-6's pulse ring is the slot's delay area in DDR, the memory O13 suspects. On v0.34 a wiped voice comes back on its next note; FUNC held right after shows `V<n>D` / `V<n>X`, and `dn2diag.py` says where the NaN was. Ask for those |
| DELTA-07 | arpeggiator / NOTE EDIT / sampler crash | v0.38: a heap corruption found and fixed (below, "blskk, v0.37") |

## misterairplane (Discord, v0.33, 2026-10-31)

| # | report | first look | status |
|---|---|---|---|
| M1 | VO-6: no audio at some CONS settings, around J-RR; not every time. At some CLEN settings the notes go too | new in v0.33: the output guard zeroes a voice that goes non-finite (it used to poison the effects instead). A consonant at J-RR or a CLEN value may drive VO-6's state to inf/NaN, and the guard now silences that voice | **open**: runner sweep of VO-6 over every CONS and CLEN, looking for non-finite output; then fix the cause in the machine, not the guard |
| M2 | Can't have more than two voices of any Monomachine engine | sounds like O1 (only a few voices sounding under dynamic allocation), which v0.29 fixed; may have come back | **not reproduced** (owner, v0.32, a new project: five MnM tracks, many voices on every engine). misterairplane (2026-10-31): two voices system-wide, two tracks or two notes on one track alike, LOCK or dynamic alike. Next: which machines, which OS version he is on (v0.29 fixed exactly this), a fresh project |
| M3 | FUNC + YES preview in +DRIVE retriggers rapidly instead of playing through | stock's key task sends repeat items (bit 3 with bit 0) while a key stays down; stock's handlers take them only where a hold means something (its lists' arrows), ours read every bit-0 item as a press | **v0.35**: a repeat of a key our overlays took does nothing (rec.c smp_ui_pop); a held YES also no longer ticks and unticks, a held arrow no longer steps twice |
| M4 | Do samples record in stereo? Is there USB recording? | the pool and every sample machine are mono by design (the import tool mixes to mono too); stereo means twice the memory and new voice code. USB audio as a recorder source: check whether the stock OS routes it to the DSP | answered; requests |
| M5 | One sample in PROJECT RAM won't play, but previews fine in the browser | v0.33's entry check plays an untrusted slot as empty; a valid sample it wrongly rejects would do exactly this. The check's rules match the link's (base past DATA_OFFSET, end inside 400 MB, format 0/1) | misterairplane (2026-10-31): sample slot 2, recorded directly on the machine; slot 1, recorded on a previous build, plays. **Next**: a recording's entry (the recorder's hole, format 1) through v0.33's entry check: read slot 2's entry over the link (DIR) and run entry_check on it; SysEx DIAG/SCAN (v0.34) on his unit |
| O13 | (owner, v0.33) PERC P-I BD: the same voices always silent (voice 1 almost always, then 4 or 3); VOICE SETUP lock 1: silent every note; waiting changes nothing; CPU 52-70 %. P-I RS: voices 1, 4, 9, 10, 12, more than half the time | **found, v0.33's own**: the output guard's wipe (`perc/program.py` `out_guard` `blown()`) stores R0, which `dsl.loop` uses as its counter: it writes 32, 31 .. 1 instead of zeros, so a voice that once went non-finite never resets (`on` stays 32; the MD words and the P-I delay lines in DDR keep the NaN) and stays silent until a power-on. Not reproduced: why voices 1 and 4 go non-finite at all (P-I's own arithmetic is clamped; suspects: the delay lines at 0x82200000, outside the proven DDR range, written by something on the unit; or circular-buffer L registers at PERC's entry). **v0.34 (docs/timing-model.md)**: the wipe fixed (the voice resets, the next note sounds), the model's NaN made the core's, runner step 3w and a unit test; the guard records which voice and whether its delay lines held the NaN (FUNC held: `V1D` / `V1X` in the tempo's place; SysEx DIAG), and SCAN (SysEx 25) counts non-finite words in any DSP memory range, so the owner's unit can say whether voice 1's lines are poisoned at power-on, while idle, or only after a note. Still open: what poisons them |

, `docs/feedback/2026-10-30-discord.csv`)

Twenty bugs and twenty-eight requests, sorted by the owner's export. Mapped to what we have:
B01 all-audio-cut (14 reports: v0.33's output guard and entry check), B06/B19 the sample-list
freeze (v0.33's paths), B08 FUNC + turn on LFO (v0.33), B16-B18 (v0.33). **Open, first after v0.33**: B10 PERC: switching LFO pages between two PERC tracks shows the
other track's parameter menu (the owner: important). B13 the recorder's normalising too loud
(a design question). The rest are old and, per the owner, fixed since: B03 (v0.29), B11/B12
(v0.30), B14 (VO-6, v0.29's voice fixes); B15 (PERC notes late, v0.27) only if it comes back. Requests to weigh: pattern direct jump, Markov
song mode, LFO matrix, trigless trigs, parameter slides (planned), screen streaming, MD/MnM
preset import, per-track flanger/phaser.

## Testers on v0.36 / v0.37 (2026-11-02, release-blocking)

| # | report | finding | status |
|---|---|---|---|
| T1 | v0.37: "samples stop playing in any machine; working on 0.36"; "I can't play anything I've recorded since 0.37 -- I see the waveform, it doesn't play; a sample recorded before plays" | **the DSP's count**. `dnfw.sampler.program.start` plays a slot below `REC_FIRST` only if it is below the directory's count (pool word 1). Only the whole directory page carries the count (BLANK and FULL: a power-on, a project's load); every live path (LOAD TO PROJECT, a recording, TRIM, DISCARD, a multi-select DELETE, a slice table) sends the slot's frames and its 16-byte entry, never the count. Since v0.33 a recording goes into the first empty slot (no DEST), and LOAD TO PROJECT does too: in a pool with no gaps, that slot is the count, so every one is silent until a power-on, its waveform drawn (the ColdFire has it). Present since v0.31 (LOAD TO PROJECT) and v0.33 (recordings into regular slots); nothing in v0.36 -> v0.37 changed it (no ColdFire C differs; DSP diffs are pvmix, DDRW, the recorder's MAIN address). That it "worked on 0.36" is which slots were free: a slot below the old count (a gap) plays | **fixed (v0.38)**: link.c `K_HEAD` (the page's magic and count) after every live entry; `smp_count_cover` when a recording starts, so it plays while it records (the DSP writes its entry then). Emulator: the new link16 `live` scenario fails on the build before the fix (all 22 adds and 3 recordings silent, the DSP's count 3 throughout) and passes after |
| T2 | ptkrm, v0.36: "after adding 10-20 samples, new ones are silent, waveform fine; old ones play; a restart makes them play; the next one added after a restart is silent again" | the same: the restart sends the whole page (the count now covering them); the next add goes into the slot at the new count. "10-20" is how many gaps below the old count the pool had. misterairplane's M5 (v0.33: "a recording in slot 2 previews but will not play; slot 1 plays") is this too: the preview (`CMD_PREVIEW`) reads the entry without the count | **fixed (v0.38)**, as T1 |
| T3 | v0.37: "the recorder with SRC MAIN still doesn't seem to get any signal" | **no DSP cause found.** v0.37's premise was wrong: its probe (`--steps mainsrc`) printed MIX_BUF's peak at our entry as `[0.0, 1.848, 0.0, ...]` and nothing at the master-mix call (the runner's block loop never reaches sw 0x1c9fd2). Hooks round sw 0x1c2712's calls (2026-11-02): `0x1c1f1e` (after the voices) writes the mix to 0x268438 each block and it is still there at our next entry; the runner's master goes NaN after two blocks (its FX path is not modelled) and something in sw 0x1c2712 before the voices clears a non-finite mix, hence the zeros. So v0.36's MAIN read the last block's mix and v0.37's reads the same mix one call later. The new runner step 3m runs the instrument's order (the per-block routine, then the driver's master-mix call through wr_pvmix and 0x1c9d3f, state carried, the master poked where stock leaves it whole): the tap is the mix every block, MAIN L+R records it within 2 LSB. Ruled out: the L2 placement (0x200a9000..0x200a9200, inside the HW-proven 0x20088400..0x200b0000, zero-loaded, 32-byte lines), SIMD mode at both sites (every MODE1 PEYEN set in the path is cleared before our code and before the call), the cache (one core, DM bus both ways), the hardware rules (gate_hwrules). **Most likely T1**: a MAIN recording goes into the first empty slot like any other and played as silence; the owner's v0.36 "MAIN L+R gave an empty sample" fits the same | **= T1 (owner on v0.37, 2026-11-02)**: the RECORDER's meter moves with SRC MAIN and with SRC = the playing track; after a MAIN recording TRIM shows a real waveform; FUNC + YES plays it. MAIN records fine; the recording played silent because of the count. \x0x/: the silent samples were there already on v0.33, his first version (v0.33's first-empty-slot recordings). Fixed with T1 |
| T4 | v0.37: "after recording, at Y:SAVE FN+N:DELETE FN+Y PLAY, FUNC + YES never plays" | **no cause found.** The DSP's preview (`CMD_PREVIEW` of the slot) does not use the count, and the new runner step 3m plays it: the SPORT page carries the mix plus the recording at half level. The ColdFire side (gate `recflow`) sends the preview on FUNC + YES and its stop on either key's release. Two candidates, neither proven: (a) it plays only while both keys are held (the DT2 also offers one-shot without holding, its D knob); a tap gives a few milliseconds, at v0.37's half level; (b) a MAIN recording that was itself silent (T3) previews as silence | **not a bug in the audio (owner on v0.37)**: holding FUNC + YES he hears the recording. Most likely a short tap: the preview plays only while both keys are held (the DT2's D offers one shot without holding: a request). **Open, UI**: the playhead does not move on the TRIM screen during the preview (not fixed here) |

**Gate (v0.38)**: link16 `live` (ColdFire, `scripts/emu_waverider_menu.py`): a pool of three
at power-on, then 22 LOAD TO PROJECTs and 3 recordings one after another, each must play on
the DSP by its own rule (`dnfw.sampler.live.slot_plays`, held to the DSP's model by
`test_v038_slot_plays_is_the_dsps_own_rule`), its entry and frames the image's, a recording
while it records. SHARC runner step 3m (`mainrec`, in the link group): MAIN recorded,
previewed in TRIM and played back on a ONESHOT track, in the instrument's block order.

## blskk (Discord, v0.37, 2026-11-02)

| # | report | status |
|---|---|---|
| B1 | "arpeggiator, note edit and sampler makes the digitone crash" (no more detail) | **v0.38: a crash path found and closed; whether it is his is not known.** `slc_keynotes` (csrc/sampler/slice.c, v0.26..v0.37: KEYBOARD's [TRIG] keys on a SLICE or GRID track with SLCE at NOTE) asked stock (`0x40034460`) for every key's notes into a `std::vector` it had put on its own stack, room for 8. A key with more notes made stock grow the vector as a vector grows: allocate, copy, and **free the old buffer: our stack address, handed to the heap's free (`0x40120270`)**. The heap is corrupt from then on, and the unit falls over later, wherever the heap is next used (a crash that seems to come from whatever was being done: the arp, NOTE EDIT, the sampler). More than 8 notes: KEYBOARD in CHORD MEMORY mode (its setup's MODE 5) with a chord memory of 9 to 16 notes (stock reads up to 16 a key, `0x4003c17c`; NOTE EDIT is where chords are made). Measured in the emulator on stock code (the snapshot's project, MODE poked): CHROMATIC and FOLDED give a key 0 or 1 note, the three chord modes 3, CHORD MEMORY as many as the memory holds (12 for a 12-note chord: 12 notes into 8 places). **Fix**: each key's notes go into an empty vector that stock grows on the heap, freed with its own operator delete (`0x4001a0d2`). Ruled out in the emulator (no fault, no stack free): the arp (UP, RNG 1..3) on ONESHOT and SLICE tracks, playing, with [TRIG] keys held in KEYBOARD (FOLDED), the ARP page, the RECORDER up, the sequencer ticked through its ISR. **Gate**: the UI fuzz (`fuzz`) now runs a fixed arp scenario before its seeds (a SLICE track at NOTE, the arp on, CHORD MEMORY with 12-note chords, PLAY, KEYBOARD, [TRIG] keys held while the sequencer ticks, the RECORDER and ARP pages) and every run fails on a free() of a stack address (`emu_waverider_menu.py`'s `stack_frees`); its seeds also turn the arp, KEYBOARD and its MODE, chord memories and the sequencer at random. **Reproduced on v0.37's code**: in that scenario the first [TRIG 1] press frees the stack buffer (`0x405c57d0`, from `0x40034d4a`, the chord memory's ninth note) and the free itself takes a CPU exception (vector 4 at `0x40120206`, the firmware's fault reporter: the EXCEPTION screen on the unit); the screen never draws again. On v0.38's code it passes. **Unverified on hardware**: that this is what blskk hit; ask him for the track's machine, KEYBOARD's MODE (FUNC + KEYBOARD) and whether chord memories were in use |
| B2 | "it registers '0 threshold' as an actual threshold, so whenever you arm the sampler it automatically catches everything" | **v0.38**: the DT2 starts "when the incoming audio exceeds the threshold" and asks for THR "just above the background noise", so at 0 it too would start on any noise. v0.30 had put THRES 0 at a fixed -60 dB, evidently under his input's noise (gear plugged in, hum, an offset). Now THRES 0 means "the first sound above the source's own noise": the DSP learns the noise from the blocks after ARM and starts on a block 12 dB over it (never under -60 dB); THRES 1..120 is the DT2's plain threshold, starting when the peak *exceeds* it. The trade, documented (docs/sampler.md, "THRES and ARM"): at THRES 0 a sound already playing steadily at ARM is taken as the floor; YES records at once. **Gate**: the SHARC runner's `rec` step, two new checks (THRES 0 waits through a -50 dB noise floor and starts on the tone's first block, frames exact; THRES 60 waits under a -14 dB tone and starts on a -4 dB one). **Unverified on hardware**: a real input's noise |

## paQ and the owner (v0.38, 2026-11-02, release-blocking)

| # | report | finding | status |
|---|---|---|---|
| R1 | paQ: "the recorder is still broken; it only records one step and leaves the rest blank". The owner: resampling MAIN or a single track, the same; TRIM shows a 2.5 s take whose waveform is a short burst at its start, then a flat line; saved and loaded to a track, the same snippet (`out/report/trim.png`) | **the DSP took the link's commands as the recorder's settings.** `program.recorder`'s `new_command` read words 2..4 of EVERY new command as source, channel and threshold (v0.15..v0.38), though only the recorder's commands carry them; SEND, VERIFY, PREVIEW and SCAN carry offsets and counts there. v0.38's count fix (`smp_count_cover`, rec.c) sends K_HEAD at every take's start, and the loader checks it with `CMD_VERIFY(0, 2)`: source 0 (IN), channel 2 (R), threshold 0. From then on the take records IN's right channel: with nothing plugged in, silence. Measured: the SHARC runner on v0.38's assembled code (`recwhole`): every take (MAIN, TRK3, IN; NOW and ARM) keeps exactly 96 frames (3 blocks: the VERIFY lands in block 3) of its source, then IN R; the model the same. Without the link's traffic, v0.35, v0.37 and v0.38's code record whole NOW takes: the owner's "recording worked on v0.35" fits (the link was idle during a take unless LOAD TO PROJECT, a TRIM or a SCAN ran meanwhile); paQ's "broken before v0.38" is not explained by this (see T1..T3: the silent recordings of v0.33..v0.37 were the count) | **fixed (v0.39)**: only ARM, NOW, STOP, MONITOR, ARM_PLAY (`REC_SETTING_CMDS`) set the source, channel and threshold. **Gate**: SHARC runner `recwhole` (fails on v0.38's code, 96 frames right of each take), unit tests `test_v039_*` (2 s takes on the model with the link's commands; fail on v0.38's program) |
| R2 | the owner: "THRES 0 still triggers" | two causes. (1) R1: K_HEAD's VERIFY set the threshold to 0 while armed, so the next block of IN R that was not exactly zero started the take (at THRES 0 and at any set THRES). (2) v0.38's floor dropped *at once* to the quietest 0.7 ms block's peak: a 50 Hz hum's or a reverb tail's zero crossing is a tenth of its crest, so the floor sat there and the next crest, 4x over it, started the take. Measured on the model: v0.38's program with a -45 dB input (DC, hiss, 50 Hz hum) starts after 31 blocks with no sound at all; v0.35/v0.37 (fixed -60 dB) on it and on MAIN's idle tail too | **fixed (v0.39)**: THRES 0 learns the floor over its first 48 blocks (32 ms: the loudest block, a whole cycle of anything down to 31 Hz; nothing starts while it learns), then follows the noise, down 26 dB/s and up 6.5 dB/s at most. **Gate**: `recwhole` (ARM at THRES 0 on IN with hiss, DC and hum, and on MAIN with a tail and dither: starts on the sound's first block) and `test_v039_thres0_waits_through_a_real_idle_input` (a second of each, idle). **Unverified on hardware**: a real input's noise and MAIN's real idle; a sound within 32 ms of ARM at THRES 0 is taken as the floor (press YES to record at once) |

## The owner (v0.38, 2026-11-02): +DRIVE

| # | report | status |
|---|---|---|
| L1 | "I loaded a sample to a slot and [six in folder AT HIHAT] show as if all of them are loaded onto Slot 3 while I only loaded one, and now those samples sound the same when I preview" (rows all "AT BIRDHOUSE HI-HA", all ">A003") | **v0.39**: `smp_lib_slot_of` (csrc/sampler/link.c) took a library sample to be in a pool slot by its frames, rate, format and seven-letter stem, plus the slot's long name *only where the pool has a meta block* (the host tools' pools); a pool made on the instrument (a NEW project's, or LOAD TO PROJECT into no pool) has none, so a pack's hits of one length matched the first loaded: drawn in its slot, previewed as it (the pool slot played), never loaded, LOAD TO TRK given its slot. Names cut at 35 by the host tools could do the same even with a meta block. Now LOAD TO PROJECT records which sample it copied (`LIBID_OFFSET`, dnfw.sampler.machines: the library entry's frames' adler-32 mixed with the slot's pool address, in the directory page after META_PTR, kept by the pool lists), and only that slot matches; a slot without one (older pools, recordings, host-tool pools) matches nothing, so such a sample previews from the +Drive and loads into a slot of its own (a duplicate at worst, never another sample's audio). **Gate**: link16 `lib` (fails on v0.38's code: 7 of 12 facts). |
| L2 | +DRIVE preview "roughly 12 dB louder" than the sample loaded and played | **not changed in v0.39**: the preview is int16 / 65536 (-6 dB of full scale) added to the master mix buffer; a track's level in that buffer cannot be measured in the SHARC runner (it does not model the stock FX/master path: docs/waverider-dsp-silence.md). On the unit: resample MAIN (the recorder's MAIN tap is that buffer before the preview) while a full-scale sample plays on a track at default VOL/LEVEL; its peak against 0.5 is the difference. |
| L3 | Held UP/DOWN in +DRIVE's menus, FUNC + arrow a page, a pushed knob turned fast, D pushed must not leave +DRIVE | **v0.39** (rec.c): the held-arrow repeat (v0.30) only ran in a folder's list; now also at the two stores and in the action menu (LOAD TO PROJECT's). FUNC + UP/DOWN a page (6 rows; the menu's first/last); a knob turned while pushed in, a page a detent; the encoders' pushes are the browser's (stock took D's). **Gate**: `drivenav`. |
| L4 | Long names: head...tail as the DT2's ("KICK_DEE...TH_HIT"), the selected row scrolling | **v0.39** (smp_page.c): unselected rows head...tail (a .WAV/.AIF/.FLAC/.MP3 dropped), the selected row scrolls (1 s rest, 5 characters a second, 1 s rest, again), redrawn only when it moves; moved off, head...tail again. +DRIVE, PROJECT RAM and the SAMP list. Slot names are the meta's long names where the pool has them, else the seven-letter name. **Gate**: `drivenav`. |

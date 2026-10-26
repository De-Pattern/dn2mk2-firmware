# Firmware versions

Every build of this mod, newest first, with what it adds and what to test after
flashing it. Each build **contains everything before it**, so you only ever flash the
newest one. All builds are on stock Digitone II **OS 1.11**.

**Download:** the `.syx` files are on the **`builds`** branch, one folder per
version (`builds/vX.Y-NAME/`), each beside its gate record (`.gate.json`). On GitHub,
switch the branch selector from `main` to `builds`, open the version's folder, click
the `.syx`, then **Download raw file**. They are kept off `main` so that the code
branch never holds Elektron firmware (see the note at the end).

**v0.4 to v0.7 are withdrawn (2026-10-18).** Their images are larger than the 2 MiB the
OS's USB upgrade receives into, and the receiver does not check: the transfer stalls at
the very end (nothing is written to flash; a power cycle clears it). Their sections
below are kept for the record; the files are gone from `builds`. Every build from v0.8
on is checked against that limit by the gate (`docs/usb-upgrade-limit.md`).

**Only flash a file whose sha256 matches its gate record** (`CLEARED TO FLASH` from
`scripts/ship_gate.py`; CLAUDE.md). The sha256 is listed below and in the
`.gate.json` beside it. On Windows: `certutil -hashfile FILE SHA256`.

Every flash, every version:

1. **Back up the +Drive** with Elektron Transfer.
2. **Low volume.** Flash over USB as usual; keep the proven DIN recovery cable at hand.
3. Run the **regression check** (about 10 minutes, `docs/SAFETY.md`): boots with no
   `EXCEPTION`; one track each of FM Tone, FM Drum, WaveTone, Swarmer and a MIDI track
   all play as before; chorus, delay, reverb, master overdrive and compressor;
   pattern change, song mode, a p-lock, an LFO on a stock machine; SAVE PROJECT,
   power-cycle, reload.
4. Then the version's own tests, below. If anything is off: recovery to stock 1.11,
   then tell Claude what you saw.

| version | date | adds | download | gated |
|---|---|---|---|---|
| MNM-1 | 2026-10-26 | **A separate line**: v0.25 without CZ/RESONATOR, plus the Monomachine's SID 6581, DPRO Wave, DPRO Ddrw, DPRO Dens and VO-6 | `builds/MNM-1-MONOMACHINE/` | yes |
| **v0.25** | 2026-10-26 | The playhead on the waveform; the DT2's sample list and +Drive-style folder browser (SAMPLE ACTION: load, rename, delete); the recorder as the DT2's (RECORDING, NORMALIZING, TRIM with preview, FILE NAME, ASSIGN); GRID/SLICE slice locks; KEYBOARD's next 16 slices; an LFO on SAMP steps through your samples; the in-browser patcher | `builds/v0.25-BROWSER/` | yes |
| v0.24 | 2026-10-25 | The Machinedrum's nine P-I machines on PERC (PI-BD, SD, MT, ML, MA, RS, RC, CC, HH) from your MD firmware, +6 dB; the first hit after choosing an MD machine is now the MD's own | `builds/v0.24-PI/` | yes |
| v0.23 | 2026-10-24 | SLICE's own menus (YES: EDIT SLICE POINTS, CREATE SLICE GRID with SLICES 2-64 and TR.DET), the slice editor, SLICES on the trig keys (KEYBOARD, SLCE NOTE); a sample with no slices plays whole | `builds/v0.23-SLICE/` | yes |
| v0.22 | 2026-10-24 | The RECORDER is its own screen (FUNC + VOICE) with the DT2's TRIM, NAME and ASSIGN steps; recordings to any slot; 400 MB for samples (after a RAM check at power-on); MD machines +6 dB; a browser import tool; ONESHOT never goes silent at LEN 0 | `builds/v0.22-RECORDER/` | yes |
| v0.21 | 2026-10-23 | RESONATOR and CZ PHASE page 1 in the Elektron style: knobs for continuous controls, choices (WAVE, SEL, OCT, MOD, KF, SUS) by name in a box | `builds/v0.21-KNOBS/` | yes |
| v0.20 | 2026-10-23 | Fixes: the buzz on WaveTone/FM after a sample or PERC track (the link no longer touches the DSP's per-track routing), the RECORDER's flashing, SLICE's pages, the sample list; PERC drawn as the Machinedrum's screen; sample pages in the DT2's own geometry | `builds/v0.20-FIXES/` | yes |
| v0.19 | 2026-10-23 | SLICE, the Digitakt II's sixth sample machine: your WAV's cue points (or a grid, or its hits) as up to 64 slices, SLCE / LEN / NOTE mode, slices marked on the waveform | `builds/v0.19-SLICE/` | yes |
| v0.18 | 2026-10-23 | The Digitakt II's own sample engine: its interpolator and decimator, its STRETCH, WERP's clock, GRID NOTE mode, BARS 1-8 and SEG 1/32-1/8, no clicks at starts, ends and retriggers | `builds/v0.18-DT2-ENGINE/` | yes |
| v0.17 | 2026-10-22 | PERC is the Machinedrum: its 25 TRX/EFM/GND machines from the MD's own firmware (every reference case matches), TYPE p-lockable as before | `builds/v0.17-MACHINEDRUM/` | yes |
| v0.16 | 2026-10-22 | 96 MB of your samples on the +Drive, loaded at power-on over a fast checked link; recordings kept after power-off; the SAMP name list; waveforms for every slot | `builds/v0.16-DRIVE/` | yes |
| v0.15 | 2026-10-22 | DT2 SRC pages (knobs, waveform, RECORDER), one encoder click a choice, value names in the header, loops follow the knobs live; RECORDER: SRC IN/MAIN/TRK1-16, CHAN, YES records, ARM, R.LEN, R.STRT | `builds/v0.15-RECORDER/` | yes |
| v0.14 | 2026-10-22 | Sampling: page 2 of every sample machine records IN / IN L / IN R / MAIN into SAMP 124-127 (threshold, length); ONESHOT's CFAD heard | `builds/v0.14-SAMPLING/` | yes |
| v0.13 | 2026-10-22 | The Digitakt II's sample machines (ONESHOT, WERP, STRETCH, REPITCH, GRID) with DT2-style pages; four test sounds; your WAVs over USB, kept on the +Drive | `builds/v0.13-SAMPLER/` | yes |
| v0.12 | 2026-10-21 | PERC: labels follow TYPE; page 1 the machine's 8 parameters; page 2 TYPE + Machinedrum effects (AMD AMF EQF EQG FLTF FLTW FLTQ); no stray ring | `builds/v0.12-PERC-FX/` | yes |
| v0.11 | 2026-10-20 | PERC: your 24 Ravel drum machines (TRX/EFM/GND) as a machine, TYPE + 8 named parameters; Waverider removed | `builds/v0.11-PERC/` | yes |
| v0.10 | 2026-10-20 | No more dead notes on RESONATOR/CZ (voice stealing); PING/SHFT TYPE by name; Waverider osc 2 (page 2); GRAN granular filter type | `builds/v0.10-GRAN/` | yes |
| v0.9 | 2026-10-19 | CZ's release: the DCW envelope runs on past its sustain step at note-off, as on a real CZ | `builds/v0.9-CZ-release/` | yes |
| v0.8 | 2026-10-18 | Everything in v0.7 (CZ PHASE, RESONATOR, SHIFT, PING, Waverider), sized to fit the USB upgrade: Waverider has 9 tables (BITS, PHAS out) | `builds/v0.8-CZ/` | yes |
| v0.7 | 2026-10-18 | CZ PHASE machine (Casio CZ phase distortion), 8-step DCW envelope on pages 2–3, up to 6 voices | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.6 | 2026-10-18 | RESONATOR machine (Rings-style modal resonator), up to 4 voices | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.5 | 2026-10-18 | SHIFT filter type (frequency shifter) beside PING; DSP memory packed tighter | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.4 | 2026-10-13 | PING filter type (SVF / LADR / VCFQ / LPG) on the FLTR page, any machine | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.3 | 2026-10-11 | Waverider W2: all page-1 controls, built-in scanner, its names in the LFO lists | `builds/v0.3-Waverider-W2/` | yes |
| v0.2 | 2026-10-11 | Waverider W5: 11 tables, POS glide, display that follows the sound | none (superseded) | before the gate |
| v0.1 | 2026-10-06 | Waverider: a wavetable machine in MACHINE SEL | none (superseded) | before the gate |

---

## MNM-1 — MONOMACHINE (a separate line: v0.25 + the Monomachine's synth machines)

`DN2mod_MNM-1_MONOMACHINE_OS1.11.syx` (in `builds/MNM-1-MONOMACHINE/`)
sha256 `daa47def96b036fdd3aeeef66504daf17a0399349c46f765aa395e6d50e37273`
Gate: CLEARED TO FLASH, 2026-10-26 (USB size 2,047,775 of 2,097,152; DSP image 1,013,668 of 1,048,575). Source: branch `monomachine`, commit `cd0dbbf`. Docs: `docs/mnm.md` on that branch.

**Not a numbered version.** It is everything in v0.25 except CZ PHASE and RESONATOR (removed),
plus the Monomachine machines. The numbered line (v0.25 and on) stays without them until we
decide which line goes on. The patcher builds it too: it asks for a fourth file, the
**Monomachine SFX-6 OS 1.32B** .syx, for this build only.

**Adds.**
- **Five machines from the Monomachine**, each its own MACHINE SEL entry, after PERC: **SID 6581**,
  **DPRO Wave**, **DPRO Ddrw**, **DPRO Dens** and **VO-6**, from your Monomachine OS (every
  reference case of the Monomachine's own DSP code matches, at 60 dB or better). One page each,
  the Monomachine's eight parameters; choices by name (SID's waves and modes, VO-6's 21
  consonants, DENS's pitches, the waves as S01..S32).
- **Every machine's note 60 is middle C** (261.6 Hz), as the DN2's own (DPRO Wave plays an
  octave up from the Monomachine's, where it sits an octave under the others).
- **The tables travel at power-on**: the Machinedrum's and Monomachine's tables are sent to the
  DSP over the sample link at power-on rather than living in the DSP's image (which frees
  about 35 KB there). PERC's machines are silent for the first ~0.1 s after power-on, and DDRW
  and DENS for ~8 s (the DSP builds their waves).

**Test** (after the regression check and v0.25's tests):
1. MACHINE SEL: the five appear after PERC, before the sample machines; each loads, shows its page.
2. Play each at C3, C4, C5: in tune with an FM Tone track at the same notes.
3. SID: WAVE through TRI/SAW/PULS/MIX/NOIS; PW and PWAD on PULS; MOD RING/SYNC.
4. DPRO Wave: WAVE S01..S32, WP and WPM.
5. DPRO Ddrw: WAV1/WAV2 with MIX; TIME on a wave change; BR1/BR2 bit reduction.
6. DPRO Dens: PCH2..4 (OFF, -12..+12, the ratios).
7. VO-6: VOC1/VOC2 for the vowel; CONS M, N, S with CLEN/CVOL; V-SW OFF ends on the consonant.
8. SAVE PROJECT, power-cycle, reload: the tracks keep their machines and knobs.
9. Three SID tracks at once: the third is silent (the DSP budget, below).

**Known issues / not done.**
- **The DSP budget.** The Monomachine voices never go quiet (as on the Monomachine) and cost
  2 to 10 Machinedrum voices each, so they are rendered in track order while their total cost
  fits a budget: two SIDs, four DPRO Waves, one DDRW and one DENS, or two VO-6 at once; a
  track past it is silent. The budget is set from the model, not measured on the instrument.
- **Mono**, one voice a track, as the Monomachine.
- **The knobs start where WaveTone's are** when the machine is chosen, not at the Monomachine's
  defaults (VO-6's VOIC at 100 whispers): set them after choosing.
- **DDRW and DENS** read stand-in waves built from the 32 DigiPRO ROM waves (your Monomachine's
  own Digibank is in its flash, not in the OS file). **DENS's chorus** (CHRL/CHRW) is not
  ported. **DPRO-BBOX** does not fit.
- **Not seen on hardware yet**: anything of it. All checked in the emulators.

---

## v0.25 — BROWSER (the playhead, the DT2's sample list and folder browser)

`DN2mod_v0.25_BROWSER_OS1.11.syx`
sha256 `bf838003ef8beb29f5903cd5a67f59cae4f6bfebead35ac11877b19cfc2a7f9a`
Gate: CLEARED TO FLASH, 2026-10-26 (USB size 2,019,596 of 2,097,152; DSP image 1,048,356 of 1,048,575). Source: commit `ba3347c` (gate script `d7182bb`). Docs: `docs/sampler.md` ("v0.25: the playhead, the DT2's sample list and browser, modulated SAMP").

Everything in v0.24, plus:

**Adds.**
- **The playhead.** On every sample machine's waveform page, a double line shows where the
  voice is reading, as on the DT2. It follows p-locked starts, LFOs on STRT and LEN,
  WERP's segments and STRETCH's head.
- **STRETCH and REPITCH mark their bars** on the waveform (BARS 1, 2, 4, 8), dotted,
  between the start and end markers.
- **The sample list, as the DT2's.** Turning SAMP brings it up, and it stays up:
  - SAMP or **UP/DOWN** move through the slots. The track plays the outlined slot, so its
    [TRIG] previews it.
  - **YES** (or pushing SAMP) keeps it, and **NO** puts SAMP back as it was.
  - The title bar reads YES:OK NO:X FN+YES:D, as the DT2's.
  - Long names show in full; an empty slot is "---".
- **The folder browser: FUNC + YES** in the list opens it, as the DT2's +Drive browser.
  - At the top, folders only: yours (from the import tool), then **incoming** (sent in no
    folder) and **recorded** (the recorder's).
  - Inside a folder, each sample with the slot it plays from (**▸A009**).
  - **YES** opens a folder, or gives the track the sample (the DT2's quick assign).
    **NO/LEFT** goes back up, and out of the browser at the top.
  - **RIGHT** on a sample opens **SAMPLE ACTION**: LOAD TO TRK, RENAME (the naming
    screen), and DELETE (asks first).
- **Long names and folders** come from the import tool. It keeps your folders: drop a
  folder, or use "Browse a folder", and each sample gets its folder's name. Names can be
  up to 35 characters.
- **An LFO on SAMP steps through your loaded samples**, from the one SAMP is set to, and
  wraps round them. Before, it mostly landed on empty slots and played nothing.
- **WERP's SEG** takes three detents for each choice, instead of one.
- **The recorder, as the DT2's** (its manual's 13.2 and your photos):
  - While it records: the **RECORDING** screen, the waveform as it comes in, the time,
    YES: STOP.
  - When it stops: **SAVING...** then **NORMALIZING...** (a bar each): the recording is
    brought to full scale (its peak to 32,700) on the +Drive and in the DSP.
  - **TRIM**: Y:SAVE keeps START..END and goes on to the name; FN+N:DEL drops it;
    **FN+Y plays START..END while you hold FUNC + YES**. No "NO: ALL". E and H move
    START and END smoothly (faster as you turn faster; FUNC held: fine).
  - **FILE NAME**: U/D the letter, L/R the cursor, FUNC + NO deletes, FUNC + YES
    inserts, YES saves, NO keeps the name. Hold FUNC: the character grid appears; FUNC +
    the arrows pick a character, and letting FUNC go puts it at the cursor.
  - **ASSIGN SAMPLE TO TRACK?**: a [TRIG] key, or NO to skip. It is on the +Drive
    either way.
- **GRID's icon** on page 1 shows the slice count as a grid (2 .. 64 cells), as the DT2's.
- **Slices to your trigs** (the DT2's ALLOCATE SLICE): on a GRID track's page, YES opens
  CREATE LINEAR LOCKS / CREATE RANDOM LOCKS / NO: CANCEL LOCKS. LINEAR locks slice 1, 2,
  3 .. onto the track's placed note trigs in order; RANDOM a random slice each (YES again
  re-rolls); NO puts back the locks there were. SLICE's menu (YES on a SLICE track) has
  the same two at its end.
- **GRID and SLICE, SLICE at NOTE, KEYBOARD mode**: [TRIG] 1..16 play slices 1..16 (GRID
  too, now), and KEYBOARD's octave (KEYBOARD + UP/DOWN, as the DT2 moves its notes) moves
  them on by 16: slices 17..32, 33..48, 49..64.
- **The import tool**:
  - **Slots**: Replace all, in list order (as before); Replace all, choosing each slot;
    or Add, which sends only the new samples into the slots you choose and keeps the rest.
  - **Long names and folders.**
  - It installs as an app from https://de-pattern.github.io/dn2mk2/.
- **The DN2 Mod Patcher** (https://de-pattern.github.io/dn2mk2/patcher.html)
  builds this file in the browser from your own DN2 1.11, DT2 1.17 and MD UW 1.63 files,
  and saves it only if its sha256 is this build's (`docs/patcher.md`). v0.24 is there too.

**Test** (after the regression check):
1. **Send samples in folders** with the import tool: drop a folder of folders, then Send.
2. **The list.** On a ONESHOT track, turn SAMP. The list stays up with long names.
   - UP/DOWN move through it, and [TRIG] plays the outlined sample.
   - NO puts the old sample back. Turn SAMP again and press YES: it keeps the new one.
3. **The browser.** In the list, FUNC + YES. Open a folder (YES), pick a sample (YES): the
   track plays it, and the page is back. Then RIGHT on a sample: RENAME it, and DELETE
   another (YES twice).
4. **The playhead.** On page 2 of ONESHOT, play a long sample: the double line moves
   across. P-lock STRT on a few steps: the line starts where each lock says. Try WERP and
   STRETCH too.
5. **STRETCH's bars.** On STRETCH page 2, set BARS to 4: three dotted lines between start
   and end.
6. **LFO on SAMP.** Load 4–5 samples, put an LFO (FREE, slow, some depth) on SAMP:
   successive notes step through your samples, with no silent ones.
7. **WERP's SEG**: three detents for each choice.
8. **Add in the import tool**: send two more samples with Add into empty slots. The
   others are still there.
9. **Record.** FUNC + VOICE, YES: the RECORDING screen draws the waveform as it comes in.
   YES stops: SAVING..., NORMALIZING... (a quiet recording comes back at full level).
10. **TRIM.** Move E and H (smooth, faster as you turn faster). Hold FUNC + YES: it plays
    START..END while held, and stops when you let go. YES: FILE NAME. Spell a name (FUNC +
    YES inserts, FUNC + NO deletes), YES: ASSIGN SAMPLE TO TRACK?, a [TRIG]: that track
    plays it. Then FUNC + NO on a second recording's TRIM drops it.
11. **SLICE's menu**: on a SLICE track, YES opens it (after using FUNC too). Its last two
    items lock slices onto placed trigs.
12. **GRID**: place trigs, YES on its page: CREATE LINEAR LOCKS puts slices 1, 2, 3 .. on
    them; RANDOM shuffles (YES again re-rolls); NO puts them back. Page 1's GRID icon
    changes with the slice count.
13. **KEYBOARD on GRID or SLICE with SLICE at NOTE**: trigs 1..16 play slices 1..16;
    KEYBOARD + UP: 17..32.

**Fixed.**
- **YES did nothing on TRIM, and on a SLICE track's page (no slice menu)**, after FUNC had
  been used once: FUNC's release carries no release flag, so v0.22..v0.24 kept FUNC
  "held" for good. FUNC is now read as it is.
- **SLICE's and GRID's menus** are drawn as soon as they open or move (they waited for the
  page's next redraw tick before).

**Known issues / not yet done.**
- **ONESHOT's FORWARD LOOP** sometimes not looping (your v0.24 report): not reproduced in
  the model yet (the loop region, the knob follow and a REV LOOP / FWD LOOP switch all loop
  there). The exact PLAY, STRT, LEN, LOOP and trig LEN when it happens would find it.
- **The preview** plays into the main mix at full level, after the master; it is not on a
  track, so the track's level, filter and FX do not touch it (as the DT2's preview).
- **Slices past 16 in KEYBOARD mode** follow the DT2: KEYBOARD + UP/DOWN (its octave) moves
  the keys on by 16 slices; PAGE stays the pattern page.
- **The browser picks among the samples already loaded.** The DT2's copies a sample from
  the +Drive into the slot; here every sample is in RAM from power-on, so picking one only
  sets SAMP.
- **One bank (A, 128 slots).** The DT2 has eight.
- **Presets from samples are not in this build.** It would need the DN2's own preset
  naming screen patched, and I left that alone rather than risk how presets save.
- **The playhead is the DSP's position at the start of each block**, so STRETCH's moves
  in 43 ms steps.
- **Not seen on hardware yet**: the playhead's rate on the real screen, the list's keys on
  the real panel, the LFO stepping through samples, and the import tool's folders. All
  were checked in the emulator, with the DSP's positions and the modulation mirror poked.

---

## v0.24 — PI (the Machinedrum's physical-model machines on PERC)

`DN2mod_v0.24_PI_OS1.11.syx`
sha256 `f5853cdb5947204c5ada072f96ea02eb1890a015a2bc151a697b0fe67401d78c`
Gate: CLEARED TO FLASH, 2026-10-25 (USB size 2,013,940 of 2,097,152; DSP image 1,047,296 of 1,048,575). Source: commit `7589d67`. Docs: `docs/md.md` ("v0.24: the tables' stream (`zpack`) and the P-I machines' room").

Everything in v0.23, plus:

**Adds.**
- **The Machinedrum's nine P-I machines on PERC's TYPE**, after GND-IM: **PI-BD, PI-SD,
  PI-MT, PI-ML, PI-MA, PI-RS, PI-RC, PI-CC, PI-HH** (the manual's P-I BD, SD, XT/MT, ML,
  MA, RS, RC, CC, HH, pages A-9 and A-10). Each is its DSP code and its host scale function
  from your MD firmware, ported as the other MD machines were, with the same page and
  parameter names as on the MD, and the same +6 dB as the other MD machines.
- How close they are to the MD (its own DSP code, run in an emulator, the golden runs in
  `test/test_md.py`): PI-MA exact; the others within 81 to 100 dB of the MD's own output
  (PI-BD 81, PI-RC 88, PI-MT 89, PI-ML 90, PI-RS 93, PI-SD 93, PI-HH 100; PI-CC by level).

**Changed.**
- **TYPE's range now covers 34 machines**, so a TYPE value saved in a kit may now pick a
  neighbouring machine (the knob is spread over 34 instead of 25). Set TYPE again on
  saved PERC kits.
- **The first hit after choosing any MD machine** is now the MD's own first hit (the
  machine's init runs after its parameters are read, as on the MD). Except **PI-ML**: on
  the MD its first note after choosing it is silent; here it plays, as the MD's second.
- The DSP's MD tables ship compressed and are decoded in the first 19 ms after power-on (as
  the sine was filled before); the tables are the same, word for word.

**Test** (after the regression check):
1. **Each P-I machine.** On a PERC track, turn TYPE through PI-BD ... PI-HH. Each shows its
   name as the MD does (P-I BD ... P-I HH) and its eight parameters, and plays.
2. **Against the MD**, if you have it to hand: the same parameters on both, by ear.
3. **The other MD machines** (TRX, EFM, GND) sound as in v0.23.
4. **Many at once.** Eight PERC tracks on P-I machines playing together: no dropouts.

**Known issues / not yet done.**
- **Not heard on hardware yet.** The P-I machines are checked against the MD's own code in
  the emulator, and the DSP's code against its model in the SHARC runner.
- The P-I machines are the heaviest MD machines (about 9,000 to 19,000 DSP instructions a
  44.1 kHz block each); the DSP's load with many at once is not measured on hardware.

---

## v0.23 — SLICE (its menus, its editor, SLICES on the trig keys)

`DN2mod_v0.23_SLICE_OS1.11.syx`
sha256 `d3468486559f4ad14c378a8b99d875b06ee2be31dde4c6cd69da37d97cc1c5ee`
Gate: CLEARED TO FLASH, 2026-10-24 (USB size 1,999,901 of 2,097,152). Source: commit `2f63d3e`. Docs: `docs/sampler.md` ("v0.23: SLICE's own menus, its editor, and SLICES on the trig keys").

Everything in v0.22, plus:

**Adds.**
- **YES on a SLICE track's page** opens the DT2's SLICE menu: **EDIT SLICE POINTS** and
  **CREATE SLICE GRID**. UP/DOWN pick, YES opens, NO closes.
- **CREATE SLICE GRID**: **SLICES** (E) 2–64 and **TR.DET** (H) off/on. YES makes the slices,
  NO cancels.
  - TR.DET off: an even grid.
  - TR.DET on: the sample is read back from the +Drive (a short "READING THE SAMPLE" wait),
    and a slice starts at each hit, up to SLICES of them.
- **EDIT SLICE POINTS**: the sample's waveform with its slices.
  - **LEFT/RIGHT** pick a slice. **E** START, **H** END and **D** LOOP move its points.
    **F** zooms; FUNC + F zooms the height. **G** scrolls.
  - Hold FUNC while turning for single-frame steps.
  - **FUNC + YES** adds a slice where the view is, and **FUNC + NO** removes the picked one.
  - **NO** leaves and saves.
- **Your slices are kept**: on the +Drive, and in the DSP at once, as soon as you leave the
  editor or make a grid.
- **SLICES on the trig keys**: on a SLICE track with **SLCE set to NOTE**, turn on
  **KEYBOARD** mode, and trig keys 1–16 play slices 1–16.
  - It records into patterns as notes, so playback hits the same slices.
  - The key lights still show the keyboard layout.
- **A sample with no slices now plays whole** on SLICE. Before, it played nothing, which is
  why SLICE seemed dead on samples sent without cue points.

**Test** (after the regression check):
1. **SLICE on a plain sample.** Put a sample with no slices on a SLICE track: it plays the
   whole sample.
2. **The grid.** YES on the SLICE page, then CREATE SLICE GRID. Set SLICES to 8, then YES.
   The page-2 markers show 8 slices, and SLCE 1–8 each play one.
3. **Transients.** Again with TR.DET ON on a drum loop: the slices start on the hits.
4. **The editor.** YES, then EDIT SLICE POINTS. Step through the slices with LEFT/RIGHT, move
   START and END, zoom in, and FUNC + YES to add a slice. NO leaves. Play the slices: your
   edits are heard.
5. **After power-off.** Power-cycle: the slices are still there.
6. **SLICES keys.** Set SLCE to NOTE and turn on KEYBOARD. Trig 1 plays slice 1, trig 2 slice
   2, and so on. Record a few into a pattern and play it back.
7. **Other tracks.** KEYBOARD mode on a WaveTone or ONESHOT track plays notes as before.

**Known issues / not yet done.**
- The DT2's **CREATE LINEAR LOCKS / RANDOM LOCKS** are not here.
- The SLICES keys work through KEYBOARD mode, not a TRIG MODE entry. The DN2's own SLICES
  entry exists but is switched off in its firmware, and turning it on would take five
  patches to stock code.
- The waveform in the editor is drawn from 1,024 points of the sample. At the deepest zoom
  it is coarse, but the slice points themselves are exact.
- Slices made on the instrument are kept in a 128 KB area at the end of the recordings'
  area, so the recordings' area is 128 KB smaller.
- **Not seen on hardware yet:** reading a sample back for TR.DET and the editor (checked
  against a model of the +Drive in the emulator), and the KEYBOARD path on the real panel.

---

## v0.22 — RECORDER (its own screen, trim/name/assign, 400 MB)

`DN2mod_v0.22_RECORDER_OS1.11.syx`
sha256 `accc18df58ef54348933a9830d9e9310e4bef521dcd33339fcb8ccf7ed718f94`
Gate: CLEARED TO FLASH, 2026-10-24 (USB size 1,995,356 of 2,097,152). Source: commit `e6810ac`. Docs: `docs/sampler.md` ("v0.22: the RECORDER is a screen of its own"), `docs/md.md` ("v0.22: level").

Everything in v0.21, plus:

**Adds.**
- **The RECORDER is a screen of its own**, as on the Digitakt II. **FUNC + VOICE** opens it
  over any page and on any track. The same combo closes it, and so does NO. (Stock's
  FUNC + VOICE unison toggle is replaced.) The page keys, PRESET, SETTINGS, TRK, PTN and
  SONG also close it. A recording keeps going after the screen closes. While it is up, its
  knobs and keys act on the recorder only and never touch the track's sound.
  - **A** SRC: **EXT L+R**, **EXT L**, **EXT R**, **MAIN**, **TRK1-16**. The screen shows
    only the input you chose.
  - **D** THRES, **E** DEST (the slot the recording goes to), **F** R.LEN, **G** R.STRT,
    **H** ARM. YES records, and YES again stops.
- **After a recording, the DT2's steps:**
  - **TRIM**: the waveform, with **E** START and **H** END. Hold FUNC for finer steps;
    LEFT and RIGHT nudge. **YES** keeps the trimmed part, **NO** keeps it all,
    **FUNC + NO** throws the recording away.
  - **NAME**: seven characters. A knob or UP/DOWN changes the letter, LEFT/RIGHT moves.
    **YES** saves the name, **NO** keeps RECnnn.
  - **ASSIGN**: press a **[TRIG] key** and that track plays the sample. A synth track
    becomes ONESHOT first. **NO** assigns none.
- **Recordings go to any slot**, not four fixed ones. They share a 32 MB area (about 5½
  minutes). DEST starts on the first empty slot and moves to the next empty one after each
  recording.
- **400 MB for samples** (it was 128 MB), on the +Drive and in the DSP's RAM: 368 MB of
  your own plus the 32 MB recordings area. At every power-on the DSP first checks that all
  of its RAM is really there (about 0.7 s). Only then does anything load past 128 MB; if
  the check fails, everything stays as in v0.21. `python tools/dn2samples.py hello` tells
  you which happened.
- **The Machinedrum machines are 6 dB louder**, level with WaveTone and FM Tone at their
  defaults. Their sound and parameters are unchanged.
- **The sample list:** **UP/DOWN** move through it, and **pressing the SAMP encoder**
  chooses and closes it.
- **GRID and SLICE** show the number of slices you chose (the box, the icon and the page-2
  markers), not up to 4.
- **LFO destinations:** a custom machine's unused parameters ("-") are gone from its list.
- **A browser import tool** (`tools/web/index.html`, on `main`/`checks`, not on `builds`).
  Open it in Chrome or Edge, from disk or a web host. Pick the Digitone II's MIDI ports,
  then drop or browse WAVs. It shows which slot each sample goes to, what is on the
  instrument now, the memory used, sent and left, and a transfer-time estimate. Then send.
  `dn2samples.py` also gains `dir`, which lists the slots.

**Fixes.**
- **Recording a track recorded the wrong thing or silence, and the meter moved on a silent
  track.** The recorder read the DSP's mix buckets by the wrong index. TRK1-16 now record
  and meter exactly that track.
- **TRK + CLEAR turned a sample, PERC, RESONATOR or CZ track into WaveTone.** It now keeps
  the machine and resets its sound.
- **ONESHOT went silent with LEN at its lowest, and a held looped note could stop for good
  while you moved STRT or LEN.** The region could become empty, and an empty region ends
  the note. Now ONESHOT always keeps at least a tiny region (32 frames, or 1/508 of the
  sample): the knobs' extremes play a very short loop, and a held note survives any sweep.

**Test** (after the regression check):
1. **The RAM check.** After power-on, run `python tools/dn2samples.py hello`. It should
   say "the DSP's RAM check: passed". Tell me if it says FAILED.
2. **The combo.** On any track and page, hold FUNC and press VOICE: the RECORDER fills the
   screen. FUNC + VOICE again closes it, and so does NO. Turn knobs A-H while it is up:
   the track's sound must not change.
3. **EXT input.** Set SRC to EXT L+R and play into the inputs: the meter must move. Try
   EXT L and EXT R. (The recorder reads the same input buffer the DN2's mixer plays, as the
   emulator shows, so this should work now. Tell me if it does not.)
4. **A track.** Set SRC to TRK1 with track 1 playing: the meter moves. On a silent track it
   stays still.
5. **Record, trim, name, assign.** YES, play, YES. TRIM shows the waveform: move START
   (E) and END (H), then YES. Spell a name, YES. Press trig 3: track 3 becomes ONESHOT and
   plays your recording from the trimmed start.
6. **FUNC + NO** on TRIM throws a recording away: its slot is empty again.
7. **After power-off.** Power-cycle: recordings, their trims and names are still there.
8. **MD level.** Play a PERC kick next to a WaveTone or FM Tone track at defaults: about
   the same loudness.
9. **The list, GRID/SLICE, TRK + CLEAR and LFO**, as described above.
   ONESHOT: hold a looped note and sweep STRT and LEN to both ends and back. It keeps
   sounding, and LEN at 0 plays a very short loop.
10. **The browser tool.** Open `tools/web/index.html` in Chrome, Connect, and check that
    section 4 lists what is on the instrument. Drop a few WAVs and send them.
11. **Over 128 MB** (only if test 1 passed and you have that many samples): send more than
    128 MB with the new `dn2samples.py`. All slots load after power-on.

**Known issues / not yet done.**
- **The 400 MB pool has not run on hardware before.** That is why the RAM check exists. If
  it fails, you lose nothing; the pool just stays at 128 MB.
- **No FUNC + YES preview on TRIM**, no zoom, and no normalising (the DT2 normalises
  recordings).
- **No trig-key audition** in the sample list. The DT2's TUNE ruler is still plain text.
- **The emulator does not change parameters on knob turns.** UP/DOWN in the sample list
  and the slice count from turning SLCE were checked in code and with set values, not by
  turning. The recorder's own knobs were checked in the emulator.
- **The LFO list filter** is checked by unit tests only, not in the emulator.

---

## v0.21 — KNOBS (RESONATOR and CZ PHASE page 1)

`DN2mod_v0.21_KNOBS_OS1.11.syx`
sha256 `173948455e1a7668ab0797403e1eb7923dfb69f437ddf8d1c744f9201cfa4094`
Gate: CLEARED TO FLASH, 2026-10-23 (USB size 1,991,417 of 2,097,152). Source: commit `8e3e5e7`. Docs: `docs/cz.md`.

Everything in v0.20, plus:

**Adds.**
- **RESONATOR's page** is drawn the way the Digitakt II's pages are. Its eight controls (TUNE,
  LEV, STRC, BRIT / DAMP, POS, EXCT, HIT) are knobs in the Elektron grid, each over its label.
- **CZ PHASE's page 1** is drawn the same way. DET and DCW are knobs. The choices (WAVE, SEL,
  OCT, MOD, KF, SUS) show their value by name in a box, for example SAW, OCT0, OFF, SUS1.
  The wave-pair picture is no longer on page 1; WAVE's box names the pair.
- CZ's envelope pages (2 and 3) are unchanged.

**Test** (after the regression check, and v0.20's tests if you have not run them):
1. **RESONATOR.** Put it on a track. Turn each of the eight knobs: the pointer follows, and
   the sound changes as before.
2. **CZ PHASE, page 1.** Turn WAVE: the box names the wave or pair. Turn SEL, OCT, MOD, KF and
   SUS: each box steps through its choices. DET and DCW are knobs.
3. **CZ pages 2 and 3.** They show the envelopes as before.

**Known issues.** Same as v0.20.

## v0.20 — FIXES (the buzz, the recorder, the pages)

`DN2mod_v0.20_FIXES_OS1.11.syx`
sha256 `e87c23626cc794547e65275176ae7f6cc914d73d86a086a09fa33d717641eb8f`
Gate: CLEARED TO FLASH, 2026-10-23 (USB size 1,991,619 of 2,097,152). Source: commit `61be36e` (the gate's own test fixes after it: `15b21f5`, `c69a379`, no firmware change). Docs: `docs/sampler.md` (the link), `docs/md.md` (the PERC page).

**Fixes.**
- **The buzz on WaveTone and FM after a sample or PERC track.** The cause was ours: the
  sample link (v0.14 to v0.19) wrote packets into 16 words of the frame the ColdFire sends
  the DSP 1,500 times a second. Those words were wrongly documented as unused. They are the
  DSP's per-track routing, so every packet (each recorder command, each check while
  samples loaded, and the whole load if the fast link was down) sent tracks' audio to the
  wrong places. That made the "fizzy" doubled sound, and only a reboot cleared it. v0.20
  never writes those words. Everything, commands included, now goes over the TDM slots
  stock leaves empty. The gate now checks the routing words in every period of every link
  test, so this mistake cannot come back unseen. The check fails on v0.19, as it should.
- **The RECORDER page flashing between two pages.** The page asked for a redraw without
  setting the screen's "redraw due" flag, so the UI pushed its other, undrawn buffer every
  other pass. It now asks the way stock pages do, 25 times a second. If the DSP does not
  answer, the RECORD box says **NO DSP / STATUS**. If the DSP does not echo our last
  command, it says **NO LINK / TO DSP**, instead of offering a YES that does nothing.
- **SLICE opened WaveTone's pages** (a table ended one machine short). Fixed: SLICE has its
  own pages.
- **The sample chooser:**
  - The old test sounds and their waveform are gone, so slots no longer all look alike.
  - A slot with nothing loaded says **EMPTY**.
  - A slot still loading says **LOADING**.
  - The arrows no longer close the list and change page while it is up.

**Looks.**
- **PERC is drawn as the Machinedrum's screen**, using its knobs, its 128 pointer
  positions, its fonts and its "clip" ties. The build reads them from your MD OS file, so
  none of the Machinedrum's art is in the repository. Page 2 lists the effects in the MD's
  order.
- **The sample machines' SRC page is drawn to the Digitakt II's own pixel geometry.** The
  geometry was measured from the DT2 OS 1.17 running in the emulator: its knob circles and
  pointers, the LEV fader, the SAMP box, the PLAY icon, the dotted empty place, the label
  font and the cell positions. LOOP's pointer is dotted while PLAY does not loop, as on the
  DT2.

**Test** (after the regression check):
1. **The buzz.** On track 1, WaveTone, play a few notes and listen. Put ONESHOT on track 2
   and play it. Open its RECORDER page (SYN page 3) for a few seconds. Go back to track 1:
   WaveTone must sound exactly as before, with no fizz. Do the same with FM Tone and with
   PERC instead of ONESHOT.
2. **If you have samples on the +Drive.** After power-on, while they load, play WaveTone
   and FM: clean.
3. **RECORDER.** The page must be steady, with no flashing.
   - The RECORD box says **YES RECORD NOW!** if the link works. It says **NO DSP** or
     **NO LINK** if not. Tell me which you see: this is the first test of the
     ColdFire-to-DSP TDM link on hardware.
   - If it says YES: press YES and talk into the input. It shows REC and the seconds.
   - YES again stops it. Play SAMP 124: your recording.
4. **The sample list.** Turn SAMP: slots without a sample say EMPTY. While the list is up,
   the arrows keep it up.
5. **PERC.** Its pages look like the Machinedrum's screen. Turn each knob: the MD-style
   pointer follows. The LEV bar on the left follows the track level.
6. **SLICE.** Choose SLICE: its own pages (TUNE, PLAY, SAMP, SLCE, LEN, LEV), not WaveTone's.
7. **Notes that start late.** Tell me if you still hear a note only after you page or turn
   a knob. I believe the routing fix covers this, but it is not proven.

**Known issues / not yet done.**
- **The ColdFire-to-DSP fast link has never been checked on hardware.** Loading samples and
  the recorder depend on it now. If test 3 says NO LINK, samples and recording will not
  work in this build, but nothing else is affected. The old fallback (the frame's words)
  was what caused the buzz, so it is gone for good.
- **No trig-key audition** in the sample list yet.
- **The arrows do not move the list**: SAMP's encoder does.
- **The DT2's TUNE box** shows its value as plain text. The DT2 draws a small ruler there,
  which is not reproduced yet.
- **Only the DT2's SRC page 1 has been compared pixel by pixel.** The emulator would not
  change page on the DT2 side, so page 2 and the RECORDER are laid out from the manual.

## v0.19 — SLICE

`DN2mod_v0.19_SLICE_OS1.11.syx`
sha256 `5bf20c2e9b2d602dd0fd122be459fa43983bfc7904793834b817d401cfd1cf1e`
Gate: CLEARED TO FLASH, 2026-10-23 (USB size 1,988,690 of 2,097,152). Source: commit `de12fa5`. Docs: `docs/sampler.md` (v0.19 section).

**Adds.**
- **SLICE**, the Digitakt II's sixth sample machine (DT2 OS 1.15 on), listed before GRID as on
  the DT2. Page: TUNE, PLAY, SAMP, SLCE (NOTE, 1..63), LEN (how many slices play on), LEV.
- **Your slices come from your WAVs**: `tools/dn2samples.py send` takes each WAV's cue points
  as its slices (most editors write them), or `--slices grid:16` (equal slices), or
  `--slices onsets` (it finds the hits), or `--slices none`. Up to 64 a sample; each runs to
  the next and loops at its start. They are kept with the sample on the +Drive.
- **SLCE NOTE**: the note picks the slice from C1 up, wrapping after the last, at the
  sample's own pitch, as on the DT2. Page 2 marks the slices on the waveform.
- Everything of v0.18's reader: its interpolation, fades and retriggers.

**Test** (after the regression check; **back up the +Drive first**; update
`tools/dn2samples.py` from the repo):
1. `python tools/dn2samples.py send --slices grid:16 yourloop.wav` (and a WAV with cue
   points with the default). Put SLICE on a track, SAMP on it.
2. SLCE 1, 2, 3...: each plays its slice; LEN 2, 4: plays on into the next slices.
3. SLCE NOTE, keyboard mode: C1, C#1, D1... play slices 1, 2, 3..., all at one pitch.
4. P-lock SLCE on steps: a chopped loop.
5. SYN page 2: the slices marked on the waveform, the played ones framed.
6. Power-cycle: the slices are still there.
7. `--slices onsets` on a drum loop: one slice a hit.

**Known issues.**
- No slice editor on the instrument (the DT2's SLICE menu, EDIT SLICE POINTS, CREATE SLICE
  GRID, linear/random locks): slices are made on the computer. A sample sent without slices
  plays nothing on SLICE.
- The DT2 keeps slices with the sound; here they belong to the sample (every sound using it
  shares them).

## v0.18 — the Digitakt II's own sample engine

`DN2mod_v0.18_DT2-ENGINE_OS1.11.syx`
sha256 `8ef50012e8dd0936c93ec5bb504583ca7c53830647ce45a0883d795abb8e6576`
Gate: CLEARED TO FLASH, 2026-10-23 (USB size 1,987,983 of 2,097,152). Source: commit `cbf5a1a`. Docs: `docs/sampler.md` (v0.18 section).

**Adds.**
- **The DT2's own reader** for ONESHOT, REPITCH, GRID and WERP: its 6-tap, 256-phase
  interpolator at 96 kHz and its 2:1 decimator, with the coefficients read from your DT2
  firmware file at build time. Against a bit-exact model of the DT2's code, ONESHOT agrees
  on 639 samples of 640 (the last within one 16-bit step). Pitched-up samples now alias as
  little as on the DT2.
- **STRETCH is the DT2's**: one read head at the pitch, jumping every 2048 samples so the
  region lasts BARS, with a 128-sample crossfade from the old head.
- **REPITCH** ignores the note and TUNE, as the DT2's does: the region simply lasts BARS.
- **GRID: SLCE 0 is NOTE** — the note picks the slice and the sample plays at its own pitch.
  LEN shows the number of slices.
- **WERP is played as the DT2 plays it**: its segment clock (the DT2's own arithmetic),
  segments starting on block boundaries, each a fresh note fading in while the previous
  one fades out under it.
- **BARS is 1, 2, 4, 8** (default 4) and **SEG is 1/32, 1/16, 1/8** (default 1/16), as on the
  DT2 OS 1.17.
- **Clicks gone**: a note's first block fades in (not ONESHOT from STRT 0, whose attack is
  kept, as on the DT2); a sample's end fades out over a block; a retrigger fades the old
  note out under the new one.
- PERC: the Machinedrum machines take a little less DSP (TRX-CY 30.5k -> 28k a block).

**Test** (after the regression check; **back up the +Drive first**):
1. ONESHOT on one of your samples: plays as before (same level at LEV 100); TUNE far up
   (+24, +36): cleaner than v0.17 (less metallic aliasing).
2. Start a sample mid-way (STRT > 0): no click at the start. FWD to its end: no click.
3. Retrigger a long sample quickly (a 16th-note pattern): no clicks between notes.
4. STRETCH on a drum loop at BARS 1/2/4/8: the loop lasts that many bars, pitch kept;
   TUNE changes pitch without changing the length.
5. REPITCH: the note and TUNE do not change it; BARS does.
6. GRID with SLCE NOTE: notes C1, C#1, D1... play slices 1, 2, 3...; at its own pitch.
7. WERP on a loop: SEG 1/32, 1/16, 1/8; MODE FWD/REV/loops; PLAY REV plays the segments
   backwards; FWD stops after the last segment, FWD LOOP goes round.
8. Your saved sounds with BARS/SEG from v0.13..v0.17 now read the DT2's values (see Known
   issues).

**Known issues.**
- BARS and SEG changed meaning (DT2's ranges): a sound saved on v0.13..v0.17 with a
  sample machine now shows the nearest DT2 choice.
- The reader costs about 9.5k DSP instructions a voice-block (a stock synth's), STRETCH
  about 6.4k; sixteen sample tracks at once plus heavy PERC machines have not been measured.
- The DT2's second declick (a zero-crossing mute it picks by flags not yet decoded) is not
  here; its loop-seam circular taps are as the DT2's code reads (not confirmable in the
  emulator).

## v0.17 — PERC is the Machinedrum

`DN2mod_v0.17_MACHINEDRUM_OS1.11.syx`
sha256 `9803119ed145485d8b5c9e1067eaec366b4bb24a8d08128f85634e5936cb878c`
Gate: CLEARED TO FLASH, 2026-10-23 (USB size 1,982,125 of 2,097,152; DSP 1,037,552 of 1,048,575). Source: commit `f98caa6`. Docs: `docs/md.md`.

**Adds.**
- **PERC's drum machines are the Machinedrum's own** (SPS-1 UW, OS 1.63): all 25 — TRX
  BD B2 SD XT CP RS CB CH OH CY MA CL XC S2, EFM BD SD XT CP RS CB HH CY, GND SN NS IM —
  ported from DSP2's code in your Machinedrum firmware file and checked against the MD's
  own output, case by case (most within 75..120 dB of it, several bit-exact). They run at
  the MD's 44.1 kHz and are resampled to the DN2's 48 kHz.
- **TYPE stays** (page 2, with the track effects AMD..FLTQ): it picks one of the 25 and
  is latched by each note, so p-locking TYPE still plays a different machine on each step.
- Page 1 is the machine's eight parameters under the MD's names; each knob lands on one of
  the MD's 128 positions.
- As on the Machinedrum, **the note does not tune** a machine (PTCH does).

**Test** (after the regression check; **back up the +Drive first**):
1. A PERC track: turn TYPE through all 25; each name shows and each sounds on a trig
   (TRX-MA, the maracas, builds up over a second).
2. P-lock TYPE on a few steps: each step plays its own machine.
3. Page 1: the eight names change with TYPE; turn each knob on a few machines.
4. Page 2: AMD..FLTQ still change the sound.
5. If you have your Machinedrum: same machine, same settings, side by side.
6. **DSP load**: eight PERC tracks of TRX-CY / EFM-CY / TRX-CH ringing together, with the
   rest of a busy pattern: listen for crackles or dropouts and report them.
   (`python tools/dn2sharc_load.py` on a usbprobe build measures it.)
7. The sample machines play your +Drive samples as before (SAMP 1..).

**Known issues.**
- **The four test sounds are gone from the image** (the Machinedrum's tables needed the
  room): SAMP 1..4 are empty until you send samples (`tools/dn2samples.py send`), which
  then load at every power-on as in v0.16.
- **TYPE's machines changed**: a sound saved with a PERC TYPE on v0.11..v0.16 (the Ravel
  set) now plays the MD machine at that TYPE position.
- **DSP cost**: the MD's machines are heavier than the Ravel ones: 3.5k..31k DSP
  instructions a block each (a stock synth is about 8..11k); TRX-CP/CY/MA/S2 and the EFMs
  are the heavy ones. A machine stops costing anything once its sound has died away, but
  many long cymbals at once could overload the DSP (crackles). Not measured on the
  instrument yet.
- For the first 0.7 s after power-on the DSP is still filling the MD's sine and tables
  (a note in that time sounds wrong).
- PERC's level (0.7 of the MD's full scale) is a guess; how it sits beside the DN2's own
  machines is for you to say.

## v0.16 — 96 MB of samples on the +Drive, recordings kept, the sample list

`DN2mod_v0.16_DRIVE_OS1.11.syx`
sha256 `98da318511036ff8acf8349f8f0d83c7052f35270a75774aa8570f0dd665af29`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,961,622 of 2,097,152). Source: commit `b502e6d`. Docs: `docs/sampler.md` (v0.16 section), `docs/link-research.md`.

**Adds.**
- **128 MB sample pool**: 96 MB for your samples (about 18 minutes of 16-bit mono at
  44.1 kHz, up from 5 MB), and four recorder slots of 8 MB (a recording runs up to 66 s).
- **Your samples live on the +Drive** and load at every power-on, as the DT2's do: the
  tool (`tools/dn2samples.py send ...`, update it from the repo) writes them straight to
  the +Drive's private region, then the instrument loads them into the DSP. `--keep` and
  `save` are no longer needed.
- **Recordings are kept**: when the RECORDER stops, the recording is saved to the +Drive by
  itself and SAMP 124..127 still hold it after a power cycle.
- **A fast link** to the DSP (spare TDM slots, about 0.7 MB/s; 20× v0.15's), every 64 KB
  checked by the DSP's own sums and sent again if wrong; if the fast link does not
  check out it falls back to the old one (slow, but always there).
- **Slots play as soon as they are in**: while a big pool loads, each sample becomes
  playable when its frames have arrived.
- **The sample list**: turning SAMP shows five sample names around the chosen one for a
  second, the chosen one framed.
- **The waveform** (SYN page 2) is drawn for every slot, the recorder's included, and for
  samples of any length.

**Test** (after the regression check; **back up the +Drive first**):
1. Power on with nothing sent: the four test sounds play as before (SAMP 1..4).
2. `python tools/dn2samples.py hello`: "sample link 3: room for 100,663,296 bytes".
3. `send` a folder of a few WAVs: the tool shows "to the +Drive" then "into the DSP"
   and says whether the fast link was used. Play them on SAMP 1..
4. Send something big (tens of MB): note the time "into the DSP" took, and whether it said
   "(slow link)".
5. Power-cycle: the samples come back by themselves (a big pool takes a while; small
   samples are playable first).
6. RECORDER: record a few seconds into SAMP 124 (YES, YES). Wait a few seconds, power-cycle:
   SAMP 124 still plays it, and page 2 draws its waveform.
7. Send samples again after recording: the recording is still in SAMP 124.
8. Turn SAMP on SYN page 1 or 2: the list of names appears and goes after a second.
9. `python tools/dn2samples.py status`: `fast_link` 1 is the fast link working; 0 is the
   fallback; `retried` counts chunks sent again.

**Known issues.**
- The fast link and the readback of recordings rely on two TDM details only the hardware
  can confirm (which 24 bits arrive, and that slots 14..15 come back from the DSP).
  If either is wrong the samples still load over the slow link (36 KB/s: 5 MB takes
  about 2.5 minutes; 96 MB would take most of an hour), and recordings are not kept
  (`status` shows `fast_link` 0). Please report what `status` says.
- A full 96 MB pool takes over two minutes to load at power-on even on the fast link.
- Writing to the +Drive happens while you play (64 KB at a time); a project save at the
  same moment waits for it.
- The sample list's timing comes from the audio clock; how it feels is for the
  instrument to say.

## v0.15 — DT2 pages, the RECORDER, track sampling, live loops

`DN2mod_v0.15_RECORDER_OS1.11.syx`
sha256 `ac54c048b93474ed8f0bd12abd07966b8589400710de75150f9c59c535df2edf`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,957,986 of 2,097,152). Source: commit `6032b50`. Docs: `docs/sampler.md` (v0.15 sections), `docs/link-research.md`.

**Adds.**
- **Loops and reverse follow the knobs while they play**: on ONESHOT, STRETCH and REPITCH,
  turning LEN, LOOP, STRT or PLAY changes a held loop at once (before, only the next trig
  did). GRID takes its slice at the trig; WERP its segments. A loop lasts as long as the
  track's AMP envelope, as on the DT2: set AMP's hold/sustain long to hear it loop.
- **One encoder click a choice** on PLAY, WERP's MODE, BARS, SEG, GRID, SLCE/LEN (GRID)
  and the recorder's SRC; ARM, R.STRT, CHAN and DEST step natively.
- **The header names the value**: REV / REV LOOP / FWD LOOP / FWD, 1/4, 1/16, OFF / ON,
  MONO L, TRK3, and SAMP shows the sample's name (KICK, your WAV's name, REC 1..4). No
  more "Prim." / "Harm.".
- **The DT2's SRC pages**: SYN page 1 the knobs (labelled), page 2 the same with the
  waveform, the machine box reading SMP; widgets redrawn after the DT2's (TUNE's value in
  its box, whole knob rings, the dotted square, BARS blocks, the SEG icon).
- **The RECORDER**, SYN page 3 of every sample machine, laid out as the DT2's: SRC (IN,
  MAIN, **TRK1..TRK16**), CHAN (MONO L+R / L / R), the RECORD NOW box (**YES** records,
  YES again stops), THRES, DEST (SAMP 124..127), R.LEN (MAX or steps at the tempo),
  R.STRT (THRES or PLAY: the first note of the pattern), ARM (turn to arm, turn again to
  stop), and an input meter. **Nothing about the recorder is saved with a sound** any
  more.
- CFAD is gone from ONESHOT (the DT2's ONESHOT has an empty place there).

**Test** (after the regression check; **back up the +Drive first**):
1. ONESHOT, SAMP 1 (KICK) or a longer sample of yours: SYN page 1 shows knobs with labels;
   SYN again: the waveform page; SYN again: RECORDER; SYN again: back to page 1.
2. PLAY: each click is one mode (FWD, FWD LOOP, REV LOOP, REV), and the header names it.
3. Set AMP hold/sustain long. PLAY FWD LOOP, hold a note (or a long trig): turn LEN and
   LOOP while it plays: the loop's end and start move at once. Switch PLAY to REV LOOP
   while it plays: it turns round. STRETCH and REPITCH: the same with LEN.
4. SAMP: the header shows KICK, SNARE, HAT, BEAT (or your samples' names).
5. WERP: SEG and BARS and MODE one click a choice; GRID: GRID, SLCE one click each.
6. RECORDER: a synth into the inputs, SRC IN, the meter moves with it. YES: the box shows
   REC and the seconds; YES again: stops. Page 1, SAMP 124: your recording.
7. THRES up to about the middle, ARM (turn H): the box says ARMED; play loud: it records.
   R.STRT PLAY, ARM, then start the pattern: it starts with the pattern.
8. SRC TRK3 (a track playing a pattern), YES, a few bars, YES; SAMP 125 (set DEST first):
   track 3's sound. SRC MAIN: the whole mix.
9. R.LEN 16 (steps): it stops by itself after a bar.
10. SAVE PROJECT with the RECORDER page showing ARM turned on, power-cycle, reload: nothing
    records on its own.

**Known issues.**
- Recordings are still lost at power-off (keeping them on the +Drive is the next build),
  and the waveform is not drawn for SAMP 124..127.
- The TRK sources and the input meter read DSP buffers whose meaning was read from the
  code (`docs/link-research.md`), not yet heard on the instrument: if TRK records the
  wrong track or the wrong level, say which.
- R.STRT PLAY starts at the first note any track plays, not at the PLAY key itself.
- The DN2's header is kept above the RECORDER (the DT2 shows a big "RECORDER" title).
- STEREO recording is not offered (the DN2's tracks are mono).
- The emulator showed the one-click-a-choice turns working, but its encoder is not a
  real one: how a fast spin feels is for the instrument to say.

## v0.14 — sampling, and CFAD

`DN2mod_v0.14_SAMPLING_OS1.11.syx`
sha256 `fd3253d66e16cd72c9ec7dc47e9b149820464a99588333b9cb134fe2beb0ac25`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,955,057 of 2,097,152). Source: commit `eb06398` (gated with the runner of `6a30218`). Docs: `docs/sampler.md` ("Page 2: sampling").

**Adds.**
- **Sampling**, as on the DT2: every sample machine (ONESHOT, WERP, STRETCH, REPITCH,
  GRID) has a **second page** (press **SYN** again): **REC** (the button fills when on),
  **SRC** (IN, IN L, IN R, or MAIN — the DN2's own mix), **THRS** (0 starts at once;
  above it waits for a hit that loud), **RLEN** (MAX = 21.8 s, else the seconds shown),
  **DEST** (the recorder's own slots, **SAMP 124-127**).
- What you record plays at once: set SAMP to its slot (124-127) on any sample track,
  and play it with every machine (GRID slices it, REPITCH fits it to BARS, ...).
- **CFAD on ONESHOT is heard now**: in FWD LOOP it crossfades the loop's end into the
  audio before LOOP, so a loop cut anywhere does not click. Drawn as a knob.
- Your USB samples use SAMP 1-122 (124-127 are the recorder's); the tool refuses more.

**Test** (after the regression check; **back up the +Drive first**, as always):
1. ONESHOT track, SAMP 1: CFAD (C) is a knob. PLAY to FWDL, LEN short, LOOP part-way;
   hold a note: with CFAD 0 the loop clicks, turned up it is smooth.
2. Page 2 (press SYN again): `Sampling (2/2)`, REC SRC THRS on top, RLEN (MAX) and DEST
   (`A 124`) below; the page dots show two pages.
3. A synth into the DN2's inputs. SRC IN, THRS 0, DEST 124: REC on, play a few seconds,
   REC off. Page 1: SAMP 124, play the track: your recording.
4. THRS up (half), REC on, wait (silence: nothing recorded), then play loud: it starts
   with the first hit.
5. SRC MAIN, DEST 125: record a pattern running on other tracks; SAMP 125 plays it.
6. RLEN to 1.0 s: the recording stops by itself after a second.
7. GRID on SAMP 125: slices of what you recorded.
8. `python tools/dn2samples.py send FOLDER` while a recording is in SAMP 124: your
   samples arrive in 1.., and SAMP 124 still plays the recording.
9. Leave REC off before SAVE (REC is saved with the sound; a sound saved with REC on
   starts recording when loaded).

**Known issues.**
- **Recordings are lost at power-off** and are not kept on the +Drive (`--keep` keeps
  only your USB samples): the ColdFire cannot read the DSP's memory back yet.
- The waveform is not drawn for SAMP 124-127 (same reason); the slot box shows the
  number.
- No input-level meter and no armed/recording indicator on page 2 (the DSP's state is
  not visible to the ColdFire); REC's button shows only that REC is on.
- One recorder: with REC on on several sample tracks, the lowest-numbered one records.
- The inputs are read as the DN2's engine converts them (the block the DSP's driver
  writes at `0x268538`); proven in the SHARC runner, not yet heard on the instrument.
  MAIN is the previous block's mix (one block, 0.7 ms, late).
- From v0.13: WERP/STRETCH/REPITCH are our readings of the manual; the widgets are close
  to the DT2's, not pixel-identical; the +Drive region (3 GiB in) and the DSP load with
  many STRETCH tracks are untested on the instrument.

## v0.13 — the Digitakt II's sample machines, and your samples

`DN2mod_v0.13_SAMPLER_OS1.11.syx`
sha256 `ae5637c4b5a04661179d7d36d1619901662958c0fa788f2328a7c0f659c61fdb`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,953,542 of 2,097,152). Source: commit `602ee63`. Docs: `docs/sampler.md`.

**Adds.**
- **Five Digitakt II machines** in MACHINE SEL, a section of their own after PERC,
  RESONATOR and CZ: **ONESHOT, WERP, STRETCH, REPITCH, GRID**.
- **Their pages look like the DT2's SRC page**: TUNE as the bipolar box, PLAY as the
  play icon, the dotted empty box, SAMP as the box with the bank letter and slot on top;
  ONESHOT and GRID show the sample's waveform across the middle with the start, end and
  loop (or slice) markers, STRT LEN LOOP (SLCE LEN GRID) under it and LEV as a pill;
  WERP, STRETCH and REPITCH show knobs, the SEG ring, MODE, BARS and the LEV fader.
- PLAY is REV, REVL, FWDL, FWD as on the DT2; SAMP 0 is OFF; BARS (1/8 to 16 bars)
  follows the DN2's tempo. Every control is an ordinary parameter: p-lockable (sample
  locks), an LFO destination, saved with the sound.
- **Four built-in test sounds** in slots 1-4 until you send your own: KICK, SNARE, HAT,
  BEAT.
- **Your own samples over USB**: `python tools/dn2samples.py send FOLDER --keep`
  (Windows, no packages; close Elektron Transfer first). The WAVs go to slots 1, 2, 3,
  ... with their names, and `--keep` stores them on the +Drive so they load at
  power-on. Up to 128 slots, 5 MB (about 54 s of mono at 48 kHz).
- They are kept in a part of the +Drive the DN2 never uses (above 3 GiB): projects,
  presets and kits are not touched.

**Test** (after the regression check; **back up the +Drive first**, as always):
1. MACHINE SEL: after CZ PHASE a dotted line, then ONESHOT, WERP, STRETCH, REPITCH,
   GRID, a dotted line, MIDI.
2. ONESHOT: the page as on the DT2 (TUNE box, PLAY icon, dotted box, SAMP box with
   `A --`). Turn SAMP (D) to 1-4: KICK, SNARE, HAT, BEAT appear as a waveform. Play.
3. PLAY: REV, REVL, FWDL (the loop marker appears, dotted), FWD. STRT and LEN move the
   markers and shorten the sound; a held note loops in FWDL.
4. GRID on BEAT: GRID (G) to 16, SLCE (E) through the hits, LEN (F) for several.
5. With a pattern running: REPITCH on BEAT, BARS 1, 2, 1/2 (speeds and pitch follow
   the tempo); STRETCH the same, pitch kept; WERP with SEG and MODE.
6. Your samples: `python tools/dn2samples.py hello` answers. Then
   `python tools/dn2samples.py send FOLDER --keep` with a few WAVs; when it says done,
   SAMP shows them and plays them; the waveform is theirs. Play a pattern on other tracks
   while it sends: nothing else should glitch.
7. Power-cycle: after the boot, SAMP shows your samples again and they play (the
   instrument loads them; give it a few seconds). `python tools/dn2samples.py forget`,
   power-cycle: the test sounds are back.
8. A sound with a sample machine: SAVE PROJECT, power-cycle, reload: machine and
   parameters come back.
9. Eight sample tracks at once with a pattern: listen for crackles (STRETCH is the
   heaviest).

**Known issues.**
- CFAD is shown but not heard yet (heard from v0.14).
- WERP, STRETCH and REPITCH are our own readings of the DT2 manual; the DT2's own
  algorithms are not public, so they are close in kind, not identical.
- The widgets are drawn in the DT2's shapes by our own code; they are close, not
  pixel-identical.
- No sampling from the inputs yet; no comb filter.
- The +Drive keep was proven in the emulator (save, clear, reload at boot, checksum
  checked) with the region moved inside the emulator's small device; the real region
  (3 GiB in) is untested until your unit runs it.
- The DSP's load with many STRETCH tracks has not been measured on the instrument.

## v0.12 — PERC pages and effects

`DN2mod_v0.12_PERC-FX_OS1.11.syx`
sha256 `c441b07c26e42a31b77ac3c366724fba7a7c84b5f7fa11ffab410b14a26dbb79`
Gate: CLEARED TO FLASH, 2026-10-21 (USB size 1,915,364 of 2,097,152, 181,788 to spare). Source: commit `0c682bf`. Docs: `docs/perc.md`.

**Adds / fixes.**
- **Labels follow TYPE.** v0.11's labels came from a copy of the sound that does not follow
  the knob, so they showed another machine's names (they only changed on a pattern change).
  Now they are read from TYPE as the page reads it: turn TYPE and every label changes
  with the name in the middle.
- **Page 1 is the machine:** its eight synthesis parameters on A–H, as on the Machinedrum
  (TRX-BD: PTCH DEC RAMP RDEC / STRT NOIS HARM CLIP).
- **Page 2 is TYPE and the Machinedrum's track effects**, ported from your Ravel code:
  AMD AMF EQF on the top row with TYPE; EQG FLTF FLTW FLTQ below. All off at their
  defaults (AMD 0, EQG centre, FLTF 0, FLTW full), so a sound plays as before until you
  turn them.
  - AMD / AMF: amplitude modulation depth and rate (0.1 Hz to 2.3 kHz).
  - EQF / EQG: one EQ band, 40 Hz to 19 kHz, ±18 dB.
  - FLTF / FLTW / FLTQ: a band filter, with a high pass at FLTF (0 is off) and a low pass
    at FLTF + FLTW (full is off), and resonance.
- **No stray ring.** A track that stops being PERC has its voice silenced, so coming back
  to PERC it waits for a note (the brief ring you heard on v0.11).
- Parameter 4 moved from one WaveTone record to another to free a record for FLTQ: on
  PERC sounds saved with v0.11, knob D of page 1 starts from a different value.

**Test** (after the regression check):
1. A PERC track: turn TYPE (page 2, A) slowly through all 24. On page 1 the labels change
   with the machine every step (TRX-BD: PTCH DEC RAMP RDEC STRT NOIS HARM CLIP; TRX-CP:
   CLPY TONE HARD RICH RATE ROOM RSIZ RTUN; GND-NS: DEC and seven `-`).
2. On a few machines, turn each labelled knob while it plays: each does what it says.
3. Page 2: with a pattern running, turn AMD up (tremolo), then AMF (its rate); EQG away
   from centre and sweep EQF; FLTF up (thinner), FLTW down (darker), FLTQ up
   (resonant). Return them to their defaults: the sound is back as it was.
4. The LFO DEST list on a PERC track shows the machine's names and AMD..FLTQ.
5. Switch a ringing PERC track to another machine and back (MACHINE SEL): no ring until
   the next trig.
6. Eight PERC tracks at once, some with the effects on: listen for crackles.
7. SAVE PROJECT, power-cycle, reload: TYPE, the parameters and the effects come back.

**Known:**
- The header line and LFO lists take the names of the machine the PERC page last showed:
  switching to another PERC track shows its names once its SYN page is drawn.
- PERC's code in L2 and the DSP's load with many PERC tracks: as v0.11.
- A sound saved with PERC, loaded on stock firmware, loads as FM Tone.

---

## v0.11 — PERC

`DN2mod_v0.11_PERC_OS1.11.syx`
sha256 `9e44b90562348210be34a8edb549599b35306795a94507e5db6ddf340764f13d`
Gate: CLEARED TO FLASH, 2026-10-20 (USB size 1,914,556 of 2,097,152, 182,596 to spare). Source: commit `5ff5e05`. Docs: `docs/perc.md`.

**Adds.**
- **PERC**, in MACHINE SEL where Waverider was (after Swarmer): your Ravel PERC drum
  machines on the Digitone, one a track. **TYPE** (page 1, A) picks one of 24:
  TRX BD B2 SD XT CP RS CB CH OH CY MA CL XC, EFM BD SD XT CP RS CB HH CY, GND SN NS IM.
  The middle of the page names it (`TRX-BD`, `Bass Drum`).
- **Eight parameters** follow it: B–H on page 1, A on page 2, named per machine as in
  Ravel (TRX-BD: PTCH DEC RAMP RDEC STRT NOIS HARM CLIP; `-` where a machine has fewer).
  The names also show in the header line and the LFO destination lists. Every one is a
  normal parameter: p-locks, LFOs, SAVE/LOAD all work.
- A note keeps the machine TYPE had when it started; the parameters are live.
- **Waverider is removed** (its tables, display and osc 2). A saved Waverider sound
  loads as PERC.
- Inside: PERC's code runs from the DSP's L2 memory (it is too big for the L1 space the
  other machines use), checked bit for bit in the runner against the same program run
  in Python, which is itself checked against your C.

**Test** (after the regression check):
1. A new track: MACHINE SEL → PERC. Page 1 shows TYPE and TRX-BD / Bass Drum; trig it.
   A kick.
2. Turn TYPE through all 24: the name, the description, the dot and the labels follow;
   trig each. All 24 sound (several peak loud: TRX-CB, TRX-MA, GND-IM, as in Ravel).
3. On a few machines turn each labelled knob while a pattern plays; a `-` knob does
   nothing.
4. Note pitch: play the track chromatically from the keys (TRX-RS, EFM-BD): pitch follows.
5. P-lock TYPE on one step and a parameter on another; an LFO on PTCH. Check the LFO
   DEST list shows PERC's names while the PERC track is active and WaveTone's on a
   WaveTone track.
6. **Load:** eight PERC tracks playing at once (a busy beat). Listen for crackles or
   dropouts, and check the stock tracks and FX still sound right.
7. SAVE PROJECT with a PERC track, power-cycle, reload: TYPE and the parameters are
   back.
8. RESONATOR, CZ, PING, SHIFT and GRAN as in v0.10.

**Known:**
- PERC's code in L2 (`0x200c0000`) is memory the stock firmware never touched in the
  emulator (from a fresh boot of the engine, every stock machine); untested on hardware.
  The DSP's load with many PERC tracks is not measured on the instrument (step 6).
- Selecting PERC starts from WaveTone's knob defaults, not each machine's Ravel defaults.
- P-I (the modal machines) is not ported.
- A sound saved with PERC, loaded on stock firmware, loads as FM Tone.

---

## v0.10 — GRAN, osc 2, voice stealing

`DN2mod_v0.10_GRAN_OS1.11.syx`
sha256 `fb18ef71eda483bd0592b145fd6b567b340c0317cc8c092fcf52b88ce8400910`
Gate: CLEARED TO FLASH, 2026-10-20 (USB size 2,080,802 of 2,097,152, 16,350 to spare).
Source: commit `456d4b9`. Docs: `docs/gran.md`, `docs/w3-osc2.md`, `docs/cz.md`
("Voice stealing"), `docs/ping.md`.

**Adds.**
- **Voice stealing on RESONATOR and CZ.** The newest notes sound, up to each machine's
  cap (RESONATOR 4, CZ 6); the oldest is stolen. With the dynamic voice setting, notes no
  longer drop out.
- **TYPE by name** on the FLTR page: PING shows SVF / LADR / VCFQ / LPG; SHIFT's MODE
  shows UP / DOWN / BOTH.
- **Waverider osc 2** on page 2: DETN LEV POS TBL / - MPOS MLEV -. Its LEV starts at 0 (off),
  so saved Waverider sounds play exactly as before.
- **GRAN (GRAINS)**, a granular effect as a new filter type, last in the FLTR list:
  SIZE DENS MODE SPRD on the bottom row, FDBK and MIX on the top, DRIV on page 2. MODE is
  NORM / UP / DOWN / REV. **MIX starts at 0: turn it up to hear it.**
- Inside: PING's and SHIFT's tables moved to the DSP's DDR to make room; they are
  checked bit for bit as before.

**Test** (after the regression check):
1. RESONATOR, then CZ, with the Voice Setup page on dynamic allocation: play fast
   chords and runs of 8+ notes. No dead notes; when the cap is reached the oldest
   note cuts off.
2. The same with a fixed 8 voices: as v0.9.
3. FLTR page on PING: turn TYPE; the cell reads SVF, LADR, VCFQ, LPG. On SHIFT, MODE reads
   UP, DOWN, BOTH. On Multi-Mode the TYPE cell is the stock picture.
4. Waverider: load a saved Waverider sound; it sounds the same as on v0.9. Page 2: turn
   LEV up, then DETN (+7 is a fifth), POS and TBL (the wave and the name follow), then
   MPOS/MLEV with a scanner RATE set on page 1.
5. Any machine, FLTR > GRAINS. MIX up. Try each MODE; SIZE short and long; DENS; SPRD
   away from the centre; FDBK high (it should build and smear but stay bounded).
6. SAVE PROJECT with a GRAN track and a Waverider osc-2 sound; power-cycle; reload:
   both come back.
7. CPU: a few tracks on GRAN at once, and 8 Waverider voices with osc 2 on. Listen for
   crackles.

**Known:**
- GRAN's buffers sit in DSP memory (DDR at `0x81400000`) that nothing has used before on
  the instrument. The same DDR area holds Waverider's tables and RESONATOR/CZ state,
  which play fine on your unit. This exact range is untested on hardware.
- A sound saved with GRAN, loaded on stock firmware, loads as Multi-Mode.
- Osc 2 shares osc 1's scanner (no RATE or MOVE of its own).

---

## v0.9 — CZ release

`DN2mod_v0.9_CZ-release_OS1.11.syx`
sha256 `850bd00abd6f9f84c112e7ac7d6681339bdcb9e2542286337357e9f7c4a51c2d`
Gate: CLEARED TO FLASH, 2026-10-19 (USB size 2,076,863 of 2,097,152). Source: commit
`b782505`. Docs: `docs/cz.md` ("The release").

**Adds.** CZ PHASE's DCW envelope now behaves like the CZ's at key-up: it holds on
the SUS step while the note is held, and on note-off runs on from the step after SUS
to step 8 (a key-up before SUS is reached jumps straight to the release). NOSUS runs
all eight steps as before. Everything else is as v0.8.

**Test** (after v0.8's list):
1. CZ PHASE, SUS2, short R3–R8, L3 high, L4–L8 falling to 0. Hold a note: the tone
   holds after its first sweep. Let go: the second part of the sweep plays as the AMP
   release fades it. (Give the AMP page a release long enough to hear it.)
2. Same with sequencer trigs of different lengths: longer trigs hold longer.
3. Release before the sweep reaches SUS: it jumps to the release part.
4. NOSUS: the whole sweep runs whatever the note length.

**Known:** the note-off is the frame flag that releases the DN2's ADSR amp envelope
(measured in the DSP emulator); that the ColdFire sends it for a CZ track as for
WaveTone is for the instrument to confirm. If it does not, the envelope simply holds
on SUS as in v0.8.

---

## v0.8 — CZ PHASE, sized for the USB upgrade

`DN2mod_v0.8_CZ_OS1.11.syx`
sha256 `5301fb4169f9d5f97c35109a15216c847e69106b56e06dc571ca4f6562fdf897`
Gate: CLEARED TO FLASH, 2026-10-18, including the new USB-size check (2,076,863 of
2,097,152 bytes, 20,289 to spare). Source: commit `89b057b`. Docs: `docs/cz.md`,
`docs/usb-upgrade-limit.md`.

**What it is.** v0.7's contents (CZ PHASE, RESONATOR, SHIFT, PING, Waverider W2) in an
image small enough for the OS's USB upgrade: Waverider's factory set is **9 tables**
(PRIM HARM PWM SYNC VOX FM FOLD ORGN RESO); BITS and PHAS are out. v0.4 to v0.7 never
install over USB (see the top).

**Test:** flash over USB from Transfer as usual; it should finish and reboot like stock.
Then the v0.7 tests below (CZ, 1–11), then v0.6 (RESONATOR), v0.5 (SHIFT) and v0.4
(PING) — none of them has run on hardware yet — and Waverider: TBL now steps through 9
tables (a saved Waverider sound may land on a different table).

**Known:** as v0.7 (CZ's steps after sustain do not run at note-off). The image is 20 KB
under the USB limit; new features must pay for their size.

---

## v0.7 — CZ PHASE (Casio CZ phase-distortion machine) — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.7_CZ_OS1.11.syx`
sha256 `0751bb0dfab83d4e9d227db7d1f9eb1ce2a1967b0e93d3db40e5901cf56c4527`
Gate: CLEARED TO FLASH, 2026-10-18. Source: commit `37fd1f4`. Docs: `docs/cz.md`.

**Adds.** A new machine, **CZ PHASE**, in MACHINE SEL after RESONATOR: the CZ-101 /
CZ-3000's phase distortion. Eight waves (saw, square, pulse, double, saw-pulse, and the
three resonance waves) and their pairs, two lines, ring and noise, and the CZ's 8-step
DCW envelope across pages 2 and 3. The DCA is the DN2's AMP page. Polyphonic up to
**6 voices** (a 7th and 8th are silent, by design). Everything else is as v0.6.

    page 1  WAVE  SEL   DET   OCT   /  MOD   DCW   KF    SUS
    page 2  R1    R2    R3    R4    /  L1    L2    L3    L4
    page 3  R5    R6    R7    R8    /  L5    L6    L7    L8

| control | what it does |
|---|---|
| WAVE | 33 choices: the 8 waves, then pairs (e.g. SW+SQ) that alternate cycle by cycle |
| SEL | lines: 1, 2, 1+1' (line 2 detuned), 1+2' (line 2 detuned, octave, MOD) |
| DET | line 2 detune, ±1 semitone |
| OCT | line 2 octave: 0, +1, −1 |
| MOD | in 1+2': RING, OFF, NOISE |
| DCW | how far the envelope bends the wave (0 = sine) |
| KF | key follow: higher notes duller |
| SUS | which step the envelope holds on (SUS1–SUS8), or NOSUS |
| R1–R8 / L1–L8 | the DCW envelope: rate and level of each step |

Page 1 draws the wave pair as it sounds at the top of the envelope; pages 2 and 3 draw
the envelope, the page's four steps solid, the sustain step marked.

**Test:**
1. FUNC + SYN, scroll to **CZ PHASE** (after RESONATOR), YES.
2. Page 1 reads SAW 1 DET OCT0 / OFF DCW KFOFF SUS1 with a wave in the middle. Turn
   WAVE: the label and the picture change (SAW, SQR… then pairs like SW+SQ).
3. Play: a bright saw that settles. DCW to 0: a pure sine. DCW up: brighter.
4. Pages 2 and 3 (press SYN again): the envelope picture follows R1–R8 / L1–L8. Set
   SUS to NOSUS and short rates: a plucky sweep; long rates: slow filter-like sweeps.
5. SEL 1+1' with DET a little off centre: chorus-like doubling. SEL 1+2', OCT +1,
   MOD RING: bell tones; MOD NOISE: a gritty, noisy line.
6. WAVE on RS1 / RS2 / RS3 with the envelope sweeping: the CZ resonance sweep.
7. Chords up to 6 notes (VOICE SETUP 6 or fewer): all sound.
8. **Load test:** 6 CZ voices plus 4 RESONATOR voices plus a busy pattern: any crackle?
   (Not measured on hardware; about 7,700 cycles a CZ voice a block, by instruction count.)
9. Save a CZ sound, reload: still CZ PHASE. Save the project, power-cycle, reload.
10. WaveTone's page 3 still shows its own envelope widgets (this build re-routes page 3
    for CZ tracks only).
11. RESONATOR (moved its tables and scratch to make room), PING, SHIFT and Waverider
    briefly, as in v0.6.

**Known:** the steps after the sustain step do not run at note-off yet (the envelope
holds on SUS until the next note; the frame's note-off is not located). The AMP
envelope still ends the note. One wave choice and one DCW envelope for both lines
(the DN2 sound has 25 machine parameters). A CZ sound loads as FM Tone on stock firmware.

---

## v0.6 — RESONATOR (Rings-style machine) — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.6_RESONATOR_OS1.11.syx`
sha256 `920ee105803cd1114770b38bdf94b8de325539c73b31371144795d495f5dd847`
Gate: CLEARED TO FLASH, 2026-10-18. Source: commit `8e6854e`. Docs: `docs/rings.md`.

**Adds.** A new machine, **RESONATOR**, in MACHINE SEL after WAVERIDER. Each note hits a
bank of 24 resonant modes with a mallet or a noise burst: strings, marimba bars, bells,
plates, glass and drums. Polyphonic up to **4 voices** (set the track's VOICE SETUP to
4 or fewer; a 5th and 6th voice are silent, by design, to keep the DSP load bounded).

    TUNE  LEV   STRC  BRIT  /  DAMP  POS   EXCT  HIT

| control | what it does |
|---|---|
| TUNE | pitch, ±5 octaves |
| LEV | level (100 = unity) |
| STRC | structure: left = harmonic (a string), middle = a bar (marimba), right = a plate / bell |
| BRIT | brightness: the mallet's hardness, and how fast the high modes die |
| DAMP | decay, 0.1 s to 12 s |
| POS | where it is hit: the middle mutes every other mode (hollow), the edge keeps them all |
| EXCT | the exciter: left = mallet, right = a noise burst, between = both |
| HIT | how hard it is hit |

The page draws the modes as lines: STRC moves their spacing, POS their heights.

**Test:**
1. FUNC + SYN, scroll to **RESONATOR** (after WAVERIDER), YES. VOICE SETUP: 4 voices.
2. The page reads TUNE LEV STRC BRIT / DAMP POS EXCT HIT, with the lines in the middle.
3. Play notes: a long, bright string (the defaults). Sweep STRC left to right: string →
   marimba → bell. Then BRIT and DAMP short for drums; POS for hollow vs full.
4. EXCT to the right with a low note: a noisy, struck plate.
5. Chords of 3–4 notes: all sound. A 5-note chord with VOICE SETUP above 4: the extra
   notes are silent (expected).
6. **Load test:** 4 voices ringing with long DAMP plus a busy pattern on other tracks:
   any crackle or dropouts? (Not measured on hardware yet; estimated ~8 % of the DSP.)
7. RESONATOR through PING and SHIFT (FLTR page): works on it like any machine.
8. LFO page on a RESONATOR track: DEST shows Structure, Brightness, Damping…; a
   WaveTone or Waverider track: their own names.
9. Save a RESONATOR sound, reload: still RESONATOR. Save the project, power-cycle,
   reload.
10. The v0.5 / v0.4 tests briefly (PING, SHIFT, Waverider as before).

**Known:** MODAL only (the plucked STRING model in the first demo is not in the machine:
a delay line a voice does not fit the DSP memory; STRC at the left is the string-like
setting). Low notes with the bright default can push into a soft limiter (LEV down).
A RESONATOR sound loads as FM Tone on stock firmware.

---

## v0.5 — SHIFT (frequency shifter) — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.5_SHIFT_OS1.11.syx`
sha256 `1ff987df0d6dd8ef3ed718682bf9e899b1f9af2fe8b71995c29d66a63e315e98`
Gate: CLEARED TO FLASH, 2026-10-18. Source: commit `be8d0ad`. Docs: `docs/shft.md`.

**Adds.** An 8th filter type, **SHIFT**, last in the FLTR tab (after PING), on every
machine. A frequency shifter: every partial moves by the same number of Hz, so sounds
go metallic and bell-like, small shifts shimmer, and feedback makes the endless
"barber-pole" climb. It takes the track's filter slot (no low-pass on a SHIFT track;
BASE / WDTH on page 2 still work).

    FLTR page 1   ATK  DEC  MIX  -    /  SHFT FDBK MODE ENV
    FLTR page 2   DRIV  .    .   KEY.T / BASE WDTH BW.RT RSET

| control | what it does |
|---|---|
| SHFT | the shift: centre (64) is none, left shifts down, right up, to ±2.5 kHz; fine near the centre |
| FDBK | feedback through the shifter (the barber-pole), soft-limited |
| MODE | thirds: UP (shifts the way SHFT points), DOWN (the opposite way), BOTH (both sidebands: ring-mod bells) |
| ENV | the envelope's push on the shift (centre is none) |
| ATK / DEC | the envelope, restarted by each note |
| MIX | dry → wet |
| DRIV | level into the shifter |
| KEY.T | the shift follows the note |

Also: the DSP code's empty blocks now load as "fill" blocks, as Elektron's own code
does; the DSP memory after boot is identical, with 10.6 KB more room in the upload.

**Test:**
1. A WaveTone or FM track: FUNC + SYN, RIGHT to FLTR, scroll to **SHIFT** (last), YES.
2. The FLTR page reads ATK DEC MIX - / SHFT FDBK MODE ENV.
3. MIX to the top. SHFT a little right of centre on a held chord: slow shimmer. Further:
   metallic. Left of centre: shifts down.
4. MODE through its thirds (UP, DOWN, BOTH) with SHFT ~ 3/4 right.
5. FDBK up with SHFT just off centre on a long note: the endless climb (or fall). Turn
   FDBK fully up: it must stay controlled, never blast.
6. ENV up, short DEC, on hits: a zap on each note.
7. PING and SHIFT on different tracks at once; then switch a SHIFT track back to
   Multi-Mode: stock labels return and it sounds as before.
8. Save a sound with SHIFT, load it back: still SHIFT. Save the project, power-cycle,
   reload.
9. The v0.4 PING tests, briefly.

**Known:** SHFT's readout is Multi-Mode's cutoff number, not Hz (64 = no shift); MODE's
icon is Multi-Mode's LP/BP/HP picture; REL on page 1 does nothing (`-`).

---

## v0.4 — PING filter — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.4_PING-filter_OS1.11.syx`
sha256 `86fc590931251776b14b7bad075336177f5b20aca60fc6c8bf557ec892d427dc`
Gate: CLEARED TO FLASH, 2026-10-13. Source: commit `43e4d58`. Docs: `docs/ping.md`.

**Adds.** A 7th filter type, **PING**, last in the FLTR tab of MACHINE SEL
(FUNC + SYN, then RIGHT to the FLTR tab). It works on every machine, the stock ones
included. A resonant filter with its own fast envelope and a built-in strike, made for
liquid, hard-hitting pings and percussion.

    FLTR page 1   ATK  DEC  CURV STRK  /  FREQ RING TYPE ENV
    FLTR page 2   DRIV  .    .   KEY.T /  BASE WDTH BW.RT RSET

| control | what it does |
|---|---|
| TYPE | the core, in four ranges low to high: **SVF** (clean, glassy), **LADR** (Roland-style, thick), **VCFQ** (Serge-style ping), **LPG** (vactrol low-pass gate, the bongo) |
| FREQ | the cutoff / the ring's pitch |
| RING | how long it rings (the resonance) |
| ATK / DEC | PING's own envelope, from 0.1 ms |
| CURV | the envelope's curve: log ← lin → exp |
| STRK | the level of the built-in strike (the "hit") |
| ENV | the envelope's depth on the cutoff |
| DRIV | the drive into the filter |
| KEY.T | how far the cutoff follows the note |

**Test:**
1. A WaveTone or FM track: FUNC + SYN, RIGHT to FLTR, scroll to **PING**, YES.
2. The FLTR page shows ATK DEC CURV STRK / FREQ RING TYPE ENV, with the curve under
   FREQ and RING moving as you turn them.
3. TYPE at the top (LPG), FREQ mid, RING up, DEC short: a round, bongo-like ping.
   Then each TYPE range (SVF, LADR, VCFQ) by ear. **Note how each sounds**, and any
   setting that is too quiet, too loud, harsh or blown out.
4. Turn STRK up and down; CURV left and right with a long DEC.
5. Choose another filter (e.g. Multi-Mode): the stock labels (SUS, REL, RESO) come back
   and it sounds as before.
6. Save a sound with PING, load it back: still PING. Save the project, power-cycle,
   reload.
7. **Load test:** PING on 4–8 tracks playing at once: any crackle or dropouts?
8. The v0.3 tests, briefly (Waverider still as before).

**Known:** TYPE's icon is Multi-Mode's LP/BP/HP picture, not the four PING names; the
curve drawn is Multi-Mode's shape. A sound saved with PING loads as Multi-Mode on stock
firmware.

---

## v0.3 — Waverider W2

`DN2mod_v0.3_Waverider-W2_OS1.11.syx`
sha256 `8cd7236c2e84b8e931174b91c99f16393cd899b6bcd602ea6de044ffee194da0`
Gate: CLEARED TO FLASH, 2026-10-11. Source: commit `3514819`. Docs: `docs/w2-scanner.md`.

**Adds.** Every control on Waverider's page 1, and a scanner (a per-voice modulator):

    TUNE   LEV    POS    TBL   /   RATE   MPOS   MLEV   MOVE

LEV (level), RATE (scanner speed), MPOS (sweep depth on POS, ±), MLEV (depth on level,
±), MOVE (shape: TRI SAW RAMP SQR RND S&H ONE ENV). Waverider's names in the LFO and
modulation destination lists. Defaults change nothing in a v0.2 sound.

**Test:**
1. A v0.2 sound sounds exactly as before.
2. Page 1 shows all eight: LEV, RATE, MPOS, MLEV, MOVE (with the shape's name).
3. MPOS up, RATE ~60, MOVE `TRI`: the timbre sweeps the table. Try `ONE`, `RND`, `S&H`.
4. MLEV up with MOVE `ENV`: each note decays. MLEV down with `SQR`: a gate.
5. LFO page on a Waverider track: DEST lists *Wave Table*, *Wave Position*,
   *Scan Rate*… A WaveTone track: WaveTone's names, unchanged.

---

## v0.2 — Waverider W5 (superseded, no download)

Built before the ship gate existed, so it is not offered; v0.3 and later contain all
of it. 11 factory tables (`PRIM HARM PWM SYNC VOX FM FOLD ORGN RESO BITS PHAS`), TBL
shows the table's name, POS glides (~21 ms) instead of stepping, the wave display
follows what you hear. Docs: `docs/w5-tables.md`.

## v0.1 — Waverider (superseded, no download)

Built before the ship gate existed. WAVERIDER in MACHINE SEL: a wavetable machine,
polyphonic (set VOICE SETUP above 1), two tables, TUNE / POS / TBL. Flashed and
working on the owner's unit, 2026-10-11.

---

**About where the files live.** The repository's `.gitignore` says it holds no
Elektron firmware, original or modified: a modified build is Elektron's OS with our
changes in it. That keeps `main` safe to make public one day. The builds branch is
private with the repository; **delete the `builds` branch before the repository is
ever made public.**

# v0.61: microtuning

Owner, 2026-11-17: microtuning after FM+, "if at all possible". The spec, with its screens, is
in the project as `claude/microtuning-spec.md`. This file says what was built and how.

## What it does

- **A tuning** has 12 offsets in tenths of a cent, one for each semitone above its ROOT. It repeats
  every octave.
- **One tuning per project.** Each track is either TUNED or not; there are 16 switches.
- **Factory tunings** (`dnfw.waverider.tunings`, read only): 12-TET, Just Major, Just Minor,
  Pythagorean, Meantone 1/4, Werckmeister III, Kirnberger III, Vallotti, Arabic Rast, Poole Rod12
  and Poole12 Min.
- **USER 1..8**: your own tunings, edited on the EDIT page.
- **Everything played on a tuned track is retuned**, voice by voice, each by its own note: the
  keyboard, trigs, chords, arp and slides. MIDI tracks and MIDI out stay 12-TET.
- **KB SETUP's SCALE, ROOT and MODE are stock's.** The tuning changes the pitch of the keys, not
  which keys play.

## The screens

**KB SETUP** (FUNC + KEYBOARD): its empty H slot becomes **TUNE**.
- Turning H tunes the active track. The value is OFF, or one of the tunings (12-TET is OFF's
  place); choosing one makes it the project's tuning.
- Pushing H opens TUNING.

**TUNING** (H pushed):

| Control | What it does |
|---|---|
| A TUNE | the project's tuning |
| B ROOT | C..B |
| C TRK | the active track on or off |
| D ALL | every track on (turn right) or off (turn left) |

- The 16 boxes show which tracks are tuned; the active one is marked.
- YES on a USER tuning opens EDIT. NO closes TUNING.
- The [TRIG] keys and the keyboard play through, so you can tune by ear.

**EDIT** (YES on a USER tuning):

| Control | What it does |
|---|---|
| A NOTE | which of the 12 notes above ROOT (LEFT and RIGHT also step it) |
| B CENT | that note's offset, a whole cent a step |
| C .1CT | that note's offset, a tenth of a cent a step |
| D FROM | a tuning to copy |

- FUNC + YES copies FROM into this slot. Copy 12-TET to reset the slot.
- NO goes back to TUNING.

## How

`csrc/sampler/tune.c`:

**Retuning**
- `tn_retune` runs in the audio interrupt (`ms_frame`, after the frame is built). A voice whose
  track is tuned gets its note's offset added to its NOTE word (`note << 8 | fine`, with the fine
  part in 1/256 semitone). The offset is picked by the note's semitone above ROOT. This is
  v0.58's method, but it never touches stock's scale tables, so v0.58's chord MODE crash cannot
  come back.
- The interrupt reads one of two snapshots (offsets in 1/256 semitone, ROOT, switches). The UI
  writes the other snapshot and then flips, so a frame never sees half a change.

**KB SETUP**
- KB SETUP counts as up when the top of the screen's view list (screen + 28, the node's view at
  + 8) has KeyboardSetup's vtable, 0x401D5650. That view is named "KeyboardSetup" at + 0x24.
- Only then do H's turn and push belong to TUNE. Everywhere else they are stock's.
- `tn_kb_draw` draws over the dotted box stock leaves in that slot.

**Keys and drawing**
- `tn_pop` runs in `smp_ui_pop`, ahead of SLICE's menus, and not while the RECORDER, the sample
  list or the browser is up.
- `tn_draw` and `tn_kb_draw` run in `wr_screen`, after stock's page is drawn.

**The record**
- Location: one sector per copy at 0x6E0400 + 2p + c, for project p (0..127) and copy c. The
  copies are written in turn, and the newer sequence wins. The region runs 0x6E0400..0x6E04FF,
  between the per-project lists (to 0x6E02FF) and the library's extension (0x6F0000).
- Contents: 'DN2T', version 1, the project, the sequence, the tuning, ROOT, the switches, the 8
  USER slots (12 signed shorts each) and a check.
- A record is refused, and 12-TET used, if its check, its project number or any value is wrong.
- When it is written: two seconds after the last change, and before a LOAD or NEW switches away.
  A project with nothing to keep (12-TET, nothing tuned, the USER slots empty) writes nothing,
  unless it is replacing an older record. NEW replaces the slot's old record with 12-TET.
- When it is read: on a LOAD, and at power-on for the active project.
- Nothing is written while ERASE MOD DATA's lock is set.

## Gate

- `unit` (`test/test_tunings.py`): each factory tuning against its definition, the fine-unit
  arithmetic and the C header.
- `tune` (ColdFire):
  - `tn_retune` on 16 voices: POOLE ROD12 at ROOT D moves each tuned voice by its offset.
    Track 4 (off), a voice with no track, and 12-TET on every track move nothing; these are the
    negative controls.
  - On the main page, H's turn and push are stock's (negative control).
  - KB SETUP's TUNE, the TUNING page's A/B/D, YES on a factory tuning and on USER 8, EDIT's B,
    FUNC + YES, and NO, NO.
  - Every screen is drawn, and each one differs.
- `tunerec` (ColdFire, `scripts/emu_tune.py`, the +Drive played by Python):
  - power-on;
  - a change is written after two seconds, into its own project's sectors;
  - LOAD, NEW and a power cycle;
  - a corrupted copy, both copies corrupted, and another project's record refused;
  - ERASE's lock;
  - every write stays in the region.

## Limits

- 12 notes per octave, octave-repeating.
- One tuning per project.
- USER slots are named USER 1..8; they cannot be renamed.
- ERASE MOD DATA does not yet clear the tunings' region: a project's tuning survives an erase.

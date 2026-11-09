# After v0.45: the owner's list (2026-11-08)

Owner, 2026-11-08 03:24: "solve the bounce issue and get FASCIA out ... keep these things in
mind for after so we remember to cover them once finished with this". Order: BOUNCE freeze fixed
(and its gate check), FASCIA released, then these.

## The order (owner's Discord post, 2026-11-08)
1. v0.45: BOUNCE (fixed) and FASCIA in one release.
2. Then: recorded samples save to the +Drive (1), the FILE NAME screen (1b), then larger sample
   pools (the RAM banks, on hold since v0.45) and other sample management.
3. Capicola stretch (heavylight's) goes in v0.46 (owner, 2026-11-08), with that release, especially if BOUNCE works on
   hardware. His source never goes in a public repo.
   **How (owner, 2026-11-08 05:24): Capicola is BOUNCE's stretch.** If BOUNCE proves itself on v0.45,
   a BOUNCE track plays its take through Capicola by default. Today a BOUNCE voice is STRETCH on
   its buffer half (grains of 43 ms). The existing stretch stays available as a switch: a choice
   control on BOUNCE's page (4 detents an option), e.g. ALGO: CAPI / GRAIN, and any others it
   offers. To check first:
   - Capicola's DSP cost per voice against STRETCH's;
   - its latency against the take's start on the step;
   - how it fits the take to its steps at the tempo (BOUNCE's rule);
   - what heavylight's licence allows us to ship.

## v0.46 plan (owner, 2026-11-08 12:54)
1. **Finish FASCIA's lightening and speed-up first** (branch `fascia-opt-wip`; the agent's next
   step was to re-apply only the exact cuts).
2. **Then measure what the rest needs:** Capicola in BOUNCE only (not every DT2 machine yet: less
   room, less risk), the FILE NAME screen, and recordings to the +Drive. Implement what fits. If
   room still runs short, the owner decides FASCIA against Capicola.
3. **Recordings to the +Drive must happen, but safely:** no restructuring that can leave things
   broken. Before any code:
   - a written design;
   - every power-cut point;
   - how old projects keep working;
   - what can go wrong;
   - its gate steps.

   The owner reviews it first.

## v0.46: the owner's decisions for working unattended (2026-11-08 14:01)
1. **Publish:** once v0.46's full gate prints CLEARED TO FLASH, publish it unattended with the
   usual five steps (FIRMWARE.md, the builds branch, the patcher with its deploy confirmed,
   releases/v0.46.md).
2. **Recordings to the +Drive:** build them without waiting for a design review, keeping the old
   path as the fallback:
   - the save writes into +DRIVE > RECORDED, with the entry written last;
   - the slot links to that file;
   - +Drive full or missing: it saves the old way (the pool's recordings area);
   - old RECnnn recordings are untouched;
   - power-cut points tested in the gate.
3. **FASCIA:** 1 to 4 voices is fine ("1 voice is fine since it's a percussive voice"). Its size
   must come down whatever happens, so there is room for Capicola and the +Drive work. Lighten
   and speed it up, then include it only if it fits after those.
4. **Space:** if FASCIA and Capicola don't both fit, Capicola goes in and FASCIA waits.
5. **Capicola:** already cleared by heavylight for the mod's firmware. It goes in BOUNCE only. His
   source never goes in a public repo.
6. **FILE NAME:**
   - names as long as the DT2's (read the stock naming code for its limit; the library stores
     up to 35);
   - the counter REC0000 (4 digits).
7. **Cut rule:** a feature that can't be made safe, or doesn't fit, is dropped from v0.46 and kept on
   a branch. The rest ships. The release note and FIRMWARE.md say what was dropped and why.

## 1. Recordings into the +Drive library's RECORDED folder, automatically
- **Today:** a recording (manual RECORD NOW, or a BOUNCE take saved with FUNC + YES) is saved
  into the project's pool, named RECnnn. The pool is saved on the +Drive with the project, and
  the PROJECT RAM browser groups those samples as recorded.
- **Nothing on the unit writes a recording into the library.** The library's RECORDED folder
  (`lib.c`: folder 1, made with the library) only fills from the host tool. `docs/rectrig.md`'s
  "and to the +Drive (RECORDED)" means the project's pool, not the library folder.
- **Wanted:** each saved recording is also copied into +DRIVE > RECORDED automatically, so it
  outlives the project. Users delete it there later if they want.
- **What it takes:** a pool-slot → library write path. The library already has the
  pieces from the host send:
  - first-fit extents (`lib_room`);
  - the index entry written last, so a cut-off write leaves no entry (`index_sector_write`);
  - adler-32 checks.

  It runs in the background after the recording's own save, as the loader does: idle-only,
  one chunk a pass, a power cut leaves either nothing or a whole entry. The name is RECnnn,
  or FILE NAME's.
- **Owner, 2026-11-08 03:33: match the DT2's order instead.** On the DT2 the save *is* the +Drive
  write: TRIM in the buffer, YES, name, YES, and the trimmed file lands in RECORDED. A pool slot
  only links to it. So:
  1. **FUNC + YES / the recorder's save:** TRIM, then FILE NAME, then the write into the library's
     RECORDED folder, entry last. That write is the one commit point.
  2. **The pool slot becomes a link to that library sample.** This is the same kind of slot
     LOAD TO PROJECT makes: a LIBID, `smp_lib_slot_of`. The frames already in DDR stay as they
     are, so nothing reloads.
  3. **The recordings' area room is freed** once the library entry is written. There is no
     pool-only RECnnn copy and no background job.
  4. **Library full or no +Drive:** refuse, and say why. The take stays where it is (buffer or
     recordings' area) as today. Nothing is deleted. (The DT2's own behaviour here is
     unconfirmed.)
  5. **Old projects:** pool-only RECnnn recordings keep working as they are. Each one could get a
     SAVE TO +DRIVE action (in PROJECT RAM's SAMPLE ACTION) that writes it to RECORDED and
     relinks the slot. There is no forced migration.
  6. **Still to check against the DT2's manual or a unit:** the default name the save screen
     offers.

## 1b. The FILE NAME screen: the DT2's length and behaviour (owner, 2026-11-08 04:00)
- **The DT2's screen (owner's photo):** FILE NAME, the name REC0000 (a 4-digit counter), a long
  field that scrolls (`>>`), and the help:
  - FUNC+ARROW: EDIT
  - FUNC+NO: DELETE
  - FUNC+YES: INSERT
  - SETTINGS: RANDOM
  - U/D: CHAR +/-
  - L/R: MOVE CURSOR
  - YES: SAVE
  - NO: ABORT
- **Ours (v0.44, on the unit):**
  - the name is REC049 (3 digits), 7 characters at most;
  - U/D CHAR, L/R MOVE, FUNC+NO DELETE, FUNC+YES INSERT, YES SAVE, NO ABORT;
  - no FUNC+ARROW EDIT, no SETTINGS: RANDOM.
- **Wanted:**
  - the DT2's character limit (the library's names hold 35, `lib.c`);
  - REC0000's 4 digits;
  - the field scrolling as the DT2's does;
  - FUNC+ARROW EDIT and SETTINGS RANDOM;
  - the feel of the stock keys.
- **Start from the Digitone II's own naming code** (its project and preset NAME screen, in the
  MAIN OS): reuse it if it can be called with our buffer, or copy its behaviour exactly.
  Find its entry, its buffer length and its key handling in the disassembly first.

## 2. A sample-lock trig mode for the DT2 machines (feasibility first; only if it can't hurt stability)
- **The idea:** FUNC + UP/DOWN opens TRIG MODE. A new mode (or the stock menu's SLICES entry)
  on a sample-machine track makes each chromatic trig key play the next loaded sample of the
  project's pool, the way SLICE's slices are played from the keys. Key k is the k-th loaded slot
  from the track's SAMP, live and recorded into the pattern as SAMP locks.
- **What exists:**
  - v0.23's SLICES on the trig keys (`docs/sampler.md`, "SLICES on the trig keys"):
    `slc_keynotes` answers KeyboardView's note query at `0x40058be8` with one note per key;
    stock does the rest (held keys, MIDI out, live recording).
  - The stock TRIG MODE menu has a SLICES entry, which the DN2 build disables (value 1024,
    refused by its setter). **It was left alone on purpose:** its setter and what the
    sequencer does with that mode were never read.
- **The question to answer first:**
  - can the menu entry be enabled by its setter alone, and what does the stock sequencer do in
    that mode (on the DT2 it is a real mode with its own recording);
  - or should we keep KEYBOARD mode and add the mapping on sample tracks behind a setting.

  Risk lives in the setter and the sequencer's mode handling. The key → note mapping is the
  proven part.
- **Gate:** keys → SAMP per key, recording, MIDI out, and every other track and mode stock.

## 3. Bug: SAMP on D shows only the slot number, not the name (intermittent, short-lived)
- **Owner's report:**
  1. He made a 16-step pattern, p-locking a different PROJECT RAM sample on each trig.
  2. He copied and pasted the first trig's lock, then turned D further up the slot list for
     each trig.
  3. For a while, turning D showed only the slot number, not the sample's name (the pool list).
  4. After a short while it showed the full list again.
- **Suspects:**
  - the sample list's names drawn from a cache that refreshes on a timer or idle pass
    (`smp_overlay_dirty`, the names' RAM copy while a save or load runs);
  - the overlay deciding the value is a lock on a slot whose name isn't known yet;
  - the copy/paste of locks leaving the overlay's "seen" state stale.
- **Next:** reproduce in the emulator with locks pasted on 16 steps and D turned per step, with
  and without a pool save running (the directory's dir_due save after edits).

## 4. The gate's blind spots that v0.44's freeze showed (found 2026-11-08)
The freeze was `wr_label` reading from address 0xEE. That is fixed in v0.45, and the gate step
`machines` catches it on v0.44. What let it through:
- **The emulator maps low memory as zeros**, so a wild read below 0x40000000 reads 0 and
  passes. Make the `machines` step's read trap shared code (`emulib`) and turn it on in every
  emulator step.
- **The steps on `ui800M-v014` drive v0.14's MACHINE SEL list**, which is built at boot:
  - `colsw` ("nine DOWNs to GRID") and `keepsamp` ("DOWN, YES") move through stale rows;
  - `fascia` and `mnmdefaults` call the commit directly.

  Move them onto a boot-built snapshot of the build under test, as `machines` does.
- **The UI fuzz only puts the six DT2 sample types under its pages:** add BOUNCE, FASCIA and the
  Monomachine machines.
- **Snapshots don't keep our code chunks' RAM pages** (every harness re-copies them), so any
  boot-time state in the chunks is reset.
- **`emu_boot_check` from reset never draws a page**, so it can't catch boot-draw bugs.
- **Minor:** `wr_count` gives BOUNCE 1 SYN page where the other sample machines have 2.

### Priority and fallbacks (owner, 2026-11-08 14:06)
- **Order:** +Drive recordings first, then Capicola, then FASCIA. Try to get all three in. FASCIA may
  drop to 1 voice for now.
- **Naming:** the DT2's length and REC0000 are preferences, not requirements. If they don't work
  out, or 16 characters with our current naming is easier, fall back to that. Aim for: as smooth
  and stable as possible, intuitive, close to the original.
- **FASCIA's bar (owner, 2026-11-08 14:08):** if it still causes serious issues, or even hints at a
  crash at 1 voice, it waits until after v0.46. Keep working on making it stable.
- **No crash may ship.** None of our changes may be able to freeze or crash the unit the way v0.44
  did. For v0.46 that means:
  - the `machines` step;
  - wild-read trapping in every emulator step that draws pages: the shared read trap (blind
    spot 4);
  - boot-built snapshots for anything that drives MACHINE SEL or the new screens;
  - power-cut and full-+Drive tests for the recordings path;
  - a guard-respecting stress test for Capicola's and FASCIA's DSP code.

  A feature without these checks doesn't ship.
- **Capicola moves to v0.47 (owner, 2026-11-08 14:29).** Port: kf.c's algorithm rewritten in our DSP DSL and
  held bit-exact to heavylight's host build. Capicola is AGPL-3.0: confirm with heavylight that his
  permission covers shipping it in the firmware. v0.46 is recordings to the +Drive plus the longer
  naming screen; FASCIA goes in if it meets its bar.
- **Capicola: on hold until further notice (owner, 2026-11-08 14:38).** heavylight's wish: anything
  built with the code from his DT2 mod stays private until his own closed beta, so no Capicola or
  flex-style machine in any release of ours, and none built either. His source stays where it is,
  untouched.

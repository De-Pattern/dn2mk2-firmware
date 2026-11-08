# After v0.45: the owner's list (2026-11-08)

Owner, 2026-11-08 03:24: "solve the bounce issue and get FASCIA out ... keep these things in
mind for after so we remember to cover them once finished with this". Order: BOUNCE freeze fixed
(and its gate check), FASCIA released, then these.

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

# KEYBOARD HOLD (v0.63, planned)

Owner, 2026-11-19: a note hold for the keyboard; he remembered it as PTN + KEYBOARD, which does
nothing on stock 1.11 (checked on his unit). Not built before: no trace in either repo.

## What it does

- **PTN + KEYBOARD** (codes 23 + 18, digikit's key table) toggles HOLD. The PTN view's key
  handler is already ours (`csrc/jump/jump.c` `jmp_key`, Direct Jump's PTN + YES/NO), so the
  combination is caught there: a fresh KEYBOARD press with PTN held and FUNC not held. The PTN
  view's message line says KB HOLD ON / KB HOLD OFF.
- With HOLD on, a [TRIG] key played as a keyboard note keeps sounding when it is let go.
- The next key pressed while no [TRIG] key is down releases every held note first, then plays
  (a new note or chord replaces the old). Keys added while others are still down join the chord.
- HOLD off releases every held note.
- The sequencer's trigs are untouched; only the keys played by hand. Chords, the arpeggiator
  (its notes are the held keys: HOLD is its latch) and microtuning work as for held keys.

## How (UI level only, no DSP change)

- Every UI item passes `rec.c smp_ui_pop` before any view sees it. A [TRIG] key's item: codes
  25..40, bit 0 of the flags on the press, bit 4 on the release.
- Which presses were keyboard notes: stock's KeyboardView asks for a key's notes through the
  site `slc_keynotes` already owns (`slice.c`, coldfire.py KEYNOTES_SITE). A key it asks for is
  marked as a keyboard key until its release; a key it never asks for (a step, a mute, a menu)
  is left alone, so no keyboard-mode flag has to be found.
- HOLD on, the release of a marked key: its item is kept (copied) and dropped (IT_DROP).
- HOLD on, a fresh press of a [TRIG] key with no [TRIG] key down and kept releases waiting: the
  kept releases go out first, one a call of `smp_ui_pop` from our own small queue, then the
  press itself (also from the queue). The UI loop calls the receive until it is empty, so the
  order is release..., press within the same pass. **To check in the emulator first**: that the
  loop does call again at once, and that an item it is given from our buffer (not its ring) is
  handled the same.
- HOLD off: every kept release goes out the same way.

## Gate (planned): `kbhold`, an emulator step

KEYBOARD mode on a synth track, HOLD on: TRIG 1 pressed and let go: its note's voice still on in
the frame (CTL_FRAME); TRIG 5 then: 1 released, 5 on; TRIG 5 + 8 together, let go: both on;
HOLD off: none on. Negative control: HOLD off, TRIG 1 let go: off. A step trig in GRID RECORDING
with HOLD on: stock's (no kept release).

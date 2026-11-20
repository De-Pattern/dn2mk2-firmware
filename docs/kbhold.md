# KEYBOARD HOLD (v0.64)

Owner, 2026-11-19: a note hold for the keyboard; he remembered it as PTN + KEYBOARD, which does
nothing on stock 1.11 (checked on his unit). Not built before: no trace in either repo.

## What it does

- **PTN + KEYBOARD** (codes 23 + 18, digikit's key table) turns HOLD on or off. The PTN view's
  message line says KB HOLD ON / KB HOLD OFF while PTN is held. KEYBOARD mode itself is not
  touched, and neither is DIRECT JUMP.
- With HOLD on, a [TRIG] key played as a keyboard note keeps sounding when it is let go.
- The next [TRIG] pressed while no other [TRIG] is down releases every held note first, then
  plays (a new note or chord replaces the old). Keys added while others are still down join the
  chord.
- HOLD off releases every held note.
- The sequencer's trigs are untouched; only the keys played by hand. Chords, the arpeggiator
  (its notes are the held keys: HOLD is its latch) and microtuning work as for held keys.
- Not kept over a power cycle (HOLD starts off).

## How (UI level only, no DSP change)

- Every UI item passes `rec.c smp_ui_pop` before any view sees it. A [TRIG] key's item: codes
  25..40, bit 0 of the flags on the press, bit 4 on the release.
- **PTN + KEYBOARD is caught there**, not in the PTN view's key handler: stock takes KEYBOARD
  before any view (measured in the emulator: with PTN held, KEYBOARD turned KEYBOARD mode off
  and `jump.c jmp_key` never saw it). The KEYBOARD press is dropped; the message goes to the PTN
  view, found in the screen's view list by its class 0x402008c4 (`rec.c smp_view_of`, the walk
  `smp_question_up` already made).
- **The PTN view is closed when PTN is let go.** Left open (stock leaves it open after PTN alone,
  and after PTN + YES / NO too), the next [TRIG] picks a pattern (measured). At PTN's release a
  NO press goes out first and then PTN's own release; `jmp_key` hands that NO to the PTN view's
  stock handler (`kh_close` 2), which closes it as PTN + [TRIG] does.
- Which presses were keyboard notes: stock's KeyboardView asks for a key's notes through the
  site `slc_keynotes` already owns (`slice.c`, coldfire.py KEYNOTES_SITE). A key it asks for is
  marked (`kh_kb`) until its release; a key it never asks for (a step, a mute, a menu) is left
  alone, so no keyboard-mode flag has to be found.
- HOLD on, the release of a marked key: its item is copied (`kh_rel`, one a key) and dropped.
- A fresh [TRIG] press with no other [TRIG] down and kept releases waiting: the kept releases
  go out first, one a call of `smp_ui_pop`, then the press (its copy), before stock's queue is
  read again. HOLD off: every kept release goes out the same way.

## Room

The image was full (v0.63: 89 bytes left of the 2 MiB USB buffer). The HOLD code was made as
small as it goes (about 300 bytes packed), and the start-up animation ships every other one of
s!Rwa²'s 37 moving frames at 160 ms (`dnfw.bootanim.SHIPPED`; his JSON is untouched): the same
length, the same last frame, about 400 bytes freer. v0.64 has 89 bytes left.

## Gate: `kbhold` (ColdFire emulator)

KEYBOARD on; PTN + KEYBOARD: the PTN view up while PTN is held and gone at its release (both
times), HOLD on then off with KEYBOARD left on, the three screens (before, ON, OFF) each its own,
DIRECT JUMP's setting the same at the end, nothing pending. The ISR's frame (bytes 0x22..0x29,
the trig and release masks): [TRIG 1] let go: no release, kept; [TRIG 5]: 1's voice released as
5's plays, 5 let go: kept; [TRIG 8] + [TRIG 11]: 5 released, both play on two new voices, both
kept; HOLD off: both released. Negative control: HOLD off, [TRIG 1] let go: released at once,
nothing kept.

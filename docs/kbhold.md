# KEYBOARD HOLD (v0.64)

Owner, 2026-11-19: a note hold for the keyboard; he remembered it as PTN + KEYBOARD, which does
nothing on stock 1.11 (checked on his unit). Not built before: no trace in either repo.
Owner, 2026-11-20: "it must hold notes that are already playing ... it must latch whatever is
currently playing being played with the trig buttons/midi in", "and it should work with arp as
well"; PTN and KEYBOARD alone must work as before.

## What it does

- **PTN + KEYBOARD** (codes 23 + 18, digikit's key table) turns HOLD on or off. The PTN view's
  message line says KB HOLD ON / KB HOLD OFF while PTN is held. KEYBOARD mode itself is not
  touched, and neither is DIRECT JUMP. PTN alone, KEYBOARD alone, PTN + [TRIG] and PTN + YES / NO
  are stock's (and v0.40's DIRECT JUMP).
- HOLD is a sustain pedal held down on every track: a played note keeps sounding after its key
  (or MIDI note-off) lets go. Notes **already held when HOLD comes on** are latched the moment
  they are let go. Notes played while HOLD is on join them.
- HOLD off releases every held note.
- [TRIG] keys in KEYBOARD mode, MIDI in, chords, the arpeggiator (it keeps running on the latched
  keys: their note-offs never reach it) and microtuning. The sequencer's own notes never pass
  there and are untouched.
- Not kept over a power cycle (HOLD starts off).

## How

- **Stock's sustain does the holding.** Stock 1.11 keeps a per-track sustain flag (`0x445fe6e0`,
  one byte a track) set by MIDI CC 64 (the CC handler at `0x40122f56` jumps to
  `0x40126d4a(track, on)`). Every live note-off goes through `0x4012182a(track, note, source)`
  (the KeyboardView's key up, the MIDI note-off entry `0x40121aae` / `0x401219ac`, all notes off,
  ...), whose first call `0x40126e30` keeps the note-off in the track's list (`0x445fe6f0` +
  8 × track) while the flag is set, instead of sending it. `0x40126d4a(track, 0)` clears the
  flag and sends every kept note-off. HOLD calls `0x40126d4a(t, on)` for the 16 tracks
  (`rec.c kh_set`).
- **PTN + KEYBOARD is caught in `rec.c smp_ui_pop`**, not in the PTN view's key handler: stock
  takes KEYBOARD before any view (measured in the emulator: with PTN held, KEYBOARD turned
  KEYBOARD mode off and `jump.c jmp_key` never saw it). The KEYBOARD press is dropped; the
  message goes to the PTN view, found in the screen's view list by its class 0x402008c4
  (`rec.c smp_view_of`, the walk `smp_question_up` already made).
- **The PTN view is closed when PTN is let go.** Left open (stock leaves it open after PTN alone,
  and after PTN + YES / NO too), the next [TRIG] picks a pattern (measured). At PTN's release a
  NO press goes out first and then PTN's own release (held back one call, `kh_press`); `jmp_key`
  hands that NO to the PTN view's stock handler (`kh_close` 2), which closes it as PTN + [TRIG]
  does.
- A first version (2026-11-19, never released) latched at the UI level: it dropped a [TRIG]
  key's release items. It could not latch MIDI in, and it was larger.

## Room

The image was full (v0.63: 89 bytes left of the 2 MiB USB buffer). The start-up animation ships
every other one of s!Rwa²'s 37 moving frames at 160 ms (`dnfw.bootanim.SHIPPED`; his JSON is
untouched): the same length, the same last frame, about 400 bytes freer. v0.64 has 291 bytes
left.

## Gate: `kbhold` (ColdFire emulator)

The screens first (after the harness's own ISR entry the panel's picture stops following the
UI: measured): KEYBOARD on; PTN + KEYBOARD twice: the PTN view up while PTN is held and gone at
its release, the three screens (before, ON, OFF) each its own. Then the ISR's frame (bytes
0x22..0x25, the trig and release masks): [TRIG 1] pressed, HOLD on (sustain on all 16 tracks),
[TRIG 1] let go: no release; [TRIG 5] played and let go: no release; a MIDI note-off on track
1's channel through stock's MIDI entry: kept in its sustain list; HOLD off: both voices
released, every flag off, every list empty. Negative controls: HOLD off, the same MIDI note-off
is not kept, and [TRIG 1] let go is released at once. KEYBOARD stays on, DIRECT JUMP's setting
is the same at the end, nothing pending.

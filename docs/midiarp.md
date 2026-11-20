# The arpeggiator on MIDI tracks (v0.67)

Owner, 2026-11-20: "just arp on midi tracks". The `midiarp` mod (`src/dnfw/mods/midiarp.py`,
`scripts/build_arp_midi_play.py`), which passed on the instrument on 2026-09-17 as
`arp-midi-play4` (DNX captures: offsets, velocity, SPD, RNG, N.LEN 1/32..1/4 within a
millisecond, no stuck notes), is now part of the DN2 mk2 build: `waverider.apply` checks its
guards and stock bytes in the image (after the mod's own section-3 edits; no byte overlaps) and
writes its edits and cave, the cave's N.LEN lookup built from the image's own tables.

What it does (from the mod's own notes):
- the ARPEGGIATOR menu opens on a MIDI track, and its knobs stay on the menu;
- a MIDI track with the arp on takes the synth road at the three forks (sequencer trig, key down,
  key up), so its notes reach the ISR's arp;
- at the ISR's voice trigger (0x400268f8), a MIDI track's note becomes a MIDI record on the batch
  the ISR already hands the MIDI task: its note is the arp's step, its length N.LEN (INF sent as the
  longest finite length);
- arp off on a MIDI track, and every synth track: stock.

Gate: `midiarp` (ColdFire emulator, three runs, KEYBOARD on, [TRIG 1] down and up with a frame
after each): MIDI track with the arp on goes through the key gate to the voice starter, never the
MIDI sender, reaches the MIDI-record hook at the voice trigger, and starts no voice; negative
controls: the same track with the arp off goes to the MIDI sender as stock; a synth track starts a
voice as stock.

Not checked in the emulator: the menu opening on a MIDI track (hardware, 2026-09-17), and the MIDI
task's sending (the emulator does not run it). With HOLD (v0.64): sustain on a MIDI track's arp
road is the synth road's, untested on the unit.

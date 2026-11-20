# The arpeggiator on MIDI tracks (v0.67)

Owner, 2026-11-20: "just arp on midi tracks". The `midiarp` mod (`src/dnfw/mods/midiarp.py`,
`scripts/build_arp_midi_play.py`) comes from the upstream project this firmware is built on, Angel
Linares's dn2_firmware_explore (`docs/UPSTREAM-README.md`): his work, tested on his unit on
2026-09-17 as `arp-midi-play4` (DNX captures: offsets, velocity, SPD, RNG, N.LEN 1/32..1/4 within a
millisecond, no stuck notes; "the owner" in `docs/ideas-backlog.md` §10 is him). It is now part of
the DN2 mk2 build, not yet tested on our owner's unit: `waverider.apply` checks its
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
MIDI sender, reaches the MIDI-record hook at the voice trigger, and the engine's voice trigger (0x400db524) is
never called for it; negative
controls: the same track with the arp off goes to the MIDI sender as stock; a synth track starts a
voice as stock.

Not checked in the emulator: the menu opening on a MIDI track (upstream's hardware, 2026-09-17), and the MIDI
task's sending (the emulator does not run it). With HOLD (v0.64): sustain on a MIDI track's arp
road is the synth road's, untested on the unit.

Measured under the emulator (v0.67): after the hook, the ISR's stock code still sets the voice
slot's note-on bit in the frame for the MIDI track's note. On upstream's unit a MIDI track's slot made no
sound: `arp-midi-diag` (2026-09-17) passed every record to the stock trigger as well, and no internal
audio came from the MIDI track (upstream's test, on his unit). Worth a listen on v0.67: a MIDI track with the arp on should stay
silent on the main outs.

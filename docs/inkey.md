# In key: arp scale lock and in-key transpose (v0.70)

Asked for on Discord by edtide (2026-11-06, "lock the DN2 arp to a scale"); calliomilope pointed
out it already existed upstream, with in-key track transposition. The owner put it next
(2026-11-21). Both are **w-winter's** mods from upstream (angellinares/dn2_firmware_explore,
AGPL-3.0, pull requests #212, #214 and #278; upstream commit 5923e1b), applied inside the DN2 mk2
build as midiarp is (v0.67), not rewritten.

## What they do

**ARP OFS IN SCALE** (`arpscale`; SETTINGS > PERSONALIZE, off by default). On, each arp step's
OFFSET counts degrees of the track's KEYBOARD SETUP scale from its root instead of semitones: in C
major, E + 2 plays G (stock: F#), + 7 is the octave. Offset 0 plays the held note unchanged; a held
note off the scale moves to the nearest scale note first (the lower on a tie). RANGE still adds
octaves. SCALE CHROMATIC and MODE CHORD MEMORY keep stock's semitones. In the ARPEGGIATOR menu,
[UP] on an active step marks it to move in semitones (a plus in the step graph); [DOWN] removes
the mark, [DOWN] again mutes the step as stock.

**Degree transpose** (`degreetranspose`). [KEYBOARD] + [FUNC] + [+]/[-] (or [KEYBOARD] + [TRK] +
[+]/[-]) moves the active track by degrees of its scale, -7..+7, one a press; it blinks while held
and takes effect on release, shown in the track box with a tick ("+2'"). Kept per track in each
pattern (bits 2..5 of the track's byte +1187), saved with it; MIDI tracks too. A track with no
scale moves by semitones. [KEYBOARD] + [TRK] + [FUNC] + [+]/[-] is stock's octave.

## How it is applied

`src/dnfw/mods/inkey.py`: upstream's two 1.11 specs, byte for byte (`arpscale_code.json`,
`degreetranspose_code.json`). `waverider.apply` checks every guard and every edit's stock bytes in
the image first (none is a site the DN2 mk2 mod writes; checked against v0.69), writes the 25
edits, and adds the two CODE chunks at their own addresses, 0x467A8000 and 0x467B8000, clear of
ours. RAM: arpscale's toggle byte 0x405CD8AF (the settings block's tail; nothing of ours uses it).
The assembler sources are upstream's, in `scripts/upstream_inkey/`.

## How it is checked

Gate step `inkey` (ColdFire emulator, the ui800M snapshot): the playing pattern set to C IONIAN,
[KEYBOARD] and TRIG 11 held (E4).

- The arp, with the audio ISR at its real rate: ARP OFS IN SCALE on, every step's note is the held
  one moved its offset in degrees of C major (E4 + 2 = G4); off, stock's sum in semitones (F#4).
- Degrees: +2 on track 1 plays E4 as G4; 0 plays E4; +2 with SCALE CHROMATIC plays F#4.

Not driven in the emulator: the [+]/[-] keys (they don't reach the transpose handler here, stock's
[TRK] + [+] neither) and the ARPEGGIATOR menu's marks. Upstream's hardware reports cover them:
arpscale passed upstream's written hardware test on the repository owner's unit (2026-10-14), and
w-winter reported both working on his (upstream `docs/flashing.md`, 2026-10-12..26).

# The Digitakt II's sample machines on the DN2 (v0.13 - v0.15)

The Digitone II and the Digitakt II are the same board and one codebase; what makes a
Digitakt a sampler is its sample machines, a sample pool in the DSP's memory, and the
ColdFire's sample manager (`docs/dt2-port-map.md`). This is the first part of putting
them beside the DN2's own machines: the machines themselves, on the DSP, playing from a
pool in the DSP's DDR.

## What v0.13 has

MACHINE SEL gains a section after PERC, RESONATOR and CZ:

| type | machine | in v0.13 |
|---|---|---|
| 8 | **ONESHOT** | plays |
| 9 | **WERP** | plays (v0.14) |
| 10 | **STRETCH** | plays (v0.14) |
| 11 | **REPITCH** | plays (v0.14) |
| 12 | **GRID** | plays |

The pool holds **four test sounds** until you send your own, made by
`dnfw.sampler.live.test_samples` (no one's recordings): 1 KICK, 2 SNARE, 3 HAT, 4 BEAT
(sixteen steps of the three, for GRID). **v0.14: your own samples**, sent over USB with
`tools/dn2samples.py` (below).

## The pages

One page each, laid out as the Digitakt II's SRC page (v0.15; the owner's photographs of
the DT2 and its manual): A TUNE, B PLAY, C an empty dotted box (CFAD on ONESHOT), D SAMP
on top, and the machine's own four below.

| machine | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| ONESHOT | TUNE | PLAY | CFAD | SAMP | STRT | LEN | LOOP | LEV |
| WERP | TUNE | PLAY | - | SAMP | SEG | MODE | BARS | LEV |
| STRETCH | TUNE | PLAY | - | SAMP | STRT | LEN | BARS | LEV |
| REPITCH | - | PLAY | - | SAMP | STRT | LEN | BARS | LEV |
| GRID | TUNE | PLAY | - | SAMP | SLCE | LEN | GRID | LEV |

The widgets are drawn in the DT2's shapes (`csrc/sampler/smp_page.c`; its widget classes
are not in the DN2, so these are our own): TUNE a bipolar box, PLAY and MODE the play
icon (|->|, |<-|, a loop with F or R), SAMP a box with an inverted bank letter and the
slot, STRT and LEN knobs, LEV a fader, SEG a ring and 1/n, BARS four blocks and the
value, an unused place a dotted box. **ONESHOT and GRID** show the sample's waveform
across the middle instead of the bottom row's widgets: the start and end as solid
markers, LOOP dotted in the loop modes, GRID's slices ticked and the slice played marked;
the bottom row's labels under it and LEV as a pill, as on the DT2.

- **TUNE** ±60 semitones around the note (C4 plays the sample at its own pitch).
- **PLAY** REV, REV LOOP, FWD LOOP, FWD (the DT2's order; FWD is the default).
  FWD LOOP loops between LOOP and the end; REV LOOP starts at the end, plays back to
  LOOP, and loops between them (DT2 manual, Appendix A).
- **SAMP** 0 is OFF (no sound, as on the DT2); 1..4 the pool's sounds; a slot the pool
  does not hold is silent.
- **STRT / LEN** where the sound starts and how much of it plays; **LOOP** the loop point.
- **GRID** 4, 8, 16, 32 or 64 equal slices; **SLCE** which one; **LEN** how many
  consecutive slices.
- **LEV** the sample's level (100 = as recorded).
- **BARS** (WERP, STRETCH, REPITCH) how long the sample (STRT..LEN) lasts: 1/8, 1/4, 1/2,
  1, 2, 4, 8 or 16 bars at the tempo. The tempo is the DN2's own, which its frame already
  carries to the DSP (BPM x 120 at frame offset 216).
- **REPITCH** plays the region faster or slower so that it lasts BARS (the note still
  transposes it). **STRETCH** keeps the pitch (TUNE and the note set it): two grains of
  43 ms, half a grain apart, cross-faded with triangle windows, each reading from where
  the region's source position was when it began, while that position moves so the
  region lasts BARS. **WERP** cuts the whole sample into **SEG** equal segments (128 down
  to 1) and starts segment k at k/SEG of BARS, each played at its own pitch in **MODE**
  (REV, REV LOOP, FWD LOOP, FWD) until the next starts; PLAY sets the order (REV plays the
  segments last to first) and whether the whole loops.
- These are our own readings of the DT2 manual (Appendix A); the DT2's own stretching
  algorithms are not public, so the sound is close in kind, not identical.
- **CFAD** (ONESHOT) is drawn but not yet heard.

The page shows the machine and the sound in the middle, and the sample as a bar: the
part that plays solid, LOOP's point marked in the loop modes, GRID's slices ticked.

## How it works

- **The DSP** (`dnfw.sampler.program`, written by `scripts/gen_smp_asm.py` to
  `csrc/waverider/sharc/smp.asm`): entered from PERC's tail, on to RESONATOR. Its code
  is in L2 at `0x200d0000` (sw `0xbe8000`), after PERC's 64 KB span, well below the
  non-cacheable window; its 16 voices' state (64 bytes each) and scratch in L1
  (`0x2def00`, Waverider's old loop room). Per voice: the region and loop are latched at
  the note; pitch and level follow the knobs every block; linear interpolation between
  frames, an integer position and a float fraction.
- **The machine lookup.** The engine maps the frame's machine field through a table
  (v0.13: a 16-entry copy at `0x2dee04`). Types 8..12 map to **5**, PERC's engine slot:
  the record's copy of that answer (`+0x1b4`) indexes 8-entry tables in the stock code
  (sw `0x1c299f`, the render code), so an answer of 8 or more would read past them. Slot
  5 is the one path through the stock code the runner and the instrument have already
  proven for PERC. PERC and the sample machines then tell themselves apart by the
  frame's own type word (`148 + 2t`), not the record.
- **The pool** is in the DSP's DDR at `0x84000000` (64 MB in; the stock program claims
  about 5 MB of a 512 MB part): a directory (magic `SMP1`, count, 128 entries of
  address, frames, rate, spare), then each sound's float32 frames. The test sounds are
  24 kHz (BEAT 12 kHz), each entry's rate scaling its step, to keep the upgrade file small.
- **The ColdFire** (`dnfw.waverider.coldfire`, `pages`, `csrc/waverider/page.c`): types
  5..12 are WaveTone clones (one range check in each shim); the name table, attribute
  rows and LOAD bound grow to 12; MACHINE SEL's group function puts 8..12 in a section
  of their own; the page renderer moved to a CODE chunk of its own at `0x46ac0000` (clear of the emulator harnesses' scratch at 0x46a00000).
- A sample machine with no renderer yet (WERP, STRETCH, REPITCH) has its buffer
  cleared each block: silent, never a stale block.

## Your samples (v0.14): `tools/dn2samples.py`

    python tools/dn2samples.py hello
    python tools/dn2samples.py send C:\samples\kit            every .wav in the folder
    python tools/dn2samples.py send kick.wav snare.wav loop.wav

Windows, no packages needed; close Elektron Transfer first (one program per MIDI port).
The WAVs (8/16/24/32-bit PCM or 32-bit float, any rate, mono or stereo) go into slots
1, 2, 3, ... in the order given (a folder: by name), named on the page by their file
names. They play at their own rate and pitch on C4. Up to 128 slots and 5 MB in all
(16-bit mono: about 54 s at 48 kHz). **They last until power-off** unless you keep them:
`send --keep` (or `save` afterwards) writes them to the +Drive, and the instrument loads
them at power-on (v0.15, below).

How it works:

- The tool lays the samples out as the DSP's pool (`dnfw.sampler.live.pool_bytes`:
  directory, names, frames as int16) and writes it in 256-byte pieces over USB SysEx,
  `F0 00 20 3C 7D 01 ...` (Elektron's header and a device byte no Elektron machine
  uses, as the read-only probe of `docs/usbprobe.md`; sub-id 01), into a **mirror** of
  the pool in the ColdFire's RAM above BSS (`0x46b00000`, 5 MB, declared by the mod).
  `csrc/sampler/link.c`, entered from the SysEx router at `0x4012169a`.
- **The link to the DSP**: the frame the ColdFire pushes to the DSP 1,500 times a
  second carries, at offsets 2650..2681, a per-track array the DSP never reads (no
  direct read in the image, and the runner's step 3c shows random words there change
  nothing). After the frame builder has built each frame (`0x400276a2`), `smp_feed`
  puts one packet there: a magic word, a word offset into the pool, six 32-bit words,
  a 16-bit check. The DSP (`dnfw.sampler.program.mailbox`, at the top of `wr_smp`)
  writes a packet that checks out, inside the pool's 16 MB, and nothing else.
  36 KB a second.
- The feeder walks the mirror from 0 to its end **over and over**, so a frame the DSP
  misses is put right on the next pass, and the DSP's pool always converges to the
  mirror. A write moves the walk back to it, so what was just sent goes first. The tool
  sends the frames first and the directory last, so no slot points at a sample before
  it is there, and waits for a whole pass before it says done.
- The page names the slots from the mirror once a pool has been sent.

## Keeping them on the +Drive (v0.15)

    python tools/dn2samples.py send C:\samples\kit --keep
    python tools/dn2samples.py save | load | forget

The pool is written to a region of the eMMC the DN2 itself never uses: the stock storage
code reads and writes nothing above 2,224 MiB, and refuses to
(`docs/drive-storage-research.md`); ours is one header sector at sector `0x600000`
(3 GiB) and the mirror's bytes after it, about 5 MB. Read and written through the stock
block driver (`0x4012c59a` / `0x4012c780`, under its own mutex), and only when every
sector is inside that region and inside the device. The header carries a magic, the
length and a checksum of the bytes, and a load that does not match them changes
nothing. At power-on the UI loop's first passes, once the device is up, load it into
the mirror; the feeder then sends it to the DSP as after a send. Projects, presets and
kits are not touched; `forget` zeroes the header sector so nothing loads.

## Checked

- `scripts/sharc_waverider_m5.py` step **3b** (in the ship gate): every sample track's
  buffer and state bit-exact to `dnfw.sampler.program` run on the DSP's memory at its
  entry, every block of nine runs; ONESHOT's KICK matches the sound itself (error
  < 1e-5); TUNE +12 is higher; reversed, looping and GRID tracks sound; PERC beside them
  stays bit-exact; WERP's buffer is 0; OFF, an empty slot and no trigger are silent; a
  second note restarts.
- Step **3c** (v0.14): good packets land in the pool, one a block; a bad check or an
  offset past the pool writes nothing; random words where the packets go (not the magic)
  change no track buffer of FM Tone, PERC or ONESHOT.
- The ColdFire end in the emulator (`scripts/emu_waverider_menu.py`'s `sysex:` and
  `isr:` steps): HELLO, WRITE, STATUS answered on USB; a write past the mirror refused;
  every packet the frame builder sent is exactly `dnfw.sampler.program.link_packet` of
  the mirror's bytes.
- Step 4: tracks 1-15 bit-identical to stock with track 0 on ONESHOT or WERP.
- `test/test_sampler.py`: the pool layout, the int16 kick, each time machine lasting
  BARS at two tempos, STRETCH keeping the pitch while REPITCH does not, the mailbox, the
  host tool's codec and WAV reading.
- The ship gate's SAVE/LOAD: types 8 and 12 round-trip; 13 loads as FM Tone.
- `test/test_waverider_dsp.py`, `test_waverider_mod.py`, `test_waverider_pages.py`.

## Next

1. CFAD (ONESHOT's crossfade at the loop point).
2. Sampling from the inputs.
3. The comb filter.

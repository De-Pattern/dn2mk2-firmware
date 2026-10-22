# The Digitakt II's sample machines on the DN2 (v0.13 - v0.16)

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
| 9 | **WERP** | plays |
| 10 | **STRETCH** | plays |
| 11 | **REPITCH** | plays |
| 12 | **GRID** | plays |

The pool holds **four test sounds** until you send your own, made by
`dnfw.sampler.live.test_samples` (no one's recordings): 1 KICK, 2 SNARE, 3 HAT, 4 BEAT
(sixteen steps of the three, for GRID). **your own samples**, sent over USB with
`tools/dn2samples.py` (below).

## The pages

One page each, laid out as the Digitakt II's SRC page (the owner's photographs of
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
- **CFAD** (ONESHOT, v0.14) crossfades the loop: in FWD LOOP, over the last X frames
  before the end (X = CFAD/127 of the shorter of the loop and what lies before LOOP)
  the sound fades into the audio just before LOOP, so the jump from the end back to
  LOOP lands where the sound already is: no click, however the loop is cut. 0 is off;
  drawn as a knob.

The page shows the machine and the sound in the middle, and the sample as a bar: the
part that plays solid, LOOP's point marked in the loop modes, GRID's slices ticked.

## v0.15: the DT2's two SRC pages, one detent a choice, live loops

- **Page 1** (SYN) is the widgets and their labels for every machine, as the DT2's SRC
  page 1; **page 2** (SYN again) is the same controls with the sample's waveform across
  the middle (the start, end, loop or slices marked; WERP its segments), as the DT2's
  page 2. The box at the left reads **SMP**. The widgets are redrawn after the DT2's: TUNE
  a box with its value in the middle, the knobs whole rings, the empty place a dotted
  square, the segment icon, BARS as one, two or four blocks.
- **ONESHOT's C is the DT2's empty box.** CFAD (v0.14) is not a DT2 ONESHOT control, so it
  is off the page and off in the DSP (`dnfw.sampler.program.CFAD_ON`).
- **One detent a choice.** PLAY, WERP's MODE, BARS, SEG, GRID's GRID, SLCE and LEN, and
  the recorder's SRC sit on records of 0..127 or so; the stock parameter setter
  (`0x40037b74`) now asks `smp_quant` (`csrc/sampler/fmt.c`) before it writes, and a turn of
  up to 8 raw steps moves to the next choice (`dnfw.sampler.machines.QUANT`; each value it
  sets is inside the choice the DSP reads, `test_sampler` checks every one). Only for a
  sound whose machine is one of ours, only those slots. ARM, R.STRT, CHAN and DEST are on
  2-, 3- and 4-step records and step natively.
- **The value text** the header shows as a control moves is ours: REV / REV LOOP / FWD
  LOOP / FWD, 1/4, 1/16, G16, a sample's name for SAMP (KICK, your WAV's name, REC 1..4),
  IN / MAIN / TRK3, MONO L, OFF / ON, MAX. The records' formatters (record + 0x34) are
  swapped while a sample machine's track is active, as `wr_names` swaps their names.
- **Loops follow the controls while they sound.** ONESHOT, STRETCH and REPITCH re-read
  STRT, LEN, LOOP and PLAY every block (`dnfw.sampler.program.live`), so a held loop moves
  its end and loop point as LEN and LOOP turn and turns round when PLAY does. GRID takes
  its slice, and WERP its segments, at the note. How long a note (and a loop) sounds is
  the track's AMP envelope, as on the DT2 (its manual: "constrained by the AMP page
  envelope parameters HLD and DEC").

## Page 3: the RECORDER (v0.15)

The third SYN page of every sample machine, laid out as the DT2's RECORDER (its manual
13.1, the owner's photograph) under the DN2's header:

| place | control | |
|---|---|---|
| A | **SRC** | IN, MAIN, TRK1..TRK16, with the channel under it |
| B | **CHAN** | MONO L+R, MONO L, MONO R (the DN2's tracks are mono: no STEREO) |
| C | **RECORD NOW** | the dotted box: **YES** records at once; YES again stops |
| D | **THRES** | 0..120, ticked on the meter |
| E | **DEST** | SAMP 124..127 (the DT2 has MON here; the DN2 monitors its inputs itself) |
| F | **R.LEN** | MAX (21.8 s, the slot) or 1..127 sixteenth steps at the tempo |
| G | **R.STRT** | THRES: ARM waits for the threshold; PLAY: for the first note any track plays |
| H | **ARM** | turn it to arm; turn it again (armed or recording) to stop |

Across the top, the source's **input meter**; in the box, ARMED / ON THRES, or REC and
the seconds, or RECORD AGAIN when a recording is done.

**Nothing about the recorder is saved with a sound.** Its settings sit on the page's
records, but the DSP acts only on a **command**, and commands are sent only while the
page is on the screen: YES, a turn of ARM, and SRC or CHAN as they change (for the
meter). ARM's switch shows what the DSP is doing, not the record's value.

How:

- **Commands** (`csrc/sampler/rec.c`, `link.c`'s `smp_command`): six words -- a sequence
  number, the command (ARM, NOW, STOP, MONITOR, ARM_PLAY), source, channel, threshold,
  DEST << 24 | frames -- sent through the sample link into the pool's **command block**
  (`dnfw.sampler.machines.CMD_OFFSET`, 0xF00) ahead of the pool's walk, 16 frames running.
  The walk steps around the block. The DSP (`dnfw.sampler.program.recorder`) acts once on
  each new sequence number.
- **Status**: every block the DSP writes 16 halves into the **SPI reply's tail** (bytes
  0xa9c..0xabb, which stock never writes and nothing the DN2 runs reads), in both reply
  pages: STATUS_MAGIC | state, the last command's sequence, frames / 32, the peak, the
  link's packet count, and a check. The ColdFire reads them from its copy of the reply
  (`0x80005E40`) in the UI loop (`smp_status`), and draws the meter and the state from
  them; a status that does not check out is ignored.
- **YES** on the page: the parameter page view's key handler (its vtable slot
  `0x401d49a8`) points to `smp_key`, which takes YES while the RECORDER is on the screen
  and hands every other key, and every other page, to stock's `0x40016480`.
- **Sources**: IN is the engine's input block (`0x268538`); MAIN the last block's mix
  (`0x268438`); **TRKn** the buffer stock fills for Overbridge's per-track stream
  (`0x259f68` + 0x100 k: the track's block, panned, the last block's, written after the
  machine dispatch by `0x1c244d`), k the track's slot from its routing half (`0x257898` +
  2t, the ColdFire's slot map), scaled back by 0x1c244d's gain (11.627).
  (`docs/link-research.md` has the reading.)
- The recordings are in the DSP's memory only: they are lost at power-off.

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

## Your samples: `tools/dn2samples.py` (v0.14 - v0.15; v0.16 below)

    python tools/dn2samples.py hello
    python tools/dn2samples.py send C:\samples\kit            every .wav in the folder
    python tools/dn2samples.py send kick.wav snare.wav loop.wav

Windows, no packages needed; close Elektron Transfer first (one program per MIDI port).
The WAVs (8/16/24/32-bit PCM or 32-bit float, any rate, mono or stereo) go into slots
1, 2, 3, ... in the order given (a folder: by name), named on the page by their file
names. They play at their own rate and pitch on C4. Up to 122 slots (124..127 are the
recorder's) and 5 MB in all
(16-bit mono: about 54 s at 48 kHz). **They last until power-off** unless you keep them:
`send --keep` (or `save` afterwards) writes them to the +Drive, and the instrument loads
them at power-on (below).

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

## v0.16: 96 MB of yours on the +Drive, the fast link, recordings kept

**The pool is 128 MB** in the DSP's DDR (`dnfw.sampler.machines.POOL_BYTES`): the first
96 MB yours (SAMP 1..122), the last 32 MB the recorder's four slots, 8 MB each (a recording
runs up to 66 s of 48 kHz int16, `REC_FRAMES`). The DSP's 512 MB part leaves stock's 5 MB and our
pool far apart (`docs/link-research.md` §6b).

**The +Drive holds the pool's image**, byte for byte as the DSP holds it, in the region of
the eMMC the DN2 never uses (sector `0x600000`, 3 GiB, and up: a header sector `DN2Q`
with the image's length and the directory page's checksum, then the image). The image is
the master copy: the host tool writes your samples straight into it, and the recorder's
recordings are written into it when they end. v0.15's `DN2P` images load as they are.

    python tools/dn2samples.py send C:\samples\kit           (sample link 3: v0.16)

- **Sending** (`tools/dn2samples.py`, sample link 3): BEGIN (the old image is marked
  empty), WRITE in order (512-byte pieces; the ColdFire gathers 64 KB and writes it to the
  eMMC), END (the header is written, then the image is loaded into the DSP). The
  recorder's four directory entries in the image are kept as they were, so sending your
  samples does not forget your recordings.
- **Loading** (power-on, END, `load`): `link.c`'s loader reads the image's directory, then
  each used slot's frames, 64 KB at a time, and sends them to the DSP; the directory page
  (up to the DSP's command block at `0xf00`) goes last, so no slot points at frames that
  are not there yet. **Every chunk is checked**: the ColdFire asks the DSP for two sums
  of the words it now holds (`CMD_VERIFY`; `a += w, b += a`, mod 2^32, 1,024 words a
  block) and compares them with its own. A chunk that does not check out is sent again.
- **The fast link** (`docs/link-research.md` §6): eight TDM slots ColdFire -> DSP (8..15)
  that stock neither fills nor reads. A hook in the SSI ISR (`0x40026098`, where every
  transmit-fill mode has ended: `smp_tdm_hook` replays the two instructions it displaced)
  writes one packet a period: 256 16-bit units under the tag byte `0xa5` (magic,
  sequence, word offset, 124 words, count, check), so 124 words, 496 bytes, 1,500 times a
  second: **about 0.7 MB/s**, 20 times the frame's words. The DSP (`tdm_rx`) reads the
  page the engine read that block and writes a packet that checks out anywhere in the
  pool but over the command block. Twice wrong on the fast link and the loader sets it
  aside for the frame's words (36 KB/s, slow but always there); the host tool says which.
- **Recordings kept**: when the recorder stops (YES, R.LEN, or the slot full), the
  ColdFire asks the DSP to send the slot back (`CMD_SEND`, 64 KB windows) over the two
  TDM slots DSP -> ColdFire (14..15; 29 words a period, about 170 KB/s), checks every
  packet, writes each window to the +Drive, and then the slot's directory entry. After a
  power cycle SAMP 124..127 play what they held. The status's frame count is in 64-frame
  units now (a slot holds more than 65,535 x 32 frames).
- **The waveform** on page 2 comes from an overview the ColdFire makes while a slot's
  frames pass through it (100 column peaks a slot), so it is drawn for the recorder's
  slots too, and for samples of any length.
- **Commands queue** (eight deep, each sent for eight frames), so VERIFY, SEND and the
  recorder's commands no longer overwrite one another.

## Checked

- `scripts/sharc_waverider_m5.py` step **3b** (in the ship gate): every sample track's
  buffer and state bit-exact to `dnfw.sampler.program` run on the DSP's memory at its
  entry, every block of nine runs; ONESHOT's KICK matches the sound itself (error
  < 1e-5); TUNE +12 is higher; reversed, looping and GRID tracks sound; PERC beside them
  stays bit-exact; WERP's buffer is 0; OFF, an empty slot and no trigger are silent; a
  second note restarts.
- Step **3c**: good packets land in the pool, one a block; a bad check or an
  offset past the pool writes nothing; random words where the packets go (not the magic)
  change no track buffer of FM Tone, PERC or ONESHOT.
- The ColdFire end in the emulator (`scripts/emu_waverider_menu.py`'s `sysex:` and
  `isr:` steps): HELLO, WRITE, STATUS answered on USB; a write past the mirror refused;
  every packet the frame builder sent is exactly `dnfw.sampler.program.link_packet` of
  the mirror's bytes.
- Step 4: tracks 1-15 bit-identical to stock with track 0 on ONESHOT or WERP.
- Step **3d** (v0.14): a track recording a 330 Hz input block by block: the slot's entry
  and int16 frames are exactly the model's; REC off keeps them; SAMP 124 plays it back,
  every sample track bit-exact. Step 3b also runs CFAD (bit-exact; the loop differs from
  the same loop without it).
- The feeder in the emulator (v0.14): 220 packets after a 2,400-byte write, each
  `link_packet` of the mirror, none touching bytes 1976..2039, every other byte sent.
- `test/test_sampler.py`: CFAD removes the loop's jump; the recorder records, keeps and
  plays back, and waits for THRS; the mailbox refuses the recorder's entries; the pool layout, the int16 kick, each time machine lasting
  BARS at two tempos, STRETCH keeping the pitch while REPITCH does not, the mailbox, the
  host tool's codec and WAV reading.
- The ship gate's SAVE/LOAD: types 8 and 12 round-trip; 13 loads as FM Tone.
- `test/test_waverider_dsp.py`, `test_waverider_mod.py`, `test_waverider_pages.py`.

## Next

1. ~~Keeping recordings, and much more sample memory~~: v0.16. More than 128 MB is
   possible (the DDR has room) once the fast link is heard working on the instrument.
2. A sample list (names) when choosing SAMP, as the DT2's.
3. Closer clones of the DT2's machines (its OS 1.17 is on hand to read) and the
   Machinedrum's (`docs/perc.md`).
4. The comb filter.

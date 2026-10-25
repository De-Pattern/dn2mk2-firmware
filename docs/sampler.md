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

## Page 3: the RECORDER (v0.15..v0.21; v0.22 below)

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

## v0.22: the RECORDER is a screen of its own

**FUNC + VOICE** opens the RECORDER over whatever page is up; FUNC + VOICE again, or
**NO**, closes it. (Stock FUNC + VOICE toggled unison; VOICE alone still opens the voice
menu, where unison is.) As on the DT2's SAMPLING screen it belongs to no track: you can
start a recording, change tracks and play, and come back to stop it.

- Its knobs are its own while it is up: **A SRC** (EXT L+R, EXT L, EXT R, MAIN, TRK1..16),
  **D THRES**, **E DEST**, **F R.LEN**, **G R.STRT**, **H ARM** (a turn arms, or stops).
  **YES** records at once, or stops. The track underneath is not touched.
- Any page key, TRK, PTN, SONG, PRESET or SETTINGS closes it and does what it does;
  PLAY, STOP, the trigs and FUNC pass through with it up. A recording runs on regardless.
- **How**: `smp_ui_pop` (csrc/sampler/rec.c) replaces the UI loop's queue receive
  (`0x4002f17e`): while the screen is up a knob or key item it takes has its type set
  to 0xFF, which the loop's switch passes over (types past 41 are skipped by stock).
  `wr_screen` replaces the loop's draw of the screen (`0x4002e4ca`) and draws the
  recorder after stock's. `rec_combo` replaces the key handler's FUNC + VOICE branch
  (`0x4005f008`, then on to the handler's common exit `0x4005fc50`).
- The old SYN page 3 recorder is gone: sample machines have two pages, as the DT2's.

**Track sources were wrong before v0.22.** The routing halves at `0x257898 + 2v` say which
*track* each DSP *voice* plays (the ColdFire fills them from `0x80005308`, slot -> track);
`0x1c244d` sums voice v into bucket route[v] of `0x259f68`. So track t's audio is bucket t.
v0.15..v0.21 read bucket route[t], which is track t's only while voice t plays track t:
with the DN2's voice allocation the meter of a silent track moved and a track recording
held another track's audio, or silence.

**Room for recordings, not four slots.** The pool's last 32 MB (about 5 1/2 minutes of 48 kHz
int16 in all) is shared by every recording; each goes where the largest free stretch is
(`smp_rec_place`: the stretches between the recordings the directory points at; the
slot's own old recording is free), into any slot: **DEST** defaults to the next empty
one, as the DT2 saves to the next free slot. The command carries the place (bits 8..23 of
its channel word, 512-byte units) and the slot (top byte of its last word); the DSP clamps
both (never past the pool's end, never past slot 126). Each is saved to the +Drive named
`RECnnn` when it ends, and DEST moves on. A host-tool `send` keeps every recording, in its
own slot if the new image leaves it empty, else in the first empty one.

**After a recording: TRIM, NAME, ASSIGN** (the DT2's steps, manual 13.2 9..11), when the
screen is up as it ends (`rec_phase` in rec.c, drawn by `trim_draw`/`name_draw`/
`assign_draw` in smp_page.c):
- **TRIM**: the recording's waveform (filled in as it is saved), **E** START and **H** END
  (a detent a 200th of it; with FUNC held, a 2000th; LEFT and RIGHT nudge them), START,
  LENGTH and END in seconds. **YES** keeps [START, END) (`smp_trim`: the entry moves, on an
  even frame; the waveform is redrawn from the columns kept), **NO** keeps it all,
  **FUNC + NO** drops it (`smp_discard`: the slot empty again, its room free).
- **NAME**: seven characters; a knob (A..H or LEVEL), UP and DOWN change the letter,
  LEFT and RIGHT move. **YES** saves it, **NO** keeps RECnnn.
- **ASSIGN**: a **[TRIG]** key (panel codes 25..40) gives track 1..16 the sample: a track
  not on a sample machine becomes ONESHOT first, through MACHINE SEL's own commit
  (`0x40031880(model, track, 8, 1, 1)`, which resets the sound to ONESHOT's defaults), then
  SAMP is set through the knob path's setter (`0x40037326(set, id, value << 8, track, 0,
  0, 1)`, the set from `0x40041A40(owner, id, track)`, the owner from `0x4018A97A()`, the
  model at owner + 0xF4). **NO** assigns none. The directory goes to the +Drive, and a
  changed entry to the DSP (the loader's own sent-and-checked path), once nothing else runs.
- Not done: the DT2's zoom, its FUNC + YES preview (on the DT2 the active track's voice
  plays it; here the DSP has no such path yet) and its normalising.

**400 MB, and a RAM check.** The pool now runs to 400 MB of the DSP's 512 MB part
(`0x84000000..0x9D000000`): yours in 0..96 MB and 128..400 MB, the recordings' 32 MB
between (the RAM proven on the instrument before v0.22: the recordings stay there). The
+Drive's image is the pool byte for byte, so the +Drive holds the same 400 MB (the eMMC
region from 3 GiB has room for far more). Nothing past 128 MB had run on the instrument,
and the DMC's size field (`docs/link-research.md`) was read, not tested, so at every
power-on the ColdFire first asks the DSP for a RAM check (`CMD_PROBE`,
`dnfw.sampler.program.probe`): 256 KB at 143 MB and the 256 KB 256 MB above it (399 MB)
are filled with two patterns and read back, 256 words a block (about 0.7 s; more than
the data cache holds, so the reads come from the RAM). On a 256 MB part the second fill
lands on the first, and the check fails. Only a passed check lets the loader load past
128 MB (`ram_top`); a failed one, or no answer in four seconds, keeps it to the proven
128 MB. Both areas are the pool's own and not yet loaded while it runs. `dn2samples.py
hello` says which (sample link 4); `send` skips the recordings' area.

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
- **The link to the DSP** (v0.14..v0.19; **withdrawn in v0.20**): the frame the ColdFire
  pushes to the DSP 1,500 times a second carries, at offsets 2650..2681, sixteen
  halfwords that this page used to call "a per-track array the DSP never reads". **That
  was wrong**: they are the DSP's per-track routing (`docs/link-research.md`, "Who sets
  the two tables": the engine copies frame `0xa5a + 2t` into `0x257898 + 2t`, and an
  entry of 16 or more lands in the FX send buses and beyond). The runner's old step 3c
  missed it because its random words left the tracks it compared alone; a run with
  random words in all eight first words changes track 0 from block 4. `smp_feed` wrote a
  packet there after the frame builder (`0x400276a2`) whenever a command or a slow-link
  chunk was due: the owner's v0.19 report, WaveTone and FM buzzy and crackling after a
  sample track was used until a reboot, is that. **v0.20** removes the hook, `smp_feed`
  and the DSP's `mailbox`; the frame builder is stock's again, commands go over the TDM
  link, and the gate checks the frame's routing words every period (`link16`), the C
  sources (`test_sources`), and the stock voices under link traffic (runner step 3c).
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
  second: **about 0.7 MB/s**. The DSP (`tdm_rx`) reads the page the engine read that
  block and writes a packet that checks out anywhere in the pool but over the command
  block. v0.20: the recorder's and the loader's commands come this way too, as a packet
  of exactly the command block's six words (each sent for 8 periods, ahead of any data);
  there is no slow link any more. Seven times wrong and the loader stops; STATUS reports
  the link down and the host tool says so.
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

## v0.18: the DT2's own reader and its STRETCH

The machines now play through the Digitakt II's own DSP code, as read from DT2 OS 1.17
(`../dt2s117/research/dt2-srcmachines.md` and `dt2-reader-exact.md`, outside the
repository: they are derived from Elektron's firmware).

- **The reader** (ONESHOT, REPITCH, GRID, WERP): each output sample is two samples at
  96 kHz from a 6-tap, 256-phase polyphase interpolator, taken through the DT2's 2:1
  decimator (a fourth-order all-pass on the even samples, averaged with the odd ones
  four outputs late). Its taps wrap inside the loop window, as the DT2's circular
  buffer does, and each 96 kHz sample keeps the DT2 MAC's whole 16-bit steps. The
  coefficients (256 x 6, and the decimator's four) are read from the owner's DT2 image
  at build time (`dnfw.dt2.rom`, `DT2_SECTION7`) and live in DDR. Against the bit-exact
  model of the DT2's code, ONESHOT's output agrees on 639 samples of 640, the last within
  one 96 kHz LSB (`test_sampler.test_oneshot_is_the_dt2s_reader`). The interpolator's
  rows sum to 0.4045 (-7.9 dB), which the DT2 makes up later in its chain; LEV 100 makes
  it up here, so a sample still plays at its own level.
- **STRETCH** is the DT2's: one read head moves at the note's pitch, and every 2048
  samples it jumps by (T - pitch) x 2048 frames, T the rate that makes the region last
  BARS (clamped to 1/8 .. 4), so that it moves at T on average; for 128 samples after a
  jump the old head crossfades linearly into the new one (both read with two taps, the old
  with the new one's fraction). A note starts by fading in from the second head, as the
  DT2's does. The region loops at STRT (the DT2's STRETCH has no LOOP). Because the head
  reaches the end at the pitch's speed between jumps, a region can end up to one grain
  (43 ms) before BARS.
- **REPITCH** plays the region so that it lasts BARS, whatever the note and TUNE (the
  DT2's takes neither; v0.13..v0.17 transposed it by the note).
- **GRID**: SLCE 0 is **NOTE**: the note picks the slice ((note - 12) mod the grid) and the
  sample plays at its own pitch; SLCE 1..63 pick a slice as before, past the grid held at
  the last (the DT2 clamps). The header shows NOTE, and GRID's LEN as the number of slices.
- **WERP** is played as the DT2 plays it (`dt2-coldfire-werp.md`): its ColdFire's segment
  clock, in its own integers, a block at a time -- each block adds (BPM x 120 x 16) >> BARS,
  and a segment ends when the sum reaches 691,200,000 >> log2(segments), the remainder
  carried -- so segments start on blocks and never drift. Each segment is a note of its own
  through the reader (fresh decimator, its first block fading in), in MODE, and the one
  still sounding fades out under it over that block. FWD and FWD LOOP play the segments
  first to last, REV and REV LOOP last to first; the loop modes go round until the next
  note, FWD and REV end after the last.
- **Ends**: a voice that does not loop and reaches its end within the next two blocks is
  faded out over this one and ends (the DT2's look-ahead): no click at a sample's end.
- **Starts**: a note's first block fades in, except ONESHOT from STRT 0, whose attack is
  kept (the DT2's ColdFire sends its declick flag, frame +0x73c, as 0 only then).
- **Retriggers**: a note while the voice sounds renders the old note first, fading out over
  the block, and adds the new one to it -- what the DT2 does with its second voice a track.
- **BARS is 1, 2, 4 or 8** (default 4) and **WERP's SEG is a segment's length, 1/32, 1/16
  or 1/8 of a bar** (default 1/16), as on the DT2 OS 1.17 (its parameter descriptors and
  formatters; `dt2-coldfire-werp.md`): the sample is (32 >> SEG) << BARS segments, each
  lasting its note value at the tempo, so the whole lasts BARS bars. (v0.13..v0.17 had
  BARS 1/8 .. 16 and SEG 128 .. 1 segments, from an earlier reading.)
- **CFAD** (v0.14, off since v0.15) is gone: the DT2 has no such control.
- What is still ours: the loops follow STRT, LEN, LOOP and PLAY while a note sounds (the
  DT2 takes them at the note; v0.15 asked for this); WERP's clock runs on the DSP (the
  DT2's runs on its ColdFire, to the same arithmetic); the DT2's zero-crossing mute (a
  second declick it chooses by flags not yet read) is not here.

## v0.19: SLICE

The DT2's sixth machine (OS 1.15 on, its manual A.2.5), machine type 13, listed before GRID
as on the DT2. Its page: TUNE, PLAY, SAMP; SLCE (NOTE, 1..63), LEN (1..64 slices), LEV.

- **The slices are the sample's own**, made on the computer: `tools/dn2samples.py send`
  takes each WAV's **cue points** as its slices (most editors write them; `--slices
  cue`, the default), or `--slices grid:N` (N equal slices), `--slices onsets` (where the
  sound's energy jumps), `--slices none`. Up to 64; each slice runs from its start to the
  next start (the last to the end) and loops at its start. They travel with the sample:
  in the pool its entry's format word counts them (bits 8..15) and the table (start, end,
  loop in frames) follows its frames; the +Drive keeps them with it.
- **The DSP** (`dnfw.sampler.program.slice_bounds`, the DT2's type 5 handler): SLCE k plays
  slice k (past the last, the last); LEN plays on through the next slices; **NOTE** picks
  the slice by the note from C1 up, wrapping after the last, at the sample's own pitch
  (the DT2: "Slices play from C1 and upwards, wrapping around"). A sample with no slices
  plays nothing on SLICE. The DT2's reader, fades and retrigger as the other machines.
- **The page** marks the slices on SYN page 2's waveform (their starts, read as the
  sample loads) and the ones that play.
- Not here: the DT2's on-device SLICE menu and slice editor (CREATE SLICE GRID, transient
  detection, EDIT SLICE POINTS, linear and random locks) -- the slices come from the
  computer instead; and the DT2 keeps slices with the sound (preset), here with the
  sample.

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

**v0.22: ONESHOT never has an empty region.** LEN at 0 made the region empty, which ended
the note: silence where the owner expected the shortest, fastest loop, and a held looped
note that met an empty region while the knobs moved (STRT at its end, LEN at 0) stayed
silent when they came back. `oneshot_bounds` now keeps at least 32 frames, or a 508th of
the sample (a quarter of LEN 1's stretch), whichever is more, and holds STRT that far from
the end (`MIN_REGION`). The same bounds serve STRETCH and REPITCH.

## v0.23: SLICE's own menus, its editor, and SLICES on the trig keys

**YES on a SLICE track's page** (slice.c; `slc_page_seen` is set while smp_page.c draws a
SLICE page and cleared by the keys that leave it) opens the DT2's SLICE menu:
- **CREATE SLICE GRID**: SLICES (E) 2..64 and TR.DET (H). YES makes them: an even grid,
  or with TR.DET a slice at each transient (the host tool's onset finder, on the sample
  read back from the +Drive: `smp_analyse`, a 64 KB chunk a UI pass, then `smp_onsets`),
  as many as SLICES at most. NO cancels.
- **EDIT SLICE POINTS**: the sample's waveform (1,024 columns read back from the +Drive)
  with its slices; LEFT/RIGHT pick one, **E** START, **H** END, **D** LOOP, **F** ZOOM
  (1x..32x), FUNC + F the height, **G** POS; a detent is a 128th of the view (FUNC held:
  a frame). FUNC + YES adds a slice at the view's middle, FUNC + NO removes the picked
  one, NO leaves and keeps the edit. A sample with no slices starts as one slice.
- The DT2's CREATE LINEAR/RANDOM LOCKS are not here (they write sequencer locks).

**Where slices made here live.** A sample sent without slices has no room after its
frames for a table, so slices made on the instrument go to the **slice area**: 768 bytes
(64 x start, end, loop) a slot in the recordings' area's last 128 KB
(`SM.SLICE_AREA`; the recordings' area is 128 KB shorter). The entry's format word gets
bit 16 and the count; the DSP then reads that slot's table there (`V['sla']`). Saved:
the slot's sectors to the +Drive, the directory too; sent: the table, then the entry,
through the loader's checked path. At power-on the area loads after the slots when any
entry has bit 16. A v0.22 recording reaching into the area (only if 32 MB of recordings
had been made) keeps the area unused: the menu says SLICE AREA IN USE.

**No slices plays the whole sample** (v0.19..v0.22: nothing played, which is why SLICE
seemed dead on samples sent without cue points).

**SLICES on the trig keys.** In KEYBOARD mode, on a SLICE track whose SLCE is NOTE, trig
key k plays slice k + 1: the KeyboardView's call for a key's notes (`0x40034460(kbd,
&notes, k)` at `0x40058be8`) goes to `slc_keynotes`, which answers the single note C0 + k
(SLCE's NOTE mode plays slice (note - 12) mod slices); every other track and mode gets
stock's notes. Stock does the rest (held keys, MIDI out, live recording: the notes record
and replay the same slices). The stock TRIG MODE menu has a SLICES entry the DN2 build
disables (value 1024, refused by its setter); it is left alone. The keys' LEDs still show
the keyboard.

## v0.25: the playhead, the DT2's sample list and browser, modulated SAMP

- **The playhead.** With no SEND running, the DSP's TDM packet carries each track's play
  position (`POS_MAGIC`, then a unit a track: `POS_NONE` or the read position as a
  fraction of the sample x `POS_ONE`; `program.tdm_tx`). link.c keeps them (`smp_pos`,
  with the period they came in), and the waveform page draws the DT2's double line where
  the active track's voice reads. That follows p-locked starts, LFOs on STRT and LEN,
  WERP's segments and STRETCH's head (its position jumps a grain, 43 ms, at a time). While
  it moves, the page asks the UI loop for redraws at the recorder's rate (25 a second).
  STRETCH and REPITCH also mark the region's bars (BARS: 1, 2, 4, 8), dotted.
- **The sample list** (DT2 manual 9.7): turning SAMP brings it up, and it stays. SAMP or
  UP/DOWN move through the slots. The track plays the outlined one, so its [TRIG]
  previews it. YES (or pushing SAMP) keeps it, NO puts SAMP back as it was, and FUNC + YES
  opens the browser. A page key keeps it, as YES does. The DT2's header goes in the title
  bar ("YES:OK NO:X FN+YES:D"), then the bank (the DN2's one bank, A) and five slots with
  their long names; an empty slot is "---".
- **The browser** (ASSIGN SAMPLE > A0nn): the import tool's folders first, then the
  samples that are in none; a folder's samples inside it. YES/RIGHT opens a folder or
  gives the track the sample, NO/LEFT goes back up, and out at the top. Every sample is
  already in RAM (the pool loads whole at power-on), so picking one only sets SAMP. The
  DT2 copies a +Drive sample into the slot instead.
- **Long names and folders**: the import tool writes a block after the image
  (`META_*`: each slot's folder and name up to 35 characters, 64 folders), pointed at from
  the directory page (`META_PTR`). link.c reads it with the directory. A long name shows
  only while the slot's short name is still what the tool made of it, so a rename on the
  instrument wins. Older firmware ignores the block.
- **Modulation on SAMP** (an LFO, or any of the six sources) steps through the slots that
  hold something, from the one SAMP is set to, wrapping round them, as the DT2's project
  slots hold only loaded samples. Before, it mostly landed on empty slots and played
  nothing. `smp_mod_apply` runs after the stock apply (`0x400db22c`, at `0x40027196`) on
  the per-voice mirror the frame is built from; an unmodulated SAMP is left alone.
- **WERP's SEG** takes three detents a choice, not one (owner: the middle choice was easy
  to skip).

### v0.25: after a recording, as the DT2 (the owner's v0.24 report and photos)

- **The keys.** The DN2's key items carry a bit (1 of the flags word) that v0.22..v0.24
  read as "FUNC held". On the instrument a plain YES carries it too, so YES on TRIM and
  YES on a SLICE track's page did nothing (the emulator's panel never set it). FUNC is now
  kept by `smp_ui_pop` itself (`smp_func_held`), from every FUNC press and release, for
  the recorder, the list, the browser and SLICE; nothing reads that bit.
- **RECORDING.** While the DSP records, the RECORDER shows the DT2's recording screen: the
  meter, the waveform as it comes in (`rec_wave`: 120 columns of the status's peaks; when
  it passes the last, columns pair up), the time, YES: STOP.
- **SAVING, NORMALIZING.** When it stops, the recording is read back and saved to the
  +Drive as before (`smp_save_recording`), and its peak noted (`peak_add`). Below 32,700
  (and above 64: silence stays as it is), it is normalised to 32,700, the DT2's
  "NORMALIZING...": the +Drive's copy a chunk a pass (`norm_chunk`, a 16.16 gain in
  32-bit arithmetic), then the DSP's through the loader's own path (read, sent,
  VERIFY-checked), the overview redrawn from it. The screen shows which, with a bar.
- **TRIM** (the DT2's 13.2 step 9): Y:SAVE keeps START..END and goes on to the name;
  FN+N:DEL drops the recording; **FN+Y plays START..END while FUNC + YES are held**
  (letting either go stops it); there is no "NO: ALL". E and H move START and END: a
  detent a 1,000th of the recording, up to 12 times that as the knob turns faster, a
  10,000th with FUNC held; the screen is redrawn on each turn.
- **FILE NAME**: U/D the character, L/R the cursor, FN+NO deletes the character at the
  cursor, FN+YES inserts a space there, YES saves, NO keeps the name it has. Seven
  characters (the instrument's slot names).
- **ASSIGN SAMPLE TO TRACK?** over the trim screen: a [TRIG] key, or NO to skip. The
  recording is on the +Drive either way.
- **The preview on the DSP** (`dnfw.sampler.program.pvmix`, `CMD_PREVIEW`). Nothing in the
  sample machines can play a slot without a track's voice (whose amp is shut without a
  note), so the preview is added to the main mix after the engine has made it: the
  per-block driver's call of 0x1c9d3f (the mix into the SPORT page, sw 0x1c9fd2: `CJUMP
  0x1c9d3f (DB)` and its two delay-slot pushes) becomes `JUMP wr_pvmix`. wr_pvmix saves
  every register it uses (R0..R3, R12, R13, I1, ASTAT), adds the preview's next 32 frames
  to both sides of the mix, restores them, and makes the stock's call itself with the
  stock's own three instructions (copied in by the build, `dsp.pvmix_object`); the callee
  returns through the C stack's word to 0x1c9fdb as before. The SHARC runner's step 3f
  runs the site to its return on the stock image and on the build: with no preview the
  two are identical in every register and every word written; with one, the build is
  exactly the stock run on the block the model mixes, every register and every word but
  the preview's own. The command (slot, first frame, end frame) is taken by the recorder;
  the status's state word carries +16 while one plays. 219 bytes of the DSP's 1 MiB upload
  buffer are left.

### v0.25: GRID and SLICE: slices to the trigs, KEYBOARD's octave, GRID's icon

- **ALLOCATE SLICE** (the DT2's, its manual A.2.6): YES on a GRID track's page opens
  CREATE LINEAR LOCKS / CREATE RANDOM LOCKS / NO: CANCEL LOCKS; SLICE's menu gains the two
  as well. LINEAR locks SLICE to slice 1, 2, 3 .. on the track's note trigs in order
  (wrapping round the slices); RANDOM a slice at random each, again on each YES; NO puts
  back the SLICE locks there were. The locks are made through the stock's own calls, the
  path a held [TRIG] and a turned knob take (found in the emulator: GRID RECORDING, a held
  trig, a knob turn reach `0x4003ceee` through the active track's parameter set's vtable at
  `0x401db7fc`: +0x40 GET, +0x44 SET (value << 8, as setValue), +0x48 CLEAR); a track's
  note trigs come from its pattern track (`0x4003b2ea(0x4003efa8(owner), track)`, its
  length `0x4004f896`, a note trig at a step `0x4004f0f4`). Gate step 6g.
- **KEYBOARD**, SLICE at NOTE, GRID as well as SLICE: [TRIG] k plays slice k, and the
  keyboard's octave (stock's: KEYBOARD + UP/DOWN) moves the keys on by 16 slices an octave
  (the octave read from the note stock gives [TRIG 9]: 60 at the middle octave).
- **GRID's icon** on page 1: its slice count as a grid of cells, 2 x 1 to 8 x 8.
- **FILE NAME's grid** (the owner's photo of the DT2's): while FUNC is held, the name sits
  over a grid of the characters a slot name takes (A-Z, - _, 0-9, space); FUNC + the arrows
  move through it, and letting FUNC go puts the picked character at the cursor (a blank
  opens the grid at A). FUNC + YES and FUNC + NO still insert and delete.

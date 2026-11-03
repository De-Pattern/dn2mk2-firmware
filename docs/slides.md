# Parameter slides (A4 mk2 / Overtone style)

The owner asked for "Overtone/A4 mk2-style parameter slides". A trig with **SLIDE** on
glides every continuous parameter its p-locks change, from the value the track had to the
locked one, over the slide length **SLEN**, instead of jumping. With SLIDE off (or on a
trig with no p-lock) everything is stock's, byte for byte.

Code: `csrc/slides/slide.c`, `csrc/slides/hooks.S`, constants and the slot tables in
`src/dnfw/slides.py`, the hooks written by `dnfw.waverider.coldfire.compose` (part of the
`waverider` mod, so of every release build). Check: `scripts/emu_slides.py`, the ship
gate's step **"parameter slides (ColdFire)"**. Background reading: `docs/overtone-map.md`
(how Overtone 1.2 does it; this design follows its shape, not its code or its ids).

## Using it

**TRIG page, second page** ("Retrig Parameters (2/2)"): its two empty places, under RTRG
and VFAD, are now **SLD** (encoder **E**) and **SLEN** (encoder **F**).

- Hold a trig (in GRID RECORDING, as for any p-lock) and turn **E** right: SLIDE ON for
  that trig; left: OFF. Turn **F**: its length. Every held trig gets the value. A trig's
  own value is drawn inverted (filled), as stock draws a p-lock.
- No trig held: the places show what a trig gets without a lock (OFF, 1 step); turning
  does nothing (there is no per-sound or per-track default).
- The trig's other p-locks are set as usual (hold the trig, turn the parameter).
- Removing a trig (or placing one, which stock does by clearing the step) clears its SLD
  and SLEN with its other locks. Releasing a held trig after turning E/F leaves it on, as
  with any p-lock. Copy and paste carry SLD/SLEN as they carry the trig's other locks
  (v0.40; "Copy and paste" below).

**SLEN** (steps of the track, its own scale followed, at the current tempo):
`1/8 1/4 1/2 3/4 1 1.5 2 3 4 6 8 12 16 32 64`; a SLIDE trig with no SLEN lock uses **1**.
At 120 BPM and 1x, 1 step is 125 ms (187.5 audio frames).

## What slides

A slot slides when the trig's lock list names it, it is continuous for the voice's machine,
and its value before the trig differs from the lock. Continuous (`dnfw.slides.masks`, from
the stock parameter table: every record naming the slot spans at least 0x2000, i.e. 32
panel steps):

- **every machine**: filter FREQ/RESO (or the variant's second), the filter envelope
  (DEL ATK DEC SUS REL ENV BASE WDTH KEY.T), the amp envelope, PAN/BAL, VOL, PTIM, the
  three FX sends, BR, SRR, OVER, and each LFO's SPD, FADE, SLEW/SPH and DEP;
- **FM TONE, WAVETONE, FM DRUM, SWARMER**: their machine page's continuous controls
  (e.g. FM TONE's DTUN FDBK MIX, the envelopes, levels, offsets, HARM; not ALGO, RATIO C/B);
- **never**: an LFO's DEST, MULT, WAVE, MODE; the EQ filter's TYPE (slot 66, which is
  then left out for every filter, the multimode's morph included); on/off and routing
  switches; trig-page values (NOTE, VEL, LEN: they are not mirror slots).
- **PERC, the Monomachine machines and the sample machines (types 5..)**: only the shared
  slots above; their own SYN controls never slide (they include choices like TYPE and SAMP,
  which a glide would step through). MIDI tracks: nothing.

A trig with SLIDE and no stock p-lock slides nothing. Reverting a slot that the previous
trig had locked (and this one does not) jumps, as stock.

## How it works (1.11 addresses)

The per-voice mirror (`docs/fx-master-modulation.md` 4c) has three arrays, word index
`17 + 101 v + s` for voice `v`, slot `s`: the target the sound and the locks write
(**SRC**, `0x80003af0`), the one-pole smoother's 16.16 state (**STATE**, `0x8000de60`), and
its output the frame is built from (**OUT**, `0x800068e4`). The voice's track is
`0x80005308[v]` (written at `0x40026a3c`), its sound `0x800052a8[v]`.

| site | stock | hook |
|---|---|---|
| `0x40026bac` | a note's voice block in the frame ISR (`movea.l %d2,%a4 ; move.l 64(%a0),%d0`) | `sl_pre(voice, track)`: the voice's running slide ends; once a frame per track, the track's values before the trig (STATE of the voice it last played on) are kept |
| `0x400db092` | the lock applier (voice, list, mirror); both its callers (a note's voice, and the trigless loop) | `sl_apply`: stock's, then the slide: each slot of the list that slides gets STATE = before-value << 16 and joins the voice's slide |
| `0x4002717e` | `jsr 0x400db12a`, the smoother | `sl_smooth`: stock's, then each sliding slot one frame on: OUT and STATE = `from + (to - from) * frac`, frac from the elapsed time; before the modulation apply, so LFOs ride on top |
| `0x400d85e8` | the lock-list builder | `sl_build`: stock's, then the step's SLD/SLEN past the list's entries (+1600, magic `'SL'`, track, step; the pool's lists are 20 + 202 x 8 bytes, stock uses at most 828) |
| `0x4003d14e` | clear a step's locks | stock's, then the step's SLD/SLEN |
| `0x400de51e` | a pattern's lock table, stored -> RAM | stock's (it skips ids above 106), then records with id 200/201 back in |
| `0x400de718` | RAM -> stored | stock's, then our records' headers as ids 200/201 |
| `wr_cell`, `wr_screen`, `smp_ui_pop` (our own) | the page cell hook, the screen draw, the UI queue | the TRIG page's two places; E/F while it is up |

- **Landing.** At the end of the slide STATE is `to << 16` and SRC is `to`: the smoother
  rests there, exactly.
- **A knob turned mid-slide** (or anything else moving SRC: a new sound on the voice, a
  pattern change, the next trig): that slot leaves the slide the frame SRC stops being the
  target. STATE holds the slide's last value, so the smoother glides on from there, no jump.
- **Tempo**: the frame's BPM x 120 (frame word 108, as the recorder reads it) each frame;
  a tempo change mid-slide changes the rest of it. Elapsed time is in 1/24 step << 16:
  `inc = (bpm120 << 16) / 112500` a frame at 1x, scaled by 6 / ticks-a-step of the track's
  scale (`0x401f6b08`, the pattern's or the track's in per-track mode).
- **Stop / start**: a slide runs on its time and ends; nothing restarts it. **Pattern
  change**: the new pattern's sound on the voice moves SRC: the slide ends there.
- **Retrigs** re-apply the trig's locks: the slide goes on from where it is to the target.
- **Trigless lock trigs** (the applier's second caller): the slide starts from the voice's
  own current values.
- **Chords / unison**: every voice the trig gets slides, from the same track values.

## Storage, and old firmware

Each of SLD and SLEN is a lock record of its own in the pattern's stock lock pool (80
records `{u8 id, u8 track, u16[128]}`, shared by the tracks). In RAM the header is
`(0x50 SLD | 0x51 SLEN, track | 0x20)` (byte 0 kept inside 0..100, like a slot, in case a
stock loop indexes with it; the track tag makes every stock per-track loop pass over it,
as the arp p-locks proved on hardware). Stored: `(200 | 201, track)`; values 0/1 for SLD,
0..14 (the SLEN table's index) for SLEN, `0xffff` no lock. `docs/lock-id-table.md` has the
allocation. A pattern can hold at most 80 records, ours included (two per track using
slides).

A project saved here and opened on **stock firmware**: stock's LOAD skips ids above 106,
so the slides are dropped and everything else loads as saved (checked under the emulator:
the stock routine leaves our record free and every other byte as this build's LOAD does).
A stock save then frees them.

## What was checked (ColdFire emulator, `scripts/emu_slides.py`)

The sequencer does not run under the emulator, so a trig is what the frame ISR's note
block does for one, called in its order (the routines themselves, hooked as in the build);
every frame after it is the **real frame ISR** run to its rte. digikit's EMAC halves every
fractional product (measured: 0.5 x 0.5 = `0x10000000`), so the stock smoother decays under
it; the harness runs the instrument's arithmetic at `0x400db12a`'s entry instead (the OFF
comparison is made both ways). See the gate step's record for the numbers; the first run
(2026-11-01, tempo 81 BPM in the snapshot) gave:

- SLIDE on, SLEN 1 step: FREQ `0x1000 -> 0x6000` and FM TONE FDBK `0x800 -> 0x7000` over
  **278 frames** (185 ms = one 16th at 81 BPM), every frame equal to the model, monotonic,
  landing exactly on the lock and staying there.
- SLIDE off: 70 frames of the whole STATE and OUT arrays identical to stock 1.11's, with
  the emulator's EMAC and with the model.
- A knob mid-slide (FREQ's SRC moved): FREQ leaves (`0x1b84 -> 0x1ba6`, then glides to the
  new value), FDBK slides on exactly. Tempo doubled mid-slide: exact, lands at frame 154.
  Trigless lock with SLIDE (1/2 step): `0x6000 -> 0x3000` exact. A trig with SLIDE and no
  p-lock: no slide. A new sound on the voice: the slide ends. Retrig: on from where it was.
- SAVE writes ids 200/201 with a plain track; LOAD brings every record back byte for byte;
  stock's LOAD of the same stored table skips ours and is otherwise identical; a stock
  pattern saves and loads byte-identically on both. Step clear removes the step's SLD/SLEN.
- The TRIG page driven through the panel: page 2 draws SLD/SLEN, page 1 does not; holding
  a trig and turning E/F writes the locks; no fault.

## Not verified (hardware)

- The sound. Every number above is the ColdFire's arrays; the DSP's reading of them is
  stock's, but nobody has heard a slide yet.
- The sequencer path itself: that `0x40026bac` and the applier run for real trigs, retrigs
  and trigless trigs as read here, and that frame word 108 is the BPM x 120 while playing
  (the recorder relies on it).
- **Settled (emulator, 2026-11-02):** a trig held in GRID RECORDING, E/F turned, released
  stays on with its step unchanged, as with a stock p-lock. Measured on stock too: a long
  hold's release never removes a trig (only a tap does), and pressing an empty step places a
  trig on the press; holding an empty step and turning E leaves that trig placed, exactly as
  holding it and turning a stock parameter does. Nothing to mark "used". E/F record nothing
  in LIVE recording (they are set on held trigs only, like the arp p-locks).
- Copy and paste on the unit (v0.40): checked under the emulator only (below).
- Overtone patterns: Overtone stores its slides as ids 115/116; we do not read them.

## Copy and paste (v0.40)

v0.39 carried nothing: stock's copies match lock records by track and ours are tagged, and
the trig copy keeps a slot/value list of its own. FUNC + RECORD, PLAY, STOP as the gate drove
is a track copy, clear and paste: the clear (`0x400e745c`) frees the track's records by their
track byte (ours, tagged, stayed), and the paste clears every step of the track (`0x4003d14e`
on each, which clears ours too) and then pastes the clipboard's records, ours skipped: the
track's slides were all gone (v0.39's note that the paste "takes a record of ours" was this:
our emptied record freed, then reused).

The fix uses the arp p-locks' sites and shapes (`scripts/build_arp_plocks.py`, each path
driven through the UI there), `dnfw.slides.PASTE_SITES`, `csrc/slides/hooks.S`, `sl_paste`,
`sl_tcopy`, `sl_tpaste` in `slide.c`:

| site | path | what it does for ours |
|---|---|---|
| `0x40053246`, `0x40052634` | page paste, its UNDO | a clipboard record of ours of the copied track: its page's values onto the destination track |
| `0x4005389c`, `0x40052948` | track paste, its UNDO | the same, all 128 steps |
| `0x400e752c` | track clear (FUNC + PLAY, `0x400e745c`) | the track compare with the tag cleared: ours freed with the track's stock locks (v0.39 kept them) |
| `0x40051158`, `0x40050cce` | shift (FUNC + LEFT/RIGHT), page autocopy | the track compare with the tag cleared: ours move with their steps |
| `0x40053f48`, `0x40055440` | trig copy, trig paste | each copied trig's SLD/SLEN by clipboard entry (`sl_tclip`, 128), onto the pasted step |

Stock clears the destination steps before it pastes (through `sl_clear`), so a pasted step's
slides are the clipboard's, as its other locks are, and steps the paste does not cover keep
theirs. Pattern copy and paste copy the whole pattern (122,478 bytes, the lock table inside):
ours go with it as bytes. Gate (`slides`): copy, clear, paste through the panel restores every
SLD/SLEN of the track exactly, cleared with the stock locks (both fail on v0.39); trig copy
and paste puts step 6's on step 9 beside its stock lock; no value of ours in a stock record.
Not driven here: shift, autocopy and the UNDO paths (the arp's checks drove them).

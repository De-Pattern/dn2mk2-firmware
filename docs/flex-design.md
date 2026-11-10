# FLEX: live-buffer machine (design settled 2026-11-10, not yet built)

Owner, 2026-11-09 (first design) and 2026-11-10 (this revision, after the Discord discussion and
the review of BOUNCE). Replaces BOUNCE (removed in v0.48: docs/bounce-removal-plan.md). Built on
the coupled emulator (ColdFire and DSP together), so record -> buffer -> note-trig playback is
tested end to end before it ships. BOUNCE passed every separate check and played nothing on the
unit: its trigs fired and takes were made; the track never played its buffer.

## Purpose (owner, 2026-11-10)

Capture perfectly timed loops from CPU-heavy tracks while the sequencer runs, then play them from
FLEX with ordinary note trigs, and mute the source to free its DSP time. Example: track 1 an
expensive Monomachine patch; FLEX on track 16 records exactly 16 steps of it from a one-shot
recorder trig on step 1; a note trig on step 1 plays the loop; track 1 is muted.
Timing accuracy and reliable playback come first; nothing that compromises them goes in.

## Decisions (owner, 2026-11-10)

- **Single buffer** per FLEX buffer slot (always the owner's intent). No take swapping.
- **No Q.PLAY.** Playback is note trigs, already on the grid. BOUNCE's Q.PLAY (when a finished take
  replaced the playing one) was ours, not the Octatrack's, and is not carried over.
- **Q.REC: a trigless way to record.** YES while the sequencer runs waits for the next Q.REC
  boundary, then records R.LEN steps. ("Start at the next step 1" from Discord is Q.REC = PLEN.)
- **Playing while recording is allowed**, as the Octatrack: a note on the recorder trig's step
  plays the audio as it arrives. Pitched up, the playhead catches the write head (stock Octatrack
  behaviour too: accepted).
- **Saving a buffer as a sample: included.**
- **The BUS matrix: wanted, if it can be done elegantly and stably**; not essential. Built last;
  left out of v0.49 if it costs too much room, DSP time, memory or development time.
- **Stereo: out of scope.** Takes are the recorder's format.
- Four detents a choice on every multi-choice knob. Screens from the handoff's mockups (below).

## The core idea: a buffer is a region plus a valid-frames count, owned by the DSP

Each of the 8 buffers: an address and length in the recordings area (allocated on first record,
R.LEN at the tempo) and a **valid-frames** count. The DSP's recorder raises the count as it writes
and reports start, progress and end to the ColdFire (BOUNCE's ColdFire predicted the end with a
timer). A FLEX voice never reads past the count. So:
- a take that ends early or is cut off leaves exactly what was written, and plays that;
- a note during a recording plays what has arrived (one block, ~0.7 ms, behind the write head:
  the DSP renders voices before the recorder writes the block);
- nothing stale or uninitialised is ever heard.
Later seamless replacement (a second region, the pointer flipped at a safe point) fits this
without a redesign.

## Machine

- Type **19** (FASCIA 18; BOUNCE's 17 stays a silent stub).
- SYN page 1: A TUNE, B PLAY, C -, D **BUF**, E STRT, F LEN, G LOOP, H LEV (ONESHOT's, BUF in SAMP's
  place). BUF 01..08, a detent each over the knob's travel (BOUNCE's BUF: default 8, only the first
  8 clicks chose). STRT/LEN/LOOP: v0.48's fine controls, against the take's length.
- Playback is ONESHOT's DSP code reading the buffer, bounded by the valid count. A waveform of the
  take on the SYN page; `BUF01 EMPTY` with nothing recorded.

## Recording

Three ways to start a take, one recorder (the DSP has one), one owner at a time:
1. **Recorder trigs**: on their step, for R.LEN steps. Ordinary (every pass) or **one-shot**
   (records once, then spent; YES YES re-arms). New trigs default to one-shot: an ordinary trig
   left on a loop re-records over the bounce every pass.
2. **Q.REC** (manual, trigless): YES while playing waits for the next boundary (OFF, 1, 2, 4, 8,
   16, 32, 64, PLEN); OFF records at once. NO cancels while waiting.
3. **The recorder's own ARM / R.STRT** (threshold, transport start), as today.

The owner state machine (ColdFire): a manual take pending or running refuses recorder trigs
(`MANUAL REC`); a trig while a take runs is refused (`BUSY`), never cuts it; two FLEX tracks'
trigs on one step: the lower track records, the other shows `BUSY`. A one-shot is spent only when
the DSP confirms its take started. No silent truncation: `NO ROOM`.

- **Sources**: TRK1..16 (one track's own block: the bounce), IN, MAIN; BUS if built.
- **Saving** (FUNC + YES): the buffer's take into the next empty pool slot and the +Drive, as a
  manual recording (SAVING, NORMALIZING, TRIM, FILE NAME, ASSIGN). BOUNCE's bn_save.

## The resampling bus (if built)

As designed 2026-11-09: the sum of the selected tracks' blocks (dry, after the amp, each track's
LEVEL applied) into the recorder. A Syntakt-style matrix page: [TRIG n] toggles track n, a selected
cell drawn inverted, its LED lit; FLEX tracks out by default (struck until pressed in); default
every non-FLEX track in; stored per FLEX track and pattern. DSP cost: one add a sample a selected
track.

## Freeing the source's DSP time

Mute, not LEVEL: a muted track gets no note-on on stock (docs/mute-research.md); its voices end by
their release, and ours then rest (Machinedrum, VO-6). To measure for every machine family (SID
and the other Monomachine machines, stock FM) with the load meter in the emulator; any that do not
rest get a fix or a release note. A TRK take is before LEVEL and the sends: FLEX has its own.

## Screens (owner, 2026-11-10: the Elektron-style mockups)

The design is the two mockup sheets in `docs/flex-mockups/` (flex-screens-a.png, flex-screens-b.png):
Elektron's eight-cell encoder grid with a label, an icon and the value in each cell, the selected
or boxed value inverted (BUF 01, ARM ON), a title bar with the track and page, the [TRIG] grids
for REC TRIGS (REC filled, ONE hatched) and REC BUS (INCL filled, EXCL open, FLEX crossed), the
waveform with its range brackets, and the boxed messages (SAVE TAKE? YES/NO, SAVED AS SAMP n,
REC REFUSED / NO ROOM, BUF BUSY, WAIT REC with the Q.REC boundary). **Not** the pixel-text
screens in the handoff PDF's appendix (owner: not the design).

Changes from the sheets, by the decisions above: no QPLAY cell (that place: MON or empty); no
CHAN L+R (no stereo; the recorder's own CHAN as it is); the buffer menu's SAVE TO POOL is the
saving above (CLEAR, RENAME, COPY TO only if they fit). Drawn with the existing renderer, font
and icons; where a mockup's icon does not exist, the nearest existing one, or a new 1-bit icon in
the same style. Kept rules:
- Recorder trigs also on the [TRIG] LEDs (bn_led_walk/bn_led_poll, branch v047's history): red a
  trig, yellow a one-shot, dim yellow spent.
- Every value of a control at the same place, size and baseline; every choice fits its cell;
  status lines and boxes fit. Gate: every control through every value (four detents a choice),
  every status drawn, the pixels inside their cell or box.

## Also in v0.49 (owner, 2026-11-10): the guard

NiKo's report (v0.47: SID + three PERC, an ONESHOT kick crunchy at ~85 %): the frame-time guard left
the sample voice out block after block (a sample voice is retried every block, so it flickered).
- Render the sample voices first, so time runs out on the heavy ones.
- A sample voice left out is stopped until its next note (as PERC's), never flickers.
Tested with the runner's stress scenario plus SID + PERC with an ONESHOT on a later track.

## Tests (gate)

- Coupled: a one-shot recorder trig on step 1, a 16-step take of a track, a FLEX note trig playing
  it, its render (read after the voices, before the stock chain) against the source; Q.REC; a note
  on the trig's step during the take; an interrupted take; the one-shot spent; negative controls
  that fail at their link.
- BUF through the knob from its default, every detent; every REC SETUP choice its 4 detents.
- The screens' text-fit check. Old BOUNCE projects still load silent (bouncegone).
- Room: the image size and the DSP time with FLEX on 16 tracks.

## Room (v0.48)

ColdFire 2,076,257 of 2,097,152 bytes stored (20,895 free); DSP 1,010,704 of 1,048,575 (37,871
free). v0.47 with BOUNCE was 2,080,802; FASCIA added about 15 KB (not in v0.49 unless FLEX leaves room).

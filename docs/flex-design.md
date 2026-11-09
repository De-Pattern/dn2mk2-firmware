# FLEX: live-buffer machine (design, not yet built)

Owner, 2026-11-09. Replaces BOUNCE (removed in v0.48: docs/bounce-removal-plan.md). Built **after**
the emulator runs the ColdFire and the DSP together, so the whole record -> buffer -> note-trig
playback path is tested before it ships (BOUNCE passed every separate check and played nothing on
the unit: its recorder trigs fired and takes were made, the playback never sounded).

Sources: the owner's FLEX handoff (DN2mk2_FLEX_Implementation_Handoff.pdf, GPT, 2026-11-09) for the
behaviour; its mockups are superseded. The owner's rules for the screens:
- SYN pages: Elektron's eight-encoder grid, icons, value fields and page navigation.
- RECORDER: the existing DT2-style recorder (meter, labels, controls, waveform).
- Waveforms: the existing waveform drawing and DT2-style trim markers.
- Recorder trigs: shown on the 16 physical keys' LEDs (v0.45..v0.47's bn_led_walk/bn_led_poll,
  in git history on branch v047).
Every screen 128 x 64, drawn with the existing renderer.

## Machine

- A new type: **19** (FASCIA is 18). BOUNCE's 17 stays a silent compatibility stub (v0.48).
- SYN page 1: A TUNE, B PLAY, C -, D **BUF**, E STRT, F LEN, G LOOP, H LEV (ONESHOT's, with BUF in
  SAMP's place).
- **BUF: 01..08 over the knob's whole travel, a detent each** (BOUNCE's BUF sat on a 0..100 record
  read as "anything over 7 is 8": the default was BUF 8 and only the first 8 clicks chose). Tested by
  turning the knob from its default, not by writing the value.
- The track plays its buffer through its **own note trigs**, as ONESHOT does. A waveform of the take
  on the SYN page; `BUF01 EMPTY` with nothing recorded.

## Recording

- FUNC + VOICE: **FLEX REC**, two pages:
  - **REC TRIGS** (on entry): [TRIG 1..16] toggle recorder trigs on the page's steps; FUNC + [TRIG]
    a one-shot. The trig LEDs show them (red a trig, yellow a one-shot, dim yellow spent). Status
    lines and the take's waveform.
  - **REC SETUP** (RIGHT): A SRC, B CHAN, C DEST, D RLEN, E ARM, F QREC, G QPLAY, H -. Four-click
    detents on every choice.
- **Sources** (A SRC):
  - **BUS** (default): the resampling bus (below).
  - **TRK1..16**: one track's own block (today's TRK source).
  - **IN**: the inputs.
  - **MAIN**: the whole mix as heard, FLEX tracks included: the feedback choice, labelled so.
- A take is heard only once it is complete; the previous take plays until then. A one-shot is
  spent only when the DSP confirms the take started. No silent truncation: `NO ROOM`, `BUSY`.

## The resampling bus (owner, 2026-11-09)

- What it records: the sum of the selected tracks' own blocks (the DSP already keeps one per
  track: SM.TRK_BUF, the source of TRK1..16 today), fed to the existing recorder. Elektron's mixer
  and the MAIN output are untouched; the DSP cost is one add a sample a selected track.
- **Selection: a matrix page, as the Syntakt's routing page.** Two rows of eight numbered cells (the
  16 tracks). **[TRIG n] toggles track n**: a selected track's cell is drawn **inverted** (filled,
  its number cut out), as a p-locked parameter is highlighted, and its key's LED lit; pressed again,
  it is removed.
- **FLEX tracks are out by default** (every FLEX track, not only the recording one, so two FLEX
  tracks never feed each other). A FLEX track's cell is drawn struck until deliberately pressed in.
- Default: every non-FLEX track in.
- **Dry**: each block is taken after the track's amp, before pan, the track's LEVEL, the send
  effects and the master section. Each track's LEVEL is applied in the bus (the ColdFire knows it),
  so the balance is as heard. Send-effect returns in the bus: only after research shows they can
  be tapped safely.
- Stored per FLEX owner track and pattern, with the other REC SETUP values.

## DSP work (the release blockers)

1. **Start and completion acknowledgements** from the DSP's recorder (today the ColdFire predicts
   the end with a timer).
2. **Which buffer each voice is reading**, so a half is never overwritten while a note plays it
   (or, conservatively, refuse a third take while any voice of that buffer sounds: `BUF BUSY`).
3. **The bus source**: the selected tracks' blocks summed into the recorder's input, with each
   track's level.
4. Per-half waveform peaks for the display (approximate peaks from the meter acceptable at first).
5. MAIN's reported silence on some units checked on its own before anything builds on it.

## Tests (gate)

- The coupled emulator: a trig on a step -> the DSP records the chosen source -> the buffer's
  directory entry -> a FLEX note trig plays it, the track's own output compared with what was
  recorded. Every source (BUS with a chosen set, TRK, IN, MAIN).
- BUF through the knob from its default, every detent.
- The matrix: [TRIG n] toggles, the inverted cells, the LEDs, FLEX tracks excluded by default.
- Old projects with BOUNCE tracks still load silent (v0.48's bouncegone step).
- Room: the image size and the DSP time with FLEX playing on 16 tracks, within the limits.

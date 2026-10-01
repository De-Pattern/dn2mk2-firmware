# Showing modulation on the controls (UI/UX study)

**The idea (owner, 2026-10-01).** LFO modulation is invisible on the Digitone II: the controls show the value you set and never move. Only MIDI modulation moves them, because it changes the value itself, and that is what we don't want. You need to see and tweak the value you set, and also see how the modulation moves it. This is a study of how to draw that on each kind of control without disturbing how it shows the value you set.

Live mockups of every option: https://claude.ai/artifact/GUC8G2HWWx4sjhPZjVKc4g (the page simulates one LFO with a set value, a depth, a speed and a wave).

Grades: **[D]** read statically, **[E]** measured in an emulator, **[O]** open.

## What the firmware gives us [D]

- **The LFOs run on the ColdFire,** the processor that draws the screen (`docs/engine-state.md`, "modulation is applied on the ColdFire").
- **Each audio tick** runs two steps:
  - `0x400db12a(0x80003af0)` copies every sound's values into a per-track array. It smooths them first, with a one-pole filter in the MAC unit (coefficients `0x7c29` and `0x03d7`). The array is around `0x800068e4`, 202 bytes a track, with parameter *i* at `+34 + 2i`.
  - `0x400db22c` then adds each modulator into the array in place (kernel `0x400db1dc`: `value − depth × source`, saturated). It uses four descriptors per modulator, at `track + 3476…`.
- **So both numbers exist side by side:** the sound holds the value you set, and the array holds the value you hear. The difference covers every modulation source, not only the LFOs.
- **The range** needs no depth decoding: keep the lowest and highest value heard over the last few cycles, and let it relax when the modulation stops.
- **The emulator doesn't run the audio tick** [E]: `0x400db22c` and `0x400db1dc` never execute in the `wr-ui800M` snapshot. A prototype has to call the evaluator itself (as `scripts/lfo4_harness.py` does), or write test values into the array.

**Open [O]** at the time, both answered on the instrument below ("As built on Waverider"):
- the array's address and layout, read live on the instrument (usbprobe PEEK while an LFO runs);
- how to ask a page to redraw at about 25 Hz while something on it is modulated. Today it redraws when a value changes.

## The representation types (emulator sweep, 2026-10-01) [E]

About 100 screens were captured: every SYN page of FM Tone, FM Drum, WaveTone, Swarmer and MIDI (Waverider's are in `docs/waverider-m7-pages.md`); FLTR pages 1–2 for all six filter machines; AMP, FX and MOD; the Delay, Reverb and Chorus pages; and Compressor, Internal Mixer ×2, FX Mixer and External Mixer. Every control falls into one of nine stock types, plus our own strip:

| # | type | where it appears |
|---|---|---|
| 1 | dial, uni- or bipolar (−/+) | ENV, DEP, WID; OVER, TIME, ADEL, TRAN, MVP |
| 2 | vertical fader | LEV1/2, VOL, T.LEV, N.LEV, NLEV, IN LR, the mixer's TRK1–16 |
| 3 | horizontal slider | compressor ATK/REL, FM Tone's X/Y MIX, WaveTone's OFS1/2 |
| 4 | number box | TUNE, TUN1/2, RATIO, RATIO OFFSET, KEY.T, MULT, KEY TRACK, ALGO, MIDI VAL1–16 |
| 5 | morphing glyph (the drawing is the value) | WAV1/2, PD1/2, SWRM, MAIN, ANIM, STIM, FOLD, HARM, FDBK, BR, SRR, MOD, DRIF, CHAR, GRAN, DEL/REV/CHR sends, THR, RAT, SCF |
| 6 | graph across cells (several parameters, one drawing) | the envelopes; FREQ/RESO, FREQ/FDBK/LPF, FREQ/GAIN/Q; BASE/WDTH; FM Tone's A/B envelope bars; send FX HPF/LPF, FREQ/GAIN |
| 7 | discrete choice, toggles included | filter TYPE, TBL1/2, M.OCT, MODE, PRE FLTR, GRAIN NOISE, PHRT, DEST; RSET, ATRG, ARST, N.RST, N.RM, DUAL |
| 8 | pan / balance | PAN, BAL |
| 9 | tick scale with a pointer | Swarmer's DET and MIX |
| 10 | Waverider strip (ours) | TUNE, POS, TBL, … |

Which of these can actually be an LFO destination is a subset; the DEST list is in `docs/modulation-mask.md`.

## One grammar for all of them

- **Solid** is the value you set, drawn exactly as today.
- **Dotted** is the range the modulation sweeps.
- **A marker** (a dot, tick or hollow pointer) is the value heard now.
- **Nothing extra** is drawn when a parameter isn't modulated.

Markers go into pixels the stock widget leaves empty (the cell's 1–2 px margin), so the base drawing is never changed.

## Three options per type

| type | A | B | C | recommended |
|---|---|---|---|---|
| dial | orbit dot outside the rim | **range arc outside the rim + orbit dot** | dotted ghost needle inside | B |
| vertical fader | side tick | **dotted side rail + tick** | inverted line across the fader | B |
| horizontal slider | tick under the track | **dotted underline + tick** | inverted notch in the edge | B |
| number box | dot along the bottom edge | **bottom edge dotted over the range + marker** | pulsing badge; hold the knob to see the number heard | B |
| morphing glyph | dotted ghost glyph at the value heard | **glyph still, dotted meter under it + dot** | badge; the glyph morphs live while the knob is held | B |
| graph across cells | **dotted ghost curve as it sounds** | hollow handle echo on the floor | dotted floor rail + tick | A |
| discrete choice | **hollow pointer at the choice heard** | box round the choice heard | badge + number of choices visited | A |
| pan / balance | tick above | **dotted bracket above + tick** | dotted ghost centre line | B |
| tick scale | **hollow pointer under the scale** | baseline dotted over the range + pointer | the nearest tick grows | A |
| Waverider strip | dot below the track | dotted row below + dot | **hollow marker; the big wave already draws what you hear** | C |

## The owner's choice (2026-10-01)

The recommended option everywhere, except **9 (tick scale)** and **10 (Waverider strip)**, which take **option B**:

| type | chosen |
|---|---|
| dial | B: range arc outside the rim + orbit dot |
| vertical fader | B: dotted side rail + tick |
| horizontal slider | B: dotted underline + tick |
| number box | B: bottom edge dotted over the range + marker |
| morphing glyph | B: glyph still, dotted meter under it + dot |
| graph across cells | A: dotted ghost curve as it sounds |
| discrete choice | A: hollow pointer at the choice heard |
| pan / balance | B: dotted bracket above + tick |
| tick scale | **B**: baseline dotted over the range + hollow pointer |
| Waverider strip | **B**: dotted row below the track + dot |

**On refreshing.** The owner proposed a static bracket worked out from the settings, with the cursor animating only while a value changes; anything that avoids a constant refresh is welcome, and a constant refresh may be measured and decided on numbers. No stock capability may be hindered.
- The bracket can be computed from the settings: each LFO's DEST and DEP (bipolar waves ± DEP, unipolar one side), and the six performance sources' depths in their descriptor lists (`docs/modulation-matrix.md`). It only changes when a setting does, and that redraws the page anyway.
- Emulator [E]: the stock SYN page redraws on its own at rest (5 draws in 100 M instructions, each a screen frame) and several times faster while a knob turns (18 in about 40 M). So the cursor can live on the redraws that already happen; the emulator's clock cannot give the rate in Hz.
- The measurement builds `modview1` and `modview2` (`scripts/build_modview_probe.py`, `tools/dn2modview.py`) read the real redraw rate, the cost of one page draw, the markers' share, and the value heard, on the instrument.

## As built on Waverider (2026-10-01)

Grade **[I]**: measured on the instrument, over the usbprobe, with the owner at the panel. Builds `modview1` … `modview4g`; the readings are in `out/modview.csv` and the owner's test plan.

### What the instrument showed

- **The redraw rate [I].** At rest, and while a pattern plays with LFOs moving a parameter, the stock UI redraws a shown page **once a second**. Turning a knob redraws it at **~26 a second**. One Waverider page draw costs **~1.4 ms**, so 25 a second is **~3.7 %** of the ColdFire: what turning a knob already costs. CPU load: ~61 % at rest, ~66 % turning.
- **The value heard [I]** is the array at `0x800068e4`, slot *s* of track *t* at `+34 + 202 t + 2 s`, **at the record's own scale**. POS 74 with no LFO reads `0x4a00` = 74 << 8. The emulator's half scale was wrong (corrected in `modview2b`).
- **It holds what was last heard.** It only follows the knob while notes play: stopped, a turn doesn't change it. So the markers show the modulation as an **offset, heard − target**, where the target array `0x80003af0` has the same layout, and draw it **around the knob's own value**. A turn moves the knob, the dot and the range together.
- **The redraw request [D, I].** The UI task polls its screen's dirty byte (`isDirty`, `0x4011d2f4`, screen +32) once a pass at `0x4002e464`, and redraws every view on it when set (`0x4011d32a`). The stock setter is `0x4011d2fe`; `View::invalidate` (`0x4011c7ba`) sets view +20 and then the screen's byte. `wr_poll` replaces that one call. While Waverider's page drew in the last 1.2 s and a marker would move, it sets the byte through the stock setter, at most every 5 ticks, then answers as stock. Off the page, or with nothing modulated, it adds no redraws (emulator control, and `modview3` at rest: 1 draw a second).
- **`0x466758b0` is not milliseconds [I].** It advances ~120 a second (239 in 2.0 s). The first cap, written as 40 "ms", held the page to ~4 redraws a second (`modview3`). Corrected in `docs/display-path.md`.
- **The LFO settings [I]** are the target array's slots 1–24, eight per LFO: SPD MULT FADE DEST WAVE SPH MODE DEP. DEST holds the destination's slot << 8 (`0x1a00` = POS). MULT raw 0–11 are 1…2K BPM (synced) and 12–23 are 1…2K fixed at 120 (raw 0 "1 BPM", 8 "256 BPM", 12 "1"). SPD `0x7000` = 48.
- **The tempo [I]** is BPM × 120 at `0x800026c2` (14400 at 120.0, 14520 at 121.0; three RAM snapshots, stopped). The SHARC's control frame carries a copy at `0x80005f38`.
- **Two LFOs on one destination [D]** (evaluator `0x40137726`, write-back `0x40137a8a`–`0x40137ad0`) add up. Each adds `(DEP − 0x4000) × 2 × wave` to the value the previous one left, clamped to 0…`0x7f00` at every step. LFO1's DEP `0x4c65` gives ±`0x18ca` (about ±25 of POS's 120), close to the ±`0x181b` the page learned on the instrument.
- **Before the first PLAY [I],** the engine's copy of a track is not the project's sound. Track 2 held defaults (no DEST, DEP 0, POS 3.0) while the page showed POS 60. So the preview stays empty until playback starts. That's faithful: nothing is modulated yet. The owner declined reading the LFO settings from the UI side to show the range earlier.
- **A positive FADE in FREE mode [I]:** after the fade, the value heard equals the knob (`0x2f00` on every read), so nothing is drawn.

### What Waverider's page draws (option B, and the owner's later choices)

- **Rate tiers** (the owner's choice D, mockups at https://claude.ai/artifact/CR7EEvwbHYo12sEQbcnGbH). The fastest LFO aimed at the parameter decides, with f = |SPD| × MULT × BPM / 30720 Hz (the manual's speed table, p. 64):
  - **up to 3 Hz** (a redraw rate's eighth): the dot under the label, the dotted range, and the wave as heard, with the LFO's dotted cursor under the position bar;
  - **3–12 Hz:** the dot over a 50 % dithered band, and the POS wave as the **two frames at the ends of the sweep**, with one pixel in nine filled between them;
  - **above 12 Hz:** the band and the two curves, no dot, `≈` beside the label, and no redraws asked for it.
- **The range** is the offset swept lately: an edge widens at once, holds 2 s, then relaxes. Only POS and TBL are marked: TUNE is pitch-converted in the array.
- **The wave** is drawn thin, as one solid span per column (Tonverk's Wavefinder draws a column the same way, 2–4 px tall). A span of 2 px or less is shrunk to its middle pixel, and each column joins its neighbour only across the gap. Drawing only a span's two edges split steep slopes into two traces (`modview4e`).

## Next

1. The stock widgets, through the per-parameter drawer `0x400169de` after its widget draw, per the chosen options and each widget's geometry. The redraw mechanism above already serves any page.
2. TUNE's marker: decode the pitch conversion in the array.
3. The opt-in: a PERSONALIZE toggle and a key combo (`docs/ideas-backlog.md` §30), after Waverider.

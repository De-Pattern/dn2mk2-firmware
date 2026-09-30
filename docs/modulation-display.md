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

**Open [O]:**
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

## Next

1. The owner picks the options, on the mockup page.
2. Read the array live on the instrument, with an LFO running, to confirm where "the value heard" lives.
3. Prototype on Waverider's own page first (we own its drawing): markers for TUNE and POS.
4. Then the stock widgets, through the per-parameter drawer `0x400169de` after its widget draw, per widget geometry. Solve the redraw cadence alongside.

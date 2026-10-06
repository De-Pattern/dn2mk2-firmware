# GRAINS: a grain oscillator machine for the Digitone II

**Opened 2026-10-06.** A seventh machine for MACHINE SEL, in the spirit of the
Access Virus TI's grain-table oscillators: granular synthesis on wavetables,
not on samples. It reads the same tables Waverider plays, so anything loaded
for Waverider works here too.

Grades, as in the upstream docs: **[D]** designed / reasoned, **[E]** measured
in an emulator or model, **[H]** on the instrument, **[O]** open.

## State

| part | state |
|---|---|
| reference model, `grains/model.py` | **[E]** SYNC and CLOUD modes, rendered to WAV (`grains/demos/`) |
| the pitch property (FMNT never moves the pitch) | **[E]** `test/test_grains_model.py`: 60 cases over FMNT, SIZE and WIN |
| the SPRD property (no subharmonic) | **[E]** same file, 3 cases |
| control layout | **[D]** proposed below, awaiting the owner's sign-off |
| machine slot (type 6) | **[D]** room for it is noted in `waverider-feasibility.md`, "Room for a seventh machine" |
| SHARC code | not started |
| DSP cost | **[D]** estimate only, below |

## How it sounds, and why

**SYNC mode.** A grain starts once per period of the played note, so the
note's pitch is the grain *rate*. Inside each grain the wave plays at the
note's frequency times `2^(FMNT/12)`, so FMNT moves a formant, the timbre,
while the pitch holds.

Each grain's envelope is FOF-style: a raised-cosine rise, then an exponential
decay whose time constant grows with SIZE. **That decay is load-bearing.** The
model's first draft used symmetric Hann windows that overlap-add to a constant.
With those, a whole-octave FMNT (+12, +24) joins the grains into one continuous
wave an octave or two up, and the note's pitch is lost. Overlapping
exponentials sum to a ramp that repeats every period, so each period keeps its
own attack at any FMNT. The test sweeps FMNT −12..+24 × SIZE 1..4 × WIN
0..1 and holds the pitch within 1 %.

**SPRD** reads each grain twice, formant pushed up and down by the same
amount. An earlier draft alternated the push between successive grains; that
makes every second period different and puts a subharmonic an octave down. It
is tested against.

**CLOUD mode** is classic asynchronous granular: DENS grains a second, each a
smooth bell SIZE × 10 ms long, playing the wave at the note's pitch, with
position scatter (JITR), pitch scatter (PJIT) and a drift through the table
(SCAN).

Every voice runs at most **4 grains** at once (oldest stolen), which bounds
the DSP cost.

## Controls (proposed)

| | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| **GRAIN** | TUNE | LEV | POS | TBL | FMNT ±24 st | SIZE | SPRD | MODE SYNC/CLOUD |
| **MOTION** | DENS | JITR | PJIT | SCAN | WIN | – | – | – |

## Stages

1. **G1** — GRAINS in MACHINE SEL as type 6, SYNC only: TUNE, POS, TBL, FMNT,
   SIZE. Reuses Waverider's table reader, directory and frame fields.
2. **G2** — SPRD, WIN, and its own pages (Waverider M7's page machinery).
3. **G3** — CLOUD: a per-voice RNG and the grain scheduler.

Each stage passes the upstream gates (`dnfw inspect`, boot from reset,
the SHARC runner against `grains/model.py` as the reference) before a flash.
The SHARC code is checked byte for byte against stock encodings for every
instruction form with an immediate (upstream's rule after the negative-shift
bug, `waverider-dsp-compare.md` §11). The engine's output is sanitised
(NaN/inf → 0, clamped) before the stock per-track chain, and every build must
pass the stock-unchanged gate and `docs/SAFETY.md`'s regression check.

## DSP budget [D]

- Measured upstream on the instrument: stock DN2 runs the SHARC at about
  **63 %**, leaving about **36 %**, roughly 240,000 cycles per 32-sample frame
  (`docs/sharc-load.md`).
- Waverider's reader costs 38 instructions a sample. A grain is one reader
  plus an envelope step: call it ~45. Four grains, ~180 a sample a voice;
  ~360 with SPRD.
- Sixteen voices × 4 grains × 32 samples ≈ 92,000 instructions a frame,
  about 40 % of the free time **if** one instruction were one cycle. The
  instrument showed stock code at several cycles an instruction (memory
  stalls), so this is measured with `tools/dn2sharc_load.py --idle` at G1,
  before anything is built on it.

## Limits

- GRAINS is built on the Waverider mod; Waverider and `lfo4` both own the
  stored-sound LOAD and are refused together upstream, so GRAINS inherits that.
- Tables: Waverider's geometry (16 frames × 512 points) until the +Drive pool
  lands (`docs/waverider-tables.md`).

# COMB- and COMB+: the Digitakt II's comb filters in the filter slot

**v0.20.** The DT2 (OS 1.15 on) has two comb filters on its filter page, COMB- and
COMB+. Here they are filter types 9 and 10 on the FLTR page, on any machine, after
GRAN (8). As with PING, SHFT and GRAN, one program (`dnfw.comb.program`) is both the
Python model and the SHARC code (`scripts/gen_comb_asm.py` writes `comb.asm` from the
same calls), and the SHARC gate holds the code to the model bit for bit.

Grades: **[D]** designed, **[E]** measured in the emulator or the SHARC runner, **[H]** on
the instrument, **[O]** open.

## What it is

A feedback comb: each sample, the track's signal plus the signal from a moment ago,
through a one-pole low-pass, fed back and clipped at ±1. The delay is one period of
FREQ's pitch, so the comb rings at that note and its harmonics; FDBK sets how long
it rings; DAMP darkens each pass, so high harmonics die first (plucked, then muted).
COMB- feeds back inverted: a hollow sound an octave down, odd harmonics only. The dry
signal passes at unity (there is no mix: the DT2 has none).

    FLTR page 1   FREQ FDBK  -   (Delay) DAMP  /  KEY.T
    FLTR page 2   the envelope's cells read -  /  BASE WDTH BW.RT RSET

| control | DN2 record | DT2 | what it does |
|---|---|---|---|
| FREQ | Frequency | FREQ | the comb's note: 69/127 of the knob is 220 Hz (A3), 12 steps an octave, 27.5 Hz .. 8.37 kHz |
| FDBK | Resonance | FDBK | the feedback, through the DT2's own 128-point curve (≈ 1 − (1 − x)^2.93) |
| DAMP | Env. Delay | LPF, reversed | 0 = open (the DT2's LPF 127, its default), up = darker |
| KEY.T | Key Tracking | KEY.T | the note moves FREQ: full = one FREQ step a semitone, from C3 (note 48) |

Unused cells read `-`. BASE and WDTH (the filter page's fixed band filter) still apply
after it.

## How it matches the DT2 [E]

Everything below was read from the DT2 1.17 image and run in the SHARC emulator
(research notes, kept outside the repository with the rest of Elektron's code):

- once a block (32 samples): `f = clamp(FREQ + KEY.T (note − 48) / 127)`;
  `hz = 220 · 2^((127 f − 69) / 12)`, below f = 33/127 a quadratic from fs/8191 to
  27.5 Hz, capped at 8372.016 Hz;
- the delay `D = fs / hz − 6 (1 − L)² (1 − 0.9 f²)` samples (the low-pass's own delay
  taken off so the comb stays in tune when damped), clamped to 1 .. 8191;
- feedback `A = ±T[127 fb]` from the DT2's table (128 float32 at DM 0x26B338 of its
  DSP image, read from the owner's copy at build time, linearly interpolated);
- the loop's low-pass: a TPT one-pole, `c = tan(π fc / fs) / (1 + tan)`,
  `fc = 22000 · clamp(L² + 0.2 f²) + 20` Hz;
- `y = clip(x + A · lp(line[n − D]), ±1)`, written back into the line, read with
  linear interpolation;
- within a block the gain ramps from the old A to the new and the read position
  cross-fades from the old delay to the new, so FREQ and FDBK sweep without zipper;
- a note on the track, or switching between COMB- and COMB+, resets it: the ring stops,
  and reads of the line not yet written since return 0 until it has wrapped.

The model matches the DT2 routine's output to within 2e-5 (exactly, in most cases)
over the four corners of FREQ / FDBK / LPF (`test/test_comb.py`, when the research
models are present). Cost: about 4,000 SHARC instructions a block per COMB track.

## Where it lives [D]

| what | where |
|---|---|
| code | L2 at sw `0xBED000` (span 0x2000); ping.asm jumps there for types 9 and 10 and it returns to PING's `wr_p_next` |
| state | DDR, 16 tracks × 64 bytes (`dsp.COMB_STATE_DDR`) |
| the DT2 feedback curve, exp2 | DDR (`dsp.COMB_TABLES_DDR`; exp2 is PERC's) |
| delay lines | DDR, 16 × 32 KB (8192 floats) at `0x81600000` |

## Tested

- **[E]** `test/test_comb.py`: against the DT2 model; the pitch; the ring and its bound;
  COMB-'s sign; reset on a note and on a type change; zero feedback is the dry signal;
  layout; the jumps between ping.asm and comb.asm; comb.asm is its generator's output;
  no committed source keeps an unresolved branch.
- **[E]** The SHARC gate's step 7c: COMB- and COMB+ on a PERC track (the MD's TRX-CY) and
  a WaveTone track, two settings each, 24 blocks: at comb.asm's entry the model runs on
  the DSP's memory, and at its return the track's buffer and state must equal the
  model's, bit for bit, every block; the comb must change the sound and stay within ±1.
- **[H]** to do on the instrument (FIRMWARE.md lists the steps).

## Open

- **[O]** The DT2's filter envelope (ENV depth into FREQ) is not there: the DN2's filter
  envelope is computed in the stock filter code, which COMB replaces. FREQ can be
  p-locked or modulated by an LFO instead.
- **[O]** The DT2 runs a comb per voice (32); here it is one per track, after the machine.

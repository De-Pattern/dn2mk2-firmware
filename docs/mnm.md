# The Monomachine's synth machines on the DN2 (v0.26, in progress)

Owner, 2026-10-25: *"i want to build the digipro, sid, and VO synth machines from the
elektron monomachine. you can erase the cz phase and resonator machines and just add these
alongside the dn2 synth machines as synth engines"* -- each its own entry in MACHINE SEL,
its page drawn as the Monomachine draws it (the owner's six screenshots from its manual).

## Where the algorithms come from

The owner's Monomachine SFX-6/60 OS 1.32B (`MNM_OS`, default `../mnm132/mnm_os1.32b.syx`,
sha256 `fe13c09f...a1710`). `../mnm132/research/` (outside the repository: Elektron's code)
records its layout: a ColdFire host (VMA 0x200000), two DSP56303s with a kernel each, and
an external image the kernels share (P/X/Y unified above 0x100000) holding every machine's
code and tables. `dnfw.mnm.rom` reads the tables from the owner's file at build time, as
`dnfw.md.rom` reads the Machinedrum's; nothing of Elektron's is in this repository.

The research tools there run each machine's own code in the DSP56300 emulator (from the
Machinedrum work, with DIV, CLB and NORMF added for the Monomachine's kernels) and record its
output (`golden/`, `MNM_GOLDEN`), and an integer model of each machine matches that output
bit for bit (`mnm_models.py`).

## How the Monomachine runs a voice (what the port keeps)

- **Blocks of 16 frames at 44.1 kHz** (2,756.25 a second). Each machine renders its
  oscillator at 4x (DPRO: 64 samples a block) or 12x (SID: 192), then a polyphase IIR
  decimator (five words of state, ten coefficients) brings it to 16.
- **The voice block**: 52 words from the host each update. The eight parameters are the
  knob positions (0..127) << 16 -- enumerated ones too: the DSP compares them with its own
  thresholds. Each machine has three entries: init (the machine was chosen), trig (a note),
  render (every block).
- **Pitch**: a word F, 2048 to the octave, 0..0x5800 (11 octaves); F = note x 2048 / 12 +
  floor(TUNE x 683 / 128), so TUNE spans -2..+2 semitones around 64; 440 Hz at F = 0x2F55
  (note 69, TUNE 64). The kernel turns F into the render's increment A through its 2048-word
  exponential table.

## The machines

| machine | id | parameters | what |
|---|---|---|---|
| DPRO-WAVE | 6 | WAVE WP WPM WPRS SYNC SFRQ --- TUNE | one of 32 single-cycle waves (512 x 12-bit), linear interpolation at 4x through a 512..1023-sample window that WP (swept by WPM) slides into the next wave; hard sync per block to SFRQ or the previous track's pitch |
| SID 6581 | 3 | PW PWAD PWRS WAVE MOD MSRC MFRQ TUNE | two 24-bit phase accumulators at 12x; TRI, SAW, PULS (swept), MIX (the chip's combined waves, a 4096-entry table), NOIS (two linked shift registers, sampled at the phase's wrap); RING, SYNC, R+S |
| VO-6 | 11 | VOC1 VOC2 V-SW VOIC CONS CLEN CVOL TUNE | (being modelled) |
| DPRO-DDRW | 32 | WAV1 MIX WAV2 TIME BR1 WID BR2 TUNE | (being modelled) |
| DPRO-DENS | 33 | PCH2 PCH3 PCH4 WAVE --- CHRL CHRW TUNE | (being modelled) |

**DPRO-BBOX** (24 drum samples, 63,049 words: about 189 KB) does not fit the firmware: the
whole image has 77 KB to spare under the 2 MiB the USB upgrade takes. **DDRW and DENS** read
the Monomachine's user Digibank (64 waves in its own flash), which is not in the OS file;
here they read the 32 ROM DigiPRO waves (twice).

## On the DN2

- **In PERC's voice** (`dnfw.md.voice`): a slot's words, the 44.1 kHz stream and its
  resampler to 48 kHz are the Machinedrum machines'; a Monomachine machine's render is two
  of its blocks (32 samples). The machine type picks the machine (not PERC's TYPE).
- **The DSL** (`dnfw.perc.dsl`, one program for the SHARC code and its model): `dnfw.mnm`
  (`wave.py`, `sid.py`, `dec.py` the shared decimator, a leaf subroutine). The 56300's
  48-bit phases are 32-bit integers here (DPRO: 21 fraction bits), its MACR rounding and
  the limiter's test a clamp.
- **The increments**: on the DSP each machine's `pitch` computes them in float from the
  DN2's pitch; `dnfw.mnm.exact` computes them in the Monomachine's integer arithmetic.

## Checks

`test/test_mnm.py`: every golden case of every machine in run mode, with the increments
exactly the Monomachine's, at 60 dB signal-to-error or better (DPRO-WAVE 63.8..99 dB, SID
94..110 dB so far); each machine's float `pitch` within 1e-4 of the exact increments.

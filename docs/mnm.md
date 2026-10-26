# The Monomachine's synth machines on the DN2 (v0.26)

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
| VO-6 | 11 | VOC1 VOC2 V-SW VOIC CONS CLEN CVOL TUNE | a band-limited pulse train (32-tap pulses, the kernel's table) and noise (VOIC mixes them) through four formant resonators in series (F1, F2 from VOC1, VOC2; F3, F4 fixed), the same four in parallel on the unvoiced source; an AGC, three internal envelopes (onset, the consonant's transition, the vowel gate), 21 consonants (CONS: their set-ups and renderers, CLEN, CVOL), a fixed output biquad. No oversampling |
| DPRO-DDRW | 32 | WAV1 MIX WAV2 TIME BR1 WID BR2 TUNE | two Digibank waves at 2x, each at its own pitch (WID detunes them up to -/+53 cents, scaled by 1 - abs(2 MIX - 1)), crossfading from the previous wave on a change (TIME), bit-reduced (BR1/BR2: 15 bits at 0 down to 3 at 127), each read at two mip levels crossfaded over the octave's top 1/16; MIX ramped over the block; the kernel's 2:1 allpass decimator |
| DPRO-DENS | 33 | PCH2 PCH3 PCH4 WAVE --- CHRL CHRW TUNE | four oscillators on one Digibank wave at 2x, three at PCH2..4's ratios (-12..+12 semitones and 2/3 3/4 4/5 5/6 6/5 5/4 4/3 3/2; the middle, 1.0, is OFF), band-limited by mip level with a crossfade over each octave's top 1/16 toward a partner sample held in the finer level's low bytes; mixed at 0.633 each (silent at 20 kHz and up, or at the first one's Hz); the 2:1 decimator. CHRL/CHRW are the Monomachine's chorus after the machine (not here) |

**DPRO-BBOX** (24 drum samples, 63,049 words: about 189 KB) does not fit the firmware: the
whole image has about 50 KB to spare under the 2 MiB the USB upgrade takes. **DDRW and DENS** read
the Monomachine's user Digibank (64 waves in its own flash, 2048 words a wave: nine mip
levels, 1024 >> L samples, each word a 16-bit sample << 8 with a crossfade partner's byte),
which is not in the OS file. Here the DSP builds a stand-in once the tables are filled
(`dnfw.mnm.dpro.build`, 8 outputs a block, about 8 s; DENS and DDRW are silent until it is
done): the 32 ROM DigiPRO waves through a 7-tap halfband chain (level 0 the ROM wave
upsampled, each level the last one's halfband, its even samples the next level and all of
them that level's partner), 256 KB of DDR (`core.DIGI_OFF`); wave n reads stack n & 31.
The golden runs load the same words (`dpro.digibank_reference`, the build run in run mode).

## On the DN2

| machine | DN2 machine type | MACHINE SEL |
|---|---|---|
| SID 6581 | 6 | SID 6581 / SID |
| DPRO-WAVE | 7 | DPRO Wave / DPW |
| DPRO-DDRW | 14 | DPRO Ddrw / DDW |
| DPRO-DENS | 15 | DPRO Dens / DNS |
| VO-6 | 16 | VO-6 / VO6 |

(`dnfw.mnm.machines.TYPES`: 6 and 7 were CZ's and RESONATOR's; 14.. follow the sample
machines. The ColdFire's type range, names, MACHINE SEL list and group, its pages' kinds
(is_wr: the type - 4) and the DSP's type lookup follow that one table.)

- **The DSP budget.** A Monomachine voice never goes quiet (as on the Monomachine: it plays
  until the next note; the DN2's amp envelope shapes what is heard), and one costs as much
  as two to ten Machinedrum voices: the model's worst case a DN2 block is about 55,000
  instructions (SID), 31,000 (WAVE), 70,000 (DDRW), 63,000 (DENS), 64,000 (VO-6). So each
  block PERC renders them in track order while their cost (`perc.program.MNM_COST`: SID
  60,000, WAVE 34,000, DDRW 78,000, DENS 70,000, VO-6 75,000) fits `MNM_BUDGET` (150,000);
  a track past it is silent that block. Two SIDs, four DPRO Waves, or one DDRW and one
  DENS, at once. The SHARC has about 250,000 cycles a frame free beside the stock engines
  (`docs/sharc-load.md`); the budget is to be raised or lowered from a reading on the
  instrument (`tools/dn2sharc_load.py`).
- **VO-6 is played 24 semitones down** (`machines.TRANSPOSE`): the Monomachine's kernel
  pitch puts its note 60 at 1046 Hz, two octaves over the others'.
- **Its AMP level** (y:(r6+175), the kernel's amp envelope, which gates the voiced path):
  that of an AMP attack of 0 (0 at the trig, then + 0x400000 a block to full), so its
  pre-delay is 0.
- **The knobs start where WaveTone's records are** when the machine is chosen (as PERC's
  do): the Monomachine's own defaults are not loaded (see FIRMWARE.md).

- **In PERC's voice** (`dnfw.md.voice`): a slot's words, the 44.1 kHz stream and its
  resampler to 48 kHz are the Machinedrum machines'; a Monomachine machine's render is two
  of its blocks (32 samples). The machine type picks the machine (not PERC's TYPE).
- **The DSL** (`dnfw.perc.dsl`, one program for the SHARC code and its model): `dnfw.mnm`
  (`wave.py`, `sid.py`, `dec.py` the shared decimator, a leaf subroutine). The 56300's
  48-bit phases are 32-bit integers here (DPRO: 21 fraction bits), its MACR rounding and
  the limiter's test a clamp.
- **The increments**: on the DSP each machine's `pitch` computes them in float from the
  DN2's pitch; `dnfw.mnm.exact` computes them in the Monomachine's integer arithmetic.

## The tables, over the fast link

The DSP image had about 50 KB to spare, so the tables no longer ride in it. The ColdFire
carries them (a CODE chunk at `TABLE_LOAD`, 0x47000000: magic, length, data) and sends them
first over the sample link at power-on (`csrc/sampler/link.c`, K_TABLES), to the pool's
table area (`dnfw.sampler.machines.TABLE_AREA`, 512 KB below the slice area); K_READY then
writes `TABLE_MAGIC` at `TABLE_READY`. The DSP's `table_fill` (`dnfw.md.core`) waits for
that word, then decodes zpack 2,048 words a block, as before. PERC's voices, the Machinedrum
machines' too, stay silent until the fill is whole (about 40 blocks).

What ships: the Machinedrum's host pitch table and zpack, which now also carries the
Monomachine's tables after the sine (`TABLE_LAYOUT["mnm"]`, starting a block). They are
stored compactly, and the fill restores them exactly:
- DPRO-WAVE's ROM words as (hi, lo) pairs (lo = the low 12 bits, signed; hi = the rest),
  which `_mnm_fix` turns back into (hi x 4096 + lo, lo x 4096): the word and its low sample
  << 12, exact in float (`dnfw.mnm.rom.packed_words`);
- SID's combined waveforms (8 bits << 16) as the 8 bits; `sid.py` scales them back.

The shipped tables came to 65 KB (94 KB with the words as they are).

## Checks

`test/test_mnm.py`: every golden case of every machine in run mode, with the increments
exactly the Monomachine's, at 60 dB signal-to-error or better (DPRO-WAVE 63.8..99 dB, SID
94..110 dB so far); each machine's float `pitch` within 1e-4 of the exact increments.

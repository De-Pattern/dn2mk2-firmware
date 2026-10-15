# SHFT: a frequency shifter in the filter slot

Owner, 2026-10-14: memory first, then SHFT. Built the PING way: a reference model and
audition WAVs first (`shft/model.py`, `shft/demos.py` -> `shft/demos/*.wav`), then the
DSP contract, the SHARC code and the FLTR page.

## What it is

A frequency shifter moves every partial by the same number of Hz (a pitch shifter
multiplies them). Harmonic sounds go metallic and bell-like; a few Hz beat and
shimmer; with feedback the shift climbs or falls for ever (the barber-pole).

As **filter type 7**, beside PING: on any machine, chosen in MACHINE SEL's FLTR tab.
It replaces the track's filter, so a SHFT track has no low-pass of its own; BASE and
WDTH (the filter page's second, fixed band filter) still apply after it.

    FLTR page 1   ATK  DEC  MIX  .   /  SHFT FDBK MODE ENV
    FLTR page 2   DRIV  .    .  KEY.T

| control | record | what it does |
|---|---|---|
| SHFT | Frequency | the shift, -2.5 kHz .. +2.5 kHz, cubic so the centre is fine; 64 = 0 |
| FDBK | Resonance | 0..0.95 of the output fed back through the shift, soft-clipped |
| MODE | Filter Type | thirds: UP, DOWN, BOTH (both sidebands: a clean ring modulation) |
| ENV | Env. Depth | the envelope's depth on the shift, +-2.5 kHz |
| ATK / DEC | Attack / Decay | the envelope, restarted by every note |
| MIX | Sustain Level | dry -> wet |
| DRIV | Env. Delay | level into the shifter |
| KEY.T | Key Tracking | the shift scales with the note (relative to C4) |

**How:** two chains of four all-passes in z^-2 make a quadrature pair 90 degrees apart
over the audio band (Olli Niemitalo's published IIR Hilbert coefficients); a
quadrature oscillator picks the sideband. Measured in the model: the unwanted sideband
is 47..58 dB down from 40 Hz to 12 kHz (32 dB at 200 Hz DOWN, where the image folds).

## Memory (2026-10-14)

Every run of 64+ zero bytes in our DSP payloads now goes into the boot stream as a
fill block (16 bytes, no payload), as the stock stream already does in the same L1
block. Memory after boot is identical; the stream is 10,592 bytes shorter: **15,699
bytes free** of the 1,048,575 upload limit (was 5,107). SHFT needs about 1.5 KB of code
and tables; its state is zeros, so it costs only a header.

The next big reserve is the 11 factory wavetables in DDR, 176 KB of the stream: they
could be generated on the DSP at boot from their partials (~3 KB each), or stored at
8 bits. That is the way to room for a Rings-style resonator and own tables.

## Audition WAVs

Each plays its phrase dry, then through SHFT.

1. `01_shimmer_3hz_chord` -- UP 3 Hz, MIX half: slow beating on a chord.
2. `02_metal_down_melody` -- DOWN 180 Hz: the melody turns metallic.
3. `03_barberpole_feedback` -- UP 6 Hz, FDBK 0.88: the endless climb.
4. `04_env_zaps` -- the envelope throws the shift on each hit (percussion).
5. `05_both_bells` -- BOTH at 333 Hz on a sine: ring-mod bells.
6. `06_sweep_full_range` -- the shift swept -2.5 .. +2.5 kHz on a held saw.
7. `07_keytracked` -- 130 Hz scaled with the note: the colour follows the melody.

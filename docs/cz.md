# CZ: a Casio CZ phase-distortion machine (planned, after RESONATOR)

Owner, 2026-10-18: *"a complex phase distortion engine based on the casio cz3000 with the
envelopes for synthesis built into subsequent pages in the synth machine ui? i would
like it to be as close as possible to the actual casio cz synths. cz-101 is another one
you could pull from, should be close to identical"*. The CZ-101, CZ-1000, CZ-3000 and
CZ-5000 share one engine; the 3000/5000 add oscillators (8 two-line voices), split,
chorus and wheels, not a different sound (Wikipedia, *Casio CZ synthesizers*) [R].

## The engine, as documented [R, to verify against the CZ-101 operation manual]

- **Phase distortion.** A cosine read through a bent phase: DCW (the "Digitally
  Controlled Wave") sets how far the phase is bent. Non-resonant waves at DCW 0 are a
  sine and at the top the full wave; the resonant waves sweep a resonance.
- **Eight waves:** saw, square, pulse, double sine, saw-pulse (half-sine in some
  sources), resonance I (saw window), II (triangle window), III (trapezoid window).
  A line can hold two waves, which alternate cycle by cycle (one octave down); two
  resonant waves cannot pair.
- **Two lines** (DCO-DCW-DCA each). Line select: 1, 2, 1+1', 1+2'. Line 2's detune
  (octave, note, fine). Ring modulation and noise modulation of line 2 by line 1.
- **Envelopes:** DCO (pitch), DCW and DCA for each line, 8 stages of rate and level
  (0-99), with a sustain point and an end point on any stage. Key follow: higher notes
  make DCW duller and DCA faster.
- **Vibrato:** one LFO a patch (triangle, square, up ramp, down ramp; delay, rate,
  depth), free per note. No LFO on DCW.

## How it would sit on the DN2 (to design)

A machine type 7 (after RESONATOR), a WaveTone clone for the ColdFire as Waverider and
RESONATOR are, with its own pages: page 1 the line and wave controls, then the three
envelopes on the pages after (rate / level pairs, the sustain and end points). It needs
its own parameter records (well over WaveTone's 25), which is option B of
`docs/waverider-m7-pages.md` (relocating the parameter table), and DSP memory: the
budget is 6.7 KB after RESONATOR, so the wavetables' reclaim (`docs/shft.md`) comes first.

First step as before: a reference model and audition WAVs, compared with recordings of
the real instrument's factory sounds.

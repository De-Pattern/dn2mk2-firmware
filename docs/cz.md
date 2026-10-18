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

## The limit that shapes it: 25 machine parameters a sound (2026-10-18)

A real CZ patch is about 120 values (three 8-step envelopes, 18 values each, per line).
A DN2 sound carries and saves 25 machine parameters, the ones every machine shares
(`docs/engine-index-map.md`: the runtime slots are full), and the frame to the DSP
carries the same 25. Giving the machine more would mean extending the saved sound,
which changes the project format: the one thing `docs/SAFETY.md` rules out.

So the CZ machine fits a CZ voice into 25 parameters. The records keep WaveTone's,
and their ranges are swapped at run time while a CZ track is active (as names already
are), so all 25 can run 0..127 on our own pages (shown as the CZ's 0..99).

Proposal (to confirm with the owner):

    page 1  LINE   WAVE A  WAVE B  SEL   DET   /  MOD   DCW   KF    OCT
    page 2  DCW    R1  R2  R3  R4  /  L1  L2  L3  L4
    page 3  DCW    R5  R6  R7  R8  /  L5  L6  L7  L8   (+ sustain and end steps)

- DCW gets the full 8-step CZ envelope (the CZ's character lives there).
- DCA is the DN2's own AMP envelope (attack, hold, decay, sustain, release).
- Both lines share the DCW envelope; line 2 has its own wave pair choice? No: SEL
  1 / 2 / 1+1' / 1+2' with line 2 detuned (DET, OCT) and ring / noise (MOD).
- The pitch envelope is the DN2's LFO / envelope routing, not a CZ DCO envelope.

Model first (`cz/model.py`, `cz/demos.py`): the eight waves, the envelopes, lines,
detune and ring, rendered to WAVs for the owner's ear.

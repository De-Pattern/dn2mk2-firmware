# CZ: a Casio CZ phase-distortion machine (machine type 7, built 2026-10-18)

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
- Both lines share the wave pair and the DCW envelope: SEL picks 1 / 2 / 1+1' / 1+2',
  with line 2 detuned (DET, OCT) and ring or noise modulation (MOD).
- The pitch envelope is the DN2's LFO / envelope routing, not a CZ DCO envelope.

Model first (`cz/model.py`, `cz/demos.py`): the eight waves, the envelopes, lines,
detune and ring, rendered to WAVs for the owner's ear.

## Built (2026-10-18)

The owner kept the full envelope on DCW (*"id rather keep them on the dcw. thats fine"*).
Machine type 7, **CZ Phase** / `CZP` in MACHINE SEL after RESONATOR. The contract is
`dnfw.cz.live` (float32, the operations in the DSP's order); `cz.asm` is generated from it
by `scripts/gen_cz_asm.py` and the SHARC gate (step 9) holds it to it bit for bit.

    page 1  WAVE  SEL   DET   OCT   /  MOD   DCW   KF    SUS
    page 2  R1    R2    R3    R4    /  L1    L2    L3    L4
    page 3  R5    R6    R7    R8    /  L5    L6    L7    L8

| control | record (slot) | what |
|---|---|---|
| WAVE | WAV1 (26) | one of 33: the eight waves, the 20 pairs of two non-resonant waves, five non-resonant + resonant pairs; a pair alternates cycle by cycle |
| SEL | MOD (37) | 1, 2, 1+1', 1+2' |
| DET | TUN2 (31) | line 2 detune, +-1 semitone (centre 0) |
| OCT | TYPE (46) | line 2 octave: 0, +1, -1 |
| MOD | RSET (39) | in 1+2': RING (line 2 x line 1), OFF, NOISE (line 2's pitch wanders) |
| DCW | LEV1 (30) | the envelope's depth |
| KF | TBL1 (27) | DCW key follow: higher notes duller |
| SUS | WAV2 (32) | the sustain step 1..8, or NOSUS |
| R1..R8, L1..L8 | PD1, OFS1, PD2, OFS2, DEC, NLEV, BASE, WDTH; LEV2, DRIF, ATK, HOLD, CHAR, MAST, FINE, TUN1 | the DCW envelope, 0..99 each (rate 99: 1.5 ms across the range; 0: about 30 s) |

The records keep their stock ranges (the indicator bars span them; the page draws the
CZ's values: page 1's enumerated controls as text, the wave pair's shape at DCW depth,
and on pages 2 and 3 the envelope with the page's four steps solid and the sustain step
marked). WaveTone's names are swapped for CZ's while a CZ track is active, as
Waverider and RESONATOR do. TBL2 (251) is unused.

v0.20: page 1 (CZ's and RESONATOR's) is drawn as the Elektron grid the DT2 pages use: a
knob for each continuous control (DET, DCW; RESONATOR's eight), and the enumerated ones
(WAVE, SEL, OCT, MOD, KF, SUS) as their value in a box, each over its label in the
stock 4 x 5 label font (`smp_knob_page`, `csrc/sampler/smp_page.c`). The wave-pair
picture is gone from page 1; WAVE's box names the pair.

**Departures from the CZ, and why.**

- One wave choice for both lines, and one DCW envelope: 25 parameters (above).
- The DCA is the DN2's AMP page, the pitch envelope its LFOs.
- **The release** (v0.9). A trigger restarts the envelope from step 1; it runs to the
  sustain step and holds. The note-off sends it on to the step after sustain, from
  wherever it is (a key-up before sustain jumps straight to the release, as on the CZ),
  and it runs to step 8 and stays there; END is fixed at step 8. The note-off is frame
  mask 36, bit t: measured in the SHARC runner, it is the mask that releases the DN2's
  own ADSR amp envelope (masks 38 and 40 do nothing to it). Whether the ColdFire sends
  it for a CZ track as it does for WaveTone is for the instrument to show.
- Line 2's detune is +-1 semitone, not the CZ's octave / note / fine.

**DSP.** `cz.asm` (868 instructions, 3,528 B) at `0x2e6000` (sw `0x173000`), entered
from RESONATOR's tail, on to `wr_ping`; its scratch block at `0x2ddd00` (the reader
span's tail, beside RESONATOR's, which moved there from `0x2e6400`); its 16 voices'
state (64 B each, zeros) and its tables (increments, rates, the 33 pairs, the page's
rate/level frame offsets) in DDR at `0x81202000`. RESONATOR's tables moved to DDR
(`0x81201000`) to make the room; they are read once a mode a block. The machine lookup
`0x25d748[7]` becomes 7 (the last of its eight entries). Section 7 is 1,046,884 bytes
of the 1,048,575 the uploader takes: 1,691 to spare, no wavetable dropped.

**Voices.** Six CZ voices render a block (`live.MAX_VOICES`); RESONATOR's cap is four.
A CZ voice never goes idle by itself (its DCA is the AMP stage, after it), so a slot
that has played keeps rendering until it is stolen.

**Voice stealing (v0.10, `dnfw.voices`).** Until v0.10 the cap counted slots in slot
order. With the DN2's dynamic voice allocation, which can hand a new note to any of the
16 slots, a new note on a high slot found the cap already taken by older voices on lower
slots and stayed silent. The owner, 2026-10-19: *"on the resonator and cz phase engines,
i have to set an explicit voice limit, or else i get a lot of dead notes"*.

Now every slot has an age, counted in blocks: 0 on the block its note arrives, one more
for each block it stays active. The slots are ranked by age, newest first, and those
ranked below the cap render. A voice past the cap is stolen: its state goes back to rest
and it falls silent. RESONATOR's entry computes the ages for both machines in one pass.
The SHARC runner holds both to `dnfw.voices.plan` bit for bit (step 9: with eight notes
on eight slots, the newest six sound). A fixed voice count of 8 on the Voice Setup page
still works as before.

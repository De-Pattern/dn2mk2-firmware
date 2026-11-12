# v0.51: the lighter Monomachine and Machinedrum machines

Owner, 2026-11-10 (ROADMAP): "rewrite and trim them for DSP time, even if they no longer match
stock bit for bit: we can make them sound good without being exact replicas"; a significant cut
is worth it even at about 70 % of today's likeness; tried in its own release, reverted if it goes
wrong. Each change is one constant, so each can go back alone:

| machine | change | the constant (exact value) | instructions a Monomachine block (16 frames) |
|---|---|---|---|
| SID 6581 | oscillators at 4x (the Monomachine's 12x), DPRO-WAVE's decimator (4:1, two inner rounds; SID's output shift kept) | `sid.OS = 4` (12) | 14,144 -> 5,059 (-64 %) |
| DPRO-DENS | its four oscillators read at 1x from the mip level the 2x increment picks; no 2:1 decimator | `dpro.OS = 1` (2) | 14,102 -> 8,503 (-40 %) |
| DPRO-DDRW | the same | `dpro.OS = 1` (2) | 11,684 -> 6,682 (-43 %) |
| VO-6 | the four series formants in float (the parallel bank's resonator), not the 56300's exact 24-bit products | `vo6.SER_EXACT = False` (True) | 16,639 -> 15,211 (-9 %) |
| DPRO-WAVE | unchanged: 2x measured and refused (the decimator with no inner round lets the images through: 59 of 78 golden cases 16..20 dB out of shape) | `wave.OS = 4` | 6,843 |

Machinedrum (`dnfw.md.trx2.EXACT = False`): TRX's 2nd-order high-pass (hp1, its cascade) and
resonator (res2) in float, not the 56300's split 12-bit products. TRX-CY 25,432 -> 17,125
instructions a 44.1 kHz block (-33 %), TRX-MA 18,089 -> 13,338 (-26 %), TRX-CH / OH / CB / S2
lighter by their filters' share. TRX-CP keeps the exact filters (its RATE 0 burst came out one
band 8 dB off in float).

The DSP-time guard decides how many voices sound (v0.36: no fixed caps), so lighter voices
give more of them at once with no other change.

## How each is held

- **The SHARC runner** holds the DSP to the model bit for bit, as before (the model is the same
  DSL program, run).
- **test_mnm.py** holds a trimmed Monomachine machine to the Monomachine's own output
  (`dnfw.mnm.bench.likeness`): its level within 2.5 dB and every octave band within 20 dB of the
  Monomachine's loudest within 6 dB (16..24 kHz within 15 dB); SID's NOIS by its level only. A
  negative control per trimmed machine: the same output 6 dB down fails. Measured: SID's tonal
  cases 0.0..0.1 dB level, bands within 0.6 dB; MIX up to +2.2 dB and some aliasing 20 dB under
  its main band; DENS within 0.6 dB everywhere; DDRW within 0.8 dB of level, +2..3 dB at 8..16 kHz
  and +6..13 dB above 16 kHz at high TUNE (a little aliasing: the 1x read folds its top partials);
  VO-6 44 dB signal-to-error or better on every case.
- **test_md.py**: a float-filter TRX machine passes either at 60 dB signal-to-error, as before, or,
  for the noise-driven ones (CH, OH, MA: their resonant filters decorrelate sample for sample),
  within 1 dB of level and 3 dB in every octave band; measured 0.0 dB on every case. Its negative
  control: a hat 2 dB down fails.

## Not verified on hardware

The sound on the unit (the emulator's float is the SHARC's; the model is the DSP bit for bit) and
the voice counts the guard then allows at the unit's real load.

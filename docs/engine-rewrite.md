# The Machinedrum / Monomachine engine rewrite (v0.72, first part)

Owner, 2026-11-23: "lets do the md/mm rewrite first ... you know how to do this best as to not
sacrifice the sound and behavior we want to retain". The aim: the same machines, lighter on the
DSP, so the DSP limit (docs/guardrail.md) allows more of them.

## Where the time goes (measured 2026-11-23, v0.71)

The DSL's run mode, one voice, eight blocks after its note, every executed instruction counted
by kind and by the source function that issued it:

- **Constant loads are 15..30 % of every machine's instructions**, and float arithmetic the
  largest share. Within straight-line code only 25 of the 8,233 constant loads are redundant: the
  constants reload because the per-sample loops have no free registers to keep them in.
- **The 56300's exact arithmetic** is the biggest single cost where it sits in a hot loop: EFM's
  `xround` (the 24 x 24-bit product, rounded) was 42 % of EFM-CY; TRX's `wmul` 35 % of TRX-S2;
  VO-6's `_floor` (an accumulator truncated to its 24-bit word) 13 % of VO-6. Each built a
  48-bit product out of 12-bit halves, about 30 instructions, where float32 needs one multiply.
- **P-I's delay lines in DDR**: about 1,800 DDR accesses a block (over half of PI-SD's and
  PI-RS's estimated cost). Each voice has an 8 KB delay area (16 x 8 KB = 128 KB); the proven
  free L2 room is 28 KB. Not moved yet.

## What changed

- **`FIX Fx BY Ry`** in the DSL (`dsl.Prog.fix_by`): a float scaled by 2^Ry and rounded to the
  nearest integer in one instruction. The assembler (selache), the SHARC runner (digikit opcode
  0xD9) and the gate's decoder all read it; our code runs with MODE1.TRUNCATE clear, as its float
  arithmetic's round-to-nearest already requires.
- **EFM** (`efm.EXACT = False`): `xround` as one float multiply and one `FIX BY`, 32 -> 8
  instructions. `xfloor` (the phase increments, up to 2^27, past float32's 24 bits) stays exact,
  so every EFM machine's pitch is the Machinedrum's to the LSB.
- **TRX's `wmul`, `wmul2`, `wmul4`** (`trx2.WMUL_EXACT = False`): one multiply and one `FIX BY`,
  about 30 -> 9 instructions. `wmulr` (its flag needs the exact low bits) and **TRX-CP** (its
  own exact copy, `trx_wmul_x`, as v0.51 kept its filters exact) stay exact. P-I's metal
  (RC, CC, HH) shares `wmul`.
- **VO-6** (`vo6.FLOOR_EXACT = False`): its accumulators keep float32's precision instead of the
  56300's truncation to a 24-bit word: finer than the Monomachine, never coarser.

Every change is one constant (`True` puts the Machinedrum's or Monomachine's arithmetic back,
bit for bit) and the model and the DSP change together: the SHARC runner still holds the DSP to
the model bit for bit.

## How the sound is held

- **test_md.py**: every Machinedrum machine at 60 dB signal-to-error against the Machinedrum's
  own output, as before, except the machines whose float arithmetic decorrelates sample for
  sample through feedback or resonance: EFM-CB, EFM-HH, EFM-CY (operator feedback) and P-I's RC,
  CC, HH join the float TRX machines (v0.51) in being held by level (within 1 dB) and every octave
  band (within 3 dB). A new negative control: EFM-CY 2 dB down is refused.
- **test_mnm.py**: VO-6 by its level and spectrum (bench.likeness), as v0.51's trimmed machines,
  with the wrong-level negative control.

## The saving (the SHARC runner's estimate a voice-block, `--steps cost`)

| machine | v0.71 | v0.72 | |
|---|---:|---:|---:|
| EFM-CY | 31,125 | 23,013 | -26 % |
| TRX-S2 | 19,812 | 16,707 | -16 % |
| EFM-CB | 20,996 | 18,500 | -12 % |
| EFM-BD, HH, XT, SD, CP, RS | | | -7..-9 % |
| TRX-CB, MA, CY, CH, OH | | | -3..-7 % |
| P-I RC, CC, HH | | | -2 % |
| VO-6 | 33,536 instructions | 28,832 | -14 % (instructions) |

## Next (not in v0.72)

- **P-I's memory**: shorter delay lines for the P-I machines that need little, so they fit L2,
  or the active part of each line paged through L1.
- **SID, DPRO-WAVE, FM+**: the decimator's saturation, FM's sine lookup and saturation.
- **A scheduler in the DSL**: pairing compute with post-modify loads and stores into the SHARC's
  multifunction instructions, and keeping constants in registers across loops, for every machine
  at once. The model and the DSP stay one program, so the runner's bit-exact check still holds.

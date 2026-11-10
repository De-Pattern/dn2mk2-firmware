# v0.48 and after: the plan (owner, 2026-11-09)

## Decisions
- **FLEX is chosen over FASCIA** if both cannot fit. FLEX: docs/flex-design.md.
- **FASCIA continues as a mono machine** (one voice), rebuilt so it can be used if room allows.
  Its budgets: **<= 8 KB stored** (today's is 15,150), **<= ~0.08 of the DSP block** (a Monomachine
  voice; today's typical 0.17, heavy 0.40). No bit-identity to the v0.45 sound required (owner): the
  DSP code still matches its own model exactly, every safety check stays, new reference renders
  afterwards, one listening pass.
- **Room** (stored bytes under the 2 MiB USB-upgrade limit): v0.48 without FASCIA 21,299 free;
  FLEX estimated 8,000-11,000; 2,000-3,000 kept free for fixes. FLEX's room is reserved first.

## Order
1. v0.47: shipped without FASCIA (preview, TUNE, INTO, BOUNCE hidden).
2. v0.48:
   - BOUNCE out (docs/bounce-removal-plan.md; code done on this branch).
   - The RECORDER's text rule: R.LEN's MAX and numbers on one baseline; every centre-box message
     inside the box (a gate check over every value and state).
   - The old open reports investigated: the sample-select freeze while playing (U2, O5), the
     Monomachine dynamic-allocation silence and voice-15 leak (O1, O2), an MD machine still heard
     after a machine change (U5), VO-6 silent at some CONS/CLEN (M1), SAMP's name on D.
   - Keyboard mode across grid recording: stock's behaviour checked in the emulator, then kept.
   - FASCIA mono, to its budgets, included only if it fits beside FLEX's reserved room.
   - The SHARC runner's FASCIA clock hook (f063559 on v047's history) back with FASCIA.
3. The emulator: the ColdFire and the DSP run together; the memory map; DSP timing.
4. FLEX (docs/flex-design.md), built on the coupled emulator.

## Later (owner, 2026-11-09)
- **DPRO-DENS may be cut** if FLEX and mono FASCIA need the room (owner: "if it helps at all, we can
  cut dpro dens"). First measure what it frees (it shares the Digibank waves and the decimator
  with DDRW and WAVE); if cut, the BOUNCE way: type kept known, a DENS track in an old project loads
  silent, a power-on test with DENS in the kit; the other four machines' bit-identity unchanged.
- **The Monomachine machines' decimator and bit reduction** (owner: "i dont think its working
  properly but not sure how to test that"). What is proven today: the DSP's output equals Elektron's
  own Monomachine code for the reference cases (BR1/BR2 at 0..127 on DDRW, the decimator inside every
  machine's render). What is not: that the knobs reach the DSP on the unit, and that the reference
  cases cover what is heard. To do:
  - A knob-to-sound check through the ColdFire: turn BR1/BR2 (and every machine's controls) on the
    panel, follow the frame word to the DSP, and require the rendered output to change as the
    reference says it should (end to end, on the coupled emulator).
  - Reference renders at extreme settings (BR 127, high notes where the decimator's aliasing shows),
    compared with Elektron's code, and listened to beside the owner's Monomachine if he has one.
  - Measured: BR's effect on the real Monomachine's output is about -60 dB up to 48, -31 dB at 96,
    -13 dB at 127 (GOLDENS-MNM): subtle by design below about 100.

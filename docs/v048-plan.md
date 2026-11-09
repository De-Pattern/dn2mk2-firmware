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

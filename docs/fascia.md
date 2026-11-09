# FASCIA: a physical/spectral percussion machine (design approved 2026-11-07)

Status: **the sound is approved and locked**. The DSP and UI integration are not started.

The owner, on the pass-3 tour: "i love the new tour sounds. theyre all perfect. great work. that will be the new engine, exactly as you made it ... just make sure it fits in every way, look, gui animation, integration into seq and modulation and p locks, encoder feel and functionality, everything."

**Order (owner, 2026-11-07):**
1. v0.44 BOUNCE (in the gate).
2. v0.45: the +Drive library from 2,048 to 16,384 samples, plus the pending fixes (SLICE's empty slots).
3. Then FASCIA.

## The reference: what is locked

- **The design model:** `src/dnfw/fascia/model.py`, float64 and block-wise (32 samples, coefficients once a block, 48 kHz).
- **The approved sound:** the 30 patches of `scripts/fascia_audition.py`.
- **The goldens:** their first seconds, kept in the private bench repo, `dn2mk2-bench/goldens/fascia` and `GOLDENS-FASCIA.md`.
  - `test/test_fascia_golden.py` holds the model to them within 2 LSB.
  - The full renders the owner heard are in `goldens/fascia/listen/`.
- **Behaviour tests:** `test/test_fascia_model.py`, 18 of them:
  - pages and choice spans;
  - every exciter by body combination, finite and bounded;
  - every control at both extremes;
  - random patches;
  - determinism and voice release;
  - velocity brightness;
  - TZFM through zero;
  - polyphony as the sum of voices;
  - coupling.

**Any change to the model's sound needs the owner's ear first.** After that, regenerate the goldens with `scripts/fascia_golden.py`.

## The pages (4 x 8 = 32; the stock space has 40)

| page | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| SYN1 EXCITERS | TYPA | TYPB | HARD | DUST | TZFM | BEND | MIX | DEC |
| SYN2 RESONATORS | BODA | BODB | TUNE | GEOM | MATL | POS | COUP | DAMP |
| SYN3 SPECTRAL | MORPH | FORM | SHIFT | RING | SIDE | FOLD | LPG | CHAR |
| SYN4 ONSET/INTERACT | ATK | CLIK | CTYP | XMOD | FDBK | BUZZ | WATR | VARY |

Choice controls:
- **TYPA, TYPB:** STRIKE, BLOW, BOW, DUST, PULSE, TZFM.
- **BODA:** MEMB, PLATE, BAR, VIBE, CHIME, BELL, GLASS, TUBE, STRING.
- **BODB:** the same, plus OFF.
- **CTYP:** SNAP, TICK, NOISE, THUMP.
- **XMOD:** EXCITE, BEND, CHOKE, TRADE.

Owner decisions:
- The 4th page was approved.
- WATR replaced BTUN.
- Body B's interval is fixed by its type: "we determine the fine tuning and take out a little bit of the guess work ... while retaining a lot of power in decision making and patching".

## What each part does (the model, in short)

### Exciters
**STRIKE:** a raised-cosine pulse of unit area, 4 ms wide (soft) down to 0.05 ms (hard). HARD sets the width and velocity scales it. DUST adds contact noise.

**BOW:** a friction bow, with force from the bow table against the relative velocity at the contact point, computed every sample.
- DUST is rosin grit: random micro-catches.
- HARD is pressure, from airy to scraping.
- DEC holds the bow on.

**BLOW:** a reed. Flow is driven by breath pressure against the body's motion, and the reed closes as the pressure difference rises. HARD makes the turbulence brighter.

**DUST:** sparse impulses whose density comes from DUST.

**PULSE:** a sine burst with a pitch envelope from BEND.

**TZFM:** through-zero linear FM, `f = fc + I fc m(t)`. The increment is signed, so the phase can run backwards. SIDE sets the modulator ratio (0.5 to 7). The TZFM knob on any other exciter adds a TZFM burst at the attack.

**ATK:** the onset.
- For impulsive exciters, the hit is smeared over a rising window (a swell).
- For BOW and BLOW, it is the rise time of the pressure.

### Bodies
Each body has 16 two-pole modes: `y = 2 r cos w y1 - r^2 y2 + g x`, with `g = amp sin w`.

**Mode ratios by type:**
- MEMB: Bessel zeros.
- PLATE: a rectangular plate, 1.31 aspect.
- BAR: a free-free bar.
- VIBE: 1 : 4 : 10, plus torsional modes.
- CHIME: free-free modes divided by 4.47, so the note is the strike note.
- BELL: measured ratios.
- GLASS: n(n²−1)/√(n²+1).
- TUBE: odd harmonics.
- STRING: harmonics.

**Twin modes:** round bodies get near-degenerate twins (SPLIT) whose beating is capped at BEAT_MAX Hz. This fixed the owner's "quivering" note on the tubular bell. CHIME's modes 1..3 are weakened.

**Damping:**
- T60 per mode is `DAMP / (1 + a1 f + a2 f²)`.
- MATL plus the body's RING_BIAS sets a1 and a2.
- The LPG adds a loss on high modes that grows as the contour falls.

**POS** weights each mode by `|sin(pi sp POS)|`. `sp` is the mode's spatial frequency: sqrt of the ratio for 2-D bodies and bars, linear for strings and tubes.

**BEND** is a tension glide, up to 7 semitones at full level, following the body's own level. Hard hits add a 4 ms contact chirp.

**VARY** controls:
- per-hit variation: about 0.1 % on mode frequency and 10 % on level, at the default of 40;
- a slow random drift of the modes while they ring.

**GEOM** stretches the mode ratios: `ratio^(0.6..1.4)`.

**MORPH** moves each mode's output level up the spectrum as it rings, keeping the sum. It never moves pitch: the owner flagged a "cartoonish pitch ramp" in pass 2, and this fixed it.

**Body B:** its pitch is `f0 * B_RATIO[type]`:
- TUBE and STRING 1:1;
- MEMB and CHIME 3:2;
- GLASS 4:3;
- PLATE, VIBE and BELL 2:1;
- BAR 2.756.

### Interaction
**XMOD and COUP:**
- **EXCITE:** B hears (1 − c) of the exciter plus c of A.
- **BEND:** A's level bends B by up to an octave.
- **CHOKE:** A ringing shortens B's T60.
- **TRADE:** EXCITE plus B back into A, and A damped by what it gives.

**FDBK:** B goes back into A one block late, bounded by tanh.

**BUZZ:** a contact gap on A. Where A swings past the gap, it buzzes (highpassed noise plus a clipped edge), and the buzz also shakes B. Snare wires, a sitar's jawari, a rattle.

### After the bodies
1. A DC block at 20 Hz: a steady bow or breath bends a body but doesn't sound.
2. The voice's level guard: threshold 0.7, 1 ms attack, 120 ms release, gain applied once a block.
3. CLIK: a transient straight to the output, scaled by HARD.
   - SNAP: a band-limited crack.
   - TICK: a 1 ms high blip.
   - NOISE: a short bright burst.
   - THUMP: a 40 Hz knock with a falling pitch.
4. RING: A times B, or times a sine at 1.414 f0 when B is off.
5. SHIFT: an SSB shift of ±5 to ±2000 Hz, bipolar around 64.
6. FORM: two vowel formants, a e i o u.
7. WATR: the sound vocodes itself.
   - The skin above 1.8 x the note goes into 8 bands from 2.2 x the note up.
   - Bands 2..7 are each heard through a narrow carrier tuned 4 to 8 % high, gated by their own envelope squared over a slow envelope.
   - The result is level-matched to the dry skin.
   - The body under 1.8 x the note is untouched, so the fundamental and pitch stay.
8. FOLD: a sine folder.
9. CHAR: an asymmetric tanh.
10. LPG: the VCA half.
11. The output knee: tanh(1.5x) / 1.5.

## Integration requirements (owner, binding; `claude/strike-requirements.md` in the project)

1. **It must fit in every way:** look, GUI animation, sequencer integration, modulation, p-locks, encoder feel, everything.
2. **Choice controls:** 4 detents per option (the v0.26 feel). They step and never glide under slides or LFOs. The model's `choice()` gives equal spans of 0..127 per option (tested).
3. **P-locks:** a locked value is highlighted exactly as stock shows it, on all four pages.
4. **Slides:** every parameter works with slide trigs and lands on the lock (the slides harness).
5. **LFOs:** every parameter is an LFO destination, with its name in the destination list. Ranges are clamped and choices stepped.
6. **Everything else stock does:** copy/paste/clear sound, presets, kit save/load, MIDI CC/NRPN, trig conditions, undo.
7. **Voices:** percussion first, polyphonic for melodic use. The CPU must not struggle.
   - Measure the per-voice cost on the SHARC runner (`--steps cost`) before choosing the mode count. At 16 modes x 2 bodies plus twins, a voice is up to about 60 two-pole resonators.
   - Voices release on silence (IDLE), and inactive stages are skipped (SHIFT at 64, WATR at 0, ...).
   - Worst-case mixes are tested with MD, MnM, sample and FM tracks.
   - Voice steals use fades. No NaNs.
8. **Look:** icons, alignment, spacing, font, highlight and animation match the Digitone II's own. The stock widgets are used where they exist. New icons for the exciter, body, click and XMOD types are drawn in the stock style.
9. **Quality:** ColdFire harness steps for the pages, detents, p-lock highlight, slides, LFO destinations and copy/paste, added to `ship_gate.py` in the same commit. The full gate runs before hardware, with no regression.

## The DSP plan (next)

1. **`fascia/live.py`:** the model in DSP order, in float32, using only the operations our SHARC code uses. That means no division, exp or sin at audio rate: tables and per-block coefficients, as `rings/live.py`.
   - Held to the model by ear-level metrics.
   - Held to the goldens' character: spectra and envelopes within tolerance, since float32 and DSP-order maths won't be bit-identical to float64.
2. **The SHARC program:** written in the PERC DSL (`dnfw.perc.dsl`, one source with emit and run modes). The runner holds the assembled code to `live.py` bit for bit.
3. **Driven BOW and BLOW** must run per sample on the DSP: the most expensive part. Measure them first, and keep a per-block fallback only if the owner approves the sound.
4. **WATR and SHIFT** need care on the DSP:
   - WATR: 6 bands x (2 band-passes + 2 followers).
   - SHIFT: a Hilbert pair, where the model uses an offline `scipy.signal.hilbert`. The DSP needs an IIR allpass pair, judged by ear against the model.
   - Both are skipped when they are off.
5. **The ColdFire side:** the machine's records (32 slots), its pages and choice widgets with the p-lock highlight and slides, the LFO destinations, its harness and gate steps. The playbook's 8 layers (`docs/FEATURE-PLAYBOOK.md`).

## References
- Mutable Instruments Elements and Rings (MIT): `/home/claude/dn2/ref/mutable`. The modal resonator, exciters, bow table.
- The LXR V2 firmware (GPL-3.0-only, github.com/erica-synths/lxr-desktop-app): `/home/claude/dn2/ref/lxr2`. Transients, snap EG, drum voice.
- The design brief: the project doc `claude/strike-design.md`.
- The requirements: the project doc `claude/strike-requirements.md`.

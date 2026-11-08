# FASCIA: a physical/spectral percussion machine (design approved 2026-11-07)

Status: **the sound is approved and locked**. The UI is in (v0.45); the DSP program (`dnfw.fascia.program`, below) is written and held to `live.py` bit for bit; hardware unverified.

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

## The ColdFire side (v0.45): type 18, where the 24 controls sit

FASCIA is machine type **18** (MACHINE SEL: "Fascia" / "FSC", in the synth section after the
Monomachine's machines, before the sample machines). Its constants and its slot table are
`src/dnfw/fascia/machines.py`: the one source the ColdFire's generated header
(`dnfw.waverider.pages`, `wr_gen.h`) reads, and the one the FASCIA DSP program is to read.
The panel itself (`PAGES`, `CHOICES`, `DEFAULTS`) is `model.py`'s, mirrored there because the
build (also run by the browser patcher) must not import numpy; `test/test_fascia_coldfire.py`
holds the two equal, and this table to the module.

**Where they sit.** Only 12 of WaveTone's 25 records span exactly 0..127 (TUN1/TUN2 are 4..124,
WAV1/WAV2 0..120, PD1/PD2/OFS1/OFS2 0..100; TBL1, TBL2, MOD, RSET and TYPE a few steps). So:

- the **19 continuous** controls ride records of exactly 0..0x7f00, and the DSP reads the
  panel's 0..127 as `word >> 8` with nothing rescaled: WaveTone's 12 (10 with a CC, MAST and
  FINE without) and FM Tone's spare records 227..233 on slots 50..56 (no CC; owner, 2026-11-08);
- the **5 choices** ride WaveTone's 0..100 / 0..120 records (each with a CC). A choice's knob is
  the value over the record's span x 127, rounded (`(v 254 + top) / (2 top)`; the value itself on
  a 0..127 record), and its option `(knob n) >> 7`, which is the model's `choice()`. A detent
  writes the middle of the option's knob span (`machines.rep_word`).

For a FASCIA sound, `param_set_slot_to_id` answers slots 50..64 with FM Tone's records (type 0)
and the ownership test accepts FM Tone's records on those slots (208..211, 227..237), for type 18
only (`dnfw.waverider.coldfire` `slot_shim`, `canon_valid`). FM Tone's 235..237 are not used:
their modulation mask is 0. Every other record the sound has on our slots is named `-` while a
FASCIA track is active, and so left out of the LFO destination list (`wr_lfo_mask`).

| control | slot | record | range | stock record | CC | kind | DSP frame offset (+146 t) |
|---|---|---|---|---|---|---|---|
| TYPA | 26 | 239 | 0..120 | WaveTone WAV1 | 41 | choice, 6 | 220 |
| TYPB | 32 | 243 | 0..120 | WaveTone WAV2 | 45 | choice, 6 | 232 |
| HARD | 30 | 241 | 0..127 | WaveTone LEV1 | 43 | knob | 228 |
| DUST | 50 | 227 | 0..127 | FM Tone PITCH | - | knob | 268 |
| TZFM | 51 | 228 | 0..127 | FM Tone P2A4 | - | knob | 270 |
| BEND | 52 | 229 | 0..127 | FM Tone RALL | - | knob | 272 |
| MIX | 53 | 230 | 0..127 | FM Tone LVAB | - | knob | 274 |
| DEC | 40 | 253 | 0..127 | WaveTone ATK | 56 | knob | 248 |
| BODA | 29 | 240 | 0..100 | WaveTone PD1 | 42 | choice, 9 | 226 |
| BODB | 35 | 244 | 0..100 | WaveTone PD2 | 46 | choice, 10 | 238 |
| TUNE | 36 | 245 | 0..127 | WaveTone LEV2 | 47 | bipolar | 240 |
| GEOM | 48 | 261 | 0..127 | WaveTone MAST | - | bipolar | 264 |
| MATL | 54 | 231 | 0..127 | FM Tone ATAB | - | knob | 276 |
| POS | 55 | 232 | 0..127 | FM Tone DCAB | - | knob | 278 |
| COUP | 56 | 233 | 0..127 | FM Tone EDAB | - | knob | 280 |
| DAMP | 41 | 254 | 0..127 | WaveTone HOLD | 57 | knob | 250 |
| MORPH | 38 | 252 | 0..127 | WaveTone DRIF | 55 | knob | 244 |
| SKIN | 42 | 255 | 0..127 | WaveTone DEC | 58 | bipolar | 252 |
| SHIFT | 45 | 258 | 0..127 | WaveTone WDTH | 61 | bipolar | 258 |
| CLIK | 44 | 257 | 0..127 | WaveTone BASE | 60 | knob | 256 |
| XMOD | 28 | 246 | 0..100 | WaveTone OFS1 | 48 | choice, 5 | 224 |
| BUZZ | 49 | 262 | 0..127 | WaveTone FINE | - | knob | 266 |
| LPG | 43 | 256 | 0..127 | WaveTone NLEV | 59 | knob | 254 |
| DRIVE | 47 | 260 | 0..127 | WaveTone CHAR | 63 | knob | 262 |

**Pages.** Three descriptors (`SYN1 EXCITE`, `SYN2 BODY`, `SYN3 SPECTRAL`; the header reads
"Fascia Excite (1/3)" ...), drawn by `fsc_page_draw` (`csrc/sampler/smp_page.c`) in the Elektron
grid of the DT2 machines' pages: eight cells at the DT2's centres, a knob for a continuous
control, the option's name in a box for a choice (four letters in the box: STRK, PULS, PLAT,
CHIM, GLAS, STRG, EXCT, CHOK, TRAD; the header and SYN held show the whole name), the label under
it, a p-locked cell inverted as stock lights a lock, SYN held showing values.

**Behaviour.** The header's value text is FASCIA's own while its track is active (`fmt.c`
`smp_formats`): 0..127, the bipolar four (TUNE, GEOM, SKIN, SHIFT) as -64..+63, a choice by name.
Each choice steps **four detents an option** (`fsc_quant`, all five, BODB's ten included); FUNC +
turn steps a choice one a click and leaves a knob where it is. MACHINE SEL writes the model's
`DEFAULTS` (`rec.c` `smp_machine_commit`). Every continuous control slides onto its lock; the
choices step (`dnfw.slides.FASCIA_SLIDE`, `slide.c continuous()`).

**DSP (v0.45).** The machine lookup sends type 18 to PERC's engine slot (5), as the sample and
Monomachine machines. PERC's chain is now PERC -> `smp.asm` -> **`fascia.asm`** (`wr_fsc`, sw
0xBD8800, L2 0x200B1000..0x200C0000) -> PING's tail (0x170280, the register restore). The
program is `src/dnfw/fascia/program.py`, in the PERC DSL: its run mode is bit-exact to
`live.py` (`test/test_fascia_program.py`; `scripts/fascia_dsp_compare.py` renders the whole
audition and its WAVs), and the SHARC runner holds the assembled code to the run mode
(parts `fascia`, `fchords`+`fsilence`, `fgarbage`, `fstress`; `fcost` measures).

- **Layout.** A voice's state is 0xF80 bytes (16 voices in two L2 rooms: 0x20098400 for 0..7,
  below the MD's state; 0x200A9400 for 8..15, after the main mix's tap). The block's scratch is
  L1 0x2E6400..0x2E7000 (I5-relative, its 64-word window holding the hot words and a pool of
  12 constants filled at `wr_fsc`'s entry). The bookkeeping (costs, strikes, steals, routine
  return words) is in the Monomachine scratch at +0x3200. The tables (`fascia/tables.json`, 1 KB)
  are in DDR at 0x81220000. (The plan's 0x200E9000.. range is refused by `dsp._check_l2`, 64 KB
  short of the non-cacheable window.)
- **Velocity.** The frame header's word `52 + 2t` holds the trig's velocity << 8 (the ColdFire's
  frame builder copies `0x8000dd40[t]` there, 0x4002750c; `docs/modulation-matrix.md`). The
  program reads `min(word >> 8, 127) / 127` as `live`'s `vel`.
- **Note.** From the frame's header word `2 + 2t` (/ 256), not the note cell (engine +0x1387c
  + 4t) that PERC and smp read: the stock unpack writes the cell after our code runs, so on a
  trig with a new note it still holds the previous note (the runner's steal 60 -> 67: the cell
  60 on the trig's block, 67 the next). Found by the runner's `fascia` part.
- **Voices.** A trig arms the voice (note-on on its block); an IDLE voice rests (the guard's
  rest list, one block); a retrigger steals with `live`'s fade. Every state word is
  initialised by the strike, and the life words are sanitised, so power-on garbage is harmless.
- **`live.py` changes for the DSP** (rounding-level: float32 where it was float64; not re-auditioned by the owner): DUST's grain
  smear `HANN_VAR * dn^2` in float32; the body ratios `exp2(LOG2R)` (the DSP's 576-byte ratio
  table dropped).

**Known limits.** TRK + CLEAR re-initialises a sound from its records' own defaults (stock's
`0x400e7d4c`), so a cleared FASCIA track starts from WaveTone's and FM Tone's defaults, not
FASCIA's (as a Monomachine track does). MIDI CC reaches only the 15 controls whose record has one.

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

# Roadmap (this fork)

What the owner has asked for and is not built yet, in the words he asked for it, with
enough of a plan that it can be picked up cold. Upstream's own parked ideas are in
`docs/ideas-backlog.md`.

## Next

- **W3: Waverider osc 2** (page 2: DETN, LEV, POS, TBL, RATE, MPOS, MLEV, MOVE on
  osc 2's WaveTone records, `docs/w2-scanner.md`).
- **The owner's own tables in a build**: `dnfw waverider slice` output into a table
  slot. This needs table compression first, because each table is 16 KB and the DSP
  has 18,979 bytes of budget left.
- **GRAINS G1** (`docs/grains.md`), the frequency shifter FX, a Rings-style resonator.

## A pingable filter (owner, 2026-10-13)

> *"is it possible to add a more pingable filter here, like a vcf or something? maybe
> something more like the resonator in the ps [3100/3300] or the memorymoog … i want
> to be able to get thick plinky watery hard hitting liquid pings from these and is
> difficult with the existing ones but i cant say for sure why that is"* -- and: *"i
> want to remember to implement this even if we dont do it right this moment"*.

**What a ping is.** A short impulse hits a resonant filter sitting just below
self-oscillation, and the filter rings out as a decaying, pitched sine-like tone. The
filter makes the sound, not the oscillator. "Thick", "watery" and "liquid" come from a
high, stable Q, a decay that tracks pitch, a little saturation in the feedback path,
and often two or three resonant peaks at once, as the PS-series resonator banks have.

**Why the stock filters probably resist it** (to be measured, not assumed):

- the resonance may be capped or gain-compensated short of a clean ring;
- the filter envelope or amp envelope may not be fast enough to give a true impulse;
- excitation is the whole oscillator, not a click, so the ring is masked by the source;
- the cutoff may not track the note exactly, so pings don't play in tune.

The first step is to measure a stock filter's impulse response in the SHARC runner.
That turns "difficult, can't say why" into numbers: Q reached, ring time, keytracking.

**Ways to build it, cheapest first:**

1. **A PING stage inside Waverider**: a per-voice resonant filter (state-variable or
   ladder, keytracked to the note) after the reader. It is excited by a built-in
   impulse at note-on as well as by the wave, with controls for FREQ, RES (up to a
   clean, bounded ring), DECAY and MIX. It lives in our own DSP code, so it changes
   nothing in the stock machines, and it reuses the W2 gain path and gate tooling.
2. **A resonator bank** in the PS spirit: 2–3 parallel band-passes at set ratios, fed
   by the same impulse and the wave. This overlaps the planned Rings-style resonator,
   so it may become that machine's simplest mode.
3. **A new filter type for every machine** in the FLTR page's type list: the biggest
   change. It means the stock filter dispatch, its records and its UI, and it touches
   stock machines' signal path, so it would come after 1 or 2 has proven the sound.

### Added 2026-10-13: the owner's own diagnosis, and the target sound

> *"faster snappier envelopes would be my dream … i would love if i could set
> exponential/log on attack and decay and really tweak the speed manually"*, and the
> filters *"seem too brittle and fragile. the resonance can get relatively high, but it
> starts to sound bad and blown out pretty quickly. then thin and not organic … maybe
> its even too dirty. i need a rounded, watery timbre … more like a marble being smacked
> against a thick bowl at a high rate of speed"*. Wanted references: Serge VCFQ,
> Buchla-style, Roland-style filters; Mutable's Ripples/Blades are analog, so there is
> no code to port from them. Beads, for a later granular FX, if its licence allows.

**What that points to:**

- **A vactrol low-pass gate (Buchla 292 style).** One envelope opens the amplitude and
  the cutoff together, with the vactrol's fast attack and slow, curved release. That is
  the classic "bongo" / liquid ping. Mutable's Plaits has an LPG model in its MIT
  codebase (I believe `plaits/dsp/fx/low_pass_gate.h`; to verify before use), and
  `stmlib`'s zero-delay-feedback state-variable filter. The SVF stays clean and stable
  at high Q, which is the opposite of "brittle".
- **"Marble on a thick bowl" is modal synthesis, more than filtering**: a struck
  object is a few inharmonic resonant modes with their own decays, hit by a very short
  exciter. Plaits' modal engine and Rings' modal resonator (MIT) do exactly this. It is
  also where the Rings-style resonator was headed anyway.
- **"Rounded" rather than "blown out"**: zero-delay-feedback (TPT) filters with soft
  saturation inside the feedback loop, so resonance compresses instead of clipping.
  A Roland-style 4-pole OTA cascade and a Serge-VCFQ-style resonant band-pass can both
  be built from the same parts (Zavalishin, *The Art of VA Filter Design*).
- **Envelopes**: our own per-voice AD inside Waverider. Attack from 0.1 ms, a CURVE
  control running log ↔ linear ↔ exp for attack and decay, per-sample rather than
  per-block, and optionally driving the LPG. The stock envelopes and their menu stay
  untouched. Changing those would alter every stock machine, which `docs/SAFETY.md`
  rules out.

**First measurement** (unverified until done): the stock filter's impulse response,
and the stock amp envelope's shortest attack and decay, in the SHARC runner, to
compare against.

Safety: a ring at high Q must be bounded (gain-limited feedback and a hard ceiling)
so it can never blow up into a full-scale tone, and the SHARC gate needs a check for
exactly that.

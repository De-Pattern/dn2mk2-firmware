# Roadmap (this fork)

What the owner has asked for and is not built yet, in the words he asked for it, with
enough of a plan that it can be picked up cold. Upstream's own parked ideas are in
`docs/ideas-backlog.md`.

## The order after v0.48 (owner, 2026-11-10)

- **v0.49: FLEX** (docs/flex-design.md) and the guard fixes (sample voices first; a dropped
  sample voice stops until its next note).
- **v0.50: lighter Monomachine machines** (and the Machinedrum's, if they gain from it). Rewrite
  and trim them for DSP time, even if they no longer match stock bit for bit: "we can make them
  sound good without being exact replicas"; a significant cut is worth it even at ~70 % of
  today's likeness. Tried in its own release, reverted if it goes wrong; no long measurement
  against the stock engines. Straight on after v0.49.
- **Stereo sampling: not planned** (owner). The DN2's tracks are mono until the stock chain pans
  them; stereo would mean two voices a note or bypassing the stock voice chain, twice the memory
  and the sample voices' DSP time, and every sample machine changed. Not what this box is for.
- **After v0.49, before v0.50's work: a full stereo assessment** (owner, 2026-11-10; a study, not
  an implementation): what stereo would take end to end -- resampling (MAIN, TRK, IN), playback on
  every sample machine, importing without folding to mono (the import tool, the pool and +Drive
  formats) -- what it would cost (DSP time, memory, polyphony, ColdFire room), what would have to
  be removed or changed, how long it would take, and how certain we could be that it works (what
  the emulator can prove, what only hardware can).
- After v0.48: the gate split into runs that fit the two-hour job limit and resume themselves.

## impbox's reports, 2026-11-10 (owner: the playhead first)

1. **The playhead moves with STRT while a sample plays** (owner: "the start indicator should move with
   the start knob, but the sample playhead indicator shouldn't move with it ... it should accurately
   show where the playhead is on the sample as it reads it"). **Fixed in v0.49** (cb1eaf1): the DSP
   no longer moves a sounding note's position when STRT/LEN/LOOP turn; they apply at the next trig
   or loop pass.
2. p-locks are not visible on sample page 2.
3. R.LEN 64 with R.STRT (on PLAY): the take does not stop after 64 steps.
4. TUNE's text rounds badly: -0.01 shows -1, -4.00 shows -5.
5. Holding TRK inverts the track area, but a sample track's text is not inverted.
6. p-locks on SLD/SLEN cannot be cleared.
7. (request) SLD/SLEN settable without a lock (a default), or the lock icon as FILL/COND show.

1..6 into v0.49 where small and contained, else a fix release before v0.50; 7 for the owner to schedule.
Owner, 2026-11-11: proceed with v0.49 (the playhead fix in it); 2..6 to the fix release.

8. STRETCH, an old project on v0.48 (impbox, 2026-11-11): plays once briefly, then all sound on every
   track stops until reboot; not reproduced on a new project (the owner: none on v0.48 with a new
   project). The sampler model plays STRETCH/REPITCH/ONESHOT cleanly with STRT/LEN at every awkward
   stored word (old 127, 120.00, out of range). impbox is uploading a video. Owner: "not worry about
   that specifically so much" for now.
9. STRETCH clicks when looping short segments, more with higher BARS (the owner, from v0.46: at the
   loop's end and at a trig after STRT moved). Minor; "in the back of our minds".
10. Gate gaps (from 8): an old-projects step (projects saved on earlier firmware, every sample machine,
   played in the coupled emulator: sound never stops) and a full-range check of every stored control
   word through the DSP (finite output, bounded position and time).
11. The coupled emulator's EMAC (found 2026-11-11 on v0.49's FLEX test): digikit's unicorn halves every
   fractional product (0.5 x 0.5 = 0x10000000), so the stock smoother 0x400db12a decays every voice
   parameter to ~3% (FLEX played reversed, ~52 semitones low). emu_slides.py already modelled the
   smoother; emu_coupled_flex now does too. Other ColdFire EMAC users (the modulation apply, maybe the
   note) are still emulated wrong: fix the EMAC itself (or model each), then put every coupled test on
   it. emu_coupled_recplay (not a gate step) fails at 6a on v0.48 and v0.49 alike: out of date.

## v0.49 FLEX reports, 2026-11-11 (impbox, AnnKorr; not yet triaged with the owner)

1. **BUF can't be set on REC SETUP** (its box only shows the track's BUF: the panel's knobs are A SRC,
   B CHAN, D R.LEN, E ARM, F Q.REC; no knob turns C). **The SYN page's BUF seems to have no effect**
   (impbox). Recording and playback both follow `rt_buf_of(t)` (sound slot 35 through
   `rt_buf_value`, which scales by stock record 244's range words). The gate only checks a fresh
   track's BUF 01 (flex link 1c): a step turning BUF through 01..08 and recording into each is missing.
2. **A FLEX take is much quieter than the input** (impbox), with no way to bring it up. Takes are
   never normalised (rectrig.c), unlike the RECORDER's (v0.40). Options: a record GAIN on REC SETUP,
   or a louder LEV range for FLEX.
3. (request) **Double buffering**: a REC trig every pass on step 1 should let step 1's note play the
   previous pass's take, not the growing one. BOUNCE's two halves per buffer are still in rectrig.c
   (`rt_play[b]`, forced to the recording half in v0.49): record into one half, play the other, flip
   when the take completes.
4. (request) **The buffers as samples in the other machines** (GRID, ONESHOT ...), as REC 1/REC 2 and
   SAMP 124-127 were.
5. AnnKorr: a good sample chop needs about 3 voices; voices are "a juggling act" with sampling and the
   new machines (and she likes the sound of voices being eaten). A comment, not a bug report yet.

## After v0.40 (owner, 2026-11-02 / 11-03)

In this order unless the owner changes it:

1. **The Monomachine / engine-direction talk** (owner: remind him once v0.40 is out). A
   build without MM (DT2 + MD), how to branch it, one gated line or two; the MM glitch
   (MM chords over several MD tracks: a garbled, bitcrushed background) first, since the
   DSP-time guard should drop voices cleanly and doesn't always. Current costs:
   `docs/dsp-cost.md` (2026-11-03); the L2 table move was measured and is not worth it.
1b. **Overbridge on the mod** (owner, 2026-11-05, after Pablo Se7en's report that Overbridge
   does not detect his modded DN2; owner: plan for it "if we arent sure about support").
   What we know: the mod never touches the USB descriptors or Elektron's OS version string
   (`dnfw/safety.py`, `modversion.py`). Its link uses TDM slots 8..15 in, 14..15 out, which
   are clear of Overbridge's 42 channels (`docs/link-research.md`: slots 0..13 plus the reply
   records). Overbridge streamed Main and tracks 1–2 on a Waverider build on 2026-09-30
   (`docs/sharc-load.md`, [V]), before the sampler and the fast link. Since then it is
   unverified. Plan:
   - Hardware, the owner's unit, current build: Overbridge Engine sees the DN2 (USB CONFIG
     = OVERBRIDGE); all channels stream with a sample machine, Waverider, MD and MM on tracks;
     the plugin syncs a kit holding our machines; the sample link still works with
     Overbridge open; DSP load with Overbridge streaming.
   - A gate step: the USB/Overbridge code and data of MAIN OS byte-identical to stock (no
     patch site inside), and, in the emulator, mode 6's packets for slots 0..13 and the
     records unchanged while the fast link runs.
   - If the plugin chokes on our machine IDs: document using the Overbridge audio device in
     the DAW without the plugin. If Overbridge itself fails: find out why before anything
     else ships.
   - The owner mentioned a 42-channel Overbridge multichannel repo he shared earlier: not
     found in this fork's notes; get the link from him.
1c. **Decided 2026-11-06 (the owner, after v0.40's release):** v0.41 = the fixes on `v041`
   (NORMALIZING watchdog, YES over SAVING, SLEN detents) + rec trigs (item 2) + slides on our
   machines' own controls (item 3) + the Overbridge gate step (1b); v0.42 = the DDRW exact
   product and the **Monomachine engines re-coded** from the bit-exact code for this firmware
   (fast memory, DSP time), gated against all 366 regenerated references with no exception;
   heavier Machinedrum engines later, only if proven to sound and behave the same. If v0.41
   is not ready before v0.42, they ship together on the one big gate.
   **The "ultra stable" pass (owner 2026-11-05; discuss before starting):** every machine as
   stable as stock; +Drive closer to the DT2's structure; all DT2 features smooth; a stronger
   DDRW bitcrush; **Elektron-style sample and recording naming**, as the DT2's NAMING screen:
   the character grid with FUNC, and **UP / DOWN scroll the character at the cursor through
   the letters and numbers** (owner 2026-11-06), LEFT / RIGHT move the cursor.
2. **Octatrack-style rec trigs: the first thing built after v0.40** (owner, 2026-11-04:
   "implement rec trigs after this"). A trig that records a set length (or until stopped),
   QREC (starts on the next bar / interval), maybe QPL; for bouncing heavy machines to
   samples. **Design (owner, 2026-11-06), building in v0.41** (docs/rectrig.md): the REC lock
   is set from the RECORDER overlay (ours, over any track): hold a step, turn H: OFF / REC 1 /
   REC 2; it records SRC/CHAN for R.LEN steps (MAX: the pattern's length) into a RAM buffer,
   not saved or normalised. Two buffers, each double-buffered over the DSP's four recorder
   slots (REC 1: SAMP 124, slots 123/125; REC 2: SAMP 125, slots 124/126). QPLAY: the track
   switches to the new take at the first boundary after it ends (OFF: as it starts); QREC: a
   manual RECORD NOW waits for the boundary. RIGHT on the RECORDER: the REC TRIGS view.
3. **Slides on the sample and Machinedrum machines' own controls** (owner, 2026-11-03).
   Today only their shared slots slide (filter, amps, FX sends, LFOs). Per machine: mark
   which of its controls are continuous (the detented choices never slide: TYPE, SAMP,
   modes), and check each sliding control changes the sound mid-note (MD machines and
   STRT read some controls only at note-on: those would slide silently, so leave them
   out). Gate: choices never move during a slide; continuous ones land on the lock.
   Start with the sample machines (TUNE) and MD.
0. **Aggregat** (owner, 2026-11-03: "after 40"): read github.com/70b185/Aggregat (its
   `export/aggregat.sqlite`, the research map) before the next new DN2 work, for known DN2
   facts and dead ends (they report three DN2 mod platforms loading at the same RAM
   address); later, maybe contribute our unit-proven facts, credited to De-Pattern only.
4. **Capicola time-stretch** (heavylight; `Capicola Stretch for DT2.7z` in the owner's
   project): after rec trigs and slides. A switch on the sample machines vs his separate engines:
   compare first, then the owner decides.

## Next (from v0.10; historical)

Built in v0.10 (2026-10-19), waiting on the instrument:

- **Voice stealing on RESONATOR and CZ** (`dnfw.voices`): the newest voices render up
  to the cap and the oldest are stolen, so the dynamic voice setting no longer leaves
  dead notes (owner: *"if its a fixable bug/behavior"*).
- **CZ note-off** (`docs/cz.md`): the DCW envelope's steps after sustain run on the
  frame's note-off.
- **PING / SHFT TYPE by name** on the FLTR page: SVF / LADR / VCFQ / LPG and
  UP / DOWN / BOTH (`docs/ping.md`).
- **W3: Waverider osc 2** (`docs/w3-osc2.md`): page 2, DETN LEV POS TBL / - MPOS MLEV -,
  off by default. Its own RATE and MOVE (a second scanner) are not built.
- **GRAN** (`docs/gran.md`): a granular effect as filter type 8.

Still to do:

- **PING P3**: tuning by ear on the instrument (the owner wants it *"rounder and
  prettier"*), and the response curve drawn as PING's.
- **GRAN**: FREEZE, and the envelope on SIZE or SPRD (decay and release are free).
- **The owner's own tables in a build**: `dnfw waverider slice` output into a table
  slot. This needs table compression first, since each table is 16 KB. The binding
  limit is now the USB upgrade buffer, 16,350 bytes left (`docs/usb-upgrade-limit.md`).
- **GRAINS G1** (`docs/grains.md`), a grain *oscillator* machine, as distinct from
  GRAN the effect.
- **L1 is full.** Every gap in the DSP's L1 tail is now used, so the next DSP feature
  moves more read-only tables to DDR first, as GRAN did with PING's and SHFT's.

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

### Decided 2026-10-13: one PING section, four types, its own envelope

Owner: the Mutable-style SVF, a Roland-style filter, a round LPG with exponential/log
(variable) decay, and VCFQ "if we can even do multiple … maybe an amalgamation of
everything with the best parts decided by you". Beads is now open source (MIT, per
the owner, 2026-10-12); Nebulae is the preferred reference for later granular work.

**Design (proposed):** one filter slot per voice, after the reader, with TYPE choosing
the core. All four share one zero-delay-feedback engine, with the same keytracking,
soft-saturating feedback, hard output ceiling and built-in strike, so four types cost
little more than one:

| TYPE | what | character |
|---|---|---|
| SVF | Mutable `stmlib`-style 2-pole, LP↔BP↔HP | clean, glassy, stable at any Q |
| LADR | Roland-style 4-pole OTA cascade, soft-clipped feedback | thick, rounded, squelchy |
| VCFQ | Serge-style resonant band-pass, Q into soft self-oscillation | the ping: watery, vocal |
| LPG | vactrol low-pass gate: the envelope opens level and cutoff together | the bongo: round, liquid |

Controls (8): TYPE FREQ RES DRIVE / ATK DEC CURVE ENV, where CURVE runs log ↔ lin ↔
exp, DEC is variable decay and ENV is the envelope's depth on the cutoff.

**Open: where the 8 controls live.** WaveTone's spare records cannot hold them as well
as osc 2's page: only 7 spare records have a 0..127 range, and osc 2 needs 3 of them.
Waverider getting records of its own (relocating the parameter table, option B in
`docs/waverider-m7-pages.md`) would unlock this, osc 2, GRAINS and every later machine.

**First step:** a Python reference model of all four types with audition WAVs
(as `grains/` did), so the sound is chosen by ear before any firmware.

### 2026-10-13: the owner's ear, and PING moves to the FLTR page

Owner, on the demos: *"these sound pretty good, especially 2, 4, and 8"* (LADR thick,
LPG bongo, VCFQ liquid fast). Mostly for **percussion synthesis, non-melodic**. And:
*"is it not going to be possible to put these somewhere where it will be possible to
use them on any machine, like the actual filter selection page?"*

**Yes, and it is probably the better home.** It is the same pattern Waverider used for
machines, applied to filters [D, from what this project has already read]:

- The FLTR page offers 6 filter types (Multimode, Lowpass 4, Equalizer, Comb-, Legacy
  LP/HP, Comb+). The frame unpack maps the page's type through a lookup to the DSP's
  own number (0->1, 1->3, 2->2, 3->4, 4->5, 5->6), and **anything else becomes 0, no
  filter** (`dnfw.waverider.frame.FILTER_TO_DSP`). That mirrors the machine lookup W5
  patched for type 5.
- The DSP renders each track's filter through a jump table, `0x8052dbc0[filter
  type]`, 7 entries (`docs/sharc-voice-path.md`). That mirrors the machine dispatch
  Waverider's loop is entered from.
- **The FLTR page's own records almost exactly fit PING's controls**, which also
  solves the records problem: FREQ (67), RESO (68, the ring time), the type's third
  parameter (66, the sub-type SVF/LADR/VCFQ/LPG), env depth (69, ENV), the filter
  envelope's delay/attack/decay/sustain/release (70-74: ATK, DEC, and CURVE on one of
  the others), key tracking (79).

So **PING becomes a 7th filter type**, selectable on any machine, the stock ones
included. Its own envelope is computed at sample rate from the filter envelope's
settings, with the curves.

To find out before committing (instruments: the ColdFire emulator for the filter
selection list and the page's labels; the SHARC runner for the dispatch, the unpack
lookup and the filter envelope's form):

1. where the FLTR page's type list is built, and whether it can take a 7th row the way
   MACHINE SEL took WAVERIDER;
2. whether the 7-entry dispatch table can take an 8th entry, or the type must be
   redirected the way the machine loop was;
3. what the stock filter envelope delivers to the DSP (per block or per sample), so
   PING's own envelope reads its settings correctly;
4. the gate extended: **filter types 0-5 bit-identical to stock**, as machines 0-4 are.

Tuning for percussion: strike-led, an option for FREQ not to follow the note (fixed
pitch), a noise component in the strike, and later a modal "bowl" sub-type (a few
inharmonic modes).

## Priorities (owner, 2026-10-29)

1. **DSP stability first**: the Machinedrum, Monomachine and sample machines stable, smooth
   and reliable in CPU terms before any new feature (bugs still fixed meanwhile).
2. **Parameter slides** next once stability allows: a per-trig slide (TRIG page 2: SLD on,
   SLEN in steps) gliding every value the trig changes from the track's current one.
3. **Later, maybe**: from complex-ping's Overtone (github.com/complex-ping/overtone, also a
   DN2 mod): LOOP (track/mix/input looper), cross-modulation between LFOs and arps, per-track
   insert effects, GROOVE (weighted steps in place of swing), envelope followers, a DSP load
   meter. Its code may also show other ways of handling the DSP budget; not studied yet.

## After v0.32 (owner, 2026-10-29)

- Remove what is left of the retired engines: SHIFT (frequency shifter), GRAN (granular
  filter type), CZ PHASE and RESONATOR: their code, generators, tables, DSP spans, tests
  and gate steps, once v0.31 and v0.32 are out.

## Requests and ideas (owner, 2026-10-31)

- **A MACRO page**: 4-8 knobs on one page, each a macro of up to 5 modulation mappings
  (mapped as the velocity and aftertouch macros in SETTINGS are, but with a knob), every
  knob visible with a renamable label, the page per track (choose which), so several
  macros are turned at once -- the Analog Four mk2's Perf mode. One macro per knob, all
  its mappings moving together, live. Weight unknown; after the stability work.
- Holding SYN to show the values on our pages (O14): v0.35.
- **Port to stock OS 1.12 (future, owner 2026-11-01: not needed now).** 1.11 already has
  Outbox 8; 1.12 adds routing the main outputs through it. The DSP program is byte for byte
  the same in 1.12 (checked), so only the ColdFire side moves: ~385 patch sites and the C's
  stock addresses (mostly a constant shift per region; every edit's stock-bytes check refuses
  a misplacement), and the gate's 1.11 emulator snapshots rebuilt. Its own release; then
  build only on 1.12. Overtone (complex-ping) is on 1.12.
- **Undecided (owner, 2026-11-01, "let's sit on it")**: PROJECT RAM shown as one list
  (or renamed POOL) instead of split into INCOMING and RECORDED, leaving those two as
  +DRIVE folders only.
- From the Discord audit (`docs/feedback/2026-10-30-discord.csv`): pattern direct jump,
  Markov song mode, an LFO matrix, trigless trigs, parameter slides, screen streaming,
  MD/MnM preset import, per-track flanger/phaser, capicola stretch, per-project sample
  pools.

## v0.35: the bug sweep (2026-11-01; the owner: "we cant keep pushing releases with the same bugs present")

The scraper's list (`docs/feedback/2026-10-31-discord.csv`, DELTA-01..15) worked through,
fixed in the tree and gated: DELTA-12 (MACHINE SEL's empty FLTR column after RIGHT from a
machine low in the list: stock keeps the list's scroll across columns; gate 6r walks it),
DELTA-04 / M3 (a held key's repeat items restarted the +DRIVE preview; ours now ignore a
repeat of a key they took), DELTA-08 / O14 (SYN held shows every page's values; 6r), DELTA-10
/ P1 (LOAD TO PROJ took two library samples of one length and a seven-letter stem for one),
DELTA-11 (a folder emptied by ticking goes; the page removes folders: DROP, link 6), B10
(PERC's names followed the last page drawn, not the active track), M5's instrument (ENTRY,
`dn2diag.py entries`). Open with instruments: DELTA-01 / M1 (VO-6: the model sweep over
every consonant x CLEN, `out/vo6/sweep.py`), DELTA-02 / M2 (two voices: ask for the USB mode
(Overbridge streams the track buffers) and the DSP load with FUNC held), DELTA-05 / M5
(`entries` says whether the DSP will play slot 2), DELTA-07 (no steps). The gate: no page of
ours may draw blank again -- 6r checks drawn columns and pages, not only memory.

## v0.34: the timing model and the P-I voices (2026-10-31, docs/timing-model.md)

Done in the tree: the output guard's wipe (O13: a wiped voice never reset), its record on
the page and over USB (DIAG), SCAN (non-finite words in any DSP memory range), the fuzz
on the real-rate audio interrupt (gate 6q), the memory-cost clock (runner 3s-F), the
model's NaN as the core's. Next, in order: the owner's SCAN readings on his unit (are
voice 1's P-I lines poisoned at power-on, while idle, or after a note?), then the cause;
the +DRIVE preview retrigger (M3); B10; the Monomachine tables to L2.

## The +Drive library, then a Transfer-style page (owner, 2026-10-30)

1. **On the instrument first**: RENAME, MOVE (MOVE SELECTED, then MOVE HERE, as the DT2's
   13.6.5) and CREATE FOLDER in the +DRIVE browser, and the link commands for each, so the
   computer can do the same (lib.c: rename an entry, change its folder, add a folder;
   each write to the index checked, as the rest).
2. **Then the import tool as Elektron Transfer's Explore**: two panes, the computer's
   folders on the left (the browser's folder access), the +Drive library on the right by
   folder. Drag from left to right sends; on the right, drag to move between folders,
   rename, delete and new folder from a right-click menu, each tick-selectable; the transfer
   queue below with each file's progress and result. The pool (PROJECT RAM) and the
   recordings stay their own view.
   **Done on the page (2026-10-31, link 5 as it is):** the two panes (this computer |
   the instrument, with tabs for the +Drive library and the project slots), tick-select on
   both sides, Send into the open folder or each into its own, drag rows (or WAVs straight
   from the desktop) onto the right, DELETE SELECTED (whole folders' samples too), NEW
   FOLDER, the transfer queue with each file's progress and result. **Still needs the next
   firmware**: link commands for MOVE (`smp_lib_move`), RENAME (`smp_lib_rename`) and
   removing an empty folder (`smp_lib_folder_drop`); the unit-side functions exist since
   v0.33, only lib.c's `smp_lib_rx` lacks the commands (24, 25, 26), then drag-to-move and
   rename on the right pane. Also for that firmware: LIST sends only 24 of a name's 35
   characters, so long names that share a start (sample packs: "CYMATICS - TRAP & 808S 8…")
   all look the same on the page (it tags repeats with their entry number until then);
   a LIST with the whole name.
   (2026-10-31: the page also reads AIFF / AIFF-C and, through the browser's decoder,
   FLAC, MP3, OGG and M4A, at 48 kHz.)
3. Also asked: **capicola** (heavylight's keyframe stretch, AGPL, github.com/heavylight-
   industries/keyframer-lab) as a CAPI switch on STRETCH, as the DT2 mod's; after the
   stability work (its SHARC glue, run.asm and dt2.c, not public yet).

# Roadmap (this fork)

What the owner has asked for and is not built yet, in the words he asked for it, with
enough of a plan that it can be picked up cold. Upstream's own parked ideas are in
`docs/ideas-backlog.md`.

## Next

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

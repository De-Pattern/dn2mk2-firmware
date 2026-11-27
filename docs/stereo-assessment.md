# Stereo sampling: an assessment (2026-11-12, revised the same day)

The owner asked for this before any code (ROADMAP, 2026-11-10). The first draft proposed L/R
pairs on two tracks and a WIDTH control; **the owner rejected that** (2026-11-12): "its just a left
and right channel", look at how the DT2 (or the Octatrack) does it.

## The design, as the DT2 does it (owner, 2026-11-12)

- **One sample, one slot, an internal L/R split.** One entry in the sample list, marked ST.
  The DT2's own sample file is the same: one file, a mono/stereo flag in its 64-byte header
  (`docs/drive-library-plan.md`, `docs/drive-storage-research.md`).
- **Stereo through the whole voice.** The DT2 has "16 stereo audio voices" (manual 4.1); the
  chain is SRC machine, bit reduction, overdrive, SRR, filter, base-width filter, amp, pan, the
  sends, track level. A stereo sample stays stereo through all of it, and PAN acts as balance.
- **No new controls.** No WIDTH, no pairs, no helper.
- **CHAN STEREO** on the recorder (the DT2's STEREO L R, MONO L, MONO R), for **IN and MAIN**.
  It may become the default. TRK on a stereo sample track records the track's stereo.
- **Mono samples and existing projects unchanged.**

## Separate and removable (owner, 2026-11-12)

- All stereo work is on its own branch, `stereo`, from v0.51, with its own builds and gate runs.
- One constant turns it on (`STEREO = 1`); every change is in its own commits.
- If it costs too much, takes too much room or goes wrong anywhere, v0.51's line simply never
  merges it. Nothing on `main` changes until the owner says so.
- The pool and +Drive formats stay readable by builds without stereo: a mono entry is
  byte-for-byte today's, and a stereo one is marked so that an older build can refuse it cleanly.

## What the DN2's chain is (measured 2026-11-12)

`scripts/sharc_stereo_probe.py`, on the SHARC runner (stock section 7, track 0, a triggered
note). Facts:

- **The whole per-track chain runs in place on one mono block** (`TRACK_BUFFERS[t]`, 32 floats).
  After the machine's render, sw `0x1c8ef1` calls, in order, on that one buffer:
  `0xb8251b`, `0x1cdb56`, `0xb80c39`, `0xb8265b`, `0xb81368`, `0xb82342` (the filters, the DC
  blocker and a level: `docs/waverider-feasibility.md`), then the amp `0xb80345`. Each has its
  own state block for the track (track 0: `0x250020`, `0x24fa20`, `0x24f320`, `0x250160`,
  `0x2533e0`, `0x2505a0`, `0x2547a0`).
- **Mono becomes stereo only at the output**, in `0x1c244d` (`0x1c24bb..0x1c254b`). It pans the
  mono block into the stereo buffer `0x259f68 + 0x100 k` (here L = R: PAN centre).
- The per-track stereo buffer `0x257ee8` and the routing buffer `0x258f68` stayed zero in this
  run; where the stock fills them (overdrive? the sends at non-zero levels?) is **not yet read**.

So on the DN2, unlike the DT2, **the chain itself is mono**.

## How stereo can work on the DN2

**Run the track's chain twice, once for L and once for R, then pan them apart.**
- Our sample machine renders L into the track's block and R into a second block.
- The same seven stock stages run on R with **a second copy of each stage's state** (so the
  filter's memory of L never leaks into R), with the same settings, p-locks and LFOs.
- At the output, L and R go to their sides, PAN as balance, instead of one mono block panned.
- The sends get both channels.

This is what the DT2 does, done with the DN2's own stages: one voice, the same filter, amp and
envelopes, in stereo. No second voice and no change to voice allocation.

## Cost

- **DSP:** a stereo note costs the chain twice plus a second channel of our render. The sample
  render is about 2.6 % of the frame a voice (`docs/dsp-cost.md`); the chain's own cost a track is
  to measure (the probe can count it). The guard counts it as it does now.
- **Voices:** unchanged. A stereo note is still one voice.
- **Memory:** 2x a sample. The pool (400 MB after the RAM check, 128 MB proven otherwise;
  `docs/sampler.md`) holds about 70 minutes of 48 kHz int16 mono, so about 35 minutes of stereo
  (23 and 11 at 128 MB). The +Drive's image is the pool byte for byte, so the same limit.
  FLEX's 32 MB recordings area holds about 5 1/2 minutes mono, about 2 3/4 stereo.
- **ColdFire:** the stereo flag, the recorder's STEREO, the list's ST, the formats. Small.
- **The DSP's room:** seven extra state blocks a stereo track and a second buffer. To measure
  against the L2 map.

## The open questions (to answer before code)

1. **Is `TRACK_BUFFERS[t]` per track or per voice?** The frame's records are per voice (sixteen
   146-byte records, `docs/lfo4-build-plan.md`). If a polyphonic sample track's voices each have
   their own chain, then "twice" is per voice; that changes the cost, not the method.
2. **Where the stock fills `0x257ee8` and `0x258f68`** (overdrive, the sends): both channels must
   reach them.
3. **Can the seven stages run a second time a block safely?** They are called with R4 = their
   state. A second call with a copied state is the plan; its effects on anything else the stage
   touches (shared tables, ramps) must be read first.
4. **The chain's cost a track,** counted.

Each is answerable on the SHARC runner before any firmware change.

## What the emulator can prove, and what only the unit can

| question | emulator | hardware only |
|---|---|---|
| the recorder writes both channels, the take equals IN's L and R | yes, coupled | |
| the stereo slot format, import, pool and +Drive, SAVE/LOAD | yes, ColdFire and unit tests | |
| the second chain pass: R through the same stages equals L's math on R's input | yes, bit for bit on the runner | |
| a stereo sample's L and R reach the output on their sides, PAN as balance | yes, the runner's output buffers | |
| the image as heard, the sends' stereo | partly | yes |
| DSP load with many stereo voices | the runner's cost step | the unit's meter |

## What armio's DN2 port shows (2026-11-13)

`github.com/armio/dn2-dt2-firmware-research` (AGPL-3.0; it relocates Elektron's DT2 DSP code)
puts the DT2's sample machines on the DN2, stereo included. **Read for addresses and method only;
nothing of it is copied here.** What it settles:

- **The same method as ours.** `build_dn2_right_process.py` relocates stock's per-track chain
  (`0x1c8ef1..0x1c9c5d`, the function our probe found) to run a second time on the right channel,
  with its own state from an "effects-only" constructor and independent voice resets
  (`build_dn2_right_engine.py`). The output then uses the DT2's own pan/balance/mixer code.
- **Question 1 answered: per voice.** Their paired records are sixteen 472-byte records, one per
  voice, and the frame record at `0x25c566 + 146 v`. A stereo note costs the chain twice for its
  voice, not for the track.
- **Question 3, partly:** a second pass needs its own state and its own reset, which they built.
  Possible, not free.
- **Storage clash.** Their sample area is the DT2 layout, LBA `0x5D8000..0x2DF0180`. All four of
  our +Drive regions (`docs/erase-mod-data.md`) are inside it: their FORMAT SAMPLES erases ours, and
  either firmware's writes damage the other's. Users moving between the two must back up first.

## A runner gap that matters for stereo (2026-11-13)

armio found that the SHARC runner executes `6b_shiftimm` (shift by immediate) on PEx only in SIMD.
Ours has the same gap: `sharc_dn2_fixups.py`'s G1 two-pass branch needs a `compute[22:16]` field,
and `6b_shiftimm` has none. **Stock's chain hits it**: on the probe's run, SIMD `6b_shiftimm` at
`0x1c948f` and `0x1c94a1` (48 each, inside the chain) and at `0xb840e6/0xb840eb/0xb84225/0xb8431b`.
PEy's result (and its status) is then stale; armio saw an even-count loop run its odd tail.
Stereo measurements wait for the fix (route `6b_shiftimm` in SIMD through `two_pass`), with a
test, and a check of what it changes in the gate's SHARC steps.

## Next

Answer the four questions on the runner, then report to the owner with the cost before any code.

## Measured (2026-11-13): who fills the stereo buffers, and what a second pass costs

`scripts/sharc_stereo_probe.py` on the runner (M4's voice run, one note on track 0), with and
without the `6b_shiftimm` fix (identical results: the fix changes nothing this probe sees).

- **Who fills them.** After the chain, stock's mixer call `0x1c304d` writes the post-chain buffers
  (`0x258f68`, routing A, at `0x1c1f4e..0x1c24a1`; `0x259f68`, raw panned, at `0x1c24bb..0x1c254b`).
  `0x257ee8` stays zero on this voice. A mono voice's L and R are equal (centre pan).
- **The chain's cost, per run:** 60,493 instructions a block (of the block's 154,175 with one
  voice playing). The body's own 15,039; its calls 0xb80c39 10,512, 0xb82342 9,728, 0x1cdb56 8,384,
  0xb80345 3,924, 0xb81368 3,264, 0xb82096 2,592, 0xb8265b 1,701, 0xb8251b 1,570, 0x180100 1,551,
  the rest under 1,000. Nearly all of it is per-channel work (filters, amp, envelope, the body):
  **a second pass for R costs about 55,000-60,000 instructions a block for each stereo voice.**
- **Against the budget:** a frame is about 666,667 cycles; stock idles about 63-65 % of it
  (docs/dsp-time.md). A stereo voice adds about 9 % of the frame in instructions, more in cycles
  (DDR stalls, not modelled). With nothing else heavy running, roughly 6-7 stereo voices fit; with
  Machinedrum/Monomachine/FASCIA voices playing, fewer. Sixteen stereo voices do not fit.
- **What follows for the design:** stereo per voice, only when the voice's sample is stereo (a mono
  sample costs nothing more), and a cap on simultaneous stereo voices (the guard's load figure, or a
  fixed number) beyond which a stereo voice plays mono (L+R). Confirm on the unit with the load meter.

## Measured (2026-11-14): what a second pass must repeat

`scripts/sharc_stereo_state.py` (M4's voice run, one note on track 0; every DM read and write of the
traced block's chain run, tagged with the call it happened in). Facts:

- **`0x1c8ef1` is one run for all sixteen voices**, not one call per voice: its run writes about
  2,800 words across every voice's state blocks (strides `0x240`, `0x30c`, `0x2e8`, `0x55c`...). A
  second run "for one voice" does not exist; the R pass has to be a per-voice copy of the chain.
- **The stages' own memory is small.** What each stage call reads and writes back, for track 0:
  `0x1cdb56` `0x24fa34`, `0x24fa50` (it writes `0x24fa30..38`, `0x24fa4c..54`); `0xb80c39`
  `0x24f380..84`; `0xb81368` `0x2533f8..fc`; `0xb82342` `0x2505ac..b0` (and writes `0x250660..68`);
  the amp `0xb80345` `0x2547bc`, `0x2547c8`; `0xb8251b` and `0xb8265b` none in their state.
- **Their parameters are set before each call** by the body and by the helpers `0xb809cb`,
  `0xb82096`, `0xb813e8`, `0xb8028c` (written into the state blocks: e.g. `0xb82342` reads
  `0x2505b4..bc`, `0x2505d0`... that `0xb82096` wrote this block). A second call for R can use L's
  parameters as they stand and keep only the stage's own words per channel.
- **The body works on the block itself too**: one per-sample loop at `0x1c9492..0x1c949e`, between
  `0xb8251b` and `0x1cdb56` (a constant `0x3fcade01`, about +4 dB, in it). An R pass has to repeat
  that step as well as the seven calls.
- The block is written in this order: the machine's render (`0x180100`, ours), `0xb8251b`, the body's
  loop, then `0x1cdb56`, `0xb80c39`, `0xb8265b`, `0xb81368`, `0xb82342`, the amp.

- **How the body calls them** (`--show`, the digikit dossier's mnemonics): each stage is called in a
  loop over the sixteen voices (`R15 = 0x10`, the state pointer stepped by the stage's stride, e.g.
  `0x14` for `0xb8251b`, `0x70` for `0xb80c39` from engine `+0xe088`), so the chain is stage by stage,
  not voice by voice. Each call: `R4` the voice's state, `R12 = R8` the voice's block (read from the
  block-pointer table through `I5`), `R9` and `R2` pushed (the amp also `R1`, from engine `+0x1390c`).
  Call sites: `0x1c9459` (`0xb8251b`), `0x1c94fd` (`0xb80c39`), `0x1c959f` (`0xb81368`), `0x1c95b4`
  (`0xb8265b`), `0x1c95c9` (`0x1cdb56`), `0x1c98af` (`0xb82342`), `0x1c99cc` (the amp).
- **The body's own step is a gain**: `0x1c948c..0x1c949e` multiplies the block by `0x3fcade01`
  (1.5849, +4 dB) when its condition holds; nothing kept between blocks.
- **Stage 2a on the runner** (2026-11-14, gate part `smp`): a format-2 sample plays (L + R) / 2,
  bit for bit the float32 sample of its mix, and bit-exact to the model.

## Stage 3 built (2026-11-14): the R pass

`dnfw.sampler.stereo` (stereo.asm, L2 0x200a9400; its data 0x200ac000, zeros): each of the seven
stage call sites is pointed at a wrapper. No stereo slot in use, or a mono voice: straight on to
the stage. A stereo voice: L's call as stock, then the stage again on R's block with R's state
(a word changed by anything but the stage follows L; the stage's own words stay R's), the +4 dB
step read from L's block (unchanged / x the constant). Each extra call copies the six words
above the wrapper's frame (the body's arguments) and makes its own frame, so calls and returns
pair as stock's.

- **Runner** (`scripts/sharc_stereo_rpass.py`, M5, one ONESHOT note, voice 0 stereo in test
  mode: R's block is L's render): after every stage R == L bit for bit (84 of 84 over 12
  blocks), and every voice's block is bit-identical to the same run without stereo.
- **The runner's decoder** reads the code at the assembler's boundaries
  (`scripts/sharc_stereo_walk.py`): a 16-bit add before `I3 = R0` read as one 32-bit
  instruction at first; the address arithmetic now uses the DSL's own idiom (R12, R13).

## Stage 4, what is next: the voices into the tracks, the tracks into the mix

- After the chain nothing writes a voice's block. It is read at `0x1c2515..0x1c2554`: a loop
  over the sixteen voices that adds each block, times a per-sample gain (the voice's level and
  its fade ramp), into its track's buffer (`0x259f68 + track x 128`); the voice's level word
  from `0x2578b8`, its track from `0x257898`, its block from the pointer table `0x257ea8`. Then
  the mixer call at `0x1c304d` takes the track buffers to the stereo bus with PAN.
- So R needs the same: R's block times the same gain into an R track buffer, then to the right
  side where L's goes to the left. Next: read that loop and the mixer exactly (the gains, the
  ramp, where PAN is applied), then add R's sum and its side behind `STEREO`, checked on the
  runner (a stereo voice with R == L must give stock's mix bit for bit).

## Stage 4 built (2026-11-14): R into its track's R half

What the runner showed (scripts/sharc_stereo_rpass.py; panread/pcread probes):

- **Between the amp and the sum** the body runs two per-voice gain ramps on the voice blocks
  (`0x1c99ed`: a level ramp; `0x1c9a59`: a fade), sample x ramp, ramp stepping each sample.
  The R pass does not copy them: the amp's wrapper keeps L's block and fills it with 1.0, a hook
  between the loops (`0x1c9a3a`) keeps the first ramp, and a hook before the sum (`0x1c2512`)
  makes L = r2 (r1 x) and R the same, stock's own multiplies in its order.
- **The sum** (`0x1c2515`) adds each voice x 11.6266 (minus a fade step a sample when its fade word
  is set) into both halves of its track's 64-word buffer at `0x259f68 + 0x100 track`. A hook
  after it (`0x1c2557`) adds g R - g L into a stereo voice's track's R half.
- **Checked**: with R == L every track buffer is bit for bit the mono run's, 8 blocks; with R
  silent the L halves are exact and only the R halves change.
- **Where the halves go**: their only readers are the sum and the per-channel output loops
  (`0x1c2680`, `0x1c26c7`), which send each track's L half and R half as separate channels
  through a routing table at `0x25d77c` (32 entries: track k's L, then its R). The main bus
  (`0x25bb68` L, `0x25bbe8` R) is built from `0x258f68`, which is fed from per-voice stereo
  buffers at `0x257ee8 + 0x100 v` that the runner never writes (filled outside the code it
  models). PAN's gains are computed per track (`0x254db4`.., `0x254f74`..) but never change
  the voice block or the track halves. **So that R reaches the right side, with PAN as
  balance, is a test for the unit**: a stereo sample with the L channel only should come out on
  the left.

So the R pass is: after the chain, for each stereo voice, the same eight steps on the R block, each
stage with a copy of its state whose parameter words follow L's and whose own words are R's (rule:
a word changed by anything but the stage follows L; what the stage itself writes stays per channel;
both copies equal at the note's start). Next: read the body's loop and the helpers' parameter writes
per voice (which words, which voice stride), then build that pass behind `STEREO`, checked on the
runner against L's math on R's input, bit for bit.

## The build, in order (owner, 2026-11-13: "stereo with a voice cap")

Each stage its own commits behind `STEREO = 1`, each with its emulator check (and a negative
control), on the `stereo` branch; nothing merges to `main` until the owner says so.

1. **Format.** A pool entry's format word: 1 int16 mono (today, byte for byte), 2 int16 stereo
   interleaved. Builds without stereo refuse 2 cleanly (their check: a format they don't know is not
   loaded). Import of a stereo WAV keeps both channels (today it mixes down); the list shows ST.
   ColdFire + unit tests.
2. **Render.** Our sample render reads format 2: L into the track's block as now, R into a second
   block per voice. A mono sample is unchanged, bit for bit (the gate's SHARC steps).
3. **The second pass (question 3 first).** Read each stage of the chain for state it shares beyond
   R4 (tables, ramps, the envelope's position). Then: for a voice whose R block is live, run the
   chain again on R with a copy of each stage's state, kept per voice. Runner check: R through the
   chain equals L's math on R's input, bit for bit, when L = R.
4. **Output.** L and R to their sides at `0x1c244d`'s pan, PAN as balance; both reach the sends.
5. **The cap.** At most N stereo voices a block (start N = 4; the load meter on the unit decides);
   past it a stereo voice plays L+R mono through one pass.
6. **Recorder.** CHAN STEREO for IN and MAIN (and FLEX's takes), writing format 2.

## Stage 2b built, and the R pass made general (2026-11-14)

**2b, the render** (`dnfw.sampler.program.stereo_voice`). A format-2 sample on a voice with a
stereo slot is read twice a block: L from the left channel into the voice's block, then R from
the right into its slot's R block (`RBLK`), each bit for bit an int16 mono sample of that channel
alone, R with its own decimator. The voice's own words are put back as L's run left them. One copy
of `voice()` runs up to three passes (L, L again on a new note's first block, R), so the program
stays inside its L2 room. Past the cap of four slots a stereo voice plays the mix (stage 2a). Each
block starts with the slots' R blocks zeroed, so a voice the guard leaves out has a silent R too.

**The runner's moving-parameter check found three gaps in the R pass**, now closed:

1. *The body's +4 dB step* was caught only at 0x1cdb56's wrapper, which some sounds never call.
2. *Five more stages* sit on the per-voice dispatch other filter types and modes take
   (`scripts/sharc_stereo_calls.py`: every call of the body under random sounds and every filter
   type): 0xb81a16, 0xb80f2e, 0xb806f5 (two sites), and second sites of 0x1cdb56 (between a x16
   and a x1/16), 0xb81368 and 0xb8265b. All are wrapped now (`STAGES`, `EXTRA_SITES`).
3. *Two of them reach past the voices' spacing* from R4 (0xb81a16 to +0x1fc, 0xb80f2e to +0x140;
   `scripts/sharc_stereo_foot.py`), so each stage's state is copied by its measured size (`SIZES`).
   R's call now runs on the voice's own state place (R's copy swapped in, L's put back after), so a
   stage that reaches its state another way still sees R's.

**One generic wrapper.** Each site jumps to a small stub (is this voice stereo? which slot?) that
sets the stage's words (stride, size, offset, trampolines) and goes to one shared body. Between
stages the body's own scalings of L's block are recognised, not copied: each wrapper after the
first compares L's block on entry with what the last wrapper left (`LLAST`); unchanged, or that
block times +4 dB, 16 or 1/16 bit for bit, and R's block gets the same. An all-zero L keeps the
last answer. Anything else (the comb filters: 0xb81526 writes its own buffer, which the body then
mixes into the block) is counted (`ODD`) and the voice falls back to mono for the rest of the block
(`MONO`: R's block is L's), so it can never sound wrong, only narrower.

**Runner checks** (`sharc_waverider_m5.py --steps stereo`, a gate part of its own): every run
bit-exact to the model, R's block included; R = L renders each channel bit for bit the mono
sample; R = L leaves all 16 tracks' buffers after the sum (both halves) and the main mix bit for
bit the mono run's, every block, with the sound's parameters moving, on **every filter type**
(the combs through the fallback); ODD only on a comb; R silent leaves every L half exact and
changes track 0's R half (R's path is live); R = -L/2 renders R's block bit for bit the mono -L/2
sample.

**Known for the test build:** the comb filters play a stereo sample's L on both sides (the
fallback); the sends (reverb, delay, chorus) take L only; that R reaches the right output is the
hardware test.

## Field reports on v0.54-t1 (Error Kit, NiKo, Discord #bug-reports, 2026-11-15): the bug list

The test build was pulled (owner) after these. Worked: the import page's "keep stereo", the size
doubled, ST in the browser. Failed:

1. **Preview** of a stereo sample: nothing.
2. **A track on a stereo sample is silent**: the waveform is drawn, the playhead moves, no sound
   (an 8 s sample; NiKo the same).
3. **SLICE**: YES for 16 slices says **NO SAMPLE**.
4. **Other tracks stall**: an FM Tone track needs 2-3 trig presses before it sounds.
5. **A loud click** when the stereo sample's track is triggered again.
6. **After a power cycle**: a click on that track, then **nothing on any track**, synths included
   (NiKo). The DSP's audio stops: the worst of them.

**Why the gate passed:** every stereo check ran in test mode (R made on the DSP from L's render).
No step took a real stereo WAV through the import page, the sample link, the pool and the DSP's
load, nor previewed, sliced or power-cycled one.

**Before any new stereo work:** a coupled gate step of the field route: a real stereo WAV imported
(keep stereo), loaded, previewed, played on a note beside an FM Tone track, sliced (16), then the
project saved and loaded again (the power cycle). It passes only when the stereo sample sounds with
L and R its own channels, the FM Tone track sounds on its first trig, no voice clicks (a jump
limit), PREVIEW sounds and SLICE finds the sample. Negative control: v0.54-t1 must fail it (items 2
and 4 at least). Then fix each item until it passes; then the sends and CHAN STEREO.

Also (Error Kit, 2026-11-17, an idea, not for now): an FX machine on the input or another track,
"like the Analog Heat": FLEX's routing into a track of effects, the source muted or mixed wet/dry.

## The cause of v0.54-t1's silent track (2026-11-25)

**Stock's pan stage ran while a stereo voice's block held ramps, not sound.** After the amp,
stock's chain runs two gain ramp loops on each voice's block (`0x1c99ed`, `0x1c9a59`), then, at
`0x1c9ae7..0x1c9b30`, a **pan stage**: each voice's block x an L gain ramp and x an R gain ramp
into that voice's stereo buffer (`0x257ee8 + 0x100 v`: L 32 floats, R 32 at `+0x80`). The sends
(`0x1c179d`) and the routing to the main bus (`0x1c1fb0`) read those buffers. v0.54-t1 measured
the two ramps by leaving 1.0 in the block from the amp until its hook before the sum
(`0x1c2512`), which is after the pan stage. So a stereo voice sent `gain x ramp`, a level with
no sound in it, to the main bus and the sends, and its sample only to the per-track outputs
(the track buffers, which is all the runner's checks looked at). That is the silent track (2),
the clicks at each retrigger (5, a step in that level), and most likely the main bus driven so
far by the level that nothing else was heard (4, 6). To be confirmed on the unit.

**Why the runner never showed it (G12).** The pan stage reaches the stereo buffers through
`I0 = MODIFY(I1, M4)` with the buffer's byte address in M4 and no width suffix (Type 7a, w = 0).
The runner scaled every MODIFY's M by 4, which is right only for `(nw)` (w = 1: the same loop
steps a pointer table with `MODIFY(I3, M6) (nw)`, M6 = 1). Its stores went to four times the
address, so the stereo buffers were zero in every run, for stock's voices too: no run ever
modelled the path a note is heard through. `sharc_dn2_fixups.py` G12 now adds M unscaled for a
MODIFY with no width (and Type 7b); the buffers fill, L == R at PAN centre for a mono voice.

**The fix** (`stereo.py`, `_pan_hook` at `0x1c9ad2`, after the second ramp loop and before the
pan stage): the block becomes L = r2 (r1 LAMP) and the slot's R block R = r2 (r1 R) there, so
the pan stage and the sum both read sound. The stereo buffer's R side is written by the hook,
R x the R gain ramp computed as stock does (the voice's gain word at `0x254f90 + 0x38 v`, plus
its step at `0x254f98 + 0x38 v` a sample from the second sample on), and stock's own write of
that side (L x the R gain) goes to a scratch block for this block (the table's entry at
`0x258eec + 8 v`; the hook before the sum puts all sixteen entries back). PAN is stock's own
gains on each side, so it acts as balance; the sends read both sides.

**Held by the runner's stereo step now:** each voice's stereo buffer after the pan stage: with
R == L bit for bit the mono run's on every filter type (and sounding on both sides); with R
silent the L side the mono run's and the R side silent; the table stock's after every block.

**The ColdFire's part** (after the merge with v0.73):
- **SLICE** (3): the analysis, the fine view and the zero-crossing snap read a stereo slot (the
  louder side for the envelope and peaks; (L + R) / 2 for the frames the editor draws and snaps to).
- **PREVIEW** (1): a stereo slot in the pool is previewed in stereo by the DSP (`pvmix`: a frame
  a word, L to the L side, R to the R); a stereo sample on the +Drive is sent mixed down.
- The sampler's scratch words past the 64th go after the recorder's GAIN words (`SC_OVER`):
  the 65th, WERP's `segnext`, had lain on the recorder stage's first float since v0.40
  (harmless: each is written and read within its own run), and the preview's new word is kept
  from block to block.
- **The sample program is 27 KB** with the L and R render, past its 24 KB after PERC: it is at
  L2 `0x200b0000` (32 KB) on this branch, between the room proven on units and PERC. The first
  build with code there: a test for the unit (every sample machine runs from it).

**Still to do before a test build:** the coupled field-route step (a stereo WAV through the
import, the link, the pool and the DSP's load; preview, a note beside an FM Tone track, slice,
save and load), the sends heard in stereo, CHAN STEREO on the recorder, the gate.

## The field route on both processors (2026-11-27): a stereo note against its two halves

**What the first route step got wrong.** Its failures (a silent first note, R silent, NaN) were the
harness's, not the build's:
- **The coupled emulator silences a track's later voices on every build.** Each voice after the
  first on a track reaches the chain's dispatch (sw `0x1c950e`) and leaves it zero. Measured with
  plain mono samples on v0.76, the released build, so this is the emulator's own limit (a unit plays
  chords). The track's third voice there also carries huge values (1e29) into the track buffer,
  which a stereo voice turns into NaN. So a coupled check can hear only the first note after boot.
- **It read the track buffer before the stereo hook ran.** It read at the sum's end
  (`0x1c2557`), the patched instruction itself, so the R half still held stock's g L. The hook
  returns at `0x1c255a`.

**Now** (`emu_coupled_stereo.py`, the gate's `stroute`). Three runs, each from the power-on load
and each playing one note as the first note after boot, so on voice 0:
- the stereo sample (L a 200 Hz saw, R a 330 Hz sine);
- the same note as a mono sample of its L channel;
- the same note as a mono sample of its R channel.

Stereo is right when it is exactly those two halves. Measured on v0.76-t1 (2026-11-27):
- **Track buffer, L half:** the L run's, bit for bit, every block.
- **Track buffer, R half:** the R run's to float rounding (1e-8; the hook adds g R - g L onto
  stock's g L).
- **Every stage of the chain:** each stage's input for the R pass, and the amp's R output, are the
  R run's bit for bit (`diag8`, `diag9` in the hunt).
- **The voice's stereo buffer** (the pan stage's output, read by the main bus and the sends): the L
  side is the L run's and the R side the R run's, exactly from the second block on. The note's
  first block takes the mix first and then L, so it is within 2.5e-7.
- **Faults:** no NaN anywhere.

The negative control is v0.54-t1, with its own layout.

**The runner, too:** `sharc_stereo_leak.py` finds no register and no engine-memory word
(`0x240000..0x260000`) that differs, at any stage call of the voices after a stereo voice, between
a stereo run and a mono run. That holds with one slot or two, in DUP or not.
`sharc_stereo_slots.py` cannot drive a second voice through the chain on the runner: its frames
carry no voice allocation.

**Still not checked by any emulator:** two or more stereo voices at once, a retrigger, and voice
stealing. The coupled emulator silences every voice after the first, so these are for the unit.

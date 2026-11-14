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

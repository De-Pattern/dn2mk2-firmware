# The timing model: what the unit does that the emulators could not see (v0.34, 2026-10-31)

The reports this answers: the unit freezing (the screen stuck, keys dead, audio stopped);
all audio cutting out while the sequencer keeps running, until a restart (CAT, 14 reports
in the owner's audit); dropouts with heavy Machinedrum and Monomachine voices; and v0.33's
O13: P-I machines silent on the same voices every time (voice 1, then 4; P-I RS 1, 4, 9,
10, 12). The question put to this: what are the likeliest causes of each, what on the
hardware do digikit's ColdFire and SHARC emulators not model, and what model and what
instrument on the unit would catch each before release.

## 1. The symptoms, and what each one can and cannot be

The unit has three things that can stop, and each stops differently. Read the symptom
by which of them stopped:

| what stopped | what you see | what it means |
|---|---|---|
| **the ColdFire took an exception** (access error, illegal instruction, address error: a bad pointer in our C, a jump into stale code) | the screen shows `EXCEPTION DSxxxx Vnn M.. P........` and the unit halts | the default handler at `0x40001252` masks interrupts, prints the vector and the registers through `0x4011ea6a`, then executes `halt`. **Every unhandled ColdFire exception draws this screen.** A freeze that keeps the normal screen is **not** a ColdFire exception |
| **the DSP stopped** (an illegal opcode or an L1 parity error jump to `0x1c07c6` and never return; or its core hung) | the audio stops, or a short loop of it repeats (the output DMA replays its last two pages); the screen and keys keep working; the sequencer keeps running | the ColdFire's ISR keeps running: the DMA rings on both sides keep moving, the SPI reply ring replays, so nothing on the ColdFire waits for the DSP. The reply's word 0 (the DSP's cycle count) freezes |
| **the DSP runs but its sound is poisoned** (a NaN or infinity in a feedback state: a filter, the delay, the reverb) | all audio silent (or a stuck tone) until a restart; everything else works | before v0.33 any non-finite sample from our voices reached the stock chain and stayed in the delay and reverb. v0.33's output guard holds every sample we make to ±8 and wipes a voice that goes non-finite |
| **the ColdFire's audio ISR starves the UI** (the ISR runs longer than a frame, so the next interrupt is late and the main task gets no time) | the screen freezes, keys are dead, audio continues or stutters; it recovers if the load drops | the ISR takes 54-56 % of the ColdFire's time on stock patterns, with peaks of 75-83 % (`docs/coldfire-tasks.md`). It runs on whatever task's stack; the main application task (prio 6) and the UI are below it |
| **the UI task is stuck** (a loop in our page code, a wait that never ends) | the screen freezes, keys are dead; audio continues (the sequencer and the ISR are not in that task); any sounding note keeps its tail, nothing new starts if the sequencer is driven from the UI task | no EXCEPTION screen |

So:

- **"Screen stuck, keys dead, audio stopped", no EXCEPTION screen** (Pablo's video, the
  owner's O5): the ColdFire did not take an exception. The two readings that fit are the
  ISR starving the UI for good (a frame that stays too long: a loop in the ISR path whose
  bound depends on data, or a per-frame cost that stays past the frame), or the UI task
  stuck while the DSP also lost its notes. v0.33 fixed the one known ISR-path cost that
  grew with the project (`smp_mod_apply` walking 128 slots for every modulated voice, up to
  4,096 checks a frame) and the sample list taking keys unseen; neither has been shown to
  be the whole story. What the emulator could not do until now: run the ISR on its own
  clock while our UI code runs (section 3.1).
- **"All audio cut out, sequencer running, until a restart"** (CAT, Moog, 14 reports): the
  DSP poisoned, or stopped. The P-I finding below makes the poisoning the likely one: a
  P-I voice's memory holding a NaN sends NaN into the FX bus, and before v0.33 nothing
  stopped it. v0.33's guard contains it per voice; the wipe that followed was broken
  (section 2), so the voice stayed dead instead -- which is exactly O13.
- **Dropouts with heavy voices**: the DSP's frame budget. The guard leaves voices out when
  the measured frame is short; the owner's meter reads 52-70 % with P-I voices, under the
  guard's limit, so the dropouts the testers hear now are not the guard's. The runner's cost
  model understated the unit (instructions, not memory): section 3.2.

## 2. O13: found, and what is still open

**Found (confirmed by running the model and the real DSP code in the runner):** v0.33's
output guard, when it wiped a voice (`dnfw.perc.program.out_guard`, `blown()`), stored
register R0 into the buffer and the voice's 32-word state. `dsl.loop()` uses R0 as its
counter, so the state got 32, 31, ... 1 instead of zeros: the `on` word stayed nonzero,
the reset that a fresh voice gets (`MDV.reset`: the Machinedrum words and the P-I delay
lines cleared) never ran, and the NaN stayed in the voice's memory. Every later note on
that voice went non-finite again and was wiped again: **silent until a power-on, on the
same voices every time**. That is the owner's report. The model and the DSP agreed
(bit-exact), which is why no gate caught it: the gate compared the two, and neither test
asked whether the voice came back.

**Fixed (v0.34):** the wipe stores a register the loop does not touch; the next block
resets the voice and a new note sounds. Checked by `test_perc_live`
(`test_v034_the_output_guard_really_wipes_a_poisoned_voice`: a NaN poked into a P-I
voice's delay lines or into the filters' state mid-note) and by runner step 3w (`wipe`):
the real DSP code on digikit's runner, a P-I voice's delay lines all NaN from block 4, the
guard's record right, the state all zeros, the next note heard.

**Also fixed, the model's NaN:** the PGR's float ALU entries (Fx + Fy, MIN, MAX among
them) say a NaN *input* gives an all-ones result; digikit's core does that. Python's
`min(1.0, nan)` is 1.0, so until v0.33 the Python model could clamp a NaN away that the
DSP carries on -- the model and the unit disagreed on exactly the case the guard exists
for. `dsl.fop` now carries a NaN input through every float operation, as the core.

**Still open: why voices 1 and 4 (P-I RS: 1, 4, 9, 10, 12) go non-finite in the first
place.** The runner and the model do not reproduce it: P-I BD's own arithmetic is clamped
to [-1, 1) at every store, retriggers with the tail left in place run clean, and every
per-slot address (the L2 state at `0x200A0000` + 1 KB t, the delay lines at `0x82200000`
+ 8 KB t) is uniform with no overlap in our own placements. What the runner cannot see,
and the instruments in section 4 will:

1. **Something on the unit writing into the delay lines.** They sit at DDR `0x82200000`,
   outside the range complex-ping proved (`0x80A00000..0x81000000`) and far above the
   stock program's static claim (`0x8052FBE0`; the engine's init writes to `0x80530BE8`).
   Checked statically (this session, `sharcimm.py` over every stock code block with
   `--min-depth 3`): **no stock code immediate names a DDR address above `0x80530000`**;
   the only hits are misdecoded floats. The stock boot stream's own DDR fills (4.5 MB at
   `0x80000018`, 526 KB at `0x804ACE8C`) come after its init block, as ours do, so DDR fill
   blocks do reach the RAM. A run-time computed pointer (one stock dispatch path in the
   runner writes 32-word bursts through a pointer the runner never initialises,
   `docs/w5-tables.md`) and DMA with a computed `ADDRSTART` are the two things no static
   scan excludes. The P-I lines are the only per-voice memory in DDR, and P-I machines are
   the only ones that die: consistent with this, not proof.
2. **The lines' own zero-fill at power-on** (a 128 KB fill block, v0.32). Stock relies on
   the same block type into DDR, so a failed fill is unlikely; a *partial* one, or one that
   lands before the DDR controller is up on some boots, is what the boot-time scan answers.
3. **The core's state at our entry** (circular buffering on, `L0..L5` not zero): evaluated
   and set aside. Stock zeroes `L0..L5` at start-up, the dispatch is C code that keeps the
   ABI's invariant, the runner's stock path shows them zero at the render call, and PERC's
   `DM(I5, M6)` post-modifies have run on units since v0.11: a nonzero L at entry would
   have corrupted memory on every voice, every block, from the first build. Not changed.

## 3. The models built

### 3.1 The ColdFire: the audio interrupt at its real cadence (`emu_waverider_menu.py --isr-frame`)

Until now the emulator never ran the audio ISR on its own: `frame:` steps entered it as a
subroutine (`guest_call`), between keys, and the UI's clocks (the frame counter
`0x4058e8d4`, +1 per ISR, which every one of our timeouts and repeats reads) stood still.
No interrupt had ever landed inside our ColdFire code in a test.

digikit has an exact-deadline event source for exactly this chain (`emu/ssi.py`,
`Ssi0Dma`): SSI0 requests at a given rate drive the eDMA channel-48/50 minor loops as the
programmed TCDs say, the channel-50 major loop's interrupt raises vector 170, whose
handler forces vector 191, and that is the audio ISR `0x40025e36`, entered with a real
exception frame and left by its own `rte`. The harness now opts in:

- `--isr-frame F`: one audio frame (32 requests, the TCD's major loop) every F
  instructions of the UI's. **Calibration:** on the unit the ISR takes about 55 % of a
  frame (`docs/coldfire-tasks.md`); here it runs about 40,000 instructions, so F = 75,000.
  (digikit's instruction clock is `emu.pit.INSTR_PER_SEC`, a proxy for its timers; the SSI
  rate is set so that the *ratio* of ISR work to UI work is the unit's. The two clocks are
  not the same time base: the 30 Hz tick is slower, relative to the audio, than on the
  unit. What this model is for is the ISR preempting our code and its cost; it is not a
  wall-clock model.)
- Three things stood in the way, all artefacts of the harness, and all silently absorbed
  by every `frame:` step since v0.14:
  - the snapshot's vector 170 is the frame-alignment routine (`docs/audio-dma.md`), which
    waits for the DSP's `0x007FFFFF` marker before it installs the normal callback; no DSP
    here, so the harness does what its success path does (the pending callbacks into
    vectors 168 and 170, the aligned flag);
  - the snapshot was booted on v0.14, and v0.14's hooks were still in its memory where the
    current build leaves stock (its frame-builder hook at `0x400276a2` jumped into code
    that is no longer there: every `frame:` step ended in an illegal-instruction exception,
    which the fault reporter recorded and v0.33's fuzz had to dismiss as "runs on stock
    too"). The section the snapshot was booted with now sits beside it
    (`<snapshot>.section_3_MAIN_OS.bin`) and its edits go back to stock before the build is
    installed;
  - the patched Unicorn does not decode ColdFire's `BITREV` (ISA_C), and stock's voice
    allocation finds its lowest free voice with `bitrev; ff1` on every note: the first
    [TRIG] press with the interrupt running raised vector 4 at `0x4002aa80` on stock
    firmware itself. digikit shims `FF1` and `MOVEC` per address; `emulib.machine` now
    shims `BITREV` the same way. (Before this, no note ever allocated a voice in the
    emulator: a whole class of stock behaviour was never run.)
- What it reports (`isr` in the JSON): deliveries (vector 170, vector 191, the ISR's rte),
  the frames counted, the ISR's cost per delivery (instructions from its entry to its rte,
  worst and mean) and **overruns** (a delivery costing more than F: on the unit the next
  frame's interrupt is late and the UI starves).
- **The fuzz (gate 6q) runs on it by default.** A seed now also fails on a CPU exception
  (with the interrupt delivered the real way, the firmware's fault reporter is a real
  sign: on the unit it is the EXCEPTION screen), on the interrupt no longer being
  delivered to the end, and on more than one frame in twenty overrunning. Random key
  sequences with the interrupt landing at arbitrary points in `rec.c`, `smp_page.c`,
  `lib.c` and `link.c` is the test that did not exist.

**What it measured (the v0.34 candidate):** the stock ISR runs about 40,300 instructions a
frame with stock tracks; our link hook (`smp_tdm_hook`, the packet in and out) adds about
420 (1 %), and `smp_mod_apply` nothing until a sample machine modulates SAMP. In the fuzz,
with sample machines on all sixteen tracks and a pool loaded, the ISR averaged 47,600 and
peaked at 49,200: about 18 % over stock. On the unit the stock ISR already peaks at 75-83 %
of a frame on a busy pattern (`docs/coldfire-tasks.md`), so sixteen sample tracks with
modulation can push a frame's interrupt to its edge: the UI starves while it lasts (the
screen freezes, keys are dead, audio continues). That is the one plausible reading of the
"frozen, no EXCEPTION, audio still playing" reports that this model gives numbers for, and
the gate's overrun count (6q) now watches it; cheapening our per-frame work (the loaded
list built when the pool changes, not every frame; the packet only while a job runs) is
the v0.35 item.

What it does not model: the ColdFire's own memory stalls (its instruction count is not
cycles; the 55 % calibration folds the average in), the MIDI task and the other tasks'
share, DSPI and eMMC latency (the eMMC reads happen in the UI task through the stock block
driver, 64 KB at a time, so their cost is UI time, not ISR time), and the DSP peer (the
RX half holds what the snapshot held).

### 3.2 The SHARC: the memory-cost clock (runner step 3s, scenario F; step 3c's calibration)

On the unit a DSP cycle is mostly memory: an L2 access costs several instruction times,
a DDR one about ten (`docs/others-dn2-research.md`); the stock render code runs at about
9 cycles an instruction (`docs/sharc-load.md`). The runner counts instructions. v0.32's
stress test fed the guard's clock at K = 3 cycles an instruction, uniformly.

- Step 3c now also measures the **whole block** (the unpack, the stock machines' standing
  work, the mix), nothing sounding: its instructions and its accesses by region, and
  solves `instructions + S x (4 L2 + 10 DDR) = 416,000` for S, the unit's silent frame
  (reply word 0, 62 % of 666,667). That S is the calibration of the weights
  (`memory_weight_scale` in the report).
- **The calibration came out consistent:** the silent block is 170,461 instructions,
  1,032 L2 and 26,923 DDR accesses in the runner; with complex-ping's weights the unit's
  416,000 cycles need S = 0.898. So "an L2 access costs about 4 instruction times, a DDR
  one about 10" reproduces the unit's silent frame within 10 %, from an independent
  measurement. The stock's silent frame is 63 % DDR time by this account: its render code
  mostly waits on memory, as `docs/sharc-load.md` inferred from the 9 cycles an instruction.
- Step 3s scenario F runs the worst case (sixteen P-I voices, every control and track
  effect moving) on a clock charged by where each access lands:
  `cycles = instructions + S x (4 L2 + 10 DDR)` (S from `DNFW_MEM_SCALE`, default 0.9).
  The guard must keep our voices inside 0.8 of the frame, leave voices out and count
  them, and every buffer must be finite.
- Per-voice costs in `docs/dsp-cost.md` are the same estimate; the unit's meter is the
  measure. The owner's readings with v0.33 (P-I BD: 52-56 % a tap, 65-70 % sequenced;
  P-I RS 42-52 %) are in the range the estimate gives (about 3 % a P-I BD voice over the
  build's 46 % floor), so the model is not far off for P-I; VO-6 and DDRW, whose tables
  live in DDR, remain the ones to measure.

### 3.3 The entry state and the stock's DDR

Evaluated, not changed (section 2, point 3, and the static scan in point 1). A gate step
that would make the DDR question a hard check -- "no stock code immediate and no resolved
DMA descriptor names a DDR address inside any region of ours" -- is a `sharcimm.py` run
over the stock code blocks with our regions as the ranges; `docs/w5-tables.md`'s runner
ceiling (`sharc_ddr_ceiling.py`) is the dynamic half. Neither can see a computed pointer;
section 4's scan can.

## 4. The instruments on the unit (v0.34)

Everything here is read-only on the unit except the scan command, which only reads DSP
memory and writes its own scratch.

1. **The guard's record.** When the output guard wipes a voice it records which slot and
   machine (`BLOWN_INFO`), where the voice's P-I delay lines first held a non-finite word
   (`BLOWN_WHERE`: the index | `WHERE_DELAY`, or `WHERE_NONE`: the poison was in the
   voice's own state, its input or the effects), that word's bits, a count, and a mask of
   slots since the ColdFire last heard. The link's idle packet carries them (units 19..22);
   `link.c` keeps them.
   - **On the screen:** FUNC held on a PERC or Monomachine page, within two seconds of a
     wipe, the tempo's place shows `V<n><where>`: the voice 1..9, A..G for 10..16, then
     `D` (its delay lines held the NaN), or `X` (they did not). `V1D` on the owner's unit
     says the poison is in voice 1's delay lines in DDR; `V1X` says it is not.
   - **Over USB:** SysEx DIAG (command 24) returns the record, the DSP load, the slots
     ever skipped for time, and the periods and frames counters.
2. **SCAN (SysEx 25, DSP command 10).** Any DSP address range (L1, L2, DDR), by address,
   walked 1,024 words a block: the count of non-finite words and the first one's index,
   through VERIFY's status halves; DIAG returns the last result. The questions it answers,
   each a minute's work on a unit over USB, before any note is played and again after:
   - *Right after power-on, before any note: are voice 1's and voice 4's delay lines all
     finite?* (`SCAN 0x82200000 2048`, `SCAN 0x82206000 2048`.) No: the fill at boot did
     not land, or something wrote there before the first note.
   - *While nothing plays, over a minute: does the count change?* Yes: something on the
     unit writes there at run time. The address of the first bad word says where.
   - *After a tap kills voice 1: which word, and is it inside the range P-I BD reads?*
   - *The L2 state slots* (`SCAN 0x200A0000 4096`) and the PERC state (`SCAN 0x2DE180
     512`), the same way.
3. **The load meter and the skip mask** (v0.30-v0.32) stay as they are; DIAG returns them.

A tool for the owner (`tools/dn2diag.py`, next) would run DIAG and the four scans in
order and print a verdict in plain words; until then the import page's console or a probe
script can send the two commands (`DN2.request(seq, 24)`; `DN2.request(seq, 25, [addr
LE32, words LE32])`).

## 5. What the gate now catches, and what it still cannot

| would have caught | step |
|---|---|
| the guard's wipe leaving a voice dead (O13's persistence) | 3w wipe; `test_perc_live` |
| a NaN the model clamps away but the DSP carries | `dsl.fop`'s core-faithful NaN; 3g garbage now means what it says |
| an interrupt landing inside our ColdFire code mid-operation (a race on the link's job words, the library index, a list) | 6q with the real-rate ISR |
| our ISR-path code costing more than a frame | 6q's overrun count |
| a CPU exception in our ColdFire code under random keys | 6q (the fault reporter is a real sign again) |
| voices left out when memory, not instructions, sets the cost | 3s scenario F |

Still not seen: a run-time writer into our DDR (the scan on the unit is the instrument);
the ColdFire's cycle-level timing and the other tasks; the DSP's own interrupts landing in
our code (`docs/for-digikit-waverider-dsp-stop.md`: the one thing no runner pass covers);
eMMC latency; two processors' clocks drifting (the TDM alignment).

## 6. For v0.34

In this build: the guard's wipe and record, the NaN-faithful model, SCAN and DIAG, the
page's `V<n><where>`, runner steps 3w and 3s-F, the fuzz on the real-rate interrupt, the
snapshot's section restored before a build is installed. Not in it: the +DRIVE preview
retrigger (M3), B10, the Monomachine tables in L2.

Checked by the gate as every build is; the SCAN and DIAG commands are checked on the
model (`test_sampler`) and the DSP's SCAN runs in the runner's own memory; they are not
yet exercised on a unit.

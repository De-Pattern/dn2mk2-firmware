# Wavefinder on the DN2: what it is, and what it would take

**Opened 2026-09-25**, at the owner's request: emulate Tonverk's **Wavefinder**
as a sixth DN2 machine. The mockup is a published artifact, built on the real
factory wavetables.

## What the machine is, from Elektron's own manual

Tonverk User Manual OS 1.4.1, section **A.2.5**, cited in our words:

> Two independent wavetable oscillators that can be blended and modulated
> separately. The position within a wavetable selects which waveform plays, and
> animating that position over time is what makes the timbre evolve. SRC Page 1
> is oscillator 1, Page 2 is oscillator 2.

**Sixteen parameters over two pages of eight** — which is exactly the DN2's page
shape, so the control surface maps with nothing left over:

| | page 1 | page 2 |
|---|---|---|
| A | `TUNE` bipolar pitch | `DTUN` detune from osc 1 |
| B | `LEV` | `LEV` |
| C | `POS` position in the table, **interpolated between waves** | `POS` |
| D | `SLOT` wavetable, **127 per project, p-lockable per step** | `SLOT` |
| E | `SPD` one cycle of the ANIM shape; looping shapes snap to beat divisions | `SPD` |
| F | `A.LEV` modulator depth on LEV | `A.LEV` |
| G | `A.POS` modulator depth on POS, **signed** | `A.POS` |
| H | `ANIM` which modulator shape | `ANIM` |

`ANIM` has **12 shapes**: five one-shots (Exp Down, Ramp Down, Tri, Ramp Up,
Exp Up), four looping (Ramp Down, Tri, Square, Ramp Up), Random, Sample and
Hold, and "Wavetable 1/2" — the *other* oscillator's output used as a modulator.

## The data, measured from Elektron's own tables

`Wavetables.zip`, the factory set for the Wavefinder SRC machine:

| | |
|---|---|
| tables | **75** |
| format | **IEEE float32, mono, 48 kHz**, uniformly |
| frame size | **2048 samples** — every file's length divides by it; no `clm` chunk |
| frames per table | **2 to 64** (64 is the most common; Bowed Lowed has 15) |
| total | **30.3 MB**; largest single table **512 KB** |

Our own `src/dnfw/wavetable.py` already reads exactly this shape — float32 WAV,
2048-sample frames when the length divides by it. So the import side is **done,
not estimated**.

> **Qualified 2026-09-26 (Milestone 0):** done for the factory shape, not for every
> table. `wavetable.parse_wav` (and its parity twin `site/js/wavetable.js`) keeps
> every digit in the five characters after a `clm ` chunk's `<!>`, so a
> `<!>256 00000000` header reads as a 2,560-point frame. Serum's `<!>2048 ...` is
> unaffected, which is why nothing has noticed. Wavefinder reads the frame length
> with `dnfw.wavefinder.source.clm_frame` instead; the LFO path is left alone
> because it ships, and is recorded here rather than silently fixed.

## The gap, in five parts

### 1. Control surface and parameters — the part already proven

Adding a page of eight parameters with names, ranges, display and p-locks is
what LFO4's fourth `[MOD]` page did, end to end, on hardware. The machine list
ceiling is now read (`docs/machine-list.md`): `moveq #4` at `0x400dc332` and
`0x400dc358`, table at `0x401f77f4`, rows of 12 bytes.

**Known. Days, not weeks** — with the one real trap already recorded: the 192
zeroed bytes after the table are a live 16-long array indexed at `0x400dc1fe`,
so a sixth row needs space found elsewhere.

### 2. Storage — settled, and it is the cheap half

**Tonverk has an SD card. The DN2 does not.** That looked like the blocking
problem. It is not, because of a decision the owner made on 2026-09-25 that
removes the expensive part entirely:

> **The wavetable set ships with the firmware.** The user picks their tables in
> our own tooling and bakes them into the image **before flashing**. No browser,
> no file navigation, no user-facing storage management at all — `SLOT` simply
> indexes a fixed set.

That is not a new mechanism to invent. **`lfowaves` already does exactly this**:
`dnfw mods apply firmware.syx --mod lfowaves --wavetable N=FILE`, WAV or JSON in,
byte-identical between the CLI and the browser page. Wavefinder is the same
pattern with bigger tables, so the import path is not merely designed, it is
**shipped and parity-checked**.

And it removes the item that makes every DT2 machine expensive: a file browser
grafted into someone else's UI framework (`docs/dt2-machine-port.md`).

**The mechanism, decided by the owner:** the tables are **baked into the
firmware**, and **at flash time the firmware writes them out into the `+Drive`**.
They are content once installed, not code — the image is the delivery vehicle,
not the home.

I argued for the simpler variant (leave them read-only in an ELE3 section and
index them directly, since a reflash is already accepted). **The owner's choice
stands, and it is the better shape for reasons that outlast the first build:**

- wavetables end up where user content lives, so they can be named, listed and
  eventually replaced *without* the image growing every time;
- the firmware image does not carry a few hundred KB forever, and flash-transfer
  time does not grow with the size of the table set;
- it is how Tonverk itself behaves, so the feature can grow toward the real
  thing rather than away from it;
- and the `+Drive` write happens **once, at install**, not at run time, so the
  audio path never touches storage.

**What it costs that variant A would not:** a write path into the `+Drive`. The
firmware already writes projects and sounds there, so the routine exists and
finding it is ordinary static ColdFire work — our home turf. The **format** is
`DNX`'s authority and must come from them, never be hand-rolled here.

**This is now the critical unknown for parts 1, 2 and 5**, and it is reachable
today without a SHARC core.

### The staging, which settles the A-versus-B argument

The owner's sequencing, and it is right: **bake one table into the firmware's
own space now, and research `+Drive` delivery later.** A and B are not competing
designs; A is the first milestone and B is the destination. The read path can be
proved before the write path exists, and nothing learned by doing A is thrown
away when B arrives — the tables, the reduction, the bake step and the reader all
carry over. Only *where the bytes live* changes.

**Milestone 0, and it is buildable today.** One table, ~16 KB at 16 frames of
512 points, in an appended section, with the firmware reading it back and
reporting a few samples over the telemetry channel.

That is worth doing on its own terms:

- it proves the **delivery vehicle** end to end — reduce, bake, load, address,
  read — which every later variant depends on;
- it **cannot disturb the audio path**, because it adds data and one read, and
  changes no machine, no selector and no engine code;
- it is sized well inside what is already proven: the whole LFO4 feature grew
  MAIN OS by **23.7 KB**, and this is smaller;
- and the telemetry channel is calibrated, so the check is a number rather than
  a judgement.

**What it deliberately does not do:** raise the machine-list ceiling. Selector 5
would be clamped to 4 by the DSP (`min(R2, 4)`, `docs/machine-list.md`) and land
on some other machine's record — untested behaviour on the audio path, for no
gain while there is nothing to render. **The ceiling moves when there is
something behind it.**

**Sizing, at int16, against a section budget the firmware already normalises**
(section 7 is 837 KB; section 8 is 160 KB):

| geometry | per table | tables in 256 KB |
|---|---|---|
| 16 frames x 256 points | 8 KB | **32** |
| 16 frames x 512 points | 16 KB | **16** |
| 32 frames x 512 points | 32 KB | 8 |
| 16 frames x 2048 points | 64 KB | 4 |
| 64 frames x 2048 points (as shipped) | 256 KB | 1 |

For comparison, the whole LFO4 feature grew MAIN OS by **23.7 KB**.

**The geometry is not decidable yet.** How few points per frame stay clean
depends on the oscillator's interpolation and any oversampling — a DSP question,
and part 4 is where it gets answered. What is decidable now is the *budget*: a
few hundred KB is ordinary for this firmware, and at 16 x 512 that is sixteen
tables, which is a real instrument rather than a demo.

### 3. Machine dispatch — partly mapped, on the wrong device

digikit have DT2 1.16's ColdFire dispatch at `0x400caf48` and the DSP selector
chain `0x2567c0[0x255970[track]]`. **Our DN2 equivalents are not located**,
beyond the name-table bound above and a per-track clamp `min(R2, 4)` in
`sw 0x1c2712` that three structures now agree on.

**Weeks.** Ordinary static work of the kind this project does well.

### 4. The DSP render code — this is the feature

A wavetable oscillator on the SHARC: two readers, linear interpolation between
frames *and* between samples, per voice, at 48 kHz, plus a 12-shape modulator
and the blend. **Sixteen voices x two oscillators = 32 readers.**

None of it exists. And the blocker is not the DSP code itself:

- there is **no SHARC core** in any emulator — no QEMU or Unicorn target — and
  digikit cost writing one at **one to two weeks of sessions** before a first
  sound;
- we can assemble SHARC with selache, but it is **GPL-3.0, so never into
  digikit**;
- our own SHARC reading is thinner than theirs, and their DN2 work is
  `[D]`-graded structural comparison, not verified semantics.

**Months, and gated on the emulator.** Writing DSP code that cannot be run is
how `lfo4-bridge` reached the instrument and faulted.

> **Superseded 2026-09-26 (Milestone 1).** The first bullet is no longer true.
> digikit's unmerged branch `work/sharc-emulator` (`6f812e9`) is a working
> SHARC+ executor -- `tools/sharc_core/` plus `tools/sharc_run.Runner` -- and it
> renders one DT2 1.16 voice to within ~3e-5 of expectation. It runs DN2 1.11
> too, and it runs **our own** SHARC code: Milestone 1 below assembled a
> wavetable reader with selache and matched a Python reference bit for bit.
> So part 4 is no longer gated on an emulator; it is gated on reading the DN2
> voice path well enough to hook it (see "The next milestone"). The second and
> third bullets stand. The text above is kept as the estimate it was.

### 5. Persistence and the sequencer

`SLOT` is p-lockable per step on Tonverk. The DN2's reserved p-lock ids and the
sound-object holes are already mapped from the LFO4 work, so this is the same
shape of problem, solved once already.

**Weeks**, after part 2 decides where wavetables live.

## The measured gap

> **Superseded 2026-09-26** by "The measured gap, revised after Milestone 1"
> below. Kept as the first estimate.

| part | state | cost |
|---|---|---|
| wavetable import | **done** (`wavetable.py` reads the exact format) | — |
| control surface, parameters, pages | **proven** by LFO4 | days |
| machine list ceiling | **read** (`docs/machine-list.md`) | done |
| storage decision | **open, and blocking** | a decision |
| DN2 machine dispatch | partly mapped, DT2 only | weeks |
| **SHARC render code** | **nothing exists; no emulator** | **months** |
| persistence, p-locks | same shape as LFO4 | weeks |

**The feature is not close.** The nearest honest milestone is not Wavefinder; it
is a SHARC emulator good enough to run one voice render offline, which digikit
have already scoped and which we would share. *(Superseded 2026-09-26: that
emulator exists, on digikit's `work/sharc-emulator`, and Milestone 1 ran our
own reader in it. What is left of part 4 is the hook, not the core.)* Everything in part 4 is
unreachable without it, and everything else is comparatively cheap.

**What is worth doing now**, in order:

1. **Take the storage decision** — baked-in tables, or `+Drive` project data. It
   changes three of the five parts and costs nothing but a conversation.
2. **Locate the DN2 machine dispatch**, the mirror of digikit's `0x400caf48`.
   Static, our home turf, and useful whatever is decided.
3. **Do not start SHARC render code** until something can run it.
   *(Superseded 2026-09-26: something can. Milestone 1 is exactly that code,
   run and checked offline before going anywhere near the instrument.)*

## Milestone 0, built and emulator-gated (2026-09-26; passed on hardware the same day, see Status)

`python scripts/build_wavefinder_m0.py --name wavefinder-m0` ->
`00_Resources/02_Builds/wavefinder-m0_DN2_1.11.syx` (sha256 `8f5d70a7...24e9`).

**What it is.** `build_lfo4_tlm.py --persist` (release semantics, no page
column diverted) plus one module and one call: `csrc/wavefinder/table.c` holds
the table as `const` data in the C chunk; `wf_m0_report()` runs inside the LFO4
telemetry burst right after `probe_a` = 99, sends one probe point (frame, index,
int16) and one slice of a whole-table checksum, CCs 41-50 on channel 16. No
machine, selector, ceiling or engine code changes.

**The table** is original: `dnfw.wavefinder.testtable`, a sine morphing to a
32-harmonic saw over 16 frames of 2048 points, reduced by `dnfw.wavefinder.reduce`
to 16 x 512 int16. `dnfw wavefinder expect` prints what the instrument must send;
checksum **`0x33e5`** (`h = h*31 + w mod 2^16`, frame-major).

**Measured:**

| | |
|---|---|
| table | 16,384 B at `0x468011e4`, inside the `CODE` chunk at `0x46800000` |
| C chunk | 4,164 -> 20,972 B image, 7,016 B BSS, ends `0x46806d54`: **1,020,588 B** free below the relocated parameter table at `0x46900000` |
| MAIN OS raw | +16,808 B over the same build without M0 (3,216,232 -> 3,233,040) |
| MAIN OS stored (aPLib) | +18,236 B (1,137,784 -> 1,156,020). **int16 wavetables do not compress** -- budget flash at about 1.1x raw |
| cost per burst | ~8,510 instructions (1,024-word checksum slice) + 10 MIDI sends, one burst per ~87 ms |

So sixteen tables at this geometry (256 KB) would fit in the RAM gap above as
it stands; the limit to watch is flash and transfer size, not address space.

**`check_coldfire.py` over the whole section now reports the table.** 92 scale-8
"instructions" fall inside `0x468011e4..0x468051e4` -- int16 samples read as
code -- plus the documented record-323 false positive. The code before and after
the table checks clean on its own, and the build's own guard (`cbuild`, which
disassembles only the linked code) passed. A future multi-table build should give
the checker the data ranges rather than read this as new noise each time.

**Gates:** `emu_boot_engine.py` from reset: *"boot from reset, the engine, and
save/load: all three in one machine."* `emu_wavefinder_m0.py` from reset: the
16 KB in memory match the host bake, the probe arrays match, and 18 real bursts
through evaluator A reported 8/8 probes and checksum `0x33e5` computed by the
firmware. `dnfw inspect`: every checksum and the HMAC reproduced.

**Input format for real tables** (`dnfw wavefinder scan PATH`, file or folder;
`dnfw wavefinder bake PATH --out DIR`; `build_wavefinder_m0.py --wav FILE`, local
testing only): any RIFF/WAVE, PCM 8/16/24/32 or float 32/64; first channel only;
sample rate ignored; frame length from `clm `, else 2048 if it divides, else the
whole file is one frame (flagged); frame count interpolated to 16; frames shorter
than 512 points are held, not interpolated.

## Milestone 1, the offline render gate (2026-09-26): our own SHARC code, run and checked

**The question.** Can SHARC code of our own, reading a baked wavetable, be run
and checked before any DSP code goes near the instrument? **Yes.** All three
gates pass, and the reader matches its reference **bit for bit**.

```
python scripts/sharc_wavefinder_render.py \
    --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \
    --digikit ../digikit-wt-sharcemu --assemble --seconds 1.0
```

`--digikit` (or `DNFW_DIGIKIT_SHARC`) names a checkout of digikit's unmerged
`work/sharc-emulator` at `6f812e9`; this gate used a detached worktree of our
digikit clone, `git -C ../digikit worktree add --detach ../digikit-wt-sharcemu
6f812e9`. `--assemble` needs WSL and selache. Without it, the committed
`csrc/wavefinder/sharc/reader.json` is used, and the script refuses it if
`reader.asm` has changed since. Output goes to `out/wavefinder/`: `m1_report.json`,
`m1_sharc.wav`, `m1_reference.wav`.

### Gate 1: digikit's runner on DN2 1.11

The runner takes any `sharcldr.LoadedMemory`, so pointing it at DN2 1.11 is one
line: `LoadedMemory.from_stream(section 7)`. No database and no device profile
are needed. The script checks that section 7's sha256 is `336e340a...3115e2`,
the hash digikit's finding 11 records.

**The routine: `sw 0x1c0790`**, a 13-instruction leaf with three return paths.
It was chosen because it is pure. It reads only its argument and its own return
slot. Its two unsigned compares sit at exact boundaries, so the inputs can land
on both sides of each, which exercises `compu`'s flags, the `LT`/`LE`
conditions and a conditional move. And its meaning can be read without running
it:

    R2 = R4 - 0x28000000
    R2 <u 0x240000   -> return R4
    R2 <=u 0x39ffff  -> return R2        (the L1 byte alias removed)
    otherwise        -> return R4

**Measured.** 11 inputs, including `0x2823ffff`, `0x28240000`, `0x2839ffff`,
`0x283a0000`, `0`, and `0xffffffff`. **11 of 11** return at `sw 0x1c07a6` with
the R0 the static reading predicts, in 7 or 10 instructions. **Control:**
selache's `selmap` decodes the same 52 bytes, and its instruction boundaries
agree with digikit's decoder at every instruction.

**What did not work, from a cold start.** These are informational and are not
part of the gate. They were run with the runner's own CLI on a
`dn2-1.11` database built in the digikit worktree:

| start | halt |
|---|---|
| `sw 0x1c2712` (16-track loop) | after 1,673 instructions: a fork at `sw 0xb8b513` (`GE` on unknown `ASTATX` flags). `--explicit-memory-model` gives the same |
| `sw 0x1c8ef1` (slot dispatch) | after 198: a fork at `sw 0x1c909f`. With `--explicit-memory-model`, after 247: *unsupported shifter op cu=2 0x90* at `sw 0x1c4f4a` |
| `sw 0x1c9e76` | returns after 136 instructions (at `sw 0x1c9e71`; not examined) |

So the executor runs DN2 code, but the DN2 voice path needs a booted state,
which is what digikit built for DT2 (`sharc_harness.setup_voice`, snapshots).
That was not attempted here. One real gap for DN2: **the executor does not run
Type 13a**, a `DO ... UNTIL` whose count is already in `LCNTR`, and digikit's
finding 11 records that DN2 1.11 uses it.

**Speed.** On CPython 3.13, while another job ran ColdFire emulator boots on
the same machine, the runner managed **45,000-48,000 instructions/s**. digikit
report 90-100k on CPython and about 270k on PyPy. PyPy was not tried here.

### Gate 2: a wavetable reader of our own

`csrc/wavefinder/sharc/reader.asm` holds `wf_render(R4 = params)`. It renders N
float samples from the Milestone 0 table: 16 frames x 512 int16, packed two to
a 32-bit word, little-endian. It interpolates linearly between samples **and**
between frames. The phase is a u32 accumulator: its top 9 bits are the sample
index, and it wraps mod 2^32, which is mod 512. The frame position is Q16.

It is 75 instructions and 380 bytes, and it is position-independent, so the
object carries no relocations. Built with `selas -proc ADSP-21569` (selache
`2b26d3b`, GPL-3.0, run in WSL).

The reference is `dnfw.wavefinder.render`, run with `dnfw wavefinder render
OUT.wav`. It has two precisions: `ideal` works in double precision, and
`float32` rounds after every operation, in the same order the SHARC code does.

**Placement.** The reader's blocks are spliced into the DN2 1.11 boot stream,
before its final block, at spans the stream never loads. The script checks
this with `owner_runs`. These spans are unloaded by the boot stream, **not
proven unused at run time**:

| | load address | bytes |
|---|---|---|
| code, `sw 0x180000` | `0x28300000` | 380 |
| table, DM `0x280000` | `0x28280000` | 16,384 |
| parameter block, DM `0x284000` | `0x28284000` | 64 |
| output, DM `0x288000` | `0x28288000` | 16,384 |

**The decode control.** selas's own instruction boundaries are read from the
object's symbol table. The source is reassembled with a global label in front
of every instruction, and the reassembly must reproduce the same bytes.
digikit's decoder must land on all 75 boundaries, with no unknown or uncertain
form. It does.

**Measured: 7 cases, all bit-exact against the float32 reference.**

| case | N | max error vs ideal | float32 mismatches |
|---|---|---|---|
| frame 0 (sine), 440 Hz | 128 | 2.9e-8 | 0 |
| frame 15 (saw), 440 Hz | 128 | 2.8e-8 | 0 |
| between frames 7 and 8, 1 kHz | 128 | 3.5e-8 | 0 |
| odd frame fraction, 97 Hz | 256 | 4.7e-8 | 0 |
| phase wrap 511 -> 0 | 64 | 2.1e-9 | 0 |
| 20 samples a cycle (2.4 kHz) | 64 | 4.5e-8 | 0 |
| zero increment | 16 | 4.7e-10 | 0 |

Full scale is 1.0, so the largest error is under one float32 ulp at 1.0
(6e-8). The phase each call writes back matches the reference in every case.

### Gate 3: a WAV

The WAV is one second at 48 kHz, a 110 Hz tone whose frame position sweeps
0 -> 15 -> 0. The position is updated once per 32-sample block, the way a DSP
updates a parameter, and the phase carries across the 1,500 calls.

- **48,000 samples**, max error vs ideal **5.8e-8**, **0** float32 mismatches;
- the 16-bit PCM is **identical** to the float32 reference's;
- 21 of 48,000 samples differ from the ideal's PCM, each by **1 LSB**. That is
  float32 against double rounding at a PCM rounding boundary, not a fault.

The files are `out/wavefinder/m1_sharc.wav` (the SHARC run) and
`m1_reference.wav` (the ideal).

**Cost.** 38 instructions a sample in the loop, plus 34 a call (measured with
N = 1, 2, 10 and 100). One second of audio took 1,905,030 instructions and
42 s of wall time.

**An estimate only [D].** 38 x 48,000 is 1.8 M instructions/s per reader, so
32 readers need 58 M/s. At the ADSP-21569's 800 MHz-1 GHz (`docs/hardware.md`)
that is about 6-7% of the core **if** every instruction took one cycle. No
cycle model, memory stall or pipeline effect has been measured, and the code
is unoptimised: no multifunction or SIMD instructions.

### What the toolchains disagree on, and how the reader avoids it

Each of these was found by the gate, not by reading, and each is worked around
in the source with the reason in a comment:

1. **`MODIFY (Ia, Mb)`.** selas encodes `MODIFY (I4, M4)` as `0x04240f800000`.
   The shipping firmware's `MODIFY (I4, M4)` is the 48-bit Type 7a
   `0x043f20000000`, and all 497 of its 48-bit MODIFYs use that layout. DN2
   1.11 also has 37 32-bit Type 7b MODIFYs, such as `0x043f653f`. Their second
   parcel ends in `0x3f`, the VISA width marker. selas compresses `MODIFY (I0,
   M0)` in this file to `0x043e0000`. Its fields match Type 7b, but it lacks the
   marker, so digikit reads it as the first 32 bits of a 48-bit 7a. digikit's
   decoder follows the firmware, so it reads both of selas's words as other
   instructions, one of them a conditional `MODIFY` of different registers.
   **The workaround:** a post-modify load, `R3 = DM(I0, M0)`. It is the same
   DAG update, and both toolchains encode it alike.
2. **Immediate `ASHIFT`.** selas encodes `R0 = ASHIFT R0 BY -31` as
   `0x023e0020e100`. The firmware's immediate ASHIFTs carry a different field
   there (`0x02087801e100` is `IF AV R0 = ashift(R0, -31)`), and digikit halts
   on *unsupported ShiftImm opcode 0x20*. selache's own runtime library also
   avoids the immediate form. **The workaround:** the register-count form.
   Immediate `LSHIFT` works and is used.
3. **`selmap` cannot read selas's own 16-bit Type 3c load** (`0x9013`). It
   walks past it and loses three boundaries. That is why the producer's
   boundaries come from the symbol table rather than from selache's decoder.
4. **Type 13a is not executed by digikit.** A separate `LCNTR = R12;` before
   the `DO` assembles to Type 13a, so the reader uses the combined
   `LCNTR = R2, DO ... UNTIL LCE` (Type 12a), the form the firmware uses.

Items 1 and 2 are selache encodings that disagree with ADI's own compiler
output. They are selache findings, not digikit ones. **Which encoding the
silicon accepts is not known.** The reader uses only forms that the firmware
itself uses.

### What is unverified

- **Silicon.** Nothing here has run on a SHARC. The executor is a model, and
  the reader's encodings are checked against digikit's decoder, which follows
  the firmware, not against a DSP.
- **The address model.** The runner treats a DM pointer as a byte address in
  the `0x28000000` alias, with DAG steps scaled by 4 (`assume_nw32`). The
  reader does address arithmetic only through the DAG, so it should not care,
  but hardware normal-word addressing is not what was run.
- **Free memory.** The placement spans are unloaded by the boot stream. They
  may still hold BSS, a heap or a stack at run time.
- **Byte order in transit.** The ColdFire bake is big-endian int16
  (`bake.to_bytes`). The reader wants little-endian (`render.dsp_bytes`).
  Which side swaps depends on a transfer path that does not exist yet.
- **The ABI.** The reader clobbers callee-saved registers. It is a gate
  routine, not a drop-in.

## The measured gap, revised after Milestone 1

| part | state | cost |
|---|---|---|
| wavetable import | **done** | — |
| baked table, read on the instrument | **[V]** Milestone 0 | done |
| control surface, parameters, pages | **proven** by LFO4 | days |
| machine list ceiling | **read** (`docs/machine-list.md`) | done |
| storage decision | **taken**: baked now, `+Drive` later | — |
| SHARC executor | **exists** (digikit `work/sharc-emulator`); runs DN2 1.11 code **[E]** | — |
| our own SHARC code, offline | **[E]** Milestone 1: a reader, bit-exact to its reference | done |
| table delivery to the DSP | **open**: nothing moves ColdFire data into DSP memory yet | weeks |
| DN2 voice-path hook | **open**: chain located, record and output buffer not | weeks |
| DN2 machine dispatch (ColdFire) | partly mapped, DT2 only | weeks |
| the 12-shape ANIM modulator, the blend, two oscillators | not started; now testable offline | weeks |
| persistence, p-locks | same shape as LFO4 | weeks |

The critical path is no longer an emulator. It is two pieces of DN2 reading:
**where a voice's samples are produced and consumed**, and **how the table
reaches DSP memory**. Both can now be answered with a runner that executes,
not only with static reading.

## The next milestone: where a reader would hook into the DN2 voice path (research only)

What is known, from `docs/sharc-voice-path.md` and digikit's finding 11, cited
in our words:

- **The chain.** `sw 0x1c9e76` calls, at `0x1c9fbc`, the 16-track loop
  `sw 0x1c2712`. Inside that loop, a per-track value is clamped to `0..4` and
  shifted left by 9 (`0x1c2947`-`0x1c294f`): a candidate machine selector into five
  512-word records **[D]**. The loop then calls `sw 0x1c8ef1`, the slot/voice
  dispatch (1,352 instructions), at `0x1c3044`. Its `JUMP IF SZ` at `0x1c99a8`
  reaches `sw 0x1c9b73`, 126 instructions with no static caller.
- **`sw 0x1c9b73` calls the stage routines that DN2 shares byte for byte with
  DT2 1.16**: stages 1, 2, 4, 5 and 6 at `0xb81368`, `0xb8265b`, `0xb81a16`,
  `0xb80f2e` and `0xb806f5`. Where they differ at all, the only differences are
  pc-relative call offsets and one table-pointer literal.
- **Stage 5 has the same shape as our reader.** digikit read it as a u32 phase
  converted to an index plus a fraction, with two `DM(I2, M)` taps and a linear
  blend. In DN2 its table-pointer literal is `0x26b3a8`. Caveat: digikit later
  withdrew their reading of the DT2 orchestrator around these stages as "a
  wavetable engine". The stages' shapes stand, but their role in a voice is
  not settled.

**Three candidate hooks, not yet ranked:**

1. **At the selector.** Raise the clamp at `0x1c294c` from 4 to 5 and supply a
   sixth 512-word record. This matches the ColdFire ceiling already read in
   `docs/machine-list.md`. It needs the record table at `I3`'s base found and
   its consumer read.
2. **At the dispatch.** Branch to our reader where `sw 0x1c8ef1` / `0x1c9b73`
   picks a voice's generator for a machine type, instead of running the stage
   chain.
3. **At the output.** Write the reader's block where a voice's samples are
   accumulated. On DT2 that is the per-track accumulate into the master mix
   at `0x25f180` / `0x25f200`. **DN2's equivalent is not located.**

**What Milestone 2 would be, still offline.** Get one DN2 voice to render in
the runner, porting digikit's DT2 approach: poke a voice record and the guard
byte that arms it. Then break at the stage-5 call and substitute our reader's
block for its output. The open questions are the DN2 voice record layout (the
structure at `0x241298` is **[O]**, and its field offsets are in
`docs/sharc-voice-path.md`), the block size (32 samples on DT2), and the
per-voice output buffer.

## Status

**Milestone 0: [V]** -- passed on the instrument 2026-09-26 (test 12,
`wavefinder-m0_DN2_1.11.syx`): a 10 s capture while a synth pattern played held
118 complete bursts, all 8 probe points matched, the checksum read `0x33e5` in
every burst, `probe_a` read 99 in all 118, and `wf_passes` climbed 65 to 79.
Checked with `dnfw wavefinder verify`. The superseded status, for the record:
[E], verified under the emulator from reset, awaiting hardware.

**Milestone 1: [E]** -- 2026-09-26, offline only: our own SHARC reader,
assembled with selas, runs in digikit's SHARC executor inside the DN2 1.11
image and matches `dnfw.wavefinder.render` bit for bit (float32) over 7 cases
and a 48,000-sample sweep; max error against the ideal 5.8e-8. Nothing has run
on a DSP, and nothing is flashed.

**[D]** for the gap estimates — they are reasoned from measured facts (the file
format, the firmware's free space, the machine table bound) but no part of the
feature *as a machine* has been attempted; Milestones 0 and 1 are its delivery
and render gates. The manual citation and the wavetable measurements
are **[V]**: read directly from Elektron's own document and files.

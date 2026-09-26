# Waverider on the DN2: what it is, and what it would take

**Renamed 2026-09-26:** our machine is **Waverider**; *Wavefinder* is Tonverk's, which it is modelled on. Build files made before the rename keep their names (`wavefinder-m0_DN2_1.11.syx`).

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
> unaffected, which is why nothing has noticed. Waverider reads the frame length
> with `dnfw.waverider.source.clm_frame` instead; the LFO path is left alone
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
byte-identical between the CLI and the browser page. Waverider is the same
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

**The feature is not close.** The nearest honest milestone is not Waverider; it
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

`python scripts/build_wavefinder_m0.py --name wavefinder-m0` (now `build_waverider_m0.py`) ->
`00_Resources/02_Builds/wavefinder-m0_DN2_1.11.syx` (sha256 `8f5d70a7...24e9`).

**What it is.** `build_lfo4_tlm.py --persist` (release semantics, no page
column diverted) plus one module and one call: `csrc/waverider/table.c` holds
the table as `const` data in the C chunk; `wr_m0_report()` runs inside the LFO4
telemetry burst right after `probe_a` = 99, sends one probe point (frame, index,
int16) and one slice of a whole-table checksum, CCs 41-50 on channel 16. No
machine, selector, ceiling or engine code changes.

**The table** is original: `dnfw.waverider.testtable`, a sine morphing to a
32-harmonic saw over 16 frames of 2048 points, reduced by `dnfw.waverider.reduce`
to 16 x 512 int16. `dnfw waverider expect` prints what the instrument must send;
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
save/load: all three in one machine."* `emu_waverider_m0.py` from reset: the
16 KB in memory match the host bake, the probe arrays match, and 18 real bursts
through evaluator A reported 8/8 probes and checksum `0x33e5` computed by the
firmware. `dnfw inspect`: every checksum and the HMAC reproduced.

**Input format for real tables** (`dnfw waverider scan PATH`, file or folder;
`dnfw waverider bake PATH --out DIR`; `build_waverider_m0.py --wav FILE`, local
testing only): any RIFF/WAVE, PCM 8/16/24/32 or float 32/64; first channel only;
sample rate ignored; frame length from `clm `, else 2048 if it divides, else the
whole file is one frame (flagged); frame count interpolated to 16; frames shorter
than 512 points are held, not interpolated.

## Milestone 1, the offline render gate (2026-09-26): our own SHARC code, run and checked

**The question.** Can SHARC code of our own, reading a baked wavetable, be run
and checked before any DSP code goes near the instrument? **Yes.** All three
gates pass, and the reader matches its reference **bit for bit**.

```
python scripts/sharc_waverider_render.py \
    --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \
    --digikit ../digikit-wt-sharcemu --assemble --seconds 1.0
```

`--digikit` (or `DNFW_DIGIKIT_SHARC`) names a checkout of digikit's unmerged
`work/sharc-emulator` at `6f812e9`; this gate used a detached worktree of our
digikit clone, `git -C ../digikit worktree add --detach ../digikit-wt-sharcemu
6f812e9`. `--assemble` needs WSL and selache. Without it, the committed
`csrc/waverider/sharc/reader.json` is used, and the script refuses it if
`reader.asm` has changed since. Output goes to `out/waverider/`: `m1_report.json`,
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

`csrc/waverider/sharc/reader.asm` holds `wr_render(R4 = params)`. It renders N
float samples from the Milestone 0 table: 16 frames x 512 int16, packed two to
a 32-bit word, little-endian. It interpolates linearly between samples **and**
between frames. The phase is a u32 accumulator: its top 9 bits are the sample
index, and it wraps mod 2^32, which is mod 512. The frame position is Q16.

It is 75 instructions and 380 bytes, and it is position-independent, so the
object carries no relocations. Built with `selas -proc ADSP-21569` (selache
`2b26d3b`, GPL-3.0, run in WSL).

The reference is `dnfw.waverider.render`, run with `dnfw waverider render
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

The files are `out/waverider/m1_sharc.wav` (the SHARC run) and
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

> **Superseded 2026-09-26** by "The measured gap, revised after Milestone 2"
> below. The two open rows ("DN2 voice-path hook", "table delivery") are now
> one located hook and one still-open transfer.

The critical path is no longer an emulator. It is two pieces of DN2 reading:
**where a voice's samples are produced and consumed**, and **how the table
reaches DSP memory**. Both can now be answered with a runner that executes,
not only with static reading.

## The next milestone: where a reader would hook into the DN2 voice path (research only)

> **Superseded 2026-09-26 by Milestone 2**, below. `sw 0x1c9b73`'s "stage
> calls" are per-track filter renders, and stage 5 is a filter's tanh
> saturator, not a wavetable reader. The hooks are now ranked, and the render
> call ranks first. The record layout, block size and output buffer below are
> answered in Milestone 2, step 1. The text is kept as the plan it was.

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

## Milestone 2, offline (2026-09-26): one DN2 voice in the runner, with our reader substituted

**The question.** Can the DN2's own voice path run in digikit's runner from a
hand-armed state, and can our reader be put where a machine's samples go?
**Yes, with measured limits.** The voice path runs, from the engine init to
the end of the per-track chain, on every block. The firmware's WaveTone
oscillator renders a waveform from its own init-built tables. Substituted at
the machine render call, our reader's block lands in the track buffer bit for
bit, and the per-track stages before the amp keep it. Two things stop an
audible voice at the end of the chain: the amp stage, because nothing
triggers a note, and WaveTone's own 2:1 decimator, which rings in the runner.
Both are measured below and neither is solved.

```
python scripts/sharc_waverider_voice.py \
    --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \
    --digikit ../digikit-wt-sharcemu [--blocks 16] [--seconds 2.5]
```

The first run builds the init snapshot, about 18 minutes (1,104 s), and
caches it as `out/waverider/m2_init_<sha>.snap`. Later runs take about 4
minutes for 16 blocks, at about 3.5 s a block. Every run writes its WAVs and `m2_report.json` to `out/waverider/`.
The numbers below are from the 16-block run of 2026-09-26: 512 samples a
step, digikit `6f812e9`, CPython 3.13 on a shared machine. That run reported
**PASS on all 17 checks**.

**The WAVs** are 2.5 s each at 48 kHz, 16-bit mono. Each is 512 rendered
samples looped out to that length, because the runner renders about 17
blocks a minute:

| file | what it is |
|---|---|
| `m2_voice_stock_osc.wav` | the firmware's WaveTone oscillator 1, hand-armed; every other sample of its 96 kHz output, normalised (raw peak 1.2e-4 of full scale in Q31) |
| `m2_voice_stock_machine.wav` | the track buffer after the WaveTone render: the ±1 Nyquist buzz of the ringing decimator |
| `m2_voice_stock_chain.wav` | the end of the per-track chain: silent (peak 4e-10) |
| `m2_voice_disarmed_osc.wav` | control: oscillator 1 unarmed, silent |
| `m2_voice_reader.wav` | our reader in WaveTone's place, straight out of the track buffer: the Milestone 1 sweep at 375 Hz |
| `m2_voice_reader_pre_amp.wav` | the same block as the amp stage receives it, filtered and about 20 dB down |
| `m2_voice_reader_chain.wav` | the same block at the end of the chain: silent (peak 3.4e-5) |
| `m2_reference.wav` | `dnfw.waverider.render` for the same blocks |

### Step 1: the map, read out of a run

**Getting the path to run at all took seven runner workarounds.** Each one
is a gap in digikit's runner, measured on DN2 1.11. They live in
`scripts/sharc_dn2_fixups.py` (G1-G7) and are written up for digikit in
`docs/for-digikit-sharc-runner-dn2.md`, Part 2.

| gap | effect on DN2 | how we got past it | control |
|---|---|---|---|
| G1 SIMD PEy modelled in 5 forms only | init's SIMD loops fill only the even half of a table | each such instruction run twice in SISD, PEy on a swapped copy | the sine table below |
| G2 `Rn = data32` does not reach Sn in SIMD | PEy's loop constants are stale | Sn set too | odd half of the sine table: wrong without it, off by up to 1; right with it, max error 3.9e-7 |
| G3 (LW) pairs in 4b/3b | a long-word load reads Unknown; the peak search forks at `0x1c4610` | pair load/store as 14a/15a do it | init returns |
| G4 L1 normal-word addresses read as byte addresses | `sinf(x)` returns `x` | NW immediate in an I register ×4 | sinf within 1 ulp of math.sin on 58 inputs |
| G5 Type 2b shadows 16-bit Type 2c | desync at `0x1c0e13` and `0x1c4f4a` | those parcels read as 2c | selache agrees; the code after them is coherent |
| G6 conditional 6a/6b halt | WaveTone oscillator 2 stops at `0x1c4470` | predicate evaluated here | -- |
| G7 Type 13a not executed | not met on this path | -- | -- |

**M1's "unmodelled shifter op at `0x1c4f4a`" is withdrawn.** ~~the first
unmodelled operation we met on the DN2 voice path~~. It is G5, a decode
misread: `0xc029` is the 16-bit `r2 = r2 + r9`. The same misread explains
digikit's provisional `21p_undoc16` / `8p_undoc48` on DT2 at `0x1c32b0` /
`0x1c32b4`.

**Two accelerations, each checked against the code it replaces.** Without
them init takes hours:

- **A1:** sinf computed as float32(math.sin).
- **A2:** the 12,819 additive-synthesis loops of the table builder
  `sw 0x1c463b` computed natively, in the firmware's float32 order. On each
  loop's first three entries, the native result equals the emulated one
  word for word.

Init (`sw 0x1c1445`) then returns after **5.0 M instructions [E]**.

**What the run shows [E]** (full list in `docs/sharc-voice-path.md`,
"Measured in the runner"):

| | |
|---|---|
| engine state | `0x241298`: R4 to init and to the dispatch. ~~[O] voice record array~~: it is per-machine voice state, one block per track |
| track records | 16 at `0x2554b8`, stride `0x234`; word `+0x1b4` is the machine type (0 FM Tone, 1 WaveTone, 2 FM Drum, 3 Swarmer, 4 MIDI) |
| arm / guard | no guard byte gates a render. Every track of a type is rendered on every block. A note is a change in a per-track counter (record word 113, compared at `0x1c90fb`, which then calls `sw 0xb82440`); poking it alone left the amp closed |
| block size | 32 (word 0 of `0x257e6c`) |
| per-voice output | a 32-float track buffer per track; pointers at `0x254a60`, buffers from `0x804acf90`, 0x80 apart |
| WaveTone | state at `0x241298 + 0x2408 + t * 0x30c`; two oscillators (`sw 0x1c44ae`, `sw 0x1c43ca`) read int16 tables (init builds 3 × 48 × 1024 points), a fixed-point mixer, a 2:1 decimator `sw 0xb8286b`, then fclip into the track buffer |
| stage 5 | `sw 0xb80f2e` is filter type 3; its table `0x26b3a8` is a tanh shaper |

The chain `0x1c9e76` → `0x1c2712` → `0x1c8ef1` → `0x1c9b73` holds, with one
correction: `0x1c9b73` is a set of jump-table arms (the filter renders), not
a stage orchestrator.

### Step 2: the stock voice

Track 0 is WaveTone and the other 15 are MIDI. One dispatch takes about
54 k instructions, about 3 s. With nothing triggered, both oscillators have
a phase increment of 0. Hand-arming oscillator 1 means giving it an
increment (`0x60000`, 562.5 Hz at its 96 kHz rate) and copying oscillator 2's
index scale and segment fields (words 14-17) into it at the render call.

- **The firmware's oscillator renders [E].** Its phase advances exactly
  2 × 32 × increment (`0x1800000`) on each of the 16 blocks. The 16 blocks
  hold 6 cycles, which is 12 zero crossings, and the buffer carries a
  waveform read from the init-built table (`m2_voice_stock_osc.wav`).
- **Control:** the same run unarmed leaves oscillator 1 silent
  (`m2_voice_disarmed_osc.wav`).
- **After WaveTone's own mixer and decimator, the track buffer is a ±1
  Nyquist buzz [E]** (`m2_voice_stock_machine.wav`). The mixer passes the
  oscillator through; that was checked. The decimator, run in the frame,
  rings at ±113, ±81, ... whatever its input. Run alone from the same state
  and input, it is linear and silent. The cause is **[O]**.
- **At the end of the chain the block is silent [E]**
  (`m2_voice_stock_chain.wav`). A constant 0.5 probe written in place of the
  render changes as it goes through the per-track stages: 0.5 → 0.499
  (written at `0xb8261c`) → 0.98 (`0x1c9492`) → 0.79 (`0x1cdbe4`) → 0.059
  (`0xb80c60`). Then the amp stage (`sw 0xb80345`, its write at `0xb80515`)
  makes it -0.0. That is what an untriggered voice should do.

### Step 3: our reader at the WaveTone call site

The hook steps over the `CALL sw 0x1c6d4a` at `0x1c9611` and runs
`wr_render` in its place, on the block's own memory, with the track buffer as
the output and 32 samples. The Milestone 1 table sweeps frame 0 → 15 → 0
across the blocks at 375 Hz.

- **The track buffer after the call equals `dnfw.waverider.render` (float32)
  bit for bit [E]:** 0 mismatches in 512 samples.
- **The stages before the amp keep our wavetable [E]:** a least-squares fit
  to the ideal reference gives gain 0.098, correlation 0.984 and SNR 14.8 dB. These stages are filters and a level, not a pure gain,
  so the fit is a measure, not an identity.
- **At the end of the chain it is silent**, peak 3.4e-5, for the same
  reason as the stock voice: the amp.

**Not an exact match, and why:** the reader's output is exact where it is
written. Beyond that, the per-track stages filter it, and nothing opens the
amp. An exact end-to-end comparison needs a note trigger with known envelope
parameters, and the ColdFire frame is what carries those.

### Step 4: the hooks, ranked

1. **Dispatch: the machine render call** (`0x1c9611` for WaveTone, one per
   machine type in `sw 0x1c8ef1`). **Measured**: the block is exact and the
   chain runs on it. It is also where a sixth machine's render would be
   called, next to the other four.
2. **The selector clamp `min(R2, 4)` at `0x1c294c`.** Needed for a sixth
   machine, since type 5 would otherwise be clamped onto MIDI's record, but
   it hosts no DSP code. It only chooses which render loop a track joins.
3. **Output: the final scatter to the 16 lanes (`0x1c9ae7`).** Reachable,
   but after the per-track filter, amp and pan; a machine written there
   bypasses them.
4. **Stage 5 (`sw 0xb80f2e`, `0x26b3a8`).** ~~the stage-5 call is the hook~~.
   It is a filter's saturator, so the wrong place.

### The measured gap, revised after Milestone 2

> **Superseded 2026-09-26** by "The measured gap, revised after Milestone 3"
> below. Three open rows ("a sixth render loop", "note trigger and amp
> envelope", part of "table delivery") are now measured. Kept as it stood.

| part | state | cost |
|---|---|---|
| wavetable import, baked table | **done**; **[V]** Milestone 0 | — |
| control surface, parameters, pages | **proven** by LFO4 | days |
| machine list ceiling | **read**: ColdFire `moveq #4`, DSP `min(R2, 4)` | done |
| SHARC executor on the DN2 voice path | **[E]** with 7 workarounds (G1-G7), each a digikit fix | — for us; PRs for digikit |
| DN2 engine layout: records, machine type, block, track buffers | **[E]** Milestone 2 | done |
| voice-path hook | **located and measured [E]**: the per-type render call in `sw 0x1c8ef1`; our block exact in the track buffer | done offline |
| a sixth render loop in `sw 0x1c8ef1` (type 5 → our reader) | not started; the four existing loops are the template | days-weeks |
| note trigger and amp envelope for a new machine | **open**: record word 113 is the note counter; envelope fields not mapped | weeks |
| table delivery to the DSP | **open**: nothing moves ColdFire data into DSP memory yet | weeks |
| WaveTone's decimator in the runner | **[O]** rings in-frame (only matters for the stock control) | — |
| the 12-shape ANIM modulator, the blend, two oscillators | not started; testable offline | weeks |
| persistence, p-locks | same shape as LFO4 | weeks |

## Milestone 3, offline (2026-09-26): an audible Waverider voice, as a sixth machine type

**The question.** With the voice-path map from Milestone 2, can the note
trigger and the amp be driven, and can Waverider be added as **machine type 5** —
its own render loop in `sw 0x1c8ef1`, calling our reader — without disturbing
types 0–4? **Yes, offline.** All three steps pass in the runner.

```
python scripts/sharc_waverider_m3.py \
    --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \
    --digikit ../digikit-wt-sharcemu [--assemble] [--blocks 6]
```

It reuses the Milestone 2 post-init snapshot (`out/waverider/m2_init_*.snap`):
engine init never touches our spliced spans or the clamp parcel, so the snapshot
is loaded against an M2-equivalent image (which its sha256 matches) and the
runner's memory is then re-pointed at the full M3 image — no 18-minute rebuild.
The run of 2026-09-26 reported **PASS on all 14 checks**, blocks = 6, digikit
`6f812e9`, CPython 3.13 on a shared machine.

### Step 1: the note trigger and the amp

Mapped by running, and each recorded in `src/dnfw/waverider/voice.py`:

| field | what it is |
|---|---|
| note counter | record word 113, compared at `0x1c90fb`; a change calls `sw 0xb82440` |
| trigger flag | engine `+0x138fc` (byte), raised by the frame unpack `sw 0x1c2712`; the frame carries the trigger bit at image offset 34 |
| amp stage | `sw 0xb80345` (its write at `0xb80515`) |
| amp setup | `sw 0xb8028c`, called at `0x1c92b0`; reads the envelope from record words `+0x20c..+0x228` (an ADSR) |
| what `sw 0x1c2712` unpacks | the 2,688-byte frame image copied to `0x25c48c`; a single-field sweep mapped its per-track offsets to the record (docs, "Measured in the runner") |

**PASS.** With a hand-built ADSR (sustain 1.0) and a note trigger fired once as
an edge, a constant 0.5 probe written where the amp reads it comes out at **0.5**
(the amp is open). **Control:** the same probe with no trigger comes out at
**0.0156** (closed). Files: `m3_amp_triggered.wav`, `m3_amp_control.wav`.

> The stock **WaveTone** voice at the end of the chain is *not* a clean control:
> its own 2:1 decimator rings in the runner (Milestone 2, `[O]`), and its
> oscillator output is ~1.2e-4 of full scale. So the amp gate is proven with a
> known probe rather than with WaveTone's own signal.

### Step 2: our reader substituted, through the per-track chain

Our reader (Milestone 1) replaces the WaveTone render at `0x1c9611`. **PASS.**

- the track buffer after the call equals `dnfw.waverider.render` (float32) **bit
  for bit**: 0 mismatches in 192 samples;
- the reader survives the per-track stages to the amp input: a least-squares fit
  to the ideal reference gives **gain 0.098, correlation 0.987, SNR 15.8 dB** —
  the same measure Milestone 2 reported, now with the trigger and amp mapped.
  Files: `m3_reader_machine.wav` (bit-exact buffer), `m3_reader_pre_amp.wav`.

**Not end-to-end loud, and why:** the per-track *filter* stages between the
buffer and the amp attenuate a raw wavetable by ~10× (peak 0.81 → 0.083),
because a zeroed frame leaves their cutoff/resonance at defaults. An audible
end-to-end voice additionally needs those filter parameters from a real frame,
which are not mapped. The amp itself opens (step 1); the filters are the
remaining gap, not the amp or the reader.

> **Superseded 2026-09-26 (Milestone 4).** ~~the per-track filter stages attenuate
> a raw wavetable by ~10× because a zeroed frame leaves their cutoff/resonance
> at defaults~~. With a zeroed frame the DSP's filter type is 0, which is **no
> filter at all** (its render arm calls nothing). The ~10× is the firmware's own
> track headroom: a fixed x1.585 (+4 dB) and then a 10 Hz DC blocker whose
> feed-forward pair the engine init scales by 0.0625 (-24 dB), both on every
> track whatever the sound. Measured in Milestone 4, "Step 1".

### Step 3: a sixth machine type (type 5 → our reader)

`csrc/waverider/sharc/machine5.asm` (`wr_render`'s sibling, `wr_type5`), 88
instructions, assembled with selas and spliced at PM `sw 0x180100`. It is a
fifth per-type render loop in the shape of the four stock ones (`0x1c93e5`,
`0x1c9401`, `0x1c941c`, `0x1c943b` in `sw 0x1c8ef1`): it scans the 16 track
records (`0x25566c`, stride `0x234`), and for every track whose machine type is
5 it calls our reader (`reader.asm` at `sw 0x180000`) on that track's voice
block, writing the track buffer. It is entered by a JUMP over `0x1c9448` — two
instructions after the Swarmer loop, before the per-track chain — modelled in
the runner by a pc redirect, and it rejoins at `0x1c944c`. **PASS.**

- a **type-5 track renders our reader into its buffer, bit for bit**: 0
  mismatches in 192 samples (`m3_type5_reader.wav`);
- **types 0–4 are bit-identical to stock** — a stock run with the entry hook
  installed (but no type-5 track) is byte-for-byte equal to one without it,
  across all 16 track buffers; and in the type-5 run, tracks 1–15 are
  byte-for-byte equal to the stock run. The sixth loop is purely additive;
- the DSP type clamp `min(R2, 4)` at `0x1c294c` is raised to `min(R2, 5)` by a
  one-parcel selas patch (`R0 = 0x4` → `R0 = 0x5` at `0x1c294a`, `800f0400` →
  `800f0500`) placed in the loaded image; **verified by running**: fed a type-5
  selector, the stock clamp leaves R2 = 4, the raised clamp leaves R2 = 5.

Both objects reassemble byte-for-byte from source with `--assemble` (selas
`2b26d3b`); their branch targets and boundaries are checked against digikit's
decoder (no unknown or uncertain form).

### Step 3 (research only): where the ColdFire would set type 5, and table delivery

**Where the ColdFire sets type 5.** Two DSP-side gates squash a type-5 frame in
stock, and both were found by running:

1. the machine-type **lookup** at `0x25d748` (a loaded data block): the frame's
   type nibble indexes it; entries `[0..4]` are `0..4`, `[5..]` are `0`, so a
   nibble of 5 becomes FM Tone. Entry `[5]` must be set to `5`. **[E]**
2. the per-track selector **clamp** `min(R2, 4)` at `0x1c294c`, raised above.
   **[E]**

The ColdFire builds the frame nibble from its own machine list (`docs/machine-list.md`:
`moveq #4`). Raising *that* is ColdFire work and is **not touched** here, per the
task. What the DSP needs is the two patches above.

**Table delivery to DSP memory.** Cited from digikit's findings 04/06 in our own
words, graded:

- The ColdFire→DSP link is a **periodic full-duplex DSPI2 SPI frame** driven by
  eDMA channels 28/29 (`FUN_400cf9c4`): on DN2, **TX 2,688 bytes, RX 2,748
  bytes**, one fixed frame per audio tick (SSI0-paced, ~87 ms). **[V]** (digikit
  finding 04; the frame's DN2 hash matches our image, Milestone 2).
- That frame is **structured parameters, not a bulk pipe**: 16 per-track slots
  of `0x92` bytes plus a header. A 16 KB table does **not** fit in one frame,
  and no existing per-frame block is a free 16 KB carrier. **[D]**
- DN2's own WaveTone tables are **built on the DSP at init** (`sw 0x1c463b`
  additive synthesis; 3 × 48 × 1024 int16), not transferred — Milestone 2 `[E]`.
  So one credible delivery path for Waverider is the same: **bake the table into
  the DSP image or build/copy it at init into DSP SDRAM**, addressed by a sample
  pointer, rather than stream it per frame. A voice's sample pointer into DSP
  SDRAM is real (`0x8045a6c8`, the ROM default digikit's Lane J1 reads). **[D]**
- A **bulk** transfer of sample bytes into DSP SDRAM is **not located**: digikit
  mark the runtime SPORT4/DMA10-11 producer and the RX payload producer both
  **[O]**. The SD-card path (eSDHC, eDMA 59) is ColdFire-side `+Drive` I/O, not a
  DSP feed. **[O]**

So table delivery is still open, but narrowed: the per-frame parameter frame is
the wrong vehicle (too small, wrong shape); the right shape is DSP-resident data
(baked or init-built), which is how the firmware already feeds its own
oscillators. **[D]**

### The measured gap, revised after Milestone 3

> **Superseded 2026-09-26** by "The measured gap, revised after Milestone 4"
> below. Kept as it stood.

| part | state | cost |
|---|---|---|
| wavetable import, baked table | **done**; **[V]** Milestone 0 | — |
| control surface, parameters, pages | **proven** by LFO4 | days |
| machine list ceiling | **read**: ColdFire `moveq #4`; DSP `min(R2,4)` **raised to 5 [E]** | done (DSP) |
| SHARC executor on the DN2 voice path | **[E]** with 9 workarounds (G1–G10) | — for us; PRs for digikit |
| DN2 engine layout: records, machine type, block, track buffers | **[E]** M2 | done |
| the note trigger and the amp gate | **[E]** M3: trigger flag, note-on fn, amp stage + ADSR mapped; amp opens on trigger, closed without | done offline |
| a sixth render loop (type 5 → our reader) | **[E]** M3: `machine5.asm`, bit-exact; types 0–4 bit-identical | done offline |
| where the ColdFire sets type 5 | **[E]** M3 research: lookup `0x25d748[5]` + clamp `0x1c294c`; ColdFire nibble builder not touched | ColdFire work |
| the per-track **filter** parameters (for an end-to-end loud voice) | **open**: zeroed-frame defaults attenuate ~10× *(superseded, Milestone 4: mapped and driven; the ~10× is the firmware's own -20 dB track headroom)* | weeks |
| table delivery to the DSP | **open, narrowed [D]**: per-frame frame is too small; DSP-resident (baked/init-built) is the shape *(superseded, Milestone 4: baked into section 7 and read through a directory [E])* | weeks |
| the 12-shape ANIM modulator, the blend, two oscillators | not started; testable offline | weeks |
| persistence, p-locks | same shape as LFO4 | weeks |

Two more runner workarounds turned up on this path and are added to
`scripts/sharc_dn2_fixups.py` and `docs/for-digikit-sharc-runner-dn2.md`:

- **G8** — a conditional Type 7a (`IF EQ MODIFY(I4, M4)`, in the amp stage once a
  note is on) halts; the runner runs only "always" and `0x17`. Evaluated here.
- **G10** — Type 8a ignores the `(LA)` loop-abort bit (`_type_25a_direct` calls
  the transfer without `loop_abort`, though `_transfer` supports it and Type 9a
  passes it). A `JUMP (LA)` out of a `DO` loop then leaves the loop's PC-stack
  entry behind and the next `RETURN` halts. Met in the amp at `0xb803ee`.

### What is unverified

- **Silicon**, as for Milestone 1. And three of the workarounds (G1, G2, G4)
  are models of SHARC+ behaviour inferred from the firmware, not cited from
  the PRM.
- **The ColdFire frame.** Every parameter here was either init's default or
  a hand poke; `sw 0x1c2712`'s unpack of a real frame was not run.
- **The note trigger and the amp envelope.** An audible voice at the end of
  the chain needs both.
- **WaveTone's decimator in the frame.** It rings, cause unknown.
- **The spliced spans.** The reader's table and code sat at spans the boot
  stream never loads (Milestone 1); the bit-exact output shows that nothing
  overwrote them during these runs.

## Milestone 4, offline (2026-09-26): the per-track filters, an audible voice end to end, and the table in the DSP image

**The question.** Part A: with the ColdFire frame's filter parameters from a
real (init) sound, is our type-5 reader audible at the end of the per-track
chain? Part B: how does a table reach DSP memory, and can the type-5 machine
read it from where the image put it? **Yes to both, offline.** The gate
reported **PASS on all 17 checks** (12 blocks, digikit `6f812e9`, CPython
3.13 on a shared machine; step 3 is report-only).

```
python scripts/sharc_waverider_m4.py \
    --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \
    --digikit ../digikit-wt-sharcemu [--assemble] [--blocks 12]
```

It reuses the Milestone 2 init snapshot (`out/waverider/m2_init_*.snap`) the
way Milestone 3 does. What is new is the driver: **every block runs the
firmware's own per-block routine `sw 0x1c2712`** -- frame unpack, slot
dispatch, per-track chain -- called as `sw 0x1c9e76` calls it at `0x1c9fbc`,
with a 2,688-byte frame image in the buffer it copies from. No track record
is poked; the note trigger, machine type and every filter and amp parameter
arrive through the frame. About 154 k instructions a block, ~10 s.

### Step 1: the frame, and the per-track stages, mapped by running

**The frame** (`src/dnfw/waverider/frame.py`, `dnfw waverider frame IMAGE
OUT`). A single-field sweep -- one 16-bit field set, the unpack run to just
before it calls the dispatch (`0x1c3044`, 10 k instructions), every DM word it
wrote diffed against a zero frame -- over every field of track 0's slot, the
header and the tail. Measured **[E]**:

| image offset | field | lands in |
|---|---|---|
| `2 + 2t` | trig note (param 19) | engine `+0x1387c + 4t`, as note + fine/256 |
| `34` | note-trigger mask, bit t = track t | byte cell engine `+0x138fc + t` (Milestone 3's hand-poked cell) |
| `36`, `38`, `40` | three more trigger masks | byte cells `+0x1391c`, `+0x1393c`, `+0x1394c` |
| `116 + 2t` | track level | record `+0x22c`, /32512 |
| `148 + 2t` | **machine type** | record `+0x1b4` |
| `180 + 2t` | **filter type** (ColdFire 0..5) | record `+0x1dc`, through a map: 0→1, 1→3, 2→2, 3→4, 4→5, 5→6, else 0 |
| `218 + 146t + ...` | parameter indices 25..99, as the ColdFire frame builder's four block copies lay them out (`docs/engine-state.md`) | record `+0x0..+0x98` (machine), `+0x1b8..+0x230` (FX, filter, amp) |

The slot offsets agree with the ColdFire side exactly: KEY.T (index 79) is
the one field scaled by /25600, its own range `0x6400`; VOL (90) is squared;
amp MODE (91) becomes a pointer. `frame.RECORD_FIELDS` lists the 26 filter,
amp and FX destinations; step 1 re-measures them every run. Values are the
ColdFire's `coarse << 8 | fine` words (FREQ's default is `0x7f00`).

**A runner gap on the way (G11).** The unpack splits every 32-bit frame word
into two parameters with `fext ... by 0:16 (se)` and `lshift ... by -16`.
digikit's FEXT (SE) does not mask its field, so each low-half parameter
carried its neighbour in bits 16-31. Found because two fields set together
disagreed with the same two set apart; checked in isolation beside plain
FEXT as a control. Workaround in `scripts/sharc_dn2_fixups.py`; a one-line
digikit fix, `docs/for-digikit-sharc-runner-dn2.md` section 17.

**The DSP filter number, and the render arms.** The dispatch copies record
`+0x1dc` into engine `+0x13840 + 4t` (when it changes) and jumps through
`0x8052dbc0[n]`, set up through `0x8052dba4[n]`. Read out of the snapshot:

| DSP n | ColdFire type | render | setup |
|---|---|---|---|
| 0 | none (type >= 6; also a zeroed frame's cached value) | **nothing** | common only |
| 1 | Multimode | `sw 0xb82342` | `sw 0xb82096` |
| 2 | Equalizer | `sw 0xb81a16` | `0x1c9722` |
| 3 | Lowpass 4 | `sw 0xb80f2e` (Milestone 2's tanh "stage 5") | `0x1c9753` |
| 4 | Comb- | `sw 0xb806f5` | `0x1c977b` |
| 5 | Legacy LP/HP | `sw 0xb81526` + inline | `0x1c97d9` |
| 6 | Comb+ | `sw 0xb806f5` | `0x1c984e` |

The ColdFire names are the filter pages 5..10 in order (`dnfw params`) and
the name rows before the machine table (`docs/machine-list.md`) **[D]**: the
name-to-number match is by order, not by audio.

**The per-track chain for track 0, in order**, from a traced block (init
sound, type 5, filter Multimode), peak of track 0's buffer in and out:

| call from | stage | state (engine +) | peak in → out | what it is |
|---|---|---|---|---|
| `0x1c9447` | our `wr_type5` → `wr_render` | voice block | → 0.555 | the machine render (bit-exact) |
| `0x1c945d` | `sw 0xb8251b` | `0xed88 + 0x14t` | 0.555 → 0.556 | a small per-track stage (not identified) |
| inline `0x1c946a` | x `0x3fcade01` = 1.585 | -- | 0.556 → 0.880 | a fixed +4 dB |
| `0x1c95cd` | `sw 0x1cdb56` | `0xe788 + 0x60t` | unchanged | flagged per track (engine `+0x1381c`); no effect here |
| `0x1c9501` | `sw 0xb80c39` → kernel `sw 0xb809f2` | `0xe088 + 0x70t` | 0.880 → 0.054 | **a 10 Hz DC blocker at -24 dB** (below) |
| `0x1c95b8` | `sw 0xb8265b` | `0xeec8 + 0x14t` | unchanged | early-out (79 instructions) |
| `0x1c95a3` | `sw 0xb81368` | `0x12148 + 0x20t` | 0.054 → 0.054 | the base-width filter [D]: BASE/WIDTH are its setup's arguments at `0x1c9281` |
| `0x1c98b3` | `sw 0xb82342` | `0xf308` | 0.054 → 0.070 | **the Multimode filter** (DSP 1) |
| `0x1c99d0` | `sw 0xb80345` | `0x13508 + 0x2ct` | 0.070 → 0.070 | the amp (open, sustain) |

**The -24 dB is the firmware's own [E].** The DC blocker's setup
`sw 0xb80b4b(block, 48000.0)`, run in isolation, computes `a0 = -a1 =
0.999346`, `b1 = -0.998692`. The engine init then multiplies a0 and a1 by
0.0625 at `0x1c8cf6` -- one SIMD multiply, PEx on a0 and PEy on a1 -- as a
re-run of the engine init under a write watch shows, write by write. With
the +4 dB before it, **a track's chain gain is about -20 dB, whatever the
sound**: headroom for sixteen tracks. So the end-of-chain level below is
expected, and nothing was "corrected" to reach it.

### Step 2: an audible Waverider voice end to end

Track 0 is machine type 5 **in the frame** (`148` = 5; the M3 clamp raise
and, new here, machine lookup `0x25d748[5] = 5`), filter type 0 (Multimode),
every parameter the init sound's default from the firmware's own table:
FREQ `0x7f00`, RESO 0, ENV depth `0x4000` (centre), BASE 0, WIDTH `0x7f00`,
amp ATK `0x0800` HOLD `0x7f00` DEC `0x2000` SUS `0x6000` REL `0x1800`, VOL
`0x6e00`. The note-trigger bit is set on block 1 only. 12 blocks, 375 Hz,
the Milestone 1 table sweeping frame 0→15→0.

| | measured |
|---|---|
| type 5 via the frame, track buffer vs `dnfw.waverider.render` float32 | **0 mismatches** in 384 samples |
| end of the per-track chain (amp output), blocks 4-11 | peak **0.090**, rms **0.044** (-21 dBFS peak) |
| fit to the ideal reference through the chain | gain 0.098, **correlation 0.987**, SNR 15.6 dB |
| control: FREQ 0 | rms **7.0e-5** (-56 dB vs open); spectral centroid **251 Hz** vs **4,651 Hz** open |
| control: no trigger | peak **0.0028** (the amp's closed floor) |

### Step 3: the stock WaveTone voice through the same path (report only)

WaveTone (type 1) with its own init machine page, same frame and trigger:
the track buffer after its render peaks at 1.0 with 345 zero crossings in
384 samples -- Milestone 2's decimator ringing, still **[O]** -- and the end
of the chain peaks at 0.160 (control, no trigger: 0.005). So the stock
voice passes the chain and the amp end to end, but what it passes is the
ringing, not a verified WaveTone waveform. The WAVs are kept for the record.

### Part B: getting a table into DSP memory

| delivery | mechanism | capacity | cost | evidence |
|---|---|---|---|---|
| **bake into section 7** | boot-stream blocks the loader writes before the entry point (`bootstream.block`, `insert_before_final`) | the L1 span `0x280000..0x2a0000` is unloaded by the stream (128 KB: 8 tables of 16 KB); free DDR beyond the 5.4 MB image not read | +16 KB per table; section 7 is stored aPLib-compressed and int16 tables barely compress (M0: ~1.1x raw) | **[V]** that a section-7 data change reaches the DSP and plays: the `transients` mod, flashed and heard 2026-09-14 (`docs/mods.md`). **[E]** that an appended block loads and our code reads it: this step |
| build at init from a compact description | DSP code at init, as WaveTone's tables are built (`sw 0x1c463b`, additive synthesis) | unlimited for tables with a short description (a harmonic series); none for arbitrary user WAVs, whose description is the table | init time: WaveTone's 3 x 48 x 1024 points are ~90 M instructions, ~0.1 s at 1 GHz **[D]** | **[E]** mechanism (Milestone 2 ran it); **[D]** for ours |
| bulk transfer from the ColdFire | an upload spread over frames, or a DMA/SPORT/boot block | the frame is parameters: step 1 found a destination for every slot field, and at one frame per ~87 ms a few spare bytes would take tens of seconds a table | new code on both processors | **[D]** frame; **[O]** DMA/SPORT (digikit's findings 04/06 leave the producers open) |

**Most feasible: bake into section 7**, and it is prototyped.

- `csrc/waverider/sharc/machine5_dir.asm` (`wr_type5d`, sw `0x180200`, 542
  bytes): Milestone 3's loop, but each voice block carries a **SLOT**, and
  the loop resolves it through a **wavetable directory** the boot stream
  loads at DM `0x28c000`: magic `WRT1`, count, table pointers. The harness
  writes phase, increment, position and slot -- **not** the table pointer.
- The image gains three boot blocks: the directory (16 bytes), table 0 at
  `0x280000` (Milestone 1's) and a second original table at `0x290000` (the
  first's frames reversed and negated), all at spans the stream never loads.

| run (same frame, same voice) | measured |
|---|---|
| slot 0 | **0 mismatches** vs table 0's float32 reference |
| slot 1 | **0 mismatches** vs table 1's; the voice block's table pointer after the run is `0x290000`, written by the DSP code from the directory |
| control: the same image without the directory block | the loop renders nothing; track 0's buffer is left exactly as it was |

**What a real build needs**, done in memory by the gate, no .syx written:
section 7 with the blocks (`out/waverider/m4_section7_waverider.bin`, 871,242
bytes, sha256 `8fab8c65...ed4cac`) goes through `dnfw`'s own
`replacement(fw, 7, ...)`, which recompresses it as the original is stored,
and `build`; the result re-loads and passes **21 of 21** `dnfw` verify
checks, HMAC-signed, 2,430,240 bytes. That section 7 also carries the M3
clamp raise and the lookup `[5] = 5`. A flashable build also needs the
ColdFire side: the machine list ceiling (`docs/machine-list.md`) and a frame
machine type of 5.

A selas/digikit disagreement turned up on a 16-bit Type 3c pre-modify read;
it is recorded as open in `docs/for-digikit-sharc-runner-dn2.md` section 19.

### What is unverified

- **Silicon**, as for every milestone; G1, G2, G4 and now G11 are models.
- **The ColdFire's frame.** The frame here is built from the parameter
  table's defaults as `coarse << 8 | fine`; a frame from the firmware's own
  builder (`0x400274ba` in the ColdFire emulator, or DNX) has not been
  compared with it. The header arrays at `44..50`, `52 + 2t`, `84 + 2t`,
  `212..216` and the tail `2554..2687` are left zero.
- **Byte order on the wire**: the image is in DSP memory order; how the
  ColdFire's big-endian SPI words land is not measured.
- **What the unnamed stages do** (`sw 0xb8251b`, `sw 0x1cdb56`,
  `sw 0xb8265b`), and whether the ColdFire filter names match the DSP numbers
  by anything but order.
- **The spliced spans at run time** (unloaded by the stream, not proven
  unused by a heap or stack), as before.
- **Type 5's per-type setup.** The dispatch's setup table `0x8052db90` has
  five entries; with type 5 it reads the next table's first word. It ran
  without fault here, but that is luck until a sixth entry exists.

### The WAVs

All 2.5 s, 48 kHz, 16-bit mono, in `out/waverider/`. Every file marked
(looped) is 384 rendered samples repeated, so it cannot show change over
time; the change is measured above. The two PREVIEWs are float32 references
with the sweep spread over the whole file, not the runner.

| file | what it is |
|---|---|
| `m4_waverider_voice_end_to_end.wav` | **the key deliverable**: the type-5 voice at the amp's output, init sound, trigger on block 1 (looped) |
| `m4_waverider_voice_end_to_end_normalised.wav` | the same x9.96, for listening (looped) |
| `m4_filter_open.wav` / `m4_filter_closed.wav` | FREQ 127 vs FREQ 0 at the end of the chain (looped) |
| `m4_no_trigger.wav` | no trigger: silent (looped) |
| `m4_type5_machine.wav` | the reader in track 0's buffer, bit-exact (looped) |
| `m4_preview_reference_sweep.wav` | PREVIEW: table 0's reference, sweep over 2.5 s |
| `m4_wavetone_end_to_end.wav`, `m4_wavetone_machine.wav` | stock WaveTone through the chain; its ringing buffer (looped) |
| `m4_baked_slot0.wav`, `m4_baked_slot1.wav` | Part B, machine5_dir's output from each directory slot (looped) |
| `m4_baked_no_directory.wav` | control: the untouched buffer, the previous block's chain output (looped) |
| `m4_preview_table1_sweep.wav` | PREVIEW: table 1's reference, sweep over 2.5 s |

### The measured gap, revised after Milestone 4

| part | state | cost |
|---|---|---|
| wavetable import, baked table | **done**; **[V]** Milestone 0 | — |
| control surface, parameters, pages | **proven** by LFO4 | days |
| machine list ceiling | ColdFire `moveq #4` not touched; DSP clamp and lookup `[5]` **raised [E]** | days (ColdFire) |
| SHARC executor on the DN2 voice path | **[E]** with 11 workarounds (G1–G11) | PRs for digikit |
| the ColdFire→DSP parameter frame | **mapped [E]**: every filter/amp/FX field, machine type, filter type, trigger masks | done offline |
| the per-track chain and filters | **mapped and driven [E]**: stage order, filter-type arms, the -20 dB track headroom | done offline |
| an audible type-5 voice end to end | **[E]** M4: r = 0.987 through the chain; FREQ-0 and no-trigger controls hold | done offline |
| table delivery to the DSP | **[E] baked into section 7 through a directory**, rebuilt and verified in memory; the section-7 route itself **[V]** by the transients mod | a flash |
| type 5's per-type setup entry | **open**: `0x8052db90` has 5 entries | days |
| the ColdFire frame for type 5 (machine type, a SLOT parameter) | not started | days-weeks |
| the 12-shape ANIM modulator, the blend, two oscillators | not started; testable offline | weeks |
| persistence, p-locks | same shape as LFO4 | weeks |

## Status

**Milestone 0: [V]** -- passed on the instrument 2026-09-26 (test 12,
`wavefinder-m0_DN2_1.11.syx`): a 10 s capture while a synth pattern played held
118 complete bursts, all 8 probe points matched, the checksum read `0x33e5` in
every burst, `probe_a` read 99 in all 118, and `wr_passes` climbed 65 to 79.
Checked with `dnfw waverider verify`. The superseded status, for the record:
[E], verified under the emulator from reset, awaiting hardware.

**Milestone 1: [E]** -- 2026-09-26, offline only: our own SHARC reader,
assembled with selas, runs in digikit's SHARC executor inside the DN2 1.11
image and matches `dnfw.waverider.render` bit for bit (float32) over 7 cases
and a 48,000-sample sweep; max error against the ideal 5.8e-8. Nothing has run
on a DSP, and nothing is flashed.

**Milestone 2: [E]**, 2026-09-26, offline only. The DN2 1.11 engine init and
slot dispatch run in digikit's runner with seven documented workarounds. The
firmware's WaveTone oscillator renders from its own tables once hand-armed.
Our reader, substituted at the WaveTone render call, is bit-exact in the
track buffer and survives the per-track stages before the amp. The end of the
chain is silent because no note is triggered, and WaveTone's decimator rings
in the runner. Nothing is flashed.

**Milestone 3: [E]**, 2026-09-26, offline only. The note trigger and the amp
are mapped and driven: the amp opens on a hand-built trigger + ADSR and is
closed without it. Our reader is added as **machine type 5** — a fifth
per-type render loop (`csrc/waverider/sharc/machine5.asm`, selas-assembled,
spliced) in `sw 0x1c8ef1`, with the DSP type clamp raised to `min(R2,5)`. A
type-5 track renders our reader into its buffer bit for bit; types 0–4 stay
bit-identical to stock. Table delivery is researched and narrowed (the
per-frame DSPI2 frame is too small; DSP-resident data is the right shape),
still `[O]` for a bulk transfer. An end-to-end *loud* voice additionally needs
the per-track filter parameters from a real frame, unmapped. Nothing is
flashed. Gate: `scripts/sharc_waverider_m3.py`, 14/14 PASS.

**Milestone 4: [E]**, 2026-09-26, offline only. Every block runs the firmware's
own `sw 0x1c2712` on a frame built from the init sound: the frame is mapped
field by field, the per-track chain and filter arms are mapped, and the type-5
reader is audible at the amp's output (correlation 0.987), quieter and darker
with FREQ 0, silent with no trigger. The table is baked into section 7 with a
directory; both slots render bit for bit, and the rebuilt image passes all 21
`dnfw` checks in memory. One more runner gap (G11). Nothing is flashed. Gate:
`scripts/sharc_waverider_m4.py`, 17/17 PASS.

**[D]** for the gap estimates — they are reasoned from measured facts (the file
format, the firmware's free space, the machine table bound) but no part of the
feature *as a machine* has been attempted; Milestones 0 and 1 are its delivery
and render gates. The manual citation and the wavetable measurements
are **[V]**: read directly from Elektron's own document and files.

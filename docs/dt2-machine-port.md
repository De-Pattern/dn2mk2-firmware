# Porting a DT2 machine to the DN2: measured, not estimated

**2026-09-25.** The question: ONESHOT is the simplest DT2 SRC machine and its
code is already in a firmware we hold, so what would porting it cost?

**Short answer: more than Waverider, not less.** The premise is true for 85% of
the image and false for exactly the part that is the machine.

## The two images are verified against digikit's own hashes

| image | section 7 blob SHA-256 | matches digikit |
|---|---|---|
| DN2 1.11 | `336e340a…3115e2` | yes |
| DT2 1.16 | `0f514a12…7fffa2` | yes |

So both databases below are built from bytes digikit have already indexed, and
their addresses can be cited directly.

## What ONESHOT is

Digitakt II manual OS 1.16, **A.2.1**, in our words: the default machine, playing
a sample linearly — forward, reversed or looped. Seven parameters on one page:

| | |
|---|---|
| `TUNE` | pitch, bipolar, ±5 octaves |
| `PLAY` | REVERSE, REVERSE LOOP, FORWARD LOOP, FORWARD |
| `SAMP` | sample select — **up to 1016 samples per project**, p-lockable (sample locks) |
| `STRT` | start position |
| `LEN` | length; start + length is the end point |
| `LOOP` | loop return point |
| `LEV` | level |

**It is a sample player.** That matters more than the parameter count.

## How much DT2 SHARC code already exists in the DN2 image

Both databases built with digikit's `sharcdb`, compared on `func_hash`
(`reloc_hash` is relocation-tolerant; `exact_hash` is byte-for-byte):

| | count |
|---|---|
| DT2 functions | 1,228 |
| DN2 functions | 1,157 |
| **DT2 functions with a relocation-tolerant twin in DN2** | **1,038 (85%)** |
| DT2 functions **byte-identical** in DN2 | 409 (33%) |
| DT2 instructions covered by a twin | 37,840 / 50,752 (75%) |

**85% shared looks like the port is nearly free. It is not**, because of *which*
15% is missing.

## The missing part is precisely the audio engine

The largest DT2 functions with **no** DN2 twin:

| DT2 `sw` | instrs | what digikit identify it as |
|---|---|---|
| `0x1c642a` | **1,464** | the per-slot dispatch — voices and effect stages |
| `0x1c2b24` | 766 | the per-track loop |
| `0x1c18a6` | 654 | — |
| `0x1c24e9` | 396 | the per-track unpack |
| `0x1c4f81` | 381 | inside the voice render |
| `0x1c207b` | 303 | the master |

And narrowing to what a machine actually needs:

- **the per-slot dispatch's reach set**: 40 functions, 28 with twins, but only
  **1,655 of 3,903 instructions (42%)** — and the missing 58% is dominated by
  the 1,464-instruction dispatch itself;
- **the voice render `0x1c4ecf`**: 84 instructions, **no DN2 twin**, and a leaf
  in the call graph.

So the 85% that transfers is the **infrastructure** — maths helpers, the
reciprocal/divide routine, the effect stages digikit already found byte-identical
across the two products. The **product-specific sample engine does not transfer
at all**, which is exactly what one would expect of a sampler and an FM synth.

**This is not a surprise so much as a correction**: "we already have the code"
is true of the platform and false of the machine.

## And the subsystem underneath it does not exist on the DN2

ONESHOT needs sample storage (1016 per project), a sample browser, sample locks
per step, and streaming from the `+Drive` into the voice at trigger time. The
DN2 has none of it as a user-facing sample path.

> **Superseded in part, 2026-09-26 (`docs/drive-storage-research.md` §4).**
> "Streaming from the `+Drive` into the voice at trigger time" is not how the
> DT2 works. It **preloads** a project's samples into a 400 MiB RAM pool
> (`0x19000000` at DT2 `0x40153814`) that sits on the SHARC side, and the voice
> reads RAM. The DN2 also has more than "none of it". The ColdFire end of the
> DT2's sample-page link (the `0x8c000000` port) is present and identical, and
> the +Drive has about 20.9 GiB the stock firmware never touches. The
> conclusion below is unchanged, because the SHARC engine is still the cost.

The owner's storage decision — **wavetables and samples both become `+Drive`
project data** — settles *where* this would live, and DNX is the format
authority for it. It does not reduce the amount of subsystem to build.

**And the owner's point, which this study under-weighted**: any DT2 machine
needs *extensive sample management tooling*, and **rerouting the whole UI to
handle it**. That is the part this page nearly costed at zero. The DN2's
interface has no sample browser, no `+Drive` file navigation, no sample
assignment screen and no sample-lock display — those are whole screens and
whole navigation paths, not a parameter page. Adding a parameter page is what
LFO4 proved we can do; adding a file browser to someone else's UI framework is a
different order of work, and it is on the critical path for **every** DT2
machine, not just ONESHOT.

Storage size is the lesser half of it. The greater half is that a sample bank is
**unbounded and user-managed** — 1016 arbitrary-length files that must be
listed, previewed, assigned, locked per step and persisted — where a wavetable
is **fixed geometry**, and a useful Waverider can ship with a handful of tables
at 8 KB each and grow later.

## Against Waverider, which is the comparison that was asked for

| | ONESHOT port | Waverider |
|---|---|---|
| DSP render code exists in a firmware we hold | **no twin in DN2** | no |
| the render itself | variable-length sample reader: start/length/loop, four play modes, per-voice streaming | fixed **2048-sample frames**, two readers, linear interpolation |
| storage | 1016 arbitrary-length samples | wavetables, fixed geometry |
| browser and locks | full sample browser, sample locks | slot list, slot locks |
| **runnable today** | no — needs a SHARC core | no — needs a SHARC core |

**A wavetable oscillator is strictly simpler than a sample player**: fixed frame
geometry, no variable length, no four play modes, no loop-point arithmetic. Both
are blocked on the same thing — nothing can execute SHARC code yet — but if that
blocker is cleared, Waverider is the smaller of the two engines *and* the one
whose data format we already parse.

## Conclusion

**Do Waverider first.** ONESHOT's apparent advantage — existing code — does not
survive measurement: the sample engine has no DN2 counterpart, and the sampler
subsystem beneath it would have to be built from nothing.

What this exercise did produce, and it is worth keeping:

- **85% of DT2's SHARC image has a twin in DN2, 33% byte-identical.** That is a
  large shared platform, and it means helper routines found in one image can be
  looked for in the other by hash rather than by reading.
- A working two-image comparison, reproducible in about 80 seconds.

## Status

**[D]** — static structural comparison only, single review. `func_hash` matching
is prioritisation evidence: collisions are possible, and two functions with the
same shape need not have the same semantics. No emulator run, no hardware.

## Revisited 2026-09-26: a ONESHOT-lite on Waverider's machinery

**Raised by the owner:** port ONESHOT as a way to test sample handling, apart
from Waverider.

**Corrected the same day, at the owner's challenge.** ~~The conclusion above
stands for a port: the DT2's sample engine has no DN2 twin, so this would be
our own player, not Elektron's moved across.~~ "No twin" means the DN2 does
not *already contain* the code, not that it cannot be moved. Both are SHARC+,
there is room, and the part a machine needs is small:
- the voice render `0x1c4ecf` is 84 instructions and a leaf;
- `0x1c4f81` beside it (381 instructions) already renders correctly in
  digikit's runner on DT2 1.16.

The large missing piece, the 1,464-instruction per-slot dispatch, is not needed:
Waverider's type-5 loop plays that role on the DN2. **So port first, and write
our own player only as the fallback.**

The conditions a port has to meet:
1. **No redistribution. Decided by the owner, 2026-09-26: the user supplies
   both firmwares.** The user uploads their DN2 1.11 OS and their DT2 OS, which
   Elektron publish for free. Our code extracts the routine from the DT2 file
   and transplants it into the DN2 image at apply time, in the CLI and in the
   browser, so no Elektron code is redistributed. This is the same pattern as
   `lfo4` rebuilding the parameter table from the user's own DN2 image.
   - What the repository holds for a transplant: only our own work (offsets,
     the donor's version and hash guards, relocation tables, adapter code).
     **Never a DT2 byte**, in code, SPEC JSON, tests or fixtures; tests that
     need the donor skip without it.
   - A transplant mod takes a second input image and refuses a donor whose
     version or hash it was not measured against.
2. **An adapter.** The routine expects the DT2's voice record (32 × `0x1d8` at
   `0x2412cc`) and absolute addresses for its tables and sample pool. That
   means a DT2-shaped record per type-5 track, filled from the DN2 frame, and
   relocated addresses.
3. **Samples in DSP memory.** This is Waverider's table-delivery problem, which
   M4 solved: bake a small bank into section 7 behind a directory.

**The offline experiment that settles it:**
- lift `0x1c4ecf`'s reach set into the DN2 image in the runner;
- drive it from the type-5 loop with a DT2-shaped record and a baked sample;
- compare it with digikit's runner executing the same routine on the DT2
  image, which is the control.

**In progress, 2026-09-26:** the offline port experiment runs on
`feature/oneshot-port`, under the two-firmware rule above. Its results will be
added here when it reports. **[D]** until then.

**What has changed since** is that most of a player's infrastructure now exists
or is being built for Waverider (`docs/waverider-feasibility.md`):
- the SHARC runner gate, and a reader of our own bit-exact to a reference (M1);
- a sixth machine type and its render loop (M3);
- the frame parameters and the per-track chain (M4);
- tables baked into section 7 behind a directory (M4);
- the first flash of modified SHARC code (M5, in progress).

**If the port fails, the fallback is a ONESHOT-lite of our own:**
- a small **baked sample bank** in section 7, as Waverider bakes tables and
  `transients` replaces the drum bank, with no browser;
- `SAMP` as a slot index, like Waverider's SLOT;
- a one-shot reader with `STRT`, `LEN`, `LOOP` and the four `PLAY` modes.

It tests the sample path end to end, but not the library: the unbounded,
user-managed bank on the `+Drive` and the browser the DN2 UI lacks stay the
expensive half (`docs/drive-storage-research.md`).

**Order:** after Waverider M5 has run modified SHARC code on the instrument.
Until then both carry the same first-flash risk. **[D]**, not started.

## The experiment, run (2026-09-26): the port works, offline

**Done, offline.** The DT2 1.16 ONESHOT render was extracted from the user's own
DT2 file, relocated into the DN2 1.11 image, and run in digikit's SHARC runner.
It is **bit-identical to the DT2 control** for all four play modes, and an
adapter of our own drives it inside the DN2's own per-block routine, audible at
the amp. Gate: `scripts/sharc_oneshot_port.py` (`6f812e9`, CPython 3.13), every
check PASS. Nothing is flashed; no .syx and no DT2 byte is written to the repo.

### What the routine is [E]

`sw 0x1c4ecf` (84 instructions) is the entry: it saves registers, and when the
voice record's sample pointer (word 0) or ACTIVE byte (`+0x1b8`) is zero it
zero-fills the output and returns. Otherwise it falls into `sw 0x1c4f81` (381
instructions), **a variable-length sample player**: 64 points at 96 kHz, a
6-tap 256-phase polyphase interpolation of int16 PCM, forward or reverse, with a
loop and a one-shot end, and declick ramps; it then calls a 2:1 decimator to 32
outputs. Confirmed by running: with a start/length/loop/step record and a known
sample it reads PCM in order, wraps at the loop, plays backwards on a negative
step, and clears ACTIVE at the end of a one-shot. So it is exactly the machine
the manual (A.2.1) describes: TUNE, PLAY (the four modes), STRT, LEN, LOOP.

### The reach set, and its size [E]

Closed under calls (digikit's `sharcdb` edges), **4 functions, 611
instructions**, none with a DN2 twin (as the 2026-09-25 study found):

| donor `sw` | instrs | window | what |
|---|---|---|---|
| `0x1c4ecf`+`0x1c4f81` | 84 + 381 | L1 | entry + the reader (one routine, moved as one span) |
| `0x1c06ba` | 47 | L1 | a float reciprocal/divide helper (the declick ramps) |
| `0xb80000` | 99 | L2 | the 2:1 decimating filter |

Plus the two data tables it reads at absolute addresses: the polyphase
coefficients (`0x25d940`, 256×6 Q31 words, 6,144 bytes) and the decimator's four
coefficients (`0x26ef88`, 16 bytes). Everything else is relative to the record
pointer (R4), the output pointer (R8) or the stack. **Ten relocation sites** in
all: two `data32` loads of the coefficient base, two `rel24` calls to the
divide helper, one `addr24` call to the decimator, its pushed return address,
and four `addr32` loads of the decimator coefficients. `src/dnfw/transplant/`
holds these as addresses, sizes, SHA-256 digests and the relocations — never a
donor byte.

### The control and the transplant [E]

digikit's runner executes the routine on the DT2 image (from its own engine
init, a hand-armed voice, an original test sample in the pool) — the control —
and, relocated, inside the DN2 image, called the same way. Per mode, the DN2
transplant is **bit-identical** to the DT2 control over the rendered blocks:

| mode | bit-identical | peak | instr/block |
|---|---|---|---|
| FORWARD | **yes** (0 differing bytes) | 0.358 | 3,611 |
| REVERSE | **yes** | 0.039 | 3,805 |
| FORWARD LOOP | **yes** | 0.358 | 3,611 |
| REVERSE LOOP | **yes** | 0.039 | 3,805 |

Controls: reverse starts quiet where forward is loud (the chirp's decayed tail
played backwards), and a triggered all-zero sample renders **exact** zero. The
relocations are the only difference between the two, and the output is identical
to the last bit — which is the strongest evidence the transplant is faithful.

### The adapter, end to end [E]

`csrc/oneshot/sharc/oneshot5.asm` (our own, selas-assembled, loaded at `sw
0x181000`) is a sixth per-type render loop, machine type 5, in the shape of
Waverider's. On a note trigger it builds a **DT2-shaped voice record** for the
track from six frame parameters (TUNE, PLAY, SAMP, STRT, LEN, LOOP), resolves
SAMP through a sample bank baked into section 7 behind an `OSB1` directory
(M4's mechanism), and calls the transplanted render with R4/R8/R12 as the
donor's own dispatch does. Driving the DN2's own per-block routine `sw
0x1c2712` with a type-5 frame and a trigger:

- the record the adapter builds matches `dnfw.oneshot.params` word for word;
- the type-5 track renders **bit-identical to the DT2 control** into its buffer;
- it passes the per-track chain and is **audible at the amp output** (peak
  0.049, ~-26 dBFS, the chain's own ~-20 dB headroom);
- a triggered all-zero sample is exact silence at the render.

`src/dnfw/oneshot/build.py` splices the transplant, the adapter, the bank and
the step table into DN2 section 7 with the type-5 patches (the clamp
`min(R2,4)→5` and lookup `[5]=5`, as M3/M4), rebuilds through `dnfw`, and the
image passes **all 21 verify checks in memory**. No .syx is written.

### The WAVs

All 2.5 s, 48 kHz, 16-bit mono, in `out/oneshot/` (looped renders say so; the
runner renders a few blocks, so each looped file is those blocks repeated and
cannot show change over time — the numbers above measure that, and a PREVIEW
plays the sample itself over the whole file):

| file | what it is |
|---|---|
| `oneshot_{forward,reverse,forward_loop,reverse_loop}_transplant.wav` | **the key deliverable**: the transplanted render inside the DN2 image, per mode; bit-identical to the control (LOOPED) |
| `oneshot_{...}_control.wav` | the DT2 control: the same routine on the DT2 image (LOOPED) |
| `oneshot_{...}_preview.wav` | PREVIEW (not the runner): the test sample itself, forward/reversed, over the whole file |
| `oneshot_adapter_machine.wav` | a type-5 track's buffer after the adapter drove the render; bit-exact to the control (LOOPED) |
| `oneshot_adapter_amp.wav` | the same voice at the amp output, end of the per-track chain; audible (LOOPED) |
| `oneshot_adapter_silent.wav` | a triggered all-zero sample: the render is exact silence (the amp's note-on click remains) |
| `oneshot_no_sample.wav` | a null-pointer record: silent (the runner cannot execute the zero-fill loop's count, so it is recorded, not a render) |

### The one blocker left, and what is unverified

- **A note trigger on a type-5 track that was idle the previous block** hits the
  firmware's per-type voice **setup** dispatch (`0x8052db90[type]` at
  `0x1c91ad`), which has five entries: `0x8052db90[5]` reads past it and the
  jump lands at 0. When the voice is triggered on the block it is dispatched,
  the note-on branch (`0x1c9104`) skips that setup and everything runs. So the
  end-to-end above **triggers on the first block**. A real type-5 machine needs
  a **sixth setup-table entry** — the same class of image patch as the clamp and
  lookup, and M4's already-recorded `[O]` ("type 5's per-type setup entry"). It
  is on the critical path for Waverider too, not only ONESHOT.
- **Silicon.** Nothing has run on a DSP; the runner uses G1–G11 (three inferred,
  not cited from the PRM). The DT2 render itself runs with **no** new runner
  workaround — it decodes and executes on digikit's runner as is.
- **The ColdFire side.** The frame here is built from parameter defaults with
  hand-set machine params; a real ColdFire never sets a machine type of 5 or a
  SAMP parameter, and there is no UI to do so.
- **The sample bank is tiny and baked**; the unbounded, user-managed `+Drive`
  library and the browser the DN2 UI lacks remain the expensive, untouched half
  (`docs/drive-storage-research.md`).

### Which bytes are whose

Committed: `src/dnfw/transplant/` (the spec — offsets, sizes, SHA-256 digests,
relocation-site values, all of our own choosing) and `src/dnfw/oneshot/` +
`csrc/oneshot/` (our adapter, record math, bank format, and original test
samples). The DT2 render, divide helper, decimator and coefficient tables are
**extracted from the user's DT2 1.16 file at apply time and relocated in
memory**; none of their bytes is in the repository. The plan refuses a wrong
device, a wrong OS version or a wrong section-7 hash on either image (three
negative controls, all PASS).

**[E]**, offline only. Gate: `scripts/sharc_oneshot_port.py`, all steps PASS.

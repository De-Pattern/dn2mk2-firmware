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

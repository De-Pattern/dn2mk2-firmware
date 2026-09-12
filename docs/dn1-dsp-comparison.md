# The DN1 runs audio DSP on the ColdFire. The DN2 does not.

`docs/engine-index-map.md` §9 established that the **Digitone II's** audio engine
is not in its firmware file: the ColdFire does no DSP, and no section carries a
DSP instruction stream. The obvious follow-up, raised by the owner: is the
**Digitone 1** the same?

**No. It is the opposite, and the difference is large and clean.**

Measured on `Digitone_and_Digitone_Keys_OS1.43_dist.zip` (DN1/Keys OS 1.43) and
`Digitone_II_OS1.11_dist.zip`, both with the Gate-F-cleared reference objdump.

## The census

| | DN1 1.43 | DN2 1.11 |
|---|---:|---:|
| MAIN OS decoded | 2,732,208 B | 3,192,192 B |
| instructions decoded (code region) | 533,223 | 582,407 |
| **MAC / MSAC** | **613** | **50** |
| `mulsl` | 840 | 916 |
| floating-point instructions | 0 | 0 |

Comparable instruction counts and near-identical `mulsl` counts — so the two
builds do a similar amount of ordinary integer multiplication. **DN1 has 12× the
multiply-accumulates.** That difference is specifically MAC, and MAC is what
audio DSP is made of.

**Count only inside the code region.** Disassembling the data region invents MAC
instructions from constant bytes: over the *whole* image DN2 shows 4,983 and DN1
3,915, almost all of it spurious. The tell is that DN2's two largest "clusters"
are byte-for-byte the same size — 532 MACs in 14,881 bytes, twice — which is a
duplicated data block, not code. Bound the scan at the code/rodata boundary
(`0x401d0000` on DN2 1.11, `0x401a0000` on DN1 1.43) or the numbers are
meaningless.

## Where DN1's DSP is, and what it looks like

The 613 MACs are not scattered. **66% sit in clusters of 20 or more**, and the
dense ones are all in one ~20 KB region:

| Range | MACs | Size |
|---|---:|---:|
| `0x4009990a`–`0x40099e4c` | 113 | 1,347 B |
| `0x40098660`–`0x40098c2e` | 86 | 1,487 B |
| `0x4009a7fa`–`0x4009ae46` | 78 | 1,613 B |
| `0x40096ae8`–`0x40096dba` | 47 | 723 B |
| `0x4009a1be`–`0x4009a67c` | 44 | 1,215 B |
| `0x40099388`–`0x400995ba` | 34 | 563 B |

`0x40096000`–`0x4009b000`, **61 external call sites, and not one string
reference** — the signature of a computation kernel rather than anything with UI
or error handling.

The code itself settles what kind of computation:

```
40099970:  macl %d1,%d5,%a0@+,%d1,%acc0
40099974:  macl %d1,%d5,%a0@+,%d1,%acc1
40099978:  macl %d1,%d5,%a0@+,%d1,%acc2
4009997c:  macl %d1,%d5,%a0@+,%d1,%acc3
```

Four multiply-accumulates into the EMAC's **four separate accumulators**, each
with a post-increment load that fetches the next operand in the same
instruction. That is a hand-tuned, software-pipelined convolution or filter
inner loop — the accumulators are being used in parallel precisely to hide the
MAC latency. Nearby, `movclrl %acc0,%d3` reads and clears an accumulator, the
standard way to finish such a loop.

And the buffers it works on are at **`0x8000d69c`, `0x8000d6a0`, `0x8000e6d0`,
`0x8000e6f0`** — the `0x80000000` fast SRAM window, which is where the startup
code copies `.data` (`docs/memory-map.md`). Audio processing on the fastest
memory in the machine. Nothing else in the firmware would be written this way.

## What this means

**Elektron moved the audio engine off the main CPU between the Digitone (2018)
and the Digitone II (2024).** The DN1's ColdFire does real signal processing;
the DN2's is a control processor with an engine somewhere it does not ship code
for.

Three consequences worth recording:

**The DN2's engine is unreachable, and now for two independent reasons.** Its
code is not in the file (§9 of `docs/engine-index-map.md`) *and* the CPU whose
code we do have is not the one doing the work. The fourth-LFO question therefore
stays exactly where PR #33 put it: the engine either already implements one or
it does not, and `scripts/build_lfo4_probe.py` asks it.

**The DN1 is the device where engine-side work is possible.** If the goal were
ever to add a modulator, an effect or a machine that the hardware does not
already have, the DN1 is the target — its DSP is in the image, at
`0x40096000`–`0x4009b000`, in a region with 61 callers and no strings to
confuse the reading. `docs/ideas-backlog.md` §1 already noted the DN1 as the
place where "sacrifice a feature for room" earns its keep; this is a second and
better reason to care about it. Its firmware is also **unsigned** (trailer all
zeros), so the build loop there is shorter.

**Section 8 is confirmed as accessory firmware.** DN1 1.43 ships section 8 at
**exactly** the same sizes as DN2 1.11 — 103,416 stored, 159,948 decoded. The
same ARM Cortex-M image in two different devices' updates is an accessory's
firmware carried by both hosts, which is what `docs/data-sections.md` inferred
from release timing and can now state from the bytes.

## DN1 1.43's sections, for the record

| id | dest | stored | decoded | |
|---|---|---:|---:|---|
| 5 | `0x00000000` | 15 | 15 | meta, raw |
| 2 | `0x02000802` | 16,052 | 29,230 | bootstrap (DN2 1.11 uses `0x02010000`) |
| 3 | `0x40000400` | 1,039,628 | 2,732,208 | MAIN OS |
| 4 | `0x80000400` | 32,776 | 32,776 | updater, raw — **same size as DN2's** |
| **6** | `0x00000000` | 1,492 | 1,492 | raw — **no DN2 equivalent**, unidentified |
| 7 | `0x00000000` | 126,352 | 126,352 | `blob`, **raw** and 6.6× smaller than DN2's 836,956 |
| 8 | `0x00000000` | 103,416 | 159,948 | ARM Cortex-M accessory firmware |

Two open threads, neither chased: **section 6** (1,492 B, raw, DN1-only) is
unidentified, and DN1's `blob` being raw and far smaller than DN2's is
consistent with the DN2 carrying engine *data* — coefficient and wavetables for
a DSP it does not carry code for — but that is an inference, not a measurement.

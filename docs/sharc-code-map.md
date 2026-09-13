# Which of the SHARC image is code, and where it executes

**Measured 2026-09-13 on Digitone II 1.11**, against digikit `ec32de1`.

`docs/sharc-image.md` establishes that section 7 is the SHARC program as an ADI
boot stream, and `bootstream.load_regions()` plays it into the memory it
describes — 9 regions, 6,423,108 bytes. That is an image, not yet a map: it does
not say which of those bytes are instructions, nor what address the processor
knows them by. Both are answered here, and neither needed a disassembler.

## 1. About 240 KB of the 837 KB section is code

The test is digikit's `sharcscan.py` decode, used as documented rather than
re-derived: a 48-bit SHARC+ VISA instruction is three little-endian 16-bit words
assembled **MSB word first**, `insn = (w0<<32)|(w1<<16)|w2`, with candidates only
at even byte offsets. A `cjump` absolute is `(insn>>24) & 0xFFFFFF == 0x180400`,
its target `insn & 0xFFFFFF`. This is how ADI's compiler emits a call, so
counting them is a code detector.

| region | bytes | cjump | what |
|---|---|---|---|
| `0x20000000..0x2001e880` | 125,056 | **1002** | **code** (L1) |
| `0x2001e888..0x2008823c` | 432,564 | 0 | data |
| `0x28240000..0x28240300` | 768 | 0 | |
| `0x282403f0..0x2826f000` | 191,504 | 0 | rodata — `event_groups.c`, `queue.c`, `stream_buffer.c`, `port.c`, `Audio Task` |
| `0x282c0000..0x282dd52c` | 120,108 | 0 | rodata — `tasks.c`, `timers.c`, `heap_4.c` |
| `0x28380000..0x283825c0` | 9,664 | 10 | |
| `0x283825c4..0x2839bffc` | 105,016 | **604** | **code** (L2) |
| `0x80000000..0x80000014` | 20 | 0 | |
| `0x80000018..0x8052fbe0` | 5,438,408 | 0 | DDR, almost all zero fill |

**1,616 cjumps, and they are not spread evenly** — they concentrate in two
regions and are absent from seven. A decoder firing on noise would not do that.

**The control is built in and was not arranged for.** The 432,564-byte data
region and the 5.4 MB DDR fill return **zero**, which is the same negative
control digikit reports (49,152 bytes of float coefficients → zero hits). A test
that fires everywhere proves nothing; this one is silent across 5.9 MB and loud
across 240 KB.

**Independent corroboration:** digikit measures **1,656** cjumps over a
comparable Digitakt II code region. Ours is 1,616 on a different product from a
different extractor. Two builds, two toolchains, same order of magnitude — the
decode transfers.

### The landmark strings are in rodata, which is where they belong

Every FreeRTOS path and `Audio Task` sits in a region with **zero** cjumps. That
is not a disappointment, it is the expected result: string constants live in
read-only data, not in `.text`. It also bounds the search for the code that
references them — it is somewhere in 240 KB, not 837 KB.

## 2. The exec↔load mapping, confirmed for one address space

Boot-stream targets are **load** addresses (`0x2826ee10`). cjump targets are
**execution** addresses in two spaces, `0x1c` and `0xb8`, and they are not the
same numbers. Nothing can be cross-referenced until they are related.

```
load = exec × 2 + 0x28000000
```

Two pieces of evidence, and the first is the one that matters:

**The entry point lands on a boundary.** The boot stream's final block gives
entry `0x001c12e2`. Mapped, that is `0x283825c4` — **exactly the first byte of
the L2 code region**, to the byte. An arbitrary affine map does not land on a
block boundary by chance.

**And the population agrees.** Of the 1,616 cjump targets, **591 of 591** in the
`0x1c` space land inside a loaded region under this map. The rival maps fail
completely:

| map | targets landing inside a loaded region |
|---|---|
| `t × 2 + 0x28000000` | **591** / 1616 |
| `t × 4 + 0x28000000` | 0 / 1616 |
| `t + 0x28000000` | 0 / 1616 |

The factor of **2** is the interesting part: it says code addresses count
**16-bit words**, which is exactly VISA's instruction granularity, and agrees
with digikit's independent alignment analysis (motifs on even offsets, spread
uniformly across mod 4, 6 and 8 — variable-length 16-bit-granular encoding, not
fixed 48-bit words). Two unrelated measurements converging on the same fact.

### Open: the `0xb8` space

**1,025 of the 1,616 targets** are in the `0xb8` space and **no mapping is
known**. `t × 2 + 0x28000000` puts them outside every loaded region. They may
address DDR (the image reserves 5.4 MB at `0x80000000`, almost all fill, which is
where a large working set would live), but that is a guess and is recorded as
one. The `0x1c` result does not transfer to it by assumption.

## What this is for

A disassembler pointed at 240 KB of identified code with a working address
mapping is a different proposition from one pointed at an 837 KB blob with no
addresses. digikit's `sharc_disasm.py` is that disassembler; this is the input
to hand it.

**What it does not establish.** Nothing here says the synthesis engine is in this
image, and the fourth-LFO question is untouched. It says where the instructions
are and what the processor calls them.

## Reproducing

The counts come from walking `bootstream.load_regions()` output with the decode
above. Nothing in this repository disassembles SHARC, and this does not either —
it counts one instruction form whose encoding is published and whose false-positive
rate is bounded by the zero-hit control regions in the table.

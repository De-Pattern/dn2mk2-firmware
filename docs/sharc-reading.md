# Reading the SHARC: how much of it decodes, and what stops the rest

**Measured 2026-09-14 on Digitone II 1.11**, against digikit `ec32de1` and
Ghidra 12.1.3 with digikit's `SHARC:LE:32:VISA` module.

`docs/sharc-code-map.md` says which bytes are code and what the processor calls
them. `docs/sharc-disassembly.md` says a disassembler exists and installs it.
Neither asks the question that decides whether the LFO hunt can proceed: **can
we actually read these instructions?**

The answer is a qualified no, and the qualification is unusually sharp — one
missing length rule accounts for 95% of the failures.

## 1. The image has no symbols, and that is settled

Before anything harder: the SHARC image was searched for names. Across all nine
loaded regions there are **2,133 distinct printable strings**, and after
discarding float data that happens to be ASCII, exactly **eight** are real:

```
0x28268a78  Audio Task
0x2826ee10  ..\..\..\..\lib\freertos-sharc\event_groups.c
0x2826ee50  ..\..\..\..\lib\freertos-sharc\queue.c
0x2826eec0  ..\..\..\..\lib\freertos-sharc\stream_buffer.c
0x2826ef40  ..\..\..\..\lib\freertos-sharc\portable\CCES\SHARC_215xx\port.c
0x282d0738  ..\..\..\..\lib\freertos-sharc\tasks.c
0x282d0848  ..\..\..\..\lib\freertos-sharc\timers.c
0x282dd0e0  ..\..\..\..\lib\freertos-sharc\portable\heap_4.c
```

No Elektron source path, no class name, no parameter label. Whatever names the
ColdFire side hands us through RTTI (`docs/mainos-image.md`), **none of it is
here**. The DSP has to be identified by structure, not by reading.

The paths do say something: the compiling unit sits four directories below a
root that also holds `lib/freertos-sharc/`, and the port is ADI's CCES for
`SHARC_215xx` — the vendor toolchain, as expected for an ADSP-21569.

## 2. Data references, and the needle that found none

A landmark is only useful if the code that points at it can be found. The first
attempt searched for the eight addresses in every plausible encoding — as-is,
minus the region base, halved, quartered — and found **zero hits in 6.4 MB**.

That is not a firmware without references. It is the wrong needle.

A 48-bit VISA instruction is three little-endian 16-bit words assembled **MSB
word first**, so a 32-bit operand sits in memory with its halves in the opposite
order to a plain little-endian long. One encoding works:

```
operand bytes = LE(hi) || LE(lo)   of   (load_address - 0x28000000)
```

**The evidence is the shape of the hits, not their existence:**

| string | references | all in code? |
|---|---|---|
| `queue.c` | 45 | yes |
| `tasks.c` | 40 | yes |
| `event_groups.c` | 14 | yes |
| `stream_buffer.c` | 14 | yes |
| `heap_4.c` | 5 | yes |
| **`Audio Task`** | **1** | yes |

All 105 hits land inside the two code regions and none in the 6.2 MB outside.
The other nineteen candidate encodings produce zero hits anywhere. And the
counts are *semantically* right: `queue.c` and `tasks.c` are FreeRTOS's two
biggest files and the ones thickest with `configASSERT`, while a task name
passed to `xTaskCreate` appears exactly once. A needle matching noise would do
none of that.

**This is a second address mapping, and it is not the one in
`docs/sharc-code-map.md`.** That file maps *execution* addresses for code.
This maps *operand* values for data, and they are different rules: code counts
16-bit words, data counts bytes.

## 3. FreeRTOS is in L1, the application is in L2

`scripts/sharc_callgraph.py` partitions the code by the only structural fact
available: **every cjump target is a function entry**, because that is what
being called means. Sorting the 1,606 resolved targets gives **461 functions**
without disassembling anything.

Naming them from the eight strings covers **65 functions**, and every one of
them is in the **L1** region. `Audio Task`'s single reference is the lone
exception, in **L2** at `0x28394018`.

So the split is clean:

| region | holds |
|---|---|
| L1 `0x20000000..0x2001e880` | FreeRTOS — tasks, queues, timers, heap, the CCES port |
| L2 `0x283825c4..0x2839bffc` | the application, including whatever makes sound |

That halves the search space for the LFO generator before a single instruction
is read, and it is measured rather than assumed.

### The audio task's creation site

`0x28394000` is a 64-byte function, called once, that loads `"Audio Task"` and
then calls `0xb88839` → `0x20011072`, which sits inside the `tasks.c` cluster.
That is `xTaskCreate`. **The task body it registers is not in the call graph**,
which is correct and is the point: a task body is reached only through the
scheduler, so nothing ever cjumps to it.

## 4. How well the disassembler actually decodes — with an oracle

`docs/sharc-disassembly.md` reported *"~81% confidently decoded"*. That number
is retracted there and the reasoning is kept. The short version:

> **[WRONG — corrected 2026-09-14]** The 81% came from walking the region and
> **restarting after each stop**. Each restart re-anchors at an arbitrary even
> offset, and an all-zero 48-bit word satisfies Type21a's mask — so the restart
> strategy manufactures its own confidence. The figure counts false positives
> as successes and has **no outcome that means "wrong"**.

`scripts/sharc_decode.py` replaces it with a measurement that can fail. The
cjump scan is independent of any walk and already validated, so **every cjump
site is an instruction boundary the disassembler never saw**. Walk each function
from its entry and ask: did the walk land on them?

| method | bytes covered | known boundaries hit |
|---|---|---|
| linear walk (`sharc_disasm.py`) | 15,902 / 229,298 — **6.9%** | 62 / 1,589 — **3.9%** |
| **Ghidra, following flow** | 74,976 — **32.7%** | 295 / 1,606 — **18.4%** |

**Ghidra is ~4.7× better on both measures, with the same instruction tables.**
The difference is entirely method: a linear walk desynchronises on one wrong
length and never recovers, while flow-following re-anchors at every branch
target. 210 of 250 checkable functions desync completely under a linear walk.

This also settles how to disassemble this image: **seed Ghidra with the 461
known entries and let flow do the rest.** Auto-analysis alone is worse than
useless here, because padding disassembles confidently.

### A worked desync, because it is instructive

Walking the `xTaskCreate` site from `0x28394000` produces eight consecutive
*confident* instructions and steps straight over the cjump at `0x28394026`. The
single error is at `0x2839400e`, where `0x9fc4` is taken as a 4-byte `16b` when
the alignment that lands on the validated cjump needs 2. Every printed line
looked fine. None after that one was.

## 5. What stops it: one rule, named by its own author

Of 396 walk failures, **378 are the same group** — `GROUP_5A_5B_MOVE`:

```
word0 matches multi-word group GROUP_5A_5B_MOVE
but the second-word test did not resolve it
```

digikit's `sharc_visa_tables.py` marks this an **honestly named gap**:
Type5a_move is 48 bits, Type5b_move is 32, they share word-0 opcode bits, and
the transcription found no fixed bit in Type5b_move's second word to test for.
Its note offers two possibilities and asserts neither — either the pair is
genuinely undecidable from opcode bits, or the 400-DPI crop missed a gray cell.

**So the SHARC is not broadly unreadable. It is one length rule away from
readable**, and a walk needs nothing but lengths to stay in step.

## 6. Resolving it from code, not from the manual

`scripts/sharc_lengths.py` uses what a transcription does not have: **1,606
verified instruction boundaries in real firmware.** Between two boundaries the
lengths must sum *exactly* to the distance, so enumerate every assignment of 4
or 6 bytes to the ambiguous instructions in a span and keep the ones that land
on the far boundary.

```
spans solved with exactly one reading      789
spans with several self-consistent readings 351
spans with no solution                      792
```

**322 ambiguous instructions are forced by the code around them: 215 are 32-bit,
107 are 48-bit.** Both forms are real and common, so no "always 48" or
"always 32" default is available.

### The question the author left open, answered

Testing all 16 bits of word1 against the outcome: **no single bit predicts the
length.** And the decisive test — restricted to the 208 decisions from spans
with *exactly one* possible reading, so no ambiguity in the reading itself —
finds **five (word0, word1) pairs forced to different lengths in different
places**:

```
word0=0x727e word1=0x8402  ->  4B at 0x20007c10   6B at 0x200121da
word0=0x727e word1=0x8128  ->  4B at 0x2000ac64   6B at 0x20014862
word0=0x726f word1=0x003f  ->  4B at 0x2000ac74   6B at 0x20016962
word0=0x724f word1=0x003f  ->  4B at 0x2000c236   6B at 0x2000c26c
word0=0x717e word1=0x07bf  ->  4B at 0x200117aa   6B at 0x20013116
```

The fourth pair is the clearest: the same two words, **54 bytes apart in the
same function**, one 32-bit and one 48-bit.

**A rule over word0 and word1 cannot exist.** The missing information is not a
gray cell the crop lost — it is not in those words at all. That is evidence for
the author's *first* possibility, and it means any VISA decoder needs context
(surrounding boundaries, or a third word's semantics) rather than a better
table.

### What would overturn this

A false-positive cjump site would manufacture a contradiction by constraining a
span wrongly. Five independent pairs from unique-reading spans make that
unlikely but not impossible, and the addresses are listed precisely so each can
be checked by hand. If the cjump scan is ever shown to produce false positives
in dense code, this section is the first thing to re-run.

## 7. The address space to give Ghidra

digikit's SLEIGH module resolves call targets itself:

```
Dest24: reloc = ((w1 & 0xff) << 17) + (w2 << 1)
```

So Ghidra works in neither load nor execution addresses but in that formula's
output:

| execution space | Ghidra flat base | region |
|---|---|---|
| `0x1cXXXX` | `0x380000 + 2·XXXX` | L2 code |
| `0xb8WWWW` | `0x1700000 + 2·WWWW` | L1 code |

The first is just the load address minus `0x28000000`, which is why the earlier
L2-only import at `0x3825c4` worked. **The second is new and useful:** place L1
at `0xb8 << 17` = `0x1700000` and the 1,025 `0xb8` calls resolve *natively*,
with no fixing up, in the same program as L2. It collides with nothing.

`scripts/export_sharc_regions.py` writes the blocks and the entry list;
`ghidra/SharcImport.java` builds the program, seeds the entries and exports the
listing. The L2 rodata blocks go at `addr - 0x28000000` so string references
resolve too.

**One block is placed on an extrapolation and is marked `unverified` in the
manifest:** the L1 *data* region, which trails L1 code. The affine rule is
verified where L1 *code* sits, because 1,025 call targets land correctly there;
nothing checks it for the data that follows. The DDR region at `0x80000000` is
not placed at all — nothing constrains where it would go.

## 8. Where this leaves the fourth LFO

Unchanged in direction, sharper in cost:

- MAIN OS contains **no generator of any kind** (`docs/display-path.md`), so the
  generator is SHARC-side.
- The SHARC application is **L2**, 105 KB, 604 call sites — FreeRTOS is L1 and
  can be set aside.
- At **18.4%** boundary coverage, reading it is not yet possible. Identifying a
  phase accumulator needs the instruction stream to be in step, and right now it
  is in step for roughly a fifth of the calls.

The blocker is therefore not "find the right decompiler" — the tooling exists
and is installed. It is one ambiguity in one instruction group, and §6 shows it
cannot be closed by a better reading of the manual.

**What would move it:** a VISA decoder that carries the constraint solver
inline, choosing lengths that keep the walk consistent with known boundaries
rather than committing greedily. That is a real piece of work and it belongs
upstream in digikit, where the tables live.

## Reproducing

```
python scripts/sharc_callgraph.py <image> --json out/sharc-graph.json
python scripts/sharc_decode.py    <image>                 # linear walk, scored
python scripts/sharc_decode.py    <image> --unresolved    # what stops it
python scripts/sharc_lengths.py   <image>                 # the 4/6 question
python scripts/export_sharc_regions.py <image> --out out/sharc
ghidra\analyze.bat <proj> sharc out\sharc\code_283825c4.bin 0x3825c4 \
    -postScript SharcImport.java out\sharc out\sharc\ghidra-listing.txt
python scripts/sharc_decode.py <image> --ghidra out/sharc/ghidra-listing.txt
```

No firmware bytes are written into this repository; `out/` is gitignored.

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

> **[SUPERSEDED 2026-09-14 - see section 10.]** The table above is measured
> against digikit `ec32de1`, the revision this repository pinned. **digikit
> PR #9 changed the tables and the linear-walk figure is now 44.9%**, not
> 3.9%. The comparison *between methods* still holds, since one decoder
> produced both rows, but the absolute numbers are stale.

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

### The 792 spans with no solution, investigated

Those failures were the first thing to explain, because if they meant the
boundaries were unreliable the contradictions above would be manufactured rather
than found. **Measured 2026-09-14 with `--why`:**

```
ran into an encoding with NO length rule        14
every assignment overshoots the boundary       778
both, on different branches                      0
```

So it is almost entirely *overshoot*: starting at a known boundary, no
combination of lengths lands exactly on the next one. Three candidate causes
were tested.

**Not false-positive boundaries sitting too close.** A cjump is 6 bytes, so a
boundary fewer than 6 bytes after a cjump site would prove one of the two is not
a real instruction start. There are **zero** such cases. The smallest gaps in
the whole population are 2 spans of 4 bytes, 1 of 8 and 6 of 10 — all legal.

**Not a mis-decoded cjump.** `decode_length_multiword(0x1804)` returns 48,
correctly, so the walk does not start a cjump span misaligned.

**Not systematic inter-function padding.** If functions were aligned, the walk
would legitimately stop short of the next entry. Entry addresses mod 8 are
`147 / 87 / 132 / 95` — a mild bias toward 0 and 4, nowhere near the
concentration alignment padding would produce.

**So the cause is not yet established.** What remains, in order of likelihood:
length rules that are wrong outside the ambiguous group; inline literal pools
between functions; and occasional bad boundaries. That is stated as an open
question rather than resolved by preference, and it is the first thing to settle
before the constraint solver is turned into a decoder.

**What it does not threaten.** The contradictions in §6 are drawn *only* from
spans that solved exactly, and no-solution spans contribute nothing to them. The
residual risk is narrower and worth naming: a span could solve exactly and still
be read wrongly, if bytes that are not instructions happened to decode to
lengths summing to the right total. Five independent pairs make that unlikely;
one hand-checked disassembly of any of the listed addresses would settle it.

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

## 9. Upstream

Both findings went back to `m-dwyer/digikit`, since the tables and the
disassembler are theirs:

| | |
|---|---|
| **PR #7** | `sharc_disasm: don't format word1 when it was never read`. `disassemble()` raises `TypeError` instead of yielding an `unknown` record when word0 matches a multi-word group and word1 could not be read — it formats `None` with `{word1:#06x}` in the branch where the value was never assigned. Reachable from documented use: any caller walking per-function buffers ends a buffer mid-instruction routinely. Verified stock-crashes / patched-yields before sending. |
| **Issue #8** | The `GROUP_5A_5B_MOVE` evidence in §6, with all five contradicting addresses, the method, and what would overturn it. Offered to contribute the constraint-carrying decoder rather than assuming they want it. |

The issue also carries the two mapping facts they can use directly: the
`0xb8 << 17` placement that makes both regions resolve in one Ghidra program
(§7), and the byte-counted word-swapped rule for data operands (§2).

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

---

# 10. Re-measured against digikit PR #9 (2026-09-14)

digikit merged **PR #9** - "SHARC analysis, firmware rebuild, and an eighth
machine in the emulator", 39 commits. Two parts land directly on this file, and
one obsoletes its headline numbers.

## The gap in section 5 is closed upstream

Section 5 said 95% of walk failures were `GROUP_5A_5B_MOVE`, and section 6
argued from code that no rule over `(word0, word1)` could exist. **digikit
resolved it in "revision 4" by re-reading the source figure at 400 DPI**, and it
is real work rather than a guess: `Type5b_move` grays its own bits 6:0 (source
bits 22:16) to zero, where `Type5a_move` carries a real `compute[22:16]`. The
test is `(word1 & 0x407f) == 0` for the 32-bit form, with bit 14 included as
confirmation rather than as a discriminator.

## The net effect on this image is large

Same oracle as section 4 - a linear walk from the 461 known entries, scored on
whether an instruction starts exactly at each validated cjump site:

| tables | boundaries hit | walks that stopped |
|---|---:|---:|
| `ec32de1` (what section 4 measured) | 62/1589 - **3.9%** | 224 |
| `main` after PR #9 | 714/1589 - **44.9%** | **19** |

**11.5x more boundaries, and stops fall from 224 to 19.** Section 4's "6.9% of
bytes readable" framing is obsolete, and so is any claim that the SHARC is
effectively unreadable.

## But the discriminator scores below a constant, on this image

Using PR #9's tables throughout and overriding **only** the 5a/5b decision:

| decision for that group | boundaries hit |
|---|---:|
| rev4 rule, `(w1 & 0x407f) == 0` | 714/1589 - 44.9% |
| **control: always 32-bit** | **824/1589 - 51.9%** |
| control: always 48-bit | 729/1589 - 45.9% |

A correct rule should beat both constants. This one sits between them, 110
boundaries below "always 32-bit".

**The controls are the whole point.** Without them, 44.9% reads as success - and
this repository has made exactly that mistake before, in the "81% confidently
decoded" that section 4 retracts for having no outcome that means *wrong*.

It agrees with section 6's constraint evidence rather than contradicting it: the
rule matches only **90 of 322** code-forced decisions (28%), and the five
contradicting `(word0, word1)` pairs survive under it. `w0=0x724f w1=0x003f`
gives `w1 & 0x407f = 0x3f`, so the rule calls it 48-bit - while the code forces
32-bit at `0x2000c236` and 48-bit at `0x2000c26c`, 54 bytes apart in one
function.

**Carried honestly:** section 6's 778 unexplained overshoots still qualify the
forced-decision numbers. The boundary-hit table does not depend on the span
solver at all, only on the cjump oracle, and is the stronger evidence. And this
is a **Digitone II** image - if rev4 beats the constants on Digitakt II and
loses here, that is more interesting than a misread figure.

Posted to `m-dwyer/digikit#8`, leading with the improvement.

## What PR #9 also gives us

Recorded because it changes what is possible here:

- **`tools/machinepatch.py` adds an eighth machine type** to Digitakt II - five
  coordinated patches (list, dispatch, group, display-name table, and the sort
  `std::map` ranks, without which `map::at(7)` throws and boot ends in
  `std::terminate`). A working precedent for adding a **track type** on this
  platform, which `docs/ideas-backlog.md` section 8 pathway 1 assumed was
  expensive. Emulator-only; selecting the machine is untested.
- **`dt2/aplib.py`, `dt2/build.py`, `dt2/authcode.py`** - an independent
  implementation of the container write side and the HMAC trailer. A second
  opinion on our Gates A-C, from code sharing no lineage with ours.
- **`tools/sharc_import.py`** imports the SHARC at its load addresses, where
  `scripts/export_sharc_regions.py` places both regions in one flat space via
  the SLEIGH relocation. Worth diffing the two approaches.

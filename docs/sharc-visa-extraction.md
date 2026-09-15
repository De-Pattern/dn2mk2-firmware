# Reading the SHARC+ VISA encodings out of the PRM

**2026-09-15.** Work done in parallel with `m-dwyer/digikit`, who is building a
SHARC+ VISA disassembler by transcribing Analog Devices' opcode figures. The
owner's idea: do it independently and compare, because her single largest bug
so far was a **misread figure**, and a second reader is the cheapest possible
check on that class of error.

Everything here is measured against **SHARC+ Core Programming Reference, Part
Number 82-100131-01, Revision 1.5**, 798 pages,
`sha256 a3edf83beb75b44a77f8366cf54c0353083ab49a1c69d8179d2b727ba7ba1470`.

## 1. The figures do not need reading by eye

Her handover records losing 88–93% of all instruction walks to one misread
figure — *"Type5b_move, eight gray cells recorded as none"* — and her next
commit is *"Read the Type5b_move figure again, at 400 DPI this time."*

**No DPI is required, because the shading is not a picture.** Across the whole
instruction chapter (pages 300–420, 121 pages):

```
pages carrying a raster image : 0
raster images in total        : 0
```

Every bit cell is a vector rectangle with a fill colour in the PDF's content
stream, and every bit number and value is real text at a known position. So the
figures come out exactly, reproducibly, with no OCR and no vision model.
`scripts/prm_opcode_figures.py` does it.

### The trap is in the geometry, not in anyone's care

**A shaded run is ONE rectangle spanning several cells**, not one rectangle per
cell. The seven shaded cells at bits 22–16 of Type5b_move are a single 63-point
box:

```
x0=316.50 w=63.00 h=9.00 fill=(0.8235, 0.8235, 0.8235)
```

Count rectangles instead of cells and you get **2 where the answer is 8**. That
is exactly the "recorded as none" failure, and it is the file's structure
inviting the error. Converting each rectangle's width back into a cell count
makes it unreadable any other way.

### Type5b_move, extracted

```
bit   47 46 45 44 43 42 41 40 39 38 37 36 35 34 33 32
value  0  1  1  1  0  0  0  0  0  0  0  0  0  0  0  0
fixed  #  #  #  #  #  .  .  .  .  .  .  .  .  .  .  .    5 cells

bit   31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16
fixed  .  #  .  .  .  .  .  .  .  #  #  #  #  #  #  #    8 cells
```

**The eight are bit 30 and bits 22–16.** Shaded means *fixed*; unshaded means
*field bit*.

> **Honest note on independence.** The number *eight* was known from her
> handover before counting, so the count is not a blind confirmation. The
> **positions**, and the shaded-means-fixed reading, are ours — and the other 52
> figures were extracted without opening `sharc_visa_tables.py`.

## 2. Coverage

Two different things are worth counting, and only one of them is at 100%.

### Figure coverage: 100%

| | |
|---|---|
| figures found (pages 308–425) | **54** |
| figures left unnamed | **0** |
| rows failing the descending-bit self-check | **0 of 137** |
| declared instruction families | **44** |
| families with no figure | **0** |

### Bit-level accounting: 87.82% — which is 100.0% of what the figures contain

Every bit of every form should be either a fixed opcode bit or part of a named
field. **1,911 of 2,176 bits are accounted for.**

**That is the ceiling, not a shortfall.** A field is named by a bracket drawn
beneath its bit row, so the most any figure-only method can recover is the
fixed bits plus the bracketed ones. `scripts/prm_label_ceiling.py` counts them
independently of the extractor:

```
bits across all figure rows            2,176
  fixed (shaded) bits                    546
  free bits under a bracket            1,365
  free bits with NO bracket              265
                                       -----
CEILING on figure-only accounting     87.82%
```

`546 + 1,365 = 1,911`, exactly what the extractor produces. **Every bit the PRM
names in its figures has been recovered.** The remaining **265 bits (12.18%)
are not named in the figures at all** — their names, where they exist, are in
the syntax tables, which is a different extraction.

> **The ceiling took three attempts, and each error inflated it.**
>
> **94.85%** — the *next* bit row's own frame sits inside the previous row's
> bracket band and is the same shape as a long bracket, so rows with no
> brackets counted as labelled. p413 has four rows and no brackets whatever;
> that version flagged one.
>
> **92.00%** — counting per *row* rather than per *bit*. A row is routinely
> part-bracketed: Type20a's bits 31..27 each carry a leader while 26..16 carry
> nothing, and crediting the whole row hid eleven unnamed bits.
>
> **87.82%** — per bit, row frames excluded.
>
> A measurement of what is *possible* is as easy to get wrong as the thing it
> bounds, and both errors ran the same way: making the document look more
> complete than it is, and our extraction look worse.

This is a coverage figure that means something, and it is the one to track. It
**cannot be improved by loosening anything** — unlike a match rate, where an
emptier table scores higher. A gap names the form and the bits that remain
unexplained.

The 265 unnamed bits fall across 23 rows. Seven rows are wholly unbracketed —
in `Type4d`, `Type20a`, `Type21a`, `Type22a`, `Type25a_rframe`, `Type25c_rframe`
and `Type26a` — and the rest are rows where only some bits carry a leader, as
in `Type20a`, whose bits 31..27 each have one while 26..16 have none.

> **[SUPERSEDED — this section previously said 91 of those bits were "ours to
> recover".]** That came from the 92.00% version of the ceiling and was an
> artefact of counting per row. There are none: the extractor reaches the
> ceiling exactly.

Widths: **16-bit ×6, 32-bit ×14, 48-bit ×34.** VISA is genuinely variable, and
treating every figure as 48-bit — slicing "the top 8 bits" at 47..40 — is
meaningless for a third of them.

The self-check is what makes the zeros above worth anything: bit labels are read
from the page rather than assumed, so a mis-mapped row shows as a sequence that
is not a clean descending run. Run over the entire 798-page document it flags
exactly one spurious figure, on page 42, outside the instruction chapters.

## 3. Three structural findings a decoder needs

### ISA and VISA must be partitioned before any prefix analysis

The processor runs one encoding or the other; they do not interleave. Of five
apparent length ambiguities in the top-7 prefix, **four dissolve once the modes
are separated** — they are `a`/`b` pairs, the same instruction in both
encodings, which never compete for the same bytes.

```
7a = ISA/VISA   7b = VISA        9a = ISA/VISA   9b = VISA
```

Measuring prefixes across both at once measures nothing.

### Decode order is load-bearing: 9 subsumption pairs

A pattern with few fixed bits **subsumes** stricter patterns nested inside its
space. Tested first, the loose one wins, swallows the strict one's
instructions, and — because the forms differ in length — desynchronises the walk
from there on. Same failure class as the Type5b bug, generalised.

Same-mode pairs, loose → strict:

| loose | fixed bits | swallows | fixed bits |
|---|---|---|---|
| `Type1a` | 3 | `Type2a` | 20 |
| `Type4a` | 4 | `Type4d` | 8 |
| `Type6a_mem` | 4 | `Type6a_nomem` | 16 |
| `Type19a` | 6 | `Type18a`, `Type20a` | 9, 9 |
| `Type14d` | 7 | `Type25a_rframe` | 24, 16 |
| `Type25a_rframe` (32-bit) | 16 | `Type25a_rframe` (48-bit) | 24 |

**Every subsumed pattern must be tried before the pattern that subsumes it.**

### An inconsistency in the PRM itself

Page 419's figure is captioned **`Type25a_rframe`** while its section heading
reads **`Type 25c VISA (rframe)`**. Anything keyed on one will disagree with
anything keyed on the other.

## 4. The measurement that matters, and why match rate is not it

A decoder built from the figures alone was run over DN2 1.11's section 7, with
controls:

| input | match rate |
|---|---|
| SHARC code `0x20000000` | **63.66%** |
| SHARC code `0x283825c4` | **63.32%** |
| **ColdFire MAIN OS — a different architecture entirely** | **53.07%** |
| **random bytes** | **46.65%** |
| all-zero bytes | 99.99% |

**That 63% is not coverage; it is an entropy measurement.** The table scores 53%
on an instruction set it has nothing to do with. Real code beats the
wrong-architecture control by ten points.

The cause is structural and not a bug: **`Type1a` fixes three bits out of
forty-eight**, by design, because it is the multifunction form and the rest is
operand. Such a pattern matches one word in eight. A handful of them predicts
the ~47% observed on noise almost exactly.

**So a coverage figure of 100% on this metric would be evidence of a worse
table, not a better one** — all-zero bytes already score 99.99%. Loosening the
patterns raises the number.

This is independent confirmation that digikit's choice of metric is the right
one: she reports **branch-target alignment, 92–99% on real firmware against
0.4–3.6% for noise** — a ~30× separation where match rate gives 1.2×.

### What does help: constraining the compute field

Chapter 18 lists which compute operations exist. Extracting the ALUOP table —
**61 of 256 eight-bit values are legal, 23.8%** — and requiring a loose 48-bit
form to carry a valid compute field moves the separation the right way:

| | before | after |
|---|---|---|
| code vs random | +16.37 pts | **+17.56 pts** |
| code vs ColdFire | +10.42 pts | **+14.60 pts** |

It suppresses false matches harder than real ones, which is what a real
constraint does. It is still not branch alignment.

## 4b. The figures alone do not decode SHARC code, and the gap is measurable

A recursive-descent walk was seeded from the boot stream's own entry point
(`scripts/sharc_seeded_walk.py`). The address mapping checks out exactly:

```
boot-stream entry  exec 0x001c12e2  ->  load 0x283825c4
```

which is the base of a code region, so the entry sits at **offset 0** of it.
`docs/sharc-code-map.md`'s `load = exec * 2 + 0x28000000` predicted that, and
the agreement is a check on the rule rather than an assumption of it.

**The walk decodes one instruction and dead-ends.** So does a run-length sweep,
from every offset and under every word order:

| word order | best runs | median | mean |
|---|---|---|---|
| **high-first / LE** | 86, 85, 84, … | **1** | 3.5 |
| high-first / BE | 52, 51, 50, … | 1 | 2.7 |
| low-first / LE | 46, 45, 44, … | 1 | 2.0 |
| low-first / BE | 51, 50, 49, … | 1 | 2.4 |

Those descending "best runs" are **one** long run counted from successive
offsets inside it, not many independent ones. High-first/LE is marginally
ahead, consistent with the assumed layout, but nothing is decisive because
nothing sustains.

**Median run of 1 means two consecutive instructions are essentially never
decoded correctly.** digikit's handover reports a median run of **632** on real
firmware after her Type5b fix, against 45 for a random-bytes control.

That is the honest size of the gap, and **it is not the figures** — those are
extracted to their ceiling (§2). It is everything else in the chapter: register
classes, the compute encodings, and the sub-opcode tables that constrain the
fields the figures leave open. A pattern with three fixed bits is not an
instruction, and no amount of geometry makes it one.

### The patterns carry no positional information, and that is measurable

If the table could locate instructions, sampling at the right stride and phase
would match far more often than sampling at the wrong one. It does not:

| region | stride 2 | stride 4 | stride 6 | stride 8 |
|---|---|---|---|---|
| `0x283825c4` | 54.1% | 55.4% | **54.1%** | 54.4% |
| `0x20000000` | 50.1% | 53.3% | **53.7%** | 53.7% |

And at a 6-byte stride, across the three possible phases: **54.1%, 54.0%,
54.5%**. A real instruction stream has a preferred phase. This one shows none,
which means the 48-bit patterns match arbitrary windows at about the same rate
wherever they land — the table says nothing about *where* an instruction starts.

**Two constraints were tried and neither fixed it.** The compute-field check
(ALUOP and MULOP, §5) leaves the median run at 1 and lowers the mean, and no
word ordering sustains a run. So the missing constraint is not the compute
field either.

There is real signal — mean run 3.48 on code against 0.90 on noise, and branch
targets landing in range 31× more often than chance — it is simply nowhere near
enough to decode. The figures are a skeleton, and the flesh is in the tables.

## 5. What is not done

**Branch alignment**, which is the metric that would be comparable to hers. The
field extents it needs are now extracted (§2), so the remaining work is
following each branch form's displacement field and checking the target lands
inside the code region on an instruction boundary. That is the next step.

**The last 12.18% of bit accounting.** Not recoverable from the figures — see
§2; the names are in the syntax tables.

### How the field extents were recovered, since it is reusable

Under each bit row the PRM draws a bracket spanning a field's cells and a leader
line out to the field's name. **The bracket's endpoints sit on cell centres**, so
a cell index is exactly `(x - (frame.x0 + 4.5)) / 9`. Matching bracket to name
means following the leader whose near end lies within the bracket's span and
taking the nearest label to its far end — width alone will not do it, because
`srcureghigh[4:0]` and `cond[4:0]` are both five bits.

Two shapes had to be handled, and each was worth several points of coverage:

- **A one-bit field is an L-leader**, not a bracket, so only one end sits on the
  grid — and **which** end depends on which side its label is. Testing only
  `x0` loses every leader that runs leftward to its name.
- **Some figures name individual bits with a bare mnemonic** (`lldi`, `lpu`,
  `spu` on Type20a) rather than the `name[hi:lo]` form. Requiring the bracketed
  form leaves those figures looking unlabelled.

A shortcut was tested and rejected: each label declares its own width, so the
widths might tile the unshaded cells. They do for only 12 of 46 figures, so
geometry was needed after all.

## 6. The compute and register tables, and what they turned out to be worth

### All five compute families extract

| family | field | patterns | values admitted |
|---|---|---|---|
| ALUOP | bits 19–12 | 61 | 61 / 256 — **23.8%** |
| MULOP | bits 19–12 | 25 | 206 / 256 — 80.5% |
| **SHIFTOP** | bits 19–12 | 25 | **25 / 256 — 9.8%** |
| **SHIFTIMM** | bits 21–16 | 18 | **18 / 64 — 28.1%** |
| DUALADDSUB | bits 19–16 | 2 | 2 / 16 — 12.5% |

SHIFTOP and SHIFTIMM needed two fixes. **Table 18-9 carries two encodings side
by side** — headed `shiftimm (bits 21-16)` and `shiftop (bits 19-12)` — so a
header pattern matching the literal word `opcode` finds neither, and a reader
that takes column 0 only loses half the table and mislabels the rest. Every
column declaring a bit range is now read, and two encodings in one table are
recorded as two families.

### The register classes are not a constraint, which was the surprise

`scripts/prm_register_classes.py` extracts Table 2-1 (pages 53–55): **20
classes with their membership**. Two findings, and the second closes a line of
attack rather than opening one.

**The PRM publishes no bit encodings.** Table 2-1 gives membership by *name* —
`RREG = r0 - r15` — and nothing in the document maps a register name to the
code that selects it. Those codes belong to the assembler, so cardinality is
all that is recoverable.

**And cardinality rejects nothing. 15 of the 20 classes exactly fill their
field width:**

```
B1REG B2REG CDREG FREG I1REG I2REG M1REG M2REG
MRXFBREG MSXFBREG RFREG RFREGDBL RREG SREG UREGDBL
```

`RREG` is 16 registers in a 4-bit field, `RFREG` 32 in 5 bits, `I1REG` 8 in 3.
A class that fills its field cannot reject a value, so it constrains nothing —
which is exactly what a well-designed ISA looks like from the inside.

`UREG` is worse than its count suggests: the PRM says it *"includes almost all
processor core registers"*, and that the data and system registers are
subgroups of it, so the 7-bit `ureg` fields are close to fully populated. Only
`SYSREG` (18 of 32) and the `UREGXDAG` variants (6 of 8) reject anything, and
they appear in few forms.

**So the largest untouched constraint turns out not to be one.** With the
compute-field result — which also failed to lengthen the decode run — that is
two of the three obvious candidates eliminated by measurement rather than
argument. What remains unexamined is the *syntax* tables, which is where the
265 unnamed bits' meanings live.

## 7. Reproducing

```sh
python scripts/prm_opcode_figures.py <prm.pdf> --pages 300-440 --check
python scripts/prm_visa_tables.py    <prm.pdf> -o visa.json --subsume
python scripts/prm_compute_tables.py <prm.pdf> -o compute.json
dnfw extract <image.syx> -o out/
python scripts/sharc_visa_coverage.py visa.json out/section_7_blob.aplib.bin
```

The PDF is not committed — it is Analog Devices'. `docs/data/` carries the
extraction.

## 7. A revision warning worth passing on

digikit's cited copy is **771 pages** and carries the instruction set in
**chapter 12**; ours is Rev 1.5 at **798 pages**, chapters 14–15. Her own notes
say the source *"[has] not been checksummed against Analog Devices' own
copies"*, and it came from a third-party mirror.

**Tables extracted from different revisions are not comparable**, and a
disagreement between them is not evidence that either is wrong. Checking this
before transcribing is what stopped 25 figures going into an ambiguous diff.

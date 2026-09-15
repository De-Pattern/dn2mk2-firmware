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

## 2. Coverage of the extraction: 100%

| | |
|---|---|
| figures found (pages 308–425) | **54** |
| figures left unnamed | **0** |
| rows failing the descending-bit self-check | **0 of 137** |
| declared instruction families | **44** |
| families with no figure | **0** |

Widths: **16-bit ×6, 32-bit ×14, 48-bit ×34.** VISA is genuinely variable, and
treating every figure as 48-bit — slicing "the top 8 bits" at 47..40 — is
meaningless for a third of them.

The self-check is what makes that "0" worth anything: bit labels are read from
the page rather than assumed, so a mis-mapped row shows as a sequence that is
not a clean descending run. Run over the entire 798-page document it flags
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

## 5. What is not done

**Field extents.** The figures' brackets bind cell ranges to names
(`srcureghigh[4:0]`, `cond[4:0]`). We extract the fixed-bit masks but not the
field positions, and **branch alignment cannot be computed without them** —
there is no displacement field to follow. This is the next step and it is the
gate on producing a number comparable to hers.

A shortcut was tested and does not hold on its own: each label declares its own
width, so the widths might tile the unshaded cells exactly. They do for 12 of
46 figures. The rest disagree, partly because several pages carry two figures
and the test summed them together, partly for reasons not yet chased.

**MULOP and SHIFTOP.** ALUOP extracts cleanly; the other two tables are not
being found by the table finder yet. `scripts/prm_compute_tables.py` reports
what it has rather than implying completeness.

## 6. Reproducing

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

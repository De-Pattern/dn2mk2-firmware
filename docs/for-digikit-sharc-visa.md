# Notes for the digikit SHARC+ VISA work — 2026-09-15

> **[PARTLY SUPERSEDED, same day.]** The author pointed us at her
> `machine-engine-link` branch, which is well ahead of what `main` showed.
> §1 and §3 below are overtaken; §4 is independently confirmed by her; the rest
> stands. See `docs/sharc-visa-extraction.md` §8 for what her branch settles,
> and what it points at that we do not have.

Written to hand over, so it leads with the things that could change what you do
next rather than with what we did. We worked the same PRM independently for a
day, on the owner's suggestion, because your largest bug so far was a misread
figure and a second reader is the cheapest check on that class of error.

Everything below is measured against **SHARC+ Core Programming Reference, Part
Number 82-100131-01, Revision 1.5**, 798 pages,
`sha256 a3edf83beb75b44a77f8366cf54c0353083ab49a1c69d8179d2b727ba7ba1470`.

---

## 1. You are probably on a different revision, and it matters first

`docs/refs/sharc-plus-isa.md` records your copy as **771 pages**, from
`docs.ampnuts.ru`, with the instruction set beginning at printed page **12-2**,
and notes it has *"not been checksummed against Analog Devices' own copies"*.

Ours is **798 pages** with the instruction set in **chapters 14–15**. So
chapters were inserted ahead of it — that is a substantive revision, not a
reprint.

**Tables extracted from different revisions are not comparable, and a
disagreement between them is not evidence that either is wrong.** If you want
to diff against anything here, the hash above is what to match. We could not
find your exact file to diff the revisions against each other.

## 2. The figures do not need reading at 400 DPI

Your handover records losing 88–93% of walks to *"Type5b_move, eight gray cells
recorded as none"*, and the next commit is *"Read the Type5b_move figure again,
at 400 DPI this time."*

**There is nothing to read.** Across the instruction chapter — pages 300–420,
121 pages — the PDF contains:

```
pages carrying a raster image : 0
raster images in total        : 0
```

Every bit cell is a **vector rectangle with a fill colour** in the content
stream, and every bit number and value is real text at a known position. The
shading is data. `scripts/prm_opcode_figures.py` in our repo reads it with no
OCR and no vision model, and a self-check that a mis-mapped row cannot survive
(bit labels are read from the page, so a wrong mapping shows as a sequence that
is not a clean descending run — 0 failures over 137 rows).

### Why that figure specifically invites the error

**A shaded run is ONE rectangle spanning several cells, not one per cell.** The
seven shaded cells at bits 22–16 of Type5b_move are a single 63-point box:

```
x0=316.50  w=63.00  h=9.00  fill=(0.8235, 0.8235, 0.8235)
```

Count rectangles instead of cells and you get **2 where the answer is 8**. That
is the "recorded as none" failure exactly, and it is structural — not
carelessness. Converting each rectangle's width back to a cell count
(`width / 9`) makes it unreadable any other way.

### Our independent read of Type5b_move

```
bit   47 46 45 44 43 42 41 40 39 38 37 36 35 34 33 32
value  0  1  1  1  0  0  0  0  0  0  0  0  0  0  0  0
fixed  #  #  #  #  #  .  .  .  .  .  .  .  .  .  .  .    5 cells

bit   31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16
fixed  .  #  .  .  .  .  .  .  .  #  #  #  #  #  #  #    8 cells
```

**The eight are bit 30 and bits 22–16.** Fields: `srcureghigh[4:0]` = 42..38,
`cond[4:0]` = 37..33, `srcureglow[1:1]` = 32, `srcureglow[0:0]` = 31,
`dstureg[6:0]` = 29..23.

*Caveat on independence:* we knew the number **eight** from your handover before
counting, so the count is not a blind confirmation. The positions are ours.

## 3. Three structural things that bite a decoder

### Decode order is load-bearing — 9 subsumption pairs

A pattern with few fixed bits **subsumes** stricter patterns nested inside its
space. Tested first, the loose one wins and swallows the strict one's
instructions; because the forms differ in length, the walk desynchronises from
there. Same failure class as your Type5b bug, generalised.

Same-mode pairs, loose → strict:

| loose | fixed bits | swallows | fixed bits |
|---|---|---|---|
| `Type1a` | 3 | `Type2a` | 20 |
| `Type4a` | 4 | `Type4d` | 8 |
| `Type6a_mem` | 4 | `Type6a_nomem` | 16 |
| `Type19a` | 6 | `Type18a`, `Type20a` | 9, 9 |
| `Type14d` | 7 | `Type25a_rframe` | 24, 16 |
| `Type25a_rframe` 32-bit | 16 | `Type25a_rframe` 48-bit | 24 |

**Every subsumed pattern must be tried before the pattern that subsumes it.**
Worth checking where these sit in your dispatch order.

### ISA and VISA must be partitioned before any prefix analysis

Of five apparent top-7 length ambiguities, **four dissolve** once modes are
separated — they are `a`/`b` pairs, the same instruction in both encodings,
which never compete for the same bytes (`7a = ISA/VISA`, `7b = VISA`). Measuring
prefixes across both at once measures nothing.

### The PRM contradicts itself at page 419

The figure is captioned **`Type25a_rframe`**; its section heading reads
**`Type 25c VISA (rframe)`**. Anything keyed on one disagrees with anything
keyed on the other.

## 4. The register classes are not a constraint — this may save you time

We extracted Table 2-1 (pages 53–55), 20 classes with membership, expecting it
to be the big remaining constraint. It is not.

**The PRM publishes no bit encodings.** Table 2-1 gives membership by *name*
(`RREG = r0 - r15`) and nothing in the document maps a register name to the
code that selects it. Those codes are the assembler's.

**And cardinality rejects nothing — 15 of the 20 classes exactly fill their
field width:**

```
B1REG B2REG CDREG FREG I1REG I2REG M1REG M2REG
MRXFBREG MSXFBREG RFREG RFREGDBL RREG SREG UREGDBL
```

`RREG` is 16 in a 4-bit field, `RFREG` 32 in 5 bits, `I1REG` 8 in 3. A class
that fills its field cannot reject a value. `UREG` is worse than its count
suggests — the PRM says it *"includes almost all processor core registers"* and
that data and system registers are subgroups of it — so 7-bit `ureg` fields are
close to fully populated. Only `SYSREG` (18 of 32) and the `UREGXDAG` variants
(6 of 8) reject anything, and they appear in few forms.

## 5. The compute tables, with the notation traps

| family | field | patterns | values admitted |
|---|---|---|---|
| ALUOP | bits 19–12 | 61 | 61 / 256 — 23.8% |
| MULOP | bits 19–12 | 25 | 206 / 256 — 80.5% |
| SHIFTOP | bits 19–12 | 25 | 25 / 256 — 9.8% |
| SHIFTIMM | bits 21–16 | 18 | 18 / 64 — 28.1% |
| DUALADDSUB | bits 19–16 | 2 | 2 / 16 — 12.5% |

Three notation traps cost us time each:

- **The cells are masked patterns, not values**, written differently per family:
  `ALUOP 00011000`, `MULOP 0000 F00x`, `SHIFTOP 11 0 0 __ __`. Letters and
  underscores are variable bits. A `^[01]+$` filter accepts ALUOP and silently
  discards the rest, which reads as those tables being absent.
- **Table 18-9 carries two encodings side by side**, headed `shiftimm (bits
  21-16)` and `shiftop (bits 19-12)`. Matching the literal word `opcode` finds
  neither.
- **The dash in "bits 19−12" is U+2212 MINUS SIGN**, not a hyphen or en dash.

## 6. Our negative results, which support your choice of metric

We built a decoder from the figures and it does not work. The measurements may
still be useful to you, because they say *what kind* of thing is missing.

**Match rate is an entropy measurement, not coverage:**

| input | match rate |
|---|---|
| SHARC code `0x20000000` | 63.66% |
| SHARC code `0x283825c4` | 63.32% |
| **ColdFire MAIN OS — a different architecture entirely** | **53.07%** |
| **random bytes** | **46.65%** |
| all-zero bytes | 99.99% |

53% on an instruction set it has nothing to do with. This is why **your branch
alignment metric is the right one** — 92–99% against 0.4–3.6% is a ~30×
separation, where match rate gives 1.2×. We reached the same conclusion by
walking into the trap you avoided.

**Median decode run is 1**, from every offset and under every word order
(high-first/LE marginally best at mean 3.5). Yours is 632 after the Type5b fix.

**And the patterns carry no positional information at all**, which we think is
the sharpest statement of the problem:

| region | stride 2 | stride 4 | stride 6 | stride 8 |
|---|---|---|---|---|
| `0x283825c4` | 54.1% | 55.4% | 54.1% | 54.4% |
| `0x20000000` | 50.1% | 53.3% | 53.7% | 53.7% |

At a 6-byte stride, across all three phases: **54.1%, 54.0%, 54.5%**. A real
instruction stream has a preferred phase; ours has none.

**Two candidate constraints eliminated by measurement:** validating the compute
field against ALUOP and MULOP leaves the median run at 1 and *lowers* the mean;
the register classes reject nothing (§4). What we have not examined is the
**syntax tables**, which is where the 265 bits the figures never name get their
meaning.

## 7. Two things that agreed with you independently

- **Your address rule.** You have `byte = 2 × short_word + 0x28000000`; our
  `docs/sharc-code-map.md` has `load = exec × 2 + 0x28000000`, derived
  separately. The boot stream's declared entry `exec 0x001c12e2` maps to `load
  0x283825c4`, which is exactly the base of a code region — predicted, then
  confirmed.
- **Recovery needs a physical MIDI DIN interface, not USB.** We learned that as
  an ~80% flash stall we first blamed on our own image.

## 8. Where our scripts are

<https://github.com/angellinares/dn2_firmware_explore>, AGPL-3.0-or-later.

```
scripts/prm_opcode_figures.py     figures -> text, with the self-check
scripts/prm_visa_tables.py        54 forms: names, modes, widths, masks, field extents
scripts/prm_compute_tables.py     ALUOP / MULOP / SHIFTOP / SHIFTIMM / DUALADDSUB
scripts/prm_register_classes.py   Table 2-1
scripts/prm_label_ceiling.py      how much the figures can give at all
scripts/sharc_seeded_walk.py      recursive descent from the entry point
scripts/sharc_branch_alignment.py your metric, with a noise control
docs/data/*.json                  the extractions
```

Field extents come from the bracket geometry: **bracket endpoints sit on cell
centres**, so a cell index is exactly `(x − (frame.x0 + 4.5)) / 9`. Two shapes
to handle — a one-bit field is an L-leader where *which* end sits on the grid
depends on which side its label is, and some figures name individual bits with
bare mnemonics (`lldi`, `lpu`) rather than `name[hi:lo]`.

Bit-level accounting reaches **87.82%**, which is **100% of what the figures
contain** — the other 265 bits are not named in them at all.

---

Happy to run anything here against a different revision, or to hand over the
JSON in whatever shape is useful. The parts we would most want checked are the
Type5b positions in §2 and the subsumption list in §3, since those are where an
independent read is worth the most.

# Cross-checking Rev 1.5 against the classic SHARC PGR

**2026-09-15.** Every instruction-opcode page of the classic manual read and
compared against our Rev 1.5 extraction. This is the check that a single
document cannot perform on itself, and the reason it matters is in digikit's
own notes: *"printed digits in gray cells are not always right -- several
figures keep a template's default digits or copy another figure."*

| | |
|---|---|
| second source | **SHARC Processor Programming Reference, Rev 2.4, April 2013** |
| part number | 82-000500-01, 694 pages |
| sha256 | `0b40637d05c7f33bc8e39235ee8a9d2c734b12c0372aff1eeac56a7554895869` |
| covers | ADSP-2136x / 2137x / 214xx — the **classic** core, not SHARC+ |
| opcode chapter | 10, "Instruction Set Opcodes", **pages 447–471** |
| pages compared | **25 of 25** |

## Why this was read as images

Our vector extractor returns **zero rows** on this manual, and that says the
conventions differ rather than that the figures are absent:

| | Rev 1.5 | classic PGR |
|---|---|---|
| cell pitch | 9 pt | ~12.5 pt |
| shading | grey `0.8235` fill per run | none — digits printed instead |
| grid | filled cells, zero-width dividers | stroked 0.5 pt lines |
| fixed bits | shaded cells | **printed digits** |

Five attempts at a text/geometry reader failed, each on the same symptom. The
rule they were all missing is visible in one glance at a render: **a digit run
is centred in its FIELD, not placed per cell** — `001` is a single centred
label spanning bits 47..45. Rendering at 600 DPI and reading answered in
minutes what the coordinate work had not in an hour.

**So: vector where it is proven and self-checking, raster where it is not.**
Rev 1.5 stays on the vector path — 54/54 figures, zero self-check failures.
This manual is read as images.

## Result: the `a`-forms agree, everywhere

Every `a`-form prefix in the classic matches our Rev 1.5 extraction:

| type | classic fixed bits | ours | |
|---|---|---|---|
| 1a | 47..45 `001` | `001xxxxx` | ✅ |
| 2c | 47..44 `1100` | `1100` | ✅ |
| 3a / 3b | 47..45 `010` | `010xxxxx` | ✅ |
| 4a / 4b | 47..45 `011`, 44 `0` | `0110xxxx` | ✅ |
| 5a move | 47..43 `01110` | `01110xxx` | ✅ |
| 5a swap | 47..43 `01111` | `011110xx` | ✅ |
| 6a | 47..44 `1000` | `1000xxxx` | ✅ |
| 7a / 7b | 47..40 `00000100` | `00000100` | ✅ |
| 8a direct | 47..40 `00000110` | `0000011x` | ✅ |
| 8a PC-rel | 47..40 `00000111` | *same form* | ✅ |
| 9a indirect | 47..40 `00001000` | `0000100x` | ✅ |
| 9a PC-rel | 47..40 `00001001` | *same form* | ✅ |
| 10a indirect | 47..45 `110` | `11xxxxxx` | ✅ |
| 10a PC-rel | 47..45 `111` | *same form* | ✅ |
| 11a subroutine | 47..40 `00001010` | `0000101x` | ✅ |
| 11a interrupt | 47..40 `00001011` | *same form* | ✅ |
| 12a imm | 47..40 `00001100` | `00001100` | ✅ |
| 12a ureg | 47..40 `00001101`, 39 `0` | `00001101` | ✅ |
| 13a | 47..40 `00001110` | `00001110` | ✅ |
| 14a | 47..42 `000100` | `000100xx` | ✅ |
| 15a | 47..45 `101` | `101xxxxx` | ✅ |
| 16a | 47..44 `1001` | `1001xxxx` | ✅ |
| 17a | 47..40 `00001111`, 39 `0` | `00001111` | ✅ |
| 18a | 47..40 `00010100` | `00010100` | ✅ |
| 19a | 47..40 `00010110`, 39 `0` | `000101xx` | ✅ |
| 20a | 47..40 `00010111` | `00010111` | ✅ |
| 21a | 47..40 `00000000`, 39 `0` | `00000000` | ✅ |
| 25a direct | 47..24, 24 bits fixed | **24 fixed** | ✅ |
| 25a PC-rel | as direct, 39..36 `0100` | **24 fixed** | ✅ |
| 25c | 47..32 `0001100100000001` | **16 fixed** | ✅ |

**And a subtlety the cross-check confirms rather than contradicts.** Where the
classic splits a type into variants — direct vs PC-relative, subroutine vs
interrupt — the discriminating bit is *bit 40* (types 8a, 9a, 11a), *bit 45*
(10a) or *bit 39* (17a/17b). Our merged forms correctly leave exactly those
bits **unfixed**. That is not a gap in our extraction; it is the right answer,
and only a second source could show it.

## Three divergences

### 1. Type 2b — digikit's documented conflict, independently reproduced

| source | bits 47..39 |
|---|---|
| Rev 1.5 (ours, and hers) | `110000000` |
| **classic PGR (this reading)** | **`000000011`** |

Her `SOURCES.md` records resolving exactly this: the PRM's `0xc00000000000`
was kept because the PGR alternative `0x000000011` *"caused width collisions"*
with the 48-bit branch family. **Our independent raster read of the classic
gives `000000011` — her documented alternative, digit for digit.** Three
readings, one conclusion: the conflict is real and her resolution stands.

### 2. Type 2a — a generational re-encoding, and our read is right

Classic gives **8** fixed bits (47..45 `000`, 44..40 `00001`); our Rev 1.5
extraction claims **20**, spanning 47..38 *and* 32..23.

> **[CORRECTED — this was first written up as "suspected fault in our caption
> grouping".]** It is not. Rendering p312 shows the figure exactly as extracted:
> grey at 47..38 and 32 in the first row, 31..23 in the second, the third row
> entirely unshaded. **Rev 1.5 genuinely puts Type 2a at `0010000000`** — nested
> inside Type 1a's `001` space, which is one of the subsumption pairs already
> recorded — while the classic has it at `000 00001`, disjoint from Type 1a.
> The encoding was reorganised between cores. Nothing to fix.

### 3. Type 25a RFRAME — also not a fault

The classic shows **all 48 bits fixed**; we extract **24**.

> **[CORRECTED.]** Our 24 grey bits are right. The classic's RFRAME is a
> fully-specified 48-bit instruction and Rev 1.5's is a different encoding.
>
> Rendering it did find something, though, and in colour: **bits 3..0 are
> yellow, not white.** That is the third cell colour — `(0.95, 0.80, 0.19)`,
> *unused or outside the field being shown* — which our reader had never looked
> for, counting every such cell as an unnamed free bit. Handling it took bit
> accounting from **87.82% to 96.69%** and cut forms with unexplained bits from
> 17 to 6.
>
> So the earlier "87.82%, which is 100% of what the figures contain" was 100%
> of what our reader could *see*. A ceiling measured by an instrument blind to
> one of three cell colours is not a property of the document.

## A generation difference, not an error

In the classic, a `b`-form is a **48-bit** encoding carrying `0111111` at bits
22..16 as its VISA marker — seen on 1b, 3b, 4b, 5b, 7b, 9b. In SHARC+ the
`b`-forms are genuinely **32-bit**. So their low-bit values are not comparable
across the two manuals, and a diff that treats them as such manufactures
conflicts. Recorded because it would be easy to report as a finding.

## What this cost and what it bought

Twenty-five pages, thirteen composite renders, read directly. It found **one
confirmed inter-document conflict** (independently corroborating digikit's),
**zero errors in Rev 1.5's figures** among the `a`-forms, and — by way of two
divergences that turned out to be generational rather than faults — **the
yellow "unused" cell colour our extractor had never looked for**, worth nearly
nine points of bit accounting.

Both apparent faults were in the comparison, not in either document. Chasing
them anyway is what surfaced the colour.

That last result is worth stating plainly: on everything comparable, Rev 1.5's
opcode figures are correct.

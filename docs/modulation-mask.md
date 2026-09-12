# The modulation mask: the firmware is already dimensioned for four modulators

Every parameter record carries a **four-bit modulator mask**, and each LFO's
destination list is built by filtering on it. Three of the four bits are spent
on LFO1, LFO2 and LFO3. **The fourth bit is set on all 189 modulatable
parameters and on all three LFOs' own parameters, and no existing filter
selects on it alone.**

This is the strongest evidence yet that a fourth LFO is the shape Elektron left
room for, and it is independent of — and agrees with — DNX's finding that the
stored sound format reserves a fourth slot in its LFO grid. It was read from the
bytes of both builds and from the code that consumes them.

It also does **not** find the modulation tick. Everything here is the
*destination and parameter* layer. See "What this does not establish".

## The mask field

This uses the anchor already in `docs/version-anchors.md` — the **parameter
record base**, the address the accessors `lea`, with `record[id] = base + id*60`:

| | 1.10E | 1.11 |
|---|---|---|
| parameter record base | `0x401e29a0` | `0x401f7f94` |

### The full record layout

`record(id) = base + id*60` — the record starts **at** the base. Fifteen 4-byte
fields, closing the 60 bytes exactly with nothing left over:

| Offset | Holds | Example (id 75, LFO1 `SPD`) |
|---|---|---|
| `+0x00` | **page id** (`paramPageID`) | `0x1a` = LFO1 |
| `+0x04` | parameter id within the page | `1` |
| `+0x08` | zero in every record seen | `0` |
| `+0x0c` | maximum value (`<< 8`) | `0x7ffe` |
| `+0x10` | default value (`<< 8`) | `0x7000` |
| `+0x14` | flag — set on bipolar parameters | `1` |
| `+0x18` | MIDI controller; `0xffffffff` when unassigned | `0x66ffff` |
| `+0x1c` | NRPN; `0xffffffff` when unassigned | `0xaa` |
| `+0x20` | a dense ordinal — **every** record has one | `0x4f` |
| **`+0x24`** | **the modulation mask** | `0xe00` |
| `+0x28` | long-name string pointer | `Speed` |
| `+0x2c` | page-label string pointer | `LFO1` |
| `+0x30` | short-name string pointer — what `version-anchors.md` indexes on | `SPD` |
| `+0x34` | **value formatter** — renders the value for display. The dispatch at `0x40035f32` (1.10E) tests it for null, `jmp`s through it, and prints `ERR` when it is null. Each one ends in the sprintf at `0x40000e82`; LFO `MULT`'s, for instance, computes `1 << v` and appends `k` above 512 | `0x400e44a4` |
| `+0x38` | unit-suffix string — **empty in all 320 records** | `""` |

Confirmed by indexing both images: ids **75–84, 85–94, 95–104** are the LFO1,
LFO2 and LFO3 blocks, and ids **6** and **10** resolve to `Machine Type` and
`Track Level` — the two live head entries `docs/parameter-table-consumer.md`
already named, from a derivation that did not use them.

### How to know an anchor is right

**A wrong anchor still produces plausible strings.** The table is dense and
every record holds four pointers, so "some record says `LFO1`" proves nothing.
Two probes do prove something, and both are in `_check_geometry` in
`scripts/build_lfo4_test.py`:

1. **A page boundary.** Id 84 is the last LFO1 record and id 85 the first LFO2
   one. An off-by-one-record anchor shifts exactly here, and nowhere a casual
   look would notice.
2. **The three LFO blocks are the same ten parameters**, so their `+0x34`
   formatter sequences must be *identical*. This is the probe that settled the
   record boundary: with the start taken 8 bytes low, LFO1's first slot picked
   up id 74's handler and LFO1 disagreed with LFO2 and LFO3. With the start at
   the base, all three sequences match exactly.

Two separate anchor errors were found and fixed this way on 2026-09-12; both are
recorded in `docs/lfo4-feasibility.md`, "The Stage 1 corrections".

## What the mask contains, measured

Histogram of `record+0x24` over all 271 named records. **Identical in 1.10E and
1.11, value for value and count for count**:

| Mask | Records | Which |
|---|---|---|
| `0x1e00` | 189 | every ordinary modulatable parameter — SYN, Filter, Amp, FX, Delay, Reverb, Ext-in, Src, CC |
| `0x0e00` | 8 | LFO1's own parameters |
| `0x0600` | 8 | LFO2's own parameters |
| `0x0200` | 8 | LFO3's own parameters |
| `0x0` | 55 | not modulatable at all — Master, Chorus, Retrig, Euclidean, Portamento, and each LFO's `SLEW` |
| `0x40000` | 1 | LFO1's `DEST` |
| `0x20000` | 1 | LFO2's `DEST` |
| `0x10000` | 1 | LFO3's `DEST` |

So the mask occupies **bits 9–12** (`0x200`, `0x400`, `0x800`, `0x1000`), and
each LFO's `DEST` parameter carries a unique identifying bit in bits 16–18.

## How the destination list is built

Four byte-identical sites do this, at `0x400397f2`, `0x40039ad4`, `0x40039cf6`
and `0x40039ef4` on 1.11 (`0x4003908a`, `0x4003936c`, `0x4003958e`, `0x4003978c`
on 1.10E — a uniform `+0x768` shift, so the code is structurally unchanged
between builds). The idiom:

```
4003 9ac2:  movel %d0,%d1
4003 9ac4:  lsll #2,%d1              ; d1 = id*4
4003 9ac6:  lsll #6,%d0              ; d0 = id*64
4003 9ac8:  lea 0x401f7f94,%a2
4003 9ace:  subl %d1,%d0             ; d0 = id*60
4003 9ad0:  movel %a2@(24,%d0:l),%d1 ; d1 = rec[id].mask   <- 24 is HEX: 0x24
4003 9ad4:  movel #7680,%d0          ; 0x1e00
4003 9ada:  btst #18,%d1             ; LFO1's DEST?
4003 9ade:  bnes done
4003 9ae0:  movew #3584,%d0          ; 0x0e00
4003 9ae4:  btst #17,%d1             ; LFO2's DEST?
4003 9ae8:  bnes done
4003 9aea:  movew #1536,%d0          ; 0x0600
4003 9aee:  btst #16,%d1             ; LFO3's DEST?
4003 9af2:  bnes done
4003 9af4:  clrl %d0                 ; not a DEST parameter -> no list
done:
```

Note the radix trap again: `%a2@(24,%d0:l)` is indexed mode, so `24` is **hex**
`0x24`, not decimal. `docs/mainos-image.md` records why this matters.

The resulting value is the **filter**, passed to the list builder
`FUN_4003951e`, whose decompiled loop is:

```c
do {
    slot = (**(code **)(*param_1 + 0x50))(param_1, i);      /* parameter at slot i */
    if (slot != 0 && (mask = FUN_400dc30e(slot), (filter & ~mask) == 0))
        push_back(destinations, &slot);
    i++;
} while (i != 0x65);                                        /* 101 slots */
```

`(filter & ~mask) == 0` is a **subset test**: a parameter joins the list only if
its mask contains *every* bit of the filter.

### The filter is the modulator's identity, not just a bitmask

At `0x40106a08` the same three values are mapped straight back to names for
display:

| Filter | Name string |
|---|---|
| `0x1e00` | **`MOD1`** |
| `0x0e00` | **`MOD2`** |
| `0x0600` | **`MOD3`** |

So the filter value *is* how the firmware refers to a modulator — and those are
the `[MOD]` page names the instrument shows.

### Working the rule through

| Filter | Admits |
|---|---|
| `MOD1` = `0x1e00` | only `0x1e00` records — ordinary parameters |
| `MOD2` = `0x0e00` | ordinary + **LFO1's** parameters |
| `MOD3` = `0x0600` | ordinary + LFO1's + **LFO2's** parameters |

Which is exactly the Digitone's documented behaviour: a higher-numbered LFO may
modulate a lower-numbered one, never the reverse, and never itself.

## The fourth bit

The filter series drops one high bit per LFO: `0x1e00`, `0x0e00`, `0x0600`. The
next term is **`0x0200`**, and it is the only filter value left. Its admission
set is:

| Record class | Mask | `0x200 ⊆ mask`? |
|---|---|---|
| ordinary parameters | `0x1e00` | **yes** |
| LFO1's parameters | `0x0e00` | **yes** |
| LFO2's parameters | `0x0600` | **yes** |
| LFO3's parameters | `0x0200` | **yes** |
| unmodulatable | `0x0` | no |

A modulator filtering on `0x0200` would see every modulatable parameter **plus
all three LFOs' own parameters, and not itself** — precisely and only what a
fourth LFO sitting at the end of the chain needs.

The practical consequence is large: **no parameter-record edits are needed to
make the existing 189 parameters LFO4 destinations.** The bit is already set on
every one of them, in both shipped builds. That removes the single most
error-prone part of the change set sketched in `docs/lfo4-feasibility.md`.

## What a fourth modulator would still require

Honest accounting, all of it still to do:

1. **A fourth `DEST` bit.** No record carries `0x8000` (bit 15) or any other
   fourth `DEST` marker, because there is no LFO4 page. LFO4's `DEST` record
   needs one, and the four filter sites need a fourth `btst`/`movew #0x200`
   pair. Each site is a straight insertion — the existing tests are already a
   chain, so a cave is only needed if the inserted code does not fit.
2. **Ten parameter ids.** LFO ids run 75–104 with no slack; id 105 is
   unallocated and Chorus resumes at 106. So there is **no reserved ten-id block
   for LFO4** — the `ERR` filler slots at the head of the table remain the plan,
   per `docs/lfo4-feasibility.md`.
3. **A `paramPageID` value.** Pages run `0x00`..`0x1e` — `0x1a`=LFO1,
   `0x1b`=LFO2, `0x1c`=LFO3, `0x1d`=Retrig, and **`0x1e` is already taken** by
   the single record id 19, `None`/`---`, the "no destination" entry (which
   carries mask `0x1e00`, so it appears in every LFO's list — that is the
   `NONE` row at the top of a `DEST` menu). So a fourth LFO page needs id
   `0x1f` or higher, and anything sized by the page count has to be found and
   grown.
4. **The engine.** Untouched by any of this.

## What this does not establish

- **Nothing about the modulation tick.** This is the destination/parameter/UI
  layer. The code that advances an LFO's phase and applies it has still not been
  found; `docs/engine-state.md` holds that hunt.
- **Nothing about the runtime sound object.** Whether a fourth LFO's phase and
  output have somewhere to live in the 960-byte runtime preset entry is open.
- **`0x200` is inferred as MOD4, not observed.** No code selects on `0x0200`
  today. The inference rests on the arithmetic series of the filters, the
  four-bit width of the field, the bit being set on all 189 modulatable records,
  and the admission set coming out exactly right. That is strong, and it is
  still an inference — the sort that `docs/engine-state.md` records a retraction
  for. It gets confirmed the day a patched build shows a parameter in a MOD4
  destination list, not before.

## Method note

The table was found by scanning the image for 60-byte-strided records with three
valid string pointers, not by following code — Ghidra builds no references into
it, because every access computes `base + id*60` at runtime. `FindDataRefs.java`
returns zero hits here, which is a property of the reference model and not
evidence of absence. The full objdump of the image is what found the four filter
sites, by grepping for the mask constant.

# The LFO parameter tables

Measured from Digitone II 1.10E and Digitone 1.42A MAIN OS on 2026-09-08.
This is the Phase 2 starting point: it answers whether the LFO count is a
constant the code reads or something structural.

**It is a table.** Each LFO is a block of records in a flat array, and the
blocks are identical in shape.

> **Revised 2026-09-08, later the same day.** The first version of this
> document described only the three LFO blocks and concluded that "LFO3 ends at
> id 24 and Chorus begins at 25", so a fourth block could not simply continue
> the sequence. Walking the whole array showed that framing was wrong. The
> array is 320 records covering the entire instrument, and **the parameter id
> is not unique across it** — 68 of the 100 ids in use are claimed by more than
> one group. Chorus's 25 is not the successor of LFO3's 24; the two are not in
> the same sequence at all. The constraint on a fourth LFO is real, but it is a
> different constraint, and it is in "What this means for a fourth LFO" below.

## The record

One uniform record per (parameter, presentation), contiguous, no header:

| | DN2 1.10E | DN1 1.42A |
|---|---|---|
| record size | **60 bytes** (15 words) | **52 bytes** (13 words) |
| name pointers | last three words | last three words |

The last three words are `[long name][page label][short name]` — for example
`"Speed"`, `"LFO1"`, `"SPD"`. Everything before them is numeric. So

```
record_start = (address of the page-label pointer) - (record size - 8)
```

**The alignment was wrong twice before it was right**, and both wrong versions
looked plausible, so here is how it was settled rather than assumed. Two
independent checks agree only on this one:

- `Amp / RSET` reads group **11**, the same group as every other Amp parameter.
  The off-by-one alignments put it in the LFO1 group, which is impossible.
- `SPH` and `SLEW` come out sharing a parameter id — which is exactly what the
  instrument does, see below. No other alignment produces that.

For DN2, the fields used below are word 2 (group), word 3 (parameter id), word
0 (a handler function pointer), word 5 (range), word 6 (default), word 9 (a
controller number, `0xffffffff` when unassigned) and word 10 (NRPN). **The
remaining words are not yet identified**, and the DN1 record's numeric layout
is different and has not been worked out at all — only its name pointers were
needed here.

## DN2: one table, 320 records, at `0x401e29d4`

`0x401e29d4 .. 0x401e74d4` — 320 records, 19,200 bytes, covering the whole
instrument: synth pages, LFOs, effects, mixer, MIDI-track pages and trig
parameters, in one flat array.

Scanning all of MAIN OS for runs of records of this shape finds exactly **two**
such tables. Plain pointer arrays have to be filtered out first: they match a
"three string pointers at +48" test at *every* 4-byte offset, whereas a real
record table matches at one offset only.

| Address | Records | What it is |
|---|---|---|
| `0x401e29d4` | 320 | the Digitone II parameter set |
| `0x401bae00` | 183 | the Digitone 1 parameter set — see the warning below |

**The low edge is uncertain.** The 60-byte stride continues below
`0x401e29d4`, but the record that would begin at `0x401e2998` holds a small
integer where every other record holds a handler pointer, and the bytes at
`0x401e29a0` are the target of a dozen `lea` instructions from elsewhere — so
that region is more likely a separate object the table happens to abut.
`0x401e29d4` is where the record shape stops being ambiguous, and every count
here is measured from there.

The first 18 records carry `0xffffffff` in **both** the group and the id field:
`Error` (repeatedly), `Machine Type`, `Solo`, `Mute`, `Pattern Mute`,
`Track Level`, `Active Track`, `Global Mix Mode`. They are not addressable by
(group, id) at all, so something reaches them **by array index**. An `Error`
record at the head is the shape of an enum whose zero value is the safe
default.

## The parameter id is not unique

This is the finding that matters, and it is a measurement rather than a reading
of the layout.

| Group | Recs | Ids | Pages |
|---|---|---|---|
| 0 | 38 | 25–33, 35–48, 50–64 | SYN |
| 1 | 25 | 25–49 | SYN |
| 2 | 30 | 25–54 | SYN |
| 3 | 8 | 25–32 | SYN |
| 5–10 | 3 each | 66–68 | Filter |
| 11 | 11 | 80–85, 89–92 | Amp |
| 13 | 11 | 69–79 | Filter |
| 14 | 2 | 93–94 | Portamento |
| 15 | 8 | 86–88, 95–99 | FX |
| 16 | 8 | 25–31 | Chorus |
| 17 | 9 | 41–48 | Reverb |
| 18 | 10 | 32–40 | Delay |
| 19 | 2 | 68–69 | Master |
| 20 | 9 | 60–67 | Master |
| 21 | 17 | 49–59 | Ext-in |
| 22 | 4 | 8–11 | *(none)* |
| 23 | 8 | 25–32 | Src |
| 24 | 16 | 33–48 | CC |
| 25 | 16 | 49–64 | *(none)* |
| **26** | **10** | **1–8** | **LFO1** |
| **27** | **10** | **9–16** | **LFO2** |
| **28** | **10** | **17–24** | **LFO3** |
| 29 | 22 | 0–5, 7, 12–25 | Retrig, Euclidean |
| 30 | 1 | 0 | *(none)* |
| — | 18 | *(none)* | *(none)* |

**68 of the 100 ids in use are claimed by more than one group.** Groups 0, 1, 2
and 3 all begin at 25. So does Chorus. So does Src. The id alone identifies
nothing: `(group, id)` is the key, or the id is scoped by something the record
does not carry.

**Groups 4, 12 and 31-and-up are unused.** A fourth LFO block needs a new group
number, and those are the free ones — **not 29**, which an earlier draft of this
document suggested and which is already Retrig and Euclidean.

### How the groups appear to cluster — INFERRED, not measured

The groups fall into sets whose ids do not collide *within* a set. This
hypothesis fits every row above. It has **not** been confirmed against code,
and the next section says what would confirm it.

| Cluster | Groups | Ids | Reading |
|---|---|---|---|
| A | 26, 27, 28, 0–3, 5–10, 13, 11, 15, 14 | 1–64, 66–99 | a synth track's parameters |
| B | 26, 27, 28, 16, 18, 17, 21, 20, 19 | 1–69 | the FX / mixer track |
| C | 26, 27, 28, 23, 24, 25 | 1–64 | a MIDI track |
| D | 29, 30, 22 | 0–25 | trig parameters |

Clusters A, B and C each contain the LFO groups, because there is only **one**
set of LFO records in the table while every track type has LFOs. Cluster D
overlaps the LFO ids completely, so trig parameters must be a separate space.

*The weakest link is the claim that the DN2's FX track has LFO pages. That is
thirty seconds on the instrument to confirm or kill, and it is worth doing
before anything is built on cluster B.*

### Two records per LFO are second presentations of an existing parameter

This is why ten records carry eight parameters, and it is not a quirk of the
table; it is what the instrument does.

**`SLEW` shares `SPH`'s id** — 6 on LFO1, 14 on LFO2, 22 on LFO3. On the
device, for waveforms such as random, the knob that sets start phase is
remapped to control slew instead. One parameter, one knob, two presentations
with different names and formatters. `SLEW` also carries **no controller
number** (`0xffffffff`) while `SPH` does, which is what you would expect if
only one of the pair is externally addressable. *Confirmed against the
instrument by its owner, 2026-09-08; the firmware layout and the device
behaviour were established independently and agree.*

**The tenth record is a second `MULT`**, sharing `MULT`'s id (2 on LFO1, 10 on
LFO2, 18 on LFO3) and its controller number, but with a different range —
`0x0b00` against `0x1700`, so twelve values against twenty-four — and a
different handler. Almost certainly the multiplier list differing between
free-running and tempo-synced speed. **Inferred from the ranges; not
confirmed.**

`SLEW` exists only on the DN2. The strings `Slew` and `SLEW` do not appear
anywhere in DN1 1.42A.

## What reads this table — answered

**`docs/parameter-table-consumer.md`.** The table is a flat array indexed by a
**global parameter id** (1..320); `record[id] = 0x401e29d0 + id*60`; ~50
accessor functions read it, and its length is a **bounds immediate `< 321`
replicated across ~43 of them**, not a stored count. LFO1 is global ids 75-84,
LFO2 85-94, LFO3 95-104. A fourth LFO appends ids 321-330 and raises every
bound. **Note:** that consumer origin is `0x401e29d0`; the field table above
used `0x401e29d4`, four bytes in, so its field *relationships* hold but the
absolute offsets are shifted by 4.

## Nothing points at this table by absolute literal

Scanning all of MAIN OS for the 32-bit value `0x401e29d4`, for one-past-the-end,
and for any record-aligned address inside the table from outside it: **zero
hits.** Addresses immediately before and after the table are referenced freely
— `0x401e29a0` from a dozen `lea` instructions, the region from `0x401e74dc`
onward from many more — so the scan works and the absence is real.

That leaves PC-relative addressing, a base register, or an anchor a fixed
distance away. **Unresolved, and it is the next thing to find**, because
whatever reaches the array is also whatever would have to be told it grew.

## The second table, and it is not the one you want

`0x401bae00`, 183 records, 19 groups, with LFO blocks for **LFO1 and LFO2 only**
and no `SLEW`. It carries the Digitone 1's parameter set — the same parameters
in the same order as DN1 1.42A's own table, including DN1-only pages.

It is **not** the MIDI-track set: MIDI tracks have no filter, no amplitude
envelope and no effect sends, and DNX records that *"MIDI tracks address a much
smaller parameter set"* (`DNX/docs/dn1-project-format.md`).

Why the DN1 set is in DN2 firmware is **UNKNOWN** and is not being pursued —
the scope here is the Digitone II. It is recorded only so that nobody mistakes
it for the real table, which is easy to do: it has LFO blocks that look right
until you notice there are two of them.

## What this means for a fourth LFO

The shape is still the good news: adding LFO4 means appending a fourth block of
ten records with a new page-label string and a new group number. Nothing about
the table is hard-coded to three, and no count field has been found beside it.

The constraint is the id, and it is **not** "Chorus is sitting on 25".

A single LFO4 block carries one id per parameter, and those records are shared
by every track type that has LFOs — clusters A, B and C above. So LFO4's eight
ids have to be free in **all three at once**. Taking the clusters at face value:

| Cluster | Highest id in use | Free from |
|---|---|---|
| A — synth track | 99 | 100 |
| B — FX track | 69 | 70 |
| C — MIDI track | 64 | 65 |

The intersection is **100 and above**, so `100–107` is the first run of eight
ids free everywhere. Id 65 is free in cluster A alone and is a red herring.

Two things must be established before that is a plan rather than an arithmetic
exercise, and they are the same question asked twice:

- **What consumes the table, and is the id bounded?** Nothing points at the
  array, so nothing is yet known about its consumer. If a parameter id indexes
  a fixed-size array — 100 entries, say, or 128 — then `100–107` is either
  exactly fine or exactly fatal, and which one is a fact we do not have.
- **How these ids relate to the parameter-lock ids DNX derived from hardware.**
  DNX found lock ids following `4 * slot + lfo` for `lfo` 1–3, leaving
  `4 * slot + 0` unused (`DNX/docs/dn2-pattern-format.md`). That is an
  interleaved space; this one is blocked, LFO1 1–8 then LFO2 9–16. They are
  plainly different numbering schemes and **no correspondence between them has
  been established** — do not assume one. If p-lock ids are derived from these
  ids arithmetically, non-contiguous LFO4 ids break that derivation, and this
  stops being a table edit.

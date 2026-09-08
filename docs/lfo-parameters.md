# The LFO parameter tables

Measured from Digitone II 1.10E and Digitone 1.42A MAIN OS on 2026-09-08.
This is the Phase 2 starting point: it answers whether the LFO count is a
constant the code reads or something structural.

**It is a table.** Each LFO is a block of records in a flat array, and the
blocks are identical in shape.

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

## DN2: the main table, `0x401e3xxx`

One flat array covering the whole instrument. Walking it: `… Amp, FX, LFO1,
LFO2, LFO3, Chorus, Delay, Reverb …`. The three LFO blocks are adjacent, and
**Chorus begins immediately after LFO3**.

| Block | Group | Records | Parameter ids | First record |
|---|---|---|---|---|
| LFO1 | 26 | 10 | **1–8** | `0x401e3b2c` |
| LFO2 | 27 | 10 | **9–16** | `0x401e3d84` |
| LFO3 | 28 | 10 | **17–24** | `0x401e3fdc` |
| Chorus | 16 | — | **25–** | `0x401e4234` |

Ten records, eight ids. The blocks differ only in the page-label pointer, the
group number, the ids, the controller and NRPN numbers, and a few defaults.
Everything else — handler pointers, ranges, flags — is identical between them.

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

## There is a second table, and it is not the one you want

A second LFO-bearing table sits at `0x401bb9xx`, with nine records per LFO
block and no LFO3 at all. It is **not** the table above and not the one to
edit. It carries the Digitone 1's parameter set — same parameters in the same
order as DN1 1.42A's own table, including DN1-only details like the Amp page's
`DRV` and `AENR`, and LFO blocks with no `SLEW`.

It is **not** the MIDI-track set: MIDI tracks have no filter, no amplitude
envelope and no effect sends, and DNX records that *"MIDI tracks address a much
smaller parameter set"* (`DNX/docs/dn1-project-format.md`).

Why the DN1 set is in DN2 firmware is **UNKNOWN** and is not being pursued —
the scope here is the Digitone II. It is recorded only so that nobody mistakes
it for the real table, which is easy to do: it has LFO blocks that look right
until you notice `SLEW` is missing.

## What this means for a fourth LFO

The good news is the shape: adding LFO4 to this table is appending a fourth
block of ten records with a new page-label string, group 29, and the next
controller and NRPN numbers. Nothing about the table is hard-coded to three.

The problem is where the ids go. **LFO3 ends at id 24 and Chorus begins at
25**, so a fourth block cannot simply continue the sequence — either it takes
ids after the end of the whole table, or everything from Chorus onward
renumbers. Which is possible depends on what else indexes into this id space,
and that is the next thing to find out.

Two things not yet known, and both bear on it:

- **What consumes the table, and whether anything holds its length.** No count
  field has been identified. If the array is walked by a bound stored
  elsewhere, that bound is the other thing LFO4 must change.
- **How these ids relate to the parameter-lock ids DNX derived from hardware.**
  DNX found lock ids following `4 * slot + lfo` for `lfo` 1–3, leaving
  `4 * slot + 0` unused (`DNX/docs/dn2-pattern-format.md`). That is an
  interleaved space; this one is blocked, LFO1 1–8 then LFO2 9–16. They are
  plainly different numbering schemes and **no correspondence between them has
  been established** — do not assume one.

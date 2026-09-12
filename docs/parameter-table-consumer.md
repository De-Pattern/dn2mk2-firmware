# What reads the parameter table, and what that means for a fourth LFO

`docs/lfo-parameters.md` found the table and left one question open: *what code
reads it, and where is its length held?* Both are answered now, read from a
Gate-F-cleared MAIN OS in Ghidra and cross-checked against the bytes.

## The table is a flat array indexed by a global parameter id

The consumer is a family of ~50 accessor and page-drawing functions. Each one
indexes the same array the same way. The clearest is the page renderer
`FUN_40016f38` (`0x40016f38`), whose decompiled lookup is:

```c
(&PTR_DAT_401e29d0)[ (-(id < 0x141) & id) * 0xf ]   //  *15 words = *60 bytes
```

> **Read this with `docs/modulation-mask.md` before editing records.**
> `0x401e29d0` is the address of a record's **short-name pointer**, which sits
> `0x38` bytes into the record — not its first byte. Every other field is at a
> *negative* offset from this anchor. Taking it as the record start silently
> shifts every field by one record; that produced a bad firmware build on
> 2026-09-11 (`docs/lfo4-feasibility.md`, "The Stage 1 correction").

Reading it:

- **Base `0x401e29d0`**, records **60 bytes** (`* 0xf` on a 4-byte array), indexed
  by **`id`**.
- **`id < 0x141`** (321) is a bounds check; the `-(...) & id` clamps an
  out-of-range id to 0.
- So **`record[id] = 0x401e29d0 + id * 60`**, for `id` in `1 .. 320`.

`FUN_40016f38` itself is the `[MOD]`/parameter page renderer: a grid loop over 8
cells, each fetching its parameter id from the page-view object's vtable and
drawing the record. Its offset-0 field is the parameter's **short-name** pointer.

**Verified by indexing.** Following `0x401e29d0 + id*60` offset 0 to its string
for a run of ids returns exactly the blocks you expect:

| ids | short names |
|---|---|
| 75–84 | SPD MULT FADE DEST WAVE SLEW SPH MODE DEP (+MULT) — **LFO1** |
| 85–94 | the same — **LFO2** |
| 95–104 | the same — **LFO3** |
| … | … |
| 315–320 | TRO OP LEN FREQ FDBK LPF |

The highest non-empty id is **320**; id 321 and up are past the table. So the
array is exactly 320 entries, `id` 1..320, with `id` 0 the unused slot the
`id == 0` branch draws blank.

## The length is a replicated immediate, not a stored count

Nothing holds "320" as a field. The bound lives as an **immediate in every
accessor** — across the 53 sites that reference the base, the bound appears as
`#321` at 32 of them, `#320` at 11, and `#311` once. That is the single most
important fact for growing the table: **its size is baked into ~43 places**, and
they must all agree.

## Two id spaces — do not confuse them

- **The global array index** used here (`id` 1..320): a parameter's position in
  the flat table. **Unique** — it is the position.
- **The record's internal `(group, id)` fields** documented in
  `docs/lfo-parameters.md` (word 2 and word 3 of a record): the per-page group
  and a small id used for MIDI CC/NRPN mapping. Those small ids are **not**
  unique — 68 of 100 are shared across groups. That earlier finding was about
  *these* fields, not the array index above.

They are different numbers. The consumer indexes by the global array index.

## What a fourth LFO takes

The table is contiguous and ends at 320, so the low-friction change is to
**append**:

1. **Append 10 records** for LFO4 after id 320, i.e. ids **321–330**, with a new
   page-label string and the next controller/NRPN numbers. (Ten ids per LFO
   block, as LFO1–3 each occupy ten.)
2. **Raise the bound** everywhere it is baked in: `#321 → #331`, `#320 → #330`,
   and the lone `#311` — the ~43 accessor sites above. Miss one and the parameter
   it guards reads as out-of-range and clamps to id 0.
3. **Add a page-view** for the fourth `[MOD]` page — an `LfoPageView`-like object
   whose vtable hands its 8 cells the new global ids 321–330, exactly as the
   three existing LFO pages hand theirs 75–84, 85–94, 95–104.

Appending avoids renumbering everything after LFO3 (Chorus onward), which
inserting between LFO3 and Chorus would force. The cost is finding and editing
every bound immediate — mechanical, but it must be complete.

**Still open, and it gates step 3:** how the page-view objects are constructed
and where their per-cell id lists live (the vtable method at `+0xbc` that returns
a cell's id). That is the next thing to read — the three existing `LfoPageView`
instances are the template. The record layout past offset 0 (the numeric fields)
is also worth pinning against this base; `docs/lfo-parameters.md`'s field table
used a base 4 bytes later (`0x401e29d4`), a different byte called "offset 0", so
its field *relationships* hold but its absolute offsets are shifted by 4 from the
consumer's origin here.

## The base, reconciled

Three addresses looked like "the base" while reading this — `0x401e29a0`,
`0x401e29d0`, `0x401e29d4` — because each accessor reads a different field and
both objdump and Ghidra fold the field offset into the base they show. The
authoritative origin is the one the indexing arithmetic uses with a name pointer
at offset 0: **`0x401e29d0`**, confirmed because `base + id*60` returns the right
parameter names. `docs/lfo-parameters.md` reported `0x401e29d4`; that was four
bytes into this origin.

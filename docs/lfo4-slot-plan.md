# Where LFO4's eight slots come from

The engine side is finished (`docs/engine-index-map.md` §§11, 14): the DN2's
SHARC implements a fourth LFO, lane 4 is a separate generator, and four run
simultaneously. Everything left is control-side, and it is one problem — **eight
runtime slots**.

`docs/engine-index-map.md` §13 measured the constraint and sketched a hook-based
answer. That sketch was pessimistic, and this document replaces it. The question
"why not move the tables into the 25 MB of unclaimed RAM?" (owner, 2026-09-12)
is the right one, and the answer splits three ways depending on *where a table
lives today*.

## The three kinds of table, and the right home for each

### 1. BSS tables built at boot — move them, it is nearly free

The `ParameterSet` slot tables at `0x42c6xxxx` are **BSS**, zeroed and then
filled by `param_set_tables_build` (`docs/parameter-set-tables.md`). The builder
passes each table's **address and byte length as literal immediates**:

```
400dc4d8:  pea 0x194            ; 404 bytes = 101 entries
400dc4dc:  pea 0x42c64b3c       ; the sound slot table
400dc4e2:  lea 0x40133ebc,%a2   ; -> a plain `clrl (a0)+` zero-fill loop
400dc4fc:  jsr %a2@
```

`0x40133ebc` is confirmed as **memset-to-zero** — a `clrl %a0@+` / `subql #4`
loop, nothing more. So the table's location and size are **two immediates**, and
the table's contents are computed at boot from the parameter records, not shipped
in the image.

**So this table can move anywhere writable and grow to any size** by changing
those two immediates and repointing the other references. For the sound slot
table that is **5 `lea` sites** (`0x400dc062`, `0x400dc4dc`, `0x400dc652`,
`0x400dc6d0`, `0x400dc752`) plus the size. Nine values, no new code, no cave.

**This is exactly what the 25 MB above the BSS end is for.**

### 2. Read-only tables that ship in the image — a cave, not the 25 MB

The forward map (`0x401fcf20`, 100 entries) and inverse map (`0x401fd0b0`) are
**constant data in the image**. Their contents arrive with the firmware.

Moving them into the 25 MB would mean also writing boot-time code to *copy* them
there, because — see the caveat below — nothing initialises that region. A
**cave** needs none of that: 432 bytes for a 108-entry forward map fits a ~1 KB
run, the bytes ship in the image exactly as they do now, and only the **4 `lea`
sites** and the `moveq #99` bound change.

For static data, a cave is strictly simpler than the 25 MB. The 25 MB wins only
where the contents are generated at runtime.

### 3. The per-object value array — it cannot move, and does not need to

This is the one the "just move the table" answer does not reach, and the reason
is worth stating precisely.

The value array is **not a table**. It is a field inside each sound object, and
the objects are an array:

```
4003e440:  moveq #127,%d1        ; index clamped to 0..127
4003e442:  cmpl %d0,%d1
4003e448:  movel #2388,%d1       ; object stride 0x954
4003e44e:  mulsl %d1,%d0
```

**Up to 128 sound objects, 2,388 bytes each** — a sound pool of ~306 KB. Each
carries its own values at `+0x14 + slot*2`, boxed in at `+0xDD` by the machine
type at `+0xDE`. A single relocated table cannot serve 128 objects.

**But it does not have to.** The need is eight *extra* slots per object, not a
relocated array:

```
ext[obj][param]   128 objects x 8 params x 2 bytes = 2,048 bytes
```

Two kilobytes, at a fixed address in the 25 MB, indexed by the **same 0..127
object index** the accessor above already computes. Slots 0–100 keep reading the
object; slots 101–108 read `ext`. Nothing in the sound object moves, its size and
layout are untouched, and the persisted format is unaffected.

## The caveat that decides how the 25 MB is used

**The BSS clear stops at `0x466b74d0`.** The region above it is never zeroed and
never written by the loader — it holds **power-on garbage** until something puts
data there.

That is fine for the `ParameterSet` table, which the builder memsets before
filling. It is **not** fine for anything expected to start at zero: our
extension array must be cleared by our own code, and a table whose contents ship
in the image cannot live there at all without a copy routine.

And placement stays at the **bottom** of the window, just above `0x466b74d0` —
the stack descends from `0x48000000` and its depth is unmeasured
(`docs/memory-map.md`).

## The revised shape of the job

| Piece | Home | Cost |
|---|---|---|
| sound `ParameterSet` table → 109 entries | **25 MB region** | 5 `lea` + 1 size immediate |
| forward map → 108 entries | **cave** (432 B) | 4 `lea` + 1 bound immediate |
| inverse map | stays | write 8 entries — already 107 wide |
| destination-list builder bound | stays | 1 immediate (`i != 0x65` → `0x6d`) |
| `slot_to_engine_index` bound | stays | 1 immediate (`moveq #99`) |
| **extension array for slots 101–108** | **25 MB region**, 2,048 B | needs zeroing at boot |
| **the access hooks** | caves | **the real work — see below** |

Everything above the last row is immediates and `lea` repointing. **The hooks are
the only genuinely new code.**

## What still needs deciding: which of the 29 sites are reachable

29 sites index the value array (15 reads, 9 writes, 5 `lea`). The hook count is
**not** 29 — it is however many of those can ever be called with a slot ≥ 101,
and most cannot:

- sites on machine-parameter paths only see slots 25–64;
- sites on filter paths only see 66–68;
- the `lea` sites take an address for a *range* of slots and may not need
  touching at all if LFO4's slots sit outside that range.

**The next job is to classify all 29 by reachable slot range.** That is static
analysis, needs no flashing, and it determines whether this build is four caves
or fifteen — which is the difference between a weekend and a project.

The known choke points, where a hook is certainly needed:

| Path | Site |
|---|---|
| control → engine | `Sound::updateMirror`, `0x4004cb04` and `0x4004cb70` |
| engine → control | the reverse copy at `0x400dd25e` |
| UI read | `parameter_value_getter` `0x4006408a` |

Plus whatever the storage path turns out to be, which is not yet scoped and is
the one place where "LFO4's values do not survive a save" would be the failure.

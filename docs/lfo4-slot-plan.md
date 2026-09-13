# Where LFO4's eight slots come from

> **⚠️ This document opened by asserting that the engine side was finished. It
> is not, and that sentence was wrong (corrected 2026-09-13).**
>
> It read: *"the DN2's SHARC implements a fourth LFO, lane 4 is a separate
> generator, and four run simultaneously"*, citing `docs/engine-index-map.md`
> §§11 and 14. **Both of those sections are withdrawn.** The two probes that
> "confirmed" a fourth generator each changed the forward *and* inverse maps
> together, so a consistent storage round-trip predicts the same positive result
> with **only three generators running** — the tests never discriminated. The
> offsets they were built on are the **DNX storage layout**, not engine
> addressing (§15).
>
> So whether a fourth LFO generator exists is **unknown**, and everything below
> is contingent on it. The plan is kept in full because the control-side
> analysis stands on its own and is still what LFO4 needs; only the premise that
> the engine is ready has been removed.

Everything below is control-side, and it is one problem — **eight runtime
slots**.

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

---

## The 29 sites, classified by how their index is produced

Static classification of every value-array access, by tracing what sets the index
register in the 24 instructions before it. The question is which sites can ever
see a slot ≥ 101.

| Index comes from | Sites | Reach |
|---|---|---|
| **`param_index_in_page`** (`0x400dbcc4`, returns `record[id]+0x04`) | `0x40036536` `0x40037194` `0x40037260` `0x40037be8` `0x40038902` `0x4006414c` | **any parameter id — generic** |
| **the changed-parameter list** (`Sound::updateMirror`) | `0x4004cb08` `0x4004cb74` | **generic** |
| **a 0..100 fill loop** | `0x400440a2` | **generic by construction** |
| **a bulk copy** (via `0x400dbc88`) | `0x4004c226` `0x4004c27c` | **generic** |
| the inverse table (reverse copy, different access form) | `0x400dd25e` | **generic** |
| small local bounds (`#4`, `#15`, `#16`, `#49`) or `is_lfo_param` | the `lea` sites and the remainder | narrow — need individual reading |

**So the hook count is around eleven, not twenty-nine** — better than §13 feared,
worse than a weekend.

**And six of the eleven share one upstream function.** All the
`param_index_in_page` sites take their index from a single accessor returning
`record[id] + 0x04`. That is the natural place to *think* about the problem, even
though hooking it alone does not solve it: changing what it returns just moves
the out-of-bounds access rather than preventing it.

## The simplification this suggests, and it may be the right design

Every difficulty above comes from one decision: **that LFO4's values live inside
the sound object**, which is full, boxed in, persisted, pooled ×128, and mirrored.

They do not have to.

LFO1–3 are *sound* parameters because they are stored in the preset. **A fourth
LFO could instead be track-level** — its eight values held in a small array of
our own, one set per track, never touching the sound object at all. Then:

| | sound-slot design | track-level design |
|---|---|---|
| sound object | grows / needs 11 hooks | **untouched** |
| slot space | needs 8 of 101 | **needs none** |
| `ParameterSet` table | relocate + grow | **unchanged** |
| forward/inverse maps | relocate + grow | **unchanged** |
| hooks | ~11 | **~3** — mirror write, UI read, UI write |
| persisted format | unchanged either way | unchanged |
| **LFO4 saved per sound?** | yes | **no — per track** |

The whole slot problem — §13, §6b, the 101-entry array, the machine-type byte —
**disappears**, because slots were only ever the mechanism for getting values
into the mirror, and a hook can put them there directly.

**The cost is real and should be stated, not buried:** a track-level LFO4 would
not be stored in a Sound preset, so loading a sound would not bring its LFO4
settings with it. Whether that is an acceptable version-one is a judgement for
the owner, not a technical question — and it is reversible later, since the
sound-slot route stays open.

**This is the decision the build now waits on**, and it is worth making before
any code is written, because the two designs share almost nothing.

---

## The canary result: no cave has ever been proven to run

**2026-09-13.** `lfo4-canary_DN2_1.11.syx` stamps `0x7700` — coarse byte **119** —
into LFO1's `SPD`, a slot the owner's own saved sound proves is serialised. The
owner flashed it, loaded an init sound, raised Amp Volume, saved, and read the
slot back with DNX.

**LFO1 `SPD` reads 112 — the init default. The canary is absent.**

By the criterion set before the test, that is the branch which invalidates the
approach: *the hook never runs, or this mirror is not what gets saved.*

### Why it does not run

`0x4004ca80` — the function this project hooked — has **no direct callers**. Its
address appears exactly once in the whole image, as **data**, at `0x401de138`:

```
0x401de134: 0x40199768
0x401de138: 0x4004ca80     <-- the hooked function
0x401de13c: 0xffffffd8     <-- -40: a `this` adjustment
0x401de140: 0x401ddd9c
```

That is a **vtable slot**, with the negative thunk offset of a multiple-
inheritance adjustment beside it. So the function is a *virtual* override
reached only through a dispatch that did not happen during an ordinary edit and
save.

The identification was not baseless — the prologue `lea %sp@(-64),%sp` and
epilogue `lea %sp@(64),%sp` pair correctly, and the `Sound::updateMirror` string
is pushed inside its bounds. But that string is pushed as an **argument to a
logging call**, which names a function rather than proving we are in it, and the
mangled symbol ends `EUlvE_` — a **lambda** inside `Sound::updateMirror`, not the
method itself. Both signals were available before any firmware was built.

### What this actually establishes

**No code cave has ever been shown to execute on this device.** Gate E proved a
*data* edit reaches the screen. Every cave built since has been verified
offline — bytes diffed, disassembly read, integrity checks green — and **none of
that tests whether the code runs.** Four builds were flashed on the assumption
that it did.

That is the gap, and it is upstream of every LFO4 question.

### The next build should prove the mechanism, nothing else

Hook a function that **certainly** runs and give it an effect impossible to
misread. `parameter_value_getter` (`0x4006408a`) is the candidate: it is called
whenever the UI draws a parameter, this project has already anchored it, and
adding a constant to its return makes **every parameter on screen read wrong by
the same amount**. Harmless, instantly visible, reverted by reflashing stock.

- **Values shift** → caves run; the mechanism is sound; the LFO4 failures were
  target-selection, and `updateMirror` simply needs finding properly.
- **Nothing changes** → caves do not run as built, and the fault is in the hook
  mechanism, the cave region, or `patch/cave.py` — which would explain every
  silent result so far, including the two "confirmed" probes now withdrawn.

**Do not build another LFO4 variant until that question is answered.** Three of
this project's flashes have now been spent on an assumption that was never
tested and could have been tested first.

### ANSWERED 2026-09-13: caves execute, and the target was always the fault

The question was put to the device twice more and both answers are in
`docs/flashing.md`.

`build_flash_control.py` carried the known-good Gate E edit alongside the
experiment. `DNFW ALIVE!` appeared in SETTINGS and `AMP VOL` still read 110 — so
**flashing works**, our images run, and the branch above was the wrong pair. The
cave test had hooked a function that is never reached for the thing being
observed: **invalid, not negative.**

`build_cave_boot_proof.py` then hooked the boot path — where nothing has to be
assumed, because the device boots — and had the cave write `CAVE RAN!!!` over
the SETTINGS string in RAM while the image still contained `PERSONALIZE`. **The
device showed `CAVE RAN!!!`.** Only the cave can have written it.

So: **caves execute, from the constants region, exactly as built.** The
suspicion that `0x4028ea02` is not executed is withdrawn (`docs/code-caves.md`).
Every silent build was target selection.

**What replaces "do not build another LFO4 variant".** The prohibition stands,
but for a new reason: not because the mechanism is unproven, but because the two
functions LFO4 must hook — the display path and the engine-feed path — are still
unnamed, and `parameter_value_getter` is now known **not** to be the first.
Guessing again costs a flash and returns one bit.

`docs/trace-harness.md` is the answer to that: eleven probes in one image, each
marking its own column of the SETTINGS string when its function runs. It settles
`G` (does the getter run at all?), `M` (is the vtable reading right?) and the
nine other candidates in a single flash, using the mechanism just proven.

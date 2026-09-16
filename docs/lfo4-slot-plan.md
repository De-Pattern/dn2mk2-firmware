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

---

## The forward and inverse maps, dumped -- and the reserved rank is a real hole

**2026-09-15.** This document listed the forward map (`0x401fcf20`) and inverse
map (`0x401fd0b0`) as things LFO4 must extend, sized the work, and never read
them. They are now dumped, and they explain two things measured elsewhere.

**Forward, `0x401fcf20`, longwords: runtime sound index -> p-lock id.**

| idx | id | | idx | id | | idx | id |
|---|---|---|---|---|---|---|---|
| 0 | 0 | | 9 | 2 | | 17 | 3 |
| 1 | 1 | | 10 | 6 | | 18 | 7 |
| 2 | 5 | | 11 | 10 | | 19 | 11 |
| 3 | 9 | | 12 | 14 | | 20 | 15 |
| 4 | 13 | | 13 | 18 | | 21 | 19 |
| 5 | 17 | | 14 | 22 | | 22 | 23 |
| 6 | 21 | | 15 | 26 | | 23 | 27 |
| 7 | 25 | | 16 | 30 | | 24 | 31 |
| 8 | 29 | | 17 | 3 | | 25 | 33 |

Indices 1-8 are LFO1, 9-16 LFO2, 17-24 LFO3 -- exactly the block boundaries
`docs/engine-state.md` derived independently from `record+0x04` -- and the ids
are `4*slot + lfo`, exactly as DNX reads them out of stored patterns. **All
eight ids DNX decoded from pattern A1 match this table entry for entry**:
`1->1, 2->5, 12->14, 13->18, 14->22, 15->26, 16->30`, and `0->0`.

So **`NOTE` landing on lock id 0 was not an arithmetic coincidence** -- the
firmware's own table says index 0 maps to id 0.

**Inverse, `0x401fd0b0`, longwords: p-lock id -> runtime sound index.**

```
id    0   1   2   3    4   5   6   7    8   9  10  11   12  13  14  15
idx   0   1   9  17    0   2  10  18    0   3  11  19    0   4  12  20
      ^                ^                ^                ^
```

**Every id in the `4*slot + 0` rank -- 0, 4, 8, 12, 16, 20, 24, 28 -- maps to
index 0.** All eight. The reserved fourth-LFO column is not an accident of
numbering that happens to be unused: it is **a structured hole, eight entries
wide, already present in the shipped table**, every entry pointing at the one
index that carries no parameter.

### It also explains DNX's "id 32 never observed"

DNX reports that ids **32**, 63-65 and 86 have never appeared on any page or
machine. The forward map says why for 32: index 24, LFO3's last slot, maps to
**31**, and index 25, the first machine parameter, maps to **33**. **Id 32 is
skipped.** Nothing maps to it, so nothing can ever store it. Two projects
reaching one fact from opposite ends -- DNX from stored patterns, this one from
the firmware's own table.

### What this does to LFO4's cost

This document estimated *"inverse map | stays | write 8 entries -- already 107
wide"*. **Confirmed, and it is exactly eight**: repoint inverse entries 0, 4, 8,
12, 16, 20, 24 and 28 from `0` to LFO4's eight runtime indices, plus the
matching eight forward entries.

Both are **data edits in the shipped image** -- no cave, no relocation, no
allocation -- and they are now located, dumped, and verified against an
independent decode of real stored data.

**Still not established:** whether anything *applies* a lock whose id is in the
reserved rank. Pattern A1 carries one, stock loads it without complaint, and the
owner sees nothing -- equally consistent with "applied to index 0, which carries
no parameter" and "ignored". The inverse map makes the first the more likely: a
reserved-rank lock resolves to the null index and is applied harmlessly to
nothing.

---

## [CORRECTION 2026-09-16] "29 sites" was never a well-defined set

Re-deriving the list before building v6's hooks, because §"The 29 sites" is the
thing step 4 of the build order is sized against.

**The method.** The sites are recognisable by their addressing mode, not by a
constant: `%aN@(0x14,%dM:l:2)` is a brief-format extension word, so the word is
`(M << 12) | 0x0A14` for index register `dM`. Scanning for those eight words,
then keeping only the ones that are **word-aligned** and whose **preceding
opcode actually names mode 110** in one of its EA fields, gives a clean list.

**It reproduces every documented site.** All eleven addresses this file and
`docs/lfo4-build-plan.md` §3 name — `0x40036536`, `0x40037194`, `0x40037260`,
`0x40037be8`, `0x40038902`, `0x4006414c`, `0x4004cb08`, `0x4004cb74`,
`0x400440a2`, `0x4004c226`, `0x4004c27c` — come back, 11 of 11. So the scan
finds the same thing the original reading found.

**But it finds 33 in the code range, not 29**, and 37 across the whole section.

### Why the discrepancy is the point, not a bug to fix

**The pattern identifies an *offset*, not *the value array*.** Any structure
anywhere in this firmware that holds a 16-bit array at `+0x14` and indexes it
with a scaled long register produces exactly these bytes. Nothing in the
encoding says `%aN` points at a sound object.

So neither 29 nor 33 is *the* number of value-array accesses. Both are counts of
a **shape**. The original 29 was presumably the shape count minus some judgement
about which bases were sound objects; that judgement is not recorded, which is
why the two numbers cannot be reconciled from the documents alone.

This is `docs/FEATURE-PLAYBOOK.md` §2.2 one level deeper. "Anchor on structure,
not on a constant" is right and it is what makes this scan reproduce the known
sites. But an addressing mode is still a **shape**, not an **identity** — and
the question v6 has to answer ("can this site ever see a slot ≥ 101") is about
identity: *is this base a sound object, and where does this index come from?*

### What this changes

**Nothing static can close it.** Whether `%a2` holds a sound object at a given
site is a fact about execution, and three separate attempts to settle
value-array reachability by reading have now produced three different answers
(144 regex hits, 29 sites, 33 sites).

**The instrument is the emulator, and it is now available.** A code hook at each
of the 33 candidates, reporting the base register and the index at every hit,
answers both halves at once: a base outside the sound-object pool
(`base + 0x4414 + i*2388`, 128 objects) disqualifies the site outright, and the
observed index range bounds what it can reach. `tools/addrtrace.py` reports hit
counts and registers by running, which is exactly this.

**The 33 candidates** (opcode address, index register):

```
0x40030ef0 d1   0x40030f34 d2   0x40030f88 d2   0x40032754 d1
0x40032774 d3   0x400328d4 d1   0x400328f4 d2   0x40036536 d2 *
0x40037194 d2 * 0x40037260 d2 * 0x40037be8 d2 * 0x40038902 d2 *
0x4003a146 d0   0x4003d864 d0   0x4003f5a2 d0   0x4003f5be d2
0x4003f700 d0   0x4003f736 d0   0x400440a2 d3 * 0x4004b16a d0
0x4004c226 d2 * 0x4004c27c d2 * 0x4004c2e4 d3   0x4004c38a d2
0x4004c42c d3   0x4004c4e6 d2   0x4004cb08 d2 * 0x4004cb74 d2 *
0x4006414c d2 * 0x4012ae74 d6   0x40140b38 d7   0x401423b2 d7
0x40142826 d7
```

`*` = named in the existing documents. The four `lea` sites are `0x40032754`,
`0x40032774`, `0x400328d4`, `0x400328f4` (opcode `41f0`); this file's §"29
sites" says **five** `lea`, which is one more discrepancy of the same kind and
for the same reason.

**Do not re-price step 4 on 33 either.** It is a candidate list to instrument,
not a hook count. The hook count is whatever survives the run.

---

## [CORRECTION 2026-09-16] The 128-object pool is stored Sounds, not the live track state

**From the owner, and it invalidates what this document has been sizing.** The
measurement that provoked it: under the emulator, `[MOD]` was pressed, LFO1's
`SPD` was turned four times, and the screen changed — `SPD` showed its value
`16.62` — while **not one byte of all 128 sound objects changed**. The stimulus
control passed (the screen proves the edit landed), so the null result is real.

### The owner's model of where track state lives

| layer | where | tied to a Sound? |
|---|---|---|
| **current project track data** | the running project's working memory, 16 tracks | **no — it stands alone** |
| project save | +Drive, when the user chooses | no |
| a stored **Sound** | +Drive, created by **burning** a track's config | that *is* what burning means |
| the **128-slot pool** | the project | **optional** assignment of a stored Sound |

In the owner's words: *"You can start a project anew in the DN and twist knobs,
and that config stays in the tracks in that project."* No Sound is involved in
that loop at any point, and the track data *"doesn't need to be tied to any
sound in the pool or +Drive at all."*

### What that means for this document

**`sound + 0x14 + slot*2` is the STORED layout.** The 128 × 2,388-byte objects
are the project's **Sound pool** — optional storage — not the structure the UI
edits. Everything in this file that sizes the job against those objects is
describing the persistence side of the feature, which is real work but is **not
where a live LFO4 value lives**.

So LFO4 needs to exist in **two** places, and only one of them is scoped here:

1. **Per-track project data** — 16 instances, live, what the encoder writes and
   what the engine reads. **Unlocated as of this correction**, and the thing to
   find next.
2. **The stored Sound format** — the 128-object layout this document already
   describes, which matters at burn and at project save.

**This also explains the 33 silent sites.** `docs/lfo4-slot-plan.md`'s
"[CORRECTION] 29 sites was never a well-defined set" found that none of the
shape-scan candidates ever executed. If they are stored-Sound code, they would
only run on load, burn or save — none of which a boot-and-twist-knobs run
performs. Their silence is consistent with being real value-array code that this
experiment never provoked, rather than with being dead.

### The method note, because it is the same one twice

The pool null result was the correct answer to a **wrongly framed question**.
Nothing static would have revealed the framing error: the layout, the stride and
the accessor are all exactly as this document describes them, and all confirmed
at runtime (128 objects, 2,388 stride, `base + 0x4414 + i*2388`). What was wrong
was believing that structure is what a knob writes.

`docs/FEATURE-PLAYBOOK.md` §2.3 says a measurement that contradicts what the
owner knows about their own instrument should make you suspect the reader. Here
the measurement was right and the *model* was wrong — and the owner corrected it
from years of use, which is the same rule pointing the same way: **ground the
model in how the device is actually operated, before sizing work against a
structure.**

### What the edit path looks like so far — 2026-09-16

Found by differencing memory across matched intervals under the emulator
(`scripts/trace_value_array_sites.py`). **None of it is the parameter store**,
which is still unlocated; it is recorded so the next attempt does not re-find it.

| address | what it is | how it was shown |
|---|---|---|
| `0x445a0988 + 0x10*n` | **input event ring**, 16 bytes per record; `+0x7` a tag, **`+0x8` a signed delta** | turning up wrote `0x01/0x02`, turning down wrote **`0xff`/`0xfe`** |
| `0x445a0dc4 + 4*n` | **per-encoder event counters**, u32 | ENC1 moved `…dc7`, ENC2 moved `…dcb`; both **rose when turning down**, so counters, not values |
| `0x44670638` | RTOS queue field taking **`0x4059d1c0`**, the prio-6 task's TCB | the written value is literally the TCB from the run's own task list |
| `0x44622bc8` / `0x44622fc8` | **fb_front / fb_back**, 1 KB each | read from the `fb_front` pointer at `0x402a0b88` |
| `0x447e1000` | title-bar text buffer | it received the ASCII `LIGHTHOUSE` |
| `0x405c5000`, `0x405c6000` | **stack** | their contents are addresses inside themselves |

#### Three false leads, and why each looked convincing

**Stride 8 in the framebuffer.** A diff showed ~68 bytes on an 8-byte stride,
matching DNX's `30 + 8*parameter + 2*lfo` LFO grid exactly. It was **glyph row
spacing in a 1-bpp framebuffer**. Caught by reading the `fb_front` pointer
rather than by noticing the pattern was wrong.

**A 32-bit "value" of `0x4059D1C0`.** Plausible as a parameter until the number
was recognised as a TCB printed in the same run's startup log. **A pointer, not
data.**

**A byte incrementing ~1 per click from zero.** The best candidate of the day
until it was turned **backwards** and kept counting up.

#### The controls that actually worked

- **Matched intervals.** Two equal windows, one quiet, one with input; diff each
  and subtract. Without it, LFO state and display redraw swamp everything.
- **Page hashing.** Hashing 4 KB pages across the whole ~100 MB BSS costs a few
  hundred KB and needs no guess about where to look.
- **Reversing the stimulus.** A value goes back; a counter does not. This is the
  single cheapest discriminator found today.
- **Differential stimulus.** Turn encoder 1, then encoder 2. Storage must differ
  per parameter; stack, display and event queues respond to both alike.

#### Owner's constraints on interpreting knob data

- Encoders are **acceleration-sensitive**, so the delta per click varies with
  turn speed — do not expect a parameter to move by the click count, or to
  return exactly to baseline after equal turns in both directions.
- Acceleration applies to parameters **with a decimal part**; enums and integer
  parameters step plainly. `SPD` displays `16.62`, so it is in the first group
  and is likely a scaled or fixed-point **16-bit** value rather than a raw byte.

#### The next technique, because memory scanning has run its course

Six memory experiments have each found a different piece of UI plumbing. The
remaining route is **from the code side**: the event ring has a consumer, and
that consumer writes the parameter. Hook `param_index_in_page` (`0x400dbcc4`) or
`param_set_slot_to_id` (`0x400dc02a`) and record the **return address** during an
edit window versus a quiet window; the caller that appears only while turning is
the edit path, and it can be read directly.

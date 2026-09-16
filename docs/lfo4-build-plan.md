
# LFO4 — the build plan

**Written 2026-09-16**, consolidating one session's reading against the owner's
instruction to crack five named pieces. It supersedes nothing; it collects what
`lfo4-feasibility.md`, `lfo4-slot-plan.md` and `modulation-matrix.md` establish
and adds what was read today.

**Read the honesty note in §7 before pricing anything from this.** All five
pieces are designed; one sub-part, `[MOD]` navigation, is not located.

## 0. The design decision, made

`lfo4-slot-plan.md` ends: *"This is the decision the build now waits on."*

**Taken: the sound-slot design.** LFO4's eight values live in an extension array
addressed by the sound-object index, and LFO4 is saved with the preset. The
track-level alternative (~3 hooks) is cheaper but LFO4 would not be stored in a
Sound — and the owner's requirement has been explicit since 2026-09-15: *"what I
would like for it to be a fourth LFO"*, with other paths acceptable only if that
one cannot be solved properly. It can.

Today's read of the sound accessor makes it cheaper than the plan feared: the
slot bound is a `moveq`, not a structural limit (§3).

---

## 1. The classifier — **designed**

Found today; see `lfo4-feasibility.md` "The runtime classifier, found".

Four `*ParameterSet` classes each carry, at **vtable slot `+0x54`**, a predicate
taking a parameter id, indexing the 321-record table at `0x401f7f94` by
`60 × id`, reading the page id at `+0x00`:

| set | predicate | claims |
|---|---|---|
| `SoundParameterSet` | `0x400dbe8a` | `page <= 4` |
| — unattributed — | `0x400dbeb6` | `0x05`–`0x0a` |
| `FxParameterSet` | `0x400dbf4e` | `0x10`–`0x15` |
| `TrigParameterSet` | `0x400dbf82` | `page == 0x1d` **or** `0x16` |
| `MidiParameterSet` | `0x400dbfbc` | `0x16`–`0x1c` |

**Page `0x1f` is claimed by nobody**, and the cascade at `0x40041a72` has no
default guard — two tests, then an unconditional fall-through into the
sound-side addressing at `0x400312fe`. That is the whole of why both probe
builds misbehaved, and it is read, not inferred.

### CORRECTION, same day: the LFO pages belong to `SoundParameterSet`

The table above lists each class's *first* predicate. `SoundParameterSet`'s
vtable body `0x40036bfa` calls **two**: `0x400dbe8a` (`page <= 4`) and then
`0x400dbee6`, a composite that is the real ownership test — and it is the one
that claims the LFO pages:

```
0x400dbf02  lea 0x401f7f94,%a0        ; the parameter table
0x400dbf0c  movel %a0@(0,%d0:l),%d3   ; %d3 = the record's PAGE ID
0x400dbf10  jsr 0x400dbe8a            ; page <= 4 ?
0x400dbf1c  jsr 0x400dbeb6            ; page 0x05-0x0a ?
0x400dbf2a  addil #-11,%d0            ; page in 11..15 -> excluded
0x400dbf34  addil #-26,%d3            ; <-- THE LFO TEST
0x400dbf3a  moveq #2,%d0
0x400dbf3c  cmpl %d3,%d0
0x400dbf3e  scc %d0                   ; (page - 26) <= 2  ->  0x1a, 0x1b, 0x1c
```

It has **four direct callers** — `0x40036c3a` (Sound's own vtable body),
`0x4004486e`, `0x400640ce` (beside the known choke point
`parameter_value_getter` `0x4006408a`) and `0x400653b6`.

**This is the sixth of the six range tests** the feasibility doc counted, and it
is the one that matters: LFOs are sound parameters, stored in the preset, so
`SoundParameterSet` owning pages `0x1a`–`0x1c` is the design working as
intended — not `MidiParameterSet`, whose `0x16`–`0x1c` range is the MIDI track's
own page span.

### The edit

LFO4 does **not** need a renumbered page. Keep LFO1–3 at `0x1a`–`0x1c` and give
LFO4 the next free id; `0x1f` is free and already used by the probe builds.

**The target is `0x400dbf34`, not `0x400dbfbc`.** ~~Widen `MidiParameterSet`'s
predicate.~~ **[WRONG — corrected the same day, above.]** The contiguous test
`(page - 26) <= 2` cannot reach `0x1f` without swallowing `0x1d` (Retrig) and
`0x1e` (None), so it becomes an **exact-match disjunct** — exactly the shape
`TrigParameterSet` already ships:

```
0x400dbfa0  moveq #29,%d1          ; page == 0x1d ?
0x400dbfa6  cmpl %d0,%d1
0x400dbfa8  beqs <yes>
0x400dbfaa  moveb #22,%d1          ; else page == 0x16 ?
```

So the form is proven to compile and run in Elektron's own code, on this exact
predicate family. **The LFO4 edit is `(page - 26) <= 2 || page == 0x1f`**, in a
**cave** — `0x400dbee6` has no slack for the extra compare.

**Open:** whether the other predicate cascades (`0x40064e90`/`0x40064f14`, and
the seven-call `0x40067xxx` cluster) need the same treatment, and whether the
other five range tests must move in step with this one. Each has to be read.

---

---

## 2. The tick — **designed**

`0x40137726`, 1,028 bytes, generator *and* apply. Both loops decoded today.

### Inner loop — one LFO

```
0x40137784  moveq #2,%d1              ; <-- THE LFO COUNT
0x401377a0  movel %d1,%sp@(48)        ; counter = 2
...
0x40137ae2  subql #1,%sp@(48)
0x40137ae6  lea %a2@(-40),%a2         ; state   -= 40
0x40137aec  lea %a3@(-40),%a3         ; state2  -= 40
0x40137af0  lea %a4@(-16),%a4
0x40137af4  cmpl %sp@(48),%d0         ; %d0 = -1
0x40137af8  bnew 0x401377a4           ; until counter == -1
```

Three iterations, counting **down**, walking LFO2 → LFO1 → LFO0. The per-LFO
state record is **40 bytes**; within an iteration the code reaches `%a2@(80)`,
`%a2@(108)` and `%a2@(112)`, i.e. the top LFO's `+0`, `+28`, `+32`.

### Outer loop — one track

```
0x40137afe  movel #202,%d1            ; value-array stride
0x40137b02  moveq #120,%d7            ; <-- LFO STATE STRIDE = 3 x 40
0x40137b04  movel #153,%d2            ; track-object stride
0x40137b0a  addql #1,%a5
0x40137b18  moveq #16,%d0
0x40137b1c  bnew 0x40137770           ; until track == 16
```

### The edits

| # | site | stock | new | bytes |
|---|---|---|---|---|
| 1 | `0x40137784` | `moveq #2,%d1` | `moveq #3,%d1` | 1 |
| 2 | `0x40137b02` | `moveq #120,%d7` | `moveq #-96` … see note | 1 |
| 3 | `0x4013773c` | `pea 0x780` (1920) | `pea 0xA00` (2560) | 2 |
| 4 | `0x4013775a` etc. | `%a2` base | base **+ 40** | cave |

**Note on #2.** 160 does not fit `moveq`'s signed byte as a positive value
(`moveq` sign-extends, and 160 would load −96). The stride must become
`movel #160,%d7`, which is 6 bytes where `moveq` is 2 — so this one is a
**cave**, not an in-place edit. Same for anywhere 120 is assumed.

**Note on #4.** The inner loop walks *down* from the top LFO, so adding a fourth
means starting `%a2`/`%a3` one record higher — `%a2 = sp@(56) + 40`,
`%a3 = base + 156` instead of `+116`.

### The state arrays must move

Measured previously and confirming the constraint:

```
0x4463ed18  backup             1920 B  -> ends 0x4463f498
0x4463f498  second tick state  1920 B  -> ends 0x4463fc18
0x4463fc18  live               1920 B  -> ends 0x4464039c
0x44640398  next structure
```

**Contiguous wall to wall.** 16 tracks × 4 LFOs × 40 = 2,560 B each, so all
three must be **relocated into the 25 MB region** above `0x466b74d0`, and —
because the BSS clear stops below that — **zeroed by our own code at boot**.
Every `lea` of `0x4463fc18` / `0x4463ed18` / `0x4463f498` repoints.

---

## 3. Runtime slot space — **designed, with a cheaper bound than expected**

The sound accessor `0x400dc02a` was read end to end today. It takes
`(slot, machine, filterType)` and returns a parameter id through **three**
tables:

```
0x400dc02c  moveq #100,%d1        ; <-- THE SLOT BOUND
0x400dc03a  cmpl %a0,%d1
0x400dc03c  bcss <return 0>       ; slot > 100 -> nothing
0x400dc042  addil #-66,%d1        ; slot in 66..68 ?  -> filter table
0x400dc04a  bccs 0x400dc096       ;    0x42c64cd0, 3 entries per filter type
0x400dc04e  cmpl %a0,%d2          ; slot <= 24 ?      -> FLAT table
0x400dc050  bges 0x400dc062       ;    0x42c64b3c, indexed by slot
0x400dc054  cmpl %a0,%d1          ; slot > 64 ?       -> FLAT table
0x400dc056  blts 0x400dc062
0x400dc06e  ...                   ; slot 25..64       -> machine table
                                  ;    0x42c64d18, 40 entries per machine
```

**LFO1–3 (slots 1–24) go through the flat table `0x42c64b3c`, indexed directly
by slot.** So LFO4's slots 101–108 need:

- the bound `moveq #100` at `0x400dc02c` → `moveq #108` — **one byte**;
- the flat table `0x42c64b3c` grown from 101 to 109 longwords and repointed —
  it is built at boot by `param_set_tables_build` (`0x400dc4d0`, `pea 0x194` =
  404 B = 101 entries), so this is a size immediate plus `lea` repointing.

That is materially cheaper than `lfo4-slot-plan.md` assumed, because it assumed
the slot→id mapping was structural. **It is a `moveq` and a table.**

### What is *not* cheaper: the value array

Unchanged from the slot plan, and it is still the real work. The values live
**inside each sound object** at `+0x14 + slot*2`, boxed in at `+0xDD` by the
machine type at `+0xDE`, in an array of **up to 128 objects of 2,388 bytes**
(`0x4003e440`–`0x4003e44e`). It cannot grow.

**The extension array**, as designed in the slot plan and unchanged:

```
ext[obj][param]   128 objects x 8 params x 2 bytes = 2,048 B
```

at a fixed address in the 25 MB region, indexed by the same 0..127 object index
the accessor already computes; slots 0–100 keep reading the object, 101–108 read
`ext`. Needs zeroing at boot, like the tick state.

**The hooks.** 29 sites index the value array; the reachable ones are ~11, and
six of those take their index from one upstream accessor (`0x400dbcc4`,
returning `record[id]+0x04`). The known choke points:

| path | site |
|---|---|
| control → engine | `Sound::updateMirror` `0x4004cb04`, `0x4004cb70` |
| engine → control | reverse copy `0x400dd25e` |
| UI read | `parameter_value_getter` `0x4006408a` |
| generic fill | `0x400440a2` |
| bulk copy | `0x4004c226`, `0x4004c27c` |

---

## 4. Serialization — **designed**, and it is nearly free

**Cracked 2026-09-16.** The pair is symmetric and both halves walk the maps we
already dumped. This is the piece the slot plan called *"not yet scoped and the
one place where 'LFO4's values do not survive a save' would be the failure"*.

### Deserialize — stored → live, at `0x400dd24a`

```
0x400dd24a  pea 0xca                    ; 202
0x400dd24e  clrl %sp@-
0x400dd250  pea %a2@(20)                ; live sound + 0x14 = THE VALUE ARRAY
0x400dd254  jsr 0x401344d8              ; memset(values, 0, 202)
0x400dd25e  lea 0x401fd0b0,%a1          ; THE INVERSE MAP
0x400dd268  lea %a3@(1c,%d0:l),%a4      ; src = stored + 28 + i   (disp8, HEX)
0x400dd26c  movel %a1@+,%d1             ; slot = inverse_map[i]
0x400dd26e  addil #10,%d1
0x400dd276  movew %a4@,%a2@(0,%d1:l:2)  ; live[20 + slot*2] = stored word
0x400dd27a  cmpil #214,%d0              ; 214/2 = 107 iterations
```

### Serialize — live → stored, at `0x400dd6f0`

```
0x400dd6f2  pea %a2@(28)                ; stored + 28
0x400dd6f6  jsr 0x401344d8              ; memset
0x400dd700  lea 0x401fcf20,%a1          ; THE FORWARD MAP
0x400dd70a  lea %a3@(14,%d1:l),%a4      ; src = live + 0x14   (disp8, HEX)
0x400dd70e  movel %a1@+,%d0             ; id = forward_map[i]
0x400dd710  addil #14,%d0
0x400dd718  movew %a4@,%a2@(0,%d0:l:2)  ; stored[28 + id*2] = live word
```

### What this means for LFO4

**The stored block at `+28` is indexed by p-lock id, 107 wide, and the only
translation in either direction is the map.** The reserved fourth-LFO rank ids
— 0, 4, 8, 12, 16, 20, 24, 28 — are already inside that 107, and DNX has
already observed the format storing and reading back a lock in that rank.

So **the persisted format needs no version bump and no new field.** The moment
the forward and inverse maps carry LFO4's eight entries — which `lfo4-slot-plan.md`
already prices as 8 + 8 data edits — the values flow both ways on their own.

Two hooks are still needed, and only because LFO4's slots are 101–108 and the
live array stops at 100:

| # | site | what the hook does |
|---|---|---|
| 1 | `0x400dd276` | slot ≥ 101 → write `ext[obj][slot-101]` instead of `live+20+slot*2` |
| 2 | `0x400dd718` | slot ≥ 101 → read from `ext` instead of `live+0x14` |
| 3 | `0x400dd24a` | the 202-byte memset must also clear the extension array |

**Unchecked:** the serialize loop's iteration bound. The deserialize side is
`cmpil #214` = 107; the serialize side was not read to its `cmp`. If they differ,
that matters.

### The other five records in the same function

Noted so they are not re-derived: `0x400dd390`–`0x400dd468` convert **five**
records from 12 stored bytes to 16 live bytes (dst `%a2+246/262/278/294/310`,
src `%a3+264/276/288/300/312`) through `0x400dd12e`. Not LFO data. The enclosing
function `0x400dd1ea` is the **v3** track converter (`%a3@(4) == 3`); `0x400ddc52`
is the v4 container gate (magic `0xBACEF00C` at `+10411`), 16 tracks, stored
stride 359, live stride 1,163.

## 5. The page view — **designed**; `[MOD]` navigation is not

`LfoPageView` is real and RTTI names it: typeinfo `0x402054a8`, primary vtable
`0x40205614`, constructor `0x4010e322`, called from exactly one site
(`0x4019fb0c`) which builds **one** instance behind a reference-counted handle.

**There is one `LfoPageView`, not three.** A fourth LFO page needs **no new view
class**. The single view serves all three pages, and columns resolve through the
vtable at `+0xBC`, `getColumnParameter`.

### The one site that hardcodes the LFOs

`LfoPageView`'s `+0xBC` is `0x4010dafc`. It calls the base implementation and
then special-cases exactly three parameter ids:

```
0x4010db0e  jsr 0x40063f24         ; base: column -> parameter id
0x4010db18  moveq #81,%d0          ; == 81 ?
0x4010db1e  moveq #91,%d1          ; == 91 ?
0x4010db24  moveb #101,%d0         ; == 101 ?
0x4010db2a  bnew 0x4010dbda        ;   none -> ordinary column
```

Read out of the parameter table at `0x401f7f94`, those three are:

| id | page | `+0x04` | names |
|---|---|---|---|
| 81 | `0x1a` | 6 | `Start Phase` / `LFO1` / `SPH` |
| 91 | `0x1b` | 14 | `Start Phase` / `LFO2` / `SPH` |
| 101 | `0x1c` | 22 | `Start Phase` / `LFO3` / `SPH` |

**`Start Phase`, one per LFO, ten apart.** A scan of the whole image for the
81/91/101 triple returns **exactly one site** — this one. So the page view's
whole LFO-specific knowledge is three constants in one function.

### The edit, and the trap in it

Add a fourth comparison for LFO4's own `SPH` record. **It is not 111.** Ten
apart would suggest it, and id 111 is `Chorus Mix Vol.` on page `0x10` —
checked, not assumed. LFO4's parameter records are repurposed from the ten dead
`ERR` slots (`scripts/build_lfo4_test.py`), so the fourth constant is **whatever
id LFO4's `Start Phase` record actually takes**, and it has to be read off the
built table rather than predicted.

`0x4010dafc` has no slack for a fourth compare, so this is a **cave**.

### `[MOD]` navigation — no handler found, and there is a reason for that

The key handler that advances `0x1a` → `0x1b` → `0x1c` was **not located**. But
the search that failed to find it is itself informative, so it is recorded
rather than left as a blank.

**There is no page-group table in the image.** Three shapes were searched for a
list of group-start pages (`0x10`, `0x16`, `0x1a`, `0x1d`) — as bytes, as words
and as longwords, with slack between them — and all three returned **zero**
hits. Every longword run of `1a 1b 1c` (13 of them) is a generic sequential
index table. The byte table at `0x401d35e8` is a format-migration remap.

**Group membership is expressed as range predicates, not as data.** The
predicate family in `0x400dbdea`–`0x400dbfcc` is exactly a set of page groups:
`<= 4`, `0x05`–`0x0a`, `0x10`–`0x15`, `0x16`–`0x1c`, `0x1d`/`0x16`, and the LFO
range `0x1a`–`0x1c`. There is nowhere else for a group to be defined.

**So the working hypothesis is that `[MOD]` navigation costs nothing extra**
under the `0x1d` design of §5b: if the group is the range test, widening the
range widens the group. **This is a hypothesis, not a finding.** It has one
clean falsifier — flash the §5b edits and press `[MOD]` four times — and if it
is wrong the symptom is a page that cannot be reached, not a broken instrument.

One more thing worth knowing before that build: `0x4012a836`, the out-of-line
`is_lfo_page`, has **zero callers and zero data references**. It is a compiler
artifact; every real use is inlined (`0x4012af7e`, `0x4012af9c`). Editing it
changes nothing, and a cave there would never run — `dnfw fn` says so plainly.

## 5b. The page number: `0x1f` is the expensive choice, `0x1d` is the cheap one

**This is the most consequential thing read today, and it reverses §1's edit.**

Hunting `[MOD]` navigation turned up the rest of the page-predicate family, and
with it the fact that **`0x1a`–`0x1c` is assumed contiguous in more places than
the six range tests already counted**. A seventh kind of site bounds at the
*last* LFO page:

```
0x400dbe5e  ... parameter id
0x400dbe7c  moveq #28,%d1               ; 0x1c
0x400dbe7e  cmpl %a0@(0,%d0:l),%d1      ; vs the record's page
0x400dbe82  scc %d0                     ; page <= 28
```

A page numbered `0x1f` fails that test, fails every `(page - 26) <= 2`, and
fails the per-LFO getter/setter's three-way `26 / 27 / 28` dispatch. **Each one
then needs an exact-match disjunct in a cave.**

### The located sites

| site | form | what it is |
|---|---|---|
| `0x400dbf34` / bound `moveq #2` at `0x400dbf3a` | `(page-26) <= 2` | `SoundParameterSet` ownership |
| `0x400dc6ba` / bound `moveq #2` at `0x400dc6b8` | `(page-26) <= 2` | `param_set_tables_build` routing |
| `0x4012a83c` / bound `moveq #2` at `0x4012a83a` | `(page-26) <= 2` | `is_lfo_page` helper |
| `0x4012af7e` / bound at `0x4012af7c` | `(page-26) <= 2` | inlined consumer |
| `0x4012af9c` / bound at `0x4012afa6` | `(page-26) <= 2` | inlined consumer |
| `0x400dbe7c` | `page <= 28` | bounds at the **last** LFO page |
| `0x4012a85c` / `0x4012a870` / `0x4012a884` | `== 27 / 26 / 28` | per-LFO byte setter into `0x466765b8` |
| `0x4012a8a8` … | `== 27 / 26 / 28` | the matching getter |
| `0x4010db18` | `== 81 / 91 / 101` | `LfoPageView` — `Start Phase` ids |

Ruled out, so they are not re-checked: `0x4017a998` and `0x401cf3f6` carry
`addil #-26` but no page bound — unrelated arithmetic, matching the feasibility
doc's warning that four of its eight hits were exactly that.

### Therefore: LFO4 on page `0x1d`, the TRIG group moved to `0x1f`

Keeping the LFO pages **contiguous** turns almost the whole list into one-byte
edits:

| edit | from | to | bytes |
|---|---|---|---|
| five `(page-26) <= 2` bounds | `moveq #2` | `moveq #3` | 1 each |
| `0x400dbe7c` | `moveq #28` | `moveq #29` | 1 |
| `TrigParameterSet` `0x400dbfa0` | `moveq #29` | `moveq #31` | 1 |
| page-`0x1d` special case `0x4003774e` | `moveq #29` | `moveq #31` | 1 |
| `param_set_tables_build` `0x400dc71e` | `moveq #29` | `moveq #31` | 1 |
| per-LFO getter/setter | — | fourth case, `page == 29` | cave ×2 |
| `LfoPageView` `0x4010db18` | — | fourth `Start Phase` id | cave |

Eight one-byte edits and three caves, against **nine** caves for the `0x1f`
route. The per-track entry at `0x466765b8` is **4 bytes wide with only 3 used**,
so LFO4's byte is already there — offset `+3`.

### Why this is not the probe that failed

Probe v1 and v2 moved the TRIG group `0x1d` → `0x1f` and the pages drew but
read wrong. (**`0x1d` is not just Retrig** — it is 22 records across three
labels: ten unlabelled TRIG parameters, four `Retrig`, eight `Euclidean`. The
earlier "move Retrig" phrasing in this document was loose and is corrected here.)
**That is this same move, minus the classifier.** They renumbered the records
and the routing constant and changed nothing else, so Retrig's parameters became
unclaimed by every predicate above and fell through to the sound set — exactly
the `VEL` = 112 / `PROB` re-aiming LFO2 symptom.

The move is sound. It was the missing half that was fatal. **Stated as a
hypothesis, not a result:** it has not been flashed, and the failure mode if a
site is still missing is the one already seen, not a brick.

## 5c. v3 is built and verifies — the falsifier for §5b

`scripts/build_page_classifier_test.py`, built 2026-09-16.

**It tests one claim and nothing else:** that every consumer of page id `0x1d`
is now known. No LFO4 records, no bounds, no tick, no slots.

A scan for comparisons against 29 **anchored on the 49 sites that load the
parameter table** at `0x401f7f94` — rather than for the bare constant, which is
what returned four unrelated hits and made the earlier cost model wrong — finds
exactly three:

| VA | what it is | in v2? |
|---|---|---|
| `0x400dc71e` | `param_set_tables_build` exact-match arm | yes |
| `0x400dbfa0` | **`TrigParameterSet` ownership predicate** | **no** |
| `0x4003774e` | page-`0x1d` special case for parameter ids 310/311 | **no** |

So v2 moved the records and the *builder* and left the *classifier* behind.
That is the whole explanation of the symptom the owner reported.

**Built and verified:** 22 records (88 bytes) + 3 code bytes, every integrity
field reproduced including the HMAC-SHA256 trailer — which `docs/version-gate.md`
§2 establishes MAIN OS actually checks at flash time, so that is not a formality.

```
page-classifier-test3_DN2_1.11.syx
sha256 eac9fe60972122f106a397b3e5fe577ff7da94adf00fecedbcbe9fdce89f6c33
```

**Not flashed.** Needs the owner's go-ahead and a named transport.

Six observations, in order, the first failure making the rest moot: it boots;
`[TRIG]` draws real defaults rather than `C0` / `0.188` / `PROB 0%`; trig
parameters p-lock; Retrig works; Euclidean works; **and nothing on the TRIG page
moves an LFO** — that last one is the v2 symptom and the one that matters.

All six pass → §5b is proven, `0x1d` is free, and the next build is LFO4's
records plus the five `moveq #2` → `moveq #3` bounds. Still broken → a fourth
consumer exists, and whether the *symptom* changed says how much narrower it is.

## 5d. Use digikit's tools, not hand-rolled scans — 2026-09-16

**Owner's instruction, and it landed on a live example:** *"Always use the
tooling at hand in other reference repos, don't build your own tooling if it is
not needed"* / *"Don't reinvent the wheel unless it is not invented."*

It was said while this document's author was running a hand-written regex scan
for value-array accesses that returned **144 hits, most of them false**. That is
the third time in this project that a hand-rolled scan produced a wrong answer
(`docs/PRINCIPLES.md` §19).

**`m-dwyer/digikit` already ships the tools.** MIT, and `capstone` is already
installed here, so every *static* one runs today:

| tool | job |
|---|---|
| `tools/rttiscan.py` | typeinfo, vtables, vtable load sites, `Class::method` strings |
| `tools/refscan.py` | exhaustive absolute-reference scan into an address range |
| `tools/vtcheck.py` | vtable validation |
| `tools/decompile.py` | decompilation |
| `tools/addrtrace.py` | **hit counts and registers at first hit, by running** |
| `emu/` | boots the firmware under Unicorn, with screen and front panel |

Only the emulator is blocked: it needs **unicorn 2.1.4 plus two of digikit's own
m68k patches** (code-hook CCR sync, EMAC MAC-with-load), built from source. Their
installer is bash + `shasum` + `.venv/bin/python`, so Windows needs the same kind
of port `ghidra/install-coldfire-emac.bat` already does for their Ghidra module.

### What it found in five seconds

`rttiscan.py` on our own DN2 1.11 MAIN OS: **1,047 typeinfo objects, 1,911
vtables, 4,845 vtable load sites, 47 `Class::method` strings.** That is the
class map §1 and §5 of this document derived by hand, one class at a time.

And it answered the `[MOD]` thread that hand-scanning had failed on all
session. **There are ten page views, each built by its own `make_shared`
factory, all in one span:**

| site | view |
|---|---|
| `0x4019f8ec` | `MasterPageView` |
| `0x4019f96c` | `FxPageView` |
| `0x4019f9ec` | `ParametersSeqNoteView` |
| `0x4019fa6c` | `AmpPageView` |
| **`0x4019fae4`** | **`LfoPageView`** |
| `0x4019fba6` | `FilterPageView` |
| `0x4019fc1e` | `MultiSourcePageView` |
| `0x4019fc96` | `MidiParameterPageView` |
| `0x4019fd58` | `ParameterPageView` |
| `0x4019fdd2` | `ParametersSeqNoteView` |

`LfoPageView`'s allocation is **432 bytes** (`pea 0x1b0` at `0x4019fac0`), and
its owner is `0x40061550`–`0x4006188a`, which constructs it with a small integer
argument (`6`) passed by address. **That owner is where `[MOD]` navigation has
to be read next**, and it is a named address rather than a guess.

**Standing rule for this project from here:** before writing any scan, name the
digikit tool that does the job, or say why it does not fit.

## 6. The build, in order

1. Relocate + zero the three tick state arrays (25 MB region).
2. Tick: `moveq #2` → `#3`; stride 120 → 160 via cave; backup size 1920 → 2560;
   `%a2`/`%a3` start +40.
3. Slot bound `moveq #100` → `#108`; grow and repoint the flat table
   `0x42c64b3c`; extension array + zeroing.
4. The ~11 value-array hooks.
5. Classifier: cave on `0x400dbfbc` adding `|| page == 0x1f`.
6. Forward map → 108 entries (cave, 432 B); inverse map 8 entries in place.
7. Parameter records for LFO4's eight parameters (already built).
8. Serialization: two hooks at `0x400dd276` / `0x400dd718`, plus clearing `ext`
   alongside the 202-byte memset at `0x400dd24a`.
9. Page view: cave on `0x4010dafc` adding LFO4's `Start Phase` id.
10. `[MOD]` navigation — **expected to come free with §5b**; verify by pressing
    `[MOD]` four times on the first build that boots.

Steps 1–9 are specified to the byte or to a named cave. Step 10 is a prediction
with a one-press test.

---

## 7. The honest state, against the five named pieces

| # | piece | state |
|---|---|---|
| 5 | classifier | **designed** — mechanism read, edit specified, cave form proven in shipped code. Other cascades unread |
| 2 | tick edit | **designed** — both loops decoded, four edits named, state relocation forced and sized |
| 1 | slot space | **designed** — route chosen, bound found to be a `moveq`, extension array unchanged from the slot plan, 11 hooks listed |
| 3 | serialization | **designed** — both halves read; the stored block at `+28` is indexed by p-lock id, 107 wide, and the maps are the only translation. No format version bump. Three hooks named. Serialize-side loop bound unchecked |
| 4 | page view | **designed** — one shared `LfoPageView`, no fourth class; its entire LFO knowledge is three `Start Phase` ids in one function. **`[MOD]` navigation: no handler found, but no page-group table exists either** — groups are range predicates, so §5b's contiguous design probably carries navigation with it. Hypothesis, with a one-press falsifier |

**Nothing here has been built, and nothing has been flashed.** All five are
specified to the point where code can be written against them. `[MOD]`
navigation is not, and saying otherwise would repeat the mistake that cost three
flashes: a cost model published ahead of the reading that supports it.

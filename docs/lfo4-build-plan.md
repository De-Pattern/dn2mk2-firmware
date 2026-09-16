
# LFO4 — the build plan

**Written 2026-09-16**, consolidating one session's reading against the owner's
instruction to crack five named pieces. It supersedes nothing; it collects what
`lfo4-feasibility.md`, `lfo4-slot-plan.md` and `modulation-matrix.md` establish
and adds what was read today.

**Read the honesty note in §7 before pricing anything from this.** All five
pieces are designed, `[MOD]` navigation included. Nothing is built or flashed.

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

### `[MOD]` navigation — **FOUND**, and it is a page count

**[SUPERSEDES the "no handler found" entry that stood here for part of
2026-09-16.]** That entry concluded, from three closed leads and the absence of
any page-group table, that navigation was probably carried by the range test.
**It is not.** There is an explicit page count, and it was found the moment the
search used digikit's `rttiscan.py` instead of hand-written regex (§5d).

The UI construction function `0x40060e72` registers each page view with a call
of the shape `register(ctx, descriptor, PAGE_COUNT, ...)` immediately before
`make_shared`-ing the view. For `LfoPageView` it does it **twice**:

```
0x40061558  moveq #3,%d1          ; <-- PAGE COUNT = 3
0x4006155a  moveq #6,%d0          ; LfoPageView's own argument
0x40061562  movel #0x401e0048,%d0 ; descriptor
0x4006156c  jsr %a5@              ; register(...)
0x4006157a  jsr 0x4019fb2a        ; make_shared<LfoPageView>(6)

0x40061868  moveq #2,%d1          ; <-- a SECOND registration, count = 2
0x4006186a  moveq #6,%d0
0x40061872  movel #0x401e0000,%d0 ; a different descriptor
0x4006187c  jsr %a5@
0x4006188a  jsr 0x4019fb2a        ; the same view again
```

Neighbouring registrations in the same function use counts 1, 2, 3 and 15 with
their own descriptors, so the third argument is a **count of pages behind one
key**, and `3` for the LFO view is the three LFO pages.

### The edit is NOT one byte — corrected before it was believed

~~`moveq #3,%d1` → `moveq #4,%d1` at `0x40061558`.~~ **[WRONG — corrected the
same day.]** The second argument is not an opaque descriptor: it is a **pointer
into a packed pool of view ids**, and the count is how many to read. The
decompiler's `0x48` is `0x401e0048` truncated to its low byte.

The pool at `0x401e0000` is **128 bytes, 32 longwords, and every one is
claimed** by one of fifteen registrations:

| offset | count | view ids | |
|---|---|---|---|
| `0x00` | 2 | `0x23 0x24` | **LfoPageView, second registration** |
| `0x08` | 1 | `0x22` | |
| `0x0c` | 2 | `0x20 0x21` | |
| `0x14` | 2 | `0x1e 0x1f` | |
| `0x1c` | 1 | `0x1d` | |
| `0x20` | 1 | `0x1b` | |
| `0x24` | 5 | `0x14`–`0x18` | |
| `0x38` | 3 | `0x11 0x12 0x13` | |
| `0x44` | 1 | `0x03` | |
| **`0x48`** | **3** | **`0x04 0x05 0x06`** | **LfoPageView, first registration** |
| `0x54` | 1 | `0x10` | |
| `0x58` | 1 | `0x0e` | |
| `0x5c` | 2 | `0x0c 0x0d` | |
| `0x64` | 5 | `0x07`–`0x0b` | |
| `0x78` | 2 | `0x01 0x02` | |

**Gaps in coverage: none.** So bumping the LFO count from 3 to 4 would read
`0x401e0054` = `0x10`, which belongs to the `(0x54, 1)` registration. LFO4
would silently take another view's id and the failure would look like a UI bug,
not a data-layout bug.

**The real edit** is to relocate the list:

| # | site | change |
|---|---|---|
| 1 | a cave or the 25 MB region | 16 bytes: `04 05 06 <new>` |
| 2 | `0x40061562` `movel #0x401e0048,%d0` | point at the new list — **4-byte immediate** |
| 3 | `0x40061558` `moveq #3,%d1` | `moveq #4,%d1` — 1 byte |

View ids free below `0x30`: **`0x0f`, `0x19`, `0x1a`, `0x1c`**, and everything
from `0x25` up. `0x25` is the safest — above the highest in use, same reasoning
as page `0x1f` in §5b.

### And the second registration is explained

`LfoPageView` is registered twice because it serves **two groups**: ids
`{0x04, 0x05, 0x06}` and ids `{0x23, 0x24}`. Three and two. The natural reading
is sound tracks (three LFOs) and MIDI tracks (two), and it is consistent with
every other view in the pool having exactly one registration.

**CONFIRMED by the owner, 2026-09-16:** *"MIDI tracks only support 2 LFOs in the
factory fw."* So `(0x00, 2)` is the MIDI-track group and `(0x48, 3)` is the
sound-track group, and the two counts are simply the two LFO counts the
instrument ships. The reading is no longer an inference from the pool.

### Decision: sound tracks only

**Owner's call, same day:** LFO4 goes on **sound tracks only**. A third MIDI-track
LFO is wanted, but as a **separate feature**, not folded into this one.

So `(0x00, 2)` is **not touched** by LFO4. Only the sound-track list `(0x48, 3)`
relocates and grows.

That separation is worth more than the bytes it saves: a MIDI LFO3 is the same
eight layers as LFO4 with different addresses, which makes it the **first real
test of `docs/FEATURE-PLAYBOOK.md`** — written from LFO4, applied to something
else. If the playbook is any good, that build should be much shorter than this
one.

**Open, and it must be settled before the build:** why there are *two*
registrations, with counts 3 and 2, both pointing at the same view class with
the same argument. The likely reading is a sound-track group and a MIDI-track
group — MIDI tracks having fewer LFO pages — but that is a guess from the
numbers, and the descriptors `0x401e0048` / `0x401e0000` have not been read.
If LFO4 should appear on MIDI tracks too, the second count moves as well.

This is a hypothesis with a one-press falsifier, unchanged from before — but it
is now a hypothesis about a **named one-byte constant** rather than about
whether a mechanism exists at all.

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

## 5e. What v4 still needs, found after v3 passed — 2026-09-16

v3 passing freed page `0x1d`. Reading the page view for the *next* build turned
up two things §5 and §5b did not have, both found with Ghidra's decompiler
rather than by eye.

### The view-id list is a `std::vector<int>`, not a registration table

`FUN_4019e6fc(vec, src, count)` allocates `count*4` bytes and `memcpy`s `count`
longwords. It is **`std::vector<int>`'s from-array constructor**. So `{4,5,6}` is
a list the view is *handed*, and `LfoPageView` is constructed with it plus a
pointer to the integer `6`:

```
local_24 = 6;
FUN_4019e6fc(vec, 0x401e0048, 3);      // vector<int>{4, 5, 6}
FUN_4019fb2a(vec, &local_24);          // make_shared<LfoPageView>(vec, &6)
```

§5b's **edit is unchanged** — the pool is still packed, the list still has to
move to grow. What was wrong was calling it a registration: nothing registers,
the view simply receives a longer vector.

**Still unknown, and it gates v4:** what maps a view id (`4`, `5`, `6`) to a
parameter page id (`0x1a`, `0x1b`, `0x1c`). They are not numerically related.
Adding a fourth id without knowing what page it resolves to is a guess, and this
project has paid for that twice. The integer `6` is passed to **both** LFO
registrations — the sound one with three ids and the MIDI one with two — so it
is not the LFO count.

### The view clamps its LFO index to 0–2

`LfoPageView` holds the current LFO index at **`+0x90`**, and
`getColumnParameter` clamps it:

```
0x4010dbbc  movel %a2@(144),%d0     ; the LFO index
0x4010dbc0  bges 0x4010dbc6
0x4010dbc2  clrl %d0                ;   < 0 -> 0
0x4010dbc6  moveq #2,%d1            ; <-- THE CLAMP
0x4010dbc8  cmpl %d0,%d1
```

**`moveq #2` → `moveq #3` at `0x4010dbc6`** is a required edit that no earlier
section had. And `+0x90` is read at **ten sites** in the view's code
(`0x4010d980`, `0x4010d99e`, `0x4010d9d0`, `0x4010d9f2`, `0x4010db4e`,
`0x4010db70`, `0x4010db84`, `0x4010dbbc`, `0x4010e1d6`, `0x4010e304`) — each has
to be read for its own bound before v4 is built, because a second clamp left at
2 produces a page that draws but shows LFO3's columns.

### The shape v4 should take

**One question: does a fourth MOD page appear and can it be reached?**

Deliberately *not* included: slot space, the tick, serialization. LFO4's ten
records keep LFO3's `+0x04` slot indices, so the new page **aliases LFO3** —
turning LFO4's `SPD` moves LFO3's `SPD`. That is safe (every slot is real, no
out-of-bounds write) and it is an unambiguous positive control: if the page
draws but the aliasing does not happen, the UI chain is not actually connected.

Pointing the records at slots 101–108 *without* the extension array would read
and write past the 101-entry value array into the machine-type byte at `+0xDE`.
**Do not build that.**
## 5f. The view-id → page mapping, solved — 2026-09-16

§5e listed this as the thing gating v4. It is solved, by decompiling four
functions instead of reading bytes.

### The chain, end to end

```c
// ParameterPageView::getColumnParameter -- 0x40063f24
if (column < 9) {
    desc = FUN_400c2474( *(int*)( *(int*)(this + 0x7c) + *(int*)(this + 0x90) * 4 ) );
    return *(int*)(desc + 8 + column * 4);
}
return 0;
```

| step | what |
|---|---|
| `this + 0x7c` | the **`std::vector<int>` of view ids**, copied in by the base ctor `0x40065bbc` (`param_1[0x1f]`) |
| `this + 0x90` | the **LFO index**, 0–2 |
| `vector[lfo]` | the **view id** — `4`, `5`, `6` for LFO1/2/3 |
| `FUN_400c2474(id)` | **`0x42432C00 + id * 44`**, bounded `id <= 36` |
| `desc + 8 + column*4` | the **parameter id** for that column |

The arithmetic closes exactly: `8 + 9 columns × 4 = 44`. Two pointer fields at
`+0`/`+4`, then nine parameter ids. **37 descriptors × 44 = 1,628 bytes.**

And the bound is not arbitrary: `moveq #36` at `0x400c2474`, and the highest
view id in the pool at `0x401e0000` is **`0x24` = 36**. They match.

### There is no free view id — checked, not assumed

§5b listed `0x0f`, `0x19`, `0x1a` and `0x1c` as "free" because no *LfoPageView*
list contains them. **That was the wrong test.** The table initialiser around
`0x400c9640` writes the `+0` and `+4` string fields of **all 37 descriptors**,
`0x0f` included. Every id is a real, named page belonging to some view.

So LFO4 needs a **38th descriptor at view id 37**, which means:

| # | site | change |
|---|---|---|
| 1 | `0x400c2474` | `moveq #36` → `moveq #37` — 1 byte |
| 2 | the table | 38 × 44 = 1,672 bytes — **needs 44 bytes of slack after `0x4243325C`, or relocation** |
| 3 | a cave | write descriptor 37's two strings and nine parameter ids at boot |
| 4 | `0x40061562` | point the id vector at a relocated `{4,5,6,37}` |
| 5 | `0x40061558` | `moveq #3` → `moveq #4` |
| 6 | `0x4010dbc6` | `moveq #2` → `moveq #3` (the LFO-index clamp, §5e) |

### Settled: the table cannot grow in place

The byte immediately after it is the base of **another** table:

```
0x400c2428  movel %d0,%d1
0x400c242a  lsll #6,%d1                 ; id * 64
0x400c242e  lea %a1@(0,%d0:l:4),%a0     ;   + id * 4   = id * 68
0x400c2434  addil #0x4243325c,%d0       ; a second descriptor table, stride 68
```

`0x4243325C` is `0x42432C00 + 37*44` exactly — the two tables abut with **no
slack**, and the 512 bytes after are densely referenced. **So the 1,672-byte
table relocates into the 25 MB region**, with every `addil #0x42432c00`
repointed. There is one such site (`0x400c2486`).

### Settled: the initialiser *clears* the nine id fields

Per descriptor it writes the two string pointers and then zeroes the rest:

```
0x400c9684  pea 0x4021b584              ; a name string
0x400c968a  pea 0x42432c2c
0x400c9690  clrl 0x42432c08             ; +8
0x400c9696  clrl 0x42432c0c             ; +12
   ...                                  ;  through
0x400c96c0  clrl 0x42432c28             ; +40
```

**Nine `clrl`s — exactly the nine column slots.** So the parameter ids are *not*
static data: they start at zero and are filled at runtime.

### ANSWERED 2026-09-16 by a write watch: the same initialiser fills them

Found with digikit's `tools/bootwatch.py` under the emulator, which reports the
writing PC directly. Watching `0x42432cb0:36` (descriptor 4 = LFO1) through a
cold boot:

```
[26632974] 0x42432cb8  value 0x4b  pc 0x400c985e
[26632976] 0x42432cbc  value 0x4c  pc 0x400c9868
[26632979] 0x42432cc0  value 0x4d  pc 0x400c9874
[26632981] 0x42432cc4  value 0x4e  pc 0x400c987e
[26632984] 0x42432cc8  value 0x4f  pc 0x400c988e
[26632986] 0x42432ccc  value 0x51  pc 0x400c9898
[26632989] 0x42432cd0  value 0x52  pc 0x400c98a8
```

`0x4b`…`0x52` are **75, 76, 77, 78, 79, 81, 82** — LFO1's parameter ids, from
the record table. (LFO1's block is ids 75–84 and the descriptor holds nine of the
ten; **80, `SLEW`, is skipped** — nine columns, ten parameters.)

And the writes are in the **same initialiser**, immediately after the `clrl`s:

```
0x400c985a  moveq #75,%d0
0x400c985c  moveq #76,%d1
0x400c985e  movel %d0,0x42432cb8        ; column 0
0x400c9864  moveb #77,%d0
0x400c9868  movel %d1,0x42432cbc        ; column 1
   ...
```

**So the ids are static after all**, written one column at a time. My earlier
scan missed them because it looked for `movel #imm,abs.l` (`23fc`) and the
compiler emitted `movel %dN,abs.l` (`23c0`/`23c1`) with the value loaded into a
register first.

**What this settles for v4:** the cave must write descriptor 37's nine ids
itself — LFO4's records on page `0x1d` will *not* populate it automatically.
Nine `movel`s plus two string pointers, in the same shape the initialiser
already uses, hooked after `0x400c98a8`.

~~Still open, and it is the last thing gating v4's cave: *what* fills them.~~
The accessor `0x400c2474` has **17 callers**; the ones sampled
(`0x4005c5b4`, and the `getColumnParameter` family) all **read** `desc + 8 + n*4`
rather than write it. No `movel #imm,abs.l` targets the table either.

Why it matters rather than being a detail: if the ids are filled by walking the
parameter records, then LFO4's ten records on page `0x1d` would populate
descriptor 37 **automatically**, and the cave only has to create the descriptor
rather than write nine ids into it. If they are filled per-view from static
lists, the cave writes them. The two designs differ by more than the bytes.
## 5g. v4 PASSED — navigation is solved; one renderer left — 2026-09-16

`scripts/build_lfo4_nav_test.py`, flashed the same day. **All five observations
passed**, including the positive control: editing the fourth page moves LFO3.

**So the navigation half of LFO4 is done**, and it cost far less than §5b
projected — no table relocation, no cave code, no 38th descriptor:

| VA | change |
|---|---|
| `0x402cf52c` | 16 bytes: the id vector `{4, 5, 6, 6}` |
| `0x40061564` | vector pointer → `0x402cf52c` |
| `0x40061558` | `moveq #3` → `moveq #4` |
| `0x4010dbc6` | `moveq #2` → `moveq #3` |

That is the *duplicate-page* form. A page with **its own** parameters still needs
the 38th descriptor and the table relocation §5f prices — v4 proves the view
will host a fourth page and drive it, not that LFO4 has one.

### The one defect: the waveform graph is blank on page four

Owner's report, and it is precise. The wave display is fetched through

```
0x4010d980  movel %a2@(144),%d0            ; the LFO index
0x4010d984  moveal %sp@(18,%d0:l:4),%a0    ; <-- a 3-element array
...
0x4010d9a2  movel %sp@(30,%d0:l:4),%d3     ; <-- and a second one
```

**Two stack arrays indexed by the LFO index**, three entries each. Index 3 reads
past them, so the graph draws nothing and nothing else breaks.

This is worth stating as a method result, not just a bug: it is **one of the ten
`+0x90` sites §5e listed as unread**, and no bound-scan would have found it,
because *there is no bound* — just an array that happens to be three long. The
device found it in one flash. That is the argument for cheap probe builds over
exhaustive static reading, and it belongs in `docs/FEATURE-PLAYBOOK.md`.

### The hunt so far: four hypotheses, all eliminated

Recorded because a closed path is a signal, and because the next person should
not re-run these.

**1. ~~`sp@(18,%d0:l:4)` is a three-element array of per-LFO pointers.~~ Wrong.**
Reading the prologue properly — `lea %sp@(-32),%sp` then `moveml` of six
registers — puts the saved registers at `sp@0..23`, **eight bytes of locals at
`sp@24..31`**, the return address at `sp@32`. So `sp@(0x18)` is `sp@24`, and the
two values written there are `17` and `119` (`0x4010d962`, `0x4010d97c`). Those
are **coordinates**, and `%a0` is used as a scratch integer (`pea %a0@(6)` →
23), not dereferenced. It is a two-way Y selection, not an LFO array.

**2. ~~An untouched `moveq #2` bound in the view.~~ Not found.** The range
`0x4010d400`–`0x4010e500` holds seven `moveq #2` sites. `0x4010dbc6` is the one
v4 already patched; `0x4010d876` pairs with a `moveq #3` but is a mode switch on
a vtable pointer; `0x4010ddc2`/`0x4010ddc6` set `%d4` to 0–3 from a comparison
against **63**, a zone classifier. None is an LFO-index bound.

**3. ~~The graph is drawn from the runtime LFO tick state.~~ Wrong.** It would
have been a satisfying answer — LFO4 has no tick state, so nothing to draw — but
the three state bases `0x4463fc18`, `0x4463ed18` and `0x4463f498` are referenced
**only** from the tick itself (`0x40137342`–`0x4013780e`). The view never reads
them.

**4. ~~A separate waveform/graph class the view owns three of.~~ No such class.**
`rttiscan.py` over the whole image finds no `Wave`, `Graph`, `Curve`, `Shape` or
`Plot` type other than `SampleWaveformsFactory`, which is for sample display.
The graph is drawn inline by `LfoPageView`.

### What is established, and the next instrument

The LFO index lives at `this+0x90` and the view's ten uses of it are all
**reads** — `movel`/`moveal`/`pea` of `%a2@(144)`. **Nothing in the view's code
range writes it**, so the page-change handler that sets it is elsewhere, and
whatever bounds *that* is the likeliest owner of the blank graph.

**The next move is a write watch on `this+0x90` under the emulator**, which is
the same technique that settled the descriptor-id question in one run
(§"ANSWERED 2026-09-16 by a write watch"). `LfoPageView` is a 432-byte
allocation (`pea 0x1b0` at `0x4019fac0`) built at a single site, so its address
is recoverable at runtime; watching `+0x90` reports the writer's PC directly
instead of another round of pattern-matching.

**This does not block LFO4.** The graph is cosmetic, every functional
observation passed, and v5 — the 38th descriptor and LFO4's own records — does
not depend on it.

## 5h. v5 built: LFO4 as its own page — 2026-09-16

`scripts/build_lfo4_page_test.py`. Gives LFO4 its **own records and its own page
descriptor**, where v4 pointed the fourth page at LFO3's.

**Deliberately not included:** independent values. LFO4's records keep LFO3's
`+0x04` slot indices, so editing page four still moves LFO3. That is §3's
extension-array work and it is v6.

| part | status |
|---|---|
| TRIG group `0x1d`→`0x1f`, three classifier bytes | proven, v3 |
| id vector, length, LFO-index clamp | proven, v4 |
| LFO4's ten records on page `0x1d` | new |
| six page-range bounds widened | new |
| a 38th descriptor via a cave | new |

The three new parts are **not separable** — records without a descriptor draw
nothing, a descriptor without records has nothing to name, and neither is
reachable unless the range tests claim `0x1d`. One question, three parts.

### The descriptor cave, and why it beats relocating the table

§5f priced a 38th descriptor as a relocation of 1,672 bytes. A **cave on the
26-byte accessor** is far smaller, and it assembled and applied clean:

```
0x402d0664  movel %sp@(4),%d0
0x402d0668  cmpil #37,%d0
0x402d066e  bnes 0x402d0688
0x402d0670  lea 0x42432d08,%a0        ; descriptor 6 (LFO3)
0x402d0676  lea 0x402d0800,%a1        ; ours
0x402d067c  movel %a0@,%a1@           ; its two string pointers, at runtime
0x402d067e  movel %a0@(4),%a1@(4)
0x402d0684  movel %a1,%d0
0x402d0686  rts
0x402d0688  moveq #36,%d1             ; replayed stock
0x402d068a  movel %a2@(4),%d0
0x402d068e  jmp 0x400c247a            ; back into the accessor
```

The two string pointers are copied **at runtime** because they are heap objects
the boot initialiser assigns (`0x401ce6d6`); they are not in the image. The nine
parameter ids are static and ours: `[1, 2, 3, 4, 5, 12, 13, 14, 10]`, mirroring
LFO3's `[95, 96, 97, 98, 99, 101, 102, 103, 10]` — same shape, same skipped
`SLEW`, same shared `Track Level` in column 8.

### A guard earned its keep

`scripts/build_lfo4_test.py` names `0x4026EFF6` as *"16 zero bytes of
unreferenced padding"* for the `LFO4` page-label string. **That is true on 1.10E
and false on 1.11**, where it reads `4b fc 7e 00 45`. v5's zero-check refused,
and the label moved into the run already verified free at `0x402cf52c`.

Anything else anchored on that address for 1.11 is suspect. **`build_lfo4_test.py`
itself still carries it**, and its default image is 1.10E, so it is not wrong
today — but it would be if re-pointed at 1.11.

```
lfo4-page-test5_DN2_1.11.syx
sha256 1d9c2989138e1c9e517c15af5ea21c04a762e36e9556b52408a5a71398d99f6d
```

21/21 integrity checks, HMAC reproduced. **Not flashed.**

Observation list in the module docstring. The discriminating one: if page four
shows **LFO3's** parameter names, the cave did not run; if it shows LFO4's, it
did.

## 5i. v5 on hardware: the page is real, the widgets are not — 2026-09-16

Owner: *"LFO4 shows now all round potentiometer controllers (like normal value
controllers) so no graph for the wave, no graph in squared view for fade, etc."*

So the page exists and draws LFO4's own columns — the descriptor cave ran — but
**every control falls back to the default rotary widget**. In v4, where page four
borrowed LFO3's descriptor and therefore LFO3's parameter ids, the specialised
widgets worked and only the wave graph was blank. The difference between the two
builds is the parameter ids.

**Therefore widget selection is keyed on parameter id.**

### And the ids cannot be moved to fix it

This is the constraint, and it is structural. LFO4's records live at the dead
`ERR` ids **1–5, 11–14, 17** — scattered and low. The LFO block is **75–104**,
and the table immediately after it is **not free**:

| ids | what |
|---|---|
| 75–84 | LFO1 |
| 85–94 | LFO2 |
| 95–104 | LFO3 |
| 105–112 | **Chorus** |
| 113–122 | **Delay** |
| 123+ | **Reverb** |

There is no free id adjacent to the LFO block, so LFO4's parameters can never
sit inside a contiguous "is an LFO parameter" range however they are allocated.
Growing the 321-record table does not help either — new ids land at 321+, still
outside every range.

**So any predicate that identifies an LFO parameter by id must be taught LFO4's
ids explicitly.** That is the shape `TrigParameterSet` already ships (an
exact-match disjunct) and the shape §5's `Start Phase` triple already needs.

### What is found so far, and what is not

Code sites naming an LFO id triple, from a structural scan for `(n, n+10, n+20)`
within 110 bytes:

| parameter | ids | sites |
|---|---|---|
| `MULT` | 76/86/96 | `0x400dbdbc` |
| `DEST` | 78/88/98 | `0x400397da`, `0x40039a9a`, `0x40039cbc`, `0x40039ebc`, `0x40066d27`, `0x40066d5c` |
| `SPH` | 81/91/101 | `0x4010db18` |
| `MULT` (2nd) | 84/94/104 | `0x400dbd4c` |

**No `WAVE` triple (79/89/99) exists**, and no general 75–104 range test was
found. So the wave graph and the `FADE` square view are selected some other way,
and that way is **not yet located**. Guessing at it is what this section refuses
to do.

### The instrument for it

The widget choice is a decision made per column at draw time, which makes it a
**trace question, not a scan question** — the same class as the descriptor-id
writer that a `bootwatch` run settled in one go after an hour of failed
greps. Drive the emulator to the LFO page, hook the draw path, and compare the
widget decision for parameter 99 (`WAVE`, LFO3) against parameter 5 (`WAVE`,
LFO4).

### 5i-b. The disjunct is confirmed, and why the WAVE scan missed it — 2026-09-16

**A logical constraint first, which narrows this more than any scan.** `v5`
clones the **whole 60-byte record** from LFO3 and overrides only page id, CC,
NRPN, page label and modmask. So if the widget were chosen from *any* record
field — including the formatter at `+0x34` — cloning would have preserved it.
The widgets went plain anyway. **Therefore the decision cannot come from the
record; it is keyed on the parameter id**, exactly as §5i concluded from the
v4/v5 difference.

**The predicate's shape is now read, not inferred.** Inside `LfoPageView`'s
vtable slot 23 (`0x40066c76`), at `0x40066d5c`:

```
40066d5c  moveq #78,%d0     ; LFO1 DEST
40066d5e  cmpl  %d3,%d0     ; %d3 = the parameter id
40066d60  beqs  ...
40066d62  moveb #88,%d0     ; LFO2 DEST
40066d66  cmpl  %d3,%d0
40066d68  beqs  ...
40066d6a  moveb #98,%d0     ; LFO3 DEST
40066d6e  cmpl  %d3,%d0
```

An **exact-match disjunct**, which is the shape §5i predicted LFO4 would have to
be taught explicitly.

#### Why §5i found no WAVE triple, and it is not because there is none

**GCC emits the first comparison as `moveq #n,%dX` and the rest as
`moveb #n,%dX`** (`0x103c 00nn`). A scan for three uniform immediates cannot see
that. Re-running §5i's `(n, n+10, n+20)` search while allowing both encodings:

| parameter | ids | code sites |
|---|---|---|
| `MULT` | 76/86/96 | `0x400dbdbc` |
| `DEST` | 78/88/98 | `0x400397da` `0x40039a9a` `0x40039cbc` `0x40039ebc` **`0x40066d5c`** |
| ? | 80/90/100 | — data only |
| `SPH` | 81/91/101 | `0x4010db18` |
| `MODE` | 82/92/102 | — data only |
| ? | 84/94/104 | `0x400dbd4c` |

**`WAVE` (79/89/99) and `FADE` (77/87/97) still have no code triple**, now
tested against both encodings. So §5i's conclusion survives a better scan: those
two widgets are selected some other way, and that way is still unlocated.

#### What slot 23 actually is, so it is not mistaken for the answer

`0x40066c76` opens with a **16-iteration loop** (`moveq #16,%d0; cmpl %d2,%d0;
bnes`), `%d2` the track index, with the `DEST` disjunct inside it. That is
**per-track destination resolution** — `DEST`'s value names another parameter —
not widget selection. It is where the disjunct shape was read, not the thing
being hunted.

#### The vtable, for whoever picks this up

`LfoPageView` vtable `0x40205614`. Slots 20–27 are a cluster in `0x4006xxxx`
that look like the per-column accessors:

```
20 0x40066df0   21 0x4006408a (parameter_value_getter)   22 0x40063fd6
23 0x40066c76 (per-track DEST)   24 0x40064224   25 0x4006415c
26 0x400642a6   27 0x400641c2
```

**The instrument is unchanged and is now available**: `--trace-ui` runs on
Digitone II 1.11 as of today, so hook these slots during an LFO page draw and
see which is called per column and what it returns. That is §5i's own
prescription, and two further scans since have not beaten it.

### 5i-c. FOUND: the WAVE/SPH widget predicate is a bitmask — 2026-09-16

**Located by tracing, exactly as §5i prescribed**, after three scans failed. It
sits inside `LfoPageView`'s **vtable slot 4**, `0x4010e0b4`, which the emulator
shows firing **92 times** while the LFO page is on screen:

```
4010e12c  moveq #22,%d1
4010e132  movel %d7,%d0          ; %d7 = the parameter id
4010e134  addil #-79,%d0         ; id - 79
4010e13e  cmpl  %d0,%d1
4010e140  bcss  0x4010e154       ; unsigned: out of range -> false
4010e142  moveb #1,%d1
4010e146  lsll  %d0,%d1          ; 1 << (id - 79)
4010e148  andil #0x501405,%d1    ; the membership mask
4010e14e  sne   %d1
```

`0x501405` has bits **0, 2, 10, 12, 20, 22**. Plus 79, that is:

| id | 79 | 81 | 89 | 91 | 99 | 101 |
|---|---|---|---|---|---|---|
| | LFO1 `WAVE` | LFO1 `SPH` | LFO2 `WAVE` | LFO2 `SPH` | LFO3 `WAVE` | LFO3 `SPH` |

**`WAVE` and `SPH` for all three LFOs, and nothing else.** That matches the panel
exactly: the sine curve in braces spans the `WAVE` and `SPH` columns as a single
widget (`docs/img/emu-lfo-page-stock-111.png`).

#### Why every scan missed it, and the rule that follows

**There is no comparison against 79, 89 or 99 anywhere in this code.** The ids
are encoded as **bit positions in a mask**. §5i's `(n, n+10, n+20)` scan, and the
two re-runs after it — one allowing GCC's mixed `moveq`/`moveb` encodings —
could never have found this, because the constants being searched for **do not
appear in the instruction stream at all**.

A membership test of the form `1 << (x - base) & mask` erases its own operands.
Scanning the whole image for that *idiom* instead finds **exactly four** sites,
of which this is the only LFO one:

| site | base | mask | ids |
|---|---|---|---|
| `0x400dbd3e` | 17 | `0x0001f3` | 17,18,21,22,23,24,25 |
| `0x400dbdae` | 11 | `0x0004c7` | 11,12,13,17,18,21 |
| `0x400dbe1c` | 11 | `0x007805` | 11,13,22,23,24,25 |
| **`0x4010e142`** | **79** | **`0x501405`** | **79,81,89,91,99,101** |

**The rule: when looking for a set membership test, scan for the idiom, not for
the members.** Four hits against three failed scans.

#### What LFO4 needs

LFO4's `WAVE` is id **5** and its `SPH` is id **12** (cloned from LFO3's 99 and
101 into the dead `ERR` slots). Both are far **below** the base of 79, so
`id - 79` underflows and the unsigned `cmpl` rejects them — which is precisely
the plain-rotary fallback the owner reported.

The mask cannot be widened to reach them: bits are relative to 79 and 5 is 74
below it. So this predicate must be **taught the two ids explicitly**, which is
the exact-match disjunct shape §5i predicted. A cave on the range check at
`0x4010e134`, adding `|| id == 5 || id == 12` before the existing test, is the
smallest form.

#### Still unfound: `FADE`

`FADE` is 77/87/97, and **no bitmask predicate covers them** — the only LFO one
is the table above. So the squared `×` view is selected by yet another
mechanism, and it remains open. It is now the last piece of §5i.

### 5i-d. And the blank graph: a three-way branch on the LFO index — 2026-09-16

Reading on past the bitmask predicate in the same method (`LfoPageView` vtable
slot 4, `0x4010e0b4`) reaches the graphic block, and it explains the **other**
defect — v4's blank waveform graph — which §5g left open.

After the column loops:

```
4010e1d6  movel %a2@(144),%d0     ; view + 0x90 = the LFO index
4010e1da  bnes  0x4010e228        ; not 0 -> try 1
4010e1e6  pea 0x4f ... jsr %a3@   ; 79   via 0x4006538e
4010e1f6  pea 0x51 ...            ; 81
4010e202  pea 0x52 ...            ; 82
4010e212  pea 0x4b ...            ; 75
4010e21e  pea 0x53 ...            ; 83
4010e228  moveq #1,%d1 / cmpl / bnes 0x4010e278
   ... 0x59 0x5b 0x5c 0x55 0x5d   ; 89 91 92 85 93
4010e278  moveq #2,%d1 / cmpl / bnes 0x4010e2f0
   ... 0x63 0x65 0x66 ...         ; 99 101 102 ...
```

**Five ids per LFO, hardcoded, one branch per index:**

| index | SPD | WAVE | SPH | MODE | DEP |
|---|---|---|---|---|---|
| 0 | 75 | 79 | 81 | 82 | 83 |
| 1 | 85 | 89 | 91 | 92 | 93 |
| 2 | 95 | 99 | 101 | 102 | 103 |

**There is no branch for index 3.** `moveq #2; cmpl; bnes` falls straight past the
end, so a fourth LFO draws none of these five graphics at all.

#### This resolves both reported defects, and they are different bugs

The two symptoms the owner reported across v4 and v5 have **separate causes**,
which is why they behaved differently:

| build | page index | ids on the page | symptom | cause |
|---|---|---|---|---|
| **v4** | 3 | LFO3's (95–104) | widgets fine, **graph blank** | bitmask passes on LFO3 ids; **this block has no index-3 branch** |
| **v5** | 3 | LFO4's (1–17) | **all plain**, graph blank | bitmask fails on the new ids **and** no index-3 branch |

§5g recorded v4's blank graph as "the one defect" and §5i recorded v5's plain
widgets as another. **They are two independent sites**, and both must be fixed:

1. **`0x4010e148`** — the membership mask `0x501405`, base 79. Teach it ids
   **5** (LFO4 `WAVE`) and **12** (LFO4 `SPH`).
2. **`0x4010e1d6`ff** — the index branch chain. Add an index-3 arm calling
   `0x4006538e` with LFO4's **1, 5, 12, 13, 14** (SPD, WAVE, SPH, MODE, DEP).

Both are caves rather than immediates: the mask cannot reach ids 74 below its
base, and the branch chain has no spare arm.

#### What is still open

`MULT`, `FADE` and `DEST` are **not** in either list — this block draws only five
of the eight LFO parameters. So `FADE`'s squared `×` view is selected by neither
mechanism found so far, and remains the last unlocated piece of §5i.

### 5i-e. The per-column draw path, end to end — 2026-09-16

`LfoPageView` vtable slot 4 (`0x4010e0b4`), read in full. Per column:

```
4010e0d0  lea 0x4006538e,%a5       ; the graphic helper the index arms call
4010e0d6  lea 0x40113558,%fp       ; flag helper A
4010e0f0  moveal %a0@(188),%a0     ; vtable +0xBC = slot 47 = 0x4010dafc
4010e0f4  jsr %a0@                 ; getColumnParameter(this, column)
4010e0f8  movel %d0,%d7            ; %d7 = the parameter id
   ...    1 << (id - 79) & 0x501405          -> the WAVE/SPH flag  [5i-c]
4010e164  jsr %fp@                 ; flag helper A (0x40113558)
4010e176  jsr 0x40113346           ; flag helper B
4010e1a0  jsr %a4@                 ; a1@(180) = vtable +0xB4 = slot 45 = 0x4006448a
                                   ; the per-column draw, 11 stack arguments
```

So the widget decision is **not one test**. The id comes from slot 47, a handful
of flags are computed beside it, and slot 45 draws from the flags rather than
from the id — which is why disassembling slot 45 finds **no id comparisons at
all**.

#### The remaining lead for `FADE`

`0x40113346` is a **table lookup, not a predicate**:

```
40113348  moveq #9,%d2      ; bound: 9 columns
40113352  cmpl  %d1,%d2
40113358  lsll  #4,%d2      ; x 16
40113364  addil #232,%d0    ; base + 232 + column*16
```

A **16-byte per-column record at +232**, bound at 9 columns — and an LFO page has
exactly nine columns. `0x40113558` calls it four times.

**If the remaining widget kinds are fields in that record, they are data, not
code** — which would explain why `FADE` (77/87/97) survives every code scan,
including the idiom scan that found the `WAVE`/`SPH` mask. Reading that record's
layout is the next step, and it is a read rather than a hunt.

#### Method note: the scans were never going to work

Four scans failed on §5i — the original triple scan, a mixed-encoding rerun, a
per-id table hunt, and an immediate scan of slot 45. The two things that worked
were **running the firmware to see which method executes**, and then **reading
that method top to bottom**. Both mechanisms found so far sat within forty bytes
of each other in one function, and neither mentions the ids it acts on: one
encodes them as bit positions, the other as branch arms on an index.

### 5i-f. The v4/v5 confound, raised and closed — 2026-09-16

Writing the problem up for a second opinion surfaced a possible flaw in the
inference everything above rests on, so it is recorded with its resolution
rather than left implicit.

**The worry.** §5i concludes "widget selection is keyed on parameter id" from
the v4/v5 difference: v4 borrowed LFO3's descriptor and drew correct widgets,
v5 used LFO4's own ids and drew plain ones. But v4 borrowed the **whole**
descriptor, so column layout was identical too. If widget choice were keyed on
**column position** rather than id, the same evidence would fit — and the
20-byte per-column records at `view+0x94` really are indexed by column, which
makes that alternative concrete rather than hypothetical.

**The resolution, from this file's own §5f.** The descriptor is **44 bytes:
`+0`, `+4`, then nine parameter ids** — `37 × 44 = 1,628 bytes`, fully
accounted for. There is no spare field in it, so it cannot carry a widget kind.

And v5's cave copies exactly that header:

```
move.l (%a0),(%a1)
move.l 4(%a0),4(%a1)
```

eight bytes, then the build writes LFO4's ids into the nine column slots. **So
v5 preserved the header byte-for-byte and changed only the ids.** The two builds
differ in the ids and nothing else, and the inference stands.

**Worth keeping as a method note anyway.** The confound was real in the sense
that the *stated* reasoning did not exclude it; it took a separate fact from
§5f to close. An experiment that changes one visible thing can still change a
second invisible one, and "v4 used LFO3's descriptor" was doing exactly that
until the descriptor's size was checked.

### 5i-g. The FADE encoding hypothesis: narrowed, not settled — 2026-09-16

**DNX's proposal**, from measuring 53,248 sound records: the squared view goes to
parameters that are **bipolar but not fine-resolution**, and `FADE` is the only
one on the LFO page with that combination. If widgets key on value encoding
rather than id, there is no predicate naming 77/87/97 to find — which is what
four failed scans look like.

#### The parameter record carries exactly that, and it is a new field

Reading the record against known ids (values are **x256 fixed point**):

| id | | `+0x0c` max | `+0x10` default | **`+0x14` fine** |
|---|---|---|---|---|
| 95 | SPD | 127.99 | 112 | **1** |
| 96 | MULT | 23 | 3 | 0 |
| 97 | **FADE** | 127 | **64** | **0** |
| 99 | WAVE | 6 | 0 | 0 |
| 103 | DEP | 127.99 | **64** | **1** |

**`+0x14` is the fine-resolution flag**, not previously named in this repository.
These reproduce DNX's corpus measurements exactly — SPD rests at 112 and carries
fine; FADE rests at 64 and does not; DEP rests at 64 and does. **Two methods on
one object that could have disagreed**, which is corroboration in the sense
`docs/lfo4-slot-plan.md` now defines.

Selecting on `default == 64 && fine == 0` across the table gives **29
parameters**, of which exactly three are the LFO pages' `FADE`.

#### The test, and why it is not decisive

`PAN` (id 71, Amp page, bipolar non-fine) draws a **bowtie with a centred `×`** —
emphatically not a plain rotary. Within the LFO page the complement also holds:
`DEP` is bipolar **and fine** and draws a round knob; `SPD` is unipolar and fine
and draws a round knob.

So **fine-resolution parameters get knobs**, and this bipolar non-fine one does
not. Directionally consistent.

**But it is a different glyph.** `FADE` draws a rectangle with `×` and a dotted
baseline; `PAN` draws a bowtie. So the test shows "bipolar non-fine gets *a*
specialised bipolar widget", not "gets *the* squared view".

#### And v5 falsifies the strong form outright

LFO4's `FADE` is a **clone** of LFO3's, so it carries `default == 64` and
`fine == 0` identically. **It drew plain anyway.** If the encoding alone selected
the widget, cloning would have preserved it.

**Therefore the encoding is at most necessary, not sufficient** — something else
gates it, and that gate is what still has to be found. The hypothesis is not
dead: it explains why no predicate names 77/87/97, and it may well be the
*first* half of a two-part test whose second half is an id or page check.

#### One observation worth keeping for §13.1 and the widget work

The Amp page draws `ATK`/`DEC`/`SUS`/`REL` as a **single envelope curve spanning
four columns**, exactly as the LFO page draws `WAVE`/`SPH` as one sine across
two. So multi-column composite widgets are a general mechanism here, not an LFO
peculiarity.

### 5i-h. The manual sharpens the criterion, and warns against one conflation

`dn_sysex/00_References` carries the DN2 user manuals, already extracted to
markdown, and they settle what these parameters *are* even though they cannot
say what selects a widget.

**On `FADE`:** *"Fade In/Out makes it possible to fade in/fade out the LFO
modulation. The knob is bipolar. Positive values give a fade-out, negative
values give a fade in. 0 gives no fade in/fade out. (-64-63)"* So the squared
`×` with a dotted baseline is depicting a **fade envelope about a centre**,
which is exactly what the glyph looks like once you know.

#### The conflation to avoid: "bipolar" in the manual is not "default 64"

**`SPD` is described as bipolar too** — *"The knob is bipolar. The LFO cycle can
be played backward by using negative values."* But its record reads **default
112, fine 1**, and it draws a plain knob.

So the manual's "bipolar" is a **statement about the control's meaning**, not
about its stored encoding. Several parameters are bipolar in that sense without
resting at 64. **Do not use the manual's wording as a proxy for the record's
default**, and do not read DNX's corpus measurement as being about the same
property — theirs is `rests at 64`, measured, which is the useful one.

#### The criterion, restated on what was actually measured

| | `+0x10` default | `+0x14` fine | widget |
|---|---|---|---|
| `FADE` | **64** | 0 | `×` in a box, dotted baseline |
| `PAN` | **64** | 0 | `×` in a bowtie |
| `MULT` | 3 | 0 | boxed number |
| `SPD` | 112 | **1** | plain knob |
| `DEP` | 64 | **1** | plain knob |

**Centred default *and* non-fine** picks out exactly the `×`-family widgets, and
each of the other three rows fails it on a different axis. That is a tighter fit
than "bipolar", and it is the form worth testing further.

**It still does not explain v5.** LFO4's `FADE` clone carries `default 64,
fine 0` and drew plain, so a second gate remains — §5i-g's conclusion is
unchanged.

### 5i-i. [WRONG - corrected within the hour] The encoding does not select the widget

§5i-g and §5i-h recorded "centred default and non-fine" as a tight fit for the
`×`-family widgets. **It is falsified**, by a screenshot that had already been
captured before either was written.

The filter page's `ENV` has a record byte-identical to `FADE`'s and `PAN`'s:

| id | | max | default | fine | widget drawn |
|---|---|---|---|---|---|
| 97 | `FADE` | 127 | 64 | 0 | `×` in a box, dotted baseline |
| 71 | `PAN` | 127 | 64 | 0 | `×` in a bowtie |
| **49** | **`ENV`** | **127** | **64** | **0** | **a round bipolar knob** |

`GAIN` (42), `DEC` (46) and `REL` (48) share the same encoding again. **Three
identical encodings, three different widgets.** So the encoding cannot be what
selects one, and DNX's hypothesis is dead as stated rather than merely
insufficient — §5i-g's "necessary but not sufficient" was too generous.

**What survives:** the `fine` flag at `+0x14` is real and newly named, and the
observation that every *fine* parameter checked draws a plain knob still stands.
It is the converse that fails: non-fine does not imply a special widget.

#### The process failure, which is the part worth keeping

The falsifying frame was captured in the **same run** as the `PAN` frame that
appeared to support the hypothesis. It sat unexamined while two sections were
written on the strength of the supporting half. **The supporting evidence was
read and the rest of the same capture was not.**

That is a sharper version of a habit that has cost this session repeatedly: the
stride-8 that was glyph rows, the `0x4059D1C0` that was a TCB, the counter that
kept counting when the knob turned back. Each time the disconfirming check was
cheap and available. Here it was already on disk.

**The rule: when a capture supports a hypothesis, look at the rest of that same
capture before writing it up.**

### 5i-j. [OWNER, and it closes the whole line] Glyphs are designed, not derived

**From the owner, 2026-09-16:** *"Glyphs are not tied to the parameter bipolar
character or any other character, they are designed elements to improve UX. For
instance, the bowtie: when you move the knob it gets the side you move it
towards filled and the centre vertical line moves with it. And has nothing to do
with how fade is visualised."*

**So a widget is assigned to a parameter, not computed from it.** The bowtie is
an animated pan indicator with its own behaviour; `FADE`'s box-and-dotted-line
draws a fade envelope about a centre; they are different designs for different
controls and share nothing but a passing resemblance in a 1-bpp screenshot.

#### What this retires

Everything in §5i-g and §5i-h that tried to *derive* the widget from the record
is closed, not merely falsified by `ENV`. There was never a property to
correlate: three parameters sharing an encoding and drawing three different
glyphs is the **expected** result of design, not an anomaly needing a second
gate. §5i-g's "necessary but not sufficient" and §5i-h's "tighter fit" were both
looking for a rule that does not exist.

**And it explains the two mechanisms that were found.** Both are explicit id
sets, which is exactly what assignment looks like in code:

- the `1 << (id - 79) & 0x501405` mask, naming `WAVE` and `SPH` for three LFOs;
- the three index arms, each naming five ids outright.

Neither derives anything. Each is a **list of which parameters get which
drawing**.

#### What it means for LFO4, and it is the practical half

**There is no shortcut.** Every specialised widget LFO4 wants must be assigned to
LFO4's ids explicitly, one site at a time. A clone inherits nothing, because the
assignment lives outside the record — which is exactly what v5 demonstrated and
what §5i concluded before this detour began.

The remaining target is unchanged and now better motivated: the **20-byte
per-column descriptor** at `view+0x94 + 20 + col*20`, whose byte `+0` looks like
a kind selector. Something writes that byte per column; the constructors found
so far only zero the block. **That writer is the assignment table**, and finding
it should hand over every widget binding at once rather than one predicate at a
time.

#### Method note

`docs/FEATURE-PLAYBOOK.md` §2.3 says a measurement that contradicts what the
owner knows about their instrument should make you suspect the reader. This is
the neighbouring case: **a hypothesis that contradicts how the instrument was
designed cannot be rescued by better measurement.** Hours went into correlating
a property against a choice that was made by a designer, and the owner closed it
in three sentences.

**None of this blocks v6.** Independent values (§3's extension array) is a
separate axis and the more important one: v5's page is real, it just looks plain.

## 5j. v5 confirmed, and two corrections — 2026-09-16

**The page header is a group counter, not a label.** All four MOD pages read
`MOD 1/4`, `MOD 2/4`, `MOD 3/4`, `MOD 4/4`. The `LFO1`/`LFO2`/`LFO3` string in
each record's `+0x2C` field is **not** the page header — it is used somewhere
else (p-lock lists, most likely). Asking the owner to "look for LFO4 on the
page" was never going to work, and the assumption should have been checked
before it was put in front of them.

It also confirms navigation is fully coherent: the counter says **4**, driven by
the id vector's length.

**The cave ran, and the widget regression proves it.** No further check is
needed:

- In **v4** page four used LFO3's descriptor, so it drew LFO3's actual records —
  and the specialised widgets **worked**.
- In **v5** the only change to that page is which descriptor it receives. The
  widgets went **plain**.

If the cave had not run, page four would be byte-for-byte the v4 page, widgets
included. It changed, so the descriptor changed, so the page is reading LFO4's
own records.

**v5 passes the question it was built to ask.**

| piece | state |
|---|---|
| a fourth `[MOD]` page, reachable | **done** (v4) |
| backed by LFO4's own parameter records | **done** (v5) |
| specialised widgets | missing — id-keyed, LFO4's ids are outside every LFO range (§5i) |
| independent values | **not started** — v6, and the real remaining work |

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
10. `[MOD]` navigation: relocate the view-id list `{4,5,6}` to `{4,5,6,0x25}`,
    repoint the immediate at `0x40061562`, and bump `moveq #3` at `0x40061558`.

**All ten steps are specified to the byte or to a named cave.**

---

## 7. The honest state, against the five named pieces

| # | piece | state |
|---|---|---|
| 5 | classifier | **designed** — mechanism read, edit specified, cave form proven in shipped code. Other cascades unread |
| 2 | tick edit | **designed** — both loops decoded, four edits named, state relocation forced and sized |
| 1 | slot space | **designed** — route chosen, bound found to be a `moveq`, extension array unchanged from the slot plan, 11 hooks listed |
| 3 | serialization | **designed** — both halves read; the stored block at `+28` is indexed by p-lock id, 107 wide, and the maps are the only translation. No format version bump. Three hooks named. Serialize-side loop bound unchecked |
| 4 | page view | **designed** — one shared `LfoPageView`, no fourth class; its LFO knowledge is three `Start Phase` ids in one function. **`[MOD]` navigation FOUND**: a pointer + count into a packed view-id pool at `0x401e0000`. The pool has **no gaps**, so the count cannot be bumped — the list relocates. The second registration is the MIDI-track group |

**Nothing here has been built, and nothing has been flashed.** All five are
specified to the point where code can be written against them. `[MOD]`
navigation is not, and saying otherwise would repeat the mistake that cost three
flashes: a cost model published ahead of the reading that supports it.

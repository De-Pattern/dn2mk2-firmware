
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

~~**Unchecked:** the serialize loop's iteration bound.~~ **Read 2026-09-20 —
they differ.** Deserialize is `cmpil #214` = **107 ids**; serialize is
`cmpil #200` = **100 live slots**, so slot 100 is never stored at all. The
forward map is 100 longwords for that reason, and the inverse map starts
immediately after it. See the step 2 result.

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

---

## 5k. The runtime layout, read end to end — 2026-09-17

Both LFO evaluators were disassembled in full today. They settle what
`docs/lfo4-slot-plan.md` circled for a week, and they make v6 a different and
much smaller job than §3 priced.

### The mirror, and that an LFO's parameters are just slots of it

The engine keeps a **per-track parameter mirror: 101 u16 slots, 202 bytes,
sixteen of them contiguous.** Evaluator A (`0x40137726`) walks it at stride 202
through `%sp@(52)`; evaluator B (`0x401373dc`) computes `%a0 + 202*track`
directly — `move.b #-54,%d1` after a `moveq #1` (the byte is `0xCA`, 202), then
`muls.l %d0,%d1`.

**An LFO's eight parameters are slots `8*lfo + 1 .. 8*lfo + 8` of that mirror.**
Not a separate structure, not a decoded copy: the same slot numbers
`scripts/dump_param_sets.py` prints.

| LFO | slots | evaluator A `%a4@` | evaluator B `%a4@` |
|---|---|---|---|
| LFO1 | 1–8 | 36–51 | 2–17 |
| LFO2 | 9–16 | 52–67 | 18–33 |
| LFO3 | 17–24 | 68–83 | 34–49 |

The two differ only by A's `lea %a4@(-34),%a4`, which biases `%a4` so the same
`@(68)` displacement lands on the top LFO.

The field order is `SPD MULT FADE DEST WAVE SPH MODE DEP` — the sound
`ParameterSet` order, and the same eight in the same order as DNX's stored
`30 + 8*param + 2*lfo` grid. **Two independent readings, two layers, one shape.**

### How a slot is read, and what "fine" actually means

Every slot is a u16 holding `display << 8`. The evaluators read

- `MULT`, `DEST`, `WAVE`, `MODE` with `mvs.b` — the **high byte**, the coarse
  value;
- `SPD`, `FADE`, `SPH`, `DEP` as full words.

That is **not** the same set as the `+0x14` fine-resolution flag, which is set
for **`SPD` and `DEP` only** — read out of the records today, and matching DNX's
corpus exactly (SPD 2,293 and DEP 3,416 non-zero fine bytes out of 159,744;
`FADE` 18, `MULT` 54, everything else under 10).

**Both are right and they are different properties.** `+0x14` is an *editor*
property: whether the UI will ever let a low byte be non-zero, and therefore
whether a stored object ever carries one. The word read is a *runtime* choice
about how many bits the arithmetic consumes. `FADE` and `SPH` are read as words
whose low byte is structurally always zero, which costs nothing and means
nothing. Recorded because the two lists look like a contradiction and are not.

### `DEST` is a slot index, and `DEP` is centred on `0x4000`

```
mvs.b %a4@(74),%d2        ; DEST, coarse
moveq #100,%d1
mvs.w %d2,%d7
cmp.l %d7,%d1
bcs   <skip>              ; DEST > 100 -> no destination
lea   %a0@(0,%d7:l:2),%fp ; %a0 = the mirror -> &mirror[DEST]
mvs.w %a4@(82),%d1        ; DEP
addi.l #-16384,%d1
add.l %d1,%d1             ; (DEP - 0x4000) * 2
mac.l %d1,%d0,%acc0
mvs.w %fp@,%d1            ; the destination's base value
add.l %d1,%d0             ; clamped to 0 .. 32512, written back as a word
```

So **`DEST` is a slot index into the same mirror, bounded 0..100**, `DEST = 0`
is the no-destination sink — which is exactly why slot 0 is one of only two
holes in the sound table — and **zero depth is `0x4000`, not `0`**. A record
zeroed to `00 00` is full *negative* depth, not "off". DNX confirms the centre
independently: DEP's coarse byte rests at 64 in 98.1% of 159,744 readings.

### Why LFO4's values cannot be slots 25–32

They are the next sixteen bytes of the mirror and they are **machine
parameters**. `dump_param_sets.py` says the sound table's only free slots are
**0 and 100** — 25–68 are free *in the flat table* but the accessor routes them
to the machine and filter tables, so the mirror cells are in use. There is no
eight-slot hole, which is what §3's extension array was always for.

### What still has to move: the three state arrays

`0x4463ed18`, `0x4463f498`, `0x4463fc18`, 1,920 bytes each (16 × 3 × 40), wall
to wall. Four LFOs need 2,560. Every site that names, sizes, strides or
initialises one was enumerated with `scripts/find_constant.py` and there are
only eight, plus two initialisers, two base accessors and one flag sweep.

**The stride arithmetic is a gift.** Both evaluators compute `track * 120` as
`(track << 7) - (track << 3)`. `track * 160` is `(track << 7) + (track << 5)` —
the same two instructions, one shift-count nibble and one opcode bit each.

## 5l. v6a is built: a fourth LFO with hard-coded parameters

`scripts/build_lfo4_tick.py` → `00_Resources/02_Builds/lfo4-tick6a_DN2_1.11.syx`.
Every integrity field verifies and the HMAC trailer is reproduced.

**It asks one question and deliberately nothing else:** told to run four LFOs
instead of three, does the fourth generate and apply modulation? LFO4's eight
parameters are sixteen bytes **in the image** — fixed, global, not editable, not
saved, not read from any preset. That removes storage, slots, serialization and
the UI from the experiment and leaves only the engine, which is the part that
has been reasoned about for a week and measured never.

| field | value | why |
|---|---|---|
| `SPD` | `0x7000` | LFO1's own default |
| `MULT` | `0x0100` | ×1, LFO1's default |
| `FADE` | `0x4000` | centred: no fade |
| `DEST` | `76 << 8` | **Filter BASE** — audible on any preset, every track |
| `WAVE` | `0x0100` | LFO1's default |
| `SPH` | `0` | |
| `MODE` | `0` | free-running, so it sweeps with no notes played |
| `DEP` | `0x7ffe` | `(0x7ffe − 0x4000) × 2`, near-full positive |

26 in-place edits, all asserted against their stock bytes, and seven stubs in
the verified-free run at `0x402dfa1c`:

| stub | replaces | does |
|---|---|---|
| `a4_top` | A's `lea %a4@(-34)` + `lea %a3@(116)` | points `%a4` at our block for the first iteration |
| `a4_bottom` | A's `lea %a4@(-16)` + the loop compare | on leaving iteration four, restores `%a4` to the mirror; re-issues the compare so the branch still works |
| `outer` | A's per-track advance | 160 does not fit a `moveq`, so the whole block moved |
| `flags` | the per-LFO flag sweep | a fourth store did not fit in place |
| `zero_backup` | init A's prologue | the relocated arrays sit above the BSS clear's bound, so nothing zeroes them |
| `b_top` / `b_bottom` | the same two jobs in evaluator B | |

**The frame-offset trap, recorded because it nearly shipped.** Five of the seven
stubs are entered by `jsr`, so the return address is on the stack and every
`%sp@(N)` inside them is the stock displacement **+4**. One stub replayed two
stock stores verbatim and would have written the frame four bytes low.

**A second error, caught by disassembling the build rather than trusting the
reasoning.** The first `%a4` bias was computed as "LFO index *i* sits at
`%a4 + 36 + 16i`, so the fourth is `+84`". That is true of the *stock initial*
`%a4`, but the loop body always reads `@(68)` and decrements at the **end**, so
the first iteration reads `+68` whatever the counter started at. Both stubs were
16 bytes off, and the build's own disassembly showed it in one line.

**[METHOD] Disassemble the build, not the plan.** Both errors were invisible in
the reasoning and obvious in the output. One `dnfw disasm` of the produced `.syx`
at the cave address is now part of building a cave, not an optional check.

### How to read the hardware result

| observation | means |
|---|---|
| boots, slow filter sweep on all 16 tracks | **a fourth LFO generates and applies** — the engine is not the obstacle, and the rest of LFO4 is plumbing |
| boots, nothing sweeps | the fourth iteration runs but produces nothing; read the state init |
| does not boot | the relocation is wrong; the state arrays are the first suspect |
| LFO1–3 misbehave | a stride edit was missed — every 120 and 1,920 in both evaluators |

The control is that the sweep must persist with LFO1–3 all set to no
destination. **Not a shipping build**: LFO4 is fixed, global and invisible, and
nothing it does is saved.

### 5l result — passed on hardware, 2026-09-17

Owner: *"`lfo4-tick6a_DN2_1.11.syx` -> works."* The engine question is answered
yes: the evaluators run a fourth LFO over the relocated, grown state and apply it.
Recorded in `docs/flashing.md`.

**Confirmed on follow-up by the owner:** LFO1–3 unaffected, and the sweep on
all tracks. **DNX's read also passes** (lane 4 all `00 00`, no trace of LFO4's values; LFO3 `DEP 7ffe` matches only by coincidence — its other fields differ). ~~Still pending:~~ DNX's read of a saved sound (lane 4 of bytes 36–93
must stay `00 00`). The owner saved `LFO4_TICK.dn2pst` for it; DNX has the request.

**What this unblocks:** the remaining LFO4 pieces are now storage and UI, not
engine — feed the fourth slot from the per-track mirror (which needs mirror
growth past slot 100, backlog §12) and join v6a to the v4 page view, whose one
known defect is the three-element waveform-graph array at `0x4010d984`.


---

## 8. The plan from 2026-09-19: per-track LFO4 on an extension table, in C

v6a answered the engine question. What is left is where LFO4's eight values live
per track, and wiring. This section records how that was decided, because two
tempting routes were ruled out and the reasons are the point.

### Where the values cannot go

- **The value array** (live sound `+20`, 101 u16 slots). Its only free slots are
  0 (the LFOs' "no destination" sink) and 100, and 65 now that the arp p-locks
  moved to their own records: three, not eight.
- **Spare bytes inside the live sound** (1,163 B). The save routine persists
  nothing past offset 373, and bytes 374..1151 were zero on all 16 tracks of the
  snapshot, but they are not free: `374` holds the arp's previous MODE
  (`0x4004bee0`), `430` / `512` and `1152`..`1162` are read through the sound's
  virtual accessor, and no static scan can attribute every displacement in the
  image to a structure. "Probably unused" was not good enough (owner: *110 %
  sure*), so this route was dropped.
- **Growing the sound or the value array.** What Elektron would do with the
  source: recompile a bigger struct and bump the storage version. Without the
  source it means ~100 uses of the 1,163 stride, ~64 of the 23,921 kit size,
  up to 74 of 202, plus multiplications the compiler hid in shifts, and every
  field displacement past the insertion point. One miss corrupts kits. Ruled out.
- **Decompiling and recompiling the OS.** Decompiler output is not buildable, the
  build itself (compiler, flags, link map, BSS) would have to be recreated, and
  field offsets are bare immediates no tool can attribute. Ruled out; but the
  *new* code can be written in C (below).

### Where they go: an extension table keyed by the sound's address

**Why it can be proven.** Its correctness depends only on catching every way a
live sound moves, and that set was enumerated:

| a live sound moves by | sites | carried by |
|---|---|---|
| whole-sound copy / clear | 32 `memcpy` / `memset` calls, literal 1,163 | the `memcpy` / `memset` hooks |
| whole-kit and pattern copies | ~9 `memcpy` / `memset` calls | the same hooks, by address range |
| save / load (stored <-> live) | `0x400dd6aa`, `0x400dd1ea` and the loops beside them | hooks on ids 0, 4, .. 28 |
| indexing (sound *t* of a kit) | 23 multiplies of 1,163 | nothing to carry |
| models and views holding a sound | `0x4004afec` stores a pointer | nothing to carry |

All 23 register loads of 1,163 are multiplies; the only loops bounded by 16
sounds are the save loop, a pointer-table build, and `0x4004afec`'s model
binding; the value-array (101 / 202) loops in real code are the lock-list
builders, save / load and engine-side arrays. **No routine copies a live sound
field by field.** `memcpy` / `memset` ran 2,347 / 15 times in 60 M instructions
of UI activity, so the hooks return at once below 1,163 bytes.

**The stored side is proven by the corpus** (DNX, 2026-09-19): across 195,256
sound objects (3,979 distinct) the lane of ids 0, 4, .. 28 -- stored bytes
**28, 36, .. 84** (`+28 + 2*id`; an earlier note here said 36 .. 92, off by one
pair) -- is `00 00` in every one, and those ids occur in no real lock record of
10,935 patterns. The stock inverse map folds them onto the no-lock sentinel, so
a stock 1.11 load ignores them. **Open:** whether a stock load + re-save keeps or
zeroes those bytes (one scratch-slot round trip would say).

### The C toolchain, and where the code lives

The new logic (the table, the `memcpy` / `memset` carry, save / load mapping,
the engine read, the page) is written in **C for ColdFire**, compiled and linked
at a fixed address, calling firmware routines by address; only the stubs at the
patch sites stay assembly. It is carried in the **appended area as a `CODE`
chunk**, beside the boot screen's `BOOT` / `ANIM` chunks under the `DNFW`
directory, and copied into free RAM above BSS by the startup hook the boot
screen already proved on hardware. A new ELE3 section (backlog §6) would be
cleaner but is unproven (updater, flash space, emulator); it stays a later
clean-up.

### The steps

| # | step | test |
|---|---|---|
| 0 | C toolchain: compile, link, package as a `CODE` chunk, startup copy (generalising the boot screen's) | a trivial C routine called from a hook, under the emulator |
| 1 | extension table + `memcpy` / `memset` carry | direct-call harness: whole-sound, kit, pattern copies, clears, overlaps, table full; cost per call |
| 2 | save / load through ids 0, 4, .. 28 | harness round trip; stock-compatibility of the stored bytes |
| 3 | engine: v6a's fixed block becomes each track's own | harness on the evaluator's inputs; **device: two tracks, different LFO4** |
| 4 | the fourth `[MOD]` page edits the table | emulator push + turn; survives copy / paste and a pattern switch |
| 5 | every edit path of the arp work, driven with controls | copy / paste of trig, page, track; undo; kit change; preset load; burn; machine change; parameter-page copy; **device: a full session** |
| 6 | LFO4 p-locks, through the arp's own-record mechanism | as the arp |
| 7 | widgets (wave graph, glyphs); a `dnfw mods` package | -- |

The device verifies at steps 3 and 5 only; every other check runs here first.

### Step 0 result — passed under the emulator, 2026-09-19

The chain works end to end from a cold boot (`scripts/emu_c_hello.py`, from
reset, beside a stock control):

| piece | where |
|---|---|
| C compiler | `m68k-linux-gnu-gcc` 13.3 in WSL, `-mcpu=5475` (ColdFire V4e); `dnfw.patch.cbuild` compiles, links at a fixed address, returns bytes, BSS size and symbols |
| area format | `dnfw.patch.area`: the boot screen's `DNFW` directory unchanged, plus a `CODE` chunk (`load`, `length`, `bss`, `init`, image) |
| loader | `csrc/runtime/loader.S`, 132 B in the clean cave `0x4028da6e` (138 B, no registered mod uses it), called from the startup calls at `0x4000053e`; data chunks go where the boot screen always put them, `CODE` chunks to their own address |
| test code | `csrc/hello/`, 124 B + 32 B BSS at `0x46800000`, hooked on `memcpy`'s entry |

Measured: the loader runs at instruction 1,359, before the caches are enabled;
its init call ran the C init, which filled a marker through the **firmware's own
`memset`**; `memcpy` is first called at 26.3 M, long after, and all 665 calls in
60 M went through the C routine with their real arguments; the stock control
made the same 665 calls. So a hook on `memcpy` (step 1) never jumps into RAM that
is not loaded yet.

Why the loader is assembly: the same logic in C compiled to 220 B (316 B in the
first draft); the largest free clean cave is 138 B. The C toolchain is proven by
the code it loads. The loader saves no registers — after the startup calls the
reset code only calls `main` (`0x40000568`).

**Not yet done, and belongs to item 6 (mod registry):** the boot screen and LFO
Waves still install their own startup stubs at the same site. The loader is a
superset of the boot screen's copy, so the boot screen can move onto it without
changing its runtime layout.

### Step 1 result — the table is carried, 2026-09-20

`scripts/build_lfo4_ext.py` → `00_Resources/02_Builds/lfo4-ext_DN2_1.11.syx`;
1,548 B of code and 6,184 B of table and state at `0x46800000`, 24 patched bytes
at three sites (the startup calls, and `memcpy` and `memset` at their entries).

| piece | where |
|---|---|
| the table | `csrc/lfo4/ext.c` — 256 entries × (u32 key + 8 × u16), open addressing, **no tombstones**: a deletion shifts its cluster back, so a free slot always ends a probe and the range walks never cross a grave |
| the size policy | `csrc/lfo4/carry.c` — under 1,163 bytes, return; exactly 1,163, one object; more, every object inside the range |
| the two stubs | `csrc/lfo4/hooks.S`, each replaying the two instructions its jump displaced |
| what runs once | `csrc/lfo4/init.c`, called by the startup loader before the firmware's BSS clear |

**The carry is by range, not by size.** §8 enumerated 32 whole-sound copies and
~9 kit and pattern copies; this build never compares against that list. A copy
of 1,163 bytes or more carries whatever the table is tracking inside the range
it covers, so a container the enumeration missed carries its sounds anyway, and
the enumeration only has to be right about which **routines** move a sound. It
is bought with a two-compare range test against the tracked bounds, which is
what keeps a frame-buffer copy free.

### What the harness measured — `scripts/emu_lfo4_ext.py`

A snapshot restored, the code written where the loader puts it, its init called,
both entries patched exactly as the build patches them — then the firmware's
**own** `memcpy` and `memset` called with laid-out arguments. All 22 checks
pass, first run:

| asked | answer |
|---|---|
| whole-sound copy, both directions, over a tracked destination | carries the eight values; the source keeps its own |
| copy from an untracked sound | the destination's entry is dropped, not left stale |
| copies of 1,162 bytes and 64 bytes | carry nothing |
| a whole kit, 16 sounds at stride 1,163 | 16/16 land at their own offsets; nothing lands between them |
| the same kit copied **overlapping**, one sound along | 16/16 |
| a block of 96,661 bytes — a size this build knows nothing about | the three sounds inside it are carried |
| `memset` of a sound, and of a kit | the entries go, and the slots read `ext_default` again |
| the table filled to 256 | the 257th is refused and counted; nothing is written over |
| half of a full table dropped | every survivor still found, every dropped key reads the default |

**Cost, instructions per call** (the emulator counts them):

| call | stock | hooked |
|---|---|---|
| a 64-byte copy — the path every call under 1,163 bytes takes | 43 | 60 (**+17**) |
| one whole sound | 466 | 759 |
| a whole kit, 16 sounds carried | — | 14,643 |

+17 on every `memcpy` is the price of the feature on the hot path. `memcpy`
was measured at 2,347 calls per 60 M instructions of UI activity (§8) and 665
per 60 M from reset, so that is between 11,000 and 40,000 instructions per 60
million: **under a thousandth of the processor.** A large
copy nowhere near a tracked sound costs **8** instructions more than with an
empty table — the range test, doing its job.

### And from reset — `scripts/emu_lfo4_boot.py`

The harness cannot see the failure this build could have on its own: a stub in
front of two routines the whole firmware uses. So stock and patched were booted
from reset, 60 M instructions each, and compared. All seven checks pass.

| asked | answer |
|---|---|
| does the control ever reach our code? | no |
| loader, and the init with it | once each |
| every `memcpy` / `memset` through the stub | 665 / 665 and 27 / 27 |
| the same calls as the stock control | 665 and 27, both |
| entries refused, batches overflowed, calls reentered | 0, 0, 0 |

**And the finding that matters for how step 1 is tested: in 60 M instructions
from reset the firmware made no copy of 1,163 bytes or more at all.** All 665
`memcpy` calls took the fast path; the carry never ran; `ext_live` ended at 0.
A boot does not load a kit or switch a pattern, which is where whole sounds
move. So the boot proves the hooks are harmless and the fast path is what a
boot pays, and it proves **nothing** about the carry — the direct-call harness
is the test of that, and step 5's driven session on the device is its
confirmation.

### What step 1 does not answer

- **Save and load** (step 2). A sound that is written from the stored side does
  not go through `memcpy`; the two hooks on ids 0, 4, .. 28 are that step.
- **Whether `memcpy` and `memset` are the only movers.** The plan read that no
  routine copies a live sound field by field, and the harness cannot see a mover
  it does not know about. What would expose one is step 5's driven session: an
  entry that vanishes after an edit path nothing here hooks.
- **What a slot with no entry should read.** `ext_default` is eight zeros today,
  which for `DEP` is full *negative* depth (§5k). Step 3 sets it to what a fresh
  sound should sound like, which is where that belongs.
- **Whether an interrupt ever copies a sound while a copy is in flight.** Both
  hooked routines are called from interrupt context, and the table work is
  neither atomic nor reentrant. Rather than assume, the slow path counts it:
  `lfo4_reentered`, checked by the boot run and to be checked again in step 5's
  driven session. If it ever moves off zero the answer is to mask interrupts
  around the carry, and we will then know the microseconds are worth spending.

### Step 2 result — a sound keeps its LFO4, 2026-09-20

`csrc/lfo4/store.c` and two more stubs in `csrc/lfo4/hooks.S`; the same build,
`lfo4-ext_DN2_1.11.syx`, now 1,884 B of code and four patched sites.

**Neither map is edited, and §4's slot renumbering is dropped.** §4 designed
LFO4 into live slots 101–108 and widened both loops to reach them. Reading the
two maps out of the image killed that: `0x401fcf20` is **100 longwords** and
`0x401fd0b0` starts immediately after it, so neither table can grow in place.
The loops are left exactly as they are, and the eight ids are handled **once,
after each loop**, from the sound's own address — the key step 1 already
carries. Two hooks, both at sites where the live sound and the stored sound are
still in `a2`/`a3`:

| direction | site | displaced | what the C does |
|---|---|---|---|
| stored → live | `0x400dd282` | `mvs.b 28(a2),d0 ; moveq #6,d2` | read the eight ids, `ext_set` them, or drop the entry if all are zero |
| live → stored | `0x400dd724` | `mvs.b 54(a2),d0 ; move.l (a0,d0*4),d0` | write `ext_get` into the eight ids |

Unlike the `memcpy` / `memset` stubs these sit inside code that never expected a
call, so both save `d0`/`d1`/`a0`/`a1` around it — all four are live across the
site. ColdFire's `MOVEM` has no predecrement mode, hence the `lea` either side.

### Which eight ids — measured, and not the ones §4 named

Driving the real serializer with a marker in **all 101 live slots** and reading
the stored block back:

- **the ids the save loop never writes: 4, 8, 12, 16, 20, 24, 28 and 32.**
  Eight, exactly what LFO4 needs;
- **id 0 is written twice** — from live slot 0, and again from live slot 65,
  which the map also folds onto it. Id 0 is the sentinel both directions fold
  onto, so it is **not ours to take**: a stock save of one of our sounds would
  drop slot 65's value on top of LFO4's first parameter. The rank starts one
  parameter later and ends at 32 instead;
- the serialize loop covers **live slots 0–99** — slot 100 is never stored, which
  answers §4's "unchecked: the serialize loop's iteration bound" (100
  iterations against deserialize's 107);
- **live slots 4, 12 and 20 do not carry their own value** into storage. They are
  LFO1–3's `DEST`, and the three fix-ups after each loop translate them through
  the map — `DEST` is a *slot index* at runtime and a *p-lock id* in storage.
  §5k read `DEST` as a slot index; this is the other half of that, and it is
  what LFO4's own `DEST` will have to do in step 4.

### §8's open question, answered by measurement

> *whether a stock load + re-save keeps or zeroes those bytes (one scratch-slot
> round trip would say)*

**It zeroes them.** Asked of stock 1.11 on the same snapshot before any of our
code was installed: a stored sound carrying all eight ids loads without
complaint, every one of the eight is folded onto live slot 0 (the last one wins),
and a stock re-save leaves **all eight at zero**. So the reserved ids survive
being *stored* by anything; they do not survive a stock firmware touching the
sound. LFO4's values are ours to keep only while our build is on the instrument
— which is the honest answer, and it means a sound round-tripped through stock
firmware comes back with LFO4 silently cleared rather than corrupted.

### What the harness measured — `scripts/emu_lfo4_store.py`

The firmware's own `0x400dd1ea` and `0x400dd6a6` called with laid-out
arguments. All ten checks pass:

| asked | answer |
|---|---|
| our load puts the eight into the table | yes, and counted as carrying |
| the live sound our load produced | **byte for byte** the one stock produced |
| our save writes the eight back | yes |
| everything else in the stored sound | **0 bytes differ** from stock's |
| save, lose the table, load again | the eight values come back |
| a stock sound (the eight ids zero) | loads to **no entry at all**, not an entry of zeros |
| saving that sound | leaves the eight ids zero, exactly as stock leaves them |

**Cost:** save 2,037 → 2,588 instructions (+551), load 4,819 → 5,514 (+695),
per sound. A pattern change loads sixteen, so ~11,000 instructions — beside the
77,000 the sixteen loads already cost.

### And from reset, again

`scripts/emu_lfo4_boot.py` with all four sites watched: the loader and init run
once, all **665** `memcpy` and **27** `memset` calls go through their stubs, the
counts match the stock control exactly, and nothing was refused, overflowed or
reentered. The two converter sites are **never reached from reset** -- a boot
loads no kit and switches no pattern -- which the script now says in as many
words rather than letting a `None == None` comparison print as a pass.

### Still open after step 2

- **Other load paths.** `0x400dd1ea` has one direct caller and is the **v3 track
  converter**; the map scan found only six references to the two tables in the
  whole image, and the other four are the p-lock path (step 6) and the two
  id↔slot translators. A preset loaded from the +Drive by some other route would
  not be hooked, and the harness cannot see a path it does not know about.
- **Id 32 in the corpus.** DNX verified the rank `4*param+0` is `00 00` across
  195,256 sound objects; the note in §8 says the lane checked was bytes 28–84
  (ids 0–28) after correcting an earlier "36–92" (ids 4–32). Since the id set is
  now **4–32**, that earlier range is the one that matters and it is worth one
  confirmation from DNX rather than a re-reading of a note.

### Step 3 result — each track has its own LFO4, 2026-09-20

`scripts/build_lfo4_tick7.py` → `00_Resources/02_Builds/lfo4-tick7_DN2_1.11.syx`.
v6a's single 16-byte parameter block becomes a **sixteen-row table** in the same
cave, and both evaluators index their own track's row.

**The index was already there, in both.** This is why the engine change is two
lines rather than a design:

| evaluator | where the track index lives at the hook |
|---|---|
| A `0x40137726` | `%a5` — zeroed at `0x40137758`, stepped once per track, used as a shift count at `0x40137770`–`0x4013777e` |
| B `0x401373dc` | `%d0` — its own argument (`movel %sp@(68),%d0`), read at `0x4013740c` and `0x40137410` and never written before the hook |

So each stub adds `track << 4` to the table base. Everything else is v6a's,
**imported rather than copied**: the state relocation, the loop counts, the
stride arithmetic, the flag sweep and five of the seven stubs. The two lines
that change are matched by their rendered text with a count-of-one assertion, so
if v6a's source moves this build stops instead of patching the wrong stub.

### What the harness measured — `scripts/emu_lfo4_tick.py`

The build's 412 changed bytes are written into a restored snapshot and the real
evaluator is entered — its generator, its MAC-unit apply, its state walk. After
40 frames, with every mirror slot starting centred at `0x4000`:

```
  track 1  slot 76  -> 0x7f00      its own row: fast
  track 2  slot 76  -> 0x447f      its own row: slow, a different value
  track 3+ slot 0                  DEST = 0, the no-destination sink
  exactly 16 words written in all, one per track
```

All five checks pass. The assertion is on the **whole** write pattern — sixteen
words, one per track, at the slot each track's row names — which is stronger
than sampling three of them.

### Three things that cost an hour, and are worth keeping

1. **It panicked, and the panic has a name.** The evaluator burned its whole
   20 M instruction budget. A PC histogram found it parked at `0x40138d92`, a
   `bras` to itself with 38 direct callers: the halt.
2. **A control cleared the build before any of it was debugged.** Stock firmware,
   same snapshot, same arguments, panicked **identically** — so the fault was
   the call, not the patch.
3. **The firmware names its own failure.** Hooking the reporter at `0x4017cec8`
   and reading its stack gives the assert verbatim:
   `GET_MACSR_MODE() == MACF_FRAC`, `../../../lib/shared/sm/fade.c` line 16,
   function `getFadeStep`. **Evaluator A expects its caller to have put the EMAC
   in fractional mode** — the audio-frame function does, a bare snapshot has
   not, and evaluator B sets it itself at `0x401373f0`. The harness now does it
   the way the firmware does, by running `movel #32,%macsr`.

### Two facts about calling evaluator A, for whoever needs them next

- **Its seven arguments**, read off the firmware's own call at `0x400272a4`:
  the parameter object, `[0x402a0dec]` (a scale, `0x25f8` in the snapshot), two
  per-track enable masks, two out-pointers, and a flag whose low byte asks for a
  state backup first.
- **The first argument is not the mirror.** The prologue does
  `lea %a0@(34),%a0`, so the sixteen 202-byte rows start **34 bytes in**. Found
  by diffing the whole buffer after a run, not by reading harder.

**Still owed: the instrument.** The plan's step 3 asks for two tracks with
different LFO4 on the device, and the build for it verifies every integrity
field. Nothing here replaces that.

### The track → live sound map, read and verified — 2026-09-20

The bridge's one missing fact. `0x400ddc52`, the v4 container gate, ends in the
sixteen-track loop:

```
0x400ddcda  movel %a3,%d3          ; a3 = the live container, argument 1
0x400ddcdc  movel %a2,%d4          ; a2 = the stored container, argument 2
0x400ddcde  addil #52,%d3          ; the live sounds start at +52
0x400ddce4  addil #60,%d4          ; the stored tracks at +60
...
0x400ddcfa  jsr %a4@               ; a4 = 0x400dd1ea, the deserializer of step 2
0x400ddd0c  addil #1163,%d3        ; live  += 1163
0x400ddd12  addil #359,%d4         ; stored += 359
0x400ddd18  moveq #16,%d0          ; sixteen tracks
```

So **`sound(track) = live container + 52 + track * 1163`**, and the live
container on 1.11 is `0x4210c08c` — the address `#PLAY_PATTERN` hands the
sequencer (`docs/service-commands.md`), a literal in the image rather than a
pointer that moves.

**Checked against a snapshot rather than left as arithmetic.** Reading those
addresses gives named sounds, in track order:

| track | address | name |
|---|---|---|
| 1 | `0x4210c0c0` | `FRAGILE BEINGS` |
| 2 | `0x4210c54b` | `DULCI SPACE` |
| 3 | `0x4210c9d6` | `LAST BREAKFAST` |
| 4 | `0x4210ce61` | `WEAVING CIRCLE` |

Two things fell out of the same read. The container's first longword is
`'KIT '`, so it is the kit header and the sounds are **not** at `+0` -- which is
what the earlier probe of `0x4210c08c` showed and could not explain. And the
loop just above the pointer setup (`0x400ddcbc`-`0x400ddcd8`) writes sixteen
words at container `+20`, each clamped to `32512`; in the snapshot they read
`0x6400` for fifteen tracks and `0x5900` for one, which is **the per-track
level**, 100 and 89 coarse.

`0x4058e8d8` -- the arp work's `TRACK_SOUNDS` -- is **not** this map: all
sixteen of its longwords are zero in the same snapshot, so that harness laid it
out synthetically.

### The bridge: one firmware, and a value in the table reaches the engine — 2026-09-20

`scripts/build_lfo4_bridge.py` → `00_Resources/02_Builds/lfo4-bridge_DN2_1.11.syx`.
The first build where steps 0–3 are the same image: the startup loader and the
`CODE` chunk, the extension table with its `memcpy` / `memset` carry, save and
load through the reserved ids, a fourth LFO in both evaluators, and now
`csrc/lfo4/bridge.c` joining the last two.

**The tick pulls; nothing pushes.** The push design — hook `Sound::updateMirror`
— died on reading it: `0x4004cb08` is a *per-parameter* update
(`mvsw %a0@(14,%d2:l:2),%d1`), one slot at a time, and LFO4's parameters are not
slots of a sound, so there is nothing there to hook. Instead `a4_top` and
`b_top`, which already run once per track with the index in hand, call
`lfo4_refresh(track)`; it returns that track's row address, having copied the
eight values from the table only if the track's sound changed or
`ext_generation` moved. Every mutator bumps that counter, so **every** edit path
is covered, named or not — the same argument that made step 1's carry
range-based rather than a list of sizes.

Both stubs preserve `d0`/`d1`/`a0`/`a1` across the call: they sit inside
evaluator code that never expected one. `%a5` survives on the compiler's own
convention.

### What the harness measured — `scripts/emu_lfo4_bridge.py`

Eight values put in the table for **one** track's sound, then the real evaluator
run. The sound address comes from the build's own `lfo4_sound_of`, so the
harness and the firmware share one arithmetic rather than two copies of it.

```
  track 2's live sound, from the firmware's own map: 0x4210c54b
  track 2  slot 76  -> 0x7f00        the only word written
  16 copies in 640 refreshes         the cache holds
  after editing SPD: 0x7f00 -> 0x41ef
```

All six checks pass:

| asked | answer |
|---|---|
| does a table entry reach the engine? | that track modulates its own destination |
| does anything else move? | **no** — the other fifteen rows are zeros, and a row of zeros is a silent LFO, not even a write to the sink |
| does the cache hold? | 16 copies across 640 refreshes |
| does an edit propagate with nothing told? | yes — `ext_set` bumps the generation, the next frame notices |
| what does the edit cost? | one copy per track, not one per frame |

**Two things the harness itself got wrong**, kept because they will recur: a
snapshot has already run past the startup loader, so a harness must do the
loader's job verbatim — copy the chunk to its run address, zero the BSS, call
the init; and the first depth value saturated at the clamp `0x7f00`, which made
two different rates look identical until the depth came down and the phase was
reset between runs.

**What is still missing to call this a feature:** nothing on the instrument
writes to the table. That is step 4, the `[MOD]` page.

### Step 4: the setter, found by asking the machine — 2026-09-20

The page needs two addresses: where the UI **reads** a parameter value, and
where a turn **writes** it. The getter was known (`0x4006408a`). The static hunt
for the setter went through several plausible candidates without deciding, so
the question went to the emulator instead: drive the panel and watch the live
sound's value array.

`scripts/emu_param_setter.py` — `panelin` input the way `scripts/drive.py` does
it, with a `UC_HOOK_MEM_WRITE` over track 1's array at `0x4210c0d4`:

```
  idle control: 0 write(s) with no input
  MOD page 1, push-and-turn +10 x2: 1 write(s)      ... and 1 on each of 2, 3, 4
  writers, hottest first:
    0x40037be8  4
  first writes:
    0x40037be8  slot 1   <- 0x78a1 (2 B)
    0x40037be8  slot 1   <- 0x7ffe (2 B)   ... clamped at the top thereafter
```

**One writer, four writes, one per page visit, against an idle control of
zero.** The setter is `0x40037be8`, `0x2a6` into `0x40037942`:

```
0x40037bd0  moveq #100,%d0
0x40037bd2  cmpl %d2,%d0
0x40037bd4  blts 0x40037c48             ; slot > 100 -> no write at all
0x40037bd6  moveal %a2@(16),%a0         ; the object that owns the sound
0x40037bde  moveal %a1@(40),%a0         ; its vtable slot 40
0x40037be2  jsr %a0@                    ; -> d0 = the live sound
0x40037be8  movew %d3,%a0@(14,%d2:l:2)  ; values[slot] = value
```

So the write is `values[d2] = d3` with **`d2` the slot and `d3` the value**, and
the sound arrives from a virtual call rather than a constant — which is what
makes it the right hook: it is already the per-track sound.

### Why that bound is the opening

`slot > 100` skips the write **entirely**. So if LFO4's ten records carry slots
**101–108**, stock firmware does nothing at all with them — no stray write, no
corrupted neighbour — and the branch at `0x40037bd4` is a free, well-defined
place to divert into `ext_set(sound, slot - 101, value)`. The same bound guards
the accessor at `0x400dc02c` (§3's `moveq #100`), so the read side has the same
shape.

That is §3's original slots-101–108 design, arrived at from the other end: the
table it needed already exists, and the two bounds that make it safe are now
located rather than assumed.

### Two things the probe had to be told

1. **Push and turn.** The first run turned the encoder without holding its push
   and reported **0 writes** — a clean-looking null that meant nothing. Encoder
   A's push is control code 41, and `code_for` is `channel * 8 + bit + 1`, so it
   is channel 5 bit 0. This is now in the routing hook so it arrives before the
   next probe is written rather than after it fails.
2. **The page never changed, and the reason is the dwell — not the key.** All
   four visits wrote **slot 1**, LFO1's `SPD`, so the repeated `[MOD]` press
   never moved off the first LFO page.

   ~~Paging is `[PAGE]`.~~ **Wrong, corrected by the owner the same day:** on
   the instrument the `[MOD]` pages cycle by *pressing `[MOD]` again*, or with
   the **up / down arrows**. `[PAGE]` opens the page settings, which is a
   different thing entirely.

   What actually happened is in this project's own notes: the runner paces
   input about 9 M instructions apart, past the firmware's ~7.5 M hold
   threshold, so **every "press" in that probe was a hold**, and a held `[MOD]`
   does not cycle. `--panel-dwell 2` is what makes a tap a tap. The step 4 test
   must tap `[MOD]`, or use up / down, and it must **check the slot it wrote**:
   four writes to slot 1 look exactly like success until you read which slot
   they hit.

   **Why it kept happening after that was understood — 2026-09-20.** The
   diagnosis above was right and the fix did not take, because
   `emulib.panel.settle` passed `CHUNK` as its spin budget instead of the
   window it was asked for. Every window under 10 M ran a full 10 M, so `tap`
   asked for 2 M and held for 10 M, and the `--dwell` argument that was
   supposed to fix it was read by nothing. A sweep over that argument came back
   identical at 500 K and 2 M — not because the pages were insensitive to it,
   but because both runs were the same 10 M. `docs/emulator.md` §"And it was
   neither the keys nor the dwell" has the walk before and after, and the pages
   turn out to be `MOD (n/3)`, one per press, clamping at the ends.

### Step 4a result — ids 101–108 reach the table, 2026-09-20

`00_Resources/02_Builds/lfo4-slots_DN2_1.11.syx` is the bridge plus one site:
`lfo4_set_stub` in place of the setter's own `slot > 100` bound at
`0x40037bd0`. Verified under the emulator by `scripts/emu_lfo4_slots.py`.

**There is no page yet, so the panel cannot ask for id 101.** Building a call
to the setter by hand would have tested a signature this project inferred
rather than the path the firmware takes, so instead the turn is real and only
the id is not: a code hook at the bound rewrites `d2` as the firmware arrives
there, with the object in `a2`, the virtual call that yields the live sound,
and the value in `d3` all exactly as a genuine encoder turn left them.

```
  the bound saw 1 turn(s): slot 1 <- 0x78a1
  lfo4_sets 1, ignored 0, sound 0x4210c0c0, slot 101, value 0x78a1
  table: live 1, inserts 1, generation 2, full 0, overflow 0
  the table's entry for 0x4210c0c0, param 0: 0x78a1
  ok  a key nothing set is absent            (it read back None)
  ok  no slot of the live sound moved        (slots [])
```

`generation 2` is the tell: one bump from the insert, one from the set.
`0x4210c0c0` is `KIT + 52`, track 0's live sound — **the firmware's own
pointer**, not one the harness computed. And nothing in the live value array
moved, which is the half that matters for safety: above 100 stock firmware
writes nothing, and neither do we.

#### The reader was wrong twice before it was right, and both are traps

The first two runs reported the table as empty. Both times the divert was fine
and `machine.call(ext_get, ...)` was not:

1. **The return is sixteen bits.** `ext_get` returns `u16`, and the high half
   of `d0` is left dirty — outside the panel run the same call gives
   `0x46801234` for a stored `0x1234`. `lfo4_harness.get` masks with
   `& 0xFFFF`; this harness did not.
2. **Once the timers are armed, the call does not reliably complete.** `Panel`
   claims the snapshot's DMA timers, so an interrupt can vector away from a
   called routine; `emu_start` then stops on its instruction count instead of
   at the return address and hands back whatever `d0` holds. It came back
   **0** — a plausible number, and the worst possible answer for a probe
   asking whether a value arrived.

The harness now reads `ext_key` / `ext_val` out of memory, which is our own
table with a known layout, and carries a control that a never-set key reads
back absent. **Scope:** only the panel-driving harnesses claim timers, and of
those only this one called into firmware code — steps 1–3 and the bridge use
`call(ext_get)` with no `Panel`, so their results stand.

The general form of both, and it is the same lesson as `emulib.panel.settle`:
a harness that reads a result through firmware it did not write needs a control
that fails when the reader is broken. "The value is not there" and "this
function no longer returns values" are the same output.

### What step 4b still needs

- The **read side**: the accessor at `0x400dc02c` carries the same `moveq #100`
  bound, so the page can display an LFO4 value only once that is diverted too.
- The **page**: a fourth `MOD` page, which the screens now say is rendered as
  `MOD (n/3)` — so the count is drawn from something, and that something has to
  become 4.

### Step 4b, mapped: what a fourth MOD page is made of — 2026-09-20

Nothing here is built yet. This is the read of the page machinery that step 4b
needs, and it came out better than the plan assumed: **no count is written
down anywhere.** Three measurements, each with the instrument named.

#### 1. The header is derived from a range, not a constant

The renderer is `0x40063f56`, and at `0x40063f84`:

```
movel %a2@(128),%d0 ; subl %a2@(124),%d0    ; end - begin
moveq #7,%d1 ; cmpl %d0,%d1 ; bges ...      ; 8 bytes or fewer -> draw no "(n/m)"
asrl #2,%d0                                 ; (end - begin) / 4 -> the total
moveal %a2@(144),%a2 ; addql #1,%a2         ; the current index, made 1-based
```

So `MOD (3/3)` is `(end - begin) / 4` over a vector of four-byte entries. A
mode with one page prints only its name. **Nothing has to be taught that there
are four pages; a fourth entry is the whole change.**

#### 2. The entries are page ids, and the vector has no room

`scripts/emu_mod_pagelist.py` hooks that instruction during a live render and
reads the object it was called with, rather than guessing which object it is:

```
object 0x447bf800: begin 0x447bf510 end 0x447bf51c -> 3 page(s), current 1
    [0] 4    [1] 5    [2] 6
the 16 bytes after the end: 0x1bf10689 0x447bf560 0x447be5e0 0x447bf894
```

**The MOD pages are ids 4, 5 and 6** — small integers, not pointers. What
follows the end is an allocator word and live pointers, so the array is exactly
its contents and a fourth entry cannot be appended in place: the array has to
be rehoused, which for us means pointing `+124`/`+128` at our own four-entry
array. That is cheap, and safe as long as nothing ever reallocates or frees it.

#### 3. A page id is a record, and a record is a list of parameters

`0x400c2474` turns an id into one:

```
moveq #36,%d1 ; cmpl %d0,%d1 ; bcc keep ; moveq #-1,%d0   ; id > 36 -> the fallback
moveq #44,%d1 ; mulsl %d1,%d0 ; addil #0x42432C00,%d0     ; record = base + 44 * id
```

`scripts/emu_page_records.py` reads them out of the snapshot — **no
instructions executed**, since `ui1200M` has long since built the table:

```
id 4 (LFO1): 0x4464fe3c 0x4464fe5c   75 76 77 78 79 81 82 83   10
id 5 (LFO2): 0x4464fe7c 0x4464fe6c   85 86 87 88 89 91 92 93   10
id 6 (LFO3): 0x4464fe9c 0x4464febc   95 96 97 98 99 101 102 103  10
```

Two pointers, **eight parameter references**, and a span of 10. The references
are **indices into the instrument's parameter table plus one** — `dnfw params
--page LFO3` names them and the order settles it:

| entry | record | parameter |
|---|---|---|
| 95, 96, 97, 98 | 94, 95, 96, 97 | SPD, MULT, FADE, DEST |
| 99, *100 skipped* | 98, *99* | WAVE, *SLEW — present in the table, not on the page* |
| 101, 102, 103 | 100, 101, 102 | SPH, MODE, DEP |

`SPD MULT FADE DEST WAVE SPH MODE DEP` — the sound `ParameterSet` order §5k
already established from the evaluators. **Two layers, one shape, again.**

Each LFO owns ten consecutive records and the groups are ten apart, so the
table itself says what a fourth would look like: group 26 = LFO1 = records
74–83 = value slots 1–8, group 27 = LFO2 = 84–93 = slots 9–16, group 28 = LFO3
= 94–103 = slots 17–24. **LFO4 = ten records carrying value slots 101–108** —
the ones step 4a already made writable.

#### What 4b has to build, and the one thing that is genuinely hard

1. **Ten parameter records.** The table is at `0x401f7fc8`, 320 records of 60
   bytes, **inside the firmware image** — so it cannot simply grow. Either ten
   spare records exist somewhere in it, or the table is relocated into the
   appended area and the code that reads it is repointed. *Not yet read: how
   many places hold `0x401f7fc8` or a bound of 320.*
2. **One page record.** `0x42432C00 + 44 * id` in RAM, ids 0–36, and **id 37's
   space is already occupied** — the probe read code pointers there
   (`0x400bdc1a`, `0x400c0822`). So the same choice applies: find an unused id
   at or below 36, or relocate the record table and raise the `moveq #36`.
3. **A fourth entry in the MOD vector**, per §2 above — the easy part.

The hard part is (1), and it is hard for a reason worth stating plainly: both
tables are sized by constants compiled into code that reads them, so growing
either means finding every reader. That is a `dnfw fn callers` and
`find_constant.py` job, and it is the next thing to do — **before** any of this
is built, because if the parameter table cannot be extended safely the page has
to be drawn another way.

### tick7 passed on hardware — 2026-09-20

`lfo4-tick7_DN2_1.11.syx` **passes on the instrument**: the per-track fourth
LFO runs, each track reading its own row. Step 3 is now proved on the device,
not only under the emulator.

**With one lesson attached, and it is about the test, not the firmware.** The
demo rows used `MULT 0x0100` — multiplier index 1, the slowest available —
with `SPD 0x7000`, so the owner had to listen through roughly **fourteen bars**
to hear one bar of movement:

> "I almost wrote that it didn't work."

That is the whole problem in one sentence. A demo whose effect is
indistinguishable from a failure **cannot tell the two apart**, and it spends
the tester's attention to find that out — on hardware, where every run costs a
flash and a listen. The build was correct and very nearly recorded as broken.

`scripts/build_lfo4_tick7.py` now uses `MULT 0x0800`, and the rule is in
`docs/FEATURE-PLAYBOOK.md` §3: **a hard-coded demonstration must be obvious
within a bar.** Keep the two rows different from each other — the per-track
claim is what is being shown — but make both unmistakable.

#### Correction: how a page entry reaches a parameter record is NOT established

§"Step 4b, mapped" says the page record's eight entries are "indices into the
instrument's parameter table plus one", on the strength of the names lining up
in `SPD MULT FADE DEST WAVE SPH MODE DEP` order. **That alignment is real and
the mechanism behind it is not read.** Three measurements since:

- **No literal reference to the table exists.** The parameter table sits at
  `0x401f7fc8` (320 records of 60 bytes). Neither that address, nor the table's
  end, nor any record boundary from -2 to +39, appears as a four-byte value
  anywhere in the image.
- **There is no RAM copy.** Searching the snapshot for the exact 60 bytes of
  LFO3's `SPD` record across the record-table region, the UI object region and
  the page-record strings finds **zero** copies. The records are read in place,
  from the image.
- **So nothing yet found turns entry 95 into record 94.** A scan for the
  `base + stride * index` idiom finds 36 tables, none of them this one.

The record layout *is* confirmed, from its own bytes: `+0` a code pointer,
`+4` a name pointer, `+8` the group (`0x1c` = 28 for LFO3), `+12` the value
slot id (`0x11` = 17, LFO3's `SPD`), `+20` the range (`0x7ffe`) -- matching
`dnfw params` field for field.

**Why this matters for 4b:** the plan's third task was "find every reader of
the parameter table's bound". If the table is never addressed by a literal
base, that task is not a constant hunt at all, and the route for adding ten
records is unknown rather than merely hard. **Read how a page entry resolves
to a record before designing anything that adds one** -- the emulator can
answer it directly by watching who reads `0x401f95d0` while the LFO3 page
draws, which is the next probe rather than another static scan.

Recorded because the earlier section reads as settled and is not.

### The gap that let the bridge reach hardware, and closing it — 2026-09-21

`lfo4-bridge` passed every check it had and then faulted on the instrument.
The checks were not wrong; they were **incomplete in a way none of them could
report**. A boot from reset runs the loader, the init and the `memcpy` /
`memset` stubs and nothing else: the audio engine does not run, and no kit
loads, so the tick and both converter stubs are untouched. Every harness that
did exercise those restored `ui1200M` -- a machine our loader never booted.

So there were two halves and no run held both. `scripts/emu_boot_engine.py`
now does, on `lfo4-slots`:

```
  booting lfo4-slots from reset, 400,000,000 instructions
  ran 400,000,000; reached {'dnfw_boot': 1, 'lfo4_init': 1}

  entering evaluator A, 8 frame(s)
  lfo4_refresh ran 128 time(s) during 8 frame(s)

  load: the table holds ['0x2a01' ... '0x2a08']
  save: the stored ids hold ['0x2a01' ... '0x2a08']
```

128 is 8 frames x 16 tracks. The eight marks go into the table through
`0x400dd1ea` and come back out of the stored ids through `0x400dd6a6`, with
every other stored value distinct (`0x40 | i` per id) so a word in the wrong
place reads as a wrong mark rather than a plausible one. The table is read out
of memory, not through `call(ext_get, ...)`: an interrupted call returns 0,
which is indistinguishable from a value that never arrived (§"Step 4a result").

**The general form, and it is the part worth keeping.** Three separate things
went wrong tonight and all three had the same shape -- a check that reports
success about work it did not do:

1. the snapshot harnesses cleared code they never ran from a real boot;
2. the boot gate printed "Safe to flash" with its coverage section silently
   deleted by an unrelated edit;
3. `machine.call(ext_get, ...)` returned 0 for a value that was present.

None of them failed. Each returned a plausible pass. The defence is the same
each time: **a control that fails when the checker is broken** -- a key nothing
set that must read back absent, a routine list that must be non-empty, a
coverage line that must appear. A green result whose instrument was never
tested is not evidence.

#### Settled: a page entry IS a parameter index, and the accessor shape — 2026-09-21

The correction above said the mechanism was unread. It is read now, by
watching the machine instead of scanning it: `scripts/emu_param_reader.py`
arms a read watch over the parameter table and opens the LFO MOD page.
**15,407 reads.** Three of the instructions that made them fetch exactly

```
records [74, 75, 76, 77, 78, 80, 81, 82]
```

and LFO1's page record holds entries **75, 76, 77, 78, 79, 81, 82, 83** — the
same set plus one, gap and all: entry 79 maps to record 78, and record 79, the
unused `SLEW`, is never touched. So **entry = index + 1**, observed rather than
inferred from names.

The accessor at `0x400dbeb6` shows why no literal base was ever found:

```
movel %sp@(4),%d0          ; the entry
cmpil #321,%d0             ; the bound -- 320 records
scs %d1 ; mvsb %d1,%d1 ; andl %d1,%d0    ; out of range -> entry 0
lea 0x401f7f94,%a0         ; base, PRE-BIASED
movel %d0,%d1 ; lsll #2,%d1 ; lsll #6,%d0 ; subl %d1,%d0   ; d0 = entry * 60
movel %a0@(0,%d0:l),%d0    ; read
```

`0x401f7f94` is `table - 60 + 8`: the `-60` folds in the `+1`, and the `+8`
is the field this accessor wants. **Every accessor carries its own biased
base, so the table's true address `0x401f7fc8` is never stored anywhere** —
which is exactly why three static searches found nothing, and the searches
were right.

`0x401f7f8c + 60 * 1 = 0x401f7fc8` — the arithmetic confirms `entry = index +
1` without appealing to the names at all.

#### What extending the table would actually cost

The constants are now enumerable, which was the whole point of the question:

| constant | value | sites |
|---|---|---|
| biased base, field `+8` | `0x401f7f94` | 53 |
| biased base, field `+16` | `0x401f7f9c` | 1 |
| biased base, field `+40` | `0x401f7fb4` | 2 |
| `cmpil #321,%d0` | the record count | 24 |

**23 of the 24 bounds sit within 24 bytes of a biased base**, so they belong to
these accessors. The one that does not is `0x400c241c` and has not been read —
it may be an unrelated use of 321, and it must be looked at before any of this
is changed.

So LFO4's ten records mean: relocate the 19,200-byte table into the appended
area with ten records appended, then rewrite **56 base literals and 24
bounds**. Mechanical, bounded, and checkable — every one is a four-byte literal
or a six-byte immediate, and `dnfw` can assert each site is stock before
patching it, exactly as the existing sites do.

It is not small, and it is no longer unknown. The open items are that one
unpaired bound, and whether anything reaches a record other than through these
accessors — the `+0` field of every record is a code pointer, and where those
are called from has not been read.

#### Correction: the two "spare" records per group are alternates — 2026-09-21

§"Step 4b, mapped" describes the gaps in a page record's entries as *"the two
unused records in each group of ten"*, and reads record 79 as an unused
`SLEW`. **Both are wrong, corrected by the owner:** `SLEW` is shown when the
waveform is **RND**. The record is not unused; it is the alternate for that
slot, and it is touched whenever a random LFO is on screen.

`dnfw params --page LFO1` shows the shape once you look for it. A group of ten
is **eight value slots plus two alternates**, and the alternates are
recognisable because they *share an id* with a primary:

| record | id | name | range | CC |
|---|---|---|---|---|
| 74 | 1 | SPD | 7ffe | 170 |
| **75** | **2** | MULT | **1700** | 171 |
| 76 | 3 | FADE | 7f00 | 172 |
| 77 | 4 | DEST | 7f00 | 173 |
| 78 | 5 | WAVE | 0600 | 174 |
| **79** | **6** | **SLEW** | 7f00 | **--** |
| **80** | **6** | SPH | 7f00 | 175 |
| 81 | 7 | MODE | 0400 | 176 |
| 82 | 8 | DEP | 7ffe | 177 |
| **83** | **2** | MULT | **0b00** | 171 |

Two ids appear twice: id 6 as `SLEW` or `SPH`, and id 2 as `MULT` with a
23-value range or an 11-value one. **`SLEW` has no CC of its own** because the
CC belongs to the slot, not the record, and slot 6's is `SPH`'s -- which is
corroboration that the two really are one value seen two ways rather than two
parameters.

So the page record's eight entries name the **default** variant, and the
renderer substitutes the alternate from state -- `WAVE = RND` selects `SLEW`
over `SPH`. Which code performs that substitution is not read.

**What it changes for LFO4.** Ten records was already the number, but the
reason was wrong, and so would the contents have been. LFO4 needs:

- eight primaries on slots **101-108**: SPD, MULT, FADE, DEST, WAVE, SPH,
  MODE, DEP -- the `ParameterSet` order §5k established and `csrc/lfo4/ext.h`
  already uses;
- a **`SLEW` alternate sharing slot 106** with `SPH`, with no CC;
- a **second `MULT` on slot 102** carrying the `0x0b00` range.

Building eight records and leaving two blank would have produced an LFO whose
random waveform has no slew control and whose multiplier list is wrong in
whichever mode selects the short range -- on a page that otherwise looked
finished. The kind of gap that reads as a firmware bug rather than a missing
record.

#### The DEST list grows with the LFO, and LFO4 inherits that — 2026-09-21

From the owner, and it is the one thing about the LFO pages that is not
uniform: **the destination list grows as you advance through the MOD pages.**
LFO2 can modulate LFO1's parameters; LFO3 can modulate LFO1's and LFO2's.
The rest of the parameters are the same on every page.

That is a deliberate acyclic design -- **LFO N may target LFO 1..N-1 and no
further** -- and it is why the feature works at all: a fourth LFO cannot create
a modulation cycle by being added at the end.

It fits what this repository already measured from the engine side. §5k:
`DEST` is a **mirror slot index**, bounded at 100 in the evaluator
(`mvs.b %a4@(74),%d2 ; moveq #100,%d1 ; cmp.l %d7,%d1`), and the LFO block
occupies slots **1-24** -- LFO1 `1-8`, LFO2 `9-16`, LFO3 `17-24`. So "LFO2 can
modulate LFO1" is `DEST` taking a value in `1..8`, and the name the page shows
for it is simply that slot's own parameter name, which is why destinations read
`SYN BASE`, `SYN PD2` and so on rather than coming from a separate list.

**What LFO4 needs:** its `DEST` list must offer slots **1-24**, all three
earlier LFOs. And the existing three must **not** gain LFO4's slots 101-108,
or the acyclic property breaks -- LFO1 could then target LFO4, which targets
LFO1.

**Half of this was already read, and the owner was right to say so.**
`docs/engine-index-map.md` covers the *conversion* side and this section had
better not duplicate it: because a `DEST` **value** is itself a slot number, it
needs the same stored/live translation as the index, and the converter
special-cases exactly the three `DEST` slots with

```
(slot & ~8) == 4 || slot == 20        ; slots {4, 12, 20} = LFO1/2/3 DEST
```

in **two** places, `0x4004cb04` and `0x4004cb70` -- found by scanning all 27
`moveq #-9` sites and keeping those with a `moveq #20` within 48 bytes. That
file also already records the fix and how cheap it is: **`~8` becomes `~24`**
and the test covers `{4, 12, 20, 28}`, all four LFOs, making the `== 20` arm
dead. `moveq #-9` is `0x70F7`, `moveq #-25` is `0x70E7` -- **two bytes at two
sites**.

So the fourth LFO's `DEST` **value** is a solved, priced problem.

**What is still open is the other half: the list the UI offers.** The converter
translates whatever value is there; it does not decide which values the page
lets you pick. Whether that per-LFO bound is computed from the LFO index or
written down three times is not read, and it decides whether LFO4's list
follows for free or is a fourth enumeration to add -- while leaving the
existing three alone, or LFO1 could target LFO4 and the acyclic property
breaks.

Answerable the way the last two were: open LFO2's MOD page, turn `DEST` to its
limit, and watch what clamps it. Worth doing **before** the ten records are
built, because if it is enumerated per LFO it is another site list like the 56
bases, and belongs in the same patch.

#### DEST is chosen in a modal browser, and the ceiling was the wrong measurement

`scripts/emu_dest_range.py` turned `DEST` on each LFO page and read where the
value stopped. LFO1 answered **99** -- one below the evaluator's bound of 100 --
and pages 2 and 3 wrote nothing at all. The screen explained both:

**Push-and-turn on `DEST` opens a modal destination browser.** A category
column (`FX` in the captured frame), a scrolling list of destination names
(`Delay Send`, `Reverb Send`, `Bit Reduction`, `Sample-Rate Redu`, `SRR
Routing`, `Overdrive`, `OVR Routing`), and a **`Confirm? Yes/No`** prompt. The
header reads `MOD1 DEST`, which also confirms the page being measured was
LFO1's.

So the later `DOWN` taps were scrolling **inside the picker**, not paging --
the machine never left the modal, and two pages reporting "nothing written"
looked exactly like a broken encoder. A modal that swallows the page keys is
worth knowing about before the next probe drives this page.

**And the ceiling does not answer the question.** LFO1 can already reach 99, so
the list is not bounded at the top by which LFO you are on. Whatever makes
LFO2's list longer than LFO1's is *which entries it contains*, not how far the
value travels -- the value is a slot number either way.

`scripts/emu_dest_list.py` reads the list instead: it opens the browser on each
page, walks it, keeps every frame, and dismisses it with `NO` before paging.
An `LFO1` category on LFO2's list and not on LFO1's own is the rule made
visible. Three identical lists would mean the rule is not in this UI at all.

### The rebuilt bridge boots on hardware — 2026-09-21

`lfo4-bridge_DN2_1.11.syx` **starts normally on the instrument.** The build
that drew `EXCEPTION V03 M0 P468004FC` now boots, so the scale-8 diagnosis and
its fix are confirmed on silicon rather than only against a disassembler and a
vendor-binary frequency argument.

That makes the chain complete for the fault: the instrument's own screen named
the vector and the address, the address named an instruction GCC had written
for us, the instruction named an addressing mode the ColdFire does not
implement, and removing it made the same build boot.

**Booting is not the whole pass**, and the rest is still open on this build:
LFO1-3 behaving as stock, a sound saving and reloading unchanged, and DNX
reading lane 4 as all `00 00`. Those are what would catch a carry or a
converter fault, which a boot cannot.

### The bridge passes on hardware — 2026-09-21

Beyond booting: a sound **saved to B249 and loaded into a different track**
comes back correct, and **all three LFOs behave as expected**.

That clears the three pieces a boot could not reach, on silicon:

- the **carry** through `memcpy` / `memset` -- a sound copied between tracks is
  exactly the range operation `csrc/lfo4/carry.c` exists for;
- both **converter hooks**, `0x400dd282` and `0x400dd724`, which run on every
  save and every load and had only ever been exercised from a snapshot and,
  since yesterday, from a real loader boot in the emulator;
- the **per-track engine**, since LFO1-3 are untouched while our stubs run in
  both evaluators every tick.

**And loading into a *different* track is the stronger half of that test.** The
extension table is keyed by the live sound's address, so a different track is a
different key: the path exercised is save-under-one-key then load-under-another,
which is the case `ext_copy` and `ext_carry` exist to handle.

**What it does not prove.** The table is empty on this build, so the save wrote
**zeros** into the eight reserved ids and the load read zeros back. It proves
the hooks do not corrupt a sound -- the risk that mattered, and the one that
would have shown as a sound loading wrong. It does not prove an LFO4 *value*
survives a save, because nothing can set one until the page exists. That check
belongs to step 4b, and `scripts/emu_boot_engine.py` already makes it under the
emulator with eight marked values.

#### The DEST list, read: LFO N offers LFO 1..N-1 minus DEST — 2026-09-21

`scripts/emu_dest_list.py` opens the destination browser on each MOD page and
walks it to the end. The rule the owner described is visible there, and it is
one entry narrower than expected:

| page | the end of its destination list |
|---|---|
| **LFO1** | `FX` -- `Delay Send`, `Reverb Send`, `Bit Reduction`, `Sample-Rate Redu`, `SRR Routing`, `Overdrive`, `OVR Routing`. **No MOD category at all.** |
| **LFO2** | `MOD1` -- `Speed`, `Multiplier`, `Fade In/Out`, `Waveform`, `Start Phase`, `Trig Mode`, `Depth` |
| **LFO3** | `MOD2` -- the same seven |

**Seven, not eight: `Destination` is excluded.** LFO2 may modulate LFO1's
speed, shape and depth, but not LFO1's own destination -- which would be a
destination choosing a destination. So the per-LFO block is
`SPD MULT FADE WAVE SPH MODE DEP`, the eight parameters minus `DEST`.

The browser is ordered by **category**, not by slot: every page opens on
`META -> None` then `SYN -> Osc1 Tune`, identical across all three, and the MOD
categories are at the far end. Two earlier guesses put the difference at the
top and then at the bottom *by slot number*, and both were wrong for the same
reason -- the list is not in slot order at all.

**Directly observed:** LFO1 has no MOD category; LFO2 ends with `MOD1`; LFO3
ends with `MOD2`. **Not directly observed:** `MOD1` also appearing on LFO3's
list, which the owner states and which LFO2's `MOD1` makes near-certain -- the
frame between `FX` and `MOD2` was skipped because a -30 turn from the end
wrapped to `None`. Worth one cheap confirmation before the list is built, not
before it is designed.

#### What LFO4's list has to be

- **LFO4 offers `MOD1` + `MOD2` + `MOD3`** -- 21 entries, seven per LFO.
- **LFO1-3 must not gain a `MOD4` category.** That is what keeps the graph
  acyclic: LFO N targets only 1..N-1, so a fourth LFO added at the end cannot
  be targeted by anything and cannot close a loop.

The open question is unchanged and is now the *only* one left on `DEST`: is
that per-page block **computed from the LFO index** -- in which case LFO4's 21
entries follow from the page existing -- or **enumerated three times**, in
which case there is a fourth enumeration to write and three existing ones to
leave alone. The browser's contents do not answer it; the code that builds the
list does.

### Step 4a passes on hardware — 2026-09-21

`lfo4-slots_DN2_1.11.syx`: several parameters modified, sounds loaded, a
project saved and reloaded. All good.

That clears the **setter divert** on silicon. It replaces the firmware's own
`slot > 100` bound at `0x40037bd0`, which sits on the path of *every* value
edit on *every* page, so a build that got it wrong would not fail in a corner --
it would fail on the first knob turned. Breadth was the right test and it
passed.

#### Where LFO4 now stands

| piece | emulator | hardware |
|---|---|---|
| the extension table, carried through `memcpy` / `memset` | yes | **yes** |
| a sound keeps its LFO4 through save and load | yes | **yes** (no corruption; values untested, nothing can set one) |
| each track has its own LFO4 in both evaluators | yes | **yes** (`tick7`) |
| the bridge: the tick pulls each track's row | yes | **yes** |
| 4a: ids 101-108 reach the table from the real setter | yes | **yes** |
| 4b: the page | -- | -- |

**Everything below the page is proven on the instrument.** What is left is the
page, and it is now specified rather than explored:

- ten parameter records -- eight primaries on slots 101-108, a `SLEW` alternate
  sharing slot 106, a second `MULT` on slot 102;
- the table relocated with those ten appended, and **56 biased bases and 24
  bounds** rewritten;
- a page record, and a fourth entry in the MOD vector;
- a `DEST` list offering `MOD1` + `MOD2` + `MOD3`, 21 entries, while LFO1-3
  gain no `MOD4`;
- the `DEST` **value** translation, already priced at two bytes in two places.

Open before building: whether the per-page `DEST` block is computed from the
LFO index or enumerated three times; the unpaired bound at `0x400c241c`; and
whether anything reaches a parameter record other than through those accessors.

#### The DEST list is a built vector, and it grows by exactly seven — 2026-09-21

`scripts/emu_dest_vector.py` captures the vector the renderer walks
(`0x40106556`, begin in `%a5` and end at `%fp@(-108)`):

| page | vector | entries | over LFO1 |
|---|---|---|---|
| LFO1 | `0x447e25f0..0x447e26cc` | **55** | -- |
| LFO2 | `0x447fabf0..0x447face8` | **62** | +7 |
| LFO3 | `0x447fabf0..0x447fad04` | **69** | +14 |

**LFO3 carries MOD1 *and* MOD2**, which the screens could not show and this
does: its tail runs `77, 79, 81, 82, 83` -- the end of LFO1's block -- then
`85, 86, 87, 89, 91, 92, 93`, LFO2's. The open item from the previous section
is closed.

**And the seven are exactly which seven.** LFO2's tail is `75, 76, 77, 79, 81,
82, 83`; as entries those are records 74, 75, 76, 78, 80, 81, 82 --
`SPD MULT FADE WAVE SPH MODE DEP`. Three of the group of ten are left out:

- entry **78** = record 77 = **`DEST`**, a destination choosing a destination;
- entry **80** = record 79 = **`SLEW`**, and entry **84** = record 83 = the
  second **`MULT`** -- the two **alternates**.

So the rule is `10 - DEST - 2 alternates = 7`, and the alternates being absent
is a second confirmation that they are alternates rather than parameters: a
value you cannot address is not a destination.

**The list is built, not stored.** LFO2 and LFO3 rendered from the *same*
buffer at `0x447fabf0` while LFO1 used another, so the storage is reused and
the contents are produced when the browser opens. Three static per-page lists
would sit at three addresses and persist. That is evidence, not proof, and it
points the remaining question at a filter rather than at three enumerations.

**What LFO4's list must be: 76 entries** -- 55 plus 21, seven each for MOD1,
MOD2 and MOD3 -- while LFO1-3 stay at 55, 62 and 69 with no MOD4 anywhere.

#### Two instructions that looked like the builder and were not — 2026-09-21

A write watch over the vector's region named `0x400392fc` as the hottest writer
of entry values on LFO2 and LFO3 and not on LFO1, which reads exactly like the
filter: one instruction, seven values on one page and fourteen on the next.

**It is the swap inside a sort partition.**

```
400392f8:  movel %a4@,%d0
400392fa:  movel %a5@,%a4@+
400392fc:  movel %d0,%a5@          ; swap, comparator via jsr %a0@
```

It writes entry values because it is **sorting** them. Its absence from LFO1's
top ten is a ranking artefact of `most_common(10)`, not evidence of anything.
The conclusion "one PC emits the destinations, therefore computed" was one
sentence from being written down, and reading the instruction is what stopped
it.

The second candidate, `0x40193f38`, writes the list in order and is
**`std::vector::push_back`** -- `end == capacity`, store, `++end`, tail-call to
the grow path. Generic too.

**The lesson is specific to this image:** it is C++ with `std::vector` and
`std::sort`, so *every* instruction that touches an entry value is a container
primitive shared by the whole program. A hot PC writing the right numbers
proves nothing about who produced them. The producer has to be identified by
its **call site**, which is what `scripts/emu_dest_pushers.py` reads: hook
`push_back` at entry, where `%sp@(0)` is still the return address, and keep the
returns whose pushed value is a parameter index in 74-103.

One call site on both LFO2 and LFO3, pushing seven and then fourteen, is a loop
over preceding LFOs. Different sites per page are three enumerations. Neither
of the first two probes could have told those apart, because both were watching
the wrong end of the call.

#### The destination list is built by one loop over every slot — 2026-09-21

`scripts/emu_dest_pushers.py` identifies the producer by call site rather than
by which instruction wrote the numbers, which is what the two false leads got
wrong:

| page | call site | pushes with an LFO-group value |
|---|---|---|
| LFO1 | -- | **0** |
| LFO2 | `0x400395b4` | 77, values `75 76 77 79 81 82 83` |
| LFO3 | **the same `0x400395b4`** | 140, those **plus** `85 86 87 89 91 92 93` |

**One call site, seven then fourteen.** Not three enumerations.

The loop around it, at `0x4003958a`:

```
moveal %a5@,%a0 ; movel %d2,%sp@- ; moveal %a0@(80),%a0 ; jsr %a0@
beqs  skip                       ; the page's own lookup returned nothing
jsr   0x400dc30e                 ; the entry's flags, record field +32
notl  %d0 ; andl %sp@(56),%d0    ; mask, from the caller's frame
bnes  skip                       ; a required bit is missing
jsr   0x40193f1e                 ; push_back
addql #1,%d2 ; moveq #101,%d1 ; cmpl %d2,%d1 ; bnes
```

**It walks slots 0..100 on every page** -- the same 100 the evaluator's `DEST`
bound uses. So the per-page difference is *not* a loop bound. Two filters
stand between a slot and the list:

1. **`obj->vtable[80](slot)`**, the page object's own lookup, which returns the
   entry for that slot **or zero**. This is where the per-page rule has to
   live: LFO2's page must answer for slots 1-8 and not for 9-24.
2. **a mask** on the caller's frame, ANDed against `~flags`, so an entry is
   included only when it carries every bit the mask requires.

**Record field `+32` is that flags word** (`0x401f7f94 + 60*entry + 24`, which
is record + 32). Measured across LFO1's group it reads `0x00NNffff`, and the
`NN` is **per slot, not per record**: `SLEW` and `SPH` share `0x6bffff`, and
both `MULT` records share `0x67ffff` -- the two alternates pairing with their
primaries exactly as they do everywhere else. The low 16 bits are all set on
every record read so far, so nothing has yet been seen to fail the mask.

**What is settled, and what is not.** The list is produced by one loop for
every page, so there is no per-LFO enumeration to extend -- that question is
closed. What decides which slots a page answers for is the vtable-80 lookup,
and **that has not been read**. The plausible reading is that a fourth LFO
page, being another instance of the same page class, computes it from its own
index and inherits the rule; that is a hypothesis for when the page object
exists, not a finding.

**For the build it changes little:** LFO4's list must hold 76 entries, and the
mechanism that fills it is shared code that already handles "every earlier LFO"
generically. Nothing here is a site list.

#### The unpaired bound is a second table, and the `+0` pointers are handlers

**`0x400c241c` (the one `cmpil #321` that sits near no biased base).** It is
not an unrelated 321. It indexes a **second table over the same entry space**:

```
cmpil #321,%d0                   ; the same bound
lsll  #6,%d1                     ; entry * 64
lea   %a1@(0,%d0:l:4),%a0        ; + entry * 4  ->  entry * 68
addil #0x4243325c,%d0            ; a RAM base
```

**321 entries of 68 bytes at `0x4243325c`**, 21,828 bytes, sitting in RAM
beside the page-record table at `0x42432c00` and the machine table at
`0x42432b24`. A runtime companion to the image's 60-byte records, indexed by
the same entry number -- which is why it shares the `321`.

It looked **far cheaper than the first table**: the base appears at only **6
sites** across five field offsets (`+0` x2, `+4`, `+20`, `+44`, `+60`), against
56 for the parameter table.

> **That reading is wrong, and the section below "The companion table has no
> base" has the measurement.** Those six sites are *entry 0's* fields. The
> table's initialiser is unrolled and writes **every** entry's addresses as
> absolute literals -- 902 of them, entries 0 to 320 with no gaps. There is no
> base, and the table does not move.

**The `+0` code pointers (the last open route).** Every one of the 320 records
has `+0` in code -- and there are only **51 distinct values** across 320
records. That is a shared handler per parameter *kind*, called **with** a
record the caller already holds, not a way of finding one. It opens no
addressing route.

#### So the addressing routes are enumerated

| route | sites |
|---|---|
| 60-byte parameter table, three biased bases | **56** |
| 68-byte runtime table, five biased bases | **6** |
| `cmpil #321`, shared by both | **24** |

No record boundary appears as a literal anywhere, the `+0` pointers are
handlers, and every accessor recomputes its address from a biased base rather
than caching a pointer -- so **patching the bases redirects every lookup**.

That closes all three questions this section opened. What extending the
parameter set costs is now a list: two tables to grow, 62 bases and 24 bounds
to rewrite, each a four- or six-byte literal that the build can assert is stock
before touching -- exactly as the four existing hook sites already do.

#### The slot lookup is not the differentiator — 2026-09-21

The hypothesis the build would have rested on was that a page's
`vtable[80](slot)` decides which slots it answers for, so a fourth LFO page
would inherit the rule from its own index. **Tested before building, and it is
wrong.**

```
  LFO1: 1111 lookup(s), slots 0..100, target 0x40036720, object 0x446ce950
  LFO2: 1111 lookup(s), slots 0..100, target 0x40036720, object 0x446ce950
  LFO3: 1010 lookup(s), slots 0..100, target 0x40036720, object 0x446ce950
```

All three call the **same function** -- which alone would have supported the
hypothesis -- **and pass the same object**. That is the part that kills it: a
lookup given identical inputs cannot return different answers per page, so it
is not where "LFO2 may target LFO1 and not LFO3" lives.

**The probe printed the wrong conclusion**, because its verdict was written for
"same target = shared rule" and did not consider that an identical object
makes the call page-independent. The data was right and the sentence under it
was not. Reading the numbers rather than the summary is the only reason it was
caught -- the same failure the sort-swap and `push_back` leads had.

That leaves exactly one per-page input in the loop: the **mask** at
`%sp@(56)`, ANDed against `~flags`. `scripts/emu_dest_mask.py` reads it.
Three masks differing by one bit per LFO is a rule a fourth page extends.
Three unrelated constants are three constants, and LFO4 needs a fourth.

### The firmware already reserves a fourth LFO in its destination flags — 2026-09-21

The per-page filter is a **mask against a capability field in each parameter
record**, and the record side of it already has a fourth LFO in it.

**The masks**, read at `0x400395a4` while each browser opens:

| page | mask | bits |
|---|---|---|
| LFO1 | `0x00001e00` | 12, 11, 10, 9 |
| LFO2 | `0x00000e00` | 11, 10, 9 |
| LFO3 | `0x00000600` | 10, 9 |
| **a fourth would be** | **`0x00000200`** | **9** |

An entry is kept when `~flags & mask == 0` -- it must carry **every** bit the
page demands -- so each page drops the top bit and admits strictly more.

**The flags are record field `+44`**, not `+32` as recorded earlier in this
file. The accessor is `movel %a0@(24,%d0:l),%d0` and **objdump prints indexed
displacements in hex with no prefix** (`docs/version-anchors.md`), so that is
`0x24` = 36, and `8 + 36` = **44**. The `+32` reading passed every sanity check
it was given -- the alternates paired with their primaries there too -- which
is exactly why it survived. It was wrong.

**Every distinct value of field +44, across all 320 records:**

| value | records | targetable by |
|---|---|---|
| `0x00001e00` | 190 | LFO1, LFO2, LFO3, **a 4th** |
| `0x00000000` | 103 | nobody |
| `0x00000e00` | 8 | LFO2, LFO3, **a 4th** -- LFO1's own block |
| `0x00000600` | 8 | LFO3, **a 4th** -- LFO2's block |
| **`0x00000200`** | **8** | **a 4th only** -- LFO3's block |
| `0x00040000` / `0x00020000` / `0x00010000` | 1 each | nobody -- the three `DEST` records |

**LFO3's eight records are marked targetable by an LFO that does not exist**,
and **nothing in the shipping firmware ever passes `0x0200`**. The staircase is
complete for four LFOs and only three consume it.

This is the same shape DNX found in the stored format -- the fourth slot of
each group of eight reserved and unused, and p-lock rank `4*param + 0` never
written (§"Why the LFO4 goal is plausible"). **Three layers now: the stored
format, the p-lock ranks, and the destination capability bits.** Elektron left
room in all three.

#### What it means for the build

**LFO4's destination list needs no data change at all.** A page passing
`0x0200` admits 190 ordinary records plus LFO1's, LFO2's and LFO3's eight
apiece; the loop is over slots and the lookup returns one entry per slot, so
the two alternates in each group collapse and each block contributes seven --
**190 + 21 + the rest of the ordinary list = the 76 entries measured**, arrived
at from the flags rather than by counting screens.

And the acyclic property is **enforced by the data, not by us**: LFO4's own
records will carry `0x0000` or a fifth-LFO bit, so no existing page can target
them whatever we do.

The `DEST` records carry one bit each -- `0x40000`, `0x20000`, `0x10000` for
LFO1, LFO2, LFO3 -- descending the same way. A fourth would be `0x8000`, which
is consistent but **unverified**: nothing reads those bits in anything measured
here, and the converter special-case at `0x4004cb04` keys on the slot number
instead.

### Step 4b, built: the table moves, and the page is two stubs — 2026-09-21

Everything above was the read. This is what got built, and the three things the
read had wrong.

#### Correction: the bound has two spellings, and there are 55 of it

§"What extending the table would actually cost" counts **24** `cmpil #321`
sites. That was a scan of `%d0` only. Across all eight data registers there are
**38**, and the bound has a second spelling — `cmpil #320` with `bhi`, which
rejects the same entries `scs` against 321 keeps — with **20** more.

Of those 58, three are not this bound at all: they step `d2` by 20 up to 320,
sixteen iterations of something else (`0x40031fee`, `0x40032422`, `0x400325e2`).
The other 55 are, and six of them needed disassembling rather than pattern
matching to say so:

| site | why it counts |
|---|---|
| `0x40036af4`, `0x40036bbc` | check an argument, then call `0x400dbff0`, an accessor |
| `0x400379ec` | the same check at a function's entry on its argument |
| `0x4003950a` | `d2 += 1` to 321: a **loop over every entry** |
| `0x4004b17a`, `0x400dc7f0` | `d2 += 1` and `lea 60(aN),aN`: loops walking the records |

The two loops with `lea 60(aN),aN` are the strongest confirmation the census is
of the right thing: the stride is in the instruction.

#### Correction: there is no block of ten spare records

Before relocating anything, the cheaper route was worth pricing — ten records
the table already has and nothing uses. Reading every page record's eight
entries (ids 0..36) says **163 of the 320 are named by a page** and 157 are
not, which sounds like plenty and is not: the unnamed ones are alternates,
records reached by group and id rather than by page, and the 18 at the front
that carry `group == -1`. None of it is a run of ten that nothing reads, and
"unreferenced by a page record" is not "unused".

So the table is relocated, which the next section prices honestly.

#### The record's fields, read by diffing the three LFO groups

Positions 0..9 of LFO1's group against LFO2's and LFO3's, word by word. What
varies is what a fourth would have to change; what does not is what it copies.

| off | field | LFO1 → LFO2 → LFO3 |
|---|---|---|
| `+0` | handler | same within a position |
| `+4` | `0x40218572` | the same word in all 320 records |
| `+8` | **group** | 26, 27, 28 |
| `+12` | **value slot** | 1-8, 9-16, 17-24 |
| `+20` | range | same |
| `+24` | default | same, twice not |
| `+32` | unknown | `0x0066ffff`.., `0x006fffff`.., **`-1` on LFO3** |
| `+36` | **NRPN** | 170.., 178.., 186.. — `-1` on `SLEW` |
| `+40` | unidentified, **unique** | 79-88, 89-98, 99-108 |
| `+44` | destination flags | `0x0e00`, `0x0600`, `0x0200` |
| `+48` | long name | `Speed`, `Multiplier`, … — shared |
| `+52` | **page label** | `LFO1`, `LFO2`, `LFO3` |
| `+56` | short name | `SPD`, `MULT`, … — shared |

`+40` is **unique across all 320 records** — 320 distinct values, no
duplicates, no `-1` — so it is a key, and a copy would collide. Its meaning is
still unknown (`dnfw.params.record.physical_id` keeps the history of three
wrong names for it), so LFO4's ten take values from **gaps inside the range the
table already uses**: in range whatever it indexes, claimed by no record.

`+36` is the NRPN, settled 45/45 against Elektron's Appendix C. LFO4's ten are
`-1`: **no NRPN, no MIDI address**, the convention `SLEW` already uses in all
three stock groups. Ten free numbers could be assigned later; doing it now
would be inventing a MIDI map to go with a page that does not exist yet.

`+8` is copied from LFO3 rather than given a new number. A new group is a new
index into whatever reads that field, and nothing here has read it; LFO3's is
known good, and `(group, id)` still names each record uniquely because the ids
are 101-108.

#### What the relocation costs, and what a mistake in it does

| | sites |
|---|---|
| 60-byte table, three pre-biased bases | 56 |
| 68-byte runtime table, five field offsets | 6 |
| the entry space bound, both spellings | 55 |
| | **117** |

`src/dnfw/patch/paramtable.py` derives all three lists from the image and
asserts the counts, rather than holding addresses; `test/test_paramtable.py`
checks that relocating touches **only** those bytes.

**A missed site degrades, it does not corrupt**, and that is worth stating
because it is what makes the change safe to ship before it is fully proven. The
copy is byte-identical for all 320 stock records, so a base that was not found
keeps reading the old table and keeps being right; it reads garbage only for
the ten new entries. A bound that was not found clamps a new entry to the
fallback record. Neither can make a stock parameter wrong. The failure that
*could* be serious is the opposite one — rewriting a literal that was never
this table — and every one of the 117 is asserted to hold its stock value
before it is touched.

That safety is also what makes a missed site invisible, so
`scripts/emu_table_watch.py` watches the old ranges for **reads** while the
firmware runs, with the stock image through the same path as the control: if
the control reads the old table and the build never does, the list is complete.

#### The page is two stubs, because both structures are built at run time

Neither the page-record table (`0x42432c00`, ids 0..36) nor the mode's page
vector exists in the image, so neither can be written at build time.

- **`0x400c2474`** is `id -> 0x42432c00 + 44 * id`, rejecting anything above 36.
  `lfo4_page_stub` answers for LFO4's id and lets every other one through to
  the arithmetic it replays.
- **`0x40063f5c`**, inside the mode-header renderer, is where `%a2` becomes the
  mode object. `lfo4_mode_stub` replays that load and calls `lfo4_pages`, which
  recognises the MOD mode by its vector holding exactly `4 5 6` and, once,
  gives it a fourth entry.

The record is assembled from LFO3's the first time a MOD header is drawn,
because its interesting fields are **pointers to string objects the UI built at
startup** — `+0` is an object holding `LFO3`, `+4` one holding `MOD`, and the
renderer passes `record + 4` to the text routine. Copying LFO3's 32-byte name
object and changing one character gets a correct `LFO4` without this code ever
having to learn that layout; `+4` is reused as it stands, since every page in
the mode shares it.

**What this does that it cannot prove.** The vector's `begin` is replaced with
an array this build owns, so a destructor that freed it would be freeing memory
the firmware's allocator never handed out. UI mode objects are built once and
kept, but that is an observation rather than a guarantee, and switching modes
hard is how it gets checked.

#### The DEST mask is a virtual function, and LFO4 will inherit LFO3's

The three per-page masks are not constants at the browser's call site. They are
**three thunks**, at `0x400c2a90`, `0x400c2aae` and `0x400c2acc`, each of which
writes one value into the argument frame and tail-branches to the same routine
at `0x400c2894`:

```
movel %sp@(8),%d0 ; movel %d0,%sp@(4)
movel %sp@(12),%d0 ; movel %d0,%sp@(8)
movel #7680,%d0                      ; 0x1e00, and 0x0e00 and 0x0600 below
movel %d0,%sp@(12)
braw 0x400c2894
```

Each is installed by a registrar at `0x400c3f80` into field `+12` of a 16-byte
descriptor, in a table of them at `0x42431d48`, `0x42431d58`, `0x42431d68`,
`0x42431d78` — one per parameter kind, four of which are visible in that
registration sequence and only three of which carry an LFO mask.

**So the mask belongs to a descriptor, and the question is which descriptor a
record gets.** It is not the record's `+0` handler: all three `DEST` records
share `0x400e30f0`. The field that differs between them and is not a name is
`+8`, the group — 26, 27, 28.

That makes a **prediction, written down before the build is flashed**: LFO4's
records carry LFO3's group, so LFO4's `DEST` list will be LFO3's — `MOD1` and
`MOD2`, not `MOD1 MOD2 MOD3`. LFO4 would be able to modulate LFO1 and LFO2 but
not LFO3. The graph stays acyclic either way, and nothing about it is unsafe;
it is one category short of the intended list.

It also names the fix, if the prediction holds: a **fourth descriptor** with a
mask thunk of our own writing `0x0200`, and a group for LFO4 that selects it.
That is a separable change and it is not made blind — it waits on the screen
saying which list actually appears.

The `0x8000` this build writes into LFO4's `DEST` record's capability field is
**inert** on that reading. It continues the `0x40000 / 0x20000 / 0x10000`
pattern and costs nothing, but nothing measured here reads those bits.

### The relocation, measured: the old table is never read again — 2026-09-21

`lfo4-table` **boots from reset without faulting**, and `scripts/emu_table_watch.py`
watched both address ranges through that boot and through 330 calls into the
accessor at `0x400dbeb6`:

```
    during boot, old 60-byte: 0 read(s)
    during boot, new 60-byte: 1,846 read(s)
    during boot, old 68-byte: 0 read(s)

    with the accessor calls, old 60-byte: 0 read(s)
    with the accessor calls, new 60-byte: 2,176 read(s)
```

The boot is not a quiet one — the gate counted **2,192 kit loads** in the same
450 M instructions — so the parameter table is being used heavily, and every
one of those uses went to the new address. **The 56 base sites are complete for
everything this boot executes.** The new range being read is the control: a
probe reporting "nothing reads the old table" while watching nothing at all
would look exactly the same.

#### And the run caught this project's own documented trap, again

The same run reported three failures, and all three were the harness:

- **"the firmware filled the relocated runtime table": 0 reads.** A table being
  *filled* is **written**, not read. The check could not have passed however
  well the build worked. It now counts both.
- **Every one of the 330 accessor calls returned 0.** Thirty-eight "matched"
  and they were exactly the thirty-eight records whose group is 0.

The second is §"Step 4a result" happening a second time: a call into
firmware-resident code on a machine with live timers gets interrupted,
`emu_start` stops on its instruction count instead of at the return address,
and `d0` holds whatever the handler left. The tell was in the run's own
numbers — **2,176 reads across 330 calls**, six per call, when the accessor
reads the table exactly once. Interrupt handlers were running inside the calls.

The answer recorded last time was *read the value out of memory instead*, and
that works when the value is in memory. Here the routine's **answer** is the
subject, so the fix has to be the other one: `After.call` now raises the
interrupt level to 7 for the duration and restores it after. Same lesson, one
layer down — **a harness that reads a result through firmware it did not write
needs a control that fails when the reader is broken**, and this time the
control was there and did its job.

### The bound that must not be raised — 2026-09-21

Found before flashing, and it is the kind of fault the boot gate cannot see.

`param_set_tables_build` (`0x400dc4d0`) walks every parameter record and files
its **entry number** into tables indexed by the record's **value slot**. There
are three of them, one per band of parameter groups, and the routine zeroes
each itself on the way in:

```
pea 0x194 ; pea 0x42c64b3c ; jsr memset      404 bytes = 101 longwords
pea 0x194 ; pea 0x42c649a8 ; jsr memset
pea 0x194 ; pea 0x42c647ac ; jsr memset
pea 0x48  ; pea 0x42c64cd0 ; jsr memset      the filter table, 72 bytes
```

and the LFO branch — groups 26, 27, 28, selected by `addil #-26,%d1 ; moveq
#2,%d6 ; cmpl %d1,%d6` — files with

```
0x400dc6d6  movel %d2,%a1@(0,%d7:l:4)     ; flat[slot] = entry
```

where `%d7` is the record's `+12`, the value slot. **101 longwords is slots
0..100.** LFO4's records carry slots 101-108, so raising this loop's bound
files eight entries **32 bytes past the end of all three tables** — and
`0x42c64b3c + 404` is `0x42c64cd0`, the filter table the same routine zeroed
two calls earlier.

It boots. It draws. Nothing faults. The instrument would have come back with
filter parameters behaving oddly and no way to connect that to a fourth LFO.

**So that one bound stays at 321** (`dnfw.patch.paramtable.NOT_THIS_TIME`), and
the loop walks the relocated table's first 320 records doing exactly what stock
does. 54 bounds, not 55. The cost is that LFO4's slots are never filed, which
costs nothing yet: `0x400dc02a` bounds slots at 100 in its own right and
answers 0 for 101 either way. That is **the read side**, and it is now a
defined piece of work rather than a loose end:

- `moveq #100` at `0x400dc02c` -> `moveq #108`, one byte;
- the three slot tables relocated at 109 entries — **five literals each**, plus
  their `pea 0x194` size immediates;
- then this bound can be raised with the rest.

`scripts/emu_table_watch.py` now hooks all three filing instructions and reads
`%d7` at each, so the next build that gets this wrong is told the highest slot
it filed instead of being congratulated on booting.

#### What this means for `lfo4-page` as it stands

The fourth page draws with LFO4's names. Its **values are not wired**: a
record's value comes from the sound at `+0x14 + slot*2`, and slot 101 is
`+0xDE`, which is the machine type — not a value of LFO4's at all. Reading it
is harmless and the 4a divert still stops the firmware writing there, so a knob
turn lands in the extension table exactly as it did in `lfo4-slots`. But what
the screen shows next to that knob is not what the knob set.

That is worth saying plainly before anyone flashes it: **the page is the
milestone, the values are the next one.**

### The companion table has no base, and the probe that proved it — 2026-09-21

`lfo4-table`'s first two builds relocated the 68-byte companion table by
patching six literals. `scripts/emu_table_watch.py`, watching both address
ranges through a boot:

```
    during boot, old 68-byte: 0 read(s), 10,591 write(s)
    during boot, new 68-byte: 0 read(s),  5,638 write(s)
```

**Written in two places, read in neither.** The six patched literals moved the
*accessor*; something else was still writing to the old address, ten thousand
times.

Scanning the image for **every** four-byte value inside the old table's span
says what: **902 literals**, in blocks of five per entry —

```
pea   <entry + 4>
pea   <entry + 20>
clr.l <entry + 0>
clr.l <entry + 44>
clr.l <entry + 60>
```

— covering entries **0 to 320 with no gaps**. The initialiser is **unrolled**.
The six sites found earlier are simply entry 0's, which is what a search for
one base finds when there is no base to find.

**So the companion table does not move**, and its bound at `0x400c241c` stays
at 321 with it: past its end are the RTOS task control blocks (`0x424388ac`,
from the boot's own `TASK_CREATE` log), and an entry of 321 there would write
into one. Left alone it clamps to entry 0, the fallback, exactly as an
out-of-range entry always did. **53 bounds, not 55.**

`csrc/lfo4/prm68.c` is deleted; there was never anything for it to be.

#### What this says about reading a structure from its accessors

Both mistakes this evening are the same mistake. The bound looked like 24 sites
because the scan only looked at `%d0`. The companion table looked like six
sites because the search only asked about entry 0. **In each case the method
answered a narrower question than the one being asked, and answered it
correctly**, which is why neither looked wrong.

What caught both was the same thing too: a probe that watches the *old*
addresses and requires silence. The first build read the old parameter table
zero times and that was the pass; the same run wrote to the old companion table
10,591 times and that was the failure. Neither number could have been guessed
from the image.

#### And the accessor the probe was calling returns a predicate

`0x400dbeb6` reads record `+8` and then returns `5 <= group <= 10` as 0 or 1:

```
movel %a0@(0,%d0:l),%d0 ; subql #5,%d0 ; moveq #5,%d1
cmpl %d0,%d1 ; scc %d0 ; mvsb %d0,%d0 ; negl %d0
```

So the 292 entries that "differed" from the group were the probe's expectation
being wrong, not the firmware's answer. The probe now calls `0x400dc11a`, which
returns record `+40` — the field that is **unique across all 320 records**, so
a wrong answer names the record it came from.

### `lfo4-table`, measured clean — 2026-09-21

`scripts/emu_table_watch.py` on the corrected build, one boot from reset and
330 calls into `0x400dc11a`:

```
  during boot, old 60-byte:            0 read(s),      0 write(s)
  during boot, new 60-byte:        1,766 read(s),  4,950 write(s)
  during boot, the 68-byte companion:  0 read(s), 10,602 write(s)

  the accessor calls alone, new 60-byte: 330 read(s)

  entries 321..330 answer [19, 21, 38, 78, 109, 118, 129, 139, 157, 159]
  param_set_tables_build filed 82 slot(s), highest 24
  all checks pass
```

Four things, and they are the four that were in doubt:

- **The old table is never touched**, through a boot that the gate counted
  2,192 kit loads in. The 56 base sites are complete for everything that runs.
- **Every one of the 330 entries answers exactly what the relocated table
  holds**, zero differing — the firmware's own arithmetic, not the probe's.
- **Entries 321 to 330 answer with LFO4's ten ids**, the gap values the build
  picked out of the range no record uses. The firmware reaches records that did
  not exist an hour ago.
- **The highest slot filed is 24**, so nothing was written past the three
  101-entry tables. The bound left alone is the reason, and this is the number
  that says so.

The companion table being written 10,602 times *where it lives* is now the
pass, not the failure: it does not move, and a build that moved it would read
an empty one.

**One thing worth noting rather than explaining away:** 4,950 **writes** into
the parameter table during boot. The records are read-only data in the image,
so something patches them at run time — per-machine ranges are the obvious
guess and it is only a guess. It does not affect this build, because every
write goes through the same bases every read does and lands in the copy. But
"the parameter table is read-only" is not true of this firmware, and anything
built on that assumption later should know.

### Step 4c: the read side is one site, and it was found by running — 2026-09-21

The plan priced the read side at "three slot tables relocated plus a bound".
**That was the wrong route entirely.** The page does not reach a value through
the slot tables; it goes entry -> slot -> the sound's own array, and the guard
in front of that is the setter's guard in mirror.

#### 119 candidates, two of which execute

A sound's values live at `+0x14`, two bytes per slot, so every read of one
carries the addressing mode `(20, An, Xn.l*2)`. Scanning the image for that
extension word finds **119** instructions. Which is the page's cannot be read
off the list -- most are coincidence, and the rest belong to MIDI, the mirror
fill, and save.

`scripts/emu_value_reads.py` hooks all 119 and opens the MOD pages:

```
  after [MOD] x1:  0x40037194  x169     0x40030f34  x13
  after [MOD] x2:  0x40037194  x39      0x40030f34  x3
  after [MOD] x3:  0x40037194  x26      0x40030f34  x2
  2 of 119 ever fired
```

**Two.** And `0x40030f34` clamps its index to `0..15` eight instructions
earlier (`moveq #15,%d0 ; cmpl %d2,%d0 ; bge`), so no LFO slot can reach it.
One site.

#### And it is step 4a's own six bytes

```
0x4003717c  moveq #100,%d0
0x4003717e  cmpl  %d2,%d0
0x40037180  blts  0x4003719a        ; slot > 100 -> return 0
...
0x40037194  mvsw  %a0@(20,%d2:l:2),%d0
```

| step | site | stock bytes | above 100 |
|---|---|---|---|
| 4a, the write | `0x40037bd0` | `7064 b082 6d72` | writes nothing |
| **4c, the read** | `0x4003717c` | `7064 b082 6d18` | returns zero |

The same three instructions, the same six bytes, the same "stock does nothing
here" that made the write safe to divert. `lfo4_get_stub` is `lfo4_set_stub` in
a mirror, down to taking the live sound from the firmware's **own** virtual
call -- `a2@(16)`, vtable slot 40 -- which is what the instructions it jumps
over were about to do.

#### The round trip, measured

`scripts/emu_lfo4_value.py` puts `0x2a5c` in the table for every track's sound,
opens the MOD page, and rewrites the slot at the bound the way step 4a's
harness rewrote it at the setter:

```
  control page: 0 diverted read(s), 0 declined
  rewritten page: the bound saw 26 read(s) for slots [17, 18, 19, 20, 21, 22, 23, 24]
  lfo4_gets 26, sound 0x4210c0c0, slot 101, value 0x2a5c
  the function returned [10844] at its epilogue
  all checks pass
```

Slots **17 to 24** are LFO3's eight, so the twenty-six reads are a real MOD
page drawing its real parameters. The control -- the same page with nothing
rewritten -- diverted **zero**, so slots the firmware owns still answer from
the sound. And `10844` is `0x2a5c`: the value went into the table through
`ext_set` and came back out of `d0` at the firmware's own epilogue.

**Nothing in that harness calls into the firmware for a result.** The value is
read out of `d0` at a hooked instruction, because a call on a machine whose
timers are running returns whatever an interrupt handler left there.

#### What it changes

`lfo4-value` is the first build where a fourth LFO is whole: a knob on the
fourth MOD page writes to the table (4a), the page reads back what it wrote
(4c), the engine modulates from it (step 3), and a save carries it (step 2).

It also fixes **turning**, not just display, and that is measured rather than
argued: a `push_and_turn` on the MOD page reaches the same read bound **133
times**, for slots 17 to 24. A UI that computes `new = old + delta` fetches
`old` through this site. Without the divert, `old` on LFO4's page would have
been the sound's `+0xDE` -- the machine type -- and a turn would have jumped
somewhere arbitrary. With it, `old` is the value the knob last set.

The control in that run is worth keeping too: the same page drawn with nothing
rewritten reached the bound **39 times and diverted none of them**, which is a
stronger statement than "zero diverted" on its own. The bound was reached; the
divert declined every slot the firmware owns.

### The gates, all four builds — 2026-09-21

| build | boots from reset | the engine and save/load | its own subject |
|---|---|---|---|
| `lfo4-table` | **yes**, 1 frame, no fault | — (a subset of the next row) | the relocation: `emu_table_watch.py`, all checks pass |
| `lfo4-page` | **yes**, 1 frame, no fault | **yes** | the page: `emu_lfo4_page.py`, 12 checks pass |
| `lfo4-value` | pending | pending | the read: `emu_lfo4_value.py`, 7 checks pass |

`emu_boot_engine.py` on `lfo4-page` — reset, then evaluator A, then a stored
sound through both converters, in one machine:

```
  lfo4_refresh ran 128 time(s) during 8 frame(s)
  load: the table holds ['0x2a01' ... '0x2a08']
  save: the stored ids hold ['0x2a01' ... '0x2a08']
  boot from reset, the engine, and save/load: all three in one machine.
```

128 is 8 frames x 16 tracks. `lfo4-page` is `lfo4-table` plus two UI hooks that
a boot never reaches, so this covers the relocation's effect on the engine and
the converters as well.

**It is also the regression test for the interrupt masking** added to
`After.call` this evening. That change touches every harness built on
`emu_boot_engine`, and this run is one of them behaving exactly as it did
before.

### Step 4d: the page drew empty dials, and the companion table is why — 2026-09-21

The first picture of the fourth page settled a great deal at once, and raised
one thing nothing else had.

`scripts/emu_lfo4_screens.py` installs the build into `ui1200M` and taps
`[MOD]` five times. **This is valid now and was not this morning:** a snapshot
has already built every runtime table from the *stock* parameter table, and
while `lfo4-table` also relocated the 68-byte companion the two disagreed --
the snapshot had filled one address and the build read another. The companion
does not move any more, and the 60-byte copy is byte-identical for all 320
stock records, so everything the snapshot computed still holds.

```
  before any tap: pages [4, 5, 6], swapped 0
  [MOD] x1: pages [4, 5, 6, 37], showing index 0
  [MOD] x4: pages [4, 5, 6, 37], showing index 3
  [MOD] x5: pages [4, 5, 6, 37], showing index 0
```

**The header reads `MOD (4/4)`**, the labels are `SPD MULT FADE DEST` over
`WAVE SPH MODE DEP`, and `[MOD]` cycles past the fourth page back to the first.
Nothing had to be taught that there are four pages.

#### And every widget was empty

Beside LFO3's page -- `512` in a box for `MULT`, `SYN PD2` for `DEST`, a square
glyph for `WAVE` -- LFO4's eight were identical blank circles. Not wrong
values: **no widget at all**, the fallback's.

`scripts/emu_lfo4_widget.py` hooks the companion-table accessor while each page
draws:

```
  [MOD] x3: entries [10, 95, 96, 97, 98, 99, 101, 102, 103]
  [MOD] x4: entries [10, 321, 322, 323, 324, 325, 327, 328, 329]
            96 of them answered 0x4243325c -- entry 0, the fallback
```

**The page asked the right questions.** Entries 321-329, its own eight plus the
shared entry 10, in the same shape LFO3 asks for 95-103. The accessor's bound
is 321 and clamps everything above it to entry 0, so each parameter was handed
the fallback row and drew the fallback's widget.

#### Ten rows, and the same divert shape a third time

The table cannot move -- 902 absolute literals, no base -- so the accessor is
diverted for LFO4's ten entries and answers from rows this build owns, copied
whole from LFO3's at first use. Copied, because the fields are pointers to
objects the UI built at startup and this code has never had to learn their
layout; at first use rather than at init, because at init the firmware has not
filled them yet.

With it, the fourth page draws `BPM 1` in a box for `MULT`, a triangle glyph
for `WAVE`, a curve for `MODE`, `---` for an unassigned `DEST`, and dials with
their `- +` marks for `SPD`, `SPH` and `DEP`. The same widget kinds LFO3 has,
showing LFO4's own values.

#### The count assertion earned its keep

Adding this broke the build with `expected 53 bound sites, found 55` -- and
those two extra sites were **in our own code**. `lfo4_comp_stub` compares
against `LFO4_ENTRY0`, which is 321, and assembles to exactly the `cmpil #321`
the site scan hunts for. A build's content is longer than stock: the appended
area, with this project's compiled C in it, follows.

Without the assertion the build would have "raised the bound" inside its own
stub, turning `LFO4_ENTRY0` into 331 and making the companion divert decline
every entry it exists for -- silently, back to empty dials. The scans stop at
`STOCK_END` now, and a test holds them there.

#### And the same *structural* mistake, three times in one evening

`hooks.S` is one assembly source; `--gc-sections` works on sections; so every
stub in a file is kept whenever any stub in it is an entry, and then every
symbol those stubs call must link -- in **every** build that compiles the file.

- this morning: step 4a's `lfo4_set_stub` had broken three tests since it was
  written, because the test's source list lacked `setter.c`;
- tonight: `lfo4_get_stub` in `hooks.S` broke `lfo4-table` and `lfo4-page`;
- an hour later: `lfo4_comp_stub` in `pagehooks.S` broke them again.

The rule, and it is now written at the top of `valuehooks.S`: **a stub belongs
in a file that only the builds patching its site compile.** `hooks.S` is the
sites every LFO4 build has, `pagehooks.S` is the page's two, `valuehooks.S` is
`lfo4-value`'s two. The test fixture compiles the whole directory, so it cannot
be the thing that notices.

### Step 4e: the waveform preview is re-coded per LFO — 2026-09-21

With step 4d the fourth page drew real widgets, and the owner, looking at it
beside LFO3's, said it was still not right. It was not: **`SPH` drew a plain
dial where LFO1-3 draw the start-phase braces around the waveform.**

Two wrong guesses first, both cheap and both worth recording:

- **The companion row was copied; maybe it should be referenced.** The owner's
  reading was that the glyph is reused between the LFOs rather than owned by
  each. Changing `lfo4_companion` from a copy of LFO3's rows to LFO3's rows
  themselves changed **nothing on screen**. The change is kept -- it is simpler,
  and it removes 680 bytes of BSS and the question of when to copy -- but it
  was not the fault.
- **Maybe the values differ.** Giving LFO4 exactly LFO3's eight values made
  seven widgets match exactly: the same `512`, the same `SYN PD2`, the same
  square waveform. `SPH` was still a plain dial. So it was never a value.

#### What it was, found by diffing what the two renders execute

`UC_HOOK_BLOCK` over one `[MOD]` tap each, and the difference of the two sets:

```
  page 3 blocks 2437, page 4 blocks 2225
  reached while drawing LFO3 and never while drawing LFO4: 12
    0x4010e00a  0x4010e010  0x4010e27e  0x4010e296
    0x4010e2a2  0x4010e2ae  0x4010e2be  ...
  and the reverse: 0x4010e2f0 among them
```

`0x4010e1f4` onward is **three near-identical blocks, one per LFO**, chosen by
an index in `%d0`, each calling `0x4006538e` five times with its own LFO's
entry numbers **written as literals**:

| index | block | WAVE, SPH, MODE, SPD, DEP |
|---|---|---|
| 0 | `0x4010e1f4` | 79, 81, 82, 75, 83 |
| 1 | `0x4010e22e` | 89, 91, 92, 85, 93 |
| 2 | `0x4010e27e` | 99, 101, 102, 95, 103 |
| 3 | — falls to `0x4010e2f0` | none |

**The owner's word for it was the right one: it is re-coded, not reused.** The
glyph drawing is shared; the five entry numbers that feed it are typed out
three times.

`scripts/emu_lfo4_wave.py` then asked the only question that decides the fix:

```
  [MOD] x3: the dispatch saw index [2]
  [MOD] x4: the dispatch saw index [3], fell through with [3]
```

**The dispatch already computes 3 for LFO4.** There is simply no block for it.

#### A fourth block, asserted to be the third

`lfo4_wave_four` in `csrc/lfo4/valuehooks.S` is LFO3's block transcribed, and
the build proves it rather than asking to be believed: it takes the firmware's
own 72 bytes at `0x4010e27e`, substitutes the five `pea` immediates
(99→325, 101→327, 102→328, 95→321, 103→329), and **refuses to build unless the
assembler produced exactly that**. A transcription that had drifted into a
paraphrase would still assemble and would draw something subtly wrong.

The fallback's first eight bytes become a jump to a stub that takes index 3 and
replays them for everything else.

#### The result, measured rather than admired

Given LFO3's own eight values, LFO4's page and LFO3's page are compared frame
to frame -- 1,024 bytes of a 128x64 panel:

```
  1,011 identical, 13 differ
  at byte offsets [343, 351, 359, 367, 1001, 1002, 1003, 1009, 1010, 1011, 1017, 1018, 1019]
```

Rendered, those thirteen bytes are **the digit in `MOD (3/4)` versus `(4/4)`,
and the page-position dots down the right edge.** Everything else -- all eight
widgets, the waveform preview, the phase braces -- is the same picture.

That is the strongest statement available short of the instrument: *with the
same values, the fourth LFO's page is the third LFO's page.*

### What the instrument said, and what each report turned out to be — 2026-09-21 evening

`lfo4-value` was flashed. Five reports, and they sort into three kinds.

#### Fixed: the defaults

> "the FADE default in LFO4 is not 0 but -64" ... "also DEPTH is -128"

Both are bipolar with a record default of `0x4000`, which displays as 0, so a
stored **zero** lands at the bottom of the range. The arithmetic matches the
report exactly, and two more were wrong the same way and less visibly: `SPD` at
0 instead of 112, `MULT` at the lowest multiplier instead of the third.

The design already handled this -- `ext_add` seeds from `ext_default`,
`ext_get` falls back to it, and `lfo4_on_load` drops the entry for a sound
carrying nothing *so that* it reads the defaults. **The array all three rely on
was never filled.** It held the zeros BSS gives.

`lfo4_init` fills it from **LFO3's own records** rather than from numbers typed
into a file: LFO4's ten are copies of LFO3's, so it cannot disagree with them.

#### Fixed, but not proved to be the cause: the live container

> "LFO4 doesn't modulate anything ... no matter the DEP or destination"

The extension table is keyed by the live sound's address, and the two ends
learned it differently: the setter from the firmware's own virtual call, the
bridge by computing `LFO4_KIT + 52 + track * 1163` from a constant measured
once out of `ui1200M`. The firmware's own routine reads the base from a global:

```
0x40025bda  movel %sp@(4),%d0 ; movel #1163,%d1 ; mulsl %d1,%d0
            addil #52,%d0
            addl 0x800052a0,%d0        <- the base
```

`bridge.c` does the same now and `LFO4_KIT` is gone from the build entirely.
`scripts/emu_lfo4_container.py` moves that global and checks `lfo4_sound_of`
follows it.

**It is not proved to be the silence.** In the snapshot *and* in a from-reset
boot the pointer equals the constant -- `scripts/emu_lfo4_sound.py` hooked 2,192
real sound loads and all sixteen of the bridge's addresses were among them. The
constant is wrong in principle and happened to be right here.

**The harness that should have caught it said so in its own docstring.**
`emu_lfo4_bridge.py`: *"the sound address comes from the build's own
`lfo4_sound_of`, so the harness and the firmware agree on the track -> sound map
by construction"*. Agreeing by construction is agreeing about nothing.
`scripts/emu_lfo4_chain.py` is that test with the address taken from the
firmware's routine instead, so the two derivations can disagree; seven checks
pass, including that they do not.

`lfo4-forcerow` settles the rest in one flash: `lfo4_refresh` discards the
lookup's answer and hands every track `tick7`'s row, the one combination
already proved audible on the instrument. Sweeps -> the lookup is at fault.
Silent -> the engine path broke when the bridge replaced `tick7`'s fixed table
with a call, which has **never** produced an audible sweep on the instrument:
the bridge's own hardware test ran with an empty table, and passing meant
silence.

#### Located, not fixed: the UI written three times over

> "random wave have phase instead of slew in LFO4"

`0x4010da30` decides the substitution. It reads the page index from the mode
object's `+144`, clamps it to **0..2** in two places, and indexes a three-entry
table at `0x40205454` holding exactly **`{80, 90, 100}`** -- the three `SLEW`
entry numbers. Page 4 never enters that routine at all, so it gives up earlier
than the clamp, at a gate not yet found.

> "browsing destinations doesn't open the destination UI ... 49 reads err, 65
> is also err ... 100 to 127 are also errors" and "the destinations are not in
> order ... it starts with MOD1"

The `err` ids and the ordering are **symptoms of the browser not opening**: with
no browser the value is dialled raw, straight past the slots that have no
parameter and past the mirror's 101. Hooking what looked like the browser's
machinery -- the list builder, the shared entry, the three mask thunks -- fired
zero times on *both* pages, so it opens by a route not yet found. The model was
wrong, not the measurement.

**The pattern, and it is the headline for what remains.** The waveform preview
was three code blocks with literal entry numbers. The `SLEW` substitution is a
three-entry table with the index clamped to 2. The `DEST` browser's mask is
three thunks in three descriptors. **The firmware's LFO UI is written three
times over**, and a fourth page is not one change but a long tail of per-LFO
hard-coding -- each found the same way, by diffing what two renders execute,
and each extended the same way.

### Both gates found, and they are the same gate — 2026-09-22

The section above is superseded in one respect and confirmed in another, and
both halves turned out to be **one shape written six times**: a parameter's
entry number compared against three literals, ten apart, with everything else
behind the `bne`.

`scripts/scan_lfo_triples.py` is that shape made searchable. It walks every
small immediate in `MAIN OS`, classified by the opcode carrying it, and reports
each window holding `v`, `v+10` and `v+20` -- because an LFO's ten records sit
ten apart, so its three copies do too. 55,272 immediates, seven windows for
`78/88/98`, and six of them are code.

#### `RND` shows `SPH`: the gate is at `0x4010db18`

`0x4010db00` is the substitution. Its **first** act, before the page index,
before the clamp, before the three-entry table:

```
4010db18  moveq #81,%d0  ; cmpl %d2,%d0 ; beq  0x4010db2e
4010db1e  moveq #91,%d1  ; cmpl %d2,%d1 ; beq  0x4010db2e
4010db24  moveb #101,%d0 ; cmpl %d2,%d0 ; bne  0x4010dbda   <- return the entry unchanged
```

81, 91 and 101 are the `SPH` entries of LFO1, LFO2 and LFO3. LFO4's is **327**.

`scripts/emu_lfo4_slew.py` measures it, and measures the half a page walk
cannot reach -- the substitution only happens once the waveform *is* `RND`, so
it selects `RND` with the encoder and then looks:

| page | index | gate asked | accepted | table gave |
|---|---|---|---|---|
| LFO1 | 0 | 117 | 13 | -- |
| LFO2 | 1 | 27 | 3 | -- |
| LFO3 | 2 | 18 | 2 | -- |
| LFO4 | 3 | 18 | **0** | -- |
| LFO3, `WAVE = RND` | 2 | 124 | 11 | **100** |
| LFO4, `WAVE = RND` | 3 | 124 | **0** | -- |

The last two rows are the finding: **the identical workload**, 124 asks on each
page, and one literal comparison decides whether `SLEW` appears. The page index
is 0, 1, 2, 3 exactly as the fourth page was built to report, and with `RND`
selected LFO3 reaches the table and reads entry 100 out of it.

`clamp->1` and `clamp->2` never fired on any page, including LFO3's at index 2:
`cmpl` against 2 passes it through. So index 3 **would** clamp, and the fix is
three things, not one -- the gate at `0x4010db18` must accept 327, the `lea
0x40205454` must point at a four-entry table (the stock three are followed
immediately by a mangled RTTI string, so it cannot grow in place), and the
`moveq #2` pair at `0x4010dbc6`/`0x4010dbcc` must become `#3`.

The other clamp, at `0x4010db74`, maps any index above 0 to **1** and would
hand LFO3's page LFO2's `SLEW`. It never ran in any measurement here, on any
page. It is left alone: changing code no probe has entered is how the filing
loop at `0x400dc7f0` nearly went to the instrument.

#### The `DEST` browser: not one route, six literals

> "browsing destinations doesn't open the destination UI ... 49 reads err"

**The model in the section above was wrong and the measurement was right.** The
list builder, the shared entry and the three mask thunks fired zero times on
*both* pages because the browser never gets that far. Six sites gate on the
`DEST` entries **78, 88, 98** first:

| site | shape |
|---|---|
| `0x400397da` | `%d2`, then the mask cascade at `0x400397f2` |
| `0x40039a9a` | `%d0`, reads `+44` from the table itself, cascade at `0x40039ad4` |
| `0x40039cbc` | cascade at `0x40039cf6` |
| `0x40039ebc` | cascade at `0x40039ef4` |
| `0x400643c0` | `%d2`, the three compares spread across the function |
| `0x40066d5c` | `%d3`, compact |

`0x400397da`'s body is the destination **randomiser**: it picks the mask, calls
`0x4003951e` to build the list, takes `0x40150670` modulo the list length and
looks the winner up. The same list builder the browser uses, reached from a
different door.

**The capability side needs no data change**, and this is the one place the
earlier reading holds up unaltered: `lfo4records.DEST_FLAGS = 0x8000` is bit
15, the cascade tests bits 18, 17 and 16, and the fourth mask the staircase
names is `0x0200` -- already recorded above, still right. What was missing was
never the flags. It was that nothing ever asks LFO4 for them.

**Watch the displacement.** Re-deriving the `+44` reading from
`movel %a2@(24,%d0:l),%d1` reproduced the old `+32` error inside an hour:
objdump prints *indexed* displacements in hex with no prefix, so that `24` is
36, and `8 + 36` is 44. The correction is recorded above and it is worth
re-reading before trusting any indexed offset in this file.

#### Both fixes, measured on the built image — 2026-09-22

The same two probes, pointed at `out/lfo4-ui` (`DT2_BUILD=out/lfo4-ui`). The
question each answers is not "does LFO4 work now" but "does LFO4 do what LFO3
does, and does LFO3 still do it".

**`SLEW`**, with the waveform selected as `RND` on each page:

| page | gate asked | accepted | table gave |
|---|---|---|---|
| LFO3 | 124 | 11 | 100 |
| LFO4, before | 124 | **0** | -- |
| LFO4, after | 127 | **11** | **326** |

`clamp->2` fired zero times, so index 3 passed the ceiling and the four-entry
table answered with LFO4's own `SLEW` entry rather than LFO3's. LFO1, LFO2 and
LFO3 accepted 13, 3 and 2 exactly as before.

**`DEST`**, opening the browser on each page:

| page | mask | destinations offered |
|---|---|---|
| LFO1 | `0x1e00` | 55 |
| LFO2 | `0x0e00` | 62 |
| LFO3 | `0x0600` | 69 |
| **LFO4** | **`0x0200`** | **76** |

**55, 62, 69, 76.** The list grows by exactly seven per LFO, which is the rule
recorded in this file the day before the fourth page could be asked -- each
group of ten contributes seven because the loop is over value slots and the two
alternates collapse onto their primaries. LFO4 is offered LFO1's, LFO2's and
LFO3's blocks and not its own, so the graph stays acyclic without anything
having to enforce it.

The counts for LFO1, LFO2 and LFO3 are the measurement that matters most here:
the cascade is shared by all four pages, so a wrong fourth branch would have
changed what the other three are offered, and a probe that only counted gate
hits would not have seen it. So the same probe was run against `lfo4-value`,
the build the fault was measured on, and the two put side by side:

| build | LFO1 | LFO2 | LFO3 | LFO4 |
|---|---|---|---|---|
| `lfo4-value` | 55 | 62 | 69 | **no mask chosen, no list built** |
| `lfo4-ui` | 55 | 62 | 69 | **76** |

A before and an after, rather than an after and an assumption.

### The browser's gate, and what hardware settled that the emulator could not — 2026-09-22 late

`lfo4-browser` is on the instrument and the owner reports the page working: the
destination window opens, `RND` shows `SLEW`, and the fourth page dot is there
from boot. Three things follow, and one of them is a correction.

**The browser was never the list machinery.** It is one test, asked three
times, at `0x40067506`, `0x400676e4` and `0x400679e6`:

```
andil #0x70000,%d0     ; bits 18, 17, 16 -- is this parameter a DEST?
beqw  <skip>           ; no: never open the window
```

`lfo4records.DEST_FLAGS` is bit 15 -- the value the staircase `0x40000 /
0x20000 / 0x10000` continues to -- so the AND yields zero. Widening the test to
`0x78000` admits LFO4 and provably nothing else: no record in the stock table
carries `0x8000` in `+44`, which `build_lfo4_browser.py` asserts against the
image before it patches.

In the emulator the change takes LFO4 from **776 firmware blocks it never
reached down to 45**, and the destination counts stay 55 / 62 / 69 / 76.

**Walking forward beat walking back.** Following the browser *up* its call
chain gave `0x401a074a`, then `0x40067370`, then a function `dnfw fn entry`
would only guess at -- four disassemblies, each answering a question nobody
asked. Listing the first place the two traces *part* gave the decision in one
look. Third time on this feature that diffing two renders beat reading harder.

**One gate was already fixed without being noticed.** Directly above the mask:

```
cmpil #320,%d3
bhiw  <skip>
```

LFO4's `DEST` entry is 324. The table relocation had already raised that bound
to 330, so it had been passing all along -- but it sits four instructions above
the real gate, and had it not been raised it would have been the obvious
culprit and the wrong one.

#### `pagelist.c` is confirmed by the instrument, not by us

`scripts/emu_lfo4_pagelist.py` reported the page-vector constructor never
running in **1.2 billion instructions** from reset, and this file recorded the
patch as unverified and possibly inert on that basis. The instrument says
otherwise: the fourth dot is there before `[MOD]` is pressed.

So the site does run -- later in a boot than this emulator reaches, which is
itself worth knowing, because the boot gate's 450 M budget draws a frame and
is nowhere near a finished UI. **The probe's finding stands and its
implication was wrong**: "not reached in 1.2 G" meant the harness stops early,
not that the code is dead.

## The table is full, and that is the whole bug — 2026-09-22 night

**`lfo4-keeprow` made it worse, and that is the finding.** With the drops in
`ext_copy`, `ext_carry` and `ext_clear` switched off, the instrument reports
modulation became *sparser*: two successes, "with a lot of wiggling", against
roughly one trig in fifteen before.

The mechanism is four lines of `ext_add`:

```c
if (ext_live == EXT_SLOTS) {       /* EXT_SLOTS is 256 */
    ext_full++;
    return 0;                      /* and ext_set then does nothing at all */
}
```

**A full table drops the panel's write on the floor.** No error, no fallback,
no display change -- the knob turn simply does not land, so the sound has no
entry, so `lfo4_refresh` fills the row from `ext_default`, whose `DEP` is
neutral, so the note is silent.

### It explains every observation, including the one read backwards

| observation | under this reading |
|---|---|
| binary per note | the entry exists or it does not |
| perfect when it works | the value that did land is correct |
| **sparser with the drops off** | the drops were the only thing *reclaiming* slots |
| faster trigging works better | more trigs -> more sound copies -> more drops -> more free slots for the next write |

That last row was read backwards all evening: "more trigs helps" was taken as
trigs **delivering** the row. They are making **room** for it.

`ext_full` has been counting this since step 1 and nothing has ever read it.
The emulator never saw it because a snapshot session creates a handful of
sounds, not the churn of a real instrument playing patterns.

### What the fix is not

It is not "stop dropping". `lfo4-keeprow` is what that looks like, and it is
worse. Nor is it simply a bigger table: 256 slots keyed by a live sound's
address is a guess about churn, and the next guess would be another one.

What the design has to face is that **a side table keyed by address cannot be
told when an address stops mattering**. Elektron's own parameters do not have
this problem because they live inside the sound's 1,163 bytes and are freed
with it. Options, cheapest first, and none yet measured:

1. **Read `ext_full` on hardware** before anything else. If it is non-zero the
   diagnosis is confirmed outright; there is no instrument for this yet.
2. Evict the least recently used entry instead of failing the insert, so a
   write always lands and only the oldest sound loses its LFO4.
3. Key by something bounded -- track and buffer index rather than address --
   which bounds the table by construction.
4. Find eight bytes inside the sound after all, which removes the table.

## Two more from the instrument, 2026-09-22 night

**LFO4's configuration does not survive a power cycle**, while every other
page's does. That is a separate, genuine gap: values reach a stored sound
through `lfo4_on_save`, but whatever the instrument does at power-off does not
route through that hook. It is a missing feature rather than a symptom of the
lookup bug, and it needs its own reading of the power-off path.

**The `RND` label has a third site.** With `RND` selected, the legend at the
top of the page shows `SLEW` correctly, but the column label under the waveform
reverts to `SPH` when the knob is not being touched. `lfo4-ui2` patched the two
routines that decide whether the waveform *is* `RND`
(`0x4003662c`, `0x40036a76`); this is a third path, for the idle rather than
the active state. Same family as everything else in this file: the UI is
written three times over, and each copy has to be found by diffing what two
renders execute.

### [WRONG — corrected 2026-09-22 night] The table-full reading above

**`lfo4-keepall` refutes it.** The section above predicted, in writing and in
advance, that a build with *every* removal path off would be worse still,
because nothing would reclaim a slot. The instrument reports the opposite: it
"modulates similar to other fw where modulation triggering was erratic" --
back to the baseline, not worse.

If exhaustion were the cause, the build that never frees a slot would be the
worst of the three. It is not. **The reading is wrong and stays here because
the reasoning was sound and the prediction was testable**, which is the only
reason it was cheap to kill.

What the three builds actually say:

| build | removal paths | on the instrument |
|---|---|---|
| `lfo4-browser` | all on | erratic, about one trig in fifteen |
| `lfo4-keeprow` | copy, carry, clear off; **load still drops** | **worse** -- two successes with a lot of wiggling |
| `lfo4-keepall` | all four off | back to the erratic baseline |

**Nothing removing a row does not fix it.** So the row is not being destroyed
between the panel writing it and the engine asking for it: it never arrives
under the key the engine asks for at note-on. That is the second of the two
outcomes `build_lfo4_keepall.py` named, and it closes the whole removal branch
that this session spent the evening on.

`lfo4-keeprow` being worse than both ends is unexplained and is a side road: it
is the only build where copies stop reclaiming *while* loads still remove the
user's fresh entry. Recorded, not chased.

#### What that leaves, and the experiment that decides it

The panel writes under the sound address the firmware's own setter hands it.
The engine reads under `*(0x800052a0) + 52 + track * 1163`. In the emulator
those are the same number -- measured, twice -- but the emulator plays no notes
and allocates no voices, and the instrument does both.

**The cheapest test is to stop keying by address at all.** A build where
`lfo4_on_set` files by *track index* and `lfo4_refresh` reads by the same index
removes the address from the question entirely:

- **modulation becomes reliable** -> the address is the fault, and the fix is
  to agree on one identity for a sound rather than two derivations of it;
- **still erratic** -> the fault is upstream of the key, in whether the write
  happens at all.

A per-track array is sixteen rows of eight `u16` -- 256 bytes, no hashing, no
eviction, and no way for it to be full. It is not the shipping design, because
p-locks and sound-per-track would need the address back. It is a probe that
answers the only question left.

### [CORRECTED again — 2026-09-22 night] `lfo4-keepall` works, and the load drop is the bug

The section immediately above misread the owner's report. "keep all is better,
it modulates similar to other fw where modulation triggering was erratic" was
taken as *still* erratic; it means it now behaves like the other firmwares,
where previously triggering had been erratic. Confirmed a message later: **"it
modulates as expected."**

So the removal branch does not close -- it is the answer. The three builds,
read correctly:

| build | removal paths | on the instrument |
|---|---|---|
| `lfo4-browser` | all on | erratic, about one trig in fifteen |
| `lfo4-keeprow` | copy, carry, clear off; **load still drops** | worse |
| `lfo4-keepall` | all four off | **works as expected** |

`keeprow` and `keepall` differ in exactly one thing, so that one thing is the
bug:

```c
void lfo4_on_load(void *live, const void *stored) {
    ...
    if (!any) {
        ext_drop((u32)live);   /* <- this */
```

`lfo4_on_load` drops the live entry whenever the stored sound it is loading
carries no LFO4 values -- which is **every stock sound**, and every sound saved
before this build existed. A load therefore wipes an edit the panel has just
made, and a boot runs that path 2,192 times.

It also explains the owner's other report of the same evening: **LFO4's
settings do not survive a power cycle.** They are removed on the way back in,
not lost on the way out.

`keeprow` being worse than either end now has a reading too: it is the only
build where copies and carries have stopped reclaiming *while* loads still
remove the user's fresh entry -- the worst of both, which is what was heard.

#### Why `keepall` is still not the fix

Nothing removes a row in it, so a sound that genuinely has no LFO4 keeps
whatever the last sound at that address had. Settings bleed between sounds and
patterns; the owner was told to expect it.

The real fix has to tell two cases apart that `!any` currently conflates:

1. **a stored sound with no LFO4 values, being loaded over a live sound the
   user has just edited** -- the edit must survive, because that is what every
   other parameter on the instrument does;
2. **a stored sound with no LFO4 values, loaded over a live sound carrying a
   previous sound's LFO4** -- the entry must go, or values bleed.

The live sound's own identity is what separates them, and `docs/lfo4-build-
plan.md` §8 already has the material: the stored block has the reserved rank
`4 * slot + 0` free. A sound saved by this build always writes those eight ids,
so "stored has no LFO4" and "stored was never saved by us" are distinguishable
if the save marks itself. That is the next piece of work, and it is small.

### [SETTLED by the owner — 2026-09-22 night] The removal branch is closed

The entry above is **wrong** and the one before it was right. Stated by the
owner directly, against a table this file had already published:

> "this is wrong. The modulation exerted is correct when it happens but it
> happens erratically"

So, finally and from the instrument rather than from inference:

| build | removal paths | on the instrument |
|---|---|---|
| `lfo4-browser` | all on | erratic; correct when it happens |
| `lfo4-keeprow` | copy, carry, clear off; load still drops | **worse** |
| `lfo4-keepall` | all four off | erratic; correct when it happens |

**Turning off every route by which a row can be removed does not fix it.**
`keepall` is no better than `browser`. The row is therefore not being destroyed
between the panel writing it and the engine asking for it -- it never arrives
under the key the engine asks for at note-on. That is the second outcome
`build_lfo4_keepall.py` named in advance, and it closes the removal branch this
session spent its evening inside.

Two things survive from the wrong entries, because they were measured rather
than reasoned:

- **`lfo4-keeprow` is worse than either end.** It is the only build where
  copies and carries stop reclaiming while loads still remove a fresh entry.
  Unexplained, recorded, not chased.
- **`lfo4_on_load` does drop a live entry whenever the stored sound carries no
  LFO4 values**, which is every stock sound. That is true, and it is very
  likely why LFO4's settings do not survive a power cycle -- a separate report
  the same evening. It is simply not the cause of the erratic triggering,
  because switching it off changed nothing.

#### Three wrong readings in one hour, and what they have in common

Exhaustion, then closure, then the load drop, then closure again. Every one
came from **inferring a conclusion out of a short report instead of restating
the report and checking it**. The owner corrected all three, twice by quoting
this file's own table back at it.

The working rule that follows: when the instrument says something, write the
sentence down verbatim first, restate what it implies in one line, and get that
confirmed **before** any of it reaches a document. A test result is evidence;
what it means is a claim, and the two were run together here three times.

#### The experiment that is actually next

Unchanged from the first correction: **stop keying by address.** A build where
`lfo4_on_set` files by track index and `lfo4_refresh` reads by the same index
takes the address out of the question.

- reliable -> the address is the fault: the panel and the engine are naming the
  same sound two different ways, and only the instrument's voice allocation can
  tell them apart, which is why every emulator measurement agreed;
- still erratic -> the fault is upstream of the key, in whether the panel's
  write happens at all.

Sixteen rows of eight `u16`: 256 bytes, no hashing, nothing that can be full,
nothing to reclaim. Not a shipping design -- p-locks and sound-per-track need
the address back -- but it answers the only question left standing.

### Measure before bisecting again — `lfo4-meter`, 2026-09-22

The track-index build above is still the right *fix-shaped* experiment, and it
is not the right *next* one. Two things changed the order.

#### tick7 already excludes the engine path, and it cost no flash

`lfo4-tick7` passed on hardware on 2026-09-20 (§"tick7 passed on hardware"):
the fourth LFO ran, **reliably**, each track reading its own row. It drove the
identical two evaluator indices this build drives — `%a5` in evaluator A,
`%d0` in evaluator B — through the identical stubs. The single difference
between it and every build since is that tick7's sixteen rows were a **static
table compiled into the image** and every build after it replaced them with
`lfo4_refresh(track)`, which is a **lookup**.

So the branch "the stubs stopped turning a row into sound" is closed by a
result that was already written down, and with it the reading that the index
handed to the stubs might be a *voice* number rather than a track number —
1-in-16 voices would produce almost exactly the observed one-trig-in-fifteen,
which is why it was worth checking, and tick7 refutes it outright. Kept here
because a closed path is still a signal: if a later result ever contradicts
tick7's, this is the first thing to re-open.

What remains is the join: the key `lfo4_on_set` writes under, and the key
`lfo4_refresh` asks under.

#### Why a meter and not a fourth bisect

`browser`, `keeprow` and `keepall` each answered one bit and cost one flash
apiece. The numbers that would answer the whole question exist only on the
instrument — the emulator runs neither the sequencer nor a pattern load, so it
cannot be asked what key the panel wrote under while a pattern played — and
there is no way to read a counter in BSS from the front panel.

But LFO4's page is ours end to end: `csrc/lfo4/getter.c` decides what each of
its eight columns displays. `scripts/build_lfo4_meter.py` builds `lfo4-browser`
with three of them displaying the measurement instead of the value.

| column | full right | full left | centre |
|---|---|---|---|
| `SPD` | the tick's last lookup **found** a row | it found nothing, and took the defaults | it has never looked |
| `FADE` | the sound the knob wrote under **is** one of the sixteen the tick asks about | it is **not** — and that alone is the whole fault | — |
| `DEP` | not a needle: the depth **the engine is holding right now**, out of `lfo4_rows` | | |

Every reading is a needle at a stop or at centre and never a number to be
interpreted, because nothing in `csrc/lfo4/meter.c` knows how a widget formats
8.8 fixed point into the figure on the glass — and because §3 of the playbook
applies to a measurement as much as to a demonstration. `MULT`, `DEST`,
`WAVE`, `SPH` and `MODE` are untouched, so a destination can still be chosen
and the LFO still runs while the three are read.

**Only the display is diverted.** The knob still writes the table through
`lfo4_on_set` and the save path still reads it through `ext_get`, so a metered
build stores exactly what `lfo4-browser` stores. It is an instrument, not a
candidate fix, and it is not meant to sound like anything.

#### What each outcome sends next

- `FADE` **left** — found it. The panel edits a sound the engine never asks
  about, and the track-index build above becomes the fix rather than a probe.
- `FADE` right, `SPD` flicking left while trigging — the keys agree and the
  table loses the row at tick time; the search moves inside `ext_find` and to
  what runs between the panel's write and the tick's read.
- `FADE` right, `SPD` right, `DEP` holding the dialled value, and still no
  modulation — then this result and tick7's disagree, and the engine path is
  back on the table after all.
- `DEP` **falling back to 0 on its own** — the bug happening, live, and
  whatever the instrument was doing at that moment is what causes it.

### The third `RND` site is not a literal triple — a null, 2026-09-22

From the instrument, in the owner's words: *"in all fw, random shp behaves and
at the top the legend with the value displays slew, but when not touching the
knob the UI shows SPH under the waveform."*

So two renderers disagree. The one that draws the big value at the top has the
substitution — it names entry **326**, whose record is LFO3's `SLEW` copied —
and the one that draws the column name under the waveform does not: it names
entry **327**, `SPH`. Two sites were already found and patched this way
(`DN2_RND_A_GATE`, `DN2_RND_B_GATE`); this is a third.

`scan_lfo_triples.py` was run over stock 1.11 for all three literal families
the first two were found by, and **every window it reports is one already
patched**:

| family | windows | where |
|---|---|---|
| 79 / 89 / 99 — the `WAVE` entries | 2 | `0x40036636`, `0x40036a80` — both patched |
| 81 / 91 / 101 — the `SPH` entries | 1 | `0x4010db18` — the SLEW gate, patched |
| 80 / 90 / 100 — the `SLEW` entries | 1 | `0x4029a5c2`, and it is **data**: a table of 0, 10, 20 … 120 disassembling as `moveq` |

**So the third site does not name its LFO with a literal at all.** It reaches
the column's name some other way — through the parameter record it already
holds, or through a per-page index — which is why three passes of a scanner
built for literals cannot see it and a fourth would not either.

That makes the next step a **differential trace**, not another scan: draw
LFO3's page and LFO4's page with `WAVE` set to `RND` and idle, record the basic
blocks each enters, and walk *forward* from the first parting. It is the method
that found the destination-browser gate after reading the image backwards from
the browser had cost four disassemblies and reached a function that could only
be guessed at. Queued behind the `lfo4-meter` gate — one machine.

### `lfo4-meter2` on the instrument: the row is right — 2026-09-22

The owner flashed `lfo4-meter2` and read the three columns on **track 5**,
nothing else playing:

| column | reading | means |
|---|---|---|
| `FADE` | 63 — and **LFO3's `FADE` at its stop also reads 63**, so 63 is confirmed as the needle's full travel | the sound the knob wrote under is one of the sixteen the tick asks about: **the keys agree** |
| `DEP` | taken to **127.98** and it holds, no snap-back | the engine's row for that track carries `0x7ffe`, full depth |
| `SPD` | **−64** with `DEST` at `None`; **−38** at `Ratio C`; **−32** at `Mix`; **−40** at `Mod3 Depth` | the row's `DEST`, and every one of the four is exact |

**The scale was confirmed against the record table rather than assumed**, which
is what makes this a measurement: `SPD` displays `slot − 64`, and

| shown | implied slot | record at that slot |
|---|---|---|
| −64 | 0 | no destination |
| −38 | 26 | `SYN Ratio C` (index 200) |
| −32 | 32 | `SYN Mix` (index 206) |
| −40 | 24 | `LFO3 Depth` (index 102) |

Four readings, four exact matches, including one — `Mod3 Depth` → LFO3's own
`Depth` — that nothing in the build could have produced by accident.

**So the row the engine holds is complete and correct**: the right key, the
exact destination slot chosen on the panel, and full depth. The remaining
inputs are the ones nobody set, and they were measured too: `lfo4_init` seeds
`ext_default` from LFO3's own records through `POSITION = {0,1,2,3,4,6,7,8}`,
giving `SPD` 0x7000 (112), `MULT` 0x0300, `FADE` 0x4000 (no fade), `WAVE` 0
(triangle), `MODE` 0. That is a working LFO, not a stalled one.

#### What has not been controlled, and it should have been first

**No control was run beside the negative.** All three destinations tried are
ones whose silence is explicable without any fault in LFO4:

- `Ratio C` is machine-dependent — slot 26 is `Ratio C` only in group 0, and
  the same slot is `Osc1 Waveform`, `Sweep Time` and `Swarm Detune` in groups
  1, 2 and 3 (§4b's colliding slot spaces, seen from the other end);
- `Mod3 Depth` is LFO3's own depth, which does nothing audible unless LFO3 is
  itself set up and aimed somewhere;
- and the evaluator **clamps the cell to `0..0x7f00`**, so a destination
  already sitting at an end of its range absorbs a modulation pushing it
  further that way. `Filter Frequency`'s record default is `0x7f00` — fully
  open — which is exactly that trap.

So the next step is not another build. It is `Filter Frequency` (**slot 67**,
so `SPD` must read **+3.00**), the destination parameter set mid-range, and
**LFO3 configured identically on the same track as the control**. Two outcomes
and they are clean:

- LFO3 sweeps and LFO4 does not — the engine has a correct row and does nothing
  with it, which contradicts `tick7` and puts the evaluator stubs back on the
  table;
- neither sweeps — the destination was inert and every negative result today
  was measuring silence that had nothing to do with LFO4.

### The emulator sweeps where the instrument does not — 2026-09-23

`scripts/emu_lfo4_sweep.py`, pointed at **the instrument's own configuration**
— track 5, slot 67 `Filter Frequency`, `DEP` at maximum — driving evaluator A
directly for 120 frames:

```
  the live sound for track 5 is 0x4210d2ec; watching slot 67 every frame
  no state backup:            119 change(s), turns round, 1 of 120 frame(s) at its maximum 0x5ffe
  asking for a state backup:  119 change(s), turns round, 1 of 120 frame(s) at its maximum 0x5ffe
  span 0x4051..0x5ffe, 120 distinct values over 120 frames
```

**A clean oscillation, and four readings fall out of it:**

| | |
|---|---|
| it moves every frame and **turns round** | not a ramp into the clamp; the phase advances on its own, unprompted |
| **1** frame of 120 at the maximum | not saturation — the earlier worry about `DEP` at full depth does not apply on this destination |
| the two trajectories are **byte-identical** | the state backup and restore are not involved. That hypothesis is closed, and it was the one `emu_lfo4_sweep.py` was written to test |
| track **5**, slot **67** | not the track, and not the destination |

**So every part of the chain works when the evaluator is driven directly**, on
exactly the configuration that is silent on the instrument.

#### What the emulator has never run, and it is the whole remaining space

This harness calls evaluator A 120 times in a row itself. It does not run the
sequencer, it does not allocate a voice, and **it never performs a note-on**.
Neither has any other probe: `emu_lfo4_trig.py` pressed a trig key and produced
no sound copy at all, which said the harness never reached the path rather than
that the path was innocent.

And the instrument's report has been about note-on from the first sentence:
binary per note, decided at note-on, sustained while the trig is held, more
frequent the faster the trig is re-pressed. Every hypothesis that did not
involve note-on has now been closed — removal (to be re-asked with a control),
the key, the row's contents, the destination, the track, the clamp, the fade,
the per-LFO flags, the state backup, the per-track strides.

**The next instrument is the note-on routine, called directly**, the way
`docs/instruments.md` says to reach what the sequencer will not run for us.
Finding it is the work: what runs when a trig fires that could decide whether
the fourth LFO's contribution survives, when the first three always do.

#### The LFO state arrays are touched from nowhere else — 2026-09-23

Before looking for a note-on routine that resets LFO phase, it was worth asking
whether one can exist. Every 32-bit reference in the stock image to the three
state array bases, and every value landing *inside* one of their 1,920-byte
spans, was listed and checked against the built image:

| reference | at | in the build |
|---|---|---|
| `STOCK_LIVE` | `0x40137342`, `0x40137742`, `0x40137760`, `0x401377f4` | patched |
| `STOCK_LIVE+37` | `0x401372fe` | patched |
| `STOCK_SECOND` | `0x40137396`, `0x40137428` | patched |
| `STOCK_SECOND+37/+38/+80` | `0x40137352`, `0x401373ba`, `0x40137420` | patched |
| `STOCK_BACKUP` | `0x40137748`, `0x4013780e` | patched |

Three further hits read "still stock" and none is real: `0x401373c0` is the
flag sweep's end bound, which is **dead code** behind the `jmp` that replaces
the routine at `0x401373b8`; and `0x40236fbe`, `0x4024c07e`, `0x4026b36e` are
2-byte-aligned windows in data that happen to fall inside a 1,920-wide range.

**So every reference is inside `0x40137342..0x4013780e` — the two evaluators
and their initialisers, and nothing else in three megabytes.** The firmware has
no other code that can reach an LFO's phase. A note-on cannot be resetting LFO
state directly, because there is nowhere for it to do so from.

That leaves one route by which anything outside the evaluators can affect an
LFO: **the per-record enable byte at `+38`**, the one the flag sweep sets.

#### Who calls the flag sweep

`0x401373b8` has **one** direct caller: `0x4012b6f4`, inside the function at
`0x4012a89a` — and the boot log names `0x4012a9a8` as the entry of a
**priority-8 task** created at `0x4012b892`. The call sits behind a dispatch:

```
4012b6ec  moveq #5,%d1
4012b6ee  cmpl  %d0,%d1
4012b6f0  bnew  0x4012b50c
4012b6f4  jsr   0x401373b8        ; the flag sweep
4012b6fa  clrl  %d2
```

So the sweep runs when that task receives **command 5**, and it is the only way
the enable byte is ever set. The next questions, in order, and all of them
static:

1. what is command 5, and what sends it;
2. where the evaluator **reads** `+38`, and whether it clears it — an enable
   that is consumed once would be per-note by construction;
3. whether our `flags` stub sets the fourth record's byte at the moment stock
   sets the first three, or a frame later.

`csrc/lfo4/`'s stub writes `+0/+40/+80/+120` and strides 160 where stock wrote
`+0/+40/+80` and strode 120, which is arithmetically right. Being right about
*where* is not the same as being right about *when*, and (2) is where that
distinction would show.

### The removal branch, closed properly this time — 2026-09-23

`lfo4-meterkeep` was flashed: `lfo4-meter3` plus `LFO4_KEEP_ROWS` **and**
`LFO4_KEEP_ALL`, so no copy, no clear and no load can drop a row. The owner ran
it with the stage visible and, for the first time on this question, **with a
control**:

> "Still now and then" — and, asked directly whether the control worked,
> **"Yeah LFO 3 swept normally."**

**So removal is not the cause.** That is what was written down on 2026-09-22
after `browser`, `keeprow` and `keepall`, and it was written down on evidence
that could not carry it — three negatives taken with no control, an inert
destination possible, the clamp uncontrolled and fade uncontrolled. The
conclusion survives; the reasoning behind it is now sound, which is a different
thing and the only reason to have spent the flash.

**Every earlier reading stays in this file, marked.** A closed path is still a
signal, and the shape of closing one badly is worth more than a tidy page.

#### What is measured, and why it does not add up to silence

| | measured how |
|---|---|
| the row the engine holds is **correct and continuously present** | `lfo4-meter2`/`meter3` on the glass: `SPD` = the row's `DEST` (four exact matches against the record table), `DEP` = the row's depth |
| **nothing removes it** | `lfo4-meterkeep`, all four drop paths off, with LFO3 as the control |
| the evaluator turns that row into a clean oscillation | `emu_lfo4_sweep.py` on track 5 into slot 67: 119 changes over 120 frames, turns round, 1 frame of 120 at the ceiling |
| the panel's key and the engine's key agree | the `FADE` needle, before it was handed back |
| LFO1-3 do the identical thing through the identical code | LFO3 sweeps, every time, on the same track and destination |

And still: **binary per note, decided at note-on, sustained while the trig is
held, more frequent the faster it is re-pressed.**

#### The one path no probe has ever run

Every harness in `scripts/` drives **evaluator A directly**. None allocates a
voice; none performs a note-on. `emu_lfo4_trig.py` pressed a trig key and
produced no sound copy at all — a null that said the harness never reached the
path, not that the path was innocent.

Closed by measurement, in the order they fell: the key; the row's contents; the
destination; the track index; the mirror clamp; fade; the per-LFO enable flag
sweep; the state backup and restore strides; the per-track pointer advances;
and now removal. **What is left is note-on, and it is where the instrument's
report has pointed from the first sentence.**

Next: find the note-on routine and call it directly, the way
`docs/instruments.md` says to reach what the sequencer will not run for us, and
watch `mirror[track][67]` across a note-on rather than across frames. The
question to answer is whether a voice samples the mirror at a moment when
LFO4's contribution is present — and if so, why LFO1-3's always is.

### Page copy/paste does not carry LFO4 — an unbuilt feature, 2026-09-23

From the instrument:

> "I could not use the device Copy/Paste function to paste LFO4 to LFO3 and
> save some setup time" — "it just did nothing at pasting (it would say that it
> was copying LFO4 though)"

**The copy is recognised and the paste is empty**, which is the signature of a
path that reaches LFO4's *page* but not LFO4's *values*.

#### Why, and it is not a bug in anything that was built

LFO4's eight values are **not in the sound.** §8's whole design is that a live
sound has no free slots and cannot grow, so they live in `ext_val`, a side
table keyed by the live sound's address. Everything that has to carry them has
had to be taught, one path at a time and each one named in this file:

| path | taught by |
|---|---|
| a knob turn | `csrc/lfo4/setter.c` |
| a page read | `csrc/lfo4/getter.c` |
| save and load | `csrc/lfo4/store.c` |
| whole-sound copy, clear, and block moves | `csrc/lfo4/carry.c` |
| the tick | `csrc/lfo4/bridge.c` |

**A parameter-page copy is none of those.** It copies one page's slots within
or between sounds, and the classes are there in the RTTI — `ParamPageCopy`
(`0x40214f62`, typeinfo at `0x401dcdbc`), `PageCopy` (`0x4021584b`,
`0x401de750`), `ModulationCopy` (`0x4021e80c`, `0x401ffc24`). Nothing in
`csrc/lfo4/` hooks any of them, so the copy buffer gets whatever the stock
accessor returns for slots 101..108 — and every stock accessor is bounded at
100. It copies nothing and pastes nothing. The page name comes from the page
record, which is ours and correct, which is exactly why the message says
"LFO4".

#### The owner's hypothesis, and why it is a real confound but not the cause

> "It is maybe because some of the elements are not configured in a standard
> way, like SPD"

**Right to raise, and it matters for any copy test run on a meter build.**
`lfo4-meter`, `meter2`, `meter3` and `meterkeep` all divert `SPD`'s and `DEP`'s
*display* through `lfo4_on_get` — and `lfo4_on_get` is the diverted read at
`0x4003717c`. If a copy path reads values through that same accessor, a copy
taken on a meter build would capture the **needle**, not the setting. So a
copy/paste test on any meter build is contaminated regardless.

It is not the cause, though, because the fault would then be a *wrong* paste,
not an empty one. An empty paste says the values never entered the buffer.

**How to tell them apart if it ever matters:** repeat the test on
`lfo4-browser`, which diverts no display. Prediction, stated before the test:
**still empty**, because the feature does not exist. If it pastes correctly on
`browser`, this entry is wrong and the meter builds broke something.

#### What building it would cost

Symmetrical with `store.c`, and probably the same shape: find where the page
copy gathers a page's values and where the paste writes them, check whether
either carries the familiar six-byte `moveq #100` bound, and divert it the way
the setter and getter already are. Two hooks and two small functions if the
bound is there; more if the page copy walks a slot list instead.

**Not urgent, and worth knowing it is missing**: it costs the owner setup time
on every test, and it is the kind of gap that makes a finished feature feel
unfinished. Added to the punch list beside the two already standing — LFO4's
settings not surviving a power cycle (`lfo4_on_load`'s drop), and the `RND`
column's third site.

### LFO3 and LFO4 are byte-identical in the evaluator — 2026-09-23

`scripts/emu_lfo4_vs_lfo3.py`. Both LFOs configured identically except for the
destination — LFO3 through the mirror at slots 17..24 where the firmware puts
its parameters, LFO4 through `ext_set` where ours live — same track, same
frame, 240 frames:

```
  LFO3 (firmware's own parameters): [16389, 16395, 16400, 16406, 16411, ...]
      240 distinct, 239 change(s) over 240, span 0x4005..0x452f
  LFO4 (ours, through ext_set)     : [16389, 16395, 16400, 16406, 16411, ...]
      240 distinct, 239 change(s) over 240, span 0x4005..0x452f
  ratio 1.00, same character
```

**Not similar — identical.** Same values in the same order, same span, same
count of changes. Given identical parameters and a zeroed phase that is the
correct answer, and it is the first time LFO4's behaviour has been measured
*against something*.

**This existed to correct a flaw in the earlier evidence.** `emu_lfo4_sweep.py`
drove LFO4 alone: its mirror is refilled with the resting `0x4000` every frame,
which leaves LFO1-3 with a `DEST` byte of `0x40` and a depth of exactly centre,
so they contribute nothing and there was nothing for LFO4's trajectory to be
wrong against. A trajectory with no control is the same mistake as a hardware
negative with no control, which this project made three times in one evening on
2026-09-22. It is now made zero times in software.

**So the evaluator is exonerated with a control, not by assertion.** The row is
right, nothing removes it, and the code that turns it into modulation treats it
exactly as it treats LFO3's. Every difference that could be measured frame by
frame has been measured and there is none.

What remains is the thing no harness in `scripts/` has ever run: **note-on.**
The instrument's report has named it from the first sentence — binary per note,
decided at note-on, sustained while the trig is held, more frequent the faster
it is re-pressed — and it is now the only place left for the difference to be.

### LFO4 reaches the mirror, proved by manipulation — 2026-09-23

`lfo4-cell` puts two live mirror cells on LFO4's page: `SPD` shows the cell
LFO4 aims at, `DEP` the cell LFO3 aims at, read straight out of
`0x800068e4 + 34 + 202*track + 2*slot`. From the instrument:

> "DEP and SPD are moving and I can affect how SPD moves (the interval between
> jumps) by changing MULT. Interestingly the higher MULT is I start seeing not
> only jumps but also smooth sweeps in certain cases."

**Both cells move, and LFO4's own `MULT` changes the rate of LFO4's cell.**
That is causation established by manipulation, not a correlation: the only
thing `MULT` touches is LFO4's own oscillator, so whatever is writing that cell
*is* LFO4.

The smooth sweeps at high `MULT` are the expected artefact of sampling a fast
oscillator at the ~30 fps the page redraws — aliasing, which only appears if the
cell is genuinely oscillating fast. It corroborates rather than complicates.

**So the whole control path is now proved end to end on the instrument:** the
panel writes the table, the table is keyed so the tick finds it, the tick fills
the row, the evaluator turns the row into a contribution, and **the
contribution lands in the mirror cell the destination names**. Every one of
those was a candidate at some point in this file and every one is now closed by
measurement, most of them with a control beside them.

#### And the fault survives all of it

The instrument still reports one trig in fifteen, while LFO3 — writing the same
kind of contribution into the same mirror, from the same evaluator, in the same
frame — sweeps every time.

That is a harder statement than anything earlier in this file, because the two
now differ in **nothing that has been measured**. What is left is between the
mirror cell and the sound: whether a voice reads that cell at all for LFO4's
destination, and why it always does for LFO3's.

**The first thing to check is the cheapest and it needs no build.** Both LFOs
have been aimed at *different* destinations so the two columns could be read
apart. That also means the two have never been compared **on the same
destination**, where the only difference left is which LFO produced the
contribution:

- put LFO3 and LFO4 both on `Filter Frequency`;
- turn LFO3's depth to centre so only LFO4 contributes;
- listen, and watch `SPD`.

A moving cell with no sound says the voice does not read what LFO4 wrote. A
moving cell **with** sound says the modulation works and the intermittency is
about something other than delivery — in which case the "one in fifteen" is
about *which* notes hear a cell that is always moving, and the question becomes
what a trig does to the voice's parameter fetch.

#### The contradiction, stated exactly — 2026-09-23

The same-destination test was run with the control asked for and confirmed:

> "so they move. And the LFO4 effect is present as always by chance every ~15
> trig pushes. ... at MULT = 32 both dials move synchronously all the way
> clockwise and then when they reach certain point they sweep back
> counterclockwise to a symmetric position and then they repeat"

and, asked directly whether LFO3's depth was at centre: **"yes"**.

Both columns read the same cell in this test, which is why they moved together —
that part is construction, not a finding. The finding is what was in the cell:

| | |
|---|---|
| LFO3's depth was at **centre**, so it contributed nothing | the control |
| the cell swept a **full triangle**, clockwise and back to a symmetric point, repeating | so **LFO4 alone** was writing it, which the earlier `MULT` manipulation already established |
| **the filter did not move**, except the usual one trig in fifteen | |

**A cell that traces a triangle is a parameter being modulated.** If the voice
read that cell, the cutoff would sweep continuously and audibly. It does not.

**So the memory the page reads and the memory the voice reads are not the same
thing, or not always.** That is the first asymmetry in this entire
investigation that LFO1-3 and LFO4 do not share, and it cannot be reconciled
with "LFO4 writes the mirror correctly" — both are measured, and both stand.

Two readings survive it, and they are distinguishable:

1. **There is more than one buffer.** The page reads `0x800068e4 + 34 + 202*track`
   directly; the evaluator writes through `%a0`, loaded from `%sp@(52)` — an
   argument its caller supplies. Nothing has ever checked that those are the
   same address on the instrument. The emulator cannot say, because the harness
   *passes* that argument itself.
2. **The voice reads it only under a condition** that LFO1-3 always satisfy and
   LFO4 satisfies about one note in fifteen.

**The test that separates them costs nothing and is a manipulation, not an
observation.** Put LFO3 on the same destination with its depth **up**, so its
sweep is plainly audible, then raise and lower LFO4's depth:

- if the audible sweep **changes** — deeper, or a different shape — then LFO4's
  contribution is in the cell the voice reads, and reading (2) is the live one;
- if the audible sweep is **untouched** by LFO4's depth while `SPD` shows the
  cell moving, the two buffers are different memory, and reading (1) is it.

Reading (1) would also explain the whole history at a stroke: the panel, the
table, the key, the row and the evaluator are all correct — as measured — and
the contribution is simply being written somewhere the sound does not come
from.

#### The two-buffer lead collapsed — 2026-09-23

Recorded because a dead lead is a signal, and because it failed in two ways
this file has warned about before.

**The claim was:** the evaluator's mirror base is loaded from a pointer at
`0x4058f39c` (`moveal 0x4058f39c,%a2` at `0x40027120`) while
`csrc/lfo4/meter.c` reads the constant `0x800068e4`, so the two might be
different memory and a fixed-address reader would see a sweep the voice never
hears.

**It is wrong twice.**

1. **`0x4058f39c` is not a pointer, it is a counter.** Every reference to it in
   the image is three instructions apart and says so:
   `movel 0x4058f39c,%d0 ; addql #1,%d0 ; moveq #31,%d1 ; andl %d0,%d1 ;
   movel %d1,0x4058f39c` — `(x + 1) & 31`. The load at `0x40027120` copies it
   straight into `%d5` and leaves `%a2` free. This is the `movea.l` trap in
   `docs/instruments.md`, third time: **`movea.l` does not prove a pointer.**
2. **The probe that "confirmed" it measured nothing.** `emu_mirror_base.py`
   read `0x00000000` and reported "the evaluator and the page are not looking
   at the same mirror". A base of zero would break LFO1-3 as well, so the value
   was never the live one — the snapshot had not run whatever sets it. Its own
   guard said "frame handler entered 64 time(s)", which counted the harness's
   loop rather than real entries. **A null is only evidence once the input is
   known to arrive**, and this probe asserted the guard without implementing it.

**What is actually there:** `%a2` is set at `0x40027194` from `%d0`, the return
of `jsr 0x400db12a` — the routine that holds `lea 0x800068e4,%a2` internally
and which `fxblock16` already proved reaches the DSP. So the evaluator's mirror
is derived from the same `0x800068e4` the page reads, and the two-buffer
reading has no support. Reading it further stalls: the decoder reports
"Address 0x400db166 is out of bounds" inside that routine, and chasing a return
value through an undecodable span by eye is the chase
`docs/FEATURE-PLAYBOOK.md` §2.4 exists to stop.

**So the contradiction stands unexplained**: LFO4's cell sweeps, driven by LFO4
alone with LFO3's depth at centre, and the filter does not move.

The cheapest remaining discriminator is still the one on the instrument, and it
is a manipulation rather than an observation: put LFO3 on the same destination
with its depth **up** so its sweep is audible, then raise and lower **LFO4's**
depth. If the audible sweep changes, both contributions are in the cell the
voice reads and the question becomes why one of them is usually inaudible; if
it does not change while `SPD` still shows movement, they are different memory
after all and the search resumes with that established rather than guessed.

## The 1-in-15 is a key that misses, not a cell that is wrong — 2026-09-23

Everything from the panel to the mirror cell is measured and correct, the
evaluator treats LFO4 and LFO3 byte-identically over 240 frames, and yet the
instrument modulates on roughly **one trig in fifteen**. That number is the
evidence nothing has used: **a wrong cell would never work.** One in fifteen is
a lookup that usually misses.

`lfo4_refresh` in `csrc/lfo4/bridge.c`:

```c
values = ext_find(lfo4_sound_of(track));
for (k...) row[k] = values ? values[k] : ext_default[k];
```

**A miss is not a no-op. It loads the defaults, and the default `DEST` is
None** — so a note whose row missed modulates nothing, and a note whose row hit
modulates. That is binary-per-note exactly as reported.

And the two sides derive the key differently, which is the whole question:

| | how the key is built |
|---|---|
| the **UI** (`hooks.S`, `valuehooks.S`) | `%a2@(16)` then `vtable[40]()` — the firmware's own virtual call |
| the **tick** (`bridge.c`) | `*0x800052a0 + 52 + 1163*track` — the firmware's arithmetic at `0x40025bda` |

The getter and setter use the **identical** derivation, which is why the page
displays what was typed. That is self-consistency, not agreement with the tick,
and it is why the page looking right has never been evidence.

### `emu_lfo4_key.py` — written, run, and its conclusion withdrawn

The first probe compared `*0x800052a0 + 52 + 1163*track` against
`lfo4_sound_of(track)` and reported **8/8 tracks agree**, concluding "the key
theory dies here". **That conclusion is withdrawn: the probe compared the tick's
formula with the tick's own formula.** `lfo4_sound_of` *is* that expression, so
agreement was guaranteed before the machine was started. It is kept because the
mistake is instructive and because one part of it is real:

> `control  store under lfo4_sound_of(0) -> hits 0->1, misses 0->0, last_lookup 1  HIT`

**The lookup machinery works.** A row stored under the tick's key is found under
the tick's key. So if there is a miss on the instrument it is the key that
differs, not `ext_find`.

This is the same failure as the `movea.l` trap and the container-header offset:
*a comparison needs two independent derivations, and "both sides call the same
function" is not two.*

### `emu_lfo4_uikey.py` — the probe that can answer it

Drives the panel to the LFO4 page so `lfo4_on_get` runs through the real path,
then reads the key the firmware's own virtual call produced (`lfo4_get_sound`)
and compares it with `lfo4_sound_of(track)`. Prediction and control are written
into the script before the run, and the control is `lfo4_gets != 0` — because a
zero key with a getter that never ran is a null about navigation, not about
keys.

### Result: the keys agree, and the theory is dead

```
lfo4_gets      65
lfo4_get_sound 0x4210c0c0   <- the UI's own virtual call
lfo4_sound_of  0x00000008   <- the tick key, by calling it
base+52+1163t  0x4210c0c0   <- the same, by reading memory
```

**`lfo4_get_sound == base + 52 + 1163*track`.** Those two are genuinely
independent: one is a C++ virtual dispatch through the firmware's own object
(`%a2@(16)` then `vtable[40]()`), the other is our arithmetic on a longword read
straight out of `*0x800052a0`. They produce the same address.

**So the UI writes LFO4's row under exactly the key the tick asks for, and the
1-in-15 is not a key that misses.** Recorded as a refutation, not a footnote:
the hypothesis was specific, it predicted a difference, and there is none.

What survives from it is still worth having:

- `ext_find` works — a row stored under the tick's key is found under it
  (`emu_lfo4_key.py`'s control, the one real line in that probe);
- a miss would load `ext_default`, whose `DEST` is None, so **if** a miss ever
  happens it is silent and total. That remains the right thing to instrument on
  hardware, because the emulator cannot produce one.

### The harness fact, which is the more useful half

**`m.call` into the build's code region is unreliable after the panel has been
driven.** `lfo4_sound_of` returned `8`, and that function returns either zero or
`base + 52 + 1163*track` — never 1..51. The call did not execute the function.

This matters beyond this probe: **most remaining LFO4 questions want the panel
driven *and* a routine called directly**, and that combination silently returns
a plausible-looking integer. The first run of this probe turned that integer
into "the UI stores LFO4's row under a key the tick never asks for" — a false
positive that read exactly like a discovery.

The guard is cheap and should be copied: **derive anything you compare twice, by
two routes, and refuse to compare when they disagree.** Whether the cause is the
code region not surviving UI execution, or the call convention not re-entering
from that state, is unmeasured and is the next thing to find out before another
probe of this shape is trusted.

### The pattern, now specific enough to be a rule

Four failures today share one shape, and it is not "static reads are risky":

| | controlled | assumed |
|---|---|---|
| the container header | the addresses | the frame they were in |
| the `movel` scan | the constant | the direction of the addressing mode |
| `emu_lfo4_key.py` | the lookup | that the two sides were different formulas |
| `emu_lfo4_uikey.py` | that the page was reached | that the other side of the comparison ran |

**Every one was a comparison where one side was controlled and the other
assumed.** The measurements were fine. Write the control for the arm you are
*not* thinking about.

### The harness question, answered — and both my explanations were wrong

`scripts/emu_call_after_panel.py`, two arms, controls on both:

```
before panel:  stub -> 42                        lfo4_sound_of(0) -> 0x4210c0c0  OK
after  panel:  lfo4_sound_of(0) FIRST -> 0x4210c0c0  OK
               stub bytes 702a4e75 (intact)      stub -> 0x4210c0c0  STALE
               the function's own 64 code bytes: unchanged
```

| candidate | verdict |
|---|---|
| the UI clobbers the build's code region | **dead** — 64 bytes byte-identical |
| the first call after the panel does not run | **dead** — called first, answered correctly |
| `m.alloc` scratch is overwritten | **dead** — `702a4e75` still there |

**What is true: the loaded code region stays callable across panel driving, and
`m.alloc` scratch does not.** The stub's bytes are intact, the call mechanism
demonstrably works in the same breath, and yet executing the stub leaves `%d0`
holding the *previous* call's result — `emu_start` did not run it. The cause is
unmeasured. The rule does not depend on knowing it:

> **After driving the panel, call only into the build's loaded code region.
> Never into `m.alloc` scratch, and never trust a returned value that equals the
> previous call's.**

That last clause is the cheap guard: a stale `%d0` is indistinguishable from an
answer, which is how `emu_lfo4_uikey.py` turned an `8` into a discovery.

**And this closes the LFO4 code region as a suspect.** The region is intact
after the UI runs, so "the firmware's heap grows into `0x46800000` and corrupts
the row table" — which would have predicted the 1-in-15 exactly — is not
supported by anything measured. Written down because it was an attractive
theory and it should not be re-derived later as though it were new.

### Where this leaves the contradiction, honestly

Every probe built today runs on a snapshot that **has already booted and never
plays a note**. `docs/instruments.md` says so in as many words. The remaining
explanations for the 1-in-15 all live at note-on, and no offline harness here
can reach it.

**So the next measurement is on the instrument and it costs two knob turns and
no flash** — see `00_Notes/.../Firmware test plan.md`, the LFO3-beside-LFO4
depth test. It discriminates between the two surviving families where nothing
offline does.

## SOLVED: LFO4's row is selected by the voice index, not the track — 2026-09-23

**Found by the owner, at the instrument, by opening the voice allocation menu.**
Four hypotheses from this session died before it and none of them would have got
here; the menu did it in one look.

### The evidence, in the order it arrived

| observation | what it fixed |
|---|---|
| *"the triggers that work always trigger on voice number 7"*, on **track 7 (index 6)** | the selector is the voice number, and "1 in 15" was never a probability -- it is **1 of 16 voices** |
| selecting **reuse** to pin the voice makes LFO4 work on **every** trig | nothing about the LFO, the row, the cell or the key is wrong |
| moved to **track 11 (index 10)** -> **voice 11** now activates | the working voice follows the **track index**, on a second track, far from the first |
| **voice 7 still activated on track 11** | *not* an anomaly -- track 7's row was still configured, so **two** populated rows meant two working voices, on any track |
| setting track 7's `DEST` to None -> **voice 7 stops, voice 11 keeps working** | the prediction that closes it: the row is indexed by voice, populated per track, and any populated row fires on its matching voice **regardless of which track is playing** |

That last one was a positive prediction made before the test and it held, which
is worth more than the four eliminations that preceded it.

### Why every previous probe missed it

- **`lfo4_misses` stayed flat** on hardware with a passing liveness control --
  and that is exactly right. The lookup never *fails*; it **succeeds on the
  wrong row**. A row for a track with no LFO4 settings is all zeros, its `DEST`
  is None, and a None destination is silent and total. Nothing increments.
- **Every offline harness drives the evaluator directly and never allocates a
  voice**, so the index it was handed was whatever the harness put there. The
  fault needs a voice pool to exist, and the emulator has none.
- **`emu_lfo4_vs_lfo3.py` found LFO3 and LFO4 byte-identical over 240 frames.**
  True, and irrelevant: both were driven with the same index.

### Where the wrong index comes in

`scripts/build_lfo4_tick7.py` picks the index at each of the two patch sites:

```python
A_INDEX = "move.l %a5,%d0    | evaluator A's track index"
B_INDEX = "                  | evaluator B's track index is already in %d0"
```

**Both comments were written by inference and neither was ever measured**, and
`lfo4-bridge` inherited them unchanged when it replaced the static table with
`lfo4_refresh(index)`. `lfo4_refresh`'s only guard is `track >= TRACKS`, so an
index of 0..15 from any source passes straight through and selects a row.

A static read of evaluator A shows `%a5` zeroed at entry (`subal %a5,%a5`) and
used to shift a 16-bit enable mask -- which *looks* like a per-track loop, and I
read it that way and said so. **The instrument disagrees, and the instrument
wins.** Which of the two sites carries the voice number is now a measurement to
make, not a register to name in a comment -- that is the mistake this whole
section is about.

### The fix, and the property it must have

Whatever index reaches `lfo4_refresh` must be **the track that owns the sound
this voice is playing**, and it must be derived from something the firmware
itself uses for LFO1-3, so the two cannot drift. The candidate:

    track = (block - 0x800068e4 - 34) / 202

taken from the very mirror block the evaluator is already reading LFO1-3's
parameters out of. Then LFO4 and LFO1-3 agree by construction rather than by
a comment -- which is the same argument that made `fxmod` trustworthy.

**Not yet built and not yet measured.** The diagnosis is closed; the fix is not.

### The readout was never calibrated, and that voided a day of readings

**The LFO4 page renders the HIGH BYTE of the value a column returns.** A
hardcoded `99` displayed as `-64`: `99` is `0x0063`, high byte `0`, and FADE
maps `(raw >> 8) - 64`. SPH maps `raw >> 8` with no offset.

Every diagnostic value returned during 2026-09-23 was in 0..15. **All of them
have a high byte of zero, so all of them displayed identically no matter what
they held.** These readings are withdrawn:

| read as | actually showed |
|---|---|
| `lfo4_last_index` "always 0" | nothing — any value 0..255 looks the same |
| `lfo4_index_max` "always 0" | nothing |
| `lfo4_out_of_range` "always 0" | nothing |
| `lfo4_block_track` "always 0" | nothing |
| `lfo4_block_ptr` "stuck at 52" | only the pointer's high byte |

**"The index is always 0" was never measured.** The whole evening's chain --
index stuck at zero, therefore the stub reads the wrong slot, therefore
`%sp@(72)` is wrong, therefore `%a4` is wrong -- rested on a readout that could
not have shown otherwise.

`lfo4_refreshes` appeared to work only because a free-running counter crosses
high-byte boundaries. **That false positive is what made the channel look
sound**, and it is why the calibration was never run: one column visibly moved,
so the instrument was assumed good.

**The rule, and it cost six flashes:** *before reading a number off an
instrument you built, put a known constant through it.* The control belongs on
the measuring device, not only on the experiment. Shifting values into the high
byte (`value << 8`) makes them readable; a constant in a second column decodes
the mapping instead of assuming it.

### With the readout calibrated, the `%a4` fix is confirmed working

`lfo4_row_for_block` now takes `%a4`, which holds the per-track mirror pointer
on entry to the stub -- Ghidra's `local_18 = param_1 + 0x22`, advanced 202 per
track, with `iVar12 = local_18 - 0x22` being the very instruction `a4_top`
replaces, and our own stub source saying the same thing in a comment nobody had
checked.

Measured: **SPH reads 15 on every track**, which is `TRACKS - 1`. The page reads
the global after the tick has walked all sixteen tracks, so it catches the last
one. **The derivation sweeps 0..15**, so the block pointer genuinely advances,
`%a4` genuinely is the per-track pointer, and every track's row is refreshed
under its own index. The prediction "SPH reads 15 whatever track you are on"
was made before the test and held.

### And the bug is still there, which moves it downstream

Rows are right and modulation is still gated on `voice == track`. The
decompiler shows exactly one candidate:

```c
uVar3 = param_3 >> (uVar13 & 0x3f) & 1;   /* an enable bit per track */
```

`param_3` is an **enable mask**, tested bit by bit against the track counter,
and it sits at `%sp@(88)` at the function entry where the disassembly shows it
loaded (`movel %sp@(88),%d5` then `asrl %d1,%d5`).

**Every harness in `scripts/` passes `0xFFFF` for it.** `emu_lfo4_vs_lfo3.py`
calls `m.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, ...)` -- all bits set, gate
held open. **So no offline probe could ever reproduce a gating bug**, which is
why LFO3 and LFO4 came back byte-identical over 240 frames while the instrument
disagreed. The harness answered the question with the gate wedged open.

If that mask carries the **voice's** bit rather than the track's, then track `n`
is enabled only when `n` equals the voice -- the owner's law exactly, with no
coincidence left in it. **Unmeasured.** The next read captures `param_3` at the
function entry, which is a different site from the one this session kept getting
wrong.

## Telemetry works: the instrument reports to the computer — 2026-09-24

**`DN2_MIDI_TX = 0x401233f2`.** Found by walking `MidiOutputStream`'s vtable at
`0x40207c98`. Its `put(byte)` appends to a buffer at `this+20`, counts at
`this+8`, and tail-calls `flush` when full; `flush` calls
`0x401233f2(buffer, count, port, flags)`. The three callers outside the class
push `port` and `flags` as **constants** -- `clrl` then `pea 0x2` -- so no stream
instance is needed: three bytes on our own stack and one call.

**Why it hid for a day.** A GCC RTTI name carries a length prefix. The typeinfo
points at `0x4023100c`; the text "MidiOutputStream" starts one byte later at
`0x4023100e`. Searching for a pointer to the *text* found nothing, and that null
was read as "no vtable, a mangled fragment". It had a vtable all along.

### Confirmed on the instrument

469 control changes on channel 16 in ten seconds, `marker` stepping cleanly.
**The firmware reports to the computer, and every future probe inherits the
channel.**

Two facts fell out of the first run that nothing had measured:

- **`lfo4_row_for_block` runs ~23,500 times a second** -- the marker stepped
  every ~87 ms at one burst per 2048 calls. That is ~1,470 evaluator passes
  across sixteen tracks.
- **A sampling period must be coprime with the loop length.** The first build
  sampled every 2048 calls; the engine walks 16 tracks in order; 2048 mod 16 is
  0, so **every burst landed on the same track for ever** and reported
  `track = 15` on all sixteen. It looked like the firmware pinning something.
  The owner disproved it in one move -- toggling other tracks changed nothing --
  before the arithmetic did. 2049 mod 16 is 1, and the round-robin then reported
  all sixteen tracks in about 1.4 s.

### The frame map, and three wrong guesses finally measured

Passing the stub's `%sp` and walking `+0..+124` over successive bursts:

| offset | observed | reading |
|---|---|---|
| **+8** | 10502, 10704, 10906 | **steps of exactly 202** -- the per-track mirror pointer, `local_18` |
| **+80, +100** | 10468, 10621, 10774 | **steps of exactly 153** -- matching `outer`'s `add.l #153` |
| **+104** | `0x3840` | the scale constant `emu_boot_engine` prints entering evaluator A |
| **+108** | 0 | **the slot guessed three times, confirmed empty** |

Two independent strides matching constants the decompiler showed in `outer`:
the frame identifying itself. **The enable mask is not in this window**, and
should not be -- `%sp@(88)` was read at the *function entry* frame, and this stub
runs below all of evaluator A's locals, so the arguments sit further up.

### And extending the reach broke the instrument

`+0..+508` in one step **killed MIDI output entirely**: audio kept playing, the
sequencer kept running, and the instrument stopped sending notes *and*
telemetry. Nothing else differed between the two builds -- same emission rate,
same message shape, same call site.

**A read is not free.** The reasoning that produced it -- *"I would rather
over-reach and discard than under-reach and guess again"* -- treated reads as
harmless because they do not write. 512 bytes above the stub's stack pointer is
past evaluator A's frame, and on a 0x4000-byte task stack can leave the mapped
region; a fault in an interrupt-driven task kills it as surely as a bad write.
Reverted to +124, which is known good.

**The next attempt is targeted, not wider**: the decompiler can give evaluator
A's frame size, and then the arguments' offsets are known rather than swept
toward. That is a Ghidra read, not a flash.

### What the channel is worth

The instrument degraded and the probe said so **in seconds**, because notes
disappearing is unmissable. The day before, this would have read as "telemetry
did not work" and cost hours.

### The frame, read properly — and the mask candidate is not the gate

With the walk back at +124 and the instrument playing (track 7 = index 6 with
LFO4, track 16 = index 15 with the MIDI machine), the frame identifies itself
through its strides:

| offset | behaviour | reading |
|---|---|---|
| +72 | steps by **202** | the per-track mirror pointer |
| +76 | steps by **160** | `STATE_STRIDE` -- the constant `tick7` records as "will not fit a moveq" |
| **+68** | `0x3FFF`, or `0` | the mask-shaped candidate, sitting between them |

Two of `outer`'s three strides, adjacent, exactly as the decompiler describes
them. So `+68` is in the right neighbourhood for an enable mask.

**Correlated against the track, it is not the gate.**

```
track 0        -> 0
tracks 1..15   -> 16383 (0x3FFF)
```

A per-track field that is zero for track 0 and all-ones everywhere else. In a
14-bit window "all ones" is what `0xFFFF` and `0xFFFFFFFF` both look like, so
this reads as a flag rather than a sixteen-bit mask.

**It cannot be what gates LFO4**: track 6 is the one with LFO4 and it reads
*enabled*, while modulation still lands only on voice 7. It shows nothing
special at index 15 either, so it does not track which tracks are playing.

Three limits on that measurement, stated because they bound it:

- **one sample per track** -- the walk visits `+68` once every ~45 s;
- **14 bits of 32** -- a CC pair carries no more, and several 32-bit values
  share that low pattern;
- **track 0 reading zero may be an artifact** of being first in the loop rather
  than a disabled state.

### Where that leaves the voice question

The frame has now been mapped rather than guessed at, and nothing in +0..+124
gates on the voice. The enable-mask hypothesis from `param_3` is **not
supported by anything measured**: the shifted-mask test at the function entry is
a different frame, and this stub cannot see it without a reach that killed the
instrument once already.

**The next step is not another sweep.** Ghidra can give evaluator A's frame size,
and with it the arguments' offsets are known rather than swept toward. That is a
static read costing no flash and no risk, and it is the right instrument -- the
same one that produced `%a4` after four builds had guessed at stack slots.

## Evaluator A's frame, read instead of swept -- and what it says about voices

**2026-09-24, static read, no flash.** The previous section ends with "the
decompiler can give evaluator A's frame size, and then the arguments' offsets
are known rather than swept toward." It does, and the answer arrives in four
instructions.

### The frame

```
0x40137726  4f ef ff b4   lea %sp@(-76),%sp
0x4013772a  12 2f 00 6b   moveb %sp@(107),%d1
0x4013772e  48 d7 7c fc   moveml %d2-%d7/%a2-%fp,%sp@
0x40137732  24 2f 00 50   movel %sp@(80),%d2
```

**There is no `LINK`.** The function allocates 76 bytes with a bare `lea` and
addresses everything through `%sp`; `moveml` saves eleven registers at `%sp@(0)`
without moving `%sp`. So the saved registers occupy +0..+43, locals +44..+75,
the return address +76, and **the arguments begin at +80**:

| | offset | what it is |
|---|---|---|
| `param_1` | **`%sp@(80)`** | the mirror base -- `lea %a0@(34),%a0` is applied to it immediately, the same `+34` as `0x400db092` |
| `param_2` | `%sp@(84)` | a scalar, read at `0x40137872` |
| `param_3` | **`%sp@(88)`** | enable mask -- `asrl %a5,%d5 ; andl #1` |
| `param_4` | **`%sp@(92)`** | enable mask -- `asrl %a5,%d7 ; andl #1` |
| `param_5` | **`%sp@(96)`** | pointer to a **16-byte array, one signed byte per track** |
| `param_6` | **`%sp@(100)`** | pointer to a second such array |
| `param_7` | `%sp@(104)`, byte at `%sp@(107)` | a flag, read *before* the prologue completes |

### The control, because a prologue read on its own is one measurement

The call site counts the arguments independently of any offset arithmetic:

```
0x400272ba  2f 01               movel %d1,%sp@-           | arg7
0x400272bc  48 6e ff b8         pea %fp@(-72)             | arg6
0x400272c0  48 6e ff a8         pea %fp@(-88)             | arg5
0x400272c4  2f 2e ff 58         movel %fp@(-168),%sp@-    | arg4
0x400272c8  2f 2e ff 68         movel %fp@(-152),%sp@-    | arg3
0x400272cc  2f 39 40 2a 0d ec   movel 0x402a0dec,%sp@-    | arg2
0x400272d2  2f 0a               movel %a2,%sp@-           | arg1
0x400272d4  4e b9 40 13 77 26   jsr 0x40137726
0x400272da  4f ef 00 1c         lea %sp@(28),%sp          | 28 bytes = 7 arguments
```

**Seven arguments, and the cleanup says so in one byte.** Every slot agrees with
the prologue. `arg5` and `arg6` are `pea %fp@(-88)` and `pea %fp@(-72)` --
adjacent locals exactly **16 bytes apart**, which is what a one-byte-per-track
array looks like from the caller's side.

### Why the +0..+124 walk found nothing, and it was closer than it looked

The walk stopped at +124 after the +508 attempt killed MIDI. From the stub's
`%sp`, evaluator A's own locals are what that window covered. **The arguments
begin one stride above the top of it.** The enable mask was never going to
appear in +0..+124 -- not because the reach was wrong in kind, but because it
was short by a handful of words.

**And it should not be reached by walking at all.** The hook site sits inside
evaluator A's frame, where `%sp@(88)` and `%sp@(96)` are *valid operands*. The
stub can be handed the masks and the voice array directly, as `build_lfo4_bridge.py`
already hands it `%a4`. No walk, no reach to earn, nothing above the frame to
fault on. That is the same move that retired the `%sp@(72)` guesses.

### What `param_5` actually holds, and this is the finding

The caller fills those two arrays in its own 16-iteration loop at
`0x400271a2`. It opens by defaulting **both to -1 for every track**:

```
0x400271a2  50 c4         st %d4                              | d4 = 0xFF
0x400271a4  1d 84 28 a8   moveb %d4,%fp@(-88,%d2:l)           | array5[track] = -1
0x400271a8  1d 84 28 b8   moveb %d4,%fp@(-72,%d2:l)           | array6[track] = -1
```

and writes a real value only here:

```
0x40027240  2f 06         movel %d6,%sp@-
0x40027242  4e 95         jsr %a5@                            | a5 = 0x40138664
0x40027244  58 8f         addql #4,%sp
0x40027246  b0 8b         cmpl %a3,%d0                        | a3 = 0x4002b22e(track)
0x40027248  66 de         bnes 0x40027228                     | no: clear bit, next
0x4002724a  1d 86 28 a8   moveb %d6,%fp@(-88,%d2:l)           | array5[track] = d6
```

`%d6` is a **bit index** -- the loop isolates the lowest set bit of a mask with
the classic `neg ; and ; ff1` idiom and converts it to a position. The bit is
kept only when `0x40138664(bit)` returns the same object as `0x4002b22e(track)`.
One function maps a track to its object; the other maps this index to an object
and the two are compared for equality. **So the index is a voice, and
`param_5[track]` is the voice currently allocated to that track, or -1 when
there is none.**

Evaluator A then uses it as an address:

```
0x401377d2  moveal %sp@(96),%a1
0x401377d6  mvsb %a1@(0,%a5:l),%d0    | d0 = voice for this track, sign-extended
0x401377da  bges 0x401377fe           | -1 means no voice: skip
...
0x401377fe  movel %d0,%d2
0x40137800  lsll #3,%d2
0x40137802  lsll #7,%d0
0x40137808  subl %d2,%d0              | d0 = voice*128 - voice*8 = voice*120
0x4013780a  addl %a0,%d0
0x4013780c  addil #0x4463ed18,%d0
```

### The correction: those arrays are indexed by voice, not by track

`build_lfo4_tick.py` says, and this document has repeated, that the three
1,920-byte arrays at `0x4463ed18` / `0x4463f498` / `0x4463fc18` are
**"16 tracks x 3 LFOs x 40"**. They are **16 *voices* x 3 LFOs x 40**. The
`x120` above is reached with a byte that the caller filled from a voice mask,
after checking that the voice belongs to this track.

~~16 tracks x 3 LFOs x 40 bytes~~ -- kept, because the stride arithmetic derived
from it is still right and every edit made on top of it still holds. **16 is 16
either way**, which is exactly why the 120 -> 160 change left LFO1-3 working and
why nothing caught this for six builds. The count was never the error; the
*name* was, and the name is what tells you which index to reach it with.

### The hypothesis this makes, and it is now a named one

The owner measured: LFO4 modulates only when the voice counter lands on the
number equal to the track index -- track 3 on voice 3, track 7 on voice 7,
track 11 on voice 11, two configured tracks giving two working voices.

Put beside the above, that is the signature of **two indices that are each
correct in their own space and are being used in one**. LFO4's *parameters*
come from `lfo4_rows[track]`, keyed by track off `%a4`, which is right. LFO4's
*state* record lives at `state + voice*160 + 120`, keyed by voice, which is also
right. Any site that reaches the state with the track index lands on the correct
record **only when track == voice** -- and that is the whole reported symptom,
including why pinning the voice makes it work on every trig and why clearing a
track kills its voice.

**This is a hypothesis, not a result.** What is measured is the frame, the
argument list, the two defaults of -1, the equality test that fills them, and
the `x120` that consumes them. What is not yet measured is *which* of our patch
sites reaches the state with the wrong index -- and the next step is to find it
in the disassembly of our own build, which is again a static read and again
costs no flash.

### For whoever picks this up

The voice number is **`%sp@(96)` byte `[%a5]`, sign-extended, `-1` for "no
voice"** -- and `-1` must skip, exactly as stock's `bges`/`blts` do. A build that
applies LFO4 to a track with no voice allocated is a build that writes into
record -1.

### Correction, same day: both indexings are real, and `outer` proves it

The section above says the three arrays are "16 **voices** x 3 LFOs x 40, **not**
16 tracks". **That is too strong, and the stub we wrote ourselves disproves it.**

`outer`, the per-track advance in `build_lfo4_tick.py`, is a subroutine, so its
`%sp@(N)` is evaluator A's `%sp@(N-4)` -- the `jsr` return address, and the
offsets line up with the frame read exactly as they must:

| `outer` | evaluator A | stride | what it walks |
|---|---|---|---|
| `%sp@(56)` | `%sp@(52)` | **202** | the per-track mirror |
| `%sp@(60)` | `%sp@(56)` | **120 stock, 160 ours** | the live state array |
| `%sp@(64)` | `%sp@(60)` | 153 | `param_1` |

`addq.l #1,%a5` sits in that same block. So the live state array at
`0x4463fc18` is **walked one 120-byte record per track**, in lockstep with the
track index -- and that is stock arithmetic we only restrided, not a reading of
ours.

Meanwhile the restore/backup block at `0x401377d2..0x4013781c` reaches
`0x4463ed18` and `0x4463fc18` as **`base + voice*120 + lfo*40`**, with the voice
from `param_5`/`param_6` and `-1` meaning none.

**Both are true at once, and that is the point.** One array is walked by track,
the other is reached by voice, and that block is the **bridge between them** --
which is exactly what carrying an LFO's phase across a voice allocation
requires. The equality test that fills `param_5` (`0x40138664(bit)` vs
`0x4002b22e(track)`) is not decoration; it is what makes the conversion legal.

~~The arrays are 16 voices x 3 LFOs x 40, not 16 tracks.~~ **Withdrawn.** What
survives from it, and it is the part that matters: **`param_5[track]` is a voice
number, `-1` when the track has no voice**, and the restore/backup paths are
voice-indexed. What does not survive is the claim that the *live* array is
voice-indexed -- `outer` walks it by track.

**Why the mistake happened, because it is a repeat.** One indexing was read and
generalised to the whole structure without checking the other sites that reach
it. That is the same shape as the three uncontrolled negatives: a single
observation treated as a property. The control was available and cheap -- our
own patch list names every site that touches these arrays.

### So the state machinery is not the suspect any more

Checking `edits()` against the above, **every site is patched**: the bulk copy
length (1920 -> 2560), both restore and backup stride idioms
(`idx<<3` -> `idx<<5`, `128-8` -> `128+32`), all three bases relocated, both
initialisers' record count (3 -> 4), track stride and array length, and the
inner loop counter 2 -> 3. The `flags` stub writes the fourth record too.

So the voice gate is **not** an unpatched stride, and the leading hypothesis of
the previous section is weakened rather than confirmed. Good: that is what the
read was for.

### The next step is a measurement, not another hypothesis

Everything above is static. The one thing that would settle it costs one build
and uses operands that are **valid at the hook site** -- no stack walk, nothing
above the frame to fault on:

> emit `%a5` (the track) and the sign-extended byte at `%sp@(96)` indexed by
> `%a5` (the claimed voice) on the same telemetry burst, beside the existing
> `probe_a = 99` constant.

On the instrument that answers, live and while the owner moves tracks:

- whether `param_5[track]` really is a voice number (it should follow the voice
  allocation display the owner already has open);
- what it reads for the track carrying LFO4, and whether it is `-1` except when
  a voice is allocated;
- and whether it equals the track index precisely when the modulation fires --
  which is the reported symptom, stated in the one quantity that can confirm it.

That is the first hardware test of the frame read, and it is worth one flash
because it discriminates rather than confirms.

## The offset is measured, the array is empty, and that retires a hypothesis

**2026-09-24, emulator + instrument, both with controls.**

### The offset, from an instrument that knew the answer first

`scripts/emu_lfo4_frame.py` calls evaluator A itself, so it *chooses* the
addresses it passes as `param_5` and `param_6` and then searches the frame our
stub is handed for those exact values. Known answer on both arms:

```
param_5 = 0x46a10d00   param_6 = 0x46a10e00   (chosen by the harness)
frame   = 0x469fffa0   (16 calls, 1 distinct)

param_1: frame + 100
param_5: frame + 116
param_6: frame + 120
```

So `%sp@(96)` and `%sp@(100)` reach our stub at **`frame + 116` and
`frame + 120`** -- exactly the pair the hardware sweep had singled out as the
only adjacent valid pointers. **The coincidence reading is dead**: those words
are the arguments, not two stack values that happened to look like addresses.
That mattered, because "looks like a pointer" is the same trap as `movea.l`
not proving a pointer.

### And the array is empty

With the offsets confirmed, `lfo4-voice`'s hardware reading stands as a result
rather than a maybe. 468 bursts, `probe_a` = 99 on every one, marker sweeping
all 128, each of the sixteen tracks sampled ~29 times, sequencer running, notes
sounding:

```
track 0..15   param_5[track] = -1     param_6[track] = -1
```

**Every track, every sample, both arrays.** Zero bursts where
`param_5[track] == track`.

### What that retires

The earlier section called `param_5[track]` "**the voice currently allocated to
that track**". ~~That~~ is too strong and the instrument says so: if it were the
current voice it could not read -1 on every track while notes are sounding.

What it actually is follows from the caller's own three gates at `0x400271a2` --
a per-track enable bit at `%fp@(-172)`, a non-zero field at `+326` of the
track's object, and a non-negative result from `0x4002b1f4` -- and from what
evaluator A does with a non-negative value: **a 40-byte record copy**. An array
that is -1 almost always and names a voice occasionally, feeding a block that
copies one LFO record, is **the voice whose state must be migrated this frame**,
not the voice that is playing. It is the phase-carrying path for a voice
changing hands, and in steady state it correctly does nothing.

So: **the restore/backup copy block essentially never runs**, and it is not the
path by which LFO4 reaches a voice. Two hypotheses die together -- the state
machinery (already cleared as fully patched) and the voice array.

### Where this leaves the hunt

Everything in evaluator A's steady-state path that has now been read is
**track-indexed**: the mirror at `%sp@(52)` (202/track), the live state array at
`%sp@(56)` (160/track in our builds, `outer` advancing both in lockstep with
`%a5`), and LFO4's parameter row from `lfo4_rows[track]`. No voice index
survives in the per-frame path at all.

**Which makes the reported symptom stranger, not clearer**, and that is an
honest position rather than a discouraging one. If nothing in this function
knows about voices, then the track -> voice coupling the owner measured happens
**after** evaluator A -- in the frame the engine builds (`0x400274ba`) and sends
(`0x400cf7be`), which is where a per-track mirror has to become per-voice DSP
state. That is the next thing to read, and it has never been looked at.

**What is now solid and should not be re-derived:** evaluator A's frame and its
seven arguments; `param_5`/`param_6` at `frame + 116` / `frame + 120`; that both
are -1 in steady state; and that the telemetry channel reads real arguments
faithfully, which is an instrument the project did not have this morning.

## The frame builder is track-indexed too, so the gate is downstream of the CPU

**2026-09-24, static read of `0x400274ba`.** The previous section ended by
pointing here: if nothing in evaluator A knows about voices, the coupling the
owner measured must happen where a per-track mirror becomes per-voice DSP state.
It does not happen here either.

### What the builder does

```
0x400274ba  lea 0x80005e60,%a3        | the frame, and %a4 walks it
0x400274c4  moveal %a2,%a5            | %a2 = param_1 of evaluator A: the mirror base
0x400274ee  movel #0x40134490,%d4     | the same copier evaluator A uses
...
0x40027526  pea 0x52 ; pea %a5@(84)  ; pea %a4@(218)  ; jsr %a1@   | 82 bytes
0x40027534  pea 0x1c ; pea %a5@(166) ; pea %a4@(300) ; jsr %a0@    | 28 bytes
0x40027544  pea 0x1a ; pea %a5@(194) ; pea %a4@(328) ; jsr %a1@    | 26 bytes
0x40027558  pea 0x0a ; pea %a5@(224) ; pea %a4@(354) ; jsr %a0@    | 10 bytes
0x40027568  lea %a5@(202),%a5         | source: one mirror record per TRACK
0x4002756c  lea %a4@(146),%a4         | destination: 146 bytes per TRACK
```

`%a2` is set at `0x40027194` and handed to evaluator A as `param_1` at
`0x400272d2`, so it is the mirror base -- the same pointer, in the same
function, a few hundred bytes apart.

**The offsets fit once the `+34` header is counted, and I had them wrong until
it was.** A record's data starts at `base + 34 + 202*track`, so `%a5@(84)`
through `%a5@(233)` is 150 bytes reaching **slots 25..99** -- comfortably inside
the 202-byte record, and slots 25..69 are exactly the FX/Master range from the
lane-16 work. My first reading said the copies overran into the next track,
which would have been a finding; it was an arithmetic slip, and it is recorded
because the slip is the kind that produces confident nonsense.

### What that settles

Three stages now read end to end -- the caller's per-track loop at `0x400271a2`,
evaluator A, and the frame builder -- and **every index in all three is the
track**. Strides 202 (mirror), 160 (LFO state, ours), 146 (frame record), `%a5`
and `%d2` both stepping once per track. The only voice-indexed thing anywhere
is the restore/backup copy block, which is -1 in steady state and does nothing.

**So the DSP receives sixteen track records and does voice assignment itself.**
Whatever couples LFO4 to one voice is **downstream of the ColdFire**, on the
SHARC side or in how a voice picks up its track's record.

### And that makes the next measurement the right one, rather than a fourth read

Reading further down this path means the SHARC, which is a second processor this
project has only partly decoded -- expensive, and it would still be static.

**The telemetry channel now reads real function arguments faithfully**, and it
can answer the question that separates upstream from downstream in one flash:

> emit LFO4's **computed modulation value** and the **DEST slot it writes**, per
> track, every burst.

- If the value is non-zero continuously for the LFO4 track while the sound only
  changes on one voice, the fault is **downstream** of evaluator A and the
  search is on the SHARC side. That would also be the first hard evidence that
  the ColdFire half of LFO4 is *complete*.
- If it is zero except when that one voice is active, the fault is **inside**
  evaluator A's per-track loop, and everything read today says where to look
  next.

Either answer closes half the remaining space, which no further static read of
this path can do.

# SOLVED: the ColdFire half of LFO4 is complete, and the voice gate is downstream

**2026-09-24, on the instrument, with a control on both arms.**

`lfo4-slotfix` reads the mirror slot LFO4's `DEST` points at, for the previous
track, every burst -- `block + 2*slot`, after two builds read it seventeen slots
low. Track 7 (index 6) carried LFO4 on `Syn Ratio C`, slot 26. Every other track
reported `DEST = 0` and never moved, on every run.

| configuration | slot 26, distinct values | span |
|---|---|---|
| LFO1 **and** LFO4 both on `Syn Ratio C` | 17 | **1553** |
| LFO1 off, LFO4 on | 18 | **528** |
| **LFO4 depth 0** | 1 | **0** |

**Remove one modulator and the span shrinks; remove the other and it vanishes.**
Neither reading alone would have carried this -- the first is equally consistent
with LFO1 doing all the work, and the third alone says nothing about which
modulator stopped. The graded series is the result.

351 bursts per run, `probe_a` reading 99 on every one, marker sweeping all 128.

## What is now established

**LFO4 generates its waveform, applies it, and writes the result into the
correct mirror slot of the correct track, every audio frame.** The parameters
come from `lfo4_rows[track]` via the bridge; the destination comes from the
row's `DEST`; the value lands where the frame builder will copy it (slots 25..99
are exactly what `0x400274ba` sends to the DSP).

So **the ColdFire half of LFO4 is complete.** That has never been demonstrated
before -- every previous claim rested on the owner hearing a sweep, which is
exactly the evidence that the voice gate makes unreliable.

## Which retires this branch's hypothesis

`fix/lfo4-voice-index` was opened to find why modulation fires only when the
voice index equals the track index. Today's reads settle where it *cannot* be:

| stage | index |
|---|---|
| the caller's loop, `0x400271a2` | **track** |
| evaluator A, `0x40137726` | **track** (`%a5`, `outer` advancing mirror 202 / state 160 / 153 in lockstep) |
| the frame builder, `0x400274ba` | **track** (source 202, destination 146) |
| LFO4's own write, measured above | **track** |

The only voice-indexed thing anywhere on the path is the restore/backup copy
block, whose two arrays read **-1 on all sixteen tracks across 468 bursts** --
it migrates a voice's LFO phase when a voice changes hands, and in steady state
it correctly does nothing.

**No voice index survives anywhere in the CPU path.** The DSP is handed sixteen
per-track records and does voice assignment itself, so the coupling the owner
measured is **downstream of the ColdFire** -- on the SHARC, or in how a voice
picks up its track's record.

## What this cost, and the one thing that prevented it costing more

Two builds were flashed with the probe reading `block - 34 + 2*slot`, seventeen
slots low. Both returned a flat value across 468 bursts with `probe_a` reading
99 throughout -- an honest channel reporting a real number from the wrong
address. **"LFO4 never writes to its destination" was one message from being
written down here as a finding.**

What stopped it was the owner setting **LFO1** -- stock, known-good -- on the
same destination. It did not move either. *A known-good source showing nothing
means the instrument is wrong, not the source.* That is
`run-a-control-beside-a-negative` applied **before** the conclusion rather than
after it, for the first time in this project, and it is the reason this section
says what it says.

## Next

The hunt moves to the SHARC (`docs/sharc-*.md`), and to whatever hands a voice
its track's record. **Nothing further about the voice gate should be read into
ColdFire code** -- four stages of it are now measured and all four are
track-indexed.

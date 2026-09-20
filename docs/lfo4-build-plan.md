
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

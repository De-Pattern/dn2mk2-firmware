
# LFO4 — the build plan

**Written 2026-09-16**, consolidating one session's reading against the owner's
instruction to crack five named pieces. It supersedes nothing; it collects what
`lfo4-feasibility.md`, `lfo4-slot-plan.md` and `modulation-matrix.md` establish
and adds what was read today.

**Read the honesty note in §7 before pricing anything from this.** Three of the
five pieces are designed to the instruction; two are not finished.

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

### The edit

LFO4 does **not** need a renumbered page. Keep LFO1–3 at `0x1a`–`0x1c` and give
LFO4 the next free id; `0x1f` is free and already used by the probe builds.

`MidiParameterSet`'s predicate `0x400dbfbc` owns `0x16`–`0x1c`, the range that
contains the LFO pages. Widening it contiguously to `0x1f` would swallow `0x1d`
(Retrig) and `0x1e` (None). **`TrigParameterSet` shows the shipped alternative**
— an exact-match disjunct:

```
0x400dbfa0  moveq #29,%d1          ; page == 0x1d ?
0x400dbfa2  movel %a0@(0,%d0:l),%d0
0x400dbfa6  cmpl %d0,%d1
0x400dbfa8  beqs <yes>
0x400dbfaa  moveb #22,%d1          ; else page == 0x16 ?
```

So the form is proven to compile and run in Elektron's own code, on this exact
predicate family. **The LFO4 edit is the same shape applied to `0x400dbfbc`**:
keep `(page - 22) <= 6`, add `|| page == 0x1f`. `0x400dbfbc` is 34 bytes and has
one direct caller outside its own vtable body, so this is a **cave**, not an
in-place edit — there is no slack for the extra compare.

**Open:** whether the other predicate cascades (`0x40064e90`/`0x40064f14`, and
the seven-call `0x40067xxx` cluster) need the same treatment. Each has to be
read; they are not assumed to share the shape of `0x40041a72`.

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

## 4. Serialization — **located and sized, not designed**

Two functions, both 16-track loops over per-track records.

`0x400ddc52` gates on a version and a magic before doing anything:

```
0x400ddc70  cmpl %a2@(4),%d0        ; version == 4
0x400ddc78  movel #0xBACEF00C,%d1
0x400ddc7e  cmpl %a2@(10411),%d1    ; magic at +10411
```

then copies 16 words from `%a2@(0x1c)` to `%a3@(0x0e)` (clamped at 32512), then
loops 16 tracks:

```
0x400ddd0c  addil #1163,%d3         ; destination stride
0x400ddd12  addil #359,%d4          ; source stride
0x400ddd1a  cmpl %d2,%d0            ; %d0 = 16
```

**Per track: 359 bytes in the stored form, 1,163 in the live form.**

**Why this piece is not finished.** DNX's format work says the stored sound
already reserves the fourth-LFO slots — offsets 36, 44, 52, 60, 68, 76, 84, 92
in the `30 + 8*parameter + 2*lfo` grid — so **the persisted format needs no
version bump**. What has *not* been done is tracing which of the two functions
above writes that grid, and where in the 359-byte record it sits. Until that is
read, the hook is not designed, and "LFO4's values do not survive a save" is
exactly the failure mode the slot plan warned about.

**Next, concretely:** read `0x400dd1ea` and `0x400e7e66` — the two per-track
callees of the loop above — and locate the sound-object copy inside them.

---

## 5. The page view — **one good finding, not a design**

`LfoPageView` is real and RTTI names it: typeinfo `0x402054a8`, primary vtable
`0x40205614`, constructor `0x4010e322`, called from exactly one site
(`0x4019fb0c`) which builds **one** instance behind a reference-counted handle.

**There is one `LfoPageView`, not three.** So a fourth LFO page needs **no new
view class** — the existing view already serves all three LFO pages and must
take the LFO index from context.

**What is missing:** where that index comes from. Two `cmpil #26` sites
(`0x401783b0`, `0x40178402`) were the obvious candidates and were **checked and
ruled out** today — they follow `lsrl #8` and are character-range tests in a
drawing routine, nothing to do with pages. The page→LFO mapping is still
unlocated, and `[MOD]` key navigation has not been looked at at all.

---

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
8. Serialization hook — **after §4 is read**.
9. Page view + `[MOD]` navigation — **after §5 is read**.

Steps 1–7 are specified to the byte or to a named cave. **8 and 9 are not.**

---

## 7. The honest state, against the five named pieces

| # | piece | state |
|---|---|---|
| 5 | classifier | **designed** — mechanism read, edit specified, cave form proven in shipped code. Other cascades unread |
| 2 | tick edit | **designed** — both loops decoded, four edits named, state relocation forced and sized |
| 1 | slot space | **designed** — route chosen, bound found to be a `moveq`, extension array unchanged from the slot plan, 11 hooks listed |
| 3 | serialization | **located, not designed** — the two loops and their strides are read; which one writes the sound grid is not |
| 4 | page view | **one finding** — a single shared `LfoPageView`, so no fourth class is needed; the page→LFO mapping and `[MOD]` navigation are unlocated |

**Nothing here has been built, and nothing has been flashed.** Three of the five
are specified to the point where code can be written against them. Two are not,
and saying otherwise would repeat the mistake that cost three flashes: a cost
model published ahead of the reading that supports it.

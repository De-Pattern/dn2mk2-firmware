# The modulation matrix: six sources, four destinations each, and who they are

`docs/engine-state.md` established that modulation is generated **and** applied
on the ColdFire, that `0x400db1dc` is the MAC kernel and `0x400db22c` drives it
for **six sources × four destinations × sixteen tracks**, and closed with the
obvious question:

> **Six sources, and the UI offers three LFOs.** What the other three are is
> *not established* and is the obvious next question: if any of the six is
> unused, or is something a fourth LFO could take over, LFO4 has a home with no
> structural change at all.

It also warned, correctly:

> **Do not assume the three spare are free.** Velocity, aftertouch, mod wheel
> and the envelopes are all candidates.

**2026-09-15 — the warning was right and the hope is dead.** The six are the six
MIDI **performance** modulators. Every one is in use. None is an LFO, and none
is free.

| # | Source | Value table | Descriptor list | Index |
|---|---|---|---|---|
| 1 | **VELOCITY** | `0x8000dd40` | `%a2@(3476)` | by track (`%d3` = 2·track) |
| 2 | **MOD WHEEL** | `0x8000de40` | `%a2@(3492)` | by `%d4` |
| 3 | **PITCH BEND** | `0x8000de20` | `%a2@(3508)` | by `%d4` |
| 4 | **BREATH CONTROLLER** | `0x8000de00` | `%a2@(3524)` | by `%d4` |
| 5 | **AFTERTOUCH** | `0x8000dde0` | `%a2@(3540)` | by `%d4` |
| 6 | **KEY TRACKING** | `0x8000dda0` | `%a2@(3556)` | by track, long stride 4 |

The pairing of a **name** to a **row** is firm for row 1 and for the set as a
whole; the name-to-row assignment of rows 2–5 is **ordered by the registration
sequence and not otherwise proved** — see "What is measured and what is
ordered", below.

## The evidence

**1. Five names sit in one contiguous run of the string pool**, at
`0x4021560e`, immediately before `Sound::updateMirror`:

```
MOD WHEEL   PITCH BEND   BREATH CONTROLLER   AFTERTOUCH   KEY TRACKING
```

GCC emits string literals in source order, so these five are neighbours in the
`Sound` translation unit — and `Sound::updateMirror` is the function
`docs/lfo4-slot-plan.md` already identified as the control→engine path.

`VELOCITY` is the sixth and lives apart, at `0x40215ad2`, beside `VelParam` and
`5ValueIN9Digisharc10velParam_tEE` — it has its own storage type, which is why
its literal is in a different unit.

**2. Six objects are registered, and five of them are named in that order.**
`0x4004c712` onwards calls one function (`0x4018d006`) on six values held in
`%d7 %d6 %d5 %d4 %d3 %d2`, then attaches a name to five of them:

```
0x4004c756  pea 0x4021560e   MOD WHEEL           ... %d6
0x4004c77a  pea 0x40215618   PITCH BEND          ... %d5
0x4004c790  pea 0x40215623   BREATH CONTROLLER   ... %d4
0x4004c7aa  pea 0x40215635   AFTERTOUCH          ... %d3
0x4004c7c4  pea 0x40215640   KEY TRACKING        ... %d2
```

`%d7` — the first registered and the only one left unnamed here — is Velocity,
which is named in its own unit.

**3. Six `*SetupView` classes exist, one per source.** From the RTTI at
`0x40219fc2`:

```
KeyTrackSetupView  BreathSetupView  ModWheelSetupView
PitchBendSetupView  AfterTouchSetupView  VelocitySetupView
```

Six sources in the engine, six setup views in the UI, six names in the string
pool. This is what the instrument presents: each of these pages offers **four
destination + depth pairs**, which is exactly the four descriptors the kernel
walks.

**4. Row 1 is pinned independently.** `0x40026ac0` writes `0x8000dd40` — source
1's table — from a byte read at note time, scaled `lsl #8`, offset and clamped
to `0..32512`:

```
0x40026a8c  moveb %a2@(3),%d0        ; the trig's byte
0x40026a96  mvsb %a0@(1152),%d0      ; or the track default
0x40026a9e  lsll #8,%d0
0x40026aa0  addl %fp@(-128),%d0
   ... clamp to 0 .. 32512 ...
0x40026ac0  movew %d0,%a0@(0,%d2:l:2)    ; 0x8000dd40[track]
```

A per-trig byte, per-track default, set at note time, clamped to a 7-bit range
scaled by 256. **That is velocity**, and it is the one row that is indexed
directly by track rather than through `%d4`.

## The descriptor format

Each source's descriptor list is **four longwords**, and the kernel at
`0x400db1dc` consumes them two fields at a time:

```
0x400db1f2  movel %a1@+,%d2                    ; one descriptor longword
0x400db1f4  mvsw %d2,%d3                       ; low word  = DESTINATION INDEX (signed)
0x400db1f6  msacw %d1l,%d2u,%a1@+,%d2,%acc0    ; high word = DEPTH; acc0 -= value x depth
0x400db1fa  mvzw %a0@(0,%d3:l:2),%d4           ; read the parameter at that index
   ... swap, bias, saturate, rescale ...
0x400db21a  movew %d4,%a0@(0,%d3:l:2)          ; write it back, modulated
0x400db21e  subql #1,%d0 / bgts                ; moveq #4 -- four per source
```

So one descriptor is:

| bits | field |
|---|---|
| 31–16 | **depth**, signed |
| 15–0 | **destination**, a signed parameter index into the 1..99 space |

and the kernel's arguments are `(value_array_base, value, descriptor_list)`,
pushed in that order.

The kernel is reached as `lea %pc@(0x400db1dc),%a3` / `jsr %a3@`, which is why a
direct-call scan reports zero callers for it. Source 6 is not called at all —
`0x400db2bc`–`0x400db30c` is the same kernel **inlined**, reading its value as a
longword from `0x8000dda0` with `asrl #8` and a `-15360` bias.

## Where the lists live, and whether a seventh fits

Inside `0x400db22c` two different strides advance together:

| register | role | stride per track |
|---|---|---|
| `%d2` | value array base (`%a2 + 34` at entry) | **202** — 101 words |
| `%a2` | descriptor record base | **153** |

So for a base `B`:

- **value arrays**: `B + 34 + 202·t`, sixteen of them, ending at `B + 3266`
- **descriptor records**: `B + 3476 + 153·t`, sixteen of them, ending at `B + 5924`

`B` is what `0x400db12a` returns when handed `0x80003af0`, so the whole
structure sits in the engine's SDRAM state and its last byte is near
`0x80005234` — just below `0x80005308`, the sixteen-entry array the `%d4` index
is read from.

**Six lists occupy 96 of the 153 bytes**, `3476` to `3572`.

The record does **not** begin at 3476, though. The frame builder at `0x400274ba`
reads three bytes per track from the same 153-stride array at **3468, 3469 and
3470** — just below the descriptor lists — and puts them in the DSP frame:

| frame slot | source |
|---|---|
| `%a3@(82)` | record `+3470`, byte, sign-extended |
| `%a3@(146)` | record `+3468` |
| `%a3@(178)` | record `+3469` |

So the record's *known* extent runs at least `3468..3572` — **104 of 153
bytes**, leaving **no more than 49 unaccounted for**, not 57. The three bytes
are unidentified; they are per-track, byte-wide, and go straight to the DSP.

> **This is slack, not free space.** `0x400db22c` not reading bytes 96–152 of the
> record proves only that *this* function does not. Nothing here shows the
> remainder is unused, and the scan for instructions bearing the displacements
> `3572`/`0xdf4` found no reader, which is a weak negative of exactly the kind
> `docs/PRINCIPLES.md` §19 is about — the descriptor lists themselves have **no
> such reader either**, because they are reached through the record pointer, not
> a literal displacement. Before anything is appended here, find the record's
> constructor and read its size.

## What is measured and what is ordered

Stated plainly, because the temptation to over-read this is real:

| Claim | Status |
|---|---|
| The six sources are Velocity, Mod Wheel, Pitch Bend, Breath, Aftertouch, Key Tracking | **Measured** — three independent signals (string run, registration sequence, six setup views) |
| None of the six is free | **Follows** — all six are named, live instrument features |
| Row 1 = Velocity | **Measured** — the note-time write at `0x40026ac0` |
| Rows 2–5 = Mod Wheel, Pitch Bend, Breath, Aftertouch **in that order** | **Ordered, not measured.** The registration sequence and the table order agree, and nothing contradicts them, but no single row of 2–5 has been pinned the way row 1 has |
| Row 6 = Key Tracking | **Ordered** — last registered, and it is the one source read as a longword per track, which suits a continuous per-track quantity |
| The descriptor format is `depth:s16 << 16 \| dest:s16` | **Measured** — from the kernel |
| At most 49 bytes of the 153-byte record are unaccounted for | **Measured** — and the first draft of this document said 57, before the frame builder was read and found using `+3468..+3470`. The number only ever moves down |
| Those bytes are available | **Not established** |

To pin rows 2–5 individually: find the MIDI CC handler that writes `0x8000de40`
/ `0x8000de20` / `0x8000de00` / `0x8000dde0` and read which controller number
reaches each. That is the same move that pinned row 1, and it has not been done.

## What this means for LFO4

The hopeful branch — *one of the six is spare, take it over* — **is closed.**

Three things survive it.

**1. There is a fallback route, and it is only a fallback.** LFO4 could be built
as a **seventh modulation source**: a value the ColdFire computes per track per
frame, dropped into a 16-word table, with a four-entry descriptor list the
existing kernel already knows how to apply. The apply side would cost *nothing
new* — no hook into the 29 value-array sites, no parameter-set table growth, no
slot problem.

> **The owner's decision, 2026-09-15: the goal is a real fourth LFO** — one that
> behaves like LFO1–3, appears as a fourth page under `[MOD]`, and is saved with
> the sound. *"Any other path is ok if we cannot solve properly how to add it as
> a fourth LFO."*
>
> So the seventh-source design is **held in reserve**, to be taken only if the
> real thing proves unreachable. It is written down here so it is not
> rediscovered, not because it is the plan. Note what it would cost: a seventh
> source is track-level, so **LFO4 would not be stored in a preset** — the same
> price `docs/lfo4-slot-plan.md` names for its track-level design, and the
> reason that design was never chosen either.

**2. The generator is now the only engine-side unknown** — and the search space
for it is much smaller than it was this morning. See below.

**3. The per-track modulated-parameter bitmap has 27 spare bits.**
`0x400db052` clears **four longwords** at `0x4664b26c + 16·track` — 128 bits —
and `0x400db092` sets bit `index & 31` of word `index >> 5`. The parameter index
space runs 1..99. So **indices 100–127 are already representable** in the
structure that tracks which parameters are modulated, at no cost. That is a
direct, independent corroboration of `docs/lfo4-slot-plan.md`'s option 1
("extend the space past 99 and put LFO4 at 100–107"), from a structure that
plan never looked at.

## The parameter-set path, found on the way

`0x400db092` is worth naming because it is the generic **"apply a list of
(index, value) pairs to one track"** routine, and it is what a parameter lock
must go through.

Given a track number, a list at `%a2@(20)` of `%a2@(8)` entries, 8 bytes each:

| entry field | use |
|---|---|
| `+0` u16 | **parameter index** |
| `+2` u16 | **value** |

for each entry it

1. sets bit `idx & 31` of longword `idx >> 5` in the per-track 128-bit bitmap at
   `0x4664b26c + 16·track` — *this parameter is now set*;
2. writes the value into the track's word array at `+2 + 2·(idx + 10 + 101·track)`
   of a caller-supplied base;
3. writes `value << 16` into the longword array at
   `0x8000de60 + 4·(101·track + 17 + idx)`.

`0x400db072` is the single-parameter form of the same thing, and `0x400db052`
clears one track's bitmap.

So `0x8000de60` holds each parameter's value as a **32-bit fixed-point base**,
one per parameter per track, which is what the MAC kernel's `swap` / bias /
saturate arithmetic is operating in.

**Everything in this routine is keyed on a parameter index in 1..99.** The six
modulators' destinations and depths are *not* in that space — they live in the
per-track descriptor records at `+3476`. See `docs/ideas-backlog.md`, "P-locking
the performance modulators", for what follows from that.

---

## Where the LFO tick is not

Searching for it is what produced most of this document, so the ground already
covered is worth recording — a later session should not re-walk it.
`docs/PRINCIPLES.md` §19 applies throughout: these are negatives, and each is
only as good as the instrument that produced it.

### The parameter-value module, `0x400daed2`–`0x400db32e`, is fully read

It is one coherent module and **none of it is an LFO**:

| Entry | What it does |
|---|---|
| `0x400daed2` | bulk-set: write *n* words into `0x8000de60` as `value << 16` |
| `0x400daf16` | set one parameter's base value |
| `0x400daf44` | walk the per-track 128-bit bitmap; for each set bit, **clear it** and restore that parameter |
| `0x400dafdc` | the same walk over a second bitmap at `0x4664b36c` |
| `0x400db052` | clear one track's bitmap |
| `0x400db072` | set one parameter: value into the array, `value << 16` into `0x8000de60` |
| `0x400db092` | **apply a p-lock list** — `(u16 index, u16 value)` pairs |
| `0x400db12a` | resolve the per-track record base from `0x80003af0` |
| `0x400db1dc` | the MAC kernel |
| `0x400db22c` | the six-source apply |

Every reference to `0x8000de60` (7 sites) and to the bitmap at `0x4664b26c` (3
sites) is inside it. **The module's whole surface is accounted for.**

### Its callers are the trig handler, not a tick

`0x400db052`, `0x400db072`, `0x400daf44` and `0x400db092` have **exactly one
direct caller each**, and all four sit in one function around `0x40026b40` —
the note/trig handler. It reads a trig descriptor and passes its lock list at
`+0x54` to `0x400db092`. So that path is **parameter locks**, confirmed, and
it runs per trig rather than per frame.

### The per-frame ISR's whole call list has been enumerated

`0x40025e0a` — the DSP-frame ISR — calls fifteen distinct addresses. Six of them
(`0x4002b1f4`, `0x4002b22e`, `0x4002b246`, `0x4002b256`, `0x4002b270`,
`0x4002b282`) are **trivial per-track table getters**, four instructions each.
The rest are the parameter store, the frame builder, and the SPI send. **No LFO
generator is called from the frame ISR.**

### The DSP frame's contents are now fully named

`docs/engine-state.md` listed seven word-arrays written through `%a3` without
saying what they carried. They are:

| frame slot | source |
|---|---|
| `%a3@(0)` | `0x8000dd60[track]`, longword, `asr #8` |
| `%a3@(50)` | `0x8000dd40[track]` — **Velocity**, the same table source 1 reads |
| `%a3@(82)` | record `+3470` |
| `%a3@(114)` | `%a2@(2·track)` |
| `%a3@(146)` | record `+3468` |
| `%a3@(178)` | record `+3469` |
| `%a3@(2648)` | a longword from a fourth per-track table, truncated to a word |

plus the four block copies of indices 25–99. **Nothing in the frame is an LFO
parameter or an LFO output**, which is a second, independent confirmation of
`docs/engine-state.md`'s central result, arrived at by enumerating the frame
rather than by converting block offsets to indices.

### So where to look next

Not in the audio frame. The DN2's LFOs are tempo-syncable, which points at the
**sequencer clock**, not the audio ISR. Three concrete moves, cheapest first:

1. **Follow `SPD`'s formatter backwards.** `docs/modulation-mask.md` has the
   parameter records and their `+0x34` formatters; LFO `MULT`'s computes
   `1 << v`. At runtime the phase increment must be `SPD × (1 << MULT)`. Find a
   variable shift by a value sourced from the LFO block.
2. **Find the phase accumulators.** Sixteen tracks × three LFOs = 48 of
   something, and the state must persist between ticks, so it is in SDRAM near
   the other engine state, not in BSS.
3. **Start at note-on instead.** `MODE` (`FRE`/`TRG`/`HLD`/`ONE`/`HLF`, strings
   at `0x40210bea`) and `SPH` mean the trig handler must reset LFO phase. The
   trig handler is already located, at `0x40026b40`. **This is probably the
   shortest route** — it is a known function that must touch LFO state.

### Found on the way: MOD1–3 are three `std::function` objects in BSS

Chasing the tick through the `MOD1`/`MOD2`/`MOD3` filter constants
(`docs/modulation-mask.md`) did not find it, but it did find how the three
modulators are *registered*, which a real fourth LFO has to join.

Three near-identical thunks exist, each supplying its own filter and tail-jumping
to one shared implementation:

```
0x400c2a90   movel #0x1e00,%sp@(12) ; braw 0x400c2894     MOD1
0x400c2aae   movel #0x0e00,%sp@(12) ; braw 0x400c2894     MOD2
0x400c2acc   movel #0x0600,%sp@(12) ; braw 0x400c2894     MOD3
```

Each thunk's address is written into BSS at boot, around
`0x42431d48`–`0x42431d84`, alongside one of three sibling functions at
`0x400c0238`, `0x400c028a` and `0x400c02dc` — 82 bytes apart, and each a GCC
`std::function` **manager** (`op 0` destroy, `1` clone, `2` allocate, `3`
destroy-and-deallocate, with a typeinfo pointer at `0x401f2530`).

So **`MOD1`, `MOD2` and `MOD3` are three `std::function` objects**, each a bound
call to `0x400c2894` carrying its own filter. They are *not* an array of three
LFOs and there is no count-of-three to increment — but they *are* a uniform
registration, built by one initialiser, which is the next best thing.

**What a fourth would cost, on this evidence alone:** an invoker thunk of about
twenty bytes (`movel #0x0200,%sp@(12)` / `braw 0x400c2894`), the same manager
shape, and a slot in the BSS run. `0x0200` is the filter
`docs/modulation-mask.md` already showed is the only one left and admits exactly
what a fourth LFO needs. **None of this is the generator** — it is the
destination-menu identity — but it is the first piece of a real fourth LFO whose
cost has been counted rather than estimated.

**A false positive worth recording.** A scan for a three-entry table of the
filter constants reported a hit at `0x401f2b4d`. It is not one: the address is
odd, and the surrounding longwords read `0, 6, 14, 30, 38, 46, 62, 78, 94, 110`
— an unrelated offset table whose bytes happen to contain the pattern. Checking
alignment before believing a table cost one command.

### RETRACTED: "the parameter-value module is read end to end"

**2026-09-15, after installing digikit's `ColdfireEMAC` Ghidra language.** The
section above claimed the modulation module `0x400daed2`-`0x400db32e` was read
end to end, ten entry points tabulated, and that the frame ISR's call list was
enumerated. **Both were wrong, and wrong the same way.**

**The ISR is not where this document said it was.** `dnfw fn entry` attributed
`0x40026b40` to `0x40025e0a` -- and printed its own caveat that the attribution
is a guess for functions not reached by a direct call. It was a guess, and a bad
one: `0x40025e0a` is a **44-byte** function. The real handler is
**`FUN_40025e36`, 7,582 bytes**, which is what `docs/engine-state.md` said in
the first place.

**Its call list is 73 functions, not 15.** The earlier enumeration scanned for
`jsr (xxx).L` only, so it missed every `bsr` and every indirect call -- and the
modulation kernel itself is reached as `lea %pc@(...),%a3` / `jsr %a3@`, which
the same document points out. A scan that cannot see the call form it had
already documented is not an enumeration.

**Seven functions in the module were never read**: `0x400dae1c`, `0x400db524`,
`0x400db640`, `0x400db72a`, `0x400db798`, `0x400db7d8`, `0x400db800`. Six of
them sit **above** `0x400db32e`, where reading stopped because the incomplete
call list gave no reason to look further.

This is `docs/PRINCIPLES.md` §19 for the third time today, and the sharpest
instance yet: **an instrument that cannot see a call form invents a module
boundary, and everything downstream inherits it.**

### What is in the unread part: a 16-slot ramp-and-timer pool

`0x400db72a` walks an array from `0x42c645e8` to `0x42c647a8` -- **448 bytes,
stride 28, sixteen elements** -- and per element:

```
+4   remaining time      countdown
+8   accumulator         += (global_elapsed * rate) >> 2, CLAMPED at 0x7fffffff
+12  rate
```

```
0x400db746  movel 0x402a0dec,%d1    ; elapsed time this tick, a global
0x400db750  mulsl %a0@,%d1          ; x rate at +12
0x400db754  asrl #2,%d1
0x400db756  addl %d1,%a2@(8)        ; accumulate
0x400db75e  cmpil #2147483647,%d1   ; and SATURATE
...
0x400db776  cmpl %d0,%d1            ; elapsed vs remaining
0x400db77c  movel %d0,%a2@(4)       ;   still running: decrement
0x400db788  jsr %a3@                ;   expired: call 0x400db4ac(element)
0x400db78c  lea %a2@(28),%a2
```

`0x400db524` and `0x400db640` index the same array by `descriptor@(16)`, using
`(x << 5) - (x << 2)` = **x × 28**, confirming the stride independently.

**This is not the LFO tick.** An LFO phase *wraps*; this **clamps** at
`0x7fffffff` and fires a callback when a countdown expires. That is a ramp with
a deadline -- a fade, a slew, a portamento or a scheduled event -- not an
oscillator. Sixteen slots also fits one-per-track rather than the forty-eight a
per-track LFO1-3 would need.

So it is **not the answer, and it is the first structure found in the right
module by an instrument that can see the whole module.** The remaining unread
functions are `0x400dae1c`, `0x400db798`, `0x400db7d8`, `0x400db800`, and the
expiry callback `0x400db4ac`.

### The rest of the module, read — and there is no oscillator in it

**2026-09-15, continued after a reboot.** The five functions left unread above
are now read. **None is an LFO.** With them the module is complete, and this
time the claim rests on Ghidra's resolved call graph under the `ColdfireEMAC`
language, not on a `jsr (xxx).L` scan.

| Entry | What it does |
|---|---|
| `0x400db4ac` | **expiry callback** for the 16-slot pool: if `+20` holds a handle, release it through `0x40138a0c` and clear it; clear the countdown at `+4` |
| `0x400db4ce` | **post a type-6 event for a track**: allocate via `0x401389d6`, set `obj[0]=6`, `obj[16]=track`, `obj[24]=pool[track]+0`, and schedule it at `time + 90000` through `0x40138b5c` |
| `0x400db798` | "is this descriptor still current": if bit 18 of `desc+56` is set, compare `pool[desc+16]+0` against `desc+24` while that slot's countdown runs |
| `0x400db7d8` | if a track's countdown has gone **negative**, fire the expiry callback |
| `0x400db800` | `pool[track]+24 = value` for track 0..15, **with interrupts masked** (`move #0x2700,%sr`) |
| `0x400dae1c` | three global housekeeping countdowns at `0x80005354`, `0x80005358` (step `2 × elapsed`) and `0x8000535c` (step 1), each firing a handler at zero |
| `0x400dae98` | load one track's **101 base values** into `0x8000dea4 + 808·track` as `value << 16` — the bulk-set path, consistent with the `101·track + 17` indexing above |

So the 16-slot pool at `0x42c645e8` is a **per-track event timer**: bounded to
tracks 0–15, holding a handle that is released on expiry, and scheduling
type-6 events 90,000 ticks out. That reads as **note gate or retrig timing**,
not modulation. It is in this module because it shares the trig-handler
descriptor (`+16` track, `+24`, `+56` flags) — not because it modulates.

### What this now establishes about the tick

**The LFO oscillator is not in the modulation module and is not called from it.**
The module is: the six-source apply, the p-lock apply, the base-value store, the
modulated-parameter bitmap, and a per-track event timer. Nothing in it wraps a
phase.

That narrows the search, honestly this time. The frame ISR `FUN_40025e36` has
73 resolved callees; the module accounts for sixteen of them, and the SPI send,
memset and block copy for three more. The remaining unread callees sit in
`0x40029bca`–`0x4002a6a2` and `0x4002b06e`–`0x4002b1b6`, next to the ISR — or
the tick does not run in the audio frame at all and lives on the sequencer
clock, which the DN2's tempo-synced LFOs would make unsurprising.

**The next search should be for the oscillator's signature, not by reading
functions one at a time:** a phase that **wraps** rather than clamps, fed by
`SPD` and `MULT` — which sit at `track_base + 36` and `+38` for LFO1, and
`+16·lfo` further for LFO2 and LFO3.

### Leads closed on the way to the tick, 2026-09-15 (evening)

Recorded so a later session does not re-walk them. Each is a negative from a
named instrument -- a whole-image objdump text export of MAIN OS 1.11 up to
`0x401f0000`, 640,982 instructions, searched rather than read by hand.

**The only PRNG constant in the image is glibc's.** `0x40150670` is `rand()`:
`seed = seed * 1103515245 + 12345`, return bits 16-30. Its family sits beside it
-- `0x4015069e` combines two draws into 32 bits, `0x401506ba` is `srand`,
`0x401506c6` burns 100,000 draws. `0x40150694`, a signed `rand() >> 8` that
would suit an `RND` wave, **has no direct callers**.

**`rand()`'s twelve callers are not an LFO.** `0x400c26b4`, `0x400c271e` and
`0x400c0aa6` scale `rand() % 32767` into a parameter's `[min, max]` and round to
`& ~0xff` -- the **parameter randomiser**. `0x400d3314` draws two distinct
indices from a table at `0x4028c1c0`. So an `RND` LFO, if it is on the ColdFire,
uses a different noise source -- or is reached indirectly, which a text search
cannot see.

**`0x400c2894`, the implementation all three MOD thunks jump to, is UI.** It
builds the destination list through `0x4003951e` and searches it for the
current `DEST`. Consistent with the MOD1-3 `std::function`s being the `[MOD]`
page's destination menu, as recorded above.

**The two clusters of indexed parameter writes are storage helpers.**
`0x4013c972` and `0x4013c9a0` write a value as a word or a long by a type code
(2 = long, 3 = word); the larger functions at `0x4013d16e`, `0x4013e7c2`,
`0x401464f6` and `0x401498aa` hold the rest of that cluster and were not read.

**Seven waveform-sized switches exist** (bound 6, then a pc-indexed jump), at
`0x4001210a`, `0x40017c12`, `0x4007032c`, `0x400708de`, `0x400ffe58`,
`0x40113974`, `0x40120ba0`, `0x40129df8`, `0x4016fd74`. None is yet tied to
`WAVE`.

**Frame-ISR callees not yet read, triaged by what they do.** The arithmetic ones
are `0x4002a6a2` (1,330 B: adds into memory, variable shift, multiply),
`0x4002a0bc` (746 B), `0x40029cd4` (722 B), `0x40003d00` and `0x40003118` --
all working on BSS at `0x4058xxxx`/`0x4059xxxx`.

### The owner's lead: follow the tempo

> *"the tick should be somehow linked to the tempo parameter"*

Right, and a better anchor than reading functions: the DN2's LFO `SPD` is
**tempo-synced**, so the phase increment must be built from the project BPM.
Whatever reads the tempo and multiplies it by something per track is either the
tick or feeds it.

### Two more closed, and the clock located

**`0x4002a0bc` is the arpeggiator step, not an LFO.** Called from the trig
handler with the track, it keeps per-track state at `0x4059c8a8 + 40·track`,
walks note bitmaps at `0x40598728` in modes 1-3 (up, down, up-down via
`3 - index`), advances an octave counter at `+28` that wraps at the sound's
`+353`, gates each step through a 16-bit mask at the sound's `+356`, adds a
per-step offset from `+358`, and returns a note number. The `#2880` the trig
handler stores into `0x4058e918[track]` beside it is a per-track note-on
initial value, not a tempo read.

**The frame time step is written in one place.** `0x402a0dec` -- the elapsed
time the event-timer pool and the housekeeping countdowns advance by -- has
**exactly one writer**, `0x4013707c`, inside a clock module around
`0x4013706a`-`0x401373b0` that also maintains a flag word at `0x402a0df0` and
values at `0x402a0df4`, `0x402a0df8` and `0x402a0dfc`. Nine functions read the
step: the frame ISR `0x40025e36`, the timer pool `0x400db524`/`0x400db72a`,
housekeeping `0x400dae1a`, the writer itself, and four not yet read --
`0x400257fa`, `0x400d7f06`, `0x40129130` and `0x401383ac`.

Following the owner's lead: a free-running LFO must add elapsed time to its
phase and a tempo-synced one needs a tempo-scaled step, so the tick either
reads `0x402a0dec` or reads something computed from it and the BPM in that
clock module.

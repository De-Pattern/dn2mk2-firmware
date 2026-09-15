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

**Six lists occupy 96 of the 153 bytes.** `3476 + 6·16 = 3572`, and track 1's
record begins at `3476 + 153 = 3629`. That leaves **57 bytes per track that this
function never touches** — room for three more descriptor lists.

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
| 57 bytes of the 153-byte record are unread by `0x400db22c` | **Measured** |
| Those 57 bytes are available | **Not established** |

To pin rows 2–5 individually: find the MIDI CC handler that writes `0x8000de40`
/ `0x8000de20` / `0x8000de00` / `0x8000dde0` and read which controller number
reaches each. That is the same move that pinned row 1, and it has not been done.

## What this means for LFO4

The hopeful branch — *one of the six is spare, take it over* — **is closed.**

Three things survive it, and two of them are better than the question that died.

**1. LFO4 does not have to be a fourth LFO.** It can be a **seventh modulation
source**: a value the ColdFire computes per track per frame, dropped into a
16-word table, with a four-entry descriptor list the existing kernel already
knows how to apply. The apply side then costs *nothing new* — no hook into the
29 value-array sites, no parameter-set table growth, no slot problem. This is
the "track-level design" of `docs/lfo4-slot-plan.md` arriving by a different
road, and the engine turns out to have been built for it.

What it still needs: a generator, a place for the descriptor list, and UI.

**2. The generator is now the only engine-side unknown.** Where LFO1–3 are
advanced and applied is **still not found** — it is not in this matrix, and the
matrix is the only per-frame modulation apply we have read. Either the LFOs run
through a separate path, or they reach the parameter array by another route
entirely. That is the next question, and it is smaller than the one it replaces.

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

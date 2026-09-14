# The FX parameter index space, and where the enumeration gate actually is

`docs/ideas-backlog.md` §8 Tier A — p-locking and modulating the global FX
settings — has been blocked on one sentence: *"`FxSetup::updateMirror` writing
into `fxSetupStorage_v0_t`, a separate structure with its own index space."*
That named a blocker without describing it.

This file describes it. The unlock was **a known positive to calibrate
against**, which this project has now failed four detectors for want of.

## 1. The calibration

An independent SHARC+ write-up (`docs/sharc-crosscheck.md`) lists seven chorus
parameters with their **SHARC-side runtime indices**, derived from the DSP end
of the pipe — the opposite end from anything we had looked at.

Against the ColdFire parameter table this repository already extracts:

| their SHARC index | their name | our `id` | our name | difference |
|---|---|---|---|---|
| `0x1A` (26) | Depth | 25 | Depth | **+1** |
| `0x1B` (27) | Speed | 26 | Speed | **+1** |
| `0x1C` (28) | High-pass | 27 | High-pass | **+1** |
| `0x1D` (29) | Width | 28 | Width | **+1** |
| `0x1E` (30) | Delay Send | 29 | Delay Send | **+1** |
| `0x1F` (31) | Reverb Send | 30 | Reverb Send | **+1** |
| `0x20` (32) | Chorus Mix | 31 | Chorus Mix Vol. | **+1** |

**Seven for seven, in the same order, with a constant offset.** Two
independently derived index spaces do not line up like that by accident.

*Evidence level: binary fact on our side (the table is in the image), reported
fact on theirs. The correspondence is inference, but a strong one.*

## 2. What the calibration revealed: one flat space, not eight

Reading `id` as a per-page number is what hid this. The eight groups below form
**one contiguous run with no gaps and no overlaps**:

| group | page | ids | count |
|---|---|---|---|
| 26 | LFO1 | 1–8 | 8 |
| 27 | LFO2 | 9–16 | 8 |
| 28 | LFO3 | 17–24 | 8 |
| 16 | **Chorus** | **25–31** | 7 |
| 18 | Delay | 32–40 | 9 |
| 17 | Reverb | 41–48 | 8 |
| 21 | Ext-in | 49–59 | 11 |
| 20 | Master | 60–67 | 8 |

`1..67`, exactly. Every other group in the table reuses ids and belongs to a
different space — group 29 (Euclidean) runs 0–25 and overlaps LFO1's range, so
it is emphatically not the same numbering.

**What the run contains is the interesting part**: the three LFOs and the global
FX and Master blocks, together, in one numbering. Those are precisely the
objects that are *not* per-voice.

*Evidence level: binary fact. The ids are in the image and the run is arithmetic.*

### The predictions this makes

If the `+1` holds beyond chorus — untested, and the obvious next thing to ask
the write-up's author — then:

| page | predicted SHARC indices |
|---|---|
| LFO1 | `0x02`–`0x09` |
| LFO2 | `0x0A`–`0x11` |
| LFO3 | `0x12`–`0x19` |
| **Chorus** | **`0x1A`–`0x20`** — confirmed |
| Delay | `0x21`–`0x29` |
| Reverb | `0x2A`–`0x31` |
| Ext-in | `0x32`–`0x3C` |
| Master | `0x3D`–`0x44` |

*Evidence level: DSP interpretation. Falsifiable, and cheap to falsify.*

## 3. The gate, located

`docs/modulation-mask.md` established by hardware test that for global FX
parameters the gate is **the enumeration, not the mask** — Delay and Reverb
carry a full modulation mask that nothing in the instrument ever offers.

The enumeration walks 101 slots of a `ParameterSet` through vtable slot `+0x50`.
`FxParameterSet`'s implementation is `FUN_400dc0b0` (1.11), and it is eight
instructions:

```
0x400dc0b0  moveq #100,%d1              ; bound
0x400dc0b2  movel %sp@(4),%d0           ; slot
0x400dc0b6  cmpl %d0,%d1
0x400dc0b8  bccs 0x400dc0be
0x400dc0ba  clrl %d0                    ; out of range -> 0
0x400dc0bc  rts
0x400dc0be  lea 0x42c649a8,%a0          ; the table
0x400dc0c4  movel %a0@(0,%d0:l:4),%d0   ; return table[slot]
0x400dc0c8  rts
```

**The whole enumeration for FX is a 101-entry pointer table at `0x42c649a8`.**
A slot whose entry is null is not offered; a slot whose entry points at a
parameter record is.

*Evidence level: binary fact — this is the disassembly.*

## 4. Why it could not be patched, and what changes that

`0x42c649a8` **is in no section**. Measured against every section's load range:

| id | name | loads at |
|---|---|---|
| 5 | meta | `0x00000000` |
| 2 | bootstrap | `0x02010000` |
| 3 | MAIN OS | `0x40000400`–`0x4030b980` |
| 4 | updater | `0x80000400` |
| 7 | blob | SHARC boot stream |
| 8 | ? | ARM image |

`0x42c649a8` sits past the end of MAIN OS in the ColdFire's DDR. So it is **not
data we can edit** — which is where `docs/modulation-mask.md` stopped, calling
it "an open question".

It is built at runtime. `FUN_400dc4d0` — found by `ghidra/FindDataRefs.java`
after that tool was fixed — zeroes six tables and then fills them:

| table | bytes | pointers | likely owner |
|---|---|---|---|
| `0x42c64b3c` | 404 | **101** | `SoundParameterSet` |
| **`0x42c649a8`** | **404** | **101** | **`FxParameterSet`** |
| `0x42c64940` | 104 | 26 | — |
| `0x42c64d18` | 800 | 200 | — |
| `0x42c64cd0` | 72 | 18 | — |
| `0x42c647ac` | 404 | 101 | — |

404 = 101 × 4 corroborates the `moveq #100` bound from the other direction:
the table's size and the function's bound agree without either being derived
from the other.

**This moves Tier A from "blocked on unpatchable data" to "a code change in a
function we have located".** The table is unpatchable; the builder is ordinary
ColdFire code in section 3, and this project has a working cave mechanism and
has executed injected ColdFire code on hardware (`docs/flashing.md`,
2026-09-13).

*Evidence level: binary fact for the addresses, sizes and the clear-calls;
**DSP/structural interpretation** for which table belongs to which class — only
`FxParameterSet` → `0x42c649a8` is proven, by `FUN_400dc0b0` naming it.*

## 5. What is still not known

Stated plainly, because the temptation after a run like this is to call it done.

- **What fills the table**, and from what source. The builder's second half
  walks records at `0x401f7f94` with a 60-byte stride — the same stride as a
  parameter record — and writes into `0x42c64d18`. The fill for `0x42c649a8`
  specifically has not been read.
- **Whether adding an entry is sufficient.** A slot pointing at an FX record
  might be offered in the destination list and still not be *applied*, because
  the modulation writer may target per-voice storage. `docs/modulation-mask.md`
  §"What this does not yet tell us" already flags this, and it is untouched.
- **Whether the `+1` generalises** past chorus.
- **Where `0x401f7fb4`'s 320-record table sits** relative to the one at
  `0x401e29d4` that `dnfw params` finds. Both are 320 records of 60 bytes and
  they are 87,520 bytes apart, so there are at least two, and nothing here says
  which is which.

## 6. The lesson, for the fourth time

Four detectors in this project have failed for the same reason, and this is the
first time the fix arrived from outside:

| instrument | failed because |
|---|---|
| zero-crossing rate | no positive sample of real transients |
| byte-plane asymmetry | no positive sample; rewarded pointer tables |
| step autocorrelation | same |
| "second hit" strike counter | no control; counted decay bumps |

Each was fixed only by obtaining a **known positive** — Syntakt's shipped
`TRANSIENT 01-08.wav` for three of them, the owner's memory of the bank for the
fourth. Here the known positive was seven numbers from someone else's document,
and it took an afternoon to convert them into a located gate.

The cheapest thing this project can do, repeatedly, is find a case where the
answer is already known and check the instrument against it first.

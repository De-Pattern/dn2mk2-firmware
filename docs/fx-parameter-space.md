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

---

## 7. The author's reply, and what it settles

The write-up's author answered four questions on 2026-09-14. Three of the
answers change something here.

### The runtime index is an ordinal, not a stored field

They name the same descriptor series we found — **`0x401E4254`, stride `0x3C`** —
which is our parameter table at `0x401e29d4` (their base sits `0x20` into our
60-byte record). Their table lists, per parameter, a *logical id*, a *physical
control id* and a *runtime index*.

**No field in the record holds the runtime index.** Every halfword of Chorus
Depth's record was checked against `0x1A`; none matches. So the runtime index is
assigned by position, which is why `id + 1` works: both are ordinals over the
same ordered set.

Their note that a disabled record at physical `0x74` "does not shift the runtime
indices" confirms the ordering skips disabled entries — and our table does show
two records sharing parameter id 31, one of them carrying `0x74`.

### Two of our column names were wrong, and one was disprovable from our own data

| our old name | correct name | evidence |
|---|---|---|
| `controller` ("MIDI controller number") | **`logical_id`** | **122 of 285 records hold a value above 127.** MIDI controller numbers stop at 127. Checkable the day it was written; never checked. |
| `nrpn` | **`physical_id`** | their transport analysis only — nothing here disproves NRPN, and the values are in range |

Chorus Depth carries 297 = `0x129` and 110 = `0x6E`, exactly their logical and
physical ids. `src/dnfw/params/record.py` renames both and keeps the old names
as aliases.

### The compressed-size ceiling is self-imposed, and we are under it

> "The only exact ceiling I established is `600148` compressed payload bytes
> when preserving the stock ELE3 section geometry… I have not established
> `600148` as a hard limit imposed by the bootloader, flash partition, or file
> format."

Our packer produces **596,466** for 1.10E — 3,682 bytes under their ceiling —
so full recompression satisfies the constraint their token-level patcher was
built to respect. No section table edit, no moved HMAC, no rebuilt transport.

They also accept the match-window finding and intend to adopt the bounded offset
and match-length rules regardless, on the grounds that recovery-mode
compatibility is stricter than a successful normal update. That is the right
reading of it.

### Song mode is ColdFire-side

Confirmed by them: section 3 only, with 2, 4, 5 and 7 byte-identical to stock.
Nothing in it touched the SHARC.

## 8. The extrapolation to every FX parameter

Applying `runtime = id + 1` across the whole contiguous run:

| runtime | id | page | name | logical | physical | status |
|---|---|---|---|---|---|---|
| `0x02` | 1 | LFO1 | Speed | 170 | 79 | predicted |
| `0x03` | 2 | LFO1 | Multiplier | 171 | 80 | predicted |
| `0x04` | 3 | LFO1 | Fade In/Out | 172 | 81 | predicted |
| `0x05` | 4 | LFO1 | Destination | 173 | 82 | predicted |
| `0x06` | 5 | LFO1 | Waveform | 174 | 83 | predicted |
| `0x07` | 6 | LFO1 | Start Phase | 175 | 85 | predicted |
| `0x08` | 7 | LFO1 | Trig Mode | 176 | 86 | predicted |
| `0x09` | 8 | LFO1 | Depth | 177 | 87 | predicted |
| `0x0A` | 9 | LFO2 | Speed | 178 | 89 | predicted |
| `0x0B` | 10 | LFO2 | Multiplier | 179 | 90 | predicted |
| `0x0C` | 11 | LFO2 | Fade In/Out | 180 | 91 | predicted |
| `0x0D` | 12 | LFO2 | Destination | 181 | 92 | predicted |
| `0x0E` | 13 | LFO2 | Waveform | 182 | 93 | predicted |
| `0x0F` | 14 | LFO2 | Start Phase | 183 | 95 | predicted |
| `0x10` | 15 | LFO2 | Trig Mode | 184 | 96 | predicted |
| `0x11` | 16 | LFO2 | Depth | 185 | 97 | predicted |
| `0x12` | 17 | LFO3 | Speed | 186 | 99 | predicted |
| `0x13` | 18 | LFO3 | Multiplier | 187 | 100 | predicted |
| `0x14` | 19 | LFO3 | Fade In/Out | 188 | 101 | predicted |
| `0x15` | 20 | LFO3 | Destination | 189 | 102 | predicted |
| `0x16` | 21 | LFO3 | Waveform | 190 | 103 | predicted |
| `0x17` | 22 | LFO3 | Start Phase | 198 | 105 | predicted |
| `0x18` | 23 | LFO3 | Trig Mode | 199 | 106 | predicted |
| `0x19` | 24 | LFO3 | Depth | 200 | 107 | predicted |
| `0x1A` | 25 | Chorus | Depth | 297 | 110 | **confirmed** |
| `0x1B` | 26 | Chorus | Speed | 298 | 111 | **confirmed** |
| `0x1C` | 27 | Chorus | High-pass | 299 | 112 | **confirmed** |
| `0x1D` | 28 | Chorus | Width | 300 | 113 | **confirmed** |
| `0x1E` | 29 | Chorus | Delay Send | 301 | 114 | **confirmed** |
| `0x1F` | 30 | Chorus | Reverb Send | 302 | 115 | **confirmed** |
| `0x20` | 31 | Chorus | Mix Volume | 303 | 117 | **confirmed** |
| `0x21` | 32 | Delay | Delay Time | 256 | 119 | predicted |
| `0x22` | 33 | Delay | Pingpong | 257 | 120 | predicted |
| `0x23` | 34 | Delay | Stereo Width | 258 | 121 | predicted |
| `0x24` | 35 | Delay | Feedback Gain | 259 | 122 | predicted |
| `0x25` | 36 | Delay | Feedback HPF | 260 | 123 | predicted |
| `0x26` | 37 | Delay | Feedback LPF | 261 | 124 | predicted |
| `0x27` | 38 | Delay | Reverb Send | 262 | 125 | predicted |
| `0x28` | 39 | Delay | Mix Volume | 263 | 127 | predicted |
| `0x29` | 40 | Delay | Delay FX Routing | — | 128 | predicted |
| `0x2A` | 41 | Reverb | Pre-delay | 264 | 130 | predicted |
| `0x2B` | 42 | Reverb | Decay Time | 265 | 131 | predicted |
| `0x2C` | 43 | Reverb | FB Shelving Freq | 266 | 132 | predicted |
| `0x2D` | 44 | Reverb | FB Shelving Gain | 267 | 133 | predicted |
| `0x2E` | 45 | Reverb | Input HPF | 268 | 134 | predicted |
| `0x2F` | 46 | Reverb | Input LPF | 269 | 135 | predicted |
| `0x30` | 47 | Reverb | Mix Volume | 271 | 137 | predicted |
| `0x31` | 48 | Reverb | Reverb FX Routing | — | 138 | predicted |
| `0x32` | 49 | Ext-in | Stereo In Level | 286 | 141 | predicted |
| `0x33` | 50 | Ext-in | Input R Volume | 287 | 143 | predicted |
| `0x34` | 51 | Ext-in | Stereo In Balance | 288 | 144 | predicted |
| `0x35` | 52 | Ext-in | Input R Pan | 289 | 146 | predicted |
| `0x36` | 53 | Ext-in | In Chorus Send | 290 | 147 | predicted |
| `0x37` | 54 | Ext-in | In Chorus Send R | 291 | 149 | predicted |
| `0x38` | 55 | Ext-in | In Delay Send | 292 | 150 | predicted |
| `0x39` | 56 | Ext-in | In Delay Send R | 293 | 152 | predicted |
| `0x3A` | 57 | Ext-in | In Reverb Send | 294 | 153 | predicted |
| `0x3B` | 58 | Ext-in | In Reverb Send R | 295 | 155 | **past the window** |
| `0x3C` | 59 | Ext-in | Dual Mono | 296 | 156 | **past the window** |
| `0x3D` | 60 | Master | Threshold | 272 | 160 | **past the window** |
| `0x3E` | 61 | Master | Attack Time | 273 | 161 | **past the window** |
| `0x3F` | 62 | Master | Release Time | 274 | 162 | **past the window** |
| `0x40` | 63 | Master | Makeup Gain | 275 | 163 | **past the window** |
| `0x41` | 64 | Master | Ratio | 276 | 164 | **past the window** |
| `0x42` | 65 | Master | Sidechain Src | 277 | 165 | **past the window** |
| `0x43` | 66 | Master | Sidechain Filter | 278 | 167 | **past the window** |
| `0x44` | 67 | Master | Dry/Wet Mix | 279 | 168 | **past the window** |

### The tension at the top, and it is real

Their transport description bounds the mirror:

```
SHARC+ receives 672 words at 0x0025C48C   ->  0xA80 bytes
parameter mirror begins at   0x0025CE96   ->  0xA0A into the packet
0xA80 - 0xA0A = 0x76 bytes = 59 halfwords ->  runtime 0..58
```

**Master's predicted indices are `0x3D`–`0x44` (61–68). They do not fit.** Nor
do the last two Ext-in entries.

Three readings, and the first is the most likely:

1. **Master travels in a different packet.** They describe the transport as
   "ColdFire `fx_setup` **category 0x10**", and `0x10` is 16 — which is exactly
   the Chorus group number in our table. If category equals group, Master
   (group 20) is a different category and simply is not in this mirror.
2. The `id + 1` chain breaks somewhere above Chorus, in which case the
   predictions for Delay and Reverb are also suspect.
3. The mirror extends past the packet the parameters arrive in.

**This is the first thing to check**, and it is checkable statically: find where
ColdFire assembles the `fx_setup` packet and see which groups it walks. It
also decides how much of the table above is worth anything.

*Evidence level for the whole table: **DSP interpretation** — a single confirmed
anchor of seven, extended by an arithmetic rule. Seven of sixty-seven rows are
measured. The rest are predictions, and the window constraint says at least
eight of them are wrong.*

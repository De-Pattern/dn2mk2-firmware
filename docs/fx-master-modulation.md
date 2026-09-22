# Can an LFO reach an FX or Master parameter?

**Read 2026-09-22, statically, on `Digitone_II_OS1.11.syx` section 3.** The
answer is yes in principle and no today, and the reason is neither the
modulation mask nor the `ParameterSet` enumeration. It is that **`DEST` names a
slot inside one 202-byte block of a seventeen-block mirror, and the FX and
Master values live in block sixteen** — the one block no LFO's base pointer ever
points at.

This file covers backlog §4's remainder: the FX and Master parameters
themselves, and the p-lock half. It does not repeat `docs/modulation-mask.md`,
`docs/parameter-set-tables.md` or `docs/fx-parameter-space.md`; it corrects
several claims in them and says so in the last section.

## 0. What was measured, and what is inferred

Everything in §§1–5 is disassembly or table bytes from the shipped 1.11 image —
binary fact. §6 (the plan) is engineering judgement. Nothing here has been on
the instrument, nothing has been built, and the emulator was not run: it is a
serial resource and another session was using it.

**The frame the DSP is sent was not observed moving.** The identification of
mirror block 16 as the FX and Master block rests on four independent readings of
ColdFire code that all produce the same arithmetic. That is strong, and it is
not a runtime observation. §6 names the cheapest experiment that would make it
one.

## 1. The records

The 320-record table is at `0x401f7fc8`, 60 bytes a record, **entry = index + 1**;
accessors reach it through the pre-biased base `0x401f7f94`, which is
`table − 60 + 8`. Field offsets below are from the record start as
`src/dnfw/params/record.py` frames it. `docs/modulation-mask.md` frames records
8 bytes lower, so every offset there is 8 less than the same field here: its
`+0x24` mask is this file's `+44`.

`+44` across all 320 records, measured:

| `+44` | records |
|---|---|
| `0x1e00` | 190 |
| `0x0e00` / `0x0600` / `0x0200` | 8 each |
| `0x40000` / `0x20000` / `0x10000` | 1 each |
| `0` | 103 |

The FX and Master pages, in full. `slot` is `+12`, the `ParameterSet` slot and
the field that decides everything below. `range` is `+20`, `NRPN` is `+36`:

| entry | page | group | slot | name | short | range | NRPN | `+44` |
|---|---|---|---|---|---|---|---|---|
| 105 | Chorus | 16 | 25 | Depth | `DPTH` | `0x7f00` | `0x129` | **0** |
| 106 | Chorus | 16 | 26 | Speed | `SPD` | `0x7f00` | `0x12a` | **0** |
| 107 | Chorus | 16 | 27 | High-pass | `HPF` | `0x7f00` | `0x12b` | **0** |
| 108 | Chorus | 16 | 28 | Width | `WDTH` | `0x7f00` | `0x12c` | **0** |
| 109 | Chorus | 16 | 29 | Delay Send | `DEL` | `0x7f00` | `0x12d` | **0** |
| 110 | Chorus | 16 | 30 | Reverb Send | `REV` | `0x7f00` | `0x12e` | **0** |
| 111 | Chorus | 16 | 31 | Chorus Mix Vol. | `CHR` | `0x7f00` | — | **0** |
| 112 | Chorus | 16 | 31 | Mix Volume | `VOL` | `0x7f00` | `0x12f` | **0** |
| 113 | Delay | 18 | 32 | Delay Time | `TIME` | `0x7f00` | `0x100` | `0x1e00` |
| 114 | Delay | 18 | 33 | Pingpong | `X` | `0x100` | `0x101` | `0x1e00` |
| 115 | Delay | 18 | 34 | Stereo Width | `WID` | `0x7f00` | `0x102` | `0x1e00` |
| 116 | Delay | 18 | 35 | Feedback Gain | `FDBK` | `0x7f00` | `0x103` | `0x1e00` |
| 117 | Delay | 18 | 36 | Feedback HPF | `HPF` | `0x7f00` | `0x104` | `0x1e00` |
| 118 | Delay | 18 | 37 | Feedback LPF | `LPF` | `0x7f00` | `0x105` | `0x1e00` |
| 119 | Delay | 18 | 38 | Reverb Send | `REV` | `0x7f00` | `0x106` | `0x1e00` |
| 120 | Delay | 18 | 39 | Delay Mix Vol. | `DEL` | `0x7f00` | — | **0** |
| 121 | Delay | 18 | 39 | Mix Volume | `VOL` | `0x7f00` | `0x107` | `0x1e00` |
| 122 | Delay | 18 | 40 | Delay FX Routing | `DEL` | `0x100` | — | `0x1e00` |
| 123 | Reverb | 17 | 41 | Pre-delay | `PRE` | `0x7f00` | `0x108` | `0x1e00` |
| 124 | Reverb | 17 | 42 | Decay Time | `DEC` | `0x7f00` | `0x109` | `0x1e00` |
| 125 | Reverb | 17 | 43 | FB Shelving Freq | `FREQ` | `0x7f00` | `0x10a` | `0x1e00` |
| 126 | Reverb | 17 | 44 | FB Shelving Gain | `GAIN` | `0x7f00` | `0x10b` | `0x1e00` |
| 127 | Reverb | 17 | 45 | Input HPF | `HPF` | `0x7f00` | `0x10c` | `0x1e00` |
| 128 | Reverb | 17 | 46 | Input LPF | `LPF` | `0x7f00` | `0x10d` | `0x1e00` |
| 129 | Reverb | 17 | 47 | Reverb Mix Vol. | `REV` | `0x7f00` | — | **0** |
| 130 | Reverb | 17 | 47 | Mix Volume | `VOL` | `0x7f00` | `0x10f` | `0x1e00` |
| 131 | Reverb | 17 | 48 | Reverb FX Routing | `REV` | `0x100` | — | `0x1e00` |
| 132 | Ext-in | 21 | 49 | Input Level | `IN` | `0x7f00` | — | **0** |
| 133–147 | Ext-in | 21 | 49–58 | fifteen level / pan / send records | | | `0x11e`–`0x127` | `0x1e00` |
| 148 | Ext-in | 21 | 59 | Dual Mono | `DUAL` | `0x100` | `0x128` | **0** |
| 149 | Master | **19** | 68 | Master Overdrive | `MOVD` | `0x7f00` | `0x132` | **0** |
| 150 | Master | 20 | 60 | Threshold | `THR` | `0x7f00` | `0x110` | **0** |
| 151 | Master | 20 | 61 | Attack Time | `ATK` | `0x7f00` | `0x111` | **0** |
| 152 | Master | 20 | 62 | Release Time | `REL` | `0x7f00` | `0x112` | **0** |
| 153 | Master | 20 | 63 | Makeup Gain | `MUP` | `0x7f00` | `0x113` | **0** |
| 154 | Master | 20 | 64 | Ratio | `RAT` | `0x700` | `0x114` | **0** |
| 155 | Master | 20 | 65 | Sidechain Src | `SCS` | `0x1200` | `0x115` | **0** |
| 156 | Master | 20 | 65 | Sidechain Src | `SCS` | `0x1300` | `0x115` | **0** |
| 157 | Master | 20 | 66 | Sidechain Filter | `SCF` | `0x7f00` | `0x116` | **0** |
| 158 | Master | 20 | 67 | Dry/Wet Mix | `MIX` | `0x7f00` | `0x117` | **0** |
| 159 | Master | **19** | 69 | Pattern Volume | `VOL` | `0x7f00` | `0x118` | **0** |

Fifty-five records over **forty-five distinct slots, 25–69, contiguous with no
gap**. Duplicate slots are UI variants of one value (`CHR`/`VOL`, `Delay Mix
Vol.`/`Mix Volume`, the two `SCS` records with different maxima).

Two things to carry forward:

- **The `Master` page spans two groups.** Group 20 is the compressor, slots
  60–67; group 19 holds Master Overdrive at slot 68 and Pattern Volume at 69.
- **No record in the whole table carries a `+12` above 99.** Measured across all
  320. Slots 100–127 are unclaimed by any parameter, which matters in §6.

## 2. Every consumer of `+44`

Found by resolving the base register of every use of the parameter-record base
`0x401f7f94`, in both the indexed and the pointer spelling, over the whole
objdump of section 3 (`out/main111.dis`, 1,079,455 lines). That base appears as
`lea 0x401f7f94,%aN` fifty times and as `addal #0x401f7f94,%aN` twice; there is
no other base into this table, and `0x401f7fb4` in `addil` form at `0x400dc12e`
reaches field `+40`, not `+44`.

**The scope of that search, said plainly:** it finds any read whose address is
computed from that one constant. It would *not* find a consumer that received a
record pointer as a function argument from somewhere else. The getter in the
list below is exactly such a hand-off, and its callers are counted separately.

Nine sites read `+44`. Nothing writes it.

| site | how | what it does |
|---|---|---|
| `0x400397c8` | `movel %a0@(36),%d3`, `%a0` from `addal` | filter cascade A: `btst #18/17/16` → `0x1e00` / `0x0e00` / `0x0600`, else 0 |
| `0x40039ad0` | `movel %a2@(24,%d0:l),%d1` | filter cascade B, byte-identical to A |
| `0x40039cf2` | same | filter cascade C |
| `0x40039ef0` | same | filter cascade D |
| **`0x400672fa`** | same | **filter cascade E** — the same three `btst`s, but it writes the result with `moveaw #0x600,%a1` / `moveaw #0x1e00,%a1`, so a scan for `movew #imm` walks past it |
| `0x40067502` | same | `andil #0x70000` at `0x40067506` — "is this entry a `DEST` record?" |
| `0x400676e0` | same | `andil #0x70000` at `0x400676e4` — same test |
| `0x400679e2` | same | `andil #0x70000` at `0x400679e6` — same test, gates opening the destination browser |
| `0x400dc32c` | same | `FUN_400dc30e(entry) -> mask`, a two-line getter, then `rts` |

`FUN_400dc30e` has **zero direct callers**; it is taken by address at
`0x40039570`, `0x40039910`, `0x40039b32` and `0x40039d54` — the four call sites
of the list builder `0x4003951e`, which invokes it through `%a2`/`%a3`.

So the field has exactly two jobs: **choose a modulator's filter** (five sites)
and **identify the three `DEST` records** (three sites), with one getter feeding
the list builder's subset test. There is no third consumer; in particular no
storage path, no MIDI path and no display path reads it.

## 3. `+44` is not the gate for these records, and that is already settled

**Do not re-run the experiment this invites.** The obvious move — give the 103
closed records `0x1e00` — was built, flashed and answered on **2026-09-12**.
`scripts/build_moddest_expand.py` opened all 32 closed parameters in three
groups; group A (13 per-voice parameters) appeared and modulated, **group B
(Chorus, 8) and group C (Master, 11) did not appear at all**. That is why
`src/dnfw/mods/moddest.py` ships only the 13. `docs/modulation-mask.md`,
"RESULT, 2026-09-12".

Delay and Reverb are the same fact from the other side: seventeen of their
nineteen records already carry a full `0x1e00`, and no destination list in the
instrument offers them.

So for FX and Master, `+44` is **necessary and not sufficient**, measured on
hardware, and the remaining work is entirely elsewhere.

## 4. What the gates actually are — three of them, in order

### 4a. Enumeration

`0x4003951e` walks slots `0..100` of a `ParameterSet` through vtable slot
`+0x50`, and only then tests the mask. `FxParameterSet`'s implementation
(`0x400dc0b0`) indexes a 101-entry pointer table at `0x42c649a8`;
`SoundParameterSet`'s (`0x400dc02a`) indexes `0x42c64b3c` and is
machine-dependent. Both tables are BSS, built at boot by
`param_set_tables_build` (`0x400dc4d0`) from the record's page id at `+8` and
filed **at the index in `+12` verbatim** (`docs/parameter-set-tables.md` §3).

An LFO on a synth track walks the sound set. FX records go to the FX set because
their page ids are 16–21. That is the gate `docs/modulation-mask.md` identified,
and it is real.

### 4b. The `DEST` value is a slot number, and the two slot spaces collide

This is the part that had not been read. When a destination is picked from the
list, the selected **entry** is converted before it is stored:

```
4003985a:  movel %a0@(0,%d3:l:4),%sp@-   ; destinations[selected] -- a table entry
4003985e:  jsr   0x400dbcc4              ; -> record+12, the ParameterSet slot
40039866:  movel %d0,%d3
40039868:  lsll  #8,%d3                  ; the stored value is slot << 8
```

and the evaluators read it back coarse:

```
mvs.b %a4@(74),%d2        ; DEST, high byte = the slot
moveq #100,%d1
cmp.l %d7,%d1 / bcs skip  ; DEST > 100 -> nothing
lea   %a0@(0,%d7:l:2),%fp ; %a0 = the track's mirror block -> &block[DEST]
```

So `DEST` carries **no identity at all** — only a number, resolved against
whichever block `%a0` points at. Chorus Depth's slot is 25; slot 25 of a sound
block is the first machine parameter. If an FX record were enumerated into the
sound set today it would be offered under its own name, and the LFO would
modulate **the machine parameter that happens to occupy that slot**. Silent
aliasing, not silence.

That corrects backlog §4's third reason, which predicted "it would be offered,
and it would not move". It would move; it would move the wrong thing.

### 4c. The mirror — and this is the finding

The per-track mirror is **not sixteen blocks. It is seventeen, and the
seventeenth holds the FX and Master values at the same slot numbers the records
carry.**

The base is a constant: `0x400db12a` ends `movel #0x800068e4,%d0 ; rts`, and the
audio-frame ISR calls it at `0x4002717e` and keeps the result in `%a2` for the
whole frame — `%a2` is not written again between `0x40027194` and `0x400275a6`,
checked. Call it `B = 0x800068e4`. Four independent readings of the layout:

1. **The smoother.** `0x400db12a` runs a one-pole filter — coefficients `0x03d7`
   and `0x7c29`, which sum to `0x8000` — from a control-side target array at
   `0x80003af0`, through 32-bit state at `0x8000de60`, into `B`. Its loop
   counter is `movel #1734,%d3` decremented by 2, writing one longword (two u16)
   per pass: **1,734 u16 values, 3,468 bytes**. And `34 + 17 × 202 = 3,468`
   exactly.
2. **The p-lock applier.** `0x400db092` computes its word index as
   `movel #202,%d2 ; mulsl track,%d2 ; addil #34,%d2 ; lsrl #1,%d2`, which is
   `101·track + 17` — the word index of block `track` in a 17-word header plus
   101-word blocks. It then writes `value << 16` into the smoother **state** at
   `0x8000de60 + 4·(101·track + 17 + index)`, so a lock jumps the filter rather
   than gliding to it.
3. **The `DEST` copy.** `0x400db1a4` copies three values per track from
   `0x80003af0 + 202·t + {42, 58, 74}` to `B + 202·t + {42, 58, 74}`, stepping
   202 until `0x800075ae` — sixteen tracks. Those offsets are slots 4, 12 and
   20: LFO1, LFO2 and LFO3's `DEST`, the three values that must not be smoothed.
4. **The frame builder.** `0x400274ba` walks the sixteen track blocks at stride
   202 from `B`, taking `%a5@(84)` for slot 25 — `34 + 2·25`. Then, **after** the
   sixteen passes, it copies five more blocks straight out of `B`:

| source | bytes | words | slots | page, from the record table |
|---|---|---|---|---|
| `%a2@(3316)` | 14 | 7 | 25–31 | **Chorus**, slots 25–31 |
| `%a2@(3330)` | 18 | 9 | 32–40 | **Delay**, slots 32–40 |
| `%a2@(3348)` | 16 | 8 | 41–48 | **Reverb**, slots 41–48 |
| `%a2@(3364)` | 22 | 11 | 49–59 | **Ext-in**, slots 49–59 |
| `%a2@(3386)` | 16 | 8 | 60–67 | **Master** compressor, slots 60–67 |
| `%a2@(3402)` | 4 | 2 | 68–69 | Master Overdrive, Pattern Volume |

`34 + 202·16 = 3266`, and `3266 + 2·slot` reproduces every one of those six
offsets: `3266 + 50 = 3316`, `3266 + 64 = 3330`, `3266 + 82 = 3348`,
`3266 + 98 = 3364`, `3266 + 120 = 3386`, `3266 + 136 = 3402`. **Five page
boundaries and five lengths, all derived from `+12` months ago and never used
for this, land on the block-16 formula with no residue.** They also land
contiguously in the frame, at `0x8000685a` through `0x800068b3` — 90 bytes for
45 values.

So:

```
mirror[block][slot] = 0x800068e4 + 34 + 202*block + 2*slot
    block 0..15  = the sixteen tracks
    block 16     = the global FX and Master values, slots 25..69
```

The whole of it, block 16 included, is regenerated from the control side every
audio frame; then the six MIDI performance modulators are applied
(`0x400db22c`, called at `0x40027196`); then the LFOs (`0x40137726`, called at
`0x400272d4`); then the frame is built (`0x400274ba`) and sent (`0x400cf7be`).
**A value written into block 16 at that point reaches the DSP in the same frame,
and is refreshed next frame rather than accumulating.**

### What this answers, and what it does not

**It answers §4's central question.** The FX and Master parameters are *not* "on
the other side of a different mirror". `FxSetup::updateMirror` (`0x4002ffca`)
writes `Digisharc::fxSetupStorage_v0_t` — the **save image**, exactly as
`Sound::updateMirror` writes `soundStorage_v3_t`, which
`docs/engine-index-map.md` §15 already retracted once for this very confusion.
The runtime path is block 16, and it is reachable by the same kind of write the
LFO already performs.

**It does not answer whether the DSP honours it.** Everything above is the
ColdFire's side of the wire. If some other path also publishes the FX settings
and wins, a write into block 16 would be overwritten. Nothing found suggests one
— block 16 is the only source the frame builder reads for these values — but
"not found by a search of the ColdFire image" is not "not present". §6 names the
experiment that would convert this into a measurement.

## 5. P-locks — a different mechanism, and it does not reach here either

From DNX's decoded format (`DNX/docs/dn2-pattern-format.md` §4, §4a, §4b, §6a),
which is measurement against hardware captures and is described here in our own
words:

- The lock table is **80 records of 258 bytes** at pattern `0x10A34`, each
  `{u8 parameter id, u8 track, 128 × (coarse, fine)}`. Every record is keyed by
  a **track 0..15** and by an id in a space that runs **1..106**, and ids 33..81
  are *machine-relative* — the same id names a different parameter on a
  different machine.
- That id space is neither the mirror slot space nor the FX set slot space. The
  per-track FX sends are lock ids 92/93/94 and mirror slots 88/86/87; nothing
  lines up.
- **The FX and Master settings are not in the lock table at all.** They are
  **kit** data: single bytes at a stride of two from `kit+5810` (Chorus),
  `kit+5824` (Delay), `kit+5842` (Reverb), `kit+5858` (Input) and `kit+5882`
  (Compressor) — one block per kit, one kit per pattern. Twelve further controls
  were locked on the device during that capture and produced no lock record at
  all.

So p-locking an FX parameter needs **three new things**, not one:

1. **An id.** The id byte is a `u8` and the named space stops at 106, so 107..255
   are representable. Whether ids above the current maximum survive a save is
   unknown and is **a question for DNX**, unasked — it is item 3 of backlog §12
   and the same class of question the sound canary answered. Do not hand-roll a
   SysEx capture here.
2. **A track that is not a track.** Every record carries one, and a global FX
   parameter has none. Block 16 suggests the sentinel: `track = 16`.
3. **Almost nothing on the apply side, if 2 holds.** `0x400db092` already
   computes `101·track + 17`, so a record with `track = 16` lands on block 16
   with no arithmetic change whatever. What would need growing is the 128-bit
   per-track bitmap at `0x4664b26c + 16·track` (a seventeenth row, 16 bytes) and
   the second per-track array the same routine writes at `101·track + index`.

**That is a better position than §4 assumed** — the applier's arithmetic is
already general over seventeen blocks — and it is still gated on a storage
question this repository cannot answer alone.

## 6. The costed plan

Three routes. They share the block-16 write and differ in how a destination is
named.

### Route A — a new `DEST` code range (recommended)

Reserve `DEST` codes **101..127** for block 16, meaning FX slot `DEST − 76` (so
101 → slot 25, 124 → slot 48). What makes this cheap:

- **101..127 are free.** No record carries a `+12` above 99, so no existing
  destination can ever produce a code in that range. Measured over all 320.
- **The `DEST` record already permits it.** `+20` is `0x7f00` on all three `DEST`
  records — a coarse maximum of 127.
- **Twenty-seven codes**, which is enough for Chorus + Delay + Reverb: slots
  25..48, twenty-four of them, the musically interesting set. Master (60..69)
  needs eleven more and therefore needs the evaluator's read widened from
  `mvs.b` to `mvz.b`, because a signed byte read makes any code above 127
  negative and the existing unsigned `bcs` bound then rejects it. That is a
  second, separate step, not a blocker on the first.

Work items, each with its site:

| # | change | where | size |
|---|---|---|---|
| 1 | raise the `moveq #100` bound and branch to a block-16 path when `DEST > 100` | both evaluators, at the `mvs.b %a4@(74)` bound | 2 caves |
| 2 | in that path, `lea 0x800075a6` (that is `B + 3266`) and index `2·(DEST − 76)` | the same two caves | included above |
| 3 | append the FX entries to the destination list | `0x4003951e`, after the 101-slot loop, walking `0x42c649a8` for slots 25..48 | 1 cave |
| 4 | make the entry → value conversion add 76 for an FX record | the `jsr 0x400dbcc4 ; lsll #8` pairs on the selection paths | 1 cave per site; **count them before believing this line** |
| 5 | leave `+44` alone, or set `0x1e00` on Chorus's eight so the subset test passes | eight record words | 8 bytes |

Nothing in route A grows a BSS table, moves an object, or touches storage —
`DEST` is already a `u16` mirror slot and a code of 101..127 fits it.

**The risk to state up front is that sixteen tracks' LFOs can all target the same
global cell**, and they will stack, because each evaluator reads the cell and
adds to it. That is a consequence of the parameters being global, and it needs
saying in the UI rather than fixing in the engine.

Rough size: **four to five caves, eight data bytes, and one count to do first**
(item 4). Comparable to `lfo4-tick6a`, which was 26 edits and seven stubs.

### Route B — enumerate FX records into the sound set

Change `param_set_tables_build` (`0x400dc4d0`) so page ids 16–21 also file into
the sound table at `+12 + 76`. It is one function and it is in the image. But the
sound slot table is 101 entries allocated with an explicit byte length, the
destination builder's bound is `i != 0x65`, and `0x400dc02a`'s is `moveq #100` —
three bounds to raise, plus the allocation. Strictly more work than route A for
the same result, and it puts FX parameters into a set whose accessor is
machine-dependent. **Recorded and not recommended.**

### Route C — apply control-side in `FxSetup::updateMirror`

Backlog §4 named this as the alternative. It is wrong in granularity and in
rate: `updateMirror` writes the *save image*, runs at edit rate, and would need
the LFO's instantaneous value, which the control side does not hold.
**Closed.** `docs/engine-index-map.md` §8 reached the same conclusion by a
different and now-superseded argument.

### The cheapest next experiment, and it is one store

**Write a ramp into block 16 from inside the audio ISR, and listen.**

A cave entered right after `jsr 0x400db22c` at `0x40027196`, holding a counter
and a single `movew` into `B + 3330` (Delay Time, slot 32) or `B + 3316` (Chorus
Depth, slot 25). Five or six instructions. It asks exactly one question — *does
the DSP act on block 16?* — with no `DEST` change, no enumeration, no mask edit
and no UI.

| result | means |
|---|---|
| the parameter sweeps | block 16 is the live FX mirror; §4's remainder is route A, and it is plumbing |
| the parameter does not move | something else publishes the FX settings and wins; find it before costing anything |
| it moves and then snaps back | block 16 is right but a later writer in the same frame overwrites; move the cave |

Make it unmissable inside a bar — full-range on delay feedback or reverb decay,
not a subtle drift. The `tick7` build took fourteen bars and was nearly reported
as broken.

**The emulator cannot settle this** and should not be spent on it: it does not
model the DSP, so the most it can show is that the bytes in the frame buffer
change. That is worth having as a pre-flight check on a build, and it is not the
answer.

## 7. Corrections to other documents in this repository

Recorded here rather than rewritten there, because none of them invalidates the
document's own conclusion.

- **`docs/modulation-mask.md`, "How the destination list is built"** says four
  byte-identical filter sites. There are **five**; the fifth is at
  `0x400672fa`/`0x40067304` and spells its result `moveaw #imm,%aN`. Commit
  `d48012e` (2026-09-22) taught `scripts/scan_lfo_triples.py` that form for the
  same reason; the table in that document has not caught up.
- **`docs/modulation-mask.md`'s histogram** is quoted over "all 271 named
  records" and gives 55 closed. Over all 320 records the count is **103**, and
  the two are the same fact — the difference is the 48 unnamed records, which
  are also closed. Both numbers appear in this repository and neither says its
  denominator in the same breath.
- **`docs/ideas-backlog.md` §4's page table** says Reverb is `0x1e00` on **7 of
  9**. Measured: **8 of 9** — only `Reverb Mix Vol.` (entry 129) is closed. The
  prose list in the same row names all eight correctly; the count is the slip.
- **`docs/fx-parameter-space.md` §2** gives the contiguous FX id run as
  **1..67**. It is **1..69**: group 19 holds Master Overdrive at slot 68 and
  Pattern Volume at slot 69, and the frame builder copies both.
- **`docs/fx-parameter-space.md` §8, "the tension at the top"** reasons that
  Master's indices do not fit a 59-halfword receive window, and suggests Master
  travels in a different packet. From this end the ColdFire builds **all 45
  values, slots 25..69, contiguously** into the frame at `0x8000685a`. The two
  readings are of opposite ends of the same wire and one of them is wrong; this
  is the first hard number from our side.
- **`docs/ideas-backlog.md` §4, reason 3** ("the FX objects are on the other side
  of a different mirror … it would be offered, and it would not move") is **half
  right, and the half that is wrong is worse than it says**. The storage split is
  real and is the *save* image; the runtime values are in the same array, block
  16. An FX record enumerated into the sound set would be offered and *would*
  move — the wrong parameter, by slot aliasing.
- **`docs/engine-index-map.md` §8** ("the LFO's running value appears never to
  exist on the control side at all — it is produced and applied engine-side") is
  **superseded** by the 2026-09-16 and 2026-09-17 readings: the evaluators at
  `0x40137726` and `0x401373dc` are ColdFire code, and `lfo4-tick6a` passed on
  hardware. Its conclusion about `FxSetup::updateMirror` survives; its reason
  does not.

## 8. The experiment, built — `fxblock16`, 2026-09-22

`scripts/build_fxblock16.py` → `00_Resources/02_Builds/fxblock16_DN2_1.11.syx`,
section also at `out/fxblock16/section_3_MAIN_OS.bin`. It is §6's last item and
nothing else: one cave, one store, no `DEST` change, no mask edit, no
enumeration, no UI, no LFO4.

### The addresses in this document were checked, and they held

Every one, read back out of `Digitone_II_OS1.11_dist.zip` section 3 with
`dnfw disasm` and asserted again by the build script before it writes anything:

| claim | at | bytes | verdict |
|---|---|---|---|
| `jsr 0x400db22c`, the six-source apply | `0x40027196` | `4e b9 40 0d b2 2c` | **holds** |
| `jsr 0x400db12a`, the mirror smoother | `0x4002717e` | `4e b9 40 0d b1 2a` | **holds** |
| `B = 0x800068e4` | `0x400db14a` | `45 f9 80 00 68 e4` — `lea 0x800068e4,%a2` | **holds** |
| the frame builder reads block 16 | `0x400275ba` | `48 6a 0d 02` — `pea %a2@(3330)` | **holds** |

The hook itself goes at **`0x4002719c`**, the instruction *after* the `jsr`,
which is what "a cave entered right after `jsr 0x400db22c`" has to mean for a
6-byte detour. `dnfw cave probe --at 0x4002719c` displaces two straight-line
instructions, `50 8f 42 ae ff 58` (`addql #8,%sp ; clrl %fp@(-168)`), with no
PC-relative opcode among them.

### A fifth reading, from the write side, and it is the strongest yet

Looking for anything that might overwrite the store before the frame is built
found the opposite: **stock code writes block 16 itself, in this same ISR, for
an audible reason.** At `0x400273f4`, gated on `0x4058e550` being non-zero:

```
4002744c:  movew 0x4058e874,%d0
40027452:  mulsw #127,%d0
40027460:  asrl  #7,%d0              ; x 127/128 -- a per-frame fade
40027468:  movew %d0,%a2@(3360)      ; slot 47  Reverb Mix Vol.
4002746c:  movew %d1,%a2@(3350)      ; slot 42  Reverb Decay Time   <- 0
40027470:  movew %d1,%a2@(3336)      ; slot 35  Delay Feedback Gain <- 0
40027474:  movew %d1,%a2@(3344)      ; slot 39  Delay Mix Vol.      <- 0
```

Four displacements, four slots, and they are exactly the four values you would
write to make the FX tails stop: fade the reverb's output, kill the reverb's
decay, kill the delay's feedback, kill the delay's output. The block-16 formula
reproduces all four with no residue, from a routine that had nothing to do with
how it was derived. §4c's four readings all watch block 16 being *built* or
*copied*; **this is the first that shows the firmware reaching into it to change
what the instrument sounds like.**

It is still ColdFire-side, so it does not close the question — but it does pick
the target. The build sweeps **slot 35, Delay Feedback Gain**,
`B + 34 + 202·16 + 2·35 = 0x800075ec`, because that is a cell the instrument
already writes when it wants something audible to change.

The same search is the reason the hook site is safe: those four writes and the
six `pea`s of the frame builder are the **only** block-16 accesses anywhere
between `0x40025e36` and `0x40027c00`, and the four are behind a mute gate that
is off while the instrument is making sound.

### The rate, counted rather than guessed

The hook sits in the vector-191 handler `FUN_40025e36` — installed at
`0x40025576` (`movel #0x40025e36,%d0 ; movel %d0,0x400002fc`, with `5` into
`ICR1_63` at `0xfc04c07f`), and raised by a software force from the SSI0-paced
eDMA-50 completion, which is the cadence digikit reads from the other side.
That major loop is 64 minors of 32 bytes over a 64-byte TDM frame, so the
handler runs **once per 32 audio frames — 1,500 Hz at 48 kHz.**

Three constants in the image agree, and the build script asserts all three:

- `0x402876f8` = **1500**, the number of ISRs the DSP send is held off for at
  boot (`0x40025e82`) — a one-second warm-up;
- `0x402a0dec` = **14,400**, the time units added per ISR (`0x40025f1c`);
- `0x40137530` = **21,600,000**, the LFO phase wrap — and 1,500 × 14,400 is
  exactly that.

So the payload advances one step every 8 calls over 256 steps: a full
`0x0000` → `0x7f00` → `0x0000` triangle in **2,048 calls = 1.37 s**, which is
one and a half sweeps per bar at 120 BPM. `tick7` is why that number is not
larger.

### What the build is, in full

62 bytes of payload in the cave at `0x4028ea02` — the one cave region with a
hardware-confirmed success (`docs/code-caves.md`) — plus the six displaced
bytes and the jump back; a 6-byte hook; and four bytes of counter in RAM above
BSS at `0x46704000`. 64 bytes of the section differ from stock, all of them
inside the hook and the cave.

```
lea %sp@(-8),%sp ; movem.l %d0-%d1,%sp@
d0 = ++*(u32*)0x46704000
d0 >>= 3 ; d1 = d0 & 0x80 ; d0 &= 0x7f ; if (d1) d0 ^= 0x7f
*(u16*)0x800075ec = d0 << 8
movem.l %sp@,%d0-%d1 ; lea %sp@(8),%sp
```

`%d0` and `%d1` both look dead at the hook and are saved anyway.

### Reading it

| what is heard | what it means |
|---|---|
| the delay feedback surges and collapses, about every 1.4 s | **block 16 is the live FX mirror.** §4's remainder is route A, and it is plumbing |
| nothing moves | **something else publishes the FX settings and wins.** Find it before costing anything in §6 |
| it moves, then snaps back | **block 16 is right and a later writer in the same frame overwrites.** Move the cave down towards `0x400275a6` |

**The Delay page on screen does not move in any of the three.** The UI reads the
control side; only block 16 is touched. A tester who watches the screen instead
of listening will read a pass as a failure.

### Gates

| gate | result |
|---|---|
| `check_coldfire.py --against` stock | **pass** — 1,539 hits shared with stock (its data), **0** new |
| `emu_boot_check.py`, from reset | **pass** — booted and drew its UI, 1 frame in 450 M instructions, against a stock control of 1; no fault, eight tasks created, the priority-6 application task among them |
| `emu_boot_engine.py --build out/fxblock16` | **does not apply, and was replaced** — see below |
| `scripts/emu_fxblock16.py` — the replacement | **pass** — booted from reset, then ran the payload 4,096 times: `0x800075ec` walked `0x0000`..`0x7f00`, 128 distinct values, repeating exactly with period 2,048, and the counter at `0x46704000` counted every call. The cave was entered **0** times during the boot itself, which is the expected answer here and not a defect |
| `dnfw inspect` | **pass** — 21/21 integrity checks, HMAC-SHA256 trailer reproduced |

**`emu_boot_engine.py` cannot be run against this build, and pretending
otherwise would be the §19 mistake again.** It opens
`out/<build>/symbols.json` and counts `lfo4_refresh`, so it only has meaning
for a build that carries a compiled chunk; `fxblock16` carries a 62-byte cave
and no chunk, and the script fails on the missing file before it boots
anything. `scripts/emu_fxblock16.py` asks the same question in the form this
build can answer: boot from reset, then run the payload 4,096 times and watch
`0x800075ec`. A value that only ever reads zero is a failure there, not an
ambiguity.

The emulator cannot settle the real question either — it does not model the
DSP, and it does not run the audio engine, so the hooked ISR never fires during
a boot. That is a known property of this harness, recorded in
`emu_boot_engine.py`'s own docstring about `lfo4_refresh`, and it is why the
cave gate calls the payload directly. Everything short of the wire can be
checked here; the wire is the flash.

## 9. It sweeps — the DSP reads block 16, 2026-09-22

`fxblock16_DN2_1.11.syx` was flashed and the owner's report is the pass row of
§8 verbatim:

> "What you hear: It sweeps"

and, asked whether it sustained or moved once and settled:

> "it keep sweeping :) all good. Go ahead with it"

**So the sound chip does act on the block at `0x800068e4`.** A write from the
ColdFire into slot 35 — Delay Feedback Gain, `B + 3336` — reaches the audio
path and is audible, and nothing later in the 0.67 ms cycle takes it back.

### What that settles, precisely

Five readings of the firmware agreed on where the FX and Master parameters sit
and **none of them proved anybody downstream read it** (§0's standing caveat, and
the whole reason §6's plan could not be costed). That gap is now closed by the
instrument rather than by another reading:

| was open | now |
|---|---|
| is block 16 the **live** FX mirror, or a copy nobody consumes? | live — a store into it changes what comes out of the speakers |
| does something **else** publish the FX settings and win? | no; there is no competing sender for this cell |
| does a later writer in the same frame overwrite ours? | no — the sweep sustains, it does not snap back |

The third row matters as much as the first: §8 listed "it moves, then snaps
back" as a distinct outcome needing the cave moved down towards `0x400275a6`.
It did not happen, so the hook site at `0x4002719c` stands.

**It also confirms §4c's formula end to end.** `mirror[block][slot] = B + 34 +
202*block + 2*slot` was derived from six `pea` displacements in the frame
builder and cross-checked against the mute-gate writes at `0x40027468`. A cell
computed from it, written by hand, produced exactly the parameter the formula
names. The arithmetic is not a plausible fit any more; it is confirmed by
construction.

### What it does not settle

The store went in from the **audio interrupt**, at a point in the frame where
the block is already built. It says the DSP reads the block; it does **not** say
that a value written from the *control* side — where an LFO's output would
arrive — survives the rebuild that happens every frame. §4c's whole finding is
that the frame builder **recomputes** block 16 from the FX setup objects, so a
control-side write is the thing that could still be overwritten, and route A
places our contribution inside that rebuild for exactly that reason.

That is a design question route A already answers, not a new unknown. But it is
the difference between "the lane is live" and "the feature works", and the two
should not be run together — §8's own lesson about reading a result for more
than it says.

### What happens next

§6's costed plan is unblocked and **route A is the one this result argues for**:
a new `DEST` code range, applied where the frame builder writes block 16, so the
modulation is part of the rebuild rather than a race against it. Roughly four or
five small patches, all of the same kind as LFO4's.

`docs/ideas-backlog.md` §4 moves from *blocked, pending one experiment* to
*ready*, which is where the owner ranked it first.

## 10. Route A's sites, read before building — 2026-09-22

§6 costed route A at "four to five caves, eight data bytes, and one count to do
first". The count was done and route A is **cheaper than it was costed**, in two
places, and the reason it is cheaper is the reason the line said to count.

### The evaluator write is a read-modify-write, and retargeting it is one `lea`

Evaluator A, `0x40137a8a` onward, is the whole mechanism in twenty bytes:

```
40137a8a  mvsb  %a4@(74),%d2          ; DEST, a byte out of the LFO's block
40137a8e  moveq #100,%d1
40137a90  mvsw  %d2,%d7
40137a92  movel %d7,%a2@(104)
40137a96  cmpl  %d7,%d1
40137a98  bcss  0x40137ad2            ; DEST > 100 -> write nothing at all
40137a9a  moveal %sp@(52),%a0         ; <- the track's mirror base
40137a9e  mvsw  %a4@(82),%d1          ; DEP
40137aa2  lea   %a0@(0,%d7:l:2),%fp   ; <- &mirror[track][DEST]
   ... macl DEP by the LFO value ...
40137ab8  mvsw  %fp@,%d1              ; read the cell
40137aba  addl  %d1,%d0               ; add
   ... clamp to 0 .. 0x7f00 ...
40137ad0  movew %d0,%fp@              ; write it back
```

**The cell address is `%a0 + 2·DEST` and `%a0` is loaded from one place.** So
pointing a code at block 16 does not need a new store, a new clamp or a second
path — it needs `%a0` to be a different base for one range of codes:

> `0x800068e4 + 34 + 202·16 − 152` = **`0x8000750e`**, because the existing
> `lea` already adds `2·DEST` and the FX slot is `DEST − 76`.

One cave, eight displaced bytes at `0x40137a96`, resuming at `0x40137a9e`:
replay the compare, send codes 1..100 to `movea.l %sp@(52),%a0`, codes 101..127
to `lea 0x8000750e,%a0`, and anything above 127 to the stock skip at
`0x40137ad2`. Everything after it — the depth multiply, the accumulate, the
clamp, the store — is stock code doing exactly what it already does.

The clamp is worth naming: the cell is clamped to `0..0x7f00` on every write,
and `0x7f00` is the same full scale stock uses when it writes block 16 itself
(`movew #32512` at `0x40027434`). So an FX cell driven this way cannot be
pushed out of range by an LFO.

### Evaluator B cannot see these codes, so it is not a second cave

`0x40137698` is the same shape — `mvsb %a4@(40),%d1 ; moveq #100,%d6 ; cmpl
%d3,%d6 ; bcss` — but B carries a **second, tighter bound** twenty-six bytes
later that A has no equivalent of:

```
401376a8  moveal %d3,%a0
401376aa  subql  #1,%a0                ; a0 = DEST - 1
401376c2  moveq  #7,%d2
401376c4  cmpl   %a0,%d2
401376c6  bcss   0x401376ee            ; DEST - 1 > 7 -> write nothing
```

So **evaluator B writes only for `DEST` 1..8** and codes 101..127 can never
reach it. Route A item 1 is therefore **one cave, not two**.

*Measured, not explained.* Why B is bounded to eight destinations when A takes a
hundred is not established here, and it should not be assumed to be a mistake or
a spare capacity — `docs/PRINCIPLES.md` on not identifying a structure from a
bare count applies. It is recorded because it changes the cost, and the
explanation can wait until something depends on it.

### Item 4 is two sites out of thirty-four

`jsr 0x400dbcc4` — the entry → value conversion — has **34 call sites** in the
image. §6 flagged "count them before believing this line", and the count is why:
only **two** are the `jsr` + `lsl.l #8` pair that item 4 is about.

| site | the shift |
|---|---|
| `0x4003985e` | `lsl.l #8,%d3` at `0x40039868` |
| `0x400c2a36` | `lsl.l #8,%d0` at `0x400c2a3e` |

The other thirty-two call the same routine for something else and must not be
touched. Item 4 is two caves.

### Revised cost

| item | costed in §6 | measured |
|---|---|---|
| 1–2 evaluator bound and block-16 base | 2 caves | **1 cave**, 8 displaced bytes |
| 3 destination list enumeration | 1 cave | not yet read — `0x4003951e` |
| 4 entry → value conversion | "1 per site", 34 sites | **2 caves** |
| 5 `+44` flags | 8 bytes | unchanged |

Item 3 is now the only unread piece, and it is the one that decides whether an
FX destination can be *chosen* rather than only *driven*.

## 11. Item 3, the destination list enumeration, read — and it changes the plan

§10 left item 3 as "the only unread piece, and the one that decides whether an
FX destination can be *chosen* rather than only *driven*". It was read on
2026-09-22. **It is not one cave after the loop.** The list is only half of a
round trip, and the other half is a shared leaf with thirty-four callers.

### What `0x4003951e` actually is

One function, **ten call sites** (`0x4003981c`, `0x4003996a`, `0x40039a16`,
`0x40039b8c`, `0x40039c38`, `0x40039dae`, `0x40039e36`, `0x400c28ee`,
`0x40106502`, `0x40107abc`), of shape

```
build(std::vector<int>* out /* %a0 */, ParameterSet* set /* sp@(4) */,
      u32 want /* sp@(8) */)
```

and the loop is nineteen instructions:

```
4003958a:  moveal %a5@,%a0            ; %a5 = the set
4003958c:  movel  %d2,%sp@-           ; the slot, 0..100
40039590:  moveal %a0@(80),%a0        ; vtable +0x50: slot -> entry
40039594:  jsr    %a0@
40039596:  movel  %d0,%sp@(48)
4003959c:  beqs   0x400395b6          ; slot unoccupied -> next
4003959e:  jsr    %a2@                ; %a2 = 0x400dc30e, the `+44` getter
400395a2:  notl   %d0
400395a4:  andl   %sp@(56),%d0        ; keep only if `want` is a subset of `+44`
400395aa:  bnes   0x400395b6
400395ac:  pea    %sp@(40)            ; &entry
400395b0:  movel  %a3@,%sp@-          ; the vector
400395b2:  jsr    %a4@                ; 0x40193f1e -- push_back
400395b6:  addql  #1,%d2
400395b8:  moveq  #101,%d1
400395ba:  cmpl   %d2,%d1
400395bc:  bnes   0x4003958a
```

So **the list holds entry numbers, not slots**, the membership test is
`(~mask & want) == 0`, and the *only* thing that decides which parameters are
walked is the set's own `slot -> entry` virtual at **vtable +0x50**. The
browser passes `want = 0x200` (`0x40107ab0`), the loosest filter — bit 9, which
`0x1e00`, `0x0e00`, `0x0600` and `0x0200` all carry. The randomiser
(`0x40039756`) passes the narrow cascade instead.

After the loop the function builds a 26-entry `std::map` from the table at
`0x4028bfc4` and sorts the vector through `0x400391a6`. That is ordering, not
enumeration: **no second source of entries exists.** So "where would FX entries
be appended" has an answer, and it is not "after the loop" — it is *inside* it,
through the set's own virtual, or nowhere.

### The consequence: it is a round trip, and both directions must agree

Three more sites matter, and together they say why one cave is not enough:

| direction | where | what it does |
|---|---|---|
| slot → entry | `0x400c28e0`, `0x40107aae` | the set's vtable `+0x50`, on the stored `DEST >> 8` |
| entry → slot | `0x4003985e` (`lsl.l #8` at `0x40039868`) | the randomiser stores `slot << 8` |
| entry → slot | `0x400c2a36` (`lsl.l #8` at `0x400c2a3e`) | the group-step stores `slot << 8` |
| entry → slot | **`0x40107b0e`** | the browser converts, then feeds the slot straight **back** into `+0x50` |

`0x40107b0e` is the correction to §10. That site has **no `lsl.l #8`**, which is
why counting the shift found two sites and not three — it converts
entry → slot and immediately asks the set for the entry again, to normalise the
duplicate records (`CHR`/`VOL`, the two `SCS`). A build that teaches only the
shifted pair to add 76 leaves the browser's own confirm path mapping code 111
back to sound slot 35.

`0x400dbcc4` — entry → `record+12` — is a five-instruction leaf with **34
callers**, of which these three are on `DEST` paths and thirty-one are not. Its
sibling `0x400dbce8` returns `record+8`, the **group**, which is what the
group-step at `0x400c2894` compares to decide where the next page of
destinations starts. Both were identified against `params/record.py`'s word
indices (`GROUP = 2` at byte 8, `PARAMETER_ID = 3` at byte 12), not guessed.

### So item 3 is a matched pair, not a cave

To make an FX destination *choosable* the two directions have to agree:

1. **slot → entry**: `SoundParameterSet`'s `+0x50` must answer codes 101..124
   with the FX records' entry numbers, which means reading `FxParameterSet`'s
   own slot table `0x42c649a8` at `code − 76` — `0x400dc0b0` is that read, four
   instructions, and it is already in the image. And `0x4003951e`'s `moveq #101`
   bound must rise to 125 so the loop reaches them.
2. **entry → slot**: the three `DEST` sites above must add 76 when the record's
   group is 16, 17 or 18, without disturbing the other thirty-one callers of
   `0x400dbcc4`.

Neither is large. What makes it a second build rather than this one is that
**none of it can be gated here**: the emulator runs no destination browser, so
the only instrument that can tell a working round trip from a half-working one
is the instrument. Shipping it with the engine change would put two questions on
one flash, which is what §3 of `docs/FEATURE-PLAYBOOK.md` exists to prevent.

**Not read, and named so it is not assumed:** whether the 26-entry ordering map
at `0x4028bfc4` has a key for groups 16..18, and what the sort at `0x400391a6`
does with an entry whose group it has no key for. That is the first thing to
read when item 3 is built, and it is the kind of omission that produces a hang
rather than a wrong name.

### Revised cost, again

| item | §10 said | now |
|---|---|---|
| 1–2 evaluator bound and block-16 base | 1 cave, 8 displaced bytes | **1 byte + 1 cave** — §12, built |
| 3 destination list enumeration | 1 cave, unread | **a `+0x50` extension and one bound byte**, and it is half of a pair |
| 4 entry → value conversion | 2 caves | **3 sites** — `0x40107b0e` carries no `lsl.l #8` |
| 5 `+44` flags | 8 bytes | unchanged; Chorus's eight only |

## 12. `fxdest`, built 2026-09-22 — route A's engine half

`scripts/build_fxdest.py` → `00_Resources/02_Builds/fxdest_DN2_1.11.syx`,
section also at `out/fxdest/section_3_MAIN_OS.bin`. Two edits, 47 bytes
changed, no chunk, no loader, no UI.

### The edits

| # | at | stock | becomes | why |
|---|---|---|---|---|
| 1 | `0x40137a8e` | `72 64` — `moveq #100,%d1` | `72 7f` — `moveq #127,%d1` | evaluator A's destination bound. `DEST` is read with `mvs.b`, so 127 is the ceiling that read can carry, and a negative byte still fails the unsigned compare exactly as in stock |
| 2 | `0x40137a9e` | `73 6c 00 52 4d f0 7a 00` — `mvs.w %a4@(82),%d1 ; lea %a0@(0,%d7:l:2),%fp` | `jmp 0x4028ea02` + `nop` | the cave |

§10 suggested hooking at `0x40137a96` and replaying the compare. Hooking two
instructions later is strictly better: **the displaced pair is straight-line**,
with no `bcc` among it, so `patch/cave.py`'s PC-relative guard passes on its own
terms rather than being waived, and the payload has only to overwrite `%a0`
before the replayed `lea` uses it. The cost is edit 1, one byte.

The cave, as `dnfw disasm` reads it back out of the built `.syx`:

```
4028ea02  4a 87              tstl  %d7
4028ea04  66 0c              bnes  0x4028ea12
4028ea06  22 0d              movel %a5,%d1          ; the track counter
4028ea08  66 08              bnes  0x4028ea12
4028ea0a  4a af 00 30        tstl  %sp@(48)         ; the inner counter, 2..0
4028ea0e  66 02              bnes  0x4028ea12
4028ea10  7e 6f              moveq #111,%d7         ; the demonstration
4028ea12  72 64              moveq #100,%d1
4028ea14  b2 87              cmpl  %d7,%d1
4028ea16  64 06              bccs  0x4028ea1e       ; DEST <= 100 -> stock base
4028ea18  41 f9 80 00 75 0e  lea   0x8000750e,%a0   ; block 16
4028ea1e  73 6c 00 52        mvsw  %a4@(82),%d1     ; the displaced stock
4028ea22  4d f0 7a 00        lea   %a0@(0,%d7:l:2),%fp
4028ea26  4e f9 40 13 7a a6  jmp   0x40137aa6
```

`0x8000750e` is `B + 34 + 202·16 − 2·76`: the stock `lea` already adds
`2·DEST`, and the FX slot is `DEST − 76`. `%d1` is scratch for two instructions
and the replayed `mvs.w` reloads it, so nothing live is clobbered; on the skip
path it leaves 127 where stock left 100, and `%d1` is dead there — written
before it is read at both `0x401377a4` and `0x40137afc`. Everything after the
jump back — the depth multiply, the accumulate, the `0..0x7f00` clamp, the
store — is stock.

### What was asserted before anything was written

Sixteen control addresses, each one `dnfw disasm` away by hand, and all sixteen
held: evaluator A's `mvs.b` and bound test, the `%sp@(52)` load, the
`addil #-16384` that makes `DEP` bipolar, the clamp and the store; the three
loop instructions the demonstration reads (`lea %a4@(-34),%a4`,
`movel %d1,%sp@(48)`, `lea %a4@(-16),%a4`) and the sixteen-track bound; the
mirror base `lea 0x800068e4,%a2`; the frame builder's `pea %a2@(3330)`; and
**evaluator B's two bounds, re-verified rather than trusted** —
`moveq #100,%d6` at `0x4013769c` and `moveq #7,%d2 ; cmpl %a0,%d2 ; bcs` at
`0x401376c2`. B keeps its own hundred, so codes 101..127 never reach it; and it
writes through `%sp@(56)`, the `0x4463fc18` array, not the mirror at all.
**Item 1 is one cave, not two, confirmed.**

Two further guards the build runs itself: nothing in the whole disassembly
branches into `0x40137a9e..0x40137aa5`, and **no longword anywhere in the
3,192,192-byte section holds one of those addresses** — which catches a jump
table that a branch grep would not see.

### The demonstration, and why it is hard-coded

Nothing on the instrument can produce a code of 101..127 until item 3 is built,
so the build carries one, in the manner of `lfo4-tick7` and `fxblock16`:

> on **track 1** only, on **LFO1** only, and only while its `DEST` reads
> **none**, the code becomes **111** — block-16 slot 35, **Delay Feedback
> Gain**, the exact cell the instrument was heard to sweep in §9.

The condition is `%d7 == 0 && %a5 == 0 && %sp@(48) == 0`: registers the
evaluator already holds, so it needs no absolute address and cannot drift with
the mirror base. `%a5` is the outer track counter (`addql #1,%a5` at
`0x40137b0a`, bounded by `moveq #16` at `0x40137b18`); `%sp@(48)` is the inner
counter, set to 2 at `0x401377a0` and decremented per LFO while `%a4` walks back
16 bytes at a time, so **2 = LFO3, 1 = LFO2, 0 = LFO1** — which is why
`%a4@(74)` reads mirror offsets 74, 58 and 42, the `DEST` cells of slots 20, 12
and 4.

`DEST = none` is the power-on default and `DEP` defaults to centre, so nothing
moves until the owner turns `DEP` up. That is the whole test, with `SPD`,
`MULT`, `WAVE` and `DEP` all live rather than a fixed triangle — a strictly
better demonstration than a hard-coded ramp, because the owner can steer it.

### Gates

| gate | result |
|---|---|
| `check_coldfire.py out/fxdest/section_3_MAIN_OS.bin` | **pass** — **1,539** hits against `out/lfo4-browser`'s **1,540**. `--against` that baseline: 1,539 shared (its data), **0 new**. Below the ceiling because this build carries no compiled chunk |
| `emu_boot_check.py out/fxdest/section_3_MAIN_OS.bin`, from reset | **pass** — *"booted and drew its UI (1 frame(s), control 1)"*, exit 0, 450 M instructions. Not a fault and not a hang |
| `emu_boot_engine.py --build out/fxdest` | **does not apply, and was replaced.** It opens `out/<build>/symbols.json` and counts `lfo4_refresh`; this build has no chunk and no symbols, so it fails on the missing file before booting anything. Recording that as "n/a" would be `docs/PRINCIPLES.md` §19 again, so `scripts/emu_fxdest.py` asks the same question in the form this build can answer |
| `scripts/emu_fxdest.py` | **pass on the third run**, exit 0, `out/emu-logs/gate_fxdest3.log`. The first two runs are in §13 because how they failed is the useful part |
| `dnfw inspect` | **pass** — 21/21 integrity checks and the HMAC-SHA256 trailer reproduced |

The passing run, eleven cases against a case-for-case stock control:

| case | `fxdest`: `%a0` / store | stock: `%a0` / store |
|---|---|---|
| sound slot 5 | `0x80006906` / `0x80006910` | `0x80006906` / `0x80006910` |
| sound slot 100 | `0x80006906` / `0x800069ce` | `0x80006906` / `0x800069ce` |
| `DEST` 0, track 2 LFO1 | `0x80006906` / `0x80006906` | same |
| `DEST` 0, track 1 LFO2 | `0x80006906` / `0x80006906` | same |
| `DEST` 0, track 1 LFO3 | `0x80006906` / `0x80006906` | same |
| **the demonstration**, `DEST` 0, track 1 LFO1 | `%d7` becomes **`0x6f`**, `0x8000750e` / **`0x800075ec`** | `%d7` stays 0, `0x80006906` / `0x80006906` |
| code 101, Chorus Depth | `0x8000750e` / `0x800075d8` | **nothing; `%a0` and `%fp` untouched** |
| code 111, Delay Feedback Gain | `0x8000750e` / **`0x800075ec`** | **nothing** |
| code 124, Reverb FX Routing | `0x8000750e` / `0x80007606` | **nothing** |
| code 127, the top of the range | `0x8000750e` / `0x8000760c` | **nothing** |
| a negative `DEST` byte | nothing; `%a0` and `%fp` untouched | nothing |

`0x800075ec` is the cell `fxblock16` swept on the instrument in §9, reached here
from a `DEST` code instead of a hard-coded address. Every other address is
`0x800075a6 + 2*(code - 76)` with no residue, and stock's `%a0` staying at zero
above code 100 is the control saying the patch is what changed — not the
harness.

**The value is not asserted and that is deliberate.** Each store carries
`0x1234`, the sentinel, because this emulator's EMAC contributes nothing to the
accumulate and the evaluator writes the cell's own value back. The address is
the whole of what route A changes; the depth is a question for the instrument.

`emu_fxdest.py` boots the patched image from reset and then **calls evaluator
A's destination write by hand**, `0x40137a8a` → `0x40137ad2`, with the registers
the tick would have held, over eleven cases: sound slots 5 and 100, `DEST = 0`
on three track/LFO combinations either side of the demonstration's, codes 101,
111, 124 and 127, and a negative byte. Both candidate cells are pre-loaded with
a sentinel and the depth is set to its positive stop with a large LFO value, so
a cell that *is* written clamps to `0x7f00` and one that is not still reads the
sentinel. **The stock section is run as a control, case for case** — it has to
agree below 101 and write nothing at all above it, or the harness is measuring
itself rather than the patch.

### What it cannot settle, said before the flash

The emulator does not model the DSP and does not run the audio engine, so the
tick never fires during a boot and no sound is produced. §9 answered the DSP
question on the instrument; what is untested until this is flashed is whether a
value written into block 16 **by the LFO tick** — which runs inside the frame
rebuild, not after it — survives to the frame builder. That is the difference §9
named between "the lane is live" and "the feature works", and it is exactly what
this build asks.

### The two things that are consequences, not defects

- **Sixteen tracks' LFOs can all target the same global FX cell and they will
  stack**, because every evaluator reads the cell and adds to it before the
  clamp. That is what the FX parameters being global means. This build exposes
  one LFO so it cannot be seen yet; it will be the first surprise the moment the
  browser can offer these codes, and it belongs in the UI rather than the engine.
- **Master (slots 60..69) is out of reach of this range.** It needs codes
  136..145, and `mvs.b` makes any byte above 127 negative, which the unsigned
  bound then rejects. Widening that read to `mvz.b` is a separate step; Chorus,
  Delay and Reverb — slots 25..48, codes 101..124 — are the whole of what
  101..127 buys.

## 13. The two harness runs that measured nothing, and why they are kept

`scripts/emu_fxdest.py` passed on its third run. The first two are recorded
because they are a clean instance of `docs/PRINCIPLES.md` §19 — *a negative is
only as good as the instrument that produced it* — and because the second one
very nearly read as a verdict on the build.

### Run 1 — "wrote nothing", eleven times, and for stock too

The harness filled five predicted cells with a sentinel, ran the evaluator, and
compared. Every case read "wrote nothing", **including the stock control's
plain sound destination**, which stock certainly writes. The zero was a
property of the harness. Nothing about `fxdest` was measured.

It was caught only because the case list carried positive controls — sound
slots 5 and 100, which have nothing to do with route A and exist purely so the
instrument can be seen finding something it must find. Without them, eleven
rows of "wrote nothing" against a build that changes where a write lands would
have read as "the patch does not write", and that is the wrong answer with the
right shape.

### Run 2 — the registers, and a refusal to conclude

Three changes: read the setup back before using it, watch the **whole**
3,468-byte mirror rather than five predicted cells, and return `%d7`, `%a0` and
`%fp` with each result. And a gate: if stock does not write the sink for sound
slot 5, print why and exit **2** without reaching a verdict on anything.

It exited 2, as designed — and its register readings are the measurement the
build actually needed:

```
fxdest  sound slot 5      byte 0x05  d7 0x00000005  a0 0x80006906  fp 0x80006910
fxdest  THE DEMO          byte 0x00  d7 0x0000006f  a0 0x8000750e  fp 0x800075ec
fxdest  code 124          byte 0x7c  d7 0x0000007c  a0 0x8000750e  fp 0x80007606
fxdest  a negative byte   byte 0xff  d7 0xffffffff  a0 0x00000000  fp 0x00000000
stock   code 111          byte 0x6f  d7 0x0000006f  a0 0x00000000  fp 0x00000000
```

Every address route A claims, from the machine, with stock as the control —
and the harness still declined to call it a pass, because it could not see the
store. That refusal is the part worth keeping.

### What was actually wrong: a read-modify-write that contributes nothing

The evaluator's store is `movew %d0,%fp@` at the end of

```
mvs.w %fp@,%d1      ; read the cell
addl  %d1,%d0       ; add this LFO's contribution
   ... clamp ...
movew %d0,%fp@      ; write it back
```

and the contribution reaches `%d0` through `macl`/`movclrl`, the EMAC. Under
this emulator that term is zero, so the evaluator **wrote the sentinel back
over itself**. A watch that compares memory before and after cannot see a store
of the value already there, and cannot see it for stock either — which is
exactly why the control failed its own positive both times.

Run 3 replaced the comparison with `UC_HOOK_MEM_WRITE`. Every store appeared at
once, each carrying `0x1234`: the diagnosis confirmed rather than worked
around.

### A reading that looked decisive and was not

Every row of runs 1 and 2 ends `pc 0x40137ad2`, which is also the target of the
evaluator's skip branch (`bcss 0x40137ad2` at `0x40137a98`). That invites the
conclusion that the evaluator took the "no destination" exit and never reached
the store.

**It does not follow.** `0x40137ad2` is the `until` argument the harness passes
to `emu_start`; the store at `0x40137ad0` is the instruction immediately before
it, so a case that runs the store stops there too. Reaching it is compatible
with both paths and distinguishes neither. What *does* distinguish them is
`%a0` and `%fp` — the skip leaves both untouched, which exactly one case shows
(the negative byte), and the write hook then found a store in each of the other
ten.

The general form, and it is the same one §19 lists six times: **a value that
every outcome produces is not a measurement.** `pc` was one; so was a memory
comparison against a read-modify-write that writes what it read.

### What the case list should carry next time

- **Positive controls that the patch has nothing to do with.** Sound slots 5
  and 100 are the only reason runs 1 and 2 were not believed.
- **A negative control inside the same run.** Stock's `%a0` staying at zero
  above code 100 is what makes "the build writes block 16" a statement about
  the build.
- **A watch that cannot be satisfied by inaction.** Hook the write; do not
  compare the memory.
- **A refusal path.** An instrument that fails its own positive should exit
  differently from one that fails the subject, or the log reads as a verdict.

## 14. Route A works on the instrument — 2026-09-23

`fxdest_DN2_1.11.syx` was flashed and the owner's report, against §12's stated
pass criterion:

> "The delay should surge and collapse — and respond to DEP and SPD, which is
> the evidence a hard-coded ramp couldn't give" -> **"yes it responds like
> this, it works."**

**So an LFO can modulate an FX parameter.** A `DEST` code above 100 retargets
the evaluator's read-modify-write from the track's own mirror block to block
16, and the value that arrives at Delay Feedback Gain is an LFO's output —
audible, and **steerable by `DEP` and `SPD`**.

### Why the steering is the part that matters

`fxblock16` (§9) already proved the DSP reads block 16, but it wrote a
hard-coded triangle from the audio ISR. Anything that merely *moved* the cell
would have sounded the same. The demonstration was built so that the only way
to get a response to the depth and rate knobs is for the value to have come
**through the LFO evaluator**: the depth multiply, the accumulate against the
cell's current contents, and the clamp are all stock code that the patch does
not touch. A ramp cannot be steered; this is.

### What is now established, end to end

| step | how |
|---|---|
| the FX/Master parameters live in mirror block 16 at `B + 34 + 202*16` | five independent reads of ColdFire code (§4c), and the formula confirmed by construction (§9) |
| the DSP acts on that block | `fxblock16` on hardware, sustained (§9) |
| a `DEST` code can reach it | one cave, one `lea 0x8000750e`, verified address-by-address against a stock control (§12) |
| **what arrives is an LFO, not a ramp** | **`fxdest` on hardware, responding to `DEP` and `SPD` (this section)** |

Two edits and 47 bytes. `docs/ideas-backlog.md` §4's engine half is **done**.

### What is left, and it is one build

The engine accepts codes 101..127; **nothing can yet choose one.** §11 read the
destination browser and specified the matched pair:

- extend `SoundParameterSet`'s `+0x50` (slot -> entry) to answer for codes
  101..124 off `FxParameterSet`'s table at `0x42c649a8`;
- raise the enumeration bound `moveq #101` -> `125` at `0x400395b8`;
- teach the **three** entry<->slot conversion sites the `+76`, including
  `0x40107b0e`, the browser's confirm path, which carries no `lsl.l #8` and is
  why a scan for the shift found only two.

**It cannot be gated in this emulator** — no destination browser runs there —
so it is the instrument's question, and it is deliberately a separate flash
from this one.

One piece is named as unread rather than assumed: whether the 26-entry ordering
map at `0x4028bfc4` has a key for groups 16-18, and what the sort does with an
entry whose group it has no key for. That is the kind of gap that hangs rather
than mis-names, and it is the first thing to read.

### The consequence to design for, now that it is real

**Sixteen tracks' LFOs can all aim at the same global FX cell, and they will
stack**, because every evaluator reads the cell and adds before the clamp. This
build exposes one LFO on one track so it cannot be seen yet. It will be the
first surprise the moment the browser can offer these codes, and it belongs in
the UI, not the engine.

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

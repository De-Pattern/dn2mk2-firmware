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
- **CORRECTED 2026-09-23, by DNX, and the correction narrows the problem.** The
  line below said twelve FX controls locked on the device produced no lock
  record. Those twelve were **not** FX controls -- they are `NOTE`, `VEL`,
  `LEN`, `PROB`, `COND`, `FILL`, `RTRG`, `VFAD`, `RATE`, `LFO.T` and `FLT.T`.
  **The per-track FX page is fully lockable already**, eight ids in the table:
  `CHR` 92, `DEL` 93, `REV` 94, `BR` 101, `SRR` 102, `SR.RT` 103, `OVER` 104,
  `OD.RT` 106. What cannot be locked is the **global** Chorus/Delay/Reverb
  pages, which are kit data. The gap is that, and only that.

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

## 15. `fxbrowser`, built 2026-09-23 — the browser half, and three corrections to §11

`scripts/build_fxbrowser.py` → `00_Resources/02_Builds/fxbrowser_DN2_1.11.syx`,
section at `out/fxbrowser/section_3_MAIN_OS.bin`. It **carries `fxdest`'s two
edits as well**, because the browser is useless without the engine and the
engine is unreachable without the browser, so the owner needs one image and not
two.

§11's specification held in all three parts. Reading the sites a second time
changed the *shape* of two of them and closed the unknown §11 named.

### The unknown is closed, and the answer is a positive one

§11, §14 and `STATUS.md` all carried the same flag: *does the 26-entry ordering
map at `0x4028bfc4` have a key for groups 16–18, and what does the sort do with
an entry whose group it has no key for?* — "the kind of gap that hangs rather
than mis-names".

**The table is a list of group ids in display order, and the FX groups are in
it:**

```
30, 12, 5, 6, 7, 8, 9, 10, 13, 11, 15, 16, 17, 18, 19, 20, 21, 29, 14, 22..28
    rank:                             11  12  13
```

Chorus (16), Reverb (17) and Delay (18) are at **ranks 11, 12 and 13**, after
group 15 and before group 19. The loop at `0x4003963c` builds `map[group] =
rank` once, behind the `0x405c6dd0` guard; the comparator at `0x4003907e` reads
`0x400dbce8(entry)` for the group, looks it up through `0x40193cf8` and sorts by
`(rank, entry)`. `0x40193cf8` is `operator[]`, which **default-inserts 0** for a
missing key — so even a group with no rank sorts to the front rather than
faulting. The hang cannot happen, and it does not arise anyway.

**The consequence for the UI, and it is worth saying to the owner:** the 24 FX
destinations appear **partway through** the list, not appended at the end —
after the synth/filter/amp pages and before the later ones, grouped Chorus,
then Reverb, then Delay. Nothing in this build chose that; the firmware already
ranked those pages.

### Correction 1 — the `+0x50` virtual is reached through one shared helper

§11 said "extend `SoundParameterSet`'s `+0x50`". The vtable slot is a wrapper:
it reads two machine bytes through `+0x28` calls and ends `jsr 0x400dc02a` at
`0x40036758`, passing `(slot, machineA, machineB)`. `FxParameterSet`'s is a
two-instruction thunk at `0x40036768` into `0x400dc0b0`.

So the edit goes on **`0x400dc02a`**, and one hook fixes all four callers of the
virtual at once — the enumeration loop, the group step's current-slot lookup and
the browser's two. The other sets are untouched and their own bounds (100, 100,
25) already reject anything above 100.

### Correction 2 — item 4 is three `jsr` targets, not three caves

All three sites are literally `4e b9 40 0d bc c4`. Rewriting the four-byte
address to a helper of our own **displaces nothing, needs no hook, and leaves
`0x400dbcc4` itself untouched for its other 31 callers** — which is exactly the
constraint §11 stated and a cleaner way to meet it than three detours.

### Correction 3 — `+44` needed measuring, and it more than halved the work

§6 item 5 offered "leave `+44` alone, or set `0x1e00` on Chorus's eight". What
the field actually carries:

- the three `DEST` records produce **different** `want` masks through the
  cascade at `0x400397f2` — LFO1 (entry 78, group 26) `0x1e00`, LFO2 (88,
  group 27) `0x0e00`, LFO3 (98, group 28) `0x0600` — and the list path at
  `0x40107ab0` passes `0x200`;
- the test keeps an entry when `want ⊆ +44`, so a record carrying `0x1e00`
  passes **all four** masks;
- **every Delay and Reverb record the FX slot table selects carries `0x1e00`
  already.** Seventeen of the twenty-four destinations need no record edit at
  all — including Delay Feedback Gain, the one the instrument has already been
  heard to modulate;
- **every Chorus record carries `0`**, blocked under every mask.

So the record edits are Chorus's eight — plus entries **120** and **129**, the
two `Mix Volume` duplicates that are blocked. Slots 31, 39 and 47 each have two
records and only one survives into the boot-time table; setting both members of
each pair makes the build correct whichever wins, rather than resting on a
derivation. That derivation was then measured anyway — see the gates.

Setting the low bits cannot disturb the three `andil #0x70000` "is this a `DEST`
record" tests (bits 16–18), and the identical edit was flashed on 2026-09-12
with no ill effect. It did nothing then because the enumeration was the real
gate, which is what this build changes.

### The edits

| # | at | stock | becomes |
|---|---|---|---|
| 1 | `0x40137a8e` | `72 64` | `72 7f` — `fxdest`: evaluator A's bound, 100 → 127 |
| 2 | `0x40137a9e` | `73 6c 00 52 4d f0 7a 00` | `jmp 0x4028ea3e` — `fxdest`: block 16 for codes 101..127 |
| 3 | `0x400dc02a` | `2f 02 72 64 20 6f 00 08` | `jmp 0x4028ea58` — slots 101..124 answer from `0x42c649a8` |
| 4 | `0x400395b8` | `72 65` | `72 7d` — the enumeration walks 0..124 |
| 5 | `0x4003985e` | `4e b9 40 0d bc c4` | `jsr 0x4028ea02` — the randomiser |
| 6 | `0x400c2a36` | `4e b9 40 0d bc c4` | `jsr 0x4028ea02` — the group step |
| 7 | `0x40107b0e` | `4e b9 40 0d bc c4` | `jsr 0x4028ea02` — the browser's confirm path |
| 8 | entries 105–112, 120, 129 | `+44` = `0` | `+44` = `0x1e00` |

**144 bytes**, 128 of them the three cave blobs, in the 170-byte cave at
`0x4028ea02` that has a hardware-confirmed success.

The helper and the `+0x50` hook are exact inverses, which is what the confirm
path at `0x40107b0e` needs — it converts entry → code and feeds the code
straight back into `+0x50`:

```
4028ea02  movel %sp@(4),%d0 ; cmpil #321,%d0 ; bcss 1f ; clrl %d0   | as 0x400dbcc4 folds it
4028ea10  1: %d0 = 60*entry ; lea 0x401f7f94,%a0 ; lea %a0@(0,%d0:l),%a0
4028ea22  movel %a0@(4),%d0        | +12 : the slot
4028ea26  movel %a0@,%d1           | +8  : the group
4028ea28  subil #16,%d1 ; cmpil #2,%d1 ; bhis 2f
4028ea36  addil #76,%d0            | -> the code, 101..124
4028ea3c  2: rts

4028ea58  movel %sp@(4),%d0 ; moveq #100,%d1 ; cmpl %d0,%d1 ; bccs 1f
4028ea62  moveq #124,%d1 ; cmpl %d0,%d1 ; bcss 1f
4028ea68  lea 0x42c64878,%a0       | 0x42c649a8 - 4*76
4028ea6e  movel %a0@(0,%d0:l:4),%d0 ; rts
4028ea74  1: <the displaced stock> ; jmp 0x400dc032
```

`fxdest`'s hard-coded demonstration is **removed**. It existed only because
nothing could choose a code; leaving it in would silently steal track 1's LFO1
the moment the owner set its `DEST` to none.

### Gates

| gate | result |
|---|---|
| `check_coldfire.py out/fxbrowser/…` | **pass** — **1,539** hits vs `out/lfo4-browser`'s **1,540**; `--against` that baseline: 1,539 shared (its data), **0 new** |
| `scripts/emu_fxbrowser.py` | **pass**, exit 0 |
| `emu_boot_check.py out/fxbrowser/…` from reset | **pass** — *"booted and drew its UI (1 frame(s), control 1)"*, exit 0, 450 M instructions. Not a fault and not a hang |
| `emu_boot_engine.py --build out/fxbrowser` | **does not apply.** It opens `out/<build>/symbols.json` and counts `lfo4_refresh`; this build carries no compiled chunk. `emu_fxbrowser.py` is the probe that asks what this build can answer |
| `dnfw inspect` | **pass** — 21/21 integrity checks, HMAC-SHA256 trailer reproduced |

`emu_fxbrowser.py` restores a booted snapshot through `scripts/emulib/machine.py`
— reusing the project's own harness rather than writing another — and **calls**
four things on the stock image and then on the build:

| asked | answer |
|---|---|
| what does the boot-time FX slot table hold for slots 25..48? | entries 105–110, **112**, 113–119, **121**, 122–128, **130**, 131 — the duplicate-slot resolution the build derived, now **measured**: 112 over 111, 121 over 120, 130 over 129 |
| does stock resolve a plain sound slot? (the known positive) | **yes, 97 of slots 0..100** — so a zero anywhere below means something |
| do slots 0..100 still answer exactly as stock answers them? | **yes, all 101, unchanged** |
| does `0x400dbcc4` itself still answer as stock does, for all 330 entries? | **yes** — its other 31 callers see nothing |
| does stock resolve codes 101..124? | **no, none of them** — the control that makes this a statement about the patch |
| do codes 101..124 resolve to the FX set's own entries? | **yes, all 24** |
| does anything above 124 resolve? | **no** — 125, 126, 127, 128, 130 all return 0 |
| does the helper add 76 exactly for groups 16/17/18? | **yes, for 27 of 330 entries** — Chorus's 8, Delay's 10, Reverb's 9 — and for nothing else |
| does the round trip close? | **yes** — `helper(slot_to_entry(code)) == code` for every code 101..124 |

### What could not be gated here, said plainly

**The emulator runs no destination browser.** There is no panel, no page view
and no encoder, so *the list itself* — whether the 24 entries are drawn, under
what names, in what order, and whether turning the encoder selects one and
leaves it again — is the instrument's question and nothing here can answer it.
Every component the browser is assembled from has been run; the assembly has
not.

That is why the test plan separates "no new names in the list" from "names
appear but nothing moves": they point at opposite halves of the round trip, and
the owner's report distinguishes them at no cost.

### What stays out, deliberately

**Master (slots 60..69).** It needs codes 136..145, and `mvs.b` at `0x40137a8a`
makes any byte above 127 negative, which the unsigned bound then rejects.
Widening that read to `mvz.b` is a third build, and it must also re-check every
other reader of that byte.

### The consequence that becomes visible with this build

**Sixteen tracks' LFOs — and all three LFOs on one track — can aim at the same
global FX cell, and they stack**, because every evaluator reads the cell and
adds to it before the clamp. `fxdest` exposed a single LFO, so it could not be
seen. From this build on it can: two LFOs on Delay Feedback Gain sum and pin at
`0x7f00`. It is not a defect and it is not fixable in the engine — it is what
the FX parameters being global means — so it is written into the owner's test
plan as something to expect rather than to report.

## 16. `fxbrowser` on the instrument: the list grew, the encoder wraps — 2026-09-23

Flashed. The owner's report:

> "when browsing the destination list, once I get to OVR Routing, if I turn one
> more click the list goes to the very top again. I can see by the scroll mark
> on the right that there was still more list after OVR Routing but I can never
> reach under it."

That is §15's test-plan row *"names appear but nothing moves"*, in a sharper
form: the **scroll indicator knows the list is longer** and the encoder does
not.

### First: the enumeration is correct, and that is measured, not assumed

`scripts/emu_destlist.py` calls the list builder `0x4003951e` directly — through
a four-instruction trampoline, because it takes its output pointer in `%a0` and
`Machine.call` can only set stack arguments — with a live `ParameterSet` reached
by replaying the browser's own prologue from `0x400c28a2`. Stock and build, on
the same snapshot, for all three `want` masks in play:

| `want` | whose | stock | `fxbrowser` | added | lost |
|---|---|---|---|---|---|
| `0x0200` | the list path, `0x40107ab0` | 76 | **100** | +24 | 0 |
| `0x1e00` | LFO1 (entry 78) | 55 | **79** | +24 | 0 |
| `0x0600` | LFO3 (entry 98) | 69 | **93** | +24 | 0 |

and the seam is exactly where §15 predicted:

```
# 53  entry 303  group 15  slot  97  'SRR Routing'
# 54  entry 304  group 15  slot  98  'Overdrive'
# 55  entry 305  group 15  slot  99  'OVR Routing'     <- the owner wraps after this
# 56  entry 105  group 16  slot  25  'Depth'           <- Chorus, rank 11
# 57  entry 106  group 16  slot  26  'Speed'
```

**So the list grew, by exactly 24, in the right place, losing nothing.** Item 3
works. The fault is downstream of it.

Three things fell out of the same run and are worth keeping:

- **The three `DEST` records get three different lists.** LFO1's `want` of
  `0x1e00` yields 55 stock entries, LFO3's `0x0600` yields 69, and the list
  path's `0x200` yields 76 — the extra ones being groups 26, 27, 28, the LFO
  pages' own parameters. An LFO cannot be offered *itself*: LFO3's list carries
  groups 26 and 27 and not 28.
- **Stock's LFO1 list ends precisely at `OVR Routing`.** 55 entries, last one
  entry 305, group 15, slot 99 — the highest occupied sound slot. So the part
  the owner can reach *is* exactly the stock list, and what he cannot reach is
  exactly what this build added.
- **Groups 0–4 have no rank.** The ordering table lists 26 groups and group 1
  (25 entries in every list) is not among them, so `operator[]` default-inserts
  rank 0 for it and it sorts beside group 30. Harmless, stock behaviour, and it
  confirms the comparator's missing-key path is the benign one §15 read.

`OVR Routing` is **entry 305**, not 304: the record **index** is 304 and
`entry = index + 1`. The first run of the harness printed its marker on the row
above for exactly that reason and the constant has been corrected.

### ~~Stock had nothing after that point~~ — RETRACTED, see §17

> ~~Stock's LFO1 list ends precisely at `OVR Routing`. 55 entries, last one
> entry 305, group 15, slot 99 — the highest occupied sound slot. So the part
> the owner can reach *is* exactly the stock list, and what he cannot reach is
> exactly what this build added.~~

**Wrong, and the log this was written from contains the disproof.** That is
LFO1's own mask `0x1e00`; the browser passes `0x200`, whose stock list is **76**
entries and runs 21 past `OVR Routing` into the Mod destinations, ending at
MOD3 Depth — which is exactly what the owner reports seeing on stock. So the
build broke reachable stock entries too, and changed the end-of-list behaviour
from "stop" to "wrap". **§17** has the correction and why the mistake happened.

### What the wrap actually points at

The navigation at `0x401079c8` walks the vector element by element
(`0x40107c38`: `lea %a3@(4),%a1 ; cmpl %a1,%d1 ; beqs`) against a `%d1` it
loads fresh from the vector's `end` at `0x40107ad0`. With 79 elements it should
reach element 56. It does not, and the display lands at the **top** rather than
stopping at the bottom — which is the shape of a *failed search*, not of a short
walk: when the current entry cannot be found in the list, control reaches
`0x40107b0c` with `%a1` still at or near `begin`, and the first element is what
gets converted and shown.

So the chain that breaks is **after** the step, not during it:

1. the encoder steps to element 56, entry 105;
2. something stores a `DEST` value for it;
3. the page redraws, reads `DEST` back, resolves it through `+0x50`
   (`0x40107aae`) and searches the list for the resulting entry;
4. the search fails, so the view snaps to the first element.

Step 4 is what the owner sees. Step 2 is the suspect, and **it is the fourth
conversion path §12's report named as the one that could not be ruled out
statically.**

`0x40107b0e` — the site this build repointed — is a *normaliser*, not the store:
it converts entry → code and feeds the code **straight back into `+0x50`** at
`0x40107b1a` to collapse duplicate records, then passes the resulting **entry**
to `%a2@(32)`. The value that ends up in `DEST` is produced inside that virtual,
whose implementation is reached through a function pointer at `this+404`
(`0x4010727a`) and has not been resolved.

**The hypothesis, stated so it can be killed:** that setter converts the entry
to a number by one of the **31 `jsr 0x400dbcc4` sites this build deliberately
did not touch**, so picking Chorus Depth stores **25** rather than **101**. Slot
25 is a real sound slot belonging to a group that is not in LFO1's list at all,
so the redraw's search fails and the view jumps to the top — and the LFO would
be silently modulating whatever sound parameter occupies slot 25, which is
precisely the aliasing §4b warned about.

### Why no fix is shipped for it

The site has not been located, and `docs/PRINCIPLES.md` §19's sibling applies to
positives as much as to negatives: a patch aimed at an unlocated site is a
guess, and it would spend a flash to find that out. The two candidate fixes are
both worse than knowing:

- **patching `0x400dbcc4` itself** would catch the unknown setter, and would
  also change the answer for its other 30 callers — including, possibly, the
  Chorus/Delay/Reverb pages' own code, which needs the raw slot 25..48. That
  blast radius cannot be measured here;
- **hunting the setter by reading** is the chase `docs/FEATURE-PLAYBOOK.md` §2.4
  exists to warn about: it is a virtual reached through a stored function
  pointer, and the instrument for that is digikit's `tools/rttiscan.py` on the
  `0x40107224` family, not more disassembly by eye.

### The observation that splits it, and it costs no flash

**The owner already has the build on the instrument.** Two things he can look at
with it, which distinguish the hypothesis from its alternatives:

1. **After the wrap, what does the LFO page show as `DEST`?** If it names a
   *sound* parameter, the raw slot was stored and the hypothesis holds. If it
   shows nothing or the first entry in the list, the store failed differently.
2. **After the wrap, is some sound parameter being modulated?** Turn `DEP` up
   and listen with the delay send down. Movement in the *voice* — filter,
   pitch, a machine parameter — is the aliasing, and it names the stored number
   directly: slot 25 is the first machine parameter.

Either answer names the number that was stored, which names the conversion, and
a located site is a two-instruction fix rather than a guess.

### What this section does not claim

The emulator runs no destination browser, so none of the above about the *view*
is measured here — only the list contents are. The walk, the search, the redraw
and the store are read from the disassembly and from one report from the
instrument, and the two candidate explanations for "jumps to the top" have not
been told apart. §19 again: this is a narrowing, not a conclusion.

## 17. §16's answer was taken from a mask the browser does not use — RETRACTED

**§16 asked "did we break it or expose it?" and answered "neither, quite".
That is wrong, and the disproof was already in the log it was written from.**

§16 reasoned from **LFO1's own mask `0x1e00`**, whose stock list is 55 entries
ending at `OVR Routing`, and concluded that stock "simply had nothing after that
point, so the reachable part is exactly the whole stock list". But the browser
does not use that mask. The list path's `want` at `0x40107ab0` is **`0x200`**,
which §15 and §16 both state — and the `0x200` dumps say something else
entirely:

| | stock, `want 0x200` |
|---|---|
| length | **76** |
| `OVR Routing` | #55 |
| after it | groups 26, 27, 28 — the Mod destinations, 21 entries |
| last | entry 103, group 28, `Depth` — **MOD3 Depth** |

The owner, asked whether stock also stops there:

> "No, after OVR Routing starts the Mod destinations in the stock settings and
> when you get to the bottom of the list at MOD X - DEPTH the scroll stops, it
> doesn't jump to the first element in the list...never."

**His description and the `0x200` list agree entry for entry, and neither agrees
with the `0x1e00` list.** So the browser shows the `0x200` list, and:

- **we did break it.** Stock reached 21 entries past `OVR Routing`; the build
  reaches none of them. The Mod destinations became unreachable too, not only
  the FX ones.
- **the end-of-list behaviour changed**, from "stop" to "wrap to the top" —
  which stock never does.

Both are consequences of the same failure, and it *strengthens* §16's mechanism
rather than weakening it: in the build's `0x200` list the FX entries are
inserted at **#56**, immediately after `OVR Routing`, so the cursor dies on the
first of them and therefore never reaches the 21 stock entries that now sit
behind them. One fault, both symptoms.

### Why the wrong reading happened, because it is reusable

**A question about the browser was answered from a mask the browser does not
use.** The run produced three lists on purpose — `0x200`, `0x1e00`, `0x0600` —
precisely because which one the browser uses was not established, and then the
conclusion was drawn from the wrong one without saying which. The harness even
printed `"stock runs 22 entries PAST OVR Routing"`, computed from the `0x200`
list, two lines above the sentence that contradicts it.

That is the same shape as measuring without a control: **three candidate answers
were collected and one was used as though it were the only one.** The fix in
practice is to name the variable in the sentence — "stock's list *for the mask
the browser passes*" — because a claim that does not carry its conditions cannot
be checked against a report from the instrument.

(The count is 21, not the 22 the harness printed: the harness counted from
`OVR Routing`'s index inclusive. Corrected here.)

## 18. The root cause: §10 counted the conversion sites with too narrow a window

`fxbrowser` patched **two** `entry -> slot << 8` sites plus one non-shifting
normaliser, on §10's count of "the `jsr 0x400dbcc4` + `lsl.l #8` pairs". That
count came from looking for the shift **adjacent** to the call.

`scripts/scan_dest_values.py` looks 64 bytes forward instead. There are **six**:

| site | shift | distance | in `fxbrowser`? |
|---|---|---|---|
| `0x4003985e` | `lsl.l #8,%d3` at `0x40039868` | 10 B | patched |
| **`0x40039a72`** | `lsl.l #8,%d2` at `0x40039a84` | **18 B** | **missed** |
| **`0x40039c94`** | `lsl.l #8,%d2` at `0x40039ca6` | **18 B** | **missed** |
| **`0x40039e92`** | `lsl.l #8,%d2` at `0x40039ea4` | **18 B** | **missed** |
| **`0x40063df2`** | `lsl.l #8,%d0` at `0x40063e06` | **20 B** | **missed** |
| `0x400c2a36` | `lsl.l #8,%d0` at `0x400c2a3e` | 8 B | patched |

The four missed ones share one shape — `jsr`, `movel %d0,%d2`, **a call to
`0x401880cc`**, then the shift — so an adjacent-pair scan walks past all four
for the same reason. The count against the window settles immediately and does
not move again:

```
   8 bytes: 2      48 bytes: 6
  12 bytes: 2      64 bytes: 6
  16 bytes: 6      96 bytes: 6
  24 bytes: 6     128 bytes: 6
```

**Two instructions of separation was the whole difference between a working
build and a half-working one.**

### The criterion, which replaces the count

> **A site that shifts `0x400dbcc4`'s result left by 8 is producing a `DEST`
> *value*, and a value must carry the route A code. A site that does not shift
> is using `record+12` as an *index* — into a page, a table, a slot space — and
> must keep the raw number.**

Six shift, twenty-eight do not. That is decidable by scanning rather than by
judgement, and the scan is committed so the next person need not trust this
page. It is the positive-side twin of `docs/PRINCIPLES.md` §19: not a negative
from an instrument that could not have found the thing, but **a count from a
scan whose window was too narrow, reported as the number of sites rather than
the number of sites of one spelling.**

### And the missed site is exactly the one the symptom names

`0x40039a72` sits inside `0x40039904`, which `rttiscan.py` identifies as
`ParameterSet`'s vtable **`+0x24`** — one of only **two** slots in all 1,911
vtables whose `+0x20`/`+0x24` pair reaches `0x400dbcc4`, the other being
`FxParameterSet`'s. It is unmistakably on the `DEST` path:

```
40039920  jsr 0x400dc30e          | the record's +44
40039924  btst #18,%d0            | which DEST class is this?
4003992a  asrl #8,%d3             | the current value -> a code
4003992c  moveal %a2@,%a0
40039932  moveal %a0@(80),%a0     | +0x50: code -> entry
40039938  pea 0x1e00              | ... and the `want` for this class
```

It recovers a code by shifting **right** by 8 and resolves it through `+0x50` —
the exact inverse of the conversion this work added — and it was still handing
back `record+12` with no `+76`. So stepping onto Chorus `Depth` stored **25**
where **101** was meant; the redraw read 25 back, `+0x50` resolved it to a sound
entry that is not in the list, the search failed, and the cursor reset to the
first element.

**That is "the list goes to the very top again", and it is why nothing past the
insertion point is reachable.**

`rttiscan.py` is what found it, in five seconds, after a good deal of reading by
eye had not — `docs/FEATURE-PLAYBOOK.md` §2.1 and §2.4, again.

## 19. `fxbrowser2`, built 2026-09-23

`scripts/build_fxbrowser2.py` → `00_Resources/02_Builds/fxbrowser2_DN2_1.11.syx`.
It is `fxbrowser` plus **four four-byte `jsr` target rewrites** onto the same
cave helper — `0x40039a72`, `0x40039c94`, `0x40039e92`, `0x40063df2`. Nothing is
added to the cave, nothing new is displaced, and `0x400dbcc4` itself is still
untouched for the 28 callers that use it as an index. **156 bytes**, against
`fxbrowser`'s 144.

It is built by importing `build_fxbrowser` and extending its `convert` tuple, so
the two builds cannot drift apart: every assertion, guard and record edit is
literally the same code.

### Gates

| gate | result |
|---|---|
| `check_coldfire.py out/fxbrowser2/…` | **pass** — 1,539 hits vs the 1,540 baseline; `--against`: 1,539 shared, **0 new** |
| `dnfw inspect` | **pass** — 21/21 integrity checks, HMAC-SHA256 trailer reproduced |
| `emu_fxbrowser.py` (round trip) | see `out/emu-logs/gate_fxbrowser2.log` |
| `emu_destlist.py` (the list must be **unchanged**) | the same log — the four new edits are conversions, not enumeration, so a changed list would itself be the finding |
| `emu_boot_check.py` from reset | the same log |

### What still cannot be gated here, and it is the same thing

**The browser does not run in this emulator.** Whether the cursor now steps onto
Chorus `Depth` and stays there, and whether the Mod destinations are reachable
again, is the instrument's question. What is gated is that the conversion is
uniform across all six value-producing sites and that nothing below code 101
moved.

**This is the second flash on one question.** If it still wraps, the next thing
to establish is which of the six sites the browser's confirm path actually
reaches — by watching `0x400dbcc4`'s callers under the emulator with a real
panel event, which this harness cannot yet produce — rather than by patching
more sites.

## 17. The browser works — backlog §4 delivered, 2026-09-23

`fxbrowser2_DN2_1.11.syx` on the instrument:

> "works :) I can modulate with the LFOs the parameters."

**So §4 is delivered.** An LFO can be pointed at a Chorus, Delay or Reverb
parameter from the `DEST` list, on any LFO of any track, and it modulates.

The chain, every link measured or heard:

| | how it was settled |
|---|---|
| the FX/Master parameters live in mirror block 16 | five independent reads of ColdFire code (§4c) |
| the DSP acts on that block | `fxblock16`, a sustained sweep on hardware (§9) |
| a `DEST` code above 100 can reach it | one cave, one `lea`, verified address-by-address against a stock control (§10, §12) |
| what arrives is an LFO, not a ramp | `fxdest` on hardware, responding to `DEP` and `SPD` (§14) |
| the codes can be **chosen** | `fxbrowser2` on hardware (this section) |

**And it took two builds because of a counting error of ours**, kept in §16 with
the reasoning: §10 scanned for `jsr 0x400dbcc4` with an **adjacent** `lsl.l #8`
and reported two conversion sites. Six exist; four separate the call from the
shift by an intervening `jsr 0x401880cc`. `fxbrowser` taught three and missed
four, so choosing an FX entry stored a number the redraw could not find, the
cursor reset to the top, and the 21 stock Mod destinations behind the insertion
point went out of reach with it. `scripts/scan_dest_values.py` replaces the
count with a rule -- **a site that shifts is producing a value and needs the
code; a site that does not shift is using `record+12` as an index and must keep
the raw number** -- and prints the count against the search window so the
judgement is visible rather than asserted.

### One defect outstanding, and it is cosmetic

> "chorus section appears like ERR in the modal."

Chorus's entries are the ones this work had to open: Delay's and Reverb's 17
records already carried `0x1e00` in `+44` and needed no edit, while Chorus's
eight carried `0`. So the group that shows `ERR` is exactly the group whose
records were edited, which is where to look first -- but it is **not** yet
established that the edit is the cause, and `ERR` is the name of the dead
records at the head of the table, so a name lookup landing on entry 0 would
produce it just as well.

Not a blocker: the destinations work. Recorded here so it is not lost, and
handed to the browser work rather than guessed at.

## 20. Backlog §4 is delivered — `fxbrowser2` works on the instrument, 2026-09-23

> "works :) I can modulate with the LFOs the parameters."

**The FX destinations are selectable from the `DEST` list and they modulate.**
Route A is complete end to end: an LFO on a synth track can be pointed at any of
the 24 Chorus, Delay and Reverb parameters by name, and the value reaches the
DSP through mirror block 16.

The fix was §18's four-site correction. Two builds were spent on one question,
and the reason is written down in §18 rather than smoothed over: a scan window
of twelve bytes instead of sixteen.

### One defect remains, and it is cosmetic

> "chorus section appears like ERR in the modal."

The **section header** for Chorus draws as `ERR`. The entries under it are
correct and they work.

## 21. The `ERR` header: what is established, and the one question that splits it

### `ERR` is a failed lookup, not a damaged string

`ERR` is the **short name (word 14) of entries 1 and 2** — the dead `Error`
records at the head of the parameter table. Nothing else in the image produces
it. So whatever names that section resolved to **entry 0**, and the header path
took its name from a record index it did not have.

### The strings Chorus needs all exist and are correct

| checked | result |
|---|---|
| the per-entry long names | **correct** — `emu_destlist.py` resolved 105 `'Depth'`, 106 `'Speed'`, 107 `'High-pass'`, 108 `'Width'` straight out of a running machine |
| the records' **page label**, word 13 | **`'Chorus'`** at `0x402105de`, in exactly the same form as Delay's `'Delay'` and Reverb's `'Reverb'` |
| the boot-built page descriptor | **exists** — `0x400c9e24` constructs `{name, entry list}` objects, `'Reverb'` at `0x42432f1c` and `'Chorus'` at `0x42432f48` |

So this is not a missing Chorus string. The string is there three different ways.

### The `+44` edit is exonerated, by naming the reads rather than by absence

Chorus is the only group whose records this work wrote, so it is the obvious
suspect and it deserves better than a shrug. §2 enumerated **all nine** consumers
of `+44`:

- **five filter-cascade sites** (`0x400397c8`, `0x40039ad0`, `0x40039cf2`,
  `0x40039ef0`, `0x400672fa`) — each is `btst #18` / `btst #17` / `btst #16`;
- **three `andil #0x70000` tests** (`0x40067502`, `0x400676e0`, `0x400679e2`) —
  the "is this a `DEST` record" question;
- **one getter** (`0x400dc32c`), which feeds the list builder's subset test.

Every one of the first eight reads **bits 16–18 only**. Chorus's `+44` went from
`0x00000000` to `0x00001e00`, which sets **bits 9–12** and leaves bits 16–18 at
zero. **So all eight return exactly what they returned before the edit**, bit for
bit. The ninth is the subset test, and that change is the feature.

The scope of that negative, stated: it covers every read of `+44` that §2's
resolution of the parameter-record base found — fifty `lea` and two `addal`
sites over the whole objdump. It would not cover a consumer that received a
record pointer as an argument from elsewhere; the getter is exactly such a
hand-off and its callers are the list builder's four.

This also agrees with the standing evidence: §15 records that the **identical**
`0x1e00` edit was flashed on 2026-09-12 and changed nothing.

### So what it most likely is, stated as a hypothesis

The FX groups were **never enumerated into a destination list before this
work**, so no section header for group 16, 17 or 18 has ever been drawn on this
instrument. The modal names a section by some lookup that has no answer for
those groups and falls through to entry 0.

The boot-built page descriptors make that concrete and plausible: their entry
lists legitimately contain **zeros** for empty positions on a page — Reverb's
array at `0x42432f20` holds `[123, 124, 125, 126, 127, 128, 0, 0, 130]` in
**stock**. A header that resolves its title by indexing one of those lists and
landing on a zero slot gets entry 0, and entry 0's short name is `ERR`.

~~**That would be a pre-existing gap newly exposed, not damage**~~ —
**REFUTED by the instrument, see §22.** Reverb and Delay draw `REV` and `DEL`
correctly, with the *same* zero-padded descriptors this paragraph blames.

### What is not established, and the one question that settles it

**Whether Delay and Reverb draw their headers correctly.** The owner named only
Chorus, but he was reporting what he noticed, not answering that question.

- **If all three show `ERR`**, the cause is generic to newly enumerated FX
  groups and the fix is one lookup, in one place.
- **If only Chorus does**, something distinguishes group 16 — it is the first FX
  group in rank order (11, before Reverb 12 and Delay 13), so it is the first
  header drawn after the transition out of group 15, and a first-transition bug
  is a different shape of fault entirely.

Those two need different fixes, and **one look at the modal tells them apart at
no cost**. Guessing between them would be a third build on a cosmetic defect,
which is the chase §18 already paid for once.

### Deliberately not fixed here

No build was made for this and **no gates were run, because nothing was built**.
The destinations work; the header is polish. The next step is one observation,
not a patch.

## 22. The `ERR` header: the zero-padding reading is refuted, and four leads are dead

Asked whether Delay and Reverb also draw `ERR`:

> "no, they show their correct short names (REV and DEL). That's why I reported
> chorus only."

**So §21's reading is wrong.** It said no FX section header had ever been drawn
and blamed the zero-padded page descriptors. Two of the three draw correctly,
with the same zero padding.

### Why it failed, because the failure is the reusable part

It **explained Chorus without predicting Delay and Reverb** — and the prediction
was available to ask for. §21 even wrote down that the two cases needed
different fixes and that one look would tell them apart, then offered a
mechanism that only covered one of them. A hypothesis that accounts for the
symptom you have, and says nothing about the cases you have not checked, has not
been tested by the symptom; it has been *fitted* to it. The discipline is the
same one `docs/PRINCIPLES.md` §19 asks for on negatives: say what the
explanation predicts elsewhere, then go and look.

### What is now measured, and what it kills

| lead | measurement | verdict |
|---|---|---|
| the `+44` edit damaged something | eight of `+44`'s nine consumers read **bits 16–18 only**; `0x1e00` sets bits 9–12 and leaves 16–18 at zero, so all eight return what they returned before, bit for bit | **exonerated, and this stands** |
| Chorus's header record was left out | entries 111 `CHR`, 120 `DEL`, 129 `REV` all carry `0x1e00` in `fxbrowser2`, 111 included | **dead** |
| the header records differ somehow | all three are structurally **identical** — handler `0x400e2ecc`, same word 1, range `0x7f00`, no NRPN, `+44` = 0 in stock. Only group, slot, default and word 10 differ, as they must | **dead** |
| the page descriptors differ | Chorus's entry list is `[105,106,107,108,0,0,109,110,112]`, Reverb's is `[123,124,125,126,127,128,0,0,130]` — both zero-padded, both excluding the `<Group> Mix Vol.` record. Symmetric | **dead** |
| the stock `Mix Volume` asymmetry — 112 has `+44` = 0 where 121 and 130 have `0x1e00` | real in **stock**, and **erased by this build**: `fxbrowser2` sets 112 to `0x1e00`, so in the built image all three groups have a capable `Mix Volume` record | **cannot explain a difference in the build** |

That last row is the one that matters and it is a logical point rather than a
new scan. The asymmetry the build was suspected of exploiting is an asymmetry the
build **removes**. For it to still be the cause, the header path would have to
read something cached from a source the record edit does not reach, and there is
no evidence of such a cache — the records are in the section and are read from
the patched image at boot.

### The accurate open defect

**The Chorus section header in the destination modal draws `ERR`; Delay and
Reverb draw `DEL` and `REV`. The cause is not known.** What has been ruled out is
above. What has not been found is **what the modal calls to name a section**:
the string objects the display-list builder at `0x40106502` hands to
`0x401170d8` are constructed *before* the per-entry loop, so the per-group text
must arrive either through `0x4019d140` or through the header object's own
construction, and neither has been read.

**Next instrument, named rather than run:** digikit's `tools/addrtrace.py` on
`0x401170d8`, which reports hit counts and registers at first hit **by running**
— the arguments at the moment a header is built are the answer, and reading more
disassembly is what the last three leads cost. That needs a panel event this
harness cannot yet produce, so it waits for a harness that can drive the modal.

### Why it stops here

The destinations work. This is the label above them, it changes no sound, and it
has already consumed three hypotheses. An accurate open defect is worth more
than a fourth guess, and a speculative fix would cost the owner a flash on
something cosmetic. **No build was made and no gates were run, because nothing
was built.**

## 23. The `ERR` is Elektron's group-name table, and `fxbrowser3` is one longword — 2026-09-23

**Found, fixed, gated.** `0x400dc3f0` is the group → **short name** lookup. It
answers `'SYN'` for groups 0..4, `'ERR'` for anything above 30, and otherwise
indexes a 26-longword table at `0x401f76f4` with `group - 5`. That table holds:

| group | slot | stock value | reads |
|---|---|---|---|
| 15 FX | `0x401f771c` | `0x40217641` | `FX` |
| **16 Chorus** | **`0x401f7720`** | **`0x40210c9e`** | **`ERR` — the out-of-range fallback's own pointer** |
| 17 Reverb | `0x401f7724` | `0x402107d2` | `REV` |
| 18 Delay | `0x401f7728` | `0x40210919` | `DEL` |

`0x402107d2` and `0x40210919` are not merely strings that happen to read `REV`
and `DEL`: they are **the exact pointers entries 129 `Reverb Mix Vol.` and 120
`Delay Mix Vol.` carry as their own short name** at record `+56`. Group 16's slot
does *not* hold entry 111 `Chorus Mix Vol.`'s `'CHR'` at `0x4021077c` — it holds
the fallback. The symmetry is exact everywhere except the one slot the owner was
looking at. Groups 19, 20, 22 and 31..34 read `ERR` too; nothing enumerates them.

`fxbrowser3` writes `0x4021077c` into `0x401f7720`. That is the whole fix: **two
bytes** different from the image already on the instrument.

### Why every one of §22's six leads had to fail

They were all about **records**, and the name is not on a record. It is on a
**group** table that no record edit can reach. And `emu_modalname.py` had
already measured that the modal's *construction* resolves no names at all — the
text is fetched when a row is **drawn**, which is the half nobody had run.

### The measurement, and its two controls

`scripts/emu_fxname.py` boots the machine and does two things. It calls
`0x400dc3f0(g)` for every group, and it constructs the destination modal for a
live `ParameterSet` and then calls each row widget's own label accessor
`0x40116e5e` — which is what the paint calls, so the string that comes back is
the string on the screen. Log: `out/emu-logs/gate_fxbrowser3.log`.

On `fxbrowser2`, the build the owner has:

```
entry 105 Chorus ( DPTH) -> 'ERR:DPTH'  table reads [16]
entry 113 Delay  ( TIME) -> 'DEL:TIME'  table reads [18]
entry 123 Reverb (  PRE) -> 'REV:PRE'   table reads [17]
```

On `fxbrowser3`:

```
entry 105 Chorus ( DPTH) -> 'CHR:DPTH'  table reads [16]
entry 113 Delay  ( TIME) -> 'DEL:TIME'  table reads [18]
entry 123 Reverb (  PRE) -> 'REV:PRE'   table reads [17]
```

Twenty-four rows, twenty-four table reads, groups `[16, 17, 18]`. The probe
**refuses to report Chorus at all** until groups 17 and 18 have come back `REV`
and `DEL` through the same call on both images, and until the draw has produced
text for a Delay row — §19's rule, and the rule this session broke once already
when `emu_mirror_base.py` read a pointer that had never been set.

### What the prediction said before the run, for all three groups

§22's lesson was that a mechanism which explains Chorus and says nothing about
Delay and Reverb has been *fitted* to the symptom. This one is read off one
table for all three and predicted each separately — 16 → `ERR`, 17 → `REV`,
18 → `DEL`, with 17's and 18's pointers equal to their `Mix Vol.` records' — and
then the run produced exactly that, including the pointer identities.

### Where the text is actually drawn, and what the "section header" is

The destination modal builds **one row widget per entry plus one per group**
(`0x401170d8`, section headers carry entry `-1`). The header's own label functor
resolves to the empty string `0x40218572` — measured, on both images — so the
**visible group name is not a separate header string at all**: it is the
`"%.16s:%.32s"` short form each row falls back to, `group:parameter`, built at
`0x40105b72` from `0x400dc3f0(group)` and the record's short name, inside the
row-label functor `0x40105a6c` that the list builder stores in every widget.

`0x400dc3f0` has exactly four callers and all four are named: `0x40105ace` (that
row label), `0x40106786` (the modal's row-activate callback), `0x400c24ee` (a
`DEST` value drawn as `%.4s` of the group name), and
`0x401072a8`, which stacks the group short name at y=`0x22` and the parameter
short name at y=`0x2a` as two `%s` lines. Every one of them reads group 16 as
`ERR` today and `CHR` after this build.

**Scope of that negative, stated:** every longword in section 3 whose value lies
within ±104 bytes of `0x401f76f4` — the table's own length — was listed. There
are two: `0x400dc406 -> 0x401f76f4`, the `lea` inside `0x400dc3f0`, and
`0x400dc266 -> 0x401f775c`, which is the **next** table (the 16 track names
`T1`..`T16`) starting where this one ends.

### The `%a0@(30,%d2:l)` trap, for the third time

The record's short name is at `+0x30` from the accessors' pre-biased base, not
`+30`: objdump prints an indexed displacement in **hex with no prefix**
(`FEATURE-PLAYBOOK.md` §2.6). Reading it as decimal points 18 bytes short and
yields a plausible-looking non-pointer. It cost ten minutes here; it has cost
this project more than that twice before.

### Gates

| gate | result |
|---|---|
| `check_coldfire` vs `out/lfo4-browser` | **pass** — 1,539 hits vs the 1,540 baseline; `--against`: `1539 shared ... those are its data, not this build's code` and `no scale-8 addressing`, **0 new**. Byte-identical to `fxbrowser2`'s figure |
| `dnfw inspect` | **21/21 `[ok]`**, including `container trailer HMAC-SHA256 reproduced` |
| build-time guards | 26 control sites asserted (9 of them new and specific to this edit), geometry 9/9, `verified: 158 bytes changed, every one inside a declared edit` |
| `emu_boot_check` from reset | **pass** — `booted and drew its UI (1 frame(s), control 1)`, `Safe to flash as far as booting goes`. **620,522,800 instructions, the same count as the stock control to the instruction** — which is what a data-pointer edge nothing reads at boot should look like. The control was re-measured because the emulator's fingerprint changed (`digikit-up/emu/dspboot.py` grew a `coverage=` option) |
| coverage of this build's own routines | **n/a, and it is not allowed to stand as a pass.** `fxbrowser3` writes no `symbols.json`, and `emu_boot_check` says so itself: *"a boot alone does not clear a build"*. The question it would answer — did the edited thing actually run? — is answered instead by `emu_fxname.py`, which calls the reader and draws the rows |
| the `ERR` itself | `emu_fxname.py`, above — this is the gate that would otherwise have been an "n/a" |

`fxbrowser3_DN2_1.11.syx`, sha256
`ed3d065735b933744d8b97173cf3a367ad1a62eb2b0bfda024e300db11340f0f`.

**Not flashed. Nothing goes near the instrument without the owner's go-ahead.**
On screen, after flashing: on a synth track, `[MOD]`, LFO1, turn `DEST` into the
FX range. The seven Chorus entries read `CHR:DPTH`, `CHR:SPD`, `CHR:HPF`,
`CHR:WDTH`, `CHR:DEL`, `CHR:REV`, `CHR:VOL` where they read `ERR:…` before.
Delay and Reverb must be **unchanged** — if either of them moves, the edit went
into the wrong slot.


## 18. The p-lock id ceiling is structural, and it is 106 — 2026-09-23

DNX measured the corpus and pointed the question back here, correctly: storage
cannot answer whether an id above 106 is usable, because its parser reads
`parameter: header & 0xff` with no bound at all, so its silence is not evidence.
**The bound is the firmware's own inverse map, and it is measurable.**

| | |
|---|---|
| forward map `0x401fcf20` | 100 longwords -- live slot -> p-lock id |
| inverse map `0x401fd0b0` | begins immediately after it |
| inverse entries 100..106 | `93, 95, 96, 97, 98, 78, 99` -- still slot numbers |
| **inverse entry 107** | **`0x4020ef38` -- a pointer. The table has ended.** |

**So the inverse map covers ids 0..106 and index 107 is already the next
structure.** An id of 107 would read a pointer as a slot number. The ceiling
DNX observed in 3,277 patterns is not a habit of the music; it is the table's
extent.

That is the same wall `csrc/lfo4/store.c` met one level down -- the two maps are
adjacent, so neither can grow in place -- and it has the same answer: **relocate
and divert**, the technique `build_lfo4_table.py` already uses for the parameter
table. Not free, and not new either.

### What DNX settled, and what it could not

**Settled from 2,041 explained records across 27 sources** -- gated so that an
unwritten slot's uninitialised flash could not be counted, which ungated
reported ids over 0..255 and tracks up to 255:

- ids run **1..106**, never 0, 94 distinct values, nothing above 106 ever;
- tracks run **0..13**, and **no written pattern anywhere carries a track above
  15**;
- **id 255 must not be used**: the unused-record marker is the header read as a
  `u16`, `0xFFFF` -- id `0xFF` with track `0xFF`. A firmware path testing only
  the id byte would read any id-255 record as unused.

**The risk it named, which storage cannot answer and our applier must:** every
one of the 2,041 records satisfies, with zero exceptions, that **every step a
record locks carries a trig on the track it names**. A `track = 16` record has
no track and therefore no step flag word. *If the scheduler fires locks from the
track's flags rather than from the lock record, a track-16 record never fires.*
That is the first thing to check before building anything.

In our favour: a track-16 record needs **no companion structure in the stored
file** -- the lock record is self-describing and there is no per-track lock
bitmap in storage. And `0xFF`, not 16, is the format's "no track here" marker,
so the sentinel cannot collide with it.

**Budget, uncosted until now:** the 80-record table is shared by all tracks and
allocated from slot 0 up. The deepest allocation seen in the corpus is **72 of
80**. FX locks would come out of that same 80.

**No reserved shape exists for FX in the lock table.** The one genuinely
reserved-looking space in the format is `kit+5900..5956` -- 28 slots, zero in
all 2,176 kits sampled, immediately after the compressor page -- but that is kit
space beside the FX *values*, not lock-table space. DNX's reading, offered as a
reading: Elektron put FX and Master outside the pattern record deliberately, so
anything here is an invention rather than an occupation -- which is an argument
for using the storage version field (the pattern record's first `u32`; 2, 3 and
4 exist in the wild), not against doing it.

**Two caveats to carry:** version 4 is measured on a 1.11 project captured
2026-09-22, so if new firmware moves the record version that fixture becomes
history; and five slots of that project carry a nonsense version word (two read
5, two `0x3FFFFFFF`, one `0x215C7F30`), which looks like residue in unwritten
slots rather than a format -- **but if 1.11 ever writes a version 5, that is
ours to confirm and DNX wants to know.**

### The loader clears the record: `track = 16` is dead, and 106 is confirmed twice — 2026-09-23

The section above ends by naming the risk the corpus could not settle: whether a
`track = 16` record ever reaches the applier. **It does not. The loader clears
it before the applier can see it.** DNX measured it on the owner's instrument,
with the owner's explicit authorisation given in DNX's own session, and the
write-up and both images are at
`dn_sysex/99_HardwareTest/dn2-fxlock-2026-09-23/track16-probe-findings.md`.

The design is worth repeating because it is the part we got right by accident of
argument: a write-and-read-back through the +Drive would have come back clean
and we would both have believed `track = 16` was allowed. The loader only runs
on a **load**, so the project was written to an empty slot, loaded on the front
panel, saved, and read back.

Two probes, one unusual field each:

| record | id | track | step | value | probes |
|---|---|---|---|---|---|
| 8 | 92 (`CHR`, known-good) | **16** | 1 | 100 | the track byte |
| 9 | **110** (above the ceiling) | 5 | 2 | 101 | the id byte |

**Both were cleared.** 8 bytes differ in 12,890,116 — four are the two probe
headers, four are the project id.

```
0x84f044   id  92 -> 255    G2 lock record 8, header
0x84f045   track 16 -> 255
0x84f146   id 110 -> 255    G2 lock record 9, header
0x84f147   track  5 -> 255
```

**Verified here, independently, from DNX's readback image:** at both addresses
the header reads `ffff`, and the 256 value bytes of each rejected record carry
exactly the payloads that were sent — `100` and `101`, still there beside the
zeros. So the rejection really is *mark unused*, not *wipe*: the loader frees
the slot using the format's ordinary `0xFFFF` marker and leaves the values
behind it untouched.

**Not verified here, and left as DNX's:** that the owner's eight FX-send records
survived byte-identical. That claim is what makes this selective rather than a
normalisation pass, and it is the load-bearing one. Reproducing it needs the
crafted image, which is not in the artefact folder as a raw `.bin`, and my own
attempt to walk the table geometry from the two known record addresses (stride
`0x102`, base = record 8 − 8·stride) landed on records that read `ffff` in both
files — so my base is wrong, which is a fact about my arithmetic and not about
DNX's result. Asked back rather than assumed.

### What it costs us

**`track = 16` cannot be the key.** The applier arithmetic that made it
attractive — `101·track + 17` landing on the FX/Master mirror block with no
change at all — is still true and still unmeasured at `0x400db092`, and it no
longer matters, because the record does not survive to reach it. A design keyed
on `track = 16` needs a **third** edit site: the loader's validation, on top of
relocating the inverse map and diverting the applier.

**106 is structural, now by two methods with no shared assumption.** Our inverse
map at `0x401fd0b0` covers ids 0..106 and index 107 is already a pointer
(`0x4020ef38`); a device clears id 110 on sight. Either alone would be a reading;
together they are a measurement, and both should be cited.

**What is not yet read, and is now the blocking question:** *what* the loader
checks. If it is a simple `track < 16` and `id <= 106`, both are two-byte
constants and in reach of the technique `build_lfo4_table.py` already uses. If
the check is a table lookup or a range derived from something else, it is not.
That is a static read on our side and nobody else can do it.

**One loose end, labelled a hypothesis by DNX and carried as one here:** the
device re-minted the project id on save, where `dn2-format.md` §2 recorded the
opposite in July. `TRACK16PROBE` was built from `TEST_FX_LOCK` and carried an id
already present in slot 9, so the plausible reading is that it mints on finding
a duplicate rather than on every save. Untested; one save of a project with a
unique id would settle it, and it costs a device write nobody has asked for.

## 24. Exposed to users: `fxmod`, the mod and the page — 2026-09-23

The feature worked on the instrument and existed only as a build script that
needs WSL, an m68k assembler and the owner's own image on a particular path.
That is not a feature anyone else has. It is now a mod and a page.

**The claim that makes it worth trusting:** `dnfw mods apply --mod fxmod`
produces a `.syx` whose sha256 is
`ed3d065735b933744d8b97173cf3a367ad1a62eb2b0bfda024e300db11340f0f` — **the same
file as `fxbrowser3_DN2_1.11.syx`**, byte for byte. `scripts/gen_fxmod_code.py`
composes the mod's data from `build_fxbrowser.compose`, the same function the
gated build comes out of, so users get the image that was measured rather than a
second implementation of it. `test/test_fxmod_mod.py` asserts that equality and
skips loudly rather than passing when the build output is absent.

`build_fxbrowser.main()` was split into `compose()` plus I/O to make that
possible; the split is byte-checked, and `build_fxbrowser3.py` still writes the
identical `.syx`.

| piece | where |
|---|---|
| the data | `scripts/gen_fxmod_code.py` -> `src/dnfw/mods/fxmod_code.json`, `site/js/mods/fxmod-code.js` |
| the CLI half | `src/dnfw/mods/fxmod.py`, registered in `src/dnfw/cli/mods.py` |
| the browser half | `site/js/mods/fxmod.js` |
| the page | `site/fx.html`, `site/js/app/fx-page.js` |
| parity | `scripts/js_fxmod_check.mjs`, run by `test/test_js_fxmod.py` |
| tests | `test/test_fxmod_mod.py` — 9, including byte equality with the gated build |

**Twenty-three edits, 179 bytes, 26 guards.** The guards are the sites the mod
reads and reasons from but never writes, and they include the three group-name
slots and the three records whose short names they share — §23's whole argument,
checked against the user's own file rather than asserted in prose.

**The site said something that had become false.** `destinations.html` told users
that Chorus and Master "stay closed, deliberately … for those the gate is a
separate enumeration, not this mask". True when written, and that separate
enumeration is exactly what this work opened. Both that page and the index card
now say so and link across. Master is still out, and both still say why.

**Rendered before it was believed.** `PRINCIPLES.md` §7 and the comment in
`destinations-page.js` that records a card rendering as `undefined` because a
field was read by the wrong name: the page was driven in Chrome with the stock
`.syx`, the 24 destinations drew in three labelled groups, the build verified
21/21 and offered `Digitone_II_OS1.11_fxmod.syx` at 2,387,616 bytes, and the
console was clean.

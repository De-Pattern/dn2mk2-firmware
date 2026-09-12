# A fourth LFO: what it takes, and an honest verdict

The goal is a 4th LFO on the Digitone II's vacant `[MOD]` page, behaving like
LFO1–3. This is the feasibility assessment after mapping the parameter table
(`docs/parameter-table-consumer.md`), its consumers, and the LFO page-view
class. Every claim here was read from a Gate-F-cleared MAIN OS 1.10E and
cross-checked against the bytes.

## Verdict

**Feasible, and the parameter table no longer needs relocating** — that was the
first read, and a better path was found. The table has **10 unused "ERR" filler
records** (ids 1-5, 11-14, 17-18 — plus id 0, the table's own unused slot), none
referenced by address, reachable only by id-indexing. A page-view's id list can
point to any ids, so LFO4 can **repurpose these dead slots in place**:
same-length edits to ten 60-byte records, no relocation, no base repointing, no
bound changes. The hardest cost in the original plan is gone.

**Corrected 2026-09-12 — the slot list was wrong, and so was the geometry.**
This section previously claimed fifteen dead slots at ids 1-5, **7-9**, 11-**15**,
17-18. Ids **7, 8, 9 are `Solo`, `Mute` and `Pattern Mute`** and id **15 is
`Active Track`** — live parameters whose *short* name happens to be `ERR`
because they are never drawn on a parameter page. Only the records whose **long**
name is also `Error` are dead. That leaves exactly ten usable slots for ten
parameters, so the list is not a preference and there is no spare.

The cause was an anchor off by one record — see "The Stage 1 corrections" below.

What remains is real but smaller: rewrite ten ERR records as LFO4's parameters
(copied from LFO3, relabelled), add a fourth page-view whose id list names those
ten ids, wire the `[MOD]` navigation to it, and confirm the **audio engine** can
run a fourth LFO at all. The last is the true open gate; the rest is patch-shaped.

## The change set, itemised

### 1. The parameter table — repurpose, do not grow

The table is a flat array, `record[id] = 0x401e29a0 + id*60` (1.10E), ids 1..320
— see `docs/modulation-mask.md` for the fifteen fields of a record. It ends at
320 with no slack, so it cannot be *grown*. It does not need to be. Its head
carries **10 unused records** whose long name is `Error` and short name `ERR` —
ids 1-5, 11-14, 17-18 — sitting among the real head entries (Machine Type id6,
Solo/Mute/Pattern Mute ids 7-9, Track Level id10, Active Track id15, Global Mix
Mode id16). Each dead one is a valid 60-byte record that just displays `ERR`,
and **none is referenced by address** (only by id-index), so overwriting one
changes nothing but what that id resolves to.

**A short name of `ERR` is not sufficient evidence that a record is dead** —
Solo, Mute, Pattern Mute and Active Track all carry it, because they are never
drawn on a parameter page. Require the *long* name to be `Error` too.

LFO4 needs ten parameter records. Take the ten dead ERR slots — ids
**1,2,3,4,5,11,12,13,14,17** — and rewrite each with LFO3's field layout: the
same handler pointers, ranges and flags, a `LFO4` page label, cleared controller
and NRPN numbers, and LFO4's modulation mask (`docs/modulation-mask.md`). Ten
same-length record edits. The page-view (below) points its id list at those ten
ids; they need not be contiguous.

This removes relocation, the 56 base repoints, and the bound sweep entirely. The
one caveat: confirm no existing page lists these ids (none should — they are the
`ERR` fallback), which a hardware boot plus a DNX project read settles.

### 2. The length bound — not touched

Because LFO4 reuses ids 1..18 rather than adding 321..330, every id stays inside
the existing `< 321` bound. The ~43 bound immediates (`#321`×32, `#320`×11,
`#311`×1) need no change at all. This is the whole benefit of repurposing over
appending.

### Alternative kept for later: grow the table by appending

Repurposing is the better path for *this* change, but the append/relocate
analysis is real and worth keeping — a larger change (more than the ten spare
slots, or a different table) would need it, and these facts hold regardless.

- **No slack after the table.** `record[id] = 0x401e29a0 + id*60` ends at id 320;
  the bytes immediately after are another lookup table. Ten new
  records (ids 321–330, +600 bytes) cannot be appended in place.
- **Relocation cost.** The table is ~19.3 KB (321 × 60). **56 sites in code hold
  an absolute literal pointing into its base** (53 at `0x401e29a0`, plus a few
  neighbours). Growing it means copying the table to a code cave, appending the
  records, and repointing all 56 base literals.
- **The bound is replicated.** The length is not stored; it is a bounds immediate
  in every accessor — `cmpi #321` at 32 sites, `#320` at 11, `#311` once.
  Appending past 320 means raising every one that guards a new id, exhaustively;
  each sits beside a `lea` of the table base.

The staged form of the append path was: (1) inert bounds sweep to prove the site
list, (2) relocate the table unchanged, (3) append the records, (4) page-view,
(5) MOD wiring. Repurposing collapses 1–3 into a single same-length patch, which
is why it is preferred here — but if the spare slots ever run out, this is the
route.

### 3. The per-LFO hardcoded id sites

Beyond the table, "three LFOs" is baked into code as literal ids. The clearest
is `LfoPageView`'s cell→id method (`0x40100a54`), which compares the fetched id
against **81, 91, 101** — the SPH ids of LFO1/2/3 — to apply the start-phase →
slew remap for random waveforms. A fourth LFO's SPH id must be added here, and
anywhere else that enumerates the three (the p-lock id derivation DNX found,
`4*slot + lfo`, is the sort of thing to re-check on hardware).

### 3b. The page id is contiguity-bound — a real constraint

`is_lfo_param_modulatable` (1.10E `0x400de34e`, **1.11 `0x400dbee6`**) decides
"is this an LFO parameter" as a **range test on the page id**:

```
addil #-26,%d3        ; page - 0x1a
moveq #2,%d0
cmpl  %d3,%d0
scc   %d0             ; (page - 0x1a) <= 2  ->  page in {0x1a, 0x1b, 0x1c}
```

Byte-identical in both builds. Widening it to `<= 3` admits page **`0x1d`**,
which is **Retrig**, not a fourth LFO. And `0x1e` is taken too — it is the
`None`/`---` destination entry (`docs/modulation-mask.md`). So the next free
page id is `0x1f`, and a contiguous range test cannot reach it without also
swallowing Retrig and None.

Three ways out, in rising cost:

1. **Renumber** so a fourth LFO is contiguous — moves Retrig and None, and
   every site that names those ids must be found. Cheap only if such sites are
   few, which is unverified.
2. **Replace the range test with an explicit `page == 0x1f ||`** — more bytes
   than the stock sequence, so it needs a cave at each site.
3. **Reuse an existing LFO page id** for a fourth page-view, distinguishing by
   parameter id instead — avoids the test entirely but may break anything that
   maps page id to LFO index.

This is a site the earlier drafts assumed was a simple bound raise. It is not.

### 4. A fourth page-view instance and its id list

`LfoPageView` (RTTI `0x402064a3`, typeinfo `0x401ece10`, vtable virtuals from
`0x401ecf7c`) is one class instantiated per LFO page. Its cell→id path
(`0x400634ea`) reads the page's id list indirectly through instance fields at
offsets 124 and 144 — so each LFO page carries (a pointer to) its own list of 8
ids. LFO1's is 75–82-ish, LFO2's 85–…, LFO3's 95–…. A fourth page needs its own
`LfoPageView` instance whose list points at the ten new ids (the ten repurposed ERR ids), plus its
page label. Constructing an object and its descriptor at boot is the main piece
of genuinely new code and data — a cave, or an unused existing structure.

### 5. Wire the fourth `[MOD]` page — no vacant slot exists

The `[MOD]` key cycles LFO1→LFO2→LFO3. **There is no pre-built vacant fourth
page** — checked 2026-09-11. The page-label strings `LFO1` (`0x401f7c0d`),
`LFO2` (`0x401f7c5d`) and `LFO3` (`0x40201cb0`) each occur once and are
scattered, not laid out as an extensible array, and **there is no `LFO4`
string anywhere in MAIN OS**. So the premise that Elektron left a ready fourth
UI page to fill is not how it is: the *vacancy* is in the data format (the sound
object reserves a fourth LFO slot; the p-lock space leaves `4*slot+0` free), not
in the UI. A fourth page needs a new `LfoPageView` instance, a new `LFO4` label
(no room to add a string in place, so this itself wants a cave or a spare
region), and the MOD navigation extended to admit and select it. This is the
new-code the feature cannot avoid.

## A staged plan

Each stage is independently flashable and observable, so a failure localises.

1. **Repurpose the table (same-length).** — **rebuilt 2026-09-12** after the
   correction below; the 2026-09-11 build was wrong and was never flashed.
   `scripts/build_lfo4_test.py` clones LFO3's ten records into the dead ERR slots
   (ids 1-5,11-14,17), clearing MIDI CC/NRPN so nothing collides, and builds
   `00_Resources/02_Builds/lfo4-test_DN2_1.10E.syx`. Verified by decoding the
   built `.syx` back and diffing the record grid: **237 bytes change**, ids
   1-5/11-14/17 become `SPD MULT FADE DEST WAVE SLEW SPH MODE DEP MULT` labelled
   `LFO4`, and **ids 6-10, 15, 16 and 18 are byte-identical** — the live head
   parameters are untouched, as is LFO3. The block's `+0x34` handler sequence is
   identical to LFO3's, which is the check that caught the second anchor error.
   A fourth
   LFO's parameter block now *exists* in the table, **labelled "LFO4"** -- an
   `LFO4` string was written into a verified-safe slot of unreferenced padding
   (`0x4026eff6`) and the block's page-label pointers repointed to it, so the
   records read as LFO4 rather than an LFO3 clone. Nothing displays them yet
   (Stage 2) and they are not proven to modulate (the engine gate). Flashing it
   is a **safety and mechanism test**: confirm the device still boots and its
   existing pages are unchanged.
2. **Add the fourth page-view.** An `LfoPageView` instance whose id list names the
   ten repurposed ids, plus the SPH-remap id (§3). This is the new-code step.
3. **Wire the `[MOD]` navigation** to the fourth page — the stage that makes it
   visible, and the real UI test.
4. **Confirm the engine** (§ below) actually generates a fourth LFO and applies
   it to the chosen destination. If the audio engine is hardcoded to three LFOs,
   the parameters will show but not modulate — that is the gate to prove before
   calling it done.

Stage 1 is within reach right now with the existing patch model. Stages 2–3 need
a code-cave applier (`patch/cave.py`, the roadmap's Phase-2 mechanism) and the
page-view / MOD-navigation reads below. Stage 4 is the make-or-break.

## The Stage 1 corrections, recorded because they nearly reached hardware

The 2026-09-11 Stage 1 build was wrong **twice over**, and both errors are the
same shape: an anchor off by a fixed amount, producing output that looked right.
Neither build was flashed.

### First: the anchor was 0x38 bytes too high

`docs/parameter-table-consumer.md` anchors the table as
`record[id] = 0x401e29d0 + id*60`, which is correct **for the field it was
derived from** — the short-name pointer the page renderer reads first. That
address is `0x38` bytes into the record. The build script took it as the record's
*first* byte, so:

- every other field it edited (`+40` controller, `+44` NRPN, `+56` page label)
  actually belonged to **`id + 1`**;
- every 60-byte clone **straddled two records**, carrying the tail of one and
  the head of the next;
- because the target ids were not contiguous, those halves did not stitch back
  together across the gaps.

The result overwrote parts of `Machine Type` (id 6), `Track Level` (id 10) and
`Solo`/`Mute`/`Pattern Mute` (7-9) — live parameters. It was never flashed.

**Why it passed its own checks.** The script guarded by reading the short name
at the anchor and requiring `"ERR"`, which is true at the anchor under *either*
reading, and true of Solo/Mute/Pattern Mute as well. The build then verified
cleanly end to end — compression, content checksum, HMAC, window — because every
one of those checks is about the *container*, and the container was perfect. A
green integrity check says the file is well-formed, never that it is correct.

**What catches it.** A wrong anchor into a dense table still yields plausible
strings. The discriminating probe is a **page boundary**: under the correct
layout id 84's page label is `LFO1` and id 85's is `LFO2`; under the off-by-one
layout id 84 reads `LFO2`. `_check_geometry` in `scripts/build_lfo4_test.py` now
probes five such positions and refuses to run if any disagrees, and the rebuilt
firmware is diffed against stock record-by-record rather than by byte count.

### Second: the record start was 8 bytes too low

The fix above moved the anchor to `base - 8 + id*60`, reasoning that the two
fields before the page id belonged to the record. They do not. The LFO parameter
dispatch at `0x40035f32` (1.10E) computes its per-parameter handler as
`base + 0x34 + id*60` and jumps through it, which fixes the record start **at**
the base — and fifteen 4-byte fields then close the 60 bytes exactly, with the
handler at `+0x34` and an always-empty unit string at `+0x38`.

The consequence of being 8 bytes low was narrower but real: every field edit was
still correct (they were expressed relative to the base), but each 60-byte clone
carried **the previous record's handler pointer**. The rebuilt LFO4 block would
have had LFO3's parameters wired to the wrong handlers.

**The probe that settles it**: LFO1, LFO2 and LFO3 are the same ten parameters,
so their handler sequences must be identical. They are, under the correct
boundary; under the 8-low boundary LFO1's first slot picks up id 74's handler and
LFO1 disagrees with the other two. `_check_geometry` now asserts this.

### The lesson

This is the same class of error as the `+30`/`0x30` radix mistake in
`docs/engine-state.md`: a small fixed offset, a result that looks right, and no
check that could tell the difference. Three instances now. The lesson
generalises — **an anchor is not verified until it has been tested somewhere its
neighbours differ**, and the cheapest such place is a repeated structure that
must agree with itself.

## Code-cave space — a real constraint on the UI stage

Stage 2 (a page-view, and any new code) needs free space to inject into, and the
obvious free space is not free. MAIN OS ends in a **64,908-byte run of zeros
from `0x402e1bf4`, but that is the `.data`/BSS initializer** -- the startup
routine copies `0x402e2000` onward to SDRAM at `0x80000000` and zero-fills BSS
there (`docs/memory-map.md`). Overwriting it changes the program's initial RAM
state, and appending after it risks the heap that lives above the SDRAM data. So there is no large safe cave in the trailing zeros, and growing
the section needs the MAIN OS memory map read first.

What *is* usable: **small runs of unreferenced padding inside the data region**
(before the BSS) -- e.g. ~1 KB zero runs around `0x4026e000`, with no code
references. The `LFO4` string above lives in one (`0x4026eff6`), proving the
technique. These are big enough for strings and small tables, but a full
page-view instance is a larger ask that the memory-map read must place safely.
`patch/cave.py` should therefore distinguish unreferenced padding (safe for
small data) from BSS (never) and from a section-grow (needs the memory map).

## The audio engine — half of this gate is now closed

**2026-09-12, measured on hardware.** A two-byte change to one parameter
record's modulation mask made **Portamento Time** — a parameter Elektron wired
to no modulator at all — both appear as an LFO destination and **actually
modulate** (`docs/modulation-mask.md`).

So the engine's **apply** path is generic and data-driven: it resolves a
destination index and applies, with no per-parameter special-casing. A fourth
LFO's *destinations* would therefore need no engine work.

What remains of this gate is narrower and sharper: **can the engine run a fourth
LFO generator?** Whether the tick advances an array of N phases or three named
instances is the single remaining unknown on the LFO4 path. Everything below
was written before that result and should be read with it in mind.

### The revised shape of the job

| Piece | Status |
|---|---|
| Storage — a reserved fourth LFO slot in the sound format | **Done by Elektron** (DNX) |
| Destination masks — the fourth rank already on every modulatable parameter | **Done by Elektron** (`docs/modulation-mask.md`) |
| Modulation apply — generic over the parameter index | **Confirmed on hardware** |
| Parameter records — ten dead ERR slots to repurpose | **Built**, `scripts/build_lfo4_test.py` |
| Enumeration — getting the records into the set the LFO walks | **Solved, and it is a data edit** (`docs/parameter-set-tables.md`) |
| **Runtime parameter indices** — eight contiguous slots | **No room.** Slots 0, 65 and 100 all resolve to engine index 0; only 65 is repairable (`docs/engine-index-map.md` §6b) |
| **The page id** — a contiguous range test `(page - 0x1a) <= 2` | **Blocked.** `0x1d` is Retrig, `0x1e` is `None` |
| **A fourth page-view and `[MOD]` navigation** | Not started; needs a cave |
| **The generator** — can the engine run four? | **Unpatchable, and now directly testable.** Its code is not in this file (`docs/engine-index-map.md` §9), but its index space reserves a complete fourth lane — and `scripts/build_lfo4_probe.py` asks it |
| **The runtime slot space** — eight slots to give it | **THE gate.** 1–2 free of 101 |

The two hard structural problems are now the runtime index space and the page
id, not the parameter table — which is the opposite of where this document
started.

**The enumeration came off the list on 2026-09-12.** It had looked like the
worst of them: the destination list is built by walking a `ParameterSet` whose
slot→id map the code reads from `0x42c64b3c`, an address outside the loaded
image, so the table could not be read at all. It turns out to be **BSS, built at
boot** by `param_set_tables_build` (1.11 `0x400dc4d0`) out of two fields of each
parameter record — `+0x00` page id and `+0x04` index-in-page. Which set a
parameter belongs to, and which slot it takes, are therefore **editable data**,
not compiled-in tables. Full reading in `docs/parameter-set-tables.md`.

That same reading sharpens the index problem rather than easing it. The sound
slot table is 101 entries wide and the free slots are exactly **65 and 100** —
the 25–68 gap in it is not free, those slots are served by the machine-type
table `0x42c64d18` and the filter-type table `0x42c64cd0`. Two free slots
against eight needed. This is now a *measured* shortfall with a named mechanism,
where before it was a count.

## The audio engine — the original analysis

Everything above is the **control and UI** side: making a fourth LFO's
parameters exist, show, and be editable. Whether a fourth LFO actually
*modulates* is a separate question in the sound engine. The DN2's synthesis runs
on a SHARC DSP (the `Digisharc` classes are its interface), and how many LFO
generators a voice runs — a constant, or an array — is not yet established.
DNX verified from hardware captures that the persisted sound object's LFO grid
is `30 + 8*param + 2*lfo`, with LFO1/2/3 at strides 30/32/34 and **the fourth
slot of each group of eight unused** — "there is room for a fourth LFO here too"
(`DNX/docs/dn2-format.md`). So the *storage* side is settled: a fourth LFO's
settings already have a reserved home in every sound.

### RETRACTED 2026-09-12: "the engine is on ColdFire"

This section used to claim the LFO computation was settled as ColdFire-side,
on this argument: *"When an LFO modulates a parameter the DN2 shows that value
moving on the parameter page, and the page is drawn by MAIN OS."*

**The premise is false.** The device's owner, who plays it: *"Interestingly, it
doesn't. Only modulation that actually moves visually values is external MIDI
modulation."* Being able to see internally-modulated values move has been a
long-standing request to Elektron.

There is a plausible design reason, and it is worth writing down because it
constrains any "show the modulation" feature we might be tempted by later: if
the displayed value followed the LFO, then arming live record while a sequence
plays would capture that movement as parameter locks, **recording the modulation
on top of itself**. Baking an LFO to p-locks deliberately is a real feature idea
(`docs/ideas-backlog.md` §5) — having it happen by accident is not.

So the argument is withdrawn, and with it the conclusion. **Where the LFO is
computed is open again**, and the surrounding evidence now leans the other way:

- no smooth curve table exists in *any* section of the firmware
  (`docs/data-sections.md`), which is what a table-driven waveform would need —
  though triangle, saw, square and ramp need no table, and the owner's read is
  that "all forms are computed/derived live", which would leave no table either
  way. So this is weak evidence, not strong;
- there is **no SHARC program anywhere in the update**, which cuts against a
  DSP-side engine — unless the DSP runs from its own never-updated flash;
- the one piece of Elektron prior art that implements LFO *generators*,
  octabam's reverb, puts them on the **DSP** — on a different and much older
  device, so a hypothesis only (`docs/octatrack-lfo-prior-art.md`).

- **A hardcoded 3-LFO site is found in the engine path.** The LFO speed handler
  `0x40035f32` carries `if (uVar1 < 3)` beside its `case 0x1e` (offset 30, the
  LFO block). That is one of the per-LFO count sites this document predicted —
  the kind of `< 3` bound a fourth LFO must raise. This still stands; it is a
  parameter-side site and does not depend on the retracted argument.

The read path described below was also read as reaching "the current,
already-modulated value". Since the display does **not** move under LFO
modulation, it more likely reaches the *set* value plus external-MIDI
modulation. Treat that chain as unverified until re-read:

> page renderer `FUN_40016f38` → value getter `FUN_40064786` → resolver
> `FUN_400635d0`, reading engine state at `+0x4f2e0` (1.10E) / `+0x4f358`
> (1.11) via a `+0x28` vtable method.

**The write-side tick remains the target**, and the cheapest way to settle which
CPU it runs on is now the *external MIDI* path: that modulation demonstrably
does move the display, so it is ColdFire-side and its write into engine state
can be traced. Whatever writes the value for external MIDI modulation is either
the same machinery the LFO uses, or proof that the LFO uses different machinery
— and either answer is progress.

## What is not yet known, and is next

- **The engine LFO count** (above) — the make-or-break.
- Does the `[MOD]` navigation already allow a fourth page? (Read the MOD-key
  handler and the page count it uses. The premise that Elektron left a vacant
  slot, if true, shrinks Stage 3.)
- How a `LfoPageView` instance is constructed and given its id list (the fields
  at offsets 124/144), so a fourth can be built — trace the vptr writers
  `0x40101306` and `0x401a2aea`.

The verdict stands and is better than the first read: the table is now a
same-length patch, not a relocation. The remaining work is a page-view, the MOD
wiring, and — first — proving the engine can run a fourth LFO.

## Closed leads — the generator hunt, 2026-09-12

Keeping these on the record because a closed path is a signal
(`docs/PRINCIPLES.md`): each of these looked like a fourth modulator and is not,
and knowing that stops the next session re-finding them.

### `MOD4` and `modTarget_t[4]` are the MOD SETUP destination slots

Two things in the shipped 1.11 image read, at first sight, like a dormant fourth
modulator:

- a **four-entry label array** at `0x402038c0` — `{MOD1, MOD2, MOD3, MOD4}` —
  sitting immediately before `ModSetupView`'s own mangled symbol data, read at
  `0x40107850` behind the guard `moveq #3,%d0; cmpl %d3,%d0; bcs bail`, i.e.
  indices **0..3**;
- the RTTI types `Value<Digisharc::modTarget_t[4]>` and
  `ValueWithMirror<Digisharc::modTarget_t[4], Digisharc::modTargetStorage_v0_t[4]>`
  (`0x4021e828`, `0x4021e84d`) — an array of **four** modulation targets, in a
  type that is mirrored to the DSP.

**Both are existing shipped functionality.** Device fact from the owner,
2026-09-12: *"For each modulation input (velocity, mod wheel, etc) there are 4
modulation destinations."* So the four are the four destination slots of one
modulation source on the MODULATION SETUP page, `modTarget_t[4]` is that array,
and `MOD4` is its fourth label. Nothing here is dormant and nothing here is an
LFO. **Lead closed.**

The general shape of the error is worth keeping: *a count of four in a device
with three LFOs is not evidence of a fourth LFO.* This is
`docs/learn-the-device-first` in practice — the count was real, the
identification was a guess, and one sentence from the instrument settled it.

### The MOD1/MOD2/MOD3 naming is a hardcoded cascade, not a table

`docs/modulation-mask.md` records a filter→name mapping at `0x40106a08`. Read as
instructions it is **three `pea` of string literals**, not an indexed table:

```
40106a22:  pea 0x4021ba7b      ; "MOD3"
40106a34:  pea 0x4021ba71      ; "MOD1"
40106a46:  pea 0x4021ba76      ; "MOD2"
40106a4e:  movel %a2@(228),%d7 ; default arm
```

The three-entry run at `0x401f7748` that also holds `MOD1 MOD2 MOD3` is a
different list — `CC, CC, MOD1, MOD2, MOD3, TRIG, META, V1, V2, V3` — and is not
what this code reads. So **naming a fourth modulator needs a code cave**, not a
data edit: there is no table to extend. Small, but it moves a task from the
"data edit" column to the "cave" column.

### There is no LFO generator class in MAIN OS

Scanning every mangled and RTTI name in 1.11 for `Lfo`/`Modulat`/`Oscill`/`Phase`
yields **`LfoPageView`** (the page UI), its `shared_ptr` plumbing, and
**`ModulationCopy`** (the copy/paste/clear buffer behind `COPY MODULATIONS`).
That is all. No LFO object, no phase accumulator type, no waveform generator.

Taken with the earlier dead ends — no waveform tables anywhere, `+0x34` is a
value formatter, `FUN_400d6360` is the SysEx dispatcher — this now points hard
at the generator living **outside MAIN OS**, on the DSP side, with the ColdFire's
role limited to mirroring `Digisharc::*` state to it. The `updateMirror` methods
(`Sound`, `Kit`, `Track`, `VoiceConfig`, `FxSetup`, `Pattern` …) are that
boundary, and they are the thing to read next: they are where the control side
hands the engine its parameters, and whatever the engine is told about LFOs
passes through them.

**That reframes the remaining question.** It is no longer "find the tick in this
image" — it is "find what MAIN OS *tells* the engine about LFOs, and whether the
shape of that message has room for a fourth." That is answerable in this image.

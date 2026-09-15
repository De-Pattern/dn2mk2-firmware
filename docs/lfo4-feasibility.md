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

> **WITHDRAWN 2026-09-12 — see `docs/engine-index-map.md` §15.** What follows was
> written when the storage-offset map was mistaken for engine addressing. The
> engine side is **not** finished; it is unknown again.
>
> ~~The engine side is finished (2026-09-12), and it opened outward.~~ The audio
> engine **does** implement a fourth LFO — confirmed on hardware by
> `scripts/build_lfo4_probe.py`, which re-pointed LFO3 at the engine's reserved
> lane and heard it still modulate (`docs/engine-index-map.md` §11,
> `docs/flashing.md`). The engine's code is not in this firmware file and cannot
> be patched, so this was the project's worst-case risk: an unreachable engine
> that might only run three. It runs four.
>
> **Everything left is on the control side**, and the single structural problem
> is the runtime slot space: a fourth LFO needs eight slots and there is one
> repairable free slot. See §11 of `docs/engine-index-map.md` for the five
> structures that bound it — four are tractable, and the sound object's own size
> is the one still unmeasured.

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
| **The generator** — can the engine run four? | **YES, and they coexist — confirmed on hardware 2026-09-12.** LFO3 driven through the reserved lane still modulates (§11), and LFO2 on lane 4 runs independently alongside LFO3 on lane 3 (§14). No engine-side unknowns remain |
| **The runtime slot space** — eight slots to give it | **THE gate, and now the only one.** Measured: the sound object's value array is exactly 101 entries and sits flush against the machine-type byte at +0xde, so it cannot grow in place (`docs/engine-index-map.md` §13). The route left is hooking the choke points to serve extra slots from separate RAM |

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

---

## §3b revisited, 2026-09-15: the page-id blocker is priced, and renumbering looks like the route

§3b above called the contiguous range test *"a site the earlier drafts assumed
was a simple bound raise. It is not."* That stands. But it left the three ways
out unpriced, and said of the renumbering option: *"Cheap only if such sites are
few, **which is unverified**."*

**It is now priced.** Renumbering is six single-byte code edits and 23 data
longwords — but the part that makes it safe is still unverified, and the section
below is careful to say which half is which.

### The range test is replicated six times, not once

Scanning for `addil #-26,%dN` — the `page − 0x1a` form §3b quotes — finds eight
sites. **Six** are the same test; two are not, and only reading them says so:

| Site | Shape | Bound |
|---|---|---|
| `0x400dbf34` | `moveq #2` / `cmpl` / `scc` | 2 — `is_lfo_param_modulatable`, the one §3b documented |
| `0x400dc6ba` | `cmpl %d1,%d6`, `%d6` set by `moveq #2` at `0x400dc6b8` | 2 |
| `0x4012a83c` | `cmpl %d0,%d1`, `%d1` set by `moveq #2` at `0x4012a83a` | 2 |
| `0x4012abca` | `moveq #2,%d2` / `cmpl` | 2 |
| `0x4012af7e` | `cmpl %d0,%d6` | 2 |
| `0x4012af9c` | `moveq #2,%d6` / `cmpl` | 2 |
| `0x4017a998` | `moveq #20` / `cmpl` — a **21-page** range | **not this test** |
| `0x401cf3f6` | `%fp − 26`, beside `%fp − 34` and `%fp − 30` | **not this test — a stack local** |

Several take the bound from a register rather than a literal, but in every case
checked the register is loaded by a `moveq #2` in the preceding instruction. **The
bound is a literal 2 in six places.**

`0x401cf3f6` looked like a seventh until it was read: it computes `%fp − 26`
between `%fp − 34` and `%fp − 30`, three stack-frame locals. It is not a page
test, and it is the first sign of how noisy this instrument is.

A sibling test sits immediately above one of them, at `0x400dc69a`:
`(page − 0x16) ≤ 3`, pages `0x16`–`0x19`, dispatching to a different
`ParameterSet` table at `0x42c647ac`. So page groups are handled as contiguous
ranges throughout — which is the whole reason contiguity matters.

### Nothing found names Retrig or None — but the scan found nothing reliably

The obstacle to renumbering was that moving Retrig (`0x1d`) and None (`0x1e`)
means finding every site that names them. Scanning every compare-and-subtract
immediate form, and then **reading each hit** rather than counting it:

| Page id | Raw hits | Survived reading |
|---|---|---|
| `0x1a` LFO1 | 10 | **8** — 6 range tests plus `cmpil #26` at `0x401783b0` and `0x40178402` |
| `0x1d` **Retrig** | 1 | **0** — `0x400b8594` is `%a1 − %d7` pointer arithmetic |
| `0x1e` **None** | 2 | **0** — `0x400d338a` is a loop bound; `0x401cf3f0` is the stack local above |

**Every hit for Retrig and None was a false positive.** Four hits, four
unrelated pieces of arithmetic. The scan's precision on this question is zero,
and that is the number to keep in mind when reading what follows.

And on the data side, indexing `record+0x00` across all 320 parameter records:

| Page | Records |
|---|---|
| `0x1a` / `0x1b` / `0x1c` | **10 each** — LFO1, LFO2, LFO3 |
| `0x1d` Retrig | **22** |
| `0x1e` None | **1** |

### So the two options, priced

**Option 2 — an explicit `page == 0x1f ||` at each test.** The stock sequence is
6 + 2 + 2 + 2 bytes; an added disjunct does not fit, so each site needs a detour.
That is **seven caves**, not one. Workable, and seven times the surface for a
silent failure.

**Option 1 — renumber so LFO4 is contiguous.** Give LFO4 page `0x1d`, move Retrig
to `0x1f` and None to `0x20`. Then:

| Change | Count | Kind |
|---|---|---|
| range-test bound `moveq #2` → `moveq #3` | 6 | **one byte each**, in place |
| Retrig records' page id `0x1d` → `0x1f` | 22 | data, in the shipped parameter table |
| None record's page id `0x1e` → `0x20` | 1 | data |
| LFO4's own 10 records at page `0x1d` | 10 | data — **already built**, `scripts/build_lfo4_test.py` |

**Six single-byte code edits and 23 data longwords, with no cave at all** — *if*
nothing else names Retrig's or None's page id. That is a different project from
six caves, and on present evidence it is the route to take. But see the gaps
below before believing the number: the evidence that nothing names them is a
scan whose every positive hit, on inspection, was something else.

### What this does not establish

Two honest gaps, and the first is the one that could sink it:

1. **Only compare-and-subtract *immediate* forms were scanned, and that
   instrument is demonstrably bad at this question.** It returned four hits for
   Retrig and None and **all four were unrelated arithmetic** — `addil #-29` is
   as likely to be a structure offset as a page id. It also sees only one
   spelling: a `moveq #29,%dN` followed by a register compare would be missed
   entirely, and there are 63 `moveq #29` sites, almost all ordinary constants.
   So **"nothing names Retrig" is what this scan failed to find, not something
   it established.** `docs/PRINCIPLES.md` §19, in its sharpest form yet: this
   negative is worth very little, and the plan above rests on it.
2. **Page ids may appear in tables as data outside the parameter records** — a
   page-order array for `[MOD]` navigation, for instance, is exactly the sort of
   thing that would exist and would not be caught by either scan above.

### Two corrections made while building the experiment

**Page `0x1d` is not Retrig.** §3b says so, and the record count of 22 appeared
to confirm it. It is the whole **sequencer/trig group**, spanning three labels:
ten unlabelled TRIG parameters (`NOTE VEL LEN uTM COND AMP.T FLT.T LFO.T PROB
FILL`), four `Retrig` (`RTRG VFAD LEN RATE`) and eight `Euclidean` (`PL1 PL2 EUC
RO1 RO2 TRO OP LEN`). The count matching is exactly what made the wrong label
easy to keep. It changes the experiment's blast radius from one small menu to
the TRIG page and its p-lock parameters, and the observation list has to cover
all three.

**The parameter table is 321 records, not 320**, and a first reconnaissance that
assumed 400 reported page `0x1f` already in use. It was reading past the end of
the table. Bounded by the located count, the page ids in use are `0x00`..`0x1e`
with gaps at **`0x04`** and **`0x0c`**, so `0x1f` is free and is the next id
above the highest in use. The two gaps are noted because they are free page ids,
but they are not contiguous with `0x1a`–`0x1c` and so do not help a range test.

### The build exists: `page-renumber-test_DN2_1.11`

`scripts/build_page_renumber_test.py` moves page `0x1d` to `0x1f` **and changes
nothing else**. Verified offline:

- `dnfw inspect` — every transport checksum, every stream sum, the content
  checksum and the HMAC-SHA256 trailer reproduce;
- a section-by-section diff against stock — **22 bytes differ, all in section 3,
  every one of them `0x1d` → `0x1f`, every one at offset `+0x00` of a 60-byte
  record.** Sections 2, 4, 5, 7 and 8 are byte-identical and no length moved.

The script refuses to write unless the table locates by signature, the LFO1/2/3
formatter blocks agree, LFO1/2/3 are still on pages `0x1a`/`0x1b`/`0x1c`, page
`0x1d` holds exactly the 22 records in exactly the three labelled groups above,
and the destination id is unused and above the highest in use.

**What to look for, in order** — the first failure makes the rest moot:

1. it boots;
2. the TRIG page draws `NOTE VEL LEN uTM` with normal values;
3. a trig p-lock takes and displays;
4. `Retrig` works;
5. `Euclidean` works.

All five pass → nothing else names the page id, and the next build is the six
`moveq #2` → `moveq #3` edits plus LFO4's ten records. Any of 2–5 fails →
something maps page id to page by a route the scans did not see, renumbering is
dead, and option 2's six caves is the route. Either answer is worth the flash.

**Not flashed.** Nothing reaches the instrument without the owner's go-ahead and
a named transport, and `docs/flashing.md` records that the recovery path needs a
physical MIDI DIN. **Back up the +Drive first** — page ids are believed to be a
runtime grouping rather than part of the stored format, but that belief is
untested, and a wiped +Drive is not recoverable from anything this project
holds.

---

**The reasoning that produced this build.** Renumbering is a pure
data edit for 23 longwords plus six single-byte code edits, all of which the
existing pipeline can already produce and verify offline. Flashing a build that
moves Retrig to `0x1f` and **nothing else** answers both gaps in one
observation: if Retrig still works and still draws its 22 parameters, nothing
else named its page id. That is one flash against an unbounded static search,
and `docs/flashing.md` records that this project has twice spent flashes on
assumptions it could have tested first.

---

## What the flash answered, 2026-09-15: the page id routes a parameter to its store

**The probe failed, and it failed usefully.** `page-renumber-test_DN2_1.11` was
flashed. The device boots and the moved pages still **draw** — but every moved
parameter reads **zero** instead of its record default, and **no edit reaches
the sequencer**.

| Parameter | Record default (`+0x10 >> 8`) | Read on the device |
|---|---|---|
| `NOTE` | 60 | **C0** — the bottom of the range |
| `PROB` | 100 | **0%** |
| `LFO.T` / `FLT.T` | 1 (on) | **off** |
| `VFAD` | 64 (the bipolar centre) | **−64** — its minimum |
| `RATE` | 12 | **blank** — below the first enum entry |

Not the defaults. **Zero**, rendered through each parameter's own formatter. And
`PTIM` (40) and `PORT` (off) — records that were *not* moved — read normally, so
the damage is exactly the 22 moved records and nothing else.

### Why: the routing cascade ends in an exact-match chain

`param_set_tables_build` assigns every parameter record to a `ParameterSet`
table **by its page id**, through a cascade of contiguous range tests:

| Pages | Table |
|---|---|
| `0x00`–`0x04` | `0x42c64d18` |
| `0x05`–`0x0a` | `0x42c64cd0` |
| `0x0b`–`0x0f` | `0x42c64b3c` (conditional) |
| `0x10`–`0x15` | `0x42c649a8` |
| `0x16`–`0x19` | `0x42c647ac` |
| `0x1a`–`0x1c` | the LFO pages — conditional, into `0x42c64b3c` / `0x42c647ac` |

and then, at `0x400dc71e`, **it stops being a cascade and becomes an exact
match**:

```
0x400dc71e  moveq #29,%d1        ; page == 0x1d ?
0x400dc720  cmpl %d0,%d1
0x400dc722  bnes 0x400dc74a      ;   no -> try 30
0x400dc724  lea 0x42c64940,%a1   ;   YES: the TRIG group's table
   ...
0x400dc74a  moveq #30,%d6        ; page == 0x1e ?
0x400dc74c  cmpl %d0,%d6
0x400dc74e  bnew 0x400dc7ea      ;   no -> FALL OUT, no table at all
```

Page `0x1f` matches neither 29 nor 30, so the 22 records **fell out of the
builder and were never given a slot in any `ParameterSet`**. They keep their
name, range and formatter, because those live in the record — so they draw. They
have no backing store, so they read zero and writes go nowhere. That is
precisely what the device showed, field for field.

### So the negative is refuted, exactly as suspected

§3b revisited said the renumbering plan rested on *"nothing else names Retrig's
page id"*, that the scan producing that negative had **zero precision**, and
that the honest move was to ask the device rather than scan harder. The device
said **no**: `0x400dc71e` names the page id as a bare `moveq #29`, in a form no
scan for "page-id compares" would ever have singled out from 63 others.

This is `docs/PRINCIPLES.md` §19 paying for itself. The plan was published with
its weakest link labelled, the experiment was aimed at that link, and one flash
settled it.

### And renumbering is not dead — it is one byte short

The exact-match constant is the fix. `moveq #29` at `0x400dc71e` is **one byte**
(`72 1d`, file offset `0x0dc31e`). Changing it to `moveq #31` routes page `0x1f`
into `0x42c64940` exactly as `0x1d` was routed.

So the full cost of a real fourth LFO's page-id problem, revised:

| Change | Count | Kind |
|---|---|---|
| TRIG group's records `0x1d` → `0x1f` | 22 | data |
| **routing constant `moveq #29` → `moveq #31`** | **1** | **code, one byte — new** |
| LFO range-test bound `moveq #2` → `moveq #3` (six sites) | 6 | code, one byte each |
| LFO4's own ten records at page `0x1d` | 10 | data, already built |

Still no cave. **The next probe is this build plus that one byte**, and it is
decisive: if the TRIG, Retrig and Euclidean parameters come back to life, the
page-id route is proven end to end and LFO4's page is free.

**What it does not yet cover.** The LFO branch routes conditionally into tables
that already exist. Whether a fourth LFO needs its own `ParameterSet` table, or
can share as LFO1–3 do, is **not** established and is the question after this
one — `docs/parameter-set-tables.md`.

---

## v2, and the diagnosis: the moved records fell through to the *sound* parameter set

**v2 failed, and it failed identically to v1.** The one-byte routing fix at
`0x400dc71e` — which does put page `0x1f` into `0x42c64940` exactly as `0x1d`
was — **changed nothing observable**. Same wrong values, same dead edits.

That null result is the most useful thing the second flash produced: **getting a
record into the `ParameterSet` table is not the binding that decides where its
value lives.**

### What the values actually are

The owner also found, on v2, that p-locking `PROB` produces **modulation
unrelated to probability** — and noted it was probably present on v1 too and
simply not looked for. It was. Both builds behave the same.

Read `record+0x04` (parameter-id-within-page) for each moved record and look it
up in the **sound** index space (`docs/engine-state.md`: 1–8 LFO1, 9–16 LFO2,
17–24 LFO3):

| TRIG param | `record+0x04` | Sound slot at that index | Its default | Observed |
|---|---|---|---|---|
| `NOTE` | 0 | *(no slot — index space starts at 1)* | — | **C0** (zero) |
| `VEL` | 1 | **LFO1 `SPD`** | **112** | **112** |
| `LEN` | 2 | LFO1 `MULT` | 1 | 0.188 |
| `PROB` | 12 | **LFO2 `DEST`** | 0 | **0%**, and p-locking it **moves LFO2's destination** |
| `VFAD` | 14 | LFO2 `SPH` | 0 | −64 (its minimum) |
| `RATE` | 16 | LFO2 `DEP` | 64 | blank — 64 is far outside `RATE`'s 0–16 range |

**`VEL` reading 112 is the proof.** 112 is LFO1 `SPD`'s default, an arbitrary
number that no other explanation predicts. And `PROB` landing on LFO2 `DEST`
predicts exactly the symptom the owner found by ear: a p-lock that modulates
something, unrelated to probability, because it is **re-aiming LFO2**.

So the moved records are reading and writing **the sound value array at index
`record+0x04`** — they have fallen through to the sound parameter set.

### What that means

The page id is consumed by a **runtime classifier** — something that decides
which parameter set a record belongs to when its value is read or written — and
that classifier is **not** `param_set_tables_build`. An unknown page id falls
back to the sound set rather than failing, which is why the parameters draw,
read plausible-looking values, and quietly write into LFO slots.

Three flashes' worth of conclusion, stated plainly:

1. **The page-id cost model in "§3b revisited" is wrong.** It counted six range
   tests plus a routing constant. There is at least one more consumer, it is
   authoritative over the others, and it has not been found. **Do not trust the
   "seven one-byte edits" figure.**
2. **`param_set_tables_build` is a red herring for this problem.** It is worth
   knowing — it is how enumeration works — but patching it bought nothing.
3. The runtime classifier is the thing to find, and it is findable: it must
   consult the page id and choose between the six `ParameterSet` accessors at
   `0x400dc02a`, `0x400dc0b0`, `0x400dc0ca` and `0x400dc0e4`. Those four are
   reached through vtables, so **whoever picks between them is the target**.

### The damage is runtime-only — an earlier warning here was overstated

This section first said the probe **silently edits sounds** and that any sound
saved under it should be treated as suspect. **That was over-cautious, and the
owner's next observation corrects it.**

> *"As soon as I move any parameter the modulation goes away."*

That is the signature of a write that lands in the **runtime value array and
nowhere else**. The p-lock path (`0x400db092`, `docs/modulation-matrix.md`)
writes the per-track array and marks the parameter in the per-track bitmap;
`0x400daf44` walks that bitmap and **restores each marked parameter from its
base value in `0x8000de60`**, clearing the bit. Any subsequent parameter write
rewrites the array from the sound object. So LFO2's `DEST` is re-aimed *in the
mirror*, not in the preset, and the next touch of anything puts it back.

**So the sound object is not modified and a saved sound does not carry the
damage** — on this evidence. The honest residue: nothing here has been checked
by reading a saved sound back with DNX, which is the instrument that would
settle it, and that check has not been done. Reflashing stock before real work
is still the right habit; treating existing sounds as damaged is not warranted.

### Two different symptoms, two different parameters

Worth stating because they are easy to conflate, and the owner flagged it:
**`VEL` is the one that *reads* 112; `PROB` is the one that *modulates*.** They
are separate predictions of the same model, not two accounts of one event.

- `VEL` has `record+0x04` = **1**, which is LFO1 `SPD` — a parameter with a
  non-zero default, so it *displays* that default: 112.
- `PROB` has `record+0x04` = **12**, which is LFO2 `DEST` — a parameter that
  *aims a modulator*, so writing it **changes what LFO2 modulates**.

A model that only explained one of these would be a coincidence. Explaining a
read and a behaviour, with different indices landing on different LFO fields, is
what makes it a diagnosis.

### What DNX contributes, and a correction to the wording above

The DNX session was asked to read pattern A1 back off the device. Before any
read, its knowledge of the **stored** format already sharpens the question, and
corrects a loose phrase used throughout this section.

**`PROB` is not a p-lockable parameter on stock firmware.** It has no id in the
lock pool at all. DNX's hardware capture of 2026-07-26 locked 61 controls, one
per step, and `PROB` — like `NOTE`, `VEL`, `LEN`, `COND`, `FILL`, `RTRG`,
`VFAD`, Retrig `LEN` and `RATE` — produced **no lock record**. Probability is a
per-trig byte in the **track record**: `+0x200` from the start of each
1,187-byte track, 128 × u8, the percentage stored literally, `0xFF` for none.
(DNX `docs/dn2-pattern-format.md` §2 / §2.3 and `NOT_LOCKABLE` in
`src/project/plockparams.ts`.)

So "p-locking `PROB`" above should be read as *"holding a trig and turning
`PROB`"*. That is what the owner did, and on stock it writes that `+0x200` byte.
It is not a p-lock, and the distinction matters for what follows.

DNX also supplies the lock-pool numbering, which is **not** the sound value
array index this document has been using: lock ids are `4·slot + lfo`, so LFO2's
are `SPD 2, MULT 6, FADE 10, DEST 14, WAVE 18, SPH 22, MODE 26, DEP 30`. LFO2
`DEST` is lock id **14**; the same parameter's index in the runtime sound array
is **12**. Two numbering schemes for one parameter — worth stating explicitly,
because confusing them is exactly the class of error that produced the §11 and
§15 retractions.

### The three outcomes, and what each would mean

DNX will report track 1's `+0x200` bytes at trigs 1 and 5, plus every lock
record on track 1 with its steps and values.

| | Reading | Conclusion |
|---|---|---|
| **1** | `+0x200` holds the percentages the owner set, no new lock record | The `PROB` edit reached the stored format normally. Saved patterns are fine for `PROB`, and the fault is narrower than thought |
| **2** | `+0x200` still `0xFF`, and a lock record appears with an **LFO2 id (14 = `DEST`)** | The misrouted edit **reached stored pattern data**. Patterns saved under either probe build carry stray locks, and this document's "runtime-only" conclusion is **wrong** |
| **3** | `+0x200` still `0xFF`, no lock record | The edit never reached stored data. The runtime-mirror reading stands |

**Outcome 2 would retract the "the damage is runtime-only" section above.** That
section already carries the residue that nothing had been read back with DNX;
this is that read.

One condition on all three, from DNX: the trig must be **saved into the
pattern** for any of it to show, though a dump of the loaded project sends its
working copy, so unsaved edits normally appear.

**A fourth thing to watch for, predicted before the read.** DNX notes that lock
id **32** is the one id it has *never* observed on any page or machine
(`src/project/plockparams.ts`) — and `PROB`'s parameter-table id is also **32**.
If the lock-pool id is the parameter-table id, then 32 being unused is exactly
what `PROB` never entering the lock pool would produce. Two independent facts
agreeing. **So a lock record carrying raw id 32 would also be significant**, and
would say the probe build pushed `PROB` into the lock pool under its own id.

Recorded here *before* the data arrives, so it counts as a prediction rather
than a reading fitted after the fact.

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
   **FOUND 2026-09-16 — see "The runtime classifier, found" below.**

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

> **⚠️ DISPUTED BY THE OWNER, 2026-09-15, and unresolved as this is written.**
> The owner's words: *"prob is plocable"*, and *"not sure where did you assert
> or got that information about not been able to p-lock it"*. Fair challenge —
> **this claim is not ours and was not verified here.** It came from the DNX
> session, and this document accepted it and rewrote its own wording within
> minutes of receiving it. That was too fast. The owner plays the instrument;
> DNX has read the stored bytes; the two may simply be describing different
> levels — settable per trig from the front panel, stored outside the lock pool
> — but that reconciliation is a guess and is **not** established. The pattern
> read now under way should settle it. Until then, treat the paragraph below as
> **DNX's claim about storage**, not as a fact about what the instrument lets
> you do.

**DNX's claim: `PROB` is not a p-lockable parameter on stock firmware.** It has no id in the
lock pool at all. DNX's hardware capture of 2026-07-26 locked 61 controls, one
per step, and `PROB` — like `NOTE`, `VEL`, `LEN`, `COND`, `FILL`, `RTRG`,
`VFAD`, Retrig `LEN` and `RATE` — produced **no lock record**. Probability is a
per-trig byte in the **track record**: `+0x200` from the start of each
1,187-byte track, 128 × u8, the percentage stored literally, `0xFF` for none.
(DNX `docs/dn2-pattern-format.md` §2 / §2.3 and `NOT_LOCKABLE` in
`src/project/plockparams.ts`.)

On that reading, "p-locking `PROB`" above would mean *"holding a trig and
turning `PROB`"*, writing the `+0x200` byte rather than making a lock record.
**That rewording is on hold pending the dispute above** — the original wording
described what the owner actually did at the instrument, and if `PROB` does
carry a lock-pool id then it was right all along and DNX's `NOT_LOCKABLE` list
is what needs the correction.

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

---

## The A1 read settles it: the damage REACHES STORED PATTERN DATA

**2026-09-15.** DNX captured Pattern+Kit 0 from the DN2 while
`page-renumber-test2` was resident — 114,118 bytes, checksums good, no writes,
saved as `DigitoneII_PatternKit_A1_page-renumber-test2_2157.syx`. Outcome **2**
of the three written down in advance.

### The reading

- **`+0x200` is `0xFF` on all 128 trigs of track 1.** No probability is stored
  anywhere on the track. The normal path is dead, as the device's behaviour
  suggested.
- **Eight lock records exist**, all on track 1, all on **trig 5** (trig 1 has
  none), with raw ids `0, 1, 5, 14, 18, 22, 26, 30`.

### Every one of the eight is predicted by the model, and nothing is left over

The model: a moved TRIG record writes the **sound** value array at index
`record+0x04`, and that is then stored under the sound lock id
`4·slot + lfo` (DNX's numbering, where LFO1–3 occupy sound indices 1–24).

| TRIG param | `record+0x04` | → lock id | in the dump | value |
|---|---|---|---|---|
| `NOTE` | 0 | **0** | yes | `0x2f00` |
| `VEL` | 1 | **1** | yes | `0x6e00` |
| `LEN` | 2 | **5** | yes | `0x5400` |
| `PROB` | 12 | **14** | yes | `0x3a00` |
| `RTRG` | 13 | **18** | yes | `0x0100` |
| `VFAD` | 14 | **22** | yes | `0x4a00` |
| Retrig `LEN` | 15 | **26** | yes | `0x3000` |
| `RATE` | 16 | **30** | yes | `0x0e00` |

**Eight observed, eight explained, none unexplained.** And the eight are exactly
the parameters on the first two TRIG pages — the ones the owner was turning.

`PROB` → lock id 14 is LFO2 `DEST`, value `0x3a00` = coarse **58**. LFO2's
destination is being re-pointed to parameter 58 every time trig 5 plays. That is
the "weird modulation unrelated to probability", named and numbered.

### Retractions this forces

**1. "The damage is runtime-only" is WRONG and is withdrawn.** That section
argued from the owner's observation that the modulation clears when any
parameter is moved, and concluded the write never left the mirror. The clearing
is real but means something else: the lock is **stored on trig 5**, re-applied
each time the sequencer reaches it, and overwritten in the mirror whenever a
parameter is written from the sound object. Transient in the mirror, permanent
in the pattern.

**2. "Saved patterns are probably fine" was wrong**, and it was told to the
owner. **Any pattern edited under either probe build can carry stray LFO locks.**
A1 track 1 trig 5 carries eight right now. They are removable — clear the locks
on that trig, or restore the pattern — but they will not remove themselves.

The earlier section had kept the honest residue that *"nothing here has been
checked by reading a saved sound back with DNX, which is the instrument that
would settle it"*. It was the right caveat and it has now cashed out against me.

### The `PROB` dispute, resolved — both sides were right

The owner said `PROB` is p-lockable; DNX reported it has **no lock-pool
record**, `NOT_LOCKABLE` being its code's name for that. DNX has since asked
that the distinction be kept sharp, and it is right twice over — the claim was
never "not p-lockable", and **this A1 read cannot confirm the stock half of it,
because it was taken on a probe build.** With that said, the three statements
below are each true of their own subject:

- **On stock**, probability has no lock-pool id and lives at `+0x200`. Source:
  DNX's **2026-07-26 hardware capture on stock**, *not* this read.
- **At the instrument**, the owner sets it per trig, which is what a player
  means by a lock — the owner is correct about the behaviour.
- **On the probe build**, it produces a genuine lock record — under **LFO2
  `DEST`'s** id, not its own.

Raw id **32** did **not** appear, so DNX's prediction held: `PROB` never enters
the lock pool under its own id, even here.

### A detail that matters to this project specifically

**Lock id `0` appeared.** Under `id = 4·slot + lfo`, id 0 is `4·0 + 0` — one of
the eight ids DNX documents as **never used**, the reserved fourth-LFO column
(`docs/dn2-pattern-format.md`; `4·slot + 0` is the free rank). `NOTE`, whose
`record+0x04` is 0, wrote into it.

So a stray write has landed in **the exact reserved slot a real LFO4 would
use**, and the pattern format accepted it and stored it. That is not a plan and
proves nothing about whether LFO4 would *work* — but it is the first time
anything has been written into that reserve and read back out, and it says the
storage side does not reject it.

### Confirmed on STOCK firmware by eye, seven of eight — and the eighth is the tell

**2026-09-15, after the owner reflashed stock.** With the probe build gone and
factory 1.11 resident, the owner opened A1 and reported which parameters are
being modulated on that trig:

> *"LFO 1 SPD, MULT and LFO2 MODE, DEST and DEP"* … *"sorry LFO2 also got
> modulated WAVE and SPH"*

Against the eight lock records DNX read:

| lock id | what it is | visible on stock? |
|---|---|---|
| 1 | LFO1 `SPD` | **yes** |
| 5 | LFO1 `MULT` | **yes** |
| 14 | LFO2 `DEST` | **yes** |
| 18 | LFO2 `WAVE` | **yes** |
| 22 | LFO2 `SPH` | **yes** |
| 26 | LFO2 `MODE` | **yes** |
| 30 | LFO2 `DEP` | **yes** |
| **0** | **`4·0 + 0` — the reserved fourth-LFO rank** | **no — and there is no UI that could show it** |

**Seven of eight, exactly, with no extras.** This is the strongest form the
confirmation could take: it is on **stock** firmware, by a human looking at the
instrument, with no tooling in the path, and it agrees parameter-for-parameter
with a decode of a dump taken from a *different* firmware.

And **the one the owner cannot see is the one that should be invisible.** Lock
id 0 occupies the `4·slot + 0` rank that DNX documents as never used — the
column a fourth LFO would live in. There is no fourth LFO page, so there is no
control to draw it against.

### What that establishes, and what it does not

**Established:** the pattern format **stores** a lock in the reserved
fourth-LFO rank, and **stock firmware loads that pattern without complaint** —
no refusal, no corruption, no visible upset, and the other seven locks work
normally alongside it. The reserve is not merely unused space in a document; it
survives a real round trip through a real instrument.

**Not established, and the distinction matters:** whether stock firmware *does*
anything with lock id 0. It is stored and loaded; whether the engine applies it
to any parameter is unknown, and the owner seeing no eighth modulation is
consistent with both "it is applied to a parameter that does not exist" and "it
is silently ignored". Reading `0x400db092`'s bound against index 0 would say.

This arrived by accident — as damage from a failed probe — which is worth
stating plainly rather than dressing up as a designed experiment. But it is the
first end-to-end evidence that the fourth rank is live storage, and it cost
nothing beyond a mistake already made.

### Housekeeping the owner still needs

Those eight locks are **real stored data on A1 track 1 trig 5** and stock
firmware is honouring seven of them. They will not clear themselves — clear the
locks on that trig, or restore the pattern.

## The runtime classifier, found — 2026-09-16

The blocker `STATUS.md` has carried since the third probe flash. It is a
**virtual predicate**, not a switch, which is why scanning for a page-id
cascade never found it.

### The four parameter sets are real C++ classes, and RTTI names them

| class | typeinfo | vtable |
|---|---|---|
| `SoundParameterSet` | `0x401db6d8` | `0x401db7fc` |
| `FxParameterSet` | `0x401db6e4` | `0x401db884` |
| `TrigParameterSet` | `0x401db6f0` | `0x401db90c` |
| `MidiParameterSet` | `0x401db6fc` | `0x401db994` |

All four derive from a common base (`0x401db6cc`). `Track` (`0x401deb80`,
constructed at `0x400515d0`) embeds a `TrigParameterSet` at `+52`.

### Slot `+0x54` is the classifier

Every one of the four vtables carries, at **offset `0x54`**, a predicate that
takes a **parameter id**, indexes the parameter table at `0x401f7f94`
(`60 × id`), reads the **page id at `+0x00`**, and answers a page test. The
shape is identical in all of them:

```
0x400dbe8a  movel %sp@(4),%d0          ; parameter id
0x400dbe8e  cmpil #321,%d0             ; bounds against the 321-record table
0x400dbe94  scs %d1
0x400dbe96  lea 0x401f7f94,%a0         ; the parameter table
0x400dbe9e  andl %d1,%d0               ; clamp to 0 if out of range
0x400dbea0  ... %d0 = 60 * id          ; (id<<6) - (id<<2)
0x400dbea8  moveq #4,%d1
0x400dbeaa  cmpl %a0@(0,%d0:l),%d1     ; vs the record's PAGE ID
0x400dbeae  scc %d0                    ; page <= 4
```

| set | predicate | pages it claims |
|---|---|---|
| `SoundParameterSet` | `0x400dbe8a` (via `0x40036bfa`) | `page <= 4` |
| `FxParameterSet` | `0x400dbf4e` | `0x10`–`0x15` |
| `TrigParameterSet` | `0x400dbf82` | `0x1d` **or** `0x16` |
| `MidiParameterSet` | `0x400dbfbc` | `0x16`–`0x1c` |

A fifth of the same shape sits at `0x400dbeb6` — pages `0x05`–`0x0a` — and is
**not yet attributed to a class**.

~~The predicate slot is called from **24 sites** across the image (the accessor
slot `+0x50` from 58).~~ **[WRONG — corrected 2026-09-16, same day.]** That
count came from scanning for *any* virtual call through offset `0x54`, on any
class. Vtable offsets are per-class, and most of those 24 belong to unrelated
types — `0x40031eaa` passes three arguments through slot `0x54`, where the
`ParameterSet` predicate takes one. **The number meant nothing.** The real
callers are counted below, by direct call to the concrete predicates.

### Who actually asks

Direct calls to the concrete predicates, which is the honest count:

| predicate | direct callers |
|---|---|
| `0x400dbe8a` Sound | `0x40036c04` (the vtable body), `0x40064e90` |
| `0x400dbeb6` unattributed | `0x40064f14` |
| `0x400dbf4e` Fx | `0x40036778`, `0x40041a96`, `0x4004484e`, `0x40067656`, `0x4006768a`, `0x40067dd4`, `0x40067f32` |
| `0x400dbf82` Trig | `0x400369d6`, `0x40041a74` |
| `0x400dbfbc` Midi | `0x400369f6` |

### Why the probe failed — read, not inferred

**Page `0x1f` is claimed by no predicate**, and the cascade at `0x40041a72` has
**no default guard**:

```
0x40041a74  jsr 0x400dbf82      ; Trig?  page == 0x1d || 0x16
0x40041a7c  tstl %d0
0x40041a7e  beqs 0x40041a94     ;   no
0x40041a90  braw 0x4003f0b6     ;   YES -> the Trig path
0x40041a96  jsr 0x400dbf4e      ; Fx?    page 0x10-0x15
0x40041aac  tstl %d0
0x40041aae  beqs 0x40041abe     ;   no
0x40041ab8  jmp 0x40030aec      ;   YES -> the Fx path
0x40041ac6  jmp 0x400312fe      ;   FALL THROUGH, unconditional
```

Two tests, then an unconditional jump. An unclaimed page is not rejected, not
logged and not defaulted — it simply takes the last branch. `0x400312fe`
computes byte offsets into the track structure (`+15856`, `+16964`, …), which
is the sound-side addressing.

That is the observed symptom exactly: `VEL` reading 112 (LFO1 `SPD`'s default)
and `PROB` re-aiming LFO2. **This was inferred from the symptom when first
written here; it is now read from the code.**

This also explains why patching `param_set_tables_build` bought nothing. That
function builds the BSS enumeration tables at boot; **this** decides ownership
at every read and write, and it never consults them.

### What it costs, and the honest caveat

These are **one-byte constants of the same kind as the six range tests** —
`moveq #4`, `moveq #5`, `moveq #6`, `moveq #29`. Widening one to cover `0x1f`
is a one-byte edit; the difficulty is that `0x1d` (Retrig) and `0x1e` (None)
sit between `0x1c` and `0x1f`, so a *contiguous* widening of the `0x16`–`0x1c`
range swallows both. `TrigParameterSet`'s predicate shows the alternative in
the shipped code: **an exact-match disjunct** (`page == 0x1d || page == 0x16`).
That is the form LFO4 needs, and it is already proven to compile and run here.

**Not yet established, and do not price the job until it is:**

1. The exact semantics of slot `+0x54`. "Owns this parameter" fits every
   observation, but `SoundParameterSet` claiming only pages `0`–`4` is
   surprising for the set with the most pages, and the unattributed
   `0x400dbeb6` may mean ownership is expressed in more than one place.
2. ~~Whether any of the 24 predicate call sites takes a different branch for an
   unclaimed page.~~ **CLOSED — read at `0x40041a72`: two tests, then an
   unconditional fall-through with no default guard.** Whether the other
   cascades (`0x40064e90`/`0x40064f14`, and the `0x40067xxx` cluster) have the
   same shape is not checked.
3. Whether slot `+0x50` (the accessor) needs the same treatment.

## The complete page map, and the arpeggiator is not in it — 2026-09-16

Dumped from the 321-record table at `0x401f7f94`, every page with its label and
short names. Written down because two questions turned on it the same day and
both were being answered by guesswork.

| page | label | n | parameters |
|---|---|---|---|
| `0x00`–`0x03` | `SYN` | 38/25/30/8 | the four machine pages |
| `0x05`–`0x0a` | `Filter` | 3/2/3/3/3/3 | per filter type |
| `0x0b` | `Amp` | 11 | `DEL ATK HOLD DEC SUS REL BAL PAN VOL MODE RSET` |
| `0x0d` | `Filter` | 11 | the filter envelope |
| `0x0e` | `Portamento` | 2 | `PTIM PORT` |
| `0x0f` | `FX` | 8 | `CHR DEL REV BR SRR SR.RT OVER OD.RT` |
| `0x10`–`0x12` | `Chorus`/`Reverb`/`Delay` | 8/9/10 | |
| `0x13`–`0x14` | `Master` | 2/9 | |
| `0x15` | `Ext-in` | 17 | |
| `0x16` | *(none)* | 4 | `NOTE NOT2 NOT3 NOT4` |
| `0x17` | `Src` | 8 | `CHAN BANK PROG PB AT MW BC SBNK` |
| `0x18` | `CC` | 16 | `VAL1`–`VAL16` |
| `0x19` | *(none)* | 16 | `SEL1`–`SEL16` |
| `0x1a`/`0x1b`/`0x1c` | `LFO1`/`LFO2`/`LFO3` | 10 each | `SPD MULT FADE DEST WAVE SLEW SPH MODE DEP MULT` |
| `0x1d` | *(none)* / `Retrig` / `Euclidean` | 10/4/8 | the TRIG group |
| `0x1e` | *(none)* | 1 | `---` |
| `0xffffffff` | *(none)* | 19 | the dead `ERR` slots |

### There is no arpeggiator page, and no arpeggiator record

**Pages `0x00`–`0x1e` are fully accounted for above and none of them is the
arpeggiator.** A scan of all 321 records for a name containing `Arp` returns
**nothing**.

That answers the owner's standing request to *"enable p-locking for the
arpeggiator settings"* at the level of what the job actually is. Arp state is
**not a parameter** on this instrument: it has no record, so no parameter id, no
`+0x04` slot index, no entry in the forward map `0x401fcf20`, and therefore no
p-lock id. It is not that arp locks are disabled — **there is nothing to lock**.

So p-lockable arp is not a flag to flip. It is the full eight-layer job in
`docs/FEATURE-PLAYBOOK.md` §1, starting at layer 1 with records that do not yet
exist, and it needs the arp state's real home found first. DNX's arp capture
(two presets differing only in `MODE`) is the right next measurement precisely
because it will show **where** that state lives.

### And it bounds the v3 probe's blast radius

DNX asked, before their capture, whether a preset saved under the v3 build could
place a value at a different stored offset than stock. The page map settles half
of it: **no arp record is on page `0x1d`**, so nothing v3 renumbers is an arp
control. The other half is conditional and is answered in
`docs/lfo4-build-plan.md` §5c.

## The arpeggiator block, located — 2026-09-16

Follows from "there is no arpeggiator parameter at all" above. Arp state is not
in the parameter table, so DNX captured it from the instrument instead: five
presets saved on **stock 1.11**, differing only in arp `MODE`. It sits at
**stored offset 331** of the 359-byte sound object, outside the `+28` p-lock
block — exactly where a thing with no p-lock id has to be.

The firmware side then gave the whole block. The v3 sound converter
`0x400dd49a`–`0x400dd5a6` walks fourteen bytes:

| stored | bound | if out of range | read as | live |
|---|---|---|---|---|
| 324 | 3 | 0 | signed | `+326` (long) |
| 325 | 2 | 0 | signed | `+330` (long) |
| 326 | 100 | **100** | unsigned | `+334` (byte) |
| 327 | 2 | 0 | signed | `+335` (long) |
| 328 | 1 | 0 | signed | `+339` (long) |
| 329 | 1 | **1** | signed | `+343` (long) |
| 330 | 1 | 0 | signed | `+347` (long) |
| **331** | **4** | 0 | signed | `+351` (byte) — **`MODE`** |
| 332 | 22 | **13** | unsigned | `+352` (byte) |
| 333 | 7 | 0 | signed | `+353` (byte) |
| 334 | *(negative test)* | **14** | signed | `+354` (byte) |
| 335 | 15 | **15** | unsigned | `+355` (byte) |
| 336–337 | — | — | **word** | `+356` — **per-step enable mask** |
| 338–353 | none | none | raw 16-byte copy | `+358` — **per-step semitone offsets** |

### The last two fields are a pair, and neither is what this project first said

**`336..337` is a 16-bit per-step enable mask.** Not a sentinel — the consumer at
`0x4004bd90` does `1 << step`, `or` to set and `andnot` to clear, into one word:

```
0x4004bd94  lsll  %d2,%d1          ; d1 = 1 << step
0x4004bd98  movew %a0@(356),%d2
0x4004bd9c  orl   %d2,%d1          ; SET
0x4004bdb2  notl  %d1              ; or, on the other arm,
0x4004bdb4  andl  %d2,%d1          ; CLEAR
0x4004bdb6  movew %d1,%a0@(356)
```

**`338..353` is a 16-byte per-step semitone-offset map** — one byte per step,
copied raw with **no bound and no signedness check**, unlike the twelve scalars.
The firmware trusts what is stored, so the range is enforced by the UI on the
way in, not on the way out.

Together they answer "off versus on at zero semitones": both store `0x00` in the
map, and **the bit in the mask is what separates them**.

So the arp region is **324..353**, and the name is at **12..27** (`0x400dd226`,
`pea %a3@(12)` with `pea 0x10`).

### Two things this project got wrong here, both the same mistake

1. ~~`0x400dd5aa` copies 16 bytes from stored 338 — the name — so the block ends
   at 338.~~ **Wrong.** It is the per-step offset map. The boundary claim came
   from assuming a 16-byte copy near the end of an object must be a name.
2. ~~`0xFFFF` at 336..337 is this firmware's "unassigned" sentinel, as in the
   parameter records' CC and NRPN fields.~~ **Wrong.** It is **all sixteen bits
   set — every step enabled**, the sensible default for an arp.

Both were reasoning from a **resemblance** instead of from a **consumer**, which
is `docs/FEATURE-PLAYBOOK.md` §2.3 in a new costume. DNX caught both from the
stored bytes before the code was read.

### And version 0 cannot hold any of it

DNX measured the object terminator `BACEF00C` at **315** in a version-0 object
(content length 319) and at **355** in a version-3 one (359). **A version-0
object ends before offset 331.** The image agrees from the other side: a scan
for any read of `+0x14B` through any address register returns **exactly one
site**, `0x400dd532`, inside the version-3 converter. Nothing else in the image
reads it.

So the arp block is **defined only by object version 3**, and a zero at 331 in a
version-0 object is padding past the terminator — never `MODE`, never `OFF`.

**Consequence for DNX:** their copy path writes version-0 objects onto a device
that saves version 3, so a DNX-copied preset carries **no arp state at all**. It
reads back byte-identical and plays, which is exactly why nobody noticed.

**Confirmed by exhaustion.** A scan of the whole image for any read of each
arp-block offset through any address register returns **one site each**, and all
three are in the same function:

| stored offset | sites | where |
|---|---|---|
| 324 (block start) | 1 | `0x400dd49c` |
| 331 (`MODE`) | 1 | `0x400dd532` |
| 336 (the mask) | 1 | `0x400dd5a0` |

All inside the version-3 converter `0x400dd1ea`. The upgrade chain does carry
version-0 gates (`tstl %aN@(4)` at `0x400e074a`, `0x400e1014`, `0x400e119a`,
`0x400e1322`) and **not one of them touches 324..353**.

### The live/stored delta is not constant — do not translate with `+20`

Worth its own note because it is an easy and wrong shortcut. The stored side is
all bytes; the live side is a **mixed struct** — seven longwords, then bytes — so
the converter expands as it goes:

| stored | live | delta |
|---|---|---|
| 324 | 326 (long) | +2 |
| 325 | 330 (long) | +5 |
| 326 | 334 (**byte**) | +8 |
| 327 | 335 (long) | +8 |
| 328 | 339 (long) | +11 |
| 329 | 343 (long) | +14 |
| 330 | 347 (long) | +17 |
| **331**–335 | 351–355 (bytes) | **+20** |
| 336 | 356 (word) | +20 |
| 338 | 358 (16 bytes) | +20 |

`+20` holds from 331 onward and **is wrong below it**, by up to eighteen bytes.
The arithmetic closes exactly — `326+4=330`, `330+4=334`, `334+1=335`, …,
`347+4=351` — which is a good check that the table is right.

### The substitution value is the default, and it cross-checks the capture

The converter does not clamp to the bound. When a value exceeds it, it
substitutes a **specific** value — 100, 1, 13, 14, 15 — and those are the
parameters' defaults, readable without turning a single knob.

DNX's capture measured non-zero at **326=100, 332=13, 334=14, 335=15** — all four
at exactly their substitution values, i.e. four knobs sitting untouched at
default. Two independent readings agreeing, from opposite ends.

**`MODE`'s bound is 4**, which independently corroborates five values (OFF, TRUE,
UP, DOWN, CYCL) and makes `0` a legal value of the field. It does **not** prove
`0` is labelled OFF; DNX is taking one more save rather than writing that down
as measured.

### What this means for p-lockable arp

The owner's standing request is now scoped. Arp has **no parameter record, no
slot index, no forward-map entry and no p-lock id** — it lives in its own
fourteen-byte region of the stored sound. Making it p-lockable is the full
eight-layer job in `docs/FEATURE-PLAYBOOK.md` §1 starting at layer 1, with the
one saving grace that **the values already persist**: they are stored, they have
known bounds and known defaults, and the converter that reads them is located.

### A correction worth keeping

This project first read the version-3 addition as *"four bytes appended at 248"*.
DNX read the bytes and it is **244**, tagged: `00 01 03 00` prepended in front of
the existing `00 01 02 00`, with `v0[n] === v3[n+4]` for 44 of 44 offsets checked
in 248..291. A nested version-tagged sub-record, not an extended run. The
converter reading 244..251 as eight independent single bytes fits that and does
not distinguish it — the bytes did.

### The one field with no load-time validation, and what is *not* known about it

Flagged by DNX, 2026-09-16, as firmware-side and worth recording against 1.11.

Of the whole arp block, **only the sixteen-byte semitone map at stored 338..353
is copied without inspection**:

```
0x400dd5aa  pea 0x10 ; pea %a3@(338) ; pea %a2@(358) ; jsr 0x40134490
```

The twelve scalars each get a bound and a substitute; the mask is a plain word;
the map gets a raw `memcpy`. So a stored byte outside whatever range the UI
enforces reaches the live object untouched.

**What is not known, and the severity depends entirely on it: the consumer is
unlocated.** Scans for `lea %aN@(358)`, for indexed byte reads against a
pre-adjusted base, and for `d16` reads of `+358` all return **nothing**. The
arp engine reaches the map through a computed pointer that no fixed-displacement
scan can see. (An earlier apparent hit on `+0x166` was `movew %sp@(358)` —
stack-relative and unrelated.)

So the honest statement is: **one field is unvalidated at load, and what an
out-of-range value costs is unmeasured** — it could be a silly note, or it could
be an index into something. Writing it down as a hazard is right; writing it
down as a *vulnerability* would be a guess.

**The instrument that would settle it** is a watch on the live map under the
emulator once the UI ports land (`docs/emulator.md`) — set a byte out of range,
drive the arp, and see what reads it. Not reachable today.

No path to it from outside the UI is known, and DNX will not write the field.

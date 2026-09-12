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

## The audio engine — the true open gate

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

Two things are now established about the engine, narrowing the gate:

- **It is on ColdFire, not the SHARC.** When an LFO modulates a parameter the
  DN2 shows that value moving on the parameter page, and the page is drawn by
  MAIN OS — so the modulated value, and therefore the LFO computation, lives on
  the ColdFire side that the tooling reads. The worst case (a SHARC-only engine
  needing a different disassembler) is ruled out.
- **A hardcoded 3-LFO site is found in the engine path.** The LFO speed handler
  `0x40035f32` carries `if (uVar1 < 3)` beside its `case 0x1e` (offset 30, the
  LFO block). That is one of the per-LFO count sites this document predicted —
  the kind of `< 3` bound a fourth LFO must raise.

The read path is now mapped end to end, which locates the generator by
elimination. Drawing a parameter goes: page renderer `FUN_40016f38` → value
getter `FUN_40064786` → resolver `FUN_400635d0`, and the resolver **reads the
current, already-modulated value out of the track/sound engine state** — an
object reached as `page_view[0x1a]` (the engine), with the value living far
inside it (`+0x4f2e0`, read via a `+0x28` vtable method). So the modulated value
is *stored* in engine state; the LFO computation that *writes* it runs on a
separate real-time tick.

**That write-side tick is the generator, and it is the remaining target.** It
advances each LFO's phase, computes its waveform, scales by depth, and writes the
modulated value into `page_view[0x1a]`'s state. To find it: identify the class of
`page_view[0x1a]` (the per-track sound engine) and read its update method, or
find what writes the `+0x4f2e0` state region. Confirm there its LFO count is a
raisable bound (`< 3` / `moveq #3`) rather than three unrolled instances — and
`0x40035f32`'s `if (uVar1 < 3)` beside `case 0x1e` is a first such site. It is a
ColdFire read throughout, not cross-CPU.

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

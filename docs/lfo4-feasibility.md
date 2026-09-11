# A fourth LFO: what it takes, and an honest verdict

The goal is a 4th LFO on the Digitone II's vacant `[MOD]` page, behaving like
LFO1–3. This is the feasibility assessment after mapping the parameter table
(`docs/parameter-table-consumer.md`), its consumers, and the LFO page-view
class. Every claim here was read from a Gate-F-cleared MAIN OS 1.10E and
cross-checked against the bytes.

## Verdict

**Feasible, and the parameter table no longer needs relocating** — that was the
first read, and a better path was found. The table has **15 unused "ERR" filler
records** (ids 1-5, 7-9, 11-15, 17-18), none referenced by address, reachable
only by id-indexing. A page-view's id list can point to any ids, so LFO4 can
**repurpose 10 of these dead slots in place**: same-length edits to ten 60-byte
records, no relocation, no base repointing, no bound changes. The hardest cost in
the original plan is gone.

What remains is real but smaller: rewrite ten ERR records as LFO4's parameters
(copied from LFO3, relabelled), add a fourth page-view whose id list names those
ten ids, wire the `[MOD]` navigation to it, and confirm the **audio engine** can
run a fourth LFO at all. The last is the true open gate; the rest is patch-shaped.

## The change set, itemised

### 1. The parameter table — repurpose, do not grow

The table is a flat array, `record[id] = 0x401e29d0 + id*60`, ids 1..320. It
ends at 320 with no slack, so it cannot be *grown*. It does not need to be. Its
head carries **15 unused records** whose short name is `ERR` — ids 1-5, 7-9,
11-15, 17-18 — placeholders next to the real head entries (Machine Type id6,
Track Level id10, Global Mix Mode id16). Each is a valid 60-byte record that
just displays `ERR`, and **none is referenced by address** (only by id-index),
so overwriting one changes nothing but what that id resolves to.

LFO4 needs ten parameter records. Take ten of the fifteen ERR slots — say ids
1,2,3,4,5,7,8,9,11,12 — and rewrite each with LFO3's field layout: the same
handler pointers, ranges and flags, a `LFO4` page label, and fresh controller
and NRPN numbers. Ten same-length record edits. The page-view (below) points its
id list at those ten ids; they need not be contiguous.

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
analysis is real and worth keeping — a larger change (more than the fifteen
spare slots, or a different table) would need it, and these facts hold
regardless.

- **No slack after the table.** `record[id] = 0x401e29d0 + id*60` ends at id 320
  (`0x401e750c`); the bytes immediately after are another lookup table. Ten new
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

### 4. A fourth page-view instance and its id list

`LfoPageView` (RTTI `0x402064a3`, typeinfo `0x401ece10`, vtable virtuals from
`0x401ecf7c`) is one class instantiated per LFO page. Its cell→id path
(`0x400634ea`) reads the page's id list indirectly through instance fields at
offsets 124 and 144 — so each LFO page carries (a pointer to) its own list of 8
ids. LFO1's is 75–82-ish, LFO2's 85–…, LFO3's 95–…. A fourth page needs its own
`LfoPageView` instance whose list points at the ten new ids (the ten repurposed ERR ids), plus its
page label. Constructing an object and its descriptor at boot is the main piece
of genuinely new code and data — a cave, or an unused existing structure.

### 5. Wire the fourth `[MOD]` page

The `[MOD]` key cycles LFO1→LFO2→LFO3. A fourth page must be reachable: the
navigation that counts and selects MOD pages has to admit a fourth and
instantiate the new page-view. **Whether a vacant fourth page already exists in
that navigation is not yet established** — it is the first thing to read next,
because if the slot is already there (Elektron having left room) this step
shrinks a lot; if not, it is more new code.

## A staged plan

Each stage is independently flashable and observable, so a failure localises.

1. **Repurpose the table (same-length).** Rewrite ten ERR records as LFO4's
   parameters, copied field-for-field from LFO3 with a `LFO4` label and fresh
   CC/NRPN. The parameters now *exist* at ids 1..12; nothing shows them yet.
   Verify with `dnfw` that the image is valid, and — once flashed — that a DNX
   read of a saved project is unaffected and no existing page changed. This is a
   pure `patch/` job, no caves.
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

What is left is one read: the MAIN OS code that consumes that grid — the per-tick
modulation update that advances each LFO's phase, computes its output, and
applies it to the destination. If it loops `lfo` 0..2, a fourth is a bound
change; if it reads all four slots and ignores the last, less. **This is the
first thing to settle before committing to a build**, because if the engine
cannot be made to run a fourth LFO, the parameters would show but not modulate.
The clean way in is to find where a sound object is read at offset `30 + 2*lfo`
in a loop, or the destination-apply that consumes an LFO's value.

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

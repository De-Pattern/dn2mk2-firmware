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
DNX found the persisted sound object reserves a fourth LFO slot
(`30 + 8*param + 2*lfo`, the fourth unused), so the *storage* has room; the
*engine* that reads it is the unknown. **This is the first thing to settle
before committing to a build**, because if the engine cannot run a fourth LFO,
the feature is cosmetic.

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

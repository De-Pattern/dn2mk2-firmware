# A fourth LFO: what it takes, and an honest verdict

The goal is a 4th LFO on the Digitone II's vacant `[MOD]` page, behaving like
LFO1–3. This is the feasibility assessment after mapping the parameter table
(`docs/parameter-table-consumer.md`), its consumers, and the LFO page-view
class. Every claim here was read from a Gate-F-cleared MAIN OS 1.10E and
cross-checked against the bytes.

## Verdict

**Feasible in principle, but it is a code-cave and relocation project, not a
patch.** It cannot be done as the same-length edits the current `patch/` model
supports. A working build needs: relocating the 320-record parameter table to
free space, repointing ~56 base references, raising ~43 bound immediates,
patching the hardcoded per-LFO id sites, and constructing and wiring a fourth
page-view. That is several stages, each verifiable on its own, and it is
realistically multi-session work. No part of it looks impossible; the cost is
breadth and the need to add code, not any single hard wall.

## The change set, itemised

### 1. Grow the parameter table — the hardest part

The table is a flat array, `record[id] = 0x401e29d0 + id*60`, ids 1..320, and it
ends exactly at id 320. **There is no slack after it** — the bytes immediately
past the last record are another lookup table. So ten new records (ids 321–330,
+600 bytes) cannot be appended in place.

The table must move. It is ~19.3 KB (321 × 60), and **56 sites in code hold an
absolute literal pointing into its base** (53 at `0x401e29a0`, plus a few
neighbours). Relocating it means:

- copy the table into a code cave (free space in the section),
- append the 10 LFO4 records,
- repoint all 56 base literals to the new address,
- raise the bound (below).

Alternatively the table could stay and only a *fourth LFO's* ten records live in
a cave, reached by a special-cased base when `id > 320` — but that means editing
every accessor to branch, which is more sites than relocating the base. Moving
the whole table is the cleaner option.

### 2. Raise the length bound — ~43 sites

The table length is not stored; it is a bounds immediate compiled into every
accessor: `cmpi #321` at 32 sites, `#320` at 11, and one `#311`. Every one that
guards an id in 321..330 must be raised (`321→331`, `320→330`). Miss one and the
parameters it guards clamp to id 0 and vanish. Finding them is mechanical — they
all sit beside a `lea` of the table base — but it must be exhaustive.

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
`LfoPageView` instance whose list points at the ten new ids (321–330), plus its
page label. Constructing an object and its descriptor at boot is new code and
new data — a cave.

### 5. Wire the fourth `[MOD]` page

The `[MOD]` key cycles LFO1→LFO2→LFO3. A fourth page must be reachable: the
navigation that counts and selects MOD pages has to admit a fourth and
instantiate the new page-view. **Whether a vacant fourth page already exists in
that navigation is not yet established** — it is the first thing to read next,
because if the slot is already there (Elektron having left room) this step
shrinks a lot; if not, it is more new code.

## A staged plan

Each stage is independently flashable and observable, so a failure localises.

1. **Bounds sweep, no growth.** Find and list all ~43 bound sites; verify by
   raising them to `#331` with the table unchanged and confirming the instrument
   still boots and behaves (nothing uses ids 321–330 yet, so this is inert — it
   proves the site list is complete and correct).
2. **Relocate the table** to a cave, repoint the 56 bases, no new records.
   Byte-for-byte identical behaviour is the pass condition — the table is just
   somewhere else.
3. **Append the 10 records** (ids 321–330), copied from an LFO block with a new
   page label. They exist but nothing shows them yet; check with `dnfw` that the
   image is valid and DNX that a saved project is unaffected.
4. **Add the fourth page-view** and its id list in a cave, and the SPH-remap id.
5. **Wire the MOD navigation** to the fourth page. This is the stage that makes
   it visible and is the real test.

Stages 1–3 are within reach with the tooling in hand plus a code-cave applier
(`patch/cave.py`, still to be built — the roadmap's Phase-2 mechanism). Stages 4
and 5 need the page-view construction and MOD navigation read first.

## What is not yet known, and is next

- Does the `[MOD]` navigation already allow a fourth page? (Read the MOD-key
  handler and the page-count it uses.)
- Where do the LFO page descriptors (the id lists at instance fields 124/144)
  live, and how are the three instances constructed? (Trace the two `LfoPageView`
  vptr writers, `0x40101306` and `0x401a2aea`.)
- Is there enough contiguous free space in MAIN OS for a ~20 KB table cave plus
  a page-view? (Scan for a run of zero/padding bytes.)

Answering these turns the staged plan into concrete addresses. None of it
changes the verdict: achievable, sizable, and the right first build is Stage 1 —
the bounds sweep — because it is inert, provable, and the foundation for the
rest.

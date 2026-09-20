# How far is a working LFO4?

> **[STATUS, 2026-09-20.]** Recovered from `analysis/lfo-tick`, which never
> reached a PR. Read it as the distance assessment it was on 2026-09-15, not as
> current state. What has changed since: the value home is **decided** --
> `docs/lfo4-build-plan.md` §8 chose an extension table keyed by the sound's
> address, carried by the `memcpy`/`memset` hooks, with the stored side proven
> against 195,256 objects in the DNX corpus -- and **step 0 is built and
> merged** (#91): C compiles for the ColdFire, a `CODE` chunk rides in the
> appended area, and a startup loader puts it at its address. Its Check 1 below
> (no BSS headroom, so the state extends rather than grows) is the reasoning
> §8 still rests on, which is why this file is worth keeping.

**2026-09-15.** With the LFO tick found (`docs/modulation-matrix.md`) every
piece of the job is now either done, a bounded data edit, a counted code edit,
or one genuinely open design choice. This file is the honest distance, stage by
stage, and it supersedes the scattered estimates in `docs/lfo4-slot-plan.md` and
`docs/lfo4-feasibility.md` where they disagree.

## The one thing that is not yet decided

**Where LFO4's eight parameters live.** The tick reads LFO *n*'s fields from the
per-track value array at indices `8n+1 .. 8n+8`. LFO1–3 are 1–24; a fourth LFO
by the same rule wants **25–32 — the first eight machine parameters**, which are
occupied. This is the eight-slot problem, and it is now the critical path.

Two routes, both real, neither built:

- **(a) A per-track extension array.** A cave in the tick's loop points the
  parameter pointer (`a4`) at a 16-track × 8-word block of our own for the fourth
  iteration only, instead of the value array. ~2 KB in the 25 MB above BSS, one
  hook in each of the two ticks. LFO4 is then a **track-level** LFO — not saved
  per preset. This is the cheapest working version.
- **(b) Grow the sound object.** LFO4's parameters become real slots 25–32
  shifted into an extension, saved with the preset. This is the full feature and
  the larger job; `docs/lfo4-slot-plan.md` §3 is the analysis.

**The owner chose route (b), 2026-09-15: saved with the sound.** But route (b)
is *not* done by growing the object — the strides `#2388`, `#202` and `#359` are
each baked into 16–29 functions and cannot be safely edited. Route (b) uses the
**same extension arrays** as route (a) plus two serialization hooks that route
LFO4's values through the stored format's already-reserved 4th LFO slot. See
`docs/lfo4-build-plan.md`. Route (a) remains the first buildable milestone on the
way to it.

## The stages, and where each stands

| Stage | State | Cost |
|---|---|---|
| Storage: reserved 4th LFO slot in the sound format | **Done by Elektron** (DNX) | — |
| Destination masks: 4th rank `0x0200` on all 189 params | **Done by Elektron**, measured both builds | — |
| Forward/inverse p-lock maps: 8 reserved-rank entries | **Located and dumped**, `docs/lfo4-slot-plan.md` | 8 + 8 data entries |
| Parameter records for LFO4's 8 params | **Built** | `scripts/build_lfo4_test.py` |
| Enumeration into the ParameterSet the tick's DEST hits | **Solved, a data edit** | `docs/parameter-set-tables.md` |
| **Page id** for a 4th `[MOD]` page | **Priced, route paused** | see below |
| **The generator (tick)** | **Found and fully read** | `0x40137726` + `0x401373dc` |
| Fourth page-view + `[MOD]` navigation | **Not started** | UI work, unscoped |
| **Where LFO4's 8 values live** | **The open decision** | route (a) or (b) above |
| Cave mechanism | **Proven on hardware** | `CAVE RAN!!!`, `docs/code-caves.md` |

## The tick edit, counted from the code

For the generator to run a fourth LFO, in **both** ticks:

| Site (main tick `0x40137726`) | Change |
|---|---|
| inner loop start `moveq #2` at `0x40137784` | → `#3` |
| per-LFO field base offsets (written for the *last* LFO) | state `a2@(80..117)` +40, params `a4@(68..82)` +16 |
| outer state stride `moveq #120` at `0x40137b02` | → `#160` |
| state array + its boot memset (`0x780` = 1920) | → 2560 B |

The state arrays are the encouraging part. **`0x4463fc18` (live) is referenced by
exactly two functions — its getter `0x40137340` and the tick — and its backup
`0x4463ed18` by the tick alone.** `0x4463f498` (the second tick's) is the same:
its getter and `0x401373dc`. So **growing them from 1,920 to 2,560 bytes touches
three functions total**, not a scattered set, provided the 640-byte extension
does not collide with what follows them in BSS (unchecked — the one measurement
still owed on this stage).

## The second tick, `0x401373dc`

A second per-track LFO evaluator with its own `16×3×40` state at `0x4463f498`,
called from `0x4012aaea`/`0x4012b0aa` inside `0x4012a9a8`. **What it serves is
not identified** — no strings, per-track over 16, distinct from the audio frame.
It matters two ways:

- a **first version can ignore it** (route a, audio-tick only), and LFO4 simply
  will not work in whatever that path renders;
- a **complete** LFO4 has to edit it identically, doubling the tick edit above.

Identifying it is a cheap next step and it removes the last unknown from the
generator side.

## The page-id stage, honestly

Renumbering was flashed twice and **paused** (`docs/lfo4-feasibility.md`, "The
A1 read settles it"): moving a page id needs a runtime classifier that has not
been found, and the cost model was retracted. LFO4 needs a way to *show* its
page. This is unbuilt and is the second-hardest piece after the value home — but
route (a) plus a reused existing page id (option 3, never scoped) may sidestep it
entirely for a first version.

## The distance, stated plainly

- **A running, track-level LFO4 that modulates (route a):** the tick edit above,
  a ~2 KB extension array, one cave per tick, and the enumeration/record work
  that is already done. **No new reverse engineering is required** — every
  address is known. It would not be saved per preset and would have no UI page
  yet; it is a proof that the fourth generator runs. This is **close**: days of
  building and one flash, gated on the BSS-collision check and a decision to
  accept a track-level v1.
- **The real feature the owner wants (route b, saved per sound, its own page):**
  adds the sound-object growth (`lfo4-slot-plan.md` §3), the page-id display
  path (unbuilt), and the UI page-view. Each is scoped but none is built, and the
  page-id path still owes a found classifier. **Further** — the generator is no
  longer the blocker; storage and UI are.

## The next three moves, cheapest first

1. **Check the 640-byte BSS headroom** after `0x4463fc18` and `0x4463f498` —
   static, decides whether the arrays grow in place or the state also relocates.
2. **Identify `0x401373dc`'s consumer** — static, removes the last generator-side
   unknown and tells us whether a v1 can skip it.
3. **Build a route-(a) proof**: the tick edit + extension array + one cave,
   flashed to show a fourth LFO modulating a destination. This is the experiment
   that turns "found the tick" into "the generator runs a fourth."


---

## The two gating checks, run 2026-09-15

### Check 1 — BSS headroom: there is none. The state relocates (or extends).

The three LFO state arrays are **contiguous, wall-to-wall** in BSS:

```
0x4463ed18  main tick BACKUP     1920 B  -> ends 0x4463f498
0x4463f498  second tick state    1920 B  -> ends 0x4463fc18
0x4463fc18  main tick LIVE       1920 B  -> ends 0x4464039c
0x44640398  next structure (timing globals, fn 0x401385cc and the 0x446406xx run)
```

Each is referenced only by its getter and tick (Check confirmed: `0x4463fc18` by
`0x40137340`/`0x40137726`, `0x4463ed18` by the tick, `0x4463f498` by
`0x40137394`/`0x401373dc`), but **there is no gap to grow into** — growing
`0x4463fc18` to 2,560 B would run into `0x44640398`, and the other two are boxed
by each other.

**So in-place growth is out**, and it confirms the extension design end to end:
LFO4's per-track 40-byte state lives in a **separate parallel array** —
`ext_state[16][40]` = 640 B — that the caved fourth iteration uses, exactly as
its parameter values live in `ext_trk`. The three stock arrays stay 1,920 B and
do not move; only the tick's inner loop learns to read the fourth LFO's state
and params from the extension. This is *simpler* than growing them, and it needs
no BSS relocation at all — the 640 B sits in the 25 MB above BSS with the other
extensions.

**Net: the tick edit shrinks.** No `#120`→`#160` stride change, no `0x780`
memset change, no array move. The loop runs three iterations over the stock
arrays as now, then a **fourth iteration** over the extension arrays — an
appended pass, not a widened one.

### Check 2 — the second tick's consumer: still unidentified, but boxed in

`0x401373dc` is called from `0x4012a9a8` (a 3,848-byte function), which is
registered only as a **callback** — its sole reference is `pea 0x4012a9a8` at
`0x4012b888`, no direct call and no strings. It works over 16 tracks on state at
`0x445fe870` / `0x446163c4`, distinct from both the audio frame and the sound
pool.

Not named, but its shape is clear: a **second, non-audio per-track LFO
evaluation** reached through a registered callback. A route-(a)/first LFO4 can
skip it and LFO4 simply will not modulate in whatever that callback renders
(likely a MIDI/CV or metering path — unconfirmed). The complete feature adds the
same appended-fourth-iteration edit to `0x401373dc`, which has its own extension
state.

**Neither check blocks the build.** Check 1 makes the tick edit smaller; check 2
is deferrable to the complete version.

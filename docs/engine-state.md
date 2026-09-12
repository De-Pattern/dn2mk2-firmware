# The engine's runtime state, and the hunt for the modulation tick

`docs/memory-map.md` establishes that the sound engine's mutable state lives in
SDRAM at `0x80000000`, not in the image, and that a fourth LFO ultimately needs
the **write side** — the tick that advances the LFOs and applies them. This is
the record of that hunt on **1.11**: what is pinned, what is not, and what was
got wrong along the way.

## The accessor, decompiled

Reached through a thunk that adds the modulation-state offset to a per-track
object pointer, then jumps:

```
0x4003e426   move.l #0x4f358,%d0 ; add.l %d0,4(%sp) ; jmp 0x4004dfb0
```

```c
/* FUN_4004dfb0 */
int accessor(int base, int index) {
  if (index < 0)    index = 0;
  else if (index > 0x7f) index = 0x7f;
  return base + 0x30 + index * 0x3c0;
}
```

So: **an array of 128 entries, 960 (`0x3c0`) bytes each, at
`track_obj + 0x4f358`, with the field of interest at `+0x30` (48)** inside each
entry. 128 × 960 = 122,880 bytes (`0x1e000`) — a substantial block, consistent
with 1.11 clearing BSS to `0x80010000`.

The same shape appears in the bulk pass `FUN_4004dc62`, which walks **exactly
128 entries** — `d2` steps by 1163 to a limit of 148,864, and 1163 × 128 =
148,864 — advancing a second, parallel array at stride 1163 while stepping the
960-byte array, and calling `FUN_4004afec` on each pair. That callee is object
setup: it stores a pointer, calls vtable slots `+0x3c` and `+0x10`, and builds
six sub-objects at stride `0x98` from 16-byte source records at stride `0x10`.

## What these 128 entries are: **Presets**, named by the UI

The callers settle it. `FUN_40016480`, one of the 24 that reach the thunk, calls
the accessor and then formats the result:

```c
uVar3 = FUN_4003e426(*(param_1 + 0x68), (int)cVar4);   /* thunk -> accessor */
FUN_4004b1f4(uVar3);
FUN_400562e6(*(param_1 + 0x6c), "Preset: %d %s", cVar4 + 1, local_c);
```

The literal at `0x402127c8` is **`"Preset: %d %s"`**, and the index is passed as
`cVar4 + 1` — 0-based internally, displayed 1-based. Its neighbours in the
string pool are all page-view UI: `SourcePageView`, `MultiSourcePageView`,
`Reload Page %s`, `COPY PAGE %.16s`, `PASTE PAGE %s`, `CLEAR PAGE %s`, and the
FM operator labels `RATIO`, `RATIO OFFSET`, `KEY TRACK`.

So the array is **128 Presets of 960 bytes each**, reached from a page-view
object's member at `+0x68` (the engine/project pointer), and the clamp to
`0..0x7f` is the preset index range.

**Correction to an earlier label:** this had been carried forward as a
"per-track object". A 128-entry preset array is project-wide, so the base is the
**engine/project root**, not a per-track object. `docs/memory-map.md`'s
"per-track object" wording predates this and should be read with that caveat.

**Not yet proven: whether "Preset" is DNX's sound pool.** DNX measures three
128-count entities on the DN2 — the pattern array (stride 89,088), the kit array
(10,752) and the **sound pool (128 × 359)**. Patterns and kits are far too large
to be 960 bytes in RAM, so the sound pool is the only plausible match by size
(359 B serialized expanding to 960 B with runtime state). That is a reasonable
inference, **not a measurement**: the UI calls this a Preset, DNX calls that a
Sound, and nothing here has yet shown they are the same array. Confirming it
means matching a known preset's field values against a decoded sound.

**The modulation tick has not been found.** `FUN_4004dc62` is an
initialise-or-apply-to-all pass, not a real-time tick; `FUN_4004dfb0` is pure
address arithmetic. Neither advances an LFO. The write-side code remains open.

## A correction, recorded because it nearly became a patch

An earlier reading of this accessor took its displacement as **+30 decimal** and
matched it against DNX's independently decoded sound object, whose LFO block is
at `offset = 30 + 8*parameter + 2*lfo` with the fourth slot of each group
unused. That looked like a striking convergence of two independent derivations.

**It was wrong.** The displacement is `0x30` = **48**, not 30. objdump prints an
indexed-mode displacement in *hex without a prefix* while printing `d16(An)` in
decimal — see `docs/mainos-image.md`, "objdump prints displacements in two
different radixes". Ghidra printed `0x30` correctly, and assembling both
candidates settled it in seconds.

The retraction matters beyond the number: **the runtime layout has not been
shown to match the serialized sound format.** DNX's reserved fourth LFO slot is
a fact about the *file* format and remains excellent evidence that Elektron left
room; it is not yet evidence about the engine's in-memory structure. The 960-byte
runtime entry and the 359-byte stored sound are, so far, unrelated measurements.

## Method notes that worked

- **Re-anchoring an object offset across builds**: histogram the immediates of
  `adda.l #imm,%aN` / `move.l #imm,%dN` in a plausible range. Every *other*
  offset matching across 1.10E and 1.11 is what makes the one that moved
  trustworthy (`+0x4f2e0` → `+0x4f358`). See `docs/version-anchors.md`.
- **Anchor on instruction sequences, not addresses** — the sequences around
  these constants were byte-identical between builds.
- **When two disassemblers disagree about a number, assemble both candidates.**
